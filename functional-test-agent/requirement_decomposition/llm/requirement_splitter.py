"""Requirement LLM 拆解器。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from requirement_decomposition.llm.langchain_chain import run_prompt_task
from requirement_decomposition.llm.llm_client import LLMClient, parse_json_response_with_repair
from requirement_decomposition.models.schema import LLMConfig, RequirementSection


class RequirementDraft(BaseModel):
    """LLM 拆解出的 Requirement 候选项。"""

    title: str
    description: str
    confidence: float = 0.0
    reasoning_summary: str = ""
    unresolved: list[dict] = Field(default_factory=list)
    ambiguity_notes: list[dict] = Field(default_factory=list)
    conflict_items: list[dict] = Field(default_factory=list)


def split_requirements(
    section: RequirementSection,
    config: LLMConfig,
    client: LLMClient,
) -> list[RequirementDraft]:
    """调用 LLM 将 section 拆成 Requirement 候选项。"""

    response = run_prompt_task(
        "requirement_split",
        {
            "section_id": section.section_id,
            "title": section.title,
            "content": section.content,
        },
        config,
        client,
    )
    data = parse_json_response_with_repair(response, client, config, "requirement_split")
    if not isinstance(data, list):
        raise ValueError("requirement_split 输出顶层必须是 JSON 数组")
    drafts = [RequirementDraft.model_validate(_normalize_draft_item(item)) for item in data]
    return _merge_ui_display_drafts(section, drafts)


def _merge_ui_display_drafts(
    section: RequirementSection,
    drafts: list[RequirementDraft],
) -> list[RequirementDraft]:
    """合并 UI 展示、页面布局、样式、视觉设计类拆解结果。

    功能说明:
        LLM 有时会把页面标题、图标、文案、样式拆成很多细 Requirement。
        这些内容适合作为同一个“页面展示/视觉设计”测试上下文，后续测试点生成时
        再在对象和 expected_results 中展开校验点。

    参数说明:
        section (RequirementSection): 当前需求片段，用于判断是否属于 UI 展示类。
        drafts (list[RequirementDraft]): LLM 原始拆解结果。

    返回值:
        list[RequirementDraft]: 合并后的 Requirement 候选项。
    """

    if len(drafts) <= 1 or not _is_ui_display_section(section):
        return drafts

    unresolved: list[dict] = []
    ambiguity_notes: list[dict] = []
    conflict_items: list[dict] = []
    for draft in drafts:
        unresolved.extend(draft.unresolved)
        ambiguity_notes.extend(draft.ambiguity_notes)
        conflict_items.extend(draft.conflict_items)

    descriptions = [f"{index}. {draft.title}: {draft.description}" for index, draft in enumerate(drafts, 1)]
    return [
        RequirementDraft(
            title=f"{section.title}页面展示与视觉校验",
            description="\n".join(descriptions),
            confidence=min((draft.confidence for draft in drafts), default=0.0),
            reasoning_summary="UI显示、页面布局、样式或视觉设计类内容合并为一个测试上下文。",
            unresolved=unresolved,
            ambiguity_notes=ambiguity_notes,
            conflict_items=conflict_items,
        )
    ]


def _is_ui_display_section(section: RequirementSection) -> bool:
    """判断 section 是否适合按 UI 展示类合并。"""

    text = f"{section.title}\n{section.content}"
    ui_keywords = ("页面布局", "布局", "样式", "视觉设计", "视觉", "UI", "图标", "文案", "文字", "显示")
    logic_keywords = (
        "交互规则",
        "输入框规则",
        "上传规则",
        "按钮规则",
        "提交成功",
        "特殊规则",
        "状态分类",
        "正向",
        "反向",
        "异常",
    )
    return any(keyword in text for keyword in ui_keywords) and not any(
        keyword in section.title for keyword in logic_keywords
    )


def _normalize_draft_item(item: dict) -> dict:
    """归一化 LLM 常见类型漂移。

    真实模型经常把 confidence 输出为“高/中/低”，或把本应为数组的 unresolved
    输出为一段字符串。这里在进入 Pydantic 前修正，减少格式漂移导致的失败。
    """

    normalized = dict(item)
    normalized["confidence"] = _normalize_confidence(normalized.get("confidence", 0.0))
    for field in ("unresolved", "ambiguity_notes", "conflict_items"):
        normalized[field] = _normalize_issue_list(normalized.get(field, []))
    return normalized


def _normalize_confidence(value) -> float:
    """将模型输出的置信度归一为 0-1 浮点数。"""

    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    mapping = {
        "高": 0.9,
        "较高": 0.8,
        "中": 0.6,
        "中等": 0.6,
        "低": 0.3,
        "较低": 0.2,
    }
    if text in mapping:
        return mapping[text]
    if text.endswith("%"):
        try:
            return float(text[:-1]) / 100
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _normalize_issue_list(value) -> list[dict]:
    """将 unresolved/ambiguity/conflict 字段归一为 list[dict]。"""

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [{"field": "unknown", "reason": text}]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        normalized: list[dict] = []
        for item in value:
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str) and item.strip():
                normalized.append({"field": "unknown", "reason": item.strip()})
        return normalized
    return [{"field": "unknown", "reason": str(value)}]
