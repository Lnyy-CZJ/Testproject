"""固定 Executor 的执行前脱敏和分类规则测试。"""

import importlib.util
import json
from pathlib import Path

import pytest


def load_runner():
    """从镜像入口源码加载纯函数，测试环境无需创建容器。"""

    path = Path(__file__).resolve().parents[2] / "executor" / "runner.py"
    spec = importlib.util.spec_from_file_location("api_executor_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_executor_redacts_request_and_json_response_fields():
    """敏感 Header、请求体和 JSON 响应在 stdout 形成前必须脱敏。"""

    runner = load_runner()
    request = runner.redact({"headers": {"Authorization": "Bearer secret"}, "body": {"password": "123"}})
    response = runner.redact_response_body('{"token":"response-secret","session":"session-secret","value":"ok"}')
    assert request["headers"]["Authorization"] == "[REDACTED]"
    assert request["body"]["password"] == "[REDACTED]"
    assert response == {"token": "[REDACTED]", "session": "[REDACTED]", "value": "ok"}


class _Response:
    """最小 HTTP 响应替身：只模拟 Runner 真正消费的受控响应边界。"""

    def __init__(self, body: str, *, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = headers or {}

    def read(self, _size: int) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


def test_dependency_executor_extracts_native_variables_and_reuses_cookie_session(monkeypatch):
    """计划拓扑优先执行，提取值以原生类型注入后继请求并复用同一 Cookie 会话。"""

    runner = load_runner()
    observed = []
    responses = iter([
        _Response(
            '{"data":{"id":7},"marker":"ticket-42"}',
            headers={"X-CSRF-Token": "csrf-value", "Set-Cookie": "session=session-secret; Path=/"},
        ),
        _Response('{"ok":true}'),
    ])

    def send(request, *, timeout):
        assert timeout == 10
        observed.append(request)
        return next(responses)

    monkeypatch.setattr(runner, "send_request", send)
    result = runner.execute_run({
        "run_id": "run_plan",
        "resolved_target_url": "https://target.example",
        "execution_plan": {
            "topological_order": ["login", "profile"],
            "nodes": [
                {
                    "node_id": "login", "executable_case_id": "case_login",
                    "request": {"method": "POST", "path": "/login", "body": {"login": True}},
                    "producers": [
                        {"name": "user_id", "extractor_type": "json_pointer", "source_path": "/data/id"},
                        {"name": "csrf", "extractor_type": "header", "source_path": "X-CSRF-Token"},
                        {"name": "status", "extractor_type": "status_code", "source_path": ""},
                        {"name": "session", "extractor_type": "cookie", "source_path": "session"},
                        {"name": "ticket", "extractor_type": "regex", "source_path": "ticket-(\\d+)"},
                    ],
                },
                {
                    "node_id": "profile", "executable_case_id": "case_profile", "depends_on": ["login"],
                    "request": {
                        "method": "POST", "path": "/users/{{user_id}}", "query": {"status": "{{status}}"},
                        "headers": {"X-CSRF-Token": "{{csrf}}"}, "cookies": {"session": "{{session}}"},
                        "body": {"id": "{{user_id}}", "ticket": "{{ticket}}"},
                    },
                },
            ],
        },
    })

    assert [item["node_id"] for item in result["step_results"]] == ["login", "profile"]
    assert json.loads(observed[1].data.decode("utf-8")) == {"id": 7, "ticket": "42"}
    assert observed[1].get_header("X-csrf-token") == "csrf-value"
    assert "session=session-secret" in observed[1].get_header("Cookie")
    assert result["case_results"][1]["status"] == "passed"
    assert "session-secret" not in json.dumps(result, ensure_ascii=False)


def test_dependency_failure_blocks_only_its_successors_and_unknown_assertion_fails_closed(monkeypatch):
    """失败分支阻断后继而不影响独立节点，未知断言绝不能被默认放行。"""

    runner = load_runner()
    requested_paths = []

    def send(request, *, timeout):
        assert timeout == 10
        requested_paths.append(request.full_url)
        return _Response('{"ok":true}')

    monkeypatch.setattr(runner, "send_request", send)
    result = runner.execute_run({
        "run_id": "run_branches", "resolved_target_url": "https://target.example",
        "execution_plan": {
            "topological_order": ["root", "blocked", "independent"],
            "nodes": [
                {"node_id": "root", "request": {"method": "GET", "path": "/root"}, "assertions": [{"operator": "unsupported", "expected": True}]},
                {"node_id": "blocked", "depends_on": ["root"], "request": {"method": "GET", "path": "/blocked"}},
                {"node_id": "independent", "request": {"method": "GET", "path": "/independent"}},
            ],
        },
    })

    by_node = {item["node_id"]: item for item in result["step_results"]}
    assert by_node["root"]["status"] == "failed"
    assert by_node["root"]["error_signature"] == "ASSERTION_UNKNOWN_OPERATOR"
    assert by_node["blocked"]["status"] == "blocked"
    assert by_node["blocked"]["error_signature"] == "DEPENDENCY_NODE_BLOCKED"
    assert by_node["independent"]["status"] == "passed"
    assert requested_paths == ["https://target.example/root", "https://target.example/independent"]


def test_compiler_edge_names_block_failed_descendant(monkeypatch):
    """Executor 必须消费编译器实际输出的 from_node/to_node，不能漏掉失败传播。"""

    runner = load_runner()
    requested_paths = []
    monkeypatch.setattr(
        runner, "send_request",
        lambda request, *, timeout: requested_paths.append(request.full_url) or _Response('{"ok":true}'),
    )
    result = runner.execute_run({
        "run_id": "run_compiler_edges", "resolved_target_url": "https://target.example",
        "plan": {
            "plan_id": "plan_edges", "sha256": "a" * 64,
            "topological_order": ["root", "child"],
            "nodes": [
                {"node_id": "root", "request": {"method": "GET", "path": "/root"}, "assertions": [{"operator": "status_code", "expected": 500}]},
                {"node_id": "child", "request": {"method": "GET", "path": "/child"}},
            ],
            "edges": [{"from_node": "root", "to_node": "child", "source_type": "variable"}],
        },
    })
    by_node = {item["node_id"]: item for item in result["step_results"]}
    assert by_node["root"]["status"] == "failed"
    assert by_node["child"]["status"] == "blocked"
    assert requested_paths == ["https://target.example/root"]


def test_variable_consumer_destination_injects_without_request_template(monkeypatch):
    """变量消费者声明本身必须把值写入 Header/Body，不能要求模型重复写模板。"""

    runner = load_runner()
    observed = []
    responses = iter([_Response('{"token":"abc"}'), _Response('{"ok":true}')])
    monkeypatch.setattr(runner, "send_request", lambda request, *, timeout: observed.append(request) or next(responses))
    result = runner.execute_run({
        "run_id": "run_consumers", "resolved_target_url": "https://target.example",
        "plan": {
            "plan_id": "plan_consumers", "sha256": "b" * 64,
            "topological_order": ["login", "profile"],
            "nodes": [
                {
                    "node_id": "login", "request": {"method": "POST", "path": "/login"},
                    "producers": [{"name": "access_token", "extractor_type": "json_pointer", "source_path": "/token"}],
                },
                {
                    "node_id": "profile", "request": {"method": "POST", "path": "/profile", "body": {}},
                    "consumers": [
                        {"name": "access_token", "destination": "header", "field_path": "Authorization", "required": True},
                        {"name": "access_token", "destination": "body", "field_path": "/session/token", "required": True},
                    ],
                },
            ],
            "edges": [{"from_node": "login", "to_node": "profile", "source_type": "variable"}],
        },
    })
    assert result["step_results"][1]["status"] == "passed"
    assert observed[1].get_header("Authorization") == "abc"
    assert json.loads(observed[1].data.decode())["session"]["token"] == "abc"


def test_executor_rejects_planless_cases_payload():
    """V2.4 Executor 不再接受旧 cases 数组，防止绕过已确认执行计划。"""

    runner = load_runner()
    with pytest.raises(ValueError, match="EXECUTION_PLAN_INVALID"):
        runner.execute_run({
            "run_id": "run_legacy", "resolved_target_url": "https://target.example",
            "cases": [{"request": {"method": "GET", "path": "/health"}}],
        })


def test_dependency_executor_rejects_unsafe_write_retry_and_marks_pending_nodes_cancelled(monkeypatch):
    """未确认幂等的写操作不可重试，取消时尚未开始节点必须各自得到终态。"""

    runner = load_runner()
    calls = []
    monkeypatch.setattr(runner, "send_request", lambda request, *, timeout: calls.append(request))
    retry_result = runner.execute_run({
        "run_id": "run_retry", "resolved_target_url": "https://target.example",
        "execution_plan": {"nodes": [{
            "node_id": "write", "request": {"method": "POST", "path": "/orders"},
            "retry_policy": {"max_retries": 1},
        }]},
    })
    assert retry_result["step_results"][0]["status"] == "error"
    assert retry_result["step_results"][0]["error_signature"] == "WRITE_RETRY_NOT_ALLOWED"
    assert calls == []

    cancelled = runner.execute_run({
        "run_id": "run_cancelled", "resolved_target_url": "https://target.example", "cancelled": True,
        "execution_plan": {"nodes": [
            {"node_id": "first", "request": {"method": "GET", "path": "/first"}},
            {"node_id": "second", "request": {"method": "GET", "path": "/second"}},
        ]},
    })
    assert [item["status"] for item in cancelled["step_results"]] == ["cancelled", "cancelled"]


def test_dependency_executor_fails_closed_for_non_object_request():
    """损坏计划节点不得让容器崩溃或退化为任意执行，应返回稳定错误终态。"""

    runner = load_runner()
    result = runner.execute_run({
        "run_id": "run_invalid", "resolved_target_url": "https://target.example",
        "execution_plan": {"nodes": [{"node_id": "invalid", "request": ["not", "an", "object"]}]},
    })
    assert result["step_results"][0]["status"] == "error"
    assert result["step_results"][0]["error_signature"] == "EXECUTION_PLAN_INVALID"
