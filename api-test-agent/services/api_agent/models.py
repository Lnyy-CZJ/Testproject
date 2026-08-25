"""API 测试智能体 V2 的任务、Review、执行和缺陷草稿模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> str:
    """返回可直接写入任务文件的 UTC ISO 时间。"""

    return datetime.now(UTC).isoformat()


class StrictModel(BaseModel):
    """拒绝未声明字段，避免模型或浏览器静默扩展执行语义。"""

    model_config = ConfigDict(
        extra="forbid", validate_by_alias=True, validate_by_name=True, serialize_by_alias=True,
    )


class SourceTrace(StrictModel):
    """记录契约来自哪个文档和结构片段。"""

    source_id: str
    section_id: str
    quote: str = ""


class FieldEvidence(StrictModel):
    """字段级证据；结构化文档使用 JSON Pointer，文本使用原文引用。"""

    field_path: str
    value: Any
    source_type: Literal["openapi_node", "source_quote", "human_override"]
    source_pointer: str
    quote: str = ""
    evidence_type: Literal["explicit", "inferred", "missing", "conflict"] = "explicit"
    confidence: float = Field(default=1.0, ge=0, le=1)
    document_version: int | None = Field(default=None, ge=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    json_pointer: str | None = None


class ReviewIssue(StrictModel):
    """冲突、歧义或未解决信息的统一表示。"""

    code: str
    field_path: str
    message: str
    severity: Literal["info", "warning", "blocker"] = "warning"
    source_pointer: str = ""
    issue_id: str = ""
    contract_id: str = ""
    status: Literal["open", "resolved", "reopened", "accepted_as_suggestion"] = "open"
    current_value: Any = None
    document_version: int | None = Field(default=None, ge=1)
    resolution_type: Literal[
        "bind_evidence", "edit_field", "remove_inference", "human_override",
    ] | None = None
    resolution_reason: str = ""
    resolved_by: dict[str, str] | None = None
    resolved_at: str | None = None
    reviewed_by: dict[str, str] | None = None
    reviewed_at: str | None = None


class DocumentValidationResult(StrictModel):
    """文档修订保存前的确定性预检结果。"""

    valid: bool
    document_format: str
    specification_version: str = ""
    estimated_interface_count: int = Field(default=0, ge=0)
    secret_risk_detected: bool = False


class DocumentRevision(StrictModel):
    """任务内不可变、可追溯的接口文档版本。"""

    revision_id: str
    version: int = Field(ge=1)
    source_type: Literal["upload", "paste", "revision"]
    source_filename: str
    media_type: str = "text/plain"
    document_format: str
    content: str
    content_sha256: str
    parent_version: int | None = Field(default=None, ge=1)
    status: Literal["uploaded", "validated", "analyzed", "superseded"] = "validated"
    validation_result: DocumentValidationResult
    change_reason: str = ""
    created_by: dict[str, str]
    created_at: str = Field(default_factory=utc_now)


class AnalysisScopeVersion(StrictModel):
    """限定单次解析所使用接口范围，不包含任何真实执行 Host。"""

    scope_id: str
    version: int = Field(ge=1)
    document_version: int = Field(ge=1)
    include_methods: list[str] = Field(default_factory=list)
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    analyze_request: bool = True
    analyze_response: bool = True
    analyze_security: bool = True
    analyze_errors: bool = True
    analyze_dependencies: bool = True
    project: str = ""
    module: str = ""
    environment: str = ""
    sha256: str = ""
    created_by: dict[str, str]
    created_at: str = Field(default_factory=utc_now)

    @field_validator("include_methods", mode="before")
    @classmethod
    def normalize_methods(cls, value: Any) -> list[str]:
        """统一 method 并拒绝非 HTTP/Gateway 类型。"""

        methods = [str(item).upper() for item in (value or [])]
        allowed = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        if any(item not in allowed for item in methods):
            raise ValueError("分析范围包含不支持的 HTTP method")
        return list(dict.fromkeys(methods))

    @field_validator("include_paths", "exclude_paths")
    @classmethod
    def validate_scope_paths(cls, value: list[str]) -> list[str]:
        """范围只接受相对路径模式，禁止注入真实目标 URL。"""

        normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        if any(not item.startswith("/") or "://" in item for item in normalized):
            raise ValueError("分析范围 path 必须是相对路径")
        return normalized


class ServerDefinition(StrictModel):
    """文档声明的服务器元数据，不作为实际执行目标。"""

    url: str
    description: str = ""


class ContractParameter(StrictModel):
    """规范化 HTTP 参数。"""

    name: str
    location: Literal["header", "path", "query", "cookie"]
    required: bool = False
    description: str = ""
    schema_definition: dict[str, Any] = Field(default_factory=dict, alias="schema")
    example: Any = None
    param_role: Literal["required", "optional", "conditional", "fixed"] = "required"
    fixed_value: Any = None
    default_value: Any = None
    allow_omit: bool = False
    baseline_value: Any = None
    data_category: Literal["baseline", "boundary", "abnormal", "security"] = "baseline"
    dependencies: list[str] = Field(default_factory=list)
    mutex_group: str | None = None
    test_strategy: list[str] = Field(default_factory=list)


class RequestBodyDefinition(StrictModel):
    """规范化请求体。"""

    required: bool = False
    content: dict[str, Any] = Field(default_factory=dict)


class ResponseDefinition(StrictModel):
    """规范化响应定义。"""

    status_code: str
    description: str = ""
    content: dict[str, Any] = Field(default_factory=dict)


class SecurityRequirement(StrictModel):
    """鉴权方案及作用域，不保存任何凭证值。"""

    scheme: str
    scopes: list[str] = Field(default_factory=list)


class AuthRequirement(StrictModel):
    """V2.4 显式鉴权要求，只描述凭证位置和协议，不保存凭证值。"""

    scheme_type: Literal[
        "bearer", "basic", "api_key", "cookie", "session", "csrf", "oauth2", "custom",
    ]
    credential_location: Literal["header", "query", "cookie", "body", "runtime_profile"]
    field_name: str = ""
    scopes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ApiDependency(StrictModel):
    """接口依赖及变量来源。"""

    contract_id: str
    variable: str = ""
    source_path: str = ""


class ContractQualityReport(StrictModel):
    """契约质量结果；分数不能覆盖硬阻断项。"""

    quality_score: float = Field(default=0, ge=0, le=1)
    hard_gate_passed: bool = False
    evidence_rate: float = Field(default=0, ge=0, le=1)
    grounding_passed: bool = False
    unsupported_facts: int = Field(default=0, ge=0)
    blockers: list[ReviewIssue] = Field(default_factory=list)


class ApiContract(StrictModel):
    """可追溯的接口契约。"""

    contract_id: str
    artifact_schema_version: int = Field(default=2, ge=2, le=3)
    version: int = Field(default=1, ge=1)
    name: str
    summary: str = ""
    module: str = ""
    tags: list[str] = Field(default_factory=list)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    sla_ms: int | None = Field(default=None, gt=0)
    servers: list[ServerDefinition] = Field(default_factory=list)
    parameters: list[ContractParameter] = Field(default_factory=list)
    request_body: RequestBodyDefinition | None = None
    responses: list[ResponseDefinition] = Field(default_factory=list)
    security: list[SecurityRequirement] = Field(default_factory=list)
    auth_conclusion: Literal["none", "required", "optional", "unresolved"] = "unresolved"
    auth_requirements: list[AuthRequirement] = Field(default_factory=list)
    body_signal_detected: bool = False
    auth_signal_detected: bool = False
    dependencies: list[ApiDependency] = Field(default_factory=list)
    source_trace: SourceTrace
    field_evidence: list[FieldEvidence] = Field(default_factory=list)
    unresolved: list[ReviewIssue] = Field(default_factory=list)
    ambiguity_notes: list[ReviewIssue] = Field(default_factory=list)
    conflict_items: list[ReviewIssue] = Field(default_factory=list)
    test_design_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    quality_report: ContractQualityReport = Field(default_factory=ContractQualityReport)
    status: Literal["draft", "confirmed_candidate", "confirmed", "changed", "deprecated"] = "draft"
    change_history: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: Any) -> str:
        """将确定性解析器和 LLM 的 method 统一为大写。"""

        return str(value).upper()

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        """拒绝完整 URL，确保执行目标只能由 target_id 决定。"""

        if not value.startswith("/") or "://" in value:
            raise ValueError("path 必须是以 / 开头的相对路径")
        return value

    @model_validator(mode="after")
    def validate_path_parameters(self) -> "ApiContract":
        """确保路径参数和模板一致，防止生成无法执行的请求。"""

        for parameter in self.parameters:
            if parameter.location == "path":
                if not parameter.required or f"{{{parameter.name}}}" not in self.path:
                    raise ValueError(f"路径参数 {parameter.name} 必须 required 且出现在 path 中")
        return self


class CaseParameterMutation(StrictModel):
    """描述基础用例对契约参数或请求体字段所做的受控变化。"""

    field_path: str
    strategy: Literal[
        "valid", "missing", "invalid_type", "boundary", "invalid_enum", "duplicate", "custom",
    ] = "custom"
    value: Any = None
    description: str = ""


class CaseEvidenceRef(StrictModel):
    """引用契约 Evidence，而不在用例中复制原始文档正文。"""

    field_path: str
    source_pointer: str
    quote: str = ""


class CaseQualityReport(StrictModel):
    """基础用例的 Grounding 和完整性门禁结果。"""

    hard_gate_passed: bool = False
    grounding_passed: bool = False
    completeness_passed: bool = False
    evidence_rate: float = Field(default=0, ge=0, le=1)
    blockers: list[ReviewIssue] = Field(default_factory=list)
    warnings: list[ReviewIssue] = Field(default_factory=list)


class BaseTestCase(StrictModel):
    """可人工 Review 的基础测试用例。"""

    case_id: str
    artifact_schema_version: int = Field(default=2, ge=2, le=3)
    version: int = Field(default=1, ge=1)
    contract_id: str
    name: str
    objective: str
    dimension: str
    risk_level: Literal["low", "medium", "high"] = "low"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    parameter_mutations: list[CaseParameterMutation] = Field(default_factory=list)
    dependencies: list[ApiDependency] = Field(default_factory=list)
    evidence_refs: list[CaseEvidenceRef] = Field(default_factory=list)
    quality_report: CaseQualityReport = Field(default_factory=CaseQualityReport)
    scenario_type: Literal["normal", "negative", "exploratory"] = "normal"
    generation_kernel: Literal[
        "legacy", "v2_minimal", "v2_fused", "v2_core_workflow", "human",
    ] = "v2_minimal"
    generation_sources: list[str] = Field(default_factory=list)
    prompt_sha256: str = ""
    source: Literal["deterministic", "document", "llm", "human"]
    status: Literal["draft", "confirmed_candidate", "confirmed", "disabled"] = "draft"
    disabled_reason: str = ""
    change_history: list[dict[str, Any]] = Field(default_factory=list)
    high_risk_confirmed_by: dict[str, str] | str | None = None
    high_risk_confirmed_at: str | None = None


class CoverageMatrixItem(StrictModel):
    """单个结构化覆盖结论。"""

    coverage_id: str
    contract_id: str
    dimension: str
    rule: str
    required: bool = True
    covered: bool = False
    case_ids: list[str] = Field(default_factory=list)
    decision_source: Literal["deterministic", "llm", "human"] = "deterministic"
    confidence: float = Field(default=1.0, ge=0, le=1)
    gap_reason: str = ""
    generation_round: int = Field(default=0, ge=0, le=3)
    rule_source: str = ""


class CoverageRoundSummary(StrictModel):
    """记录每轮补齐前后的缺口数量和终止原因。"""

    round_number: int = Field(ge=1, le=3)
    missing_before: int = Field(ge=0)
    generated_count: int = Field(ge=0)
    missing_after: int = Field(ge=0)
    stop_reason: str = ""


class CoverageMatrix(StrictModel):
    """覆盖矩阵及有限补齐元信息。"""

    version: int = Field(default=1, ge=1)
    contract_version: int = Field(ge=1)
    round_count: int = Field(default=0, ge=0, le=3)
    items: list[CoverageMatrixItem] = Field(default_factory=list)
    rounds: list[CoverageRoundSummary] = Field(default_factory=list)
    accepted_gap_ids: list[str] = Field(default_factory=list)
    partial_success: bool = False


class VariableDefinition(StrictModel):
    """可执行用例中的变量定义。"""

    name: str
    source: Literal["environment", "input", "precondition", "response", "constant"]
    source_path: str = ""


class VariableProducer(StrictModel):
    """声明节点执行后如何从受控响应中产生 Run 级变量。"""

    name: str
    extractor_type: Literal["json_pointer", "header", "cookie", "status_code", "regex"]
    source_path: str = ""
    required: bool = True
    sensitive: bool = False


class VariableConsumer(StrictModel):
    """声明变量写入请求的确定位置，禁止运行时猜测登录或鉴权语义。"""

    name: str
    destination: Literal["path", "query", "header", "cookie", "body"]
    field_path: str
    required: bool = True
    default_policy: Literal["error", "use_default"] = "error"
    default_value: Any = None


class RetryPolicy(StrictModel):
    """执行节点重试策略；写请求只有显式幂等确认后才可重试。"""

    max_attempts: int = Field(default=1, ge=1, le=3)
    idempotent: bool = False
    idempotency_key_header: str = ""
    confirmed: bool = False


class FailurePolicy(StrictModel):
    """前置失败后的确定性传播策略。"""

    on_failure: Literal["block_descendants", "continue_independent"] = "block_descendants"


class AssertionDefinition(StrictModel):
    """白名单断言定义。"""

    operator: Literal["equals", "not_equals", "contains", "exists", "status_code", "schema"]
    actual_path: str = ""
    expected: Any = None


class ExecutableRequest(StrictModel):
    """不含真实 Host 的可执行请求。"""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    headers: dict[str, Any] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    cookies: dict[str, Any] = Field(default_factory=dict)
    body: Any = None

    @field_validator("path")
    @classmethod
    def relative_path_only(cls, value: str) -> str:
        """执行请求只能保存相对路径。"""

        if not value.startswith("/") or "://" in value:
            raise ValueError("可执行请求 path 必须是相对路径")
        return value


class ExecutableCase(StrictModel):
    """通过静态校验后才允许进入执行预览的用例。"""

    executable_case_id: str
    artifact_schema_version: int = Field(default=2, ge=2, le=3)
    version: int = Field(default=1, ge=1)
    base_case_id: str
    contract_id: str
    name: str
    risk_level: Literal["low", "medium", "high"]
    high_risk_approved: bool = False
    document_sla_ms: int | None = Field(default=None, gt=0)
    target_id: str = ""
    request: ExecutableRequest
    precondition_case_ids: list[str] = Field(default_factory=list)
    assertions: list[AssertionDefinition] = Field(default_factory=list)
    variables: list[VariableDefinition] = Field(default_factory=list)
    variable_producers: list[VariableProducer] = Field(default_factory=list)
    variable_consumers: list[VariableConsumer] = Field(default_factory=list)
    data_refs: list[str] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    setup_script: str = ""
    teardown_script: str = ""
    observation_targets: list[str] = Field(default_factory=list)
    generation_kernel: Literal[
        "legacy", "v2_minimal", "v2_fused", "v2_core_workflow", "human",
    ] = "v2_minimal"
    generation_sources: list[str] = Field(default_factory=list)
    prompt_sha256: str = ""
    source_version_sha256: str = ""
    validation_status: Literal["pending", "ready", "disabled"] = "pending"
    validation_issues: list[ReviewIssue] = Field(default_factory=list)
    review_status: Literal["confirmed_candidate", "confirmed", "disabled"] = "confirmed_candidate"
    enabled: bool = False


class GenerationProvenance(StrictModel):
    """记录一次生成实际使用的内核、输入版本和 Prompt。"""

    attempt_id: str = ""
    generation_kernel: Literal[
        "legacy", "v2_minimal", "v2_fused", "v2_core_workflow", "human",
    ]
    contract_ids: list[str] = Field(default_factory=list)
    input_versions: dict[str, int] = Field(default_factory=dict)
    prompt_ids: list[str] = Field(default_factory=list)
    prompt_sha256: dict[str, str] = Field(default_factory=dict)
    model_names: list[str] = Field(default_factory=list)
    deterministic_case_count: int = Field(default=0, ge=0)
    llm_case_count: int = Field(default=0, ge=0)
    rejected_case_count: int = Field(default=0, ge=0)
    ai_supplement_status: Literal["not_called", "succeeded", "partial", "failed"] = "not_called"
    rejections: list["GenerationRejection"] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class GenerationRejection(StrictModel):
    """单条模型候选的脱敏拒绝摘要。"""

    contract_id: str
    item_index: int
    model_call_id: str | None = None
    prompt_id: str
    prompt_sha256: str
    error_code: str
    field_path: str = ""
    rejection_stage: Literal["response", "schema", "grounding", "completeness", "deduplication"]
    suggestion: str


class StageEvent(StrictModel):
    """面向测试人员的脱敏阶段事件，不保存正文和 Secret。"""

    event_id: str
    task_id: str
    attempt_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None
    level: Literal["debug", "info", "warning", "error"] = "info"
    stage: str
    node: str
    event_type: Literal[
        "started", "progress", "artifact", "review", "completed", "failed",
        "skipped", "retry", "rejected",
    ]
    status: str
    message: str
    input_versions: dict[str, int] = Field(default_factory=dict)
    output_versions: dict[str, int] = Field(default_factory=dict)
    duration_ms: int | None = Field(default=None, ge=0)
    model_call_id: str | None = None
    error_code: str | None = None
    workflow_id: str | None = None
    workflow_version: str | None = None
    workflow_sha256: str | None = None
    prompt_sha256: str | None = None
    created_at: str = Field(default_factory=utc_now)


class WorkflowProvenance(StrictModel):
    """证明阶段真实运行的 Workflow、版本和 Prompt 快照。"""

    workflow_id: str
    workflow_version: str
    workflow_sha256: str
    prompt_sha256: dict[str, str] = Field(default_factory=dict)
    input_versions: dict[str, int] = Field(default_factory=dict)
    node_ids: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorkflowRuntimeContext:
    """Workflow 的进程内运行上下文。

    回调由 Runner 注入且不序列化，确保生成图既能写脱敏事件和调用统一模型
    包装器，又无法获知 TaskStore 路径或持久化实现。
    """

    task_id: str
    attempt_id: str
    workflow_id: str
    workflow_version: str
    input_versions: dict[str, int]
    event_sink: Callable[[StageEvent], None]
    model_invoker: Callable[[str, str, str], str] | None = None


class WorkflowResult(StrictModel):
    """三个生成 Workflow 交给 V2 控制平面的统一无副作用结果。"""

    status: Literal["ready", "partial_ready", "failed"]
    items: list[dict[str, Any]] = Field(default_factory=list)
    rejections: list[GenerationRejection] = Field(default_factory=list)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    workflow_provenance: WorkflowProvenance


class ModelUsageRecord(StrictModel):
    """单次模型调用的供应商报告用量和 Prompt 来源。"""

    call_id: str
    attempt_id: str
    stage: str
    node: str
    prompt_id: str
    prompt_sha256: str
    model_name: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    reported: bool = False
    retry_number: int = Field(default=0, ge=0)
    started_at: str = Field(default_factory=utc_now)
    finished_at: str = Field(default_factory=utc_now)
    duration_ms: int = Field(default=0, ge=0)
    status: Literal["succeeded", "failed", "rejected"] = "succeeded"


class PerformanceEvaluation(StrictModel):
    """保存单次耗时、阈值来源和连续验证依据。"""

    duration_ms: int = Field(ge=0)
    threshold_ms: int = Field(gt=0)
    threshold_source: Literal["document", "project", "environment", "default"]
    status: Literal["within_threshold", "warning", "performance_candidate", "not_applicable"]
    basis: str
    qualifying_run_ids: list[str] = Field(default_factory=list)


class CaseResult(StrictModel):
    """单条可执行用例的脱敏结果。"""

    case_id: str
    status: Literal["passed", "failed", "error", "skipped", "cancelled"]
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    step_results: list[dict[str, Any]] = Field(default_factory=list)
    request_summary: dict[str, Any] = Field(default_factory=dict)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    assertion_results: list[dict[str, Any]] = Field(default_factory=list)
    failure_classification: Literal[
        "product_defect_candidate", "environment_blocked", "test_data_issue",
        "test_case_issue", "performance_candidate", "unknown", "none",
    ] = "none"
    error_signature: str = ""
    performance_evaluation: PerformanceEvaluation | None = None


class ExecutionPlanNode(StrictModel):
    """执行计划中的不可变请求节点；字段与纯编译器输出保持一一对应。"""

    node_id: str
    executable_case_id: str
    write_operation: bool = False
    request: ExecutableRequest | None = None
    producers: list[VariableProducer] = Field(default_factory=list)
    consumers: list[VariableConsumer] = Field(default_factory=list)
    session_produces: list[str] = Field(default_factory=list)
    session_consumes: list[str] = Field(default_factory=list)
    assertions: list[AssertionDefinition] = Field(default_factory=list)
    observation_targets: list[str] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    setup_capabilities: list[str] = Field(default_factory=list)
    teardown_capabilities: list[str] = Field(default_factory=list)


class ExecutionPlanEdge(StrictModel):
    """带来源的有向依赖边，便于 Review 和失败归因。"""

    from_node: str
    to_node: str
    source_type: Literal[
        "explicit_precondition", "variable", "cookie_session", "csrf", "manual_order",
    ]
    source_ref: str = ""
    reason: str


class ExecutionPlan(StrictModel):
    """创建 Run 的唯一业务输入；不接受 Host、凭证、镜像或命令。"""

    plan_id: str
    artifact_schema_version: int = Field(default=1, ge=1, le=1)
    task_id: str
    version: int = Field(ge=1)
    source_executable_version: int = Field(ge=1)
    source_executable_sha256: str
    target_id: str
    environment: str
    target_policy_sha256: str = ""
    resource_policy_id: str
    egress_policy_id: str
    policy_version: str = ""
    credential_profile_ref: str = ""
    nodes: list[ExecutionPlanNode] = Field(default_factory=list)
    edges: list[ExecutionPlanEdge] = Field(default_factory=list)
    topological_order: list[str] = Field(default_factory=list)
    node_count: int = Field(default=0, ge=0)
    edge_count: int = Field(default=0, ge=0)
    write_operation_count: int = Field(default=0, ge=0)
    high_risk_count: int = Field(default=0, ge=0)
    teardown_count: int = Field(default=0, ge=0)
    confirmation_summary: dict[str, int] = Field(default_factory=dict)
    confirmation_sha256: str
    sha256: str = ""
    status: Literal["draft", "ready", "confirmed", "stale"] = "draft"
    blockers: list[ReviewIssue] = Field(default_factory=list)
    created_by: str = ""
    review_reason: str = ""
    confirmed_by: str = ""
    confirmed_at: str | None = None
    confirmation_reason: str = ""
    created_at: str = Field(default_factory=utc_now)


class ExecutionStepResult(StrictModel):
    """阶段四单节点结果；blocked 与根因失败必须分开记录。"""

    step_id: str
    node_id: str
    executable_case_id: str
    status: Literal["passed", "failed", "error", "blocked", "skipped", "cancelled", "timed_out"]
    started_at: str
    finished_at: str
    duration_ms: int = Field(ge=0)
    blocked_by: list[str] = Field(default_factory=list)
    extracted_variables: list[str] = Field(default_factory=list)
    request_summary: dict[str, Any] = Field(default_factory=dict)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    assertion_results: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ExecutionRun(StrictModel):
    """一次独立执行尝试；重试必须创建新 Run。"""

    run_id: str
    task_id: str
    executable_case_version: int = Field(ge=1)
    execution_plan_id: str | None = None
    execution_plan_version: int | None = Field(default=None, ge=1)
    execution_plan_sha256: str = ""
    environment: str
    target_id: str
    resolved_base_url_masked: str = ""
    status: Literal[
        "created", "validating", "provisioning", "running", "reporting",
        "succeeded", "failed", "cancelled", "timed_out",
    ] = "created"
    created_by: str
    confirmed_by: str
    confirmation_sha256: str
    config_release_id: str | None = None
    created_at: str = Field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    node_summary: dict[str, int] = Field(default_factory=dict)
    retry_of_run_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class DefectDraft(StrictModel):
    """只在本地保存、编辑和下载的缺陷草稿。"""

    draft_id: str
    version: int = Field(ge=1)
    task_id: str
    run_id: str
    case_ids: list[str]
    title: str
    module: str
    interface: str
    severity_suggestion: Literal["low", "medium", "high", "critical"] = "medium"
    environment: str
    preconditions: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
    masked_request: dict[str, Any] = Field(default_factory=dict)
    expected_result: str
    actual_result: str
    status_code: int | None = None
    request_id: str = ""
    error_summary: str = ""
    evidence_links: list[str] = Field(default_factory=list)
    ai_analysis: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    open_questions: list[str] = Field(default_factory=list)
    manual_reason: str = ""
    created_by: str
    updated_by: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    sha256: str = ""


TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({
        "waiting_contract_review", "waiting_case_review", "waiting_executable_review",
        "waiting_execution_confirmation",
        "partial_success", "succeeded", "failed", "cancelled",
    }),
    "waiting_contract_review": frozenset({"pending", "cancelled"}),
    "waiting_case_review": frozenset({"pending", "cancelled"}),
    "waiting_executable_review": frozenset({"pending", "waiting_execution_confirmation", "cancelled"}),
    "waiting_execution_confirmation": frozenset({"succeeded", "partial_success", "cancelled"}),
    "partial_success": frozenset(),
    "succeeded": frozenset(),
    "failed": frozenset({"pending"}),
    "cancelled": frozenset(),
}

RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"validating", "cancelled"}),
    "validating": frozenset({"provisioning", "failed", "cancelled"}),
    "provisioning": frozenset({"running", "failed", "cancelled", "timed_out"}),
    "running": frozenset({"reporting", "failed", "cancelled", "timed_out"}),
    "reporting": frozenset({"succeeded", "failed"}),
    "succeeded": frozenset(), "failed": frozenset(), "cancelled": frozenset(), "timed_out": frozenset(),
}


def assert_transition(current: str, target: str, *, kind: Literal["task", "run"] = "task") -> None:
    """校验状态迁移，不合法时抛出 ValueError 并保持原状态。"""

    transitions = TASK_TRANSITIONS if kind == "task" else RUN_TRANSITIONS
    if target not in transitions.get(current, frozenset()):
        raise ValueError(f"非法{kind}状态迁移: {current} -> {target}")
