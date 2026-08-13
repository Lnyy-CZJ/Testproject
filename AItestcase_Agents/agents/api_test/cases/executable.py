"""从已确认基础用例生成规范化用例，并执行静态验证。"""

from __future__ import annotations

import re
from collections import defaultdict, deque

from agents.api_test.cases.script_policy import validate_script
from services.api_agent.models import (
    ApiContract, AssertionDefinition, BaseTestCase, ExecutableCase, ExecutableRequest, ReviewIssue,
)


VARIABLE = re.compile(r"\$\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}")


def build_executable_cases(
    base_cases: list[BaseTestCase], contracts: list[ApiContract], *, version: int = 1,
) -> list[ExecutableCase]:
    """把已确认基础用例转换为不含 Host 的最小可执行用例。"""

    by_id = {item.contract_id: item for item in contracts if item.status == "confirmed"}
    result = []
    for base in base_cases:
        contract = by_id.get(base.contract_id)
        if base.status != "confirmed" or not contract:
            continue
        result.append(ExecutableCase(
            executable_case_id=f"exec_{base.case_id.removeprefix('case_')}",
            version=version, base_case_id=base.case_id, contract_id=contract.contract_id,
            name=base.name, risk_level=base.risk_level,
            high_risk_approved=base.risk_level != "high" or base.status == "confirmed",
            document_sla_ms=contract.sla_ms,
            request=ExecutableRequest(method=contract.method, path=contract.path),
            assertions=[AssertionDefinition(operator="status_code", expected=200)],
            validation_status="pending", enabled=False,
        ))
    return validate_executable_cases(result, contracts)


def validate_executable_cases(
    cases: list[ExecutableCase], contracts: list[ApiContract],
) -> list[ExecutableCase]:
    """校验契约一致性、变量、依赖、断言和 AST 策略。"""

    contracts_by_id = {item.contract_id: item for item in contracts}
    case_ids = {item.executable_case_id for item in cases}
    cycle_nodes = _cycle_nodes(cases)
    allowed_assertions = {"equals", "not_equals", "contains", "exists", "status_code", "schema"}
    for case in cases:
        issues: list[ReviewIssue] = []
        contract = contracts_by_id.get(case.contract_id)
        if not contract or contract.status != "confirmed":
            issues.append(_issue("contract_id", "CONTRACT_NOT_CONFIRMED", "关联契约不存在或未确认"))
        elif (case.request.method, case.request.path) != (contract.method, contract.path):
            issues.append(_issue("request", "CONTRACT_REQUEST_MISMATCH", "请求 method/path 与契约不一致"))
        missing_dependencies = sorted(set(case.precondition_case_ids) - case_ids)
        if missing_dependencies:
            issues.append(_issue("precondition_case_ids", "DEPENDENCY_MISSING", f"依赖用例不存在: {missing_dependencies}"))
        if case.executable_case_id in cycle_nodes:
            issues.append(_issue("precondition_case_ids", "DEPENDENCY_CYCLE", "用例依赖存在循环"))
        if any(assertion.operator not in allowed_assertions for assertion in case.assertions):
            issues.append(_issue("assertions", "ASSERTION_UNSUPPORTED", "存在不支持的断言操作符"))
        defined = {item.name for item in case.variables}
        used = set(VARIABLE.findall(str(case.request.model_dump())))
        missing_variables = sorted(used - defined)
        if missing_variables:
            issues.append(_issue("variables", "VARIABLE_SOURCE_MISSING", f"变量缺少来源: {missing_variables}"))
        issues.extend(validate_script(case.setup_script, "setup_script"))
        issues.extend(validate_script(case.teardown_script, "teardown_script"))
        if case.risk_level == "high" and not case.high_risk_approved:
            issues.append(_issue("risk_level", "HIGH_RISK_NOT_APPROVED", "高风险用例尚未获得人工执行批准"))
        case.validation_issues = issues
        case.validation_status = "disabled" if issues else "ready"
        case.enabled = not issues
    return cases


def _cycle_nodes(cases: list[ExecutableCase]) -> set[str]:
    """使用 Kahn 算法找出依赖环中的用例 ID。"""

    outgoing: dict[str, set[str]] = defaultdict(set)
    indegree = {item.executable_case_id: 0 for item in cases}
    for item in cases:
        for dependency in item.precondition_case_ids:
            if dependency in indegree:
                outgoing[dependency].add(item.executable_case_id)
                indegree[item.executable_case_id] += 1
    queue = deque(key for key, value in indegree.items() if value == 0)
    visited = set()
    while queue:
        current = queue.popleft()
        visited.add(current)
        for child in outgoing[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    return set(indegree) - visited


def _issue(field: str, code: str, message: str) -> ReviewIssue:
    """构造静态验证阻断问题。"""

    return ReviewIssue(code=code, field_path=field, message=message, severity="blocker")
