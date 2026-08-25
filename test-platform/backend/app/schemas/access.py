from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    """平台管理员创建项目时提供的稳定身份与说明。"""

    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    reason: str = Field(min_length=2, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class ProjectUpdateRequest(BaseModel):
    """项目 code 不可修改，只允许更新展示信息。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    revision: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class ProjectResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    status: str
    revision: int
    authorization_epoch: int
    relation: str | None = None
    manager_count: int = 0
    member_count: int = 0
    tool_count: int = 0
    active_grant_count: int = 0
    updated_at: datetime


class ProjectMemberRequest(BaseModel):
    """普通管理员只能用完整用户名精确添加，不提供目录枚举。"""

    username: str = Field(min_length=3, max_length=128)
    reason: str = Field(min_length=2, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class ProjectRelationRemoveRequest(BaseModel):
    """移除项目关系属于高风险授权变更，必须留下可审计原因。"""

    reason: str = Field(min_length=2, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class ProjectMemberResponse(BaseModel):
    id: str
    user_id: str
    username: str
    display_name: str
    relation: Literal["manager", "member"]
    role: Literal["platform_admin", "admin", "tester"]
    status: Literal["active", "disabled"]
    created_at: datetime


class ProjectImpactPreviewResponse(BaseModel):
    expected_revision: int
    impact_token: str
    manager_count: int
    member_count: int
    tool_count: int
    active_grant_count: int
    running_task_count: Literal["unknown"] = "unknown"


class ProjectStatusChangeRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    impact_token: str = Field(min_length=16)
    reason: str = Field(min_length=2, max_length=1000)
    force_unknown_impact: bool = False


class ToolAccessResponse(BaseModel):
    id: str
    name: str
    description: str
    is_enabled: bool
    access_scope: Literal["public", "project"]
    project_id: str | None
    project_name: str | None
    revision: int
    authorization_epoch: int
    public_safety_policy_status: str
    public_policy_complete: bool
    public_eligible: bool
    updated_at: datetime


class ToolImpactPreviewRequest(BaseModel):
    access_scope: Literal["public", "project"]
    project_id: str | None = None


class ToolImpactPreviewResponse(BaseModel):
    revision: int
    expected_revision: int
    impact_token: str
    expires_at: datetime
    current_access_scope: str
    next_access_scope: str
    current_project_id: str | None
    next_project_id: str | None
    affected_user_count: int
    extra_grant_count: int
    historical_resource_count: int
    running_task_count: int | Literal["unknown"] = "unknown"


class ToolAccessChangeRequest(ToolImpactPreviewRequest):
    revision: int = Field(ge=1)
    impact_token: str = Field(min_length=16)
    reason: str = Field(min_length=2, max_length=1000)
    is_enabled: bool | None = None
    force_unknown_impact: bool = False


class ToolGrantCreateRequest(BaseModel):
    user_id: str
    tool_id: str
    days: int = Field(default=7, ge=1, le=90)
    reason: str = Field(min_length=2, max_length=1000)
    renewed_from_grant_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    model_config = ConfigDict(extra="forbid")


class ToolGrantRevokeRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)


class ToolGrantRenewRequest(BaseModel):
    expires_at: datetime
    reason: str = Field(min_length=2, max_length=1000)


class ToolGrantResponse(BaseModel):
    id: str
    user_id: str
    username: str | None = None
    tool_id: str
    tool_name: str | None = None
    project_id: str
    project_name: str | None = None
    status: str
    grant_reason: str
    expires_at: datetime
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None

    model_config = ConfigDict(from_attributes=True)
