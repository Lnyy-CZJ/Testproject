from typing import Literal

from pydantic import BaseModel


class ServiceHealthResponse(BaseModel):
    """平台进程或就绪状态响应。"""

    service: Literal["platform-api"] = "platform-api"
    status: Literal["ok", "ready"]
    version: str
    component_version: str
    revision: str
    dirty: bool
    content_sha256: str
    runtime_environment: str
