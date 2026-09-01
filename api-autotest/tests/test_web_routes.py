"""壳服务路由单元测试。

功能说明:
    使用 Flask test client 覆盖全部端点的状态码与关键响应契约，验证
    根路径与子路径（base path）两种挂载模式、分页夹取、凭证状态、
    报告元信息与静态报告、日志兜底原文输出及任务访问隔离。任务执行一律使用
    patch_command 模拟子进程，不发真实请求。
"""

from __future__ import annotations

import json
import subprocess
import time
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml
from flask.testing import FlaskClient

from conftest import junit_xml, patch_command
from web.app import create_app, load_web_settings, validate_base_path
from web.task_manager import TaskManager
from web.task_store import TaskStore

# 伪造任务 ID（格式合法但不存在）。
UNKNOWN_TASK_ID = "20260101-000000-0000"


def test_flow_catalog_and_selector_render_readable_display_name() -> None:
    """Flow 表格和任务下拉框都应优先展示项目资产的可读标题。

    Catalog 为兼容旧调用方保留 ``name=flow_id``，真正的中文业务标题位于
    ``display_name``。该回归测试避免前端只渲染稳定 ID，导致新增 Flow 在
    平台上难以辨认。
    """

    script = (
        Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "item.display_name || item.name || item.id" in script
    assert "flowTitle(item)" in script


def test_v3_single_and_flow_retry_controls_are_supported() -> None:
    """V3 单条任务应同时支持原参数重试和修改参数后重试。

    Task V3 不只用于批次；统一队列上线后，新创建的单接口与 Flow 也会写成
    V3。前端必须通过同一个兼容性判断接受 V2/V3，同时继续拒绝无法证明
    数据契约兼容的历史 schema。
    """

    script = (
        Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "function supportsRetrySchema(schemaVersion)" in script
    assert "supportsRetrySchema(original.schema_version)" in script
    assert "supportsRetrySchema(task.schema_version)" in script


def test_platform_secret_management_url_is_allowlisted() -> None:
    """工具只允许跳回本站管理页，但 Secret 页面也必须属于合法目标。

    Evaluation Flow 缺少 API Key 时，后端会返回 Scope 精确深链。该测试直接
    执行前端 URL 校验函数，避免页面把正确深链静默丢弃后仍跳到普通配置。
    """

    script = (
        Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    helper_start = script.index("  function safeManagementUrl(url)")
    helper_end = script.index("\n  function managementLink", helper_start)
    helper = script[helper_start:helper_end]
    node_program = """
const window = { location: { origin: "http://localhost:8080" } };
""" + helper + """
if (safeManagementUrl("/settings/secrets?scope_id=dating") !== "/settings/secrets?scope_id=dating") process.exit(11);
if (safeManagementUrl("https://example.com/settings/secrets") !== "") process.exit(12);
"""

    subprocess.run(["node", "-e", node_program], check=True)


def test_batch_failed_retry_uses_backend_status_contract() -> None:
    """前端“失败项”必须与后端 failed/error 重试集合完全一致。

    cancelled、timed_out 与 not_run 仍是需要展示的终态，但它们没有可复制的
    失败执行项，不能使“仅重试失败项”按钮变为可用，也不能计入可重试失败数。
    """

    script = (
        Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "function isRetryableBatchFailure(status)" in script
    assert "batchItems.some((item) => isRetryableBatchFailure(item.status))" in script
    assert '["failed", "error", "timed_out", "cancelled"].includes(item.status)' not in script


def test_batch_detail_exposes_counts_failure_filter_and_not_run_label() -> None:
    """批次详情必须展示五类计数、失败筛选，并本地化未执行状态。"""

    root = Path(__file__).resolve().parents[1]
    template = (root / "web" / "templates" / "task_detail.html").read_text(
        encoding="utf-8"
    )
    script = (root / "web" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert 'id="detail-batch-counts"' in template
    assert 'id="detail-batch-filter"' in template
    assert 'not_run: "未执行"' in script
    assert 'batchFilter === "failed"' in script
    assert '["not_run", "cancelled"].includes' in script
    for label in ("总数", "通过", "失败", "跳过", "未执行"):
        assert label in script


def test_batch_media_contract_signature_ignores_display_copy() -> None:
    """批量图片 Flow 只按执行约束判断契约兼容性。

    Analysis 与 Reply 可以使用不同 label/description，MIME 声明顺序也不影响
    约束语义；数量或文件大小不同才应判为冲突。测试直接交给 Node 执行页面
    中的纯函数，避免只校验一段不会真正工作的静态字符串。
    """

    script = (
        Path(__file__).resolve().parents[1] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    helper_start = script.index("    function normalizedFileExecutionContract(contract)")
    helper_end = script.index("\n    function setFileInputContract(contract)", helper_start)
    helpers = script[helper_start:helper_end]
    node_program = helpers + """
const analysis = {
  type: "files", required: true, min_items: 1, max_items: 9,
  allowed_content_types: ["image/jpeg", "image/png", "image/webp"],
  max_size_bytes: 7000000, label: "Analysis 图片", description: "分析流程文案",
};
const reply = {
  type: "files", required: true, min_items: 1, max_items: 9,
  allowed_content_types: ["image/webp", "image/png", "image/jpeg"],
  max_size_bytes: 7000000, label: "Reply 图片", description: "回复流程文案",
};
const incompatible = { ...reply, max_items: 8 };
if (fileExecutionContractSignature(analysis) !== fileExecutionContractSignature(reply)) process.exit(11);
if (fileExecutionContractSignature(analysis) === fileExecutionContractSignature(incompatible)) process.exit(12);
const normalized = normalizedFileExecutionContract(analysis);
if (Object.prototype.hasOwnProperty.call(normalized, "label")) process.exit(13);
if (Object.prototype.hasOwnProperty.call(normalized, "description")) process.exit(14);
"""

    completed = subprocess.run(
        ["node", "-e", node_program],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "JSON.stringify(fileInputContract)" not in script
    assert "JSON.stringify(contracts[0])" not in script


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

    def test_busy_route_accepts_second_task_into_queue(self, client, monkeypatch):
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
        assert second.status_code == 201
        queued = manager.store.load(second.get_json()["id"])
        assert queued["status"] == "pending"
        assert queued["queue"]["sequence"] > manager.store.load(task_id)["queue"]["sequence"]

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
    """日志接口：框架日志优先，console 兜底同样返回原文。"""

    def test_console_fallback_preserves_raw_output(self, client, monkeypatch):
        test_client, manager = client
        script = "print('Authorization: Bearer supersecret123')"
        patch_command(monkeypatch, manager, script)
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        manager.wait_idle()
        task_id = submitted.get_json()["id"]

        logs = test_client.get(f"/api/tasks/{task_id}/logs").get_json()
        assert logs["source"] == "console"
        text = "\n".join(logs["lines"])
        assert "supersecret123" in text

    def test_console_fallback_keeps_latest_bounded_tail(self, client, monkeypatch):
        """Console 响应先取最新内容再限长，必须保留真正的末尾错误。"""
        test_client, manager = client
        script = "print('BEGIN-' + 'x' * 12000 + '-FINAL-CONSOLE-ERROR')"
        patch_command(monkeypatch, manager, script)
        submitted = test_client.post(
            "/api/tasks", json={"env": "test", "run_type": "single"}
        )
        manager.wait_idle()
        task_id = submitted.get_json()["id"]

        logs = test_client.get(f"/api/tasks/{task_id}/logs").get_json()
        text = "\n".join(logs["lines"])

        assert logs["source"] == "console"
        assert "FINAL-CONSOLE-ERROR" in text
        assert "BEGIN-" not in text
        assert len(text) <= 10_000

    def test_v3_console_fallback_uses_project_runtime_path(self, client):
        """V3 无 framework log 时应读取项目隔离的 runtime console。

        新队列中的单接口、Flow 与批次任务都使用 V3，并由 TaskManager 把
        console 写入 ``runtime/<project>/<task>/console.log``。此处同时放置
        一个旧目录诱饵，确保接口不会错误回退到 ``tasks/<task>``。
        """

        test_client, manager = client
        task_id = "20260830-120000-a3b3"
        manager.store.save(
            {
                "schema_version": 3,
                "id": task_id,
                "status": "failed",
                "project": {"project_id": "dating"},
                "runtime": {"target_env": "test"},
                "selection": {
                    "run_type": "single",
                    "api_id": "GetMe",
                    "case_id": "get_me_success",
                },
                "log_file": None,
            }
        )
        runtime_console = manager.store.console_log_path(task_id, "dating")
        runtime_console.parent.mkdir(parents=True, exist_ok=True)
        runtime_console.write_text("V3-RUNTIME-CONSOLE", encoding="utf-8")
        legacy_console = manager.store.console_log_path(task_id)
        legacy_console.parent.mkdir(parents=True, exist_ok=True)
        legacy_console.write_text("WRONG-LEGACY-CONSOLE", encoding="utf-8")

        logs = test_client.get(f"/api/tasks/{task_id}/logs").get_json()
        text = "\n".join(logs["lines"])

        assert logs["source"] == "console"
        assert "V3-RUNTIME-CONSOLE" in text
        assert "WRONG-LEGACY-CONSOLE" not in text

    def test_framework_log_keeps_latest_bounded_tail(self, client):
        """Framework 单行日志也必须受字符上限约束并保留真正尾部。"""
        test_client, manager = client
        task_id = "20260828-120000-abcd"
        log_path = manager._project_root / "logs/dating/test/2026-08-28/raw.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "BEGIN-" + "x" * 12000 + "-FINAL-FRAMEWORK-ERROR",
            encoding="utf-8",
        )
        manager.store.save(
            {
                "schema_version": 2,
                "id": task_id,
                "status": "failed",
                "project": {"project_id": "dating"},
                "runtime": {"target_env": "test"},
                "log_file": log_path.relative_to(manager._project_root).as_posix(),
            }
        )

        logs = test_client.get(f"/api/tasks/{task_id}/logs").get_json()
        text = "\n".join(logs["lines"])

        assert logs["source"] == "framework_log"
        assert "FINAL-FRAMEWORK-ERROR" in text
        assert "BEGIN-" not in text
        assert len(text) <= 10_000

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

    def test_v3_report_uses_project_path_and_validates_project_binding(
        self, client, fake_project
    ):
        """V3 任务必须从项目隔离目录读取报告，并校验报告所属项目。"""

        test_client, manager = client
        task_id = "20260101-000000-0003"
        manager.store.save(
            {
                "id": task_id,
                "schema_version": 3,
                "status": "succeeded",
                "created_at": "2026-01-01T00:00:00+00:00",
                "project": {
                    "platform_project_id": "dating-platform",
                    "project_id": "dating",
                    "display_name": "Dating",
                },
            }
        )
        report_dir = (
            fake_project
            / "reports"
            / "task-reports"
            / "dating"
            / task_id
            / "current"
        )
        report_dir.mkdir(parents=True)
        (report_dir / "index.html").write_text(
            "<html>dating v3 report</html>", encoding="utf-8"
        )
        meta_path = report_dir / "report-meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "project_id": "dating",
                    "source": "task-manager",
                }
            ),
            encoding="utf-8",
        )

        meta = test_client.get(f"/api/report/meta?task_id={task_id}")
        page = test_client.get(f"/reports/{task_id}/index.html")

        assert meta.status_code == 200
        assert meta.get_json()["exists"] is True
        assert page.status_code == 200
        assert "dating v3 report" in page.get_data(as_text=True)

        # 同一 task_id 下若元数据声称属于其他项目，也必须 fail-closed。
        meta_path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "project_id": "truthy",
                    "source": "task-manager",
                }
            ),
            encoding="utf-8",
        )
        assert (
            test_client.get(f"/api/report/meta?task_id={task_id}").get_json()[
                "exists"
            ]
            is False
        )

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


class TestMultiProjectWebContract:
    """最终七页与业务 API 契约，覆盖 Scope 交集、预检和任务 V2。"""

    @staticmethod
    def _enable_flow_file_inputs(multi_project_root: Path) -> None:
        """给临时 Dating Flow 增加图片输入契约，避免测试依赖生产资产副本。"""

        flow_path = (
            multi_project_root
            / "projects"
            / "dating"
            / "data"
            / "flows"
            / "dating_demo_flow.yaml"
        )
        with flow_path.open("a", encoding="utf-8") as file:
            file.write(
                "\ninputs:\n"
                "  media_files:\n"
                "    type: files\n"
                "    required: true\n"
                "    min_items: 1\n"
                "    max_items: 9\n"
                "    allowed_content_types: [image/jpeg, image/png, image/webp]\n"
                "    max_size_bytes: 7000000\n"
                "    label: 分析图片\n"
                "    description: 按聊天顺序选择图片\n"
            )

    @staticmethod
    def _platform_client(
        multi_project_root,
        monkeypatch,
        runtime_normal=None,
        credential_provider=None,
    ):
        """构造平台模式应用；所有外部响应均为完整的 Scope 契约夹具。"""

        settings = make_settings("/api-autotest")
        settings.update(
            {
                "config_source": "platform",
                "platform_api_url": "http://platform.invalid/api/v1",
                "platform_environment": "dev",
            }
        )
        token_file = multi_project_root / "platform-client-token"
        token_file.write_text("tool-token", encoding="utf-8")
        settings["platform_client_token_file"] = str(token_file)
        calls: list[tuple[str, dict]] = []
        if runtime_normal is None:
            runtime_normal = {
                "gateway.base_url": "https://gateway.test.invalid",
                "gateway.path": "/gateway/invoke",
                "gateway.comm": {"platform": "ios", "locale": "zh-Hans-CN"},
                "flow.analysis.poll_interval_seconds": 1,
                "flow.analysis.timeout_seconds": 120,
            }
        if credential_provider is None:
            credential_provider = {
                "status": "healthy", "credential_version": 4
            }

        scopes = [
            {
                "id": "scope-truthy-dev-test",
                "runtime_scope_id": "scope-truthy-dev-test",
                "tool_id": "api-autotest",
                "platform_project_id": "platform-truthy",
                "project_id": "truthy",
                "display_name": "Truthy Gateway",
                "platform_environment": "dev",
                "target_env": "test",
                "status": "active",
                "release": {"id": "release-truthy-v2", "version": 2, "status": "active"},
                "credential_profiles": [
                    {"id": "truthy_session", "status": "ready", "version": 2}
                ],
                "management_url": "/settings/config?scope_id=scope-truthy-dev-test",
            },
            {
                "id": "scope-dating-dev-test",
                "runtime_scope_id": "scope-dating-dev-test",
                "tool_id": "api-autotest",
                "platform_project_id": "platform-dating",
                "project_id": "dating",
                "display_name": "Dating AI Assistant",
                "platform_environment": "dev",
                "target_env": "test",
                "status": "active",
                "release": {"id": "release-dating-v3", "version": 3, "status": "active"},
                "credential_profiles": [
                    {"id": "anonymous_session", "status": "ready", "version": 4}
                ],
                "management_url": "/settings/config?scope_id=scope-dating-dev-test",
            },
            {
                "id": "scope-not-deployed",
                "runtime_scope_id": "scope-not-deployed",
                "tool_id": "api-autotest",
                "platform_project_id": "platform-ghost",
                "project_id": "ghost",
                "display_name": "Ghost",
                "platform_environment": "dev",
                "target_env": "test",
                "status": "active",
                "release": {"id": "release-ghost", "version": 1, "status": "active"},
                "credential_profiles": [],
            },
        ]

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/internal/tools/api-autotest/runtime-scopes"):
                return _FakeRuntimeConfigResponse({"items": scopes})
            if url.endswith("/internal/tools/api-autotest/runtime-config"):
                return _FakeRuntimeConfigResponse(
                    {
                        "tool_id": "api-autotest",
                        "project_id": "dating",
                        "runtime_scope_id": "scope-dating-dev-test",
                        "platform_project_id": "platform-dating",
                        "environment": "dev",
                        "target_env": "test",
                        "release_id": "release-dating-v3",
                        "release_version": 3,
                        "snapshot_selector": {
                            "runtime_scope_id": "scope-dating-dev-test",
                            "release_id": "release-dating-v3",
                            "release_version": 3,
                        },
                        "configured_secret_keys": ["ACCESS_TOKEN"],
                        "credential_metadata": {
                            "providers": {
                                "gateway_session": {
                                    **credential_provider
                                },
                                "admin_login": {"status": "missing"},
                            }
                        },
                        "normal": runtime_normal,
                        "secrets": {},
                        "management_url": "/settings/config?scope_id=scope-dating-dev-test",
                    }
                )
            raise AssertionError(f"unexpected GET {url}")

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/internal/tools/api-autotest/runtime-contexts"):
                project_id = kwargs["json"]["project_id"]
                assert project_id in {"truthy", "dating"}
                scope_id = f"scope-{project_id}-dev-test"
                return _FakeRuntimeConfigResponse(
                    {
                        "runtime_context_id": f"rtx-{project_id}-user-1",
                        "expires_at": "2026-08-27T18:00:00Z",
                        "project_id": project_id,
                        "runtime_scope_id": scope_id,
                        "platform_project_id": f"platform-{project_id}",
                        "platform_environment": "dev",
                        "target_env": "test",
                        "resource_snapshot": {
                            "owner_user_id": "user-1",
                            "access_scope_snapshot": "project",
                            "project_id_snapshot": f"platform-{project_id}",
                            "authorization_source_snapshot": "project-member",
                        },
                    }
                )
            if url.endswith("/internal/tools/api-autotest/runtime-config/dispatch-materialize"):
                return _FakeRuntimeConfigResponse(
                    {
                        "tool_id": "api-autotest",
                        "project_id": "dating",
                        "runtime_scope_id": "scope-dating-dev-test",
                        "platform_project_id": "platform-dating",
                        "environment": "dev",
                        "target_env": "test",
                        "release_id": "release-dating-v3",
                        "release_version": 3,
                        "normal": runtime_normal,
                        "secrets": {"ACCESS_TOKEN": "runtime-only-secret"},
                        "credential_metadata": {
                            "providers": {
                                "gateway_session": {
                                    "status": "healthy",
                                    "credential_id": "credential-dating-session",
                                    "credential_version": 4,
                                }
                            }
                        },
                        "configured_secret_keys": ["ACCESS_TOKEN"],
                    }
                )
            if url.endswith("/internal/tools/api-autotest/resource-access/check"):
                return _FakeRuntimeConfigResponse(
                    {
                        "allowed": True,
                        "user_id": "user-1",
                        "data_scope": "global",
                        "managed_project_ids": [],
                    }
                )
            if url.endswith("/internal/tools/api-autotest/audit-events"):
                return _FakeRuntimeConfigResponse({})
            raise AssertionError(f"unexpected POST {url}")

        monkeypatch.setattr("web.app.requests.get", fake_get)
        monkeypatch.setattr("web.app.requests.post", fake_post)
        app = create_app(project_root=multi_project_root, settings=settings)
        app.config["TESTING"] = True
        client = app.test_client()
        client.set_cookie("tp_csrf", "csrf-token")
        return client, app.config["AUTOTEST_MANAGER"], calls

    def test_seven_pages_render_and_refresh_under_base_path(
        self, multi_project_root, monkeypatch
    ):
        client, manager, _calls = self._platform_client(multi_project_root, monkeypatch)
        task_id = "20260827-120000-a1b2"
        manager.store.save(
            {
                "schema_version": 2,
                "id": task_id,
                "status": "succeeded",
                "project": {"project_id": "dating", "display_name": "Dating AI Assistant"},
                "runtime": {"target_env": "test"},
                "selection": {"run_type": "single", "api_id": "GetMe"},
                "created_at": "2026-08-27T12:00:00+08:00",
                "resource_snapshot": {},
            }
        )
        headers = {
            "X-Platform-Resource-Context": "opaque-global",
            "X-Platform-User-Context": "signed-user",
        }
        expected_pages = {
            "/api-autotest/": "overview",
            "/api-autotest/projects": "projects",
            "/api-autotest/tasks/new?mode=single": "task-new",
            "/api-autotest/tasks/new?mode=flow": "task-new",
            "/api-autotest/tasks/new?mode=batch": "task-new",
            "/api-autotest/catalog": "catalog",
            "/api-autotest/tasks": "tasks",
            f"/api-autotest/tasks/{task_id}": "task-detail",
        }
        for path, page_name in expected_pages.items():
            response = client.get(path, headers=headers)
            assert response.status_code == 200, path
            body = response.get_data(as_text=True)
            assert f'data-page="{page_name}"' in body
            assert 'href="/api-autotest/projects"' in body
            assert "项目配置" not in body
            assert "配置异常" not in body
            assert "保存草稿" not in body

        assert client.get("/api-autotest/tasks/new/single").status_code == 302
        assert client.get("/api-autotest/tasks/new/flow").status_code == 302
        batch_page = client.get(
            "/api-autotest/tasks/new?mode=batch", headers=headers
        ).get_data(as_text=True)
        # 产品契约统一使用“批量回归”，避免导航与 PRD、页面标题出现两套术语。
        assert ">批量回归</a>" in batch_page
        assert "加入执行队列（0）" in batch_page
        app_script = client.get("/api-autotest/static/app.js").get_data(as_text=True)
        assert "加入执行队列（${selectedCount}）" in app_script
        flow_page = client.get(
            "/api-autotest/tasks/new?mode=flow", headers=headers
        ).get_data(as_text=True)
        assert 'id="task-media-files"' in flow_page
        assert 'multiple' in flow_page
        assert 'accept="image/jpeg,image/png,image/webp"' in flow_page
        assert 'id="task-media-error"' in flow_page
        assert 'aria-live="polite"' in flow_page
        assert 'id="task-input-summary"' in flow_page
        assert 'id="task-runtime-inputs"' in flow_page
        assert 'id="runtime-input-fields"' in flow_page
        assert 'id="runtime-input-reset-all"' in flow_page
        assert 'id="runtime-input-empty"' in flow_page
        assert "当前测试资产没有可修改的静态请求参数" in flow_page

        single_page = client.get(
            "/api-autotest/tasks/new?mode=single", headers=headers
        ).get_data(as_text=True)
        assert 'id="runtime-input-empty"' in single_page
        assert "当前测试资产没有可修改的静态请求参数" in single_page

        detail_page = client.get(
            f"/api-autotest/tasks/{task_id}", headers=headers
        ).get_data(as_text=True)
        assert 'id="detail-attachments"' in detail_page
        assert 'id="detail-attachment-list"' in detail_page
        assert 'id="detail-runtime-overrides"' in detail_page
        assert 'id="task-retry-edit"' in detail_page

    def test_projects_are_scope_package_intersection_and_catalog_is_project_scoped(
        self, multi_project_root, monkeypatch
    ):
        client, _manager, _calls = self._platform_client(multi_project_root, monkeypatch)
        headers = {"X-Platform-User-Context": "signed-user"}
        projects = client.get("/api-autotest/api/projects", headers=headers).get_json()

        assert projects["total"] == 2
        assert [item["project_id"] for item in projects["items"]] == ["dating", "truthy"]
        assert all(item["target_env"] == "test" for item in projects["items"])
        assert projects["items"][0]["counts"] == {"apis": 1, "cases": 1, "flows": 1}

        catalog = client.get(
            "/api-autotest/api/catalog?project_id=dating&type=apis",
            headers=headers,
        ).get_json()
        assert catalog["project_id"] == "dating"
        assert [item["id"] for item in catalog["apis"]] == ["GetMe"]
        assert catalog["cases"][0]["id"] == "get_me_success"
        assert catalog["cases"][0]["batch_eligible"] is True
        assert catalog["cases"][0]["risk_tags"] == []
        assert catalog["flows"][0]["id"] == "dating_demo_flow"
        assert catalog["flows"][0]["steps"] == [
            {
                "id": "get_me",
                "kind": "api",
                "api_id": "GetMe",
                "name": "Dating AI Assistant 当前用户",
            }
        ]

    def test_selected_case_batch_preflight_and_submit_use_one_v3_task(
        self, multi_project_root, monkeypatch
    ):
        """Web 批次提交保存一个任务和两个逻辑子项，不拆 Runtime Context。"""

        case_path = (
            multi_project_root
            / "projects/dating/data/cases/GetMe.yaml"
        )
        document = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        second = deepcopy(document["cases"][0])
        second["id"] = "get_me_second"
        second["name"] = "再次获取当前用户"
        second["tags"] = ["regression"]
        document["cases"].append(second)
        case_path.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        client, manager, _calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        patch_command(monkeypatch, manager, "print('batch')")
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        catalog = client.get(
            "/api-autotest/api/catalog?project_id=dating",
            headers=headers,
        ).get_json()
        items = [
            {
                "asset_id": item["asset_id"],
                "asset_revision": item["asset_revision"],
            }
            for item in catalog["cases"]
        ]
        payload = {
            "project_id": "dating",
            "run_type": "batch",
            "batch_type": "cases",
            "selection_mode": "selected",
            "items": items,
            "tag_filters": [],
            "risk_acknowledgements": [],
        }

        preflight = client.post(
            "/api-autotest/api/preflight", headers=headers, json=payload
        )
        assert preflight.status_code == 200
        preflight_body = preflight.get_json()
        assert preflight_body["ready"] is True
        assert preflight_body["batch"]["item_count"] == 2
        assert preflight_body["queue"]["capacity"] == 20

        submitted = client.post(
            "/api-autotest/api/tasks", headers=headers, json=payload
        )
        assert submitted.status_code == 201
        stored = manager.store.load(submitted.get_json()["id"])
        assert stored["schema_version"] == 3
        assert stored["batch"]["item_count"] == 2
        manager.wait_idle()
        stored = manager.store.load(submitted.get_json()["id"])
        assert stored["runtime"]["credential_profiles"] == [
            {"id": "anonymous_session", "status": "ready", "version": 4}
        ]
        assert catalog["flows"][0]["credential_profiles"] == [
            "anonymous_session"
        ]

        # 项目切换本身不执行 API，不能因为项目内某个可选 Profile 缺失而禁用；
        # 真正提交单接口/Flow 时再按所选资产严格校验。
        context = client.get(
            "/api-autotest/api/projects/truthy/context",
            headers=headers,
        ).get_json()
        assert context["preflight"]["ready"] is True
        assert context["preflight"]["profiles"] == [
            {
                "id": "truthy_session",
                "status": "missing",
                "version": None,
                "provider_type": "truthy_session",
                "expires_at": None,
                "refresh_expires_at": None,
                "last_checked_at": None,
                "last_error_code": None,
                "reason": "当前 Runtime Scope 尚未配置该凭证",
                "management_url": (
                    "/account/credentials?"
                    "scope_id=scope-truthy-dev-test&provider_type=truthy_session"
                ),
            }
        ]

    def test_flow_batch_preflight_keeps_preview_and_file_contract_when_files_missing(
        self, multi_project_root, monkeypatch
    ):
        """缺图片时仍返回已解析批次和权威文件契约，供页面修正输入。"""

        flow_path = (
            multi_project_root
            / "projects/dating/data/flows/dating_demo_flow.yaml"
        )
        document = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
        document["tags"] = ["interactive"]
        document["inputs"] = {
            "media_files": {
                "type": "files",
                "required": True,
                "min_items": 1,
                "max_items": 9,
                "allowed_content_types": ["image/jpeg", "image/png"],
                "max_size_bytes": 7_000_000,
                "label": "聊天截图",
            }
        }
        flow_path.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        client, _manager, _calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        catalog = client.get(
            "/api-autotest/api/catalog?project_id=dating", headers=headers
        ).get_json()
        flow = next(item for item in catalog["flows"] if item["id"] == "dating_demo_flow")

        response = client.post(
            "/api-autotest/api/preflight",
            headers=headers,
            json={
                "project_id": "dating",
                "run_type": "batch",
                "batch_type": "flows",
                "selection_mode": "selected",
                "items": [
                    {
                        "asset_id": flow["id"],
                        "asset_revision": flow["asset_revision"],
                    }
                ],
                "tag_filters": [],
                "risk_acknowledgements": [],
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["ready"] is False
        assert body["batch"]["item_count"] == 1
        assert body["batch"]["resolved_count"] == 1
        assert body["batch"]["input_contract"] == document["inputs"]["media_files"]
        assert body["errors"][0]["code"] == "TASK_INPUTS_REQUIRED"

    def test_batch_submit_reports_contract_conflict_before_missing_files(
        self, multi_project_root, monkeypatch
    ):
        """直接提交不兼容图片 Flow 时也必须优先返回契约冲突。"""

        flow_dir = multi_project_root / "projects/dating/data/flows"
        scenario_dir = multi_project_root / "projects/dating/data/scenarios"
        base_flow = yaml.safe_load(
            (flow_dir / "dating_demo_flow.yaml").read_text(encoding="utf-8")
        )
        base_scenario = yaml.safe_load(
            (scenario_dir / "dating_demo_flow.yaml").read_text(encoding="utf-8")
        )
        contract = {
            "type": "files",
            "required": True,
            "min_items": 1,
            "max_items": 9,
            "allowed_content_types": ["image/jpeg", "image/png"],
            "max_size_bytes": 7_000_000,
        }
        for flow_id, maximum in (
            ("media_flow_nine", 9),
            ("media_flow_eight", 8),
        ):
            flow_document = deepcopy(base_flow)
            flow_document["tags"] = ["interactive"]
            flow_document["inputs"] = {
                "media_files": {**contract, "max_items": maximum}
            }
            (flow_dir / f"{flow_id}.yaml").write_text(
                yaml.safe_dump(flow_document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            (scenario_dir / f"{flow_id}.yaml").write_text(
                yaml.safe_dump(base_scenario, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        client, _manager, _calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        catalog = client.get(
            "/api-autotest/api/catalog?project_id=dating", headers=headers
        ).get_json()
        by_id = {item["id"]: item for item in catalog["flows"]}

        response = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json={
                "project_id": "dating",
                "run_type": "batch",
                "batch_type": "flows",
                "selection_mode": "selected",
                "items": [
                    {
                        "asset_id": flow_id,
                        "asset_revision": by_id[flow_id]["asset_revision"],
                    }
                    for flow_id in ("media_flow_nine", "media_flow_eight")
                ],
                "tag_filters": [],
                "risk_acknowledgements": [],
            },
        )

        assert response.status_code == 400
        assert response.get_json()["error_code"] == "BATCH_INPUT_CONTRACT_CONFLICT"

    def test_catalog_exposes_real_multi_image_contract_and_nested_business_steps(
        self, project_root
    ):
        """目录必须暴露文件约束和 foreach 内真实步骤，供表单动态渲染。"""

        from web.catalog import build_catalog

        catalog = build_catalog(project_root, "dating")
        flow = next(
            item for item in catalog["flows"]
            if item["id"] == "multi_image_analysis"
        )

        assert flow["name"] == "multi_image_analysis"
        assert flow["display_name"] == "Dating 多图 Analysis 保留结果链路"
        assert flow["inputs"] == {
            "media_files": {
                "type": "files",
                "required": True,
                "min_items": 1,
                "max_items": 9,
                "allowed_content_types": [
                    "image/jpeg",
                    "image/png",
                    "image/webp",
                ],
                "max_size_bytes": 7000000,
                "label": "分析图片",
                "description": "按聊天顺序选择 1～9 张图片",
            }
        }
        # foreach 内三个上传步骤仍按业务步骤展开；正式 Result 后新增的 Debug
        # 与 Cost 也必须进入目录计数和预览，确保 Web 与真实执行拓扑一致。
        assert flow["step_count"] == 10
        assert [step["id"] for step in flow["steps"]] == [
            "get_upload_config",
            "validate_media_files",
            "prepare_upload",
            "upload_binary",
            "complete_upload",
            "create_analysis",
            "poll_analysis",
            "get_analysis_result",
            "get_task_debug",
            "get_provider_cost",
        ]
        repeated = flow["steps"][2:5]
        assert all(step["repeat_for"] == "media_files" for step in repeated)
        assert all(step["parent_id"] == "upload_media_files" for step in repeated)

    def test_file_input_preflight_and_multipart_submit_use_real_uploaded_images(
        self, multi_project_root, monkeypatch
    ):
        """文件型 Flow 可同时提交真实图片与声明内的普通运行参数。"""

        self._enable_flow_file_inputs(multi_project_root)
        client, manager, calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        patch_command(
            monkeypatch,
            manager,
            "import json, os; "
            "path = os.environ['API_AUTOTEST_TASK_INPUT_MANIFEST_FILE']; "
            "manifest = json.load(open(path, encoding='utf-8')); "
            "assert len(manifest['media_files']) == 2; "
            "assert manifest['media_files'][0]['original_name'] == 'chat_01.png'; "
            "asset_path = os.environ['API_AUTOTEST_EXECUTION_ASSET_FILE']; "
            "asset = json.load(open(asset_path, encoding='utf-8')); "
            "params = asset['resolved_execution_asset']['flow_case']['scenario']"
            "['step_data']['get_me']['params']; "
            "assert params['locale'] == 'zh-CN'; "
            "print('ok')",
        )
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        selection = {
            "project_id": "dating",
            "run_type": "flow",
            "flow_id": "dating_demo_flow",
        }

        missing = client.post(
            "/api-autotest/api/preflight", headers=headers, json=selection
        ).get_json()
        assert missing["ready"] is False
        assert missing["errors"][0]["code"] == "TASK_INPUTS_REQUIRED"
        assert missing["asset"]["inputs"]["media_files"] == {
            "type": "files",
            "required": True,
            "min_items": 1,
            "max_items": 9,
            "allowed_content_types": [
                "image/jpeg",
                "image/png",
                "image/webp",
            ],
            "max_size_bytes": 7_000_000,
            "label": "分析图片",
            "description": "按聊天顺序选择图片",
        }
        selection = {
            **selection,
            "asset_revision": missing["asset"]["asset_revision"],
            "runtime_overrides": {"client_locale": "zh-CN"},
        }

        input_metadata = {
            "media_files": [
                {
                    "name": "chat_01.png",
                    "content_type": "image/png",
                    "size_bytes": 13,
                },
                {
                    "name": "chat_02.png",
                    "content_type": "image/png",
                    "size_bytes": 13,
                },
            ]
        }
        ready = client.post(
            "/api-autotest/api/preflight",
            headers=headers,
            json={**selection, "inputs": input_metadata},
        ).get_json()
        assert ready["ready"] is True
        assert all(
            "inputs" not in call[1].get("json", {})
            for call in calls
        )

        json_submit = client.post(
            "/api-autotest/api/tasks", headers=headers, json=selection
        )
        assert json_submit.status_code == 400
        assert json_submit.get_json()["error_code"] == "TASK_INPUTS_REQUIRED"

        png = b"\x89PNG\r\n\x1a\nimage"
        submitted = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            data={
                "task_payload": json.dumps(selection),
                "media_files": [
                    (BytesIO(png), "chat_01.png", "image/png"),
                    (BytesIO(png), "chat_02.png", "image/png"),
                ],
            },
            content_type="multipart/form-data",
        )
        assert submitted.status_code == 201, submitted.get_json()
        manager.wait_idle()
        record = manager.store.load(submitted.get_json()["id"])
        assert record["status"] == "succeeded", record
        assert [item["original_name"] for item in record["attachments"]] == [
            "chat_01.png",
            "chat_02.png",
        ]
        assert record["input"]["runtime_overrides"] == {
            "client_locale": "zh-CN"
        }
        manifest_path = multi_project_root / record["input_manifest_file"]
        assert manifest_path.is_file()
        assert manifest_path.stat().st_mode & 0o777 == 0o600

    def test_flow_preflight_and_submit_allow_auto_discovered_static_param(
        self, multi_project_root, monkeypatch
    ):
        """Flow 未声明的静态请求参数也应通过公开契约进入当前任务快照。"""

        scenario_path = (
            multi_project_root
            / "projects"
            / "dating"
            / "data"
            / "scenarios"
            / "dating_demo_flow.yaml"
        )
        scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
        scenario["step_data"]["get_me"]["params"]["tone"] = "yaml-default"
        scenario_path.write_text(
            yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        client, manager, _calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        patch_command(
            monkeypatch,
            manager,
            "import json, os; "
            "asset_path = os.environ['API_AUTOTEST_EXECUTION_ASSET_FILE']; "
            "asset = json.load(open(asset_path, encoding='utf-8')); "
            "params = asset['resolved_execution_asset']['flow_case']['scenario']"
            "['step_data']['get_me']['params']; "
            "assert params['tone'] == 'tester-entered-value'; "
            "assert params['locale'] == 'en-US'; "
            "print('ok')",
        )
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        selection = {
            "project_id": "dating",
            "run_type": "flow",
            "flow_id": "dating_demo_flow",
        }

        preflight = client.post(
            "/api-autotest/api/preflight", headers=headers, json=selection
        )
        assert preflight.status_code == 200
        preflight_body = preflight.get_json()
        assert preflight_body["ready"] is True
        assert [
            field["key"] for field in preflight_body["asset"]["runtime_inputs"]
        ] == ["client_locale", "get_me__tone"]
        assert "target" not in json.dumps(preflight_body["asset"])

        payload = {
            **selection,
            "asset_revision": preflight_body["asset"]["asset_revision"],
            "runtime_overrides": {"get_me__tone": "tester-entered-value"},
        }
        override_preflight = client.post(
            "/api-autotest/api/preflight", headers=headers, json=payload
        )
        assert override_preflight.status_code == 200
        assert override_preflight.get_json()["ready"] is True

        submitted = client.post(
            "/api-autotest/api/tasks", headers=headers, json=payload
        )
        assert submitted.status_code == 201, submitted.get_json()
        manager.wait_idle()
        record = manager.store.load(submitted.get_json()["id"])
        assert record["status"] == "succeeded", record
        assert record["input"]["runtime_overrides"] == {
            "get_me__tone": "tester-entered-value"
        }

    def test_single_task_rejects_uploaded_images(
        self, multi_project_root, monkeypatch
    ):
        """图片只属于声明文件输入的 Flow，单接口任务不能夹带附件。"""

        client, _manager, _calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        selection = {
            "project_id": "dating",
            "run_type": "single",
            "api_id": "GetMe",
            "case_id": "get_me_success",
        }
        response = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            data={
                "task_payload": json.dumps(selection),
                "media_files": (
                    BytesIO(b"\x89PNG\r\n\x1a\nimage"),
                    "chat.png",
                    "image/png",
                ),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 400
        assert response.get_json()["error_code"] == "TASK_INPUTS_NOT_ALLOWED"

    def test_preflight_and_submit_allow_declared_runtime_overrides(
        self, multi_project_root, monkeypatch
    ):
        client, manager, calls = self._platform_client(multi_project_root, monkeypatch)
        patch_command(
            monkeypatch,
            manager,
            "import os; "
            "assert os.environ['PLATFORM_CREDENTIAL_ID'] == 'credential-dating-session'; "
            "assert os.environ['PLATFORM_CREDENTIAL_VERSION'] == '4'; print('ok')",
        )
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        selection = {
            "project_id": "dating",
            "run_type": "single",
            "api_id": "GetMe",
            "case_id": "get_me_success",
        }

        preflight = client.post(
            "/api-autotest/api/preflight", headers=headers, json=selection
        )
        assert preflight.status_code == 200
        preflight_body = preflight.get_json()
        assert preflight_body["ready"] is True
        assert preflight_body["asset"]["runtime_input_count"] == 1
        assert preflight_body["asset"]["runtime_inputs"][0]["key"] == "client_locale"
        assert "target" not in json.dumps(preflight_body["asset"])
        assert preflight_body["runtime"]["scope_id"] == "scope-dating-dev-test"
        assert preflight_body["runtime"]["target_env"] == "test"
        assert preflight_body["profiles"] == [
            {"id": "anonymous_session", "status": "ready", "version": 4}
        ]

        revision = preflight_body["asset"]["asset_revision"]
        overridden = {
            **selection,
            "asset_revision": revision,
            "runtime_overrides": {"client_locale": "zh-CN"},
        }
        override_preflight = client.post(
            "/api-autotest/api/preflight",
            headers=headers,
            json=overridden,
        )
        assert override_preflight.status_code == 200
        override_body = override_preflight.get_json()
        assert override_body["ready"] is True
        assert override_body["asset"]["applied_overrides"] == [
            {
                "key": "client_locale",
                "label": "客户端语言",
                "base_value": "en-US",
                "override_value": "zh-CN",
                "resolved_value": "zh-CN",
            }
        ]

        for forbidden in (
            "target_env",
            "gateway_url",
            "release_id",
            "timeout",
            "poll_interval_seconds",
            "secrets",
            "runtime_scope_id",
        ):
            response = client.post(
                "/api-autotest/api/tasks",
                headers=headers,
                json={**selection, forbidden: "browser-override"},
            )
            assert response.status_code == 400, forbidden
            assert response.get_json()["error_code"] == "INVALID_PARAMS"

        submitted = client.post(
            "/api-autotest/api/tasks", headers=headers, json=overridden
        )
        assert submitted.status_code == 201
        manager.wait_idle()
        task_id = submitted.get_json()["id"]
        record = manager.store.load(task_id)
        assert record["schema_version"] == 3
        assert record["status"] == "succeeded", record
        assert record["project"]["project_id"] == "dating"
        assert record["runtime"]["runtime_scope_id"] == "scope-dating-dev-test"
        assert record["runtime"]["target_env"] == "test"
        assert record["selection"]["api_id"] == "GetMe"
        assert record["selection"]["case_id"] == "get_me_success"
        assert record["input"]["runtime_overrides"] == {
            "client_locale": "zh-CN"
        }
        public = client.get(
            f"/api-autotest/api/tasks/{task_id}",
            headers={"X-Platform-Resource-Context": "opaque-global"},
        ).get_json()
        assert public["asset_snapshot"]["override_count"] == 1
        serialized_public = json.dumps(public, ensure_ascii=False)
        assert "resolved_execution_asset" not in serialized_public
        assert "runtime_input_definitions" not in serialized_public
        assert '"target"' not in serialized_public
        assert not any(
            call[1].get("json", {}).get("target_env") == "browser-override"
            for call in calls
        )

    def test_preflight_and_submit_allow_auto_discovered_case_parameter(
        self, multi_project_root, monkeypatch
    ):
        """Case 无 runtime_inputs 时仍可提交任意同类型静态请求参数值。"""

        case_path = (
            multi_project_root
            / "projects"
            / "dating"
            / "data"
            / "cases"
            / "GetMe.yaml"
        )
        document = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        selected_case = document["cases"][0]
        selected_case.pop("runtime_inputs")
        selected_case["request"]["params"] = {
            "locale": "en-US",
            "note": "yaml-default",
        }
        case_path.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        client, manager, _calls = self._platform_client(
            multi_project_root,
            monkeypatch,
        )
        patch_command(monkeypatch, manager, "print('ok')")
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        selection = {
            "project_id": "dating",
            "run_type": "single",
            "api_id": "GetMe",
            "case_id": "get_me_success",
        }

        preflight = client.post(
            "/api-autotest/api/preflight",
            headers=headers,
            json=selection,
        ).get_json()
        fields = {item["key"]: item for item in preflight["asset"]["runtime_inputs"]}
        assert set(fields) == {"locale", "note"}
        assert fields["note"]["type"] == "string"
        assert fields["note"]["options"] == []

        submitted = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json={
                **selection,
                "asset_revision": preflight["asset"]["asset_revision"],
                "runtime_overrides": {
                    "locale": "fr-CA",
                    "note": "tester supplied value",
                },
            },
        )
        assert submitted.status_code == 201, submitted.get_json()
        manager.wait_idle()
        record = manager.store.load(submitted.get_json()["id"])
        assert record["status"] == "succeeded"
        assert record["input"]["runtime_overrides"] == {
            "locale": "fr-CA",
            "note": "tester supplied value",
        }

    def test_runtime_override_errors_and_stale_revision_use_stable_contracts(
        self,
        multi_project_root,
        monkeypatch,
    ):
        """Preflight 返回字段错误，Task 提交按输入/竞态分别返回 400/409。"""
        client, manager, _calls = self._platform_client(
            multi_project_root,
            monkeypatch,
        )
        patch_command(monkeypatch, manager, "print('must-not-run')")
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
        }
        selection = {
            "project_id": "dating",
            "run_type": "single",
            "api_id": "GetMe",
            "case_id": "get_me_success",
        }
        catalog = client.get(
            "/api-autotest/api/catalog?project_id=dating",
            headers=headers,
        ).get_json()
        case = catalog["cases"][0]

        unknown_payload = {
            **selection,
            "asset_revision": case["asset_revision"],
            "runtime_overrides": {"gateway_url": "https://forbidden.invalid"},
        }
        preflight = client.post(
            "/api-autotest/api/preflight",
            headers=headers,
            json=unknown_payload,
        )
        assert preflight.status_code == 200
        body = preflight.get_json()
        assert body["ready"] is False
        assert body["errors"][0]["code"] == "RUNTIME_OVERRIDE_UNKNOWN_KEY"
        assert body["errors"][0]["field_errors"] == [
            {"key": "gateway_url", "message": "字段未在当前 YAML 中开放"}
        ]

        rejected = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json=unknown_payload,
        )
        assert rejected.status_code == 400
        assert rejected.get_json()["error_code"] == "RUNTIME_OVERRIDE_UNKNOWN_KEY"

        stale = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json={
                **selection,
                "asset_revision": f"sha256:{'0' * 64}",
                "runtime_overrides": {"client_locale": "zh-CN"},
            },
        )
        assert stale.status_code == 409
        assert stale.get_json()["error_code"] == "RUNTIME_OVERRIDE_SCHEMA_CHANGED"
        assert manager.store.list() == []

    def test_preflight_explains_unready_dating_credential(
        self, multi_project_root, monkeypatch
    ):
        """资产预检必须展示未就绪 Profile 的真实状态、原因和修复入口。"""

        client, _manager, _calls = self._platform_client(
            multi_project_root,
            monkeypatch,
            credential_provider={
                "status": "action_required",
                "credential_id": "ucred-dating-session",
                "credential_version": 23,
                "expires_at": "2026-08-29T08:36:30+00:00",
                "refresh_expires_at": "2026-09-27T08:36:30+00:00",
                "last_checked_at": "2026-08-29T09:07:30+00:00",
                "last_error_code": "CREDENTIAL_REFRESH_HTTPSTATUSERROR",
            },
        )
        response = client.post(
            "/api-autotest/api/preflight",
            headers={
                "X-CSRF-Token": "csrf-token",
                "X-Platform-User-Context": "signed-user",
            },
            json={
                "project_id": "dating",
                "run_type": "single",
                "api_id": "GetMe",
                "case_id": "get_me_success",
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["ready"] is False
        assert body["profiles"] == [{
            "id": "anonymous_session",
            "provider_type": "gateway_session",
            "status": "action_required",
            "version": 23,
            "expires_at": "2026-08-29T08:36:30+00:00",
            "refresh_expires_at": "2026-09-27T08:36:30+00:00",
            "last_checked_at": "2026-08-29T09:07:30+00:00",
            "last_error_code": "CREDENTIAL_REFRESH_HTTPSTATUSERROR",
            "reason": "自动续期请求返回 HTTP 错误，需要重新配置或验证凭证",
            "management_url": (
                "/account/credentials?scope_id=scope-dating-dev-test"
                "&provider_type=gateway_session"
            ),
        }]
        error = body["errors"][0]
        assert error["code"] == "PROJECT_CREDENTIAL_MISSING"
        assert error["message"] == (
            "anonymous_session 凭证需要处理："
            "自动续期请求返回 HTTP 错误，需要重新配置或验证凭证"
        )
        assert error["scope_id"] == "scope-dating-dev-test"
        assert error["profile_details"] == body["profiles"]
        assert error["management_url"] == body["profiles"][0]["management_url"]

    def test_preflight_reports_manifest_config_keys_missing_from_release(
        self, multi_project_root, monkeypatch
    ):
        """Scope/Release 就绪也不能掩盖当前项目 Manifest 的缺失配置键。"""

        client, _manager, _calls = self._platform_client(
            multi_project_root,
            monkeypatch,
            runtime_normal={
                "gateway.base_url": "https://gateway.test.invalid",
                "gateway.path": "/gateway/invoke",
                "gateway.comm": {"platform": "ios"},
            },
        )
        response = client.post(
            "/api-autotest/api/preflight",
            headers={
                "X-CSRF-Token": "csrf-token",
                "X-Platform-User-Context": "signed-user",
            },
            json={
                "project_id": "dating",
                "run_type": "flow",
                "flow_id": "dating_demo_flow",
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["ready"] is False
        error = next(
            item for item in body["errors"]
            if item["code"] == "PROJECT_CONFIG_MISSING"
        )
        assert error["logical_keys"] == [
            "flow.analysis.poll_interval_seconds",
            "flow.analysis.timeout_seconds",
        ]

    def test_preflight_missing_asset_secret_links_to_scope_secret_page(
        self, multi_project_root, monkeypatch
    ):
        """资产专属 Secret 缺失时应指向同一 Scope 的 Secret 管理页。"""

        api_path = (
            multi_project_root
            / "projects"
            / "dating"
            / "data"
            / "apis"
            / "GetMe.yaml"
        )
        api = yaml.safe_load(api_path.read_text(encoding="utf-8"))
        api["transport"] = {
            "target": "dating_evaluation",
            "bearer_token_variable": "DATING_EVALUATION_API_KEY",
        }
        api_path.write_text(
            yaml.safe_dump(api, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        client, _manager, _calls = self._platform_client(
            multi_project_root,
            monkeypatch,
            runtime_normal={
                "gateway.base_url": "https://gateway.test.invalid",
                "gateway.path": "/gateway/invoke",
                "gateway.comm": {"platform": "ios"},
                "flow.analysis.poll_interval_seconds": 1,
                "flow.analysis.timeout_seconds": 120,
                "gateway.targets.dating_evaluation.base_url": (
                    "https://evaluation.test.invalid"
                ),
                "gateway.targets.dating_evaluation.path": "/admin/invoke",
            },
        )

        response = client.post(
            "/api-autotest/api/preflight",
            headers={
                "X-CSRF-Token": "csrf-token",
                "X-Platform-User-Context": "signed-user",
            },
            json={
                "project_id": "dating",
                "run_type": "single",
                "api_id": "GetMe",
                "case_id": "get_me_success",
            },
        )

        assert response.status_code == 200
        body = response.get_json()
        error = next(
            item
            for item in body["errors"]
            if item["code"] == "PROJECT_SECRET_MISSING"
        )
        assert error["logical_keys"] == ["DATING_EVALUATION_API_KEY"]
        assert error["management_url"] == (
            "/settings/secrets?scope_id=scope-dating-dev-test"
        )

    def test_task_filters_and_retry_create_a_new_record(
        self, multi_project_root, monkeypatch
    ):
        client, manager, _calls = self._platform_client(multi_project_root, monkeypatch)
        patch_command(monkeypatch, manager, "print('ok')")
        write_headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
            "X-Platform-Resource-Context": "opaque-global",
        }
        submitted = client.post(
            "/api-autotest/api/tasks",
            headers=write_headers,
            json={
                "project_id": "dating",
                "run_type": "flow",
                "flow_id": "dating_demo_flow",
            },
        ).get_json()
        manager.wait_idle()
        listing = client.get(
            "/api-autotest/api/tasks?project_id=dating&status=succeeded&run_type=flow",
            headers=write_headers,
        ).get_json()
        assert listing["total"] == 1
        assert listing["items"][0]["id"] == submitted["id"]

        retried = client.post(
            f"/api-autotest/api/tasks/{submitted['id']}/retry",
            headers=write_headers,
        )
        assert retried.status_code == 201
        manager.wait_idle()
        retry_record = manager.store.load(retried.get_json()["id"])
        assert retry_record["retry_of"] == submitted["id"]
        assert manager.store.load(submitted["id"])["retry_of"] is None

    def test_modified_parameter_retry_preserves_retry_chain(
        self, multi_project_root, monkeypatch
    ):
        """创建页修改参数后提交的新任务仍必须记录来源任务。"""

        client, manager, _calls = self._platform_client(
            multi_project_root, monkeypatch
        )
        patch_command(monkeypatch, manager, "print('ok')")
        headers = {
            "X-CSRF-Token": "csrf-token",
            "X-Platform-User-Context": "signed-user",
            "X-Platform-Resource-Context": "opaque-global",
        }
        original = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json={
                "project_id": "dating",
                "run_type": "flow",
                "flow_id": "dating_demo_flow",
            },
        ).get_json()
        manager.wait_idle()

        retried = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json={
                "project_id": "dating",
                "run_type": "flow",
                "flow_id": "dating_demo_flow",
                "retry_from": original["id"],
            },
        )

        assert retried.status_code == 201
        manager.wait_idle()
        retry_record = manager.store.load(retried.get_json()["id"])
        assert retry_record["retry_of"] == original["id"]

        mismatched = client.post(
            "/api-autotest/api/tasks",
            headers=headers,
            json={
                "project_id": "dating",
                "run_type": "flow",
                "flow_id": "anonymous_session_refresh",
                "retry_from": original["id"],
            },
        )
        assert mismatched.status_code == 400
        assert mismatched.get_json()["error_code"] == "INVALID_PARAMS"
