"""API 测试智能体 V2 的阶段式任务调度扩展。"""

from __future__ import annotations

import os
import secrets
from typing import Any

from services.api_agent.v2_store import ApiV2Store
from services.api_agent.document_service import DocumentRevisionService
from services.api_agent.models import StageEvent
from services.api_agent.stage_events import StageEventStore
from services.common.errors import ServiceError
from services.common.task_manager import TaskManager
from services.common.task_models import utc_now


class ApiTaskManager(TaskManager):
    """复用单槽 FIFO，并为新 API 任务增加版本和 Attempt 语义。"""

    def _append_event_safely(self, event: StageEvent) -> None:
        """阶段记录是可观察性产物，写入失败不得改变任务状态。"""

        try:
            StageEventStore(self.store).append(event)
        except (OSError, TypeError, ValueError):
            return

    def submit(self, record: dict[str, Any], request_payload: dict[str, Any], *, max_waiting: int | None = None) -> dict[str, Any]:
        """把新 API 任务标记为 Schema V2 并初始化阶段目录。"""

        record.update({
            "schema_version": 2,
            "current_versions": {},
            "completed_stages": [],
            "stage": "document_preflight_queued",
        })
        versions = ApiV2Store(self.store)
        versions.initialize(record["id"])
        # 文档初始版本需要读取创建请求中的受控相对路径；父类随后会写入完整请求。
        self.store.atomic_write_json(self.store.task_dir(record["id"]) / "request.json", request_payload)
        document, scope = DocumentRevisionService(self.store).ensure_initial_versions(
            record["id"], created_by={
                "user_id": str(record.get("created_by_user_id", "system")),
                "username": str(record.get("created_by_username", "system")),
            },
            register=True,
            task_record=record,
        )
        record["current_versions"].update({
            "documents": {"version": document["version"], "sha256": document["sha256"]},
            "analysis-scopes": {"version": scope["version"], "sha256": scope["sha256"]},
        })
        generation_kernel = self._generation_kernel()
        record["generation_kernel"] = generation_kernel
        attempt = versions.create_attempt(
            record["id"], stage="document_preflight",
            metadata={"generation_kernel": generation_kernel},
        )
        record["current_attempt_id"] = attempt["id"]
        request_payload = {
            **request_payload,
            "schema_version": 2,
            "from_stage": "document_preflight",
            "attempt_id": attempt["id"],
            "generation_kernel": generation_kernel,
            "document_version": document["version"],
            "scope_version": scope["version"],
            "source_versions": {
                "documents": document["version"],
                "analysis-scopes": scope["version"],
            },
        }
        submitted = super().submit(record, request_payload, max_waiting=max_waiting)
        self._append_event_safely(StageEvent(
            event_id=f"event_{secrets.token_hex(10)}", task_id=record["id"],
            attempt_id=attempt["id"], stage="document_preflight", node="task_manager",
            event_type="started", status="pending", message="任务已创建并进入分析队列",
        ))
        return submitted

    def enqueue_stage(
        self,
        task_id: str,
        *,
        from_stage: str,
        expected_status: str | set[str] | frozenset[str],
        source_versions: dict[str, Any],
        max_waiting: int | None = None,
        request_updates: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """从 Review 或失败阶段创建新 Attempt，复用显式上游版本。"""

        allowed = {"base_case_generation", "executable_generation", "document_preflight"}
        if from_stage not in allowed:
            raise ServiceError(422, "RETRY_STAGE_UNSUPPORTED", "重试阶段不受支持")
        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("schema_version") != 2:
                raise ServiceError(404, "TASK_NOT_FOUND", "V2 任务不存在")
            idempotency_slot = f"{from_stage}:{idempotency_key}" if idempotency_key else ""
            if idempotency_slot and idempotency_slot in record.get("stage_idempotency_keys", {}):
                # 组合确认可能因浏览器重试重复到达。返回原任务快照，避免产生第二个
                # Attempt；重新分析保留既有的显式冲突语义，提示用户刷新影响预览。
                if from_stage == "document_preflight":
                    raise ServiceError(409, "REANALYZE_ALREADY_RUNNING", "相同的重新分析请求已创建")
                return record
            allowed_statuses = {expected_status} if isinstance(expected_status, str) else set(expected_status)
            if record.get("status") not in allowed_statuses:
                raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许进入该阶段")
            if idempotency_key and record.get("last_reanalyze_idempotency_key") == idempotency_key:
                raise ServiceError(409, "REANALYZE_ALREADY_RUNNING", "相同的重新分析请求已创建")
            self.assert_capacity(max_waiting)
            request_path = self.store.task_dir(task_id) / "request.json"
            import json

            payload = json.loads(request_path.read_text(encoding="utf-8"))
            generation_kernel = self._generation_kernel()
            attempt = ApiV2Store(self.store).create_attempt(
                task_id, stage=from_stage, source_versions=source_versions,
                metadata={
                    **({"idempotency_key": idempotency_key} if idempotency_key else {}),
                    "generation_kernel": generation_kernel,
                },
            )
            payload.update({
                "from_stage": from_stage, "attempt_id": attempt["id"],
                "source_versions": source_versions, "generation_kernel": generation_kernel,
            })
            payload.update(request_updates or {})
            self.store.atomic_write_json(request_path, payload)
            queued_at = utc_now()
            record.update({
                "status": "pending", "stage": f"{from_stage}_queued", "queued_at": queued_at,
                "current_attempt_id": attempt["id"], "error_code": None, "error_message": None,
                "generation_kernel": generation_kernel,
            })
            if idempotency_key:
                record["last_reanalyze_idempotency_key"] = idempotency_key
                record.setdefault("stage_idempotency_keys", {})[idempotency_slot] = attempt["id"]
            self._write_execution(record, kind=from_stage, queued_at=queued_at)
            self.store.save(record)
            self._append_event_safely(StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
                attempt_id=attempt["id"], stage=from_stage, node="task_manager",
                event_type="started", status="pending", message=f"阶段已进入队列：{from_stage}",
                input_versions={key: int(value) for key, value in source_versions.items() if isinstance(value, int)},
            ))
            self._condition.notify_all()
            return record

    def cancel(self, task_id: str) -> dict[str, Any]:
        """取消任务并尽力记录产品级事件。"""

        record = super().cancel(task_id)
        attempt_id = str(record.get("current_attempt_id") or "")
        if attempt_id:
            self._append_event_safely(StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=task_id,
                attempt_id=attempt_id, stage=str(record.get("stage") or "task"),
                node="task_manager", event_type="failed", status="cancelled",
                level="warning", message="任务已取消",
            ))
        return record

    @staticmethod
    def _generation_kernel() -> str:
        """在 Attempt 创建时固化内核；生产未配置时保持旧内核。"""

        configured = os.getenv("API_GENERATION_KERNEL", "").strip()
        if not configured:
            environment = os.getenv("PLATFORM_RUNTIME_ENV", "dev").strip().lower()
            configured = "v2_minimal" if environment in {"prod", "production"} else "v2_core_workflow"
        if configured not in {"v2_minimal", "v2_fused", "v2_core_workflow"}:
            raise ServiceError(422, "GENERATION_KERNEL_UNSUPPORTED", "API 生成内核配置不受支持")
        return configured
