"""把 App 里的 Tk 控件替换成"只会往网页发消息"的替身。

思路：App 的全部业务逻辑（流式、计费、朗读、附件、导入）保持不变，只把
`self.chat / self.input / self.sidebar / self.status_left ...` 换成这里的适配器，
它们的方法签名和原来的控件一致，内部改成 postMessage 给 ui/shell_html.py 的页面。
这样"外壳搬进 WebView2"不用重写业务代码，风险最小。
"""

from __future__ import annotations

import tkinter as tk

from . import theme
from .webchat import WebChatView, _clock, _content_text  # noqa: F401  复用取历史消息的格式化逻辑


class _Emitter:
    def __init__(self, app) -> None:
        self.app = app

    def _send(self, type_: str, data=None) -> None:
        self.app.post(type_, data)


# --------------------------------------------------------------------------- 消息块
class JsBlock(_Emitter):
    def __init__(self, app, msg_id: str, model: str) -> None:
        super().__init__(app)
        self.msg_id = msg_id
        self.model = model
        self.body_text = ""
        self.reasoning_text = ""
        self._notes: list[str] = []
        self._finished = False
        self._is_error = False
        self._speak_state = "idle"

    def append_reasoning(self, text: str) -> None:
        self.reasoning_text += text
        self._send("reasoning", {"id": self.msg_id, "text": text})

    def append_content(self, text: str) -> None:
        self.body_text += text
        self._send("content", {"id": self.msg_id, "text": text})

    def add_note(self, note: str) -> None:
        self._notes.append(note)
        self._send("note", {"id": self.msg_id, "text": note})

    def finalize(self, *, citations=None, footer: str = "", cost_text: str = "") -> None:
        self._finished = True
        self._send(
            "assistant_end",
            {
                "id": self.msg_id,
                "content": self.body_text,
                "reasoning": self.reasoning_text,
                "notes": self._notes,
                "citations": citations or [],
                "footer": footer,
                "cost": cost_text,
            },
        )

    def set_error(self, message: str) -> None:
        self._finished = True
        self._is_error = True
        self._send("error", {"id": self.msg_id, "text": message})

    def speak_text(self) -> str:
        if self._is_error:
            return ""
        return (self.body_text or "").strip()

    def on_speak_click(self) -> None:
        if self.app.chat.on_speak:
            self.app.chat.on_speak(self)

    def set_speak_state(self, state: str) -> None:
        self._speak_state = state
        self._send("speak_state", {"id": self.msg_id, "state": state})

    @property
    def speak_state(self) -> str:
        return self._speak_state


# --------------------------------------------------------------------------- 对话区
class JsChat(_Emitter):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._blocks: dict[str, JsBlock] = {}
        self._last_assistant = None
        self._msg_id = 0
        self.zoom = 1.0
        self._full_msgs: list[dict] = []
        self._full_model = "deepseek-flash"
        self._cny_rate = 7.10
        self.on_speak = None
        self.on_stop_speak = None

    # ---- 与 WebChatView 同名同签名 ----
    def show_welcome(self) -> None:
        self._send("welcome")

    def clear(self) -> None:
        self._blocks.clear()
        self._last_assistant = None
        self._send("clear")

    def add_user(self, content, *, attachments=None, msg_index=None, quotes=None) -> None:
        # 直接委托给 WebChatView，签名永远跟随它。
        # 这里曾复制实现而漏加 quotes 参数，导致 on_send 抛 TypeError、点击发送毫无反应。
        WebChatView.add_user(
            self, content, attachments=attachments, msg_index=msg_index, quotes=quotes
        )

    def add_assistant(self, *, model: str = "deepseek-flash", timestamp=None, index=None) -> JsBlock:
        self._msg_id += 1
        mid = "a" + str(self._msg_id)
        payload = {"id": mid, "model": model, "time": _clock(timestamp)}
        if index is not None:
            payload["index"] = index
        self._send("assistant_begin", payload)
        block = JsBlock(self.app, mid, model)
        self._blocks[mid] = block
        self._last_assistant = block
        return block

    def add_notice(self, text: str) -> None:
        self._send("notice", {"text": text})

    def render_history(self, messages, *, model: str = "deepseek-flash", show_all: bool = False, cny_rate: float = 7.10) -> None:
        WebChatView.render_history(self, messages, model=model, show_all=show_all, cny_rate=cny_rate)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = float(zoom)
        self._send("zoom", {"zoom": self.zoom})

    def set_visible(self, visible: bool) -> None:
        pass

    def refresh_bounds(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


# --------------------------------------------------------------------------- 输入栏
class _Toggle:
    def __init__(self, app, key: str, value: bool = False) -> None:
        self.app = app
        self.key = key
        self._value = bool(value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self.app.post("set_toggle", {"key": self.key, "value": bool(value)})


class _ModelMenu:
    def __init__(self, app) -> None:
        self.app = app

    def set(self, value: str) -> None:
        self.app.post("set_model", str(value))


class _RichVar:
    def __init__(self, app) -> None:
        self.app = app
        self._value = False

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self.app.post("set_rich", self._value)


class _Text:
    def __init__(self, app) -> None:
        self.app = app

    def focus_set(self) -> None:
        self.app.post("input_focus")


class JsInput(_Emitter):
    def __init__(self, app, *, model: str, thinking: bool, web: bool) -> None:
        super().__init__(app)
        self.think_toggle = _Toggle(app, "thinking", thinking)
        self.search_toggle = _Toggle(app, "web", web)
        self.model_menu = _ModelMenu(app)
        self.rich_var = _RichVar(app)
        self.text = _Text(app)
        self.attach_btn = _Noop()
        self._busy = False

    def show_attachments(self, items) -> None:
        """items 是 FileRef 列表（不是 dict），两种都兼容一下。"""
        out = []
        for item in items or []:
            if isinstance(item, dict):
                fid = item.get("file_id") or ""
                name = item.get("name") or item.get("filename") or fid
            else:
                fid = getattr(item, "file_id", "") or ""
                name = getattr(item, "filename", "") or getattr(item, "name", "") or fid
            out.append({"name": name, "file_id": fid})
        self._send("attachments", out)

    def show_quotes(self, items) -> None:
        out = []
        for q in items or []:
            out.append({
                "text": q.get("text", "") if isinstance(q, dict) else str(q),
                "role": q.get("role", "") if isinstance(q, dict) else "",
            })
        self._send("quotes", out)

    def set_text(self, text: str) -> None:
        self._text_cache = text
        self._send("input_set", text)

    def append_text(self, text: str) -> None:
        """语音识别结果追加到输入框；走前端 append，不能覆盖用户已手输的内容。"""
        text = text or ""
        self._text_cache = self.get_text() + text
        self._send("input_append", text)

    def get_text(self) -> str:
        return getattr(self, "_text_cache", "")

    def clear(self) -> None:
        self._text_cache = ""
        self._send("input_clear")

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._send("busy", self._busy)

    def set_hint(self, text: str) -> None:
        self._send("hint", text)

    def set_cost(self, text: str) -> None:
        self._send("cost", text)

    def set_rich(self, value: bool) -> None:
        self.rich_var.set(value)

    def set_recording(self, on: bool, _elapsed: float = 0.0) -> None:
        self._send("recording", bool(on))

    def set_voice_busy(self, busy: bool) -> None:
        self._send("status", "正在识别语音…" if busy else "")


# --------------------------------------------------------------------------- 其他
class _Noop:
    def configure(self, **_kw) -> None:
        pass

    def cget(self, _k) -> str:
        return ""

    def pack(self, **_kw) -> None:
        pass

    def grid(self, **_kw) -> None:
        pass

    def grid_remove(self) -> None:
        pass

    def pack_forget(self) -> None:
        pass


class JsLabel(_Emitter):
    """状态栏 / 标题 / 来源按钮这类只显示文字的控件。"""

    def __init__(self, app, kind: str) -> None:
        super().__init__(app)
        self.kind = kind
        self._text = ""

    def configure(self, text=None, **_kw) -> None:
        if text is None:
            return
        self._text = str(text)
        if self.kind == "title":
            self._send("title", self._text)
        elif self.kind == "status":
            self._send("status", self._text)
        elif self.kind == "status_right":
            self._send("status_right", self._text)
        elif self.kind == "source":
            self._send("source_btn", self._text)
        elif self.kind == "notice":
            self._send("notice_bar", self._text)

    def cget(self, _k) -> str:
        return self._text

    pack = _Noop.pack
    grid = _Noop.grid
    grid_remove = _Noop.grid_remove
    pack_forget = _Noop.pack_forget


class JsSidebar(_Emitter):
    def refresh(self, items: list[dict], active: str | None = None) -> None:
        from datetime import datetime

        out = []
        for it in items or []:
            bits = []
            if it.get("imported"):
                bits.append("[官网导入]")
            bits.append(f"{it.get('turns', 0)} 轮")
            ts = it.get("updated_at") or 0
            if ts:
                bits.append(datetime.fromtimestamp(ts).strftime("%m-%d %H:%M"))
            out.append(
                {
                    "id": it.get("id"),
                    "title": str(it.get("title") or "新对话"),
                    "meta": " · ".join(bits),
                    "ts": ts,
                    "pinned": bool(it.get("pinned")),
                }
            )
        self._items = out
        self._send("sessions", {"items": out, "active": active})

    def set_active(self, session_id: str | None) -> None:
        self._send("sessions", {"items": getattr(self, "_items", []), "active": session_id})

    def pack(self, **_kw) -> None:
        pass

    def pack_forget(self) -> None:
        pass


class JsPanel(_Emitter):
    def __init__(self, app) -> None:
        super().__init__(app)
        self.visible = False

    def set_results(self, groups, cites, notes=None) -> None:
        self._send("panel", {"groups": groups or [], "cites": cites or [], "notes": notes or []})

    def set_visible(self, visible: bool) -> None:
        self.visible = bool(visible)
        self._send("panel_open", self.visible)

    def grid(self, **_kw) -> None:
        self.set_visible(True)

    def grid_remove(self) -> None:
        self.set_visible(False)

    def set_theme(self) -> None:
        pass


class JsNoticeBar(_Noop):
    def __init__(self, app) -> None:
        self.app = app

    def grid(self, **_kw) -> None:
        self.app.post("notice_show", True)

    def grid_remove(self) -> None:
        self.app.post("notice_show", False)
