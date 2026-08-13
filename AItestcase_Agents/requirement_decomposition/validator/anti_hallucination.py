"""防幻觉后处理。

该模块负责把 LLM 产出的候选事实与原文 evidence 对齐。无依据内容不会删除，
而是从 `requirement_facts` 移动到 `test_design_suggestions`，方便人工 review。
"""

from __future__ import annotations

from copy import deepcopy

from requirement_decomposition.llm.evidence_binder import bind_field_evidence
from requirement_decomposition.llm.grounding_checker import run_grounding_check
from requirement_decomposition.models.schema import Requirement


def apply_anti_hallucination(requirement: Requirement) -> Requirement:
    """应用 evidence、Grounding Check，并隔离 unsupported facts。"""

    processed = deepcopy(requirement)
    processed.field_evidence = bind_field_evidence(processed)
    processed.grounding_check = run_grounding_check(processed.field_evidence)
    _move_unsupported_facts_to_suggestions(processed)
    return processed


def _move_unsupported_facts_to_suggestions(requirement: Requirement) -> None:
    """将 Grounding Check 中的 unsupported facts 移到 suggestions。"""

    unsupported_by_field = _unsupported_values_by_field(requirement)
    if not unsupported_by_field:
        return

    facts = requirement.requirement_facts
    suggestions = requirement.test_design_suggestions

    if "test_objects" in unsupported_by_field:
        facts.test_objects = [
            item for item in facts.test_objects if item.name not in unsupported_by_field["test_objects"]
        ]
    if "constraints" in unsupported_by_field:
        facts.constraints = [
            item for item in facts.constraints if item.rule not in unsupported_by_field["constraints"]
        ]
    if "state_model" in unsupported_by_field:
        unsupported_state_values = unsupported_by_field["state_model"]
        facts.state_model.states = [
            state for state in facts.state_model.states if state not in unsupported_state_values
        ]
        facts.state_model.transitions = [
            transition
            for transition in facts.state_model.transitions
            if f"{transition.from_state} -> {transition.to_state}" not in unsupported_state_values
        ]
    if "permissions" in unsupported_by_field:
        facts.permissions = [
            item for item in facts.permissions if item.rule not in unsupported_by_field["permissions"]
        ]
    if "acceptance_criteria" in unsupported_by_field:
        facts.acceptance_criteria = [
            item
            for item in facts.acceptance_criteria
            if item.then not in unsupported_by_field["acceptance_criteria"]
        ]

    for field, values in unsupported_by_field.items():
        for value in values:
            hint = f"{field}: {value}"
            if hint not in suggestions.test_generation_hints:
                suggestions.test_generation_hints.append(hint)


def _unsupported_values_by_field(requirement: Requirement) -> dict[str, set[str]]:
    """按字段聚合 unsupported 值。"""

    unsupported_by_field: dict[str, set[str]] = {}
    for item in requirement.grounding_check.unsupported_items:
        field = item.get("field")
        value = item.get("value")
        if not field or not value:
            continue
        unsupported_by_field.setdefault(str(field), set()).add(str(value))
    return unsupported_by_field
