"""confirmed_candidate 准入门禁。"""

from __future__ import annotations

from copy import deepcopy

from requirement_decomposition.models.schema import GroundingCheck, QualityGateConfig, Requirement
from requirement_decomposition.validator.risk_tag_validator import validate_risk_tags
from requirement_decomposition.validator.schema_validator import validate_requirement_schema
from requirement_decomposition.validator.state_model_validator import validate_state_model

_CRITICAL_EVIDENCE_FIELDS = {
    "title",
    "description",
    "test_objects",
    "constraints",
    "acceptance_criteria",
}


def apply_confirmed_gate(
    requirement: Requirement,
    quality_gate: QualityGateConfig | None = None,
) -> Requirement:
    """根据准入门槛设置 Requirement 状态。

    第四阶段只自动进入 `confirmed_candidate`，不做人工 `confirmed`。
    """

    gate = quality_gate or QualityGateConfig()
    processed = deepcopy(requirement)
    blockers = _confirmed_gate_blockers(processed, gate)
    processed.status = "draft" if blockers else "confirmed_candidate"
    return processed


def _confirmed_gate_blockers(
    requirement: Requirement,
    gate: QualityGateConfig,
) -> list[dict]:
    """返回阻断 confirmed_candidate 的原因。"""

    blockers: list[dict] = []
    schema_result = validate_requirement_schema(requirement)
    if gate.require_schema_valid and not schema_result.passed:
        blockers.extend(schema_result.issues)

    if gate.require_source_trace and not requirement.source_trace.quote.strip():
        blockers.append({"issue_type": "missing_source_trace", "field": "source_trace"})

    if gate.require_field_evidence:
        evidence_fields = {
            item.field for item in requirement.field_evidence if item.evidence_type == "explicit"
        }
        missing_fields = sorted(_CRITICAL_EVIDENCE_FIELDS - evidence_fields)
        if missing_fields:
            blockers.append(
                {
                    "issue_type": "missing_field_evidence",
                    "field": "field_evidence",
                    "value": missing_fields,
                }
            )

    if gate.require_test_objects and not requirement.requirement_facts.test_objects:
        blockers.append({"issue_type": "missing_test_objects", "field": "test_objects"})
    if gate.require_constraints and not requirement.requirement_facts.constraints:
        blockers.append({"issue_type": "missing_constraints", "field": "constraints"})
    if gate.require_gwt and not requirement.requirement_facts.acceptance_criteria:
        blockers.append({"issue_type": "missing_gwt", "field": "acceptance_criteria"})
    grounding_check = _grounding_check(requirement)
    if gate.require_grounding_check_passed and not grounding_check.passed:
        blockers.append({"issue_type": "grounding_check_failed", "field": "grounding_check"})

    unsupported_count = len(grounding_check.unsupported_items)
    if unsupported_count > gate.max_unsupported_facts:
        blockers.append(
            {
                "issue_type": "unsupported_facts_exceeded",
                "field": "grounding_check.unsupported_items",
                "value": unsupported_count,
            }
        )
    if requirement.unresolved:
        blockers.append({"issue_type": "has_unresolved", "field": "unresolved"})
    if requirement.conflict_items:
        blockers.append({"issue_type": "has_conflict_items", "field": "conflict_items"})

    risk_result = validate_risk_tags(requirement)
    if not risk_result.passed:
        blockers.extend(risk_result.issues)

    state_result = validate_state_model(
        requirement.requirement_facts.state_model,
        requirement_id=requirement.requirement_id,
    )
    if not state_result.passed:
        blockers.extend(state_result.issues)

    return blockers


def _grounding_check(requirement: Requirement) -> GroundingCheck:
    """兼容测试或外部调用中传入 dict 的 grounding_check。"""

    if isinstance(requirement.grounding_check, GroundingCheck):
        return requirement.grounding_check
    return GroundingCheck.model_validate(requirement.grounding_check)
