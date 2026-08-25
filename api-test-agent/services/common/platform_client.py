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

    def _json(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """发送内部 JSON 请求，并保留平台返回的安全稳定错误码。"""

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        request = Request(
            f"{self.api_url}{path}", data=data, method=method,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
            return json.loads(body) if body else {}
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8"))
                code = str(error["code"])
                message = str(error["message"])
            except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置服务暂时不可用") from None
            raise ServiceError(int(exc.code), code, message) from None
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置服务暂时不可用") from None

    def runtime_config(
        self,
        *,
        include_secrets: bool,
        runtime_context_id: str | None = None,
        llm_capability: str | None = "default",
    ) -> dict[str, Any]:
        """读取规划快照或兼容期当前快照，并复核服务绑定范围。"""

        query_values = {"include_secrets": "true" if include_secrets else "false"}
        if runtime_context_id:
            query_values["runtime_context_id"] = runtime_context_id
        if llm_capability:
            query_values["llm_capability"] = llm_capability
        query = urlencode(query_values)
        result = self._json("GET", f"/internal/tools/{self.tool_id}/runtime-config?{query}")
        if result.get("tool_id") != self.tool_id or result.get("environment") != self.environment:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置作用域不匹配")
        return result

    def resource_access_check(
        self,
        resource_context: str,
        *,
        action: str,
        root_resource_id: str | None = None,
    ) -> dict[str, Any]:
        """向平台核验 opaque 资源上下文，禁止 Agent 自行解码或推导权限。"""

        if not resource_context:
            raise ServiceError(401, "RESOURCE_CONTEXT_REQUIRED", "当前请求缺少可信资源上下文")
        result = self._json(
            "POST", f"/internal/tools/{self.tool_id}/resource-access/check",
            {"action": action, "resource_type": "task", "root_resource_id": root_resource_id},
            extra_headers={"X-Platform-Resource-Context": resource_context},
        )
        # tool/environment 是授权响应的强绑定字段；字段缺失与值不匹配均拒绝，
        # 防止错误响应或串线响应被当前 Agent 接受。
        if result.get("tool_id") != self.tool_id or result.get("environment") != self.environment:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台资源授权作用域不匹配")
        return result

    def plan_runtime_config(
        self,
        signed_user_context: str,
        *,
        resource_type: str,
        resource_id: str,
        llm_capability: str = "default",
        resource_context: str | None = None,
    ) -> dict[str, Any]:
        """兑换可信 Header，并规划可安全落盘的任务版本选择器。"""

        if not signed_user_context:
            raise ServiceError(403, "RUNTIME_CONTEXT_REQUIRED", "当前请求缺少可信用户上下文")
        context = self._json(
            "POST",
            f"/internal/tools/{self.tool_id}/runtime-contexts",
            {"resource_type": resource_type, "resource_id": resource_id},
            extra_headers={
                "X-Platform-User-Context": signed_user_context,
                **({"X-Platform-Resource-Context": resource_context} if resource_context else {}),
            },
        )
        runtime_context_id = context.get("runtime_context_id")
        if not isinstance(runtime_context_id, str) or not runtime_context_id:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台用户上下文响应无效")
        snapshot = self.runtime_config(
            include_secrets=False,
            runtime_context_id=runtime_context_id,
            llm_capability=llm_capability,
        )
        selector = snapshot.get("snapshot_selector")
        if selector is not None and not isinstance(selector, dict):
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置选择器无效")
        return {
            "runtime_context_id": runtime_context_id,
            "runtime_context_expires_at": context.get("expires_at"),
            "snapshot_selector": selector,
            "llm_capability": llm_capability,
            "release_id": snapshot.get("release_id"),
            "release_version": snapshot.get("release_version"),
        }

    def materialize_runtime_config(self, runtime_metadata: dict[str, Any]) -> dict[str, Any]:
        """在 Worker 启动时重新校验 Context 并物化精确历史版本。"""

        runtime_context_id = runtime_metadata.get("runtime_context_id")
        if not isinstance(runtime_context_id, str) or not runtime_context_id:
            raise ServiceError(403, "RUNTIME_CONTEXT_REQUIRED", "当前任务缺少可信用户上下文")
        selector = runtime_metadata.get("snapshot_selector")
        if selector is None:
            return self.runtime_config(
                include_secrets=True,
                runtime_context_id=runtime_context_id,
                llm_capability=str(runtime_metadata.get("llm_capability") or "default"),
            )
        if not isinstance(selector, dict):
            raise ServiceError(409, "RUNTIME_SNAPSHOT_INVALID", "任务配置快照无效，请重新提交任务")
        result = self._json(
            "POST",
            f"/internal/tools/{self.tool_id}/runtime-config/materialize",
            {
                "runtime_context_id": runtime_context_id,
                "snapshot_selector": selector,
            },
        )
        if result.get("tool_id") != self.tool_id or result.get("environment") != self.environment:
            raise ServiceError(503, PLATFORM_CONFIG_UNAVAILABLE, "平台配置作用域不匹配")
        return result

    def audit(self, event: dict[str, Any]) -> None:
        """上报幂等审计；调用者决定失败是否影响主流程。"""

        self._json("POST", f"/internal/tools/{self.tool_id}/audit-events", event)
