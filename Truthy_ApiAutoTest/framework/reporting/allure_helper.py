"""可选 Allure 安全附件封装。"""

from __future__ import annotations

import json
from typing import Any

from framework.security.redactor import Redactor

try:
    import allure as _allure
except ImportError:  # Allure 是可选报告依赖，缺失时不得阻断测试收集。
    _allure = None


MAX_ATTACHMENT_BYTES = 1024 * 1024


def _bounded_json(payload: Any, max_bytes: int) -> str:
    """序列化 JSON，并在超限时生成仍为合法 JSON 的预览包装。"""
    body = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
    encoded = body.encode("utf-8")
    if len(encoded) <= max_bytes:
        return body

    preview_size = max(0, max_bytes - 100)
    while preview_size >= 0:
        preview = encoded[:preview_size].decode("utf-8", errors="ignore")
        bounded = json.dumps(
            {"truncated": True, "original_bytes": len(encoded), "preview": preview},
            ensure_ascii=False,
            sort_keys=True,
        )
        if len(bounded.encode("utf-8")) <= max_bytes:
            return bounded
        preview_size -= 16
    raise ValueError("max_bytes 太小，无法容纳截断附件元数据")


def attach_safe_json(
    name: str,
    payload: Any,
    *,
    redactor: Redactor | None = None,
    max_bytes: int = 1024 * 1024,
) -> bool:
    """向 Allure 附加递归脱敏且不超过大小限制的 JSON。

    功能说明:
        递归脱敏诊断对象，限制为 1 MiB 内的合法 JSON 后附加到 Allure。
    参数说明:
        name: 附件展示名称。
        payload: 待脱敏的请求、响应或诊断对象。
        redactor: 可选自定义脱敏器，默认使用安全字段集合。
        max_bytes: 调用方期望的 UTF-8 附件上限；实际值会被钳制为不超过 1 MiB。
    返回值:
        成功附加返回 ``True``；Allure 未安装时安全返回 ``False``。
    异常说明:
        上限小到无法容纳截断元数据时抛出 ``ValueError``。
    """
    if _allure is None:
        return False
    safe_payload = (redactor or Redactor.from_config()).redact(payload)
    effective_max_bytes = min(max_bytes, MAX_ATTACHMENT_BYTES)
    body = _bounded_json(safe_payload, effective_max_bytes)
    _allure.attach(body, name, _allure.attachment_type.JSON)
    return True
