from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    """审计列表和详情的安全响应。"""

    id: str
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    actor_snapshot: dict[str, Any]
    action: str
    resource_type: str
    resource_id: str | None
    tool_id: str | None
    environment_id: str | None
    outcome: str
    error_code: str | None
    request_id: str | None
    ip_address: str | None
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    metadata_json: dict[str, Any]
    detail: str


class AuditListResponse(BaseModel):
    """分页审计响应。"""

    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int
