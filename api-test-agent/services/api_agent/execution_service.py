"""S1 Mock Run、不可变结果、失败分类和慢响应规则。"""

from __future__ import annotations

import json
import hashlib
import secrets
from pathlib import Path
from typing import Any, Callable

from services.api_agent.models import CaseResult, ExecutionRun, PerformanceEvaluation, utc_now
from services.api_agent.v2_store import ApiV2Store, canonical_sha256
from services.common.errors import ServiceError
from services.common.redaction import redact_structure
from services.common.task_store import TaskStore
from services.execution_controller.contracts import CreateRunRequest, RuntimeAdapter


ResultFactory = Callable[[ExecutionRun, list[dict[str, Any]]], list[dict[str, Any]]]


class MockExecutionService:
    """仅供 Flask TESTING 注入的执行协调器，不在生产应用自动创建。"""

    def __init__(self, store: TaskStore, runtime: RuntimeAdapter, result_factory: ResultFactory):
        self.store = store
        self.runtime = runtime
        self.result_factory = result_factory

    def execute(
        self,
        task_id: str,
        *,
        confirmation_sha256: str,
        expected_confirmation_sha256: str,
        actor_id: str,
        environment: str,
        target_id: str = "mock-target",
        resolved_target_url: str = "",
        project_threshold_ms: int | None = None,
        environment_threshold_ms: int | None = None,
    ) -> ExecutionRun:
        """创建独立 Run 并通过 Fake Runtime 生成标准、已脱敏结果。

        异常说明:
            确认摘要失效或无可执行用例时，在创建 Run 前抛出稳定业务错误。
        """

        if confirmation_sha256 != expected_confirmation_sha256:
            raise ServiceError(409, "EXECUTION_CONFIRMATION_STALE", "执行确认摘要已变化，请重新确认")
        executable = ApiV2Store(self.store).load_version(task_id, "executable-cases")
        cases = [item for item in executable["items"] if item.get("enabled") and item.get("validation_status") == "ready"]
        if not cases:
            raise ServiceError(409, "EXECUTABLE_CASE_NOT_READY", "没有通过静态校验的可执行用例")
        run_id = f"run_{secrets.token_hex(10)}"
        run = ExecutionRun(
            run_id=run_id, task_id=task_id, executable_case_version=executable["version"],
            environment=environment, target_id=target_id, status="validating", created_by=actor_id,
            confirmed_by=actor_id, confirmation_sha256=confirmation_sha256,
        )
        versions = ApiV2Store(self.store)
        versions.save_run_document(task_id, run_id, "run.json", run.model_dump(mode="json"))
        input_payload = {
            "run_id": run_id, "executable_sha256": executable["sha256"], "target_id": target_id,
            "resolved_target_url": resolved_target_url, "request_timeout_seconds": 10, "cases": cases,
        }
        input_path = versions.save_run_document(task_id, run_id, "input.json", redact_structure(input_payload))
        run.status = "provisioning"
        result = self.runtime.create(CreateRunRequest(
            run_id=run_id, input_id=f"{task_id}/{run_id}/input.json",
            output_id=f"{task_id}/{run_id}/executor-output.json",
            input_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
            resource_policy_id=getattr(self.runtime, "resource_policy_id", "s1-fake-resource"),
            egress_policy_id=getattr(self.runtime, "egress_policy_id", "s1-no-egress"), timeout_seconds=60,
        ))
        run.started_at = utc_now()
        if result.status in {"cancelled", "timed_out", "failed"}:
            run.status = result.status
            run.error_code = result.error_code or f"MOCK_{result.status.upper()}"
            run.finished_at = utc_now()
            versions.save_run_document(task_id, run_id, "run.json", run.model_dump(mode="json"))
            return run
        run.status = "running"
        raw_results = self.result_factory(run, cases)
        case_results = self._normalize_results(
            task_id, run, raw_results, cases,
            project_threshold_ms=project_threshold_ms,
            environment_threshold_ms=environment_threshold_ms,
        )
        versions.save_run_document(task_id, run_id, "case-results.json", [item.model_dump(mode="json") for item in case_results])
        run.status = "reporting"
        run.summary = self._summary(case_results)
        report = redact_structure({
            "run_id": run_id, "status": "succeeded", "summary": run.summary,
            "case_results": [item.model_dump(mode="json") for item in case_results],
        })
        versions.save_run_document(task_id, run_id, "report.json", report)
        run.status = "succeeded"
        run.finished_at = utc_now()
        versions.save_run_document(task_id, run_id, "run.json", run.model_dump(mode="json"))
        return run


    def cancel(self, task_id: str, run_id: str) -> ExecutionRun:
        """取消未终态 Mock Run；原结果文件不会被删除。"""

        run = self.load_run(task_id, run_id)
        if run.status in {"succeeded", "failed", "cancelled", "timed_out"}:
            raise ServiceError(409, "INVALID_RUN_STATE", "终态 Run 不允许取消")
        self.runtime.cancel(run_id)
        run.status = "cancelled"
        run.finished_at = utc_now()
        ApiV2Store(self.store).save_run_document(task_id, run_id, "run.json", run.model_dump(mode="json"))
        return run

    def load_run(self, task_id: str, run_id: str) -> ExecutionRun:
        """读取单个 Run，并阻止路径穿越。"""

        if not run_id.startswith("run_") or Path(run_id).name != run_id:
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在")
        path = self.store.task_dir(task_id) / "runs" / run_id / "run.json"
        try:
            return ExecutionRun.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在") from None

    def _normalize_results(
        self, task_id: str, run: ExecutionRun, raw_results: list[dict[str, Any]], cases: list[dict[str, Any]],
        *, project_threshold_ms: int | None, environment_threshold_ms: int | None,
    ) -> list[CaseResult]:
        """存储前脱敏，并为每条结果计算阈值来源和连续超限依据。"""

        by_id = {item["executable_case_id"]: item for item in cases}
        normalized = []
        for raw in raw_results:
            cleaned = redact_structure(raw)
            case_id = str(cleaned.get("case_id", ""))
            case = by_id.get(case_id, {})
            document_sla = case.get("document_sla_ms")
            if document_sla:
                threshold, source = int(document_sla), "document"
            elif project_threshold_ms:
                threshold, source = int(project_threshold_ms), "project"
            elif environment_threshold_ms:
                threshold, source = int(environment_threshold_ms), "environment"
            else:
                threshold, source = 3000, "default"
            duration = int(cleaned.get("duration_ms", 0))
            qualifying = self._prior_slow_runs(task_id, case_id, run.environment, threshold, source)
            applicable = cleaned.get("status") in {"passed", "failed"} and cleaned.get("failure_classification") not in {"environment_blocked"}
            if not applicable:
                performance_status, qualifying = "not_applicable", []
            elif duration <= threshold:
                performance_status, qualifying = "within_threshold", []
            else:
                qualifying = [*qualifying, run.run_id]
                performance_status = "performance_candidate" if len(qualifying) >= 3 else "warning"
            cleaned["performance_evaluation"] = PerformanceEvaluation(
                duration_ms=duration, threshold_ms=threshold, threshold_source=source,
                status=performance_status, basis=f"{source} threshold={threshold}ms; duration={duration}ms",
                qualifying_run_ids=qualifying[-3:] if performance_status == "performance_candidate" else qualifying,
            ).model_dump(mode="json")
            if performance_status == "performance_candidate" and cleaned.get("failure_classification") in {"none", "unknown"}:
                cleaned["failure_classification"] = "performance_candidate"
            normalized.append(CaseResult.model_validate(cleaned))
        return normalized

    def _prior_slow_runs(self, task_id: str, case_id: str, environment: str, threshold: int, source: str) -> list[str]:
        """按时间顺序查找同用例、环境和阈值语义下末尾连续慢 Run。"""

        records = []
        runs_dir = self.store.task_dir(task_id) / "runs"
        for path in runs_dir.glob("run_*/case-results.json"):
            try:
                run = ExecutionRun.model_validate_json((path.parent / "run.json").read_text(encoding="utf-8"))
                results = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if run.environment != environment:
                continue
            result = next((item for item in results if item.get("case_id") == case_id), None)
            evaluation = (result or {}).get("performance_evaluation") or {}
            records.append((run.created_at, run.run_id, result, evaluation))
        consecutive = []
        for _created, run_id, result, evaluation in sorted(records):
            qualifies = (
                result and result.get("status") in {"passed", "failed"}
                and result.get("failure_classification") != "environment_blocked"
                and evaluation.get("threshold_ms") == threshold
                and evaluation.get("threshold_source") == source
                and evaluation.get("duration_ms", 0) > threshold
            )
            consecutive = [*consecutive, run_id] if qualifies else []
        return consecutive[-2:]

    @staticmethod
    def _summary(results: list[CaseResult]) -> dict[str, Any]:
        """按失败分类输出确定性报告摘要。"""

        classifications: dict[str, int] = {}
        for result in results:
            classifications[result.failure_classification] = classifications.get(result.failure_classification, 0) + 1
        return {
            "total": len(results), "passed": sum(item.status == "passed" for item in results),
            "failed": sum(item.status != "passed" for item in results), "classifications": classifications,
        }


class RealExecutionService(MockExecutionService):
    """通过独立 Controller 同步执行，并读取标准 Executor 输出。"""

    def __init__(self, store: TaskStore, runtime: RuntimeAdapter):
        """复用既有不可变 Run、脱敏、分类和报告逻辑，不在 Web 内发目标请求。"""

        super().__init__(store, runtime, self._read_executor_results)

    def _read_executor_results(self, run: ExecutionRun, _cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """只读取当前 Run 的固定输出文件；格式不合法时失败关闭。"""

        path = self.store.task_dir(run.task_id) / "runs" / run.run_id / "executor-output.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ServiceError(502, "EXECUTOR_RESULT_INVALID", "Executor 未返回有效结果") from exc
        if payload.get("run_id") != run.run_id or not isinstance(payload.get("case_results"), list):
            raise ServiceError(502, "EXECUTOR_RESULT_INVALID", "Executor 结果与当前 Run 不匹配")
        return payload["case_results"]
