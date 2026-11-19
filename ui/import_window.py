"""导入会话窗口。

支持两类文件：
1. 本软件导出的备份 JSON；
2. DeepSeek 官网导出的数据（deepseek_data-*.zip 或解压出的 conversations.json）。
解析在后台线程做，导入只是把消息写成本地会话文件，不发任何网络请求。
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from dskit import importer
from dskit.errors import DSException
from dskit.session import SessionStore

from . import theme
from .lazylist import LazyScrollFrame

C = theme.COLORS
MAX_ROWS = 200


class ImportRow(ctk.CTkFrame):
    def __init__(self, master, item, *, already: bool, checked: bool = True, on_change=None) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=8)
        self.item = item
        self.already = already
        self.var = tk.BooleanVar(master=self, value=checked and not already)

        self.cb = ctk.CTkCheckBox(
            self,
            text="",
            variable=self.var,
            width=24,
            checkbox_width=17,
            checkbox_height=17,
            corner_radius=4,
            border_width=1,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            border_color=C["border"],
            state="disabled" if already else "normal",
            command=on_change,
        )
        self.cb.pack(side="left", padx=(8, 4), pady=8)

        text_col = ctk.CTkFrame(self, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True, pady=6)
        title = (item.title or "未命名").replace("\n", " ")
        if len(title) > 46:
            title = title[:46] + "…"
        ctk.CTkLabel(
            text_col,
            text=title,
            font=theme.ctk_font(12, "bold"),
            text_color=C["text_dim"] if already else C["text"],
            anchor="w",
            justify="left",
        ).pack(fill="x")
        meta = item.display_meta()
        if already:
            meta += " · 已导入过"
        if item.warnings:
            meta += " · " + item.warnings[0]
        ctk.CTkLabel(text_col, text=meta, font=theme.ctk_font(10), text_color=C["text_dim"], anchor="w").pack(fill="x")

    def selected(self) -> bool:
        return bool(self.var.get())

    def set_checked(self, value: bool) -> None:
        if not self.already:
            self.var.set(value)


class ImportWindow(ctk.CTkToplevel):
    def __init__(self, master, *, store: SessionStore, on_imported) -> None:
        super().__init__(master)
        self.store = store
        self.on_imported = on_imported
        self.items: list = []
        self._shown: list = []
        self._checked: set = set()   # 选中的索引集合（懒加载下状态存在这里，不依赖 row 控件）
        self._existing: set = set()
        self._loading = False

        self.title("导入会话")
        self.geometry(self._center(820, 660))
        self.minsize(720, 560)
        self.configure(fg_color=C["bg"])
        self.transient(master)
        self._build()
        self.after(80, self._focus_self)

    def _center(self, w: int, h: int) -> str:
        """居中到主窗口。

        单位坑：geometry() 的宽高是逻辑单位（内部会乘缩放），x/y 是物理像素。
        """
        self.update_idletasks()
        scale = 1.0
        try:
            scale = float(self.master._get_window_scaling()) or 1.0
        except Exception:
            pass
        px, py = self.master.winfo_rootx(), self.master.winfo_rooty()
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()

        w = min(w, int(sw / scale) - 40)
        h = min(h, int(sh / scale) - 60)
        x = px + (pw - w * scale) / 2
        y = py + (ph - h * scale) / 2
        x = max(0, min(x, sw - w * scale - 10))
        y = max(0, min(y, sh - h * scale - 60))
        return f"{int(w)}x{int(h)}+{int(x)}+{int(y)}"

    def _focus_self(self) -> None:
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 布局
    def _build(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(18, 2))
        ctk.CTkLabel(head, text="导入会话", font=theme.ctk_font(20, "bold"), text_color=C["text"]).pack(side="left")

        tip = (
            "支持两种文件：① 本软件导出的备份 .json；② DeepSeek 官网导出的数据（.zip 或解压后的 conversations.json）。\n"
            "导入只把历史消息读进本地查看，不会重新发给模型，不产生 token 与工具费用。"
        )
        ctk.CTkLabel(
            self,
            text=tip,
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=24, pady=(4, 12))

        picker = ctk.CTkFrame(self, fg_color="transparent")
        picker.pack(fill="x", padx=24)
        self.path_label = ctk.CTkLabel(
            picker,
            text="尚未选择文件",
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
            anchor="w",
            justify="left",
        )
        self.path_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            picker,
            text="选择文件…",
            width=104,
            height=32,
            corner_radius=8,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            text_color="#FFFFFF",
            font=theme.ctk_font(12, "bold"),
            command=self._pick,
        ).pack(side="right")

        self.list_frame = LazyScrollFrame(
            self,
            row_height=60,
            overscan=8,
            fg_color=C["surface_soft"],
            corner_radius=10,
            border_width=1,
            border_color=C["border"],
            scrollbar_button_color=C["border"],
        )
        self.list_frame.pack(fill="both", expand=True, padx=24, pady=12)

        self.empty = ctk.CTkLabel(
            self.list_frame,
            text="选择文件后，这里会列出可导入的会话",
            font=theme.ctk_font(11),
            text_color=C["text_dim"],
        )
        self.list_frame.set_empty(self.empty)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=24, pady=(0, 18))

        self.select_all_btn = ctk.CTkButton(
            bottom,
            text="全选",
            width=58,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(11),
            command=lambda: self._toggle_all(True),
        )
        self.select_all_btn.pack(side="left")
        self.select_none_btn = ctk.CTkButton(
            bottom,
            text="全不选",
            width=64,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(11),
            command=lambda: self._toggle_all(False),
        )
        self.select_none_btn.pack(side="left", padx=(8, 0))

        self.status = ctk.CTkLabel(bottom, text="", font=theme.ctk_font(11), text_color=C["text_dim"], anchor="w")
        self.status.pack(side="left", padx=(12, 0))

        self.import_btn = ctk.CTkButton(
            bottom,
            text="导入",
            width=96,
            height=34,
            corner_radius=9,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            text_color="#FFFFFF",
            font=theme.ctk_font(12, "bold"),
            state="disabled",
            command=self._do_import,
        )
        self.import_btn.pack(side="right")
        ctk.CTkButton(
            bottom,
            text="取消",
            width=72,
            height=34,
            corner_radius=9,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(12),
            command=self.destroy,
        ).pack(side="right", padx=(0, 10))

    # ------------------------------------------------------------------ 解析
    def _pick(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择会话文件",
            filetypes=[("会话文件", "*.json *.zip"), ("JSON", "*.json"), ("ZIP", "*.zip"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.path_label.configure(text=path, text_color=C["text_soft"])
        self._start_load(Path(path))

    def _start_load(self, path: Path) -> None:
        if self._loading:
            return
        self._loading = True
        self.status.configure(text="正在解析…", text_color=C["text_dim"])
        self.import_btn.configure(state="disabled")
        self.list_frame.clear()
        self._shown = []
        self._checked.clear()

        result: dict = {}

        def worker() -> None:
            try:
                result["items"] = importer.load_path(path)
            except DSException as exc:
                result["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                result["error"] = f"{type(exc).__name__}: {exc}"

        threading.Thread(target=worker, daemon=True).start()
        self._poll_load(result)

    def _poll_load(self, result: dict) -> None:
        """后台线程只写 result，界面更新留在主线程，避免 Tk 跨线程报错。"""
        if not self.winfo_exists():
            return
        if "items" in result:
            self._show(result["items"])
        elif "error" in result:
            self._failed(result["error"])
        else:
            self.after(120, lambda: self._poll_load(result))

    def _failed(self, message: str) -> None:
        self._loading = False
        self.status.configure(text=message, text_color=C["danger"])
        self.empty.configure(text="解析失败，换个文件试试")
        self.list_frame.set_empty(self.empty)

    def _show(self, items: list) -> None:
        self._loading = False
        self.items = items
        self._shown = items[:MAX_ROWS]
        self._existing = self.store.existing_raw_ids()
        # 默认全选（排除已导入过）
        self._checked = set()
        for i, item in enumerate(self._shown):
            already = str(item.raw_id) in self._existing and bool(item.raw_id)
            if not already:
                self._checked.add(i)

        def factory(item, index):
            already = str(item.raw_id) in self._existing and bool(item.raw_id)
            return ImportRow(
                self.list_frame,
                item,
                already=already,
                checked=(index in self._checked),
                on_change=lambda i=index: self._on_toggle(i),
            )

        self.list_frame.set_items(self._shown, factory)
        self.import_btn.configure(state="normal")
        self._update_count()

    def _on_toggle(self, index: int) -> None:
        if index in self._checked:
            self._checked.discard(index)
        else:
            self._checked.add(index)
        self._update_count()

    def _toggle_all(self, value: bool) -> None:
        self._checked = set()
        if value:
            for i, item in enumerate(self._shown):
                already = str(item.raw_id) in self._existing and bool(item.raw_id)
                if not already:
                    self._checked.add(i)
        self.list_frame.update_all(lambda idx, w: w.set_checked(idx in self._checked))
        self._update_count()

    def _update_count(self) -> None:
        count = len(self._checked)
        total = len(self._shown)
        hint = f"（共 {len(self.items)} 个会话，仅显示最近 {total} 个）" if len(self.items) > MAX_ROWS else ""
        self.status.configure(text=f"已选 {count} / {total} 个会话{hint}", text_color=C["text_dim"])
        self.import_btn.configure(text=f"导入 {count} 个" if count else "导入", state="normal" if count else "disabled")

    # ------------------------------------------------------------------ 导入
    def _do_import(self) -> None:
        chosen = [self._shown[i] for i in sorted(self._checked) if i < len(self._shown)]
        if not chosen:
            return
        existing = self.store.existing_raw_ids()
        created = []
        skipped = 0
        for item in chosen:
            if item.raw_id and str(item.raw_id) in existing:
                skipped += 1
                continue
            session = importer.to_session(item)
            self.store.save(session)
            created.append(session)
        if created and self.on_imported:
            self.on_imported(created)
        self.status.configure(
            text=f"已导入 {len(created)} 个" + (f"，跳过 {skipped} 个重复" if skipped else ""),
            text_color=C["ok"],
        )
        self.after(700, self.destroy)
