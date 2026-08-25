from __future__ import annotations

from typing import Any

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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

    runtime_context_id: str | None = Field(default=None, min_length=8, max_length=64)
    provider_type: str
    status: str
    expires_at: str | None = None
    error_code: str | None = None


class SessionWriteRequest(BaseModel):
    """工具原子写回动态会话。"""

    expected_version: int = Field(ge=0)
    values: dict[str, Any]


class UserCredentialSessionWriteRequest(BaseModel):
    """按 Runtime Context 所属用户原子写回个人会话。"""

    model_config = ConfigDict(extra="forbid")

    runtime_context_id: str = Field(min_length=8, max_length=64)
    expected_version: int = Field(ge=0)
    values: dict[str, Any] = Field(min_length=1, max_length=100)


class RuntimeContextCreateRequest(BaseModel):
    """把签名用户上下文兑换为绑定单一任务资源的持久上下文。"""

    model_config = ConfigDict(extra="forbid")

    resource_type: str = Field(pattern="^(task|run|request)$")
    resource_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )


class RuntimeContextResponse(BaseModel):
    """工具可保存到内部任务元数据的短期不透明 Context。"""

    runtime_context_id: str
    tool_id: str
    environment_id: str
    expires_at: datetime
    resource_snapshot: dict[str, str | None]


class ResourceAccessCheckRequest(BaseModel):
    """工具针对根业务资源请求平台统一判定的数据范围。"""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=64)
    resource_type: str = Field(default="task", pattern="^(task|run|request|export)$")
    root_resource_id: str | None = Field(default=None, min_length=1, max_length=128)


class BusinessResourceRegisterRequest(BaseModel):
    """无长期 Runtime Context 的轻量工具登记根业务资源。"""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1, max_length=64)
    resource_type: str = Field(pattern="^(task|run|request|export)$")
    resource_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ResourceAccessCheckResponse(BaseModel):
    """只包含数据过滤所需的窄授权结果，不返回平台控制面权限。"""

    allowed: bool
    action: str
    user_id: str
    username: str
    display_name: str
    tool_id: str
    environment: str
    data_scope: str = Field(pattern="^(own|project|global)$")
    managed_project_ids: list[str] = Field(default_factory=list)
    access_scope_snapshot: str | None = Field(default=None, pattern="^(public|project)$")
    project_id_snapshot: str | None = None
    authorization_source_snapshot: str | None = None


class RuntimeSnapshotSelector(BaseModel):
    """规划阶段可持久化的非敏感、不可变版本选择器。"""

    model_config = ConfigDict(extra="forbid")

    release_id: str | None = None
    system_secret_versions: dict[str, str] = Field(default_factory=dict)
    credential_versions: dict[str, int] = Field(default_factory=dict)
    credential_secret_versions: dict[str, dict[str, str]] = Field(default_factory=dict)
    llm_capability: str | None = None
    llm_binding_release_id: str | None = None
    llm_profile_release_id: str | None = None
    llm_secret_version_id: str | None = None


class RuntimeConfigMaterializeRequest(BaseModel):
    """执行开始时按已规划版本物化一次 Secret 快照。"""

    model_config = ConfigDict(extra="forbid")

    runtime_context_id: str = Field(min_length=8, max_length=64)
    snapshot_selector: RuntimeSnapshotSelector


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
    subject_user_id: str | None = None
    runtime_context_expires_at: datetime | None = None
    snapshot_selector: RuntimeSnapshotSelector | None = None
