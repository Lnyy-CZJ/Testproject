from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LlmProfileCreateRequest(BaseModel):
    """创建 Profile 身份及指定环境首个草稿。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")


class LlmProfileUpdateRequest(BaseModel):
    """修改不包含运行参数的 Profile 身份信息。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class LlmProfileResponse(BaseModel):
    id: str
    name: str
    description: str
    protocol: str
    is_archived: bool
    environment_id: str
    active_release_id: str | None
    active_release_version: int | None
    api_key_configured: bool
    binding_count: int
    created_at: datetime
    updated_at: datetime


class LlmBindingResponse(BaseModel):
    id: str
    tool_id: str
    capability_key: str
    display_name: str
    description: str
    environment_id: str
    active_release_id: str | None
    active_release_version: int | None
    profile_id: str | None
    enabled: bool | None
    api_key_override_configured: bool


class LlmConnectionTestRequest(BaseModel):
    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    binding_id: str = Field(min_length=1, max_length=64)


class LlmEffectiveConfigResponse(BaseModel):
    status: str
    binding_id: str
    capability_key: str
    binding_release_id: str
    binding_release_version: int
    profile_id: str
    profile_name: str
    profile_release_id: str
    profile_release_version: int
    protocol: str
    base_url: str
    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None
    api_key_configured: bool
    api_key_version: int | None = None
    snapshot_id: str
    api_key: str | None = None


class LlmConnectionTestResponse(BaseModel):
    status: str
    checked_at: datetime
    model: str
    snapshot_id: str


class PersonalLlmProfileCreateRequest(BaseModel):
    """创建并发布当前用户在指定环境的个人 LLM Profile。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    provider: str = Field(default="openai_compatible", pattern="^openai_compatible$")
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1, max_length=65536)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    enabled: bool = True


class PersonalLlmProfileUpdateRequest(BaseModel):
    """更新个人 Profile 身份或为指定环境发布一版参数。"""

    model_config = ConfigDict(extra="forbid")

    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    provider: str | None = Field(default=None, pattern="^openai_compatible$")
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    api_key: str | None = Field(default=None, min_length=1, max_length=65536)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    enabled: bool | None = None


class PersonalLlmProfileResponse(BaseModel):
    """个人 Profile 当前环境的安全摘要，永不返回 API Key。"""

    id: str
    name: str
    description: str
    provider: str
    is_archived: bool
    environment_id: str
    active_release_id: str | None
    active_release_version: int | None
    base_url: str | None
    model: str | None
    temperature: float | None
    max_tokens: int | None
    timeout_seconds: int | None
    enabled: bool | None
    api_key_configured: bool
    binding_count: int
    created_at: datetime
    updated_at: datetime


class PersonalLlmBindingPutRequest(BaseModel):
    """替换并发布当前用户在一个目录能力上的个人 Binding。"""

    model_config = ConfigDict(extra="forbid")

    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    expected_version: int = Field(ge=0)
    # ``None + enabled=false`` 表示显式解绑；它是归档 Profile 前的安全操作。
    profile_id: str | None
    enabled: bool = True
    model_override: str | None = Field(default=None, min_length=1, max_length=256)
    temperature_override: float | None = Field(default=None, ge=0, le=2)
    max_tokens_override: int | None = Field(default=None, ge=1, le=131072)
    timeout_seconds_override: int | None = Field(default=None, ge=1, le=600)
    api_key_override: str | None = Field(default=None, min_length=1, max_length=65536)
    clear_api_key_override: bool = False


class PersonalLlmBindingResponse(BaseModel):
    """用户个人 Binding 与公共能力目录的合并摘要。"""

    id: str | None
    binding_id: str
    tool_id: str
    capability_key: str
    display_name: str
    description: str
    environment_id: str
    active_release_id: str | None
    current_version: int
    profile_id: str | None
    enabled: bool | None
    model_override: str | None
    temperature_override: float | None
    max_tokens_override: int | None
    timeout_seconds_override: int | None
    api_key_override_configured: bool


class PersonalLlmConnectionTestRequest(BaseModel):
    """测试当前用户指定目录能力的已发布个人连接。"""

    model_config = ConfigDict(extra="forbid")

    environment_id: str = Field(pattern="^[a-z][a-z0-9-]{1,31}$")
    binding_id: str = Field(min_length=1, max_length=64)
