"""只用于 Flask TESTING 的 Fake Runtime；不建立任何网络或容器连接。"""

from __future__ import annotations

from collections.abc import Callable

from services.execution_controller.contracts import CreateRunRequest, RuntimeResult


class DisabledRuntimeAdapter:
    """生产默认适配器，任何创建请求都明确返回未就绪。"""

    def create(self, _request: CreateRunRequest) -> RuntimeResult:
        return RuntimeResult(status="failed", error_code="EXECUTION_NOT_READY")

    def cancel(self, _run_id: str) -> RuntimeResult:
        return RuntimeResult(status="failed", error_code="EXECUTION_NOT_READY")

    def reconcile(self, _active_run_ids: set[str]) -> list[str]:
        return []


class FakeRuntimeAdapter:
    """使用内存场景函数验证生命周期，不调用 HTTP、Docker、Kubernetes 或宿主进程。"""

    def __init__(self, scenario: Callable[[CreateRunRequest], RuntimeResult] | None = None):
        self.scenario = scenario or (lambda request: RuntimeResult(status="succeeded", result_id=request.output_id))
        self.states: dict[str, RuntimeResult] = {}

    def create(self, request: CreateRunRequest) -> RuntimeResult:
        result = self.scenario(request)
        self.states[request.run_id] = result
        return result

    def cancel(self, run_id: str) -> RuntimeResult:
        if run_id not in self.states:
            return RuntimeResult(status="failed", error_code="RUN_NOT_FOUND")
        result = RuntimeResult(status="cancelled")
        self.states[run_id] = result
        return result

    def reconcile(self, active_run_ids: set[str]) -> list[str]:
        orphans = sorted(set(self.states) - active_run_ids)
        for run_id in orphans:
            self.states[run_id] = RuntimeResult(status="cancelled", error_code="ORPHAN_RECLAIMED")
        return orphans
