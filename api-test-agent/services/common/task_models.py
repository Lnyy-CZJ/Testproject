"""公共任务和产物模型。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


TaskStatus = Literal[
    "pending", "running", "waiting_review", "waiting_contract_review",
    "waiting_case_review", "waiting_execution_confirmation", "partial_success",
    "succeeded", "failed", "cancelled",
]
TERMINAL_STATUSES = frozenset({"partial_success", "succeeded", "failed", "cancelled"})


def utc_now() -> str:
    """返回带 UTC 时区的 ISO 时间。"""

    return datetime.now(UTC).isoformat()


class ArtifactModel(BaseModel):
    """已登记且允许下载的任务产物。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    name: str
    relative_path: str
    size: int = Field(ge=0)
    sha256: str
    stage: str
    created_at: str
    review_input: bool = False
    expired: bool = False


class PublicTaskModel(BaseModel):
    """返回浏览器的任务字段白名单。"""

    model_config = ConfigDict(extra="ignore")
    schema_version: int = 1
    id: str
    agent_type: str
    operation: str
    status: TaskStatus
    stage: str
    created_by_user_id: str
    created_by_username: str
    project_id: str
    project_name: str
    module_id: str
    module_name: str
    title: str = ""
    environment: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    resume_requested_at: str | None = None
    queued_at: str | None = None
    cancel_requested_at: str | None = None
    config_release_id: str | None = None
    config_release_version: int | None = None
    model_name: str | None = None
    prompt_bundle_sha256: str | None = None
    app_revision: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    artifacts_expire_at: str | None = None
    artifacts_expired: bool = False
    review: dict[str, Any] = Field(default_factory=dict)
    review_draft: dict[str, Any] = Field(default_factory=dict)
    review_ai: dict[str, Any] = Field(default_factory=dict)
    review_source: dict[str, Any] = Field(default_factory=dict)
    case_review: dict[str, Any] = Field(default_factory=dict)
    case_review_draft: dict[str, Any] = Field(default_factory=dict)
    case_review_ai: dict[str, Any] = Field(default_factory=dict)
    case_review_source: dict[str, Any] = Field(default_factory=dict)
    config_history: list[dict[str, Any]] = Field(default_factory=list)
    current_versions: dict[str, Any] = Field(default_factory=dict)
    completed_stages: list[str] = Field(default_factory=list)
    current_attempt_id: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    ui_capabilities: dict[str, bool] = Field(default_factory=dict)
    test_point_count: int = 0
    test_case_count: int = 0
    test_point_review_version: int | None = None
    test_case_review_version: int | None = None


def public_task(record: dict[str, Any]) -> dict[str, Any]:
    """按显式模型移除 PID、路径和其他内部字段。"""

    source = dict(record)
    source["title"] = str(source.get("title") or f"{source.get('project_name', '')} / {source.get('module_name', '')}").strip(" / ")
    summary = source.get("result_summary") or {}
    review = source.get("review") or {}
    case_review = source.get("case_review") or {}
    point_source = source.get("review_source") or {}
    case_source = source.get("case_review_source") or {}
    source["test_point_count"] = int(review.get("test_point_count") or point_source.get("test_point_count") or summary.get("test_point_count") or 0)
    source["test_case_count"] = int(case_review.get("test_case_count") or case_source.get("test_case_count") or summary.get("test_case_count") or 0)
    source["test_point_review_version"] = review.get("version")
    source["test_case_review_version"] = case_review.get("version")
    completed_items = source["test_case_count"] or source["test_point_count"]
    source["progress"] = {
        "stage": str(source.get("stage") or "queued"),
        "completed_items": completed_items,
        "total_items": None,
    }
    source["ui_capabilities"] = {
        "workbench_v2": bool(source.get("workbench_v2_enabled", False)),
        "mindmap_edit": bool(source.get("workbench_v2_enabled", False)),
        "table_readonly": bool(source.get("workbench_v2_enabled", False)),
    }
    payload = PublicTaskModel.model_validate(source).model_dump()
    # 嵌套 Review 元数据也执行字段白名单，避免相对路径逐步演变成公共协议。
    payload["review"] = {key: payload["review"].get(key) for key in ("version", "sha256", "confirmed_at", "test_point_count") if key in payload["review"]}
    payload["review_draft"] = {key: payload["review_draft"].get(key) for key in ("revision", "content_sha256", "saved_by_username", "saved_at") if key in payload["review_draft"]}
    payload["review_ai"] = {key: payload["review_ai"].get(key) for key in ("status", "operation", "request_version", "base_revision", "base_sha256", "requested_at", "started_at", "finished_at", "suggestion_count", "valid_suggestion_count", "model_name", "prompt_bundle_sha256", "error_code", "error_message") if key in payload["review_ai"]}
    payload["review_source"] = {key: payload["review_source"].get(key) for key in ("artifact_id", "sha256", "test_point_count") if key in payload["review_source"]}
    payload["case_review"] = {key: payload["case_review"].get(key) for key in ("version", "sha256", "confirmed_at", "test_case_count") if key in payload["case_review"]}
    payload["case_review_draft"] = {key: payload["case_review_draft"].get(key) for key in ("revision", "content_sha256", "saved_by_username", "saved_at") if key in payload["case_review_draft"]}
    payload["case_review_ai"] = {key: payload["case_review_ai"].get(key) for key in ("status", "operation", "request_version", "base_revision", "base_sha256", "requested_at", "started_at", "finished_at", "suggestion_count", "valid_suggestion_count", "model_name", "prompt_bundle_sha256", "error_code", "error_message") if key in payload["case_review_ai"]}
    payload["case_review_source"] = {key: payload["case_review_source"].get(key) for key in ("artifact_id", "sha256", "test_case_count") if key in payload["case_review_source"]}
    return payload
