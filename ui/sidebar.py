"""左侧边栏：新建对话、搜索过滤、会话列表、导入会话、设置。"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import unicodedata
from datetime import datetime

import customtkinter as ctk

from . import theme
from .lazylist import LazyScrollFrame

C = theme.COLORS


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _cut(text: str, limit: int) -> str:
    if _width(text) <= limit:
        return text
    out, acc = "", 0
    for ch in text:
        acc += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if acc > limit - 1:
            break
        out += ch
    return out + "…"


class SessionRow(ctk.CTkFrame):
    def __init__(self, master, item: dict, *, on_click, on_menu) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=8)
        self.item = item
        self._active = False
        self._on_click = on_click
        self._on_menu = on_menu

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="x", padx=10, pady=(6, 4))

        title = (item.get("title") or "新对话").replace("\n", " ")
        self.title_label = ctk.CTkLabel(
            body,
            text=_cut(title, 30),
            font=theme.ctk_font(12, "bold"),
            text_color=C["text"],
            anchor="w",
            justify="left",
        )
        self.title_label.pack(fill="x")

        meta_bits = []
        if item.get("imported"):
            src = {"app": "本软件", "deepseek_web_v3": "官网", "deepseek_web_legacy": "官网旧版", "conversations": "通用"}.get(
                str(item.get("source") or ""), "导入"
            )
            meta_bits.append(f"[{src}导入]")
        meta_bits.append(f"{item.get('turns', 0)} 轮")
        ts = item.get("updated_at") or 0
        if ts:
            meta_bits.append(datetime.fromtimestamp(ts).strftime("%m-%d %H:%M"))
        self.meta_label = ctk.CTkLabel(
            body,
            text=_cut(" · ".join(meta_bits), 34),
            font=theme.ctk_font(10),
            text_color=C["text_dim"],
            anchor="w",
        )
        self.meta_label.pack(fill="x", pady=(1, 0))

        for widget in (self, body, self.title_label, self.meta_label):
            widget.bind("<Button-1>", self._click)
            widget.bind("<Button-3>", self._menu)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _click(self, _event=None) -> None:
        self._on_click(self.item["id"])

    def _menu(self, event) -> None:
        self._on_menu(self.item, event.x_root, event.y_root)

    def _enter(self, _event=None) -> None:
        if not self._active:
            self.configure(fg_color=C["sidebar_hover"])

    def _leave(self, _event=None) -> None:
        if not self._active:
            self.configure(fg_color="transparent")

    def set_active(self, active: bool) -> None:
        self._active = active
        self.configure(fg_color=C["sidebar_active"] if active else "transparent")


def _round_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, fill: str) -> None:
    """在 Canvas 上画圆角矩形（用平滑多边形，比一堆 arc 便宜）。"""
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    canvas.create_polygon(points, smooth=True, splinesteps=12, fill=fill, outline="")


class _FooterItem(tk.Canvas):
    """侧边栏底部的菜单行：圆角高亮块 + 图标 + 文字（整体居中）。

    用 Canvas 而不是 CTkButton/CTkFrame：一个控件就能画圆角 + 两段文字，
    窗口缩放时几乎不花时间（CTk 控件每个都要重绘画布）。
    """

    HEIGHT = 40  # 逻辑像素：行内上下各留 ~8px，比纯文字行松一点

    def __init__(self, master, *, icon: str, text: str, command) -> None:
        super().__init__(
            master,
            height=self.HEIGHT,
            bd=0,
            highlightthickness=0,
            bg=C["sidebar"],
            cursor="hand2",
        )
        # tk.Canvas 不吃 CTk 的缩放：按窗口 DPI 把逻辑高度换算成像素
        try:
            scale = float(ctk.ScalingTracker.get_window_scaling(self.winfo_toplevel())) or 1.0
        except Exception:
            scale = 1.0
        self._scale = max(1.0, scale)
        self._h = int(self.HEIGHT * self._scale)
        self.configure(height=self._h)
        self._command = command
        self._icon = icon
        self._text = text
        self._hover = False
        font = tkfont.Font(font=theme.font(11))
        self._w_icon = font.measure(icon)
        self._w_text = font.measure(text)
        self._gap = int(9 * scale)
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            return
        s = self._scale
        height = self._h
        inset_x = int(8 * s)
        if self._hover:
            _round_rect(
                self,
                inset_x,
                int(3 * s),
                width - inset_x,
                height - int(3 * s),
                int(8 * s),
                C["sidebar_hover"],
            )
        total = self._w_icon + self._gap + self._w_text
        x = max(float(inset_x + 4), (width - total) / 2)
        mid = height / 2
        self.create_text(x, mid, text=self._icon, anchor="w", font=theme.font(11), fill=C["text_dim"])
        self.create_text(
            x + self._w_icon + self._gap,
            mid,
            text=self._text,
            anchor="w",
            font=theme.font(11),
            fill=C["text_soft"],
        )

    def _click(self, _event=None) -> None:
        if self._command:
            self._command()

    def _enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self._hover = False
        self._draw()


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, *, callbacks: dict) -> None:
        super().__init__(master, fg_color=C["sidebar"], corner_radius=0, width=268)
        self.pack_propagate(False)
        self.callbacks = callbacks
        self._items: list[dict] = []
        self._visible_items: list[dict] = []
        self._signature: tuple | None = None
        self.active_id: str | None = None
        self._menu = tk.Menu(self, tearoff=0)

        # ---- 品牌区 ----
        # 行高和主界面顶栏一致；文字贴着行首放，这样它的中心正好和右边「新对话」
        # 那一行（标题）对齐 —— 之前是相对「标题+副标题」整块居中，看着就矮了一截。
        brand = ctk.CTkFrame(self, fg_color="transparent", height=theme.TOP_BAR_HEIGHT)
        brand.pack(fill="x", padx=14)
        brand.pack_propagate(False)
        ctk.CTkLabel(
            brand,
            text="DeepSeek",
            font=theme.ctk_font(19, "bold"),
            text_color=C["accent"],
            anchor="w",
        ).pack(side="top", fill="both", expand=True)

        self.new_btn = ctk.CTkButton(
            self,
            text="⊕  新建对话",
            height=40,
            corner_radius=20,
            fg_color=C["surface"],
            hover_color=C["card"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text"],
            font=theme.ctk_font(13, "bold"),
            command=callbacks["new"],
        )
        self.new_btn.pack(fill="x", padx=14, pady=(0, 10))

        # ---- 搜索 ----
        self.search_entry = ctk.CTkEntry(
            self,
            height=30,
            corner_radius=8,
            border_width=1,
            border_color=C["border"],
            fg_color=C["surface"],
            placeholder_text="搜索对话…",
            placeholder_text_color=C["text_dim"],
            text_color=C["text"],
            font=theme.ctk_font(12),
        )
        self.search_entry.pack(fill="x", padx=14, pady=(0, 8))
        self.search_entry.bind("<KeyRelease>", self._on_filter)

        # ---- 列表 ----
        self.list_frame = LazyScrollFrame(
            self,
            row_height=68,
            overscan=8,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=C["sidebar"],
            scrollbar_button_hover_color=C["border"],
        )
        # 左边留 14 与「新建对话」「搜索框」对齐（右侧留给隐藏的滚动条）
        self.list_frame.pack(fill="both", expand=True, padx=(14, 0))

        # 空状态放在列表内部，跟着列表一起滚动，位置不会被 footer 挤走
        self.empty_label = ctk.CTkLabel(
            self.list_frame,
            text="还没有对话\n点上面「新建对话」开始",
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
            justify="left",
            anchor="w",
        )
        self.list_frame.set_empty(self.empty_label)

        # ---- 底部 ----
        # 一条细分隔线 + 两行"菜单项"（图标左、文字左对齐、整行悬停高亮），
        # 比两个带边框的按钮干净；用原生 tk 控件，缩放时也不会拖慢重绘。
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=6, pady=(4, 10))

        tk.Frame(footer, height=1, bg=C["border_soft"]).pack(fill="x", padx=6, pady=(0, 6))

        self.import_btn = _FooterItem(footer, icon="⤓", text="导入会话", command=callbacks["import"])
        self.import_btn.pack(fill="x", pady=(0, 2))

        self.settings_btn = _FooterItem(footer, icon="⚙", text="设置", command=callbacks["settings"])
        self.settings_btn.pack(fill="x")

        tk.Label(
            footer,
            text="绿色便携版 · 数据存在 data 目录",
            bg=C["sidebar"],
            fg=C["text_dim"],
            font=theme.font(9),
            anchor="center",
        ).pack(fill="x", pady=(8, 0))

    # ---------- 列表 ----------
    def refresh(self, items: list[dict], active_id: str | None = None) -> None:
        signature = tuple((i.get("id"), i.get("title"), i.get("turns"), i.get("updated_at")) for i in items)
        same = signature == self._signature and active_id == self.active_id
        self._items = items
        self.active_id = active_id
        if same:
            return
        self._signature = signature
        self._render()

    def set_active(self, session_id: str | None) -> None:
        self.active_id = session_id
        items = getattr(self, "_visible_items", None) or self._items
        self.list_frame.update_all(lambda idx, w: w.set_active(idx < len(items) and items[idx]["id"] == session_id))

    def _on_filter(self, _event=None) -> None:
        self._render()

    def _render(self) -> None:
        keyword = self.search_entry.get().strip().lower()
        items = self._items
        if keyword:
            items = [i for i in items if keyword in (i.get("title") or "").lower()]
        self._visible_items = items

        if not items:
            self.empty_label.configure(text="没有匹配的对话" if keyword else "还没有对话\n点上面「新建对话」开始")
            self.list_frame.set_empty(self.empty_label)
            return

        def factory(item, index):
            return SessionRow(self.list_frame, item, on_click=self.callbacks["select"], on_menu=self._popup_menu)

        self.list_frame.set_items(items, factory)
        self.list_frame.update_all(lambda idx, w: w.set_active(idx < len(items) and items[idx]["id"] == self.active_id))

    def _popup_menu(self, item: dict, x: int, y: int) -> None:
        self._menu.delete(0, "end")
        self._menu.add_command(label="重命名", command=lambda: self.callbacks["rename"](item["id"]))
        self._menu.add_command(label="导出为 Markdown", command=lambda: self.callbacks["export_md"](item["id"]))
        self._menu.add_command(label="导出备份 (JSON)", command=lambda: self.callbacks["export_json"](item["id"]))
        self._menu.add_separator()
        self._menu.add_command(label="删除对话", command=lambda: self.callbacks["delete"](item["id"]))
        try:
            self._menu.tk_popup(x, y)
        finally:
            self._menu.grab_release()
