"""S1 Mock Run、不可变结果、失败分类和慢响应规则。"""

from __future__ import annotations

import json
import hashlib
import secrets
from pathlib import Path
from typing import Any, Callable

from services.api_agent.models import (
    CaseResult,
    ExecutionRun,
    ExecutionStepResult,
    PerformanceEvaluation,
    utc_now,
)
from services.api_agent.execution_plan import validate_execution_plan_hashes
from services.api_agent.v2_store import ApiV2Store
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
        # Real Executor 的逐节点结果与兼容 CaseResult 共用一次回调。按 Run 暂存
        # 原始节点结果，主流程统一完成 Schema 校验和一次性落盘，避免被兼容结果覆盖。
        self._pending_step_results: dict[str, list[dict[str, Any]]] = {}

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
        execution_plan: dict[str, Any],
        retry_of_run_id: str | None = None,
    ) -> ExecutionRun:
        """创建独立 Run 并通过 Fake Runtime 生成标准、已脱敏结果。

        异常说明:
            确认摘要失效或无可执行用例时，在创建 Run 前抛出稳定业务错误。
        """

        if confirmation_sha256 != expected_confirmation_sha256:
            raise ServiceError(409, "EXECUTION_CONFIRMATION_STALE", "执行确认摘要已变化，请重新确认")
        executable = ApiV2Store(self.store).load_version(task_id, "executable-cases")
        if not isinstance(execution_plan, dict) or execution_plan.get("status") != "confirmed":
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "只能使用已确认的 V2.4 执行计划创建 Run")
        # 新 V2.4 编译计划在服务边界再次重算业务正文 SHA；测试夹具和历史只读
        # 计划没有目标快照，由浏览器 Run 路由统一要求重新生成，避免破坏历史报告读取。
        if execution_plan.get("target_policy_sha256") and not validate_execution_plan_hashes(execution_plan):
            raise ServiceError(409, "EXECUTION_PLAN_STALE", "执行计划内容校验失败，请重新生成并确认")
        if execution_plan.get("confirmation_sha256") != confirmation_sha256:
            raise ServiceError(409, "EXECUTION_PLAN_CONFIRMATION_EXPIRED", "执行计划确认摘要已失效")
        if int(execution_plan.get("source_executable_version", 0) or 0) != int(executable["version"]):
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "执行计划引用的执行定义版本已过期")
        if str(execution_plan.get("source_executable_sha256", "")) != str(executable.get("sha256", "")):
            raise ServiceError(409, "EXECUTION_PLAN_INVALID", "执行计划引用的执行定义内容已变化")
        planned_resource_policy = str(execution_plan.get("resource_policy_id", ""))
        if planned_resource_policy and planned_resource_policy != str(getattr(self.runtime, "resource_policy_id", "")):
            raise ServiceError(409, "EXECUTION_PLAN_POLICY_STALE", "执行计划资源策略已变化，请重新生成计划")
        planned_egress_policy = str(execution_plan.get("egress_policy_id", ""))
        if planned_egress_policy and planned_egress_policy != str(getattr(self.runtime, "egress_policy_id", "")):
            raise ServiceError(409, "EXECUTION_PLAN_POLICY_STALE", "执行计划出口策略已变化，请重新生成计划")
        nodes = execution_plan.get("nodes") if isinstance(execution_plan.get("nodes"), list) else []
        cases = [
            {
                "executable_case_id": str(node.get("executable_case_id") or node.get("node_id")),
                "document_sla_ms": node.get("document_sla_ms"),
                "request": node.get("request") if isinstance(node.get("request"), dict) else {},
            }
            for node in nodes if isinstance(node, dict)
        ]
        if not cases:
            raise ServiceError(409, "EXECUTABLE_CASE_NOT_READY", "没有通过静态校验的可执行用例")
        run_id = f"run_{secrets.token_hex(10)}"
        run = ExecutionRun(
            run_id=run_id, task_id=task_id, executable_case_version=executable["version"],
            execution_plan_id=str(execution_plan.get("plan_id") or "") or None,
            execution_plan_version=int(execution_plan.get("version") or 0) or None,
            execution_plan_sha256=str(execution_plan.get("sha256") or ""),
            environment=environment, target_id=target_id, status="validating", created_by=actor_id,
            confirmed_by=actor_id, confirmation_sha256=confirmation_sha256,
            retry_of_run_id=retry_of_run_id,
        )
        versions = ApiV2Store(self.store)
        versions.save_run_document(task_id, run_id, "run.json", run.model_dump(mode="json"))
        input_payload = {
            "run_id": run_id, "executable_sha256": executable["sha256"], "target_id": target_id,
            "resolved_target_url": resolved_target_url, "request_timeout_seconds": 10,
        }
        input_payload["plan"] = execution_plan
        input_path = versions.save_run_document(task_id, run_id, "input.json", redact_structure(input_payload))
        run.status = "provisioning"
        result = self.runtime.create(CreateRunRequest(
            run_id=run_id, input_id=f"{task_id}/{run_id}/input.json",
            plan_id=run.execution_plan_id or "", plan_sha256=run.execution_plan_sha256,
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
        # 逐节点结果与兼容 CaseResult 分开保存。前者保留 DAG 节点、阻断来源和
        # 变量提取摘要，后者继续服务现有报告与 Bug 草稿，二者均在落盘前脱敏。
        step_results = []
        node_ids = [str(item) for item in execution_plan.get("topological_order", [])]
        raw_steps = self._pending_step_results.pop(run_id, raw_results)
        for index, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            node_id = str(raw.get("node_id") or (node_ids[index] if index < len(node_ids) else raw.get("case_id", "")))
            extracted = raw.get("extracted_variables") if isinstance(raw.get("extracted_variables"), list) else []
            extracted_names = [
                str(item.get("name")) if isinstance(item, dict) else str(item)
                for item in extracted if (isinstance(item, dict) and item.get("name")) or isinstance(item, str)
            ]
            normalized_step = ExecutionStepResult.model_validate({
                "step_id": str(raw.get("step_id") or f"step_{index + 1}"),
                "node_id": node_id,
                "executable_case_id": str(raw.get("executable_case_id") or raw.get("case_id") or node_id),
                "status": raw.get("status"),
                "started_at": raw.get("started_at") or utc_now(),
                "finished_at": raw.get("finished_at") or utc_now(),
                "duration_ms": int(raw.get("duration_ms", 0) or 0),
                "blocked_by": raw.get("blocked_by") if isinstance(raw.get("blocked_by"), list) else [],
                "extracted_variables": extracted_names,
                "request_summary": raw.get("request_summary") if isinstance(raw.get("request_summary"), dict) else {},
                "response_summary": raw.get("response_summary") if isinstance(raw.get("response_summary"), dict) else {},
                "assertion_results": raw.get("assertion_results") if isinstance(raw.get("assertion_results"), list) else [],
                "error_code": str(raw.get("error_code") or raw.get("error_signature") or "") or None,
                "error_message": str(raw.get("error_message") or "") or None,
            })
            step_results.append(redact_structure(normalized_step.model_dump(mode="json")))
        versions.save_run_document(task_id, run_id, "step-results.json", step_results)
        case_results = self._normalize_results(
            task_id, run, raw_results, cases,
            project_threshold_ms=project_threshold_ms,
            environment_threshold_ms=environment_threshold_ms,
        )
        versions.save_run_document(task_id, run_id, "case-results.json", [item.model_dump(mode="json") for item in case_results])
        run.status = "reporting"
        run.summary = self._summary(case_results)
        run.node_summary = {
            status: sum(1 for item in step_results if item.get("status") == status)
            for status in ("passed", "failed", "error", "blocked", "skipped", "cancelled", "timed_out")
            if any(item.get("status") == status for item in step_results)
        }
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
            # Executor V2.4 会返回节点级附加字段；它们进入独立 step-results.json，
            # 不能直接喂给 extra=forbid 的兼容 CaseResult Schema。
            cleaned = {
                key: value for key, value in cleaned.items()
                if key in {
                    "case_id", "status", "started_at", "finished_at", "duration_ms",
                    "step_results", "request_summary", "response_summary", "assertion_results",
                    "failure_classification", "error_signature", "performance_evaluation",
                }
            }
            if cleaned.get("status") == "blocked":
                cleaned["status"] = "skipped"
            elif cleaned.get("status") == "timed_out":
                cleaned["status"] = "error"
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
        if isinstance(payload.get("step_results"), list):
            self._pending_step_results[run.run_id] = payload["step_results"]
        return payload["case_results"]
