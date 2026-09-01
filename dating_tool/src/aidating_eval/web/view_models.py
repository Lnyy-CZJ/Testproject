"""Web 返回值的纯函数映射。

这里不携带任何认证或后端 Wire 逻辑，只把领域对象转换为模板/API 可以消费的 JSON 形状，
便于 Flask 路由保持薄层，也避免 Jinja 直接读取内部对象的私有字段。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def jsonable(value: Any) -> Any:
    """递归转换 Enum、Path、dataclass 和容器为 JSON 原生值。"""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item) for item in value]
    return value


def run_summary(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """提取列表页需要的有限 Manifest 字段。"""

    keys = (
        "run_id",
        "created_at",
        "updated_at",
        "mode",
        "task_kind",
        "status",
        "case_count",
        "cleanup_status",
        "cancel_requested",
        "summary",
    )
    return {key: jsonable(manifest[key]) for key in keys if key in manifest}


__all__ = ["jsonable", "run_summary"]
