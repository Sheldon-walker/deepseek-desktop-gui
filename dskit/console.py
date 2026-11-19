"""轻量终端输出工具：颜色、状态行、表格、中文对齐。

刻意不引入 rich/colorama：一是减少打包体积，二是 GUI 阶段用不到。
Windows 10+ 通过 os.system("") 打开 ANSI 支持。
"""

from __future__ import annotations

import os
import sys
import unicodedata

_ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}

_color_enabled = True


def init(no_color: bool = False) -> None:
    """初始化：开启 Windows ANSI、把 stdout 切成 UTF-8。"""
    global _color_enabled
    if os.name == "nt":
        try:
            os.system("")  # 让 cmd/PowerShell 接受 ANSI 转义
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    _color_enabled = not no_color and os.environ.get("NO_COLOR") is None


def paint(text: str, color: str = "", *, bold: bool = False, dim: bool = False) -> str:
    if not _color_enabled:
        return text
    prefix = ""
    if color:
        prefix += _ANSI.get(color, "")
    if dim:
        prefix += _ANSI["dim"]
    if bold:
        prefix += _ANSI["bold"]
    return f"{prefix}{text}{_ANSI['reset']}" if prefix else text


def width(text: str) -> int:
    """按终端显示宽度算长度（中文/全角算 2）。"""
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def pad(text: str, target: int) -> str:
    return text + " " * max(0, target - width(text))


def truncate(text: str, limit: int) -> str:
    if width(text) <= limit:
        return text
    out, acc = "", 0
    for ch in text:
        acc += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if acc > limit - 2:
            break
        out += ch
    return out + ".."


def hr(char: str = "-", n: int = 72) -> None:
    print(paint(char * n, "gray"))


def title(text: str) -> None:
    print()
    print(paint(f"== {text} ", "cyan", bold=True) + paint("=" * max(0, 66 - width(text)), "gray"))


def info(text: str) -> None:
    print(paint("  " + text, "gray"))


def ok(text: str) -> None:
    print(paint("  [OK]   ", "green", bold=True) + text)


def fail(text: str) -> None:
    print(paint("  [FAIL] ", "red", bold=True) + text)


def warn(text: str) -> None:
    print(paint("  [WARN] ", "yellow") + text)


def bullet(text: str) -> None:
    print(paint("  - ", "gray") + text)


def table(headers: list[str], rows: list[list[str]], *, aligns: list[str] | None = None) -> None:
    """简易表格，按显示宽度对齐。aligns 取值 l/c/r。"""
    cols = len(headers)
    aligns = aligns or ["l"] * cols
    widths = [width(h) for h in headers]
    for row in rows:
        for i in range(cols):
            cell = str(row[i]) if i < len(row) else ""
            widths[i] = max(widths[i], width(cell))

    def render(cells: list[str]) -> str:
        out = []
        for i, cell in enumerate(cells):
            fill = widths[i] - width(cell)
            if aligns[i] == "r":
                out.append(" " * fill + cell)
            elif aligns[i] == "c":
                left = fill // 2
                out.append(" " * left + cell + " " * (fill - left))
            else:
                out.append(cell + " " * fill)
        return "  " + "  ".join(out).rstrip()

    print(paint(render(headers), "bold"))
    print(paint("  " + "  ".join("-" * w for w in widths), "gray"))
    for row in rows:
        print(render([str(c) for c in row]))
