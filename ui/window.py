"""主窗口：把侧边栏、聊天区、输入区、状态栏串起来，并管理流式线程与本地存储。"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import unicodedata
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from dskit import asr, audio, docs, player, tts
from dskit.client import DEFAULT_SYSTEM_PROMPT, DeepSeekClient
from dskit.config import AVAILABLE_MODELS, EFFORT_LEVELS, Config, data_dir
from dskit.docs import FileRef
from dskit.errors import DSException
from dskit.session import Session, SessionStore, write_export
from dskit.usage import Usage

from . import fonts, shell_ui, theme, wv2
from .import_web import ImportWindow
from .shell_html import SHELL_HTML
from .input_bar import InputBar
from .search_panel import SearchPanel
from .settings_web import SettingsWindow
from .sidebar import Sidebar
from .webchat import WebChatView

C = theme.COLORS

HERO_FONT_SIZE = 19  # 欢迎页标题字号（logo 尺寸跟着它走）


class App(ctk.CTk):
    def __init__(self) -> None:
        self.cfg = Config.load()
        theme.apply(self.cfg.theme)
        super().__init__(fg_color=theme.COLORS["bg"])
        theme.init_fonts(self)

        self.title(" ")
        self._fit_screen()
        self.minsize(940, 600)
        self._setup_window_icon()

        self.client = DeepSeekClient(self.cfg)
        self.store = SessionStore()
        self._theme_at_open = self.cfg.theme

        # CustomTkinter 会在 after() 里恢复焦点；主题重建销毁控件后，这个延迟回调
        # 会指向已销毁的控件，抛出无害的 "bad window path name"。这里只吞这一种。
        def _report_callback_exception(exc_type, exc, tb) -> None:
            if isinstance(exc, tk.TclError) and "bad window path name" in str(exc):
                return
            import traceback

            traceback.print_exception(exc_type, exc, tb)

        self.report_callback_exception = _report_callback_exception

        self.session: Session | None = None
        self.attachments: list[FileRef] = []
        self.q: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.streaming = False
        self._stream_sid: str | None = None
        self._block = None
        self._busy_upload = False
        self.last_usage = Usage()
        self.recorder = audio.WavRecorder()
        self._voice_timer: str | None = None
        self._voice_busy = False
        self.player = player.WavPlayer()
        self._tts_block = None
        self._tts_gen = 0
        self._tts_auto = False
        self._editing_index: int | None = None
        self._notice_closed: set[str] = set()  # 用户手动关掉导入提示的会话 id
        self.quotes: list[dict] = []  # 引用选区：{text, role, context:[{role,text}]}
        self._search_groups: list[dict] = []
        self._search_cites: list[dict] = []
        self._panel_open = False

        self._web = str(os.environ.get("DEEPSEEK_UI") or getattr(self.cfg, "ui", "web") or "web").lower() != "tk"
        if self._web:
            self._setup_window_icon()
        self._build()
        self.refresh_sessions()
        self.new_chat(show_welcome=True)
        self.after(40, self._poll)
        self.bind("<Control-n>", lambda _e: self.new_chat(show_welcome=True))
        self.bind("<Escape>", self._on_escape)
        self.bind_all("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.bind_all("<Control-0>", self._on_ctrl_zero)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self.cfg.has_key:
            self.after(280, self._first_run_hint)

    # ------------------------------------------------------------------ 网页外壳
    def _build_web(self) -> None:
        """整个界面只有一个 WebView2：窗口缩放由浏览器重排，不再逐个 Tk 控件重绘。"""
        self._wv = None
        self._host = tk.Frame(self, bg="#ffffff", highlightthickness=0, bd=0)
        self._host.pack(fill="both", expand=True)
        self._host.bind("<Configure>", self._on_host_resize, add="+")
        self._sync_job = None
        self._web_ready = False
        self._pending_posts: list[dict] = []

        self.chat = shell_ui.JsChat(self)
        self.chat.on_speak = self.on_speak
        self.chat.on_stop_speak = self.stop_speak
        self.input = shell_ui.JsInput(
            self, model=self.cfg.model, thinking=self.cfg.thinking, web=self.cfg.web_search
        )
        self.sidebar = shell_ui.JsSidebar(self)
        self.search_panel = shell_ui.JsPanel(self)
        self.status_left = shell_ui.JsLabel(self, "status")
        self.status_right = shell_ui.JsLabel(self, "status_right")
        self.title_label = shell_ui.JsLabel(self, "title")
        self.notice_label = shell_ui.JsLabel(self, "notice")
        self.notice_bar = shell_ui.JsNoticeBar(self)
        self.source_btn = shell_ui.JsLabel(self, "source")
        self.after(80, self._init_webview)

    def _init_webview(self) -> None:
        try:
            self._wv = wv2.WebView(
                self._host.winfo_id(),
                user_data_folder=str(data_dir() / "webview2"),
                on_ready=self._on_wv_ready,
                on_message=self._on_web_message,
                on_error=lambda msg: self.status_left.configure(text=f"界面异常：{msg}"),
            )
        except Exception as exc:  # noqa: BLE001
            # 没有 WebView2 运行时就退回旧的 Tk 界面，别让用户直接打不开
            self._web = False
            for child in self.winfo_children():
                child.destroy()
            self._build()
            self.refresh_sessions()
            self.new_chat(show_welcome=True)
            self.status_left.configure(text=f"内置浏览器不可用，已切回经典界面：{exc}")

    def _on_wv_ready(self) -> None:
        if not self._wv:
            return
        self._wv.navigate_html(SHELL_HTML)
        self._sync_web_bounds()
        self._wv.set_visible(True)
        # 缩放统一走页面 CSS body.zoom（字号/间距/图标一起缩放，且 Tk 状态栏由我们控制）。
        # 不再叠加 WebView 原生 zoom，否则两者相乘会缩放过头。
        self.chat.zoom = float(getattr(self.cfg, "chat_zoom", 1.0) or 1.0)

    def _on_host_resize(self, _event=None) -> None:
        if self._sync_job is not None:
            return
        self._sync_job = self.after(25, self._run_sync)

    def _run_sync(self) -> None:
        self._sync_job = None
        self._sync_web_bounds()

    def _sync_web_bounds(self) -> None:
        if not self._wv or not self._wv.is_ready:
            return
        try:
            self._wv.set_bounds(0, 0, max(1, self._host.winfo_width()), max(1, self._host.winfo_height()))
        except Exception:
            pass

    def post(self, type_: str, data=None) -> None:
        payload = {"type": type_}
        if data is not None:
            payload["data"] = data
        wv = getattr(self, "_wv", None)
        # 页面还没加载完就先攒着，否则启动时的历史/会话会丢
        if not wv or not self._web_ready:
            self._pending_posts.append(payload)
            return
        try:
            wv.post_json(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    def _flush_posts(self) -> None:
        pending, self._pending_posts = self._pending_posts, []
        for payload in pending:
            wv = getattr(self, "_wv", None)
            if not wv:
                break
            try:
                wv.post_json(json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass

    def _push_init(self) -> None:
        sessions = self._session_items(self._web_filter)
        self.post(
            "init",
            {
                "sessions": sessions,
                "active": self.session.id if self.session else None,
                "title": self.title_label.cget("text") or "新对话",
                "model": self.cfg.model,
                "models": list(AVAILABLE_MODELS),
                "thinking": self.cfg.thinking,
                "effort": self.cfg.reasoning_effort,
                "efforts": list(EFFORT_LEVELS),
                "web": self.cfg.web_search,
                "rich": self.cfg.rich_layout_default,
                "theme": "dark" if theme.is_dark() else "light",
                "data_dir": f"数据目录：{data_dir()}",
                "side_width": self.cfg.sidebar_width,
                "panel_width": self.cfg.panel_width,
                "notice": "",
                "zoom": float(getattr(self.cfg, "chat_zoom", 1.0) or 1.0),
                "chat_style": fonts.style_payload(self.cfg),
            },
        )

    def _session_items(self, keyword: str = "") -> list[dict]:
        items = []
        low = (keyword or "").strip().lower()
        for it in self.store.list():
            title = str(it.get("title") or "新对话")
            if low and low not in title.lower():
                continue
            bits = []
            if it.get("imported"):
                bits.append("[官网导入]")
            bits.append(f"{it.get('turns', 0)} 轮")
            ts = it.get("updated_at") or 0
            if ts:
                bits.append(datetime.fromtimestamp(ts).strftime("%m-%d %H:%M"))
            items.append({"id": it.get("id"), "title": title, "meta": " · ".join(bits),
                          "ts": ts, "pinned": bool(it.get("pinned"))})
        return items

    @property
    def _web_filter(self) -> str:
        return getattr(self, "_web_search_text", "")

    def _on_web_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return
        kind = msg.get("type")
        data = msg.get("data")
        if kind == "js_error":
            try:
                with open(data_dir() / "ui_error.log", "a", encoding="utf-8") as fh:
                    fh.write(str(data) + "\n")
            except Exception:
                pass
        elif kind == "shell_ready":
            self._web_ready = True
            self._flush_posts()
            self._push_init()
        elif kind == "send":
            text = (data or {}).get("text") if isinstance(data, dict) else ""
            if text:
                try:
                    self.on_send(str(text))
                except Exception as exc:
                    # 发送链路的任何异常都必须可见，否则界面表现为"点了没反应"且无痕迹
                    import traceback
                    try:
                        with open(data_dir() / "ui_error.log", "a", encoding="utf-8") as fh:
                            fh.write("[send] " + traceback.format_exc() + "\n")
                    except Exception:
                        pass
                    try:
                        self._toast(f"发送失败：{exc}", error=True)
                    except Exception:
                        pass
        elif kind == "stop":
            self.on_stop()
        elif kind == "new_chat":
            self.new_chat(show_welcome=True)
        elif kind == "open_session":
            self.open_session(str(data))
        elif kind == "session_action":
            action = (data or {}).get("action")
            sid = (data or {}).get("id")
            if action == "rename":
                self.rename_session(str(sid))
            elif action == "delete":
                self.delete_session(str(sid))
            elif action == "pin":
                self._pin_session(str(sid))
            elif action == "export":
                self.export_markdown(str(sid))
        elif kind == "multi_delete":
            ids = [str(x) for x in (data or [])]
            self._multi_delete(ids)
        elif kind == "multi_export":
            ids = [str(x) for x in (data or [])]
            self._multi_export(ids)
        elif kind == "multi_pin":
            ids = [str(x) for x in (data or [])]
            self._multi_pin(ids)
        elif kind == "search":
            self._web_search_text = str(data or "")
            self.post("sessions", {"items": self._session_items(self._web_search_text),
                                   "active": self.session.id if self.session else None})
        elif kind == "toggle":
            key = (data or {}).get("key")
            value = bool((data or {}).get("value"))
            if key == "thinking":
                self._on_think_change(value)
            elif key == "web":
                self._on_search_change(value)
            elif key == "rich":
                self._on_rich_change(value)
        elif kind == "model":
            self._on_model_change(str(data))
        elif kind == "effort":
            self.cfg.reasoning_effort = str(data)
            self.cfg.save()
        elif kind == "paste_image":
            self._attach_pasted_image((data or {}).get("name") or "image.png", (data or {}).get("b64") or "")
        elif kind == "attach":
            self.on_attach()
        elif kind == "remove_attachment":
            for ref in list(self.attachments):
                if ref.file_id == data:
                    self.remove_attachment(ref)
                    break
        elif kind == "mic_start":
            self.on_voice_press()
        elif kind == "mic_stop":
            self.on_voice_release()
        elif kind == "panel_toggle":
            self.toggle_search_panel()
        elif kind == "panel_width":
            try:
                self.cfg.panel_width = max(260, min(720, int(data)))
                self._save_sizes()
            except (TypeError, ValueError):
                pass
        elif kind == "sidebar_width":
            try:
                self.cfg.sidebar_width = max(200, min(420, int(data)))
                self._save_sizes()
            except (TypeError, ValueError):
                pass
        elif kind == "settings":
            self.open_settings()
        elif kind == "import":
            self.open_import()
        elif kind == "copy":
            self._clipboard(str(data or ""))
        elif kind == "copy_user":
            self._clipboard(str(data or ""))
        elif kind == "open_url":
            try:
                webbrowser.open(str(data))
            except Exception:
                pass
        elif kind == "regen":
            self.regenerate()
        elif kind == "delete_msg":
            idx = (data or {}).get("index")
            if idx is not None:
                self.delete_message(int(idx))
        elif kind == "edit_user":
            idx = (data or {}).get("index")
            text = (data or {}).get("text") or ""
            if idx is not None:
                self.edit_message(int(idx), str(text))
        elif kind == "speak":
            mid = (data or {}).get("id")
            block = self.chat._blocks.get(str(mid))
            if block is not None:
                self.on_speak(block)
        elif kind == "speak_selection":
            text = str((data or {}).get("text") or "").strip()
            if text:
                self._speak_selection(text)
        elif kind == "quote_selection":
            self._add_quote(data or {})
        elif kind == "quote_remove":
            try:
                idx = int(data)
                if 0 <= idx < len(self.quotes):
                    self.quotes.pop(idx)
                    self.input.show_quotes(self.quotes)
            except (TypeError, ValueError):
                pass
        elif kind == "show_sources":
            self.show_message_sources((data or {}).get("index"), (data or {}).get("note") or "")
        elif kind == "expand_history":
            try:
                self.chat.render_history(self.session.messages, model=self.session.model or self.cfg.model,
                                         show_all=True, cny_rate=self.cfg.cny_rate)
            except Exception:
                pass
        elif kind == "notice_close":
            if self.session is not None:
                self._notice_closed.add(self.session.id)
            self.post("notice_show", False)
        elif kind == "zoom_wheel":
            try:
                self._apply_zoom(1 if int(data) > 0 else -1)
            except (TypeError, ValueError):
                pass
        elif kind == "zoom_reset":
            self._on_ctrl_zero()

    def _save_sizes(self) -> None:
        """拖拽宽度后延迟写盘，避免每帧写配置。"""
        job = getattr(self, "_size_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._size_job = self.after(400, self._do_save_sizes)

    def _do_save_sizes(self) -> None:
        self._size_job = None
        try:
            self.cfg.save()
        except Exception:
            pass

    def _toast(self, text: str, *, error: bool = False) -> None:
        """界面内提示（Tk 的 messagebox 会被 WebView 盖住，等于没提示）。"""
        self.post("toast", {"text": text, "kind": "error" if error else "info", "ms": 5000 if error else 3000})

    def _system_prompt(self) -> str:
        return (getattr(self.cfg, "system_prompt", "") or "").strip() or DEFAULT_SYSTEM_PROMPT

    def _attach_pasted_image(self, name: str, b64: str) -> None:
        """把粘进输入框的图片落成临时文件，再走原来的上传解析流程。"""
        import base64
        import tempfile
        import time as _time

        if not self.cfg.has_key:
            messagebox.showinfo("需要 API Key", "图片解析走官方 Files API，请先在设置里填写 API Key。", parent=self)
            self.open_settings()
            return
        try:
            raw = base64.b64decode(b64)
        except Exception:
            self._toast("图片读取失败，试试重新截图再粘贴", error=True)
            return
        suffix = Path(name).suffix.lower() or ".png"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            suffix = ".png"
        folder = Path(tempfile.gettempdir()) / "deepseek-paste"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"paste-{int(_time.time() * 1000)}-{len(self.attachments)}{suffix}"
            path.write_bytes(raw)
        except OSError:
            return
        self._upload_paths([str(path)])

    def _clipboard(self, text: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    # ------------------------------------------------------------------ 布局
    def _build(self) -> None:
        if getattr(self, "_web", False):
            return self._build_web()
        self.sidebar = Sidebar(
            self,
            callbacks={
                "new": lambda: self.new_chat(show_welcome=True),
                "select": self.open_session,
                "import": self.open_import,
                "settings": self.open_settings,
                "rename": self.rename_session,
                "export_md": self.export_markdown,
                "export_json": self.export_backup,
                "delete": self.delete_session,
            },
        )
        self.sidebar.pack(side="left", fill="y")

        divider = ctk.CTkFrame(self, fg_color=C["border"], width=1, corner_radius=0)
        divider.pack(side="left", fill="y")
        self.divider = divider
        self._sidebar_collapsed = False

        main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        main.pack(side="left", fill="both", expand=True)
        self.main = main
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=0)
        main.grid_rowconfigure(3, weight=1)

        # ---- 顶栏 ----
        # 用 grid 让「标题 + 副标题」这一整体在顶栏里垂直居中，
        # 和左侧边栏的 DeepSeek 品牌行对齐（否则文字块会整体偏高）。
        top = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0, height=theme.TOP_BAR_HEIGHT)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        top.grid_rowconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)

        self.toggle_btn = ctk.CTkButton(
            top,
            text="☰",
            width=32,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            text_color=C["text_soft"],
            font=theme.ctk_font(15, "bold"),
            command=self.toggle_sidebar,
        )
        self.toggle_btn.grid(row=0, column=0, padx=(10, 4), sticky="w")

        left = ctk.CTkFrame(top, fg_color="transparent")
        left.grid(row=0, column=1, sticky="w")
        # 只留对话名一行：模型名在输入栏里能随时切，顶栏再显示一遍反而多余，
        # 单行也能和三横图标、左边的 DeepSeek 品牌共用同一条中线。
        self.title_label = ctk.CTkLabel(
            left,
            text="新对话",
            font=theme.ctk_font(14, "bold"),
            text_color=C["text"],
            anchor="w",
        )
        self.title_label.pack(side="left")

        right = ctk.CTkFrame(top, fg_color="transparent")
        right.grid(row=0, column=2, padx=(0, 18), sticky="e")
        self.source_btn = ctk.CTkButton(
            right,
            text="来源",
            width=56,
            height=30,
            corner_radius=8,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(11),
            command=self.toggle_search_panel,
        )
        self.source_btn.pack()

        ctk.CTkFrame(main, fg_color=C["border"], height=1, corner_radius=0).grid(row=1, column=0, sticky="ew")

        # ---- 导入提示条 ----
        self.notice_bar = ctk.CTkFrame(main, fg_color=C["warn_bg"], corner_radius=0, height=28)
        self.notice_label = ctk.CTkLabel(
            self.notice_bar,
            text="",
            font=theme.ctk_font(10),
            text_color=C["warn_fg"],
            anchor="w",
        )
        self.notice_label.pack(side="left", padx=22)

        # ---- 聊天区 ----
        self.chat = WebChatView(
            main,
            on_speak=self.on_speak,
            on_stop_speak=self.stop_speak,
            on_edit_user=self.edit_message,
            on_copy_user=self.copy_user,
            on_regenerate=self.regenerate,
            on_delete_msg=self.delete_message,
            on_show_sources=self.show_message_sources,
        )
        self.chat.grid(row=3, column=0, sticky="nsew")
        self.chat.zoom = self.cfg.chat_zoom

        # ---- 输入区 ----
        # 输入栏放在一个「可移动」的容器里：欢迎页时居中摆在欢迎语下方，
        # 有对话后容器回到第 4 行贴底。Tk 不能改变父控件，所以移动的是容器。
        self.input_holder = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
        self.input = InputBar(
            self.input_holder,
            on_send=self.on_send,
            on_stop=self.on_stop,
            on_attach=self.on_attach,
            on_remove_attach=self.remove_attachment,
            on_rich_change=self._on_rich_change,
            on_model_change=self._on_model_change,
            on_think_change=self._on_think_change,
            on_search_change=self._on_search_change,
            on_voice_press=self.on_voice_press,
            on_voice_release=self.on_voice_release,
            model=self.cfg.model,
            thinking=self.cfg.thinking,
            web_search=self.cfg.web_search,
        )
        self.input.pack(fill="both", expand=True)
        self.input_holder.grid(row=4, column=0, sticky="ew")
        self.input.set_rich(self.cfg.rich_layout_default)
        self.input.bind("<Configure>", self._on_input_configure, add="+")

        # ---- 欢迎页（欢迎语 + logo，居中等宽于输入框） ----
        self.hero = ctk.CTkFrame(main, fg_color=C["bg"], corner_radius=0)
        hero_inner = ctk.CTkFrame(self.hero, fg_color="transparent")
        hero_inner.pack(expand=True)
        hero_font = theme.ctk_font(HERO_FONT_SIZE, "bold")
        # logo 高度跟着标题字号走（约为字号的 1.15 倍），换字号也不会一大一小
        logo_h = max(20, int(round(round(HERO_FONT_SIZE * theme.FONT_SCALE) * 1.15)))
        logo_w = int(round(logo_h * 34 / 25))
        try:
            from . import icons as ic

            self._logo = ic.logo((logo_w, logo_h))
            ctk.CTkLabel(hero_inner, text="", image=self._logo, width=logo_w).pack(side="left", padx=(0, 10))
        except Exception:
            self._logo = None
        ctk.CTkLabel(
            hero_inner,
            text="欢迎回来，想从哪里开始？",
            font=hero_font,
            text_color=C["text"],
        ).pack(side="left")

        self._welcome_mode: bool | None = None
        self._hero_geo = None
        self._hero_job = None
        main.bind("<Configure>", self._on_main_configure, add="+")

        # ---- 检索结果侧栏 ----
        self.search_panel = SearchPanel(main, width=self.cfg.panel_width, on_resize=self._on_panel_resize)
        self._panel_open = False  # 重建界面（切主题）时也要按"收起"状态开始
        self._apply_panel_width(self.cfg.panel_width)
        # 从窗口最顶一直到底部（row0~row5）：面板标题行和右上角「来源」按钮齐平
        self.search_panel.grid(row=0, column=1, rowspan=6, sticky="nsew")
        self.search_panel.grid_remove()

        # ---- 状态栏 ----
        status = ctk.CTkFrame(main, fg_color=C["surface_soft"], corner_radius=0, height=26)
        status.grid(row=5, column=0, sticky="ew")
        status.grid_propagate(False)
        self.status_left = ctk.CTkLabel(status, text="", font=theme.ctk_font(10), text_color=C["text_dim"], anchor="w")
        self.status_left.pack(side="left", padx=(22, 0))
        self.status_right = ctk.CTkLabel(
            status,
            text=f"数据目录：{data_dir()}",
            font=theme.ctk_font(10),
            text_color=C["text_dim"],
            anchor="e",
        )
        self.status_right.pack(side="right", padx=(0, 22))

        self._show_welcome()

    def _fit_screen(self) -> None:
        """按屏幕尺寸给一个合适的初始大小。

        注意单位：CustomTkinter 的 geometry() 会把**宽高**乘上缩放系数（逻辑单位），
        但 **坐标** 原样传给 Tk（物理像素）。混用会让窗口跑到屏幕外，
        所以这里宽高按逻辑算、坐标按物理算。
        """
        self.update_idletasks()
        scale = 1.0
        try:
            scale = float(self._get_window_scaling()) or 1.0
        except Exception:
            pass
        sw_px = self.winfo_screenwidth()          # 物理像素
        sh_px = self.winfo_screenheight()
        sw = sw_px / scale                        # 逻辑尺寸
        sh = sh_px / scale

        width = int(min(1240, max(940, sw - 90)))
        height = int(min(860, max(600, sh - 90)))
        x = max(0, int((sw_px - width * scale) / 2))
        y = max(0, int((sh_px - height * scale) / 2) - int(30 * scale / 1.75))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._start_size = (width, height)

    def _show_welcome(self) -> None:
        self.chat.show_welcome()
        self._set_mode(welcome=True)

    # ------------------------------------------------------------------ 欢迎页 / 对话页布局
    def _set_mode(self, welcome: bool) -> None:
        """欢迎页：隐藏对话区，欢迎语 + 输入框整体居中；有消息后输入框贴底。"""
        if getattr(self, "_web", False):
            return
        if self._welcome_mode == welcome:
            if welcome:
                self._place_hero()
            return
        self._welcome_mode = welcome
        if welcome:
            self.chat.grid_remove()
            self.chat.set_visible(False)
            self.input_holder.grid_remove()
            self.after(20, self._place_hero)
        else:
            self.hero.place_forget()
            self.input_holder.place_forget()
            self.input_holder.grid(row=4, column=0, sticky="ew")
            self.chat.grid(row=3, column=0, sticky="nsew")
            self.chat.set_visible(True)
            self.chat.refresh_bounds()

    def _on_main_configure(self, _event=None) -> None:
        if getattr(self, "_web", False) or not self._welcome_mode:
            return
        self._place_hero()

    def _place_hero(self) -> None:
        """把欢迎语和输入框作为一个整体居中摆放。

        注意 CTk 的 place 只接受逻辑尺寸：x/y 会被乘上缩放系数，width/height
        不允许传，所以宽度用 relwidth 按比例给。
        """
        if not self._welcome_mode:
            return
        try:
            scale = float(self.main._get_widget_scaling()) or 1.0
            mw = self.main.winfo_width() / scale
            mh = self.main.winfo_height() / scale
            if mw <= 2 or mh <= 2:
                return
            hero_h = self.hero.winfo_reqheight() / scale
            in_h = self.input_holder.winfo_reqheight() / scale
            gap = 18
            total = hero_h + gap + in_h
            top = max(16, (mh - total) / 2 - 14)
            # 右侧检索栏展开时，只在剩下的区域里居中，别压到面板底下
            reserved = float(getattr(self, "_panel_width", 0) or 0) if getattr(self, "_panel_open", False) else 0.0
            avail = max(320.0, mw - reserved)
            width = max(320.0, min(860.0, avail - 64))
            relw = max(0.15, min(1.0, width / mw))
            relx = (avail / 2 + max(0.0, mw - avail - reserved)) / mw if reserved else 0.5
            target = (round(top), round(relw, 4), round(relx, 4), round(hero_h))
            if target == self._hero_geo:
                return  # 尺寸没变就别再动布局，避免打字时反复重排
            self._hero_geo = target
            self.hero.place(relx=relx, y=top, anchor="n", relwidth=relw)
            self.input_holder.place(relx=relx, y=top + hero_h + gap, anchor="n", relwidth=relw)
        except Exception:
            pass

    def _on_input_configure(self, _event=None) -> None:
        """输入框高度变化（换行自动增高 / 出现附件）时，重新把整组居中。"""
        if getattr(self, "_web", False) or not self._welcome_mode:
            return
        if getattr(self, "_hero_job", None) is not None:
            try:
                self.after_cancel(self._hero_job)
            except Exception:
                self._hero_job = None
        self._hero_job = self.after(50, self._run_hero_job)

    def _run_hero_job(self) -> None:
        self._hero_job = None
        self._place_hero()

    def _set_title(self, text: str) -> None:
        self.title_label.configure(text=_clip_title(text))

    def toggle_sidebar(self) -> None:
        """收起 / 展开左侧边栏。"""
        if self._sidebar_collapsed:
            self.sidebar.pack(side="left", fill="y", before=self.main)
            self.divider.pack(side="left", fill="y", before=self.main)
            self._sidebar_collapsed = False
        else:
            self.sidebar.pack_forget()
            self.divider.pack_forget()
            self._sidebar_collapsed = True

    def _app_ico_path(self) -> Path | None:
        base = getattr(sys, "_MEIPASS", None)
        if base:
            p = Path(base) / "app.ico"
            if p.exists():
                return p
        p = Path(__file__).resolve().parent.parent / "app.ico"
        return p if p.exists() else None

    def _setup_window_icon(self) -> None:
        """标题栏 / 任务栏 / Alt-Tab 都用清晰的原生尺寸图标。

        之前把 ICON_SMALL 置空，Windows 会用 32px 的大图标去填 16px 的标题栏，
        再被任务栏放大回 32px，两处都会发虚。这里按当前窗口 DPI 精确取图：
        小图标给 16*缩放，大图标给 32*缩放，app.ico 里对应的尺寸都有。
        """
        if sys.platform != "win32":
            return
        ico = self._app_ico_path()
        if ico is not None:
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass
        # Tk 在窗口第一次映射时还会再设一次图标，等它做完再覆盖成 DPI 精确尺寸
        self.after(120, self._apply_native_icons)
        self.after(800, self._apply_native_icons)

    def _apply_native_icons(self) -> None:
        ico = self._app_ico_path()
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = wintypes.LPARAM
            user32.LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.LoadImageW.restype = wintypes.HANDLE

            hwnd = user32.GetAncestor(wintypes.HWND(self.winfo_id()), 2) or wintypes.HWND(self.winfo_id())
            if not hwnd or ico is None:
                return
            dpi = 96
            try:
                dpi = int(user32.GetDpiForWindow(hwnd)) or 96
            except Exception:
                pass
            ratio = max(1.0, dpi / 96.0)
            IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
            WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
            self._icons = []
            for slot, base in ((ICON_SMALL, 16), (ICON_BIG, 32)):
                size = int(round(base * ratio))
                handle = user32.LoadImageW(None, str(ico), IMAGE_ICON, size, size, LR_LOADFROMFILE)
                if handle:
                    self._icons.append(handle)
                    user32.SendMessageW(hwnd, WM_SETICON, slot, handle)
        except Exception:
            pass

    # ------------------------------------------------------------------ 首启动
    def _first_run_hint(self) -> None:
        answer = messagebox.askyesno(
            "还没有配置 API Key",
            "还没有填写 DeepSeek API Key，现在去设置里填写吗？\n\n"
            "Key 在 platform.deepseek.com 的「API keys」页面创建，以 sk- 开头。",
            parent=self,
        )
        if answer:
            self.open_settings()

    # ------------------------------------------------------------------ 会话
    def refresh_sessions(self) -> None:
        active = self.session.id if self.session else None
        self.sidebar.refresh(self.store.list(), active)

    def new_chat(self, *, show_welcome: bool = True) -> None:
        if self.streaming:
            self.on_stop()
        self.stop_speak()
        self._editing_index = None
        self._reset_search_panel()
        self.session = Session(model=self.cfg.model)
        self.attachments.clear()
        self.input.show_attachments([])
        self.quotes.clear()
        self.input.show_quotes([])
        self._set_title("新对话")
        self.sidebar.set_active(None)
        self.last_usage = Usage()
        self.status_left.configure(text="")
        self._update_notice()
        self._show_welcome()
        try:
            self.input.text.focus_set()
        except Exception:
            pass

    def open_session(self, session_id: str) -> None:
        if self.streaming and self._stream_sid == session_id:
            return
        try:
            session = self.store.load(session_id)
        except (OSError, ValueError) as exc:
            messagebox.showerror("打开失败", f"读取会话失败：{exc}", parent=self)
            return
        self.stop_speak()
        self._reset_search_panel()
        self.session = session
        self.attachments.clear()
        self.input.show_attachments([])
        self.quotes.clear()
        self.input.show_quotes([])
        self._set_title(session.title or "未命名")
        self.sidebar.set_active(session_id)
        self.chat.render_history(session.messages, model=session.model or self.cfg.model, cny_rate=self.cfg.cny_rate)
        self._set_mode(False)
        self._update_notice()
        self.status_left.configure(text=f"{session.user_turns} 轮 · {len(session.messages)} 条消息")
        if session.model in AVAILABLE_MODELS:
            self.input.model_menu.set(session.model)

    def _update_notice(self) -> None:
        session = self.session
        if session and session.is_imported and session.id not in self._notice_closed:
            src = session.source_label or "外部文件"
            self.notice_label.configure(
                text=f"此会话从「{src}」导入，仅本地保存。继续对话时历史会一并发送并计入输入 token。"
            )
            self.notice_bar.grid(row=2, column=0, sticky="ew")
        else:
            self.notice_bar.grid_remove()

    def rename_session(self, session_id: str) -> None:
        dialog = ctk.CTkInputDialog(text="输入新的会话标题：", title="重命名")
        value = dialog.get_input()
        if not (value and value.strip()):
            return
        new_title = value.strip()[:60]
        try:
            # 当前会话必须改内存里的对象：否则下次发送时旧对象会把自动标题写回磁盘
            if self.session and self.session.id == session_id:
                self.session.title = new_title
                self.session.extra["title_manual"] = True
                self.store.save(self.session)
            else:
                session = self.store.load(session_id)
                session.title = new_title
                session.extra["title_manual"] = True
                self.store.save(session)
        except (OSError, ValueError) as exc:
            messagebox.showerror("重命名失败", f"保存会话失败：{exc}", parent=self)
            return
        if self.session and self.session.id == session_id:
            self._set_title(new_title)
        self.refresh_sessions()

    def delete_session(self, session_id: str) -> None:
        if not messagebox.askyesno("删除对话", "删除后无法恢复，确定删除这个会话吗？", parent=self):
            return
        self.store.delete(session_id)
        if self.session and self.session.id == session_id:
            self.new_chat(show_welcome=True)
        self.refresh_sessions()

    def _pin_session(self, session_id: str) -> None:
        try:
            session = self.store.load(session_id)
        except (OSError, ValueError):
            return
        extra = session.extra
        extra["pinned"] = not bool(extra.get("pinned"))
        self.store.save(session)
        self.refresh_sessions()
        self._toast("已置顶" if extra["pinned"] else "已取消置顶")

    def _multi_delete(self, ids: list[str]) -> None:
        if not ids:
            return
        if not messagebox.askyesno("删除对话", f"删除选中的 {len(ids)} 个会话？删除后无法恢复。", parent=self):
            return
        for sid in ids:
            self.store.delete(sid)
        if self.session and self.session.id in ids:
            self.new_chat(show_welcome=True)
        self.refresh_sessions()
        self._toast(f"已删除 {len(ids)} 个会话")

    def _multi_export(self, ids: list[str]) -> None:
        if not ids:
            return
        parts = []
        for sid in ids:
            try:
                session = self.store.load(sid)
            except (OSError, ValueError):
                continue
            parts.append(f"# {session.title}\n\n" + self.store.export_markdown(session))
        if not parts:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="导出选中的会话（Markdown）", defaultextension=".md",
            initialfile="deepseek-会话合集.md", filetypes=[("Markdown", "*.md")],
        )
        if not path:
            return
        Path(path).write_text("\n\n---\n\n".join(parts), encoding="utf-8")
        self._toast(f"已导出 {len(parts)} 个会话：{path}")

    def _multi_pin(self, ids: list[str]) -> None:
        if not ids:
            return
        # 以第一个被选中的状态为准：若全都已置顶则取消，否则全部置顶
        states = []
        for sid in ids:
            try:
                states.append(bool(self.store.load(sid).extra.get("pinned")))
            except (OSError, ValueError):
                pass
        target = not all(states) if states else True
        for sid in ids:
            try:
                session = self.store.load(sid)
            except (OSError, ValueError):
                continue
            session.extra["pinned"] = target
            self.store.save(session)
        self.refresh_sessions()
        self._toast(f"已{'置顶' if target else '取消置顶'} {len(ids)} 个会话")

    def export_markdown(self, session_id: str) -> None:
        try:
            session = self.store.load(session_id)
        except (OSError, ValueError):
            return
        default = f"{_safe_name(session.title)}.md"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出为 Markdown",
            defaultextension=".md",
            initialfile=default,
            filetypes=[("Markdown", "*.md")],
        )
        if not path:
            return
        Path(path).write_text(self.store.export_markdown(session), encoding="utf-8")
        self.status_left.configure(text=f"已导出：{path}")

    def export_backup(self, session_id: str) -> None:
        try:
            session = self.store.load(session_id)
        except (OSError, ValueError):
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="导出备份（可再次导入）",
            defaultextension=".json",
            initialfile=f"{_safe_name(session.title)}.json",
            filetypes=[("会话备份", "*.json")],
        )
        if not path:
            return
        write_export(session, path)
        self.status_left.configure(text=f"已导出备份：{path}")

    # ------------------------------------------------------------------ 设置 / 导入
    def open_settings(self) -> None:
        self._theme_at_open = self.cfg.theme
        self._font_at_open = (self.cfg.chat_font_family, self.cfg.chat_font_name)
        SettingsWindow(self, self.cfg, on_saved=self._on_settings_saved)

    def _on_settings_saved(self, cfg: Config) -> None:
        theme_changed = self._theme_at_open != cfg.theme
        font_changed = self._font_at_open != (cfg.chat_font_family, cfg.chat_font_name)
        self.cfg = cfg
        self.client = DeepSeekClient(cfg)
        if theme_changed:
            theme.apply(cfg.theme)
            self._rebuild_ui()
            # 网页外壳不会重建页面（只推主题色），但要让同次保存的排版/字体改动生效
            self.post("chat_style", fonts.style_payload(cfg, with_font=font_changed))
            self.status_left.configure(text="已切换主题，当前会话已保留")
            return
        self.input.model_menu.set(cfg.model)
        self.input.think_toggle.set(cfg.thinking)
        self.input.search_toggle.set(cfg.web_search)
        self.input.set_rich(cfg.rich_layout_default)
        # 排版立即生效；只有字体真的换了才重传 base64，其它调整走轻量增量
        self.post("chat_style", fonts.style_payload(cfg, with_font=font_changed))
        self.status_left.configure(text="设置已保存，阅读排版已应用")

    def _rebuild_ui(self) -> None:
        """切换主题时重建界面，保留当前会话与附件。"""
        if self.streaming:
            self.on_stop()
        if getattr(self, "_web", False):
            # 网页外壳不用重建（重建会把 WebView 一起销毁成白屏），推个主题色就行
            self.post("theme", {"dark": theme.is_dark()})
            return
        sid = self.session.id if (self.session is not None and self.session.messages) else None
        attachments = list(self.attachments)
        self.attachments.clear()
        for child in self.winfo_children():
            child.destroy()
        self._build()
        self.refresh_sessions()
        self.attachments = attachments
        self.input.show_attachments(attachments)
        if sid:
            try:
                self.open_session(sid)
            except Exception:
                self.new_chat(show_welcome=True)
        else:
            self.new_chat(show_welcome=True)

    def open_import(self) -> None:
        ImportWindow(self, store=self.store, on_imported=self._on_imported)

    def _on_imported(self, sessions: list[Session]) -> None:
        self.refresh_sessions()
        if sessions:
            latest = max(sessions, key=lambda s: s.updated_at)
            self.open_session(latest.id)
            self.status_left.configure(text=f"已导入 {len(sessions)} 个会话")

    # ------------------------------------------------------------------ 开关
    def _on_model_change(self, value: str) -> None:
        self.cfg.model = value
        self.cfg.save()
        if self.session:
            self.session.model = value

    def _on_think_change(self, value: bool) -> None:
        self.cfg.thinking = value
        self.cfg.save()

    def _on_search_change(self, value: bool) -> None:
        self.cfg.web_search = value
        self.cfg.save()

    def _on_rich_change(self, value: bool) -> None:
        self.cfg.rich_layout_default = value
        self.cfg.save()

    # ------------------------------------------------------------------ 附件
    def on_attach(self) -> None:
        if self._busy_upload:
            return
        if not self.cfg.has_key:
            messagebox.showinfo("需要 API Key", "文件解析走官方 Files API，请先在设置里填写 API Key。", parent=self)
            self.open_settings()
            return
        paths = filedialog.askopenfilenames(
            parent=self,
            title="选择文件（PDF / Word / PPT / Excel / 图片 / 文本）",
            filetypes=[
                ("支持的文档", "*.pdf *.doc *.docx *.ppt *.pptx *.xlsx *.xls *.txt *.md *.csv *.json *.epub"),
                ("所有文件", "*.*"),
            ],
        )
        if not paths:
            return
        self._upload_paths([str(x) for x in paths])

    def _upload_paths(self, paths: list[str]) -> None:
        if self._busy_upload:
            self._toast("上一个附件还在解析，稍等一下")
            return
        if not paths:
            return
        self._busy_upload = True
        self.input.set_hint("正在上传解析…")
        self.input.attach_btn.configure(state="disabled")
        rich = bool(self.input.rich_var.get())

        def worker() -> None:
            refs: list[FileRef] = []
            try:
                for raw in paths:
                    path = Path(raw)
                    ref = docs.upload_document(self.client, path, rich_layout=rich)
                    docs.attach_preview(ref, path)
                    refs.append(ref)
                self.q.put(("attached", refs, None))
            except DSException as exc:
                self.q.put(("attach_fail", str(exc), None))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("attach_fail", f"{type(exc).__name__}: {exc}", None))

        threading.Thread(target=worker, daemon=True).start()
        # 兜底：万一网络卡死，2 分钟后自动解锁，别让界面一直卡在"正在上传"
        self.after(120_000, self._upload_guard)

    def _upload_guard(self) -> None:
        if not self._busy_upload:
            return
        self._busy_upload = False
        self.input.set_hint("")
        self._toast("附件解析超时，可换个文件或检查网络后重试", error=True)

    def remove_attachment(self, ref: FileRef) -> None:
        self.attachments = [r for r in self.attachments if r.file_id != ref.file_id]
        self.input.show_attachments(self.attachments)

    # ------------------------------------------------------------------ 语音
    def on_voice_press(self) -> None:
        if self._voice_busy or self.recorder.is_recording:
            return
        if not self.cfg.has_key:
            self._first_run_hint()
            return
        if not audio.has_input_device():
            messagebox.showwarning("没有麦克风", "没有检测到录音设备，请检查系统的输入设备设置。", parent=self)
            return
        try:
            self.recorder.start()
        except audio.RecordError as exc:
            messagebox.showerror("无法录音", str(exc), parent=self)
            return
        self.input.set_recording(True, 0.0)
        self.status_left.configure(text="录音中…松开发送，Esc 取消")
        self._voice_tick()

    def _voice_tick(self) -> None:
        if not self.recorder.is_recording:
            self._voice_timer = None
            return
        elapsed = self.recorder.elapsed
        self.input.set_recording(True, elapsed)
        if self.recorder.reached_limit:
            self.on_voice_release(auto=True)
            return
        self._voice_timer = self.after(100, self._voice_tick)

    def on_voice_release(self, auto: bool = False) -> None:
        if self._voice_timer is not None:
            try:
                self.after_cancel(self._voice_timer)
            except Exception:
                pass
            self._voice_timer = None
        if not self.recorder.is_recording:
            return
        try:
            recording = self.recorder.stop()
        except audio.RecordError as exc:
            self.input.set_recording(False)
            messagebox.showerror("录音失败", str(exc), parent=self)
            return

        self.input.set_recording(False)
        self.input.show_attachments(self.attachments)
        if recording.seconds < 0.6:
            self.status_left.configure(text="录音太短，已取消（按住多说一会儿）")
            return

        self._voice_busy = True
        self.input.set_voice_busy(True)
        self.status_left.configure(text=f"正在识别 {recording.seconds:.1f} 秒语音…")
        note = "（已达 115 秒上限，自动停止）" if auto else ""

        def worker() -> None:
            try:
                result = asr.transcribe(self.client, recording.wav)
                self.q.put(("asr_ok", (result, recording.seconds), None))
            except DSException as exc:
                self.q.put(("asr_fail", asr.describe_error(exc), None))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("asr_fail", f"{type(exc).__name__}: {exc}", None))

        threading.Thread(target=worker, daemon=True).start()
        if note:
            self.status_left.configure(text=note)

    def _on_escape(self, _event=None) -> None:
        if self.recorder.is_recording:
            self.recorder.cancel()
            if self._voice_timer is not None:
                try:
                    self.after_cancel(self._voice_timer)
                except Exception:
                    pass
                self._voice_timer = None
            self.input.set_recording(False)
            self.input.show_attachments(self.attachments)
            self.status_left.configure(text="已取消录音")
            return
        if self._tts_block is not None:
            self.stop_speak()
            self.status_left.configure(text="已停止朗读")

    # ------------------------------------------------------------------ 缩放
    def _apply_zoom(self, step: int) -> None:
        """step: +1 放大 / -1 缩小。Tk 与页面两条入口都收敛到这里。"""
        factor = 1.1 if step > 0 else 1 / 1.1
        new = min(1.8, max(0.7, self.cfg.chat_zoom * factor))
        if abs(new - self.cfg.chat_zoom) < 0.001:
            return
        self.cfg.chat_zoom = round(new, 3)
        self.chat.zoom = self.cfg.chat_zoom
        self.chat.set_zoom(self.cfg.chat_zoom)
        # 缩放置盘做防抖，别每次滚轮都写文件
        job = getattr(self, "_zoom_save_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._zoom_save_job = self.after(500, self._do_save_zoom)
        self.status_left.configure(text=f"页面缩放 {int(round(self.cfg.chat_zoom * 100))}%")

    def _do_save_zoom(self) -> None:
        self._zoom_save_job = None
        try:
            self.cfg.save()
        except OSError:
            pass

    def _on_ctrl_wheel(self, event) -> None:
        delta = getattr(event, "delta", 0)
        if not delta:
            return
        if self._web:
            return  # Web 模式下滚轮由页面 JS 接管，避免 Tk 与页面重复缩放
        self._apply_zoom(1 if delta > 0 else -1)
        return "break"

    def _on_ctrl_zero(self, _event=None) -> None:
        self.cfg.chat_zoom = 1.0
        self.chat.zoom = 1.0
        self.chat.set_zoom(1.0)
        job = getattr(self, "_zoom_save_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._zoom_save_job = self.after(500, self._do_save_zoom)
        self.status_left.configure(text="页面缩放 100%")
        return "break"

    # ------------------------------------------------------------------ 引用选区
    def _add_quote(self, data: dict) -> None:
        text = str(data.get("picked") or "").strip()
        if not text:
            return
        role = str(data.get("context", [{}])[-1].get("role") or "") if isinstance(data.get("context"), list) else ""
        ctx = []
        raw = data.get("context")
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ctx.append({"role": str(item.get("role") or ""), "text": str(item.get("text") or "")[:1200]})
        self.quotes.append({"text": text[:2000], "role": role, "context": ctx})
        self.input.show_quotes(self.quotes)
        self._toast("已引用，发送消息时会带上这段文字和上下文")

    def _quote_prompt(self) -> str:
        """把引用及上下文拼成一段 system 说明，让模型知道引用内容和前后语境。"""
        if not self.quotes:
            return ""
        lines = ["用户在提问时引用了下面这些本对话中的文字（含其上下文）。请结合这些引用及语境回答用户的新问题："]
        for i, q in enumerate(self.quotes, 1):
            lines.append(f"\n【引用 {i}】" + (f"（{q['role']}的消息）" if q.get("role") else ""))
            lines.append(q.get("text", ""))
            ctx = q.get("context") or []
            if ctx:
                lines.append("引用所在语境（前一条 / 本条 / 后一条）：")
                for c in ctx:
                    lines.append(f"- {c.get('role') or '消息'}：{c.get('text', '')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 朗读
    def _speak_selection(self, text: str) -> None:
        """朗读选中的一段文字：复用 on_speak，用一次性 block 承载。"""
        class _TmpBlock:
            def __init__(self, t: str) -> None:
                self._t = t
                self._speak_state = "idle"

            def speak_text(self) -> str:
                return self._t

            def set_speak_state(self, state: str) -> None:
                self._speak_state = state

        self.on_speak(_TmpBlock(text))

    def on_speak(self, block, auto: bool = False) -> None:
        """点朗读按钮：同一个块再点一次就是停止。"""
        if block is None:
            return
        if block is self._tts_block:
            self.stop_speak()
            self.status_left.configure(text="已停止朗读")
            return
        if not self.cfg.has_key:
            self._first_run_hint()
            return
        if not player.available():
            messagebox.showinfo("暂不支持", "朗读目前只支持 Windows。", parent=self)
            return

        text = tts.prepare_text(block.speak_text())
        if not text:
            self.status_left.configure(text="这段回答没有可朗读的文字（可能主要是代码或表格）")
            return

        self.stop_speak()
        chunks = tts.split_chunks(text)
        self._tts_gen += 1
        gen = self._tts_gen
        self._tts_block = block
        self._tts_auto = auto
        block.set_speak_state("loading")
        hint = f"正在合成语音（共 {len(chunks)} 段）…" if len(chunks) > 1 else "正在合成语音…"
        self.status_left.configure(text=hint)
        voice = self.cfg.tts_voice
        client = self.client

        def worker() -> None:
            pending = None
            try:
                for idx in range(len(chunks)):
                    if gen != self._tts_gen:
                        return
                    result = pending
                    pending = None
                    if result is None:
                        result = tts.synthesize(client, chunks[idx], voice_id=voice)
                    if gen != self._tts_gen:
                        return
                    self.q.put(("tts_play", (gen, result, idx + 1, len(chunks)), None))
                    if gen != self._tts_gen:
                        return
                    try:
                        seconds = self.player.play(result.audio)
                    except player.PlaybackError as exc:
                        self.q.put(("tts_fail", (gen, str(exc)), None))
                        return
                    # 播放期间先把下一段合成好，段与段之间就不会空等
                    if idx + 1 < len(chunks) and gen == self._tts_gen:
                        try:
                            pending = tts.synthesize(client, chunks[idx + 1], voice_id=voice)
                        except DSException:
                            pending = None
                    if not self.player.wait(seconds + 30):
                        return
                self.q.put(("tts_done", gen, None))
            except DSException as exc:
                self.q.put(("tts_fail", (gen, tts.describe_error(exc)), None))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("tts_fail", (gen, f"{type(exc).__name__}: {exc}"), None))

        threading.Thread(target=worker, daemon=True).start()

    def stop_speak(self) -> None:
        """停掉朗读并让后台线程失效。会安全处理「本来没在播」的情况。"""
        self._tts_gen += 1
        self._tts_auto = False
        try:
            self.player.stop()
        except Exception:
            pass
        block, self._tts_block = self._tts_block, None
        if block is not None:
            try:
                block.set_speak_state("idle")
            except Exception:
                pass

    def _on_tts_play(self, data) -> None:
        gen, result, index, total = data
        if gen != self._tts_gen:
            return
        block = self._tts_block
        if block is None:
            return
        try:
            block.set_speak_state("playing")
        except Exception:
            self.stop_speak()
            return
        usd = result.cost()
        label = f"朗读 {index}/{total}" if total > 1 else "朗读"
        seconds = max(1, round(result.seconds))
        self.status_left.configure(
            text=f"{label} · {seconds} 秒音频 · {result.billed} 字符 · 约 ¥{usd * self.cfg.cny_rate:.5f}"
        )

    def _on_tts_done(self, gen) -> None:
        if gen != self._tts_gen:
            return
        block, self._tts_block = self._tts_block, None
        if block is not None:
            try:
                block.set_speak_state("idle")
            except Exception:
                pass
        self.status_left.configure(text="朗读结束")

    def _on_tts_fail(self, data) -> None:
        gen, message = data
        if gen != self._tts_gen:
            return
        block, self._tts_block = self._tts_block, None
        auto = self._tts_auto
        self._tts_auto = False
        if block is not None:
            try:
                block.set_speak_state("idle")
            except Exception:
                pass
        self.status_left.configure(text=str(message))
        if not auto:
            messagebox.showerror("朗读失败", str(message), parent=self)

    def _auto_read(self, block, sid: str | None) -> None:
        if not self.cfg.auto_read or self.streaming or not self._current(sid):
            return
        if self._tts_block is not None:
            return
        if not block.speak_text():
            return
        self.on_speak(block, auto=True)

    # ------------------------------------------------------------------ 检索侧栏
    def _reset_search_panel(self) -> None:
        self._search_groups = []
        self._search_cites = []
        try:
            self.search_panel.set_results([], [])
            self._set_panel(False)
        except Exception:
            pass

    def toggle_search_panel(self) -> None:
        self._set_panel(not self._panel_open)

    def _apply_panel_width(self, width: int) -> None:
        """侧栏宽度由 grid 列的 minsize 决定（CTkFrame 自己的 width 会被子控件覆盖）。"""
        self._panel_width = int(width)
        if getattr(self, "_web", False):
            return
        # 注意：面板收起时要不留 minsize，否则空列也会占着宽度，把对话区压窄。
        self._panel_width = int(width)
        try:
            scale = float(self.main._get_widget_scaling()) or 1.0
        except Exception:
            scale = 1.0
        minsize = int(round(width * scale)) if getattr(self, "_panel_open", False) else 0
        try:
            self.main.grid_columnconfigure(1, minsize=minsize)
        except Exception:
            pass

    def _on_panel_resize(self, width: int) -> None:
        """拖拽侧栏宽度：立即生效，停手 0.4 秒后再落盘，避免频繁写配置。"""
        self.cfg.panel_width = int(width)
        self._apply_panel_width(width)
        if getattr(self, "_panel_save_job", None):
            try:
                self.after_cancel(self._panel_save_job)
            except Exception:
                pass
        self._panel_save_job = self.after(400, self._save_panel_width)

    def _save_panel_width(self) -> None:
        self._panel_save_job = None
        try:
            self.cfg.save()
        except Exception:
            pass

    def _set_panel(self, open_: bool) -> None:
        self._panel_open = open_
        if open_:
            self.search_panel.grid(row=0, column=1, rowspan=6, sticky="nsew")
            self.search_panel.set_visible(True)
        else:
            self.search_panel.set_visible(False)
            self.search_panel.grid_remove()
        self._apply_panel_width(getattr(self, "_panel_width", self.cfg.panel_width))
        self._update_source_btn()
        if self._welcome_mode:
            self._hero_geo = None
            self._place_hero()

    def _update_source_btn(self) -> None:
        n = len(self._search_cites) + sum(len(g.get("sources") or []) for g in self._search_groups)
        self.source_btn.configure(text=f"来源 {n}" if n else "来源")

    def _build_search_results(self, stream) -> None:
        groups: list[dict] = []
        for info in getattr(stream, "tool_calls", []) or []:
            group = _group_from_info(
                {
                    "kind": info.kind,
                    "queries": info.queries,
                    "url": info.url,
                    "title": info.title,
                    "sources": info.sources,
                }
            )
            if group is not None:
                groups.append(group)
        cites = getattr(stream, "citations", []) or []
        self._search_groups = groups
        self._search_cites = cites
        self.search_panel.set_results(groups, cites)
        if (groups or cites) and not self._panel_open:
            self._set_panel(True)

    def _append_live_group(self, payload: dict) -> None:
        """流式过程中把联网动作追加到侧栏，这样回答还没结束也能点开看。"""
        group = _group_from_info(payload)
        if group is None:
            return
        known = {s.get("url") for g in self._search_groups for s in (g.get("sources") or [])}
        fresh = [s for s in group["sources"] if s.get("url") and s["url"] not in known]
        if not fresh and not group.get("query"):
            return
        self._search_groups.append({"query": group["query"], "sources": fresh})
        if self._panel_open:
            self.search_panel.set_results(self._search_groups, self._search_cites)
        self._update_source_btn()

    def show_message_sources(self, index=None, note: str = "") -> None:
        """点消息里的「联网搜索」这一行：在右侧栏展示该轮抓到的来源。"""
        groups: list[dict] = []
        cites: list[dict] = []
        notes: list[str] = []
        msgs = self.session.messages if self.session is not None else []
        try:
            idx = int(index)
        except (TypeError, ValueError):
            idx = None

        if idx is not None and 0 <= idx < len(msgs):
            msg = msgs[idx]
            sources = msg.get("_sources") or _sources_from_tool_calls(msg.get("server_tool_calls"))
            cites = msg.get("_citations") or []
            notes = msg.get("_notes") or []
            if sources:
                groups = [{"query": _query_from_note(note) or "本轮联网来源", "sources": sources}]
            self._search_groups = groups
            self._search_cites = cites
        else:
            # 正在流式输出的这一轮还没写进会话，用过程中累积的数据
            groups = [dict(g) for g in self._search_groups]
            cites = list(self._search_cites)

        if not groups and not cites and note:
            notes = notes or [note]

        self.search_panel.set_results(groups, cites, notes)
        self._set_panel(True)
        if not groups and not cites:
            self.status_left.configure(text="这一轮没有保存下来的来源链接（联网记录只有搜索动作）")

    def _collect_sources(self, stream) -> list[dict]:
        """把联网搜索/网页读取到的来源整理成 {title,url} 列表，供历史回看。"""
        out: list[dict] = []
        for info in getattr(stream, "tool_calls", []) or []:
            if info.kind in ("search", "deep_search"):
                for s in info.sources or []:
                    if s.get("url"):
                        out.append({"title": s.get("title") or s.get("url"), "url": s.get("url")})
            elif info.kind in ("read_link", "open_page", "find_in_page") and info.url:
                out.append({"title": info.title or info.url, "url": info.url})
        seen: set[str] = set()
        dedup: list[dict] = []
        for s in out:
            if s["url"] not in seen:
                seen.add(s["url"])
                dedup.append(s)
        return dedup

    def _current_opts(self) -> dict:
        return {
            "model": self.cfg.model,
            "thinking": bool(self.input.think_toggle.get()),
            "reasoning_effort": self.cfg.reasoning_effort,
            "web_search": bool(self.input.search_toggle.get()),
            "read_url": self.cfg.read_url,
        }

    def copy_user(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_left.configure(text="已复制")

    def edit_message(self, msg_index, text: str) -> None:
        if self.streaming or self.session is None:
            return
        if msg_index is None or msg_index >= len(self.session.messages):
            return
        if self.session.messages[msg_index].get("role") != "user":
            return
        self._editing_index = msg_index
        self.input.set_text(text)
        self.input.set_hint("已载入待编辑消息，发送后将从这一条重新生成")
        self.status_left.configure(text="编辑中：发送后将丢弃这条消息及之后的回复")

    def delete_message(self, index) -> None:
        """删除单条消息（历史/当前会话都支持）。"""
        if self.streaming or self.session is None:
            return
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        msgs = self.session.messages
        if not (0 <= index < len(msgs)):
            return
        del msgs[index]
        self.session.updated_at = datetime.now().timestamp()
        self.store.save(self.session)
        self.chat.render_history(msgs, model=self.session.model or self.cfg.model, cny_rate=self.cfg.cny_rate)
        self._set_mode(bool(msgs))
        self.refresh_sessions()
        self.status_left.configure(text="已删除该条消息")

    def regenerate(self) -> None:
        if self.streaming or self.session is None:
            return
        msgs = self.session.messages
        if not msgs or msgs[-1].get("role") != "assistant":
            return
        self.stop_speak()
        msgs.pop()
        self.store.save(self.session)
        self.chat.render_history(self.session.messages, model=self.session.model or self.cfg.model, cny_rate=self.cfg.cny_rate)
        self._set_mode(False)
        self.status_left.configure(text="重新生成中…")
        messages = self.session.to_api_messages(self._system_prompt())
        self._begin_stream(self.session, messages, self._current_opts())

    # ------------------------------------------------------------------ 发送
    def on_send(self, text: str) -> None:
        if self.streaming:
            return
        self.stop_speak()
        if not self.cfg.has_key:
            self._first_run_hint()
            return
        if self.session is None:
            self.new_chat()

        session = self.session
        editing = self._editing_index
        self._editing_index = None

        file_ids = [a.file_id for a in self.attachments]
        att_meta = [{"name": a.filename, "file_id": a.file_id} for a in self.attachments]

        if (
            editing is not None
            and 0 <= editing < len(session.messages)
            and session.messages[editing].get("role") == "user"
        ):
            del session.messages[editing:]
            self.chat.render_history(session.messages, model=session.model or self.cfg.model, cny_rate=self.cfg.cny_rate)

        # 引用快照：气泡上可见 + 写进本地历史 + 作为上下文发给模型（三处都要用）
        quotes_snapshot = [
            {"text": q.get("text", ""), "role": q.get("role", "")}
            for q in self.quotes
        ]
        quote_prompt = self._quote_prompt()   # 必须在清空 self.quotes 之前生成

        user_msg = session.add_user(text, file_ids=file_ids)
        if quotes_snapshot:
            user_msg["_quotes"] = quotes_snapshot   # "_" 前缀：to_api_messages 会自动剔除，不重复发送
            self._toast(f"已附上 {len(quotes_snapshot)} 段引用：显示在气泡上，并随本次提问发送给模型")
        self._set_mode(False)
        self.chat.add_user(
            text, attachments=att_meta, msg_index=len(session.messages) - 1,
            quotes=quotes_snapshot,
        )
        self.input.clear()
        self.attachments.clear()
        self.input.show_attachments([])
        self.quotes.clear()
        self.input.show_quotes([])
        self.store.save(session)
        self._set_title(session.title)
        self.refresh_sessions()

        messages = session.to_api_messages(self._system_prompt())
        # 引用说明合并进第一条 system 消息，避免部分服务端只取首条 system 而丢掉引用
        if quote_prompt:
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = ((messages[0]["content"] or "") + "\n\n" + quote_prompt).strip()
            else:
                messages.insert(0, {"role": "system", "content": quote_prompt})
        self._begin_stream(session, messages, self._current_opts())

    def _begin_stream(self, session: Session, messages: list[dict], opts: dict) -> None:
        self.streaming = True
        self.stop_flag.clear()
        self._stream_sid = session.id
        # 新一轮：侧栏清空上一轮的数据（面板开着的话换成本轮空状态）
        self._search_groups = []
        self._search_cites = []
        if self._panel_open:
            self.search_panel.set_results([], [])
        self._update_source_btn()
        self._block = self.chat.add_assistant(model=opts.get("model", self.cfg.model), index=len(session.messages))
        self.input.set_busy(True)
        self.status_left.configure(text="正在生成…")
        self.status_right.configure(text="按「停止」可中断，已生成内容会保留")

        def worker() -> None:
            try:
                stream = self.client.chat_stream(messages, **opts)
                for ev in stream:
                    if self.stop_flag.is_set():
                        break
                    if ev.kind == "content":
                        self.q.put(("content", ev.data, session.id))
                    elif ev.kind == "reasoning":
                        self.q.put(("reasoning", ev.data, session.id))
                    elif ev.kind == "tool":
                        info = ev.data
                        self.q.put(("tool", info.describe(), session.id))
                        self.q.put(
                            (
                                "toolinfo",
                                {
                                    "kind": getattr(info, "kind", ""),
                                    "queries": list(getattr(info, "queries", []) or []),
                                    "url": getattr(info, "url", ""),
                                    "title": getattr(info, "title", ""),
                                    "sources": list(getattr(info, "sources", []) or []),
                                },
                                session.id,
                            )
                        )
                    elif ev.kind == "error":
                        self.q.put(("stream_error", str(ev.data), session.id))
                self.q.put(("finish", stream, session.id))
            except DSException as exc:
                self.q.put(("fail", exc, session.id))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("fail", DSException(f"{type(exc).__name__}: {exc}", code="ui_error"), session.id))

        threading.Thread(target=worker, daemon=True).start()

    def on_stop(self) -> None:
        if not self.streaming:
            return
        self.stop_flag.set()
        self.status_left.configure(text="正在停止…")

    # ------------------------------------------------------------------ 事件循环
    def _poll(self) -> None:
        wv = getattr(self, "_wv", None)
        if wv is not None:
            try:
                wv.poll()
            except Exception:
                pass
        try:
            # 一次最多取一批，并且把连续的内容增量合并成一条：
            # 流式时每个 delta 都单独走一次 COM + 一次 DOM 重写会让 UI 线程忙不过来，
            # 表现就是「生成回答时输入框打字卡」。
            batch: list[tuple] = []
            while len(batch) < 240:
                try:
                    batch.append(self.q.get_nowait())
                except queue.Empty:
                    break
            merged: list[tuple] = []
            for kind, data, sid in batch:
                if (
                    merged
                    and merged[-1][0] == kind
                    and merged[-1][2] == sid
                    and kind in ("content", "reasoning")
                ):
                    merged[-1] = (kind, merged[-1][1] + data, sid)
                else:
                    merged.append((kind, data, sid))
            for kind, data, sid in merged:
                self._handle(kind, data, sid)
        except Exception as exc:  # noqa: BLE001
            self.status_left.configure(text=f"界面异常：{exc}")
        self.after(35, self._poll)

    def _current(self, sid: str | None) -> bool:
        return bool(self.session and sid and self.session.id == sid)

    def _handle(self, kind: str, data, sid: str | None) -> None:
        if kind == "content":
            if self._current(sid) and self._block:
                self._block.append_content(data)
            return
        if kind == "reasoning":
            if self._current(sid) and self._block:
                self._block.append_reasoning(data)
            return
        if kind == "tool":
            if self._current(sid) and self._block:
                self._block.add_note(str(data))
            return
        if kind == "toolinfo":
            if self._current(sid) and isinstance(data, dict):
                self._append_live_group(data)
            return
        if kind == "stream_error":
            if self._current(sid) and self._block:
                self._block.set_error(str(data))
            self.status_left.configure(text=str(data))
            return
        if kind == "finish":
            self._finish(data, sid)
            return
        if kind == "fail":
            self._fail(data, sid)
            return
        if kind == "attached":
            refs = data or []
            self.attachments.extend(refs)
            self._busy_upload = False
            self.input.attach_btn.configure(state="normal")
            self.input.set_hint("")
            self.input.show_attachments(self.attachments)
            if refs:
                self.post("toast", {"text": f"已添加 {len(refs)} 个附件"})
            return
        if kind == "attach_fail":
            self._busy_upload = False
            self.input.attach_btn.configure(state="normal")
            self.input.set_hint("")
            self.input.show_attachments(self.attachments)
            self._toast(f"附件失败：{data}", error=True)
            return
        if kind == "status":
            self.status_left.configure(text=str(data))
            return
        if kind == "tts_play":
            self._on_tts_play(data)
            return
        if kind == "tts_done":
            self._on_tts_done(data)
            return
        if kind == "tts_fail":
            self._on_tts_fail(data)
            return
        if kind == "asr_ok":
            self._voice_busy = False
            self.input.set_voice_busy(False)
            result, seconds = data
            if result.text:
                self.input.append_text(result.text)
                usd = result.cost()
                self.status_left.configure(
                    text=f"语音识别 {seconds:.1f}s · {len(result.text)} 字 · 约 ¥{usd * self.cfg.cny_rate:.5f}"
                )
            else:
                self.status_left.configure(text="没听清，请再说一次")
            self.input.show_attachments(self.attachments)
            return
        if kind == "asr_fail":
            self._voice_busy = False
            self.input.set_voice_busy(False)
            self.status_left.configure(text=str(data))
            self.input.show_attachments(self.attachments)
            messagebox.showerror("语音识别失败", str(data), parent=self)
            return

    def _finish(self, stream, sid: str) -> None:
        self.streaming = False
        self.input.set_busy(False)
        stopped = self.stop_flag.is_set()
        self.stop_flag.clear()

        session = self.session if self._current(sid) else self._load_silent(sid)
        usage = getattr(stream, "usage", Usage())
        footer = ""
        cost_text = ""
        if usage:
            cost = usage.cost(self.cfg.model)
            footer = usage.summary()
            cost_text = f"≈ {_fmt_money(cost.cny(self.cfg.cny_rate))}"
            self.last_usage = usage
            self.input.set_cost(f"上次 {usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens)} tokens · {cost_text}")

        if session is not None:
            msg = session.add_assistant(stream.assistant_message(), citations=getattr(stream, "citations", None))
            if usage:
                msg["_usage"] = usage.to_dict()
            sources = self._collect_sources(stream)
            if sources:
                msg["_sources"] = sources
            if self.cfg.save_history:
                self.store.save(session)

        auto_block = None
        if self._current(sid) and self._block:
            if stopped:
                self._block.add_note("（已手动停止生成）")
            self._block.finalize(
                citations=getattr(stream, "citations", None), footer=footer, cost_text=cost_text
            )
            if usage:
                self.status_left.configure(
                    text=f"本次 {usage.total_tokens or (usage.prompt_tokens + usage.completion_tokens)} tokens · 约 {cost_text}"
                )
            else:
                self.status_left.configure(text="")
            remaining = len(getattr(stream, "text", "") or "")
            self.status_right.configure(text=f"本次输出 {remaining} 字" if remaining else "")
            auto_block = self._block
        else:
            self.status_left.configure(text="另一会话的回复已保存")

        self._block = None
        self._stream_sid = None
        if self._current(sid):
            self._build_search_results(stream)
        self.refresh_sessions()

        if auto_block is not None and self.cfg.auto_read and not stopped:
            self.after(200, lambda b=auto_block, i=sid: self._auto_read(b, i))

    def _fail(self, exc: DSException, sid: str | None) -> None:
        self.streaming = False
        self.input.set_busy(False)
        self.stop_flag.clear()
        text = str(exc)
        if self._current(sid) and self._block:
            self._block.set_error(text)
        self.status_left.configure(text=text)
        self._block = None
        self._stream_sid = None
        if exc.code in ("missing_api_key", "http_401"):
            if messagebox.askyesno("API Key 无效", f"{text}\n\n现在去设置里修改吗？", parent=self):
                self.open_settings()

    def _load_silent(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        try:
            return self.store.load(sid)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------ 关闭
    def _on_close(self) -> None:
        if self.streaming:
            if not messagebox.askyesno("还在生成", "正在生成回复，确定退出吗？已生成的部分会保存。", parent=self):
                return
            self.stop_flag.set()
            self.after(120, self._really_close)
            return
        self._really_close()

    def _really_close(self) -> None:
        wv = getattr(self, "_wv", None)
        if wv is not None:
            try:
                wv.close()
            except Exception:
                pass
            self._wv = None
        try:
            if self.recorder.is_recording:
                self.recorder.cancel()
        except Exception:
            pass
        try:
            self.player.close()
        except Exception:
            pass
        try:
            if self.session and self.session.messages and self.cfg.save_history:
                self.store.save(self.session)
        except Exception:
            pass
        self.destroy()


def _group_from_info(info: dict) -> dict | None:
    """把一次联网动作整理成侧栏里的一个分组。"""
    kind = str(info.get("kind") or "")
    queries = [str(q) for q in (info.get("queries") or []) if q]
    url = str(info.get("url") or "")
    title = str(info.get("title") or "")
    sources = [s for s in (info.get("sources") or []) if isinstance(s, dict) and s.get("url")]
    if kind in ("search", "deep_search"):
        return {"query": "搜索：" + (" / ".join(queries) if queries else "（未命名）"), "sources": sources}
    if kind in ("read_link", "open_page", "find_in_page") and url:
        return {"query": f"读取网页：{title or url}", "sources": [{"title": title or url, "url": url}]}
    return None


def _sources_from_tool_calls(steps) -> list[dict]:
    """从历史消息里的 server_tool_calls 还原来源列表（老会话没存 _sources 时用）。"""
    out: list[dict] = []
    seen: set[str] = set()

    def add(title, url) -> None:
        url = str(url or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append({"title": str(title or url), "url": url})

    for step in steps or []:
        if not isinstance(step, dict):
            continue
        for call in step.get("calls") or []:
            if not isinstance(call, dict):
                continue
            action = call.get("action") or {}
            page = call.get("page") or {}
            for src in call.get("sources") or []:
                if isinstance(src, dict):
                    add(src.get("title"), src.get("url"))
            add(page.get("title") or action.get("title"), action.get("url") or page.get("url"))
    return out


def _clip_title(text: str, limit: int = 46) -> str:
    """顶栏标题按显示宽度截断（中文算 2），避免长标题把右侧按钮挤出去。"""
    text = (text or "").replace("\n", " ").strip() or "新对话"
    acc = 0
    for i, ch in enumerate(text):
        acc += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if acc > limit:
            return text[:i].rstrip() + "…"
    return text


def _query_from_note(note: str) -> str:
    """笔记形如「联网搜索：关键词（5 条结果）」，去掉末尾的结果数。"""
    note = (note or "").strip()
    if note.endswith("）") and "（" in note:
        note = note[: note.rindex("（")].strip()
    return note


def _fmt_money(value: float) -> str:
    """金额显示：大额 4 位小数，小额保留到 6 位，避免一长串 0。"""
    if value >= 0.01:
        return f"¥{value:.4f}"
    if value >= 0.0001:
        return f"¥{value:.5f}"
    return f"¥{value:.6f}"


def _safe_name(title: str) -> str:
    cleaned = "".join(ch for ch in (title or "会话") if ch not in '\\/:*?"<>|').strip()
    return (cleaned or "会话")[:40]
