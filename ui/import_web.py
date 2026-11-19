"""导入会话窗口（WebView2 版）。

对外接口与旧的 ui/import_window.ImportWindow 一致：
    ImportWindow(master, store=store, on_imported=cb)

列表可能上千条，交给浏览器渲染（分批 append），勾选状态在页面里维护，
点「导入」时把选中索引回传，这里按索引写本地会话。
文件选择仍走 Tk 原生对话框，解析在后台线程做（不发网络请求）。
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from dskit import importer
from dskit.errors import DSException
from dskit.session import SessionStore

from . import theme, wv2
from .import_html import IMPORT_HTML

WIDTH, HEIGHT = 880, 680


class ImportWindow(ctk.CTkToplevel):
    def __init__(self, master, *, store: SessionStore, on_imported) -> None:
        super().__init__(master)
        self.store = store
        self.on_imported = on_imported
        self.items: list = []
        self._existing: set = set()
        self._loading = False
        self._ready = False
        self._pending: list[dict] = []
        self._wv: wv2.WebView | None = None

        self.title("导入会话")
        self.withdraw()
        self.configure(fg_color=theme.COLORS["bg"])
        self.transient(master)
        self.geometry(self._center(WIDTH, HEIGHT))
        self.minsize(720, 540)

        self._host = tk.Frame(self, bg=theme.COLORS["bg"], highlightthickness=0, bd=0)
        self._host.pack(fill="both", expand=True)
        self._sync_job = None
        self._host.bind("<Configure>", self._on_resize)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _e: self._close())
        self.after(30, self._init_webview)
        self.after(30, self._poll)
        self.deiconify()
        self.lift()
        self.after(120, self._focus_self)

    # ---------- 基础 ----------
    def _center(self, w: int, h: int) -> str:
        self.update_idletasks()
        px, py = self.master.winfo_rootx(), self.master.winfo_rooty()
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2 - 20
        x = max(0, min(x, sw - w - 10))
        y = max(0, min(y, sh - h - 50))
        return f"{w}x{h}+{int(x)}+{int(y)}"

    def _focus_self(self) -> None:
        try:
            self.focus_force()
            self.grab_set()
        except Exception:
            pass

    def _close(self) -> None:
        if self._wv is not None:
            try:
                self._wv.close()
            except Exception:
                pass
            self._wv = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    # ---------- WebView ----------
    def _init_webview(self) -> None:
        try:
            self._wv = wv2.WebView(
                self._host.winfo_id(),
                user_data_folder=str(importer_data_dir()),
                on_ready=self._on_ready,
                on_message=self._on_message,
                on_error=lambda msg: messagebox.showerror("导入会话", f"页面加载失败：{msg}", parent=self),
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导入会话", f"无法创建内置浏览器：{exc}", parent=self)
            self._close()

    def _on_ready(self) -> None:
        if not self._wv:
            return
        self._wv.navigate_html(IMPORT_HTML)
        self._sync_bounds()
        self._wv.set_visible(True)

    def _on_resize(self, _event=None) -> None:
        if self._sync_job is not None:
            return
        self._sync_job = self.after(25, self._run_sync)

    def _run_sync(self) -> None:
        self._sync_job = None
        self._sync_bounds()

    def _sync_bounds(self) -> None:
        if not self._wv or not self._wv.is_ready:
            return
        try:
            self._wv.set_bounds(0, 0, max(1, self._host.winfo_width()), max(1, self._host.winfo_height()))
        except Exception:
            pass

    def _poll(self) -> None:
        if self._wv:
            try:
                self._wv.poll()
            except Exception:
                pass
        if self.winfo_exists():
            self.after(30, self._poll)

    def _post(self, type_: str, data=None) -> None:
        payload = {"type": type_}
        if data is not None:
            payload["data"] = data
        if not self._wv or not self._ready:
            self._pending.append(payload)
            return
        try:
            self._wv.post_json(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    def _on_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        kind = msg.get("type")
        data = msg.get("data")
        if kind == "ready":
            self._ready = True
            self._post("init", {"dark": theme.is_dark()})
            pending, self._pending = self._pending, []
            for payload in pending:
                self._post(payload["type"], payload.get("data"))
        elif kind == "pick":
            self._pick()
        elif kind == "cancel":
            self._close()
        elif kind == "do_import":
            try:
                self._do_import([int(i) for i in (data or [])])
            except (TypeError, ValueError):
                pass
        elif kind == "js_error":
            # 页面脚本异常写日志，便于排查（不打扰用户）
            try:
                from dskit.config import data_dir

                with open(data_dir() / "ui_error.log", "a", encoding="utf-8") as fh:
                    fh.write("import: " + str(data) + "\n")
            except Exception:
                pass

    # ---------- 解析 ----------
    def _pick(self) -> None:
        if self._loading:
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="选择会话文件",
            filetypes=[("会话文件", "*.json *.zip"), ("JSON", "*.json"), ("ZIP", "*.zip"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self._post("path", path)
        self._start_load(Path(path))

    def _start_load(self, path: Path) -> None:
        self._loading = True
        self._post("loading", "正在解析…")
        result: dict = {}

        def worker() -> None:
            try:
                result["items"] = importer.load_path(path)  # 不截断，全部返回
            except DSException as exc:
                result["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                result["error"] = f"{type(exc).__name__}: {exc}"

        threading.Thread(target=worker, daemon=True).start()
        self._poll_load(result)

    def _poll_load(self, result: dict) -> None:
        if not self.winfo_exists():
            return
        if "items" in result:
            self._loading = False
            self._show(result["items"])
        elif "error" in result:
            self._loading = False
            self._post("error", result["error"])
        else:
            self.after(120, lambda: self._poll_load(result))

    def _show(self, items: list) -> None:
        self.items = items
        self._existing = self.store.existing_raw_ids()
        rows = []
        for it in items:
            already = bool(it.raw_id) and str(it.raw_id) in self._existing
            rows.append({"title": it.title or "未命名", "meta": it.display_meta(), "already": already})
        self._post("items", rows)

    # ---------- 导入 ----------
    def _do_import(self, indices: list[int]) -> None:
        created = []
        skipped = 0
        existing = self.store.existing_raw_ids()
        for i in indices:
            if not (0 <= i < len(self.items)):
                continue
            item = self.items[i]
            if item.raw_id and str(item.raw_id) in existing:
                skipped += 1
                continue
            session = importer.to_session(item)
            self.store.save(session)
            existing.add(str(item.raw_id))
            created.append(session)
        if created and self.on_imported:
            self.on_imported(created)
        msg = f"已导入 {len(created)} 个" + (f"，跳过 {skipped} 个重复" if skipped else "")
        self._post("done", msg)
        self.after(900, self._close)


def importer_data_dir():
    from dskit.config import data_dir

    return data_dir() / "webview2"
