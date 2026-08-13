"""本地 Bug 草稿的生成、版本、冲突和确定性下载。"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from services.api_agent.models import CaseResult, DefectDraft, ExecutionRun, utc_now
from services.api_agent.v2_store import canonical_sha256
from services.common.errors import ServiceError
from services.common.redaction import redact_structure
from services.common.task_store import TaskStore


EDITABLE_FIELDS = frozenset({
    "title", "module", "severity_suggestion", "preconditions", "reproduction_steps",
    "expected_result", "actual_result", "error_summary", "ai_analysis", "confidence",
    "open_questions", "manual_reason",
})


class DefectDraftService:
    """只在当前任务目录保存草稿；没有任何外部系统调用。"""

    def __init__(self, store: TaskStore):
        self.store = store

    def create(self, task_id: str, run_id: str, case_ids: list[str], *, actor_id: str, manual_reason: str = "") -> DefectDraft:
        """从已保存失败结果生成脱敏草稿；环境/数据/用例问题要求人工理由。"""

        run, results = self._load_results(task_id, run_id)
        selected = [
            item for item in results
            if item.case_id in case_ids and (
                item.status != "passed" or item.failure_classification == "performance_candidate"
            )
        ]
        if not selected:
            raise ServiceError(422, "DEFECT_SOURCE_INVALID", "请选择已保存的失败结果")
        discouraged = {"environment_blocked", "test_data_issue", "test_case_issue"}
        if any(item.failure_classification in discouraged for item in selected) and not manual_reason.strip():
            raise ServiceError(422, "DEFECT_REASON_REQUIRED", "该分类不建议作为接口 Bug；继续生成需填写原因")
        first = selected[0]
        draft_id = f"draft_{secrets.token_hex(10)}"
        draft = DefectDraft(
            draft_id=draft_id, version=1, task_id=task_id, run_id=run_id,
            case_ids=[item.case_id for item in selected], title=f"[API] {first.case_id} 执行结果不符合预期",
            module="API 测试", interface=first.case_id, environment=run.environment,
            preconditions=["使用已确认契约和用例版本执行"],
            reproduction_steps=["选择对应执行环境", "执行已确认用例", "查看失败断言与脱敏响应"],
            masked_request=redact_structure(first.request_summary), expected_result="接口响应满足已确认契约与断言",
            actual_result=str(first.response_summary or first.error_signature),
            status_code=first.response_summary.get("status_code") if isinstance(first.response_summary, dict) else None,
            request_id=str(first.response_summary.get("request_id", "")) if isinstance(first.response_summary, dict) else "",
            error_summary=first.error_signature, evidence_links=[f"runs/{run_id}/case-results.json"],
            ai_analysis=f"失败分类：{first.failure_classification}", confidence=0.5,
            manual_reason=manual_reason, created_by=actor_id, updated_by=actor_id,
        )
        return self._save(task_id, draft)

    def list(self, task_id: str) -> list[DefectDraft]:
        """返回每个本地草稿的最新版本，不读取或同步任何外部状态。"""

        root = self.store.task_dir(task_id) / "versions" / "defect-drafts"
        drafts = []
        for directory in root.glob("draft_*"):
            if directory.is_dir() and Path(directory.name).name == directory.name:
                try:
                    drafts.append(self.load(task_id, directory.name))
                except ServiceError:
                    continue
        return sorted(drafts, key=lambda item: (item.updated_at, item.draft_id), reverse=True)

    def update(self, task_id: str, draft_id: str, *, base_version: int, fields: dict[str, Any], actor_id: str) -> DefectDraft:
        """以乐观锁追加草稿版本，永不覆盖旧文件。"""

        current = self.load(task_id, draft_id)
        if current.version != base_version:
            raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "Bug 草稿已更新，请刷新后重试")
        if not fields or set(fields) - EDITABLE_FIELDS:
            raise ServiceError(422, "REVIEW_FIELD_FORBIDDEN", "草稿包含不可编辑字段")
        payload = current.model_dump(mode="json")
        payload.update(redact_structure(fields))
        payload.update({"version": base_version + 1, "updated_by": actor_id, "updated_at": utc_now(), "sha256": ""})
        return self._save(task_id, DefectDraft.model_validate(payload))

    def load(self, task_id: str, draft_id: str, version: int | None = None) -> DefectDraft:
        """读取指定或最新草稿版本。"""

        if not draft_id.startswith("draft_") or Path(draft_id).name != draft_id:
            raise ServiceError(404, "DEFECT_DRAFT_NOT_FOUND", "Bug 草稿不存在")
        directory = self.store.task_dir(task_id) / "versions" / "defect-drafts" / draft_id
        if version is None:
            versions = [int(path.stem[1:]) for path in directory.glob("v*.json") if path.stem[1:].isdigit()]
            version = max(versions, default=0)
        try:
            return DefectDraft.model_validate_json((directory / f"v{version}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ServiceError(404, "DEFECT_DRAFT_NOT_FOUND", "Bug 草稿不存在") from None

    def download(self, task_id: str, draft_id: str, format_name: str) -> tuple[bytes, str, str]:
        """在下载前再次脱敏，并返回 JSON 或确定性 Markdown。"""

        draft_model = self.load(task_id, draft_id)
        draft = redact_structure(draft_model.model_dump(mode="json"))
        if format_name == "json":
            self._append_audit(task_id, draft_model, action="download_json")
            return json.dumps(draft, ensure_ascii=False, indent=2).encode(), "application/json", f"{draft_id}.json"
        if format_name != "markdown":
            raise ServiceError(422, "DOWNLOAD_FORMAT_UNSUPPORTED", "仅支持 JSON 和 Markdown")
        lines = [
            f"# {draft['title']}", "", f"- 环境：{draft['environment']}", f"- 接口：{draft['interface']}",
            f"- 严重程度建议：{draft['severity_suggestion']}", "", "## 复现步骤", "",
            *[f"{index}. {step}" for index, step in enumerate(draft["reproduction_steps"], 1)],
            "", "## 预期结果", "", draft["expected_result"], "", "## 实际结果", "", draft["actual_result"],
            "", "## 证据", "", *[f"- {item}" for item in draft["evidence_links"]], "",
        ]
        self._append_audit(task_id, draft_model, action="download_markdown")
        return "\n".join(lines).encode(), "text/markdown; charset=utf-8", f"{draft_id}.md"

    def _save(self, task_id: str, draft: DefectDraft) -> DefectDraft:
        """计算内容 SHA 并原子追加版本。"""

        payload = redact_structure(draft.model_dump(mode="json"))
        payload["sha256"] = canonical_sha256({**payload, "sha256": ""})
        validated = DefectDraft.model_validate(payload)
        path = self.store.task_dir(task_id) / "versions" / "defect-drafts" / draft.draft_id / f"v{draft.version}.json"
        TaskStore.atomic_write_json(path, validated.model_dump(mode="json"))
        self._append_audit(task_id, validated, action="save")
        return validated

    def _load_results(self, task_id: str, run_id: str) -> tuple[ExecutionRun, list[CaseResult]]:
        """只读取当前任务内已落盘的 Run 和结果。"""

        if not run_id.startswith("run_") or Path(run_id).name != run_id:
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 不存在")
        directory = self.store.task_dir(task_id) / "runs" / run_id
        try:
            run = ExecutionRun.model_validate_json((directory / "run.json").read_text(encoding="utf-8"))
            results = [CaseResult.model_validate(item) for item in json.loads((directory / "case-results.json").read_text(encoding="utf-8"))]
        except (OSError, ValueError, json.JSONDecodeError):
            raise ServiceError(404, "RUN_NOT_FOUND", "Run 结果不存在") from None
        return run, results

    def _append_audit(self, task_id: str, draft: DefectDraft, *, action: str) -> None:
        """草稿审计只保存 ID、版本、SHA 和人员。"""

        path = self.store.task_dir(task_id) / "defect-audit.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"schema_version": 2, "items": []}
        payload["items"].append({
            "action": action,
            "draft_id": draft.draft_id, "version": draft.version, "sha256": draft.sha256,
            "updated_by": draft.updated_by, "updated_at": draft.updated_at,
        })
        TaskStore.atomic_write_json(path, payload)
