"""应用版本与更新源常量。

版本号唯一真源：设置页「当前版本」、CLI `update`、版本比较都读 APP_VERSION。
发版时只改这里，并让 GitHub Release 的 tag 与它严格对应：

    APP_VERSION = "0.1.3"  ->  tag v0.1.3

改完重新打包 exe，再建 Release（不要勾 pre-release）并上传 DeepSeekDesktop.exe。
"""

from __future__ import annotations

APP_NAME = "DeepSeek Desktop"

# 当前版本号，需与最新正式版 Release 的 tag 对应。设置页「当前版本」显示的就是它。
APP_VERSION = "0.1.3"

# GitHub 更新源，格式 owner/repo。用户可在设置页「更新源」里覆盖。
UPDATE_REPO = "Sheldon-walker/deepseek-desktop-gui"

# 单文件 exe 文件名，用于从 Release assets 里挑下载直链。
EXE_NAME = "DeepSeekDesktop.exe"

GITHUB_API = "https://api.github.com"


def releases_page_url(repo: str = "") -> str:
    """仓库的 Releases 页面地址（浏览器打开用）。"""
    owner_repo = (repo or UPDATE_REPO).strip().strip("/")
    return f"https://github.com/{owner_repo}/releases"
