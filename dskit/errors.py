"""统一异常类型与错误映射。

设计目标：上层（CLI / GUI）只需要捕获 DSException，就能拿到可直接展示给用户的中文提示。
所有 HTTP 状态码、网络异常、流式中途失败都在这里归一化。
"""

from __future__ import annotations

import json
from typing import Any

import requests

# HTTP 状态码 -> (简短说明, 处理建议)
_STATUS_MAP: dict[int, tuple[str, str]] = {
    400: ("请求参数错误", "检查模型名、消息格式或文件类型；文件解析失败也会返回 400"),
    401: ("API Key 无效或未填写", "到 platform.deepseek.com 重新生成 sk- 开头的 Key"),
    402: ("账户余额不足", "到 platform.deepseek.com 充值后重试"),
    403: ("请求被安全策略拒绝", "该链接或内容不允许抓取，可换一个来源"),
    404: ("请求的资源不存在", "网页抓不到（站点拒绝/无正文），或模型名写错"),
    408: ("请求超时", "网络较慢或文件过大；正式版上传接口限制 120 秒"),
    413: ("上传内容过大", "PDF/Word 最大 100MB，纯文本/表格/电子书最大 32MB"),
    422: ("请求无法处理", "参数组合不合法"),
    429: ("触发频率限制", "搜索 100 QPS / 抓取 25 QPS；稍后会自动重试"),
    500: ("服务端内部错误", "稍后重试"),
    502: ("网关错误", "稍后重试"),
    503: ("服务繁忙", "稍后重试"),
    504: ("下游服务超时", "稍后重试"),
}

_RETRYABLE = {429, 500, 502, 503, 504}


class DSException(Exception):
    """所有 DeepSeek 接口相关异常的统一类型。"""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        hint: str | None = None,
        retryable: bool = False,
        detail: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.hint = hint
        self.retryable = retryable
        self.detail = detail
        self.raw = raw

    def __str__(self) -> str:  # noqa: D105
        text = self.message
        if self.status:
            text = f"[{self.status}] {text}"
        if self.hint:
            text = f"{text} -> {self.hint}"
        return text

    def as_dict(self) -> dict[str, Any]:
        """便于 GUI 层结构化展示。"""
        return {
            "message": self.message,
            "status": self.status,
            "code": self.code,
            "hint": self.hint,
            "retryable": self.retryable,
            "detail": self.detail,
        }


def missing_key() -> DSException:
    return DSException(
        "未配置 API Key",
        code="missing_api_key",
        hint="运行 `python cli.py config set-key sk-xxx`，或设置环境变量 DEEPSEEK_API_KEY",
    )


def _extract_api_message(text: str) -> str:
    """尽量从错误响应体里取出官方原始 message。"""
    if not text:
        return ""
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text.strip()[:300]
    err = obj.get("error") if isinstance(obj, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or "").strip()[:300]
    if isinstance(err, str):
        return err.strip()[:300]
    return ""


def from_http(status: int, body: str = "") -> DSException:
    """把 HTTP 错误响应转成 DSException。"""
    label, hint = _STATUS_MAP.get(status, (f"接口返回异常状态 {status}", "查看 detail 里的原始返回"))
    api_msg = _extract_api_message(body)
    message = label
    if api_msg and api_msg != label:
        message = f"{label}：{api_msg}"
    return DSException(
        message,
        status=status,
        code=f"http_{status}",
        hint=hint,
        retryable=status in _RETRYABLE,
        detail=(body or "")[:800],
    )


def from_payload(obj: Any) -> DSException:
    """把流式响应中夹带的 error 对象转成 DSException。"""
    err = {}
    if isinstance(obj, dict):
        err = obj.get("error") or {}
    if not isinstance(err, dict):
        err = {"message": str(err)}
    message = str(err.get("message") or "生成过程中断").strip()
    code = str(err.get("code") or "stream_error")
    return DSException(
        f"生成中断：{message}",
        code=code,
        hint="可重试；若反复出现请检查输入是否触发内容安全策略",
        retryable=False,
        detail=json.dumps(obj, ensure_ascii=False)[:800],
        raw=obj,
    )


def from_network(exc: Exception) -> DSException:
    """把 requests 的网络层异常转成可读提示。"""
    if isinstance(exc, requests.exceptions.ProxyError):
        return DSException(
            "代理连接失败",
            code="proxy_error",
            hint="检查设置里的代理地址格式，例如 http://127.0.0.1:7890",
            detail=str(exc),
        )
    if isinstance(exc, requests.exceptions.SSLError):
        return DSException("HTTPS 证书校验失败", code="ssl_error", hint="检查系统时间或代理软件的证书", detail=str(exc))
    if isinstance(exc, requests.exceptions.Timeout):
        return DSException("网络超时", code="timeout", hint="检查网络/代理，或调大 timeout", retryable=True, detail=str(exc))
    if isinstance(exc, requests.exceptions.ConnectionError):
        return DSException(
            "无法连接到 DeepSeek 服务器",
            code="connection_error",
            hint="检查网络、DNS 或代理设置",
            retryable=True,
            detail=str(exc),
        )
    return DSException("请求失败", code="request_error", hint=None, detail=str(exc))
