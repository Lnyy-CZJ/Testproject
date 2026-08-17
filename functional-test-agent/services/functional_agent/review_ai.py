"""功能测试在线 Review 的受控 LLM 建议 Adapter。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agents.functional_test.prompts.review_test_points import REVIEW_TEST_POINTS_PROMPT
from services.common.errors import ServiceError
from services.common.review import ReviewService, ReviewValidation, normalize_for_storage, review_content_sha256, validate_points
from services.common.task_models import utc_now


class ReviewAIRequest(BaseModel):
    """不可变 AI 请求信封。"""

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


def request_sha(payload: dict[str, Any]) -> str:
    """计算不含服务端 request_sha256 字段的稳定请求摘要。"""

    safe = {key: value for key, value in payload.items() if key != "request_sha256"}
    return hashlib.sha256(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _extract_json(text: str) -> dict[str, Any]:
    """解析标准或 fenced JSON，并只进行一次安全语法修复。"""

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            value = repair_json(candidate, return_objects=True)
        except Exception as exc:
            raise ServiceError(422, "REVIEW_AI_RESPONSE_INVALID", "AI 建议格式不合法") from exc
    if not isinstance(value, dict) or not isinstance(value.get("suggestions"), list):
        raise ServiceError(422, "REVIEW_AI_RESPONSE_INVALID", "AI 建议缺少结构化列表")
    return value


def _requirements_context(task_dir: Path) -> Any:
    """只从当前任务固定候选读取需求事实，不扫描其他任务或历史目录。"""

    candidates = sorted((task_dir / "work" / "output" / "requirements_docs").glob("**/test_seed.json"))
    candidates += sorted((task_dir / "work" / "output" / "requirements_docs").glob("**/requirements.json"))
    for path in candidates:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
    source = (task_dir / request_payload["input_relative_path"]).resolve()
    if task_dir not in source.parents or not source.is_file():
        return ""
    return source.read_text(encoding="utf-8")[:120_000]


def run_review_ai(store, task_id: str, request_version: int, *, max_context: int = 500, max_suggestions: int = 200) -> dict[str, Any]:
    """调用当前功能智能体模型并发布经过动作白名单校验的建议。"""

    task_dir = store.task_dir(task_id)
    request_path = task_dir / "input" / "review-ai" / f"request-v{request_version}.json"
    request = ReviewAIRequest.model_validate(json.loads(request_path.read_text(encoding="utf-8")))
    review = ReviewService(store).load(task_id)
    if review["revision"] != request.base_revision or review["sha256"] != request.base_sha256:
        raise ServiceError(409, "REVIEW_AI_BASE_CHANGED", "AI 建议基准草稿已变化")
    points = review["points"]
    modules = set(request.scope.get("modules", []))
    features = set(request.scope.get("features", []))
    scoped = [item for item in points if isinstance(item, dict) and (not modules or item.get("module") in modules) and (not features or item.get("feature") in features)]
    if len(scoped) > max_context:
        raise ServiceError(422, "REVIEW_AI_SCOPE_REQUIRED", "草稿过大，请先限定模块或功能范围")
    requirements = _requirements_context(task_dir)
    prompt = REVIEW_TEST_POINTS_PROMPT.format(operation=request.operation, requirements=json.dumps(requirements, ensure_ascii=False), points=json.dumps([{key: item.get(key, "") for key in ("id", "module", "feature", "scenario", "test_point", "risk_level")} for item in scoped], ensure_ascii=False), selected_ids=json.dumps(request.selected_ids, ensure_ascii=False), instruction=json.dumps(request.instruction, ensure_ascii=False))
    if len(prompt) > 120_000:
        raise ServiceError(422, "REVIEW_AI_SCOPE_REQUIRED", "AI 上下文过大，请缩小分析范围")
    from agents.common.config.settings import llm
    from agents.common.utils.token_usage import invoke_with_token_usage

    response = invoke_with_token_usage(llm, prompt, "test_points_review_ai")
    parsed = _extract_json(str(getattr(response, "content", response)))
    if len(parsed["suggestions"]) > max_suggestions:
        raise ServiceError(422, "REVIEW_AI_RESPONSE_INVALID", "AI 建议数量超过上限")
    by_id = {item.get("id"): item for item in points if isinstance(item, dict)}
    accepted, rejected = [], []
    for raw in parsed["suggestions"]:
        if not isinstance(raw, dict):
            rejected.append({"reason": "建议不是对象"})
            continue
        action, target = raw.get("action"), raw.get("target_id")
        expected = "replace" if request.operation == "rewrite_selected" else "add"
        if action != expected or (action == "replace" and target not in request.selected_ids):
            rejected.append({"reason": "建议动作或目标不合法"})
            continue
        point = raw.get("point")
        if not isinstance(point, dict):
            rejected.append({"reason": "建议测试点不是对象"})
            continue
        if action == "replace":
            original = by_id.get(target)
            if not original:
                rejected.append({"reason": "目标测试点不存在"})
                continue
            point["id"] = target
            order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
            if order.get(point.get("risk_level"), 99) > order.get(original.get("risk_level"), 99):
                point["risk_level"] = original.get("risk_level")
        normalized = normalize_for_storage([point])[0]
        validation = validate_points([normalized])
        digest = hashlib.sha256((request.request_sha256 + action + str(target) + review_content_sha256([normalized])).encode()).hexdigest()[:16]
        accepted.append({"suggestion_id": f"suggestion_{digest}", "action": action, "target_id": target, "point": normalized, "reason": str(raw.get("reason", ""))[:500], "source_basis": str(raw.get("source_basis", ""))[:1000], "validation": validation.model_dump()})
    model_name = str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))
    envelope = {"schema_version": 1, "request_version": request_version, "operation": request.operation, "base_revision": request.base_revision, "base_sha256": request.base_sha256, "model_name": model_name, "prompt_bundle_sha256": os.getenv("PROMPT_BUNDLE_SHA256", ""), "started_at": request.requested_at, "finished_at": utc_now(), "summary": str(parsed.get("summary", ""))[:1000], "suggestions": accepted, "rejected_suggestions": rejected, "warnings": []}
    path = task_dir / "input" / "review-ai" / f"suggestions-v{request_version}.json"
    ReviewService._atomic_create(path, json.dumps(envelope, ensure_ascii=False, indent=2).encode())
    return {"request_version": request_version, "suggestion_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "suggestion_count": len(parsed["suggestions"]), "valid_suggestion_count": len(accepted), "model_name": model_name, "relative_path": path.relative_to(task_dir).as_posix()}
