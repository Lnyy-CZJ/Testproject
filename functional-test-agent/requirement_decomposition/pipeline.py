"""需求拆解流水线。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from requirement_decomposition.chunker import chunk_markdown_sections
from requirement_decomposition.config import load_config
from requirement_decomposition.generator import (
    generate_test_seeds,
    write_requirement_markdown,
    write_requirements_json,
    write_test_seeds_json,
)
from requirement_decomposition.llm.fact_bundle_batch_extractor import extract_fact_bundles
from requirement_decomposition.llm.llm_client import DefaultLLMClient, LLMClient
from requirement_decomposition.llm.requirement_splitter import RequirementDraft, split_requirements
from requirement_decomposition.llm.self_checker import run_llm_self_check
from requirement_decomposition.models.schema import (
    DecompositionResult,
    LLMSelfCheck,
    Requirement,
    RequirementSection,
    SourceConfig,
    SourceTrace,
)
from requirement_decomposition.parser import parse_markdown_document
from requirement_decomposition.validator.anti_hallucination import apply_anti_hallucination
from requirement_decomposition.validator.confirmed_gate_validator import apply_confirmed_gate
from requirement_decomposition.validator.quality_validator import build_quality_report


def run_decomposition(
    source_path: str,
    config_path: str,
    llm_client: LLMClient | None = None,
    output_dir: str | None = None,
) -> DecompositionResult:
    """执行需求拆解。

    需求拆解必须使用 LLM 链路。代码层只负责防幻觉和质量校验。
    """

    try:
        return _run_decomposition(
            source_path=source_path,
            config_path=config_path,
            llm_client=llm_client,
            output_dir=output_dir,
        )
    except Exception as exc:
        return DecompositionResult(
            success=False,
            errors=[_format_error(exc)],
            quality_report={"quality_score": 0.0, "quality_gate_passed": False, "issues": []},
        )


def _run_decomposition(
    source_path: str,
    config_path: str,
    llm_client: LLMClient | None = None,
    output_dir: str | None = None,
) -> DecompositionResult:
    """执行需求拆解的内部实现。"""

    config = load_config(config_path, source_path=source_path)
    runtime_model = os.getenv("LLM_MODEL", "").strip()
    if runtime_model:
        # 平台 Runner 的任务快照是实际模型来源；覆盖仅用于元数据和拆解调用记录。
        config.llm.model = runtime_model
    if output_dir:
        _apply_output_dir(config, output_dir)
    documents = [
        parse_markdown_document(
            source.path,
            source_id=source.source_id,
            trust_level=source.trust_level,
        )
        for source in config.sources
    ]
    sections = [section for document in documents for section in chunk_markdown_sections(document)]

    if not config.llm.enabled:
        raise RuntimeError("LLM 已关闭，需求拆解 Skill 需要启用 LLM")

    active_llm_client = llm_client or DefaultLLMClient()
    _log_progress(config.llm, f"已解析 {len(sections)} 个需求片段，开始 LLM 拆解")
    requirements = _build_llm_requirements(
        sections,
        config.sources,
        config.llm,
        active_llm_client,
    )

    requirements = [apply_anti_hallucination(requirement) for requirement in requirements]
    requirements = [
        apply_confirmed_gate(requirement, config.quality_gate) for requirement in requirements
    ]
    test_seeds = generate_test_seeds(
        requirements,
        include_confirmed_candidate=config.output.test_seed.include_confirmed_candidate,
    )
    grounding_summary = _build_grounding_summary(requirements, checked=True)
    quality_report = build_quality_report(requirements, config.quality_gate)
    quality_report["phase"] = "llm_quality_gate"
    llm_trace = {
        "enabled": config.llm.enabled,
        "model": config.llm.model,
        "prompt_version": config.llm.prompt_version,
    }

    top_level_data = {
        "project": config.project.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in config.sources],
        "domains": [],
        "modules": [],
        "features": [],
        "requirements": [
            requirement.model_dump(mode="json", by_alias=True) for requirement in requirements
        ],
        "llm_trace": llm_trace,
        "grounding_summary": grounding_summary,
        "quality_report": quality_report,
        "version": {"phase": "llm_only", "schema_version": "v1.2"},
    }

    _write_outputs(config, top_level_data, requirements, test_seeds)
    return DecompositionResult(
        success=True,
        requirements=requirements,
        test_seeds=test_seeds,
        quality_report=quality_report,
        llm_trace=llm_trace,
        grounding_summary=grounding_summary,
        warnings=["已执行 LLM 拆解、防幻觉校验和质量门禁；人工 confirmed 仍需外部确认"],
    )


def _build_llm_requirements(
    sections: list[RequirementSection],
    sources: list[SourceConfig],
    llm_config,
    llm_client: LLMClient,
) -> list[Requirement]:
    """使用第二阶段 LLM 链路构建 Requirement 草稿。"""

    source_by_id = {source.source_id: source for source in sources}
    requirements: list[Requirement] = []

    for section in sections:
        _log_progress(llm_config, f"处理 {section.section_id}: {section.title}")
        drafts = split_requirements(section, llm_config, llm_client)
        _log_progress(llm_config, f"{section.section_id} 拆出 {len(drafts)} 个 Requirement")
        _log_progress(llm_config, f"批量抽取字段: {section.section_id}")
        fact_bundles = extract_fact_bundles(section, drafts, llm_config, llm_client)
        for draft, (facts, suggestions) in zip(drafts, fact_bundles):
            requirement = _llm_draft_to_requirement(
                section=section,
                source=source_by_id.get(section.source_id),
                draft=draft,
                requirement_id=f"REQ-{len(requirements) + 1:03d}",
                facts=facts,
                suggestions=suggestions,
                llm_config=llm_config,
                llm_client=llm_client,
            )
            requirements.append(requirement)

    return requirements


def _llm_draft_to_requirement(
    section: RequirementSection,
    source: SourceConfig | None,
    draft: RequirementDraft,
    requirement_id: str,
    facts,
    suggestions,
    llm_config,
    llm_client: LLMClient,
) -> Requirement:
    """将 LLM draft 和各字段抽取结果组装为 Requirement。"""

    domain = section.heading_path[0] if section.heading_path else ""
    module = section.heading_path[-2] if len(section.heading_path) >= 2 else domain
    feature = section.title
    unresolved = list(draft.unresolved)
    if source is None:
        unresolved.append({"field": "source", "reason": "section 对应 source 配置不存在"})

    requirement = Requirement(
        requirement_id=requirement_id,
        title=draft.title,
        domain=domain,
        module=module,
        feature=feature,
        description=draft.description,
        source_trace=SourceTrace(
            source_id=section.source_id,
            section_id=section.section_id,
            quote=section.quote,
        ),
        requirement_facts=facts,
        test_design_suggestions=suggestions,
        unresolved=unresolved,
        ambiguity_notes=draft.ambiguity_notes,
        conflict_items=draft.conflict_items,
        llm_metadata={
            "llm_enabled": True,
            "model": llm_config.model,
            "prompt_version": llm_config.prompt_version,
            "confidence": draft.confidence,
            "reasoning_summary": draft.reasoning_summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        status="draft",
    )
    if getattr(llm_config, "self_check_enabled", False):
        _log_progress(llm_config, f"LLM 自检: {requirement_id} {draft.title}")
        requirement.llm_self_check = run_llm_self_check(section, requirement, llm_config, llm_client)
    else:
        requirement.llm_self_check = LLMSelfCheck(passed=True, issues=[])
    return requirement


def _write_outputs(
    config,
    top_level_data: dict,
    requirements: list[Requirement],
    test_seeds,
) -> None:
    """根据配置写入输出文件。"""

    if config.output.requirement_json.enabled:
        write_requirements_json(top_level_data, _resolve_output_path(config.output.requirement_json.path))
    if config.output.markdown.enabled:
        write_requirement_markdown(requirements, _resolve_output_path(config.output.markdown.path))
    if config.output.test_seed.enabled:
        write_test_seeds_json(test_seeds, _resolve_output_path(config.output.test_seed.path))


def _apply_output_dir(config, output_dir: str) -> None:
    """将需求拆解输出重定向到独立目录。

    功能说明:
        调用方可以在不修改 YAML 配置的情况下，将本次需求拆解产物写入
        output/requirements_docs/<功能名>/ 这类独立目录。

    参数说明:
        config: 已加载的 DecompositionConfig。
        output_dir (str): 本次拆解产物目录。

    返回值:
        None。直接修改 config.output 中的文件路径。

    异常说明:
        不主动抛出异常；路径创建由各 writer 负责。
    """

    resolved_dir = Path(output_dir).expanduser().resolve()
    config.output.requirement_json.path = str(resolved_dir / "requirements.json")
    config.output.markdown.path = str(resolved_dir / "requirements_md")
    config.output.test_seed.path = str(resolved_dir / "test_seed.json")


def _build_grounding_summary(requirements: list[Requirement], checked: bool) -> dict:
    """汇总 Grounding Check 结果。"""

    unsupported_facts = sum(
        len(requirement.grounding_check.unsupported_items) for requirement in requirements
    )
    moved_to_suggestions = sum(
        1
        for requirement in requirements
        for item in requirement.grounding_check.unsupported_items
        if item.get("action") == "move_to_test_design_suggestions"
    )
    return {
        "checked": checked,
        "unsupported_facts": unsupported_facts,
        "moved_to_suggestions": moved_to_suggestions,
    }


def _resolve_output_path(path: str) -> str:
    """统一解析输出路径。"""

    return str(Path(path).expanduser().resolve())


def _format_error(exc: Exception) -> str:
    """格式化异常，避免 KeyError(0) 变成不可读的 '0'。"""

    message = str(exc)
    if message:
        return f"{type(exc).__name__}: {message}"
    return repr(exc)


def _log_progress(llm_config, message: str) -> None:
    """输出拆解进度，避免真实 LLM 调用时看起来像卡死。"""

    if getattr(llm_config, "verbose", False):
        print(f"[requirement_decomposition] {message}", flush=True)
