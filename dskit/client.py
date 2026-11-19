"""DeepSeek 对话接口封装（OpenAI 兼容格式 + DeepSeek 扩展）。

只依赖 requests，不依赖 openai SDK —— 三个理由：
1. 打包体积小（PyInstaller 单文件更好控制）；
2. server_tool_calls / annotations / reasoning_content 这些 DeepSeek 扩展字段能原样收发；
3. 流式解析完全可控，方便 GUI 逐字渲染。

接口文档：https://api-docs.deepseek.com
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import requests

from . import errors
from .config import Config
from .errors import DSException
from .usage import Usage

DEFAULT_SYSTEM_PROMPT = (
    "你是 DeepSeek 桌面客户端里的助手。回答要准确、结构清晰，能用短句就别写长段。"
    "涉及事实、数据、时效性内容时如果开启了联网，请优先查证并在句末用 [序号] 标注来源。"
    "不确定的地方直接说明不确定，不要编造。"
)


@dataclass
class Event:
    """流式事件。kind: reasoning / content / tool / citation / usage / done / error"""

    kind: str
    data: Any = None


@dataclass
class ToolCallInfo:
    """模型发起的一次服务端联网动作（搜索 / 打开网页 / 页内查找）。"""

    kind: str = ""
    type: str = ""
    status: str = ""
    queries: list[str] = field(default_factory=list)
    url: str = ""
    title: str = ""
    sources: list[dict] = field(default_factory=list)

    def describe(self) -> str:
        if self.kind in ("search", "deep_search"):
            q = " / ".join(self.queries) if self.queries else "(未命名查询)"
            n = len(self.sources)
            return f"联网搜索：{q}" + (f"（{n} 条结果）" if n else "")
        if self.kind == "read_link":
            return f"读取网页：{self.title or self.url}"
        if self.kind == "open_page":
            return f"打开页面：{self.url}"
        if self.kind == "find_in_page":
            return f"页内查找：{self.url}"
        if self.kind == "image_search":
            return "图片搜索"
        return f"联网动作：{self.type or self.kind}"


class ChatStream:
    """可迭代的流式响应。

    用法::

        stream = client.chat_stream(messages)
        for ev in stream:
            if ev.kind == "content":
                print(ev.data, end="")
        print(stream.usage.summary())

    迭代结束后可直接读取 text / reasoning / citations / usage 等结果字段，
    也可用 assistant_message() 拿到可以塞回历史的 assistant 消息。
    """

    def __init__(self, client: "DeepSeekClient", payload: dict, *, timeout: float | None = None) -> None:
        self.client = client
        self.payload = payload
        self.timeout = timeout
        self.text = ""
        self.reasoning = ""
        self.usage: Usage = Usage()
        self.citations: list[dict] = []
        self.tool_calls: list[ToolCallInfo] = []
        self.server_tool_calls: list[dict] = []   # 原样回传给下轮请求
        self.finish_reason: str = ""
        self.first_token_ms: int | None = None
        self.error: DSException | None = None
        self._raw: list[dict] = []

    # ---------- 迭代 ----------
    def __iter__(self) -> Iterator[Event]:
        cfg = self.client.cfg
        url = self.client.url("/chat/completions")
        started = time.perf_counter()
        try:
            resp = self.client.session.post(
                url,
                json=self.payload,
                headers=self.client.headers(),
                stream=True,
                timeout=(15, self.timeout or cfg.timeout),
                proxies=cfg.proxies(),
            )
        except requests.RequestException as exc:
            raise errors.from_network(exc) from exc

        with resp:
            if resp.status_code != 200:
                raise errors.from_http(resp.status_code, resp.text or "")

            for raw_line in resp.iter_lines(chunk_size=512):
                if not raw_line:
                    continue
                if raw_line.startswith(b":"):       # SSE 注释/心跳
                    continue
                if not raw_line.startswith(b"data:"):
                    continue
                data = raw_line[5:].strip()
                if data in (b"[DONE]", b'"DONE"'):
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue

                # 生成中途失败：最后一帧会带 error 且没有 choices
                if isinstance(obj, dict) and obj.get("error") and not obj.get("choices"):
                    exc = errors.from_payload(obj)
                    self.error = exc
                    yield Event("error", exc)
                    return

                if isinstance(obj, dict) and obj.get("usage"):
                    self.usage = Usage.from_api(obj["usage"])

                for choice in obj.get("choices") or []:
                    delta = choice.get("delta") or {}
                    think = delta.get("reasoning_content")
                    if think:
                        self.reasoning += think
                        yield Event("reasoning", think)
                    content = delta.get("content")
                    if content:
                        if self.first_token_ms is None:
                            self.first_token_ms = int((time.perf_counter() - started) * 1000)
                        self.text += content
                        yield Event("content", content)
                    if delta.get("server_tool_calls"):
                        for info in self._absorb_tool_calls(delta["server_tool_calls"]):
                            yield Event("tool", info)
                    if delta.get("annotations"):
                        for cite in self._absorb_citations(delta["annotations"]):
                            yield Event("citation", cite)
                    if choice.get("finish_reason"):
                        self.finish_reason = choice["finish_reason"]

                if obj.get("usage"):
                    yield Event("usage", self.usage)

        if not self.text and self.finish_reason == "content_filter":
            self.error = DSException(
                "内容被安全策略拦截，未返回正文",
                code="content_filter",
                hint="换一种表述，或关闭联网后重试",
            )
            yield Event("error", self.error)
            return

        yield Event("done", self.finish_reason)

    # ---------- 增量字段累积 ----------
    def _absorb_tool_calls(self, steps: list[dict]) -> list[ToolCallInfo]:
        """server_tool_calls 按 step 下发，每步可能多次增量；这里做去重合并。"""
        fresh: list[ToolCallInfo] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            calls = step.get("calls") or []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                cid = call.get("id") or f"idx{len(self.server_tool_calls)}"
                exists = next(
                    (c for c in self.server_tool_calls if c.get("calls") and c["calls"][0].get("id") == cid),
                    None,
                )
                if exists is not None:
                    continue
                self.server_tool_calls.append({"index": step.get("index", 0), "calls": [call]})
                action = call.get("action") or {}
                page = call.get("page") or {}
                info = ToolCallInfo(
                    kind=str(call.get("kind") or action.get("type") or ""),
                    type=str(call.get("type") or ""),
                    status=str(call.get("status") or ""),
                    queries=list(action.get("queries") or []),
                    url=str(action.get("url") or page.get("url") or ""),
                    title=str(page.get("title") or ""),
                    sources=list(call.get("sources") or []),
                )
                self.tool_calls.append(info)
                fresh.append(info)
        return fresh

    def _absorb_citations(self, annos: list[dict]) -> list[dict]:
        fresh: list[dict] = []
        for anno in annos:
            if not isinstance(anno, dict):
                continue
            body = anno.get("url_citation") or anno
            url = str(body.get("url") or "")
            key = (url, body.get("start_index"))
            if any((c.get("url"), c.get("start_index")) == key for c in self.citations):
                continue
            cite = {
                "type": anno.get("type") or "url_citation",
                "url": url,
                "title": str(body.get("title") or ""),
                "start_index": body.get("start_index"),
                "end_index": body.get("end_index"),
            }
            self.citations.append(cite)
            fresh.append(cite)
        return fresh

    # ---------- 结果 ----------
    def assistant_message(self) -> dict:
        """可原样塞回 messages 的 assistant 消息。

        注意：请求里带 tools 时，DeepSeek 要求把 reasoning_content 与
        server_tool_calls 一并回传，否则会 400 或丢失已读网页。
        """
        msg: dict[str, Any] = {"role": "assistant", "content": self.text}
        if self.reasoning:
            msg["reasoning_content"] = self.reasoning
        if self.server_tool_calls:
            msg["server_tool_calls"] = self.server_tool_calls
        if self.citations:
            msg["annotations"] = self.citations
        return msg


class DeepSeekClient:
    """对话、联网、网页抓取、文件解析的统一入口。"""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config.load()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "DeepSeekDesktop/0.1"})

    # ---------- 基础设施 ----------
    def url(self, path: str) -> str:
        return f"{self.cfg.base_url.rstrip('/')}{path}"

    def headers(self) -> dict[str, str]:
        if not self.cfg.has_key:
            raise errors.missing_key()
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        retries: int = 2,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict:
        """通用 JSON 请求，带 429/5xx 指数退避重试。"""
        last_exc: DSException | None = None
        call_headers = kwargs.pop("headers", None) or self.headers()
        for attempt in range(retries + 1):
            retry_after: float | None = None
            try:
                resp = self.session.request(
                    method,
                    self.url(path),
                    json=json_body,
                    headers=call_headers,
                    timeout=timeout or self.cfg.timeout,
                    proxies=self.cfg.proxies(),
                    **kwargs,
                )
            except requests.RequestException as exc:
                err = errors.from_network(exc)
                if not err.retryable or attempt >= retries:
                    raise err from exc
                last_exc = err
            else:
                if resp.status_code < 400:
                    if not resp.content:
                        return {}
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise DSException(
                            "响应不是合法 JSON",
                            code="bad_json",
                            detail=resp.text[:400],
                        ) from exc
                err = errors.from_http(resp.status_code, resp.text or "")
                if not err.retryable or attempt >= retries:
                    raise err
                last_exc = err
                try:
                    retry_after = float(resp.headers.get("Retry-After", "") or "")
                except (TypeError, ValueError):
                    retry_after = None

            time.sleep(min(8.0, retry_after if retry_after else 0.8 * (2**attempt)))

        raise last_exc or DSException("请求失败", code="request_error")

    def post_binary(
        self,
        path: str,
        *,
        json_body: dict,
        retries: int = 1,
        timeout: tuple[float, float] | None = None,
        on_progress=None,
    ) -> tuple[bytes, str]:
        """POST 并取回二进制响应（TTS 这类直接返回音频流的接口）。

        服务端是边合成边下发，所以用 stream=True 累积，on_progress(已收字节, 总字节)。
        返回 (数据, Content-Type)。
        """
        last_exc: DSException | None = None
        for attempt in range(retries + 1):
            retry_after: float | None = None
            try:
                resp = self.session.post(
                    self.url(path),
                    json=json_body,
                    headers={**self.headers(), "Accept": "*/*"},
                    stream=True,
                    timeout=timeout or (15, self.cfg.timeout),
                    proxies=self.cfg.proxies(),
                )
            except requests.RequestException as exc:
                err = errors.from_network(exc)
                if not err.retryable or attempt >= retries:
                    raise err from exc
                last_exc = err
            else:
                with resp:
                    if resp.status_code >= 400:
                        err = errors.from_http(resp.status_code, resp.text or "")
                        if not err.retryable or attempt >= retries:
                            raise err
                        last_exc = err
                        try:
                            retry_after = float(resp.headers.get("Retry-After", "") or "")
                        except (TypeError, ValueError):
                            retry_after = None
                    else:
                        total = 0
                        try:
                            total = int(resp.headers.get("Content-Length") or 0)
                        except (TypeError, ValueError):
                            total = 0
                        buf = bytearray()
                        for piece in resp.iter_content(16384):
                            if not piece:
                                continue
                            buf.extend(piece)
                            if on_progress:
                                on_progress(len(buf), total)
                        return bytes(buf), resp.headers.get("Content-Type", "")

            time.sleep(min(8.0, retry_after if retry_after else 0.8 * (2**attempt)))

        raise last_exc or DSException("请求失败", code="request_error")

    # ---------- 对话 ----------
    def build_payload(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        web_search: bool | None = None,
        read_url: bool | None = None,
        max_tokens: int | None = None,
        stream: bool = True,
        temperature: float | None = None,
    ) -> dict:
        cfg = self.cfg
        think = cfg.thinking if thinking is None else thinking
        search = cfg.web_search if web_search is None else web_search
        read = cfg.read_url if read_url is None else read_url

        payload: dict[str, Any] = {
            "model": model or cfg.model,
            "messages": messages,
            "stream": stream,
            # thinking 显式下发，避免不同版本默认值变化
            "thinking": {"type": "enabled" if think else "disabled"},
        }
        if think:
            payload["reasoning_effort"] = reasoning_effort or cfg.reasoning_effort
        if stream:
            payload["stream_options"] = {"include_usage": True}
        limit = cfg.max_tokens if max_tokens is None else max_tokens
        if limit and limit > 0:
            payload["max_tokens"] = max(1, min(int(limit), 393216))
        # 思考模式下 temperature 不生效，干脆不传（界面上也会置灰）
        temp = cfg.temperature if temperature is None else temperature
        if temp is not None and not think:
            payload["temperature"] = max(0.0, min(2.0, float(temp)))

        # top_p：flash 思考模式下服务端把下限压到 0.95，这里提前钳住，免得静默改参数
        top_p = cfg.top_p
        if top_p is not None:
            top_p = max(0.01, min(1.0, float(top_p)))
            if think and str(payload.get("model", "")).startswith("deepseek-flash"):
                top_p = max(0.95, top_p)
            payload["top_p"] = top_p

        stop = [w for w in (cfg.stop_words or []) if str(w).strip()]
        if stop:
            payload["stop"] = stop[:16]

        tools: list[dict] = []
        if search:
            tools.append({"type": "deepseek_web_search"})
        if read:
            tools.append({"type": "deepseek_read_url"})
        if tools:
            payload["tools"] = tools
        return payload

    def chat_stream(
        self,
        messages: list[dict],
        *,
        timeout: float | None = None,
        **options: Any,
    ) -> ChatStream:
        payload = self.build_payload(messages, stream=True, **options)
        return ChatStream(self, payload, timeout=timeout)

    def chat(self, messages: list[dict], **options: Any) -> ChatStream:
        """非流式对话，返回一个已完成的 ChatStream（字段一致便于复用）。"""
        payload = self.build_payload(messages, stream=False, **options)
        data = self.request("POST", "/chat/completions", json_body=payload)
        stream = ChatStream(self, payload)
        message = (data.get("choices") or [{}])[0].get("message") or {}
        stream.text = message.get("content") or ""
        stream.reasoning = message.get("reasoning_content") or ""
        stream.finish_reason = (data.get("choices") or [{}])[0].get("finish_reason") or ""
        stream.server_tool_calls = message.get("server_tool_calls") or []
        stream.citations = (message.get("annotations") or [])
        if stream.server_tool_calls:
            stream._absorb_tool_calls(stream.server_tool_calls)
        if data.get("usage"):
            stream.usage = Usage.from_api(data["usage"])
        return stream

    # ---------- 账户 ----------
    def models(self) -> list[str]:
        data = self.request("GET", "/models", retries=1)
        return [item.get("id", "") for item in (data.get("data") or []) if item.get("id")]

    def balance(self) -> dict:
        """账户余额。返回 {available, currency, total} 之类的结构化信息。"""
        data = self.request("GET", "/user/balance", retries=1)
        infos = data.get("balance_infos") or []
        if infos:
            first = infos[0]
            return {
                "available": bool(data.get("is_available")),
                "currency": first.get("currency", "CNY"),
                "total": float(first.get("total_balance") or 0),
                "granted": float(first.get("granted_balance") or 0),
                "topped_up": float(first.get("topped_up_balance") or 0),
            }
        return {"available": bool(data.get("is_available")), "currency": "CNY", "total": 0.0, "granted": 0.0, "topped_up": 0.0}

    def close(self) -> None:
        self.session.close()
