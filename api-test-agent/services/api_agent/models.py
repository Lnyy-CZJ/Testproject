"""API 测试智能体 V2 的任务、Review、执行和缺陷草稿模型。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

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


class ReviewIssue(StrictModel):
    """冲突、歧义或未解决信息的统一表示。"""

    code: str
    field_path: str
    message: str
    severity: Literal["info", "warning", "blocker"] = "warning"
    source_pointer: str = ""


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
    version: int = Field(default=1, ge=1)
    name: str
    summary: str = ""
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path: str
    sla_ms: int | None = Field(default=None, gt=0)
    servers: list[ServerDefinition] = Field(default_factory=list)
    parameters: list[ContractParameter] = Field(default_factory=list)
    request_body: RequestBodyDefinition | None = None
    responses: list[ResponseDefinition] = Field(default_factory=list)
    security: list[SecurityRequirement] = Field(default_factory=list)
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


class BaseTestCase(StrictModel):
    """可人工 Review 的基础测试用例。"""

    case_id: str
    version: int = Field(default=1, ge=1)
    contract_id: str
    name: str
    objective: str
    dimension: str
    risk_level: Literal["low", "medium", "high"] = "low"
    preconditions: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    expected_results: list[str] = Field(default_factory=list)
    source: Literal["deterministic", "document", "llm", "human"]
    status: Literal["draft", "confirmed_candidate", "confirmed", "disabled"] = "draft"
    disabled_reason: str = ""
    change_history: list[dict[str, Any]] = Field(default_factory=list)


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


class CoverageMatrix(StrictModel):
    """覆盖矩阵及有限补齐元信息。"""

    version: int = Field(default=1, ge=1)
    contract_version: int = Field(ge=1)
    round_count: int = Field(default=0, ge=0, le=3)
    items: list[CoverageMatrixItem] = Field(default_factory=list)
    accepted_gap_ids: list[str] = Field(default_factory=list)
    partial_success: bool = False


class VariableDefinition(StrictModel):
    """可执行用例中的变量定义。"""

    name: str
    source: Literal["environment", "input", "precondition", "response", "constant"]
    source_path: str = ""


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
    setup_script: str = ""
    teardown_script: str = ""
    validation_status: Literal["pending", "ready", "disabled"] = "pending"
    validation_issues: list[ReviewIssue] = Field(default_factory=list)
    enabled: bool = False


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


class ExecutionRun(StrictModel):
    """一次独立执行尝试；重试必须创建新 Run。"""

    run_id: str
    task_id: str
    executable_case_version: int = Field(ge=1)
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
        "waiting_contract_review", "waiting_case_review", "waiting_execution_confirmation",
        "partial_success", "succeeded", "failed", "cancelled",
    }),
    "waiting_contract_review": frozenset({"pending", "cancelled"}),
    "waiting_case_review": frozenset({"pending", "cancelled"}),
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
