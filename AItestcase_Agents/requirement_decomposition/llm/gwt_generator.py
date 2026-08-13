"""GWT 验收标准生成器。"""

from __future__ import annotations

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.llm.test_object_extractor import _base_variables, _items
from requirement_decomposition.models.schema import (
    AcceptanceCriterion,
    LLMConfig,
    RequirementSection,
)


def generate_gwt_criteria(
    section: RequirementSection,
    draft: RequirementDraft,
    config: LLMConfig,
    client: LLMClient,
) -> list[AcceptanceCriterion]:
    """调用 LLM 生成 Given / When / Then 验收标准。"""

    response = run_prompt_task(
        "gwt_generate",
        _base_variables(section, draft),
        config,
        client,
    )
    data = parse_json_response(response)
    return [AcceptanceCriterion.model_validate(item) for item in _items(data)]
