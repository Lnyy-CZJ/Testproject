"""日志、错误与路径的二次脱敏。"""

from __future__ import annotations

import re
from typing import Any


_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|cookie|password|passwd|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(mysql\+?\w*://[^:\s]+:)[^@\s]+(@)"),
]
_PATH = re.compile(r"/(?:Users|home|app)/[^\s:'\"]+")
_TRACEBACK = re.compile(r"Traceback \(most recent call last\):.*?(?=\n\S|\Z)", re.DOTALL)


def redact_text(value: str) -> str:
    """隐藏凭证、内部绝对路径和完整 Python 堆栈。"""

    text = value or ""
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1[REDACTED]\2" if pattern is _PATTERNS[2] else r"\1[REDACTED]", text)
    text = _PATH.sub("[INTERNAL_PATH]", text)
    return _TRACEBACK.sub("[详细堆栈已隐藏]", text)


_SENSITIVE_KEYS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie", "api-key", "apikey",
    "api_key", "token", "access_token", "refresh_token", "password", "passwd", "secret",
})


def redact_structure(value: Any, *, key: str = "") -> Any:
    """递归脱敏 Header、Query、JSON/Form、日志和报告结构。

    参数说明:
        value: 任意 JSON 可序列化值。
        key: 递归时当前字段名；调用方通常无需传入。
    返回值:
        保持原结构的新对象；敏感字段值替换为固定占位符。
    """

    normalized = key.lower().replace("_", "-")
    # Header 名称经常使用 ``X-Access-Token``、``X-Client-Secret`` 等前缀，
    # 只匹配固定键会把这类值写入阶段结果。后缀判断仍然限定在凭证语义，
    # 不会把普通业务字段（如 token_count）误判为 Secret。
    sensitive_names = {item.replace("_", "-") for item in _SENSITIVE_KEYS}
    sensitive_suffix = normalized.endswith(("-token", "-secret", "-password", "-api-key"))
    if normalized in sensitive_names or sensitive_suffix:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact_structure(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_structure(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [redact_structure(item, key=key) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
