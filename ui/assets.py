"""把 assets 里的图片转成可内联的 data URI（WebView2 页面里直接用，不用起本地服务）。"""

from __future__ import annotations

import base64
import io
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"


def data_uri(name: str, box: int, *, pad: bool = False) -> str:
    """读 assets/icons 下的 PNG，等比缩到 box 像素内，返回 data:image/png;base64,..."""
    try:
        from PIL import Image

        img = Image.open(ICON_DIR / name).convert("RGBA")
        if pad:
            bbox = img.split()[-1].getbbox()
            if bbox:
                img = img.crop(bbox)
        w, h = img.size
        scale = box / max(1, max(w, h))
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""
