"""懒加载滚动列表：只渲染可见行 + 缓冲，滚动时回收/复用。

CustomTkinter 的 CTkScrollableFrame 会把所有子控件一次性创建出来，
几百行时创建/销毁都卡。这里改成虚拟滚动：固定行高，用 place 定位
可见行，上下留白由内框总高度撑起，滚动时只创建/销毁可见范围的行。

适用场景：行高基本一致的列表（会话列表、导入列表等）。
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import theme

C = theme.COLORS


class LazyScrollFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, *, row_height: int = 58, overscan: int = 8, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._row_height = row_height
        self._overscan = overscan
        self._items: list = []
        self._factory = None
        self._widgets: dict[int, object] = {}
        self._total = 0
        self._last_view = -1
        self._empty_widget = None

        # 监听画布滚动/尺寸变化，用轮询兜底（最可靠）
        self._parent_canvas.bind("<Configure>", lambda e: self._schedule_render(), add="+")
        self._parent_canvas.bind("<MouseWheel>", lambda e: self._schedule_render(), add="+")
        self.bind("<Configure>", lambda e: self._schedule_render(), add="+")
        self.after(80, self._poll)

    # ------------------------------------------------------------------ 对外
    def set_items(self, items: list, factory) -> None:
        self._items = items
        self._factory = factory
        self._total = len(items) * self._row_height
        for w in self._widgets.values():
            w.destroy()
        self._widgets.clear()
        if self._empty_widget is not None:
            self._empty_widget.place_forget()
        # 关键：这里要设的是「内层内容 frame」的高度（撑起可滚动区域），
        # 而不是 CTkScrollableFrame.configure(height=…) —— 后者设的是画布视口高度，
        # 会让列表整体被拉伸、滚不动。所以直接走 tkinter.Frame.configure。
        # 高度按 widget 缩放换算成物理像素，和下面 place 的 y 坐标保持同一坐标系。
        total_px = self._apply_widget_scaling(self._total)
        tk.Frame.configure(self, height=total_px if total_px else 1)
        self._schedule_render(immediate=True)

    def set_empty(self, widget) -> None:
        """显示空状态（items 为空时调用）。widget 会被 place 到顶部。"""
        self._empty_widget = widget
        self.set_items([], None)
        widget.place(x=0, y=0, relwidth=1.0)

    def clear(self) -> None:
        self.set_items([], None)

    def update_all(self, fn) -> None:
        """对当前可见的每一行执行 fn(index, widget)。"""
        for idx, w in list(self._widgets.items()):
            try:
                fn(idx, w)
            except Exception:
                pass

    # ------------------------------------------------------------------ 渲染
    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        try:
            view = self._parent_canvas.canvasy(0)
        except Exception:
            view = 0
        if abs(view - self._last_view) > 4:
            self._last_view = view
            self._render()
        self.after(100, self._poll)

    def _schedule_render(self, immediate: bool = False) -> None:
        if immediate:
            self._render()
        else:
            self.after(20, self._render)

    def _render(self) -> None:
        if not self._items or self._factory is None:
            return
        canvas = self._parent_canvas
        try:
            top = canvas.canvasy(0)
            view_h = canvas.winfo_height()
        except Exception:
            return

        # canvasy/winfo_height 都是物理像素，行高也要换算成物理像素再算索引，
        # 否则高 DPI（如 175%）下会算错可视范围。
        rh = self._apply_widget_scaling(self._row_height)
        start = max(0, int(top / rh) - self._overscan)
        end = min(len(self._items), int((top + view_h) / rh) + self._overscan + 1)

        # 回收范围外的行
        for idx in list(self._widgets):
            if idx < start or idx >= end:
                try:
                    self._widgets[idx].destroy()
                except Exception:
                    pass
                del self._widgets[idx]

        # 创建范围内的行
        for idx in range(start, end):
            if idx not in self._widgets:
                try:
                    w = self._factory(self._items[idx], idx)
                    # CTk 控件禁止在 place 里传 width/height，改用相对尺寸：
                    # relheight = 行高 / 总高，配合上面按缩放设置的内容高度，正好等于行高物理像素。
                    w.place(x=0, y=idx * self._row_height, relwidth=1.0, relheight=self._row_height / self._total)
                    self._widgets[idx] = w
                except Exception:
                    pass
