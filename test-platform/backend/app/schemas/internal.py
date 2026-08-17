from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConfigAckRequest(BaseModel):
    """工具确认已成功加载配置 Release。"""

    release_id: str


class ToolAuditEventRequest(BaseModel):
    """工具提交的受控幂等审计事件。"""

    event_id: str = Field(min_length=8, max_length=64)
    action: str = Field(min_length=3, max_length=128)
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str | None = Field(default=None, max_length=128)
    outcome: str = Field(pattern="^(success|failed|denied|unknown)$")
    error_code: str | None = Field(default=None, max_length=128)
    actor_user_id: str | None = Field(default=None, max_length=64)
    actor_username: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialStatusRequest(BaseModel):
    """工具上报的不含 Token 的凭证状态。"""

    provider_type: str
    status: str
    expires_at: str | None = None
    error_code: str | None = None


class SessionWriteRequest(BaseModel):
    """工具原子写回动态会话。"""

    expected_version: int = Field(ge=0)
    values: dict[str, Any]


class RuntimeConfigResponse(BaseModel):
    """工具按任务读取的不可变配置快照。"""

    tool_id: str
    environment: str
    release_id: str | None
    release_version: int | None
    normal: dict[str, Any]
    secrets: dict[str, str]
    credential_metadata: dict[str, Any]
    configured_secret_keys: list[str] = Field(default_factory=list)
    llm: dict[str, Any] | None = None
