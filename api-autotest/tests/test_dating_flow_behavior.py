"""Dating Analysis 成功、失败和超时分支的结果读取与清理测试。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from utils.custom.assertions import assert_gateway_response
from utils.custom.flow_runner import FlowEnvironmentError, FlowExecutionError, FlowRunner
from utils.custom.flow_loader import load_flow_cases
from utils.custom.project_registry import ProjectRegistry
from utils.custom.runtime_context import RuntimeContext


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _Response:
    """提供 Gateway 分层断言需要的最小响应。"""

    status_code = 200

    def __init__(
        self,
        data: dict[str, object],
        *,
        success: bool = True,
        code: int = 0,
        message: str = "ok",
        business_error_code: str | None = None,
    ) -> None:
        self._data = data
        self._success = success
        self._code = code
        self._message = message
        self._business_error_code = business_error_code

    def json(self) -> dict[str, object]:
        child_response: dict[str, object] = {
            "id": "req_0",
            "success": self._success,
            "code": self._code,
            "message": self._message,
            "data": self._data,
        }
        if self._business_error_code:
            child_response["business_error_code"] = self._business_error_code
        return {
            "code": 0,
            "message": "ok",
            "responses": [child_response],
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


class _UploadResponse:
    """签名 PUT 响应替身。"""

    status_code = 200


class _MultiImageGateway:
    """按真实 Analysis/Reply Flow 方法名返回协议响应并记录执行顺序。"""

    def __init__(
        self,
        context,
        *,
        analysis_status: str = "succeeded",
        reply_status: str = "succeeded",
        preferences_complete: bool = True,
        reply_create_error: tuple[str, str] | None = None,
    ) -> None:
        self.context = context
        self.analysis_status = analysis_status
        self.reply_status = reply_status
        self.preferences_complete = preferences_complete
        self.reply_create_error = reply_create_error
        self.methods: list[str] = []
        self.params: list[tuple[str, dict[str, object]]] = []
        self.uploads: list[bytes] = []
        self.asset_index = 0
        self.settings = {"timeout": 5}
        self.http_client = self

    def put_bytes(self, **kwargs: object) -> _UploadResponse:
        """记录每次外部 PUT 的原始图片字节。"""

        content = kwargs["content"]
        assert isinstance(content, bytes)
        self.uploads.append(content)
        return _UploadResponse()

    def invoke(self, case: dict[str, object]) -> _Response:
        """解析当前 foreach 变量，模拟 Dating Gateway 成功或失败终态。"""

        request = case["request"]
        assert isinstance(request, dict)
        method = str(request["method_name"])
        variables = RuntimeContext(self.context.as_dict())
        variables.set("client_request_id", f"client-{len(self.methods) + 1}")
        resolved_params = variables.resolve(request.get("params") or {})
        assert isinstance(resolved_params, dict)
        self.methods.append(method)
        self.params.append((method, resolved_params))
        if method == "GetUserPreferences":
            data = {
                "preferences_complete": self.preferences_complete,
                "dating_goal": "relationship" if self.preferences_complete else "",
                "your_voice": "warm" if self.preferences_complete else "",
                "version": 3 if self.preferences_complete else 0,
                "update_time": 1787875200000 if self.preferences_complete else 0,
            }
        elif method == "UpdateUserPreferences":
            self.preferences_complete = True
            data = {
                "preferences_complete": True,
                "dating_goal": resolved_params["dating_goal"],
                "your_voice": resolved_params["your_voice"],
                "version": int(resolved_params["expected_version"]) + 1,
                "update_time": 1787875200000,
            }
        elif method == "GetMediaUploadConfig":
            data = {
                "config_version": "v1",
                "allowed_content_types": ["image/png"],
                "min_asset_count": 1,
                "max_asset_count": 9,
                "max_size_bytes": 7000000,
            }
        elif method == "PrepareMediaUpload":
            self.asset_index += 1
            size_bytes = int(resolved_params["size_bytes"])
            data = {
                "asset_id": f"asset-{self.asset_index}",
                "status": "prepared",
                "upload_url": f"https://upload.example/{self.asset_index}",
                "upload_method": "PUT",
                "required_headers": {
                    "Content-Type": "image/png",
                    "Content-Length": str(size_bytes),
                },
            }
        elif method == "CompleteMediaUpload":
            data = {
                "asset_id": resolved_params["asset_id"],
                "status": "uploaded",
                "uploaded_time": "2026-08-28T12:00:00Z",
            }
        elif method == "CreateAnalysisTask":
            data = {
                "task_id": "analysis-1",
                "task_type": "relationship_analysis",
                "status": "queued",
                "phase": "queued",
                "create_time": "2026-08-28T12:00:00Z",
                "expire_time": "2026-09-28T12:00:00Z",
            }
        elif method == "GetAnalysisTask":
            data = {
                "task_id": "analysis-1",
                "task_type": "relationship_analysis",
                "status": self.analysis_status,
                "phase": "completed",
                "retryable": False,
                "create_time": "2026-08-28T12:00:00Z",
                "expire_time": "2026-09-28T12:00:00Z",
            }
        elif method == "GetAnalysisResult":
            # 模拟当前真实接口正在演进的结果结构：Flow 只应依赖 message=ok，
            # 不得因为 next_steps 或信号字段改名而把成功业务请求判成失败。
            data = {
                "task_id": "analysis-1",
                "task_type": "relationship_analysis",
                "result_id": "result-1",
                "schema_version": "dating.relationship_analysis.v1",
                "result": {
                    "overview": {
                        "next_steps": {
                            "action": "wait",
                            "communication": "stay warm",
                            "observation": "watch follow-up",
                        },
                        "dashboard": {},
                    },
                    "chat_signals": {
                        "positive_signals": [],
                        "watch_signals": [],
                        "risk_signals": [],
                    },
                    "key_events": {
                        "turning_points": [],
                        "hidden_meanings": [],
                        "did_well": [],
                        "could_improve": [],
                    },
                },
                "create_time": "2026-08-28T12:00:00Z",
                "expire_time": "2026-09-28T12:00:00Z",
            }
        elif method == "CreateReplyTask":
            if self.reply_create_error:
                error_code, error_message = self.reply_create_error
                return _Response(
                    {},
                    success=False,
                    code=400,
                    message=error_message,
                    business_error_code=error_code,
                )
            data = {
                "task_id": "reply-1",
                "task_type": "reply_generation",
                "status": "queued",
                "phase": "queued",
            }
        elif method == "GetReplyTask":
            data = {
                "task_id": "reply-1",
                "task_type": "reply_generation",
                "status": self.reply_status,
                "phase": "done" if self.reply_status == "succeeded" else "failed",
            }
        elif method == "GetReplyResult":
            # Reply 结果同样视为开发中结构；只保留一个未知扩展字段，证明项目
            # Scenario 没有继续绑定 schema_version、roles 等易变业务字段。
            data = {
                "experimental_payload": {"revision": 2},
            }
        elif method == "GetTaskDebug":
            # Debug/Cost 属于 Evaluation Admin Gateway，但两个多图 Flow 复用同一
            # task_id 即可查询。测试替身回显该 ID，供 until 校验真实拓扑行为。
            data = {"task": {"task_id": resolved_params["task_id"]}}
        elif method == "GetProviderCostSummary":
            data = {"task_id": resolved_params["task_id"]}
        else:
            raise AssertionError(f"测试替身未声明方法响应: {method}")
        return _Response(data)


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


def _run_multi_image_analysis(
    tmp_path: Path,
    *,
    analysis_status: str = "succeeded",
) -> tuple[_MultiImageGateway, RuntimeContext, list[bytes]]:
    """用三张受控图片运行真实 Analysis Flow，并返回执行证据。"""

    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    flow_case = load_flow_cases(
        package.root,
        selected_flow="multi_image_analysis",
    )[0]
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    media_files = []
    expected_payloads = []
    for order in range(1, 4):
        payload = b"\x89PNG\r\n\x1a\n" + f"image-{order}".encode()
        expected_payloads.append(payload)
        relative_path = f"{order:03d}.png"
        (input_root / relative_path).write_bytes(payload)
        media_files.append(
            {
                "order": order,
                "original_name": f"chat_{order:02d}.png",
                "relative_path": relative_path,
                "content_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    holder: dict[str, _MultiImageGateway] = {}

    def gateway_factory(context):
        gateway = _MultiImageGateway(context, analysis_status=analysis_status)
        holder["gateway"] = gateway
        return gateway

    runtime = FlowRunner(
        package.root,
        gateway_factory=gateway_factory,
        runtime_variables={
            "media_files": media_files,
            "analysis_poll_interval_seconds": 1,
            "analysis_timeout_seconds": 3,
        },
        task_input_root=input_root,
        sleep=lambda _seconds: None,
    ).run(flow_case)

    return holder["gateway"], runtime, expected_payloads


def test_real_multi_image_flow_uploads_each_image_and_keeps_remote_task(
    tmp_path: Path,
) -> None:
    """真实项目资产必须按输入顺序多次上传，并一次提交全部 asset_ids。"""

    gateway, runtime, expected_payloads = _run_multi_image_analysis(tmp_path)

    assert gateway.uploads == expected_payloads
    assert gateway.methods == [
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "CreateAnalysisTask",
        "GetAnalysisTask",
        "GetAnalysisResult",
        "GetTaskDebug",
        "GetProviderCostSummary",
    ]
    create_params = next(params for method, params in gateway.params if method == "CreateAnalysisTask")
    assert create_params["asset_ids"] == ["asset-1", "asset-2", "asset-3"]
    assert next(
        params for method, params in gateway.params if method == "GetTaskDebug"
    ) == {"task_id": "analysis-1"}
    assert next(
        params
        for method, params in gateway.params
        if method == "GetProviderCostSummary"
    ) == {"task_id": "analysis-1"}
    assert runtime.get("task_id") == "analysis-1"
    assert "DeleteTaskData" not in gateway.methods


def test_analysis_failed_terminal_skips_result_and_runs_diagnostics(
    tmp_path: Path,
) -> None:
    """Analysis 业务失败时不查询 Result，但仍应保留 Debug/Cost 诊断链路。"""

    gateway, runtime, _ = _run_multi_image_analysis(
        tmp_path,
        analysis_status="failed",
    )

    assert gateway.methods[-3:] == [
        "GetAnalysisTask",
        "GetTaskDebug",
        "GetProviderCostSummary",
    ]
    assert "GetAnalysisResult" not in gateway.methods
    assert "DeleteTaskData" not in gateway.methods
    assert runtime.get("analysis_status") == "failed"


def _run_multi_image_reply(
    tmp_path: Path,
    *,
    preferences_complete: bool,
    reply_status: str = "succeeded",
    reply_create_error: tuple[str, str] | None = None,
    gateway_holder: dict[str, _MultiImageGateway] | None = None,
) -> _MultiImageGateway:
    """用两张受控图片运行真实 Reply Flow，返回仅替代外部网络的 Gateway。"""

    package = ProjectRegistry(PROJECT_ROOT / "projects").get("dating")
    flow_case = load_flow_cases(
        package.root,
        selected_flow="multi_image_reply",
    )[0]
    input_root = tmp_path / "reply-inputs"
    input_root.mkdir()
    media_files = []
    for order in range(1, 3):
        payload = b"\x89PNG\r\n\x1a\n" + f"reply-{order}".encode()
        relative_path = f"{order:03d}.png"
        (input_root / relative_path).write_bytes(payload)
        media_files.append(
            {
                "order": order,
                "original_name": f"reply_{order:02d}.png",
                "relative_path": relative_path,
                "content_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    holder = gateway_holder if gateway_holder is not None else {}

    def gateway_factory(context):
        gateway = _MultiImageGateway(
            context,
            preferences_complete=preferences_complete,
            reply_status=reply_status,
            reply_create_error=reply_create_error,
        )
        holder["gateway"] = gateway
        return gateway

    FlowRunner(
        package.root,
        gateway_factory=gateway_factory,
        runtime_variables={
            "media_files": media_files,
            "analysis_poll_interval_seconds": 1,
            "analysis_timeout_seconds": 3,
        },
        task_input_root=input_root,
        sleep=lambda _seconds: None,
    ).run(flow_case)
    return holder["gateway"]


def test_reply_flow_updates_incomplete_preferences_before_ordered_uploads(
    tmp_path: Path,
) -> None:
    """偏好不完整时只更新一次，然后按图片顺序上传并只创建一个 Reply。"""

    gateway = _run_multi_image_reply(tmp_path, preferences_complete=False)

    assert gateway.methods == [
        "GetUserPreferences",
        "UpdateUserPreferences",
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
        "CreateReplyTask",
        "GetReplyTask",
        "GetReplyResult",
        "GetTaskDebug",
        "GetProviderCostSummary",
    ]
    update_params = next(
        params for method, params in gateway.params if method == "UpdateUserPreferences"
    )
    assert update_params["dating_goal"] == "relationship"
    assert update_params["your_voice"] == "warm"
    assert update_params["expected_version"] == 0
    create_params = next(
        params for method, params in gateway.params if method == "CreateReplyTask"
    )
    assert create_params["asset_ids"] == ["asset-1", "asset-2"]
    assert create_params["locale"] == "en-US"
    assert next(
        params for method, params in gateway.params if method == "GetTaskDebug"
    ) == {"task_id": "reply-1"}
    assert next(
        params
        for method, params in gateway.params
        if method == "GetProviderCostSummary"
    ) == {"task_id": "reply-1"}
    assert "DeleteTaskData" not in gateway.methods


def test_reply_flow_skips_preference_update_when_already_complete(
    tmp_path: Path,
) -> None:
    """偏好已完整时不得覆盖用户现有选择。"""

    gateway = _run_multi_image_reply(tmp_path, preferences_complete=True)

    assert gateway.methods[0] == "GetUserPreferences"
    assert "UpdateUserPreferences" not in gateway.methods
    assert gateway.methods[-4:] == [
        "GetReplyTask",
        "GetReplyResult",
        "GetTaskDebug",
        "GetProviderCostSummary",
    ]


def test_reply_flow_failed_terminal_skips_result_and_runs_diagnostics(
    tmp_path: Path,
) -> None:
    """Reply 业务失败时不查询 Result，但仍应保留 Debug/Cost 诊断链路。"""

    holder: dict[str, _MultiImageGateway] = {}
    gateway = _run_multi_image_reply(
        tmp_path,
        preferences_complete=True,
        reply_status="failed",
        gateway_holder=holder,
    )

    assert gateway.methods[-3:] == [
        "GetReplyTask",
        "GetTaskDebug",
        "GetProviderCostSummary",
    ]
    assert "GetReplyResult" not in gateway.methods
    assert "DeleteTaskData" not in gateway.methods


def test_reply_flow_rejected_terminal_remains_fatal(tmp_path: Path) -> None:
    """rejected 仍代表 Flow 不可接受的业务终态，后续步骤不得继续。"""

    holder: dict[str, _MultiImageGateway] = {}
    with pytest.raises(FlowExecutionError, match=r"FLOW_TERMINATED.*'rejected'"):
        _run_multi_image_reply(
            tmp_path,
            preferences_complete=True,
            reply_status="rejected",
            gateway_holder=holder,
        )

    assert holder["gateway"].methods[-1] == "GetReplyTask"
    assert "GetReplyResult" not in holder["gateway"].methods
    assert "GetTaskDebug" not in holder["gateway"].methods
    assert "GetProviderCostSummary" not in holder["gateway"].methods


def test_reply_flow_surfaces_business_error_before_task_id_extraction(
    tmp_path: Path,
) -> None:
    """创建任务业务失败时应显示服务端原因，而不是误报 task_id 提取失败。"""

    with pytest.raises(
        FlowExecutionError,
        match=r"CreateReplyTask.*INPUT_INVALID.*requested_intent is unsupported",
    ) as caught:
        _run_multi_image_reply(
            tmp_path,
            preferences_complete=True,
            reply_create_error=("INPUT_INVALID", "requested_intent is unsupported"),
        )

    assert "提取路径不存在" not in str(caught.value)


def test_poll_retries_declared_transient_business_error_code(tmp_path: Path) -> None:
    """Debug/Cost 尚未落库时应等待重试，而不是在第一次业务失败时终止 Flow。"""

    class RetryGateway:
        """第一次返回未就绪业务码，第二次返回可供 until 匹配的数据。"""

        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, case: dict[str, object]) -> _Response:
            self.calls += 1
            if self.calls == 1:
                return _Response(
                    {},
                    success=False,
                    code=409,
                    message="debug data is not ready",
                    business_error_code="DEBUG_DATA_NOT_READY",
                )
            return _Response({"task": {"task_id": "dating_task_1"}})

    gateway = RetryGateway()
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    flow_case = {
        "id": "debug-retry",
        "api_definitions": {
            "GetTaskDebug": {
                "id": "GetTaskDebug",
                "name": "Get Task Debug",
                "request": {
                    "service_name": "tool.dating.internal.DatingEvaluationService",
                    "method_name": "GetTaskDebug",
                },
            }
        },
        "flow": {
            "steps": [
                {
                    "id": "get_debug",
                    "api": "GetTaskDebug",
                    "until": {
                        "path": "$.task.task_id",
                        "equals": "dating_task_1",
                        "retry_on_business_error_codes": ["DEBUG_DATA_NOT_READY"],
                        "interval_seconds": 2,
                        "timeout_seconds": 6,
                    },
                }
            ]
        },
        "scenario": {
            "variables": {},
            "step_data": {
                "get_debug": {
                    "params": {"task_id": "dating_task_1"},
                    "assert": {"http_status": 200, "gateway": {"message": "ok"}},
                }
            },
        },
    }

    FlowRunner(
        tmp_path,
        gateway_factory=lambda _: gateway,
        sleep=sleep,
        monotonic=lambda: now[0],
    ).run(flow_case)

    assert gateway.calls == 2
    assert now[0] == 2


def test_platform_missing_flow_fixture_fails_instead_of_skipping() -> None:
    """平台项目包缺少 fixture 属于发布错误，CLI/Jenkins 必须非零失败。"""

    from test_cases import test_gateway_flow as flow_test_module

    handler = getattr(flow_test_module, "_handle_flow_environment_error", None)
    assert handler is not None, "缺少平台/本地差异化的 Flow 环境错误处理"
    with pytest.raises(pytest.fail.Exception, match="平台项目运行资产不可用"):
        handler("platform", FlowEnvironmentError("fixture 不存在"))


def test_admin_flow_guard_uses_credential_profile_not_shared_api_id() -> None:
    """同名 API 不能让 Dating Evaluation 错误依赖 Truthy Admin 凭证。

    ``GetProviderCostSummary`` 同时存在于 Truthy Admin 与 Dating Evaluation。
    运行守卫必须读取当前执行快照内的逻辑 Profile，而不能按全局 API ID 猜测。
    """

    from test_cases import test_gateway_flow as flow_test_module

    requires_admin = getattr(
        flow_test_module,
        "_flow_requires_admin_credentials",
        None,
    )
    assert callable(requires_admin), "缺少按 API credential_profile 判定的 Admin 守卫"
    dating_flow = {
        "flow": {
            "steps": [
                {"id": "get_provider_cost", "api": "GetProviderCostSummary"}
            ]
        },
        "api_definitions": {
            "GetProviderCostSummary": {
                "id": "GetProviderCostSummary",
                "credential_profile": "public",
            }
        },
    }
    truthy_flow = {
        "flow": {
            "steps": [
                {"id": "get_provider_cost", "api": "GetProviderCostSummary"}
            ]
        },
        "api_definitions": {
            "GetProviderCostSummary": {
                "id": "GetProviderCostSummary",
                "credential_profile": "admin_session",
            }
        },
    }

    assert requires_admin(dating_flow) is False
    assert requires_admin(truthy_flow) is True


def test_task_input_manifest_loads_ordered_verified_media_files(tmp_path: Path) -> None:
    """执行入口必须校验 project/task/摘要，并保留 manifest 中的图片顺序。"""

    from test_cases.test_gateway_flow import _load_task_input_manifest

    input_root = tmp_path / "runtime/dating/20260828-120000-a1b2/inputs"
    input_root.mkdir(parents=True)
    files = []
    for order, payload in enumerate((b"first", b"second"), start=1):
        name = f"{order:03d}-image.png"
        (input_root / name).write_bytes(payload)
        files.append(
            {
                "order": order,
                "original_name": f"chat_{order:02d}.png",
                "relative_path": name,
                "content_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest_path = input_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "dating",
                "task_id": "20260828-120000-a1b2",
                "media_files": files,
            }
        ),
        encoding="utf-8",
    )

    variables, resolved_root = _load_task_input_manifest(
        manifest_path,
        project_id="dating",
        task_id="20260828-120000-a1b2",
    )

    assert [item["original_name"] for item in variables["media_files"]] == [
        "chat_01.png",
        "chat_02.png",
    ]
    assert resolved_root == input_root.resolve()


@pytest.mark.parametrize("failure", ["project", "task", "escape", "sha256"])
def test_task_input_manifest_fails_closed_on_identity_or_file_tampering(
    tmp_path: Path,
    failure: str,
) -> None:
    """输入清单身份、路径和摘要任一不可信时都不得启动 Gateway 请求。"""

    from test_cases.test_gateway_flow import _load_task_input_manifest

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    payload = b"image"
    (input_root / "001.png").write_bytes(payload)
    outside = tmp_path / "outside.png"
    outside.write_bytes(payload)
    document = {
        "schema_version": 1,
        "project_id": "dating",
        "task_id": "20260828-120000-a1b2",
        "media_files": [
            {
                "order": 1,
                "original_name": "chat.png",
                "relative_path": "001.png",
                "content_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    if failure == "project":
        document["project_id"] = "truthy"
    elif failure == "task":
        document["task_id"] = "20260828-120001-a1b3"
    elif failure == "escape":
        document["media_files"][0]["relative_path"] = "../outside.png"
    else:
        document["media_files"][0]["sha256"] = "0" * 64
    manifest_path = input_root / "manifest.json"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(FlowEnvironmentError, match="TASK_INPUTS_MISSING"):
        _load_task_input_manifest(
            manifest_path,
            project_id="dating",
            task_id="20260828-120000-a1b2",
        )


def test_default_flow_collection_skips_required_file_input_without_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 smoke/all 不应误跑交互 Flow；显式选择却缺文件时必须失败。"""

    from test_cases import test_gateway_flow as flow_test_module

    (tmp_path / "data").mkdir()
    flow_cases = [
        {"id": "regular", "flow": {"steps": []}},
        {
            "id": "destructive",
            "tags": ["explicit", "destructive", "isolated"],
            "flow": {"steps": []},
        },
        {
            "id": "interactive",
            "flow": {
                "inputs": {
                    "media_files": {"type": "files", "required": True}
                },
                "steps": [],
            },
        },
    ]

    def fake_load(_root: Path, selected_flow: str | None = None):
        if selected_flow:
            return [item for item in flow_cases if item["id"] == selected_flow]
        return flow_cases

    monkeypatch.setattr(flow_test_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(flow_test_module, "load_flow_cases", fake_load)
    monkeypatch.delenv("API_AUTOTEST_TASK_INPUT_MANIFEST_FILE", raising=False)

    assert [
        item["id"]
        for item in flow_test_module._load_selected_flow_cases(None, "dating")
    ] == ["regular"]
    with pytest.raises(FlowEnvironmentError, match="TASK_INPUTS_REQUIRED"):
        flow_test_module._load_selected_flow_cases("interactive", "dating")

    monkeypatch.setenv("API_AUTOTEST_TASK_INPUT_MANIFEST_FILE", "/task/inputs/manifest.json")
    assert [
        item["id"]
        for item in flow_test_module._load_selected_flow_cases(None, "dating")
    ] == ["regular", "interactive"]
    assert flow_test_module._load_selected_flow_cases(
        "destructive",
        "dating",
    )[0]["id"] == "destructive"


def test_flow_runner_forwards_one_stable_comm_id_for_all_steps() -> None:
    """同一 Flow 的幂等键应进入逐步骤 comm，不能污染业务 params。"""

    captured: list[str] = []

    class Gateway:
        def __init__(self, context: RuntimeContext) -> None:
            self.context = context

        def invoke(self, case: dict[str, object]) -> _Response:
            request = case["request"]
            comm = case.get("comm")
            assert isinstance(request, dict)
            assert isinstance(comm, dict)
            resolved_comm = self.context.resolve(comm)
            captured.append(str(resolved_comm["client_request_id"]))
            assert "client_request_id" not in (request.get("params") or {})
            return _Response({"task_id": "task-1"})

    api_definition = {
        "id": "CreateDemo",
        "name": "创建演示任务",
        "credential_profile": "anonymous_session",
        "request": {
            "service_name": "example.DemoService",
            "method_name": "CreateDemo",
        },
    }
    flow_case = {
        "id": "stable_run_id",
        "name": "stable_run_id",
        "flow": {
            "steps": [
                {"id": "first", "api": "CreateDemo"},
                {"id": "second", "api": "CreateDemo"},
            ]
        },
        "scenario": {
            "step_data": {
                step_id: {
                    "comm": {"client_request_id": "{{flow_run_id}}-analysis"},
                    "params": {},
                    "assert": {"http_status": 200, "gateway": {"message": "ok"}},
                }
                for step_id in ("first", "second")
            }
        },
        "api_definitions": {"CreateDemo": api_definition},
    }

    FlowRunner(
        PROJECT_ROOT / "projects/dating",
        gateway_factory=Gateway,
    ).run(flow_case)

    assert len(captured) == 2
    assert captured[0] == captured[1]
    assert captured[0].startswith("flow_")
    assert captured[0].endswith("-analysis")


def test_flow_data_not_equals_rejects_reused_deleted_user_id() -> None:
    """注销后若服务端错误复活旧 user_id，删除账号 Flow 必须失败。"""

    flow_case = {
        "id": "account_recreated",
        "name": "account_recreated",
        "flow": {
            "steps": [{"id": "create_again", "api": "CreateAnonymousSession"}]
        },
        "scenario": {
            "step_data": {
                "create_again": {
                    "params": {},
                    "assert": {
                        "http_status": 200,
                        "gateway": {"message": "ok"},
                        "data_not_equals": {"user_id": "deleted-user"},
                    },
                }
            }
        },
        "api_definitions": {
            "CreateAnonymousSession": {
                "id": "CreateAnonymousSession",
                "name": "创建匿名会话",
                "credential_profile": "public",
                "request": {
                    "service_name": "tool.identity.IdentityService",
                    "method_name": "CreateAnonymousSession",
                },
            }
        },
    }

    with pytest.raises(AssertionError, match="不应等于"):
        FlowRunner(
            PROJECT_ROOT / "projects/dating",
            gateway_factory=lambda _context: _Gateway(
                [{"user_id": "deleted-user"}]
            ),
        ).run(flow_case)


def test_isolated_flow_session_policy_uses_task_device_and_no_shared_session() -> None:
    """破坏性 Flow 必须隔离 device/token，避免注销平台共享测试账号。"""

    from test_cases import test_gateway_flow as flow_test_module

    configure = getattr(flow_test_module, "_configure_flow_session", None)
    derive_settings = getattr(flow_test_module, "_isolated_gateway_settings", None)
    assert callable(configure), "缺少 isolated Flow 会话隔离入口"
    assert callable(derive_settings), "缺少 isolated Flow device 派生入口"

    flow_case = {
        "id": "delete_account_contract",
        "tags": ["explicit", "destructive", "isolated"],
    }
    flow_context = RuntimeContext(
        {
            "flow_run_id": "20260829-120000-abcd",
            "access_token": "must-be-removed",
            "refresh_token": "must-be-removed",
            "user_id": "must-be-removed",
        }
    )
    framework_context = RuntimeContext(
        {
            "access_token": "shared-token",
            "refresh_token": "shared-refresh",
            "user_id": "shared-user",
        }
    )

    is_isolated = configure(flow_case, flow_context, framework_context)
    settings = derive_settings(
        {"comm": {"device_id": "dating-test", "platform": "ios"}},
        flow_context,
    )

    assert is_isolated is True
    assert flow_context.get("access_token") is None
    assert flow_context.get("refresh_token") is None
    assert flow_context.get("user_id") is None
    assert settings["comm"]["device_id"] == (
        "dating-test-isolated-20260829-120000-abcd"
    )
    assert settings["comm"]["platform"] == "ios"
