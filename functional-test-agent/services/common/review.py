"""在线测试点 Review 的规范化、校验、版本与文件事务。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.common.errors import ServiceError
from services.common.task_models import utc_now
from services.common.task_store import TaskStore
from services.common.versioned_review import TEST_POINT_SPEC, VersionedReviewStore

STANDARD_FIELDS = ("id", "module", "feature", "scenario", "test_point", "risk_level")
FIELD_LIMITS = {"id": 64, "module": 200, "feature": 200, "scenario": 500, "test_point": 2000}
RISK_LEVELS = frozenset({"P0", "P1", "P2", "P3"})
MAX_POINTS = 5000


class ReviewPoint(BaseModel):
    """测试点标准字段；额外 JSON 字段允许往返但不由网页编辑。"""

    model_config = ConfigDict(extra="allow")
    id: str = ""
    module: str = ""
    feature: str = ""
    scenario: str = ""
    test_point: str = ""
    risk_level: str = ""


class ValidationIssue(BaseModel):
    """可定位到行和字段的稳定校验问题。"""

    level: str
    code: str
    message: str
    row_index: int | None = None
    point_id: str | None = None
    field: str | None = None
    related_rows: list[int] = Field(default_factory=list)


class ReviewValidation(BaseModel):
    """服务端权威校验结果。"""

    valid_for_resume: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]


def parse_points(payload: Any) -> list[Any]:
    """解析列表或兼容包装对象，拒绝没有测试点数组的结构。"""

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("test_points", "test_point", "points"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ServiceError(422, "REVIEW_FILE_INVALID", "Review JSON 必须包含测试点数组")


def normalize_compare_text(value: str) -> str:
    """生成只用于重复比较的文本，不改变最终保存正文。"""

    return " ".join(value.strip().split()).casefold()


def normalize_for_storage(points: list[Any]) -> list[Any]:
    """规范化标准字段并保留扩展字段；非对象留给校验器定位。"""

    normalized: list[Any] = []
    for item in points:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        ordered: dict[str, Any] = {}
        for key in STANDARD_FIELDS:
            value = item.get(key, "")
            ordered[key] = value.strip() if isinstance(value, str) else value
        for key, value in item.items():
            if key not in ordered:
                ordered[key] = value
        normalized.append(ordered)
    return normalized


def canonical_review_bytes(points: list[Any]) -> bytes:
    """返回用于大小、幂等与 SHA 的稳定 UTF-8 JSON。"""

    return json.dumps(normalize_for_storage(points), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def review_content_sha256(points: list[Any]) -> str:
    """计算规范化测试点列表 SHA-256。"""

    return hashlib.sha256(canonical_review_bytes(points)).hexdigest()


def diff_points(original: list[Any], current: list[Any]) -> dict[str, int]:
    """以 ID 作为稳定主键计算 O(n) 修改摘要。"""

    old = {item.get("id"): item for item in normalize_for_storage(original) if isinstance(item, dict) and item.get("id")}
    new = {item.get("id"): item for item in normalize_for_storage(current) if isinstance(item, dict) and item.get("id")}
    added, deleted = len(new.keys() - old.keys()), len(old.keys() - new.keys())
    modified = unchanged = risk_changed = 0
    for point_id in old.keys() & new.keys():
        if canonical_review_bytes([old[point_id]]) == canonical_review_bytes([new[point_id]]):
            unchanged += 1
        else:
            modified += 1
        if old[point_id].get("risk_level") != new[point_id].get("risk_level"):
            risk_changed += 1
    return {"added": added, "modified": modified, "deleted": deleted, "unchanged": unchanged, "risk_changed": risk_changed}


def validate_points(points: list[Any], *, original: list[Any] | None = None, max_bytes: int = 5 * 1024 * 1024, max_characters: int = 500_000) -> ReviewValidation:
    """执行完整确定性校验，业务错误允许保存但阻止继续。"""

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    if not points:
        errors.append(ValidationIssue(level="error", code="POINTS_EMPTY", message="至少保留一个测试点"))
    if len(points) > MAX_POINTS:
        errors.append(ValidationIssue(level="error", code="POINTS_LIMIT_EXCEEDED", message="测试点数量超过 5000 条"))
    try:
        content = canonical_review_bytes(points)
        if len(content) > max_bytes or len(content.decode("utf-8")) > max_characters:
            errors.append(ValidationIssue(level="error", code="REVIEW_SIZE_EXCEEDED", message="Review 内容超过大小限制"))
    except (TypeError, UnicodeError):
        errors.append(ValidationIssue(level="error", code="FIELD_TYPE_INVALID", message="Review 包含无法序列化的字段"))

    ids: defaultdict[str, list[int]] = defaultdict(list)
    exact: defaultdict[tuple[str, ...], list[int]] = defaultdict(list)
    texts: defaultdict[str, list[int]] = defaultdict(list)
    normalized = normalize_for_storage(points)
    for index, item in enumerate(normalized):
        if not isinstance(item, dict):
            errors.append(ValidationIssue(level="error", code="POINT_NOT_OBJECT", message="测试点必须是对象", row_index=index))
            continue
        point_id = item.get("id") if isinstance(item.get("id"), str) else None
        if any(str(key).startswith("_") for key in item):
            errors.append(ValidationIssue(level="error", code="CLIENT_PRIVATE_FIELD", message="测试点包含客户端内部字段", row_index=index))
        for field in STANDARD_FIELDS:
            value = item.get(field, "")
            if not isinstance(value, str):
                errors.append(ValidationIssue(level="error", code="FIELD_TYPE_INVALID", message=f"{field} 必须是字符串", row_index=index, point_id=point_id, field=field))
                continue
            if "\x00" in value:
                errors.append(ValidationIssue(level="error", code="TEXT_CONTAINS_NUL", message=f"{field} 不能包含 NUL", row_index=index, point_id=point_id, field=field))
            if not value:
                errors.append(ValidationIssue(level="error", code="FIELD_REQUIRED", message=f"{field} 不能为空", row_index=index, point_id=point_id, field=field))
            if FIELD_LIMITS.get(field) and len(value) > FIELD_LIMITS[field]:
                errors.append(ValidationIssue(level="error", code="FIELD_TOO_LONG", message=f"{field} 超过长度限制", row_index=index, point_id=point_id, field=field))
        risk = item.get("risk_level")
        if isinstance(risk, str) and risk and risk not in RISK_LEVELS:
            errors.append(ValidationIssue(level="error", code="RISK_LEVEL_INVALID", message="风险等级必须是 P0/P1/P2/P3", row_index=index, point_id=point_id, field="risk_level"))
        if isinstance(point_id, str) and point_id:
            ids[point_id].append(index)
            if not re.fullmatch(r"TP\d{3,}", point_id):
                warnings.append(ValidationIssue(level="warning", code="POINT_ID_NON_STANDARD", message="ID 不符合推荐格式", row_index=index, point_id=point_id, field="id"))
        values = [item.get(field) for field in ("module", "feature", "scenario", "test_point")]
        if all(isinstance(value, str) and value for value in values):
            exact[tuple(normalize_compare_text(value) for value in values)].append(index)
        text = item.get("test_point")
        if isinstance(text, str) and text:
            texts[normalize_compare_text(text)].append(index)
            if len(text) < 2:
                warnings.append(ValidationIssue(level="warning", code="POINT_TEXT_TOO_SHORT", message="测试点文本过短", row_index=index, point_id=point_id, field="test_point"))

    for code, groups, message in (("POINT_ID_DUPLICATE", ids, "测试点 ID 重复"), ("POINT_EXACT_DUPLICATE", exact, "测试点内容完全重复")):
        for indexes in groups.values():
            if len(indexes) > 1:
                errors.extend(ValidationIssue(level="error", code=code, message=message, row_index=index, related_rows=indexes) for index in indexes)
    for indexes in texts.values():
        contexts = {tuple(normalize_compare_text(str(normalized[i].get(field, ""))) for field in ("module", "feature", "scenario")) for i in indexes if isinstance(normalized[i], dict)}
        if len(indexes) > 1 and len(contexts) > 1:
            warnings.extend(ValidationIssue(level="warning", code="POINT_TEXT_REUSED", message="相同测试点文本用于不同上下文", row_index=index, related_rows=indexes) for index in indexes)

    diff = diff_points(original or [], normalized)
    original_by_id = {
        item.get("id"): item
        for item in normalize_for_storage(original or [])
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    }
    for index, item in enumerate(normalized):
        if not isinstance(item, dict) or item.get("id") not in original_by_id:
            continue
        if item.get("risk_level") != original_by_id[item["id"]].get("risk_level"):
            warnings.append(
                ValidationIssue(
                    level="warning",
                    code="RISK_LEVEL_CHANGED",
                    message="测试点风险等级已变更",
                    row_index=index,
                    point_id=item.get("id"),
                    field="risk_level",
                )
            )
    original_count = len(original or [])
    if original_count and diff["deleted"] / original_count > 0.3:
        warnings.append(ValidationIssue(level="warning", code="DELETE_RATIO_HIGH", message="删除数量超过原始测试点的 30%"))
    if original_count and diff["added"] / original_count > 0.5:
        warnings.append(ValidationIssue(level="warning", code="ADD_RATIO_HIGH", message="新增数量超过原始测试点的 50%"))
    return ReviewValidation(valid_for_resume=not errors, errors=errors, warnings=warnings)


class ReviewService:
    """在 TaskStore 锁内管理草稿、原稿和不可变确认版本。"""

    def __init__(self, store: TaskStore):
        self.store = store
        self.files = VersionedReviewStore(store, TEST_POINT_SPEC)

    def _draft_path(self, task_id: str) -> Path:
        return self.files.draft_path(task_id)

    @staticmethod
    def _read_json(path: Path) -> Any:
        return VersionedReviewStore.read_json(path)

    def original_points(self, task_id: str) -> tuple[list[Any], dict[str, Any]]:
        """从 artifact 白名单读取模型原稿，禁止目录扫描。"""

        payload, item = self.files.load_original(task_id)
        points = parse_points(payload)
        return normalize_for_storage(points), item

    def load(self, task_id: str) -> dict[str, Any]:
        """返回当前原稿、草稿、校验和 diff；草稿缺失时使用 revision 0。"""

        original, artifact = self.original_points(task_id)
        path = self._draft_path(task_id)
        if path.exists():
            envelope = self._read_json(path)
            points = parse_points(envelope.get("test_points", []))
            revision = int(envelope.get("revision", 0))
            actual_digest = review_content_sha256(points)
            digest = str(envelope.get("content_sha256") or actual_digest)
            if digest != actual_digest:
                raise ServiceError(500, "STORAGE_WRITE_FAILED", "Review 草稿完整性校验失败")
            saved_at, saved_by = envelope.get("saved_at"), envelope.get("saved_by_username")
        else:
            points, revision, saved_at, saved_by = original, 0, None, None
            digest = review_content_sha256(points)
        validation = validate_points(points, original=original)
        return {"points": points, "original_points": original, "revision": revision, "sha256": digest, "source_artifact_id": artifact["id"], "saved_at": saved_at, "saved_by_username": saved_by, "validation": validation.model_dump(), "diff_summary": diff_points(original, points)}

    def load_version(self, task_id: str, *, kind: str, version: int | None = None) -> dict[str, Any]:
        """读取原稿、当前草稿或指定确认版本，并返回统一只读元数据。"""

        current = self.load(task_id)
        if kind == "draft":
            return {**current, "kind": "draft", "versions": self.files.confirmed_versions(task_id)}
        if kind == "generated":
            points = current["original_points"]
            return {
                **current, "points": points, "revision": 0, "sha256": review_content_sha256(points),
                "validation": validate_points(points, original=points).model_dump(),
                "diff_summary": diff_points(points, points), "kind": "generated",
                "versions": self.files.confirmed_versions(task_id),
            }
        if kind == "confirmed" and version is not None:
            points = normalize_for_storage(parse_points(self.files.read_confirmed_version(task_id, version)))
            return {
                **current, "points": points, "revision": 0, "sha256": review_content_sha256(points),
                "validation": validate_points(points, original=current["original_points"]).model_dump(),
                "diff_summary": diff_points(current["original_points"], points), "kind": "confirmed",
                "version": version, "versions": self.files.confirmed_versions(task_id),
            }
        raise ServiceError(422, "INVALID_INPUT", "Review 版本类型不受支持")

    def save_draft(self, task_id: str, points: list[Any], *, revision: int, sha256: str, user_id: str, username: str, max_bytes: int, max_characters: int) -> dict[str, Any]:
        """使用 revision/SHA 乐观锁原子保存草稿；冲突时绝不覆盖。"""

        with self.store.locked():
            current = self.load(task_id)
            if revision != current["revision"] or sha256 != current["sha256"]:
                raise ServiceError(409, "REVIEW_REVISION_CONFLICT", "草稿已被其他页面更新", {"current_revision": current["revision"], "current_sha256": current["sha256"], "saved_at": current.get("saved_at"), "saved_by": current.get("saved_by_username")})
            normalized = normalize_for_storage(points)
            validation = validate_points(normalized, original=current["original_points"], max_bytes=max_bytes, max_characters=max_characters)
            digest = review_content_sha256(normalized)
            if digest == current["sha256"] and current["revision"] > 0:
                return current
            envelope = {"schema_version": 1, "revision": revision + 1, "content_sha256": digest, "base_generated_sha256": review_content_sha256(current["original_points"]), "saved_by_user_id": user_id, "saved_by_username": username, "saved_at": utc_now(), "test_points": normalized}
            TaskStore.atomic_write_json(self._draft_path(task_id), envelope)
            record = self.store.load(task_id) or {}
            record["review_draft"] = {key: envelope[key] for key in ("revision", "content_sha256", "saved_by_user_id", "saved_by_username", "saved_at")}
            self.store.save(record)
            return {"points": normalized, "original_points": current["original_points"], "revision": revision + 1, "sha256": digest, "saved_at": envelope["saved_at"], "saved_by_username": username, "validation": validation.model_dump(), "diff_summary": diff_points(current["original_points"], normalized), "source_artifact_id": current["source_artifact_id"]}

    def confirm(self, task_id: str, *, revision: int, sha256: str, accept_warnings: bool) -> dict[str, Any]:
        """校验草稿并创建或复用不可变确认 JSON。"""

        with self.store.locked():
            current = self.load(task_id)
            if current["revision"] == 0:
                raise ServiceError(422, "REVIEW_DRAFT_REQUIRED", "请先保存 Review 草稿")
            if revision != current["revision"] or sha256 != current["sha256"]:
                raise ServiceError(409, "REVIEW_REVISION_CONFLICT", "草稿已被其他页面更新", {"current_revision": current["revision"], "current_sha256": current["sha256"]})
            validation = ReviewValidation.model_validate(current["validation"])
            if validation.errors:
                raise ServiceError(422, "REVIEW_VALIDATION_FAILED", "草稿仍有阻塞错误", {"validation": validation.model_dump()})
            if validation.warnings and not accept_warnings:
                raise ServiceError(409, "REVIEW_WARNING_CONFIRMATION_REQUIRED", "草稿包含警告，请确认后继续", {"validation": validation.model_dump()})
            task_dir = self.store.task_dir(task_id)
            record = self.store.load(task_id) or {}
            existing = record.get("review", {})
            if existing.get("sha256") == sha256 and existing.get("relative_path"):
                return existing
            versioned_paths = self.files.confirmed_files(task_id)
            # 文件发布成功但 task.json 索引更新失败时，从不可变文件恢复同一确认版本。
            for version, confirmed_path in sorted(versioned_paths):
                try:
                    confirmed_points = parse_points(self._read_json(confirmed_path))
                except ServiceError:
                    continue
                if review_content_sha256(confirmed_points) == sha256:
                    return {
                        "version": version,
                        "relative_path": confirmed_path.relative_to(task_dir).as_posix(),
                        "sha256": sha256,
                        "confirmed_at": utc_now(),
                        "test_point_count": len(confirmed_points),
                    }
            versions = [version for version, _path in versioned_paths]
            version = max(versions, default=0) + 1
            path = self.files.create_confirmed(task_id, version, current["points"])
            return {"version": version, "relative_path": path.relative_to(task_dir).as_posix(), "sha256": sha256, "confirmed_at": utc_now(), "test_point_count": len(current["points"])}

    @staticmethod
    def _atomic_create(path: Path, payload: bytes) -> None:
        """仅在目标不存在时原子发布不可变文件。"""
        VersionedReviewStore.atomic_create(path, payload)
