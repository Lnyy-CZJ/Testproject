from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """自助注册只接受身份凭据，禁止夹带角色、项目或授权字段。"""

    username: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)

    model_config = ConfigDict(extra="forbid")


class ProjectSummary(BaseModel):
    """当前用户可见的最小项目与关系摘要。"""

    id: str
    code: str
    name: str
    status: str
    relation: str | None = None


class ToolGrantSummary(BaseModel):
    """当前用户自己的额外工具授权摘要。"""

    id: str
    tool_id: str
    tool_name: str
    project_id: str
    project_name: str
    status: str
    grant_reason: str
    expires_at: datetime


class SetupRequest(BaseModel):
    """首次管理员初始化请求。"""

    bootstrap_token: str = Field(min_length=16, max_length=512)
    username: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)


class LoginRequest(BaseModel):
    """用户名密码登录请求。"""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    """当前用户修改密码请求。"""

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserSummary(BaseModel):
    """可安全返回浏览器的用户摘要。"""

    id: str
    username: str
    display_name: str
    status: str
    must_change_password: bool


class MeResponse(BaseModel):
    """当前登录用户、角色和有效权限。"""

    user: UserSummary
    role: str | None = None
    roles: list[str]
    projects: list[ProjectSummary] = Field(default_factory=list)
    extra_tool_grants: list[ToolGrantSummary] = Field(default_factory=list)
    platform_permissions: list[str]
    tool_permissions: dict[str, list[str]]
    permission_version: int = 1
    session_expires_at: datetime


class SessionResponse(BaseModel):
    """用户可见的会话元数据。"""

    id: str
    created_at: datetime
    last_seen_at: datetime
    absolute_expires_at: datetime
    ip_address: str
    current: bool


class MessageResponse(BaseModel):
    """无敏感数据的通用成功响应。"""

    message: str
