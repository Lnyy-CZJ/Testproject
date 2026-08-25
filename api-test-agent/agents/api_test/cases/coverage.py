"""基于已确认契约生成确定性覆盖矩阵，并限制 LLM 补齐轮次。"""

from __future__ import annotations

import hashlib
from typing import Callable

from services.api_agent.models import ApiContract, BaseTestCase, CoverageMatrix, CoverageMatrixItem, CoverageRoundSummary


Supplementer = Callable[[list[CoverageMatrixItem], list[BaseTestCase], int], list[BaseTestCase]]


def _stable_id(prefix: str, *parts: str) -> str:
    """由业务键生成任务内稳定 ID。"""

    return f"{prefix}_{hashlib.sha256('|'.join(parts).encode()).hexdigest()[:20]}"


def build_coverage(
    contracts: list[ApiContract],
    *,
    contract_version: int,
    supplementer: Supplementer | None = None,
    max_rounds: int = 3,
) -> tuple[list[BaseTestCase], CoverageMatrix]:
    """生成基础用例和结构化覆盖矩阵。

    参数说明:
        contracts: 仅接受 status=confirmed 的契约。
        contract_version: 当前 Review 契约版本。
        supplementer: 可选 LLM 补齐器，只接收仍缺失的结构化覆盖项。
        max_rounds: 固定上限，超过 3 会被截断。
    返回值:
        基础用例列表和覆盖矩阵；缺口不会触发无限循环。
    """

    confirmed = [item for item in contracts if item.status == "confirmed"]
    cases: list[BaseTestCase] = []
    matrix_items: list[CoverageMatrixItem] = []
    for contract in confirmed:
        _append_case(cases, matrix_items, contract, "positive", "正常请求", "验证接口按契约返回成功结果")
        # 业务语义无法由契约确定性推断，作为非阻断缺口交给 LLM 或人工补齐。
        matrix_items.append(CoverageMatrixItem(
            coverage_id=_stable_id("coverage", contract.contract_id, "business_scenario"),
            contract_id=contract.contract_id, dimension="business_scenario",
            rule="补充文档事实支持的业务场景", required=False, covered=False,
            decision_source="llm", confidence=0.0, gap_reason="确定性规则无法推断业务语义",
        ))
        for parameter in contract.parameters:
            if parameter.required:
                _append_case(
                    cases, matrix_items, contract,
                    f"required_missing:{parameter.location}:{parameter.name}",
                    f"必填参数 {parameter.name} 缺失", f"验证缺少 {parameter.name} 时返回明确错误",
                )
            schema = parameter.schema_definition
            if schema.get("type"):
                _append_case(
                    cases, matrix_items, contract,
                    f"type_invalid:{parameter.location}:{parameter.name}",
                    f"参数 {parameter.name} 类型错误", "验证参数类型校验",
                )
            if schema.get("enum"):
                _append_case(
                    cases, matrix_items, contract,
                    f"enum_boundary:{parameter.location}:{parameter.name}",
                    f"参数 {parameter.name} 枚举边界", "验证枚举合法值与非法值",
                )
            if any(key in schema for key in ("minimum", "maximum", "minLength", "maxLength")):
                _append_case(
                    cases, matrix_items, contract,
                    f"boundary:{parameter.location}:{parameter.name}",
                    f"参数 {parameter.name} 边界", "验证长度或数值边界",
                )
        if contract.request_body:
            content = next(iter(contract.request_body.content.values()), {})
            schema = content.get("schema", content) if isinstance(content, dict) else {}
            for name in schema.get("required", []) if isinstance(schema, dict) else []:
                _append_case(
                    cases, matrix_items, contract, f"required_missing:body:{name}",
                    f"必填请求体字段 {name} 缺失", f"验证缺少 {name} 时接口按契约拒绝请求",
                )
        if contract.security:
            _append_case(cases, matrix_items, contract, "auth_missing", "缺少鉴权", "验证未鉴权请求被拒绝")
        if contract.method in {"POST", "PUT", "PATCH", "DELETE"}:
            _append_case(
                cases, matrix_items, contract, "idempotency", "重复提交与幂等",
                "验证写接口重复请求的业务语义", risk="high",
            )
        for response in contract.responses:
            if response.status_code not in {"200", "201", "202", "204", "default"}:
                _append_case(
                    cases, matrix_items, contract, f"response:{response.status_code}",
                    f"文档错误响应 {response.status_code}", "验证文档声明的异常响应",
                )
    rounds = 0
    round_summaries: list[CoverageRoundSummary] = []
    previous_missing: tuple[str, ...] | None = None
    limit = min(3, max(0, max_rounds))
    while supplementer and rounds < limit:
        missing = tuple(item.coverage_id for item in matrix_items if not item.covered)
        if not missing or missing == previous_missing:
            break
        previous_missing = missing
        rounds += 1
        before = len(missing)
        generated = supplementer([item for item in matrix_items if not item.covered], cases, rounds) or []
        existing = {item.case_id for item in cases}
        for item in generated:
            if item.case_id not in existing:
                cases.append(item)
                existing.add(item.case_id)
        for matrix in matrix_items:
            matched = [case.case_id for case in cases if case.contract_id == matrix.contract_id and case.dimension == matrix.dimension]
            if matched:
                matrix.case_ids = matched
                matrix.covered = True
                matrix.generation_round = rounds if any(case.source == "llm" for case in cases if case.case_id in matched) else 0
        after = sum(1 for item in matrix_items if not item.covered)
        round_summaries.append(CoverageRoundSummary(
            round_number=rounds, missing_before=before, generated_count=len(generated),
            missing_after=after, stop_reason="没有新增用例" if not generated else "",
        ))
    missing = [item for item in matrix_items if item.required and not item.covered]
    return cases, CoverageMatrix(
        contract_version=contract_version, round_count=rounds,
        items=matrix_items, rounds=round_summaries, partial_success=bool(missing),
    )


def _append_case(
    cases: list[BaseTestCase],
    matrix: list[CoverageMatrixItem],
    contract: ApiContract,
    dimension: str,
    name: str,
    objective: str,
    *,
    risk: str = "low",
) -> None:
    """追加一条确定性覆盖项及其基础用例。"""

    case_id = _stable_id("case", contract.contract_id, dimension)
    coverage_id = _stable_id("coverage", contract.contract_id, dimension)
    status = "draft" if risk == "high" else "confirmed_candidate"
    cases.append(BaseTestCase(
        case_id=case_id, contract_id=contract.contract_id, name=name,
        objective=objective, dimension=dimension, risk_level=risk,
        steps=[{"action": "按契约构造请求", "contract_id": contract.contract_id}],
        expected_results=[objective], source="deterministic", status=status,
    ))
    matrix.append(CoverageMatrixItem(
        coverage_id=coverage_id, contract_id=contract.contract_id,
        dimension=dimension, rule=objective, covered=True, case_ids=[case_id],
    ))
