"""对话区 WebView 容器：用 WebView2 渲染聊天内容，替代原来的 Tk ChatView。

对外接口与旧 ChatView 兼容（add_user / add_assistant / render_history /
show_welcome / set_zoom），内部把消息转成 JSON 发给前端 HTML 渲染。
"""

from __future__ import annotations

import json
import time
import webbrowser

import customtkinter as ctk

from dskit.config import data_dir
from dskit.usage import Usage

from . import theme, wv2
from .chat_html import CHAT_HTML

C = theme.COLORS


def _money(value: float) -> str:
    if value >= 0.01:
        return f"¥{value:.4f}"
    if value >= 0.0001:
        return f"¥{value:.5f}"
    return f"¥{value:.6f}"


def _clock(ts: float | None = None) -> str:
    return time.strftime("%H:%M", time.localtime(ts or time.time()))


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for part in content or []:
        if isinstance(part, dict):
            if part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif part.get("type") == "file":
                parts.append(f"[附件 {part.get('file_id')}]")
        elif part:
            parts.append(str(part))
    return "\n".join(parts)


class WebAssistantBlock:
    """流式助手消息的兼容层（对旧 AssistantBlock 接口做等价实现）。"""

    def __init__(self, view: "WebChatView", msg_id, model: str) -> None:
        self.view = view
        self.msg_id = msg_id
        self.model = model
        self.reasoning_text = ""
        self.body_text = ""
        self._notes: list[str] = []
        self._finished = False
        self._is_error = False
        self._speak_state = "idle"

    # ---------- 流式写入 ----------
    def append_reasoning(self, text: str) -> None:
        self.reasoning_text += text
        self.view._send("reasoning", {"id": self.msg_id, "text": text})

    def append_content(self, text: str) -> None:
        self.body_text += text
        self.view._send("content", {"id": self.msg_id, "text": text})

    def add_note(self, note: str) -> None:
        self._notes.append(note)
        self.view._send("note", {"id": self.msg_id, "text": note})

    # ---------- 收尾 ----------
    def finalize(self, *, citations=None, footer: str = "", cost_text: str = "") -> None:
        self._finished = True
        self.view._send(
            "assistant_end",
            {
                "id": self.msg_id,
                "content": self.body_text,
                "reasoning": self.reasoning_text,
                "notes": self._notes,
                "citations": citations or [],
                "footer": footer,
                "cost": cost_text,
                "regen": True,
                "error": False,
            },
        )
        self.view._on_block_finished(self)

    def finish_reasoning(self) -> None:
        pass

    def toggle_reasoning(self) -> None:
        pass

    def render_citations(self, citations) -> None:
        pass

    def set_error(self, message: str) -> None:
        self._finished = True
        self._is_error = True
        self.view._send("error", {"id": self.msg_id, "text": message})

    # ---------- 朗读 ----------
    def speak_text(self) -> str:
        if self._is_error:
            return ""
        return (self.body_text or "").strip()

    def on_speak_click(self) -> None:
        if self.view.on_speak:
            self.view.on_speak(self)

    def on_regen_click(self) -> None:
        if self.view.on_regenerate:
            self.view.on_regenerate()

    def set_regenerate(self, show: bool) -> None:
        pass

    def set_speak_state(self, state: str) -> None:
        self._speak_state = state
        self.view._send("speak_state", {"id": self.msg_id, "state": state})

    @property
    def speak_state(self) -> str:
        return self._speak_state


class WebChatView(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_speak=None,
        on_stop_speak=None,
        on_edit_user=None,
        on_copy_user=None,
        on_regenerate=None,
        on_delete_msg=None,
        on_show_sources=None,
    ) -> None:
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self.on_speak = on_speak
        self.on_stop_speak = on_stop_speak
        self.on_edit_user = on_edit_user
        self.on_copy_user = on_copy_user
        self.on_regenerate = on_regenerate
        self.on_delete_msg = on_delete_msg
        self.on_show_sources = on_show_sources

        self.zoom = 1.0
        self._msg_id = 0
        self._wv: wv2.WebView | None = None
        self._html_ready = False
        self._visible = True
        self._pending: list[str] = []
        self._blocks: dict = {}
        self._last_assistant: WebAssistantBlock | None = None
        self._full_msgs: list[dict] = []
        self._full_model = "deepseek-flash"
        self._cny_rate = 7.10
        self._init_failed = False

        self.bind("<Configure>", self._on_resize)
        self.bind("<Destroy>", lambda _e: self.shutdown())
        self.after(80, self._init_webview)
        self.after(40, self._poll)

    # ------------------------------------------------------------------ 初始化
    def _init_webview(self) -> None:
        try:
            top = self.winfo_toplevel()
            parent = top.winfo_id()
        except Exception:
            self._init_failed = True
            return
        try:
            udf = str(data_dir() / "webview2")
            self._wv = wv2.WebView(
                parent,
                user_data_folder=udf,
                on_ready=self._on_wv_ready,
                on_message=self._on_wv_message,
                on_error=self._on_wv_error,
            )
        except RuntimeError as exc:
            self._init_failed = True
            self._show_fallback(str(exc))

    def _on_wv_ready(self) -> None:
        if self._wv:
            self._wv.navigate_html(CHAT_HTML)
            if self._visible:
                self._sync_bounds()
                self._wv.set_visible(True)
            else:
                self._wv.set_visible(False)
            if self.zoom != 1.0:
                try:
                    self._wv.set_zoom(float(self.zoom))
                except Exception:
                    pass

    def _on_wv_error(self, message: str) -> None:
        self._init_failed = True
        self._show_fallback(message)

    def _show_fallback(self, message: str) -> None:
        """WebView2 不可用时，在占位区显示一条提示。"""
        for child in self.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self,
            text=f"对话渲染组件不可用：{message}\n\n请确认系统已安装 Microsoft Edge WebView2 Runtime。",
            font=theme.ctk_font(12),
            text_color=C["danger"],
            justify="left",
            wraplength=560,
        ).pack(padx=26, pady=40, anchor="w")

    def _poll(self) -> None:
        if self._wv:
            try:
                self._wv.poll()
            except Exception:
                pass
        self.after(35, self._poll)

    # ------------------------------------------------------------------ 双向通信
    def _send(self, type_: str, data=None) -> None:
        msg = {"type": type_}
        if data is not None:
            msg["data"] = data
        s = json.dumps(msg, ensure_ascii=False)
        if self._html_ready and self._wv and not self._init_failed:
            self._wv.post_json(s)
        else:
            self._pending.append(s)

    def _flush(self) -> None:
        pending, self._pending = self._pending, []
        for s in pending:
            if self._wv and not self._init_failed:
                self._wv.post_json(s)

    def _on_wv_message(self, json_str: str) -> None:
        try:
            msg = json.loads(json_str)
        except (ValueError, TypeError):
            return
        t = msg.get("type")
        d = msg.get("data")
        if t == "web_ready":
            self._html_ready = True
            self._apply_theme()
            self._flush()
        elif t == "copy":
            self._copy_text(d)
        elif t == "copy_user":
            if self.on_copy_user:
                self.on_copy_user(d or "")
        elif t == "edit_user":
            if self.on_edit_user and isinstance(d, dict):
                self.on_edit_user(d.get("index"), d.get("text", ""))
        elif t == "delete_msg":
            if self.on_delete_msg and isinstance(d, dict):
                self.on_delete_msg(d.get("index"))
        elif t == "show_sources":
            if self.on_show_sources and isinstance(d, dict):
                self.on_show_sources(d.get("index"), d.get("note") or "")
        elif t == "speak":
            self._handle_speak(d)
        elif t == "regen":
            if self.on_regenerate:
                self.on_regenerate()
        elif t == "open_url":
            try:
                webbrowser.open(d)
            except Exception:
                pass
        elif t == "expand_history":
            self.render_history(self._full_msgs, model=self._full_model, cny_rate=getattr(self, "_cny_rate", 7.10))

    def _apply_theme(self) -> None:
        if self._wv:
            self._wv.post_json(json.dumps({"type": "theme", "data": {"dark": theme.is_dark()}}))

    def _copy_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _handle_speak(self, d) -> None:
        if not isinstance(d, dict):
            return
        mid = d.get("id")
        block = self._blocks.get(mid)
        if block is not None and self.on_speak:
            self.on_speak(block)

    # ------------------------------------------------------------------ 布局同步
    def _on_resize(self, _event=None) -> None:
        # 连续缩放时别堆积 after 任务，合并成一次
        if getattr(self, "_sync_job", None) is not None:
            return
        self._sync_job = self.after(25, self._run_sync)

    def _run_sync(self) -> None:
        self._sync_job = None
        self._sync_bounds()

    def _sync_bounds(self) -> None:
        if not self._wv or not self._wv.is_ready or not self._visible:
            return
        try:
            top = self.winfo_toplevel()
            x = self.winfo_rootx() - top.winfo_rootx()
            y = self.winfo_rooty() - top.winfo_rooty()
            w = max(1, self.winfo_width())
            h = max(1, self.winfo_height())
            self._wv.set_bounds(x, y, w, h)
        except Exception:
            pass

    def set_visible(self, visible: bool) -> None:
        """欢迎页时隐藏 WebView2（它是独立子窗口，不隐藏会盖住居中的欢迎语）。"""
        self._visible = bool(visible)
        if not self._wv:
            return
        try:
            self._wv.set_visible(self._visible)
            if self._visible:
                self._sync_bounds()
        except Exception:
            pass

    def refresh_bounds(self) -> None:
        """重新显示后立刻按当前控件位置同步一次，避免残留旧尺寸。"""
        self.after(0, self._sync_bounds)
        self.after(60, self._sync_bounds)

    # ------------------------------------------------------------------ 对外接口（兼容旧 ChatView）
    def show_welcome(self) -> None:
        self._send("welcome")

    def clear(self) -> None:
        if self.on_stop_speak:
            self.on_stop_speak()
        self._blocks.clear()
        self._last_assistant = None
        self._send("clear")

    def add_user(self, content, *, attachments=None, msg_index=None, quotes=None) -> None:
        text = content if isinstance(content, str) else _content_text(content)
        files = [{"name": a.get("name"), "file_id": a.get("file_id")} for a in (attachments or [])]
        self._send("user", {
            "id": "u" + str(self._msg_id), "text": text, "files": files,
            "quotes": quotes or [], "index": msg_index,
        })

    def add_assistant(self, *, model: str = "deepseek-flash", timestamp=None, index=None) -> WebAssistantBlock:
        self._msg_id += 1
        mid = "a" + str(self._msg_id)
        payload = {"id": mid, "model": model, "time": _clock(timestamp)}
        if index is not None:
            payload["index"] = index
        self._send("assistant_begin", payload)
        block = WebAssistantBlock(self, mid, model)
        self._blocks[mid] = block
        self._last_assistant = block
        return block

    def _on_block_finished(self, block: WebAssistantBlock) -> None:
        self._last_assistant = block

    def add_notice(self, text: str) -> None:
        self._send("notice", {"text": text})

    def render_history(self, messages, *, model: str = "deepseek-flash", show_all: bool = False, cny_rate: float = 7.10) -> None:
        self._full_msgs = list(messages)
        self._full_model = model
        self._cny_rate = cny_rate
        self._blocks.clear()
        self._last_assistant = None
        msgs: list[dict] = []
        for idx, m in enumerate(messages):
            role = m.get("role")
            if role == "user":
                content = m.get("content")
                files = []
                if isinstance(content, list):
                    files = [
                        {"name": p.get("file_id"), "file_id": p.get("file_id")}
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "file"
                    ]
                    content = "\n".join(
                        str(p.get("text") or "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                msgs.append({
                    "role": "user", "content": content or "", "files": files,
                    "quotes": m.get("_quotes") or [], "index": idx,
                })
            elif role == "assistant":
                content = _content_text(m.get("content"))
                reasoning = str(m.get("reasoning_content") or "")
                notes = m.get("_notes") or []
                citations = m.get("_citations") or []
                sources = m.get("_sources") or []
                footer = ""
                cost = ""
                usage_raw = m.get("_usage")
                if usage_raw:
                    usage = Usage.from_dict(usage_raw)
                    footer = usage.summary()
                    cost = f"≈ {_money(usage.cost(model).cny(cny_rate))}"
                mid = "h" + str(idx)
                msgs.append(
                    {
                        "role": "assistant",
                        "model": model,
                        "time": _clock(m.get("_ts")),
                        "content": content,
                        "reasoning": reasoning,
                        "notes": notes,
                        "citations": citations,
                        "sources": sources,
                        "footer": footer,
                        "cost": cost,
                        "index": idx,
                    }
                )
                block = WebAssistantBlock(self, mid, model)
                block.body_text = content
                block.reasoning_text = reasoning
                block._finished = True
                self._blocks[mid] = block
            elif role == "system" and m.get("_kind") == "context":
                msgs.append({"role": "notice", "text": "（已注入网页/搜索上下文）"})
        self._send("history", {"messages": msgs})

    def set_zoom(self, zoom: float) -> None:
        self.zoom = zoom
        if self._wv and self._wv.is_ready:
            try:
                self._wv.set_zoom(float(zoom))
            except Exception:
                pass

    def scroll_to_end(self) -> None:
        self._send("scroll_end")

    # ------------------------------------------------------------------ 关闭
    def shutdown(self) -> None:
        if self._wv:
            try:
                self._wv.close()
            except Exception:
                pass
            self._wv = None
