"""Dating Analysis 成功、失败和超时分支的结果读取与清理测试。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from utils.custom.assertions import assert_gateway_response
from utils.custom.flow_runner import FlowEnvironmentError, FlowExecutionError, FlowRunner


class _Response:
    """提供 Gateway 分层断言需要的最小响应。"""

    status_code = 200

    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def json(self) -> dict[str, object]:
        return {
            "code": 0,
            "responses": [
                {"id": "req_0", "success": True, "code": 0, "data": self._data}
            ],
        }


class _Gateway:
    """按调用顺序返回数据并记录实际调用的方法名。"""

    def __init__(self, data: list[dict[str, object]]) -> None:
        self.data = iter(data)
        self.methods: list[str] = []
        self.persisted_session_methods: list[str] = []

    def invoke(self, case: dict[str, object]) -> _Response:
        request = case["request"]
        assert isinstance(request, dict)
        self.methods.append(str(request["method_name"]))
        return _Response(next(self.data))

    def persist_session_state_for_case(self, case: dict[str, object]) -> None:
        """模拟 GatewayApi：仅记录显式会话步骤完成后的持久化通知。"""

        request = case["request"]
        assert isinstance(request, dict)
        method_name = str(request["method_name"])
        if method_name in {"CreateAnonymousSession", "RefreshSession"}:
            self.persisted_session_methods.append(method_name)


def _assertions() -> dict[str, object]:
    return {
        "http_status": 200,
        "gateway": {"code": 0},
        "response": {"id": "req_0", "success": True, "code": 0},
    }


def _flow_case() -> dict[str, object]:
    definitions = {
        method: {
            "id": method,
            "name": method,
            "request": {"service_name": "dating.Service", "method_name": method},
        }
        for method in ("GetAnalysisTask", "GetAnalysisResult", "DeleteTaskData")
    }
    return {
        "id": "analysis",
        "api_definitions": definitions,
        "flow": {
            "steps": [
                {
                    "id": "poll",
                    "api": "GetAnalysisTask",
                    "until": {
                        "path": "$.status",
                        "equals": "succeeded",
                        "terminate_on": ["rejected", "failed"],
                        "interval_seconds": "{{analysis_poll_interval_seconds}}",
                        "timeout_seconds": "{{analysis_timeout_seconds}}",
                    },
                    "extract": {"analysis_status": "$.status"},
                },
                {
                    "id": "result",
                    "api": "GetAnalysisResult",
                    "skip_unless": {"variable": "analysis_status", "equals": "succeeded"},
                },
                {
                    "id": "cleanup",
                    "api": "DeleteTaskData",
                    "run_on_termination": True,
                },
            ]
        },
        "scenario": {
            "variables": {},
            "step_data": {
                "poll": {"params": {}, "assert": _assertions()},
                "result": {"params": {}, "assert": _assertions()},
                "cleanup": {"params": {}, "assert": _assertions()},
            },
        },
    }


def _runner(
    tmp_path: Path,
    gateway: _Gateway,
    *,
    sleep: Callable[[float], None] = lambda _: None,
    monotonic: Callable[[], float] = lambda: 0,
) -> FlowRunner:
    return FlowRunner(
        tmp_path,
        gateway_factory=lambda _: gateway,
        sleep=sleep,
        monotonic=monotonic,
        runtime_variables={
            "analysis_poll_interval_seconds": 1,
            "analysis_timeout_seconds": 2,
        },
    )


def test_success_reads_result_then_deletes_private_data(tmp_path: Path) -> None:
    """只有 succeeded 分支调用结果接口，随后始终删除私密任务数据。"""
    gateway = _Gateway([{"status": "succeeded"}, {"result": {}}, {"logical_deleted": True}])

    _runner(tmp_path, gateway).run(_flow_case())

    assert gateway.methods == ["GetAnalysisTask", "GetAnalysisResult", "DeleteTaskData"]


def test_failed_terminal_skips_result_but_deletes_private_data(tmp_path: Path) -> None:
    """failed/rejected 终态不得读取结果，但必须执行终止清理。"""
    gateway = _Gateway([{"status": "failed"}, {"logical_deleted": True}])

    _runner(tmp_path, gateway).run(_flow_case())

    assert gateway.methods == ["GetAnalysisTask", "DeleteTaskData"]


def test_poll_timeout_deletes_private_data_before_raising(tmp_path: Path) -> None:
    """轮询超时保留失败结论，但应先执行 DeleteTaskData 清理。"""
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    gateway = _Gateway(
        [
            {"status": "processing"},
            {"status": "processing"},
            {"status": "processing"},
            {"logical_deleted": True},
        ]
    )

    with pytest.raises(FlowExecutionError, match="轮询步骤 poll 超时"):
        _runner(tmp_path, gateway, sleep=sleep, monotonic=lambda: now[0]).run(
            _flow_case()
        )

    assert gateway.methods == [
        "GetAnalysisTask",
        "GetAnalysisTask",
        "GetAnalysisTask",
        "DeleteTaskData",
    ]


def test_gateway_assertion_failure_still_deletes_private_data(tmp_path: Path) -> None:
    """协议/业务断言失败也属于终止路径，不能绕过私密任务清理。"""

    flow_case = _flow_case()
    scenario = flow_case["scenario"]
    assert isinstance(scenario, dict)
    step_data = scenario["step_data"]
    assert isinstance(step_data, dict)
    poll = step_data["poll"]
    assert isinstance(poll, dict)
    assertions = poll["assert"]
    assert isinstance(assertions, dict)
    assertions["response"] = {"id": "req_0", "success": False, "code": 0}
    gateway = _Gateway(
        [{"status": "processing"}, {"logical_deleted": True}]
    )

    with pytest.raises(AssertionError, match="业务子响应字段 success"):
        _runner(tmp_path, gateway).run(flow_case)

    assert gateway.methods == ["GetAnalysisTask", "DeleteTaskData"]


def test_explicit_session_flow_steps_persist_after_response_extraction(
    tmp_path: Path,
) -> None:
    """Flow 中显式创建/刷新会话后也必须通知平台写回完整 Credential。"""

    definitions = {
        method: {
            "id": method,
            "name": method,
            "request": {
                "service_name": "tool.identity.IdentityService",
                "method_name": method,
            },
        }
        for method in ("CreateAnonymousSession", "RefreshSession")
    }
    flow_case = {
        "id": "session-refresh",
        "api_definitions": definitions,
        "flow": {
            "steps": [
                {
                    "id": "create",
                    "api": "CreateAnonymousSession",
                    "extract": {"access_token": "$.access_token"},
                },
                {
                    "id": "refresh",
                    "api": "RefreshSession",
                    "extract": {"access_token": "$.access_token"},
                },
            ]
        },
        "scenario": {
            "variables": {},
            "step_data": {
                "create": {"params": {}, "assert": _assertions()},
                "refresh": {"params": {}, "assert": _assertions()},
            },
        },
    }
    gateway = _Gateway(
        [{"access_token": "created-token"}, {"access_token": "refreshed-token"}]
    )

    _runner(tmp_path, gateway).run(flow_case)

    assert gateway.persisted_session_methods == [
        "CreateAnonymousSession",
        "RefreshSession",
    ]


def test_nested_data_type_assertions_reject_malformed_analysis_result() -> None:
    """Analysis 三个固定模块类型错误时必须失败，不能只检查字段存在。"""

    response = _Response(
        {
            "schema_version": "dating.relationship_analysis.v1",
            "result": {
                "overview": [],
                "chat_signals": {},
                "key_events": {},
            },
        }
    )

    with pytest.raises(AssertionError, match=r"result\.overview.*object"):
        assert_gateway_response(
            response,
            {
                **_assertions(),
                "data_types": {
                    "result": "object",
                    "result.overview": "object",
                    "result.chat_signals": "object",
                    "result.key_events": "object",
                },
            },
        )


def test_platform_missing_flow_fixture_fails_instead_of_skipping() -> None:
    """平台项目包缺少 fixture 属于发布错误，CLI/Jenkins 必须非零失败。"""

    from test_cases import test_gateway_flow as flow_test_module

    handler = getattr(flow_test_module, "_handle_flow_environment_error", None)
    assert handler is not None, "缺少平台/本地差异化的 Flow 环境错误处理"
    with pytest.raises(pytest.fail.Exception, match="平台项目运行资产不可用"):
        handler("platform", FlowEnvironmentError("fixture 不存在"))
