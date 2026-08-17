"""质量评分与质量报告。"""

from __future__ import annotations

from requirement_decomposition.models.schema import QualityGateConfig, Requirement
from requirement_decomposition.validator.confirmed_gate_validator import _confirmed_gate_blockers
from requirement_decomposition.validator.risk_tag_validator import validate_risk_tags
from requirement_decomposition.validator.schema_validator import validate_requirement_schema
from requirement_decomposition.validator.state_model_validator import validate_state_model


def build_quality_report(
    requirements: list[Requirement],
    quality_gate: QualityGateConfig | None = None,
) -> dict:
    """生成质量报告。

    评分目标是给出稳定、可解释的门禁信号；confirmed 人工确认不在本阶段自动完成。
    """

    gate = quality_gate or QualityGateConfig()
    total = len(requirements)
    if total == 0:
        return _empty_report()

    schema_results = [validate_requirement_schema(requirement) for requirement in requirements]
    state_results = [
        validate_state_model(requirement.requirement_facts.state_model, requirement.requirement_id)
        for requirement in requirements
    ]
    risk_results = [validate_risk_tags(requirement) for requirement in requirements]
    gate_blockers = [
        issue
        for requirement in requirements
        for issue in _confirmed_gate_blockers(requirement, gate)
    ]

    issues = [
        issue
        for result in [*schema_results, *state_results, *risk_results]
        for issue in result.issues
    ]
    issues.extend(gate_blockers)
    issues.extend(_llm_self_check_issues(requirements))

    field_completeness = _rate(_has_required_fields(requirement) for requirement in requirements)
    traceability_rate = _rate(bool(requirement.source_trace.quote.strip()) for requirement in requirements)
    field_evidence_rate = _rate(bool(requirement.field_evidence) for requirement in requirements)
    grounding_check_rate = _rate(requirement.grounding_check.passed for requirement in requirements)
    llm_self_check_rate = _rate(requirement.llm_self_check.passed for requirement in requirements)
    schema_valid_rate = _rate(result.passed for result in schema_results)
    unsupported_facts = sum(
        len(requirement.grounding_check.unsupported_items) for requirement in requirements
    )

    unsupported_penalty = 1.0 if unsupported_facts == 0 else 0.0
    quality_score = round(
        field_completeness * 0.2
        + traceability_rate * 0.2
        + field_evidence_rate * 0.2
        + grounding_check_rate * 0.2
        + schema_valid_rate * 0.1
        + unsupported_penalty * 0.1,
        4,
    )

    return {
        "quality_score": quality_score,
        "field_completeness": field_completeness,
        "traceability_rate": traceability_rate,
        "field_evidence_rate": field_evidence_rate,
        "grounding_check_rate": grounding_check_rate,
        "llm_self_check_rate": llm_self_check_rate,
        "schema_valid_rate": schema_valid_rate,
        "unsupported_facts": unsupported_facts,
        "requirements_total": total,
        "confirmed_candidate_requirements": _count_status(requirements, "confirmed_candidate"),
        "confirmed_requirements": _count_status(requirements, "confirmed"),
        "draft_requirements": _count_status(requirements, "draft"),
        "quality_gate_passed": quality_score >= gate.min_quality_score and not gate_blockers,
        "issues": issues,
    }


def _empty_report() -> dict:
    """空输入质量报告。"""

    return {
        "quality_score": 0.0,
        "field_completeness": 0.0,
        "traceability_rate": 0.0,
        "field_evidence_rate": 0.0,
        "grounding_check_rate": 0.0,
        "llm_self_check_rate": 0.0,
        "schema_valid_rate": 0.0,
        "unsupported_facts": 0,
        "requirements_total": 0,
        "confirmed_candidate_requirements": 0,
        "confirmed_requirements": 0,
        "draft_requirements": 0,
        "quality_gate_passed": False,
        "issues": [],
    }


def _has_required_fields(requirement: Requirement) -> bool:
    """判断核心字段是否完整。"""

    facts = requirement.requirement_facts
    return all(
        [
            bool(requirement.title.strip()),
            bool(requirement.description.strip()),
            bool(requirement.source_trace.quote.strip()),
            bool(facts.test_objects),
            bool(facts.constraints),
            bool(facts.acceptance_criteria),
        ]
    )


def _rate(values) -> float:
    """计算布尔值通过率。"""

    value_list = list(values)
    if not value_list:
        return 0.0
    return round(sum(1 for value in value_list if value) / len(value_list), 4)


def _count_status(requirements: list[Requirement], status: str) -> int:
    """按状态计数。"""

    return sum(1 for requirement in requirements if requirement.status == status)


def _llm_self_check_issues(requirements: list[Requirement]) -> list[dict]:
    """汇总 LLM 自检发现的问题。"""

    issues: list[dict] = []
    for requirement in requirements:
        if requirement.llm_self_check.passed:
            continue
        for item in requirement.llm_self_check.issues:
            issues.append(
                {
                    "issue_type": "llm_self_check_failed",
                    "requirement_id": requirement.requirement_id,
                    "field": "llm_self_check",
                    "value": item,
                }
            )
    return issues
