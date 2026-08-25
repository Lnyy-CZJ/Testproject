"""V2.1 文档版本、范围、问题闭环和旧任务兼容测试。"""

from __future__ import annotations

import json

from services.api_agent.document_service import DocumentRevisionService
from services.api_agent.models import (
    AnalysisScopeVersion, ApiContract, ContractParameter, FieldEvidence, ResponseDefinition,
    ReviewIssue, SourceTrace,
)
from services.api_agent.v2_store import ApiV2Store
from services.common.task_store import TaskStore, new_task_id


def _legacy_task(tmp_path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    source = """# 退出登录\n\nPOST /api/logout\n\n```bash\ncurl -X POST -H 'X-CSRF-Token: token' /api/logout\n```\n"""
    (task_dir / "input" / "source.md").write_text(source, encoding="utf-8")
    TaskStore.atomic_write_json(task_dir / "request.json", {
        "input_relative_path": "input/source.md", "input_original_name": "接口文档.md",
    })
    store.save({
        "id": task_id, "schema_version": 2, "status": "waiting_contract_review",
        "current_versions": {}, "completed_stages": [], "created_by_user_id": "tester",
    })
    return store, task_id


def test_legacy_document_is_virtual_until_a_revision_is_created(tmp_path) -> None:
    store, task_id = _legacy_task(tmp_path)
    service = DocumentRevisionService(store)
    listed = service.list_documents(task_id)
    assert listed["current_version"] == 1
    assert not list((store.task_dir(task_id) / "versions" / "documents").glob("v*.json"))

    saved = service.create_revision(
        task_id, base_version=1,
        content=service.get_document(task_id, 1)["content"] + "\n响应 204。\n",
        change_reason="补充成功响应", actor={"user_id": "tester", "username": "tester"},
    )
    assert saved["version"] == 2
    assert service.compare(task_id, 1, 2)["lines"]


def test_scope_preview_has_stable_sha_and_preserves_terminal_assets(tmp_path) -> None:
    store, task_id = _legacy_task(tmp_path)
    service = DocumentRevisionService(store)
    service.ensure_initial_versions(task_id, register=True)
    scope = service.save_scope(
        task_id, base_version=1, document_version=1,
        fields={"include_methods": ["post"], "include_paths": ["/api/*"]},
        actor={"user_id": "tester", "username": "tester"}, reason="只分析退出登录",
    )
    first = service.preview_reanalysis(task_id, document_version=1, scope_version=scope["version"])
    second = service.preview_reanalysis(task_id, document_version=1, scope_version=scope["version"])
    assert first["preview_sha256"] == second["preview_sha256"]
    assert first["document_version"] == 1


def test_human_override_resolves_ungrounded_field_and_rechecks_gate(tmp_path) -> None:
    store, task_id = _legacy_task(tmp_path)
    service = DocumentRevisionService(store)
    service.ensure_initial_versions(task_id, register=True)
    issue = ReviewIssue(
        code="UNGROUNDED_FIELD", field_path="parameters[0].required",
        message="字段缺少直接原文依据", severity="blocker", source_pointer="section-001",
    )
    contract = ApiContract(
        contract_id="contract_logout", name="退出登录", method="POST", path="/api/logout",
        parameters=[ContractParameter(name="X-CSRF-Token", location="header", required=False)],
        source_trace=SourceTrace(source_id="doc", section_id="section-001"),
        field_evidence=[
            FieldEvidence(field_path="method", value="POST", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="path", value="/api/logout", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="parameters[0].name", value="X-CSRF-Token", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="parameters[0].location", value="header", source_type="source_quote", source_pointer="section-001"),
        ],
        unresolved=[issue],
    )
    envelope = ApiV2Store(store).save_version(
        task_id, kind="contracts", items=[contract.model_dump(mode="json", by_alias=True)],
    )
    issue_id = service.list_issues(task_id)["items"][0]["issue_id"]
    resolved = service.resolve_issue(
        task_id, issue_id, base_contract_version=envelope["version"],
        action="human_override", reason="接口开发者确认该 Header 非必填",
        payload={"value": False}, actor={"user_id": "tester", "username": "tester"},
    )
    assert resolved["items"][0]["status"] == "confirmed_candidate"
    assert resolved["items"][0]["unresolved"][0]["status"] == "resolved"


def test_human_override_can_resolve_auth_conclusion(tmp_path) -> None:
    """页面提供的鉴权结论人工确认必须能在后端受控落盘，不能出现字段白名单冲突。"""

    store, task_id = _legacy_task(tmp_path)
    service = DocumentRevisionService(store)
    service.ensure_initial_versions(task_id, register=True)
    contract = ApiContract(
        contract_id="contract_health", name="健康检查", method="GET", path="/api/v1/health/live",
        auth_signal_detected=True, auth_conclusion="unresolved",
        source_trace=SourceTrace(source_id="doc", section_id="section-001"),
        field_evidence=[
            FieldEvidence(field_path="method", value="GET", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="path", value="/api/v1/health/live", source_type="source_quote", source_pointer="section-001"),
        ],
        unresolved=[ReviewIssue(
            code="CONTRACT_AUTH_CONCLUSION_MISSING", field_path="auth_conclusion",
            message="鉴权结论未确定", severity="blocker", source_pointer="section-001",
        )],
    )
    envelope = ApiV2Store(store).save_version(
        task_id, kind="contracts", items=[contract.model_dump(mode="json", by_alias=True)],
    )
    issue_id = service.list_issues(task_id)["items"][0]["issue_id"]
    resolved = service.resolve_issue(
        task_id, issue_id, base_contract_version=envelope["version"],
        action="human_override", reason="公开健康探针无需鉴权",
        payload={"value": "none"}, actor={"user_id": "tester", "username": "tester"},
    )
    assert resolved["items"][0]["auth_conclusion"] == "none"
    assert resolved["items"][0]["unresolved"][0]["status"] == "resolved"


def test_issue_can_bind_multiple_complementary_document_ranges(tmp_path) -> None:
    """一次处理可关联多个直接支持同一字段的原文片段。"""

    store, task_id = _legacy_task(tmp_path)
    service = DocumentRevisionService(store)
    service.ensure_initial_versions(task_id, register=True)
    contract = ApiContract(
        contract_id="contract_logout", name="退出登录", method="POST", path="/api/logout",
        source_trace=SourceTrace(source_id="doc", section_id="section-001"),
        field_evidence=[
            FieldEvidence(field_path="method", value="POST", source_type="source_quote", source_pointer="section-001"),
        ],
        unresolved=[ReviewIssue(
            code="UNGROUNDED_FIELD", field_path="path", message="接口路径需要关联原文",
            severity="blocker", source_pointer="section-001",
        )],
    )
    envelope = ApiV2Store(store).save_version(
        task_id, kind="contracts", items=[contract.model_dump(mode="json", by_alias=True)],
    )
    issue_id = service.list_issues(task_id)["items"][0]["issue_id"]

    resolved = service.resolve_issue(
        task_id, issue_id, base_contract_version=envelope["version"], action="bind_evidence",
        reason="接口定义和 Curl 示例共同支持该路径",
        payload={"document_version": 1, "ranges": [
            {"start_line": 3, "end_line": 3}, {"start_line": 6, "end_line": 6},
        ]}, actor={"user_id": "tester", "username": "tester"},
    )

    path_evidence = [item for item in resolved["items"][0]["field_evidence"] if item["field_path"] == "path"]
    assert len(path_evidence) == 2


def test_reanalysis_stale_marker_keeps_old_case_files(tmp_path) -> None:
    store, task_id = _legacy_task(tmp_path)
    versions = ApiV2Store(store)
    first_contract = versions.save_version(task_id, kind="contracts", items=[])
    old_cases = versions.save_version(
        task_id, kind="base-cases", items=[], source_versions={"contracts": first_contract["version"]},
    )
    second_contract = versions.save_version(task_id, kind="contracts", items=[])
    versions.mark_downstream_stale(task_id, contract_version=second_contract["version"], reason="重新分析")
    record = store.load(task_id)
    assert record["stale_versions"][0]["version"] == old_cases["version"]
    assert json.loads((store.task_dir(task_id) / "versions" / "base-cases" / "v1.json").read_text())["items"] == []


def test_analysis_scope_filters_tags_and_selected_content(tmp_path) -> None:
    store, task_id = _legacy_task(tmp_path)
    contract = ApiContract(
        contract_id="contract_logout", name="退出登录", method="POST", path="/api/logout",
        module="认证", tags=["session"],
        parameters=[ContractParameter(name="X-CSRF-Token", location="header")],
        responses=[ResponseDefinition(status_code="200"), ResponseDefinition(status_code="401")],
        source_trace=SourceTrace(source_id="doc", section_id="section-001"),
        field_evidence=[
            FieldEvidence(field_path="method", value="POST", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="path", value="/api/logout", source_type="source_quote", source_pointer="section-001"),
        ],
    )
    scope = AnalysisScopeVersion(
        scope_id="scope_1", version=2, document_version=1,
        include_methods=["post"], modules=["认证"], tags=["session"],
        analyze_request=False, analyze_response=True, analyze_errors=False,
        created_by={"user_id": "tester", "username": "tester"},
    )
    result = DocumentRevisionService(store).filter_contracts([contract], scope)
    assert len(result) == 1
    assert result[0].parameters == []
    assert [item.status_code for item in result[0].responses] == ["200"]
