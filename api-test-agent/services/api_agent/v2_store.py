"""API 测试智能体 V2 的版本化阶段存储。"""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from services.common.artifacts import merge_registry, publish_artifact
from services.common.task_models import utc_now
from services.common.task_store import TaskStore


VERSION_KINDS = frozenset({"contracts", "base-cases", "coverage", "executable-cases", "defect-drafts"})


def canonical_sha256(payload: Any) -> str:
    """对结构化数据进行稳定序列化并返回内容 SHA。"""

    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class ApiV2Store:
    """在既有 TaskStore 目录内管理 API 专属版本、Attempt 和 Run。

    该类不修改旧任务；调用方必须仅对 ``schema_version=2`` 的任务使用。
    """

    def __init__(self, store: TaskStore):
        self.store = store

    def initialize(self, task_id: str) -> None:
        """创建 V2 固定阶段目录；重复调用不会清理或覆盖已有文件。"""

        task_dir = self.store.task_dir(task_id)
        for relative in (
            "versions/contracts", "versions/base-cases", "versions/coverage",
            "versions/executable-cases", "versions/defect-drafts", "attempts", "runs",
        ):
            (task_dir / relative).mkdir(parents=True, exist_ok=True, mode=0o700)

    def create_attempt(self, task_id: str, *, stage: str, source_versions: dict[str, Any] | None = None) -> dict[str, Any]:
        """创建不可变 GenerationAttempt 元数据并返回引用。"""

        self.initialize(task_id)
        attempt_id = f"attempt_{secrets.token_hex(10)}"
        payload = {
            "schema_version": 2,
            "id": attempt_id,
            "task_id": task_id,
            "stage": stage,
            "status": "created",
            "source_versions": source_versions or {},
            "created_at": utc_now(),
        }
        TaskStore.atomic_write_json(self.store.task_dir(task_id) / "attempts" / attempt_id / "attempt.json", payload)
        return payload

    def save_version(
        self,
        task_id: str,
        *,
        kind: str,
        items: Any,
        source_versions: dict[str, Any] | None = None,
        created_by: str = "system",
    ) -> dict[str, Any]:
        """追加保存一个版本，并将其立即登记为可下载阶段产物。

        异常说明:
            kind 不在固定白名单时抛出 ValueError，防止浏览器控制磁盘路径。
        """

        if kind not in VERSION_KINDS:
            raise ValueError("版本类型不受支持")
        self.initialize(task_id)
        with self.store.locked():
            directory = self.store.task_dir(task_id) / "versions" / kind
            existing = sorted(directory.glob("v*.json"))
            version = max((int(path.stem[1:]) for path in existing if path.stem[1:].isdigit()), default=0) + 1
            content_sha = canonical_sha256(items)
            envelope = {
                "schema_version": 2,
                "kind": kind,
                "version": version,
                "sha256": content_sha,
                "source_versions": source_versions or {},
                "created_by": created_by,
                "created_at": utc_now(),
                "items": items,
            }
            path = directory / f"v{version}.json"
            TaskStore.atomic_write_json(path, envelope)
            artifact = publish_artifact(
                self.store,
                task_id,
                path,
                artifact_type=f"api_v2_{kind}",
                stage=kind,
                destination_group=f"versions/{kind}",
                review_input=kind in {"contracts", "base-cases"},
            )
            merge_registry(self.store, task_id, [artifact])
            record = self.store.load(task_id)
            if record:
                record.setdefault("current_versions", {})[kind] = {"version": version, "sha256": content_sha}
                completed = record.setdefault("completed_stages", [])
                if kind not in completed:
                    completed.append(kind)
                self.store.save(record)
            return envelope

    def load_version(self, task_id: str, kind: str, version: int | None = None) -> dict[str, Any]:
        """读取指定或当前版本，并验证任务记录中声明的内容 SHA。"""

        if kind not in VERSION_KINDS:
            raise ValueError("版本类型不受支持")
        if version is None:
            record = self.store.load(task_id) or {}
            version = int(record.get("current_versions", {}).get(kind, {}).get("version", 0))
        path = self.store.task_dir(task_id) / "versions" / kind / f"v{version}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FileNotFoundError("版本不存在或已损坏") from exc
        if payload.get("sha256") != canonical_sha256(payload.get("items")):
            raise ValueError("版本内容校验失败")
        return payload

    def save_run_document(self, task_id: str, run_id: str, name: str, payload: Any) -> Path:
        """在单 Run 独占目录内保存输入或输出，不接受包含路径分隔符的名称。"""

        if not run_id.startswith("run_") or Path(name).name != name:
            raise ValueError("Run 文件标识不合法")
        path = self.store.task_dir(task_id) / "runs" / run_id / name
        TaskStore.atomic_write_json(path, payload)
        return path
