"""联网能力封装：Search API / Fetch API。

两条互补的联网路径，本模块负责「客户端显式检索」，client.py 里的
deepseek_web_search / deepseek_read_url 工具负责「模型自主检索」。

- 显式检索：需要用户看到搜索结果列表、或想把网页正文拼进上下文时用。
- 模型自主检索：日常"联网搜索"开关走这条，模型自己决定搜什么、读哪页，
  并在回答里返回 annotations 引用。

接口：
  POST  {base}/v1/tools/search    $0.75 / 1000 次成功请求，QPS 100
  POST  {base}/v1/tools/fetch     $0.75 / 1000 次成功请求，QPS 25
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .client import DeepSeekClient
from .errors import DSException

_URL_RE = re.compile(r"https?://[^\s<>\"'）)\]，。；、]+", re.IGNORECASE)


@dataclass
class SearchResult:
    title: str = ""
    url: str = ""
    snippet: str = ""
    summary: str = ""
    content: str = ""
    site_name: str = ""
    date: str = ""
    authority: int = -1
    rerank_score: float = 0.0

    @classmethod
    def from_api(cls, raw: dict) -> "SearchResult":
        return cls(
            title=str(raw.get("title") or ""),
            url=str(raw.get("url") or ""),
            snippet=str(raw.get("snippet") or ""),
            summary=str(raw.get("summary") or ""),
            content=str(raw.get("content") or ""),
            site_name=str(raw.get("site_name") or ""),
            date=str(raw.get("date") or ""),
            authority=int(raw.get("authority") if raw.get("authority") is not None else -1),
            rerank_score=float(raw.get("rerank_score") or 0.0),
        )

    def display(self) -> str:
        meta = []
        if self.site_name:
            meta.append(self.site_name)
        if self.date:
            meta.append(self.date[:10])
        if self.rerank_score:
            meta.append(f"score {self.rerank_score:.2f}")
        return f"{self.title}  [{' | '.join(meta)}]" if meta else self.title


@dataclass
class FetchedPage:
    url: str = ""
    title: str = ""
    content: str = ""
    truncated: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def chars(self) -> int:
        return len(self.content)


def search(
    client: DeepSeekClient,
    query: str,
    *,
    count: int = 8,
    need_content: bool = False,
    ori_question: str | None = None,
) -> list[SearchResult]:
    """调用官方搜索接口，返回结构化结果。

    query 支持 site: / -site: / "精确短语" / lang: / after: / before: 等运算符。
    """
    query = (query or "").strip()
    if not query:
        raise DSException("搜索关键词为空", code="empty_query", hint="换个具体一点的问题再搜")
    body = {
        "query": query[:128],
        "count": max(1, min(int(count), 50)),
        "need_content": bool(need_content),
    }
    if ori_question:
        body["ori_question"] = ori_question[:128]

    data = client.request("POST", "/v1/tools/search", json_body=body)
    return [SearchResult.from_api(item) for item in (data.get("results") or [])]


def fetch_url(client: DeepSeekClient, url: str, *, max_chars: int = 0) -> FetchedPage:
    """抓取单个网页并返回 Markdown 正文。

    max_chars > 0 时做客户端截断（服务端返回全文，长页面可能上万字）。
    """
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise DSException(
            "链接格式不对",
            code="bad_url",
            hint="需要以 http:// 或 https:// 开头的完整网址",
        )
    data = client.request("POST", "/v1/tools/fetch", json_body={"url": url[:8192]})
    page = FetchedPage(
        url=url,
        title=str(data.get("title") or ""),
        content=str(data.get("content") or ""),
    )
    if max_chars and len(page.content) > max_chars:
        page.content = page.content[:max_chars] + "\n\n…（内容过长，已截断）"
        page.truncated = True
    return page


def extract_urls(text: str) -> list[str]:
    """从用户输入里提取链接（去重保序，最多 5 个）。"""
    seen: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:!?")
        if url not in seen:
            seen.append(url)
        if len(seen) >= 5:
            break
    return seen


def build_context(results: list[SearchResult], *, max_chars: int = 6000) -> str:
    """把搜索结果拼成可直接塞进 messages 的参考资料块。"""
    if not results:
        return ""
    chunks: list[str] = []
    used = 0
    for idx, item in enumerate(results, 1):
        body = (item.summary or item.snippet or item.content or "").strip()
        if not body:
            continue
        block = f"[{idx}] {item.title}\n来源：{item.url}\n时间：{item.date[:10] or '未知'}\n{body}\n"
        if used + len(block) > max_chars:
            break
        chunks.append(block)
        used += len(block)
    return "\n".join(chunks)
