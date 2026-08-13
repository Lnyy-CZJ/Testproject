"""Requirement 综合字段抽取器。"""

from __future__ import annotations

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.llm.normalizers import normalize_test_object_item
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.llm.test_object_extractor import _base_variables, _items
from requirement_decomposition.models.schema import (
    AcceptanceCriterion,
    Constraint,
    LLMConfig,
    PermissionRule,
    RequirementFacts,
    RequirementSection,
    StateModel,
    TestDesignSuggestions,
    TestObject,
)


def extract_fact_bundle(
    section: RequirementSection,
    draft: RequirementDraft,
    config: LLMConfig,
    client: LLMClient,
) -> tuple[RequirementFacts, TestDesignSuggestions]:
    """一次 LLM 调用抽取测试点生成所需字段。

    功能说明:
        将 test_objects、constraints、state_model、permissions、GWT 和 risk_tags
        放到同一个 Prompt 中抽取，减少真实 LLM 请求次数，避免长文档拆解时长时间无输出。

    参数说明:
        section (RequirementSection): 当前需求切片。
        draft (RequirementDraft): Requirement 候选项。
        config (LLMConfig): LLM 调用配置。
        client (LLMClient): 可注入 LLM 客户端。

    返回值:
        tuple[RequirementFacts, TestDesignSuggestions]: 需求事实和测试设计建议。
    """

    response = run_prompt_task(
        "fact_bundle_extract",
        _base_variables(section, draft),
        config,
        client,
    )
    data = parse_json_response(response)
    if not isinstance(data, dict):
        raise ValueError("fact_bundle_extract 输出必须是 JSON 对象")

    facts = RequirementFacts(
        test_objects=[
            TestObject.model_validate(normalize_test_object_item(item))
            for item in _items(data.get("test_objects", []))
        ],
        constraints=[Constraint.model_validate(item) for item in _items(data.get("constraints", []))],
        state_model=StateModel.model_validate(data.get("state_model", {})),
        permissions=[PermissionRule.model_validate(item) for item in _items(data.get("permissions", []))],
        acceptance_criteria=[
            AcceptanceCriterion.model_validate(item)
            for item in _items(data.get("acceptance_criteria", []))
        ],
    )
    suggestions = TestDesignSuggestions(
        risk_tags=_unique_strings(data.get("risk_tags", [])),
        negative_suggestions=_unique_strings(data.get("negative_suggestions", [])),
        boundary_suggestions=_unique_strings(data.get("boundary_suggestions", [])),
        test_generation_hints=_unique_strings(data.get("test_generation_hints", [])),
    )
    return facts, suggestions


def _unique_strings(value) -> list[str]:
    """将 LLM 返回值归一为去重字符串列表。"""

    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []

    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in items:
            items.append(text)
    return items
