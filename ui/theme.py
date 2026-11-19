"""界面主题：颜色、字体、间距。

浅色 / 深色两套调色板集中在这里。切换主题调用 `theme.apply("dark"/"light")`：
它会设置 CustomTkinter 的 appearance mode，并**原地替换 COLORS 字典内容**。
各模块顶部 `C = theme.COLORS` 拿到的是同一个 dict 对象，原地替换后所有
`C[...]` 取值立即生效 —— 但已创建好的控件不会自动变色，所以切换主题后由
主窗口 `App` 重建界面（会保留当前会话）。

字体相关保持不变，只在根窗口创建后 `init_fonts` 挑一次真实存在的字体。
"""

from __future__ import annotations

import tkinter.font as tkfont

_LIGHT = {
    "sidebar": "#F7F8FA",
    "sidebar_hover": "#EDEFF3",
    "sidebar_active": "#E6EAFF",
    "bg": "#FFFFFF",
    "surface": "#FFFFFF",
    "surface_soft": "#FAFBFC",
    "card": "#F6F7F9",
    "border": "#E4E6EA",
    "border_soft": "#EFF0F3",
    "text": "#1A1C1F",
    "text_soft": "#5A6068",
    "text_dim": "#9AA0AA",
    "accent": "#4D6BFE",
    "accent_hover": "#3B57E2",
    "accent_soft": "#EDF0FF",
    "user_bubble": "#EEF2FF",
    "user_bubble_border": "#DEE4FF",
    "code_bg": "#F4F5F7",
    "code_border": "#E6E8EC",
    "code_fg": "#2B2F36",
    "code_inline_fg": "#B4442E",
    "select_bg": "#CBD9FF",
    "switch_off": "#D5D8DE",
    "switch_disabled": "#E8EAEE",
    "danger": "#E5484D",
    "danger_hover": "#C93C41",
    "danger_soft": "#FDECEC",
    "ok": "#0F7B5A",
    "warn": "#A9620B",
    "warn_bg": "#FFF8E6",
    "warn_fg": "#8A5A00",
    "thinking_bg": "#FAFAFB",
    "thinking_text": "#8B9199",
    "shadow": "#F0F1F4",
}

_DARK = {
    "sidebar": "#1F2125",
    "sidebar_hover": "#2A2D32",
    "sidebar_active": "#2E3A5C",
    "bg": "#16181B",
    "surface": "#1C1E22",
    "surface_soft": "#202227",
    "card": "#26282D",
    "border": "#34373D",
    "border_soft": "#2A2D32",
    "text": "#E7E9EC",
    "text_soft": "#A9AFB8",
    "text_dim": "#7C848E",
    "accent": "#7C93FF",
    "accent_hover": "#94A7FF",
    "accent_soft": "#262C45",
    "user_bubble": "#262C45",
    "user_bubble_border": "#39446A",
    "code_bg": "#23252A",
    "code_border": "#34373D",
    "code_fg": "#D7DBE0",
    "code_inline_fg": "#FF9D7A",
    "select_bg": "#3A4A7A",
    "switch_off": "#3A3D42",
    "switch_disabled": "#2A2D32",
    "danger": "#F0716E",
    "danger_hover": "#D9534F",
    "danger_soft": "#3A2326",
    "ok": "#3BBF8F",
    "warn": "#E0A65C",
    "warn_bg": "#33291A",
    "warn_fg": "#E0A65C",
    "thinking_bg": "#1E2024",
    "thinking_text": "#9AA0AA",
    "shadow": "#111214",
}

COLORS = dict(_LIGHT)
CURRENT = "light"

# 全局字号放大系数：整体偏小时调大这里即可，font() / ctk_font() 都会套用
FONT_SCALE = 1.16

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18, "xl": 26}

# 顶栏高度（逻辑像素）：侧边栏的 DeepSeek 品牌行用同一个高度，两行才对得上
TOP_BAR_HEIGHT = 60

UI_FAMILIES = ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"]

_ui_family = UI_FAMILIES[0]
_mono_family = MONO_FAMILIES[-1]


def apply(mode: str) -> None:
    """切换到指定主题。注意是原地替换 COLORS，不要重新赋值 COLORS 变量。"""
    global CURRENT
    mode = "dark" if str(mode).lower() == "dark" else "light"
    CURRENT = mode
    import customtkinter as ctk

    ctk.set_appearance_mode(mode)
    COLORS.clear()
    COLORS.update(_DARK if mode == "dark" else _LIGHT)


def is_dark() -> bool:
    return CURRENT == "dark"


def init_fonts(root) -> None:
    """在 Tk 根窗口创建后挑一个系统里真实存在的字体。"""
    global _ui_family, _mono_family
    try:
        available = {name.lower() for name in tkfont.families(root)}
    except Exception:
        return
    for name in UI_FAMILIES:
        if name.lower() in available:
            _ui_family = name
            break
    for name in MONO_FAMILIES:
        if name.lower() in available:
            _mono_family = name
            break


def ui_family() -> str:
    return _ui_family


def mono_family() -> str:
    return _mono_family


def font(size: int = 13, weight: str = "normal", *, mono: bool = False) -> tuple:
    """给 tk 原生控件用的字体元组。"""
    return (mono_family() if mono else ui_family(), round(size * FONT_SCALE), weight)


def ctk_font(size: int = 13, weight: str = "normal"):
    """给 CustomTkinter 控件用的字体（延迟导入，避免循环依赖）。"""
    import customtkinter as ctk

    return ctk.CTkFont(family=ui_family(), size=round(size * FONT_SCALE), weight=weight)
