"""聊天区：消息气泡、流式追加、思考过程折叠、引用列表。

渲染策略：
- 用户消息：右对齐淡蓝气泡，用 Label 自动换行（宽度随窗口变化）；
- 助手消息：整宽文本块，流式时逐字 append（纯文本，开销小），
  结束后整段重新按 Markdown 渲染一次（有样式，且只渲染一次）。
"""

from __future__ import annotations

import time
import tkinter as tk

import customtkinter as ctk

from . import theme
from .mdtext import AutoText

C = theme.COLORS
MAX_RENDER = 20          # 历史最多直接渲染的消息条数，超出折叠


def _clock(ts: float | None = None) -> str:
    return time.strftime("%H:%M", time.localtime(ts or time.time()))


class AssistantBlock:
    """一条助手消息。流式期间可增量写入，结束后统一排版。"""

    def __init__(self, view: "ChatView", *, model: str = "deepseek-flash", timestamp: float | None = None) -> None:
        self.view = view
        self.reasoning_text = ""
        self.body_text = ""
        self._reason_open = True
        self._finished = False

        self.outer = ctk.CTkFrame(view, fg_color="transparent")
        self.outer.pack(fill="x", padx=26, pady=(4, 16))

        header = ctk.CTkFrame(self.outer, fg_color="transparent")
        header.pack(fill="x")
        self.name_label = ctk.CTkLabel(
            header,
            text="DeepSeek",
            font=theme.ctk_font(12, "bold"),
            text_color=C["accent"],
        )
        self.name_label.pack(side="left")
        self.meta_label = ctk.CTkLabel(
            header,
            text=f"{model} · {_clock(timestamp)}",
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
        )
        self.meta_label.pack(side="left", padx=(8, 0))
        self.copy_btn = ctk.CTkButton(
            header,
            text="复制",
            width=44,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            text_color=C["text_dim"],
            font=theme.ctk_font(11),
            command=self.copy,
        )
        self.copy_btn.pack(side="right")
        self.regen_btn = ctk.CTkButton(
            header,
            text="重新生成",
            width=72,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            text_color=C["text_dim"],
            font=theme.ctk_font(11),
            command=self.on_regen_click,
        )
        self._regen_shown = False
        self.speak_btn = ctk.CTkButton(
            header,
            text="朗读",
            width=62,
            height=22,
            corner_radius=6,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            text_color=C["text_dim"],
            font=theme.ctk_font(11),
            command=self.on_speak_click,
        )
        self._speak_state = "idle"
        self._speak_shown = False
        self._is_error = False

        # 思考过程（可折叠）
        self.reason_wrap = ctk.CTkFrame(self.outer, fg_color="transparent")
        self.reason_toggle = ctk.CTkButton(
            self.reason_wrap,
            text="▾ 思考过程",
            anchor="w",
            height=22,
            width=120,
            corner_radius=6,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            text_color=C["thinking_text"],
            font=theme.ctk_font(11),
            command=self.toggle_reasoning,
        )
        self.reason_toggle.pack(anchor="w", pady=(4, 0))
        self.reason_box = ctk.CTkFrame(self.reason_wrap, fg_color=C["thinking_bg"], corner_radius=8, border_width=1, border_color=C["border_soft"])
        self.reason_box.pack(fill="x", pady=(2, 6))
        self.reason_text = AutoText(
            self.reason_box,
            font_size=12,
            fg=C["thinking_text"],
            bg=C["thinking_bg"],
            max_lines=18,
            padx=10,
            pady=8,
            zoom=self.view.zoom,
        )
        self.reason_text.pack(fill="x")
        self.view._register_zoom_text(self.reason_text)

        # 正文
        self.body = AutoText(self.outer, font_size=13, bg=C["bg"], max_lines=200, zoom=self.view.zoom)
        self.body.pack(fill="x", pady=(6, 0))
        self.view._register_zoom_text(self.body)

        # 联网动作 / 引用
        self.notes_label = ctk.CTkLabel(
            self.outer,
            text="",
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
            justify="left",
            anchor="w",
            wraplength=640,
        )
        self.cites_frame = ctk.CTkFrame(self.outer, fg_color="transparent")

        # 费用徽标：浅色底 + 左侧 token 明细 + 右侧金额
        self.footer_bar = ctk.CTkFrame(self.outer, fg_color=C["accent_soft"], corner_radius=8)
        self.footer = ctk.CTkLabel(
            self.footer_bar,
            text="",
            font=theme.ctk_font(11),
            text_color=C["text_soft"],
            anchor="w",
            justify="left",
        )
        self.cost_label = ctk.CTkLabel(
            self.footer_bar,
            text="",
            font=theme.ctk_font(11, "bold"),
            text_color=C["accent"],
            anchor="e",
        )
        self.footer.pack(side="left", padx=(12, 6), pady=6)
        self.cost_label.pack(side="right", padx=(6, 12), pady=6)
        self._footer_shown = False

    # ---------- 流式写入 ----------
    def append_reasoning(self, text: str) -> None:
        self.reasoning_text += text
        if not self.reason_wrap.winfo_ismapped():
            self.reason_wrap.pack(fill="x", before=self.body)
        self.reason_toggle.configure(text=f"▾ 思考过程 · {len(self.reasoning_text)} 字（进行中）")
        self.reason_text.append(text, "dim")
        self.view.query_scroll()

    def append_content(self, text: str) -> None:
        self.body_text += text
        self.body.append(text)
        self.view.query_scroll()

    def add_note(self, note: str) -> None:
        current = self.notes_label.cget("text")
        lines = [ln for ln in current.split("\n") if ln] + [note]
        self.notes_label.configure(text="\n".join(lines))
        if not self.notes_label.winfo_ismapped():
            self.notes_label.pack(fill="x", pady=(4, 0))

    # ---------- 收尾 ----------
    def finalize(self, *, citations: list[dict] | None = None, footer: str = "", cost_text: str = "") -> None:
        self._finished = True
        if self.body_text.strip():
            self._show_speak_button()
        if self.body_text.strip():
            self.body.set_markdown(self.body_text)
        elif not self.body_text:
            self.body.set_plain("（没有返回内容）", "dim")
        self.finish_reasoning()
        if citations:
            self.render_citations(citations)
        if footer or cost_text:
            self.footer.configure(text=footer)
            self.cost_label.configure(text=cost_text)
            if not self._footer_shown:
                self.footer_bar.pack(fill="x", pady=(8, 0))
                self._footer_shown = True
        self.view._on_block_finished(self)
        self.view.scroll_to_end()

    def finish_reasoning(self) -> None:
        if not self.reasoning_text:
            self.reason_wrap.pack_forget()
            return
        self.reason_toggle.configure(text=f"▸ 思考过程 · {len(self.reasoning_text)} 字")
        if self.body_text.strip():
            self._reason_open = False
            self.reason_box.pack_forget()

    def toggle_reasoning(self) -> None:
        self._reason_open = not self._reason_open
        if self._reason_open:
            self.reason_box.pack(fill="x", pady=(2, 6))
            self.reason_toggle.configure(text=f"▾ 思考过程 · {len(self.reasoning_text)} 字")
        else:
            self.reason_box.pack_forget()
            self.reason_toggle.configure(text=f"▸ 思考过程 · {len(self.reasoning_text)} 字")

    def render_citations(self, citations: list[dict]) -> None:
        seen: set[str] = set()
        rows: list[tuple[str, str]] = []
        for cite in citations:
            url = str(cite.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append((str(cite.get("title") or url), url))
        if not rows:
            return
        for widget in self.cites_frame.winfo_children():
            widget.destroy()
        self.cites_frame.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(
            self.cites_frame,
            text="参考来源",
            font=theme.ctk_font(11, "bold"),
            text_color=C["text_soft"],
            anchor="w",
        ).pack(fill="x")
        for idx, (title, url) in enumerate(rows, 1):
            row = ctk.CTkFrame(self.cites_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(row, text=f"{idx}.", width=18, font=theme.ctk_font(11), text_color=C["text_dim"]).pack(side="left")
            link = ctk.CTkLabel(
                row,
                text=title if len(title) <= 52 else title[:52] + "…",
                font=theme.ctk_font(11),
                text_color=C["accent"],
                cursor="hand2",
                anchor="w",
            )
            link.pack(side="left")
            link.bind("<Button-1>", lambda _e, u=url: _open(u))
            ctk.CTkLabel(row, text=url[:64], font=theme.ctk_font(10), text_color=C["text_dim"]).pack(side="left", padx=(8, 0))

    def set_error(self, message: str) -> None:
        self._finished = True
        self._is_error = True
        self.hide_speak_button()
        self.body.set_plain(message, "dim")
        self.body.configure(fg=C["danger"])
        self.finish_reasoning()

    # ---------- 朗读 ----------
    def speak_text(self) -> str:
        """要朗读的原始 Markdown（清洗交给 dskit.tts.prepare_text）。"""
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
        if show and not self._regen_shown:
            self._regen_shown = True
            self.regen_btn.pack(side="right", padx=(0, 2))
        elif not show and self._regen_shown:
            self._regen_shown = False
            self.regen_btn.pack_forget()

    def _show_speak_button(self) -> None:
        if self._speak_shown:
            return
        self._speak_shown = True
        self.speak_btn.pack(side="right", padx=(0, 2))

    def hide_speak_button(self) -> None:
        if self._speak_shown:
            self.speak_btn.pack_forget()
            self._speak_shown = False

    def set_speak_state(self, state: str) -> None:
        self._speak_state = state
        if state == "loading":
            self.speak_btn.configure(text="合成中…", text_color=C["text_dim"], width=68)
        elif state == "playing":
            self.speak_btn.configure(text="■ 停止", text_color=C["accent"], width=62)
        else:
            self.speak_btn.configure(text="朗读", text_color=C["text_dim"], width=62)

    @property
    def speak_state(self) -> str:
        return self._speak_state

    # ---------- 其它 ----------
    def copy(self) -> None:
        text = self.body_text or self.body.all_text()
        if not text:
            return
        self.view.clipboard_clear()
        self.view.clipboard_append(text)
        self.copy_btn.configure(text="已复制")
        self.view.after(1200, lambda: self.copy_btn.configure(text="复制"))

    def restore(self, msg: dict) -> None:
        """把历史里的 assistant 消息渲染出来（不流式）。"""
        self.reasoning_text = str(msg.get("reasoning_content") or "")
        self.body_text = _content_text(msg.get("content"))
        if self.body_text.strip():
            self._show_speak_button()
        if self.reasoning_text:
            self.reason_wrap.pack(fill="x", before=self.body)
            self.reason_toggle.configure(text=f"▸ 思考过程 · {len(self.reasoning_text)} 字")
            self.reason_text.set_plain(self.reasoning_text, "dim")
            self._reason_open = False
            self.reason_box.pack_forget()
        else:
            self.reason_wrap.pack_forget()
        self.body.set_markdown(self.body_text)
        notes = msg.get("_notes") or []
        if notes:
            self.notes_label.configure(text="\n".join(str(n) for n in notes))
            self.notes_label.pack(fill="x", pady=(4, 0))
        if msg.get("_citations"):
            self.render_citations(msg["_citations"])
        self._finished = True


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


def _open(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:
        pass


class ChatView(ctk.CTkScrollableFrame):
    def __init__(
        self,
        master,
        *,
        on_speak=None,
        on_stop_speak=None,
        on_edit_user=None,
        on_copy_user=None,
        on_regenerate=None,
    ) -> None:
        super().__init__(
            master,
            fg_color=C["bg"],
            corner_radius=0,
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["text_dim"],
        )
        self.on_speak = on_speak
        self.on_stop_speak = on_stop_speak
        self.on_edit_user = on_edit_user
        self.on_copy_user = on_copy_user
        self.on_regenerate = on_regenerate
        self._last_assistant: AssistantBlock | None = None
        self.zoom = 1.0
        self._zoom_texts: list[AutoText] = []
        self._zoom_labels: list[tuple[ctk.CTkLabel, int]] = []
        self._full_msgs: list[dict] = []
        self._full_model = "deepseek-flash"
        # 滚轮每格滚 3 个增量（默认 1 太慢）
        self._parent_canvas.configure(yscrollincrement=3)
        self._user_labels: list[ctk.CTkLabel] = []
        self._welcome: ctk.CTkFrame | None = None
        self._scroll_job: str | None = None
        self._stick_bottom = True
        self.bind("<Configure>", self._on_resize)
        self.winfo_toplevel().bind("<MouseWheel>", self._on_wheel, add="+")
        # 顶部留白，首条消息不贴边
        ctk.CTkFrame(self, fg_color="transparent", height=6).pack(fill="x")

    # ---------- 滚动 ----------
    def _on_wheel(self, _event) -> None:
        self._stick_bottom = self._at_bottom()

    def _at_bottom(self) -> bool:
        try:
            return self._parent_canvas.yview()[1] >= 0.995
        except Exception:
            return True

    def query_scroll(self) -> None:
        """流式追加后调用：只有原本贴着底部才自动跟随，避免抢用户滚动。"""
        if self._stick_bottom:
            self.scroll_to_end()

    def scroll_to_end(self) -> None:
        if self._scroll_job is not None:
            return
        self._scroll_job = self.after(40, self._do_scroll)

    def _refresh_scrollregion(self) -> None:
        """内容高度变化后强制刷新 canvas 滚动区域（缩放/追加消息后必调）。"""
        try:
            self.update_idletasks()
            self._parent_canvas.configure(scrollregion=self._parent_canvas.bbox("all"))
        except Exception:
            pass

    def _refresh_scrollregion_idle(self) -> None:
        self.after_idle(self._refresh_scrollregion)

    def _do_scroll(self) -> None:
        self._scroll_job = None
        try:
            self.update_idletasks()
            self._parent_canvas.yview_moveto(1.0)
            self._stick_bottom = True
        except Exception:
            pass

    # ---------- 布局响应 ----------
    def _on_resize(self, _event=None) -> None:
        wrap = max(260, int(self.winfo_width() * 0.68))
        for label in self._user_labels:
            try:
                label.configure(wraplength=wrap)
            except tk.TclError:
                pass

    # ---------- 内容 ----------
    def clear(self) -> None:
        if self.on_stop_speak:
            self.on_stop_speak()
        for child in self.winfo_children():
            child.destroy()
        self._user_labels.clear()
        self._welcome = None
        self._last_assistant = None
        self._zoom_texts.clear()
        self._zoom_labels.clear()

    # ---------- 缩放 ----------
    def _register_zoom_text(self, widget: AutoText) -> None:
        self._zoom_texts.append(widget)

    def _register_zoom_label(self, label: ctk.CTkLabel, base: int) -> None:
        self._zoom_labels.append((label, base))

    def set_zoom(self, zoom: float) -> None:
        self.zoom = zoom
        try:
            top = self._parent_canvas.yview()[0]
        except Exception:
            top = 0.0
        for widget in self._zoom_texts:
            try:
                widget.set_zoom(zoom)
            except Exception:
                pass
        for label, base in self._zoom_labels:
            try:
                label.configure(font=theme.ctk_font(round(base * zoom)))
            except Exception:
                pass
        # 等 AutoText 重新计算完高度后，刷新滚动区域并尽量回到原位置
        def _after_zoom() -> None:
            self._refresh_scrollregion()
            try:
                self._parent_canvas.yview_moveto(top)
            except Exception:
                pass

        self.after(90, _after_zoom)

    def show_welcome(self) -> None:
        self.clear()
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, pady=(90, 0))
        self._welcome = wrap
        ctk.CTkLabel(wrap, text="有什么可以帮你？", font=theme.ctk_font(28, "bold"), text_color=C["text"]).pack(anchor="w", padx=26)
        ctk.CTkLabel(
            wrap,
            text="在下方输入框提问，开始与 DeepSeek 对话。",
            font=theme.ctk_font(14),
            text_color=C["text_dim"],
        ).pack(anchor="w", padx=28, pady=(10, 0))

    def add_user(self, content, *, attachments: list[dict] | None = None, msg_index: int | None = None) -> None:
        self._dismiss_welcome()
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=26, pady=(10, 6))
        bubble = ctk.CTkFrame(
            row,
            fg_color=C["user_bubble"],
            corner_radius=14,
            border_width=1,
            border_color=C["user_bubble_border"],
        )
        bubble.pack(side="right", anchor="e")

        text = content if isinstance(content, str) else _content_text(content)

        # 气泡左侧的操作：复制 / 编辑（小号幽灵按钮）
        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.pack(side="right", anchor="e", padx=(0, 8))
        if self.on_copy_user is not None:
            ctk.CTkButton(
                actions,
                text="复制",
                width=44,
                height=20,
                corner_radius=6,
                fg_color="transparent",
                hover_color=C["sidebar_hover"],
                text_color=C["text_dim"],
                font=theme.ctk_font(10),
                command=lambda t=text: self.on_copy_user(t),
            ).pack(side="left")
        if self.on_edit_user is not None:
            ctk.CTkButton(
                actions,
                text="✎ 编辑",
                width=52,
                height=20,
                corner_radius=6,
                fg_color="transparent",
                hover_color=C["sidebar_hover"],
                text_color=C["text_dim"],
                font=theme.ctk_font(10),
                command=lambda i=msg_index, t=text: self.on_edit_user(i, t),
            ).pack(side="left", padx=(4, 0))

        label = ctk.CTkLabel(
            bubble,
            text=text,
            font=theme.ctk_font(round(13 * self.zoom)),
            text_color=C["text"],
            justify="left",
            wraplength=max(260, int(self.winfo_width() * 0.68)),
            anchor="w",
        )
        label.pack(padx=14, pady=(9, 4) if attachments else (9, 9), anchor="w")
        self._user_labels.append(label)
        self._register_zoom_label(label, 13)

        for item in attachments or []:
            ctk.CTkLabel(
                bubble,
                text=f"📎 {item.get('name') or item.get('file_id')}",
                font=theme.ctk_font(11),
                text_color=C["text_soft"],
                anchor="w",
            ).pack(padx=14, pady=(0, 8), anchor="w")
        self.scroll_to_end()
        self._refresh_scrollregion_idle()

    def add_assistant(self, *, model: str = "deepseek-flash", timestamp: float | None = None) -> AssistantBlock:
        self._dismiss_welcome()
        block = AssistantBlock(self, model=model, timestamp=timestamp)
        self._set_last_assistant(block)
        self.scroll_to_end()
        self._refresh_scrollregion_idle()
        return block

    def _set_last_assistant(self, block: "AssistantBlock") -> None:
        if self._last_assistant is not None and self._last_assistant is not block:
            self._last_assistant.set_regenerate(False)
        self._last_assistant = block
        # 只在回答完成后才显示「重新生成」，流式生成中不显示
        block.set_regenerate(self.on_regenerate is not None and block._finished)

    def _on_block_finished(self, block: "AssistantBlock") -> None:
        if self._last_assistant is block and self.on_regenerate is not None:
            block.set_regenerate(True)
        self._refresh_scrollregion_idle()

    def add_notice(self, text: str) -> None:
        label = ctk.CTkLabel(
            self,
            text=text,
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
            justify="left",
            anchor="w",
        )
        label.pack(fill="x", padx=28, pady=(0, 10))

    def render_history(self, messages: list[dict], *, model: str = "deepseek-flash", show_all: bool = False) -> None:
        self._full_msgs = list(messages)
        self._full_model = model
        self.clear()
        AutoText._bulk_mode = True

        # 超长历史折叠：只渲染最近 MAX_RENDER 条，避免几百个控件拖垮界面
        hidden = 0
        visible = messages
        if not show_all and len(messages) > MAX_RENDER:
            hidden = len(messages) - MAX_RENDER
            self._add_collapse_notice(hidden)
            visible = messages[hidden:]

        last_assistant: AssistantBlock | None = None
        for idx, msg in enumerate(visible, start=hidden):
            role = msg.get("role")
            if role == "user":
                files = []
                content = msg.get("content")
                if isinstance(content, list):
                    files = [
                        {"name": p.get("file_id"), "file_id": p.get("file_id")}
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "file"
                    ]
                    content = "\n".join(
                        str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                    )
                self.add_user(content, attachments=files, msg_index=idx)
            elif role == "assistant":
                block = AssistantBlock(self, model=model, timestamp=msg.get("_ts"))
                block.restore(msg)
                last_assistant = block
            elif role == "system" and msg.get("_kind") == "context":
                self.add_notice("（已注入网页/搜索上下文）")
        if last_assistant is not None:
            self._set_last_assistant(last_assistant)
        AutoText._bulk_mode = False
        # 布局完成后统一算高度：displaylines 在未布局时很慢，布局后很快
        self.update_idletasks()
        for widget in self._zoom_texts:
            try:
                widget.autosize_now()
            except Exception:
                pass
        self.scroll_to_end()
        self._refresh_scrollregion_idle()

    def _add_collapse_notice(self, hidden: int) -> None:
        ctk.CTkButton(
            self,
            text=f"已折叠更早的 {hidden} 条消息 · 点击展开（展开较多消息可能需要几秒）",
            height=34,
            corner_radius=8,
            fg_color=C["surface_soft"],
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(11),
            command=self._expand_history,
        ).pack(fill="x", padx=26, pady=(10, 6))

    def _expand_history(self) -> None:
        self.render_history(self._full_msgs, model=self._full_model, show_all=True)

    def _dismiss_welcome(self) -> None:
        if self._welcome is not None:
            self._welcome.destroy()
            self._welcome = None
