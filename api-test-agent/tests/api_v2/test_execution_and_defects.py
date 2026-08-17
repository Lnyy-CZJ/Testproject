"""S1 Mock 报告、慢响应、脱敏和本地 Bug 草稿测试。"""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from services.api_agent.defect_service import DefectDraftService
from services.api_agent.execution_service import MockExecutionService
from services.api_agent.v2_store import ApiV2Store
from services.common.errors import ServiceError
from services.common.task_store import TaskStore, new_task_id
from services.execution_controller.fake_runtime import FakeRuntimeAdapter


def _setup(tmp_path, *, document_sla_ms=None):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "schema_version": 2, "current_versions": {}, "completed_stages": []})
    ApiV2Store(store).save_version(task_id, kind="executable-cases", items=[{
        "executable_case_id": "exec_case_1", "version": 1, "base_case_id": "case_1",
        "contract_id": "contract_1", "name": "登录", "risk_level": "low", "high_risk_approved": False, "document_sla_ms": document_sla_ms, "target_id": "",
        "request": {"method": "POST", "path": "/login", "headers": {}, "query": {}, "body": None},
        "precondition_case_ids": [], "assertions": [], "variables": [], "setup_script": "",
        "teardown_script": "", "validation_status": "ready", "validation_issues": [], "enabled": True,
    }])
    return store, task_id


def _raw_result(duration=3500, status="passed", classification="none"):
    return {
        "case_id": "exec_case_1", "status": status,
        "started_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:04+00:00",
        "duration_ms": duration, "step_results": [],
        "request_summary": {"headers": {"Authorization": "Bearer top-secret"}, "body": {"password": "123456"}},
        "response_summary": {"status_code": 500, "token": "response-secret", "request_id": "req-1"},
        "assertion_results": [], "failure_classification": classification, "error_signature": "assertion failed",
    }


def test_three_independent_slow_runs_and_storage_redaction(tmp_path):
    store, task_id = _setup(tmp_path)
    service = MockExecutionService(store, FakeRuntimeAdapter(), lambda _run, _cases: [_raw_result()])

    runs = [service.execute(
        task_id, confirmation_sha256="confirmed", expected_confirmation_sha256="confirmed",
        actor_id="user_1", environment="test",
    ) for _ in range(3)]

    statuses = []
    for run in runs:
        result = json.loads((store.task_dir(task_id) / "runs" / run.run_id / "case-results.json").read_text())[0]
        statuses.append(result["performance_evaluation"]["status"])
        assert result["request_summary"]["headers"]["Authorization"] == "[REDACTED]"
        assert result["request_summary"]["body"]["password"] == "[REDACTED]"
        assert result["response_summary"]["token"] == "[REDACTED]"
    assert statuses == ["warning", "warning", "performance_candidate"]
    performance_draft = DefectDraftService(store).create(
        task_id, runs[-1].run_id, ["exec_case_1"], actor_id="user_1",
    )
    assert "performance_candidate" in performance_draft.ai_analysis


def test_stale_confirmation_does_not_create_run(tmp_path):
    store, task_id = _setup(tmp_path)
    service = MockExecutionService(store, FakeRuntimeAdapter(), lambda _run, _cases: [])
    with pytest.raises(ServiceError) as error:
        service.execute(
            task_id, confirmation_sha256="old", expected_confirmation_sha256="new",
            actor_id="user_1", environment="test",
        )
    assert error.value.code == "EXECUTION_CONFIRMATION_STALE"
    assert not list((store.task_dir(task_id) / "runs").glob("run_*"))


def test_document_sla_has_priority_over_project_and_environment(tmp_path):
    store, task_id = _setup(tmp_path, document_sla_ms=1000)
    service = MockExecutionService(store, FakeRuntimeAdapter(), lambda _run, _cases: [_raw_result(duration=1500)])
    run = service.execute(
        task_id, confirmation_sha256="confirmed", expected_confirmation_sha256="confirmed",
        actor_id="user_1", environment="test", project_threshold_ms=5000, environment_threshold_ms=6000,
    )
    result = json.loads((store.task_dir(task_id) / "runs" / run.run_id / "case-results.json").read_text())[0]
    assert result["performance_evaluation"]["threshold_ms"] == 1000
    assert result["performance_evaluation"]["threshold_source"] == "document"


def test_fake_executor_can_use_loopback_mock_api_server(tmp_path):
    """S1 只连接进程内 loopback Mock Server，不访问公网、内网或真实目标。"""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"mock failure"}')

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        store, task_id = _setup(tmp_path)

        def result_factory(_run, _cases):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/login", data=b"{}", method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=2)
            except urllib.error.HTTPError as error:
                status_code = error.code
            return [{**_raw_result(status="failed", classification="product_defect_candidate"), "response_summary": {"status_code": status_code}}]

        run = MockExecutionService(store, FakeRuntimeAdapter(), result_factory).execute(
            task_id, confirmation_sha256="confirmed", expected_confirmation_sha256="confirmed",
            actor_id="user_1", environment="test",
        )
        report = json.loads((store.task_dir(task_id) / "runs" / run.run_id / "report.json").read_text())
        assert report["case_results"][0]["response_summary"]["status_code"] == 500
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_local_defect_draft_versions_and_downloads(tmp_path):
    store, task_id = _setup(tmp_path)
    execution = MockExecutionService(
        store, FakeRuntimeAdapter(),
        lambda _run, _cases: [_raw_result(status="failed", classification="product_defect_candidate")],
    )
    run = execution.execute(
        task_id, confirmation_sha256="confirmed", expected_confirmation_sha256="confirmed",
        actor_id="user_1", environment="test",
    )
    drafts = DefectDraftService(store)
    created = drafts.create(task_id, run.run_id, ["exec_case_1"], actor_id="user_1")
    updated = drafts.update(
        task_id, created.draft_id, base_version=1,
        fields={"title": "登录接口返回 500", "actual_result": "服务返回 500"}, actor_id="user_1",
    )
    assert updated.version == 2
    assert drafts.list(task_id)[0].draft_id == created.draft_id
    assert drafts.load(task_id, created.draft_id, 1).title != updated.title
    assert drafts.download(task_id, created.draft_id, "json")[1] == "application/json"
    markdown = drafts.download(task_id, created.draft_id, "markdown")[0].decode()
    assert "# 登录接口返回 500" in markdown
    with pytest.raises(ServiceError) as error:
        drafts.update(task_id, created.draft_id, base_version=1, fields={"title": "stale"}, actor_id="user_2")
    assert error.value.code == "REVIEW_VERSION_CONFLICT"


def test_environment_issue_requires_manual_reason(tmp_path):
    store, task_id = _setup(tmp_path)
    execution = MockExecutionService(
        store, FakeRuntimeAdapter(), lambda _run, _cases: [_raw_result(status="error", classification="environment_blocked")],
    )
    run = execution.execute(
        task_id, confirmation_sha256="confirmed", expected_confirmation_sha256="confirmed",
        actor_id="user_1", environment="test",
    )
    with pytest.raises(ServiceError) as error:
        DefectDraftService(store).create(task_id, run.run_id, ["exec_case_1"], actor_id="user_1")
    assert error.value.code == "DEFECT_REASON_REQUIRED"
    assert execution.load_run(task_id, run.run_id).status == "succeeded"
