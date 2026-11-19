"""本地录音（Windows WinMM），不依赖 sounddevice / numpy。

为什么手写 ctypes：
- 最终要打成单文件 exe，sounddevice 会带进 PortAudio + 通常还要 numpy（十几 MB）；
- ASR 接口只认 16bit PCM WAV，WinMM 能直接按这个格式录，省掉重采样；
- 录音数据只在内存里拼 WAV，不落盘，隐私上更干净。

对外只有三个东西：has_input_device() / WavRecorder.start() / WavRecorder.stop()。
非 Windows 平台会抛 RecordError，UI 里会提示不支持。
"""

from __future__ import annotations

import ctypes
import io
import os
import struct
import sys
import time
import wave
from dataclasses import dataclass
from ctypes import wintypes

WAVE_MAPPER = 0xFFFFFFFF
WAVE_FORMAT_PCM = 1
CALLBACK_NULL = 0
WHDR_DONE = 0x00000001
MMSYSERR_NOERROR = 0

_ERRORS = {
    2: "设备 ID 无效",
    3: "设备被禁用或未启用",
    4: "设备已被占用",
    5: "句柄无效",
    6: "找不到音频驱动",
    7: "内存不足",
    8: "设备不支持该音频格式",
    11: "参数无效（采样率或声道不被支持）",
    12: "设备正忙",
}

MAX_SECONDS = 115          # 接口上限 120 秒，留点余量
MAX_BYTES = 8 * 1024 * 1024


class RecordError(Exception):
    """录音相关错误，消息可直接给用户看。"""


if sys.platform == "win32":

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", wintypes.WORD),
            ("nChannels", wintypes.WORD),
            ("nSamplesPerSec", wintypes.DWORD),
            ("nAvgBytesPerSec", wintypes.DWORD),
            ("nBlockAlign", wintypes.WORD),
            ("wBitsPerSample", wintypes.WORD),
            ("cbSize", wintypes.WORD),
        ]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.c_void_p),
            ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD),
            ("dwUser", ctypes.c_void_p),
            ("dwFlags", wintypes.DWORD),
            ("dwLoops", wintypes.DWORD),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.c_void_p),
        ]

    _winmm = ctypes.WinDLL("winmm")
    _winmm.waveInGetNumDevs.restype = wintypes.UINT
    _winmm.waveInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_size_t,
        ctypes.POINTER(WAVEFORMATEX),
        ctypes.c_size_t,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    _winmm.waveInOpen.restype = wintypes.UINT
    _winmm.waveInPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), wintypes.UINT]
    _winmm.waveInUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), wintypes.UINT]
    _winmm.waveInAddBuffer.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), wintypes.UINT]
    _winmm.waveInStart.argtypes = [ctypes.c_void_p]
    _winmm.waveInStop.argtypes = [ctypes.c_void_p]
    _winmm.waveInReset.argtypes = [ctypes.c_void_p]
    _winmm.waveInClose.argtypes = [ctypes.c_void_p]


def _err(code: int) -> str:
    return _ERRORS.get(code, f"错误码 {code}")


def has_input_device() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return _winmm.waveInGetNumDevs() > 0
    except Exception:
        return False


@dataclass
class Recording:
    wav: bytes
    seconds: float
    rate: int
    channels: int = 1

    @property
    def size(self) -> int:
        return len(self.wav)


class WavRecorder:
    """单缓冲录音：开一块够 115 秒的内存，停止时取已录字节数。"""

    def __init__(self, *, max_seconds: int = MAX_SECONDS, preferred_rate: int = 16000) -> None:
        self.max_seconds = max(1, min(int(max_seconds), MAX_SECONDS))
        self.preferred_rate = preferred_rate
        self._handle = ctypes.c_void_p()
        self._buffer = None
        self._header = None
        self._rate = preferred_rate
        self._channels = 1
        self._started_at = 0.0
        self._open = False

    # ---------- 状态 ----------
    @property
    def is_recording(self) -> bool:
        return self._open

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._open else 0.0

    @property
    def reached_limit(self) -> bool:
        return self._open and self.elapsed >= self.max_seconds - 1

    # ---------- 开始 ----------
    def start(self) -> None:
        if sys.platform != "win32":
            raise RecordError("语音输入目前只支持 Windows")
        if self._open:
            return
        if not has_input_device():
            raise RecordError("没有检测到麦克风，请检查系统录音设备")

        last = None
        for rate in (self.preferred_rate, 44100, 48000):
            try:
                self._open_device(rate)
                self._started_at = time.monotonic()
                return
            except RecordError as exc:
                last = exc
                self._cleanup()
        raise last or RecordError("无法打开录音设备")

    def _open_device(self, rate: int) -> None:
        fmt = WAVEFORMATEX(
            wFormatTag=WAVE_FORMAT_PCM,
            nChannels=1,
            nSamplesPerSec=rate,
            nAvgBytesPerSec=rate * 2,
            nBlockAlign=2,
            wBitsPerSample=16,
            cbSize=0,
        )
        handle = ctypes.c_void_p()
        rc = _winmm.waveInOpen(ctypes.byref(handle), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, CALLBACK_NULL)
        if rc != MMSYSERR_NOERROR:
            raise RecordError(f"打开麦克风失败：{_err(rc)}")

        size = rate * 2 * self.max_seconds
        buffer = ctypes.create_string_buffer(size)
        header = WAVEHDR(
            lpData=ctypes.cast(buffer, ctypes.c_void_p),
            dwBufferLength=size,
            dwBytesRecorded=0,
            dwUser=None,
            dwFlags=0,
            dwLoops=0,
            lpNext=None,
            reserved=None,
        )
        rc = _winmm.waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        if rc != MMSYSERR_NOERROR:
            _winmm.waveInClose(handle)
            raise RecordError(f"准备录音缓冲失败：{_err(rc)}")
        rc = _winmm.waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(header))
        if rc != MMSYSERR_NOERROR:
            _winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
            _winmm.waveInClose(handle)
            raise RecordError(f"挂载录音缓冲失败：{_err(rc)}")
        rc = _winmm.waveInStart(handle)
        if rc != MMSYSERR_NOERROR:
            _winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
            _winmm.waveInClose(handle)
            raise RecordError(f"启动录音失败：{_err(rc)}")

        self._handle = handle
        self._buffer = buffer
        self._header = header
        self._rate = rate
        self._open = True

    # ---------- 停止 ----------
    def stop(self) -> Recording:
        if not self._open:
            raise RecordError("当前没有在录音")
        seconds = self.elapsed
        header = self._header
        try:
            _winmm.waveInStop(self._handle)
            _winmm.waveInReset(self._handle)       # 回收缓冲并写回 dwBytesRecorded
            _winmm.waveInUnprepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))
        finally:
            _winmm.waveInClose(self._handle)
            self._open = False

        size = int(header.dwBytesRecorded or 0)
        raw = ctypes.string_at(header.lpData, size) if size > 0 else b""
        self._buffer = None
        self._header = None
        self._handle = ctypes.c_void_p()
        return Recording(wav=_to_wav(raw, self._rate, self._channels), seconds=seconds, rate=self._rate)

    def cancel(self) -> None:
        """放弃本次录音，不生成 WAV。"""
        if not self._open:
            return
        try:
            _winmm.waveInStop(self._handle)
            _winmm.waveInReset(self._handle)
            if self._header is not None:
                _winmm.waveInUnprepareHeader(self._handle, ctypes.byref(self._header), ctypes.sizeof(self._header))
        except Exception:
            pass
        finally:
            try:
                _winmm.waveInClose(self._handle)
            except Exception:
                pass
            self._open = False
            self._buffer = None
            self._header = None
            self._handle = ctypes.c_void_p()

    def _cleanup(self) -> None:
        try:
            if self._handle:
                _winmm.waveInClose(self._handle)
        except Exception:
            pass
        self._open = False
        self._buffer = None
        self._header = None
        self._handle = ctypes.c_void_p()


def _to_wav(pcm: bytes, rate: int, channels: int) -> bytes:
    """把裸 PCM 包成 WAV。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def wav_info(data: bytes) -> dict:
    """读一下 WAV 头，自检和日志用。"""
    with wave.open(io.BytesIO(data), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return {
            "channels": wf.getnchannels(),
            "rate": rate,
            "width": wf.getsampwidth(),
            "frames": frames,
            "seconds": frames / rate if rate else 0,
        }


def peak_level(pcm_or_wav: bytes) -> int:
    """粗略的峰值电平，用于判断是不是录到了静音（0-32767）。"""
    data = pcm_or_wav
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as wf:
            data = wf.readframes(wf.getnframes())
    if not data:
        return 0
    peak = 0
    for (sample,) in struct.iter_unpack("<h", data[: len(data) // 2 * 2]):
        value = sample if sample >= 0 else -sample
        if value > peak:
            peak = value
            if peak >= 32000:
                break
    return peak


__all__ = [
    "MAX_BYTES",
    "MAX_SECONDS",
    "RecordError",
    "Recording",
    "WavRecorder",
    "has_input_device",
    "peak_level",
    "wav_info",
]
