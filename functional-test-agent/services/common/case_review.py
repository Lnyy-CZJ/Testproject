"""在线测试用例 Review 的规范化、校验、覆盖和文件事务。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from services.common.errors import ServiceError
from services.common.review import ValidationIssue, normalize_compare_text
from services.common.task_models import utc_now
from services.common.task_store import TaskStore
from services.common.versioned_review import TEST_CASE_SPEC, VersionedReviewStore


CASE_FIELDS = (
    "case_id", "test_point_id", "module", "feature", "scenario", "case_name",
    "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result",
)
TEXT_LIMITS = {
    "case_id": 64, "test_point_id": 64, "module": 200, "feature": 200,
    "scenario": 500, "case_name": 500, "expected_result": 4000, "actual_result": 4000,
}
PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})


class CoverageSummary(BaseModel):
    """确认测试点与当前用例引用的覆盖摘要。"""

    confirmed_test_points: int
    covered_test_points: int
    uncovered_test_points: int
    uncovered_ids: list[str] = Field(default_factory=list)


class CaseReviewValidation(BaseModel):
    """服务端权威用例校验结果。"""

    valid_for_confirm: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    coverage: CoverageSummary


def parse_cases(payload: Any) -> list[Any]:
    """接受列表及两个历史包装键，拒绝其他顶层结构。"""

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("test_cases", "cases"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ServiceError(422, "CASE_REVIEW_FILE_INVALID", "测试用例 JSON 必须包含用例数组")


def _list_text(value: Any) -> Any:
    """兼容数组或多行文本；非法类型保留给校验器定位。"""

    if value is None:
        return []
    if isinstance(value, list):
        return [item.strip() if isinstance(item, str) else item for item in value]
    if isinstance(value, str):
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        return [re.sub(r"^\s*\d+[\.、\)]\s*", "", line) for line in lines]
    return value


def normalize_cases(cases: list[Any]) -> list[Any]:
    """规范化标准字段并原样保留未知扩展字段。"""

    normalized: list[Any] = []
    for item in cases:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        ordered: dict[str, Any] = {}
        for field in CASE_FIELDS:
            value = item.get(field, [] if field in {"preconditions", "test_steps"} else ({} if field == "test_data" else ""))
            if field in {"preconditions", "test_steps"}:
                value = _list_text(value)
            elif isinstance(value, str):
                value = value.strip()
            ordered[field] = value
        for key, value in item.items():
            if key not in ordered:
                ordered[key] = value
        normalized.append(ordered)
    return normalized


def canonical_case_bytes(cases: list[Any]) -> bytes:
    """返回稳定 JSON 字节，用于限制、diff、CAS 和幂等。"""

    return json.dumps(normalize_cases(cases), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def case_content_sha256(cases: list[Any]) -> str:
    """计算规范化用例正文 SHA-256。"""

    return hashlib.sha256(canonical_case_bytes(cases)).hexdigest()


def diff_cases(original: list[Any], current: list[Any]) -> dict[str, int]:
    """以 case_id 为主键计算 O(n) 用例变更摘要。"""

    old = {item.get("case_id"): item for item in normalize_cases(original) if isinstance(item, dict) and item.get("case_id")}
    new = {item.get("case_id"): item for item in normalize_cases(current) if isinstance(item, dict) and item.get("case_id")}
    modified = unchanged = priority_changed = 0
    for case_id in old.keys() & new.keys():
        if canonical_case_bytes([old[case_id]]) == canonical_case_bytes([new[case_id]]):
            unchanged += 1
        else:
            modified += 1
        priority_changed += old[case_id].get("priority") != new[case_id].get("priority")
    return {
        "added": len(new.keys() - old.keys()), "modified": modified,
        "deleted": len(old.keys() - new.keys()), "unchanged": unchanged,
        "priority_changed": priority_changed,
    }


def _json_shape(value: Any, *, max_depth: int = 20, max_nodes: int = 5000) -> bool:
    """以迭代方式限制测试数据深度和节点数，避免深层 JSON 消耗攻击。"""

    stack = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            return False
        if isinstance(current, dict):
            stack.extend((key, depth + 1) for key in current)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return True


def validate_cases(
    cases: list[Any], *, confirmed_point_ids: set[str], original: list[Any] | None = None,
    max_cases: int = 2000, max_bytes: int = 10 * 1024 * 1024, max_characters: int = 1_000_000,
) -> CaseReviewValidation:
    """执行确定性用例校验；业务错误允许保存但阻止最终确认。"""

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    normalized = normalize_cases(cases)
    if not normalized:
        errors.append(ValidationIssue(level="error", code="CASES_EMPTY", message="至少保留一个测试用例"))
    if len(normalized) > max_cases:
        errors.append(ValidationIssue(level="error", code="CASES_LIMIT_EXCEEDED", message=f"测试用例数量超过 {max_cases} 条"))
    try:
        content = canonical_case_bytes(normalized)
        if len(content) > max_bytes or len(content.decode("utf-8")) > max_characters:
            errors.append(ValidationIssue(level="error", code="CASE_REVIEW_SIZE_EXCEEDED", message="测试用例草稿超过大小限制"))
    except (TypeError, UnicodeError):
        errors.append(ValidationIssue(level="error", code="CASE_FIELD_TYPE_INVALID", message="用例包含无法序列化的字段"))

    ids: defaultdict[str, list[int]] = defaultdict(list)
    exact: defaultdict[tuple[str, ...], list[int]] = defaultdict(list)
    names: defaultdict[str, list[int]] = defaultdict(list)
    covered: set[str] = set()
    for index, item in enumerate(normalized):
        if not isinstance(item, dict):
            errors.append(ValidationIssue(level="error", code="CASE_NOT_OBJECT", message="测试用例必须是对象", row_index=index))
            continue
        case_id = item.get("case_id") if isinstance(item.get("case_id"), str) else None
        point_id = item.get("test_point_id") if isinstance(item.get("test_point_id"), str) else None
        if any(str(key).startswith("_") for key in item):
            errors.append(ValidationIssue(level="error", code="CLIENT_PRIVATE_FIELD", message="用例包含客户端内部字段", row_index=index, point_id=case_id))
        for field in ("case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "expected_result", "actual_result"):
            value = item.get(field, "")
            if not isinstance(value, str):
                errors.append(ValidationIssue(level="error", code="CASE_FIELD_TYPE_INVALID", message=f"{field} 必须是字符串", row_index=index, point_id=case_id, field=field))
                continue
            if "\x00" in value:
                errors.append(ValidationIssue(level="error", code="TEXT_CONTAINS_NUL", message=f"{field} 不能包含 NUL", row_index=index, point_id=case_id, field=field))
            if field not in {"actual_result"} and not value:
                errors.append(ValidationIssue(level="error", code="CASE_FIELD_REQUIRED", message=f"{field} 不能为空", row_index=index, point_id=case_id, field=field))
            if TEXT_LIMITS.get(field) and len(value) > TEXT_LIMITS[field]:
                errors.append(ValidationIssue(level="error", code="CASE_FIELD_TOO_LONG", message=f"{field} 超过长度限制", row_index=index, point_id=case_id, field=field))
        if item.get("priority") and item.get("priority") not in PRIORITIES:
            errors.append(ValidationIssue(level="error", code="CASE_PRIORITY_INVALID", message="优先级必须是 P0/P1/P2/P3", row_index=index, point_id=case_id, field="priority"))
        if case_id:
            ids[case_id].append(index)
        if point_id:
            if confirmed_point_ids and point_id not in confirmed_point_ids:
                errors.append(ValidationIssue(level="error", code="CASE_REFERENCE_INVALID", message="引用的测试点不存在于确认版本", row_index=index, point_id=case_id, field="test_point_id"))
            else:
                covered.add(point_id)
        for field in ("preconditions", "test_steps"):
            value = item.get(field)
            if not isinstance(value, list) or any(not isinstance(entry, str) for entry in value):
                errors.append(ValidationIssue(level="error", code="CASE_FIELD_TYPE_INVALID", message=f"{field} 必须是字符串数组", row_index=index, point_id=case_id, field=field))
            elif field == "test_steps" and not value:
                errors.append(ValidationIssue(level="error", code="CASE_STEPS_EMPTY", message="测试步骤不能为空", row_index=index, point_id=case_id, field=field))
            elif len(value) > 100 or any(len(entry) > 2000 for entry in value):
                errors.append(ValidationIssue(level="error", code="CASE_LIST_LIMIT_EXCEEDED", message=f"{field} 超过限制", row_index=index, point_id=case_id, field=field))
        data = item.get("test_data")
        if not isinstance(data, (dict, list, str)):
            errors.append(ValidationIssue(level="error", code="CASE_FIELD_TYPE_INVALID", message="test_data 必须是对象、数组或字符串", row_index=index, point_id=case_id, field="test_data"))
        elif not _json_shape(data):
            errors.append(ValidationIssue(level="error", code="CASE_DATA_TOO_COMPLEX", message="测试数据嵌套或节点数超过限制", row_index=index, point_id=case_id, field="test_data"))
        if item.get("actual_result"):
            warnings.append(ValidationIssue(level="warning", code="ACTUAL_RESULT_PRESENT", message="实际结果为只读历史字段，不会由 AI 修改", row_index=index, point_id=case_id, field="actual_result"))
        comparable = [item.get(field) for field in ("test_point_id", "case_name", "preconditions", "test_steps", "test_data", "expected_result")]
        if all(value not in (None, "", [], {}) for value in comparable):
            exact[tuple(json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else normalize_compare_text(value) for value in comparable)].append(index)
        if isinstance(item.get("case_name"), str) and item.get("case_name"):
            names[normalize_compare_text(item["case_name"])].append(index)

    for indexes in ids.values():
        if len(indexes) > 1:
            errors.extend(ValidationIssue(level="error", code="CASE_ID_DUPLICATE", message="测试用例 ID 重复", row_index=index, related_rows=indexes) for index in indexes)
    for indexes in exact.values():
        if len(indexes) > 1:
            errors.extend(ValidationIssue(level="error", code="CASE_EXACT_DUPLICATE", message="测试用例内容完全重复", row_index=index, related_rows=indexes) for index in indexes)
    for indexes in names.values():
        if len(indexes) > 1 and not any(set(indexes) == set(group) for group in exact.values()):
            warnings.extend(ValidationIssue(level="warning", code="CASE_NAME_REUSED", message="相同用例名称用于不同数据或预期", row_index=index, related_rows=indexes) for index in indexes)
    uncovered = sorted(confirmed_point_ids - covered)
    if uncovered:
        errors.append(ValidationIssue(level="error", code="TEST_POINT_UNCOVERED", message=f"仍有 {len(uncovered)} 个确认测试点没有用例覆盖"))
    coverage = CoverageSummary(
        confirmed_test_points=len(confirmed_point_ids), covered_test_points=len(confirmed_point_ids & covered),
        uncovered_test_points=len(uncovered), uncovered_ids=uncovered,
    )
    return CaseReviewValidation(valid_for_confirm=not errors, errors=errors, warnings=warnings, coverage=coverage)


class CaseReviewService:
    """在 TaskStore 锁内管理用例原稿、草稿和不可变确认版本。"""

    def __init__(self, store: TaskStore):
        self.store = store
        self.files = VersionedReviewStore(store, TEST_CASE_SPEC)

    def original_cases(self, task_id: str) -> tuple[list[Any], dict[str, Any]]:
        """从登记产物读取并规范化模型用例原稿。"""

        payload, artifact = self.files.load_original(task_id)
        return normalize_cases(parse_cases(payload)), artifact

    def confirmed_point_ids(self, task_id: str) -> set[str]:
        """只读取当前任务 request 指向的确认测试点，禁止目录扫描。"""

        task_dir = self.store.task_dir(task_id)
        record = self.store.load(task_id) or {}
        request_path = task_dir / "request.json"
        try:
            request_payload = self.files.read_json(request_path)
        except ServiceError:
            request_payload = {}
        relative = (record.get("review") or {}).get("relative_path") or request_payload.get("review_relative_path")
        if not relative:
            return set()
        path = (task_dir / str(relative)).resolve()
        if task_dir not in path.parents or not path.is_file() or path.is_symlink():
            raise ServiceError(422, "CASE_REFERENCE_INVALID", "确认测试点文件不存在")
        from services.common.review import normalize_for_storage, parse_points

        return {
            item.get("id") for item in normalize_for_storage(parse_points(self.files.read_json(path)))
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        }

    def load(self, task_id: str, **limits: int) -> dict[str, Any]:
        """加载当前用例工作区；草稿缺失时以模型原稿作为 revision 0。"""

        original, artifact = self.original_cases(task_id)
        path = self.files.draft_path(task_id)
        if path.exists():
            envelope = self.files.read_json(path)
            cases = normalize_cases(parse_cases(envelope.get("test_cases", [])))
            revision = int(envelope.get("revision", 0))
            digest = str(envelope.get("content_sha256") or case_content_sha256(cases))
            if digest != case_content_sha256(cases):
                raise ServiceError(500, "STORAGE_WRITE_FAILED", "测试用例草稿完整性校验失败")
            saved_at, saved_by = envelope.get("saved_at"), envelope.get("saved_by_username")
        else:
            cases, revision, saved_at, saved_by = original, 0, None, None
            digest = case_content_sha256(cases)
        point_ids = self.confirmed_point_ids(task_id)
        if not point_ids:
            point_ids = {item.get("test_point_id") for item in cases if isinstance(item, dict) and item.get("test_point_id")}
        validation = validate_cases(cases, confirmed_point_ids=point_ids, original=original, **limits)
        return {
            "cases": cases, "original_cases": original, "revision": revision, "sha256": digest,
            "source_artifact_id": artifact["id"], "saved_at": saved_at, "saved_by_username": saved_by,
            "validation": validation.model_dump(), "coverage": validation.coverage.model_dump(),
            "diff_summary": diff_cases(original, cases), "confirmed_test_point_ids": sorted(point_ids),
        }

    def load_version(self, task_id: str, *, kind: str, version: int | None = None, **limits: int) -> dict[str, Any]:
        """读取用例原稿、草稿或确认版本，保持现有校验和覆盖协议。"""

        current = self.load(task_id, **limits)
        if kind == "draft":
            return {**current, "kind": "draft", "versions": self.files.confirmed_versions(task_id)}
        if kind == "generated":
            cases = current["original_cases"]
        elif kind == "confirmed" and version is not None:
            cases = normalize_cases(parse_cases(self.files.read_confirmed_version(task_id, version)))
        else:
            raise ServiceError(422, "INVALID_INPUT", "用例 Review 版本类型不受支持")
        validation = validate_cases(
            cases, confirmed_point_ids=set(current["confirmed_test_point_ids"]),
            original=current["original_cases"], **limits,
        )
        return {
            **current, "cases": cases, "revision": 0, "sha256": case_content_sha256(cases),
            "validation": validation.model_dump(), "coverage": validation.coverage.model_dump(),
            "diff_summary": diff_cases(current["original_cases"], cases), "kind": kind,
            "version": version if kind == "confirmed" else None,
            "versions": self.files.confirmed_versions(task_id),
        }

    def save_draft(self, task_id: str, cases: list[Any], *, revision: int, sha256: str, user_id: str, username: str, **limits: int) -> dict[str, Any]:
        """使用 revision/SHA CAS 原子保存用例草稿；冲突时绝不覆盖。"""

        with self.store.locked():
            current = self.load(task_id, **limits)
            if revision != current["revision"] or sha256 != current["sha256"]:
                raise ServiceError(409, "CASE_REVIEW_REVISION_CONFLICT", "用例草稿已被其他页面更新", {"current_revision": current["revision"], "current_sha256": current["sha256"], "saved_at": current.get("saved_at"), "saved_by": current.get("saved_by_username")})
            normalized = normalize_cases(cases)
            digest = case_content_sha256(normalized)
            if digest == current["sha256"] and current["revision"] > 0:
                return current
            validation = validate_cases(normalized, confirmed_point_ids=set(current["confirmed_test_point_ids"]), original=current["original_cases"], **limits)
            envelope = {
                "schema_version": 1, "revision": revision + 1, "content_sha256": digest,
                "base_generated_sha256": case_content_sha256(current["original_cases"]),
                "saved_by_user_id": user_id, "saved_by_username": username, "saved_at": utc_now(),
                "test_cases": normalized,
            }
            TaskStore.atomic_write_json(self.files.draft_path(task_id), envelope)
            record = self.store.load(task_id) or {}
            record["case_review_draft"] = {key: envelope[key] for key in ("revision", "content_sha256", "saved_by_user_id", "saved_by_username", "saved_at")}
            self.store.save(record)
            return {
                **current, "cases": normalized, "revision": revision + 1, "sha256": digest,
                "saved_at": envelope["saved_at"], "saved_by_username": username,
                "validation": validation.model_dump(), "coverage": validation.coverage.model_dump(),
                "diff_summary": diff_cases(current["original_cases"], normalized),
            }

    def confirm(self, task_id: str, *, revision: int, sha256: str, accept_warnings: bool, **limits: int) -> dict[str, Any]:
        """校验草稿并创建或复用不可变用例确认版本。"""

        with self.store.locked():
            current = self.load(task_id, **limits)
            if current["revision"] == 0:
                raise ServiceError(422, "CASE_REVIEW_DRAFT_REQUIRED", "请先保存测试用例草稿")
            if revision != current["revision"] or sha256 != current["sha256"]:
                raise ServiceError(409, "CASE_REVIEW_REVISION_CONFLICT", "用例草稿已被其他页面更新", {"current_revision": current["revision"], "current_sha256": current["sha256"]})
            validation = CaseReviewValidation.model_validate(current["validation"])
            if validation.errors:
                raise ServiceError(422, "CASE_REVIEW_VALIDATION_FAILED", "用例草稿仍有阻塞错误", {"validation": validation.model_dump()})
            if validation.warnings and not accept_warnings:
                raise ServiceError(409, "CASE_REVIEW_WARNING_CONFIRMATION_REQUIRED", "用例草稿包含警告，请确认后发布", {"validation": validation.model_dump()})
            record = self.store.load(task_id) or {}
            existing = record.get("case_review", {})
            if existing.get("sha256") == sha256 and existing.get("relative_path"):
                return existing
            for version, path in self.files.confirmed_files(task_id):
                try:
                    confirmed = normalize_cases(parse_cases(self.files.read_json(path)))
                except ServiceError:
                    continue
                if case_content_sha256(confirmed) == sha256:
                    return {"version": version, "relative_path": path.relative_to(self.store.task_dir(task_id)).as_posix(), "sha256": sha256, "confirmed_at": utc_now(), "test_case_count": len(confirmed)}
            version = max((item[0] for item in self.files.confirmed_files(task_id)), default=0) + 1
            path = self.files.create_confirmed(task_id, version, current["cases"])
            return {"version": version, "relative_path": path.relative_to(self.store.task_dir(task_id)).as_posix(), "sha256": sha256, "confirmed_at": utc_now(), "test_case_count": len(current["cases"])}

    def read_confirmed(self, task_id: str, metadata: dict[str, Any]) -> list[Any]:
        """按已登记相对路径读取确认版本并验证内容 SHA。"""

        task_dir = self.store.task_dir(task_id)
        path = (task_dir / str(metadata.get("relative_path", ""))).resolve()
        if task_dir not in path.parents or not path.is_file() or path.is_symlink():
            raise ServiceError(404, "ARTIFACT_NOT_READY", "确认用例版本不存在")
        cases = normalize_cases(parse_cases(self.files.read_json(path)))
        if case_content_sha256(cases) != metadata.get("sha256"):
            raise ServiceError(500, "STORAGE_WRITE_FAILED", "确认用例版本完整性校验失败")
        return cases
