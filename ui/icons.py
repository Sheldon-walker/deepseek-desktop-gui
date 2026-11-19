"""图标资源加载。

把 assets/icons 下的 PNG 转成 CustomTkinter 的 CTkImage。打包成单文件 exe 时，
资源会被 PyInstaller 解到临时目录（sys._MEIPASS），源码运行时则读项目内 assets。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

import customtkinter as ctk


def _asset(name: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "assets" / "icons" / name
        if p.exists():
            return p
    return Path(__file__).resolve().parent.parent / "assets" / "icons" / name


def icon(name: str, size: tuple[int, int]) -> ctk.CTkImage:
    """加载单个 PNG 图标。这些图标是 ON/OFF 状态色，不随深浅主题变化。"""
    img = Image.open(_asset(name))
    return ctk.CTkImage(light_image=img, dark_image=img, size=size)


# 各图标（供输入栏使用）
def think(size=(16, 16)) -> tuple[ctk.CTkImage, ctk.CTkImage]:
    return icon("ui-icons_01-deep-think-blue.png", size), icon("ui-icons_06-deep-think-black.png", size)


def search(size=(16, 16)) -> tuple[ctk.CTkImage, ctk.CTkImage]:
    return icon("ui-icons_02-smart-search-blue.png", size), icon("ui-icons_07-smart-search-black.png", size)


def microphone(size=(18, 18)) -> ctk.CTkImage:
    return icon("ui-icons_03-microphone-black.png", size)


def paperclip(size=(18, 18)) -> ctk.CTkImage:
    return icon("ui-icons_04-paperclip-black.png", size)


def send(size=(34, 34)) -> tuple[ctk.CTkImage, ctk.CTkImage]:
    """返回 (disabled 浅色, active 深色)。"""
    return icon("ui-icons_05-send-disabled.png", size), icon("ui-icons_08-send-active.png", size)


def logo(size=(34, 25)) -> ctk.CTkImage:
    """应用 logo（欢迎语前的蓝色鲸鱼）。源图是等比裁切过的 PNG，放大也清晰。"""
    return icon("app-logo.png", size)
