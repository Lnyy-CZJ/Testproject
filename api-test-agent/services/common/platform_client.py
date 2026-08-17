"""最小权限的平台内部 API Client。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.common.errors import PLATFORM_CONFIG_UNAVAILABLE, ServiceError


class PlatformClient:
    """按固定 tool_id/environment 读取配置并写审计。"""

    def __init__(self, api_url: str, tool_id: str, environment: str, token_file: Path, timeout: float = 5.0):
        self.api_url = api_url.rstrip("/")
        self.tool_id = tool_id
        self.environment = environment
        self.token_file = Path(token_file)
        self.timeout = timeout

    def _token(self) -> str:
        """按请求读取 Token，避免写入任务记录或长期复制。"""

        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台工具身份不可用") from None
        if len(token) < 32:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台工具身份不可用")
        return token

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict[str, Any]:
        """发送内部 JSON 请求，并把网络错误映射为稳定错误码。"""

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.api_url}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
            return json.loads(body) if body else {}
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置服务暂时不可用") from None

    def runtime_config(self, *, include_secrets: bool) -> dict[str, Any]:
        """读取当前环境的配置快照，并复核服务绑定范围。"""

        query = urlencode({
            "include_secrets": "true" if include_secrets else "false",
            "llm_capability": "default",
        })
        result = self._json("GET", f"/internal/tools/{self.tool_id}/runtime-config?{query}")
        if result.get("tool_id") != self.tool_id or result.get("environment") != self.environment:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置作用域不匹配")
        return result

    def audit(self, event: dict[str, Any]) -> None:
        """上报幂等审计；调用者决定失败是否影响主流程。"""

        self._json("POST", f"/internal/tools/{self.tool_id}/audit-events", event)
