"""语音合成（TTS）接口封装。

接口：POST {base}/v1/tools/tts
- JSON 请求：text（必填）、voice_id（stella / tide）、format（wav / pcm）、filter_markdown（默认 true）；
- 响应体是**音频二进制流**（wav 返回 audio/wav；pcm 是 24kHz 16bit 单声道裸数据）；
- 单次最多 10,000 计费字符、请求体 64KiB、音频最长 30 分钟；
- 不支持语速控制，也不支持断点续传；
- 计费：每 10,000 字符 $0.45（官方限时 5 折 $0.225）。
  一个汉字算 2 个字符，字母/数字/空格等各算 1 个。

这里多做两件事：
1. `prepare_text()` 把 Markdown 洗干净（代码块、表格、引用编号这些念出来很怪）；
2. `split_chunks()` 把长文按句子切成多段，避免超过单次上限，也让第一段能更快出声。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import audio, player
from .client import DeepSeekClient
from .errors import DSException, missing_key

VOICES = {"stella": "女声 · Stella", "tide": "男声 · Tide"}
DEFAULT_VOICE = "stella"

PRICE_PER_10K = 0.45          # 美元 / 万字符（官方标价）
PRICE_PROMO_PER_10K = 0.225   # 限时 5 折
MAX_BILLED = 10000            # 单次上限（计费字符）
MAX_BODY_BYTES = 64 * 1024    # 请求体上限
CHUNK_BILLED = 4500           # 分段阈值：留足余量，长文也能较快听到第一段

# ---------------------------------------------------------------- 文本处理

_FENCE = re.compile(r"```[^\n]*\n.*?```", re.S)
_FENCE_TAIL = re.compile(r"```.*\Z", re.S)          # 未闭合的代码块
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_CITE = re.compile(r"\[(?:\d{1,3}|\^\d+|citation:\d+)\]")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.M)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_LIST = re.compile(r"^\s*(?:[-*+]|\d{1,2}[.)])\s+", re.M)
_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)
_BOLD = re.compile(r"(\*\*|__)(.+?)\1", re.S)
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]{1,120})\*(?![*\w])")
_CODE = re.compile(r"`([^`]*)`")
_URL = re.compile(r"https?://[^\s)\]，。；、）]+")
_TAG = re.compile(r"<[^>\n]{1,40}>")
_WS = re.compile(r"[ \t\u3000]{2,}")


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x3400 <= o <= 0x4DBF      # 扩展 A
        or 0x4E00 <= o <= 0x9FFF   # 基本区
        or 0xF900 <= o <= 0xFAFF   # 兼容表意
        or 0x3000 <= o <= 0x303F   # 中文标点（、。「」等）
        or 0xFF01 <= o <= 0xFF0F   # 全角 ！＂＃…／
        or 0xFF1A <= o <= 0xFF20   # 全角 ：；＜＝＞？＠
        or 0xFF3B <= o <= 0xFF40   # 全角 ［＼］＾＿｀
        or 0xFF5B <= o <= 0xFF65   # 全角 ｛｜｝～・
    )


def billed_chars(text: str) -> int:
    """按官方规则估算计费字符：汉字 2，其它 1。"""
    return sum(2 if is_cjk(ch) else 1 for ch in (text or ""))


def prepare_text(markdown: str) -> str:
    """把要给模型看的 Markdown 洗成适合朗读的纯文本。

    代码块和表格整段丢掉——念出来没有意义，还会把大部分时长耗在这上面。
    """
    text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return ""
    text = _FENCE.sub("\n", text)
    text = _FENCE_TAIL.sub("\n", text)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _TABLE_LINE.sub("", text)
    text = _HR.sub("", text)
    text = _CITE.sub("", text)
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    text = _LIST.sub("", text)
    text = _BOLD.sub(lambda m: m.group(2), text)
    text = _ITALIC.sub(lambda m: m.group(1), text)
    text = _CODE.sub(lambda m: m.group(1), text)
    text = _URL.sub("", text)
    text = _TAG.sub("", text)
    text = _WS.sub(" ", text)

    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def split_chunks(text: str, limit: int = CHUNK_BILLED) -> list[str]:
    """按句子边界切段，每段计费字符不超过 limit。"""
    text = (text or "").strip()
    if not text:
        return []
    if billed_chars(text) <= limit:
        return [text]

    pieces = re.split(r"(?<=[。！？!?；;…\n])", text)
    chunks: list[str] = []
    buf = ""
    size = 0
    for piece in pieces:
        if not piece:
            continue
        n = billed_chars(piece)
        if n > limit:                      # 单句超长（没有标点），硬切
            if buf.strip():
                chunks.append(buf.strip())
            chunks.extend(_hard_split(piece, limit))
            buf, size = "", 0
            continue
        if buf and size + n > limit:
            chunks.append(buf.strip())
            buf, size = "", 0
        buf += piece
        size += n
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def _hard_split(text: str, limit: int) -> list[str]:
    out: list[str] = []
    buf = ""
    size = 0
    for ch in text:
        n = 2 if is_cjk(ch) else 1
        if buf and size + n > limit:
            out.append(buf.strip())
            buf, size = "", 0
        buf += ch
        size += n
    if buf.strip():
        out.append(buf.strip())
    return out


# ---------------------------------------------------------------- 接口

@dataclass
class TtsResult:
    audio: bytes = b""
    text: str = ""
    voice_id: str = DEFAULT_VOICE
    fmt: str = "wav"
    billed: int = 0
    seconds: float = 0.0
    content_type: str = ""

    @property
    def size(self) -> int:
        return len(self.audio)

    def cost(self, per_10k: float = PRICE_PER_10K) -> float:
        return self.billed / 10000 * per_10k

    def format_cost(self, cny_rate: float = 7.10) -> str:
        usd = self.cost()
        return f"${usd:.6f} / ¥{usd * cny_rate:.5f}"


def synthesize(
    client: DeepSeekClient,
    text: str,
    *,
    voice_id: str = DEFAULT_VOICE,
    fmt: str = "wav",
    filter_markdown: bool = True,
    timeout: tuple[float, float] = (15, 300),
    on_progress=None,
) -> TtsResult:
    """合成一段文字，音频只在内存里返回，不写文件。"""
    cleaned = (text or "").strip()
    if not cleaned:
        raise DSException("没有可朗读的文字", code="empty_text", hint="这段回答主要是代码或空内容")
    if voice_id not in VOICES:
        voice_id = DEFAULT_VOICE
    if fmt not in ("wav", "pcm"):
        fmt = "wav"

    billed = billed_chars(cleaned)
    if billed > MAX_BILLED:
        raise DSException(
            f"文本超过单次上限（约 {billed} 计费字符，上限 {MAX_BILLED}）",
            code="text_too_long",
            hint="请分段朗读，或换一段更短的内容",
        )
    if not client.cfg.has_key:
        raise missing_key()

    body = {
        "text": cleaned,
        "voice_id": voice_id,
        "format": fmt,
        "filter_markdown": bool(filter_markdown),
    }
    raw, ctype = client.post_binary(
        "/v1/tools/tts",
        json_body=body,
        retries=1,
        timeout=timeout,
        on_progress=on_progress,
    )
    if not raw:
        raise DSException("合成结果为空", code="empty_audio", hint="换一段文字再试")

    raw = player.repair_wav(raw)   # 官方是流式 WAV，头长度 0xFFFFFFFF，需修复后才能算时长/播放

    seconds = 0.0
    if fmt == "wav":
        try:
            seconds = audio.wav_info(raw)["seconds"]
        except Exception as exc:  # noqa: BLE001
            raise DSException(
                "返回的音频不是合法 WAV",
                code="bad_audio",
                detail=f"{raw[:16]!r}",
            ) from exc
    else:
        seconds = len(raw) / (24000 * 2)      # 24kHz 16bit 单声道

    return TtsResult(
        audio=raw,
        text=cleaned,
        voice_id=voice_id,
        fmt=fmt,
        billed=billed,
        seconds=seconds,
        content_type=ctype,
    )


def describe_error(exc: DSException) -> str:
    """给界面用的短提示。"""
    if exc.status == 400:
        return "这段文字无法合成（可能为空或未通过内容审核）"
    if exc.status == 402:
        return "账户余额不足，无法合成语音"
    if exc.status == 429:
        return "合成请求太多，稍后再试"
    if exc.status in (503, 504):
        return "合成服务繁忙，稍后再试"
    return str(exc)


__all__ = [
    "CHUNK_BILLED",
    "DEFAULT_VOICE",
    "MAX_BILLED",
    "PRICE_PER_10K",
    "PRICE_PROMO_PER_10K",
    "TtsResult",
    "VOICES",
    "billed_chars",
    "describe_error",
    "is_cjk",
    "prepare_text",
    "split_chunks",
    "synthesize",
]
