"""API V2 Schema 和状态机测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.api_agent.models import (
    AnalysisScopeVersion,
    ApiContract,
    ExecutionPlan,
    ExecutionPlanEdge,
    ExecutionPlanNode,
    ExecutionStepResult,
    ExecutableCase,
    FieldEvidence,
    SourceTrace,
    VariableConsumer,
    VariableProducer,
    WorkflowProvenance,
    WorkflowResult,
    assert_transition,
)


def contract_payload() -> dict:
    """构造最小可验证契约。"""

    return {
        "contract_id": "contract_post_users_id",
        "name": "更新用户",
        "method": "post",
        "path": "/users/{id}",
        "parameters": [{
            "name": "id", "location": "path", "required": True, "schema": {"type": "string"},
        }],
        "source_trace": SourceTrace(source_id="doc", section_id="paths", quote="POST /users/{id}").model_dump(),
        "field_evidence": [FieldEvidence(
            field_path="method", value="POST", source_type="openapi_node",
            source_pointer="/paths/~1users~1{id}/post",
        ).model_dump()],
    }


def test_contract_is_strict_and_path_is_relative() -> None:
    contract = ApiContract.model_validate(contract_payload())
    assert contract.method == "POST"
    invalid = contract_payload() | {"path": "https://example.test/users", "unexpected": True}
    with pytest.raises(ValidationError):
        ApiContract.model_validate(invalid)


def test_path_parameter_must_match_template() -> None:
    payload = contract_payload()
    payload["parameters"][0]["required"] = False
    with pytest.raises(ValidationError):
        ApiContract.model_validate(payload)


def test_state_transitions_reject_illegal_shortcuts() -> None:
    assert_transition("pending", "running")
    assert_transition("running", "waiting_contract_review")
    with pytest.raises(ValueError):
        assert_transition("pending", "succeeded")
    with pytest.raises(ValueError):
        assert_transition("succeeded", "running")


def test_analysis_scope_is_strict_and_normalizes_methods() -> None:
    scope = AnalysisScopeVersion(
        scope_id="scope_1", version=1, document_version=1,
        include_methods=["get", "POST", "get"],
        created_by={"user_id": "tester", "username": "tester"},
    )
    assert scope.include_methods == ["GET", "POST"]
    with pytest.raises(ValidationError):
        AnalysisScopeVersion.model_validate(scope.model_dump() | {"target_url": "https://example.test"})


def test_v24_contract_distinguishes_missing_auth_from_explicit_no_auth() -> None:
    """缺少鉴权结论不能被误写为明确无需鉴权。"""

    unresolved = ApiContract.model_validate(contract_payload())
    assert unresolved.auth_conclusion == "unresolved"

    explicit_none = ApiContract.model_validate(contract_payload() | {
        "artifact_schema_version": 3,
        "auth_conclusion": "none",
        "auth_signal_detected": True,
    })
    assert explicit_none.auth_conclusion == "none"


def test_v24_executable_case_rejects_host_and_models_variable_flow() -> None:
    """执行定义只保存相对请求，并能显式描述变量生产和消费。"""

    payload = {
        "executable_case_id": "exec_login",
        "base_case_id": "case_login",
        "contract_id": "contract_login",
        "name": "登录并提取 token",
        "risk_level": "low",
        "request": {"method": "POST", "path": "/login", "body": {"username": "tester"}},
        "variable_producers": [{
            "name": "access_token", "extractor_type": "json_pointer",
            "source_path": "/data/token", "required": True, "sensitive": True,
        }],
        "variable_consumers": [{
            "name": "csrf_token", "destination": "header",
            "field_path": "X-CSRF-Token", "required": True,
        }],
        "generation_kernel": "v2_core_workflow",
    }
    case = ExecutableCase.model_validate(payload)
    assert case.variable_producers[0].name == "access_token"
    assert case.variable_consumers[0].destination == "header"
    with pytest.raises(ValidationError):
        ExecutableCase.model_validate(payload | {
            "request": {"method": "POST", "path": "https://example.test/login"},
        })


def test_v24_workflow_result_has_stable_provenance_and_rejections() -> None:
    """控制平面只消费结构化 WorkflowResult，不依赖工作流内部状态。"""

    result = WorkflowResult(
        status="partial_ready",
        items=[{"contract_id": "contract_login"}],
        rejections=[],
        quality_summary={"accepted": 1, "rejected": 0},
        workflow_provenance=WorkflowProvenance(
            workflow_id="api_base_case", workflow_version="2.4.0",
            workflow_sha256="a" * 64, prompt_sha256={"base": "b" * 64},
        ),
    )
    assert result.status == "partial_ready"
    assert result.workflow_provenance.workflow_id == "api_base_case"


def test_v24_execution_plan_and_step_result_are_strict() -> None:
    """执行计划绑定来源 SHA，逐节点结果能表达依赖阻断。"""

    plan = ExecutionPlan(
        plan_id="plan_001", task_id="task_001", version=1,
        source_executable_version=2, source_executable_sha256="a" * 64,
        target_id="local-api", environment="dev",
        resource_policy_id="local-restricted-v1", egress_policy_id="local-platform-v1",
        nodes=[ExecutionPlanNode(node_id="exec_login", executable_case_id="exec_login")],
        edges=[], topological_order=["exec_login"], confirmation_sha256="b" * 64,
    )
    assert plan.status == "draft"
    step = ExecutionStepResult(
        step_id="step_2", node_id="exec_profile", executable_case_id="exec_profile",
        status="blocked", started_at="2026-08-21T00:00:00+00:00",
        finished_at="2026-08-21T00:00:00+00:00", duration_ms=0,
        blocked_by=["exec_login"], error_code="DEPENDENCY_NODE_BLOCKED",
    )
    assert step.blocked_by == ["exec_login"]

    with pytest.raises(ValidationError):
        ExecutionPlan.model_validate(plan.model_dump() | {"host": "http://127.0.0.1"})
