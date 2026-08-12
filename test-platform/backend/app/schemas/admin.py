from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    """管理员创建用户请求。"""

    username: str = Field(min_length=3, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    role_ids: list[str] = Field(default_factory=list, max_length=20)
    must_change_password: bool = True


class UserUpdateRequest(BaseModel):
    """管理员修改用户状态和角色请求。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
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
    role_ids: list[str]
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
