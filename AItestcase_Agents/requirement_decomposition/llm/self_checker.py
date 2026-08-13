"""LLM 自检器。"""

from __future__ import annotations

import json

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response
from requirement_decomposition.models.schema import LLMConfig, LLMSelfCheck, Requirement, RequirementSection


def run_llm_self_check(
    section: RequirementSection,
    requirement: Requirement,
    config: LLMConfig,
    client: LLMClient,
) -> LLMSelfCheck:
    """调用 LLM 对 Requirement 结构做自检。

    功能说明:
        自检用于发现拆解合并、遗漏权限/状态/边界、无依据推断等问题。
        自检结果进入质量报告和人工 review 参考，不替代代码校验。

    参数说明:
        section (RequirementSection): 当前需求切片，提供原文上下文。
        requirement (Requirement): 已组装的 Requirement。
        config (LLMConfig): LLM 调用配置。
        client (LLMClient): 可注入 LLM 客户端。

    返回值:
        LLMSelfCheck: 标准化后的自检结果。
    """

    response = run_prompt_task(
        "self_check",
        {
            "section_id": section.section_id,
            "source_content": section.content,
            "requirement_json": json.dumps(
                requirement.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
            ),
        },
        config,
        client,
    )
    data = parse_json_response(response)
    return LLMSelfCheck.model_validate(_normalize_self_check(data))


def _normalize_self_check(data) -> dict:
    """兼容 LLM 自检返回的常见形态。"""

    if isinstance(data, dict):
        return {
            "passed": bool(data.get("passed", False)),
            "issues": _normalize_issues(data.get("issues", [])),
        }
    raise ValueError("self_check 输出必须是 JSON 对象")


def _normalize_issues(value) -> list[dict]:
    """将自检 issue 归一为 list[dict]。"""

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [] if not text else [{"type": "self_check_issue", "description": text}]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        issues: list[dict] = []
        for item in value:
            if isinstance(item, dict):
                issues.append(item)
            elif isinstance(item, str) and item.strip():
                issues.append({"type": "self_check_issue", "description": item.strip()})
        return issues
    return [{"type": "self_check_issue", "description": str(value)}]
