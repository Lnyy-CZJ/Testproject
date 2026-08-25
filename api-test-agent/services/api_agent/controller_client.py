"""API Agent Web 到独立执行 Controller 的窄客户端。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from services.execution_controller.contracts import CreateRunRequest, RuntimeResult


class ControllerClient:
    """只调用固定 Controller 路由，Token 从只读文件读取且不写日志。"""

    resource_policy_id = "local-restricted-v1"
    egress_policy_id = "local-platform-v1"

    def __init__(self, base_url: str, token_file: Path, *, timeout_seconds: int = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file
        self.timeout_seconds = timeout_seconds

    def _call(self, path: str, payload: dict) -> RuntimeResult:
        """发送内部鉴权请求并将网络/协议问题映射为稳定运行时错误。"""

        try:
            token = self.token_file.read_text(encoding="utf-8").strip()
            request = urllib.request.Request(
                f"{self.base_url}{path}", data=json.dumps(payload).encode(), method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return RuntimeResult.model_validate_json(response.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode())
                # Controller 的运行时失败使用 ``RuntimeResult`` 顶层 error_code；
                # 鉴权和请求校验错误仍沿用标准 error.code 信封。两种结构都要
                # 保留稳定错误码，避免页面只能看到没有诊断价值的笼统拒绝。
                code = body.get("error_code") or body.get("error", {}).get("code", "CONTROLLER_REJECTED")
            except (ValueError, json.JSONDecodeError):
                code = "CONTROLLER_REJECTED"
            return RuntimeResult(status="failed", error_code=code)
        except (OSError, ValueError, urllib.error.URLError):
            return RuntimeResult(status="failed", error_code="CONTROLLER_UNAVAILABLE")

    def create(self, request: CreateRunRequest) -> RuntimeResult:
        return self._call("/internal/v1/runs", request.model_dump(mode="json"))

    def cancel(self, run_id: str) -> RuntimeResult:
        return self._call(f"/internal/v1/runs/{run_id}/cancel", {})

    def reconcile(self, active_run_ids: set[str]) -> list[str]:
        """对账由 Controller 运维任务调用；Web 请求路径不执行全局回收。"""

        return []
