"""对话区排版样式：预设字体、自定义字体导入、生成给 WebView2 的样式数据。

自定义字体由用户自行选择本机 .ttf/.otf/.woff/.woff2 文件，复制到
``data/fonts/`` 后以 base64 data URI 注入页面 @font-face——因为 WebView2 用
NavigateToString 加载 HTML，本地文件路径无法直接引用，data URI 最可靠且
不依赖任何额外 COM 接口。字体文件仅留在本机，不随仓库分发（有版权风险）。
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

from dskit.config import data_dir

# key / 显示名 / CSS font-family 栈。family 均为代码内常量，不接受用户输入，避免 CSS 注入。
FONT_PRESETS: list[tuple[str, str, str]] = [
    ("", "系统默认（微软雅黑 UI）",
     '"Microsoft YaHei UI","Microsoft YaHei","Segoe UI","PingFang SC",Arial,sans-serif'),
    ("yahei", "微软雅黑", '"Microsoft YaHei","Microsoft YaHei UI",sans-serif'),
    ("songti", "宋体 · 衬线（长文阅读）", '"SimSun","Songti SC","Noto Serif CJK SC",serif'),
    ("heiti", "黑体", '"SimHei","Heiti SC",sans-serif'),
    ("dengxian", "等线", '"DengXian","Microsoft YaHei",sans-serif'),
    ("kaiti", "楷体", '"KaiTi","STKaiti",serif'),
    ("sourcehan", "思源黑体 / Noto Sans CJK",
     '"Source Han Sans SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif'),
    ("mono", "等宽 · Consolas（代码向）",
     'Consolas,"Cascadia Mono","Courier New","Microsoft YaHei",monospace'),
    ("georgia", "Georgia · 英文衬线", 'Georgia,"Times New Roman","Microsoft YaHei",serif'),
]

CUSTOM_KEY = "custom"
CUSTOM_FAMILY = "DSCustomFont"          # 固定 family 名，绝不从文件名拼接
FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
MAX_FONT_BYTES = 6 * 1024 * 1024        # 6 MB：字体以 base64 经 postMessage 传输，
                                         # 过大会让消息体膨胀到 ~8MB 并卡顿；常用字体子集通常 < 5MB

_MIME = {
    ".ttf": "font/ttf", ".otf": "font/otf",
    ".woff": "font/woff", ".woff2": "font/woff2",
}

DEFAULTS: dict[str, object] = {
    "chat_pad_x": 36,
    "chat_line_height": 1.85,
    "chat_font_size": 16,
    "chat_font_family": "",
    "chat_font_name": "",
}


def fonts_dir() -> Path:
    return data_dir() / "fonts"


def presets_for_ui() -> list[dict]:
    return [{"value": k, "label": label} for k, label, _ in FONT_PRESETS]


def family_css(key: str, *, custom: bool = False) -> str:
    """把设置里的字体 key 转成 CSS font-family 值。"""
    if custom or key == CUSTOM_KEY:
        # 自定义字体优先，失败时回退到系统默认栈
        return f'"{CUSTOM_FAMILY}",' + FONT_PRESETS[0][2]
    for k, _label, css in FONT_PRESETS:
        if k == key:
            return css
    return FONT_PRESETS[0][2]


def import_font(src: str | Path) -> str:
    """校验并复制字体到 data/fonts/，返回安全的文件名。失败抛 ValueError。"""
    p = Path(src)
    if not p.is_file():
        raise ValueError("文件不存在")
    ext = p.suffix.lower()
    if ext not in FONT_EXTS:
        raise ValueError("仅支持 .ttf / .otf / .woff / .woff2 字体文件")
    size = p.stat().st_size
    if size > MAX_FONT_BYTES:
        raise ValueError(f"字体文件过大（{size / 1024 / 1024:.1f} MB），上限 6 MB，建议使用字体子集")
    if size == 0:
        raise ValueError("字体文件为空")
    target_dir = fonts_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    # 文件名只保留安全字符，杜绝路径穿越与 CSS 注入
    safe = "".join(c for c in p.name if c.isalnum() or c in "._-")[:80] or ("font" + ext)
    dest = target_dir / safe
    if p.resolve() != dest.resolve():
        shutil.copyfile(p, dest)
    return safe


def remove_font(name: str) -> None:
    """删除已导入的字体文件（只在 data/fonts/ 内操作）。"""
    safe = Path(name).name
    if safe != name or not safe:
        return
    p = fonts_dir() / safe
    if p.is_file() and p.suffix.lower() in FONT_EXTS:
        try:
            p.unlink()
        except OSError:
            pass


def font_face_rules(name: str) -> tuple[str, str]:
    """返回 (@font-face CSS, 实际使用的 family 名)。文件缺失时回退系统默认。"""
    if not name:
        return "", family_css("")
    safe = Path(name).name
    p = fonts_dir() / safe
    if safe != name or not p.is_file() or p.suffix.lower() not in FONT_EXTS:
        return "", family_css("")
    try:
        raw = p.read_bytes()
    except OSError:
        return "", family_css("")
    mime = _MIME.get(p.suffix.lower(), "font/ttf")
    uri = "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")
    css = (
        '@font-face{font-family:"' + CUSTOM_FAMILY + '";'
        'src:url("' + uri + '");font-display:swap;}'
    )
    return css, family_css("", custom=True)


def style_payload(cfg, *, with_font: bool = True) -> dict:
    """生成发给 WebView2 的 chat_style 消息体。

    with_font=False 时省略 font_face（大字符串），用于「字体没变」的增量更新。
    """
    family = str(getattr(cfg, "chat_font_family", "") or "")
    name = str(getattr(cfg, "chat_font_name", "") or "")
    custom = family == CUSTOM_KEY and bool(name)
    face_css, resolved_family = font_face_rules(name) if custom else ("", family_css(family))
    line_height = float(getattr(cfg, "chat_line_height", DEFAULTS["chat_line_height"]))
    # 段落间距随行距联动：行距越大，段落间留白略增，长文阅读更接近截图效果
    para = round(min(0.95, max(0.35, 0.35 + (line_height - 1.4) * 0.45)), 2)
    payload = {
        "pad_x": int(getattr(cfg, "chat_pad_x", DEFAULTS["chat_pad_x"])),
        "line_height": line_height,
        "font_size": int(getattr(cfg, "chat_font_size", DEFAULTS["chat_font_size"])),
        "font_family": resolved_family,
        "para": para,
        "custom_name": name if custom else "",
    }
    if with_font:
        payload["font_face"] = face_css
    return payload
