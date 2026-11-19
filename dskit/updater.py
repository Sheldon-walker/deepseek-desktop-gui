"""软件更新检查 —— 基于 GitHub Releases。

只做一件事：向 GitHub 匿名查询最新正式版 Release，返回结构化结果。
不自动执行、不上报任何本地数据：只有用户在设置里点「检查更新」才会调用一次。
只依赖 requests（项目已有），不引入新库。

接口：GET https://api.github.com/repos/{owner}/{repo}/releases/latest
未认证限流 60 次/小时/IP，手动点击足够；不携带 API Key 或任何本地内容。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import requests

from .version import APP_VERSION, EXE_NAME, GITHUB_API, UPDATE_REPO

_TIMEOUT = 10
_UA = "DeepSeekDesktop-Updater/1.0"


def clean_repo(value: str) -> str:
    """把 'https://github.com/owner/repo.git' 规整成 'owner/repo'。"""
    v = (value or "").strip()
    v = re.sub(r"^https?://(?:www\.)?github\.com/", "", v, flags=re.I)
    v = re.sub(r"\.git$", "", v.strip().rstrip("/"), flags=re.I)
    return v.strip("/")


def effective_repo(configured: str = "") -> str:
    """设置页填了就用设置页的，否则用内置默认仓库。"""
    return clean_repo(configured) or UPDATE_REPO


def parse_version(text: str) -> tuple[int, int, int, int]:
    """'v0.1.1' / '0.1.1-beta.2' -> (0, 1, 1, 1|0)。

    第 4 位是稳定版标志：正式版 1、预发布 0，
    这样 0.1.1-beta 会排在 0.1.1 正式版之前。
    完全解析不出数字时返回 (0, 0, 0, 0)，表示无效版本。
    """
    s = (text or "").strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    pre = bool(re.search(r"[-+]", s))
    core = re.split(r"[-+]", s, maxsplit=1)[0]
    nums: list[int] = []
    matched = False
    for part in core.split(".")[:3]:
        m = re.match(r"\s*(\d+)", part)
        nums.append(int(m.group(1)) if m else 0)
        if m:
            matched = True
    while len(nums) < 3:
        nums.append(0)
    # 第 4 位：0 = 预发布或无效版本，1 = 正式版
    return (nums[0], nums[1], nums[2], 0 if (pre or not matched) else 1)


def compare_versions(a: str, b: str) -> int:
    """a > b 返回 1，相等返回 0，a < b 返回 -1。"""
    pa, pb = parse_version(a), parse_version(b)
    return (pa > pb) - (pa < pb)


@dataclass
class UpdateInfo:
    """一次检查的结果。ok=False 时 message 是给用户看的中文提示。"""

    current: str = ""
    latest: str = ""
    has_update: bool = False
    ok: bool = False
    message: str = ""
    notes: str = ""
    html_url: str = ""
    download_url: str = ""
    published_at: str = ""
    release_name: str = ""
    prerelease: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_release(data: dict, *, current: str) -> UpdateInfo:
    # tag_name 才是版本号；name 只是 Release 标题，不能拿来比较
    latest = str(data.get("tag_name") or "").strip()
    if not latest:
        return UpdateInfo(current=current, ok=False, message="Release 缺少版本号（tag_name），无法比较")

    info = UpdateInfo(
        current=current,
        latest=latest,
        ok=True,
        notes=str(data.get("body") or "").strip(),
        html_url=str(data.get("html_url") or ""),
        published_at=str(data.get("published_at") or ""),
        release_name=str(data.get("name") or ""),
        prerelease=bool(data.get("prerelease")),
    )

    # 下载链接：优先同名 exe，其次任意 exe，都没有就回退到 Release 页面
    assets = data.get("assets") or []
    exe = next((a for a in assets if str(a.get("name", "")).lower() == EXE_NAME.lower()), None)
    if exe is None:
        exe = next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    info.download_url = str((exe or {}).get("browser_download_url") or "")

    cmp = compare_versions(latest, current)
    info.has_update = cmp > 0
    if cmp > 0:
        info.message = "有新的稳定版本可用。"
    elif cmp == 0:
        info.message = "已是最新版本。"
    else:
        info.message = "本地版本高于线上 Release（可能是开发版）。"
    return info


def parse_release_payload(raw: str | dict, *, current: str = APP_VERSION) -> UpdateInfo:
    """解析 GitHub Release JSON。单独抽出来便于离线自测，不发网络请求。"""
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return _parse_release(data, current=current)


def check_update(
    *,
    repo: str = "",
    current: str = APP_VERSION,
    timeout: int = _TIMEOUT,
    proxies: dict | None = None,
) -> UpdateInfo:
    """查询最新正式版 Release。

    任何失败都返回 ok=False + 中文提示，不抛异常，界面可以直接渲染。
    """
    owner_repo = effective_repo(repo)
    if owner_repo.count("/") != 1 or not all(owner_repo.split("/")):
        return UpdateInfo(
            current=current, ok=False,
            message=f"更新源格式不对：{owner_repo!r}，应填 owner/repo",
        )

    url = f"{GITHUB_API}/repos/{owner_repo}/releases/latest"
    try:
        resp = requests.get(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": _UA},
            timeout=(5, timeout),
            proxies=proxies,
        )
    except requests.RequestException as exc:
        return UpdateInfo(current=current, ok=False, message=f"无法连接 GitHub：{exc}")

    if resp.status_code == 404:
        return UpdateInfo(
            current=current, ok=False,
            message="该仓库还没有发布过 Release（发版后即可检查到更新）",
        )
    if resp.status_code == 403:
        return UpdateInfo(
            current=current, ok=False,
            message="GitHub API 请求次数已达上限（未认证 60 次/小时），请稍后再试",
        )
    if resp.status_code >= 400:
        return UpdateInfo(current=current, ok=False, message=f"检查更新失败：HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError:
        return UpdateInfo(current=current, ok=False, message="GitHub 返回了无法解析的内容")
    return parse_release_payload(data, current=current)
