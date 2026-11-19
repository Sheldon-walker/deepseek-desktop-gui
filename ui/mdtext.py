"""消息正文渲染：一个能自动伸缩高度的只读 Text，加一个轻量 Markdown 渲染器。

为什么用原生 tk.Text 而不是 CTkTextbox：
- 需要 tag 级样式（代码块底色、加粗、标题、引用灰字）；
- 需要按内容自动算高度，避免气泡里出现滚动条；
- 只读状态下仍可选中复制。
"""

from __future__ import annotations

import re
import tkinter as tk

from . import theme

INLINE_RE = re.compile(r"\*\*(?P<bold>.+?)\*\*|`(?P<code>[^`\n]+)`|\[(?P<text>[^\]]+)\]\((?P<url>[^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d+[.)])\s+(.*)$")
QUOTE_RE = re.compile(r"^>\s?(.*)$")
RULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _configure_tags(widget: tk.Text, *, base_size: int = 13) -> None:
    c = theme.COLORS
    widget.tag_configure("plain", foreground=c["text"])
    widget.tag_configure("bold", font=theme.font(base_size, "bold"))
    widget.tag_configure(
        "code",
        font=theme.font(base_size - 1, mono=True),
        background=c["code_bg"],
        foreground=c["code_fg"],
        lmargin1=10,
        lmargin2=10,
        rmargin=8,
    )
    widget.tag_configure("code_inline", font=theme.font(base_size - 1, mono=True), background=c["code_bg"], foreground=c["code_inline_fg"])
    widget.tag_configure("h1", font=theme.font(base_size + 4, "bold"), spacing1=8, spacing3=4)
    widget.tag_configure("h2", font=theme.font(base_size + 2, "bold"), spacing1=6, spacing3=3)
    widget.tag_configure("h3", font=theme.font(base_size + 1, "bold"), spacing1=4, spacing3=2)
    widget.tag_configure("li", lmargin1=14, lmargin2=26)
    widget.tag_configure("quote", foreground=c["text_soft"], lmargin1=14, lmargin2=14, font=theme.font(base_size, "italic"))
    widget.tag_configure("rule", foreground=c["border"])
    widget.tag_configure("link", foreground=c["accent"], underline=True)
    widget.tag_configure("dim", foreground=c["thinking_text"])
    widget.tag_configure("gap", spacing1=2, spacing3=6)


class AutoText(tk.Text):
    """只读、按内容自动调整行高的文本框。"""

    _bulk_mode = False   # 批量渲染期间为 True：跳过按条 resize，最后统一布局再算

    def __init__(
        self,
        master,
        *,
        font_size: int = 13,
        fg: str | None = None,
        bg: str | None = None,
        max_lines: int = 42,
        padx: int = 0,
        pady: int = 0,
        wrap: str = "word",
        mono: bool = False,
        zoom: float = 1.0,
    ) -> None:
        self._orig_size = font_size
        self._zoom = zoom
        self._mono = mono
        self._base_size = self._effective_size()
        super().__init__(
            master,
            wrap=wrap,
            bd=0,
            highlightthickness=0,
            relief="flat",
            font=theme.font(self._base_size, mono=mono),
            fg=fg or theme.COLORS["text"],
            bg=bg or theme.COLORS["surface"],
            insertwidth=0,
            padx=padx,
            pady=pady,
            spacing1=1,
            spacing2=1,
            spacing3=1,
            height=1,
            width=1,
            selectbackground=theme.COLORS["select_bg"],
            selectforeground=theme.COLORS["text"],
            cursor="arrow",
            takefocus=0,
        )
        self._max_lines = max_lines
        self._resize_job: str | None = None
        _configure_tags(self, base_size=self._base_size)
        self.configure(state="disabled")
        self.bind("<Configure>", self._schedule_resize)

    # ---------- 尺寸 ----------
    def _schedule_resize(self, _event=None) -> None:
        if AutoText._bulk_mode:
            return
        if self._resize_job is not None:
            return
        self._resize_job = self.after(60, self._do_resize)

    def _effective_size(self) -> int:
        return max(8, round(self._orig_size * self._zoom))

    def set_zoom(self, zoom: float) -> None:
        """缩放字号：只重配字体与 tag，不重绘内容，滚动位置保留。"""
        self._zoom = zoom
        size = self._effective_size()
        if size == self._base_size:
            return
        self._base_size = size
        self.configure(font=theme.font(size, mono=self._mono))
        _configure_tags(self, base_size=size)
        self._schedule_resize()

    def _do_resize(self) -> None:
        self._resize_job = None
        if not self.get("1.0", "end-1c").strip():
            lines = 1
        else:
            try:
                info = self.dlineinfo("end-1c")
            except tk.TclError:
                return
            if not info:
                # 尚未布局（宽度未定），等 <Configure> 再触发
                return
            line_h = info[3]
            if line_h <= 0:
                return
            lines = int((info[1] + info[3]) / line_h)
            lines = max(1, min(lines, self._max_lines))
        if int(self.cget("height")) != lines:
            self.configure(height=lines)

    def autosize_now(self) -> None:
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
            self._resize_job = None
        self._do_resize()

    # ---------- 内容 ----------
    def clear(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def append(self, text: str, tags: str | tuple = "plain") -> None:
        if not text:
            return
        self.configure(state="normal")
        self.insert("end", text, tags)
        self.configure(state="disabled")
        self._schedule_resize()

    def set_markdown(self, body: str) -> None:
        render_markdown(self, body, base_size=self._base_size)
        self._schedule_resize()

    def set_plain(self, body: str, tag: str = "plain") -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", body, tag)
        self.configure(state="disabled")
        self._schedule_resize()

    def all_text(self) -> str:
        return self.get("1.0", "end-1c")


_link_seq = 0


def _insert_link(widget: tk.Text, label: str, url: str, extra: tuple[str, ...] = ()) -> None:
    """每个链接用独立 tag，才能绑定各自的跳转地址。"""
    global _link_seq
    _link_seq += 1
    tag = f"link_{_link_seq}"
    widget.tag_configure(tag, foreground=theme.COLORS["accent"], underline=True)
    widget.tag_bind(tag, "<Button-1>", lambda _e, u=url: _open_url(u))
    widget.tag_bind(tag, "<Enter>", lambda _e: widget.configure(cursor="hand2"))
    widget.tag_bind(tag, "<Leave>", lambda _e: widget.configure(cursor="arrow"))
    widget.insert("end", label or url, (tag,) + extra)


def _insert_inline(widget: tk.Text, text: str, extra: tuple[str, ...] = ()) -> None:
    pos = 0
    for match in INLINE_RE.finditer(text):
        if match.start() > pos:
            widget.insert("end", text[pos : match.start()], ("plain",) + extra)
        if match.group("bold") is not None:
            widget.insert("end", match.group("bold"), ("bold",) + extra)
        elif match.group("code") is not None:
            widget.insert("end", match.group("code"), ("code_inline",) + extra)
        else:
            _insert_link(widget, match.group("text") or "", match.group("url") or "", extra)
        pos = match.end()
    if pos < len(text):
        widget.insert("end", text[pos:], ("plain",) + extra)


def _open_url(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open(url)
    except Exception:
        pass


def render_markdown(widget: tk.Text, body: str, *, base_size: int = 13) -> None:
    """把模型输出的 Markdown 渲染成带样式的文本（够用即可，不追求完整语法）。"""
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    if not body:
        widget.configure(state="disabled")
        return

    in_code = False
    for raw_line in body.replace("\r\n", "\n").rstrip("\n").split("\n"):
        line = raw_line.rstrip()
        fence = line.strip().startswith("```")
        if fence:
            if in_code:
                widget.insert("end", "\n")
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            widget.insert("end", line + "\n", ("code",))
            continue

        if not line.strip():
            widget.insert("end", "\n")
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            tag = "h1" if level == 1 else ("h2" if level == 2 else "h3")
            widget.insert("end", heading.group(2) + "\n", (tag,))
            continue

        if RULE_RE.match(line):
            widget.insert("end", "─" * 46 + "\n", ("rule",))
            continue

        quote = QUOTE_RE.match(line)
        if quote:
            _insert_inline(widget, quote.group(1), ("quote",))
            widget.insert("end", "\n")
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            indent = len(bullet.group(1)) // 2
            widget.insert("end", "  " * indent + "· ", ("plain",))
            _insert_inline(widget, bullet.group(3), ("li",))
            widget.insert("end", "\n", ("li",))
            continue

        ordered = ORDERED_RE.match(line)
        if ordered:
            indent = len(ordered.group(1)) // 2
            widget.insert("end", "  " * indent + ordered.group(2) + " ", ("plain",))
            _insert_inline(widget, ordered.group(3), ("li",))
            widget.insert("end", "\n", ("li",))
            continue

        _insert_inline(widget, line)
        widget.insert("end", "\n")

    widget.configure(state="disabled")
