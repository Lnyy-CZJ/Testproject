"""Grounding Check。"""

from __future__ import annotations

from requirement_decomposition.models.schema import FieldEvidence, GroundingCheck

_FACT_FIELDS = {
    "test_objects",
    "constraints",
    "state_model",
    "permissions",
    "acceptance_criteria",
}


def run_grounding_check(field_evidence: list[FieldEvidence]) -> GroundingCheck:
    """根据字段级 evidence 生成 Grounding Check 结果。"""

    unsupported_items = [
        {
            "field": evidence.field,
            "value": evidence.value,
            "reason": "原文缺少足够依据，不能作为需求事实",
            "action": "move_to_test_design_suggestions",
        }
        for evidence in field_evidence
        if evidence.field in _FACT_FIELDS and evidence.evidence_type != "explicit"
    ]
    return GroundingCheck(passed=not unsupported_items, unsupported_items=unsupported_items)
