"""API 智能体独立 Web 服务的身份、所有权和执行门禁测试。"""

from __future__ import annotations

import io
import json
from pathlib import Path

from services.api_agent.app import create_app
from services.common.config import ServiceSettings
from services.common.errors import ServiceError
from services.common.task_models import utc_now


class FakePlatformClient:
    """提供不读取 Token 和网络的最小平台配置。"""

    def __init__(self) -> None:
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

    def runtime_config(self, *, include_secrets: bool):
        """返回与参数兼容的隔离配置快照。"""

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


def headers(user: str = "user_1", permissions: str = "tool.view,tool.execute,tool.result.view,task.cancel") -> dict[str, str]:
    """构造经过网关签发的可信身份头。"""

    return {
        "X-Platform-User-ID": user,
        "X-Platform-Username": user,
        "X-Platform-Display-Name": user,
        "X-Platform-Permissions": permissions,
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

    client, _app = make_client(tmp_path)
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
    path = f"/api-test-agent/api/v1/tasks/{task['id']}"
    assert client.get(path, headers=headers()).status_code == 200
    assert client.get(path, headers=headers("other")).status_code == 404
    assert client.get(path, headers=headers("admin", "tool.result.view,task.view.all")).status_code == 200


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


def test_task_page_exposes_stage_workspace(tmp_path: Path) -> None:
    """详情页按阶段展示工作区，并提供受控执行确认弹窗。"""

    client, _app = make_client(tmp_path)
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
    page = client.get(f"/api-test-agent/tasks/{created['id']}", headers=headers())
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "确认分析范围" in html
    assert "coverage-matrix" in html
    assert "execution-confirm-dialog" in html
    assert "run-report" in html


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
