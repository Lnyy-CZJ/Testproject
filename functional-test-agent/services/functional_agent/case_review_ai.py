"""测试用例在线 Review 的受控 LLM 建议 Adapter。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agents.functional_test.prompts.review_test_cases import REVIEW_TEST_CASES_PROMPT
from services.common.case_review import CaseReviewService, case_content_sha256, normalize_cases, validate_cases
from services.common.errors import ServiceError
from services.common.review import parse_points
from services.common.task_models import utc_now
from services.common.versioned_review import VersionedReviewStore
from services.functional_agent.review_ai import _extract_json, _requirements_context


class CaseReviewAIRequest(BaseModel):
    """不可变用例 AI 请求信封。"""

    schema_version: int = 1
    request_version: int
    operation: Literal["supplement", "rewrite_selected", "generate_from_instruction"]
    base_revision: int
    base_sha256: str
    selected_ids: list[str] = Field(default_factory=list)
    scope: dict[str, list[str]] = Field(default_factory=dict)
    instruction: str = ""
    requested_by_user_id: str
    requested_at: str
    idempotency_key_sha256: str
    request_sha256: str


def case_request_sha(payload: dict[str, Any]) -> str:
    """计算不含 request_sha256 自身的稳定请求摘要。"""

    safe = {key: value for key, value in payload.items() if key != "request_sha256"}
    return hashlib.sha256(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _confirmed_points(store, task_id: str, point_ids: set[str]) -> list[dict[str, Any]]:
    """读取当前任务确认测试点摘要，不读取其他任务或历史 output。"""

    task_dir = store.task_dir(task_id)
    record = store.load(task_id) or {}
    request_payload = VersionedReviewStore.read_json(task_dir / "request.json")
    relative = (record.get("review") or {}).get("relative_path") or request_payload.get("review_relative_path")
    if not relative:
        return [{"id": point_id} for point_id in sorted(point_ids)]
    path = (task_dir / str(relative)).resolve()
    if task_dir not in path.parents or not path.is_file() or path.is_symlink():
        raise ServiceError(422, "CASE_REFERENCE_INVALID", "确认测试点文件不存在")
    points = parse_points(VersionedReviewStore.read_json(path))
    return [
        {key: item.get(key, "") for key in ("id", "module", "feature", "scenario", "test_point", "risk_level")}
        for item in points if isinstance(item, dict) and item.get("id") in point_ids
    ]


def run_case_review_ai(
    store, task_id: str, request_version: int, *,
    max_context_cases: int = 300, max_context_points: int = 300, max_suggestions: int = 100,
) -> dict[str, Any]:
    """调用当前模型并保存通过动作、引用与保护字段校验的建议。"""

    task_dir = store.task_dir(task_id)
    ai_dir = task_dir / "input" / "case-review-ai"
    request_path = ai_dir / f"request-v{request_version}.json"
    request = CaseReviewAIRequest.model_validate(VersionedReviewStore.read_json(request_path))
    service = CaseReviewService(store)
    review = service.load(task_id)
    if review["revision"] != request.base_revision or review["sha256"] != request.base_sha256:
        raise ServiceError(409, "CASE_REVIEW_AI_BASE_CHANGED", "用例 AI 建议基准草稿已变化")
    cases = review["cases"]
    modules = set(request.scope.get("modules", []))
    features = set(request.scope.get("features", []))
    scoped = [
        item for item in cases if isinstance(item, dict)
        and (not modules or item.get("module") in modules)
        and (not features or item.get("feature") in features)
    ]
    if len(scoped) > max_context_cases:
        raise ServiceError(422, "CASE_REVIEW_AI_SCOPE_REQUIRED", "用例草稿过大，请先限定模块或功能范围")
    point_ids = set(review["confirmed_test_point_ids"])
    points = _confirmed_points(store, task_id, point_ids)
    if len(points) > max_context_points:
        raise ServiceError(422, "CASE_REVIEW_AI_SCOPE_REQUIRED", "确认测试点过多，请先限定分析范围")
    requirements = _requirements_context(task_dir)
    prompt = REVIEW_TEST_CASES_PROMPT.format(
        operation=request.operation,
        test_points=json.dumps(points, ensure_ascii=False),
        requirements=json.dumps(requirements, ensure_ascii=False),
        cases=json.dumps([{key: item.get(key, "") for key in ("case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result")} for item in scoped], ensure_ascii=False),
        selected_ids=json.dumps(request.selected_ids, ensure_ascii=False),
        instruction=json.dumps(request.instruction, ensure_ascii=False),
    )
    if len(prompt) > 120_000:
        raise ServiceError(422, "CASE_REVIEW_AI_SCOPE_REQUIRED", "用例 AI 上下文超过限制，请缩小范围")
    from agents.common.config.settings import llm
    from agents.common.utils.token_usage import invoke_with_token_usage

    response = invoke_with_token_usage(llm, prompt, "test_cases_review_ai")
    parsed = _extract_json(str(getattr(response, "content", response)))
    if len(parsed["suggestions"]) > max_suggestions:
        raise ServiceError(422, "CASE_REVIEW_AI_RESPONSE_INVALID", "用例 AI 建议数量超过上限")
    by_id = {item.get("case_id"): item for item in cases if isinstance(item, dict) and item.get("case_id")}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    expected_action = "replace" if request.operation == "rewrite_selected" else "add"
    for raw in parsed["suggestions"]:
        if not isinstance(raw, dict):
            rejected.append({"reason": "建议不是对象"})
            continue
        action, target = raw.get("action"), raw.get("target_id")
        if action != expected_action or (action == "replace" and target not in request.selected_ids):
            rejected.append({"reason": "建议动作或目标不合法"})
            continue
        proposal = raw.get("case")
        if not isinstance(proposal, dict):
            rejected.append({"reason": "建议用例不是对象"})
            continue
        proposal = dict(proposal)
        if action == "replace":
            original = by_id.get(target)
            if not original:
                rejected.append({"reason": "目标用例不存在"})
                continue
            if priority_order.get(proposal.get("priority"), 99) > priority_order.get(original.get("priority"), 99):
                rejected.append({"reason": "改写建议降低了优先级"})
                continue
            # 保护字段以当前草稿为准，模型无权修改或清空。
            for field in ("case_id", "test_point_id", "actual_result"):
                proposal[field] = original.get(field, "")
        elif proposal.get("case_id") in by_id or proposal.get("test_point_id") not in point_ids:
            rejected.append({"reason": "新增建议 ID 重复或测试点引用无效"})
            continue
        normalized = normalize_cases([proposal])[0]
        validation = validate_cases([normalized], confirmed_point_ids={normalized.get("test_point_id")} if normalized.get("test_point_id") else set())
        if validation.errors:
            rejected.append({"reason": "建议未通过字段校验"})
            continue
        digest = hashlib.sha256((request.request_sha256 + str(action) + str(target) + case_content_sha256([normalized])).encode()).hexdigest()[:16]
        accepted.append({
            "suggestion_id": f"case_suggestion_{digest}", "action": action, "target_id": target,
            "case": normalized, "reason": str(raw.get("reason", ""))[:500],
            "source_basis": str(raw.get("source_basis", ""))[:1000], "validation": validation.model_dump(),
        })
    model_name = str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))
    envelope = {
        "schema_version": 1, "request_version": request_version, "operation": request.operation,
        "base_revision": request.base_revision, "base_sha256": request.base_sha256,
        "model_name": model_name, "prompt_bundle_sha256": os.getenv("PROMPT_BUNDLE_SHA256", ""),
        "started_at": request.requested_at, "finished_at": utc_now(), "summary": str(parsed.get("summary", ""))[:1000],
        "suggestions": accepted, "rejected_suggestions": rejected, "warnings": [],
    }
    suggestion_path = ai_dir / f"suggestions-v{request_version}.json"
    VersionedReviewStore.atomic_create(suggestion_path, json.dumps(envelope, ensure_ascii=False, indent=2).encode())
    return {
        "request_version": request_version, "suggestion_sha256": hashlib.sha256(suggestion_path.read_bytes()).hexdigest(),
        "suggestion_count": len(parsed["suggestions"]), "valid_suggestion_count": len(accepted),
        "model_name": model_name, "relative_path": suggestion_path.relative_to(task_dir).as_posix(),
    }
