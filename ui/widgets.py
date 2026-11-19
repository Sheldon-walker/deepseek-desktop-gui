"""自绘小控件。

CTkSwitch 在当前 CustomTkinter 版本 + 自定义配色下画不出轨道，
这里用 Canvas 自己画一个，颜色、尺寸完全可控，行为也简单。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import theme

C = theme.COLORS


class ToggleSwitch(tk.Canvas):
    def __init__(
        self,
        master,
        *,
        value: bool = True,
        command=None,
        width: int = 38,
        height: int = 20,
        bg: str | None = None,
        on_color: str | None = None,
        off_color: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bd=0,
            highlightthickness=0,
            bg=bg or C["bg"],
            cursor="arrow" if disabled else "hand2",
        )
        self._tw = width
        self._th = height
        self._on = bool(value)
        self._command = command
        self._on_color = on_color or C["accent"]
        self._off_color = off_color or C["switch_off"]
        self._disabled = disabled
        if not disabled:
            self.bind("<Button-1>", self._toggle)
        self._draw()

    # ---------- 绘制 ----------
    def _draw(self) -> None:
        self.delete("all")
        radius = self._th / 2
        color = self._on_color if self._on else self._off_color
        if self._disabled:
            color = C["switch_disabled"]
        self.create_oval(0, 0, self._th, self._th, fill=color, outline=color)
        self.create_oval(self._tw - self._th, 0, self._tw, self._th, fill=color, outline=color)
        self.create_rectangle(radius, 0, self._tw - radius, self._th, fill=color, outline=color)
        pad = 3
        size = self._th - pad * 2
        x = self._tw - self._th + pad if self._on else pad
        self.create_oval(x, pad, x + size, pad + size, fill="#FFFFFF", outline="")

    # ---------- 行为 ----------
    def _toggle(self, _event=None) -> None:
        if self._disabled:
            return
        self._on = not self._on
        self._draw()
        if self._command:
            self._command(self._on)

    def get(self) -> bool:
        return self._on

    def set(self, value: bool) -> None:
        self._on = bool(value)
        self._draw()

    def set_bg(self, color: str) -> None:
        self.configure(bg=color)


class LabeledToggle(ctk.CTkFrame):
    """开关 + 文字，点文字也能切换。"""

    def __init__(
        self,
        master,
        text: str,
        *,
        value: bool = True,
        command=None,
        font_size: int = 11,
        text_color: str | None = None,
        bg: str | None = None,
    ) -> None:
        super().__init__(master, fg_color=bg or "transparent", corner_radius=0)
        self._command = command
        self.switch = ToggleSwitch(self, value=value, command=self._on_change, bg=bg or C["bg"])
        self.switch.pack(side="left", pady=1)
        self.label = ctk.CTkLabel(
            self,
            text=text,
            font=theme.ctk_font(font_size),
            text_color=text_color or C["text_soft"],
            cursor="hand2",
        )
        self.label.pack(side="left", padx=(7, 0))
        self.label.bind("<Button-1>", lambda _e: self.switch._toggle())

    def _on_change(self, value: bool) -> None:
        if self._command:
            self._command(value)

    def get(self) -> bool:
        return self.switch.get()

    def set(self, value: bool) -> None:
        self.switch.set(value)

    def set_bg(self, color: str) -> None:
        self.configure(fg_color=color)
        self.switch.set_bg(color)


def _capsule_width(master, font, text: str, *, has_image: bool) -> int:
    """估算胶囊按钮需要多宽：文字实测宽度 + 图标 + 内边距（逻辑单位）。"""
    text_len = len(text) * 13.0
    try:
        scale = 1.0
        get_scale = getattr(master, "_get_widget_scaling", None)
        if callable(get_scale):
            scale = max(1.0, float(get_scale()))
        text_len = float(font.measure(text)) / scale
    except Exception:
        pass
    extra = 24 + (22 if has_image else 0)
    return int(max(56, min(150, text_len + extra)))


class CapsuleToggle(ctk.CTkButton):
    """胶囊形开关按钮：激活时浅蓝底 + 蓝边 + 蓝字 + 蓝色图标，关闭时白底 + 灰边 + 深字 + 黑色图标。

    用于输入框里的「深度思考 / 联网」等轻量开关，样式接近官方输入框的胶囊按钮。
    """

    def __init__(
        self,
        master,
        text: str,
        *,
        value: bool = True,
        command=None,
        font_size: int = 12,
        height: int = 28,
        on_image=None,
        off_image=None,
    ) -> None:
        font = theme.ctk_font(font_size)
        # CTkButton 默认宽度 140，四个胶囊挤在一起会把输入栏撑得比窗口还宽，
        # 右侧的发送按钮就会被裁掉。这里按文字实际宽度算一个刚好合适的宽度。
        super().__init__(
            master,
            text=text,
            width=_capsule_width(master, font, text, has_image=bool(on_image or off_image)),
            height=height,
            corner_radius=height // 2,
            border_width=1,
            font=font,
            compound="left" if (on_image or off_image) else "top",
            command=self._toggle,
        )
        # 注意：CTkButton 内部用 self._command 保存点击回调，这里绝不能覆盖它，
        # 否则点击就不会再触发 _toggle。用户回调存到 _callback。
        self._callback = command
        self._on_image = on_image
        self._off_image = off_image
        self._value = bool(value)
        self._apply()

    def _toggle(self) -> None:
        self._value = not self._value
        self._apply()
        if self._callback:
            self._callback(self._value)

    def _apply(self) -> None:
        img = self._on_image if self._value else self._off_image
        if self._value:
            self.configure(
                fg_color=C["accent_soft"],
                hover_color=C["accent_soft"],
                border_color=C["accent"],
                text_color=C["accent"],
                image=img,
            )
        else:
            # 关闭：白底 + 浅灰边 + 深色文字
            self.configure(
                fg_color=C["surface"],
                hover_color=C["card"],
                border_color=C["border"],
                text_color=C["text"],
                image=img,
            )

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self._apply()


class HoldButton(ctk.CTkFrame):
    """按住说话按钮：按下触发 on_press，松开发 on_release。

    用 Frame + Label 自己拼，不走 CTkButton —— 需要在 press 阶段就开始录音，
    而 CTkButton 的 command 只在松开时触发。支持传图标（image），空闲态显示图标。
    """

    def __init__(
        self,
        master,
        text: str = "语音",
        *,
        on_press=None,
        on_release=None,
        width: int = 78,
        height: int = 28,
        image=None,
        border_width: int = 1,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            corner_radius=8,
            border_width=border_width,
            border_color=C["border"],
            fg_color="transparent",
        )
        self.pack_propagate(False)
        self._on_press = on_press
        self._on_release = on_release
        self._enabled = True
        self._pressed = False
        self._idle_image = image
        self.label = ctk.CTkLabel(
            self,
            text="" if image else text,
            image=image,
            font=theme.ctk_font(12),
            text_color=C["text_soft"],
        )
        self.label.pack(fill="both", expand=True)
        for widget in (self, self.label):
            widget.bind("<ButtonPress-1>", self._press)
            widget.bind("<ButtonRelease-1>", self._release)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)
        self.configure(cursor="hand2")
        self.label.configure(cursor="hand2")

    # ---------- 事件 ----------
    def _press(self, _event=None) -> None:
        if not self._enabled or self._pressed:
            return
        self._pressed = True
        if self._on_press:
            self._on_press()

    def _release(self, _event=None) -> None:
        if not self._pressed:
            return
        self._pressed = False
        if self._on_release and self._enabled:
            self._on_release()

    def _enter(self, _event=None) -> None:
        if self._enabled and not self._pressed:
            self.configure(fg_color=C["sidebar_hover"])

    def _leave(self, _event=None) -> None:
        if not self._pressed:
            self.configure(fg_color="transparent")

    # ---------- 状态 ----------
    def set_text(self, text: str) -> None:
        self.label.configure(text=text, image=None)

    def show_idle(self) -> None:
        self.label.configure(text="" if self._idle_image else "语音", image=self._idle_image)

    def set_recording(self, active: bool) -> None:
        if active:
            self.configure(fg_color=C["danger_soft"], border_color=C["danger"])
            self.label.configure(text_color=C["danger"])
        else:
            self.configure(fg_color="transparent", border_color=C["border"])
            self.label.configure(text_color=C["text_soft"])

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self.label.configure(cursor="hand2" if enabled else "arrow")
        self.label.configure(text_color=C["text_soft"] if enabled else C["text_dim"])
