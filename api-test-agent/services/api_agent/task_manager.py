"""API 测试智能体 V2 的阶段式任务调度扩展。"""

from __future__ import annotations

from typing import Any

from services.api_agent.v2_store import ApiV2Store
from services.common.errors import ServiceError
from services.common.task_manager import TaskManager
from services.common.task_models import utc_now


class ApiTaskManager(TaskManager):
    """复用单槽 FIFO，并为新 API 任务增加版本和 Attempt 语义。"""

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
        attempt = versions.create_attempt(record["id"], stage="document_preflight")
        record["current_attempt_id"] = attempt["id"]
        request_payload = {**request_payload, "schema_version": 2, "from_stage": "document_preflight", "attempt_id": attempt["id"]}
        return super().submit(record, request_payload, max_waiting=max_waiting)

    def enqueue_stage(
        self,
        task_id: str,
        *,
        from_stage: str,
        expected_status: str,
        source_versions: dict[str, Any],
        max_waiting: int | None = None,
    ) -> dict[str, Any]:
        """从 Review 或失败阶段创建新 Attempt，复用显式上游版本。"""

        allowed = {"base_case_generation", "executable_generation", "document_preflight"}
        if from_stage not in allowed:
            raise ServiceError(422, "RETRY_STAGE_UNSUPPORTED", "重试阶段不受支持")
        with self._condition:
            record = self.store.load(task_id)
            if not record or record.get("schema_version") != 2:
                raise ServiceError(404, "TASK_NOT_FOUND", "V2 任务不存在")
            if record.get("status") != expected_status:
                raise ServiceError(409, "INVALID_TASK_STATE", "当前任务状态不允许进入该阶段")
            self.assert_capacity(max_waiting)
            request_path = self.store.task_dir(task_id) / "request.json"
            import json

            payload = json.loads(request_path.read_text(encoding="utf-8"))
            attempt = ApiV2Store(self.store).create_attempt(task_id, stage=from_stage, source_versions=source_versions)
            payload.update({"from_stage": from_stage, "attempt_id": attempt["id"], "source_versions": source_versions})
            self.store.atomic_write_json(request_path, payload)
            queued_at = utc_now()
            record.update({
                "status": "pending", "stage": f"{from_stage}_queued", "queued_at": queued_at,
                "current_attempt_id": attempt["id"], "error_code": None, "error_message": None,
            })
            self._write_execution(record, kind=from_stage, queued_at=queued_at)
            self.store.save(record)
            self._condition.notify_all()
            return record
