"""测试点与测试用例 Review 共用的版本化文件事务。"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.common.artifacts import load_registry, resolve_artifact
from services.common.errors import ServiceError
from services.common.task_store import TaskStore


@dataclass(frozen=True)
class ReviewResourceSpec:
    """描述一种 Review 资源的固定文件和产物协议。"""

    resource_type: str
    artifact_type: str
    envelope_key: str
    draft_filename: str
    confirmed_pattern: str


TEST_POINT_SPEC = ReviewResourceSpec(
    resource_type="test_points",
    artifact_type="test_points_json",
    envelope_key="test_points",
    draft_filename="review-draft.json",
    confirmed_pattern="review-test-points-v{version}.json",
)
TEST_CASE_SPEC = ReviewResourceSpec(
    resource_type="test_cases",
    artifact_type="test_cases_json",
    envelope_key="test_cases",
    draft_filename="case-review-draft.json",
    confirmed_pattern="review-test-cases-v{version}.json",
)


class VersionedReviewStore:
    """提供固定路径、原稿定位和不可变确认版本能力。

    业务层仍负责解析、规范化和校验；本类不理解测试点或测试用例字段，
    从而避免两类 Review 因共享业务规则而互相影响。
    """

    def __init__(self, store: TaskStore, spec: ReviewResourceSpec):
        self.store = store
        self.spec = spec

    def draft_path(self, task_id: str) -> Path:
        """返回由服务端配置生成的草稿路径，不接受客户端路径。"""

        return self.store.task_dir(task_id) / "input" / self.spec.draft_filename

    @staticmethod
    def read_json(path: Path) -> Any:
        """读取 JSON；损坏或 I/O 异常统一映射为稳定存储错误。"""

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ServiceError(500, "STORAGE_WRITE_FAILED", "Review 文件读取失败") from exc

    def load_original(self, task_id: str) -> tuple[Any, dict[str, Any]]:
        """只从 artifact registry 定位最新原稿，禁止扫描任意目录。"""

        candidates = [
            item for item in load_registry(self.store, task_id)
            if item.get("type") == self.spec.artifact_type and not item.get("expired")
        ]
        if not candidates:
            raise ServiceError(404, "REVIEW_DRAFT_REQUIRED", "Review 原始产物不存在")
        artifact = sorted(candidates, key=lambda item: item.get("created_at", ""))[-1]
        try:
            path, _metadata = resolve_artifact(self.store, task_id, artifact["id"])
        except (KeyError, ValueError, FileNotFoundError):
            raise ServiceError(404, "REVIEW_DRAFT_REQUIRED", "Review 原始产物不存在") from None
        return self.read_json(path), artifact

    def confirmed_files(self, task_id: str) -> list[tuple[int, Path]]:
        """扫描固定确认文件名，用于索引丢失后的安全恢复。"""

        escaped = re.escape(self.spec.confirmed_pattern).replace(re.escape("{version}"), r"(\d+)")
        matcher = re.compile(escaped)
        result: list[tuple[int, Path]] = []
        for path in (self.store.task_dir(task_id) / "input").iterdir():
            match = matcher.fullmatch(path.name)
            if match and path.is_file() and not path.is_symlink():
                result.append((int(match.group(1)), path))
        return sorted(result)

    def confirmed_versions(self, task_id: str) -> list[int]:
        """返回安全确认版本号列表，不向调用方暴露任务文件路径。"""

        return [version for version, _path in self.confirmed_files(task_id)]

    def read_confirmed_version(self, task_id: str, version: int) -> Any:
        """按服务端固定文件名读取确认版本，拒绝客户端路径。"""

        if version < 1:
            raise ServiceError(404, "REVIEW_VERSION_NOT_FOUND", "确认版本不存在")
        expected = self.store.task_dir(task_id) / "input" / self.spec.confirmed_pattern.format(version=version)
        if not expected.is_file() or expected.is_symlink():
            raise ServiceError(404, "REVIEW_VERSION_NOT_FOUND", "确认版本不存在")
        return self.read_json(expected)

    @staticmethod
    def atomic_create(path: Path, payload: bytes) -> None:
        """通过同目录临时文件和硬链接发布不可变文件，拒绝覆盖。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ServiceError(500, "STORAGE_WRITE_FAILED", "确认版本已存在且不可覆盖") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def create_confirmed(self, task_id: str, version: int, payload: Any) -> Path:
        """以稳定 JSON 格式创建指定版本的不可变确认文件。"""

        path = self.store.task_dir(task_id) / "input" / self.spec.confirmed_pattern.format(version=version)
        self.atomic_create(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        return path
