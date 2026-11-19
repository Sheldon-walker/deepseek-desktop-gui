"""语音识别（ASR）接口封装。

接口：POST {base}/v1/tools/asr
- multipart 的 `file` 字段，格式仅支持 16bit PCM WAV 或 Ogg Opus；
- 单次 ≤8MB、时长 ≤120 秒；立体声只识别左声道；
- 不支持流式，整段上传后返回整段文本；
- 按音频时长计费：$0.116 / 小时（官方限时 5 折 $0.058，以官网为准）。

语言不用传，服务端自动识别（支持中文、粤语、英语、日语等 21 种）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import DeepSeekClient
from .errors import DSException, from_http, from_network

MAX_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 120
ASR_PER_HOUR = 0.116


@dataclass
class AsrResult:
    text: str = ""
    duration_ms: int = 0
    request_id: str = ""
    bytes_sent: int = 0

    @property
    def seconds(self) -> float:
        return self.duration_ms / 1000 if self.duration_ms else 0.0

    def cost(self, rate_per_hour: float = ASR_PER_HOUR) -> float:
        return self.seconds / 3600 * rate_per_hour

    def format_cost(self, cny_rate: float = 7.10) -> str:
        usd = self.cost()
        return f"${usd:.6f} / ¥{usd * cny_rate:.5f}"


def transcribe(
    client: DeepSeekClient,
    wav: bytes,
    *,
    filename: str = "voice.wav",
    timeout: tuple[int, int] = (20, 180),
) -> AsrResult:
    """把一段 WAV 交给官方 ASR，返回识别文本。

    wav 直接来自 dskit.audio.WavRecorder.stop().wav，只在内存里传，不落盘。
    """
    if not wav:
        raise DSException("录音数据为空", code="empty_audio", hint="按住按钮说话，松开后自动识别")
    if len(wav) > MAX_BYTES:
        raise DSException(
            f"录音文件过大（{len(wav) / 1024 / 1024:.1f}MB）",
            code="audio_too_large",
            hint="接口上限 8MB（约 4 分钟），请分段说",
        )
    if not client.cfg.has_key:
        from .errors import missing_key

        raise missing_key()

    # 上传要走 multipart：显式给 headers（不带 Content-Type），让 requests 自己拼 boundary
    data = client.request(
        "POST",
        "/v1/tools/asr",
        files={"file": (filename, wav, "audio/wav")},
        headers={"Authorization": f"Bearer {client.cfg.api_key}"},
        timeout=timeout,
        retries=1,
    )

    return AsrResult(
        text=str(data.get("text") or "").strip(),
        duration_ms=int(data.get("duration_ms") or 0),
        request_id=str(data.get("request_id") or ""),
        bytes_sent=len(wav),
    )


def describe_error(exc: DSException) -> str:
    """给界面用的短提示。"""
    if exc.status == 400:
        return "音频格式不对（需要 16bit PCM WAV）"
    if exc.status == 413:
        return "音频太大，请缩短录音"
    if exc.status == 429:
        return "识别请求太频繁，稍后再试"
    if exc.status in (503, 504):
        return "识别服务繁忙，稍后再试"
    return str(exc)


__all__ = ["ASR_PER_HOUR", "AsrResult", "MAX_BYTES", "MAX_SECONDS", "describe_error", "from_http", "from_network", "transcribe"]
