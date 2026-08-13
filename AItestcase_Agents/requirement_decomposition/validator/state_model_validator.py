"""state_model 合法性校验。"""

from __future__ import annotations

from requirement_decomposition.models.schema import StateModel
from requirement_decomposition.validator.schema_validator import ValidationResult


def validate_state_model(
    state_model: StateModel,
    requirement_id: str = "",
) -> ValidationResult:
    """校验状态集合、流转状态、trigger 和重复流转。"""

    issues: list[dict] = []
    states = set(state_model.states)
    seen_transitions: set[tuple[str, str, str, bool]] = set()

    for transition in state_model.transitions:
        if transition.from_state not in states or transition.to_state not in states:
            issues.append(
                {
                    "issue_type": "state_transition_unknown_state",
                    "requirement_id": requirement_id,
                    "field": "requirement_facts.state_model.transitions",
                    "value": f"{transition.from_state} -> {transition.to_state}",
                    "reason": "from/to 必须存在于 states 中",
                }
            )
        if not transition.trigger.strip():
            issues.append(
                {
                    "issue_type": "state_transition_empty_trigger",
                    "requirement_id": requirement_id,
                    "field": "requirement_facts.state_model.transitions.trigger",
                    "value": f"{transition.from_state} -> {transition.to_state}",
                    "reason": "状态流转 trigger 不允许为空",
                }
            )

        key = (
            transition.from_state,
            transition.to_state,
            transition.trigger,
            transition.valid,
        )
        if key in seen_transitions:
            issues.append(
                {
                    "issue_type": "state_transition_duplicate",
                    "requirement_id": requirement_id,
                    "field": "requirement_facts.state_model.transitions",
                    "value": f"{transition.from_state} -> {transition.to_state}",
                    "reason": "同一状态流转不能重复",
                }
            )
        seen_transitions.add(key)

    return ValidationResult(passed=not issues, issues=issues)
