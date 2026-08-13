"""覆盖矩阵有限补齐和可执行用例静态验证测试。"""

from __future__ import annotations

from agents.api_test.cases.coverage import build_coverage
from agents.api_test.cases.business_supplement import create_business_supplementer
from agents.api_test.cases.executable import validate_executable_cases
from services.api_agent.models import (
    ApiContract, BaseTestCase, ExecutableCase, ExecutableRequest, SourceTrace, VariableDefinition,
)


def confirmed_contract() -> ApiContract:
    """构造用例测试所需的已确认契约。"""

    return ApiContract(
        contract_id="contract_login", name="登录", method="POST", path="/login",
        source_trace=SourceTrace(source_id="doc", section_id="s", quote="POST /login"),
        status="confirmed",
    )


def test_deterministic_coverage_and_high_risk_default() -> None:
    cases, matrix = build_coverage([confirmed_contract()], contract_version=1)
    assert matrix.round_count == 0
    assert all(item.covered for item in matrix.items if item.required)
    assert any(item.dimension == "business_scenario" and not item.covered for item in matrix.items)
    high = next(item for item in cases if item.risk_level == "high")
    assert high.status == "draft"


def test_supplement_is_limited_to_three_rounds() -> None:
    calls = []
    contracts = []
    for index in range(3):
        contract = confirmed_contract().model_copy(deep=True)
        contract.contract_id = f"contract_{index}"
        contract.path = f"/login/{index}"
        contracts.append(contract)

    def supplement(missing, _cases, round_index):
        calls.append((len(missing), round_index))
        target = missing[0]
        return [BaseTestCase(
            case_id=f"case_business_{round_index}", contract_id=target.contract_id,
            name="业务补充", objective="补充业务语义", dimension=target.dimension,
            source="llm", status="confirmed_candidate",
        )]

    _cases, matrix = build_coverage(
        contracts, contract_version=1, supplementer=supplement, max_rounds=99,
    )
    assert [item[1] for item in calls] == [1, 2, 3]
    assert matrix.round_count == 3
    assert not [item for item in matrix.items if item.dimension == "business_scenario" and not item.covered]


def test_static_validator_blocks_variable_script_and_high_risk() -> None:
    contract = confirmed_contract()
    case = ExecutableCase(
        executable_case_id="exec_1", base_case_id="case_1", contract_id=contract.contract_id,
        name="危险用例", risk_level="high",
        request=ExecutableRequest(method="POST", path="/login", body={"token": "${{missing}}"}),
        setup_script="import subprocess\nsubprocess.run(['id'])",
        variables=[VariableDefinition(name="known", source="input")],
    )
    validated = validate_executable_cases([case], [contract])[0]
    codes = {item.code for item in validated.validation_issues}
    assert {"VARIABLE_SOURCE_MISSING", "SCRIPT_IMPORT_FORBIDDEN", "HIGH_RISK_NOT_APPROVED"} <= codes
    assert validated.validation_status == "disabled"


def test_dependency_cycle_is_disabled() -> None:
    contract = confirmed_contract()
    first = ExecutableCase(
        executable_case_id="exec_1", base_case_id="case_1", contract_id=contract.contract_id,
        name="one", risk_level="low", request=ExecutableRequest(method="POST", path="/login"),
        precondition_case_ids=["exec_2"],
    )
    second = first.model_copy(update={
        "executable_case_id": "exec_2", "base_case_id": "case_2", "precondition_case_ids": ["exec_1"],
    })
    result = validate_executable_cases([first, second], [contract])
    assert all(any(issue.code == "DEPENDENCY_CYCLE" for issue in item.validation_issues) for item in result)


def test_business_supplement_rejects_contract_changes_and_accepts_only_gap():
    missing = build_coverage([confirmed_contract()], contract_version=1)[1].items
    business_gap = [item for item in missing if item.dimension == "business_scenario"]
    supplement = create_business_supplementer(lambda _prompt: [
        {"contract_id": "contract_login", "dimension": "business_scenario", "name": "登录锁定", "objective": "验证连续失败后的锁定规则"},
        {"contract_id": "invented", "dimension": "business_scenario", "name": "幻觉接口", "objective": "不得接受"},
    ])
    generated = supplement(business_gap, [], 1)
    assert len(generated) == 1
    assert generated[0].contract_id == "contract_login"
    assert generated[0].source == "llm"
