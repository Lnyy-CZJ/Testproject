"""API V2 文档修订、分析范围、影响预览和问题解决服务。"""

from __future__ import annotations

from copy import deepcopy
from difflib import unified_diff
from fnmatch import fnmatch
import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agents.api_test.contracts.format_detector import detect_document_format
from agents.api_test.contracts.quality_gate import apply_quality_gate
from services.api_agent.models import (
    AnalysisScopeVersion, ApiContract, DocumentRevision, DocumentValidationResult,
    FieldEvidence, ReviewIssue, utc_now,
)
from services.api_agent.v2_store import ApiV2Store, canonical_sha256
from services.common.errors import ServiceError
from services.common.redaction import redact_text
from services.common.task_store import TaskStore


MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_CHARACTERS = 500_000
_ISSUE_ACTIONS = frozenset({
    "bind_evidence", "edit_field", "remove_inference", "human_override",
    "accept_as_suggestion", "review", "reopen",
})
_PARAMETER_PATH = re.compile(r"^parameters\[(\d+)]\.(name|location|required|description)$")
_RESPONSE_PATH = re.compile(r"^responses\[(\d+)]\.status_code$")


def _actor(user_id: str, username: str) -> dict[str, str]:
    return {"user_id": user_id, "username": username}


def _issue_id(contract_id: str, issue: ReviewIssue) -> str:
    """为旧问题生成跨读取稳定的 ID，不修改旧版本。"""

    if issue.issue_id:
        return issue.issue_id
    value = f"{contract_id}|{issue.code}|{issue.field_path}|{issue.source_pointer}"
    return "issue_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


class DocumentRevisionService:
    """在 TaskStore 任务锁内追加文档、范围和 Review 版本。"""

    def __init__(self, store: TaskStore, *, feature_enabled: bool | None = None):
        self.store = store
        self.versions = ApiV2Store(store)
        self._feature_enabled = feature_enabled

    def feature_enabled(self) -> bool:
        """本机开发默认开启；生产必须显式开启。"""

        import os

        if self._feature_enabled is not None:
            return self._feature_enabled
        configured = os.getenv("API_PRE_REVIEW_V21_ENABLED")
        if configured is not None:
            return configured.strip().lower() in {"1", "true", "yes", "on"}
        return os.getenv("APP_ENV", os.getenv("RUNTIME_ENVIRONMENT", "dev")).lower() not in {"prod", "production"}

    def ensure_initial_versions(
        self, task_id: str, *, created_by: dict[str, str] | None = None,
        register: bool = False, task_record: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """读取初始文档与范围；旧任务只读访问时返回内存中的虚拟 v1。"""

        documents = self.versions.list_versions(task_id, "documents")
        scopes = self.versions.list_versions(task_id, "analysis-scopes")
        if documents and scopes:
            return documents[0], scopes[0]
        record = task_record or self.store.load(task_id) or {}
        request_path = self.store.task_dir(task_id) / "request.json"
        try:
            request_payload = json.loads(request_path.read_text(encoding="utf-8"))
            source_path = self.store.task_dir(task_id) / str(request_payload["input_relative_path"])
            content = source_path.read_text(encoding="utf-8")
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ServiceError(404, "DOCUMENT_SOURCE_NOT_AVAILABLE", "原始接口文档不可用，已生成产物仍可查看") from exc
        actor = created_by or _actor(str(record.get("created_by_user_id", "system")), str(record.get("created_by_username", "system")))
        if not documents:
            document = self._build_document(
                content=content, filename=str(request_payload.get("input_original_name", source_path.name)),
                source_type="paste" if request_payload.get("input_original_name") == "pasted.md" else "upload",
                version=1, parent_version=None, reason="初始接口文档", actor=actor, status="analyzed",
            )
            document_envelope = self._initial_envelope("documents", document.model_dump(mode="json"), actor)
            if register:
                document_envelope = self.versions.save_version(
                    task_id, kind="documents", items=document.model_dump(mode="json"), created_by=actor["user_id"],
                )
        else:
            document_envelope = documents[0]
            document = DocumentRevision.model_validate(document_envelope["items"])
        if not scopes:
            scope = self._build_scope(
                version=1, document_version=document.version, fields={
                    "project": record.get("project_name", ""), "module": record.get("module_name", ""),
                    "environment": record.get("environment", ""),
                }, actor=actor,
            )
            scope_envelope = self._initial_envelope("analysis-scopes", scope.model_dump(mode="json"), actor)
            if register:
                scope_envelope = self.versions.save_version(
                    task_id, kind="analysis-scopes", items=scope.model_dump(mode="json"),
                    source_versions={"documents": document.version}, created_by=actor["user_id"],
                )
        else:
            scope_envelope = scopes[0]
        return document_envelope, scope_envelope

    def list_documents(self, task_id: str) -> dict[str, Any]:
        virtual_document, _scope = self.ensure_initial_versions(task_id)
        items = []
        envelopes = self.versions.list_versions(task_id, "documents") or [virtual_document]
        current_version = int(envelopes[0]["version"])
        for envelope in envelopes:
            document = DocumentRevision.model_validate(envelope["items"])
            items.append({
                "version": document.version, "revision_id": document.revision_id,
                "source_filename": document.source_filename, "document_format": document.document_format,
                "content_sha256": document.content_sha256, "parent_version": document.parent_version,
                "status": document.status if document.version == current_version else "superseded",
                "created_by": document.created_by, "created_at": document.created_at,
            })
        return {"items": items, "current_version": items[0]["version"]}

    def get_document(self, task_id: str, version: int) -> dict[str, Any]:
        virtual_document, _scope = self.ensure_initial_versions(task_id)
        try:
            envelope = self.versions.load_version(task_id, "documents", version)
        except FileNotFoundError:
            if version != 1 or self.versions.list_versions(task_id, "documents"):
                raise ServiceError(404, "DOCUMENT_SOURCE_NOT_AVAILABLE", "文档版本不存在")
            envelope = virtual_document
        document = DocumentRevision.model_validate(envelope["items"])
        return {**document.model_dump(mode="json"), "content": redact_text(document.content), "sha256": envelope["sha256"]}

    def create_revision(
        self, task_id: str, *, base_version: int, content: str, change_reason: str,
        actor: dict[str, str],
    ) -> dict[str, Any]:
        """校验并追加文档修订；不自动启动重新分析。"""

        if not self.feature_enabled():
            raise ServiceError(403, "FEATURE_DISABLED", "文档修订与重新分析当前未启用")
        if not change_reason.strip():
            raise ServiceError(422, "DOCUMENT_VALIDATION_FAILED", "文档修订必须填写修改说明")
        with self.store.locked():
            self.ensure_initial_versions(task_id, created_by=actor, register=True)
            latest = self.versions.list_versions(task_id, "documents")[0]
            if int(latest["version"]) != base_version:
                raise ServiceError(409, "DOCUMENT_VERSION_CONFLICT", "文档已产生新版本，请刷新后重试")
            previous = DocumentRevision.model_validate(latest["items"])
            document = self._build_document(
                content=content, filename=previous.source_filename, source_type="revision",
                version=base_version + 1, parent_version=base_version,
                reason=change_reason.strip(), actor=actor, status="validated",
            )
            saved = self.versions.save_version(
                task_id, kind="documents", items=document.model_dump(mode="json"),
                source_versions={"documents": base_version}, created_by=actor["user_id"],
            )
            self.append_action_audit(
                task_id, action="document.revision", version=saved["version"],
                object_id=document.revision_id, actor=actor,
            )
            return saved

    def compare(self, task_id: str, from_version: int, to_version: int) -> dict[str, Any]:
        before = DocumentRevision.model_validate(self.versions.load_version(task_id, "documents", from_version)["items"])
        after = DocumentRevision.model_validate(self.versions.load_version(task_id, "documents", to_version)["items"])
        lines = list(unified_diff(
            before.content.splitlines(), after.content.splitlines(),
            fromfile=f"v{from_version}", tofile=f"v{to_version}", lineterm="",
        ))
        return {"from_version": from_version, "to_version": to_version, "lines": lines[:5000], "truncated": len(lines) > 5000}

    def get_scope(self, task_id: str) -> dict[str, Any]:
        _document, virtual_scope = self.ensure_initial_versions(task_id)
        try:
            return self.versions.load_version(task_id, "analysis-scopes")
        except FileNotFoundError:
            return virtual_scope

    def save_scope(
        self, task_id: str, *, base_version: int, document_version: int,
        fields: dict[str, Any], actor: dict[str, str], reason: str,
    ) -> dict[str, Any]:
        if not self.feature_enabled():
            raise ServiceError(403, "FEATURE_DISABLED", "分析范围修改当前未启用")
        if not reason.strip():
            raise ServiceError(422, "ANALYSIS_SCOPE_INVALID", "修改分析范围必须填写原因")
        with self.store.locked():
            self.ensure_initial_versions(task_id, created_by=actor, register=True)
            self.versions.load_version(task_id, "documents", document_version)
            current = self.get_scope(task_id)
            if int(current["version"]) != base_version:
                raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "分析范围已更新，请刷新后重试")
            try:
                scope = self._build_scope(
                    version=base_version + 1, document_version=document_version,
                    fields=fields, actor=actor,
                )
            except ValidationError as exc:
                raise ServiceError(422, "ANALYSIS_SCOPE_INVALID", "分析范围包含不支持的 method 或 path") from exc
            saved = self.versions.save_version(
                task_id, kind="analysis-scopes", items=scope.model_dump(mode="json"),
                source_versions={"documents": document_version, "analysis-scopes": base_version},
                created_by=actor["user_id"],
            )
            self.append_action_audit(
                task_id, action="analysis_scope.update", version=saved["version"],
                object_id=scope.scope_id, actor=actor,
            )
            return saved

    def preview_reanalysis(self, task_id: str, *, document_version: int, scope_version: int) -> dict[str, Any]:
        virtual_document, virtual_scope = self.ensure_initial_versions(task_id)
        try:
            document_envelope = self.versions.load_version(task_id, "documents", document_version)
        except FileNotFoundError:
            if document_version != 1:
                raise ServiceError(404, "DOCUMENT_SOURCE_NOT_AVAILABLE", "文档版本不存在")
            document_envelope = virtual_document
        try:
            scope_envelope = self.versions.load_version(task_id, "analysis-scopes", scope_version)
        except FileNotFoundError:
            if scope_version != 1:
                raise ServiceError(422, "ANALYSIS_SCOPE_INVALID", "分析范围版本不存在")
            scope_envelope = virtual_scope
        document = DocumentRevision.model_validate(document_envelope["items"])
        scope = AnalysisScopeVersion.model_validate(scope_envelope["items"])
        if scope.document_version != document_version:
            raise ServiceError(422, "ANALYSIS_SCOPE_INVALID", "分析范围未绑定所选文档版本")
        record = self.store.load(task_id) or {}
        stale = []
        for kind in ("contracts", "coverage", "base-cases", "executable-cases"):
            pointer = record.get("current_versions", {}).get(kind)
            if pointer:
                stale.append({"kind": kind, **pointer})
        runs_dir = self.store.task_dir(task_id) / "runs"
        drafts = self.versions.list_versions(task_id, "defect-drafts")
        summary = {
            "task_id": task_id, "document_version": document_version,
            "document_sha256": document.content_sha256, "scope_version": scope_version,
            "scope_sha256": scope.sha256,
            "estimated_interface_count": document.validation_result.estimated_interface_count,
            "stale_versions": stale,
            "preserved_run_count": len(list(runs_dir.glob("run_*/run.json"))) if runs_dir.is_dir() else 0,
            "preserved_defect_version_count": len(drafts),
        }
        summary["preview_sha256"] = canonical_sha256(summary)
        return summary

    def list_issues(self, task_id: str, contract_id: str = "") -> dict[str, Any]:
        current = self.versions.load_version(task_id, "contracts")
        items = []
        for raw in current["items"]:
            contract = ApiContract.model_validate(raw)
            if contract_id and contract.contract_id != contract_id:
                continue
            for category in ("conflict_items", "ambiguity_notes", "unresolved"):
                for issue in getattr(contract, category):
                    payload = issue.model_copy(update={
                        "issue_id": _issue_id(contract.contract_id, issue),
                        "contract_id": contract.contract_id,
                    }).model_dump(mode="json")
                    try:
                        payload["current_value"] = self._field_value(contract, issue.field_path)
                    except ServiceError:
                        payload["current_value"] = issue.current_value
                    payload.update({"category": category, "method": contract.method, "path": contract.path})
                    items.append(payload)
        return {"version": current["version"], "items": items}

    def resolve_issue(
        self, task_id: str, issue_id: str, *, base_contract_version: int,
        action: str, reason: str, payload: dict[str, Any], actor: dict[str, str],
    ) -> dict[str, Any]:
        """在同一任务锁内完成版本冲突检查、修改、门禁和保存。"""

        with self.store.locked():
            return self._resolve_issue_locked(
                task_id, issue_id, base_contract_version=base_contract_version,
                action=action, reason=reason, payload=payload, actor=actor,
            )

    def _resolve_issue_locked(
        self, task_id: str, issue_id: str, *, base_contract_version: int,
        action: str, reason: str, payload: dict[str, Any], actor: dict[str, str],
    ) -> dict[str, Any]:
        """执行受控问题动作并追加契约版本。"""

        if action not in _ISSUE_ACTIONS:
            raise ServiceError(422, "REVIEW_ACTION_UNSUPPORTED", "问题解决动作不受支持")
        if action not in {"reopen", "review"} and not reason.strip():
            raise ServiceError(422, "REVIEW_ISSUE_STILL_BLOCKED", "问题解决必须填写依据或原因")
        current = self.versions.load_version(task_id, "contracts")
        if int(current["version"]) != base_contract_version:
            raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "契约已更新，请刷新后重试")
        contracts = [ApiContract.model_validate(item) for item in current["items"]]
        target: tuple[ApiContract, str, int, ReviewIssue] | None = None
        for contract in contracts:
            for category in ("conflict_items", "ambiguity_notes", "unresolved"):
                for index, issue in enumerate(getattr(contract, category)):
                    if _issue_id(contract.contract_id, issue) == issue_id:
                        target = contract, category, index, issue
                        break
        if target is None:
            raise ServiceError(404, "REVIEW_ISSUE_NOT_FOUND", "冲突或未解决项不存在")
        contract, category, index, issue = target
        issue.issue_id = issue_id
        issue.contract_id = contract.contract_id
        if action == "reopen":
            issue.status = "reopened"
            issue.reviewed_by = None
            issue.reviewed_at = None
        elif action == "review":
            if issue.status not in {"resolved", "accepted_as_suggestion"}:
                raise ServiceError(409, "REVIEW_ISSUE_STILL_BLOCKED", "问题尚未解决，不能复核")
            issue.reviewed_by = actor
            issue.reviewed_at = utc_now()
        else:
            self._apply_issue_resolution(task_id, contract, issue, action, reason.strip(), payload, actor)
        getattr(contract, category)[index] = issue
        checked = apply_quality_gate(contract)
        checked.change_history.append({
            "field_path": issue.field_path, "old_value": issue.current_value,
            "new_value": payload.get("value"), "reason": reason, **actor,
            "action": action, "changed_at": utc_now(),
        })
        items = [checked if item.contract_id == checked.contract_id else item for item in contracts]
        saved = self.versions.save_version(
            task_id, kind="contracts", items=[item.model_dump(mode="json", by_alias=True) for item in items],
            source_versions={"contracts": base_contract_version}, created_by=actor["user_id"],
        )
        self._append_audit(task_id, action, saved["version"], issue, actor)
        return saved

    def filter_contracts(
        self, contracts: list[ApiContract], scope: AnalysisScopeVersion, *, minimum_score: float = 0.90,
    ) -> list[ApiContract]:
        """按已确认范围过滤并裁剪分析维度；空规则代表全部。"""

        result = []
        for contract in contracts:
            if scope.include_methods and contract.method not in scope.include_methods:
                continue
            if scope.include_paths and not any(fnmatch(contract.path, pattern) for pattern in scope.include_paths):
                continue
            if scope.exclude_paths and any(fnmatch(contract.path, pattern) for pattern in scope.exclude_paths):
                continue
            if scope.modules and contract.module not in scope.modules:
                continue
            if scope.tags and not set(contract.tags).intersection(scope.tags):
                continue
            scoped = contract.model_copy(deep=True)
            if not scope.analyze_request:
                scoped.parameters = []
                scoped.request_body = None
                self._drop_contract_paths(scoped, ("parameters", "request_body"))
            if not scope.analyze_response:
                scoped.responses = []
                self._drop_contract_paths(scoped, ("responses",))
            elif not scope.analyze_errors:
                scoped.responses = [item for item in scoped.responses if item.status_code.startswith("2")]
                self._drop_contract_paths(scoped, ("responses",))
                scoped.field_evidence.extend(
                    FieldEvidence(
                        field_path=f"responses[{index}].status_code", value=item.status_code,
                        source_type="human_override", source_pointer=f"analysis-scope:v{scope.version}",
                    )
                    for index, item in enumerate(scoped.responses)
                )
            if not scope.analyze_security:
                scoped.security = []
                self._drop_contract_paths(scoped, ("security",))
            if not scope.analyze_dependencies:
                scoped.dependencies = []
            result.append(apply_quality_gate(scoped, minimum_score=minimum_score))
        return result

    @staticmethod
    def _drop_contract_paths(contract: ApiContract, prefixes: tuple[str, ...]) -> None:
        """清理被范围排除字段的 Evidence 与问题，避免展示过期阻断。"""

        def kept(field_path: str) -> bool:
            return not any(field_path == prefix or field_path.startswith(f"{prefix}[") or field_path.startswith(f"{prefix}.") for prefix in prefixes)

        contract.field_evidence = [item for item in contract.field_evidence if kept(item.field_path)]
        contract.unresolved = [item for item in contract.unresolved if kept(item.field_path)]
        contract.conflict_items = [item for item in contract.conflict_items if kept(item.field_path)]
        contract.ambiguity_notes = [item for item in contract.ambiguity_notes if kept(item.field_path)]

    def _build_document(
        self, *, content: str, filename: str, source_type: str, version: int,
        parent_version: int | None, reason: str, actor: dict[str, str], status: str,
    ) -> DocumentRevision:
        encoded = content.encode("utf-8")
        if not content.strip() or len(encoded) > MAX_DOCUMENT_BYTES or len(content) > MAX_DOCUMENT_CHARACTERS:
            raise ServiceError(422, "DOCUMENT_VALIDATION_FAILED", "接口文档为空或超过 5 MB/字符限制")
        try:
            document_format, _structured, profile = detect_document_format(content, filename)
        except ServiceError as exc:
            raise ServiceError(422, "DOCUMENT_VALIDATION_FAILED", exc.message, details={"cause": exc.code}) from exc
        safe_content = redact_text(content)
        return DocumentRevision(
            revision_id=f"document_{secrets.token_hex(10)}", version=version,
            source_type=source_type, source_filename=Path(filename).name or "document.md",
            media_type="application/json" if Path(filename).suffix.lower() == ".json" else "text/plain",
            document_format=document_format.value, content=safe_content,
            content_sha256=hashlib.sha256(safe_content.encode("utf-8")).hexdigest(),
            parent_version=parent_version, status=status,
            validation_result=DocumentValidationResult(
                valid=True, document_format=document_format.value,
                specification_version=profile.specification_version,
                estimated_interface_count=profile.estimated_interface_count,
                secret_risk_detected=profile.secret_risk_detected,
            ),
            change_reason=reason, created_by=actor,
        )

    @staticmethod
    def _initial_envelope(kind: str, items: Any, actor: dict[str, str]) -> dict[str, Any]:
        """构造不落盘的旧任务虚拟 v1，避免只读访问改写历史目录。"""

        return {
            "schema_version": 2, "kind": kind, "version": 1,
            "sha256": canonical_sha256(items), "source_versions": {},
            "created_by": actor["user_id"], "created_at": utc_now(),
            "lifecycle_status": "current", "stale_reason": "", "virtual": True,
            "items": items,
        }

    @staticmethod
    def _build_scope(
        *, version: int, document_version: int, fields: dict[str, Any], actor: dict[str, str],
    ) -> AnalysisScopeVersion:
        allowed = {
            "include_methods", "include_paths", "exclude_paths", "modules", "tags",
            "analyze_request", "analyze_response", "analyze_security", "analyze_errors",
            "analyze_dependencies", "project", "module", "environment",
        }
        scope_payload = {key: value for key, value in fields.items() if key in allowed}
        scope = AnalysisScopeVersion(
            scope_id=f"scope_{secrets.token_hex(10)}", version=version,
            document_version=document_version, created_by=actor, **scope_payload,
        )
        scope.sha256 = canonical_sha256(scope.model_dump(mode="json", exclude={"sha256"}))
        return scope

    def _apply_issue_resolution(
        self, task_id: str, contract: ApiContract, issue: ReviewIssue, action: str,
        reason: str, payload: dict[str, Any], actor: dict[str, str],
    ) -> None:
        value = payload.get("value", issue.current_value)
        issue.current_value = self._field_value(contract, issue.field_path)
        contract.field_evidence = [item for item in contract.field_evidence if item.field_path != issue.field_path]
        if action == "bind_evidence":
            version = int(payload.get("document_version", 0))
            document = DocumentRevision.model_validate(self.versions.load_version(task_id, "documents", version)["items"])
            lines = document.content.splitlines()
            current = self._field_value(contract, issue.field_path)
            ranges = payload.get("ranges") if isinstance(payload.get("ranges"), list) else [{
                "start_line": payload.get("start_line", 0), "end_line": payload.get("end_line", 0),
            }]
            evidence: list[FieldEvidence] = []
            for selected in ranges:
                start_line = int(selected.get("start_line", 0)) if isinstance(selected, dict) else 0
                end_line = int(selected.get("end_line", 0)) if isinstance(selected, dict) else 0
                if start_line < 1 or end_line < start_line or end_line > len(lines):
                    raise ServiceError(422, "EVIDENCE_RANGE_INVALID", "文档依据行号范围不合法")
                quote = "\n".join(lines[start_line - 1:end_line])
                if str(current).lower() not in quote.lower() and not (
                    str(current).lower() == "header" and re.search(r"(?i)(?:-H|header|请求头)", quote)
                ):
                    raise ServiceError(422, "EVIDENCE_RANGE_INVALID", "所选原文不能直接支持当前字段值")
                evidence.append(FieldEvidence(
                    field_path=issue.field_path, value=current, source_type="source_quote",
                    source_pointer=f"document:v{version}:L{start_line}-L{end_line}", quote=quote,
                    evidence_type="explicit", document_version=version,
                    start_line=start_line, end_line=end_line,
                ))
            contract.field_evidence.extend(evidence)
            issue.resolution_type = "bind_evidence"
        elif action in {"edit_field", "human_override"}:
            self._set_field_value(contract, issue.field_path, value)
            contract.field_evidence.append(FieldEvidence(
                field_path=issue.field_path, value=value, source_type="human_override",
                source_pointer=f"review:v{contract.version}", quote=reason,
                evidence_type="explicit",
            ))
            issue.resolution_type = action
        elif action in {"remove_inference", "accept_as_suggestion"}:
            issue.status = "accepted_as_suggestion"
            issue.resolution_reason = reason
            issue.resolved_by = actor
            issue.resolved_at = utc_now()
            return
        issue.status = "resolved"
        issue.resolution_reason = reason
        issue.resolved_by = actor
        issue.resolved_at = utc_now()

    @staticmethod
    def _field_value(contract: ApiContract, field_path: str) -> Any:
        if field_path in {"name", "summary", "method", "path", "auth_conclusion"}:
            return getattr(contract, field_path)
        match = _PARAMETER_PATH.fullmatch(field_path)
        if match and int(match.group(1)) < len(contract.parameters):
            return getattr(contract.parameters[int(match.group(1))], match.group(2))
        match = _RESPONSE_PATH.fullmatch(field_path)
        if match and int(match.group(1)) < len(contract.responses):
            return contract.responses[int(match.group(1))].status_code
        if field_path == "request_body.required" and contract.request_body:
            return contract.request_body.required
        raise ServiceError(422, "REVIEW_FIELD_FORBIDDEN", "该契约字段不允许人工修改")

    @staticmethod
    def _set_field_value(contract: ApiContract, field_path: str, value: Any) -> None:
        if field_path in {"name", "summary", "method", "path"}:
            setattr(contract, field_path, value)
            return
        if field_path == "auth_conclusion":
            normalized = str(value).strip().lower()
            if normalized not in {"none", "required", "optional", "unresolved"}:
                raise ServiceError(
                    422, "REVIEW_PATCH_INVALID",
                    "鉴权结论只能是 none、required、optional 或 unresolved",
                )
            contract.auth_conclusion = normalized
            return
        match = _PARAMETER_PATH.fullmatch(field_path)
        if match and int(match.group(1)) < len(contract.parameters):
            key = match.group(2)
            if key == "required":
                value = DocumentRevisionService._as_boolean(value)
            setattr(contract.parameters[int(match.group(1))], key, value)
            return
        match = _RESPONSE_PATH.fullmatch(field_path)
        if match and int(match.group(1)) < len(contract.responses):
            contract.responses[int(match.group(1))].status_code = str(value)
            return
        if field_path == "request_body.required" and contract.request_body:
            contract.request_body.required = DocumentRevisionService._as_boolean(value)
            return
        raise ServiceError(422, "REVIEW_FIELD_FORBIDDEN", "该契约字段不允许人工修改")

    @staticmethod
    def _as_boolean(value: Any) -> bool:
        """把 Review 表单布尔值做严格转换，拒绝 ``"false"`` 被当成真。"""

        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "是"}:
            return True
        if normalized in {"false", "0", "no", "否"}:
            return False
        raise ServiceError(422, "REVIEW_PATCH_INVALID", "布尔字段只能填写 true 或 false")

    def _append_audit(
        self, task_id: str, action: str, version: int, issue: ReviewIssue,
        actor: dict[str, str],
    ) -> None:
        with self.store.locked():
            path = self.store.task_dir(task_id) / "review-audit.json"
            try:
                audit = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                audit = {"schema_version": 2, "items": []}
            audit["items"].append({
                "action": f"review_issue.{action}", "version": version, **actor,
                "objects": [{"object_id": issue.issue_id, "field_path": issue.field_path}],
                "created_at": utc_now(),
            })
            TaskStore.atomic_write_json(path, audit)

    def append_action_audit(
        self, task_id: str, *, action: str, version: int,
        object_id: str, actor: dict[str, str], field_paths: list[str] | None = None,
    ) -> None:
        """追加不含文档正文、请求响应或 Secret 的版本动作审计。"""

        with self.store.locked():
            path = self.store.task_dir(task_id) / "review-audit.json"
            try:
                audit = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                audit = {"schema_version": 2, "items": []}
            audit["items"].append({
                "action": action, "version": version, **actor,
                "objects": [{"object_id": object_id, "field_paths": field_paths or []}],
                "created_at": utc_now(),
            })
            TaskStore.atomic_write_json(path, audit)
