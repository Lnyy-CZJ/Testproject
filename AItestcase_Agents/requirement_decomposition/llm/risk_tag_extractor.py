"""风险标签提取器。"""

from __future__ import annotations

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.llm.requirement_splitter import RequirementDraft
from requirement_decomposition.llm.test_object_extractor import _base_variables
from requirement_decomposition.models.schema import LLMConfig, RequirementSection


def extract_risk_tags(
    section: RequirementSection,
    draft: RequirementDraft,
    config: LLMConfig,
    client: LLMClient,
) -> list[str]:
    """调用 LLM 提取测试风险标签。

    功能说明:
        风险标签用于指导测试点生成智能体补充高风险测试方向，属于
        test_design_suggestions，不作为原文需求事实。

    参数说明:
        section (RequirementSection): 当前需求切片，提供原文上下文。
        draft (RequirementDraft): Requirement 候选项。
        config (LLMConfig): LLM 调用配置。
        client (LLMClient): 可注入 LLM 客户端。

    返回值:
        list[str]: LLM 建议的风险标签列表，枚举合法性由后续校验器处理。
    """

    response = run_prompt_task(
        "risk_tag_extract",
        _base_variables(section, draft),
        config,
        client,
    )
    data = parse_json_response(response)
    return _risk_tags(data)


def _risk_tags(data) -> list[str]:
    """兼容多种 LLM JSON 返回形态。"""

    if isinstance(data, dict):
        raw_tags = data.get("risk_tags", data.get("items", []))
    elif isinstance(data, list):
        raw_tags = data
    else:
        raise ValueError("risk_tag_extract 输出必须是对象或数组")

    tags: list[str] = []
    for item in raw_tags:
        if isinstance(item, str):
            tag = item.strip()
        elif isinstance(item, dict):
            tag = str(item.get("value") or item.get("tag") or item.get("name") or "").strip()
        else:
            tag = ""
        if tag and tag not in tags:
            tags.append(tag)
    return tags
