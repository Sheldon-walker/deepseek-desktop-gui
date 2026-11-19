"""token 用量与费用估算。

价格来源：DeepSeek 官方 Models & Pricing（2026-11 核对）。
单位：美元 / 100 万 tokens。

计费规则要点
------------
1. deepseek-flash / deepseek-v4-pro 的输入分「缓存命中」与「未命中」两档价格，
   命中缓存便宜 50 倍左右，多轮对话重复前缀会自动命中。
2. 高峰时段价格为闲时的 2 倍：UTC 01:00-04:00 与 06:00-10:00（周一至周五）。
   换算成北京时间是 09:00-12:00 和 14:00-18:00。
3. Search / Fetch 不按 token 计费，按「成功请求次数」计费：$0.75 / 1000 次。
4. 思考模式的 reasoning token 计入输出，同样收费。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# (闲时, 高峰) 单价，美元 / 1M tokens
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "deepseek-flash": {
        "cache_hit": (0.003, 0.006),
        "cache_miss": (0.15, 0.30),
        "output": (0.60, 1.20),
    },
    "deepseek-v4-pro": {
        "cache_hit": (0.022, 0.044),
        "cache_miss": (0.66, 1.32),
        "output": (1.98, 3.96),
    },
}

# 按次计费（美元 / 次）
SEARCH_PER_REQUEST = 0.75 / 1000
FETCH_PER_REQUEST = 0.75 / 1000
ASR_PER_SECOND = 0.116 / 3600           # 语音识别，$0.116/小时
TTS_PER_1K_CHARS = None                 # 见官方 tts 页面，阶段 4 再接入

# 文档解析按页计费，单价见官方 Models & Pricing 的 OCR 段落
OCR_PAGE_PRICE = None

PEAK_WINDOWS_UTC = ((1, 4), (6, 10))    # UTC 01:00-04:00, 06:00-10:00


def is_peak(moment: datetime | None = None) -> bool:
    """判断某一时刻是否处于高峰计费时段（周一至周五）。"""
    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    if now.weekday() >= 5:              # 5=周六 6=周日
        return False
    for start, end in PEAK_WINDOWS_UTC:
        if start <= now.hour < end:
            return True
    return False


def beijing_time(moment: datetime | None = None) -> str:
    now = moment or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    tool_search: int = 0            # 实际计费的联网搜索次数
    tool_fetch: int = 0             # 实际计费的网页抓取次数
    tool_image_search: int = 0

    @classmethod
    def from_api(cls, raw: dict) -> "Usage":
        raw = raw or {}
        details = raw.get("prompt_tokens_details") or {}
        completion_details = raw.get("completion_tokens_details") or {}
        tool_use = raw.get("server_tool_use") or {}
        hit = int(raw.get("prompt_cache_hit_tokens") or details.get("cached_tokens") or 0)
        miss = int(raw.get("prompt_cache_miss_tokens") or 0)
        prompt = int(raw.get("prompt_tokens") or 0)
        if not miss and prompt:
            miss = max(0, prompt - hit)
        return cls(
            prompt_tokens=prompt,
            completion_tokens=int(raw.get("completion_tokens") or 0),
            total_tokens=int(raw.get("total_tokens") or 0),
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
            tool_search=int(tool_use.get("tool_search") or 0),
            tool_fetch=int(tool_use.get("tool_fetch") or 0),
            tool_image_search=int(tool_use.get("tool_image_search") or 0),
        )

    def __bool__(self) -> bool:  # noqa: D105
        return bool(self.total_tokens or self.tool_search or self.tool_fetch)

    def merge(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_hit_tokens=self.cache_hit_tokens + other.cache_hit_tokens,
            cache_miss_tokens=self.cache_miss_tokens + other.cache_miss_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            tool_search=self.tool_search + other.tool_search,
            tool_fetch=self.tool_fetch + other.tool_fetch,
            tool_image_search=self.tool_image_search + other.tool_image_search,
        )

    # ---------- 费用 ----------
    def cost(self, model: str, *, at: datetime | None = None) -> "Cost":
        prices = PRICING.get(model) or PRICING["deepseek-flash"]
        idx = 1 if is_peak(at) else 0
        token_cost = (
            self.cache_hit_tokens * prices["cache_hit"][idx]
            + self.cache_miss_tokens * prices["cache_miss"][idx]
            + self.completion_tokens * prices["output"][idx]
        ) / 1_000_000
        tool_cost = (self.tool_search + self.tool_image_search) * SEARCH_PER_REQUEST + self.tool_fetch * FETCH_PER_REQUEST
        return Cost(
            token_usd=token_cost,
            tool_usd=tool_cost,
            peak=bool(idx),
            model=model,
            usage=self,
        )

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "tool_search": self.tool_search,
            "tool_fetch": self.tool_fetch,
            "tool_image_search": self.tool_image_search,
        }

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Usage":
        raw = raw or {}
        return cls(
            prompt_tokens=int(raw.get("prompt_tokens") or 0),
            completion_tokens=int(raw.get("completion_tokens") or 0),
            total_tokens=int(raw.get("total_tokens") or 0),
            cache_hit_tokens=int(raw.get("cache_hit_tokens") or 0),
            cache_miss_tokens=int(raw.get("cache_miss_tokens") or 0),
            reasoning_tokens=int(raw.get("reasoning_tokens") or 0),
            tool_search=int(raw.get("tool_search") or 0),
            tool_fetch=int(raw.get("tool_fetch") or 0),
            tool_image_search=int(raw.get("tool_image_search") or 0),
        )

    def summary(self) -> str:
        parts = [f"输入 {self.prompt_tokens}（缓存命中 {self.cache_hit_tokens}）"]
        out = f"输出 {self.completion_tokens}"
        if self.reasoning_tokens:
            out += f"（其中思考 {self.reasoning_tokens}）"
        parts.append(out)
        parts.append(f"合计 {self.total_tokens or (self.prompt_tokens + self.completion_tokens)} tokens")
        if self.tool_search or self.tool_fetch:
            parts.append(f"联网：搜索 {self.tool_search} 次 / 抓取 {self.tool_fetch} 次")
        return " | ".join(parts)


@dataclass
class Cost:
    token_usd: float = 0.0
    tool_usd: float = 0.0
    peak: bool = False
    model: str = "deepseek-flash"
    usage: Usage | None = None

    @property
    def usd(self) -> float:
        return self.token_usd + self.tool_usd

    def cny(self, rate: float = 7.10) -> float:
        return self.usd * rate

    def format(self, rate: float = 7.10) -> str:
        tag = "高峰价" if self.peak else "闲时价"
        return f"${self.usd:.6f} / ¥{self.cny(rate):.5f}（{tag}，{self.model}）"
