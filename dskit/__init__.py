"""dskit —— DeepSeek 桌面客户端的 API 封装层。

CLI demo 与后续 GUI 共用同一套接口，不含任何界面代码。

快速开始::

    from dskit import Config, DeepSeekClient, search, fetch_url, upload_document

    cfg = Config.load()
    client = DeepSeekClient(cfg)

    stream = client.chat_stream([{"role": "user", "content": "你好"}])
    for event in stream:
        if event.kind == "content":
            print(event.data, end="", flush=True)
    print(stream.usage.summary())
"""

from __future__ import annotations

from . import asr, audio, console, docs, errors, importer, player, search, session, tts, usage
from .client import DEFAULT_SYSTEM_PROMPT, ChatStream, DeepSeekClient, Event, ToolCallInfo
from .config import AVAILABLE_MODELS, TTS_VOICES, Config, base_dir, data_dir
from .docs import FileRef, delete_file, list_files, local_text, upload_document
from .errors import DSException
from .importer import ImportedSession, load_path, to_session
from .search import FetchedPage, SearchResult, build_context, extract_urls, fetch_url, search
from .session import Session, SessionStore
from .usage import Cost, Usage, is_peak

__all__ = [
    "AVAILABLE_MODELS",
    "TTS_VOICES",
    "ChatStream",
    "Config",
    "Cost",
    "DEFAULT_SYSTEM_PROMPT",
    "DSException",
    "DeepSeekClient",
    "Event",
    "FetchedPage",
    "FileRef",
    "ImportedSession",
    "SearchResult",
    "Session",
    "SessionStore",
    "ToolCallInfo",
    "Usage",
    "asr",
    "audio",
    "base_dir",
    "build_context",
    "console",
    "data_dir",
    "delete_file",
    "docs",
    "errors",
    "extract_urls",
    "fetch_url",
    "importer",
    "is_peak",
    "list_files",
    "load_path",
    "local_text",
    "player",
    "search",
    "session",
    "to_session",
    "tts",
    "upload_document",
    "usage",
]
