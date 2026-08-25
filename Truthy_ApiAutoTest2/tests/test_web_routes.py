"""壳服务路由单元测试。

功能说明:
    使用 Flask test client 覆盖全部端点的状态码与关键响应契约，验证
    根路径与子路径（base path）两种挂载模式、分页夹取、凭证状态、
    报告元信息与静态报告、日志兜底脱敏零泄漏。任务执行一律使用
    patch_command 模拟子进程，不发真实请求。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from flask.testing import FlaskClient

from conftest import junit_xml, patch_command
from web.app import create_app, load_web_settings, validate_base_path
from web.task_manager import TaskManager
from web.task_store import TaskStore

# 伪造任务 ID（格式合法但不存在）。
UNKNOWN_TASK_ID = "20260101-000000-0000"


def make_settings(base_path: str = "") -> dict:
    """构造测试用运行配置。"""
    return {
        "host": "127.0.0.1",
        "port": 5003,
        "base_path": base_path,
        "platform_home_url": "/",
        "timeout_seconds": 30,
        "tasks_retain": 50,
        "report_dir": "reports/allure-current",
    }


@pytest.fixture
def app_env(fake_project: Path, make_manager):
    """应用工厂：返回 ``(test_client, manager, base_path)`` 构造器。"""

    def _build(base_path: str = "", inject_manager: bool = True):
        settings = make_settings(base_path)
        manager = None
        if inject_manager:
            manager = make_manager(fake_project)
            app = create_app(
                project_root=fake_project,
                settings=settings,
                task_manager=manager,
            )
        else:
            app = create_app(project_root=fake_project, settings=settings)
        app.config["TESTING"] = True
        return app.test_client(), manager

    return _build


@pytest.fixture
def client(app_env) -> tuple[FlaskClient, TaskManager]:
    """根路径模式下的测试客户端与执行引擎。"""
    return app_env()


class TestSettingsAndBasePath:
    """运行配置解析与基础路径校验（纯函数）。"""

    def test_validate_base_path_accepts_empty_and_strips_trailing_slash(self):
        assert validate_base_path("") == ""
        assert validate_base_path("  ") == ""
        assert validate_base_path("/api-autotest") == "/api-autotest"
        assert validate_base_path("/api-autotest/") == "/api-autotest"

    @pytest.mark.parametrize(
        "value",
        ["api", "/a?b=1", "/a#frag", "http://x", "/a//b", "/a/../b"],
    )
    def test_validate_base_path_rejects_invalid(self, value):
        with pytest.raises(ValueError):
            validate_base_path(value)

    def test_load_web_settings_defaults(self):
        settings = load_web_settings({})
        assert settings["host"] == "127.0.0.1"
        assert settings["port"] == 5003
        assert settings["base_path"] == ""
        assert settings["timeout_seconds"] == 1800
        assert settings["tasks_retain"] == 50
        assert settings["report_dir"] == "reports/allure-current"

    def test_load_web_settings_overrides(self):
        settings = load_web_settings(
            {
                "API_AUTOTEST_HOST": "0.0.0.0",
                "API_AUTOTEST_PORT": "6000",
                "API_AUTOTEST_BASE_PATH": "/api-autotest/",
                "API_AUTOTEST_TASK_TIMEOUT_SECONDS": "60",
                "API_AUTOTEST_TASKS_RETAIN": "5",
                "API_AUTOTEST_REPORT_DIR": "reports/x",
                "PLATFORM_HOME_URL": "/home",
            }
        )
        assert settings["host"] == "0.0.0.0"
        assert settings["port"] == 6000
        assert settings["base_path"] == "/api-autotest"
        assert settings["timeout_seconds"] == 60
        assert settings["tasks_retain"] == 5
        assert settings["report_dir"] == "reports/x"
        assert settings["platform_home_url"] == "/home"

    def test_load_web_settings_invalid_port(self):
        with pytest.raises(ValueError):
            load_web_settings({"API_AUTOTEST_PORT": "not-a-port"})


class TestPagesAndHealth:
    """页面渲染与健康检查。"""

    def test_health_ok(self, client):
        test_client, _ = client
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {
            "status": "ok", "service": "api-autotest", "version": "unknown",
            "revision": "unknown", "dirty": True, "content_sha256": "unknown",
            "runtime_environment": "unknown",
        }

    def test_index_and_catalog_pages_render(self, client):
        test_client, _ = client
        index = test_client.get("/")
        assert index.status_code == 200
        assert "接口自动化" in index.get_data(as_text=True)
        catalog = test_client.get("/catalog")
        assert catalog.status_code == 200

    def test_task_detail_page(self, client, monkeypatch):
        test_client, manager = client
        patch_command(monkeypatch, manager, "print('ok')")
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        task_id = submitted.get_json()["id"]
        page = test_client.get(f"/tasks/{task_id}")
        assert page.status_code == 200
        assert task_id in page.get_data(as_text=True)

    def test_task_detail_page_unknown_task(self, client):
        test_client, _ = client
        assert test_client.get(f"/tasks/{UNKNOWN_TASK_ID}").status_code == 404

    def test_base_path_mode(self, app_env):
        test_client, _ = app_env(base_path="/api-autotest")
        assert test_client.get("/api-autotest/health").status_code == 200
        assert test_client.get("/health").status_code == 404
        index = test_client.get("/api-autotest/")
        assert index.status_code == 200
        # JS 基址注入模板，页面不硬编码根路径。
        assert '"/api-autotest"' in index.get_data(as_text=True)


class TestTaskRoutes:
    """任务提交、列表、详情、取消与结果接口。"""

    def test_resource_context_hides_foreign_task_and_report_from_enumeration(
        self, client, monkeypatch, tmp_path
    ):
        """tester-b 不能借由列表、详情或静态报告路径枚举 tester-a 的任务。

        opaque context 的内容由平台验证，测试仅模拟平台的 ``allowed=false``
        决策；应用不能从浏览器 Header 推断 owner/project。
        """
        test_client, manager = client
        task_id = "20260101-000000-0001"
        manager.store.save(
            {
                "id": task_id,
                "status": "succeeded",
                "created_at": "2026-01-01T00:00:00+00:00",
                "resource_snapshot": {
                    "owner_user_id": "tester-a",
                    "access_scope_snapshot": "project",
                    "project_id_snapshot": "project-a",
                    "authorization_source_snapshot": "project-member",
                },
            }
        )
        token_file = tmp_path / "platform-token"
        token_file.write_text("test-tool-token", encoding="utf-8")
        settings = test_client.application.config["AUTOTEST_SETTINGS"]
        settings.update(
            {
                "platform_api_url": "http://platform.invalid/api/v1",
                "platform_client_token_file": str(token_file),
            }
        )
        report_dir = (
            manager.project_root / "reports" / "task-reports" / task_id / "current"
        )
        report_dir.mkdir(parents=True)
        (report_dir / "index.html").write_text("private report", encoding="utf-8")

        denied = _FakePlatformErrorResponse(404, "RESOURCE_NOT_FOUND", "not found")

        def access_response(_url, *, headers, **_kwargs):
            """模拟平台核验后的 own/project/global 查询范围，不解码 opaque 值。"""
            opaque_context = headers.get("X-Platform-Resource-Context")
            if opaque_context == "opaque-manager":
                return _FakeRuntimeConfigResponse(
                    {
                        "allowed": True,
                        "user_id": "manager-a",
                        "data_scope": "project",
                        "managed_project_ids": ["project-a"],
                    }
                )
            if opaque_context == "opaque-platform-admin":
                return _FakeRuntimeConfigResponse(
                    {"allowed": True, "user_id": "platform-admin", "data_scope": "global"}
                )
            if opaque_context == "opaque-extra-grant-admin":
                return _FakeRuntimeConfigResponse(
                    {"allowed": True, "user_id": "admin-extra", "data_scope": "own"}
                )
            return denied

        monkeypatch.setattr("web.app.requests.post", access_response)
        headers = {"X-Platform-Resource-Context": "opaque-tester-b"}

        listing = test_client.get("/api/tasks", headers=headers)
        detail = test_client.get(f"/api/tasks/{task_id}", headers=headers)
        report = test_client.get(f"/api/report/meta?task_id={task_id}", headers=headers)
        unknown = test_client.get(f"/api/tasks/{UNKNOWN_TASK_ID}", headers=headers)

        assert listing.get_json()["items"] == []
        assert detail.status_code == 404
        assert report.status_code == 404
        assert unknown.status_code == detail.status_code
        assert test_client.get(
            "/api/tasks", headers={"X-Platform-Resource-Context": "opaque-manager"}
        ).get_json()["items"][0]["id"] == task_id
        assert test_client.get(
            "/api/tasks", headers={"X-Platform-Resource-Context": "opaque-extra-grant-admin"}
        ).get_json()["items"] == []
        assert test_client.get(
            "/api/tasks", headers={"X-Platform-Resource-Context": "opaque-platform-admin"}
        ).get_json()["items"][0]["id"] == task_id

    def test_submit_invalid_body(self, client):
        test_client, _ = client
        response = test_client.post(
            "/api/tasks", data="not json", content_type="application/json"
        )
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "INVALID_PARAMS"

    def test_submit_invalid_params(self, client):
        test_client, _ = client
        response = test_client.post(
            "/api/tasks", json={"env": "prod", "run_type": "single"}
        )
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "INVALID_PARAMS"

    def test_submit_and_query_lifecycle(self, client, monkeypatch):
        test_client, manager = client
        patch_command(monkeypatch, manager, "print('ok')")
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        assert submitted.status_code == 201
        body = submitted.get_json()
        assert body["id"]
        assert body["status"] in ("pending", "running")

        manager.wait_idle()

        listing = test_client.get("/api/tasks").get_json()
        assert listing["total"] == 1
        assert listing["items"][0]["id"] == body["id"]

        detail = test_client.get(f"/api/tasks/{body['id']}").get_json()
        assert detail["status"] == "succeeded"

        # 未生成 JUnit：结果接口给出原因码而非错误。
        result = test_client.get(f"/api/tasks/{body['id']}/result").get_json()
        assert result["result_available"] is False
        assert result["reason_code"] == "JUNIT_NOT_GENERATED"

    def test_result_with_junit(self, client, monkeypatch, tmp_path):
        test_client, manager = client
        staged = tmp_path / "staged.xml"
        staged.write_text(
            junit_xml([("case_a", "passed"), ("case_b", "failure")]),
            encoding="utf-8",
        )
        # 模拟 pytest：写出 JUnit 后以退出码 1 结束。
        patch_command(
            monkeypatch,
            manager,
            f"import shutil, sys; shutil.copy({str(staged)!r}, '{{junit}}'); "
            "sys.exit(1)",
        )
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        manager.wait_idle()
        result = test_client.get(
            f"/api/tasks/{submitted.get_json()['id']}/result"
        ).get_json()
        assert result["result_available"] is True
        assert result["summary"]["total"] == 2
        assert result["summary"]["failed"] == 1
        assert result["failed_cases"][0]["name"] == "case_b"

    def test_pagination_clamped(self, client, monkeypatch):
        test_client, manager = client
        patch_command(monkeypatch, manager, "print('ok')")
        for _ in range(2):
            test_client.post("/api/tasks", json={"env": "test", "run_type": "single"})
            manager.wait_idle()

        first = test_client.get("/api/tasks?page=1&page_size=1").get_json()
        second = test_client.get("/api/tasks?page=2&page_size=1").get_json()
        assert first["total"] == 2
        assert len(first["items"]) == 1
        assert first["items"][0]["id"] != second["items"][0]["id"]

        clamped = test_client.get("/api/tasks?page_size=999").get_json()
        assert clamped["page_size"] == 100

        assert test_client.get("/api/tasks?page=abc").status_code == 400

    def test_slot_busy_via_route(self, client, monkeypatch):
        test_client, manager = client
        patch_command(monkeypatch, manager, "import time; time.sleep(2)")
        first = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        assert first.status_code == 201
        # 等待子进程真正启动占住槽位。
        task_id = first.get_json()["id"]
        while manager.store.load(task_id)["status"] != "running":
            time.sleep(0.02)
        second = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        assert second.status_code == 409
        assert second.get_json()["error_code"] == "SLOT_BUSY"

    def test_cancel_via_route(self, client, monkeypatch):
        test_client, manager = client
        patch_command(monkeypatch, manager, "import time; time.sleep(10)")
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        task_id = submitted.get_json()["id"]
        while manager.store.load(task_id)["status"] != "running":
            time.sleep(0.02)

        cancelled = test_client.post(f"/api/tasks/{task_id}/cancel")
        assert cancelled.status_code == 200

        manager.wait_idle()
        assert (
            test_client.get(f"/api/tasks/{task_id}").get_json()["status"]
            == "cancelled"
        )

        again = test_client.post(f"/api/tasks/{task_id}/cancel")
        assert again.status_code == 409
        assert again.get_json()["error_code"] == "TASK_TERMINATED"

    def test_unknown_task_endpoints(self, client):
        test_client, _ = client
        assert test_client.get(f"/api/tasks/{UNKNOWN_TASK_ID}").status_code == 404
        assert (
            test_client.post(f"/api/tasks/{UNKNOWN_TASK_ID}/cancel").status_code
            == 404
        )
        assert (
            test_client.get(f"/api/tasks/{UNKNOWN_TASK_ID}/result").status_code
            == 404
        )
        assert (
            test_client.get(f"/api/tasks/{UNKNOWN_TASK_ID}/logs").status_code == 404
        )


class TestLogsRoutes:
    """日志接口：框架日志优先、console 兜底必须二次脱敏。"""

    def test_console_fallback_redacts_secrets(self, client, monkeypatch):
        test_client, manager = client
        script = "print('Authorization: Bearer supersecret123')"
        patch_command(monkeypatch, manager, script)
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        manager.wait_idle()
        task_id = submitted.get_json()["id"]

        logs = test_client.get(f"/api/tasks/{task_id}/logs").get_json()
        assert logs["source"] == "console_redacted"
        text = "\n".join(logs["lines"])
        assert "supersecret123" not in text
        assert "[REDACTED]" in text

    def test_logs_tail_param(self, client, monkeypatch):
        test_client, manager = client
        patch_command(monkeypatch, manager, "print('line')")
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        manager.wait_idle()
        task_id = submitted.get_json()["id"]

        assert (
            test_client.get(f"/api/tasks/{task_id}/logs?tail=abc").status_code == 400
        )
        logs = test_client.get(f"/api/tasks/{task_id}/logs?tail=1").get_json()
        assert len(logs["lines"]) <= 1

    def test_logs_without_any_output(self, client):
        # 无 console 文件（任务从未启动子进程）时返回 none 而非报错。
        test_client, manager = client
        manager.store.save(
            {
                "id": "20260101-000000-0001",
                "status": "failed",
                "junit_file": "reports/junit-task-20260101-000000-0001.xml",
                "log_file": None,
            }
        )
        logs = test_client.get("/api/tasks/20260101-000000-0001/logs").get_json()
        assert logs["source"] == "none"
        assert logs["lines"] == []


class TestCatalogCredentialsReportRoutes:
    """用例库、凭证状态与报告接口。"""

    def test_catalog_api(self, client):
        test_client, _ = client
        response = test_client.get("/api/catalog")
        assert response.status_code == 200
        body = response.get_json()
        assert set(body.keys()) == {"apis", "cases", "flows", "errors"}

    def test_credentials_status_ready(self, client):
        test_client, _ = client
        body = test_client.get(
            "/api/credentials/status?env=test&run_type=single"
        ).get_json()
        assert body["base_config"]["ready"] is True
        assert body["admin"]["required"] is False
        assert body["admin"]["ready"] is True
        # 只返回状态与字段名，不返回凭证值。
        assert "fake-auth-token" not in json.dumps(body)

    def test_credentials_status_admin_required(self, client):
        test_client, _ = client
        body = test_client.get(
            "/api/credentials/status?env=test&run_type=flow&flow=AdminFlow"
        ).get_json()
        assert body["admin"]["required"] is True
        assert body["admin"]["ready"] is True
        assert body["admin"]["missing_fields"] == []

    def test_report_missing(self, client):
        test_client, _ = client
        meta = test_client.get("/api/report/meta").get_json()
        assert meta["exists"] is False
        assert meta["report_url"] is None
        assert test_client.get("/reports/index.html").status_code == 404

    def test_report_stat_oserror_degrades_to_missing(
        self, client, fake_project, monkeypatch
    ):
        """报告目录 stat 抛 OSError 时降级为"暂无报告"，不得 500。

        场景说明:
            Docker Desktop for Mac 绑定挂载在宿主机原子切换 symlink 后，
            容器内残留句柄可能使 exists()/resolve() 抛 OSError(EINVAL)
            而非 ENOENT；只读展示端点必须优雅降级。
        """
        test_client, manager = client
        task_id = "20260101-000000-0001"
        manager.store.save({"id": task_id, "status": "succeeded"})
        (fake_project / "reports" / "task-reports" / task_id / "current").mkdir(
            parents=True
        )
        real_exists = Path.exists

        def flaky_exists(self, *args, **kwargs):
            # 仅对报告指针目录注入异常，其余路径保持真实行为。
            if self.name == "current":
                raise OSError(22, "Invalid argument")
            return real_exists(self, *args, **kwargs)

        monkeypatch.setattr(Path, "exists", flaky_exists)
        response = test_client.get(f"/api/report/meta?task_id={task_id}")
        assert response.status_code == 200
        meta = response.get_json()
        assert meta["exists"] is False
        assert meta["report_url"] is None

    def test_report_published(self, client, fake_project):
        test_client, manager = client
        task_id = "20260101-000000-0001"
        manager.store.save(
            {
                "id": task_id,
                "status": "succeeded",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        report_dir = fake_project / "reports" / "task-reports" / task_id / "current"
        report_dir.mkdir(parents=True)
        (report_dir / "index.html").write_text(
            "<html>allure report</html>", encoding="utf-8"
        )
        (report_dir / "report-meta.json").write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "synced_at": "2026-08-10T10:00:00+08:00",
                    "source": "jenkins",
                }
            ),
            encoding="utf-8",
        )

        meta = test_client.get(f"/api/report/meta?task_id={task_id}").get_json()
        assert meta["exists"] is True
        assert meta["source"] == "jenkins"
        assert meta["report_url"] == f"/reports/{task_id}/index.html"

        page = test_client.get(f"/reports/{task_id}/index.html")
        assert page.status_code == 200
        assert "allure report" in page.get_data(as_text=True)

    def test_report_binding_rejects_authorized_task_when_current_belongs_to_another_task(
        self, client, fake_project
    ):
        """授权某个任务不能成为读取另一任务全局 current 报告的通行证。"""

        test_client, manager = client
        requested_task_id = "20260101-000000-0001"
        foreign_task_id = "20260101-000000-0002"
        manager.store.save(
            {
                "id": requested_task_id,
                "status": "succeeded",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        report_dir = (
            fake_project / "reports" / "task-reports" / requested_task_id / "current"
        )
        report_dir.mkdir(parents=True)
        (report_dir / "index.html").write_text("foreign report", encoding="utf-8")
        (report_dir / "report-meta.json").write_text(
            json.dumps({"task_id": foreign_task_id, "source": "jenkins"}),
            encoding="utf-8",
        )

        meta = test_client.get(
            f"/api/report/meta?task_id={requested_task_id}"
        )
        page = test_client.get(f"/reports/{requested_task_id}/index.html")

        assert meta.status_code == 200
        assert meta.get_json() == {"exists": False, "report_url": None}
        assert page.status_code == 404
        assert test_client.get("/reports/index.html").status_code == 404


class _FakeRuntimeConfigResponse:
    """模拟平台 runtime-config 响应对象。"""

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakePlatformErrorResponse:
    """模拟平台返回带稳定错误码的非 2xx JSON 响应。"""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self._payload = {"code": code, "message": message}

    def raise_for_status(self) -> None:
        """保持 requests.Response 的非成功状态行为。"""

        raise requests.HTTPError(f"platform returned {self.status_code}")

    def json(self) -> dict:
        return self._payload


class TestPlatformCredentialStatus:
    """平台模式凭证状态：以平台 Secret 键名清单判定，不读本地凭证。"""

    def _build_client(
        self,
        fake_project: Path,
        make_manager,
        monkeypatch,
        configured_keys: set[str] | None = None,
        request_error: Exception | None = None,
    ):
        """构造平台模式应用与测试客户端，并打桩平台 HTTP 调用。

        返回值:
            ``(test_client, calls)``；calls 记录打桩收到的 (url, kwargs)。
        """
        settings = make_settings()
        settings["config_source"] = "platform"
        settings["platform_api_url"] = "http://platform-api.invalid/api/v1"
        token_file = fake_project / "client-token"
        token_file.write_text("test-client-token", encoding="utf-8")
        settings["platform_client_token_file"] = str(token_file)

        calls: list[tuple[str, dict]] = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if request_error is not None:
                raise request_error
            return _FakeRuntimeConfigResponse(
                {
                    "runtime_context_id": "rtx_status_user_1",
                    "expires_at": "2026-08-24T12:00:00Z",
                }
            )

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            if request_error is not None:
                raise request_error
            return _FakeRuntimeConfigResponse(
                {
                    "tool_id": "api-autotest",
                    "release_id": "rel_test",
                    "snapshot_selector": {"release_id": "rel_test"},
                    "configured_secret_keys": sorted(configured_keys or set()),
                }
            )

        monkeypatch.setattr("web.app.requests.post", fake_post)
        monkeypatch.setattr("web.app.requests.get", fake_get)

        app = create_app(
            project_root=fake_project,
            settings=settings,
            task_manager=make_manager(fake_project),
        )
        app.config["TESTING"] = True
        return app.test_client(), calls

    def test_admin_ready_when_platform_keys_configured(
        self, fake_project, make_manager, monkeypatch
    ):
        # 本地 .env 之外，平台清单齐备即应就绪；且只以键名查询不下发 Secret 值。
        client, calls = self._build_client(
            fake_project,
            make_manager,
            monkeypatch,
            configured_keys={
                "ADMIN_SESSION_TOKEN",
                "ADMIN_OPERATOR_ID",
                "ADMIN_OPERATOR_NAME",
            },
        )
        body = client.get(
            "/api/credentials/status?env=test&run_type=flow&flow=AdminFlow",
            headers={"X-Platform-User-Context": "signed-status-user-1"},
        ).get_json()
        assert body["base_config"]["ready"] is True
        assert body["admin"]["required"] is True
        assert body["admin"]["ready"] is True
        assert body["admin"]["missing_fields"] == []

        assert len(calls) == 2
        context_url, context_kwargs = calls[0]
        assert context_url.endswith("/internal/tools/api-autotest/runtime-contexts")
        assert context_kwargs["headers"]["X-Platform-User-Context"] == "signed-status-user-1"
        url, kwargs = calls[1]
        assert url.endswith("/internal/tools/api-autotest/runtime-config")
        assert kwargs["params"] == {
            "include_secrets": "false",
            "runtime_context_id": "rtx_status_user_1",
        }
        assert kwargs["headers"]["Authorization"] == "Bearer test-client-token"

    def test_admin_missing_fields_follow_platform_keys(
        self, fake_project, make_manager, monkeypatch
    ):
        # fake_project 本地 .env 含全部 Admin 凭证，但平台清单缺两项时，
        # 应以平台清单为准报告缺失（平台模式本地凭证不参与合并）。
        client, _ = self._build_client(
            fake_project,
            make_manager,
            monkeypatch,
            configured_keys={"ADMIN_SESSION_TOKEN"},
        )
        body = client.get(
            "/api/credentials/status?env=test&run_type=flow&flow=AdminFlow",
            headers={"X-Platform-User-Context": "signed-status-user-1"},
        ).get_json()
        assert body["admin"]["ready"] is False
        assert body["admin"]["missing_fields"] == [
            "ADMIN_OPERATOR_ID",
            "ADMIN_OPERATOR_NAME",
        ]

    def test_platform_unavailable_degrades_gracefully(
        self, fake_project, make_manager, monkeypatch
    ):
        # 平台接口异常时状态接口不得 500，降级为基础配置未就绪且不误报字段。
        client, _ = self._build_client(
            fake_project,
            make_manager,
            monkeypatch,
            request_error=ConnectionError("platform unreachable"),
        )
        response = client.get(
            "/api/credentials/status?env=test&run_type=flow&flow=AdminFlow",
            headers={"X-Platform-User-Context": "signed-status-user-1"},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["base_config"]["ready"] is False
        assert "平台运行配置暂时不可用" in body["base_config"]["message"]
        assert body["admin"]["ready"] is False
        assert body["admin"]["missing_fields"] == []

    def test_non_admin_target_skips_platform_lookup(
        self, fake_project, make_manager, monkeypatch
    ):
        # 目标不含 Admin 步骤时不应调用平台接口。
        client, calls = self._build_client(
            fake_project, make_manager, monkeypatch, configured_keys=set()
        )
        body = client.get(
            "/api/credentials/status?env=test&run_type=single"
        ).get_json()
        assert body["admin"]["required"] is False
        assert calls == []

    def test_task_submission_preserves_personal_credential_error(
        self, fake_project, monkeypatch
    ):
        """个人凭证缺失必须原样返回 409，不能被折叠成通用平台 503。"""

        settings = make_settings()
        settings["config_source"] = "platform"
        settings["platform_api_url"] = "http://platform-api.invalid/api/v1"
        token_file = fake_project / "client-token"
        token_file.write_text("test-client-token", encoding="utf-8")
        settings["platform_client_token_file"] = str(token_file)

        def fake_post(url, **kwargs):
            return _FakeRuntimeConfigResponse(
                {
                    "runtime_context_id": "rtx_missing_credential_user",
                    "expires_at": "2026-08-24T12:00:00Z",
                }
            )

        def fake_get(url, **kwargs):
            return _FakePlatformErrorResponse(
                409,
                "PERSONAL_CREDENTIAL_NOT_CONFIGURED",
                "请先配置当前工具的个人凭证",
            )

        monkeypatch.setattr("web.app.requests.post", fake_post)
        monkeypatch.setattr("web.app.requests.get", fake_get)
        app = create_app(project_root=fake_project, settings=settings)
        app.config["TESTING"] = True
        test_client = app.test_client()
        test_client.set_cookie("tp_csrf", "test-csrf")

        response = test_client.post(
            "/api/tasks",
            headers={
                "X-CSRF-Token": "test-csrf",
                "X-Platform-User-Context": "signed-missing-credential-user",
            },
            json={"env": "test", "run_type": "single"},
        )

        assert response.status_code == 409
        assert response.get_json() == {
            "error": "请先配置当前工具的个人凭证",
            "error_code": "PERSONAL_CREDENTIAL_NOT_CONFIGURED",
        }
        assert TaskStore(fake_project / "tasks", fake_project / "reports").list() == []


class TestStartupRecovery:
    """应用工厂自建引擎时执行启动恢复。"""

    def test_create_app_recovers_leftover_tasks(self, fake_project):
        store = TaskStore(fake_project / "tasks", fake_project / "reports")
        store.save({"id": "20260101-000000-0009", "status": "running", "input": {}})

        app = create_app(project_root=fake_project, settings=make_settings())
        app.config["TESTING"] = True

        record = TaskStore(fake_project / "tasks", fake_project / "reports").load(
            "20260101-000000-0009"
        )
        assert record["status"] == "failed"
        assert record["error_message"] == "服务重启，任务中断"
