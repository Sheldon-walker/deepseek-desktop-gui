#!/usr/bin/env python
"""DeepSeek 桌面版 —— 图形界面入口。

    python app.py

打包成 exe 后双击运行，配置与会话都在程序目录的 data 子目录里。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _enable_dpi_awareness() -> None:
    """在创建任何 Tk 窗口前显式开启 DPI 感知，避免高分屏下窗口尺寸/字体被虚拟化缩放。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # Win10 1703+：Per-Monitor V2（值为 -4）
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except Exception:
            pass
        # 退而求其次：Per-Monitor Aware
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main() -> int:
    _enable_dpi_awareness()
    try:
        from ui.window import App
    except ImportError as exc:
        print("缺少依赖：", exc)
        print("请先执行：pip install -r requirements.txt")
        return 1

    try:
        app = App()
        app.mainloop()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        try:
            from tkinter import messagebox

            messagebox.showerror("程序异常", traceback.format_exc()[-1200:])
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
