#!/usr/bin/env python
"""离线自测：不需要 API Key，不需要联网。

本机起一个假服务器模拟 DeepSeek 的 SSE / Search / Fetch / Files 接口，
验证封装层的解析、重试、异常映射、计费、会话存储是否正确。

    python selftest.py            # 跑全部用例
    python selftest.py -v         # 打印每个用例细节

真实接口联调请用：python cli.py verify
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dskit import docs  # noqa: E402
from dskit.client import DeepSeekClient  # noqa: E402
from dskit.config import Config  # noqa: E402
from dskit.errors import DSException  # noqa: E402
from dskit.search import extract_urls, fetch_url, search  # noqa: E402
from dskit.session import Session, SessionStore  # noqa: E402
from dskit.usage import Usage, is_peak  # noqa: E402

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv
STATE: dict[str, object] = {"attempts": 0, "last_body": None, "last_raw": b""}


# --------------------------------------------------------------------------- 假服务器
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # 静音
        pass

    # ---- 工具 ----
    def _read_raw(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        STATE["last_raw"] = raw
        return raw

    def _body(self) -> dict:
        try:
            return json.loads(self._read_raw() or b"{}")
        except ValueError:
            return {}

    def _json(self, code: int, obj: dict) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _sse_head(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _sse(self, obj: dict | str) -> None:
        data = obj if isinstance(obj, str) else "data: " + json.dumps(obj, ensure_ascii=False)
        chunk = (data + "\n\n").encode("utf-8")
        self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
        self.wfile.flush()

    def _sse_end(self) -> None:
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    # ---- 路由 ----
    def do_GET(self) -> None:
        if self.path.startswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]})
        if self.path.startswith("/user/balance"):
            return self._json(
                200,
                {
                    "is_available": True,
                    "balance_infos": [
                        {"currency": "CNY", "total_balance": "12.34", "granted_balance": "2.00", "topped_up_balance": "10.34"}
                    ],
                },
            )
        self._json(404, {"error": {"message": "not found"}})

    def do_DELETE(self) -> None:
        self._json(200, {"id": "file-api-test", "object": "file", "deleted": True})

    def do_POST(self) -> None:
        if self.path.startswith("/chat/completions"):
            return self.chat()
        if self.path.startswith("/v1/tools/search"):
            body = self._body()
            STATE["last_body"] = body
            if (STATE.get("mode") or "normal") == "ratelimit":
                STATE["attempts"] = int(STATE.get("attempts") or 0) + 1
                if int(STATE["attempts"]) <= 2:
                    payload = b'{"error":{"message":"rate limited"}}'
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Retry-After", "0")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
            return self._json(
                200,
                {
                    "results": [
                        {
                            "rerank_score": 2.4,
                            "title": "DeepSeek V4.1-Flash 发布",
                            "url": "https://example.com/a",
                            "snippet": "官方发布 V4.1-Flash，API 名 deepseek-flash。",
                            "summary": "长摘要",
                            "content": "",
                            "site_name": "Example News",
                            "date": "2026-09-10T00:00:00+00:00",
                            "authority": 3,
                        },
                        {
                            "title": "第二条结果",
                            "url": "https://example.com/b",
                            "snippet": "snippet b",
                            "summary": "summary b",
                        },
                    ]
                },
            )
        if self.path.startswith("/v1/tools/fetch"):
            body = self._body()
            if "broken" in (body.get("url") or ""):
                return self._json(404, {"error": {"message": "fetch could not retrieve usable page content"}})
            return self._json(200, {"title": "Example Domain", "content": "# Example\n\nHello world. " * 40})
        if self.path.startswith("/v1/tools/asr"):
            self._read_raw()
            return self._json(200, {"request_id": "r1", "text": "你好，帮我总结一下这个页面", "duration_ms": 1200})
        if self.path.startswith("/v1/tools/tts"):
            body = self._body()
            STATE["last_body"] = body
            if (STATE.get("mode") or "") == "tts400":
                return self._json(400, {"error": {"message": "Content Exists Risk", "code": "content_filter"}})
            data = _make_wav(2.4, rate=24000, freq=220.0)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/files"):
            self._read_raw()
            return self._json(
                200,
                {
                    "id": "file-api-abc123",
                    "object": "file",
                    "bytes": 1234,
                    "created_at": 1762790000,
                    "filename": "document.pdf",
                    "purpose": "text_recognition",
                },
            )
        self._json(404, {"error": {"message": "not found"}})

    # ---- 对话（含三种情形：正常流、限流、鉴权失败、中途报错） ----
    def chat(self) -> None:
        body = self._body()
        STATE["last_body"] = body
        auth = self.headers.get("Authorization", "")
        if "invalid" in auth:
            return self._json(401, {"error": {"message": "Authentication Fails", "type": "authentication_error"}})

        mode = (STATE.get("mode") or "normal")
        if mode == "ratelimit":
            STATE["attempts"] = int(STATE.get("attempts") or 0) + 1
            if int(STATE["attempts"]) <= 2:
                self.send_response(429)
                payload = b'{"error":{"message":"rate limited"}}'
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "0")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

        self._sse_head()
        if body.get("thinking", {}).get("type") == "enabled":
            for piece in ["用户", "在问", "9.11 与 9.8"]:
                self._sse({"choices": [{"index": 0, "delta": {"reasoning_content": piece}}]})

        # 联网工具调用增量（含重复片段，验证去重）
        if body.get("tools"):
            call = {
                "index": 0,
                "calls": [
                    {
                        "index": 0,
                        "id": "srvtoolu_s_01",
                        "type": "deepseek_web_search",
                        "kind": "search",
                        "action": {"type": "search", "queries": ["DeepSeek 最新模型"]},
                        "status": "completed",
                        "sources": [{"type": "url", "url": "https://example.com/a", "title": "A"}],
                    }
                ],
            }
            self._sse({"choices": [{"index": 0, "delta": {"server_tool_calls": [call]}}]})
            self._sse({"choices": [{"index": 0, "delta": {"server_tool_calls": [call]}}]})

        if mode == "midstream":
            self._sse({"choices": [{"index": 0, "delta": {"content": "部分内容"}}]})
            self._sse({"error": {"message": "upstream interrupted", "code": "server_error"}})
            self._sse_end()
            return

        for piece in ["9.11 ", "更大", "。"]:
            self._sse(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": piece,
                                "annotations": [
                                    {"type": "url_citation", "url_citation": {"url": "https://example.com/a", "title": "A", "start_index": 0, "end_index": 4}}
                                ]
                                if piece == "9.11 "
                                else None,
                            },
                        }
                    ]
                }
            )
            time.sleep(0.01)

        self._sse(
            {
                "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "prompt_cache_hit_tokens": 1000,
                    "prompt_cache_miss_tokens": 200,
                    "completion_tokens_details": {"reasoning_tokens": 120},
                    "server_tool_use": {"tool_search": 1},
                },
            }
        )
        self._sse("[DONE]")
        self._sse_end()


class QuietServer(ThreadingHTTPServer):
    """连接被客户端提前关闭时不打印无用堆栈。"""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: D102
        pass


def start_server() -> tuple[QuietServer, str]:
    server = QuietServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


# --------------------------------------------------------------------------- 用例
CASES: list[tuple[str, callable]] = []


def case(name: str):
    def wrap(fn):
        CASES.append((name, fn))
        return fn

    return wrap


def make_client(base_url: str, *, key: str = "sk-test-123456") -> DeepSeekClient:
    cfg = Config(api_key=key, base_url=base_url, thinking=True, web_search=True, read_url=True)
    cfg.normalize()
    client = DeepSeekClient(cfg)
    client.session.trust_env = False   # 忽略系统代理，避免本机请求被劫持
    return client


@case("流式解析：reasoning / content / usage / 引用去重")
def t_stream(base: str) -> str:
    client = make_client(base)
    stream = client.chat_stream([{"role": "user", "content": "9.11 和 9.8 哪个大"}])
    events = list(stream)
    assert stream.reasoning == "用户在问9.11 与 9.8", stream.reasoning
    assert stream.text == "9.11 更大。", stream.text
    assert stream.usage.prompt_tokens == 1200 and stream.usage.completion_tokens == 300
    assert stream.usage.cache_hit_tokens == 1000 and stream.usage.cache_miss_tokens == 200
    assert stream.usage.reasoning_tokens == 120
    assert stream.usage.tool_search == 1
    assert len(stream.citations) == 1, stream.citations
    assert stream.finish_reason == "stop"
    kinds = [e.kind for e in events]
    assert "reasoning" in kinds and "content" in kinds and "done" in kinds
    return f"{len(events)} 个事件, 正文 {len(stream.text)} 字"


@case("工具调用去重 + assistant_message 可回传")
def t_tool_calls(base: str) -> str:
    client = make_client(base)
    stream = client.chat_stream([{"role": "user", "content": "最新模型"}])
    list(stream)
    assert len(stream.server_tool_calls) == 1, stream.server_tool_calls
    assert len(stream.tool_calls) == 1
    info = stream.tool_calls[0]
    assert info.kind == "search" and info.queries == ["DeepSeek 最新模型"]
    assert "联网搜索" in info.describe()
    msg = stream.assistant_message()
    assert msg["role"] == "assistant" and msg["server_tool_calls"] and msg["reasoning_content"]
    return f"工具 {info.describe()}"


@case("请求体：thinking / tools / stream_options 组合正确")
def t_payload(base: str) -> str:
    client = make_client(base)
    list(client.chat_stream([{"role": "user", "content": "hi"}], thinking=False, web_search=True))
    body = STATE["last_body"]
    assert body["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in body
    assert [t["type"] for t in body["tools"]] == ["deepseek_web_search", "deepseek_read_url"]
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}

    list(client.chat_stream([{"role": "user", "content": "hi"}], thinking=True, reasoning_effort="max", web_search=False, read_url=False))
    body = STATE["last_body"]
    assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "max"
    assert "tools" not in body
    return "两种模式请求体均正确"


@case("重试：429 两次后成功（指数退避）")
def t_retry(base: str) -> str:
    STATE["mode"] = "ratelimit"
    STATE["attempts"] = 0
    try:
        client = make_client(base)
        data = client.request("POST", "/v1/tools/search", json_body={"query": "x"}, retries=3)
        assert data.get("results")
        assert int(STATE["attempts"]) == 3, STATE["attempts"]
        return f"第 {STATE['attempts']} 次成功"
    finally:
        STATE["mode"] = "normal"


@case("异常：401 映射为中文提示")
def t_401(base: str) -> str:
    client = make_client(base, key="sk-invalid")
    try:
        list(client.chat_stream([{"role": "user", "content": "hi"}]))
    except DSException as exc:
        assert exc.status == 401, exc.status
        assert "API Key" in exc.message
        assert not exc.retryable
        return str(exc)
    raise AssertionError("没有抛出异常")


@case("异常：流式中途失败被捕获且保留部分内容")
def t_midstream(base: str) -> str:
    STATE["mode"] = "midstream"
    try:
        client = make_client(base)
        stream = client.chat_stream([{"role": "user", "content": "hi"}])
        err = None
        for ev in stream:
            if ev.kind == "error":
                err = ev.data
        assert err is not None, "没有 error 事件"
        assert stream.text == "部分内容", stream.text
        assert "生成中断" in err.message
        return err.message
    finally:
        STATE["mode"] = "normal"


@case("Search API：字段映射与查询参数")
def t_search(base: str) -> str:
    client = make_client(base)
    results = search(client, "DeepSeek V4.1", count=5)
    assert len(results) == 2
    first = results[0]
    assert first.title.startswith("DeepSeek") and first.url.endswith("/a")
    assert first.site_name == "Example News" and first.authority == 3
    assert STATE["last_body"]["count"] == 5
    assert results[1].authority == -1
    return f"{len(results)} 条, 首条 {first.title}"


@case("Fetch API：正文返回、截断与 404 提示")
def t_fetch(base: str) -> str:
    client = make_client(base)
    page = fetch_url(client, "https://example.com/a")
    assert page.title == "Example Domain" and page.chars > 100
    small = fetch_url(client, "https://example.com/a", max_chars=50)
    assert small.truncated and "已截断" in small.content
    try:
        fetch_url(client, "https://broken.test/x")
    except DSException as exc:
        assert exc.status == 404 and "不存在" in exc.message
        return f"{page.chars} 字；404 正确映射"
    raise AssertionError("404 未抛异常")


@case("Files API：multipart 中 purpose 必须先于 file")
def t_upload(base: str) -> str:
    tmp = Path(tempfile_dir()) / "dskit_selftest.pdf"
    docs.make_minimal_pdf(tmp)
    assert tmp.read_bytes().startswith(b"%PDF-1.4")
    client = make_client(base)
    ref = docs.upload_document(client, tmp)
    raw: bytes = STATE["last_raw"]  # type: ignore[assignment]
    i_purpose = raw.find(b'name="purpose"')
    i_file = raw.find(b'name="file"')
    assert i_purpose != -1 and i_file != -1 and i_purpose < i_file, (i_purpose, i_file)
    assert b"text_recognition" in raw
    assert ref.file_id == "file-api-abc123" and ref.purpose == "text_recognition"
    assert ref.block() == {"type": "file", "file_id": "file-api-abc123"}
    tmp.unlink(missing_ok=True)
    return f"{ref.file_id}, 表单顺序正确"


def _make_wav(seconds: float = 0.6, rate: int = 16000, freq: float = 440.0) -> bytes:
    import io
    import math
    import struct
    import wave

    frames = int(rate * seconds)
    pcm = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(frames))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@case("ASR：multipart 上传、结果解析、按时长计费")
def t_asr(base: str) -> str:
    from dskit import asr

    wav = _make_wav(0.6)
    client = make_client(base)
    result = asr.transcribe(client, wav)
    raw: bytes = STATE["last_raw"]  # type: ignore[assignment]
    assert b'name="file"' in raw and b"audio/wav" in raw, raw[:120]
    assert result.text.startswith("你好") and result.duration_ms == 1200
    # 1.2 秒 * $0.116/3600
    assert abs(result.cost() - 1.2 / 3600 * 0.116) < 1e-12
    assert "¥" in result.format_cost()
    return f"{result.text[:8]}… · {result.seconds:.1f}s · {result.format_cost()}"


@case("ASR：超大文件本地拦截，不发请求")
def t_asr_guard(base: str) -> str:
    from dskit import asr

    client = make_client(base)
    try:
        asr.transcribe(client, b"0" * (9 * 1024 * 1024))
    except DSException as exc:
        assert exc.code == "audio_too_large"
        return exc.message
    raise AssertionError("没有拦截超大音频")


@case("音频工具：WAV 头解析、峰值电平")
def t_audio_helpers(base: str) -> str:
    from dskit import audio

    wav = _make_wav(0.5, rate=16000)
    info = audio.wav_info(wav)
    assert info["rate"] == 16000 and info["channels"] == 1 and info["width"] == 2
    assert abs(info["seconds"] - 0.5) < 0.05
    peak = audio.peak_level(wav)
    assert 11000 < peak < 13000, peak
    assert audio.peak_level(b"") == 0
    return f"{info['frames']} 帧, 峰值 {peak}"


@case("TTS：二进制音频、请求字段、按字符计费")
def t_tts(base: str) -> str:
    from dskit import tts

    client = make_client(base)
    result = tts.synthesize(client, "你好，这是朗读测试。")
    body = STATE["last_body"]  # type: ignore[assignment]
    assert body["voice_id"] == "stella" and body["format"] == "wav", body
    assert body["filter_markdown"] is True
    assert result.audio[:4] == b"RIFF" and len(result.audio) > 1000
    assert abs(result.seconds - 2.4) < 0.05, result.seconds
    assert result.billed == tts.billed_chars(result.text) == 20, result.billed
    assert abs(result.cost() - 20 / 10000 * 0.45) < 1e-12
    assert "¥" in result.format_cost()
    return f"{result.seconds:.1f}s 音频 · {result.billed} 字符 · {result.format_cost()}"


@case("TTS：文本清洗（代码块/表格/引用编号）与长文分段")
def t_tts_text(base: str) -> str:
    from dskit import tts

    md = (
        "## 标题\n\n正文一[1]。\n\n"
        "```python\nprint('x')\n```\n\n"
        "| 项目 | 价格 |\n| --- | --- |\n| TTS | 0.45 |\n\n"
        "参考：[官方文档](https://api-docs.deepseek.com)\n"
    )
    clean = tts.prepare_text(md)
    assert "print" not in clean and "|" not in clean and "[1]" not in clean, clean
    assert "标题" in clean and "正文一" in clean and "官方文档" in clean, clean

    long_text = "这是一个测试句子。" * 400
    chunks = tts.split_chunks(long_text)
    assert len(chunks) > 1
    assert all(tts.billed_chars(c) <= tts.CHUNK_BILLED for c in chunks)
    assert "".join(chunks) == long_text.replace("\n", "")
    return f"清洗后 {len(clean)} 字；长文切成 {len(chunks)} 段"


@case("TTS：400 内容审核错误被映射为可读提示")
def t_tts_error(base: str) -> str:
    from dskit import tts

    STATE["mode"] = "tts400"
    try:
        client = make_client(base)
        try:
            tts.synthesize(client, "随便说点什么")
        except DSException as exc:
            assert exc.status == 400
            return tts.describe_error(exc)
        raise AssertionError("400 没有抛出异常")
    finally:
        STATE["mode"] = "normal"


@case("播放器：修复流式 WAV 头（data 长度 0xFFFFFFFF）")
def t_repair_wav(base: str) -> str:
    import struct

    from dskit import player

    rate = 24000
    n = 8000
    pcm = b"\x00\x00" * n
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    bad = (
        b"RIFF"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + fmt
        + b"data"
        + struct.pack("<I", 0xFFFFFFFF)
        + pcm
    )
    fixed = player.repair_wav(bad)
    assert fixed[:4] == b"RIFF" and fixed[4:8] != struct.pack("<I", 0xFFFFFFFF)
    assert player.is_wav(fixed)
    assert abs(player.wav_seconds(fixed) - n / rate) < 0.01
    # 已经完好的 WAV 原样返回（幂等）
    assert player.repair_wav(fixed) == fixed
    return f"{len(bad)} -> {len(fixed)} 字节, 时长 {player.wav_seconds(fixed):.2f}s"


@case("播放器：WAV 校验、时长解析、坏数据拦截")
def t_player(base: str) -> str:
    from dskit import player

    wav = _make_wav(1.5, rate=24000)
    assert player.is_wav(wav) and abs(player.wav_seconds(wav) - 1.5) < 0.01
    assert not player.is_wav(b"RIFF0000")
    p = player.WavPlayer()
    try:
        p.play(b"definitely not a wav")
    except player.PlaybackError as exc:
        return f"时长 {player.wav_seconds(wav):.2f}s；坏数据已拦截（{exc}）"
    raise AssertionError("坏数据没有被拦截")


@case("费用计算：闲时/高峰、缓存命中、按次计费")
def t_cost(base: str) -> str:
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000, cache_hit_tokens=600_000, cache_miss_tokens=400_000)
    off_peak = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)   # 周二 12:00 UTC，闲时
    peak = datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc)        # 周二 02:00 UTC，高峰
    assert not is_peak(off_peak) and is_peak(peak)
    weekend = datetime(2026, 11, 15, 2, 0, tzinfo=timezone.utc)     # 周日
    assert not is_peak(weekend)

    cheap = usage.cost("deepseek-flash", at=off_peak)
    expected = 600_000 * 0.003 / 1e6 + 400_000 * 0.15 / 1e6 + 1_000_000 * 0.60 / 1e6
    assert abs(cheap.token_usd - expected) < 1e-9, (cheap.token_usd, expected)
    pricey = usage.cost("deepseek-flash", at=peak)
    assert abs(pricey.token_usd - expected * 2) < 1e-9

    with_tools = Usage(prompt_tokens=10, completion_tokens=10, tool_search=1, tool_fetch=2)
    assert abs(with_tools.cost("deepseek-flash", at=off_peak).tool_usd - 0.00225) < 1e-9
    return f"闲时 ${cheap.usd:.6f} / 高峰 ${pricey.usd:.6f}"


@case("会话：保存/读取/回传格式（剔除本地字段）")
def t_session(base: str) -> str:
    root = Path(tempfile_dir()) / "dskit_sessions_test"
    store = SessionStore(root)
    session = Session(model="deepseek-flash")
    session.add_user("第一问", file_ids=["file-api-abc123"])
    session.add_assistant({"role": "assistant", "content": "第一答", "reasoning_content": "想过"}, citations=[{"url": "https://e.com"}])
    session.add_user("第二问")
    path = store.save(session)
    assert path.exists()

    loaded = store.load(session.id)
    assert loaded.title == "第一问" and loaded.user_turns == 2
    api_msgs = loaded.to_api_messages("你是有用的助手")
    assert api_msgs[0]["role"] == "system"
    assert all(not any(k.startswith("_") for k in m) for m in api_msgs)
    assert api_msgs[1]["content"][1] == {"type": "file", "file_id": "file-api-abc123"}
    assert api_msgs[2]["reasoning_content"] == "想过"

    assert store.list()[0]["id"] == session.id
    assert "第一答" in store.export_markdown(loaded)
    store.delete(session.id)
    assert not store.list()
    for f in root.glob("*"):
        f.unlink(missing_ok=True)
    return "保存/读取/导出/删除均正常"


@case("配置：脏值归一化、Key 脱敏")
def t_config(base: str) -> str:
    cfg = Config.from_dict({"model": "gpt-4", "base_url": "api.deepseek.com/", "timeout": "abc", "reasoning_effort": "ultra", "cny_rate": 0})
    assert cfg.model == "deepseek-flash"
    assert cfg.base_url == "https://api.deepseek.com"
    assert cfg.timeout == 120 and cfg.reasoning_effort == "high" and cfg.cny_rate == 7.10
    assert cfg.proxies() is None
    cfg.proxy = "http://127.0.0.1:7890"
    assert cfg.proxies()["https"] == "http://127.0.0.1:7890"
    masked = Config(api_key="sk-1234567890abcdef").masked_key()
    assert masked.startswith("sk-123") and masked.endswith("cdef") and "*" in masked
    return masked


@case("杂项：URL 提取、本地文本、文件类型判断")
def t_misc(base: str) -> str:
    urls = extract_urls("看下 https://a.com/x?y=1 和 https://a.com/x?y=1 ，还有 http://b.cn/p）")
    assert urls == ["https://a.com/x?y=1", "http://b.cn/p"], urls

    tmp = Path(tempfile_dir()) / "dskit_selftest_gbk.txt"
    tmp.write_bytes("中文内容测试".encode("gbk"))
    assert docs.local_text(tmp) == "中文内容测试"
    tmp.unlink()

    assert docs.pick_purpose(Path("a.pdf")) == "text_recognition"
    assert docs.pick_purpose(Path("a.pdf"), rich_layout=True) == "rich_layout_recognition"
    assert docs.pick_purpose(Path("a.docx")) == "text_recognition"
    assert docs.pick_purpose(Path("a.xlsx")) == "user_data"
    try:
        docs.pick_purpose(Path("a.exe"))
    except DSException as exc:
        assert "不支持" in exc.message
    return "URL/编码/类型判断正常"


@case("导入：官网 v3 导出（含分支按 current_message_id 取主线）")
def t_import_v3(base: str) -> str:
    from dskit import importer

    v3 = {
        "id": "conv-abc",
        "title": "测试会话",
        "current_message_id": 4,
        "updated_at": "2026-05-17T10:00:00+08:00",
        "messages": [
            {"id": 1, "parent_id": None, "role": "USER", "fragments": [{"type": "REQUEST", "content": "你好"}]},
            {
                "id": 2,
                "parent_id": 1,
                "role": "ASSISTANT",
                "fragments": [
                    {"type": "THINK", "content": "用户只是打招呼"},
                    {"type": "RESPONSE", "content": "你好呀，需要什么帮助？"},
                ],
                "status": "FINISHED",
            },
            {"id": 3, "parent_id": 1, "role": "USER", "fragments": [{"type": "REQUEST", "content": "分支B"}]},
            {
                "id": 4,
                "parent_id": 3,
                "role": "ASSISTANT",
                "fragments": [
                    {"type": "TOOL_SEARCH", "content": "DeepSeek 最新"},
                    {"type": "RESPONSE", "content": "回答B"},
                ],
            },
        ],
    }
    path = Path(tempfile_dir()) / "dskit_imp_v3.json"
    path.write_text(json.dumps(v3, ensure_ascii=False), encoding="utf-8")
    items = importer.load_path(path)
    assert len(items) == 1
    item = items[0]
    assert item.source == "deepseek_web_v3" and item.title == "测试会话"
    texts = [m["content"] for m in item.messages]
    assert texts == ["你好", "分支B", "回答B"], texts          # 走了 current_message_id 那条线
    assert item.messages[2].get("_notes") and "联网搜索" in item.messages[2]["_notes"][0]
    path.unlink()
    return f"{len(item.messages)} 条消息, 主线正确"


@case("导入：官网 v3 + 旧版 mapping + 简化格式 + 本软件备份")
def t_import_multi(base: str) -> str:
    from dskit import importer
    from dskit.session import export_bundle

    legacy = {
        "title": "旧格式会话",
        "mapping": {
            "root": {"parent": None, "children": ["1"], "message": None},
            "1": {"parent": "root", "children": ["2"], "message": {"fragments": [{"type": "REQUEST", "content": "问句"}]}},
            "2": {
                "parent": "1",
                "children": [],
                "message": {"fragments": [{"type": "RESPONSE", "content": "答句"}, {"type": "THINK", "content": "想想"}]},
            },
        },
    }
    simple = {"conversations": [{"title": "简化", "messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}]}

    session = Session(model="deepseek-flash")
    session.add_user("备份里的问题")
    session.add_assistant({"role": "assistant", "content": "备份里的回答"})
    own = export_bundle(session)

    for name, payload in (("legacy", legacy), ("simple", simple), ("own", own)):
        path = Path(tempfile_dir()) / f"dskit_imp_{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        items = importer.load_path(path)
        assert items, name
        if name == "legacy":
            assert items[0].source == "deepseek_web_legacy"
            assert items[0].messages[1].get("reasoning_content") == "想想"
        elif name == "simple":
            assert items[0].source == "conversations" and len(items[0].messages) == 2
        else:
            assert items[0].source == "app"
            assert items[0].messages[0]["content"] == "备份里的问题"
        path.unlink()

    converted = importer.to_session(items[0])
    assert converted.is_imported and converted.extra["source"] == "app"
    return "4 种结构均解析正常"


@case("导入：官网 ZIP（chat_sessions 目录 + index）")
def t_import_zip(base: str) -> str:
    import zipfile

    from dskit import importer

    conv = {
        "id": "c1",
        "title": "打包的会话",
        "current_message_id": 2,
        "messages": [
            {"id": 1, "parent_id": None, "role": "USER", "fragments": [{"type": "REQUEST", "content": "zip 问题"}]},
            {"id": 2, "parent_id": 1, "role": "ASSISTANT", "fragments": [{"type": "RESPONSE", "content": "zip 回答"}]},
        ],
    }
    index = [{"id": "c1", "updated_at": "2026-05-01T00:00:00+08:00", "title": "打包的会话"}]
    path = Path(tempfile_dir()) / "dskit_imp.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"export_format_version": 3}))
        zf.writestr("chat_session_index.json", json.dumps(index, ensure_ascii=False))
        zf.writestr("chat_sessions/c1.json", json.dumps(conv, ensure_ascii=False))
        zf.writestr("user.json", json.dumps({"user_id": "u1"}))
    items = importer.load_path(path)
    assert len(items) == 1 and items[0].title == "打包的会话"
    assert [m["content"] for m in items[0].messages] == ["zip 问题", "zip 回答"]
    path.unlink()
    return "ZIP 解析正常"


@case("更新：版本号解析与比较")
def t_update_version(base: str) -> str:
    from dskit.updater import clean_repo, compare_versions, effective_repo, parse_version
    from dskit.version import UPDATE_REPO

    assert parse_version("v1.6.0") == (1, 6, 0, 1)
    assert parse_version("1.5.2") == (1, 5, 2, 1)
    assert parse_version("1.6") == (1, 6, 0, 1)
    assert parse_version("1.6.0-beta.2") == (1, 6, 0, 0)
    assert parse_version("乱七八糟") == (0, 0, 0, 0)
    assert compare_versions("v1.6.0", "1.5.2") == 1
    assert compare_versions("1.5.2", "v1.6.0") == -1
    assert compare_versions("v1.5.2", "1.5.2") == 0
    assert compare_versions("1.6.0-beta.1", "1.6.0") == -1
    assert clean_repo("https://github.com/Sheldon-walker/deepseek-desktop-gui.git") == "Sheldon-walker/deepseek-desktop-gui"
    assert clean_repo(" owner/repo ") == "owner/repo"
    assert effective_repo("") == UPDATE_REPO
    return "v 前缀 / 预发布 / 粘贴仓库 URL 均正确"


@case("更新：Release 解析（有新版本 + exe 直链）")
def t_update_release(base: str) -> str:
    from dskit.updater import parse_release_payload

    payload = {
        "tag_name": "v1.6.0",
        "name": "1.6.0 稳定版",
        "body": "## 更新内容\n- 新增检查更新\n- 修复若干问题",
        "html_url": "https://github.com/Sheldon-walker/deepseek-desktop-gui/releases/tag/v1.6.0",
        "published_at": "2026-11-20T10:00:00Z",
        "prerelease": False,
        "assets": [
            {"name": "README.txt", "browser_download_url": "https://example.com/README.txt"},
            {"name": "DeepSeekDesktop.exe", "browser_download_url": "https://example.com/DeepSeekDesktop.exe"},
        ],
    }
    info = parse_release_payload(payload, current="1.5.2")
    assert info.ok and info.has_update
    assert info.latest == "v1.6.0"
    assert info.message == "有新的稳定版本可用。"
    assert info.download_url.endswith("DeepSeekDesktop.exe")
    assert "新增检查更新" in info.notes
    assert info.to_dict()["current"] == "1.5.2"
    return "状态 / 版本 / 下载直链 / 更新日志均正确"


@case("更新：同版本 / 本地更高 / 缺 tag 边界")
def t_update_release_edge(base: str) -> str:
    from dskit.updater import parse_release_payload

    same = parse_release_payload({"tag_name": "v1.5.2", "body": ""}, current="1.5.2")
    assert same.ok and not same.has_update and same.message == "已是最新版本。"
    old = parse_release_payload({"tag_name": "v1.0.0"}, current="1.5.2")
    assert old.ok and not old.has_update and "高于" in old.message
    bad = parse_release_payload({"name": "没有 tag"}, current="1.5.2")
    assert not bad.ok and "tag_name" in bad.message
    return "三种边界均正确"


def tempfile_dir() -> Path:
    import tempfile

    return Path(tempfile.gettempdir())


# --------------------------------------------------------------------------- 运行
def main() -> int:
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("ALL_PROXY", None)

    server, base = start_server()
    print(f"假服务器已启动：{base}\n")

    passed = 0
    failed: list[tuple[str, str]] = []
    for name, fn in CASES:
        start = time.time()
        try:
            detail = fn(base)
            passed += 1
            print(f"[PASS] {name}  ({(time.time() - start) * 1000:.0f}ms)")
            if VERBOSE:
                print(f"       {detail}")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            print(f"[FAIL] {name}\n       {type(exc).__name__}: {exc}")

    server.shutdown()
    print(f"\n通过 {passed}/{len(CASES)}")
    if failed:
        print("失败项：")
        for name, err in failed:
            print(f"  - {name}: {err}")
        return 1
    print("离线自测全部通过。接下来用真实 Key 跑：python cli.py verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
