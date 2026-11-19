"""会话导入：把外部文件转成本软件的 Session。

支持三类来源，全部纯本地解析，不联网、不调模型、不产生任何费用：

1. 本软件导出的备份（`{"app":"DeepSeekDesktop","session":{...}}`）
2. DeepSeek 官网导出的数据包 `deepseek_data-*.zip`（export_format_version 3）
   结构：manifest.json / chat_session_index.json / chat_sessions/<id>.json
   每条消息 `{id, parent_id, role, fragments:[{type,content}], status, inserted_at}`，
   fragments 的 type 有 REQUEST / RESPONSE / THINK / TOOL_SEARCH / TOOL_OPEN /
   READ_LINK / FILE / CONTENT_FILTER 等。
3. 旧版 conversations.json（mapping 树，和 ChatGPT 导出同构），
   以及各种 `{"conversations":[{messages:[{role,content}]}]}` 的简化格式。

分支处理：官网导出是树（重新生成回答会产生分支），导入时沿
`current_message_id` 往上找父链，得到用户当时实际看到的那条主线。
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import DSException
from .session import Session

SUPPORTED_SUFFIXES = (".json", ".zip")
_ROLE_MAP = {
    "user": "user",
    "human": "user",
    "request": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "model": "assistant",
    "bot": "assistant",
    "response": "assistant",
    "system": "system",
    "tool": "tool",
}
_TOOL_FRAGMENTS = {"TOOL_SEARCH", "TOOL_OPEN", "READ_LINK", "TOOL_FIND", "TOOL_IMAGE_SEARCH", "SEARCH"}


@dataclass
class ImportedSession:
    title: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    model: str = ""
    messages: list[dict] = field(default_factory=list)
    source: str = "conversations"
    raw_id: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m.get("role") == "user")

    def display_meta(self) -> str:
        when = ""
        if self.updated_at:
            when = datetime.fromtimestamp(self.updated_at).strftime("%Y-%m-%d %H:%M")
        parts = [when] if when else []
        parts.append(f"{self.turns} 轮")
        if self.model:
            parts.append(self.model)
        return " · ".join(parts)


# --------------------------------------------------------------------------- 工具
def _parse_ts(value: Any) -> float:
    """兼容 unix 秒/毫秒、ISO 8601 字符串。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        num = float(value)
        return num / 1000 if num > 1e11 else num
    text = str(value).strip()
    if not text:
        return 0.0
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return _parse_ts(float(text))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _role(value: Any, default: str = "") -> str:
    return _ROLE_MAP.get(str(value or "").strip().lower(), default)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        out = []
        for part in value:
            if isinstance(part, dict):
                out.append(str(part.get("text") or part.get("content") or ""))
            else:
                out.append(str(part))
        return "".join(out)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or "")
    return str(value)


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def _id_key(value: Any) -> tuple[int, str]:
    """消息 id 排序键：能转数字就按数字，否则按字符串长度+内容。"""
    try:
        return (int(value), "")
    except (TypeError, ValueError):
        text = str(value or "")
        return (10**9, text)


# --------------------------------------------------------------------------- fragments
def _message_from_fragments(node: dict, *, ts: float) -> dict | None:
    frags = node.get("fragments")
    if isinstance(frags, str):        # 早期导出里 fragments 可能是空串
        frags = []
    if not isinstance(frags, list):
        frags = []

    texts: list[str] = []
    reasoning: list[str] = []
    notes: list[str] = []
    for frag in frags:
        if not isinstance(frag, dict):
            texts.append(str(frag))
            continue
        kind = str(frag.get("type") or "").upper()
        content = _as_text(frag.get("content"))
        if kind == "CONTENT_FILTER":
            return None
        if kind == "REQUEST":
            texts.append(content)
        elif kind == "RESPONSE":
            texts.append(content)
        elif kind == "THINK":
            reasoning.append(content)
        elif kind == "FILE":
            name = frag.get("file_name") or frag.get("name") or frag.get("file_id") or "附件"
            texts.append(f"[附件：{name}（官网导出不含文件本体）]")
        elif kind in _TOOL_FRAGMENTS:
            note = _tool_note(kind, content)
            if note:
                notes.append(note)
        else:
            if content:
                texts.append(content)

    role = _role(node.get("role"))
    if not role:
        has_request = any(isinstance(f, dict) and str(f.get("type")).upper() == "REQUEST" for f in frags)
        role = "user" if has_request else "assistant"

    body = _clean("\n\n".join(t for t in texts if t))
    think = _clean("\n".join(reasoning))
    if not body and not think:
        return None
    msg: dict[str, Any] = {"role": role, "content": body, "_ts": ts, "_imported": True}
    if think:
        msg["reasoning_content"] = think
    if notes:
        msg["_notes"] = notes
    return msg


def _tool_note(kind: str, content: str) -> str:
    brief = _clean(content).replace("\n", " ")
    if len(brief) > 120:
        brief = brief[:120] + "…"
    label = {
        "TOOL_SEARCH": "联网搜索",
        "SEARCH": "联网搜索",
        "TOOL_OPEN": "打开网页",
        "READ_LINK": "读取链接",
        "TOOL_FIND": "页内查找",
        "TOOL_IMAGE_SEARCH": "图片搜索",
    }.get(kind, kind)
    return f"{label}：{brief}" if brief else label


# --------------------------------------------------------------------------- 三种结构
def _from_v3(obj: dict) -> ImportedSession | None:
    """官网 export_format_version 3：messages 用 parent_id 串成的树。"""
    raw_messages = obj.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return None
    by_id: dict[str, dict] = {}
    for msg in raw_messages:
        if isinstance(msg, dict) and msg.get("id") is not None:
            by_id[str(msg["id"])] = msg

    chain: list[dict] = []
    seen: set[str] = set()
    current = obj.get("current_message_id")
    while current is not None and str(current) in by_id and str(current) not in seen:
        seen.add(str(current))
        node = by_id[str(current)]
        chain.append(node)
        current = node.get("parent_id")
    chain.reverse()

    if not chain:
        chain = sorted([m for m in raw_messages if isinstance(m, dict)], key=lambda m: _id_key(m.get("id")))

    messages: list[dict] = []
    for node in chain:
        ts = _parse_ts(node.get("inserted_at") or node.get("created_at"))
        msg = _message_from_fragments(node, ts=ts)
        if msg:
            messages.append(msg)
    if not messages:
        return None

    updated = _parse_ts(obj.get("updated_at")) or (messages[-1].get("_ts") or 0)
    created = _parse_ts(obj.get("inserted_at") or obj.get("created_at")) or (messages[0].get("_ts") or 0)
    return ImportedSession(
        title=_clean(str(obj.get("title") or "")) or _fallback_title(messages),
        created_at=created or updated,
        updated_at=updated,
        model=str(obj.get("model") or ""),
        messages=messages,
        source="deepseek_web_v3",
        raw_id=str(obj.get("id") or ""),
    )


def _from_mapping(obj: dict) -> ImportedSession | None:
    """旧版 / ChatGPT 同构：mapping 树，走最长分支。"""
    mapping = obj.get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        return None

    depth_cache: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id in depth_cache:
            return depth_cache[node_id]
        node = mapping.get(node_id) or {}
        kids = [k for k in (node.get("children") or []) if k in mapping]
        value = 1 if not kids else 1 + max(depth(k) for k in kids)
        depth_cache[node_id] = value
        return value

    current = "root" if "root" in mapping else next(
        (k for k, v in mapping.items() if isinstance(v, dict) and not v.get("parent")), ""
    )
    chain: list[dict] = []
    seen: set[str] = set()
    while current and current in mapping and current not in seen:
        seen.add(current)
        node = mapping[current]
        if isinstance(node.get("message"), dict):
            chain.append(node["message"])
        kids = [k for k in (node.get("children") or []) if k in mapping]
        if not kids:
            break
        current = max(kids, key=depth)

    messages: list[dict] = []
    for node in chain:
        ts = _parse_ts(node.get("inserted_at") or node.get("create_time"))
        author = node.get("author") or {}
        node2 = dict(node)
        node2.setdefault("role", author.get("role"))
        msg = _message_from_fragments(node2, ts=ts)
        if not msg and isinstance(node.get("content"), dict):
            text = _as_text(node["content"].get("parts"))
            if text.strip():
                msg = {"role": _role(author.get("role"), "assistant"), "content": _clean(text), "_ts": ts, "_imported": True}
        if msg:
            messages.append(msg)
    if not messages:
        return None

    updated = _parse_ts(obj.get("updated_at")) or (messages[-1].get("_ts") or 0)
    created = _parse_ts(obj.get("inserted_at") or obj.get("create_time")) or (messages[0].get("_ts") or 0)
    return ImportedSession(
        title=_clean(str(obj.get("title") or "")) or _fallback_title(messages),
        created_at=created or updated,
        updated_at=updated,
        model=str(obj.get("model") or ""),
        messages=messages,
        source="deepseek_web_legacy",
        raw_id=str(obj.get("id") or ""),
    )


def _from_simple(obj: dict) -> ImportedSession | None:
    """{messages:[{role,content}]} 这类简化格式。"""
    raw_messages = obj.get("messages") or obj.get("chat_messages") or obj.get("items")
    if not isinstance(raw_messages, list) or not raw_messages:
        return None
    messages: list[dict] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = _role(item.get("role") or (item.get("author") or {}).get("role") or item.get("sender"))
        if role not in ("user", "assistant", "system"):
            role = "assistant" if item.get("content") and not item.get("is_user") else "user"
        text = _as_text(item.get("content") or item.get("text") or item.get("message"))
        think = _as_text(item.get("reasoning_content") or item.get("thinking") or item.get("reasoning"))
        if not text.strip() and not think.strip():
            continue
        msg: dict[str, Any] = {
            "role": role,
            "content": _clean(text),
            "_ts": _parse_ts(item.get("create_time") or item.get("timestamp") or item.get("created_at")),
            "_imported": True,
        }
        if think.strip():
            msg["reasoning_content"] = _clean(think)
        messages.append(msg)
    if not messages:
        return None
    updated = _parse_ts(obj.get("updated_at") or obj.get("update_time")) or (messages[-1].get("_ts") or 0)
    created = _parse_ts(obj.get("create_time") or obj.get("created_at")) or (messages[0].get("_ts") or 0)
    return ImportedSession(
        title=_clean(str(obj.get("title") or obj.get("name") or "")) or _fallback_title(messages),
        created_at=created or updated,
        updated_at=updated,
        model=str(obj.get("model") or ""),
        messages=messages,
        source="conversations",
        raw_id=str(obj.get("id") or ""),
    )


def _fallback_title(messages: list[dict]) -> str:
    for msg in messages:
        if msg.get("role") == "user":
            first = _clean(str(msg.get("content") or "")).splitlines()
            if first and first[0].strip():
                return first[0].strip()[:40]
    return "导入的对话"


def _convert_one(obj: Any) -> ImportedSession | None:
    if not isinstance(obj, dict):
        return None
    if "mapping" in obj:
        return _from_mapping(obj)
    if isinstance(obj.get("messages"), list):
        if any(isinstance(m, dict) and m.get("fragments") is not None for m in obj["messages"]):
            return _from_v3(obj)
        return _from_simple(obj)
    return _from_simple(obj)


# --------------------------------------------------------------------------- 入口
def load_path(path: str | Path, *, max_sessions: int | None = None) -> list[ImportedSession]:
    """读取 .json 或 .zip，返回可导入的会话列表（按更新时间倒序）。

    max_sessions=None 表示全部返回（默认）；只有显式传值才截断。
    """
    p = Path(path)
    if not p.exists():
        raise DSException(f"文件不存在：{p}", code="file_not_found")
    suffix = p.suffix.lower()
    if suffix == ".zip":
        items = _load_zip(p)
    elif suffix == ".json":
        items = _load_json_file(p)
    else:
        raise DSException(
            f"不支持的文件类型：{suffix or '无扩展名'}",
            code="unsupported_file",
            hint="支持 .json（本软件备份 / 官网 conversations.json）和 .zip（官网导出包）",
        )
    if not items:
        raise DSException(
            "没有解析出任何会话",
            code="empty_import",
            hint="确认是 DeepSeek 官网导出的 JSON/ZIP，或本软件导出的备份文件",
        )
    items.sort(key=lambda x: (x.updated_at, x.created_at), reverse=True)
    if max_sessions is not None and len(items) > max_sessions:
        keep = items[:max_sessions]
        keep[0].warnings.append(f"文件中共 {len(items)} 个会话，仅列出最近 {max_sessions} 个")
        return keep
    return items


def _load_json_file(p: Path) -> list[ImportedSession]:
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        raise DSException("不是合法 JSON 文件", code="bad_json", detail=str(exc)) from exc
    return _from_object(raw, filename=p.name)


def _from_object(raw: Any, *, filename: str = "") -> list[ImportedSession]:
    from .session import Session as _Session
    from .session import is_own_export

    if is_own_export(raw):
        session = _Session.from_dict(raw["session"])
        session.extra["imported"] = True
        session.extra["source"] = "app"
        session.extra["imported_at"] = datetime.now().timestamp()
        item = ImportedSession(
            title=session.title,
            created_at=session.created_at,
            updated_at=session.updated_at,
            model=session.model,
            messages=session.messages,
            source="app",
            raw_id=session.id,
        )
        return [item]

    if isinstance(raw, list):
        if raw and all(isinstance(x, str) for x in raw[:5]):
            raise DSException(
                "这看起来不是对话导出文件",
                code="unknown_format",
                hint=f"文件名：{filename}",
            )
        out: list[ImportedSession] = []
        for entry in raw:
            item = _convert_one(entry)
            if item:
                out.append(item)
        return out

    if isinstance(raw, dict):
        for key in ("conversations", "data", "sessions", "chat_sessions", "items"):
            value = raw.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                out = []
                for entry in value:
                    item = _convert_one(entry) or _from_v3(entry)
                    if item:
                        out.append(item)
                if out:
                    return out
        single = _convert_one(raw)
        if single:
            return [single]
    return []


def _load_zip(p: Path) -> list[ImportedSession]:
    items: list[ImportedSession] = []
    index_meta: dict[str, dict] = {}
    try:
        with zipfile.ZipFile(p) as zf:
            names = zf.namelist()
            for name in names:
                base = name.rsplit("/", 1)[-1].lower()
                if base in ("chat_session_index.json", "manifest.json") or base == "user.json":
                    continue
                if not base.endswith(".json"):
                    continue
                try:
                    raw = json.loads(zf.read(name).decode("utf-8", "replace"))
                except (ValueError, KeyError):
                    continue
                if base == "conversations.json":
                    for item in _from_object(raw, filename=name):
                        items.append(item)
                    continue
                if (
                    isinstance(raw, list)
                    and raw
                    and isinstance(raw[0], dict)
                    and "id" in raw[0]
                    and "updated_at" in raw[0]
                    and "messages" not in raw[0]
                ):
                    for entry in raw:
                        if isinstance(entry, dict):
                            index_meta[str(entry.get("id"))] = entry
                    continue
                if isinstance(raw, dict):
                    for item in _from_object(raw, filename=name):
                        items.append(item)
    except zipfile.BadZipFile as exc:
        raise DSException("ZIP 文件损坏或未下载完整", code="bad_zip", detail=str(exc)) from exc

    for item in items:
        meta = index_meta.get(item.raw_id)
        if meta:
            item.updated_at = item.updated_at or _parse_ts(meta.get("updated_at"))
            if not item.title:
                item.title = str(meta.get("title") or "")
    return items


def to_session(item: ImportedSession) -> Session:
    """转成本软件的 Session（打上 imported 标记，便于侧边栏区分）。"""
    session = Session(
        title=item.title or "导入的对话",
        created_at=item.created_at or datetime.now().timestamp(),
        updated_at=item.updated_at or datetime.now().timestamp(),
        model=item.model if item.model in ("deepseek-flash", "deepseek-v4-pro") else "deepseek-flash",
        messages=item.messages,
        extra={
            "imported": True,
            "source": item.source,
            "raw_id": item.raw_id,
            "imported_at": datetime.now().timestamp(),
        },
    )
    return session
