from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import (
    LEGACY_PASSWORD_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
)


class RegisterRequest(BaseModel):
    """自助注册只接受身份凭据，禁止夹带角色、项目或授权字段。"""

    username: str
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    model_config = ConfigDict(extra="forbid")

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """先清理首尾空白，再执行沿用的 3–128 位用户名约束。"""

        cleaned = value.strip()
        if not 3 <= len(cleaned) <= 128:
            raise ValueError("用户名长度必须为 3–128 位")
        return cleaned

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        """去除显示名称两端空白，并拒绝 trim 后为空的输入。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("显示名称不能为空")
        return normalized


class RegistrationStatusResponse(BaseModel):
    """公开注册能力状态，不包含阈值、锁定或基础设施信息。"""

    mode: Literal["open", "disabled", "invite"]


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
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class LoginRequest(BaseModel):
    """用户名密码登录请求。"""

    username: str = Field(min_length=1, max_length=128)
    # 登录必须兼容发布前已存在的长密码；新密码限制只用于设置入口。
    password: str = Field(min_length=1, max_length=LEGACY_PASSWORD_MAX_LENGTH)


class ChangePasswordRequest(BaseModel):
    """当前用户修改密码请求。"""

    current_password: str = Field(min_length=1, max_length=LEGACY_PASSWORD_MAX_LENGTH)
    new_password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
    )


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
