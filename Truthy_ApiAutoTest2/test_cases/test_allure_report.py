"""Allure 观察层的元数据、步骤与安全附件测试。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests


def test_single_metadata_maps_all_fields_and_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单接口元数据必须完整映射，且保留 YAML 中的全部标签。"""
    from utils.third_party import allure_reporter

    calls: list[tuple[str, Any]] = []
    dynamic = SimpleNamespace(
        title=lambda value: calls.append(("title", value)),
        parent_suite=lambda value: calls.append(("parent_suite", value)),
        suite=lambda value: calls.append(("suite", value)),
        feature=lambda value: calls.append(("feature", value)),
        story=lambda value: calls.append(("story", value)),
        tag=lambda value: calls.append(("tag", value)),
    )
    monkeypatch.setattr(allure_reporter.allure, "dynamic", dynamic)

    allure_reporter.set_single_case_metadata(
        {
            "name": "获取当前用户",
            "api_id": "GetMe",
            "case_id": "get_me_success",
            "tags": ["smoke", "user"],
        }
    )

    assert calls == [
        ("title", "获取当前用户"),
        ("parent_suite", "Gateway API 自动化"),
        ("suite", "单接口测试"),
        ("feature", "GetMe"),
        ("story", "get_me_success"),
        ("tag", "smoke"),
        ("tag", "user"),
    ]


@pytest.mark.parametrize(
    ("flow_case", "expected_title"),
    [
        (
            {
                "id": "FlowId",
                "name": "Flow 名称",
                "scenario": {"name": "Scenario 名称"},
            },
            "Scenario 名称",
        ),
        ({"id": "FlowId", "name": "Flow 名称", "scenario": {}}, "Flow 名称"),
        ({"id": "FlowId", "scenario": {}}, "FlowId"),
    ],
)
def test_flow_metadata_uses_fixed_title_priority(
    monkeypatch: pytest.MonkeyPatch,
    flow_case: dict[str, Any],
    expected_title: str,
) -> None:
    """Flow 标题按 Scenario、Flow 名称和 Flow ID 的顺序降级。"""
    from utils.third_party import allure_reporter

    calls: list[tuple[str, Any]] = []
    dynamic = SimpleNamespace(
        title=lambda value: calls.append(("title", value)),
        suite=lambda value: calls.append(("suite", value)),
        feature=lambda value: calls.append(("feature", value)),
        tag=lambda value: calls.append(("tag", value)),
    )
    monkeypatch.setattr(allure_reporter.allure, "dynamic", dynamic)
    flow_case["tags"] = ["flow", "smoke"]

    allure_reporter.set_flow_metadata(flow_case)

    assert calls == [
        ("title", expected_title),
        ("suite", "多接口流程"),
        ("feature", "FlowId"),
        ("tag", "flow"),
        ("tag", "smoke"),
    ]


def test_runtime_metadata_contains_only_safe_scope_and_release_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JUnit/Allure 只记录可追溯身份，不得把 settings/Secret 值写进报告。"""
    from utils.third_party import allure_reporter

    calls: list[tuple[str, str]] = []
    dynamic = SimpleNamespace(
        parameter=lambda name, value: calls.append((name, value)),
    )
    monkeypatch.setattr(allure_reporter.allure, "dynamic", dynamic)

    metadata = allure_reporter.build_runtime_report_metadata(
        project_id="dating",
        target_env="test",
        config_source="platform",
        settings={
            "gateway_base_url": "https://must-not-appear.example",
            "runtime_variables": {"AUTH_TOKEN": "must-not-appear"},
            "runtime_metadata": {
                "task_id": "20260827-120000-a1b2",
                "platform_environment": "dev",
                "runtime_scope_id": "scope-dating-test",
                "config_release_id": "release-dating-v3",
                "config_release_version": 3,
                "credential_profiles": [
                    {"id": "anonymous_session", "secret": "must-not-appear"}
                ],
            },
        },
    )
    allure_reporter.set_runtime_report_metadata(metadata)

    assert metadata == {
        "project_id": "dating",
        "target_env": "test",
        "config_source": "platform",
        "task_id": "20260827-120000-a1b2",
        "platform_environment": "dev",
        "runtime_scope_id": "scope-dating-test",
        "config_release_id": "release-dating-v3",
        "config_release_version": "3",
    }
    assert calls == list(metadata.items())
    assert "must-not-appear" not in json.dumps(metadata)


def test_attachments_use_declared_types_and_json_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON 和文本附件必须使用固定类型及中文友好的 JSON 格式。"""
    from utils.third_party import allure_reporter

    calls: list[tuple[str, str, Any]] = []
    attachment_type = SimpleNamespace(JSON="json-type", TEXT="text-type")
    monkeypatch.setattr(allure_reporter.allure, "attachment_type", attachment_type)
    monkeypatch.setattr(
        allure_reporter.allure,
        "attach",
        lambda body, name, attachment_type: calls.append(
            (name, body, attachment_type)
        ),
    )

    allure_reporter.attach_json("请求", {"中文": object()})
    allure_reporter.attach_text("说明", 123)

    assert calls[0][0] == "请求"
    assert calls[0][2] == "json-type"
    assert calls[0][1].startswith('{\n  "中文": "')
    assert calls[0][1].endswith('"\n}')
    assert "\\u4e2d" not in calls[0][1]
    assert calls[1] == ("说明", "123", "text-type")


def test_reporter_failure_is_best_effort_and_logs_raw_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reporter 写入失败不得影响测试，异常日志保留原始异常内容。"""
    from utils.third_party import allure_reporter

    secret = "very-secret-token"

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(allure_reporter.allure, "attach", fail)
    allure_reporter.attach_json("请求", {"access_token": secret})

    assert "RuntimeError" in caplog.text
    assert secret in caplog.text


def test_step_passes_title_and_preserves_business_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """步骤标题必须透传，且业务异常不能被 Reporter 吞掉或替换。"""
    from utils.third_party import allure_reporter

    titles: list[str] = []

    @contextmanager
    def fake_step(title: str):
        titles.append(title)
        yield

    monkeypatch.setattr(allure_reporter.allure, "step", fake_step)
    business_error = ValueError("business")

    with pytest.raises(ValueError) as caught:
        with allure_reporter.step("执行接口：GetMe"):
            raise business_error

    assert caught.value is business_error
    assert titles == ["执行接口：GetMe"]


def test_step_creation_failure_falls_back_to_empty_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allure 步骤无法创建时仍应执行测试体并传播业务异常。"""
    from utils.third_party import allure_reporter

    def fail_step(title: str) -> None:
        raise RuntimeError("reporter unavailable")

    monkeypatch.setattr(allure_reporter.allure, "step", fail_step)
    reached: list[bool] = []
    with allure_reporter.step("降级步骤"):
        reached.append(True)
    assert reached == [True]


def test_single_entry_wraps_gateway_call_and_preserves_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单接口入口必须先设置元数据，再在固定步骤内原样传播接口异常。"""
    from test_cases import test_single_api

    events: list[str] = []
    expected = RuntimeError("gateway failed")

    @contextmanager
    def fake_step(title: str):
        events.append(f"enter:{title}")
        yield
        events.append(f"exit:{title}")

    class Gateway:
        @staticmethod
        def execute(case: dict[str, Any]) -> None:
            events.append("execute")
            raise expected

    monkeypatch.setattr(
        test_single_api,
        "set_single_case_metadata",
        lambda case: events.append("metadata"),
    )
    monkeypatch.setattr(test_single_api, "step", fake_step)
    single_case = {
        "api_id": "GetMe",
        "execution_case": {},
    }

    with pytest.raises(RuntimeError) as caught:
        test_single_api.test_single_gateway_api(single_case, Gateway(), {})

    assert caught.value is expected
    assert events == ["metadata", "enter:执行接口：GetMe", "execute"]


def test_flow_top_level_titles_are_stable() -> None:
    """API、等待和 action 顶层步骤标题必须遵循固定格式。"""
    from utils.custom.flow_runner import FlowRunner

    assert FlowRunner._build_step_title(
        {"api": "GetMe"}, "fetch", 1, 3
    ) == "1/3 fetch：GetMe"
    assert FlowRunner._build_step_title(
        {"wait": {"seconds": 1.5}}, "pause", 2, 3
    ) == "2/3 pause：等待 1.5s"
    assert FlowRunner._build_step_title(
        {"action": "prepared_media_upload"}, "upload", 3, 3
    ) == "3/3 upload：prepared_media_upload"


def test_flow_poll_creates_numbered_steps_and_safe_summaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """轮询网络调用必须位于连续编号子步骤，并附加匹配摘要。"""
    from utils.custom import flow_runner

    class Response:
        status_code = 200

        def __init__(self, status: str) -> None:
            self.status = status

        def json(self) -> dict[str, Any]:
            return {
                "code": 0,
                "message": "ok",
                "responses": [
                    {
                        "id": "req_0",
                        "success": True,
                        "code": 0,
                        "message": "ok",
                        "data": {"status": self.status},
                    }
                ],
            }

    events: list[str] = []
    summaries: list[dict[str, Any]] = []

    class Gateway:
        settings = {"timeout": 1}
        http_client = None

        def __init__(self) -> None:
            self.responses = [Response("RUNNING"), Response("SUCCEEDED")]

        def invoke(self, case: dict[str, Any]) -> Response:
            events.append("invoke")
            return self.responses.pop(0)

    @contextmanager
    def fake_step(title: str):
        events.append(f"enter:{title}")
        yield
        events.append(f"exit:{title}")

    monkeypatch.setattr(flow_runner, "report_step", fake_step)
    monkeypatch.setattr(
        flow_runner,
        "attach_json",
        lambda name, data: summaries.append(data),
    )
    now = [0.0]
    gateway = Gateway()
    flow_case = {
        "id": "PollFlow",
        "api_definitions": {
            "Demo": {
                "id": "Demo",
                "name": "示例",
                "request": {
                    "service_name": "service.Demo",
                    "method_name": "Demo",
                },
            }
        },
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
            "name": "轮询场景",
            "variables": {},
            "step_data": {
                "poll": {
                    "params": {},
                    "assert": {
                        "http_status": 200,
                        "gateway": {"code": 0, "message": "ok"},
                        "response": {
                            "id": "req_0",
                            "success": True,
                            "code": 0,
                            "message": "ok",
                        },
                    },
                }
            },
        },
    }

    flow_runner.FlowRunner(
        tmp_path,
        gateway_factory=lambda context: gateway,
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
        monotonic=lambda: now[0],
    ).run(flow_case)

    assert events == [
        "enter:1/1 poll：Demo",
        "enter:第 1 次轮询",
        "invoke",
        "exit:第 1 次轮询",
        "enter:第 2 次轮询",
        "invoke",
        "exit:第 2 次轮询",
        "exit:1/1 poll：Demo",
    ]
    assert summaries == [
        {
            "path": "$.status",
            "actual": "RUNNING",
            "expected": "SUCCEEDED",
            "matched": False,
        },
        {
            "path": "$.status",
            "actual": "SUCCEEDED",
            "expected": "SUCCEEDED",
            "matched": True,
        },
    ]


def test_http_post_attachments_preserve_raw_values_and_non_json_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway 附件保留原始对象和非 JSON 响应正文。"""
    from utils.custom import http_client

    class Response:
        status_code = 502
        text = "response-access-secret"

        @staticmethod
        def json() -> Any:
            raise ValueError("not json")

    class Session:
        @staticmethod
        def post(*args: Any, **kwargs: Any) -> Response:
            return Response()

    attachments: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        http_client,
        "attach_json",
        lambda name, data: attachments.append((name, data)),
        raising=False,
    )
    client = http_client.HttpClient(Session())
    client.post_json(
        "https://gateway.example/api",
        {"Authorization": "header-secret"},
        {"access_token": "request-token-secret"},
        1,
    )

    serialized = json.dumps(attachments, ensure_ascii=False)
    assert "header-secret" in serialized
    assert "request-token-secret" in serialized
    assert "response-access-secret" in serialized
    assert attachments[0][1]["headers"]["Authorization"] == "header-secret"
    assert attachments[1][1]["body_type"] == "text"
    assert attachments[1][1]["body"] == Response.text


def test_http_exception_attachment_preserves_raw_request_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """网络异常附件保留原始请求和异常，原 requests 异常原样抛出。"""
    from utils.custom import http_client

    expected = requests.Timeout("signed-secret")

    class Session:
        @staticmethod
        def post(*args: Any, **kwargs: Any) -> Any:
            raise expected

    attachments: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        http_client,
        "attach_json",
        lambda name, data: attachments.append((name, data)),
        raising=False,
    )

    with pytest.raises(requests.Timeout) as caught:
        http_client.HttpClient(Session()).post_json(
            "https://gateway.example/api",
            {"Authorization": "header-secret"},
            {"token": "request-token-secret"},
            1,
        )

    assert caught.value is expected
    assert attachments[-1][1]["exception_type"] == "Timeout"
    assert attachments[-1][1]["exception_message"] == "signed-secret"
    serialized = json.dumps(attachments, ensure_ascii=False)
    assert "signed-secret" in serialized
    assert "header-secret" in serialized
    assert "request-token-secret" in serialized


def test_put_attachments_preserve_signature_but_omit_binary_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COS PUT 附件保留完整签名 URL，但二进制正文仍只记录字节数。"""
    from utils.custom import http_client

    response = SimpleNamespace(
        status_code=200,
        headers={"x-cos-request-id": "raw-response-header"},
        text="raw-upload-response",
    )

    class Session:
        @staticmethod
        def put(**kwargs: Any) -> Any:
            return response

    attachments: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        http_client,
        "attach_json",
        lambda name, data: attachments.append((name, data)),
        raising=False,
    )
    result = http_client.HttpClient(Session()).put_bytes(
        "https://cos.example/media.jpg?signature=signed-secret",
        {"Content-Length": "3", "Content-Type": "image/jpeg"},
        b"abc",
        1,
    )

    assert result is response
    serialized = json.dumps(attachments, ensure_ascii=False)
    assert "signed-secret" in serialized
    assert "abc" not in serialized
    assert attachments[0][1]["url"].endswith("?signature=signed-secret")
    assert attachments[0][1]["content_length"] == 3
    assert attachments[1][1]["status_code"] == 200
    assert attachments[1][1]["headers"] == {
        "x-cos-request-id": "raw-response-header"
    }
    assert attachments[1][1]["body"] == "raw-upload-response"


def test_put_exception_attachment_preserves_raw_values_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUT 失败附件保留签名 URL 和异常原文，并保持原始异常对象。"""
    from utils.custom import http_client

    expected = requests.ConnectionError("signed-secret")

    class Session:
        @staticmethod
        def put(**kwargs: Any) -> Any:
            raise expected

    attachments: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        http_client,
        "attach_json",
        lambda name, data: attachments.append((name, data)),
    )

    with pytest.raises(requests.ConnectionError) as caught:
        http_client.HttpClient(Session()).put_bytes(
            "https://cos.example/media.jpg?signature=signed-secret",
            {"Content-Length": "3", "Content-Type": "image/jpeg"},
            b"abc",
            1,
        )

    assert caught.value is expected
    assert attachments[-1][1]["exception_type"] == "ConnectionError"
    assert attachments[-1][1]["exception_message"] == "signed-secret"
    serialized = json.dumps(attachments, ensure_ascii=False)
    assert "signed-secret" in serialized
    assert "abc" not in serialized


def _read_jenkinsfile() -> str:
    """
    读取项目根目录的 Jenkinsfile。

    功能说明:
        为 Jenkins Pipeline 合约测试提供统一的文本入口，避免各测试重复定位文件。

    返回值:
        str: Jenkinsfile 的 UTF-8 文本内容。

    异常说明:
        FileNotFoundError: Jenkinsfile 不存在时直接失败，提示流水线入口缺失。
    """
    return (Path(__file__).resolve().parents[1] / "Jenkinsfile").read_text(
        encoding="utf-8"
    )


def test_jenkinsfile_preserves_existing_execution_contract() -> None:
    """暂停自动触发后仍必须保留参数和原有测试入口。"""
    content = _read_jenkinsfile()

    for parameter in ("RUN_TYPE", "FLOW"):
        assert f"name: '{parameter}'" in content
    # 目标环境不是工具/Jenkins 的用户选择项；只由部署平台固定映射。
    assert "name: 'ENVIRONMENT'" not in content
    assert "name: 'TARGET_ENV'" not in content
    assert "disableConcurrentBuilds()" in content
    # 暂停期间 Jenkinsfile 不能声明 cron，否则手动构建后会重新注册定时器。
    assert "triggers {" not in content
    assert "cron(" not in content
    assert "test_cases/test_single_api.py" in content
    assert "test_cases/test_gateway_flow.py" in content
    assert ".venv/bin/python runtest.py" in content
    # Jenkins 首次加载参数定义时尚无参数环境变量，必须使用声明值作为安全默认值。
    assert 'PLATFORM_ENVIRONMENT="${PLATFORM_ENVIRONMENT:-dev}"' in content
    assert 'dev) TARGET_ENV="test"' in content
    assert 'prod) TARGET_ENV="prod"' in content
    assert 'RUN_TYPE="${RUN_TYPE:-all}"' in content
    assert 'FLOW="${FLOW:-}"' in content


def test_jenkinsfile_generates_and_publishes_allure3() -> None:
    """Pipeline 必须生成 Allure 原始数据并使用固定策略发布 Allure 3。"""
    content = _read_jenkinsfile()

    assert "ALLURE_VERSION = '3.14.3'" in content
    # Allure 原始结果按项目和任务隔离，五条 pytest 分支必须使用同一动态目录。
    assert content.count('--alluredir="$ALLURE_RESULTS"') == 5
    assert content.count("--clean-alluredir") == 5
    assert content.count("--allure-no-capture") == 5
    assert "allureVersion: '3'" in content
    assert "includeProperties: false" in content
    assert "resultPolicy: 'LEAVE_AS_IS'" in content
    assert (
        'results: [[path: "Truthy_ApiAutoTest2/reports/task-reports/'
        "${params.PROJECT_ID ?: 'truthy'}/${params.PLATFORM_TASK_ID}/allure-results\"]]"
        in content
    )
    assert "catchError(" in content
    assert "buildResult: 'UNSTABLE'" in content
    assert "stageResult: 'UNSTABLE'" in content
    # 平台报告同步链路依赖 post 阶段在项目目录内生成可归档的 HTML 报告。
    assert (
        'allure awesome "$ALLURE_RESULTS" --output allure-report-publish'
        in content
    )


def test_jenkinsfile_isolates_cli_and_archives_only_required_outputs() -> None:
    """Allure CLI 必须隔离在任务工作区，归档范围不得包含环境和工具目录。"""
    content = _read_jenkinsfile()

    assert "NODE_VERSION = '22.23.2'" in content
    assert (
        "NODE_SHA256 = "
        "'61130f394c1630d211dd50aecc4353d379480f36d3ac913cd85dbba1aed585c6'"
        in content
    )
    assert (
        'https://nodejs.org/dist/v$NODE_VERSION/'
        'node-v$NODE_VERSION-darwin-arm64.tar.gz'
        in content
    )
    assert "shasum -a 256 -c -" in content
    assert 'export PATH="/opt/homebrew/bin:/usr/local/bin:' in content
    assert 'NPM_BIN="$(command -v npm || true)"' in content
    assert '"$NPM_BIN" install --global' in content
    assert '--prefix "$ALLURE_HOME"' in content
    assert '"allure@$ALLURE_VERSION"' in content
    assert (
        "PATH+NODE=${env.WORKSPACE}/.jenkins-tools/"
        "node-v${env.NODE_VERSION}-darwin-arm64/bin"
        in content
    )
    assert ".jenkins-tools/allure/bin" in content
    # 归档统一在 dir(PROJECT_DIR) 作用域内调用，pattern 不带项目目录前缀；
    # 项目级任务报告与 JUnit 必须一并归档；allure-report-publish 供平台拉取。
    assert (
        "artifacts: "
        "'logs/**/*,"
        "reports/junit/**/*,"
        "reports/task-reports/**/*,"
        "allure-report-publish/**/*'"
        in content
    )
    for excluded_path in (".env", ".venv", ".jenkins-tools"):
        assert excluded_path not in content.partition("archiveArtifacts(")[2]
