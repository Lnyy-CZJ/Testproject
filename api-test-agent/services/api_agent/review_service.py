"""API 契约与基础用例的版本化人工 Review 服务。"""

from __future__ import annotations

from copy import deepcopy
import secrets
from typing import Any

from agents.api_test.contracts.quality_gate import apply_quality_gate
from agents.api_test.cases.grounding import assess_case_grounding, contract_evidence_refs
from agents.api_test.cases.executable import validate_executable_cases
from services.api_agent.models import (
    ApiContract, BaseTestCase, CoverageMatrix, ExecutableCase, FieldEvidence, utc_now,
)
from services.api_agent.v2_store import ApiV2Store, canonical_sha256
from services.common.errors import ServiceError
from services.common.task_store import TaskStore


CONTRACT_EDITABLE_FIELDS = frozenset({
    "name", "summary", "method", "path", "parameters", "request_body",
    "responses", "security", "dependencies", "test_design_suggestions",
})
CASE_EDITABLE_FIELDS = frozenset({
    "name", "objective", "dimension", "risk_level", "preconditions", "steps",
    "expected_results", "parameter_mutations", "dependencies", "evidence_refs",
    "scenario_type", "disabled_reason",
})
EXECUTABLE_EDITABLE_FIELDS = frozenset({
    "request", "precondition_case_ids", "assertions", "variables", "variable_producers",
    "variable_consumers", "data_refs", "retry_policy", "failure_policy", "setup_script",
    "teardown_script", "observation_targets",
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
        """编辑、确认或禁用基础用例；调用方负责校验用例 Review 权限。"""

        with self.store.locked():
            current = self.versions.load_version(task_id, "base-cases")
            if current["version"] != base_version:
                raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "用例已被其他 Review 更新，请刷新后重试")
            cases = [BaseTestCase.model_validate(item) for item in current["items"]]
            try:
                contract_envelope = self.versions.load_version(task_id, "contracts")
                contracts = {item.contract_id: item for item in (
                    ApiContract.model_validate(value) for value in contract_envelope["items"]
                )}
            except FileNotFoundError:
                # 旧测试夹具和只读历史任务可能只有用例版本；确认时仍会被契约门禁阻断。
                contracts = {}
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
                        "generation_kernel": "human", "generation_sources": ["human_review"],
                        "status": "draft" if fields.get("risk_level") == "high" else "confirmed_candidate",
                        **fields,
                    })
                    contract = contracts.get(case.contract_id)
                    if contract:
                        case.evidence_refs = case.evidence_refs or contract_evidence_refs(contract)
                        case.quality_report = assess_case_grounding(case, contract)
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
                    updated["generation_kernel"] = "human"
                    updated["generation_sources"] = ["human_review"]
                    updated["status"] = "draft" if updated.get("risk_level") == "high" else "confirmed_candidate"
                    case = BaseTestCase.model_validate(updated)
                    contract = contracts.get(case.contract_id)
                    if contract:
                        case.evidence_refs = case.evidence_refs or contract_evidence_refs(contract)
                        case.quality_report = assess_case_grounding(case, contract)
                    by_id[case.case_id] = case
                elif action == "confirm":
                    if case.risk_level == "high" and not can_approve_high_risk:
                        raise ServiceError(403, "HIGH_RISK_PERMISSION_REQUIRED", "当前角色不能确认高风险用例")
                    if case.status not in {"confirmed_candidate", "draft", "confirmed"}:
                        raise ServiceError(409, "CASE_REVIEW_BLOCKED", "当前用例状态不可确认")
                    contract = contracts.get(case.contract_id)
                    if contracts and not contract:
                        raise ServiceError(409, "CASE_REVIEW_BLOCKED", "关联契约不存在或未确认")
                    if contract:
                        case.evidence_refs = case.evidence_refs or contract_evidence_refs(contract)
                        case.quality_report = assess_case_grounding(case, contract)
                        if not case.quality_report.hard_gate_passed:
                            raise ServiceError(409, "CASE_GROUNDING_FAILED", "用例 Grounding 未通过，不能确认")
                    case.status = "confirmed"
                    if case.risk_level == "high":
                        case.high_risk_confirmed_by = actor
                        case.high_risk_confirmed_at = utc_now()
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
            self.versions.mark_base_case_downstream_stale_locked(
                task_id, reason="基础用例 Review 产生新版本",
            )
            self._append_audit(task_id, "case_review", saved["version"], actor, audit_entries)
            return saved

    def case_confirmation_preview(self, task_id: str) -> dict[str, Any]:
        """生成一键确认的稳定摘要和 SHA。

        SHA 覆盖基础用例版本、候选集合、跳过原因、高风险集合和当前契约版本。
        浏览器确认后若任一输入发生变化，写请求会以版本冲突拒绝，避免确认到刷新后的
        另一批用例。
        """

        current = self.versions.load_version(task_id, "base-cases")
        record = self.store.load(task_id) or {}
        candidates: list[str] = []
        high_risk: list[str] = []
        skipped: list[dict[str, str]] = []
        for case in (BaseTestCase.model_validate(item) for item in current["items"]):
            if case.status not in {"draft", "confirmed_candidate", "confirmed"}:
                skipped.append({"case_id": case.case_id, "code": "CASE_REVIEW_BLOCKED"})
                continue
            if case.quality_report.blockers:
                skipped.append({"case_id": case.case_id, "code": "CASE_GROUNDING_FAILED"})
                continue
            candidates.append(case.case_id)
            if case.risk_level == "high":
                high_risk.append(case.case_id)
        summary = {
            "base_version": int(current["version"]),
            "base_sha256": str(current["sha256"]),
            "contract_version": int(
                record.get("current_versions", {}).get("contracts", {}).get("version", 0) or 0
            ),
            "candidate_ids": sorted(candidates),
            "high_risk_ids": sorted(high_risk),
            "skipped": sorted(skipped, key=lambda item: item["case_id"]),
        }
        summary["confirmation_sha256"] = canonical_sha256(summary)
        return summary

    def confirm_all_cases(
        self,
        task_id: str,
        *,
        base_version: int,
        confirmation_sha256: str,
        reason: str,
        actor: dict[str, str],
        can_approve_high_risk: bool,
    ) -> dict[str, Any]:
        """确认当前版本中所有可确认用例，并返回明确的跳过清单。

        本方法复用逐条 Review 的 Grounding、权限和审计逻辑。不可确认项不会被改写，
        也不会因批量操作绕过质量门禁。
        """

        if not reason.strip():
            raise ServiceError(422, "REVIEW_PATCH_INVALID", "一键确认必须填写原因")
        preview = self.case_confirmation_preview(task_id)
        if base_version != preview["base_version"] or confirmation_sha256 != preview["confirmation_sha256"]:
            raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "用例确认摘要已失效，请刷新后重试")
        if preview["high_risk_ids"] and not can_approve_high_risk:
            raise ServiceError(403, "HIGH_RISK_PERMISSION_REQUIRED", "当前角色不能确认高风险用例")
        if not preview["candidate_ids"]:
            raise ServiceError(409, "CASE_REVIEW_BLOCKED", "没有可确认的基础用例")
        saved = self.review_cases(
            task_id,
            base_version=base_version,
            changes=[
                {"case_id": case_id, "action": "confirm", "reason": reason.strip()}
                for case_id in preview["candidate_ids"]
            ],
            actor=actor,
            can_approve_high_risk=can_approve_high_risk,
        )
        return {
            **saved,
            "confirmed_case_ids": preview["candidate_ids"],
            "skipped": preview["skipped"],
            "high_risk_case_ids": preview["high_risk_ids"],
            "confirmation_sha256": preview["confirmation_sha256"],
        }

    def review_executable_cases(
        self,
        task_id: str,
        *,
        base_version: int,
        changes: list[dict[str, Any]],
        actor: dict[str, str],
    ) -> dict[str, Any]:
        """编辑、确认或禁用执行定义，并在编辑后重新运行静态安全门禁。"""

        with self.store.locked():
            current = self.versions.load_version(task_id, "executable-cases")
            if int(current["version"]) != base_version:
                raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "执行定义已更新，请刷新后重试")
            cases = [ExecutableCase.model_validate(item) for item in current["items"]]
            by_id = {item.executable_case_id: item for item in cases}
            try:
                contracts = [
                    ApiContract.model_validate(item)
                    for item in self.versions.load_version(task_id, "contracts")["items"]
                ]
            except FileNotFoundError:
                contracts = []
            audit_entries: list[dict[str, str]] = []
            for change in changes:
                case_id = str(change.get("executable_case_id", ""))
                case = by_id.get(case_id)
                if case is None:
                    raise ServiceError(422, "EXECUTABLE_CASE_NOT_FOUND", "执行定义不存在")
                action = str(change.get("action", ""))
                if action == "edit":
                    patch = change.get("fields")
                    if not isinstance(patch, dict) or not patch or set(patch) - EXECUTABLE_EDITABLE_FIELDS:
                        raise ServiceError(422, "REVIEW_FIELD_FORBIDDEN", "执行定义包含不可编辑字段")
                    updated = case.model_dump(mode="json")
                    updated.update(patch)
                    updated.update({
                        "review_status": "confirmed_candidate",
                        "generation_kernel": "human",
                        "generation_sources": ["human_review"],
                        "validation_issues": [],
                    })
                    candidate = ExecutableCase.model_validate(updated)
                    case = validate_executable_cases([candidate], contracts)[0] if contracts else candidate
                    case.enabled = case.validation_status == "ready"
                    by_id[case_id] = case
                elif action == "confirm":
                    if case.validation_status != "ready" or not case.enabled:
                        raise ServiceError(409, "EXECUTABLE_CASE_NOT_READY", "静态校验未通过的执行定义不能确认")
                    case.review_status = "confirmed"
                elif action == "disable":
                    case.review_status = "disabled"
                    case.validation_status = "disabled"
                    case.enabled = False
                else:
                    raise ServiceError(422, "REVIEW_ACTION_UNSUPPORTED", "执行定义 Review 动作不受支持")
                audit_entries.append({"object_id": case_id, "action": action})
            ordered = [by_id[item.executable_case_id] for item in cases]
            saved = self.versions.save_version(
                task_id, kind="executable-cases",
                items=[item.model_dump(mode="json") for item in ordered],
                source_versions={**current.get("source_versions", {}), "executable-cases": base_version},
                created_by=actor["user_id"], artifact_schema_version=3,
            )
            self._append_audit(task_id, "executable_review", saved["version"], actor, audit_entries)
            self.versions.mark_execution_plans_stale(
                task_id, executable_version=int(saved["version"]), reason="执行定义 Review 产生新版本",
            )
            return saved

    def accept_coverage_gaps(
        self, task_id: str, *, base_version: int, gap_ids: list[str],
        reason: str, actor: dict[str, str],
    ) -> dict[str, Any]:
        """接受明确选择的覆盖缺口并保留理由；不伪造为已覆盖。"""

        if not gap_ids or not reason.strip():
            raise ServiceError(422, "REVIEW_PATCH_INVALID", "接受覆盖缺口必须选择缺口并填写理由")
        with self.store.locked():
            current = self.versions.load_version(task_id, "coverage")
            if int(current["version"]) != base_version:
                raise ServiceError(409, "REVIEW_VERSION_CONFLICT", "覆盖矩阵已更新，请刷新后重试")
            matrix = CoverageMatrix.model_validate(current["items"])
            available = {item.coverage_id for item in matrix.items if item.required and not item.covered}
            requested = list(dict.fromkeys(str(item) for item in gap_ids))
            if any(item not in available for item in requested):
                raise ServiceError(422, "REVIEW_PATCH_INVALID", "包含不存在或已覆盖的缺口")
            matrix.accepted_gap_ids = list(dict.fromkeys([*matrix.accepted_gap_ids, *requested]))
            matrix.partial_success = any(
                item.required and not item.covered and item.coverage_id not in matrix.accepted_gap_ids
                for item in matrix.items
            )
            saved = self.versions.save_version(
                task_id, kind="coverage", items=matrix.model_dump(mode="json"),
                source_versions={**current.get("source_versions", {}), "coverage": base_version},
                created_by=actor["user_id"],
            )
            self._append_audit(
                task_id, "coverage_gap_accept", saved["version"], actor,
                [{"object_id": item, "action": "accept_gap", "reason": reason.strip()} for item in requested],
            )
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
