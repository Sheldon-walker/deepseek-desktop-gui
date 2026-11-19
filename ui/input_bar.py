"""底部输入区：多行输入、附件、模型/思考/联网开关、发送/停止。"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from dskit.config import AVAILABLE_MODELS

from . import icons as ic
from . import theme
from .widgets import CapsuleToggle, HoldButton

C = theme.COLORS

PLACEHOLDER = "给 DeepSeek 发送消息"


class AttachmentChip(ctk.CTkFrame):
    def __init__(self, master, ref, on_remove) -> None:
        super().__init__(master, fg_color=C["card"], corner_radius=8, border_width=1, border_color=C["border_soft"])
        text = f"📎 {ref.filename}"
        if ref.chars:
            text += f"（{ref.chars} 字）"
        ctk.CTkLabel(self, text=text, font=theme.ctk_font(11), text_color=C["text_soft"]).pack(side="left", padx=(8, 4), pady=4)
        close = ctk.CTkButton(
            self,
            text="✕",
            width=18,
            height=18,
            corner_radius=9,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            text_color=C["text_dim"],
            font=theme.ctk_font(10),
            command=lambda: on_remove(ref),
        )
        close.pack(side="right", padx=(0, 4))


class InputBar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_send,
        on_stop,
        on_attach,
        on_remove_attach,
        on_rich_change,
        on_model_change=None,
        on_think_change=None,
        on_search_change=None,
        on_voice_press=None,
        on_voice_release=None,
        model: str = "deepseek-flash",
        thinking: bool = True,
        web_search: bool = False,
    ) -> None:
        super().__init__(master, fg_color=C["bg"], corner_radius=0)
        self._on_send = on_send
        self._busy = False
        self._placeholder_on = True
        self._silent = False
        self._grow_job = None
        self._last_height = 58

        # ---- 图标 ----
        self._think_on, self._think_off = ic.think()
        self._search_on, self._search_off = ic.search()
        self._mic_img = ic.microphone()
        self._clip_img = ic.paperclip()
        self._send_disabled_img, self._send_active_img = ic.send()

        # ---- 附件行 ----
        self.attach_row = ctk.CTkFrame(self, fg_color="transparent")
        self._chips: list[AttachmentChip] = []
        self.on_remove_attach = on_remove_attach

        # ---- 输入框（大圆角胶囊） ----
        box = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=20, border_width=1, border_color=C["border"])
        box.pack(fill="x", padx=22, pady=(2, 0))
        self.box = box

        self.text = ctk.CTkTextbox(
            box,
            height=58,
            corner_radius=0,
            border_width=0,
            fg_color="transparent",
            text_color=C["text_dim"],
            font=theme.ctk_font(13),
            activate_scrollbars=False,
            wrap="word",
        )
        self.text.pack(fill="x", padx=14, pady=(10, 0))
        self.text.insert("1.0", PLACEHOLDER)
        self.text.bind("<Key>", self._on_key)
        self.text.bind("<FocusOut>", self._restore_placeholder)
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<Shift-Return>", lambda _e: None)
        self.text.bind("<Control-Return>", self._on_ctrl_return)
        self.text.bind("<KeyRelease>", self._autogrow)
        # 中文输入法上屏 / 粘贴 / 右键粘贴都不一定走 <Key>，用 <<Modified>> 兜底
        try:
            self.text._textbox.edit_modified(False)
            self.text._textbox.bind("<<Modified>>", self._on_modified, add="+")
        except Exception:
            pass

        # ---- 工具行（输入框内部底部） ----
        bar = ctk.CTkFrame(box, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(2, 8))

        self.think_toggle = CapsuleToggle(
            bar, "深度思考", value=thinking, command=on_think_change, height=28,
            on_image=self._think_on, off_image=self._think_off,
        )
        self.think_toggle.pack(side="left", padx=(0, 6))
        self.search_toggle = CapsuleToggle(
            bar, "联网", value=web_search, command=on_search_change, height=28,
            on_image=self._search_on, off_image=self._search_off,
        )
        self.search_toggle.pack(side="left", padx=(0, 6))

        self.model_menu = ctk.CTkOptionMenu(
            bar,
            values=list(AVAILABLE_MODELS),
            width=132,
            height=28,
            corner_radius=14,
            fg_color=C["card"],
            button_color=C["card"],
            button_hover_color=C["border"],
            text_color=C["text_soft"],
            dropdown_fg_color=C["surface"],
            dropdown_text_color=C["text"],
            dropdown_hover_color=C["sidebar_hover"],
            font=theme.ctk_font(11),
            command=on_model_change,
        )
        self.model_menu.set(model)
        self.model_menu.pack(side="left", padx=(0, 6))

        self.rich_var = tk.BooleanVar(value=False)
        self.rich_check = ctk.CTkCheckBox(
            bar,
            text="含图表识别",
            variable=self.rich_var,
            width=92,
            height=28,
            checkbox_width=15,
            checkbox_height=15,
            corner_radius=4,
            border_width=1,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(12),
            command=lambda: None if self._silent else on_rich_change(bool(self.rich_var.get())),
        )
        self.rich_check.pack(side="left", padx=(0, 6))

        self.hint = ctk.CTkLabel(
            bar,
            text="",
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
            anchor="w",
        )

        self.cost_label = ctk.CTkLabel(
            bar,
            text="",
            font=theme.ctk_font(10),
            text_color=C["text_dim"],
            anchor="e",
        )
        self.cost_label.pack(side="right", padx=(0, 10))

        self.actions = ctk.CTkFrame(bar, fg_color="transparent")
        self.actions.pack(side="right")

        self.voice_btn = HoldButton(
            self.actions,
            on_press=on_voice_press,
            on_release=on_voice_release,
            width=30,
            height=30,
            image=self._mic_img,
            border_width=0,
        )
        self.voice_btn.pack(side="left", padx=(0, 4))

        self.attach_btn = ctk.CTkButton(
            self.actions,
            text="",
            image=self._clip_img,
            width=30,
            height=30,
            corner_radius=15,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            border_width=0,
            command=on_attach,
        )
        self.attach_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = ctk.CTkButton(
            self.actions,
            text="停止",
            width=56,
            height=30,
            corner_radius=15,
            fg_color="transparent",
            hover_color=C["danger_soft"],
            border_width=1,
            border_color=C["danger"],
            text_color=C["danger"],
            font=theme.ctk_font(12, "bold"),
            command=on_stop,
        )
        self.send_btn = ctk.CTkButton(
            self.actions,
            text="",
            image=self._send_disabled_img,
            width=36,
            height=36,
            corner_radius=18,
            fg_color="transparent",
            hover_color=C["card"],
            border_width=0,
            command=self._submit,
        )
        self.send_btn.pack(side="right")

        # 提示文字最后 pack：宽度不足时（比如右侧检索栏展开）优先压缩它，
        # 而不是把右侧按钮挤到看不见。
        self.hint.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self._update_send_state()
        self._rich_visible = True
        self.bind("<Configure>", self._on_width_change, add="+")

    def _on_width_change(self, _event=None) -> None:
        """窄的时候（比如右侧检索栏拉得很大）先收起「含图表识别」，别把按钮挤没。"""
        try:
            width = self.winfo_width() / max(1.0, float(self._get_widget_scaling()))
        except Exception:
            return
        show = width >= 700
        if show == self._rich_visible:
            return
        self._rich_visible = show
        try:
            if show:
                self.rich_check.pack(side="left", padx=(0, 6), before=self.hint)
            else:
                self.rich_check.pack_forget()
        except Exception:
            pass

    # ---------- 占位符 ----------
    def _clear_placeholder(self, _event=None) -> None:
        """只抹掉开头那段占位符，别把用户刚输入/粘贴的内容一起删掉。"""
        if not self._placeholder_on:
            return
        self._placeholder_on = False
        try:
            self.text.configure(text_color=C["text"])
            current = self.text.get("1.0", "end")
            offset = current.find(PLACEHOLDER)
            if offset >= 0:
                self.text.delete(f"1.0 + {offset}c", f"1.0 + {offset + len(PLACEHOLDER)}c")
        except Exception:
            pass

    def _on_key(self, _event=None) -> None:
        # 第一次按键才清掉占位符：这样发完消息后还能看到输入提示
        if self._placeholder_on:
            self._clear_placeholder()
        self._update_send_state()

    def _on_modified(self, _event=None) -> None:
        """任何改动都要走这里：中文输入法上屏、粘贴不一定触发 <Key>，
        只靠 <Key> 清占位符会导致"打上去的字被当成占位符"，回车也发不出去。"""
        tb = self.text._textbox
        try:
            if not tb.edit_modified():
                return
            tb.edit_modified(False)
        except Exception:
            return
        if self._placeholder_on and tb.get("1.0", "end").strip() not in ("", PLACEHOLDER.strip()):
            self._clear_placeholder()
        self._update_send_state()

    def _restore_placeholder(self, _event=None) -> None:
        if self._placeholder_on:
            return
        if not self.text.get("1.0", "end").strip():
            self.text.delete("1.0", "end")
            self.text.insert("1.0", PLACEHOLDER)
            self.text.configure(text_color=C["text_dim"])
            self._placeholder_on = True

    def _safe_focus(self) -> None:
        """聚焦输入框；重建主题后旧控件可能已销毁，这里容错。"""
        try:
            self.text.focus_set()
        except Exception:
            pass

    def _autogrow(self, _event=None) -> None:
        """把「按行数算高度」推迟到停手后再做。

        `count(displaylines)` 要按当前宽度重排整段文字，千字草稿要 30ms 左右，
        每次按键都算就会明显卡顿（打字掉帧），所以这里只排一次延时任务。
        """
        if self._grow_job is not None:
            try:
                self.after_cancel(self._grow_job)
            except Exception:
                self._grow_job = None
        self._grow_job = self.after(60, self._apply_autogrow)

    def _apply_autogrow(self) -> None:
        self._grow_job = None
        try:
            lines = int(self.text._textbox.count("1.0", "end", "displaylines")[0])
        except Exception:
            return
        lines = max(2, min(lines, 9))
        height = 22 * lines + 12
        if height != self._last_height:
            self._last_height = height
            try:
                self.text.configure(height=height)
            except Exception:
                pass
        self._update_send_state()

    # ---------- 发送 ----------
    def _on_return(self, event):
        if event.state & 0x0001:      # Shift 按下 → 换行
            return None
        self._submit()
        return "break"

    def _on_ctrl_return(self, _event=None):
        self._submit()
        return "break"

    def _submit(self) -> None:
        if self._busy:
            return
        text = self.text.get("1.0", "end").strip()
        if not text or text == PLACEHOLDER.strip():
            return
        self._on_send(text)

    def clear(self) -> None:
        self.text.delete("1.0", "end")
        self._placeholder_on = False
        self._restore_placeholder()
        self.text.configure(height=58)
        self._last_height = 58
        self._update_send_state()

    def set_text(self, text: str) -> None:
        self._clear_placeholder()
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self._safe_focus()
        self._autogrow()
        self._update_send_state()

    def get_text(self) -> str:
        text = self.text.get("1.0", "end").strip()
        if self._placeholder_on and text in ("", PLACEHOLDER.strip()):
            return ""
        return text

    def _update_send_state(self) -> None:
        """有内容可发时发送按钮深色，无内容时浅色。"""
        if self._busy:
            return
        current = self.text.get("1.0", "end").strip()
        has = bool(current) and current != PLACEHOLDER.strip()
        self.send_btn.configure(image=self._send_active_img if has else self._send_disabled_img)

    # ---------- 状态 ----------
    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.send_btn.pack_forget()
            self.stop_btn.pack(side="right")
            self.attach_btn.configure(state="disabled")
        else:
            self.stop_btn.pack_forget()
            self.send_btn.pack(side="right")
            self.attach_btn.configure(state="normal")

    def set_hint(self, text: str) -> None:
        self.hint.configure(text=text)

    def set_cost(self, text: str) -> None:
        self.cost_label.configure(text=text)

    def set_rich(self, value: bool) -> None:
        # 程序设置时不要触发回调，避免启动就把配置写一遍
        self._silent = True
        self.rich_var.set(value)
        self._silent = False

    # ---------- 语音 ----------
    def set_recording(self, active: bool, seconds: float = 0.0) -> None:
        if active:
            self.voice_btn.set_text(f"● {seconds:.1f}s")
            self.voice_btn.set_recording(True)
            self.set_hint("正在录音…松开发送，Esc 取消")
        else:
            self.voice_btn.show_idle()
            self.voice_btn.set_recording(False)

    def set_voice_busy(self, busy: bool) -> None:
        if busy:
            self.voice_btn.set_text("识别中…")
            self.voice_btn.set_enabled(False)
            self.set_hint("正在识别语音…")
        else:
            self.voice_btn.show_idle()
            self.voice_btn.set_enabled(True)

    def append_text(self, text: str) -> None:
        """把识别结果接到已有输入后面。"""
        text = (text or "").strip()
        if not text:
            return
        self._clear_placeholder()
        current = self.text.get("1.0", "end").strip()
        if current:
            self.text.insert("end", " " + text)
        else:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", text)
        self._safe_focus()
        self._autogrow()
        self._update_send_state()

    # ---------- 附件 ----------
    def show_quotes(self, quotes: list) -> None:
        """Tk 回退界面没有选区引用 UI，留空实现避免切换会话时报错。"""
        return

    def show_attachments(self, refs: list) -> None:
        for chip in self._chips:
            chip.destroy()
        self._chips.clear()
        if not refs:
            self.attach_row.pack_forget()
            self.set_hint("")
            return
        self.attach_row.pack(fill="x", padx=22, pady=(4, 0), before=self.box)
        for ref in refs:
            chip = AttachmentChip(self.attach_row, ref, self.on_remove_attach)
            chip.pack(side="left", padx=(0, 6))
            self._chips.append(chip)
        total = sum(getattr(r, "chars", 0) or 0 for r in refs)
        self.set_hint(f"已挂载 {len(refs)} 个文件" + (f"，本地预览 {total} 字" if total else ""))
