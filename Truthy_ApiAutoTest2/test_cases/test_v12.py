"""V1.2 文件日志与通用 Flow 能力测试。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from utils.custom.assertions import assert_gateway_response
from utils.custom.http_client import HttpClient
from utils.custom.logger import configure_logging, get_logger
from runtest import build_pytest_args


class JsonResponse:
    """提供 HTTP 客户端测试所需的最小 JSON 响应。"""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        """返回初始化时传入的响应体。"""
        return self._body


def _gateway_response(data: dict) -> JsonResponse:
    """构造包含一个 req_0 成功子响应的标准 Gateway 响应。"""
    return JsonResponse(
        200,
        {
            "code": 0,
            "message": "ok",
            "responses": [
                {
                    "id": "req_0",
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "data": data,
                }
            ],
        },
    )


def test_configure_logging_creates_one_utf8_file(tmp_path: Path) -> None:
    """日志初始化应在当天目录创建唯一 UTF-8 日志文件并写入中文。"""
    log_path = configure_logging(
        log_directory=tmp_path,
        env="test",
        console=False,
        file=True,
        now=datetime(2026, 7, 27, 10, 30, 0),
    )
    get_logger("v12.file").info("中文日志")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_path is not None
    assert log_path.parent == tmp_path / "2026-07-27"
    assert "中文日志" in log_path.read_text(encoding="utf-8")


def test_configure_logging_cleans_only_expired_date_directories(
    tmp_path: Path,
) -> None:
    """首次创建当天目录时，只删除超过 7 天的合法日期日志目录。"""
    expired_directory = tmp_path / "2026-07-19"
    boundary_directory = tmp_path / "2026-07-20"
    recent_directory = tmp_path / "2026-07-26"
    non_date_directory = tmp_path / "manual_backup"
    for directory in (
        expired_directory,
        boundary_directory,
        recent_directory,
        non_date_directory,
    ):
        directory.mkdir(parents=True)
        (directory / "run.log").write_text("历史日志", encoding="utf-8")

    log_path = configure_logging(
        log_directory=tmp_path,
        env="test",
        console=False,
        file=True,
        now=datetime(2026, 7, 27, 10, 30, 0),
    )

    assert log_path is not None
    assert not expired_directory.exists()
    assert boundary_directory.is_dir()
    assert recent_directory.is_dir()
    assert non_date_directory.is_dir()
    assert (tmp_path / "2026-07-27").is_dir()


def test_configure_logging_does_not_repeat_cleanup_in_existing_daily_directory(
    tmp_path: Path,
) -> None:
    """当天目录已存在时不重复清理，避免运行中误删新增的历史归档目录。"""
    (tmp_path / "2026-07-27").mkdir()
    expired_directory = tmp_path / "2026-07-19"
    expired_directory.mkdir()

    configure_logging(
        log_directory=tmp_path,
        env="test",
        console=False,
        file=True,
        now=datetime(2026, 7, 27, 10, 30, 0),
    )

    assert expired_directory.is_dir()


def test_http_client_logs_elapsed_time(caplog: pytest.LogCaptureFixture) -> None:
    """成功请求日志应包含可定位性能问题的耗时字段。"""

    class SuccessfulSession:
        """返回成功响应的 requests.Session 替身。"""

        def post(self, *args: object, **kwargs: object) -> JsonResponse:
            return JsonResponse(200, {"code": 0, "message": "ok"})

    with caplog.at_level(logging.INFO):
        HttpClient(session=SuccessfulSession()).post_json(
            "http://example.test/gateway/invoke",
            {},
            {},
            1,
        )

    assert "elapsed_ms" in caplog.text


def test_file_log_masks_tokens_and_signed_url(tmp_path: Path) -> None:
    """文件日志不得泄露请求/响应 token 或预签名 URL 查询参数。"""

    class SecureSession:
        """同时提供 POST 与 PUT 的成功响应。"""

        def post(self, *args: object, **kwargs: object) -> JsonResponse:
            return JsonResponse(
                200,
                {
                    "access_token": "response-access-secret",
                    "upload_url": "https://upload.example/file?q-signature=response-signed-secret",
                    "code": 0,
                },
            )

        def put(self, *args: object, **kwargs: object) -> JsonResponse:
            return JsonResponse(200, {})

    log_path = configure_logging(
        log_directory=tmp_path,
        env="test",
        console=False,
        file=True,
    )
    client = HttpClient(session=SecureSession())
    client.post_json(
        "http://example.test/gateway/invoke",
        {"Authorization": "header-secret"},
        {"comm": {"auth_token": "request-token-secret"}},
        1,
    )
    client.put_bytes(
        "https://upload.example/file?q-signature=signed-secret",
        {},
        b"abc",
        1,
    )
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_path is not None
    content = log_path.read_text(encoding="utf-8")

    assert "request-token-secret" not in content
    assert "header-secret" not in content
    assert "response-access-secret" not in content
    assert "signed-secret" not in content
    assert "response-signed-secret" not in content
    assert "***" in content


def test_data_fields_accepts_empty_values() -> None:
    """data_fields 表示字段存在，合法空字符串、0、false 和空列表应通过。"""
    response = JsonResponse(
        200,
        {
            "code": 0,
            "responses": [
                {
                    "id": "req_0",
                    "success": True,
                    "code": 0,
                    "data": {
                        "empty_text": "",
                        "zero": 0,
                        "disabled": False,
                        "items": [],
                    },
                }
            ],
        },
    )

    data = assert_gateway_response(
        response,
        {
            "http_status": 200,
            "gateway": {"code": 0},
            "response": {"id": "req_0", "success": True, "code": 0},
            "data_fields": ["empty_text", "zero", "disabled", "items"],
        },
    )

    assert data["empty_text"] == ""


def test_data_equals_reads_nested_paths() -> None:
    """场景值断言应支持对象字段和数组索引路径。"""
    from utils.custom.assertions import assert_data_equals

    assert_data_equals(
        {
            "status": "SUCCEEDED",
            "progress": {"stage": "report_ready"},
            "items": [{"candidate_id": "candidate_1"}],
        },
        {
            "status": "SUCCEEDED",
            "progress.stage": "report_ready",
            "items[0].candidate_id": "candidate_1",
        },
    )


def _write_flow_fixture(root: Path, flow: dict, scenario: dict) -> None:
    """为 FlowLoader 测试创建最小 API、Flow 和 Scenario 文件。"""
    for directory in ("apis", "flows", "scenarios"):
        (root / "data" / directory).mkdir(parents=True, exist_ok=True)
    (root / "data" / "apis" / "Demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "Demo",
                "name": "示例接口",
                "request": {
                    "service_name": "service.Demo",
                    "method_name": "Demo",
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (root / "data" / "flows" / "Demo.yaml").write_text(
        yaml.safe_dump(flow, allow_unicode=True),
        encoding="utf-8",
    )
    (root / "data" / "scenarios" / "Demo.yaml").write_text(
        yaml.safe_dump(scenario, allow_unicode=True),
        encoding="utf-8",
    )


def test_flow_loader_pairs_same_name_files(tmp_path: Path) -> None:
    """同名 Flow 与 Scenario 应组成一条可参数化的流程用例。"""
    from utils.custom.flow_loader import load_flow_cases

    _write_flow_fixture(
        tmp_path,
        {
            "name": "示例流程",
            "tags": ["flow", "smoke"],
            "steps": [{"id": "demo", "api": "Demo"}],
        },
        {
            "name": "成功场景",
            "variables": {},
            "step_data": {
                "demo": {
                    "params": {},
                    "assert": {},
                }
            },
        },
    )

    flow_cases = load_flow_cases(tmp_path)

    assert len(flow_cases) == 1
    assert flow_cases[0]["id"] == "Demo"
    assert flow_cases[0]["name"] == "示例流程"
    assert flow_cases[0]["scenario"]["name"] == "成功场景"
    assert list(flow_cases[0]["api_definitions"]) == ["Demo"]


def test_flow_loader_rejects_duplicate_step_ids(tmp_path: Path) -> None:
    """重复 step ID 应在发请求前被配置校验拒绝。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_flow_fixture(
        tmp_path,
        {
            "name": "重复步骤流程",
            "steps": [
                {"id": "demo", "api": "Demo"},
                {"id": "demo", "wait": {"seconds": 1}},
            ],
        },
        {"name": "场景", "step_data": {}},
    )

    with pytest.raises(FlowConfigError, match="重复.*demo"):
        load_flow_cases(tmp_path)


def test_flow_loader_rejects_unknown_scenario_step(tmp_path: Path) -> None:
    """Scenario 不得为 Flow 中不存在的步骤配置数据。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_flow_fixture(
        tmp_path,
        {"name": "示例流程", "steps": [{"id": "demo", "api": "Demo"}]},
        {"name": "场景", "step_data": {"missing": {"params": {}}}},
    )

    with pytest.raises(FlowConfigError, match="missing"):
        load_flow_cases(tmp_path)


def test_flow_loader_rejects_orphan_scenario(tmp_path: Path) -> None:
    """没有同名 Flow 的 Scenario 应在收集阶段被拒绝。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_flow_fixture(
        tmp_path,
        {"name": "示例流程", "steps": [{"id": "demo", "api": "Demo"}]},
        {"name": "场景", "step_data": {}},
    )
    (tmp_path / "data" / "scenarios" / "Orphan.yaml").write_text(
        "name: 孤立场景\nstep_data: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(FlowConfigError, match="Orphan"):
        load_flow_cases(tmp_path)


def test_flow_loader_rejects_invalid_extract_path(tmp_path: Path) -> None:
    """非法 extract 路径应在发送请求前被拒绝。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_flow_fixture(
        tmp_path,
        {
            "name": "示例流程",
            "steps": [
                {
                    "id": "demo",
                    "api": "Demo",
                    "extract": {"task_id": "data.task_id"},
                }
            ],
        },
        {"name": "场景", "step_data": {}},
    )

    with pytest.raises(FlowConfigError, match="extract"):
        load_flow_cases(tmp_path)


def test_flow_loader_rejects_unknown_action(tmp_path: Path) -> None:
    """V1.2 未注册的特殊动作应在配置校验阶段失败。"""
    from utils.custom.flow_loader import FlowConfigError, load_flow_cases

    _write_flow_fixture(
        tmp_path,
        {"name": "示例流程", "steps": [{"id": "action", "action": "unknown"}]},
        {"name": "场景", "step_data": {}},
    )

    with pytest.raises(FlowConfigError, match="unknown"):
        load_flow_cases(tmp_path)


def _runner_api_definitions() -> dict[str, dict]:
    """返回 FlowRunner 测试使用的内存 API 定义，不创建 case 文件。"""
    return {
        "Demo": {
            "id": "Demo",
            "name": "示例接口",
            "request": {
                "service_name": "service.Demo",
                "method_name": "Demo",
            },
            "_source": "data/apis/Demo.yaml",
        },
        "Detail": {
            "id": "Detail",
            "name": "详情接口",
            "request": {
                "service_name": "service.Detail",
                "method_name": "Detail",
            },
            "_source": "data/apis/Detail.yaml",
        },
    }


def _runner_success_assertions(
    data_equals: dict | None = None,
) -> dict:
    """返回 FlowRunner 测试使用的完整成功断言。"""
    assertions = {
        "http_status": 200,
        "gateway": {"code": 0, "message": "ok"},
        "response": {
            "id": "req_0",
            "success": True,
            "code": 0,
            "message": "ok",
        },
    }
    if data_equals is not None:
        assertions["data_equals"] = data_equals
    return assertions


class QueueGateway:
    """按顺序返回响应并记录 case 的 GatewayApi 测试替身。"""

    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.settings = {"timeout": 15}
        self.http_client = None

    def invoke(self, case: dict) -> JsonResponse:
        """记录合并后的 case 并返回下一个响应。"""
        self.calls.append(case)
        return self.responses.pop(0)


def test_flow_runner_uses_complete_scenario_data_and_extracts_value(
    tmp_path: Path,
) -> None:
    """FlowRunner 应使用完整场景数据，不读取或合并任何 case 默认值。"""
    from utils.custom.flow_runner import FlowRunner

    gateway = QueueGateway([_gateway_response({"task_id": "task_1", "status": "QUEUED"})])
    flow_case = {
        "id": "DemoFlow",
        "name": "示例流程",
        "api_definitions": _runner_api_definitions(),
        "flow": {
            "steps": [
                {
                    "id": "demo",
                    "api": "Demo",
                    "extract": {"task_id": "$.task_id"},
                }
            ]
        },
        "scenario": {
            "name": "成功场景",
            "variables": {
                "seed": "seed_1",
                "expected_status": "QUEUED",
                "expected_message": "ok",
            },
            "step_data": {
                "demo": {
                    "params": {"nested": {"b": 3}, "seed": "{{seed}}"},
                    "assert": {
                        "http_status": 200,
                        "gateway": {
                            "code": 0,
                            "message": "{{expected_message}}",
                        },
                        "response": {
                            "id": "req_0",
                            "success": True,
                            "code": 0,
                            "message": "{{expected_message}}",
                        },
                        "data_equals": {
                            "status": "{{expected_status}}",
                        },
                    },
                }
            },
        },
    }

    context = FlowRunner(
        tmp_path,
        gateway_factory=lambda runtime: gateway,
    ).run(flow_case)

    # FlowRunner 保留请求占位符，真实 GatewayApi 在生成请求 ID 后统一解析。
    assert gateway.calls[0]["request"]["params"] == {
        "nested": {"b": 3},
        "seed": "{{seed}}",
    }
    assert gateway.calls[0]["request"]["service_name"] == "service.Demo"
    assert gateway.calls[0]["request"]["method_name"] == "Demo"
    assert gateway.calls[0]["assert"]["gateway"]["message"] == "ok"
    assert gateway.calls[0]["assert"]["data_equals"]["status"] == "QUEUED"
    assert context.get("task_id") == "task_1"
    assert not (tmp_path / "data" / "cases").exists()


def test_flow_runner_keeps_later_api_variable_for_gateway_resolution(
    tmp_path: Path,
) -> None:
    """前序提取变量应保留到 Gateway 构造请求时解析，场景断言仍提前解析。"""
    from utils.custom.flow_runner import FlowRunner

    gateway = QueueGateway(
        [
            _gateway_response({"task_id": "task_1"}),
            _gateway_response({"task_id": "task_1", "detail": "ready"}),
        ]
    )
    flow_case = {
        "id": "TwoStepFlow",
        "name": "两步流程",
        "api_definitions": _runner_api_definitions(),
        "flow": {
            "steps": [
                {
                    "id": "create",
                    "api": "Demo",
                    "extract": {"task_id": "$.task_id"},
                },
                {
                    "id": "detail",
                    "api": "Detail",
                },
            ]
        },
        "scenario": {
            "name": "变量传递场景",
            "variables": {},
            "step_data": {
                "create": {
                    "params": {"input": "value"},
                    "assert": _runner_success_assertions(),
                },
                "detail": {
                    "params": {"task_id": "{{task_id}}"},
                    "assert": _runner_success_assertions(
                        {"task_id": "{{task_id}}"}
                    ),
                },
            },
        },
    }

    context = FlowRunner(
        tmp_path,
        gateway_factory=lambda runtime: gateway,
    ).run(flow_case)

    assert gateway.calls[1]["request"] == {
        "service_name": "service.Detail",
        "method_name": "Detail",
        "params": {"task_id": "{{task_id}}"},
    }
    assert gateway.calls[1]["assert"]["data_equals"] == {"task_id": "task_1"}
    assert context.get("task_id") == "task_1"


def test_flow_runner_keeps_contexts_isolated(tmp_path: Path) -> None:
    """同一个 Runner 连续运行两条 Flow 时不得共享业务变量。"""
    from utils.custom.flow_runner import FlowRunner

    runner = FlowRunner(tmp_path, gateway_factory=lambda runtime: QueueGateway([]))
    flow_case = {
        "id": "WaitFlow",
        "name": "等待流程",
        "api_definitions": {},
        "flow": {"steps": [{"id": "wait", "wait": {"seconds": 0}}]},
        "scenario": {"name": "场景", "variables": {}, "step_data": {}},
    }

    first = runner.run(flow_case)
    first.set("task_id", "task_1")
    second = runner.run(flow_case)

    assert second.get("task_id") is None


def test_flow_runner_executes_fixed_wait_without_real_sleep(tmp_path: Path) -> None:
    """固定等待应调用注入的 sleep，单元测试不真实阻塞。"""
    from utils.custom.flow_runner import FlowRunner

    sleeps: list[float] = []
    flow_case = {
        "id": "WaitFlow",
        "name": "等待流程",
        "api_definitions": {},
        "flow": {"steps": [{"id": "wait", "wait": {"seconds": 1.5}}]},
        "scenario": {"name": "场景", "variables": {}, "step_data": {}},
    }

    FlowRunner(
        tmp_path,
        gateway_factory=lambda runtime: QueueGateway([]),
        sleep=lambda seconds: sleeps.append(seconds),
    ).run(flow_case)

    assert sleeps == [1.5]


def test_flow_runner_polls_until_value_matches(tmp_path: Path) -> None:
    """轮询应在响应路径等于期望值后停止。"""
    from utils.custom.flow_runner import FlowRunner

    gateway = QueueGateway(
        [
            _gateway_response({"status": "RUNNING"}),
            _gateway_response({"status": "SUCCEEDED"}),
        ]
    )
    now = [0.0]
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    flow_case = {
        "id": "PollFlow",
        "name": "轮询流程",
        "api_definitions": _runner_api_definitions(),
        "flow": {
            "steps": [
                {
                    "id": "poll",
                    "api": "Demo",
                    "until": {
                        "path": "$.status",
                        "equals": "SUCCEEDED",
                        "interval_seconds": 1,
                        "timeout_seconds": 3,
                    },
                }
            ]
        },
        "scenario": {
            "name": "场景",
            "variables": {},
            "step_data": {
                "poll": {
                    "params": {},
                    "assert": _runner_success_assertions(),
                }
            },
        },
    }

    FlowRunner(
        tmp_path,
        gateway_factory=lambda runtime: gateway,
        sleep=fake_sleep,
        monotonic=lambda: now[0],
    ).run(flow_case)

    assert len(gateway.calls) == 2
    assert sleeps == [1.0]


def test_flow_runner_reports_poll_timeout(tmp_path: Path) -> None:
    """轮询超时错误应包含步骤、最后实际值和调用次数。"""
    from utils.custom.flow_runner import FlowExecutionError, FlowRunner

    gateway = QueueGateway(
        [_gateway_response({"status": "RUNNING"}) for _ in range(3)]
    )
    now = [0.0]

    def fake_sleep(seconds: float) -> None:
        now[0] += seconds

    flow_case = {
        "id": "PollFlow",
        "name": "轮询流程",
        "api_definitions": _runner_api_definitions(),
        "flow": {
            "steps": [
                {
                    "id": "poll",
                    "api": "Demo",
                    "until": {
                        "path": "$.status",
                        "equals": "SUCCEEDED",
                        "interval_seconds": 1,
                        "timeout_seconds": 2,
                    },
                }
            ]
        },
        "scenario": {
            "name": "场景",
            "variables": {},
            "step_data": {
                "poll": {
                    "params": {},
                    "assert": _runner_success_assertions(),
                }
            },
        },
    }

    with pytest.raises(FlowExecutionError, match="poll.*RUNNING.*3"):
        FlowRunner(
            tmp_path,
            gateway_factory=lambda runtime: gateway,
            sleep=fake_sleep,
            monotonic=lambda: now[0],
        ).run(flow_case)


def test_flow_runner_uploads_prepared_media(tmp_path: Path) -> None:
    """prepared_media_upload 应使用上下文中的 URL、请求头和文件字节。"""
    from utils.custom.flow_runner import FlowRunner

    media_path = tmp_path / "photo.jpg"
    media_path.write_bytes(b"abc")

    class PutClient:
        """记录 COS PUT 参数的 HTTP 客户端替身。"""

        def __init__(self) -> None:
            self.call: dict | None = None

        def put_bytes(self, **kwargs: object) -> JsonResponse:
            self.call = kwargs
            return JsonResponse(200, {})

    gateway = QueueGateway([])
    gateway.http_client = PutClient()
    flow_case = {
        "id": "UploadFlow",
        "name": "上传流程",
        "api_definitions": {},
        "flow": {
            "steps": [
                {"id": "upload", "action": "prepared_media_upload"},
            ]
        },
        "scenario": {
            "name": "上传场景",
            "variables": {
                "media_file": str(media_path),
                "upload_url": "https://upload.example/file",
                "upload_headers": {"Content-Length": "3", "Content-Type": "image/jpeg"},
            },
            "step_data": {},
        },
    }

    context = FlowRunner(
        tmp_path,
        gateway_factory=lambda runtime: gateway,
    ).run(flow_case)

    assert gateway.http_client.call["content"] == b"abc"
    assert context.get("media_size_bytes") == 3


def test_build_pytest_args_supports_flow_filter() -> None:
    """统一入口指定 Flow 时应只运行 Flow 测试入口。"""
    args = build_pytest_args(env="test", flow="Demo")

    assert args[0] == "test_cases/test_gateway_flow.py"
    assert "--flow=Demo" in args
