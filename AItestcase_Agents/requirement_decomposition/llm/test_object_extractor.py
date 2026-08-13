"""测试对象提取器。"""

from __future__ import annotations

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.llm.normalizers import normalize_test_object_item
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.models.schema import LLMConfig, RequirementSection, TestObject


def extract_test_objects(
    section: RequirementSection,
    draft: RequirementDraft,
    config: LLMConfig,
    client: LLMClient,
) -> list[TestObject]:
    """调用 LLM 提取测试对象。"""

    response = run_prompt_task(
        "test_object_extract",
        _base_variables(section, draft),
        config,
        client,
    )
    data = parse_json_response(response)
    return [TestObject.model_validate(normalize_test_object_item(item)) for item in _items(data)]


def _base_variables(section: RequirementSection, draft: RequirementDraft) -> dict[str, str]:
    """构造通用 Prompt 变量。"""

    return {
        "section_id": section.section_id,
        "source_content": section.content,
        "requirement_title": draft.title,
        "requirement_description": draft.description,
    }


def _items(data) -> list[dict]:
    """兼容 `{items: [...]}` 和直接数组两种返回格式。"""

    if isinstance(data, dict):
        return data.get("items", [])
    if isinstance(data, list):
        return data
    raise ValueError("LLM 提取结果必须是对象或数组")
