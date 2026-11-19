"""设置窗口：API Key、模型、开关、代理、数据目录、连接测试。"""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from pathlib import Path

import customtkinter as ctk

from dskit.client import DeepSeekClient
from dskit.config import AVAILABLE_MODELS, EFFORT_LEVELS, Config, data_dir
from dskit.errors import DSException
from dskit.tts import VOICES

from . import theme
from .widgets import LabeledToggle

C = theme.COLORS


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, cfg: Config, *, on_saved=None) -> None:
        super().__init__(master)
        self.cfg = cfg
        self.on_saved = on_saved
        self.title("设置")
        self.geometry(self._center(760, 720))
        self.minsize(700, 620)
        self.configure(fg_color=C["bg"])
        self.transient(master)
        self._testing = False

        self._build()
        self.after(80, self._focus_self)

    def _sync_temp_state(self, value=None) -> None:
        """思考模式下 temperature 不生效：置灰 + 文字提示。"""
        think = bool(self.think_sw.get()) if value is None else bool(value)
        try:
            self.temp_entry.configure(state="disabled" if think else "normal")
            self.temp_state.configure(text="思考模式下不生效" if think else "")
        except Exception:
            pass

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
        self.grab_set()
        try:
            self.key_entry.focus_set()
        except Exception:
            pass

    # ------------------------------------------------------------------ 布局
    def _build(self) -> None:
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 4))
        ctk.CTkLabel(head, text="设置", font=theme.ctk_font(20, "bold"), text_color=C["text"]).pack(side="left")
        ctk.CTkLabel(
            head,
            text=f"配置文件：{Config.path()}",
            font=theme.ctk_font(10),
            text_color=C["text_dim"],
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=C["border"])
        scroll.pack(fill="both", expand=True, padx=14, pady=6)

        # ---- 外观 ----
        self._section(scroll, "外观")
        theme_row = self._row(scroll, "主题")
        self.theme_var = tk.StringVar(value="深色" if self.cfg.theme == "dark" else "浅色")
        ctk.CTkOptionMenu(
            theme_row,
            values=["浅色", "深色"],
            variable=self.theme_var,
            width=140,
            height=32,
            corner_radius=8,
            fg_color=C["card"],
            button_color=C["border"],
            button_hover_color=C["sidebar_hover"],
            text_color=C["text"],
            dropdown_fg_color=C["surface"],
            dropdown_text_color=C["text"],
            dropdown_hover_color=C["sidebar_hover"],
            font=theme.ctk_font(12),
        ).pack(side="left")
        self._hint(scroll, "切换主题会重建界面，但当前会话和附件都会保留。")

        # ---- 账号 ----
        self._section(scroll, "账号")
        key_row = self._row(scroll, "API Key")
        self.key_entry = ctk.CTkEntry(
            key_row,
            height=34,
            corner_radius=8,
            border_color=C["border"],
            fg_color=C["surface"],
            text_color=C["text"],
            font=theme.ctk_font(12),
            show="•",
        )
        self.key_entry.pack(side="left", fill="x", expand=True)
        if self.cfg.api_key:
            self.key_entry.insert(0, self.cfg.api_key)
        self.show_key = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            key_row,
            text="显示",
            variable=self.show_key,
            width=60,
            checkbox_width=15,
            checkbox_height=15,
            corner_radius=4,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(11),
            command=self._toggle_key,
        ).pack(side="left", padx=(10, 0))

        link_row = ctk.CTkFrame(scroll, fg_color="transparent")
        link_row.pack(fill="x", padx=6, pady=(0, 6))
        link = ctk.CTkLabel(
            link_row,
            text="到 platform.deepseek.com 申请 API Key（sk- 开头）",
            font=theme.ctk_font(11),
            text_color=C["accent"],
            cursor="hand2",
        )
        link.pack(side="left", padx=(120, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open("https://platform.deepseek.com/api_keys"))

        # ---- 生成参数 ----
        self._section(scroll, "生成参数")
        temp_row = self._row(scroll, "temperature")
        self.temp_entry = ctk.CTkEntry(
            temp_row, width=110, height=32, corner_radius=8,
            border_color=C["border"], fg_color=C["surface"], text_color=C["text"], font=theme.ctk_font(12),
        )
        self.temp_entry.pack(side="left")
        self.temp_entry.insert(0, f"{self.cfg.temperature:g}")
        self.temp_state = ctk.CTkLabel(
            temp_row, text="", font=theme.ctk_font(10), text_color=C["text_dim"]
        )
        self.temp_state.pack(side="left", padx=(10, 0))
        self._hint(scroll, "0 ~ 2，越大越发散。开启深度思考时该参数不生效，会被忽略。")

        top_row = self._row(scroll, "top_p")
        self.top_entry = ctk.CTkEntry(
            top_row, width=110, height=32, corner_radius=8,
            border_color=C["border"], fg_color=C["surface"], text_color=C["text"], font=theme.ctk_font(12),
        )
        self.top_entry.pack(side="left")
        self.top_entry.insert(0, f"{self.cfg.top_p:g}")
        self._hint(scroll, "核采样阈值 0.01 ~ 1。deepseek-flash 在思考模式下最低 0.95，低于 0.95 会按 0.95 发送。")

        max_row = self._row(scroll, "最大输出")
        self.max_entry = ctk.CTkEntry(
            max_row, width=110, height=32, corner_radius=8,
            border_color=C["border"], fg_color=C["surface"], text_color=C["text"], font=theme.ctk_font(12),
        )
        self.max_entry.pack(side="left")
        self.max_entry.insert(0, str(self.cfg.max_tokens or 0))
        ctk.CTkLabel(max_row, text="tokens，0 = 服务端默认", font=theme.ctk_font(10), text_color=C["text_dim"]).pack(
            side="left", padx=(10, 0)
        )

        sys_row = self._row(scroll, "系统提示词")
        self.sys_text = ctk.CTkTextbox(
            sys_row, height=88, width=380, corner_radius=8, border_width=1,
            border_color=C["border"], fg_color=C["surface"], text_color=C["text"], font=theme.ctk_font(12),
        )
        self.sys_text.pack(side="left", fill="x", expand=True)
        self.sys_text.insert("1.0", self.cfg.system_prompt or "")
        self._hint(scroll, "留空则使用内置提示词；填写后会完全替换内置提示词。")

        stop_row = self._row(scroll, "停止词")
        self.stop_text = ctk.CTkTextbox(
            stop_row, height=64, width=380, corner_radius=8, border_width=1,
            border_color=C["border"], fg_color=C["surface"], text_color=C["text"], font=theme.ctk_font(12),
        )
        self.stop_text.pack(side="left", fill="x", expand=True)
        self.stop_text.insert("1.0", "\n".join(self.cfg.stop_words or []))
        self._hint(scroll, "一行一个，最多 16 个；模型生成到这些词就停止。")

        # ---- 语音 ----
        self._section(scroll, "语音")
        voice_row = self._row(scroll, "朗读音色")
        self.voice_var = tk.StringVar(value=VOICES.get(self.cfg.tts_voice, VOICES["stella"]))
        ctk.CTkOptionMenu(
            voice_row,
            values=list(VOICES.values()),
            variable=self.voice_var,
            width=220,
            height=32,
            corner_radius=8,
            fg_color=C["card"],
            button_color=C["border"],
            button_hover_color=C["sidebar_hover"],
            text_color=C["text"],
            dropdown_fg_color=C["surface"],
            dropdown_text_color=C["text"],
            dropdown_hover_color=C["sidebar_hover"],
            font=theme.ctk_font(12),
        ).pack(side="left")
        self.auto_read_sw = self._switch(scroll, "新回答自动朗读", self.cfg.auto_read)
        self._hint(
            scroll,
            "朗读按字符计费：每万字符 $0.45（官方限时 5 折 $0.225），一个汉字算 2 个字符。"
            "音频只在内存里播放，不保存文件。",
        )

        # ---- 默认行为 ----
        self._section(scroll, "默认行为")
        self.think_sw = self._switch(scroll, "默认开启深度思考", self.cfg.thinking, command=self._sync_temp_state)
        self.search_sw = self._switch(scroll, "默认开启联网搜索", self.cfg.web_search)
        self.read_sw = self._switch(scroll, "自动读取消息里的网页链接", self.cfg.read_url)
        self.show_reason_sw = self._switch(scroll, "界面显示思考过程", self.cfg.show_reasoning)
        self.save_history_sw = self._switch(scroll, "自动保存本地对话历史", self.cfg.save_history)
        self.rich_sw = self._switch(scroll, "文件默认按「含图表识别」解析", self.cfg.rich_layout_default)
        self._hint(scroll, "联网搜索默认由模型自行判断是否需要搜索；关掉则完全不联网。")
        self._sync_temp_state()

        # ---- 网络 ----
        self._section(scroll, "网络")
        proxy_row = self._row(scroll, "代理")
        self.proxy_entry = ctk.CTkEntry(
            proxy_row,
            height=32,
            corner_radius=8,
            border_color=C["border"],
            fg_color=C["surface"],
            text_color=C["text"],
            placeholder_text="http://127.0.0.1:7890（留空走系统设置）",
            placeholder_text_color=C["text_dim"],
            font=theme.ctk_font(12),
        )
        self.proxy_entry.pack(side="left", fill="x", expand=True)
        if self.cfg.proxy:
            self.proxy_entry.insert(0, self.cfg.proxy)

        timeout_row = self._row(scroll, "超时（秒）")
        self.timeout_entry = ctk.CTkEntry(timeout_row, width=110, height=32, corner_radius=8, border_color=C["border"], fg_color=C["surface"], text_color=C["text"], font=theme.ctk_font(12))
        self.timeout_entry.pack(side="left")
        self.timeout_entry.insert(0, str(self.cfg.timeout))
        self._hint(scroll, "上传大文件解析时服务端最长要 120 秒，建议保持 120 以上。")

        # ---- 数据 ----
        self._section(scroll, "数据")
        dir_row = self._row(scroll, "数据目录")
        ctk.CTkLabel(
            dir_row,
            text=str(data_dir()),
            font=theme.ctk_font(11),
            text_color=C["text_soft"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            dir_row,
            text="打开",
            width=56,
            height=28,
            corner_radius=8,
            fg_color=C["card"],
            hover_color=C["sidebar_hover"],
            text_color=C["text_soft"],
            font=theme.ctk_font(11),
            command=lambda: webbrowser.open(Path(data_dir()).as_uri()),
        ).pack(side="right")
        self._hint(scroll, "配置和会话都存在这里。整个程序目录拷走即可在别的电脑继续用。")

        # ---- 底部按钮 ----
        bottom = ctk.CTkFrame(self, fg_color=C["bg"])
        bottom.pack(fill="x", padx=24, pady=(0, 18))

        # 测试连接固定在底部，不用滚到最下面找
        ctk.CTkButton(
            bottom,
            text="测试连接",
            width=100,
            height=36,
            corner_radius=9,
            fg_color=C["card"],
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(12),
            command=self._test,
        ).pack(side="left")
        self.test_label = ctk.CTkLabel(bottom, text="", font=theme.ctk_font(11), text_color=C["text_dim"], anchor="w")
        self.test_label.pack(side="left", padx=(12, 0))

        ctk.CTkButton(
            bottom,
            text="保存",
            width=96,
            height=36,
            corner_radius=9,
            fg_color=C["accent"],
            hover_color=C["accent_hover"],
            text_color="#FFFFFF",
            font=theme.ctk_font(13, "bold"),
            command=self._save,
        ).pack(side="right")
        ctk.CTkButton(
            bottom,
            text="取消",
            width=80,
            height=36,
            corner_radius=9,
            fg_color="transparent",
            hover_color=C["sidebar_hover"],
            border_width=1,
            border_color=C["border"],
            text_color=C["text_soft"],
            font=theme.ctk_font(13),
            command=self.destroy,
        ).pack(side="right", padx=(0, 10))

    # ------------------------------------------------------------------ 小部件
    def _section(self, master, text: str) -> None:
        ctk.CTkLabel(
            master,
            text=text,
            font=theme.ctk_font(12, "bold"),
            text_color=C["accent"],
            anchor="w",
        ).pack(fill="x", padx=8, pady=(14, 6))

    def _row(self, master, label: str) -> ctk.CTkFrame:
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(row, text=label, width=110, anchor="w", font=theme.ctk_font(12), text_color=C["text_soft"]).pack(side="left")
        return row

    def _hint(self, master, text: str) -> None:
        ctk.CTkLabel(
            master,
            text=text,
            font=theme.ctk_font(10),
            text_color=C["text_dim"],
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=(126, 8), pady=(0, 6))

    def _switch(self, master, text: str, value: bool, command=None):
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=3)
        toggle = LabeledToggle(row, text, value=value, font_size=12, bg=C["bg"], command=command)
        toggle.pack(side="left", padx=(110, 0))
        return toggle

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key.get() else "•")

    # ------------------------------------------------------------------ 动作
    def _test(self) -> None:
        if self._testing:
            return
        self._testing = True
        self.test_label.configure(text="正在连接…", text_color=C["text_dim"])
        key = self.key_entry.get().strip()
        proxy = self.proxy_entry.get().strip()

        result: dict = {}

        def worker() -> None:
            try:
                cfg = Config.from_dict({**self.cfg.to_dict(), "api_key": key, "proxy": proxy})
                client = DeepSeekClient(cfg)
                models = client.models()
                try:
                    balance = client.balance()
                    extra = f"，余额 {balance.get('total')} {balance.get('currency')}"
                except DSException:
                    extra = ""
                result["ok"] = (True, f"连接成功：{'、'.join(models)}{extra}")
            except DSException as exc:
                result["ok"] = (False, str(exc))
            except Exception as exc:  # noqa: BLE001
                result["ok"] = (False, f"{type(exc).__name__}: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        self._poll_test(result)

    def _poll_test(self, result: dict) -> None:
        if not self.winfo_exists():
            return
        if "ok" in result:
            ok, message = result["ok"]
            self._test_done(ok, message)
        else:
            self.after(150, lambda: self._poll_test(result))

    def _test_done(self, ok: bool, text: str) -> None:
        self._testing = False
        self.test_label.configure(text=text, text_color=C["ok"] if ok else C["danger"])

    def _save(self) -> None:
        cfg = self.cfg
        cfg.api_key = self.key_entry.get().strip()
        cfg.thinking = bool(self.think_sw.get())
        cfg.web_search = bool(self.search_sw.get())
        cfg.read_url = bool(self.read_sw.get())
        cfg.show_reasoning = bool(self.show_reason_sw.get())
        cfg.save_history = bool(self.save_history_sw.get())
        cfg.rich_layout_default = bool(self.rich_sw.get())
        label = self.voice_var.get()
        cfg.tts_voice = next((k for k, v in VOICES.items() if v == label), cfg.tts_voice)
        cfg.auto_read = bool(self.auto_read_sw.get())
        cfg.theme = "dark" if self.theme_var.get() == "深色" else "light"
        try:
            cfg.temperature = float(self.temp_entry.get().strip() or 1.0)
        except ValueError:
            cfg.temperature = 1.0
        try:
            cfg.top_p = float(self.top_entry.get().strip() or 1.0)
        except ValueError:
            cfg.top_p = 1.0
        try:
            cfg.max_tokens = int(self.max_entry.get().strip() or 0)
        except ValueError:
            cfg.max_tokens = 0
        cfg.system_prompt = self.sys_text.get("1.0", "end").strip()
        cfg.stop_words = [ln.strip() for ln in self.stop_text.get("1.0", "end").splitlines() if ln.strip()]
        cfg.proxy = self.proxy_entry.get().strip()
        try:
            cfg.timeout = int(self.timeout_entry.get().strip() or 120)
        except ValueError:
            cfg.timeout = 120
        cfg.normalize()
        cfg.save()
        if self.on_saved:
            self.on_saved(cfg)
        self.destroy()
