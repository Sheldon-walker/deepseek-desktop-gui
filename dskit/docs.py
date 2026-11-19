"""PDF / Word / PPT / 表格 / 图片 的文件解析封装。

主路径：走官方 Files API 上传解析，拿到 file_id 后在对话里用
`{"type": "file", "file_id": ...}` 引用。好处是扫描件、图表、复杂版式
都由服务端处理，本地不需要 pypdf / python-docx 这些依赖（打包更小）。

  POST {base}/files        multipart: purpose 必须排在 file 之前
  purpose=text_recognition          只取文字（合同、论文、扫描件）
  purpose=rich_layout_recognition   文字 + 图表按原位置交给模型（财报、PPT）
  purpose=user_data                 txt/md/csv/json/xlsx/xls/epub/mobi/图片

备选路径：本地抽文本（local_text），仅在装了 pypdf / python-docx 时生效，
用于预览前 N 字、或在 file_id 过期后仍能复用历史结论。
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from .client import DeepSeekClient
from .errors import DSException

# 需要服务端解析的版式文档
LAYOUT_EXTS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
# 上传即转 Markdown，不计费
DATA_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".xlsx", ".xls", ".epub", ".mobi"}
CODE_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".sh", ".sql", ".yaml", ".yml", ".toml", ".ini", ".log", ".html", ".css", ".xml"}

MAX_UPLOAD = {"layout": 100 * 1024 * 1024, "data": 32 * 1024 * 1024}


@dataclass
class FileRef:
    """一次上传的结果，可存进本地历史 json 里复用。"""

    file_id: str = ""
    filename: str = ""
    size: int = 0
    purpose: str = ""
    local_path: str = ""
    chars: int = 0          # 本地预览抽到的字数（拿不到就是 0）
    preview: str = ""       # 本地预览前 300 字

    @classmethod
    def from_api(cls, raw: dict, *, local_path: str = "") -> "FileRef":
        return cls(
            file_id=str(raw.get("id") or ""),
            filename=str(raw.get("filename") or ""),
            size=int(raw.get("bytes") or 0),
            purpose=str(raw.get("purpose") or ""),
            local_path=local_path,
        )

    def block(self) -> dict:
        """对话消息里的引用块。"""
        return {"type": "file", "file_id": self.file_id}

    def display(self) -> str:
        return f"{self.filename}（{human_size(self.size)}，{self.purpose or 'n/a'}）"


def human_size(num: int) -> str:
    if not num:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def pick_purpose(path: Path, *, rich_layout: bool = False) -> str:
    ext = path.suffix.lower()
    if ext in LAYOUT_EXTS:
        return "rich_layout_recognition" if rich_layout else "text_recognition"
    if ext in DATA_EXTS or ext in CODE_EXTS:
        return "user_data"
    raise DSException(
        f"暂不支持的文件类型：{ext or '无扩展名'}",
        code="unsupported_file",
        hint="支持 PDF / Word / PPT / Excel / 图片 / txt / md / csv / json / 代码文件 / epub",
    )


def _ascii_filename(name: str) -> str:
    """multipart 的 filename 用 ASCII，避免不同 urllib3 版本对中文编码不一致。

    真实文件名只用于界面展示，服务端按文件内容判断格式，不依赖文件名。
    """
    try:
        name.encode("ascii")
        return name
    except UnicodeEncodeError:
        ext = Path(name).suffix or ".bin"
        return "document" + ext


def upload_document(
    client: DeepSeekClient,
    path: str | Path,
    *,
    rich_layout: bool = False,
    expire_seconds: int = 0,
) -> FileRef:
    """上传并解析文件，返回 FileRef。

    注意超时：文档解析在服务端进行，上传+解析最长各 120 秒，这里给 300 秒读超时。
    """
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        raise DSException(f"文件不存在：{p}", code="file_not_found", hint="检查路径是否正确")
    purpose = pick_purpose(p, rich_layout=rich_layout)
    size = p.stat().st_size
    limit = MAX_UPLOAD["layout"] if purpose != "user_data" else MAX_UPLOAD["data"]
    if size > limit:
        raise DSException(
            f"文件过大：{human_size(size)}",
            code="file_too_large",
            hint=f"该类型上限 {human_size(limit)}",
        )

    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    data: dict[str, str] = {}
    if expire_seconds:
        data["expires_after[anchor]"] = "created_at"
        data["expires_after[seconds]"] = str(int(expire_seconds))

    with p.open("rb") as fh:
        # requests 会按 files 列表顺序写表单：purpose 一定要在 file 之前
        files = [
            ("purpose", (None, purpose)),
            ("file", (_ascii_filename(p.name), fh, mime)),
        ]
        raw = client.request(
            "POST",
            "/files",
            files=files,
            data=data or None,
            headers={"Authorization": f"Bearer {client.cfg.api_key}"},
            timeout=(30, 300),
            retries=0,
        )

    ref = FileRef.from_api(raw, local_path=str(p))
    if not ref.file_id:
        raise DSException("上传成功但没拿到 file_id", code="bad_file_response", detail=str(raw)[:300])
    return ref


def delete_file(client: DeepSeekClient, file_id: str) -> bool:
    """删除云端的解析结果（本地历史里如果还引用它就会失效，谨慎调用）。"""
    client.request("DELETE", f"/files/{file_id}", retries=0)
    return True


def list_files(client: DeepSeekClient, *, limit: int = 20) -> list[dict]:
    data = client.request("GET", "/files", params={"limit": str(limit), "order": "desc"}, retries=0)
    return list(data.get("data") or [])


# ---------- 本地抽取（可选依赖） ----------
def local_text(path: str | Path, *, max_chars: int = 20000) -> str:
    """尽量在本地把文本抽出来，用于预览或离线兜底。

    txt/md/csv/json/代码：纯标准库即可。
    pdf / docx：需要 pypdf / python-docx，没装就返回空串（不报错）。
    """
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext in DATA_EXTS or ext in CODE_EXTS:
            raw = p.read_bytes()
            for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
                try:
                    return raw.decode(enc)[:max_chars]
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "replace")[:max_chars]
        if ext == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore
            except ImportError:
                return ""
            reader = PdfReader(str(p))
            out: list[str] = []
            for page in reader.pages:
                out.append(page.extract_text() or "")
                if sum(len(x) for x in out) > max_chars:
                    break
            return re.sub(r"\n{3,}", "\n\n", "\n".join(out))[:max_chars]
        if ext == ".docx":
            try:
                import docx  # type: ignore
            except ImportError:
                return ""
            document = docx.Document(str(p))
            return "\n".join(par.text for par in document.paragraphs)[:max_chars]
    except Exception:  # 本地抽取永远不该阻断主流程
        return ""
    return ""


def attach_preview(ref: FileRef, path: str | Path) -> FileRef:
    """给 FileRef 填上本地预览，便于界面显示"已读取 N 字"。"""
    text = local_text(path, max_chars=2000)
    if text:
        ref.chars = len(text)
        ref.preview = text[:300].replace("\r", "")
    return ref


# ---------- 自检用：生成一个最小可用 PDF ----------
def make_minimal_pdf(path: str | Path, lines: list[str] | None = None) -> Path:
    """手搓一个合法 PDF，供自检脚本验证"上传-解析-提问"链路，免装第三方库。"""
    lines = lines or ["DEEPSEEK DESKTOP PARSER TEST", "keyword: BLUEWHALE-2026"]
    body = "BT /F1 14 Tf 60 780 Td " + " ".join(
        f"({line.replace(chr(92), '').replace('(', '').replace(')', '')}) Tj 0 -22 Td" for line in lines
    ) + " ET"
    body_bytes = body.encode("latin-1", "replace")
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(body_bytes)} >>\nstream\n{body}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets: list[int] = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1", "replace")
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("latin-1")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    return target
