"""阶段三主 Workflow 的纯内存行为测试。"""

from __future__ import annotations

import agents.api_test.workflows.api_run_case_wrokflow as workflow_module
from agents.api_test.workflows.api_run_case_wrokflow import ApiRunCaseGeneratorWorkFlow
from services.api_agent.models import (
    ApiContract,
    BaseTestCase,
    ResponseDefinition,
    SourceTrace,
    WorkflowRuntimeContext,
)


def _runtime() -> WorkflowRuntimeContext:
    """构造无目录、数据库或网络能力的阶段三运行时。"""

    return WorkflowRuntimeContext(
        task_id="task_executable_workflow",
        attempt_id="attempt_executable_workflow",
        workflow_id="api-run-case",
        workflow_version="v2.4",
        input_versions={"contracts": 1, "base-cases": 1},
        event_sink=lambda _event: None,
        model_invoker=None,
    )


def _contract() -> ApiContract:
    """提供已确认的会话接口契约。"""

    return ApiContract(
        contract_id="contract_session",
        artifact_schema_version=3,
        name="创建会话",
        method="POST",
        path="/sessions/{session_id}",
        responses=[ResponseDefinition(status_code="201", description="created")],
        source_trace=SourceTrace(source_id="fixture", section_id="session", quote="POST /sessions/{session_id}"),
        status="confirmed",
    )


def _base_case(case_id: str = "case_session") -> BaseTestCase:
    """提供已确认基础用例，避免 Workflow 读取任何历史产物。"""

    return BaseTestCase(
        case_id=case_id,
        artifact_schema_version=3,
        contract_id="contract_session",
        name="使用会话创建资源",
        objective="验证携带登录会话后可创建资源",
        dimension="normal",
        source="human",
        status="confirmed",
    )


def _complete_candidate() -> dict:
    """返回旧完整请求生成节点的结构化输出。"""

    return {
        "request": {
            "method": "POST",
            "path": "/sessions/{session_id}",
            "headers": {"Authorization": "{{token}}", "X-CSRF-Token": "{{csrf}}"},
            "query": {"verbose": True},
            "cookies": {"SESSION": "{{session}}"},
            "body": {"username": "{{username}}", "password": "{{password}}"},
        },
        "precondition_case_ids": ["exec_login"],
        "variable_producers": [
            {"name": "token", "extractor_type": "header", "source_path": "Authorization"},
            {"name": "csrf", "extractor_type": "header", "source_path": "X-CSRF-Token"},
            {"name": "session", "extractor_type": "cookie", "source_path": "SESSION"},
        ],
        "variable_consumers": [
            {"name": "token", "destination": "header", "field_path": "Authorization"},
            {"name": "csrf", "destination": "header", "field_path": "X-CSRF-Token"},
            {"name": "session", "destination": "cookie", "field_path": "SESSION"},
        ],
        "data_refs": ["baseline.session-user"],
        "assertions": [{"operator": "status_code", "expected": 201}],
        "observation_targets": ["response.body.resource_id"],
    }


def test_platform_workflow_runs_legacy_generation_node_and_outputs_complete_safe_case(monkeypatch):
    """若平台分支扫描目录、写 MySQL 或绕过旧生成节点，此测试应失败。"""

    def forbidden(*_args, **_kwargs):
        raise AssertionError("平台 Workflow 不得访问宿主目录或 MySQL")

    monkeypatch.setattr(workflow_module, "inspect_test_files", forbidden)
    monkeypatch.setattr(workflow_module, "get_system_db_connection", forbidden)
    generated = []

    def legacy_generator(base_case, contract, manifest):
        generated.append((base_case.case_id, contract.contract_id, manifest["data_refs"]))
        return _complete_candidate()

    result = ApiRunCaseGeneratorWorkFlow(legacy_case_generator=legacy_generator).run(
        base_cases=[_base_case()],
        contracts=[_contract()],
        controlled_manifest={
            "data_refs": ["baseline.session-user"], "capabilities": [],
            "precondition_case_ids": ["exec_login"],
        },
        runtime=_runtime(),
    )

    assert generated == [("case_session", "contract_session", ["baseline.session-user"])]
    assert result.status == "ready"
    assert len(result.items) == 1
    item = result.items[0]
    assert item["generation_kernel"] == "v2_core_workflow"
    assert item["request"]["path"] == "/sessions/{session_id}"
    assert item["request"]["headers"]["Authorization"] == "{{token}}"
    assert item["request"]["query"] == {"verbose": True}
    assert item["request"]["cookies"] == {"SESSION": "{{session}}"}
    assert item["request"]["body"]["username"] == "{{username}}"
    assert item["precondition_case_ids"] == ["exec_login"]
    assert item["data_refs"] == ["baseline.session-user"]
    assert item["assertions"][0]["operator"] == "status_code"
    assert item["observation_targets"] == ["response.body.resource_id"]
    assert item["validation_status"] == "ready"


def test_platform_workflow_isolates_host_and_literal_credential_candidate():
    """若任一坏候选使整批失败，或 Host/凭证未禁用，此测试应失败。"""

    good = _complete_candidate()
    bad = _complete_candidate()
    bad["request"] = {
        "method": "POST",
        "path": "https://unsafe.example.test/sessions",
        "headers": {"Authorization": "Bearer plaintext-secret"},
    }

    def legacy_generator(base_case, _contract, _manifest):
        return good if base_case.case_id == "case_good" else bad

    result = ApiRunCaseGeneratorWorkFlow(legacy_case_generator=legacy_generator).run(
        base_cases=[_base_case("case_good"), _base_case("case_bad")],
        contracts=[_contract()],
        controlled_manifest={
            "data_refs": ["baseline.session-user"], "capabilities": [],
            "precondition_case_ids": ["exec_login"],
        },
        runtime=_runtime(),
    )

    assert result.status == "partial_ready"
    assert len(result.items) == 2
    ready = [item for item in result.items if item["validation_status"] == "ready"]
    disabled = [item for item in result.items if item["validation_status"] == "disabled"]
    assert len(ready) == 1
    assert len(disabled) == 1
    assert {issue["code"] for issue in disabled[0]["validation_issues"]} >= {
        "HOST_FORBIDDEN", "PLAINTEXT_CREDENTIAL_FORBIDDEN",
    }


def test_platform_workflow_recursively_rejects_plaintext_credentials():
    """Query、Cookie、Body 和变量默认值中的凭证不能绕过 Header 专项检查。"""

    candidate = _complete_candidate()
    candidate["request"].update({
        "query": {"api_key": "plain-query-key"},
        "cookies": {"SESSION": "plain-cookie"},
        "body": {"password": "plain-password"},
    })
    candidate["variable_consumers"].append({
        "name": "fallback_token", "destination": "header", "field_path": "X-Api-Key",
        "required": False, "default_policy": "use_default", "default_value": "plain-default",
    })
    result = ApiRunCaseGeneratorWorkFlow(legacy_case_generator=lambda *_args: candidate).run(
        base_cases=[_base_case()], contracts=[_contract()],
        controlled_manifest={
            "data_refs": ["baseline.session-user"], "capabilities": [],
            "precondition_case_ids": ["exec_login"],
        }, runtime=_runtime(),
    )
    assert result.items[0]["validation_status"] == "disabled"
    assert "PLAINTEXT_CREDENTIAL_FORBIDDEN" in {
        issue["code"] for issue in result.items[0]["validation_issues"]
    }


def test_normal_case_uses_documented_success_response_when_model_omits_assertion():
    """模型漏写断言时只能使用契约明确响应，不能伪造默认 200，也不能禁用正常用例。"""

    candidate = {
        "request": {"method": "POST", "path": "/sessions/{session_id}"},
        "assertions": [],
    }
    result = ApiRunCaseGeneratorWorkFlow(legacy_case_generator=lambda *_args: candidate).run(
        base_cases=[_base_case()], contracts=[_contract()],
        controlled_manifest={"data_refs": [], "capabilities": [], "precondition_case_ids": []},
        runtime=_runtime(),
    )
    assert result.items[0]["assertions"] == [{
        "operator": "status_code", "expected": 201, "actual_path": "",
    }]
    assert result.items[0]["validation_status"] == "ready"
