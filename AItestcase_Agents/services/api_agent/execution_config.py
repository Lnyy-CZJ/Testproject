"""S2 本机执行开关和登记目标配置。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionTarget:
    """Web 可选择的逻辑目标；内部 URL 只进入受控 Run 输入。"""

    target_id: str
    environment: str
    internal_base_url: str
    masked_base_url: str
    allow_write_methods: bool


def load_execution_targets() -> dict[str, ExecutionTarget]:
    """加载目标登记表；格式错误时返回空表并使执行门禁失败关闭。"""

    try:
        raw = json.loads(os.getenv("API_EXECUTION_TARGETS", "[]"))
        targets = {
            str(item["target_id"]): ExecutionTarget(
                target_id=str(item["target_id"]), environment=str(item["environment"]),
                internal_base_url=str(item["internal_base_url"]).rstrip("/"),
                masked_base_url=str(item["masked_base_url"]),
                allow_write_methods=bool(item.get("allow_write_methods", False)),
            )
            for item in raw
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return targets


def execution_enabled() -> bool:
    """仅显式 true 且运行环境非 prod 时允许真实执行。"""

    enabled = os.getenv("API_EXECUTION_ENABLED", "false").strip().lower() == "true"
    environment = os.getenv("PLATFORM_RUNTIME_ENV", "dev").strip().lower()
    return enabled and environment not in {"prod", "production"}
