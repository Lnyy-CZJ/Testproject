"""test_seed 输出生成器。"""

from __future__ import annotations

import json
from pathlib import Path

from requirement_decomposition.models.schema import Requirement, TestSeed, TestSeedRecord


def generate_test_seeds(
    requirements: list[Requirement],
    include_confirmed_candidate: bool = False,
) -> list[TestSeedRecord]:
    """按功能聚合生成测试点种子。

    功能说明:
        测试点生成智能体不应逐条消费 REQ 明细，而应按功能消费聚合后的上下文。
        draft 或存在未确认信息的 Requirement 不会被丢弃，会在 status_tags 和
        uncertain_items 中标记为“未确定”。

    参数说明:
        requirements (list[Requirement]): 全量 Requirement 明细。
        include_confirmed_candidate (bool): 保留兼容参数；聚合模式下不再过滤草稿，
            只用于旧调用方语义兼容。

    返回值:
        list[TestSeedRecord]: 按 module + feature 聚合后的 test_seed。
    """

    grouped: dict[tuple[str, str], list[Requirement]] = {}
    for requirement in requirements:
        key = (requirement.module or "-", requirement.feature or "-")
        grouped.setdefault(key, []).append(requirement)

    return [
        _requirements_to_group_seed(index, module, feature, items)
        for index, ((module, feature), items) in enumerate(grouped.items(), start=1)
    ]


def write_test_seeds_json(test_seeds: list[TestSeedRecord], path: str) -> None:
    """写入 test_seed JSON 文件。"""

    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            [seed.model_dump(mode="json", by_alias=True) for seed in test_seeds],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _requirements_to_group_seed(
    index: int,
    module: str,
    feature: str,
    requirements: list[Requirement],
) -> TestSeedRecord:
    """将同一功能下的多个 Requirement 聚合为 test_seed。"""

    seed = TestSeed()
    status_tags: list[str] = []
    source_sections: list[str] = []

    for requirement in requirements:
        facts = requirement.requirement_facts
        seed.requirement_titles.append(requirement.title)
        _extend_unique(seed.objects, [item.name for item in facts.test_objects])
        _extend_unique(seed.conditions, facts.preconditions)
        _extend_unique(seed.constraints, [item.rule for item in facts.constraints])
        _extend_unique(seed.permissions, [item.role for item in facts.permissions])
        _extend_unique(seed.risk_tags, requirement.test_design_suggestions.risk_tags)
        _extend_unique(seed.expected_results, [item.then for item in facts.acceptance_criteria])
        _extend_unique(
            seed.negative_suggestions,
            requirement.test_design_suggestions.negative_suggestions,
        )
        _extend_unique(seed.uncertain_items, _uncertain_items(requirement))
        _extend_unique(status_tags, _status_tags(requirement))
        _extend_unique(source_sections, [requirement.source_trace.section_id])

        for transition in facts.state_model.transitions:
            text = f"{transition.from_state} -> {transition.to_state}"
            if transition.valid:
                _extend_unique(seed.state_transitions, [text])
            else:
                _extend_unique(seed.invalid_state_transitions, [text])

    requirement_ids = [requirement.requirement_id for requirement in requirements]
    grounded_count = sum(1 for requirement in requirements if requirement.grounding_check.passed)
    has_suggestions = any(
        requirement.test_design_suggestions.risk_tags
        or requirement.test_design_suggestions.negative_suggestions
        or requirement.test_design_suggestions.boundary_suggestions
        or requirement.test_design_suggestions.test_generation_hints
        for requirement in requirements
    )

    return TestSeedRecord(
        requirement_id=f"SEED-{index:03d}",
        requirement_ids=requirement_ids,
        module=module,
        feature=feature,
        source_trace={
            "source_ids": sorted({requirement.source_trace.source_id for requirement in requirements}),
            "section_ids": source_sections,
        },
        test_seed=seed,
        evidence_summary={
            "fact_fields_grounded": grounded_count == len(requirements),
            "suggestions_include_inferred_items": has_suggestions,
        },
        status_tags=status_tags or ["已确认"],
    )


def _uncertain_items(requirement: Requirement) -> list[str]:
    """提取需要人工关注的未确定项。"""

    items: list[str] = []
    if requirement.status not in {"confirmed", "confirmed_candidate"}:
        items.append(f"{requirement.requirement_id}: 状态为 {requirement.status}")
    for item in requirement.unresolved:
        items.append(f"{requirement.requirement_id}: 未确定 - {_issue_text(item)}")
    for item in requirement.ambiguity_notes:
        items.append(f"{requirement.requirement_id}: 多义 - {_issue_text(item)}")
    for item in requirement.conflict_items:
        items.append(f"{requirement.requirement_id}: 冲突 - {_issue_text(item)}")
    for item in requirement.grounding_check.unsupported_items:
        field = item.get("field", "unknown")
        value = item.get("value", "")
        items.append(f"{requirement.requirement_id}: 缺少原文证据 - {field}: {value}")
    return items


def _status_tags(requirement: Requirement) -> list[str]:
    """生成聚合 test_seed 的状态标签。"""

    tags: list[str] = []
    if requirement.status in {"draft", "changed"}:
        tags.append("未确定")
    if requirement.unresolved:
        tags.append("存在未确定项")
    if requirement.ambiguity_notes:
        tags.append("存在多义")
    if requirement.conflict_items:
        tags.append("存在冲突")
    if requirement.grounding_check.unsupported_items:
        tags.append("存在无证据建议")
    if requirement.status == "confirmed_candidate":
        tags.append("候选确认")
    if requirement.status == "confirmed":
        tags.append("已确认")
    return tags


def _issue_text(item: dict) -> str:
    """将 issue 字典转成简短可读文本。"""

    if not item:
        return "-"
    field = item.get("field") or item.get("type") or "unknown"
    reason = item.get("reason") or item.get("description") or item.get("value") or str(item)
    return f"{field}: {reason}"


def _extend_unique(target: list[str], values) -> None:
    """追加去重字符串。"""

    for value in values:
        text = str(value).strip()
        if text and text not in target:
            target.append(text)


def _requirement_to_seed(requirement: Requirement) -> TestSeedRecord:
    """兼容旧调用：将单个 Requirement 转换为聚合 test_seed。"""

    facts = requirement.requirement_facts
    state_transitions = []
    invalid_state_transitions = []
    for transition in facts.state_model.transitions:
        text = f"{transition.from_state} -> {transition.to_state}"
        if transition.valid:
            state_transitions.append(text)
        else:
            invalid_state_transitions.append(text)

    seed = TestSeed(
        objects=[item.name for item in facts.test_objects],
        conditions=list(facts.preconditions),
        constraints=[item.rule for item in facts.constraints],
        state_transitions=state_transitions,
        invalid_state_transitions=invalid_state_transitions,
        permissions=[item.role for item in facts.permissions],
        risk_tags=list(requirement.test_design_suggestions.risk_tags),
        expected_results=[item.then for item in facts.acceptance_criteria],
        negative_suggestions=list(requirement.test_design_suggestions.negative_suggestions),
    )

    return TestSeedRecord(
        requirement_id=requirement.requirement_id,
        module=requirement.module,
        feature=requirement.feature,
        source_trace={
            "source_id": requirement.source_trace.source_id,
            "section_id": requirement.source_trace.section_id,
        },
        test_seed=seed,
        evidence_summary={
            "fact_fields_grounded": requirement.grounding_check.passed,
            "suggestions_include_inferred_items": bool(
                requirement.test_design_suggestions.risk_tags
                or requirement.test_design_suggestions.negative_suggestions
                or requirement.test_design_suggestions.boundary_suggestions
            ),
        },
    )
