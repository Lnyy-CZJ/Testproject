"""从已确认基础用例生成规范化用例，并执行静态验证。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict, deque
from typing import Any, Callable

from agents.api_test.cases.grounding import extract_template_variables, validate_legacy_executable
from agents.api_test.cases.script_policy import validate_script
from services.api_agent.models import (
    ApiContract, AssertionDefinition, BaseTestCase, ExecutableCase, ExecutableRequest, ReviewIssue,
    VariableDefinition,
)


VARIABLE = re.compile(r"\$\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}")


def build_executable_cases(
    base_cases: list[BaseTestCase], contracts: list[ApiContract], *, version: int = 1,
    request_generator: Callable[[str], Any] | None = None,
) -> list[ExecutableCase]:
    """把已确认基础用例转换为不含 Host 的最小可执行用例。"""

    by_id = {item.contract_id: item for item in contracts if item.status == "confirmed"}
    result = []
    positive_by_contract = {
        item.contract_id: f"exec_{item.case_id.removeprefix('case_')}"
        for item in base_cases if item.status == "confirmed" and item.dimension == "positive"
    }
    for base in base_cases:
        contract = by_id.get(base.contract_id)
        if base.status != "confirmed" or not contract:
            continue
        request, variables = _build_request(base, contract)
        assertions, observations = _build_expectations(base, contract)
        dependency_contracts = {item.contract_id for item in [*base.dependencies, *contract.dependencies]}
        preconditions = [positive_by_contract[item] for item in sorted(dependency_contracts) if item in positive_by_contract]
        executable = ExecutableCase(
            executable_case_id=f"exec_{base.case_id.removeprefix('case_')}",
            version=version, base_case_id=base.case_id, contract_id=contract.contract_id,
            name=base.name, risk_level=base.risk_level,
            high_risk_approved=base.risk_level != "high" or base.status == "confirmed",
            document_sla_ms=contract.sla_ms,
            request=request,
            precondition_case_ids=preconditions,
            assertions=assertions,
            variables=variables,
            observation_targets=observations,
            generation_kernel=base.generation_kernel,
            generation_sources=base.generation_sources,
            prompt_sha256=base.prompt_sha256,
            validation_status="pending", enabled=False,
        )
        if request_generator is not None and base.generation_kernel == "v2_fused":
            _apply_generated_definition(executable, base, contract, request_generator)
        result.append(executable)
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
        issues: list[ReviewIssue] = list(case.validation_issues)
        contract = contracts_by_id.get(case.contract_id)
        if not contract or contract.status != "confirmed":
            issues.append(_issue("contract_id", "CONTRACT_NOT_CONFIRMED", "关联契约不存在或未确认"))
        elif (case.request.method, case.request.path) != (contract.method, contract.path):
            normalized_path = re.sub(r"\$\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}", r"{\1}", case.request.path)
            if case.request.method != contract.method or normalized_path != contract.path:
                issues.append(_issue("request", "CONTRACT_REQUEST_MISMATCH", "请求 method/path 与契约不一致"))
        missing_dependencies = sorted(set(case.precondition_case_ids) - case_ids)
        if missing_dependencies:
            issues.append(_issue("precondition_case_ids", "DEPENDENCY_MISSING", f"依赖用例不存在: {missing_dependencies}"))
        if case.executable_case_id in cycle_nodes:
            issues.append(_issue("precondition_case_ids", "DEPENDENCY_CYCLE", "用例依赖存在循环"))
        if any(assertion.operator not in allowed_assertions for assertion in case.assertions):
            issues.append(_issue("assertions", "ASSERTION_UNSUPPORTED", "存在不支持的断言操作符"))
        defined = {item.name for item in case.variables}
        used = extract_template_variables(case.request.model_dump(mode="json"))
        missing_variables = sorted(used - defined)
        if missing_variables:
            issues.append(_issue("variables", "VARIABLE_SOURCE_MISSING", f"变量缺少来源: {missing_variables}"))
        issues.extend(validate_script(case.setup_script, "setup_script"))
        issues.extend(validate_script(case.teardown_script, "teardown_script"))
        if case.risk_level == "high" and not case.high_risk_approved:
            issues.append(_issue("risk_level", "HIGH_RISK_NOT_APPROVED", "高风险用例尚未获得人工执行批准"))
        if contract and contract.request_body and contract.request_body.required and case.request.body is None:
            issues.append(_issue("request.body", "CASE_REQUEST_INCOMPLETE", "契约要求请求体，当前执行定义 body 为空"))
        documented_statuses = {item.status_code for item in contract.responses} if contract else set()
        for assertion in case.assertions:
            if assertion.operator == "status_code" and str(assertion.expected) not in documented_statuses:
                issues.append(_issue("assertions", "CASE_EXPECTATION_UNGROUNDED", "状态码断言没有契约依据"))
        if not case.assertions and not case.observation_targets:
            issues.append(_issue("assertions", "CASE_EXPECTATION_UNGROUNDED", "执行定义没有断言或探索观察目标"))
        if case.generation_kernel in {"legacy", "v2_minimal"} and contract:
            issues.extend(validate_legacy_executable(case.model_dump(mode="json"), contract))
        case.validation_issues = issues
        case.validation_status = "disabled" if issues else "ready"
        case.enabled = not issues
    return cases


def executable_prompt_sha256() -> str:
    """返回平台可执行定义 Prompt 的稳定 SHA。"""

    from agents.api_test.prompts.api_case_generator import v2_prompt

    return hashlib.sha256(v2_prompt.template.encode("utf-8")).hexdigest()


def _apply_generated_definition(
    executable: ExecutableCase,
    base: BaseTestCase,
    contract: ApiContract,
    request_generator: Callable[[str], Any],
) -> None:
    """合并模型生成的白名单执行字段；非法输出保留确定性结果并增加阻断。"""

    from agents.api_test.prompts.api_case_generator import v2_prompt

    context = {
        "contract": contract.model_dump(mode="json", exclude={"servers"}),
        "base_case": base.model_dump(mode="json"),
        "deterministic_request": executable.request.model_dump(mode="json"),
    }
    prompt = v2_prompt.format(generation_context=json.dumps(context, ensure_ascii=False))
    try:
        raw = request_generator(prompt)
        raw = getattr(raw, "content", raw)
        if isinstance(raw, str):
            raw = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        if not isinstance(raw, dict) or not isinstance(raw.get("request"), dict):
            raise ValueError("模型未返回 request 对象")
        request = ExecutableRequest.model_validate(raw["request"])
        executable.request = request
        if isinstance(raw.get("preconditions"), list):
            executable.precondition_case_ids = [str(value) for value in raw["preconditions"] if str(value).startswith("exec_")]
        if isinstance(raw.get("variables"), list):
            executable.variables = [VariableDefinition.model_validate(value) for value in raw["variables"]]
        if isinstance(raw.get("assertions"), list):
            executable.assertions = [AssertionDefinition.model_validate(value) for value in raw["assertions"]]
        if isinstance(raw.get("observation_targets"), list):
            executable.observation_targets = [str(value) for value in raw["observation_targets"] if str(value).strip()]
        executable.generation_sources = list(dict.fromkeys([*executable.generation_sources, "api_case_generator.v2_prompt"]))
        executable.prompt_sha256 = executable_prompt_sha256()
    except (TypeError, ValueError, json.JSONDecodeError):
        executable.validation_issues.append(_issue(
            "request", "CASE_PROMPT_OUTPUT_INVALID", "模型执行定义不符合白名单 Schema，已保留确定性定义但禁止执行",
        ))


def _sample_value(schema: dict[str, Any], name: str) -> Any:
    """优先使用契约示例；否则生成带显式来源的输入变量。"""

    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    return f"${{{{{name}}}}}"


def _build_request(base: BaseTestCase, contract: ApiContract) -> tuple[ExecutableRequest, list[VariableDefinition]]:
    """根据已确认契约构造 Header、Query、Cookie、Path 和 Body。"""

    headers: dict[str, Any] = {}
    query: dict[str, Any] = {}
    cookies: dict[str, Any] = {}
    path = contract.path
    variables: dict[str, VariableDefinition] = {}
    for parameter in contract.parameters:
        value = parameter.example if parameter.example is not None else _sample_value(parameter.schema_definition, parameter.name)
        if isinstance(value, str) and value.startswith("${{"):
            variables[parameter.name] = VariableDefinition(name=parameter.name, source="input", source_path=parameter.name)
        if parameter.location == "header":
            headers[parameter.name] = value
        elif parameter.location == "query":
            query[parameter.name] = value
        elif parameter.location == "cookie":
            cookies[parameter.name] = value
        elif parameter.location == "path":
            path = path.replace(f"{{{parameter.name}}}", str(value))

    body: Any = None
    if contract.request_body:
        content = next(iter(contract.request_body.content.values()), {})
        schema = content.get("schema", content) if isinstance(content, dict) else {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        body = {}
        for name, definition in properties.items():
            value = _sample_value(definition if isinstance(definition, dict) else {}, name)
            body[name] = value
            if isinstance(value, str) and value.startswith("${{"):
                variables[name] = VariableDefinition(name=name, source="input", source_path=f"body.{name}")
        if not properties and contract.request_body.required:
            body = None

    request = ExecutableRequest(
        method=contract.method, path=path, headers=headers, query=query, cookies=cookies, body=body,
    )
    for mutation in base.parameter_mutations:
        if mutation.strategy != "missing":
            continue
        name = mutation.field_path.rsplit(".", 1)[-1]
        headers.pop(name, None)
        query.pop(name, None)
        cookies.pop(name, None)
        if isinstance(request.body, dict):
            request.body.pop(name, None)
    return request, list(variables.values())


def _build_expectations(base: BaseTestCase, contract: ApiContract) -> tuple[list[AssertionDefinition], list[str]]:
    """只使用文档响应码生成断言；无依据时降级为探索观察。"""

    statuses = [item.status_code for item in contract.responses if item.status_code != "default"]
    if base.scenario_type == "exploratory" or not statuses:
        return [], base.expected_results or ["记录实际状态码与响应结构，等待人工复核"]
    if base.dimension.startswith("response:"):
        expected = base.dimension.split(":", 1)[1]
    elif base.scenario_type == "negative":
        expected = next((value for value in statuses if not value.startswith("2")), statuses[0])
    else:
        expected = next((value for value in statuses if value.startswith("2")), statuses[0])
    return [AssertionDefinition(operator="status_code", expected=int(expected) if expected.isdigit() else expected)], []


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
