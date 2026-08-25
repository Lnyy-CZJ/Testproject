"""V2.2 融合生成、Grounding 与历史执行门禁测试。"""

from __future__ import annotations

from agents.api_test.cases.fused_kernel import GenerationContext, generate_fused_cases
from agents.api_test.cases.grounding import assess_case_grounding, validate_legacy_executable
from agents.api_test.cases.executable import build_executable_cases
from agents.api_test.workflows.api_basecase_workflow import ApiBaseCaseGeneratorWorkFlow
from agents.api_test.workflows.api_run_case_wrokflow import ApiRunCaseGeneratorWorkFlow
from services.api_agent.models import (
    ApiContract,
    BaseTestCase,
    ContractParameter,
    FieldEvidence,
    RequestBodyDefinition,
    ResponseDefinition,
    SourceTrace,
)


def login_contract() -> ApiContract:
    """返回包含 Cookie、请求体和响应依据的登录契约。"""

    return ApiContract(
        contract_id="contract_login",
        name="用户登录",
        summary="使用账号密码登录并返回 CSRF Token",
        method="POST",
        path="/api/login",
        parameters=[
            ContractParameter(name="session", location="cookie", required=False),
        ],
        request_body=RequestBodyDefinition(
            required=True,
            content={"application/json": {"schema": {"type": "object", "required": ["username", "password"], "properties": {"username": {"type": "string"}, "password": {"type": "string"}}}}},
        ),
        responses=[
            ResponseDefinition(status_code="200", description="登录成功"),
            ResponseDefinition(status_code="401", description="账号或密码错误"),
        ],
        source_trace=SourceTrace(source_id="doc", section_id="login", quote="POST /api/login"),
        field_evidence=[
            FieldEvidence(field_path="method", value="POST", source_type="source_quote", source_pointer="login", quote="POST /api/login"),
            FieldEvidence(field_path="path", value="/api/login", source_type="source_quote", source_pointer="login", quote="POST /api/login"),
            FieldEvidence(field_path="request_body", value={"username": "string", "password": "string"}, source_type="source_quote", source_pointer="login", quote="username password"),
            FieldEvidence(field_path="responses", value=[200, 401], source_type="source_quote", source_pointer="login", quote="200 登录成功；401 账号或密码错误"),
        ],
        status="confirmed",
    )


def test_fused_kernel_builds_detailed_login_cases_without_foreign_domain() -> None:
    context = GenerationContext.from_contract(login_contract(), contract_version=1)
    cases, provenance = generate_fused_cases(context)

    rendered = " ".join(
        value
        for case in cases
        for value in [case.name, case.objective, *case.expected_results, *(str(step) for step in case.steps)]
    )
    assert cases
    assert all(case.steps and case.expected_results and case.evidence_refs for case in cases)
    assert not {"商品", "订单", "支付"}.intersection(rendered)
    assert provenance.generation_kernel == "v2_fused"
    assert provenance.contract_ids == ["contract_login"]


def test_fused_kernel_normalizes_positive_and_isolates_one_invalid_item() -> None:
    """模型的兼容枚举和单条坏数据不能阻断其他候选。"""

    payload = [
        {
            "name": f"登录场景 {index}",
            "objective": "验证用户登录",
            "dimension": f"business_scenario_{index}",
            "scenario_type": "positive",
            "preconditions": [],
            "steps": [{"order": 1, "action": "提交账号密码", "method": "POST", "path": "/api/login"}],
            "expected_results": ["登录成功"],
        }
        for index in range(9)
    ]
    payload.append({
        "name": "损坏候选", "objective": "验证用户登录",
        "dimension": "broken", "scenario_type": "positive",
        "steps": "not-a-list", "expected_results": ["登录成功"],
    })

    cases, provenance = generate_fused_cases(
        GenerationContext.from_contract(login_contract(), contract_version=1),
        model=lambda _prompt: __import__("json").dumps(payload, ensure_ascii=False),
        attempt_id="attempt_v23",
    )

    llm_cases = [item for item in cases if item.source == "llm"]
    assert len(llm_cases) == 9
    assert {item.scenario_type for item in llm_cases} == {"normal"}
    assert provenance.llm_case_count == 9
    assert provenance.rejected_case_count == 1
    assert provenance.rejections[0].error_code == "CASE_PROMPT_ITEM_INVALID"


def test_grounding_rejects_unrelated_llm_business_case() -> None:
    case = BaseTestCase(
        case_id="case_order",
        contract_id="contract_login",
        name="订单支付",
        objective="验证订单支付成功",
        dimension="business_scenario",
        source="llm",
        steps=[{"action": "提交订单并支付"}],
        expected_results=["支付成功"],
    )
    report = assess_case_grounding(case, login_contract())
    assert not report.hard_gate_passed
    assert any(item.code == "CASE_BUSINESS_CONTEXT_UNSUPPORTED" for item in report.blockers)


def test_legacy_gate_rejects_incomplete_execution_definition() -> None:
    issues = validate_legacy_executable({
        "request": {"method": "POST", "path": "/api/login", "body": None},
        "assertions": [],
        "generation_kernel": "v2_minimal",
    }, login_contract())
    assert {item.code for item in issues} >= {"CASE_REQUEST_INCOMPLETE", "LEGACY_VALIDATION_REQUIRED"}


def test_fused_executable_uses_v2_prompt_without_accepting_host() -> None:
    """融合执行定义可补全请求，但模型不能注入 Host 等越权字段。"""

    base = BaseTestCase(
        case_id="case_login", contract_id="contract_login", name="用户正常登录",
        objective="验证账号密码登录", dimension="positive", source="deterministic",
        status="confirmed", steps=[{"action": "提交账号密码"}], expected_results=["登录成功"],
        evidence_refs=[{"field_path": "request_body", "source_pointer": "login"}],
        generation_kernel="v2_fused", generation_sources=["deterministic"],
    )

    def generate(_prompt: str) -> str:
        return """{"request":{"method":"POST","path":"/api/login","headers":{},"query":{},"cookies":{},"body":{"username":"${{username}}","password":"${{password}}"}},"variables":[{"name":"username","source":"input","source_path":"body.username"},{"name":"password","source":"input","source_path":"body.password"}],"assertions":[{"operator":"status_code","expected":200}]}"""

    [case] = build_executable_cases([base], [login_contract()], request_generator=generate)
    assert case.validation_status == "ready"
    assert "api_case_generator.v2_prompt" in case.generation_sources
    assert case.prompt_sha256

    def inject_host(_prompt: str) -> str:
        return '{"request":{"method":"POST","path":"/api/login","host":"https://invalid.example"}}'

    [rejected] = build_executable_cases([base], [login_contract()], request_generator=inject_host)
    assert rejected.validation_status == "disabled"
    assert "CASE_PROMPT_OUTPUT_INVALID" in {item.code for item in rejected.validation_issues}


def test_legacy_workflow_can_opt_in_to_shared_fused_kernel() -> None:
    """旧导入路径保留，同时显式融合模式不再调用旧图中的模型节点。"""

    contract = login_contract()
    generated = ApiBaseCaseGeneratorWorkFlow().generator_base_case({
        "generation_kernel": "v2_fused", "v2_contract": contract.model_dump(mode="json"),
        "contract_version": 1,
    })
    assert generated["cases"]
    assert all(item["generation_kernel"] == "v2_fused" for item in generated["cases"])

    base = BaseTestCase.model_validate({**generated["cases"][0], "status": "confirmed"})
    executable = ApiRunCaseGeneratorWorkFlow.generator_api_case({
        "generation_kernel": "v2_fused", "v2_contract": contract.model_dump(mode="json"),
        "base_case": base.model_dump(mode="json"), "generator_count": 0,
    })
    assert executable["api_case"]["request"]["url"] == "/api/login"
    assert executable["api_case"]["request"]["base_url"] == "${{base_url}}"
