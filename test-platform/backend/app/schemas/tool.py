from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ToolResponse(BaseModel):
    """前端可见的工具目录字段，不包含内部健康地址。"""

    id: str
    name: str
    description: str
    entry_url: str
    short_code: str
    icon_key: str
    category: str
    features: list[str]
    sort_order: int
    access_scope: Literal["public", "project"] = "project"
    project_id: str | None = None
    project_name: str | None = None
    access_source: str | None = None
    can_manage: bool = False

    model_config = ConfigDict(from_attributes=True)


class ToolListResponse(BaseModel):
    """工具目录列表响应。"""

    items: list[ToolResponse]


class ToolHealthResponse(BaseModel):
    """单个工具的健康探测结果。"""

    tool_id: str
    status: Literal["healthy", "unhealthy"]
    checked_at: datetime
    version: str | None = None
    revision: str | None = None
    dirty: bool | None = None
    runtime_environment: str | None = None
