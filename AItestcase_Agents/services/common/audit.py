"""构造不包含业务正文和 Secret 的工具审计事件。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from services.common.platform_client import PlatformClient


LOGGER = logging.getLogger("agent.audit")


def emit_audit(
    client: PlatformClient,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    outcome: str,
    actor_user_id: str | None,
    actor_username: str | None,
    metadata: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    """尽力写平台审计；平台暂时不可用时记录本地结构化告警。"""

    event = {
        "event_id": f"audit_{uuid.uuid4().hex}",
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "outcome": outcome,
        "error_code": error_code,
        "actor_user_id": actor_user_id,
        "actor_username": actor_username,
        "metadata": metadata or {},
    }
    try:
        client.audit(event)
    except Exception as exc:  # 审计失败不覆盖已经完成的用户操作。
        LOGGER.warning("audit_delivery_failed action=%s resource_id=%s reason=%s", action, resource_id, type(exc).__name__)

