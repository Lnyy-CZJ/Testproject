"""API 智能体独立 Web 服务的身份、所有权和执行门禁测试。"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

from services.api_agent.app import create_app
from services.api_agent.execution_config import ExecutionTarget
from services.api_agent.execution_service import MockExecutionService
from services.api_agent.models import ApiContract, BaseTestCase, ContractParameter, FieldEvidence, ModelUsageRecord, ReviewIssue, SourceTrace, StageEvent
from services.api_agent.stage_events import StageEventStore
from services.api_agent.v2_store import ApiV2Store
from services.common.config import ServiceSettings
from services.common.errors import ServiceError
from services.common.task_models import utc_now
from services.execution_controller.fake_runtime import FakeRuntimeAdapter


class FakePlatformClient:
    """提供不读取 Token 和网络的最小平台配置。"""

    def __init__(self) -> None:
        self.planned: list[tuple[str, str, str]] = []
        self.snapshot = {
            "tool_id": "api-test-agent",
            "environment": "dev",
            "release_id": "rel_api_test",
            "release_version": 2,
            "normal": {
                "QUEUE_MAX_WAITING": 5,
                "UPLOAD_MAX_BYTES": 5 * 1024 * 1024,
                "UPLOAD_MAX_CHARACTERS": 500_000,
                "DATABASE_PERSIST_ENABLED": False,
            },
            "secrets": {"LLM_API_KEY": "sentinel"},
            "configured_secret_keys": ["LLM_API_KEY"],
        }

    def runtime_config(self, *, include_secrets: bool, llm_capability=None):
        """返回与参数兼容的隔离配置快照。"""

        return self.snapshot

    def resource_access_check(self, resource_context: str, *, action: str, root_resource_id: str | None = None) -> dict:
        """模拟平台签名资源上下文的服务端核验，不信任浏览器身份字段。"""

        _prefix, user_id, data_scope, project_id, managed = resource_context.split("|", 4)
        return {
            "allowed": True, "user_id": user_id, "username": user_id,
            "display_name": user_id, "data_scope": data_scope,
            "managed_project_ids": [item for item in managed.split(",") if item],
            "action": action, "root_resource_id": root_resource_id,
            "access_scope_snapshot": "public" if project_id == "-" else "project",
            "project_id_snapshot": None if project_id == "-" else project_id,
            "authorization_source_snapshot": "project_member",
        }

    def plan_runtime_config(
        self,
        signed_user_context: str,
        *,
        resource_type: str,
        resource_id: str,
        llm_capability: str = "default",
        resource_context: str | None = None,
    ) -> dict:
        """模拟兑换并返回不含 Secret 的任务选择器。"""

        self.planned.append((signed_user_context, resource_type, resource_id))
        return {
            "runtime_context_id": "rtx_api_user_1",
            "runtime_context_expires_at": "2026-08-24T12:00:00Z",
            "snapshot_selector": {
                "release_id": "rel_api_test",
                "credential_versions": {},
            },
            "release_id": "rel_api_test",
            "release_version": 2,
        }

    def materialize_runtime_config(self, _runtime_metadata: dict) -> dict:
        """返回仅供子进程内存使用的测试快照。"""

        return self.snapshot

    def audit(self, _event):
        """测试中不向平台发送审计事件。"""

        return None


class FakeManager:
    """同步保存任务的 API 路由测试调度器。"""

    def __init__(self, store) -> None:
        self.store = store

    def assert_capacity(self, _limit) -> None:
        return None

    def submit(self, record, payload, *, max_waiting=None):
        record.update({"schema_version": 2, "current_versions": {}, "completed_stages": []})
        self.store.atomic_write_json(self.store.task_dir(record["id"]) / "request.json", payload)
        self.store.save(record)
        return record

    def cancel(self, task_id):
        record = self.store.load(task_id)
        record.update({"status": "cancelled", "stage": "cancelled", "finished_at": utc_now()})
        self.store.save(record)
        return record

    def enqueue_stage(self, *_args, **_kwargs):
        raise ServiceError(409, "INVALID_TASK_STATE", "测试任务未进入 Review")


def headers(
    user: str = "user_1",
    permissions: str = "tool.view,tool.execute,tool.result.view,task.cancel",
    *,
    scope: str = "own",
    project_id: str = "project",
    managed_projects: tuple[str, ...] = (),
) -> dict[str, str]:
    """构造经过网关签发的可信身份头。"""

    return {
        "X-Platform-User-ID": user,
        "X-Platform-Username": user,
        "X-Platform-Display-Name": user,
        "X-Platform-Permissions": permissions,
        "X-Platform-User-Context": f"signed-context-for-{user}",
        "X-Platform-Resource-Context": f"resource|{user}|{scope}|{project_id}|{','.join(managed_projects)}",
        "X-CSRF-Token": "csrf",
    }


def make_client(tmp_path: Path):
    """创建只使用临时任务目录的 API 测试 Client。"""

    settings = ServiceSettings(
        tool_id="api-test-agent",
        agent_type="api",
        base_path="/api-test-agent",
        host="127.0.0.1",
        port=5005,
        data_dir=tmp_path / "api",
        platform_api_url="http://unused",
        platform_client_token_file=tmp_path / "unused",
        runtime_environment="dev",
        platform_home_url="/",
        app_revision="api-test-revision",
    )
    platform = FakePlatformClient()
    app = create_app(
        settings=settings,
        platform_client=platform,
        safe_config_loader=lambda: platform.runtime_config(include_secrets=False),
        manager_factory=lambda store, _loader: FakeManager(store),
    )
    app.config["TESTING"] = True
    client = app.test_client()
    client.set_cookie("tp_csrf", "csrf")
    return client, app


def test_create_owner_admin_and_version_visibility(tmp_path: Path) -> None:
    """创建者和管理员可见任务，其他普通用户收到统一 404。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks",
        headers=headers(),
        data={
            "operation": "generate_api_cases",
            "project_name": "项目 A",
            "module_name": "登录",
            "environment": "dev",
            "document_file": (io.BytesIO(b"openapi: 3.0.0\npaths: {}"), "openapi.yaml"),
        },
        content_type="multipart/form-data",
    )
    assert created.status_code == 202
    task = created.get_json()
    assert task["schema_version"] == 2
    assert task["app_revision"] == "api-test-revision"
    assert "internal" not in task
    record = app.extensions["task_store"].load(task["id"])
    assert record["internal"]["runtime_context_id"] == "rtx_api_user_1"
    assert record["internal"]["snapshot_selector"]["release_id"] == "rel_api_test"
    assert "signed-context-for-user_1" not in json.dumps(record, ensure_ascii=False)
    assert app.extensions["platform_client"].planned == [
        ("signed-context-for-user_1", "task", task["id"])
    ]
    path = f"/api-test-agent/api/v1/tasks/{task['id']}"
    assert client.get(path, headers=headers()).status_code == 200
    assert client.get(path, headers=headers("other")).status_code == 404
    assert client.get(path, headers=headers("admin", "tool.result.view,task.view.all", scope="global")).status_code == 200


def test_browser_task_view_all_cannot_bypass_owner_isolation(tmp_path: Path) -> None:
    """浏览器自报旧全局任务权限不能让 tester 读取或取消他人任务。"""

    client, _app = make_client(tmp_path)
    base = "/api-test-agent/api/v1/tasks"
    created = client.post(
        base,
        headers=headers("tester_a"),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A", "module_name": "登录",
            "environment": "dev", "document_file": (io.BytesIO(b"openapi: 3.0.0\npaths: {}"), "api.yaml"),
        },
        content_type="multipart/form-data",
    )
    assert created.status_code == 202
    task_id = created.get_json()["id"]
    forged = headers("tester_b", "tool.result.view,task.cancel,task.view.all")
    assert client.get(base, headers=forged).get_json()["items"] == []
    missing = client.get(f"{base}/missing", headers=forged)
    for suffix in ("", "/logs", "/artifacts"):
        actual = client.get(f"{base}/{task_id}{suffix}", headers=forged)
        assert actual.status_code == 404
        assert actual.get_json()["error"]["code"] == missing.get_json()["error"]["code"]
    assert client.post(f"{base}/{task_id}/cancel", headers=forged).status_code == 404


def test_platform_scopes_keep_review_retry_and_download_bound_to_root_task(tmp_path: Path) -> None:
    """manager/global 可读项目快照，extra grant admin 仍不能读取或重试他人任务。"""

    client, app = make_client(tmp_path)
    base = "/api-test-agent/api/v1/tasks"

    def create(owner: str) -> str:
        response = client.post(
            base, headers=headers(owner),
            data={
                "operation": "generate_api_cases", "project_name": "项目 A", "module_name": owner,
                "environment": "dev", "document_file": (io.BytesIO(b"openapi: 3.0.0\npaths: {}"), "api.yaml"),
            }, content_type="multipart/form-data",
        )
        assert response.status_code == 202
        return response.get_json()["id"]

    task_a, task_b, task_extra = create("tester_a"), create("tester_b"), create("extra_admin")
    manager = headers("manager", "tool.result.view", scope="project", managed_projects=("project",))
    global_admin = headers("platform_admin", "tool.result.view", scope="global")
    extra_grant = headers("extra_admin", "tool.result.view,tool.execute,task.cancel", scope="own")
    assert {item["id"] for item in client.get(base, headers=manager).get_json()["items"]} == {task_a, task_b, task_extra}
    assert {item["id"] for item in client.get(base, headers=global_admin).get_json()["items"]} == {task_a, task_b, task_extra}
    assert [item["id"] for item in client.get(base, headers=extra_grant).get_json()["items"]] == [task_extra]

    record = app.extensions["task_store"].load(task_a)
    record.update({"status": "failed", "stage": "failed"})
    app.extensions["task_store"].save(record)
    # API V2 Review、重试和下载均经 Blueprint 的 root task context，不接受派生 ID 直达。
    assert client.get(f"{base}/{task_a}/contracts", headers=extra_grant).status_code == 404
    assert client.post(f"{base}/{task_a}/retry", headers=extra_grant).status_code == 404
    assert client.get(f"{base}/{task_a}/artifacts/unknown", headers=extra_grant).status_code == 404


def test_csrf_and_execution_are_fail_closed(tmp_path: Path) -> None:
    """写请求要求双提交 CSRF，真实执行关闭时不创建 Run。"""

    client, app = make_client(tmp_path)
    wrong = headers()
    wrong["X-CSRF-Token"] = "wrong"
    assert client.post("/api-test-agent/api/v1/tasks", headers=wrong, data={}).status_code == 403
    created = client.post(
        "/api-test-agent/api/v1/tasks",
        headers=headers(),
        data={
            "operation": "parse_api_document",
            "project_name": "A",
            "module_name": "B",
            "environment": "dev",
            "document_file": (io.BytesIO(b"{}"), "api.json"),
        },
        content_type="multipart/form-data",
    ).get_json()
    execute_headers = headers(permissions="tool.execute,tool.result.view,api-test-agent.execute")
    response = client.post(f"/api-test-agent/api/v1/tasks/{created['id']}/execute", headers=execute_headers)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "EXECUTION_NOT_READY"
    runs = app.extensions["task_store"].task_dir(created["id"]) / "runs"
    assert not runs.exists() or not list(runs.glob("run_*"))


def test_health_readiness_and_api_workbench(tmp_path: Path) -> None:
    """健康检查无需身份，受保护就绪页和工作台展示独立版本。"""

    client, _app = make_client(tmp_path)
    assert client.get("/health").get_json() == {
        "service": "api-test-agent", "status": "ok", "version": "unknown",
        "revision": "api-test-revision", "dirty": True, "runtime_environment": "dev",
        "content_sha256": "unknown",
    }
    assert client.get("/api-test-agent/").status_code == 401
    readiness = client.get("/api-test-agent/api/v1/readiness", headers=headers(permissions="tool.view"))
    assert readiness.status_code == 200
    assert readiness.get_json()["api_execution_enabled"] is False
    page = client.get("/api-test-agent/", headers=headers())
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "API 测试智能体" in html and "api-v2-workbench.css" in html
    assert "创建 API 测试任务" in html
    assert "task-create-dialog" in html


def test_api_review_status_marks_empty_runner_log_complete(tmp_path: Path) -> None:
    """API Review/准备态已结束当前 Runner，空日志不得持续显示为启动中。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks",
        headers=headers(),
        data={
            "operation": "parse_api_document",
            "project_name": "A",
            "module_name": "B",
            "environment": "dev",
            "document_file": (io.BytesIO(b"{}"), "api.json"),
        },
        content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "partial_success", "stage": "execution_ready"})
    store.save(record)

    response = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/logs",
        headers=headers(),
    )

    assert response.status_code == 200
    assert response.get_json()["complete"] is True


def test_task_page_exposes_stage_workspace(tmp_path: Path) -> None:
    """详情页按阶段展示工作区，并提供受控执行确认弹窗。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks",
        headers=headers(),
        data={
            "operation": "generate_api_cases",
            "project_name": "项目 A",
            "module_name": "登录",
            "environment": "dev",
            "document_text": "GET /api/v1/me",
        },
        content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "failed", "stage": "api_v2", "completed_stages": ["contracts"]})
    store.save(record)
    page = client.get(f"/api-test-agent/tasks/{created['id']}", headers=headers())
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "确认分析范围" in html
    assert "coverage-matrix" in html
    assert "execution-confirm-dialog" in html
    assert "run-report" in html
    assert "executable-case-review" in html
    assert "execution-plan-review" in html
    assert "完整请求与静态校验" in html
    assert "依赖拓扑与变量流" in html
    assert "document-revision-dialog" in html
    assert "review-issue-dialog" in html
    assert "文档依据与确认项" in html
    assert 'data-completed-stages="contracts"' in html
    assert "契约事实与 Evidence" not in html
    assert "关键字段必须有 Evidence" not in html
    assert "stage-level-filter" in html and "usage-group" in html
    assert "确认全部候选" in html and "case-bulk-confirm-dialog" in html
    assert '<details class="generation-provenance-details">' in html
    assert '<details class="usage-details">' in html
    script = client.get("/api-test-agent/static/api-v2-workbench.js").get_data(as_text=True)
    assert "输出 / 总 Token" not in script
    assert "输入 Token" in script and "输出 Token" in script and "总 Token" in script
    assert "<h4>文档依据与质量门禁</h4>" in script
    assert '"依据校验已通过"' in script and '"依据校验未通过"' in script
    assert "暂无文档依据" in script
    assert "<h4>Evidence 与质量门禁</h4>" not in script


def test_case_confirm_all_endpoint_binds_current_version_and_returns_skips(tmp_path: Path) -> None:
    """一键确认接口必须使用服务端预览 SHA，且禁用项仍清晰返回。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /login",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "waiting_case_review", "stage": "case_review"})
    store.save(record)
    cases = [
        BaseTestCase(
            case_id="case_ready", contract_id="contract_login", name="正常登录",
            objective="验证登录", dimension="normal", source="deterministic",
            status="confirmed_candidate",
        ).model_dump(mode="json"),
        BaseTestCase(
            case_id="case_disabled", contract_id="contract_login", name="禁用候选",
            objective="不执行", dimension="negative", source="deterministic", status="disabled",
        ).model_dump(mode="json"),
    ]
    ApiV2Store(store).save_version(created["id"], kind="base-cases", items=cases)
    permission_headers = headers(permissions="tool.result.view,api-test-agent.case.review")

    preview = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases/confirmation-preview",
        headers=permission_headers,
    )
    assert preview.status_code == 200
    payload = preview.get_json()
    confirmed = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases/confirm-all",
        headers=permission_headers,
        json={
            "base_version": payload["base_version"],
            "confirmation_sha256": payload["confirmation_sha256"],
            "reason": "测试人员批量复核",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["confirmed_case_ids"] == ["case_ready"]
    assert confirmed.get_json()["skipped"] == [
        {"case_id": "case_disabled", "code": "CASE_REVIEW_BLOCKED"},
    ]


def test_confirm_and_generate_executable_confirms_then_creates_attempt_without_run(tmp_path: Path) -> None:
    """组合动作只创建阶段三 Attempt，不得越过阶段四创建 Run。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /login",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "waiting_case_review", "stage": "case_review"})
    store.save(record)
    ApiV2Store(store).save_version(
        created["id"], kind="contracts", items=[],
    )
    ApiV2Store(store).save_version(
        created["id"], kind="base-cases", items=[BaseTestCase(
            case_id="case_ready", contract_id="contract_login", name="正常登录",
            objective="验证登录", dimension="normal", source="deterministic",
            status="confirmed_candidate",
        ).model_dump(mode="json")], source_versions={"contracts": 1},
    )
    queued_calls = []

    def enqueue_stage(task_id, **kwargs):
        queued_calls.append(kwargs)
        latest = store.load(task_id)
        latest.update({
            "status": "pending", "stage": "executable_generation_queued",
            "current_attempt_id": "attempt_exec_1",
        })
        latest.setdefault("stage_idempotency_keys", {})[
            f"executable_generation:{kwargs['idempotency_key']}"
        ] = "attempt_exec_1"
        store.save(latest)
        return latest

    app.extensions["task_manager"].enqueue_stage = enqueue_stage
    permissions = headers(permissions=(
        "tool.result.view,api-test-agent.case.review,api-test-agent.executable.generate"
    ))
    preview = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases/confirmation-preview",
        headers=permissions,
    ).get_json()
    response = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases/confirm-and-generate-executable",
        headers=permissions,
        json={
            "base_version": preview["base_version"],
            "confirmation_sha256": preview["confirmation_sha256"],
            "idempotency_key": "confirm-exec-001", "reason": "基础用例已复核",
        },
    )

    assert response.status_code == 202
    assert queued_calls[0]["from_stage"] == "executable_generation"
    assert queued_calls[0]["source_versions"]["base-cases"] == 2
    repeated = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases/confirm-and-generate-executable",
        headers=permissions,
        json={
            "base_version": preview["base_version"],
            "confirmation_sha256": preview["confirmation_sha256"],
            "idempotency_key": "confirm-exec-001", "reason": "浏览器重复提交",
        },
    )
    assert repeated.status_code == 202
    assert len(queued_calls) == 1
    runs_dir = store.task_dir(created["id"]) / "runs"
    assert not runs_dir.exists() or not list(runs_dir.glob("run_*"))


def test_execution_plan_preview_create_get_and_confirm(tmp_path: Path) -> None:
    """执行计划 API 必须在创建 Run 前完成确定性编译、版本化和独立确认。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "GET /health",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "waiting_executable_review", "stage": "executable_review"})
    store.save(record)
    executable = ApiV2Store(store).save_version(
        created["id"], kind="executable-cases", items=[{
            "executable_case_id": "exec_health", "validation_status": "ready",
            "review_status": "confirmed", "enabled": True, "lifecycle_status": "current",
            "risk_level": "low", "request": {
                "method": "POST", "path": "/health",
                "headers": {"Authorization": "Bearer {{token}}"},
            },
            "precondition_case_ids": [], "variable_producers": [], "variable_consumers": [],
            "assertions": [{"operator": "status_code", "expected": 200}],
            "retry_policy": {"max_retries": 0},
        }],
    )
    app.extensions["api_execution_targets"] = {
        "local-api": ExecutionTarget(
            target_id="local-api", environment="dev", internal_base_url="http://mock-api:8080",
            masked_base_url="http://mock-api:***", allow_write_methods=True,
        ),
    }
    permission_headers = headers(permissions=(
        "tool.result.view,api-test-agent.executable.review,api-test-agent.execute"
    ))
    public_cases = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/executable-cases",
        headers=permission_headers,
    ).get_json()
    assert public_cases["items"][0]["request"]["headers"]["Authorization"] == "[REDACTED]"
    preview = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execution-plans/preview",
        headers=permission_headers,
        json={"executable_version": executable["version"], "target_id": "local-api"},
    )
    assert preview.status_code == 200
    assert preview.get_json()["stage_state"] == "ready"

    created_plan = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execution-plans",
        headers=permission_headers,
        json={
            "executable_version": executable["version"], "target_id": "local-api",
            "idempotency_key": "plan-001", "reason": "执行定义已复核",
        },
    )
    assert created_plan.status_code == 201
    plan = created_plan.get_json()["items"]
    assert plan["nodes"][0]["write_operation"] is True
    refresh_preview = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execute/preview",
        headers=permission_headers,
    )
    assert refresh_preview.get_json()["plan_id"] == plan["plan_id"]
    assert refresh_preview.get_json()["plan_status"] == "ready"
    fetched = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execution-plans/{plan['plan_id']}",
        headers=permission_headers,
    )
    assert fetched.status_code == 200
    assert fetched.get_json()["items"]["nodes"][0]["request"]["headers"]["Authorization"] == "[REDACTED]"
    confirmed = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execution-plans/{plan['plan_id']}/confirm",
        headers=permission_headers,
        json={
            "plan_version": created_plan.get_json()["version"],
            "confirmation_sha256": plan["confirmation_sha256"], "reason": "允许本机测试执行",
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["items"]["status"] == "confirmed"
    app.extensions["api_fake_execution_service"] = MockExecutionService(
        store, FakeRuntimeAdapter(), lambda _run, _cases: [{
            "case_id": "exec_health", "status": "passed",
            "started_at": "2026-08-21T00:00:00+00:00",
            "finished_at": "2026-08-21T00:00:00+00:00", "duration_ms": 12,
            "step_results": [], "request_summary": {"path": "/health"},
            "response_summary": {"status_code": 200}, "assertion_results": [],
            "failure_classification": "none", "error_signature": "",
        }],
    )
    # 计划确认后撤销写权限时，初次 Run 与 retry 都必须复用同一套当前配置门禁。
    app.extensions["api_execution_targets"]["local-api"] = ExecutionTarget(
        target_id="local-api", environment="dev", internal_base_url="http://mock-api:8080",
        masked_base_url="http://mock-api:***", allow_write_methods=False,
    )
    write_blocked = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execution-plans/{plan['plan_id']}/runs",
        headers=permission_headers,
        json={"confirmation_sha256": plan["confirmation_sha256"]},
    )
    assert write_blocked.status_code == 403
    assert write_blocked.get_json()["error"]["code"] == "EXECUTION_TARGET_WRITE_DENIED"
    app.extensions["api_execution_targets"]["local-api"] = ExecutionTarget(
        target_id="local-api", environment="dev", internal_base_url="http://mock-api:8080",
        masked_base_url="http://mock-api:***", allow_write_methods=True,
    )
    run_response = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/execution-plans/{plan['plan_id']}/runs",
        headers=permission_headers,
        json={"confirmation_sha256": plan["confirmation_sha256"]},
    )
    assert run_response.status_code == 202
    run = run_response.get_json()
    assert run["execution_plan_id"] == plan["plan_id"]
    input_payload = json.loads(
        (store.task_dir(created["id"]) / "runs" / run["run_id"] / "input.json").read_text()
    )
    assert "cases" not in input_payload and input_payload["plan"]["plan_id"] == plan["plan_id"]
    steps = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/runs/{run['run_id']}/steps",
        headers=permission_headers,
    )
    assert steps.status_code == 200
    assert steps.get_json()["items"][0]["node_id"] == "exec_health"

    # 非测试部署即使 Controller 已配置，也必须服从真实执行总开关。
    original_testing = app.config["TESTING"]
    app.config["TESTING"] = False
    app.extensions["api_real_execution_service"] = app.extensions["api_fake_execution_service"]
    app.extensions["api_execution_enabled"] = False
    blocked_retry = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/runs/{run['run_id']}/retry",
        headers=permission_headers,
    )
    assert blocked_retry.status_code == 403
    assert blocked_retry.get_json()["error"]["code"] == "EXECUTION_NOT_READY"
    app.config["TESTING"] = original_testing

    app.extensions["api_execution_targets"]["local-api"] = ExecutionTarget(
        target_id="local-api", environment="dev", internal_base_url="http://mock-api:8080",
        masked_base_url="http://mock-api:***", allow_write_methods=False,
    )
    blocked_write_retry = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/runs/{run['run_id']}/retry",
        headers=permission_headers,
    )
    assert blocked_write_retry.status_code == 403
    assert blocked_write_retry.get_json()["error"]["code"] == "EXECUTION_TARGET_WRITE_DENIED"
    app.extensions["api_execution_targets"]["local-api"] = ExecutionTarget(
        target_id="local-api", environment="dev", internal_base_url="http://mock-api:8080",
        masked_base_url="http://mock-api:***", allow_write_methods=True,
    )

    retried = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/runs/{run['run_id']}/retry",
        headers=permission_headers,
    )
    assert retried.status_code == 202
    retried_run = retried.get_json()
    assert retried_run["run_id"] != run["run_id"]
    assert retried_run["execution_plan_id"] == plan["plan_id"]
    retried_input = json.loads(
        (store.task_dir(created["id"]) / "runs" / retried_run["run_id"] / "input.json").read_text()
    )
    assert "cases" not in retried_input
    assert retried_input["plan"]["plan_id"] == plan["plan_id"]
def test_stage_resolver_keeps_generation_and_execution_ready_visible() -> None:
    """刷新页面时必须依据真实阶段恢复工作区，不能回退到阶段一或空报告。"""

    script = Path(__file__).resolve().parents[2] / "services/common/static/api-v2-workbench.js"
    node = subprocess.run(
        [
            "node", "-e",
            "const {resolveApiV2Stage}=require(process.argv[1]);"
            "const done=new Set(['contracts','base-cases','coverage','executable-cases']);"
            "console.log(JSON.stringify(["
            "resolveApiV2Stage('pending','base_case_generation_queued',done),"
            "resolveApiV2Stage('running','executable_generation_running',done),"
            "resolveApiV2Stage('waiting_executable_review','executable_review',done),"
            "resolveApiV2Stage('waiting_execution_confirmation','execution_ready',done),"
            "resolveApiV2Stage('failed','execution_plan',done),"
            "resolveApiV2Stage('partial_success','execution_ready',done,true)"
            "]));",
            str(script),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert node.returncode == 0, node.stdout + node.stderr
    assert json.loads(node.stdout) == [1, 2, 2, 3, 3, 4]


def test_cases_normal_gate_returns_arrays_instead_of_503(tmp_path: Path) -> None:
    """契约 Review 阶段返回可渲染空态，items 始终是数组。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "GET /api/v1/me",
        }, content_type="multipart/form-data",
    ).get_json()
    record = app.extensions["task_store"].load(created["id"])
    record.update({"status": "waiting_contract_review", "stage": "contract_review"})
    app.extensions["task_store"].save(record)
    response = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases", headers=headers(),
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "stage_state": "blocked",
        "base_cases": {"version": 0, "sha256": "", "source_versions": {}, "lifecycle_status": "current", "items": []},
        "coverage_matrix": {
            "version": 0, "sha256": "", "contract_version": 0, "round_count": 0,
            "accepted_gap_ids": [], "partial_success": False,
            "lifecycle_status": "current", "items": [],
        },
    }


def test_issue_resolution_from_case_review_returns_to_contract_gate(tmp_path: Path) -> None:
    """后续 Review 阶段修订契约后，旧用例变 stale 并返回契约门禁。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "A", "module_name": "退出登录",
            "environment": "dev", "document_text": "POST /logout",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "waiting_case_review", "stage": "case_review"})
    store.save(record)
    issue = ReviewIssue(
        code="UNGROUNDED_FIELD", field_path="parameters[0].required",
        message="缺少原文依据", severity="blocker",
    )
    contract = ApiContract(
        contract_id="contract_logout", name="退出登录", method="POST", path="/logout",
        parameters=[ContractParameter(name="X-CSRF-Token", location="header")],
        source_trace=SourceTrace(source_id="doc", section_id="section-001"),
        field_evidence=[
            FieldEvidence(field_path="method", value="POST", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="path", value="/logout", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="parameters[0].name", value="X-CSRF-Token", source_type="source_quote", source_pointer="section-001"),
            FieldEvidence(field_path="parameters[0].location", value="header", source_type="source_quote", source_pointer="section-001"),
        ], unresolved=[issue],
    )
    versions = ApiV2Store(store)
    contracts = versions.save_version(created["id"], kind="contracts", items=[contract.model_dump(mode="json")])
    versions.save_version(created["id"], kind="base-cases", items=[], source_versions={"contracts": contracts["version"]})
    versions.save_version(created["id"], kind="coverage", items={
        "version": 1, "contract_version": contracts["version"], "round_count": 0,
        "items": [], "accepted_gap_ids": [], "partial_success": False,
    }, source_versions={"contracts": contracts["version"]})
    issue_id = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/review-issues", headers=headers(),
    ).get_json()["items"][0]["issue_id"]
    response = client.put(
        f"/api-test-agent/api/v1/tasks/{created['id']}/review-issues/{issue_id}",
        headers=headers(permissions="tool.result.view,api-test-agent.contract.review"),
        json={
            "base_contract_version": contracts["version"], "action": "human_override",
            "reason": "测试人员确认非必填", "payload": {"value": False},
        },
    )
    assert response.status_code == 200
    updated = store.load(created["id"])
    assert updated["status"] == "waiting_contract_review"
    assert {item["kind"] for item in updated["stale_versions"]} == {"base-cases", "coverage"}


def test_list_runs_returns_only_safe_task_summary(tmp_path: Path) -> None:
    """Run 列表只返回当前任务的脱敏摘要，不暴露报告正文。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks",
        headers=headers(),
        data={
            "operation": "generate_api_cases",
            "project_name": "项目 A",
            "module_name": "登录",
            "environment": "dev",
            "document_text": "GET /api/v1/me",
        },
        content_type="multipart/form-data",
    ).get_json()
    runs_dir = app.extensions["task_store"].task_dir(created["id"]) / "runs"
    first = runs_dir / "run_first"
    second = runs_dir / "run_second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "run.json").write_text(json.dumps({
        "run_id": "run_first", "status": "failed", "created_at": "2026-08-18T09:00:00+08:00",
        "finished_at": "2026-08-18T09:01:00+08:00", "summary": {"total": 2, "passed": 1, "failed": 1},
        "request_summary": {"authorization": "secret"},
    }), encoding="utf-8")
    (second / "run.json").write_text(json.dumps({
        "run_id": "run_second", "status": "succeeded", "created_at": "2026-08-18T10:00:00+08:00",
        "finished_at": "2026-08-18T10:01:00+08:00", "summary": {"total": 3, "passed": 3, "failed": 0},
    }), encoding="utf-8")

    response = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/runs",
        headers=headers(permissions="tool.result.view"),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latest_run_id"] == "run_second"
    assert [item["run_id"] for item in payload["items"]] == ["run_second", "run_first"]
    assert payload["items"][1]["total_cases"] == 2
    assert "secret" not in response.get_data(as_text=True)


def test_stage_event_usage_and_provenance_endpoints_are_owner_scoped(tmp_path: Path) -> None:
    """阶段记录接口只返回当前任务的脱敏摘要。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /api/login",
        }, content_type="multipart/form-data",
    ).get_json()
    attempt_id = "attempt_test_v22"
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record["current_attempt_id"] = attempt_id
    store.save(record)
    StageEventStore(store).append(StageEvent(
        event_id="event_test", task_id=created["id"], attempt_id=attempt_id,
        stage="base_case_generation", node="fused_kernel", event_type="completed",
        status="succeeded", message="Cookie: session=secret-value",
    ))

    event_response = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/stage-events",
        headers=headers(permissions="tool.result.view"),
    )
    assert event_response.status_code == 200
    assert "secret-value" not in event_response.get_data(as_text=True)
    assert client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/stage-events",
        headers=headers("other", "tool.result.view"),
    ).status_code == 404
    assert client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/model-usage",
        headers=headers(permissions="tool.result.view"),
    ).status_code == 200
    assert client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/generation-provenance",
        headers=headers(permissions="tool.result.view"),
    ).status_code == 200


def test_contracts_return_generating_before_first_version_exists(tmp_path: Path) -> None:
    """新任务详情页不得把契约尚未生成误报为 500 或 503。"""

    client, _app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /api/login",
        }, content_type="multipart/form-data",
    ).get_json()

    response = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/contracts",
        headers=headers(permissions="tool.result.view"),
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "stage_state": "generating", "version": 0, "sha256": "",
        "items": [], "task_status": "pending",
    }
    missing = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/contracts?version=9",
        headers=headers(permissions="tool.result.view"),
    )
    assert missing.status_code == 404
    assert missing.get_json()["error"]["code"] == "CONTRACT_VERSION_NOT_FOUND"


def test_ai_supplement_retry_reuses_current_versions(tmp_path: Path) -> None:
    """AI-only 重试创建新 Attempt 时必须显式复用当前产物版本。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /api/login",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record.update({"status": "waiting_case_review", "stage": "case_review"})
    store.save(record)
    versions = ApiV2Store(store)
    versions.save_version(created["id"], kind="contracts", items=[])
    versions.save_version(created["id"], kind="base-cases", items=[])
    versions.save_version(created["id"], kind="coverage", items={"version": 1, "contract_version": 1, "items": []})

    captured = {}

    class CapturingManager:
        def enqueue_stage(self, task_id, **kwargs):
            captured.update({"task_id": task_id, **kwargs})
            queued = store.load(task_id)
            queued.update({"status": "pending", "stage": "base_case_generation_queued"})
            return queued

    app.extensions["task_manager"] = CapturingManager()
    response = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/cases/supplement/retry",
        headers=headers(permissions="tool.result.view,api-test-agent.case.review"),
    )

    assert response.status_code == 202
    assert captured["request_updates"] == {"supplement_only": True}
    assert captured["source_versions"] == {"contracts": 1, "base-cases": 1, "coverage": 1}


def test_failed_task_retry_uses_attempt_stage_instead_of_legacy_task_stage(tmp_path: Path) -> None:
    """历史任务的通用 api_v2 阶段不得阻止从真实失败 Attempt 重试。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /api/login",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    attempt = ApiV2Store(store).create_attempt(
        created["id"], stage="base_case_generation", source_versions={"contracts": 1},
    )
    record = store.load(created["id"])
    record.update({"status": "failed", "stage": "api_v2", "current_attempt_id": attempt["id"]})
    store.save(record)
    captured = {}

    class CapturingManager:
        def enqueue_stage(self, task_id, **kwargs):
            captured.update({"task_id": task_id, **kwargs})
            queued = store.load(task_id)
            queued.update({"status": "pending", "stage": "base_case_generation_queued"})
            return queued

    app.extensions["task_manager"] = CapturingManager()
    response = client.post(
        f"/api-test-agent/api/v1/tasks/{created['id']}/retry",
        headers=headers(), json={"stage": "api_v2", "source_versions": {}},
    )

    assert response.status_code == 202
    assert captured["from_stage"] == "base_case_generation"
    assert captured["source_versions"] == {"contracts": 1}


def test_usage_summary_is_owner_scoped_and_global_requires_view_all(tmp_path: Path) -> None:
    """任务统计沿用所有权；跨任务统计只允许全局查看角色。"""

    client, app = make_client(tmp_path)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A",
            "module_name": "登录", "environment": "dev", "document_text": "POST /api/login",
        }, content_type="multipart/form-data",
    ).get_json()
    store = app.extensions["task_store"]
    record = store.load(created["id"])
    record["current_attempt_id"] = "attempt_usage"
    store.save(record)
    StageEventStore(store).save_usage(created["id"], ModelUsageRecord(
        call_id="call_usage", attempt_id="attempt_usage", stage="document_parsing",
        node="parser", prompt_id="parser_v2", prompt_sha256="a" * 64,
        model_name="fake", input_tokens=10, output_tokens=5, total_tokens=15, reported=True,
    ))

    task_response = client.get(
        f"/api-test-agent/api/v1/tasks/{created['id']}/usage/summary",
        headers=headers(permissions="tool.result.view"),
    )
    assert task_response.status_code == 200
    assert task_response.get_json()["summary"]["total_tokens"] == 15
    assert client.get(
        "/api-test-agent/api/v1/usage/summary",
        headers=headers(permissions="tool.result.view"),
    ).status_code == 403
    assert client.get(
        "/api-test-agent/api/v1/usage/summary",
        headers=headers(permissions="tool.result.view,task.view.all", scope="global"),
    ).status_code == 200
