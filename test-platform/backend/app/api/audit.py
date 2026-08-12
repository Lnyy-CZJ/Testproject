from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context, require_csrf, require_platform
from app.core.errors import PlatformError
from app.core.redaction import redact
from app.db.session import get_db
from app.models.audit import AuditLog
from app.schemas.audit import AuditEventResponse, AuditListResponse
from app.services.audit import add_audit_event
from app.services.authorization import has_platform_permission


router = APIRouter(prefix="/audit", tags=["audit"])


def _response(row: AuditLog) -> AuditEventResponse:
    """将数据库记录转换为再次脱敏的对外审计响应。"""

    return AuditEventResponse(
        id=row.id,
        occurred_at=row.occurred_at,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        actor_snapshot=redact(row.actor_snapshot),
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        tool_id=row.tool_id,
        environment_id=row.environment_id,
        outcome=row.outcome,
        error_code=row.error_code,
        request_id=row.request_id,
        ip_address=row.ip_address,
        before_json=redact(row.before_json) if row.before_json is not None else None,
        after_json=redact(row.after_json) if row.after_json is not None else None,
        metadata_json=redact(row.metadata_json),
        detail=row.detail,
    )


def _filters(
    statement,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    action: str | None,
    tool_id: str | None,
    outcome: str | None,
):
    """在列表和导出间复用确定性的审计筛选条件。"""

    if start_at is not None:
        statement = statement.where(AuditLog.occurred_at >= start_at)
    if end_at is not None:
        statement = statement.where(AuditLog.occurred_at <= end_at)
    if action:
        statement = statement.where(AuditLog.action == action)
    if tool_id:
        statement = statement.where(AuditLog.tool_id == tool_id)
    if outcome:
        statement = statement.where(AuditLog.outcome == outcome)
    return statement


@router.get("/events", response_model=AuditListResponse)
def list_events(
    context: Annotated[AuthContext, Depends(require_platform("platform.audit.view"))],
    database: Annotated[Session, Depends(get_db)],
    page: int = 1,
    page_size: int = 50,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    action: str | None = None,
    tool_id: str | None = None,
    outcome: str | None = None,
) -> AuditListResponse:
    """按权限返回分页审计事件，所有结构化字段在响应前再次脱敏。"""

    if page < 1 or page_size < 1 or page_size > 200:
        raise PlatformError(422, "VALIDATION_ERROR", "分页参数不正确")
    base = _filters(
        select(AuditLog), start_at=start_at, end_at=end_at,
        action=action, tool_id=tool_id, outcome=outcome,
    )
    count_statement = _filters(
        select(func.count()).select_from(AuditLog), start_at=start_at, end_at=end_at,
        action=action, tool_id=tool_id, outcome=outcome,
    )
    rows = list(database.scalars(
        base.order_by(AuditLog.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all())
    return AuditListResponse(
        items=[_response(row) for row in rows],
        total=int(database.scalar(count_statement) or 0),
        page=page,
        page_size=page_size,
    )


@router.get("/events/{event_id}", response_model=AuditEventResponse)
def get_event(
    event_id: str,
    context: Annotated[AuthContext, Depends(require_platform("platform.audit.view"))],
    database: Annotated[Session, Depends(get_db)],
) -> AuditEventResponse:
    """返回单条审计详情，不提供任何更新或删除能力。"""

    row = database.get(AuditLog, event_id)
    if row is None:
        raise PlatformError(404, "NOT_FOUND", "审计事件不存在")
    return _response(row)


@router.post("/exports")
def export_events(
    request: Request,
    context: Annotated[AuthContext, Depends(require_csrf)],
    database: Annotated[Session, Depends(get_db)],
    start_at: datetime,
    end_at: datetime,
) -> StreamingResponse:
    """导出指定时间范围内最多十万条已脱敏审计 CSV。"""

    if not has_platform_permission(database, context.user.id, "platform.audit.export"):
        raise PlatformError(403, "PERMISSION_DENIED", "无权导出审计日志")
    if start_at >= end_at:
        raise PlatformError(422, "VALIDATION_ERROR", "审计导出时间范围不正确")
    rows = list(database.scalars(
        select(AuditLog).where(
            AuditLog.occurred_at >= start_at,
            AuditLog.occurred_at <= end_at,
        ).order_by(AuditLog.occurred_at).limit(100001)
    ).all())
    if len(rows) > 100000:
        raise PlatformError(422, "AUDIT_EXPORT_TOO_LARGE", "审计导出最多支持 100,000 行")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "occurred_at", "actor_type", "actor_id", "action", "resource_type",
        "resource_id", "tool_id", "environment_id", "outcome", "error_code", "request_id",
    ])
    for row in rows:
        writer.writerow([
            row.id, row.occurred_at.isoformat(), row.actor_type, row.actor_id or "", row.action,
            row.resource_type, row.resource_id or "", row.tool_id or "", row.environment_id or "",
            row.outcome, row.error_code or "", row.request_id or "",
        ])
    add_audit_event(
        database, action="audit.export", resource_type="audit_log", outcome="success",
        request=request, actor=context.user,
        metadata={"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "row_count": len(rows)},
    )
    database.commit()
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=audit-events.csv"},
    )
