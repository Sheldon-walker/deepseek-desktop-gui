"""检索结果侧栏：展示当前回答触发的搜索查询与来源链接。

顶部标题行用 Tk 画（高度与顶栏一致，和右上角「来源」按钮齐平），下面的列表交给
WebView2 渲染（ui/panel_html.py）——几十上百条来源时，Tk 控件列表会卡，
HTML 一页渲染滚动、换行、hover 都很轻。左边缘可以拖拽调宽。

数据来自流式过程中模型返回的 server_tool_calls（search/read_link 的 queries、sources）
以及回答里的 citations（参考来源）。
"""

from __future__ import annotations

import json
import tkinter as tk
import webbrowser

import customtkinter as ctk

from dskit.config import data_dir

from . import theme, wv2
from .panel_html import PANEL_HTML

C = theme.COLORS

MIN_WIDTH = 260
MAX_WIDTH = 720


def _open(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


class SearchPanel(ctk.CTkFrame):
    def __init__(self, master, *, width: int = 340, on_resize=None) -> None:
        super().__init__(
            master,
            fg_color=C["surface_soft"],
            corner_radius=0,
            border_width=1,
            border_color=C["border_soft"],
            width=width,
        )
        self.grid_propagate(False)
        self.on_resize = on_resize
        self._width = int(width)
        self._drag_x: int | None = None
        self._drag_w = 0
        self._wv: wv2.WebView | None = None
        self._ready = False
        self._visible = False
        self._failed = False
        self._data = {"groups": [], "cites": [], "notes": []}
        self._sync_job = None
        self._guide = None
        self._pending_w = int(width)

        # ---- 左边缘拖拽条 ----
        self.grip = tk.Frame(
            self, width=7, bd=0, highlightthickness=0, bg=C["surface_soft"], cursor="sb_h_double_arrow"
        )
        self.grip.place(x=0, y=0, relheight=1.0)
        # 里面画一条 1px 竖线：平时是分隔线，指着就变蓝，提示这里可以左右拖
        self.grip_line = tk.Frame(self.grip, width=1, bd=0, highlightthickness=0, bg=C["border"])
        self.grip_line.place(x=3, y=0, relheight=1.0)
        for widget in (self.grip, self.grip_line):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)
            widget.bind("<Enter>", self._grip_hover)
            widget.bind("<Leave>", self._grip_idle)

        # ---- 标题行：高度与顶栏一致，文字垂直居中，和右上角「来源」按钮同一水平
        head = ctk.CTkFrame(self, fg_color="transparent", height=theme.TOP_BAR_HEIGHT)
        head.pack(fill="x")
        head.pack_propagate(False)
        inner = ctk.CTkFrame(head, fg_color="transparent")
        inner.pack(side="left", fill="both", expand=True, padx=(16, 12))
        ctk.CTkLabel(inner, text="检索结果", font=theme.ctk_font(13, "bold"), text_color=C["text"]).pack(side="left")
        self.count_label = ctk.CTkLabel(inner, text="", font=theme.ctk_font(11), text_color=C["text_dim"])
        self.count_label.pack(side="right")

        # ---- 列表容器（WebView2 挂在这里） ----
        self.host = tk.Frame(self, bd=0, highlightthickness=0, bg=C["surface_soft"])
        self.host.pack(fill="both", expand=True)
        self.host.bind("<Configure>", lambda _e: self._schedule_sync(), add="+")

        self.bind("<Destroy>", self._on_destroy, add="+")
        self.after(30, self._poll)

    # ------------------------------------------------------------------ WebView2
    def _ensure_webview(self) -> None:
        if self._wv is not None or self._failed:
            return
        try:
            udf = str(data_dir() / "webview2")
            self._wv = wv2.WebView(
                self.host.winfo_id(),
                user_data_folder=udf,
                on_ready=self._on_ready,
                on_message=self._on_message,
                on_error=self._on_error,
            )
        except Exception as exc:  # noqa: BLE001
            self._failed = True
            self._fallback(str(exc))

    def _on_ready(self) -> None:
        if not self._wv:
            return
        self._wv.navigate_html(PANEL_HTML)
        self._wv.set_visible(self._visible)
        self._sync_bounds()

    def _on_error(self, message: str) -> None:
        self._failed = True
        self._fallback(message)

    def _fallback(self, message: str) -> None:
        for child in self.host.winfo_children():
            child.destroy()
        ctk.CTkLabel(
            self.host,
            text=f"来源列表组件不可用：{message}",
            font=theme.ctk_font(11),
            text_color=C["danger"],
            wraplength=max(160, self._width - 40),
        ).pack(padx=12, pady=16)

    def _on_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        kind = msg.get("type")
        if kind == "panel_ready":
            self._ready = True
            self._push_theme()
            self._push_data()
        elif kind == "open":
            url = str(msg.get("data") or "")
            if url:
                _open(url)

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", None) is not self:
            return
        if self._wv is not None:
            try:
                self._wv.close()
            except Exception:
                pass
            self._wv = None

    def _poll(self) -> None:
        if self._wv:
            try:
                self._wv.poll()
            except Exception:
                pass
        self.after(35, self._poll)

    def _post(self, type_: str, data=None) -> None:
        if not self._wv or not self._ready:
            return
        msg = {"type": type_}
        if data is not None:
            msg["data"] = data
        try:
            self._wv.post_json(json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass

    def _push_theme(self) -> None:
        self._post("theme", {"dark": theme.is_dark()})

    def _push_data(self) -> None:
        self._post("render", self._data)

    def _schedule_sync(self) -> None:
        if getattr(self, "_sync_job", None) is not None:
            return
        self._sync_job = self.after(25, self._run_sync)

    def _run_sync(self) -> None:
        self._sync_job = None
        self._sync_bounds()

    def _sync_bounds(self) -> None:
        if not self._wv or not self._wv.is_ready:
            return
        try:
            w = max(1, self.host.winfo_width())
            h = max(1, self.host.winfo_height())
            self._wv.set_bounds(0, 0, w, h)
        except Exception:
            pass

    # ------------------------------------------------------------------ 显示 / 数据
    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        if visible:
            self._ensure_webview()
        if self._wv:
            try:
                self._wv.set_visible(self._visible)
                if visible:
                    self._sync_bounds()
            except Exception:
                pass

    def set_theme(self) -> None:
        self._push_theme()

    def set_results(self, groups: list[dict], cites: list[dict], notes: list[str] | None = None) -> None:
        groups = [g for g in (groups or []) if g.get("sources")]
        cites = [c for c in (cites or []) if c.get("url")] if cites else []
        notes = [str(n) for n in (notes or []) if str(n).strip()]
        total = sum(len(g.get("sources") or []) for g in groups) + len(cites)
        self.count_label.configure(text=f"{total} 条" if total else "")
        self._data = {"groups": groups, "cites": cites, "notes": notes}
        if self._visible:
            self._ensure_webview()
        self._push_data()

    def _grip_hover(self, _event=None) -> None:
        try:
            self.grip.configure(bg=C["accent_soft"])
            self.grip_line.configure(bg=C["accent"])
        except Exception:
            pass

    def _grip_idle(self, _event=None) -> None:
        try:
            self.grip.configure(bg=C["surface_soft"])
            self.grip_line.configure(bg=C["border"])
        except Exception:
            pass

    # ---------- 拖拽调宽 ----------
    # 拖拽时只画一条参考线，松手才真正改列宽：每帧都重排整个窗口（60ms+）会明显卡。
    def _drag_start(self, event) -> None:
        self._drag_x = event.x_root
        self._drag_w = self.winfo_width()
        self._pending_w = self._width
        try:
            self._guide = tk.Frame(self.master, bd=0, highlightthickness=0, bg=C["accent"], width=2)
            self._guide.place(x=self.winfo_x(), y=0, relheight=1.0)
        except Exception:
            self._guide = None

    def _drag_move(self, event) -> None:
        if self._drag_x is None:
            return
        try:
            scale = max(1.0, float(self._get_widget_scaling()))
        except Exception:
            scale = 1.0
        # 以「对话区所在的容器」为基准，别把聊天区挤到只剩一条缝
        try:
            host_w = self.master.winfo_width()
        except Exception:
            host_w = 0
        if host_w <= 1:
            host_w = self.winfo_toplevel().winfo_width()
        upper = int(min(MAX_WIDTH * scale, max(MIN_WIDTH * scale, host_w * 0.6)))
        px = int(max(MIN_WIDTH * scale, min(upper, self._drag_w + (self._drag_x - event.x_root))))
        self._pending_w = int(round(px / scale))
        if self._guide is not None:
            try:
                self._guide.place(x=max(0, self.winfo_x() - (self.winfo_width() - px)))
            except Exception:
                pass

    def _drag_end(self, _event=None) -> None:
        if self._drag_x is None:
            return
        self._drag_x = None
        if getattr(self, "_guide", None) is not None:
            try:
                self._guide.destroy()
            except Exception:
                pass
            self._guide = None
        width = getattr(self, "_pending_w", self._width)
        if width != self._width:
            self._width = width
            if self.on_resize:
                self.on_resize(width)


__all__ = ["SearchPanel"]
