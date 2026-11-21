"""本地配置读写 —— 绿色便携版。

所有数据都放在程序目录下的 data/：
    程序目录/data/config.json     配置
    程序目录/data/sessions/*.json 会话历史
打包成 exe 后，"程序目录"就是 exe 所在目录，整个文件夹拷到别的电脑即可带走全部数据。

若程序目录不可写（例如放在 Program Files），会自动回退到
%APPDATA%/DeepSeekDesktop，并在设置页显示实际路径。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

APP_NAME = "DeepSeekDesktop"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
AVAILABLE_MODELS = ("deepseek-flash", "deepseek-v4-pro")
EFFORT_LEVELS = ("low", "medium", "high")
TTS_VOICES = ("stella", "tide")
DEFAULT_TTS_VOICE = "stella"

_dir_cache: Path | None = None


def base_dir() -> Path:
    """程序根目录：打包后是 exe 所在目录，开发时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def legacy_dir() -> Path:
    """旧版本（阶段 1）使用的 APPDATA 目录，仅用于一次性迁移。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def data_dir() -> Path:
    """数据目录，带可写性探测与回退。"""
    global _dir_cache
    if _dir_cache is not None:
        return _dir_cache
    target = base_dir() / "data"
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _dir_cache = target
    except OSError:
        fallback = legacy_dir()
        fallback.mkdir(parents=True, exist_ok=True)
        _dir_cache = fallback
    return _dir_cache


def config_dir() -> Path:
    return data_dir()


def migrate_legacy() -> None:
    """把阶段 1 存在 APPDATA 的配置与会话搬到程序目录（只补不改）。"""
    src = legacy_dir()
    dst = data_dir()
    if not src.exists() or src == dst:
        return
    try:
        cfg_src = src / "config.json"
        cfg_dst = dst / "config.json"
        if cfg_src.exists() and not cfg_dst.exists():
            shutil.copy2(cfg_src, cfg_dst)
        s_src, s_dst = src / "sessions", dst / "sessions"
        if s_src.is_dir():
            s_dst.mkdir(parents=True, exist_ok=True)
            for file in s_src.glob("*.json"):
                if not (s_dst / file.name).exists():
                    shutil.copy2(file, s_dst / file.name)
    except OSError:
        pass


@dataclass
class Config:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    thinking: bool = True                 # 深度思考模式（开关 6 之"思考模式"）
    reasoning_effort: str = "high"        # low / medium / high
    temperature: float = 1.0              # 0~2，思考模式下不生效（不传）
    top_p: float = 1.0                    # 0~1；flash 思考模式下最低 0.95
    system_prompt: str = ""               # 留空则用内置默认提示词
    stop_words: list[str] = field(default_factory=list)   # 命中即停止生成
    web_search: bool = True               # 联网搜索开关
    read_url: bool = True                 # 允许模型读取消息里的链接
    proxy: str = ""                       # 形如 http://127.0.0.1:7890，留空则走系统环境变量
    timeout: int = 120                    # 读超时（秒）
    max_tokens: int = 0                   # 0 表示不传，用服务端默认
    cny_rate: float = 7.10                # 美元 -> 人民币汇率，仅用于费用估算展示
    show_reasoning: bool = True           # CLI/界面是否展示思考过程
    save_history: bool = True             # 是否把对话存成本地 json
    rich_layout_default: bool = False     # 文件解析默认是否勾选「含图表识别」
    tts_voice: str = DEFAULT_TTS_VOICE    # 朗读音色：stella（女）/ tide（男）
    auto_read: bool = False               # 新回答生成完自动朗读（默认关）
    theme: str = "light"                  # 界面主题：light / dark
    chat_zoom: float = 1.0                # 聊天区字号缩放（Ctrl+滚轮），0.7~1.8
    panel_width: int = 340                # 右侧检索结果栏宽度（可拖拽），260~720
    sidebar_width: int = 268              # 左侧会话栏宽度（可拖拽），200~420
    ui: str = "web"                       # 界面外壳：web（WebView2 整窗） / tk（旧版 Tk 控件）
    update_repo: str = ""                 # GitHub 更新源 owner/repo，留空用 dskit/version.py 的默认值
    # ---------- 对话区排版（设置页「阅读排版」）----------
    chat_pad_x: int = 36                  # 消息区左右留白 px，8~120
    chat_line_height: float = 1.85        # 正文行距倍数，1.2~2.6
    chat_font_size: int = 16              # 正文字号 px，12~24
    chat_font_family: str = ""            # 预设字体 key，"" = 系统默认，"custom" = 用户上传
    chat_font_name: str = ""              # 自定义字体文件名（data/fonts/ 下），不入库

    # ---------- 路径 ----------
    @classmethod
    def path(cls) -> Path:
        return data_dir() / "config.json"

    # ---------- 读写 ----------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        migrate_legacy()
        p = path or cls.path()
        cfg = cls()
        raw: dict[str, Any] = {}
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raw = {}
            cfg = cls.from_dict(raw)
        # 环境变量优先级最高，方便临时覆盖（不落盘）。
        # 覆盖值只在内存的 cfg 上生效：to_dict()/save() 会把仍保持注入值的字段
        # 还原成磁盘原值；用户主动改过（值已偏离注入值）的字段允许正常落盘。
        env_fields: set[str] = set()
        env_injected: dict[str, str] = {}
        env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if env_key:
            cfg.api_key = env_key
            env_fields.add("api_key")
            env_injected["api_key"] = env_key
        env_base = os.environ.get("DEEPSEEK_BASE_URL", "").strip()
        if env_base:
            cfg.base_url = env_base
            env_fields.add("base_url")
            env_injected["base_url"] = env_base
        # 动态实例属性，故意不是 dataclass 字段：fields(self) 不含它们，
        # to_dict() 就不会把这些内部状态写进 config.json。
        cfg._disk_raw = raw
        cfg._env_fields = env_fields
        cfg._env_injected = env_injected
        return cfg

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in (raw or {}).items() if k in known}
        cfg = cls(**data)
        cfg.normalize()
        return cfg

    def normalize(self) -> None:
        self.api_key = (self.api_key or "").strip()
        self.base_url = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            self.base_url = DEFAULT_BASE_URL
        if self.model not in AVAILABLE_MODELS:
            self.model = DEFAULT_MODEL
        if self.reasoning_effort == "max":      # 旧版本用的是 low/high/max
            self.reasoning_effort = "high"
        if self.reasoning_effort not in EFFORT_LEVELS:
            self.reasoning_effort = "high"
        try:
            self.temperature = min(2.0, max(0.0, float(self.temperature)))
        except (TypeError, ValueError):
            self.temperature = 1.0
        try:
            self.top_p = min(1.0, max(0.01, float(self.top_p)))
        except (TypeError, ValueError):
            self.top_p = 1.0
        if isinstance(self.stop_words, str):
            self.stop_words = [w.strip() for w in self.stop_words.replace("\n", ",").split(",")]
        if not isinstance(self.stop_words, list):
            self.stop_words = []
        self.stop_words = [str(w).strip() for w in self.stop_words if str(w).strip()][:16]
        if self.tts_voice not in TTS_VOICES:
            self.tts_voice = DEFAULT_TTS_VOICE
        if self.theme not in ("light", "dark"):
            self.theme = "light"
        if self.ui not in ("web", "tk"):
            self.ui = "web"
        try:
            self.chat_zoom = min(1.8, max(0.7, float(self.chat_zoom)))
        except (TypeError, ValueError):
            self.chat_zoom = 1.0
        try:
            self.sidebar_width = min(420, max(200, int(self.sidebar_width)))
        except (TypeError, ValueError):
            self.sidebar_width = 268
        try:
            self.panel_width = min(720, max(260, int(self.panel_width)))
        except (TypeError, ValueError):
            self.panel_width = 340
        try:
            self.timeout = max(10, int(self.timeout))
        except (TypeError, ValueError):
            self.timeout = 120
        try:
            self.max_tokens = max(0, int(self.max_tokens))
        except (TypeError, ValueError):
            self.max_tokens = 0
        try:
            self.cny_rate = float(self.cny_rate) or 7.10
        except (TypeError, ValueError):
            self.cny_rate = 7.10
        self.proxy = (self.proxy or "").strip()
        self.update_repo = (self.update_repo or "").strip()
        # 对话排版：全部钳制到安全范围，旧配置缺字段时用 dataclass 默认值
        try:
            self.chat_pad_x = min(120, max(8, int(self.chat_pad_x)))
        except (TypeError, ValueError):
            self.chat_pad_x = 36
        try:
            self.chat_line_height = round(min(2.6, max(1.2, float(self.chat_line_height))), 2)
        except (TypeError, ValueError):
            self.chat_line_height = 1.85
        try:
            self.chat_font_size = min(24, max(12, int(self.chat_font_size)))
        except (TypeError, ValueError):
            self.chat_font_size = 16
        self.chat_font_family = str(self.chat_font_family or "").strip()
        # 文件名只保留 basename，杜绝路径穿越
        self.chat_font_name = str(self.chat_font_name or "").strip()
        if self.chat_font_name:
            self.chat_font_name = Path(self.chat_font_name).name[:80]
        if self.chat_font_family == "custom" and not self.chat_font_name:
            self.chat_font_family = ""

    def to_dict(self, *, mask_key: bool = False) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        # 环境变量注入的 api_key / base_url 只在内存生效：字段值仍等于注入值时
        # 还原成磁盘原值（磁盘没该字段则用 dataclass 默认值），绝不把临时注入值
        # 写进 config.json；用户主动改过、值已偏离注入值的字段允许正常落盘。
        env_fields = getattr(self, "_env_fields", None)
        if env_fields:
            raw = getattr(self, "_disk_raw", None)
            raw = raw if isinstance(raw, dict) else {}
            injected = getattr(self, "_env_injected", None)
            injected = injected if isinstance(injected, dict) else {}
            defaults = type(self)()
            for name in env_fields:
                if name in injected and getattr(self, name, None) != injected[name]:
                    continue
                data[name] = raw[name] if name in raw else getattr(defaults, name)
        if mask_key and data.get("api_key"):
            data["api_key"] = mask_key_value(data["api_key"])
        return data

    def save(self, path: Path | None = None) -> Path:
        p = path or self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)  # 原子替换，避免写一半损坏配置
        return p

    # ---------- 便捷 ----------
    def proxies(self) -> dict[str, str] | None:
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    def masked_key(self) -> str:
        return mask_key_value(self.api_key)


def mask_key_value(key: str) -> str:
    key = key or ""
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}{'*' * (len(key) - 10)}{key[-4:]}"
