"""内存播放（Windows WinMM PlaySound），不落盘、不引额外依赖。

TTS 返回的是完整 WAV，直接把内存地址交给 `PlaySoundW(..., SND_MEMORY)` 就能响，
不需要临时文件，也不需要 pygame / simpleaudio / pydub（这些都会让单文件 exe 变大）。

为什么用 SND_ASYNC 而不是同步：
- 同步调用会阻塞到播放结束，而用 PlaySound(NULL) 去停止时**打断不了**另一个线程里
  正在阻塞的同步播放（实测会一直播完），所以同步模式没法做「点一下停止」；
- 异步模式调用立即返回，停止就是再调一次 PlaySound(NULL)，符合官方文档的用法。

代价是拿不到系统级的播放完成事件，用 WAV 头里的时长估算播放位置，
误差在几十毫秒级，对「朗读」这种场景够用。
"""

from __future__ import annotations

import ctypes
import io
import struct
import sys
import threading
import time
import wave
from ctypes import wintypes

SND_SYNC = 0x0000
SND_ASYNC = 0x0001
SND_NODEFAULT = 0x0002
SND_MEMORY = 0x0004


class PlaybackError(Exception):
    """播放相关错误，消息可直接展示给用户。"""


if sys.platform == "win32":
    _winmm = ctypes.WinDLL("winmm")
    _winmm.PlaySoundW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    _winmm.PlaySoundW.restype = wintypes.BOOL
    _winmm.waveOutGetNumDevs.restype = wintypes.UINT


def available() -> bool:
    """当前平台能不能播放。"""
    return sys.platform == "win32"


def wav_seconds(data: bytes) -> float:
    """从 WAV 头算时长。"""
    with wave.open(io.BytesIO(data), "rb") as wf:
        rate = wf.getframerate()
        return wf.getnframes() / rate if rate else 0.0


def has_output_device() -> bool:
    """当前是否有可用的音频输出设备（扬声器/耳机）。"""
    if not available():
        return False
    try:
        return _winmm.waveOutGetNumDevs() > 0
    except Exception:
        return False


def repair_wav(data: bytes) -> bytes:
    """把带流式/损坏头的 WAV 规范成标准 WAV。

    官方 TTS 是边合成边下发，`data` 块长度会写成 0xFFFFFFFF（未知长度），
    PlaySound / wave 模块读这种头会失败或算错时长。这里重新解析 fmt/data，
    用标准库 wave 重写一份头，长度填真实值。
    """
    if not data or data[:4] != b"RIFF" or len(data) < 44:
        return data
    pos = 12
    fmt = b""
    data_off = 0
    data_size = 0
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        if cid == b"fmt " and not fmt:
            fmt = data[pos + 8 : pos + 8 + min(size, 40)]
        if cid == b"data":
            data_off = pos + 8
            data_size = len(data) - data_off
            break
        pos += 8 + size + (size & 1)
    if not fmt or not data_off or data_size <= 0:
        return data

    fmt_tag, channels, rate, _avg, _align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if fmt_tag == 0xFFFE:                      # WAVE_FORMAT_EXTENSIBLE
        if len(fmt) < 26:
            return data
        fmt_tag = struct.unpack("<H", fmt[24:26])[0]
    if fmt_tag != 1 or bits not in (8, 16):    # 只处理 PCM
        return data

    pcm = data[data_off : data_off + data_size]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bits // 8)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def is_wav(data: bytes) -> bool:
    return len(data) > 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


class WavPlayer:
    """同一时刻只播一段；再次 play 会先停掉上一段。"""

    def __init__(self) -> None:
        self._buffer = None            # 当前播放的音频内存，必须一直持有引用
        self._retired = None           # 上一段缓冲，多留一轮，防止停止后引擎还在读
        self._playing = False
        self._started_at = 0.0
        self._duration = 0.0
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()

    # ---------- 状态 ----------
    @property
    def is_playing(self) -> bool:
        if not self._playing:
            return False
        if time.monotonic() - self._started_at >= self._duration:
            self._playing = False
            return False
        return True

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        if not self._playing:
            return 0.0
        return min(self._duration, time.monotonic() - self._started_at)

    # ---------- 播放 ----------
    def play(self, wav: bytes) -> float:
        """播放一段内存里的 WAV，立即返回时长（秒）。"""
        if not available():
            raise PlaybackError("朗读目前只支持 Windows")
        if not wav:
            raise PlaybackError("音频数据为空")
        wav = repair_wav(wav)          # 关键：官方流式 WAV 的头长度是 0xFFFFFFFF
        if not is_wav(wav):
            raise PlaybackError("音频数据不是合法的 WAV")
        if not has_output_device():
            raise PlaybackError("没有检测到可用的音频输出设备（扬声器/耳机）")
        try:
            seconds = wav_seconds(wav)
        except (wave.Error, EOFError) as exc:
            raise PlaybackError(f"WAV 头解析失败：{exc}") from exc
        if seconds <= 0:
            raise PlaybackError("音频时长为 0")

        with self._lock:
            self._silence()
            # 保留旧缓冲一轮再释放：PlaySound 停止后驱动可能还在读最后几个字节
            self._retired = self._buffer
            self._buffer = ctypes.create_string_buffer(wav, len(wav))
            ptr = ctypes.cast(self._buffer, ctypes.c_void_p)
            ok = _winmm.PlaySoundW(ptr, None, SND_MEMORY | SND_ASYNC | SND_NODEFAULT)
            if not ok:
                self._buffer = None
                raise PlaybackError("系统无法播放这段音频")
            self._stop_evt.clear()
            self._duration = seconds
            self._started_at = time.monotonic()
            self._playing = True
        return seconds

    def stop(self) -> None:
        with self._lock:
            self._silence()

    # ---------- 内部 ----------
    def _silence(self) -> None:
        self._stop_evt.set()
        if available():
            try:
                _winmm.PlaySoundW(None, None, 0)      # 传 NULL 即停止当前播放
            except Exception:
                pass
        self._playing = False

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞到播放结束或被停止。返回 True 表示正常播完。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.is_playing:
            if self._stop_evt.is_set():
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return not self._stop_evt.is_set()

    def close(self) -> None:
        self.stop()
        self._buffer = None
        self._retired = None


__all__ = ["PlaybackError", "WavPlayer", "available", "has_output_device", "is_wav", "repair_wav", "wav_seconds"]
