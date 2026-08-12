from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.redaction import redact
from app.core.security import new_id
from app.models.audit import AuditLog
from app.models.identity import User


def add_audit_event(
    database: Session,
    *,
    action: str,
    resource_type: str,
    outcome: str,
    request: Request | None = None,
    actor: User | None = None,
    actor_type: str = "user",
    actor_id: str | None = None,
    resource_id: str | None = None,
    tool_id: str | None = None,
    environment_id: str | None = None,
    error_code: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    detail: str = "",
    event_id: str | None = None,
) -> AuditLog:
    """
    将结构化且已脱敏的审计事件加入当前事务。

    参数说明:
        database: 当前业务事务的数据库会话。
        action/resource_type/outcome: 稳定事件标识、资源类型和结果。
        request/actor: 可选的 HTTP 与用户上下文。
    返回值:
        AuditLog: 已加入 Session、尚未强制提交的审计模型。
    """

    resolved_actor_id = actor.id if actor is not None else actor_id
    actor_snapshot = (
        {"username": actor.username, "display_name": actor.display_name}
        if actor is not None
        else {}
    )
    row = AuditLog(
        id=event_id or new_id("aud"),
        actor_type=actor_type,
        actor_id=resolved_actor_id,
        actor_snapshot=redact(actor_snapshot),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        tool_id=tool_id,
        environment_id=environment_id,
        outcome=outcome,
        error_code=error_code,
        request_id=getattr(request.state, "request_id", None) if request else None,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent", "")[:512] if request else None,
        before_json=redact(before) if before is not None else None,
        after_json=redact(after) if after is not None else None,
        metadata_json=redact(metadata or {}),
        detail=detail[:1000],
    )
    database.add(row)
    return row
