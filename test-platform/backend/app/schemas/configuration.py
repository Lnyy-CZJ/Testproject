from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    value_scope: str
    credential_provider_type: str | None


class ReleaseItemRequest(BaseModel):
    """普通配置项草稿值；Secret 通过独立接口维护。"""

    definition_id: str
    value: Any | None = None


class ReleaseCreateRequest(BaseModel):
    """创建指定工具和环境的配置草稿。"""

    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    owner_type: str = Field(pattern="^(platform|tool|tool_project_scope|llm_profile|llm_binding)$")
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
    owner_type: str = Field(pattern="^(platform|tool|tool_project_scope|llm_profile|llm_binding)$")
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
    runtime_scope_id: str | None = Field(default=None, min_length=1, max_length=64)
    provider_type: str = Field(pattern="^(gateway_session|admin_login)$")


class CredentialResponse(BaseModel):
    """凭证生命周期状态。"""

    id: str
    tool_id: str
    environment_id: str
    runtime_scope_id: str | None
    provider_type: str
    status: str
    current_version: int
    expires_at: datetime | None
    refresh_expires_at: datetime | None
    last_error_code: str | None
    last_checked_at: datetime | None


class PersonalCredentialPutRequest(BaseModel):
    """原子创建或替换当前登录用户的一版个人凭证。

    ``extra=forbid`` 是所有权边界的一部分：客户端不能通过附带 ``user_id``
    或其他未声明字段指定写入主体，服务端始终从认证会话解析用户。
    """

    model_config = ConfigDict(extra="forbid")

    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    runtime_scope_id: str | None = Field(default=None, min_length=1, max_length=64)
    expected_version: int = Field(ge=0)
    values: dict[str, Any] = Field(min_length=1, max_length=100)


class PersonalCredentialFieldResponse(BaseModel):
    """可展示的个人凭证字段状态；永不包含值、长度、掩码或指纹。"""

    key: str
    display_name: str
    required: bool
    configured: bool


class PersonalCredentialResponse(BaseModel):
    """个人凭证元数据与字段就绪状态。"""

    id: str
    tool_id: str
    environment_id: str
    runtime_scope_id: str | None
    provider_type: str
    status: str
    current_version: int
    expires_at: datetime | None
    refresh_expires_at: datetime | None
    last_checked_at: datetime | None
    last_error_code: str | None
    fields: list[PersonalCredentialFieldResponse]


class PersonalCredentialValidationResponse(BaseModel):
    """受控验证请求的调度结果；不把未实现的 Provider 校验伪装为成功。"""

    id: str
    validation_state: str
    status: str
    current_version: int


class RuntimeScopeCreateRequest(BaseModel):
    """创建不可变五元组 Scope；环境映射由服务端和数据库双重校验。"""

    model_config = ConfigDict(extra="forbid")

    environment_id: str = Field(pattern="^(dev|prod)$")
    tool_id: str = Field(min_length=1, max_length=64)
    platform_project_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,31}$")
    target_env: str = Field(pattern="^(test|prod)$")
    display_name: str = Field(min_length=1, max_length=128)
    is_default: bool = False


class RuntimeScopePatchRequest(BaseModel):
    """仅更新展示/启停/默认状态，并使用 revision 防止覆盖并发修改。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern="^(active|disabled)$")
    is_default: bool | None = None
    revision: int = Field(ge=1)


class RuntimeScopeResponse(BaseModel):
    """管理端可见的 Scope 元数据；不包含配置或 Secret 值。"""

    id: str
    environment_id: str
    platform_environment: str
    tool_id: str
    platform_project_id: str
    project_id: str
    target_env: str
    display_name: str
    status: str
    is_default: bool
    revision: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
