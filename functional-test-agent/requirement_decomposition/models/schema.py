"""需求拆解 Skill 的 Pydantic 数据模型。

这些模型只表达 PRD V1.2 已确认的结构。需求拆解必须由 LLM 链路完成，
规则只用于 Schema、证据和质量校验，不再提供规则生成模式。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    """项目信息配置。"""

    project_id: str = "PROJECT-001"
    project_name: str = "未命名项目"
    version: str = "1.0.0"


class SourceConfig(BaseModel):
    """需求来源配置。"""

    source_id: str = "SRC-001"
    source_type: Literal["markdown"] = "markdown"
    path: str
    trust_level: Literal["high", "medium", "low"] = "high"


class LLMConfig(BaseModel):
    """LLM 配置。"""

    enabled: bool = True
    model: str = "gpt-4.1"
    temperature: float = 0.1
    max_tokens: int = 4096
    prompt_version: str = "v1.0"
    verbose: bool = True
    self_check_enabled: bool = False


class OutputFileConfig(BaseModel):
    """单个输出文件或目录的配置。"""

    enabled: bool = True
    path: str
    include_confirmed_candidate: bool = False


class OutputConfig(BaseModel):
    """全部输出配置。"""

    requirement_json: OutputFileConfig = Field(
        default_factory=lambda: OutputFileConfig(path="output/requirements.json")
    )
    markdown: OutputFileConfig = Field(
        default_factory=lambda: OutputFileConfig(path="output/requirements_md")
    )
    test_seed: OutputFileConfig = Field(
        default_factory=lambda: OutputFileConfig(path="output/test_seed.json")
    )


class QualityGateConfig(BaseModel):
    """质量门禁配置。具体门禁逻辑在后续阶段实现。"""

    min_quality_score: float = 0.9
    require_source_trace: bool = True
    require_field_evidence: bool = True
    require_test_objects: bool = True
    require_constraints: bool = True
    require_gwt: bool = True
    require_schema_valid: bool = True
    require_grounding_check_passed: bool = True
    max_unsupported_facts: int = 0


class DecompositionConfig(BaseModel):
    """需求拆解运行配置。"""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    quality_gate: QualityGateConfig = Field(default_factory=QualityGateConfig)


class SourceDocument(BaseModel):
    """解析后的原始文档。"""

    source_id: str
    source_type: Literal["markdown"] = "markdown"
    path: str
    trust_level: Literal["high", "medium", "low"] = "high"
    content: str


class RequirementSection(BaseModel):
    """按标题切分后的需求片段。"""

    source_id: str
    section_id: str
    title: str
    heading_path: list[str] = Field(default_factory=list)
    content: str
    quote: str


class SourceTrace(BaseModel):
    """Requirement 的来源追溯信息。"""

    source_id: str
    section_id: str
    quote: str


class EvidenceQuote(BaseModel):
    """字段级证据中的原文引用。"""

    source_id: str
    section_id: str
    quote: str


class FieldEvidence(BaseModel):
    """字段级 evidence。"""

    field: str
    value: str
    evidence: EvidenceQuote
    evidence_type: Literal["explicit", "inferred", "missing", "conflict"] = "explicit"
    confidence: float = 1.0


class TestObject(BaseModel):
    """测试对象。"""

    name: str
    type: str
    values: list[str] = Field(default_factory=list)


class Constraint(BaseModel):
    """业务或测试约束。"""

    object: str
    rule: str
    constraint_type: str
    test_dimension: str = ""


class StateTransition(BaseModel):
    """状态流转。"""

    from_state: str = Field(alias="from")
    to_state: str = Field(alias="to")
    trigger: str
    valid: bool = True


class StateModel(BaseModel):
    """状态模型。"""

    entity: str = ""
    states: list[str] = Field(default_factory=list)
    transitions: list[StateTransition] = Field(default_factory=list)


class PermissionRule(BaseModel):
    """权限规则。"""

    role: str
    rule: str


class AcceptanceCriterion(BaseModel):
    """Given / When / Then 验收标准。"""

    given: str
    when: str
    then: str


class RequirementFacts(BaseModel):
    """原文明确支持的需求事实。"""

    test_objects: list[TestObject] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    trigger: str = ""
    constraints: list[Constraint] = Field(default_factory=list)
    state_model: StateModel = Field(default_factory=StateModel)
    permissions: list[PermissionRule] = Field(default_factory=list)
    main_flow: list[str] = Field(default_factory=list)
    exception_flows: list[str] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)


class TestDesignSuggestions(BaseModel):
    """AI 推断出的测试设计建议，不作为需求事实。"""

    risk_tags: list[str] = Field(default_factory=list)
    test_generation_hints: list[str] = Field(default_factory=list)
    negative_suggestions: list[str] = Field(default_factory=list)
    boundary_suggestions: list[str] = Field(default_factory=list)


class GroundingCheck(BaseModel):
    """Grounding Check 结果。"""

    passed: bool = False
    unsupported_items: list[dict] = Field(default_factory=list)


class LLMMetadata(BaseModel):
    """Requirement 级 LLM 元信息。"""

    llm_enabled: bool = False
    model: str = ""
    prompt_version: str = ""
    confidence: float = 0.0
    reasoning_summary: str = ""
    generated_at: str = ""


class LLMSelfCheck(BaseModel):
    """LLM 自检结果。第一阶段默认未执行。"""

    passed: bool = False
    issues: list[dict] = Field(default_factory=list)


class Requirement(BaseModel):
    """结构化 Requirement。"""

    requirement_id: str
    title: str
    domain: str = ""
    module: str = ""
    feature: str = ""
    description: str
    source_trace: SourceTrace
    requirement_facts: RequirementFacts = Field(default_factory=RequirementFacts)
    test_design_suggestions: TestDesignSuggestions = Field(
        default_factory=TestDesignSuggestions
    )
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    grounding_check: GroundingCheck = Field(default_factory=GroundingCheck)
    unresolved: list[dict] = Field(default_factory=list)
    ambiguity_notes: list[dict] = Field(default_factory=list)
    conflict_items: list[dict] = Field(default_factory=list)
    llm_metadata: LLMMetadata = Field(default_factory=LLMMetadata)
    llm_self_check: LLMSelfCheck = Field(default_factory=LLMSelfCheck)
    status: Literal["draft", "confirmed_candidate", "confirmed", "changed", "deprecated"] = (
        "draft"
    )


class TestSeed(BaseModel):
    """测试点生成系统消费的轻量输入。"""

    objects: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    state_transitions: list[str] = Field(default_factory=list)
    invalid_state_transitions: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    negative_suggestions: list[str] = Field(default_factory=list)
    requirement_titles: list[str] = Field(default_factory=list)
    uncertain_items: list[str] = Field(default_factory=list)


class EvidenceSummary(BaseModel):
    """test_seed 的证据摘要。"""

    fact_fields_grounded: bool = False
    suggestions_include_inferred_items: bool = False


class TestSeedRecord(BaseModel):
    """单个功能聚合后的 test_seed 输出记录。"""

    requirement_id: str
    requirement_ids: list[str] = Field(default_factory=list)
    module: str
    feature: str
    source_trace: dict
    test_seed: TestSeed
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    status_tags: list[str] = Field(default_factory=list)


class DecompositionResult(BaseModel):
    """run_decomposition 的返回对象。"""

    success: bool
    requirements: list[Requirement] = Field(default_factory=list)
    test_seeds: list[TestSeedRecord] = Field(default_factory=list)
    quality_report: dict = Field(default_factory=dict)
    llm_trace: dict = Field(default_factory=dict)
    grounding_summary: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
