from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
