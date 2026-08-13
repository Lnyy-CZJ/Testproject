"""Requirement 综合字段批量抽取器。"""

from __future__ import annotations

import json

from requirement_decomposition.llm.fact_bundle_extractor import _unique_strings
from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response_with_repair
from requirement_decomposition.llm.normalizers import normalize_test_object_item
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.llm.test_object_extractor import _items
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


def extract_fact_bundles(
    section: RequirementSection,
    drafts: list[RequirementDraft],
    config: LLMConfig,
    client: LLMClient,
) -> list[tuple[RequirementFacts, TestDesignSuggestions]]:
    """一次 LLM 调用批量抽取多个 Requirement 的字段。

    功能说明:
        对同一个 section 拆出的多个 Requirement 批量抽取字段，显著减少真实
        LLM 请求次数，避免长文档运行时迟迟不生成输出。

    参数说明:
        section (RequirementSection): 当前需求切片。
        drafts (list[RequirementDraft]): 该 section 拆出的 Requirement 候选项。
        config (LLMConfig): LLM 调用配置。
        client (LLMClient): 可注入 LLM 客户端。

    返回值:
        list[tuple[RequirementFacts, TestDesignSuggestions]]: 与 drafts 顺序一致的字段结果。
    """

    if not drafts:
        return []

    response = run_prompt_task(
        "fact_bundle_batch_extract",
        {
            "section_id": section.section_id,
            "source_content": section.content,
            "requirements_json": json.dumps(
                [
                    {
                        "index": index,
                        "title": draft.title,
                        "description": draft.description,
                    }
                    for index, draft in enumerate(drafts)
                ],
                ensure_ascii=False,
            ),
        },
        config,
        client,
    )
    data = parse_json_response_with_repair(response, client, config, "fact_bundle_batch_extract")
    items = _items(data)
    by_index = {_item_index(item): item for item in items}

    bundles: list[tuple[RequirementFacts, TestDesignSuggestions]] = []
    for index in range(len(drafts)):
        item = by_index.get(index)
        if item is None:
            raise ValueError(f"fact_bundle_batch_extract 缺少 index={index} 的抽取结果")
        bundles.append(_bundle_from_item(item))
    return bundles


def _bundle_from_item(item: dict) -> tuple[RequirementFacts, TestDesignSuggestions]:
    """将单个批量抽取项转换为模型。"""

    facts = RequirementFacts(
        test_objects=[
            TestObject.model_validate(normalize_test_object_item(value))
            for value in _items(item.get("test_objects", []))
        ],
        constraints=[Constraint.model_validate(value) for value in _items(item.get("constraints", []))],
        state_model=StateModel.model_validate(item.get("state_model", {})),
        permissions=[PermissionRule.model_validate(value) for value in _items(item.get("permissions", []))],
        acceptance_criteria=[
            AcceptanceCriterion.model_validate(value)
            for value in _items(item.get("acceptance_criteria", []))
        ],
    )
    suggestions = TestDesignSuggestions(
        risk_tags=_unique_strings(item.get("risk_tags", [])),
        negative_suggestions=_unique_strings(item.get("negative_suggestions", [])),
        boundary_suggestions=_unique_strings(item.get("boundary_suggestions", [])),
        test_generation_hints=_unique_strings(item.get("test_generation_hints", [])),
    )
    return facts, suggestions


def _item_index(item: dict) -> int:
    """读取批量结果中的 index。"""

    try:
        return int(item["index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("fact_bundle_batch_extract 每个 item 必须包含整数 index") from exc
