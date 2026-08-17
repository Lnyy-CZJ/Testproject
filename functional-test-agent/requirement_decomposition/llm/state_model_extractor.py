"""状态模型提取器。"""

from __future__ import annotations

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.llm.test_object_extractor import _base_variables
from requirement_decomposition.models.schema import LLMConfig, RequirementSection, StateModel


def extract_state_model(
    section: RequirementSection,
    draft: RequirementDraft,
    config: LLMConfig,
    client: LLMClient,
) -> StateModel:
    """调用 LLM 提取状态集合和状态流转。"""

    response = run_prompt_task(
        "state_model_extract",
        _base_variables(section, draft),
        config,
        client,
    )
    data = parse_json_response(response)
    return StateModel.model_validate(data)
