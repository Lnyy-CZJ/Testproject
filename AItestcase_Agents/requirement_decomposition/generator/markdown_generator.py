"""Requirement Markdown 输出生成器。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from requirement_decomposition.models.schema import Requirement


def write_requirement_markdown(requirements: list[Requirement], output_dir: str) -> None:
    """为每个 Requirement 生成明细 Markdown，并生成总览文档。"""

    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    for requirement in requirements:
        content = _render_requirement(requirement)
        (directory / f"{requirement.requirement_id}.md").write_text(content, encoding="utf-8")
    (directory / "requirements_summary.md").write_text(
        _render_summary(requirements),
        encoding="utf-8",
    )


def _render_summary(requirements: list[Requirement]) -> str:
    """渲染 Requirement 总览 Markdown。"""

    status_counter = Counter(requirement.status for requirement in requirements)
    grouped: dict[tuple[str, str], list[Requirement]] = {}
    for requirement in requirements:
        grouped.setdefault((requirement.module or "-", requirement.feature or "-"), []).append(requirement)

    lines = [
        "# 需求拆解总览",
        "",
        "## 汇总",
        "",
        f"- Requirement 总数: {len(requirements)}",
        f"- confirmed_candidate: {status_counter.get('confirmed_candidate', 0)}",
        f"- draft: {status_counter.get('draft', 0)}",
        f"- confirmed: {status_counter.get('confirmed', 0)}",
        "",
        "## 按功能聚合",
        "",
    ]
    for index, ((module, feature), items) in enumerate(grouped.items(), start=1):
        tags = _group_status_tags(items)
        lines.extend(
            [
                f"### SEED-{index:03d} {module} / {feature}",
                "",
                f"- 关联 REQ: {', '.join(item.requirement_id for item in items)}",
                f"- 状态标签: {', '.join(tags) if tags else '已确认'}",
                f"- 测试对象: {_join_unique(_collect_objects(items))}",
                f"- 风险标签: {_join_unique(_collect_risk_tags(items))}",
                "",
                "#### 需求点",
                "",
            ]
        )
        lines.extend(f"- [{item.requirement_id}](./{item.requirement_id}.md) {item.title}" for item in items)
        uncertain = _collect_uncertain_items(items)
        if uncertain:
            lines.extend(["", "#### 未确定 / 待确认", ""])
            lines.extend(f"- {item}" for item in uncertain)
        lines.append("")
    return "\n".join(lines)


def _render_requirement(requirement: Requirement) -> str:
    """渲染单个 Requirement。"""

    lines = [
        f"# {requirement.requirement_id} {requirement.title}",
        "",
        f"- 状态: {requirement.status}",
        f"- 领域: {requirement.domain or '-'}",
        f"- 模块: {requirement.module or '-'}",
        f"- 功能: {requirement.feature or '-'}",
        "",
        "## 描述",
        "",
        requirement.description or "-",
        "",
        "## 需求事实",
        "",
        "### 测试对象",
        "",
        *_render_test_objects(requirement),
        "",
        "### 约束",
        "",
        *_render_constraints(requirement),
        "",
        "### 权限",
        "",
        *_render_permissions(requirement),
        "",
        "### 状态模型",
        "",
        *_render_state_model(requirement),
        "",
        "### GWT 验收标准",
        "",
        *_render_acceptance_criteria(requirement),
        "",
        "## 测试设计建议",
        "",
        *_render_suggestions(requirement),
        "",
        "## Grounding Check",
        "",
        f"- 通过: {requirement.grounding_check.passed}",
        f"- unsupported_items: {len(requirement.grounding_check.unsupported_items)}",
        "",
        "## 来源",
        "",
        f"- source_id: {requirement.source_trace.source_id}",
        f"- section_id: {requirement.source_trace.section_id}",
        "",
        "```text",
        requirement.source_trace.quote,
        "```",
        "",
    ]
    return "\n".join(lines)


def _group_status_tags(requirements: list[Requirement]) -> list[str]:
    """生成一组 Requirement 的状态标签。"""

    tags: list[str] = []
    for requirement in requirements:
        if requirement.status in {"draft", "changed"}:
            _append_unique(tags, "未确定")
        if requirement.unresolved:
            _append_unique(tags, "存在未确定项")
        if requirement.ambiguity_notes:
            _append_unique(tags, "存在多义")
        if requirement.conflict_items:
            _append_unique(tags, "存在冲突")
        if requirement.grounding_check.unsupported_items:
            _append_unique(tags, "存在无证据建议")
        if requirement.status == "confirmed_candidate":
            _append_unique(tags, "候选确认")
        if requirement.status == "confirmed":
            _append_unique(tags, "已确认")
    return tags


def _collect_objects(requirements: list[Requirement]) -> list[str]:
    """收集测试对象名称。"""

    values: list[str] = []
    for requirement in requirements:
        for item in requirement.requirement_facts.test_objects:
            _append_unique(values, item.name)
    return values


def _collect_risk_tags(requirements: list[Requirement]) -> list[str]:
    """收集风险标签。"""

    values: list[str] = []
    for requirement in requirements:
        for item in requirement.test_design_suggestions.risk_tags:
            _append_unique(values, item)
    return values


def _collect_uncertain_items(requirements: list[Requirement]) -> list[str]:
    """收集未确定和待确认信息。"""

    values: list[str] = []
    for requirement in requirements:
        if requirement.status not in {"confirmed", "confirmed_candidate"}:
            values.append(f"{requirement.requirement_id}: 状态为 {requirement.status}")
        for item in requirement.unresolved:
            values.append(f"{requirement.requirement_id}: 未确定 - {_issue_text(item)}")
        for item in requirement.ambiguity_notes:
            values.append(f"{requirement.requirement_id}: 多义 - {_issue_text(item)}")
        for item in requirement.conflict_items:
            values.append(f"{requirement.requirement_id}: 冲突 - {_issue_text(item)}")
        for item in requirement.grounding_check.unsupported_items:
            field = item.get("field", "unknown")
            value = item.get("value", "")
            values.append(f"{requirement.requirement_id}: 缺少原文证据 - {field}: {value}")
    return values


def _issue_text(item: dict) -> str:
    """将 issue 字典转成简短文本。"""

    field = item.get("field") or item.get("type") or "unknown"
    reason = item.get("reason") or item.get("description") or item.get("value") or str(item)
    return f"{field}: {reason}"


def _join_unique(values: list[str]) -> str:
    """格式化去重列表。"""

    return ", ".join(values) if values else "-"


def _append_unique(values: list[str], item: str) -> None:
    """追加去重文本。"""

    text = item.strip()
    if text and text not in values:
        values.append(text)


def _render_test_objects(requirement: Requirement) -> list[str]:
    """渲染测试对象列表。"""

    objects = requirement.requirement_facts.test_objects
    if not objects:
        return ["- 无"]
    return [
        f"- {item.name}（{item.type}）"
        + (f": {', '.join(item.values)}" if item.values else "")
        for item in objects
    ]


def _render_constraints(requirement: Requirement) -> list[str]:
    """渲染约束列表。"""

    constraints = requirement.requirement_facts.constraints
    if not constraints:
        return ["- 无"]
    return [
        f"- [{item.constraint_type}] {item.object}: {item.rule}"
        + (f"（{item.test_dimension}）" if item.test_dimension else "")
        for item in constraints
    ]


def _render_permissions(requirement: Requirement) -> list[str]:
    """渲染权限规则。"""

    permissions = requirement.requirement_facts.permissions
    if not permissions:
        return ["- 无"]
    return [f"- {item.role}: {item.rule}" for item in permissions]


def _render_state_model(requirement: Requirement) -> list[str]:
    """渲染状态模型。"""

    state_model = requirement.requirement_facts.state_model
    lines = [f"- 实体: {state_model.entity or '-'}"]
    lines.append(
        "- 状态: " + (", ".join(state_model.states) if state_model.states else "无")
    )
    if state_model.transitions:
        lines.append("- 流转:")
        lines.extend(
            f"  - {item.from_state} -> {item.to_state} / {item.trigger} / valid={item.valid}"
            for item in state_model.transitions
        )
    return lines


def _render_acceptance_criteria(requirement: Requirement) -> list[str]:
    """渲染 GWT 验收标准。"""

    criteria = requirement.requirement_facts.acceptance_criteria
    if not criteria:
        return ["- 无"]
    lines: list[str] = []
    for index, item in enumerate(criteria, start=1):
        lines.extend(
            [
                f"- AC-{index}",
                f"  - Given: {item.given}",
                f"  - When: {item.when}",
                f"  - Then: {item.then}",
            ]
        )
    return lines


def _render_suggestions(requirement: Requirement) -> list[str]:
    """渲染测试设计建议。"""

    suggestions = requirement.test_design_suggestions
    lines: list[str] = []
    if suggestions.risk_tags:
        lines.append("- 风险标签: " + ", ".join(suggestions.risk_tags))
    if suggestions.test_generation_hints:
        lines.append("- 测试生成提示:")
        lines.extend(f"  - {item}" for item in suggestions.test_generation_hints)
    if suggestions.negative_suggestions:
        lines.append("- 负向建议:")
        lines.extend(f"  - {item}" for item in suggestions.negative_suggestions)
    if suggestions.boundary_suggestions:
        lines.append("- 边界建议:")
        lines.extend(f"  - {item}" for item in suggestions.boundary_suggestions)
    return lines or ["- 无"]
