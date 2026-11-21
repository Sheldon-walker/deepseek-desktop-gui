"""对话会话与本地历史存储。

历史只写本机：%APPDATA%/DeepSeekDesktop/sessions/<id>.json，一条会话一个文件，
原子写入，不联网、不传第三方。GUI 侧边栏直接读 SessionStore 即可。

消息体统一用 API 原始格式（role/content/...），额外字段以 "_" 开头（_ts/_citations），
回传给接口前会被 to_api_messages() 剔除。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import data_dir


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


@dataclass
class Session:
    id: str = ""
    title: str = "新对话"
    created_at: float = 0.0
    updated_at: float = 0.0
    model: str = "deepseek-flash"
    messages: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = _new_id()
        if not self.created_at:
            self.created_at = _now()
        self.updated_at = self.updated_at or self.created_at

    # ---------- 写入 ----------
    def add_user(
        self,
        text: str,
        *,
        file_ids: list[str] | None = None,
        url_context: str = "",
        file_names: list[str] | None = None,
    ) -> dict:
        """添加一条用户消息。带文件/网页上下文时用 content 数组。

        file_names 与 file_ids 按位置对应，只写进 content part 的 "_name"（下划线前缀，
        to_api_messages() 会剔除，不发给官方 API），用于本地重开历史时还原原始文件名。
        旧调用不传该参数时行为不变。
        """
        parts: list[dict] = []
        if url_context.strip():
            parts.append({"type": "text", "text": f"{text}\n\n以下是用户要求参考的网页内容：\n\n{url_context}"})
        if file_ids:
            if not parts:
                parts.append({"type": "text", "text": text})
            for i, fid in enumerate(file_ids):
                part = {"type": "file", "file_id": fid}
                if file_names and i < len(file_names) and file_names[i]:
                    part["_name"] = file_names[i]
                parts.append(part)
        content: Any = parts if parts else text
        msg = {"role": "user", "content": content, "_ts": _now()}
        self.messages.append(msg)
        if self.title == "新对话" and not self.extra.get("title_manual"):
            self.title = text.strip().splitlines()[0][:28] if text.strip() else "新对话"
        self.updated_at = _now()
        return msg

    def add_assistant(self, message: dict, *, citations: list[dict] | None = None) -> dict:
        msg = dict(message)
        msg.setdefault("role", "assistant")
        msg["_ts"] = _now()
        if citations:
            msg["_citations"] = citations
        self.messages.append(msg)
        self.updated_at = _now()
        return msg

    def add_system_context(self, text: str) -> None:
        """把搜索/网页结果作为一条 system 消息注入（不污染用户原话）。"""
        self.messages.append({"role": "system", "content": text, "_ts": _now(), "_kind": "context"})

    def clear(self) -> None:
        self.messages.clear()
        self.updated_at = _now()

    # ---------- 读取 ----------
    def to_api_messages(self, system_prompt: str = "") -> list[dict]:
        """产出可直接发给接口的 messages（剔除 "_" 本地字段，含 content part 内的）。"""
        out: list[dict] = []
        if system_prompt:
            out.append({"role": "system", "content": system_prompt})
        for msg in self.messages:
            clean = {k: v for k, v in msg.items() if not k.startswith("_")}
            # 顶层剔除是浅拷贝，content 数组里的 part 需要单独再剔除一次下划线本地字段
            # （如附件的 "_name"），否则会被原样发给官方 API 造成 400。
            content = clean.get("content")
            if isinstance(content, list):
                clean["content"] = [
                    {k: v for k, v in part.items() if not k.startswith("_")}
                    if isinstance(part, dict) else part
                    for part in content
                ]
            if clean.get("role") == "assistant" and not clean.get("content") and not clean.get("server_tool_calls"):
                continue  # 空回复（被中断）不入上下文
            out.append(clean)
        return out

    def last_user_text(self) -> str:
        for msg in reversed(self.messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            for part in content or []:
                if isinstance(part, dict) and part.get("type") == "text":
                    return str(part.get("text") or "")
            return ""
        return ""

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "updated_at": self.updated_at,
            "model": self.model,
            "turns": sum(1 for m in self.messages if m.get("role") in ("user", "assistant")),
        }

    @property
    def user_turns(self) -> int:
        return sum(1 for m in self.messages if m.get("role") == "user")

    @property
    def is_imported(self) -> bool:
        return bool(self.extra.get("imported"))

    @property
    def source_label(self) -> str:
        return {
            "app": "本软件",
            "deepseek_web_v3": "官网导出",
            "deepseek_web_legacy": "官网导出(旧)",
            "conversations": "通用格式",
        }.get(str(self.extra.get("source") or ""), "")

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "model": self.model,
            "messages": self.messages,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Session":
        return cls(
            id=str(raw.get("id") or _new_id()),
            title=str(raw.get("title") or "新对话"),
            created_at=float(raw.get("created_at") or _now()),
            updated_at=float(raw.get("updated_at") or _now()),
            model=str(raw.get("model") or "deepseek-flash"),
            messages=list(raw.get("messages") or []),
            extra=dict(raw.get("extra") or {}),
        )


class SessionStore:
    """会话文件仓库。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (data_dir() / "sessions")

    def path_of(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def save(self, session: Session) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_of(session.id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        return target

    def load(self, session_id: str) -> Session:
        raw = json.loads(self.path_of(session_id).read_text(encoding="utf-8"))
        return Session.from_dict(raw)

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        items: list[dict] = []
        for file in self.root.glob("*.json"):
            try:
                raw = json.loads(file.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            items.append(
                {
                    "id": raw.get("id") or file.stem,
                    "title": raw.get("title") or "新对话",
                    "updated_at": float(raw.get("updated_at") or 0),
                    "model": raw.get("model") or "",
                    "turns": sum(1 for m in raw.get("messages") or [] if m.get("role") in ("user", "assistant")),
                    "imported": bool((raw.get("extra") or {}).get("imported")),
                    "source": str((raw.get("extra") or {}).get("source") or ""),
                    "pinned": bool((raw.get("extra") or {}).get("pinned")),
                }
            )
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def existing_raw_ids(self) -> set[str]:
        """已导入过的外部会话 id，用于避免重复导入。"""
        found: set[str] = set()
        if not self.root.exists():
            return found
        for file in self.root.glob("*.json"):
            try:
                raw = json.loads(file.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            raw_id = str((raw.get("extra") or {}).get("raw_id") or "")
            if raw_id:
                found.add(raw_id)
        return found

    def delete(self, session_id: str) -> bool:
        target = self.path_of(session_id)
        if target.exists():
            target.unlink()
            return True
        return False

    def export_markdown(self, session: Session) -> str:
        lines = [f"# {session.title}", ""]
        for msg in session.messages:
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, list):
                content = "\n".join(str(p.get("text") or f"[文件 {p.get('file_id')}]") for p in content if isinstance(p, dict))
            if role == "user":
                lines += ["## 我", str(content or ""), ""]
            elif role == "assistant":
                if msg.get("reasoning_content"):
                    lines += ["> 思考过程：", "> " + str(msg["reasoning_content"]).replace("\n", "\n> "), ""]
                lines += ["## 助手", str(content or ""), ""]
                for cite in msg.get("_citations") or []:
                    lines.append(f"- [{cite.get('title') or cite.get('url')}]({cite.get('url')})")
                if msg.get("_citations"):
                    lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------- 导出/导入标记
EXPORT_APP_ID = "DeepSeekDesktop"
EXPORT_KIND = "session"
EXPORT_VERSION = 1


def export_bundle(session: Session) -> dict:
    """本软件导出的备份文件结构（可原样再导入）。"""
    return {
        "app": EXPORT_APP_ID,
        "kind": EXPORT_KIND,
        "version": EXPORT_VERSION,
        "exported_at": _now(),
        "session": session.to_dict(),
    }


def write_export(session: Session, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export_bundle(session), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def is_own_export(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("app") == EXPORT_APP_ID and isinstance(raw.get("session"), dict)
