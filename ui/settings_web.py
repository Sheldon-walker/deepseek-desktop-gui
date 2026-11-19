"""设置窗口（WebView2 版）：整页 HTML 表单，避免 CTk 控件滚动/重绘卡顿。

对外接口与旧的 ui/settings_window.SettingsWindow 一致：
    SettingsWindow(master, cfg, on_saved=cb)
保存时把表单值写回 Config、normalize + save，再回调 on_saved(cfg)。
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from dskit import updater
from dskit.client import DeepSeekClient
from dskit.config import EFFORT_LEVELS, Config, data_dir
from dskit.tts import VOICES
from dskit.errors import DSException
from dskit.version import APP_VERSION, UPDATE_REPO, releases_page_url

from . import theme, wv2
from .settings_html import settings_html

WIDTH, HEIGHT = 720, 760


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, cfg: Config, *, on_saved=None) -> None:
        super().__init__(master)
        self.cfg = cfg
        self.on_saved = on_saved
        self.withdraw()
        self.title("设置")
        self.configure(fg_color=theme.COLORS["bg"])
        self.resizable(True, True)
        self.minsize(600, 520)
        self.transient(master)
        self._wv: wv2.WebView | None = None
        self._ready = False
        self._pending: list[dict] = []
        self._testing = False
        self._checking_update = False
        self._update_info = updater.UpdateInfo(current=APP_VERSION)

        self.geometry(self._center(WIDTH, HEIGHT))
        self._host = tk.Frame(self, bg=theme.COLORS["bg"], highlightthickness=0, bd=0)
        self._host.pack(fill="both", expand=True)
        self._sync_job = None
        self._host.bind("<Configure>", self._on_resize)
        self.after(30, self._init_webview)
        self.after(60, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.deiconify()
        self.lift()
        self.after(120, self._focus_self)
        self.bind("<Escape>", lambda _e: self._close())

    # ---------- 基础 ----------
    def _center(self, w: int, h: int) -> str:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        return f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 30)}"

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
        self.destroy()

    # ---------- WebView ----------
    def _init_webview(self) -> None:
        try:
            self._wv = wv2.WebView(
                self._host.winfo_id(),
                user_data_folder=str(data_dir() / "webview2"),
                on_ready=self._on_ready,
                on_message=self._on_message,
                on_error=lambda msg: messagebox.showerror("设置", f"页面加载失败：{msg}", parent=self),
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("设置", f"无法创建内置浏览器：{exc}", parent=self)
            self._close()

    def _on_ready(self) -> None:
        if not self._wv:
            return
        self._wv.navigate_html(settings_html())
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

    # ---------- 数据 ----------
    def _payload(self) -> dict:
        cfg = self.cfg
        return {
            "dark": theme.is_dark(),
            "api_key": cfg.api_key,
            "theme": cfg.theme,
            "thinking": cfg.thinking,
            "web_search": cfg.web_search,
            "read_url": cfg.read_url,
            "show_reasoning": cfg.show_reasoning,
            "save_history": cfg.save_history,
            "rich": cfg.rich_layout_default,
            "auto_read": cfg.auto_read,
            "voice": cfg.tts_voice,
            "voices": {k: v for k, v in VOICES.items()},
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "max_tokens": cfg.max_tokens,
            "system_prompt": cfg.system_prompt,
            "stop_words": "\n".join(cfg.stop_words or []),
            "effort": cfg.reasoning_effort,
            "efforts": list(EFFORT_LEVELS),
            "proxy": cfg.proxy,
            "timeout": cfg.timeout,
            "data_dir": str(data_dir()),
            "version": APP_VERSION,
            "update_repo": cfg.update_repo,
            "repo_default": UPDATE_REPO,
            "latest_version": self._update_info.latest or "",
        }

    def _on_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        kind = msg.get("type")
        if kind == "ready":
            self._ready = True
            pending, self._pending = self._pending, []
            for payload in pending:
                self._post(payload["type"], payload.get("data"))
            self._post("init", self._payload())
        elif kind == "save":
            self._save(msg.get("data") or {})
        elif kind == "test":
            self._last_form = msg.get("data") or {}
            self._test()
        elif kind == "check_update":
            self._check_update(msg.get("data") or {})
        elif kind == "download_update":
            self._open_url(self._update_info.download_url or self._update_info.html_url)
        elif kind == "open_release":
            repo = updater.effective_repo(self.cfg.update_repo)
            self._open_url(self._update_info.html_url or releases_page_url(repo))
        elif kind == "close":
            self._close()

    def _apply(self, data: dict) -> Config:
        cfg = self.cfg
        cfg.api_key = str(data.get("api_key") or "").strip()
        cfg.theme = "dark" if data.get("theme") == "dark" else "light"
        cfg.thinking = bool(data.get("thinking"))
        cfg.web_search = bool(data.get("web_search"))
        cfg.read_url = bool(data.get("read_url"))
        cfg.show_reasoning = bool(data.get("show_reasoning"))
        cfg.save_history = bool(data.get("save_history"))
        cfg.rich_layout_default = bool(data.get("rich"))
        cfg.auto_read = bool(data.get("auto_read"))
        cfg.tts_voice = str(data.get("voice") or cfg.tts_voice)
        cfg.reasoning_effort = str(data.get("effort") or cfg.reasoning_effort)
        cfg.system_prompt = str(data.get("system_prompt") or "").strip()
        cfg.stop_words = [w.strip() for w in str(data.get("stop_words") or "").splitlines() if w.strip()]
        cfg.proxy = str(data.get("proxy") or "").strip()
        cfg.update_repo = str(data.get("update_repo") or "").strip()
        for key, caster in (("temperature", float), ("top_p", float), ("timeout", int), ("max_tokens", int)):
            raw = data.get(key)
            try:
                setattr(cfg, key, caster(raw) if raw not in (None, "") else getattr(cfg, key))
            except (TypeError, ValueError):
                pass
        cfg.normalize()
        return cfg

    def _save(self, data: dict) -> None:
        cfg = self._apply(data)
        try:
            cfg.save()
        except OSError as exc:
            messagebox.showerror("保存失败", f"写入配置出错：{exc}", parent=self)
            return
        if self.on_saved:
            self.on_saved(cfg)
        self._close()

    def _test(self) -> None:
        if self._testing:
            return
        self._testing = True
        self._post("testing", True)
        cfg = Config.from_dict(self._last_form or self.cfg.to_dict())
        client = DeepSeekClient(cfg)

        def worker() -> None:
            try:
                models = client.models()
                try:
                    balance = client.balance()
                    extra = f"，余额 {balance.get('total')} {balance.get('currency')}"
                except DSException:
                    extra = ""
                self._post("test_result", {"ok": True, "text": f"连接成功：{'、'.join(models)}{extra}"})
            except DSException as exc:
                self._post("test_result", {"ok": False, "text": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._post("test_result", {"ok": False, "text": f"{type(exc).__name__}: {exc}"})
            finally:
                self._testing = False
                self._post("testing", False)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- 软件更新 ----------
    def _open_url(self, url: str) -> None:
        if not url:
            messagebox.showinfo("软件更新", "暂无可用的下载或发布页链接。", parent=self)
            return
        try:
            webbrowser.open(url)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("软件更新", f"无法打开浏览器：{exc}", parent=self)

    def _check_update(self, data: dict) -> None:
        """后台线程查 GitHub Releases，结果用 after(0) 回 Tk 主线程再刷页面。"""
        if self._checking_update:
            return
        self._checking_update = True
        self._post("upd_status", True)
        repo = str(data.get("repo") or "").strip() or self.cfg.update_repo
        proxies = self.cfg.proxies()
        timeout = min(15, max(5, self.cfg.timeout))

        def worker() -> None:
            try:
                info = updater.check_update(
                    repo=repo, current=APP_VERSION, timeout=timeout, proxies=proxies,
                )
            except Exception as exc:  # noqa: BLE001
                info = updater.UpdateInfo(current=APP_VERSION, ok=False, message=f"检查失败：{exc}")

            def done() -> None:
                self._checking_update = False
                self._update_info = info
                self._post("upd_status", False)
                self._post("upd_result", info.to_dict())

            try:
                self.after(0, done)
            except Exception:  # noqa: BLE001
                done()  # 窗口已关闭时 after 会抛错，_post 内部有保护

        threading.Thread(target=worker, daemon=True).start()

    # 供 _test 使用：最近一次表单值（由页面在点「测试连接」时一并带上）
    _last_form: dict = {}
