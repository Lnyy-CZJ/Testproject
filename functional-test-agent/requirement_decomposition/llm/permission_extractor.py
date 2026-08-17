"""权限规则提取器。"""

from __future__ import annotations

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.llm.test_object_extractor import _base_variables, _items
from requirement_decomposition.models.schema import LLMConfig, PermissionRule, RequirementSection


def extract_permissions(
    section: RequirementSection,
    draft: RequirementDraft,
    config: LLMConfig,
    client: LLMClient,
) -> list[PermissionRule]:
    """调用 LLM 提取权限规则。"""

    response = run_prompt_task(
        "permission_extract",
        _base_variables(section, draft),
        config,
        client,
    )
    data = parse_json_response(response)
    return [PermissionRule.model_validate(item) for item in _items(data)]
