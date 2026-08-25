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


VERSION_KINDS = frozenset({
    "documents", "analysis-scopes", "contracts", "base-cases", "coverage",
    "executable-cases", "execution-plans", "defect-drafts",
})


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
            "versions/documents", "versions/analysis-scopes", "versions/contracts", "versions/base-cases", "versions/coverage",
            "versions/executable-cases", "versions/execution-plans", "versions/defect-drafts",
            "attempts", "runs",
        ):
            (task_dir / relative).mkdir(parents=True, exist_ok=True, mode=0o700)

    def create_attempt(
        self, task_id: str, *, stage: str, source_versions: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            "metadata": metadata or {},
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
        artifact_schema_version: int | None = None,
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
                "artifact_schema_version": artifact_schema_version,
                "kind": kind,
                "version": version,
                "sha256": content_sha,
                "source_versions": source_versions or {},
                "created_by": created_by,
                "created_at": utc_now(),
                "lifecycle_status": "current",
                "stale_reason": "",
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
                review_input=kind in {"contracts", "base-cases", "executable-cases", "execution-plans"},
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

    def list_versions(self, task_id: str, kind: str) -> list[dict[str, Any]]:
        """按版本倒序返回已校验信封，损坏文件不会影响其他历史版本。"""

        if kind not in VERSION_KINDS:
            raise ValueError("版本类型不受支持")
        directory = self.store.task_dir(task_id) / "versions" / kind
        result = []
        for path in sorted(directory.glob("v*.json"), reverse=True) if directory.is_dir() else []:
            if not path.stem[1:].isdigit():
                continue
            try:
                result.append(self.load_version(task_id, kind, int(path.stem[1:])))
            except (FileNotFoundError, ValueError):
                continue
        return sorted(result, key=lambda item: int(item["version"]), reverse=True)

    def lifecycle_status(self, task_id: str, envelope: dict[str, Any]) -> str:
        """根据当前版本指针推导版本是否仍可用于派生。"""

        record = self.store.load(task_id) or {}
        current = record.get("current_versions", {}).get(envelope.get("kind", ""), {})
        if int(current.get("version", 0)) == int(envelope.get("version", -1)):
            return "current"
        if envelope.get("kind") in {"documents", "analysis-scopes"}:
            return "superseded"
        return "stale"

    def mark_downstream_stale(self, task_id: str, *, contract_version: int, reason: str) -> None:
        """登记旧契约派生产物失效；正文和历史版本保持不可变。"""

        with self.store.locked():
            record = self.store.load(task_id) or {}
            stale = record.setdefault("stale_versions", [])
            for kind in ("coverage", "base-cases", "executable-cases", "execution-plans"):
                pointer = record.get("current_versions", {}).get(kind)
                if not pointer:
                    continue
                try:
                    envelope = self.load_version(task_id, kind, int(pointer["version"]))
                except (FileNotFoundError, ValueError, TypeError):
                    continue
                source_contract = int(envelope.get("source_versions", {}).get("contracts", 0) or 0)
                if source_contract and source_contract != contract_version:
                    entry = {"kind": kind, "version": envelope["version"], "sha256": envelope["sha256"], "reason": reason}
                    if entry not in stale:
                        stale.append(entry)
            record.pop("execution_confirmation_sha256", None)
            self.store.save(record)

    def mark_execution_plans_stale(
        self, task_id: str, *, executable_version: int, reason: str,
    ) -> None:
        """执行定义变化后失效当前计划和确认摘要，但不改写历史计划正文。"""

        with self.store.locked():
            record = self.store.load(task_id) or {}
            pointer = record.get("current_versions", {}).get("execution-plans")
            if pointer:
                try:
                    envelope = self.load_version(task_id, "execution-plans", int(pointer["version"]))
                except (FileNotFoundError, ValueError, TypeError):
                    envelope = None
                source_executable = int(
                    (envelope or {}).get("source_versions", {}).get("executable-cases", 0) or 0
                )
                if envelope and source_executable and source_executable != executable_version:
                    entry = {
                        "kind": "execution-plans", "version": envelope["version"],
                        "sha256": envelope["sha256"], "reason": reason,
                    }
                    stale = record.setdefault("stale_versions", [])
                    if entry not in stale:
                        stale.append(entry)
            record.pop("execution_confirmation_sha256", None)
            self.store.save(record)

    def mark_base_case_downstream_stale_locked(self, task_id: str, *, reason: str) -> None:
        """基础用例变更时登记当前执行定义与计划为 stale。

        调用约束：调用方必须已持有 ``TaskStore.locked()``。该专用方法不再次加锁，
        避免 Review 的版本保存与失效登记之间出现可见竞态。
        """

        record = self.store.load(task_id) or {}
        stale = record.setdefault("stale_versions", [])
        for kind in ("executable-cases", "execution-plans"):
            pointer = record.get("current_versions", {}).get(kind)
            if not pointer:
                continue
            try:
                envelope = self.load_version(task_id, kind, int(pointer["version"]))
            except (FileNotFoundError, ValueError, TypeError):
                continue
            entry = {
                "kind": kind, "version": envelope["version"],
                "sha256": envelope["sha256"], "reason": reason,
            }
            if entry not in stale:
                stale.append(entry)
        record.pop("execution_confirmation_sha256", None)
        self.store.save(record)

    def save_run_document(self, task_id: str, run_id: str, name: str, payload: Any) -> Path:
        """在单 Run 独占目录内保存输入或输出，不接受包含路径分隔符的名称。"""

        if not run_id.startswith("run_") or Path(name).name != name:
            raise ValueError("Run 文件标识不合法")
        path = self.store.task_dir(task_id) / "runs" / run_id / name
        TaskStore.atomic_write_json(path, payload)
        return path
