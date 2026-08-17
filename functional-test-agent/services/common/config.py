"""Web 服务自身配置；本模块不会导入智能体 LLM 配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServiceSettings:
    """单个智能体 Web 服务的不可变部署配置。"""

    tool_id: str
    agent_type: str
    base_path: str
    host: str
    port: int
    data_dir: Path
    platform_api_url: str
    platform_client_token_file: Path
    runtime_environment: str
    platform_home_url: str
    app_revision: str


def load_service_settings(tool_id: str, agent_type: str, default_path: str, default_port: int) -> ServiceSettings:
    """读取并校验指定服务的部署配置。

    异常说明:
        配置的工具 ID、基础路径或环境不合法时抛出 RuntimeError，阻止服务以错误身份启动。
    """

    actual_tool_id = os.getenv("AGENT_TOOL_ID", tool_id).strip()
    if actual_tool_id != tool_id:
        raise RuntimeError(f"AGENT_TOOL_ID 必须为 {tool_id}")
    base_path = os.getenv("AGENT_BASE_PATH", default_path).strip().rstrip("/")
    if not base_path.startswith("/") or ".." in base_path:
        raise RuntimeError("AGENT_BASE_PATH 不合法")
    environment = os.getenv("PLATFORM_RUNTIME_ENV", "dev").strip()
    if not environment or "/" in environment or ".." in environment:
        raise RuntimeError("PLATFORM_RUNTIME_ENV 不合法")
    return ServiceSettings(
        tool_id=tool_id,
        agent_type=agent_type,
        base_path=base_path,
        host=os.getenv("AGENT_WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENT_WEB_PORT", str(default_port))),
        data_dir=Path(os.getenv("AGENT_DATA_DIR", f"runtime/{environment}/{agent_type}")).resolve(),
        platform_api_url=os.getenv("PLATFORM_API_URL", "http://platform-api:8000/api/v1").rstrip("/"),
        platform_client_token_file=Path(os.getenv("PLATFORM_CLIENT_TOKEN_FILE", "/run/secrets/platform-client-token")),
        runtime_environment=environment,
        platform_home_url=os.getenv("PLATFORM_HOME_URL", "/"),
        app_revision=os.getenv("APP_REVISION", "unknown"),
    )

