from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConfigDefinitionResponse(BaseModel):
    """配置中心可展示的定义元数据。"""

    id: str
    key: str
    display_name: str
    description: str
    owner_type: str
    owner_id: str
    group_key: str
    value_type: str
    sensitivity: str
    required: bool
    default_value: Any | None
    validation_schema: dict[str, Any]
    apply_mode: str
    editable: bool
    sort_order: int


class ReleaseItemRequest(BaseModel):
    """普通配置项草稿值；Secret 通过独立接口维护。"""

    definition_id: str
    value: Any | None = None


class ReleaseCreateRequest(BaseModel):
    """创建指定工具和环境的配置草稿。"""

    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    owner_type: str = Field(pattern="^(platform|tool)$")
    owner_id: str = Field(min_length=1, max_length=64)


class ReleaseUpdateRequest(BaseModel):
    """使用乐观锁更新草稿配置项。"""

    revision: int = Field(ge=1)
    items: list[ReleaseItemRequest] = Field(max_length=200)


class ReleaseResponse(BaseModel):
    """配置 Release 及其普通配置项。"""

    id: str
    environment_id: str
    owner_type: str
    owner_id: str
    version: int
    revision: int
    status: str
    created_by: str
    published_by: str | None
    created_at: datetime
    published_at: datetime | None
    items: list[ReleaseItemRequest]


class SecretReplaceRequest(BaseModel):
    """Secret 新版本输入；明文只允许出现在请求体。"""

    environment_id: str
    owner_type: str = Field(pattern="^(platform|tool)$")
    owner_id: str
    definition_id: str
    value: str = Field(min_length=1, max_length=65536)
    expires_at: datetime | None = None


class SecretResponse(BaseModel):
    """永不回显明文的 Secret 元数据。"""

    id: str
    environment_id: str
    owner_type: str
    owner_id: str
    definition_id: str
    configured: bool
    status: str
    version: int | None
    expires_at: datetime | None
    updated_at: datetime


class CredentialCreateRequest(BaseModel):
    """将已导入 Secret 组合为可由 Agent 维护的凭证。"""

    tool_id: str = Field(min_length=1, max_length=64)
    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    provider_type: str = Field(pattern="^(gateway_session|admin_login)$")


class CredentialResponse(BaseModel):
    """凭证生命周期状态。"""

    id: str
    tool_id: str
    environment_id: str
    provider_type: str
    status: str
    current_version: int
    expires_at: datetime | None
    refresh_expires_at: datetime | None
    last_error_code: str | None
    last_checked_at: datetime | None
