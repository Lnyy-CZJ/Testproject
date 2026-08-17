"""API 契约与基础用例的版本化人工 Review 服务。"""

from __future__ import annotations

from copy import deepcopy
import secrets
from typing import Any

from agents.api_test.contracts.quality_gate import apply_quality_gate
from services.api_agent.models import ApiContract, BaseTestCase, FieldEvidence, utc_now
from services.api_agent.v2_store import ApiV2Store
from services.common.errors import ServiceError
from services.common.task_store import TaskStore


CONTRACT_EDITABLE_FIELDS = frozenset({
    "name", "summary", "method", "path", "parameters", "request_body",
    "responses", "security", "dependencies", "test_design_suggestions",
})
CASE_EDITABLE_FIELDS = frozenset({
    "name", "objective", "dimension", "risk_level", "preconditions", "steps",
    "expected_results", "disabled_reason",
})


class ApiReviewService:
    """在任务锁内完成 Review 冲突检测、白名单编辑、版本追加和本地审计。"""

    def __init__(self, store: TaskStore):
        self.store = store
        self.versions = ApiV2Store(store)

    def review_contracts(
        self,
        task_id: str,
        *,
        base_version: int,
        changes: list[dict[str, Any]],
        actor: dict[str, str],
    ) -> dict[str, Any]:
        """按契约 ID 执行 edit/confirm/deprecate，并追加新版本。"""

        with self.store.locked():
            current = self.versions.load_version(task_id, "contracts")
            if current["version"] != base_version:
                raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "契约已被其他 Review 更新，请刷新后重试")
            contracts = [ApiContract.model_validate(item) for item in current["items"]]
            by_id = {item.contract_id: item for item in contracts}
            audit_entries = []
            for change in changes:
                contract = by_id.get(str(change.get("contract_id", "")))
                if not contract:
                    raise ServiceError(422, "CONTRACT_NOT_FOUND", "Review 中包含不存在的契约")
                action = str(change.get("action", ""))
                original_status = contract.status
                if action == "edit":
                    patch = change.get("fields")
                    if not isinstance(patch, dict) or not patch:
                        raise ServiceError(422, "REVIEW_PATCH_INVALID", "契约编辑字段不能为空")
                    illegal = set(patch) - CONTRACT_EDITABLE_FIELDS
                    if illegal:
                        raise ServiceError(422, "REVIEW_FIELD_FORBIDDEN", f"字段不可编辑: {sorted(illegal)}")
                    original = contract.model_dump(mode="json", by_alias=True)
                    updated = deepcopy(original)
                    updated.update(patch)
                    updated["field_evidence"] = [
                        item for item in updated.get("field_evidence", [])
                        if not any(
                            item.get("field_path") == field
                            or str(item.get("field_path", "")).startswith(f"{field}[")
                            or str(item.get("field_path", "")).startswith(f"{field}.")
                            for field in patch
                        )
                    ]
                    for issue_field in ("unresolved", "conflict_items", "ambiguity_notes"):
                        updated[issue_field] = [
                            item for item in updated.get(issue_field, [])
                            if not any(
                                item.get("field_path") == field
                                or str(item.get("field_path", "")).startswith(f"{field}[")
                                or str(item.get("field_path", "")).startswith(f"{field}.")
                                for field in patch
                            )
                        ]
                    history = updated.setdefault("change_history", [])
                    for field, value in patch.items():
                        history.append({
                            "field_path": field, "old_value": original.get(field), "new_value": value,
                            "reason": str(change.get("reason", "")), **actor, "changed_at": utc_now(),
                        })
                        updated.setdefault("field_evidence", []).append(FieldEvidence(
                            field_path=field, value=value, source_type="human_override",
                            source_pointer=f"review:v{base_version}", evidence_type="explicit",
                        ).model_dump(mode="json"))
                        if field == "parameters" and isinstance(value, list):
                            for index, parameter in enumerate(value):
                                if not isinstance(parameter, dict):
                                    continue
                                for key in ("name", "location", "required"):
                                    updated["field_evidence"].append(FieldEvidence(
                                        field_path=f"parameters[{index}].{key}", value=parameter.get(key),
                                        source_type="human_override", source_pointer=f"review:v{base_version}",
                                        evidence_type="explicit",
                                    ).model_dump(mode="json"))
                        if field == "responses" and isinstance(value, list):
                            for index, response in enumerate(value):
                                if isinstance(response, dict):
                                    updated["field_evidence"].append(FieldEvidence(
                                        field_path=f"responses[{index}].status_code", value=response.get("status_code"),
                                        source_type="human_override", source_pointer=f"review:v{base_version}",
                                        evidence_type="explicit",
                                    ).model_dump(mode="json"))
                    updated["status"] = "draft"
                    contract = apply_quality_gate(ApiContract.model_validate(updated))
                    by_id[contract.contract_id] = contract
                elif action == "confirm":
                    if not contract.quality_report.hard_gate_passed or contract.status not in {"confirmed_candidate", "confirmed"}:
                        raise ServiceError(409, "CONTRACT_QUALITY_BLOCKED", "存在硬阻断的契约不能确认")
                    contract.status = "confirmed"
                elif action == "deprecate":
                    contract.status = "deprecated"
                elif action == "return":
                    contract.status = "draft"
                    contract.change_history.append({
                        "field_path": "status", "old_value": original_status,
                        "new_value": "draft", "reason": str(change.get("reason", "人工退回")),
                        **actor, "changed_at": utc_now(),
                    })
                else:
                    raise ServiceError(422, "REVIEW_ACTION_UNSUPPORTED", "契约 Review 动作不受支持")
                audit_entries.append({"object_id": contract.contract_id, "action": action})
            ordered = [by_id[item.contract_id] for item in contracts]
            saved = self.versions.save_version(
                task_id, kind="contracts",
                items=[item.model_dump(mode="json", by_alias=True) for item in ordered],
                source_versions={"contracts": base_version}, created_by=actor["user_id"],
            )
            self._append_audit(task_id, "contract_review", saved["version"], actor, audit_entries)
            return saved

    def review_cases(
        self,
        task_id: str,
        *,
        base_version: int,
        changes: list[dict[str, Any]],
        actor: dict[str, str],
        can_approve_high_risk: bool,
    ) -> dict[str, Any]:
        """编辑、确认或禁用基础用例；高风险确认要求额外执行权限。"""

        with self.store.locked():
            current = self.versions.load_version(task_id, "base-cases")
            if current["version"] != base_version:
                raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "用例已被其他 Review 更新，请刷新后重试")
            cases = [BaseTestCase.model_validate(item) for item in current["items"]]
            by_id = {item.case_id: item for item in cases}
            audit_entries = []
            for change in changes:
                action = str(change.get("action", ""))
                if action == "add":
                    fields = change.get("fields") if isinstance(change.get("fields"), dict) else {}
                    illegal = set(fields) - (CASE_EDITABLE_FIELDS | {"contract_id"})
                    if illegal or not fields.get("contract_id"):
                        raise ServiceError(422, "REVIEW_PATCH_INVALID", "新增用例字段不完整或包含受保护字段")
                    case = BaseTestCase.model_validate({
                        "case_id": f"case_{secrets.token_hex(10)}", "source": "human",
                        "status": "draft" if fields.get("risk_level") == "high" else "confirmed_candidate",
                        **fields,
                    })
                    cases.append(case)
                    by_id[case.case_id] = case
                    audit_entries.append({"object_id": case.case_id, "action": action})
                    continue
                case = by_id.get(str(change.get("case_id", "")))
                if not case:
                    raise ServiceError(422, "CASE_NOT_FOUND", "Review 中包含不存在的用例")
                if action == "edit":
                    patch = change.get("fields")
                    if not isinstance(patch, dict) or set(patch) - CASE_EDITABLE_FIELDS:
                        raise ServiceError(422, "REVIEW_FIELD_FORBIDDEN", "用例包含不可编辑字段")
                    updated = case.model_dump(mode="json")
                    for field, value in patch.items():
                        updated.setdefault("change_history", []).append({
                            "field_path": field, "old_value": updated.get(field), "new_value": value,
                            "reason": str(change.get("reason", "")), **actor, "changed_at": utc_now(),
                        })
                        updated[field] = value
                    updated["source"] = "human"
                    updated["status"] = "draft" if updated.get("risk_level") == "high" else "confirmed_candidate"
                    case = BaseTestCase.model_validate(updated)
                    by_id[case.case_id] = case
                elif action == "confirm":
                    if case.risk_level == "high" and not can_approve_high_risk:
                        raise ServiceError(403, "HIGH_RISK_PERMISSION_REQUIRED", "确认高风险用例需要执行权限")
                    if case.status not in {"confirmed_candidate", "draft", "confirmed"}:
                        raise ServiceError(409, "CASE_REVIEW_BLOCKED", "当前用例状态不可确认")
                    case.status = "confirmed"
                elif action == "disable":
                    case.status = "disabled"
                    case.disabled_reason = str(change.get("reason", "")) or "人工禁用"
                else:
                    raise ServiceError(422, "REVIEW_ACTION_UNSUPPORTED", "用例 Review 动作不受支持")
                audit_entries.append({"object_id": case.case_id, "action": action})
            ordered = [by_id[item.case_id] for item in cases]
            saved = self.versions.save_version(
                task_id, kind="base-cases",
                items=[item.model_dump(mode="json") for item in ordered],
                source_versions={**current.get("source_versions", {}), "base-cases": base_version},
                created_by=actor["user_id"],
            )
            self._append_audit(task_id, "case_review", saved["version"], actor, audit_entries)
            return saved

    def _append_audit(
        self, task_id: str, action: str, version: int,
        actor: dict[str, str], objects: list[dict[str, str]],
    ) -> None:
        """只记录对象、动作和版本，不记录文档、请求响应或 Secret。"""

        path = self.store.task_dir(task_id) / "review-audit.json"
        try:
            import json
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"schema_version": 2, "items": []}
        payload["items"].append({
            "action": action, "version": version, **actor, "objects": objects, "created_at": utc_now(),
        })
        TaskStore.atomic_write_json(path, payload)
