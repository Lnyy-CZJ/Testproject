"""
认证相关 Pydantic Schema

与 Go 版 API 响应格式完全兼容，字段使用 camelCase。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: str = Field(..., max_length=100, description="邮箱")
    password: str = Field(..., min_length=6, description="密码")
    nickname: str | None = Field(default=None, max_length=50, description="昵称")


class LoginResponse(BaseModel):
    """登录响应"""
    token: str = Field(..., description="JWT Token")
    user: "UserProfile" = Field(..., description="用户信息")

    model_config = {"populate_by_name": True}


class UserProfile(BaseModel):
    """用户个人信息"""
    id: int
    username: str
    email: str
    nickname: str | None = None
    avatar: str | None = None
    agentTypes: str | None = Field(default=None, alias="agent_types")
    platformRole: str = Field(default="member", alias="platform_role")
    mustChangePassword: bool = Field(default=False, alias="must_change_password")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class UpdateProfileRequest(BaseModel):
    """更新个人资料请求"""
    nickname: str | None = Field(default=None, max_length=50, description="昵称")
    avatar: str | None = Field(default=None, max_length=255, description="头像地址")
    agentTypes: str | None = Field(default=None, alias="agent_types", description="Agent 身份逗号串")

    model_config = {"populate_by_name": True}


class UpdateAgentTypesRequest(BaseModel):
    """更新 Agent 身份请求"""
    agentTypes: list[str] = Field(..., min_length=1, description="Agent 身份列表")


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    oldPassword: str | None = Field(default=None, description="旧密码，兼容旧字段")
    currentPassword: str | None = Field(default=None, description="当前密码，前端现用字段")
    newPassword: str = Field(..., min_length=6, description="新密码")

    def current_password_value(self) -> str:
        """
        获取当前密码字段值。

        功能说明:
            前端当前传 `currentPassword`，旧文档中曾使用 `oldPassword`。
            这里统一兼容，避免前端改动。

        返回值:
            str: 当前密码。
        """
        return self.currentPassword or self.oldPassword or ""


class CreateUserRequest(BaseModel):
    """管理员创建用户请求"""
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    password: str | None = Field(default=None, min_length=6)
    nickname: str | None = Field(default=None, max_length=50)
    platformRole: str = Field(default="member", alias="platform_role")
    projectIds: list[int] = Field(default_factory=list, alias="project_ids")
    projectRole: str | None = Field(default=None, alias="project_role")

    model_config = {"populate_by_name": True}


class TempPasswordResponse(BaseModel):
    """临时密码响应"""
    temporaryPassword: str


class UpdatePlatformRoleRequest(BaseModel):
    """更新平台角色请求"""
    platformRole: str = Field(..., alias="platform_role")

    model_config = {"populate_by_name": True}
