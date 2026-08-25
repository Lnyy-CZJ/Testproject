from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.auth import ProjectSummary, ToolGrantSummary


class UserCreateRequest(BaseModel):
    """管理员创建用户请求。"""

    username: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["platform_admin", "admin", "tester"] | None = None
    role_ids: list[str] = Field(default_factory=list, max_length=20)
    must_change_password: bool = True


class UserUpdateRequest(BaseModel):
    """管理员修改用户状态和角色请求。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    role: Literal["platform_admin", "admin", "tester"] | None = None
    role_ids: list[str] | None = Field(default=None, max_length=20)


class ResetPasswordRequest(BaseModel):
    """管理员重置用户密码请求。"""

    new_password: str = Field(min_length=12, max_length=256)


class UserAdminResponse(BaseModel):
    """管理页面用户详情。"""

    id: str
    username: str
    display_name: str
    status: str
    must_change_password: bool
    role: Literal["platform_admin", "admin", "tester"] | None
    role_ids: list[str]
    projects: list[ProjectSummary] = Field(default_factory=list)
    extra_tool_grants: list[ToolGrantSummary] = Field(default_factory=list)
    last_login_at: datetime | None
    created_at: datetime


class RoleGrantRequest(BaseModel):
    """角色授权项。"""

    permission_code: str
    resource_type: str = Field(pattern="^(platform|tool)$")
    resource_id: str = "*"


class RoleCreateRequest(BaseModel):
    """创建角色请求。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    grants: list[RoleGrantRequest] = Field(default_factory=list, max_length=100)


class RoleUpdateRequest(BaseModel):
    """修改角色请求。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    grants: list[RoleGrantRequest] | None = Field(default=None, max_length=100)


class RoleResponse(BaseModel):
    """角色及其授权项响应。"""

    id: str
    name: str
    description: str
    is_builtin: bool
    grants: list[RoleGrantRequest]


class CredentialReadinessResponse(BaseModel):
    """管理员可查看的用户级配置就绪度安全摘要。

    该模型刻意不包含 Credential、Secret、Release 或 Profile 的内部 ID，也不
    返回字段名称、掩码、长度、哈希等可用于推断 Secret 的信息。Credential 与
    LLM 能力共用一张只读表，通过 ``resource_type`` 区分。
    """

    resource_type: str = Field(pattern="^(credential|llm_binding)$")
    user_id: str
    username: str
    user_status: str
    environment_id: str
    tool_id: str
    provider_type: str | None = None
    capability_key: str | None = None
    readiness_status: str = Field(pattern="^(configured|missing|invalid|expiring)$")
    credential_status: str | None = None
    current_version: int
    configured_field_count: int = Field(ge=0)
    required_field_count: int = Field(ge=0)
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_error_code: str | None = None
