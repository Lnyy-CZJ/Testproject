"""字段级 evidence 绑定。"""

from __future__ import annotations

from requirement_decomposition.models.schema import EvidenceQuote, FieldEvidence, Requirement


def bind_field_evidence(requirement: Requirement) -> list[FieldEvidence]:
    """为 Requirement 的关键字段生成字段级 evidence。

    第三阶段先采用规则匹配：字段值能从 source quote 中获得足够依据时标记为
    explicit，否则标记为 inferred，后续由 Grounding Check 决定是否转入 suggestions。
    """

    quote = requirement.source_trace.quote
    evidence_quote = EvidenceQuote(
        source_id=requirement.source_trace.source_id,
        section_id=requirement.source_trace.section_id,
        quote=quote,
    )
    items: list[FieldEvidence] = []

    _append(items, "title", requirement.title, quote, evidence_quote, threshold=0.75)
    _append(items, "description", requirement.description, quote, evidence_quote, threshold=0.75)

    for test_object in requirement.requirement_facts.test_objects:
        _append(items, "test_objects", test_object.name, quote, evidence_quote, threshold=0.5)

    for constraint in requirement.requirement_facts.constraints:
        # 约束通常会把“待支付订单”结构化改写为“订单状态必须为待支付”，
        # 因此阈值略低于普通描述，避免把合理结构化表达误判为推断。
        _append(items, "constraints", constraint.rule, quote, evidence_quote, threshold=0.5)

    state_model = requirement.requirement_facts.state_model
    for state in state_model.states:
        _append(items, "state_model", state, quote, evidence_quote, threshold=0.75)
    for transition in state_model.transitions:
        transition_value = f"{transition.from_state} -> {transition.to_state}"
        _append(items, "state_model", transition_value, quote, evidence_quote, threshold=0.75)

    for permission in requirement.requirement_facts.permissions:
        _append(items, "permissions", permission.rule, quote, evidence_quote, threshold=0.75)

    for criterion in requirement.requirement_facts.acceptance_criteria:
        # GWT 的 then 是最直接的可验证结果，先以 then 作为事实值校验对象。
        _append(items, "acceptance_criteria", criterion.then, quote, evidence_quote, threshold=0.55)

    return items


def _append(
    items: list[FieldEvidence],
    field: str,
    value: str,
    quote: str,
    evidence_quote: EvidenceQuote,
    threshold: float,
) -> None:
    """追加单个字段证据。"""

    clean_value = value.strip()
    if not clean_value:
        return
    items.append(
        FieldEvidence(
            field=field,
            value=clean_value,
            evidence=evidence_quote,
            evidence_type="explicit" if _is_grounded(clean_value, quote, threshold) else "inferred",
            confidence=_coverage(clean_value, quote),
        )
    )


def _is_grounded(value: str, quote: str, threshold: float) -> bool:
    """判断字段值是否能从原文获得依据。"""

    normalized_value = _normalize(value)
    normalized_quote = _normalize(quote)
    if not normalized_value:
        return False
    # 结果文案类词汇必须原文明确出现，避免把“成功提示”等常见测试经验当成事实。
    for strict_term in ("成功", "提示", "返回"):
        if strict_term in normalized_value and strict_term not in normalized_quote:
            return False
    if normalized_value in normalized_quote:
        return True
    return _coverage(value, quote) >= threshold


def _coverage(value: str, quote: str) -> float:
    """计算字段值中的关键字符在 quote 中的覆盖率。"""

    value_chars = set(_normalize(value))
    if not value_chars:
        return 0.0
    quote_chars = set(_normalize(quote))
    return round(len(value_chars & quote_chars) / len(value_chars), 4)


def _normalize(text: str) -> str:
    """去掉空白和常见连接符，降低格式差异对匹配的影响。"""

    return (
        text.replace(" ", "")
        .replace("\n", "")
        .replace("\t", "")
        .replace("->", "")
        .replace("→", "")
        .replace("-", "")
        .replace("，", "")
        .replace(",", "")
        .replace("。", "")
        .replace("；", "")
        .replace(";", "")
        .strip()
    )
