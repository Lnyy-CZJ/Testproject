from __future__ import annotations

from typing import Any


SENSITIVE_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "cookie",
    "private_key",
)


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否属于禁止记录明文的敏感类型。"""

    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in SENSITIVE_MARKERS)


def redact(value: Any) -> Any:
    """
    递归脱敏字典和列表中的敏感字段。

    参数说明:
        value: 待写入日志或审计的结构化值。
    返回值:
        Any: 结构保持不变、敏感值替换为固定占位符的副本。
    """

    if isinstance(value, dict):
        return {
            str(key): "***" if is_sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value
