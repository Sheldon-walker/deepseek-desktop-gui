"""应用版本与更新源常量。

发新版本时只改这里：把 APP_VERSION 改成新版本号并提交，
再按 README「版本更新与发版流程」打 tag、建 Release 即可。
"""

from __future__ import annotations

APP_NAME = "DeepSeek Desktop"

# 当前版本号。设置页「当前版本」显示的就是它。
APP_VERSION = "1.0.0"

# GitHub 更新源，格式 owner/repo。用户可在设置页「更新源」里覆盖。
UPDATE_REPO = "Sheldon-walker/deepseek-desktop-gui"

# 单文件 exe 文件名，用于从 Release assets 里挑下载直链。
EXE_NAME = "DeepSeekDesktop.exe"

GITHUB_API = "https://api.github.com"


def releases_page_url(repo: str = "") -> str:
    """仓库的 Releases 页面地址（浏览器打开用）。"""
    owner_repo = (repo or UPDATE_REPO).strip().strip("/")
    return f"https://github.com/{owner_repo}/releases"
