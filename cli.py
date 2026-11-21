#!/usr/bin/env python
"""DeepSeek 桌面客户端 —— 阶段 1 命令行 demo。

用法：
    python cli.py verify                  # 全链路自检（推荐第一步）
    python cli.py chat "介绍一下 DeepSeek V4.1"
    python cli.py chat "这篇文档讲了什么" -f 报告.pdf --think
    python cli.py chat "总结这个页面" -u https://example.com
    python cli.py repl                    # 交互式多轮对话
    python cli.py search "量子计算 2026 进展"
    python cli.py fetch https://example.com
    python cli.py doc 合同.pdf            # 只上传解析，拿 file_id
    python cli.py asr --record 5          # 录 5 秒并识别（验证麦克风与 ASR）
    python cli.py asr speech.wav          # 识别现成的 16bit WAV
    python cli.py tts "你好，世界"          # 合成语音并直接播放（不落盘）
    python cli.py tts --file 回答.md --out reply.wav
    python cli.py models / balance
    python cli.py config show | set-key sk-xxx | set model deepseek-v4-pro
    python cli.py sessions list | show <id> | export <id> | rm <id>
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dskit import asr, audio, console, docs, player, tts  # noqa: E402
from dskit.client import DEFAULT_SYSTEM_PROMPT, DeepSeekClient  # noqa: E402
from dskit.config import AVAILABLE_MODELS, Config, data_dir  # noqa: E402
from dskit.errors import DSException  # noqa: E402
from dskit.search import extract_urls, fetch_url, search  # noqa: E402
from dskit.session import Session, SessionStore  # noqa: E402
from dskit.updater import check_update  # noqa: E402
from dskit.usage import Usage  # noqa: E402
from dskit.version import APP_VERSION, UPDATE_REPO, releases_page_url  # noqa: E402


# --------------------------------------------------------------------------- 输出
def banner() -> None:
    console.info("DeepSeek 桌面客户端 · 命令行阶段（阶段 1）")
    console.info("接口: https://api.deepseek.com  模型: deepseek-flash / deepseek-v4-pro")


def print_usage_line(usage: Usage, cfg: Config, model: str, elapsed: float | None = None) -> None:
    if not usage:
        console.info("未返回 usage 统计")
        return
    cost = usage.cost(model)
    line = usage.summary()
    if elapsed:
        line += f" | 耗时 {elapsed:.1f}s"
    console.info(line)
    console.info("预估费用 " + cost.format(cfg.cny_rate))


def render(stream, *, show_reasoning: bool = True, quiet_tools: bool = False) -> None:
    """把流式事件渲染到终端。思考内容用暗色，回答用正文。"""
    mode = ""
    try:
        for ev in stream:
            if ev.kind == "reasoning":
                if not show_reasoning:
                    continue
                if mode != "reason":
                    print()
                    print(console.paint("-- 思考过程 " + "-" * 40, "gray"))
                    mode = "reason"
                print(console.paint(ev.data, dim=True), end="", flush=True)
            elif ev.kind == "content":
                if mode != "answer":
                    print()
                    print(console.paint("-- 回答 " + "-" * 46, "cyan"))
                    mode = "answer"
                print(ev.data, end="", flush=True)
            elif ev.kind == "tool":
                if quiet_tools:
                    continue
                if mode:
                    print()
                print(console.paint("   [联网] " + ev.data.describe(), "yellow"))
                mode = ""
            elif ev.kind == "error":
                print()
                console.fail(str(ev.data))
    finally:
        if mode:
            print()
            print()


def print_citations(citations: list[dict]) -> None:
    if not citations:
        return
    console.hr()
    seen: list[str] = []
    idx = 0
    for cite in citations:
        url = cite.get("url") or ""
        if not url or url in seen:
            continue
        seen.append(url)
        idx += 1
        title = console.truncate(cite.get("title") or url, 60)
        print(console.paint(f"  [{idx}] ", "cyan") + title)
        print(console.paint(f"      {url}", "gray"))


# --------------------------------------------------------------------------- 上下文准备
def upload_files(client: DeepSeekClient, paths: list[str], *, rich: bool) -> list[str]:
    file_ids: list[str] = []
    for raw in paths:
        path = Path(raw)
        console.info(f"上传解析 {path.name}（{docs.human_size(path.stat().st_size) if path.exists() else '?'}）…")
        started = time.perf_counter()
        ref = docs.upload_document(client, path, rich_layout=rich)
        docs.attach_preview(ref, path)
        elapsed = time.perf_counter() - started
        note = f"{ref.chars} 字预览" if ref.chars else "服务端解析完成"
        console.ok(f"{path.name} -> {ref.file_id}（{elapsed:.1f}s，{note}）")
        file_ids.append(ref.file_id)
    return file_ids


def fetch_context(client: DeepSeekClient, urls: list[str], *, max_chars: int) -> str:
    blocks: list[str] = []
    for url in urls:
        console.info(f"抓取 {url} …")
        page = fetch_url(client, url, max_chars=max_chars)
        console.ok(f"{page.title or '(无标题)'} · {page.chars} 字{'（已截断）' if page.truncated else ''}")
        blocks.append(f"[网页] {page.title}\n来源：{page.url}\n\n{page.content}")
    return "\n\n---\n\n".join(blocks)


# --------------------------------------------------------------------------- 命令：chat
def cmd_chat(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    show_reason = cfg.show_reasoning and not args.hide_reasoning

    file_ids = upload_files(client, args.file or [], rich=args.rich_layout) if args.file else []
    urls = list(args.url or []) or extract_urls(args.prompt)
    context = fetch_context(client, urls, max_chars=args.max_context) if urls else ""

    session = Session(model=cfg.model)
    session.add_user(args.prompt, file_ids=file_ids, url_context=context)

    thinking = cfg.thinking if args.think is None else args.think
    web = cfg.web_search if args.search is None else args.search

    console.hr()
    started = time.perf_counter()
    stream = client.chat_stream(
        session.to_api_messages(DEFAULT_SYSTEM_PROMPT),
        model=cfg.model,
        thinking=thinking,
        web_search=web,
    )
    try:
        render(stream, show_reasoning=show_reason)
    except DSException as exc:
        console.fail(str(exc))
        return 1
    except KeyboardInterrupt:
        print()
        console.warn("已中断")
        return 130
    elapsed = time.perf_counter() - started

    session.add_assistant(stream.assistant_message(), citations=stream.citations)
    print_citations(stream.citations)
    console.hr()
    print_usage_line(stream.usage, cfg, cfg.model, elapsed)
    if stream.tool_calls:
        console.info(f"本次联网动作 {len(stream.tool_calls)} 次：" + "；".join(t.describe() for t in stream.tool_calls))

    if cfg.save_history and not args.no_save:
        store = SessionStore()
        store.save(session)
        console.info(f"对话已保存：{store.path_of(session.id)}")
        if args.export:
            md = store.export_markdown(session)
            out = Path(args.export)
            out.write_text(md, encoding="utf-8")
            console.ok(f"已导出 {out}")

    if stream.error:
        return 1
    return 0


# --------------------------------------------------------------------------- 命令：repl
REPL_HELP = """命令：
  /think on|off        切换深度思考
  /search on|off       切换联网搜索
  /file <路径>          挂载文件（下一轮生效，可多次）
  /url <链接>           抓取网页作为上下文（下一轮生效）
  /clear               清空当前会话上下文
  /cost                查看本会话累计用量
  /save [路径]          导出 Markdown
  /exit                退出（Ctrl+C 同）"""


def cmd_repl(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    store = SessionStore()
    session = Session(model=cfg.model)
    thinking = cfg.thinking and not args.no_think
    web = cfg.web_search and not args.no_search
    pending_files: list[str] = []
    pending_urls: list[str] = []
    total = Usage()

    console.title("交互模式")
    console.info(f"模型 {cfg.model} | 思考 {'开' if thinking else '关'} | 联网 {'开' if web else '关'}")
    console.info("输入 /help 看命令，Ctrl+C 退出")

    while True:
        try:
            raw = input(console.paint("\n你 > ", "cyan", bold=True)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue

        if raw.startswith("/"):
            head, _, tail = raw[1:].partition(" ")
            head = head.lower().strip()
            tail = tail.strip()
            if head in ("exit", "quit", "q"):
                break
            if head == "help":
                print(REPL_HELP)
                continue
            if head == "clear":
                session.clear()
                total = Usage()
                console.ok("上下文已清空")
                continue
            if head == "cost":
                console.info(total.summary() if total else "还没有用量")
                if total:
                    console.info("累计预估 " + total.cost(cfg.model).format(cfg.cny_rate))
                continue
            if head == "think":
                thinking = tail.lower() in ("on", "1", "true", "开")
                console.ok(f"思考模式 {'开' if thinking else '关'}")
                continue
            if head == "search":
                web = tail.lower() in ("on", "1", "true", "开")
                console.ok(f"联网搜索 {'开' if web else '关'}")
                continue
            if head == "file":
                if tail and Path(tail).exists():
                    pending_files.append(tail)
                    console.ok(f"已加入待上传：{tail}")
                else:
                    console.warn("文件不存在")
                continue
            if head == "url":
                if tail:
                    pending_urls.append(tail)
                    console.ok(f"已加入待抓取：{tail}")
                else:
                    console.warn("请给出完整链接")
                continue
            if head == "save":
                text = store.export_markdown(session)
                out = Path(tail or f"{session.id}.md")
                out.write_text(text, encoding="utf-8")
                console.ok(f"已导出 {out.resolve()}")
                continue
            console.warn("未知命令，输入 /help 查看")
            continue

        try:
            file_ids = upload_files(client, pending_files, rich=False) if pending_files else []
            context = fetch_context(client, pending_urls, max_chars=8000) if pending_urls else ""
            session.add_user(raw, file_ids=file_ids, url_context=context)
            pending_files.clear()
            pending_urls.clear()

            started = time.perf_counter()
            stream = client.chat_stream(
                session.to_api_messages(DEFAULT_SYSTEM_PROMPT),
                model=cfg.model,
                thinking=thinking,
                web_search=web,
            )
            render(stream, show_reasoning=cfg.show_reasoning and not args.hide_reasoning)
            elapsed = time.perf_counter() - started
            session.add_assistant(stream.assistant_message(), citations=stream.citations)
            if stream.usage:
                total = total.merge(stream.usage)
            print_citations(stream.citations)
            console.hr()
            print_usage_line(stream.usage, cfg, cfg.model, elapsed)
        except DSException as exc:
            console.fail(str(exc))
        except KeyboardInterrupt:
            print()
            console.warn("本轮已中断")

    if session.messages and cfg.save_history:
        store.save(session)
        console.info(f"会话已保存：{store.path_of(session.id)}")
    console.info("再见")
    return 0


# --------------------------------------------------------------------------- 命令：search / fetch / doc
def cmd_search(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    started = time.perf_counter()
    try:
        results = search(client, args.query, count=args.count, need_content=args.content)
    except DSException as exc:
        console.fail(str(exc))
        return 1
    elapsed = time.perf_counter() - started

    if not results:
        console.warn("没有结果（官方说明：空结果不计费）")
        return 0
    console.title(f"搜索结果 · {len(results)} 条 · {elapsed:.2f}s")
    for idx, item in enumerate(results, 1):
        print(console.paint(f"  [{idx}] ", "cyan") + item.display())
        print(console.paint(f"      {item.url}", "gray"))
        if item.snippet:
            print("      " + console.truncate(item.snippet, 120))
        if args.content and item.content:
            console.info(f"      正文 {len(item.content)} 字")
    console.hr()
    console.info(f"计费：搜索按次 $0.75/1000，本次 1 次 ≈ $0.00075")
    return 0


def cmd_fetch(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    started = time.perf_counter()
    try:
        page = fetch_url(client, args.url, max_chars=args.max_chars)
    except DSException as exc:
        console.fail(str(exc))
        return 1
    elapsed = time.perf_counter() - started
    console.title(f"网页抓取 · {elapsed:.2f}s")
    console.info(f"标题：{page.title or '(无)'}")
    console.info(f"字数：{page.chars}{'（已截断）' if page.truncated else ''}")
    console.hr()
    print(page.content[: args.preview] if args.preview > 0 else page.content)
    if args.preview > 0 and page.chars > args.preview:
        console.hr()
        console.info(f"…仅显示前 {args.preview} 字，用 --preview 0 查看全文")
    if args.save:
        Path(args.save).write_text(page.content, encoding="utf-8")
        console.ok(f"已保存 {args.save}")
    return 0


def cmd_doc(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    ref = docs.upload_document(client, args.path, rich_layout=args.rich_layout)
    docs.attach_preview(ref, args.path)
    console.title("文档解析完成")
    console.info(f"file_id ：{ref.file_id}")
    console.info(f"文件名  ：{ref.filename}（{docs.human_size(ref.size)}）")
    console.info(f"解析方式：{ref.purpose}")
    if ref.chars:
        console.info(f"本地预览：{ref.chars} 字")
        console.hr()
        print(console.truncate(ref.preview.replace("\n", " "), 300))
    console.hr()
    console.info("在对话里引用：" + f'{{"type": "file", "file_id": "{ref.file_id}"}}')
    console.info("计费：上传按页计费（仅解析成功时），之后每次对话按输入 token 计费")
    if args.delete:
        docs.delete_file(client, ref.file_id)
        console.ok("已在云端删除该文件")
    return 0


# --------------------------------------------------------------------------- 命令：tts
def _join_wav(parts: list[bytes]) -> bytes:
    """把多段 WAV 拼成一个（只拼数据块，保留第一个的头）。"""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        for idx, data in enumerate(parts):
            with wave.open(io.BytesIO(data), "rb") as src:
                if idx == 0:
                    out.setnchannels(src.getnchannels())
                    out.setsampwidth(src.getsampwidth())
                    out.setframerate(src.getframerate())
                out.writeframes(src.readframes(src.getnframes()))
    return buf.getvalue()


def cmd_tts(args: argparse.Namespace, cfg: Config) -> int:
    text = (args.text or "").strip()
    if args.file:
        path = Path(args.file)
        if not path.exists():
            console.fail(f"文件不存在：{path}")
            return 1
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        console.fail("请给出要朗读的文字，或用 --file 指定文本文件")
        return 1

    clean = tts.prepare_text(text)
    if not clean:
        console.fail("这段内容没有可朗读的文字（可能主要是代码或表格）")
        return 1

    chunks = tts.split_chunks(clean)
    console.title("语音合成")
    console.info(f"{len(clean)} 字 · {tts.billed_chars(clean)} 计费字符 · {len(chunks)} 段 · 音色 {tts.VOICES[args.voice]}")

    client = DeepSeekClient(cfg)
    parts: list[bytes] = []
    total_cost = 0.0
    started = time.perf_counter()
    for idx, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            console.info(f"  第 {idx}/{len(chunks)} 段（{tts.billed_chars(chunk)} 字符）…")
        try:
            result = tts.synthesize(client, chunk, voice_id=args.voice)
        except DSException as exc:
            console.fail(tts.describe_error(exc))
            return 1
        parts.append(result.audio)
        total_cost += result.cost()
    elapsed = time.perf_counter() - started

    joined = _join_wav(parts) if len(parts) > 1 else parts[0]
    try:
        seconds = player.wav_seconds(joined)
    except Exception:  # noqa: BLE001
        seconds = 0.0

    console.ok(f"合成完成：{seconds:.1f} 秒音频，耗时 {elapsed:.1f}s")
    console.info(f"费用约 ${total_cost:.6f} / ¥{total_cost * cfg.cny_rate:.5f}（每万字符 $0.45）")

    if args.out:
        Path(args.out).write_bytes(joined)
        console.ok(f"已保存 {args.out}（{docs.human_size(len(joined))}）")

    if args.no_play:
        return 0
    if not player.available():
        console.warn("当前平台不支持直接播放，已跳过（可用 --out 保存）")
        return 0
    console.info("开始播放…（Ctrl+C 停止）")
    wav_player = player.WavPlayer()
    try:
        wav_player.play(joined)
        wav_player.wait(seconds + 10)
    except player.PlaybackError as exc:
        console.fail(str(exc))
        return 1
    except KeyboardInterrupt:
        wav_player.stop()
        console.warn("已停止")
        return 130
    return 0


# --------------------------------------------------------------------------- 命令：asr
def cmd_asr(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)

    if args.record:
        if not audio.has_input_device():
            console.fail("没有检测到麦克风")
            return 1
        seconds = max(1, int(args.record))
        recorder = audio.WavRecorder(max_seconds=max(seconds + 5, 10))
        console.title(f"录音 {seconds} 秒")
        console.info("现在开始说话…")
        try:
            recorder.start()
        except audio.RecordError as exc:
            console.fail(str(exc))
            return 1
        started = time.perf_counter()
        try:
            while time.perf_counter() - started < seconds:
                left = seconds - (time.perf_counter() - started)
                print(f"\r  还剩 {left:4.1f}s ", end="", flush=True)
                time.sleep(0.1)
            print("\r  录音结束      ")
        except KeyboardInterrupt:
            print()
            recorder.cancel()
            console.warn("已取消")
            return 130
        recording = recorder.stop()
    else:
        if not args.path:
            console.fail("请给出 WAV 路径，或用 --record N 现场录音")
            return 1
        path = Path(args.path)
        if not path.exists():
            console.fail(f"文件不存在：{path}")
            return 1
        data = path.read_bytes()
        try:
            info = audio.wav_info(data)
        except Exception as exc:  # noqa: BLE001
            console.fail(f"不是合法的 WAV：{exc}")
            return 1
        console.title("音频信息")
        console.info(f"{info['rate']}Hz · {info['channels']} 声道 · {info['seconds']:.1f}s · {docs.human_size(len(data))}")
        recording = audio.Recording(wav=data, seconds=info["seconds"], rate=info["rate"], channels=info["channels"])

    if recording.seconds < 0.5:
        console.fail("录音太短")
        return 1

    console.info(f"上传识别（{docs.human_size(recording.size)}，{recording.seconds:.1f}s）…")
    started = time.perf_counter()
    try:
        result = asr.transcribe(client, recording.wav)
    except DSException as exc:
        console.fail(asr.describe_error(exc))
        return 1
    elapsed = time.perf_counter() - started

    console.title(f"识别结果 · {elapsed:.1f}s")
    print(result.text or "（没有识别出内容）")
    console.hr()
    console.info(f"音频时长 {result.seconds:.1f}s · {len(result.text)} 字 · request_id {result.request_id or '-'}")
    console.info(f"本次费用 {result.format_cost(cfg.cny_rate)}（$0.116/小时，按音频时长计费）")
    if args.save:
        Path(args.save).write_text(result.text, encoding="utf-8")
        console.ok(f"已保存 {args.save}")
    return 0


# --------------------------------------------------------------------------- 命令：update
def cmd_update(args: argparse.Namespace, cfg: Config) -> int:
    """检查 GitHub 上的新版本（走 GitHub API，不消耗 DeepSeek API 额度）。"""
    repo = cfg.update_repo or UPDATE_REPO
    console.title("软件更新")
    console.info(f"当前版本：{APP_VERSION}")
    console.info(f"更新源：{repo}")
    info = check_update(
        repo=cfg.update_repo, current=APP_VERSION,
        timeout=min(15, max(5, cfg.timeout)), proxies=cfg.proxies(),
    )
    if not info.ok:
        console.warn(info.message)
        console.info(f"发布页：{releases_page_url(repo)}")
        return 0 if "未找到正式版" in info.message else 1
    console.info(f"最新版本：{info.latest}  发布：{info.published_at[:10]}")
    if info.has_update:
        console.ok(info.message)
        if info.notes:
            print("\n" + info.notes[:2000])
        console.info(f"下载：{info.download_url or info.html_url}")
    else:
        console.ok(info.message)
    return 0


# --------------------------------------------------------------------------- 命令：models / balance / config / sessions
def cmd_models(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    try:
        ids = client.models()
    except DSException as exc:
        console.fail(str(exc))
        return 1
    console.title("可用模型")
    for mid in ids:
        mark = "  <- 当前" if mid == cfg.model else ""
        print(f"  - {mid}{console.paint(mark, 'green')}")
    console.info("deepseek-flash 支持思考/非思考双模式、联网、文件；deepseek-v4-pro 推理更强、更贵")
    return 0


def cmd_balance(args: argparse.Namespace, cfg: Config) -> int:
    client = DeepSeekClient(cfg)
    try:
        info = client.balance()
    except DSException as exc:
        console.fail(str(exc))
        return 1
    console.title("账户余额")
    console.info(f"可用：{'是' if info.get('available') else '否'}  总额：{info.get('total')} {info.get('currency')}")
    console.info(f"赠送：{info.get('granted')}  充值：{info.get('topped_up')}")
    if info.get("total") == 0:
        console.warn("余额为 0，调用会返回 402")
    return 0


def cmd_config(args: argparse.Namespace, cfg: Config) -> int:
    action = args.action
    if action == "show":
        console.title("当前配置")
        data = cfg.to_dict(mask_key=True)
        for key, value in data.items():
            print(f"  {console.pad(key, 20)}{value}")
        console.hr()
        console.info(f"配置文件：{Config.path()}")
        console.info(f"历史目录：{data_dir() / 'sessions'}")
        console.info("API Key 也可以用环境变量 DEEPSEEK_API_KEY 提供（优先级更高）")
        return 0

    if action == "set-key":
        key = (args.value or "").strip()
        if not key:
            console.fail("请提供 Key，例如：python cli.py config set-key sk-xxxx")
            return 1
        if not key.startswith("sk-"):
            console.warn("DeepSeek 的 Key 一般以 sk- 开头，确认没粘错")
        cfg.api_key = key
        cfg.normalize()
        path = cfg.save()
        console.ok(f"已保存到 {path}（{cfg.masked_key()}）")
        return 0

    if action == "set":
        if not args.key or args.value is None:
            console.fail("用法：config set <字段> <值>，例如 config set model deepseek-v4-pro")
            return 1
        field_name = args.key
        if not hasattr(cfg, field_name):
            console.fail(f"未知字段 {field_name}")
            return 1
        current = getattr(cfg, field_name)
        value: object = args.value
        if isinstance(current, bool):
            value = str(args.value).lower() in ("1", "true", "on", "yes", "开")
        elif isinstance(current, int):
            value = int(args.value)
        elif isinstance(current, float):
            value = float(args.value)
        setattr(cfg, field_name, value)
        cfg.normalize()
        cfg.save()
        console.ok(f"{field_name} = {getattr(cfg, field_name)}")
        return 0

    if action == "unset-key":
        cfg.api_key = ""
        cfg.save()
        console.ok("已清空本地 API Key")
        return 0

    console.fail("未知操作")
    return 1


def cmd_sessions(args: argparse.Namespace, cfg: Config) -> int:
    store = SessionStore()
    if args.action == "list":
        items = store.list()
        if not items:
            console.info("还没有本地会话")
            return 0
        console.title("本地会话")
        rows = []
        for item in items:
            when = datetime.fromtimestamp(item["updated_at"]).strftime("%m-%d %H:%M")
            rows.append([item["id"], when, str(item["turns"]), console.truncate(item["title"], 34)])
        console.table(["ID", "更新时间", "条数", "标题"], rows)
        return 0
    if args.action in ("show", "export", "rm"):
        if not args.id:
            console.fail("请给出会话 ID")
            return 1
        try:
            session = store.load(args.id)
        except (OSError, ValueError) as exc:
            console.fail(f"读取失败：{exc}")
            return 1
        if args.action == "show":
            print(store.export_markdown(session))
            return 0
        if args.action == "export":
            out = Path(args.out or f"{session.id}.md")
            out.write_text(store.export_markdown(session), encoding="utf-8")
            console.ok(f"已导出 {out.resolve()}")
            return 0
        store.delete(args.id)
        console.ok("已删除")
        return 0
    console.fail("未知操作")
    return 1


# --------------------------------------------------------------------------- 命令：verify
class Check:
    def __init__(self, name: str, fn) -> None:
        self.name = name
        self.fn = fn


def cmd_verify(args: argparse.Namespace, cfg: Config) -> int:
    """逐项验证四项核心接口 + 流式 + 异常捕获。每项独立跑，互不阻塞。"""
    if not cfg.has_key and not args.key:
        console.fail("未找到 API Key")
        console.info("任选一种方式配置：")
        console.bullet("python cli.py config set-key sk-xxxx")
        console.bullet("set DEEPSEEK_API_KEY=sk-xxxx  （Windows cmd）")
        console.bullet("$env:DEEPSEEK_API_KEY='sk-xxxx'  （PowerShell）")
        return 2

    if args.key:
        cfg.api_key = args.key.strip()

    client = DeepSeekClient(cfg)
    results: list[tuple[str, bool, str, float]] = []
    total_usage = Usage()
    run_model = cfg.model if not args.model else args.model

    def run(name: str, fn) -> None:
        print()
        print(console.paint(f">> {name}", "bold"))
        started = time.perf_counter()
        try:
            detail = fn() or ""
            ok = True
        except DSException as exc:
            detail = str(exc)
            ok = False
        except Exception as exc:  # 自检脚本要能兜住任何异常并继续
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
        elapsed = time.perf_counter() - started
        if ok:
            console.ok(f"{detail}  ({elapsed:.2f}s)")
        else:
            console.fail(f"{detail}  ({elapsed:.2f}s)")
        results.append((name, ok, detail, elapsed))

    # 1. Key / 模型列表
    def check_models() -> str:
        ids = client.models()
        if not ids:
            raise DSException("模型列表为空")
        missing = [m for m in (run_model,) if m not in ids]
        if missing:
            raise DSException(f"模型列表里没有 {missing}（返回：{ids}）")
        return "可用模型 " + ", ".join(ids)

    # 2. 流式对话
    def check_stream() -> str:
        stream = client.chat_stream(
            [{"role": "user", "content": "用一句不超过20字的话介绍你自己。"}],
            thinking=False,
            web_search=False,
            read_url=False,
        )
        chunks = 0
        for ev in stream:
            if ev.kind == "content":
                chunks += 1
            if ev.kind == "error":
                raise ev.data
        if not stream.text.strip():
            raise DSException("没有收到正文")
        total_usage.merge(stream.usage)
        first = f"首字 {stream.first_token_ms}ms, " if stream.first_token_ms else ""
        return f"{first}分片 {chunks} 个, {console.truncate(stream.text.strip(), 40)}"

    # 3. 思考模式
    def check_thinking() -> str:
        stream = client.chat_stream(
            [{"role": "user", "content": "9.11 和 9.8 哪个更大？只回答结论。"}],
            thinking=True,
            reasoning_effort="low",
            web_search=False,
            read_url=False,
        )
        for ev in stream:
            if ev.kind == "error":
                raise ev.data
        if not stream.reasoning.strip():
            raise DSException("没有收到 reasoning_content，思考模式可能未生效")
        total_usage.merge(stream.usage)
        return f"思考 {len(stream.reasoning)} 字, 输出 {len(stream.text)} 字, 结论含 9.11={'9.11' in stream.text}"

    # 4. Search API
    def check_search() -> str:
        results = search(client, "DeepSeek V4.1 Flash 发布", count=5)
        if not results:
            raise DSException("搜索无结果")
        return f"{len(results)} 条, 首条: {console.truncate(results[0].title, 34)}"

    # 5. Fetch API
    def check_fetch() -> str:
        page = fetch_url(client, "https://example.com")
        if not page.content.strip():
            raise DSException("抓取内容为空")
        return f"{page.title or '(无标题)'} · {page.chars} 字"

    # 6. 文件解析 + 7. 带文件对话
    sample = Path(tempfile_dir()) / "dskit_sample.pdf"
    state: dict[str, str] = {}

    def check_upload() -> str:
        docs.make_minimal_pdf(sample, ["DEEPSEEK DESKTOP PARSER TEST", "keyword: BLUEWHALE-2026", "version: 1.0"])
        ref = docs.upload_document(client, sample)
        if not ref.file_id:
            raise DSException("没有返回 file_id")
        state["file_id"] = ref.file_id
        return f"file_id={ref.file_id}（{sample.stat().st_size} 字节样本 PDF）"

    def check_file_chat() -> str:
        fid = state.get("file_id")
        if not fid:
            raise DSException("上一步未拿到 file_id，跳过")
        stream = client.chat_stream(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "这份文档里的 keyword 是什么？只回答关键词本身。"},
                        {"type": "file", "file_id": fid},
                    ],
                }
            ],
            thinking=False,
            web_search=False,
            read_url=False,
        )
        for ev in stream:
            if ev.kind == "error":
                raise ev.data
        total_usage.merge(stream.usage)
        hit = "BLUEWHALE" in stream.text.upper()
        if not hit:
            raise DSException(f"未能读出关键词，模型回答：{console.truncate(stream.text, 60)}")
        return f"模型正确读出关键词（回答 {len(stream.text)} 字）"

    # 8. 模型自主联网
    def check_web_tools() -> str:
        stream = client.chat_stream(
            [{"role": "user", "content": "DeepSeek 目前最新的模型叫什么？请联网确认后用一句话回答。"}],
            thinking=False,
            web_search=True,
            read_url=True,
        )
        for ev in stream:
            if ev.kind == "error":
                raise ev.data
        total_usage.merge(stream.usage)
        if not stream.tool_calls and not stream.citations:
            raise DSException("模型没有触发联网（可能判断无需搜索）；可重试")
        kinds = ",".join(sorted({t.kind for t in stream.tool_calls if t.kind})) or "仅引用"
        return f"联网动作 {len(stream.tool_calls)} 次({kinds}), 引用 {len(stream.citations)} 条, 计费搜索 {stream.usage.tool_search} 次"

    # 9. 异常捕获
    def check_error() -> str:
        bad = Config.from_dict({**cfg.to_dict(), "api_key": "sk-invalid-000000000000000000000000"})
        bad_client = DeepSeekClient(bad)
        try:
            list(bad_client.chat_stream([{"role": "user", "content": "hi"}], web_search=False, read_url=False))
        except DSException as exc:
            if exc.status != 401:
                raise DSException(f"期望 401，实际 {exc.status}：{exc}")
            return f"正确捕获：{exc.message}"
        raise DSException("错误 Key 居然没报错")

    console.title("全链路自检")
    console.info(f"模型 {run_model} | base_url {cfg.base_url} | 代理 {cfg.proxy or '未设置'}")
    console.info("说明：9 项检查都会真实消耗少量额度（合计约 $0.001），Search/Fetch 各 1 次")

    run("1. API Key 与模型列表", check_models)
    run("2. 流式对话（非思考）", check_stream)
    run("3. 深度思考（reasoning_content）", check_thinking)
    run("4. 联网搜索 Search API", check_search)
    run("5. 网页抓取 Fetch API", check_fetch)
    run("6. 文件解析 Files API", check_upload)
    run("7. 带文件对话（file_id 引用）", check_file_chat)
    run("8. 模型自主联网（web tools）", check_web_tools)
    run("9. 异常捕获（错误 Key → 401）", check_error)

    console.title("汇总")
    rows = []
    for name, ok, detail, elapsed in results:
        rows.append(["PASS" if ok else "FAIL", name, f"{elapsed:.2f}s", console.truncate(detail.replace("\n", " "), 52)])
    console.table(["结果", "检查项", "耗时", "详情"], rows)

    passed = sum(1 for r in results if r[1])
    console.info(f"通过 {passed}/{len(results)}")
    if total_usage:
        cost = total_usage.cost(run_model)
        console.info("本次自检用量：" + total_usage.summary())
        console.info("本次自检费用：" + cost.format(cfg.cny_rate))

    if sample.exists():
        try:
            sample.unlink()
        except OSError:
            pass

    if passed == len(results):
        console.ok("阶段 1 全部接口验证通过，可以进入 GUI 开发")
        return 0
    console.warn("存在未通过项，请把上面的 FAIL 详情发我")
    return 1


def tempfile_dir() -> Path:
    return Path(tempfile.gettempdir())


# --------------------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="DeepSeek 桌面客户端 · 阶段 1 命令行 demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--key", help="临时指定 API Key（不写入配置文件）")
    parser.add_argument("--model", choices=AVAILABLE_MODELS, help="覆盖模型")
    parser.add_argument("--proxy", help="代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--no-color", action="store_true", help="关闭彩色输出")

    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("verify", help="全链路自检（建议第一步）")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("chat", help="单轮问答（流式）")
    p.add_argument("prompt", help="问题")
    p.add_argument("-f", "--file", action="append", help="附带文件，可多次")
    p.add_argument("--rich-layout", action="store_true", help="文件按图表版式解析（更多 token，更贵）")
    p.add_argument("-u", "--url", action="append", help="附带网页链接，可多次")
    p.add_argument("--think", dest="think", action="store_true", help="开启深度思考")
    p.add_argument("--no-think", dest="think", action="store_false", help="关闭深度思考")
    p.add_argument("--search", dest="search", action="store_true", help="开启联网搜索")
    p.add_argument("--no-search", dest="search", action="store_false", help="关闭联网搜索")
    p.add_argument("--hide-reasoning", action="store_true", help="不显示思考过程")
    p.add_argument("--max-context", type=int, default=12000, help="网页上下文最多字符数")
    p.add_argument("--no-save", action="store_true", help="不保存本次对话")
    p.add_argument("--export", help="同时导出 Markdown 到指定路径")
    p.set_defaults(think=None, search=None, func=cmd_chat)

    p = sub.add_parser("repl", help="交互式多轮对话")
    p.add_argument("--no-think", action="store_true")
    p.add_argument("--no-search", action="store_true")
    p.add_argument("--hide-reasoning", action="store_true")
    p.set_defaults(think=None, search=None, func=cmd_repl)

    p = sub.add_parser("search", help="只调搜索接口看结果")
    p.add_argument("query")
    p.add_argument("--count", type=int, default=8)
    p.add_argument("--content", action="store_true", help="同时取回网页正文（更慢更大）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("fetch", help="只调抓取接口读网页")
    p.add_argument("url")
    p.add_argument("--max-chars", type=int, default=20000)
    p.add_argument("--preview", type=int, default=1200, help="终端显示多少字，0 表示全部")
    p.add_argument("--save", help="正文另存为文件")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("tts", help="语音合成（直接播放或另存 WAV）")
    p.add_argument("text", nargs="?", help="要朗读的文字")
    p.add_argument("--file", help="从文本文件读取内容")
    p.add_argument("--voice", default="stella", choices=list(tts.VOICES), help="音色（默认 stella）")
    p.add_argument("--out", help="另存为 WAV 文件")
    p.add_argument("--no-play", action="store_true", help="只合成，不播放")
    p.set_defaults(func=cmd_tts)

    p = sub.add_parser("asr", help="语音识别（现场录音或指定 WAV）")
    p.add_argument("path", nargs="?", help="已有的 16bit WAV 文件")
    p.add_argument("--record", type=int, metavar="秒", help="现场录 N 秒再识别")
    p.add_argument("--save", help="把识别文本存到文件")
    p.set_defaults(func=cmd_asr)

    p = sub.add_parser("doc", help="只上传解析文件，拿 file_id")
    p.add_argument("path")
    p.add_argument("--rich-layout", action="store_true")
    p.add_argument("--delete", action="store_true", help="解析后立即在云端删除")
    p.set_defaults(func=cmd_doc)

    p = sub.add_parser("update", help="检查 GitHub 上的新版本（不消耗 API 额度）")
    p.set_defaults(func=cmd_update)

    sub.add_parser("models", help="列出可用模型").set_defaults(func=cmd_models)
    sub.add_parser("balance", help="查看余额").set_defaults(func=cmd_balance)

    p = sub.add_parser("config", help="查看/修改配置")
    p.add_argument("action", choices=["show", "set-key", "unset-key", "set"])
    p.add_argument("key", nargs="?", help="set 时的字段名")
    p.add_argument("value", nargs="?", help="set 时的值")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("sessions", help="本地历史管理")
    p.add_argument("action", choices=["list", "show", "export", "rm"])
    p.add_argument("id", nargs="?")
    p.add_argument("--out", help="export 的输出路径")
    p.set_defaults(func=cmd_sessions)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console.init(no_color=getattr(args, "no_color", False))

    if not args.cmd:
        parser.print_help()
        print()
        banner()
        return 0

    cfg = Config.load()
    if getattr(args, "key", None):
        cfg.api_key = args.key.strip()   # 全局 --key 覆盖，方便临时换 Key 调试
    if args.model:
        cfg.model = args.model
    if args.proxy:
        cfg.proxy = args.proxy
    cfg.normalize()

    try:
        return args.func(args, cfg)
    except DSException as exc:
        console.fail(str(exc))
        if exc.detail:
            console.info(str(exc.detail)[:300])
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
