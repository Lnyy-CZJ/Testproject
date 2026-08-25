"""API V2.2 阶段事件、模型用量和生成来源的文件化存储。"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.api_agent.models import GenerationProvenance, ModelUsageRecord, StageEvent
from services.common.redaction import redact_structure
from services.common.errors import structured_log
from services.common.task_store import TaskStore


_ID = re.compile(r"^(attempt|run)_[A-Za-z0-9_-]{1,96}$")


class StageEventStore:
    """在任务目录内追加脱敏事件，并原子保存模型用量和来源。"""

    def __init__(self, store: TaskStore):
        self.store = store

    def _attempt_dir(self, task_id: str, attempt_id: str, *, create: bool = False) -> Path:
        """解析受控 Attempt 目录，拒绝路径注入。"""

        if not _ID.fullmatch(attempt_id) or not attempt_id.startswith("attempt_"):
            raise ValueError("Attempt ID 不合法")
        path = self.store.task_dir(task_id) / "attempts" / attempt_id
        if create:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            raise ValueError("Attempt 不存在")
        return path

    def append(self, event: StageEvent) -> dict[str, Any]:
        """校验、脱敏并持久化单条产品级阶段事件。"""

        if not event.attempt_id:
            raise ValueError("阶段事件必须绑定 Attempt")
        payload = redact_structure(event.model_dump(mode="json"))
        payload["message"] = str(payload.get("message", ""))[:2000]
        path = self._attempt_dir(event.task_id, event.attempt_id, create=True) / "events.jsonl"
        with self.store.locked():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return payload

    def list_events(
        self,
        task_id: str,
        *,
        attempt_id: str,
        run_id: str = "",
        stage: str = "",
        level: str = "",
        cursor: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """按游标返回白名单事件；损坏行被跳过。"""

        if run_id and (not _ID.fullmatch(run_id) or not run_id.startswith("run_")):
            raise ValueError("Run ID 不合法")
        if level and level not in {"debug", "info", "warning", "error"}:
            raise ValueError("阶段记录级别不合法")
        cursor = max(0, int(cursor))
        limit = min(500, max(1, int(limit)))
        path = self._attempt_dir(task_id, attempt_id) / "events.jsonl"
        items: list[dict[str, Any]] = []
        damaged = 0
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    item = StageEvent.model_validate(json.loads(line)).model_dump(mode="json")
                except (ValueError, TypeError, json.JSONDecodeError):
                    damaged += 1
                    continue
                if run_id and item.get("run_id") != run_id:
                    continue
                if stage and item.get("stage") != stage:
                    continue
                if level and item.get("level") != level:
                    continue
                items.append(redact_structure(item))
        page = items[cursor:cursor + limit]
        if damaged:
            structured_log(
                logging.getLogger("api_test_agent.stage_events"), "warning",
                task_id=task_id, attempt_id=attempt_id, stage=stage or None,
                node="event_reader", event="damaged_event_skipped", status="warning",
                damaged_count=damaged,
            )
        next_cursor = cursor + len(page) if cursor + len(page) < len(items) else None
        return {"items": page, "cursor": cursor, "next_cursor": next_cursor, "total": len(items)}

    def save_usage(self, task_id: str, record: ModelUsageRecord) -> None:
        """追加模型调用记录；供应商未报告时保留 reported=false。"""

        path = self._attempt_dir(task_id, record.attempt_id, create=True) / "model-usage.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"schema_version": 2, "items": []}
        items = [item for item in payload.get("items", []) if item.get("call_id") != record.call_id]
        items.append(redact_structure(record.model_dump(mode="json")))
        TaskStore.atomic_write_json(path, {"schema_version": 2, "items": items})

    def list_usage(self, task_id: str, *, attempt_id: str) -> dict[str, Any]:
        """返回当前 Attempt 用量和可靠汇总，不估算未报告 Token。"""

        path = self._attempt_dir(task_id, attempt_id) / "model-usage.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {"items": []}
        items = []
        for value in raw.get("items", []):
            try:
                items.append(ModelUsageRecord.model_validate(value).model_dump(mode="json"))
            except (ValueError, TypeError):
                continue
        reported = [item for item in items if item["reported"]]
        return {
            "items": redact_structure(items),
            "summary": {
                "call_count": len(items),
                "reported_calls": len(reported),
                "input_tokens": sum(item["input_tokens"] for item in reported),
                "output_tokens": sum(item["output_tokens"] for item in reported),
                "total_tokens": sum(item["total_tokens"] for item in reported),
            },
        }

    def summarize_usage(
        self, records: list[dict[str, Any]], *, group_by: str = "attempt",
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """直接聚合可见任务的 Attempt 文件，不创建第二份统计数据。"""

        dimensions = {
            "attempt": "attempt_id", "stage": "stage", "node": "node",
            "model": "model_name", "prompt": "prompt_id", "kernel": "generation_kernel",
            "project": "project_name", "module": "module_name",
        }
        if group_by not in dimensions:
            raise ValueError("用量分组维度不合法")
        filters = filters or {}
        rows: list[dict[str, Any]] = []
        attempts: list[dict[str, str]] = []
        rejection_count = grounding_rejections = schema_rejections = partial_attempts = 0
        contract_ids: set[str] = set()
        valid_case_count = 0
        for task in records:
            task_id = str(task.get("id", ""))
            if not task_id:
                continue
            attempts_dir = self.store.task_dir(task_id) / "attempts"
            for attempt_dir in attempts_dir.glob("attempt_*") if attempts_dir.is_dir() else []:
                attempt_id = attempt_dir.name
                try:
                    attempt = json.loads((attempt_dir / "attempt.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    attempt = {}
                try:
                    raw_usage = json.loads((attempt_dir / "model-usage.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raw_usage = {"items": []}
                try:
                    provenance = GenerationProvenance.model_validate_json(
                        (attempt_dir / "generation-provenance.json").read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    provenance = None
                kernel = str((provenance.generation_kernel if provenance else None) or attempt.get("metadata", {}).get("generation_kernel") or task.get("generation_kernel") or "v2_minimal")
                attempts.append({
                    "task_id": task_id, "attempt_id": attempt_id,
                    "stage": str(attempt.get("stage", "")),
                    "created_at": str(attempt.get("created_at", "")), "generation_kernel": kernel,
                })
                if provenance:
                    rejection_count += provenance.rejected_case_count
                    grounding_rejections += sum(item.error_code == "CASE_GROUNDING_FAILED" for item in provenance.rejections)
                    schema_rejections += sum(item.error_code in {"CASE_PROMPT_ITEM_INVALID", "LLM_RESPONSE_INVALID"} for item in provenance.rejections)
                    partial_attempts += provenance.ai_supplement_status == "partial"
                    contract_ids.update(provenance.contract_ids)
                    valid_case_count += provenance.deterministic_case_count + provenance.llm_case_count
                for value in raw_usage.get("items", []):
                    try:
                        usage = ModelUsageRecord.model_validate(value).model_dump(mode="json")
                    except (TypeError, ValueError):
                        continue
                    row = {
                        **usage, "task_id": task_id, "project_id": str(task.get("project_id", "")),
                        "project_name": str(task.get("project_name", "")),
                        "module_id": str(task.get("module_id", "")),
                        "module_name": str(task.get("module_name", "")),
                        "generation_kernel": kernel,
                    }
                    if self._usage_matches(row, filters):
                        rows.append(row)

        def metrics(values: list[dict[str, Any]]) -> dict[str, Any]:
            reported = [item for item in values if item["reported"]]
            durations = [item["duration_ms"] for item in values]
            calls = len(values)
            return {
                "call_count": calls, "reported_calls": len(reported),
                "unreported_calls": calls - len(reported),
                "input_tokens": sum(item["input_tokens"] for item in reported),
                "output_tokens": sum(item["output_tokens"] for item in reported),
                "total_tokens": sum(item["total_tokens"] for item in reported),
                "average_duration_ms": round(sum(durations) / calls, 2) if calls else 0,
                "max_duration_ms": max(durations, default=0),
                "retry_rate": round(sum(item["retry_number"] > 0 for item in values) / calls, 4) if calls else 0,
            }

        summary = metrics(rows)
        call_count = summary["call_count"]
        summary.update({
            "schema_failure_rate": round(schema_rejections / call_count, 4) if call_count else 0,
            "grounding_rejection_rate": round(grounding_rejections / call_count, 4) if call_count else 0,
            "partial_success_rate": round(partial_attempts / len(attempts), 4) if attempts else 0,
            "rejected_case_count": rejection_count,
            "tokens_per_valid_contract": round(summary["total_tokens"] / len(contract_ids), 2) if contract_ids else None,
            "tokens_per_valid_case": round(summary["total_tokens"] / valid_case_count, 2) if valid_case_count else None,
        })
        key_name = dimensions[group_by]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get(key_name) or "未记录"), []).append(row)
        return {
            "summary": summary,
            "groups": [{"key": key, **metrics(values)} for key, values in sorted(grouped.items())],
            "available_attempts": attempts, "group_by": group_by,
            "estimated_cost": None, "cost_status": "not_configured",
            "usage_reliable": summary["unreported_calls"] == 0,
        }

    @staticmethod
    def _usage_matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
        """执行白名单精确筛选；时间使用供应商调用记录时间。"""

        fields = {
            "project_id", "module_id", "attempt_id", "stage", "node",
            "model_name", "prompt_id", "generation_kernel", "status",
        }
        for key in fields:
            if filters.get(key) and str(row.get(key, "")) != filters[key]:
                return False
        started = str(row.get("started_at", ""))
        try:
            occurred = datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return not filters.get("from") and not filters.get("to")
        for key, lower in (("from", True), ("to", False)):
            if not filters.get(key):
                continue
            try:
                bound = datetime.fromisoformat(filters[key].replace("Z", "+00:00")).astimezone(UTC)
            except ValueError as exc:
                raise ValueError("用量时间筛选格式不合法") from exc
            if (lower and occurred < bound) or (not lower and occurred > bound):
                return False
        return True

    def save_provenance(self, task_id: str, provenance: GenerationProvenance) -> None:
        """原子保存当前 Attempt 的生成来源。"""

        if not provenance.attempt_id:
            raise ValueError("生成来源必须绑定 Attempt")
        path = self._attempt_dir(task_id, provenance.attempt_id, create=True) / "generation-provenance.json"
        TaskStore.atomic_write_json(path, redact_structure(provenance.model_dump(mode="json")))

    def load_provenance(self, task_id: str, *, attempt_id: str) -> dict[str, Any]:
        """读取并校验生成来源；不存在时返回空结构。"""

        path = self._attempt_dir(task_id, attempt_id) / "generation-provenance.json"
        try:
            return redact_structure(GenerationProvenance.model_validate_json(path.read_text(encoding="utf-8")).model_dump(mode="json"))
        except (OSError, ValueError):
            return {"attempt_id": attempt_id, "generation_kernel": "v2_minimal", "available": False}

    def invoke_model(
        self,
        task_id: str,
        *,
        attempt_id: str,
        stage: str,
        node: str,
        prompt_id: str,
        prompt: str,
        model: Any,
        retry_number: int = 0,
    ) -> Any:
        """调用 LangChain 模型并记录真实 Prompt 摘要、耗时和供应商 usage。"""

        import hashlib

        call_id = f"call_{secrets.token_hex(10)}"
        started = time.monotonic()
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            self.append(StageEvent(
                event_id=f"event_{secrets.token_hex(10)}", task_id=task_id, attempt_id=attempt_id,
                stage=stage, node=node, event_type="started", status="running",
                message=f"模型调用开始：{prompt_id}", model_call_id=call_id,
            ))
        except (OSError, TypeError, ValueError):
            pass
        response = None
        status = "failed"
        try:
            response = model.invoke(prompt)
            metadata = getattr(response, "response_metadata", None)
            if isinstance(metadata, dict):
                metadata["api_model_call_id"] = call_id
            status = "succeeded"
            return response
        except Exception as exc:
            setattr(exc, "model_call_id", call_id)
            raise
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            usage = getattr(response, "usage_metadata", None) if response is not None else None
            metadata = getattr(response, "response_metadata", {}) if response is not None else {}
            if not isinstance(usage, dict):
                usage = metadata.get("token_usage") if isinstance(metadata, dict) else None
            usage = usage if isinstance(usage, dict) else {}
            input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
            output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
            total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
            model_name = str(
                (metadata.get("model_name") if isinstance(metadata, dict) else "")
                or getattr(model, "model_name", "") or getattr(model, "model", "") or "unknown"
            )
            try:
                self.save_usage(task_id, ModelUsageRecord(
                    call_id=call_id, attempt_id=attempt_id, stage=stage, node=node,
                    prompt_id=prompt_id, prompt_sha256=prompt_sha, model_name=model_name,
                    input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens,
                    reported=bool(usage), retry_number=retry_number, duration_ms=duration_ms, status=status,
                ))
                self.append(StageEvent(
                    event_id=f"event_{secrets.token_hex(10)}", task_id=task_id, attempt_id=attempt_id,
                    stage=stage, node=node, event_type="completed" if status == "succeeded" else "failed",
                    status=status, level="info" if status == "succeeded" else "error",
                    message=f"模型调用{('完成' if status == 'succeeded' else '失败')}：{prompt_id}",
                    model_call_id=call_id, duration_ms=duration_ms,
                ))
            except (OSError, TypeError, ValueError):
                pass
