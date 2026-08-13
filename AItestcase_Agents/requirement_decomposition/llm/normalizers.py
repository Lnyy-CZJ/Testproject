"""LLM 输出归一化工具。"""

from __future__ import annotations

import json


def normalize_test_object_item(item: dict) -> dict:
    """归一化测试对象字段。

    功能说明:
        真实 LLM 可能把 `values` 输出为对象列表，而 Schema 期望字符串列表。
        这里将复杂值转换成可读字符串，避免一次字段格式漂移中断整篇拆解。

    参数说明:
        item (dict): LLM 输出的单个 test_object。

    返回值:
        dict: 可被 TestObject Pydantic 模型校验的字典。
    """

    normalized = dict(item)
    normalized["values"] = normalize_string_list(normalized.get("values", []))
    return normalized


def normalize_string_list(value) -> list[str]:
    """将任意 LLM 列表值归一为 list[str]。"""

    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        value = [value]

    items: list[str] = []
    for item in value:
        text = _to_readable_string(item)
        if text and text not in items:
            items.append(text)
    return items


def _to_readable_string(value) -> str:
    """把复杂 LLM 值转换成可读字符串。"""

    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return "；".join(f"{key}: {val}" for key, val in value.items() if val is not None)
    if isinstance(value, (list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return str(value).strip()
