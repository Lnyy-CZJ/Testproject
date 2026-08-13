"""两个智能体 Web 路由、CSRF、RBAC 和所有权测试。"""

from __future__ import annotations

import io
import json
import hashlib
from pathlib import Path

import pytest

from services.api_agent.app import create_app as create_api_app
from services.common.config import ServiceSettings
from services.common.errors import ServiceError
from services.common.task_models import utc_now
from services.functional_agent.app import create_app as create_functional_app


class FakePlatformClient:
    """不读取 Token 或网络的测试平台 Client。"""

    snapshot = {
        "tool_id": "", "environment": "dev", "release_id": "rel_test", "release_version": 1,
        "normal": {"QUEUE_MAX_WAITING": 5, "UPLOAD_MAX_BYTES": 5 * 1024 * 1024, "UPLOAD_MAX_CHARACTERS": 500_000, "ONLINE_REVIEW_ENABLED": True, "REVIEW_AI_ENABLED": True, "ONLINE_CASE_REVIEW_ENABLED": True, "CASE_REVIEW_AI_ENABLED": True},
        "secrets": {"LLM_API_KEY": "sentinel"}, "configured_secret_keys": ["LLM_API_KEY"],
    }

    def runtime_config(self, *, include_secrets: bool):
        return self.snapshot

    def audit(self, _event):
        return None


class FakeManager:
    """同步保存任务的路由测试调度器。"""

    def __init__(self, store):
        self.store = store

    def assert_capacity(self, _limit):
        return None

    def submit(self, record, payload, *, max_waiting=None):
        if record.get("agent_type") == "api":
            # 路由替身保持生产 ApiTaskManager 的 V2 新任务语义。
            record.update({"schema_version": 2, "current_versions": {}, "completed_stages": []})
        self.store.atomic_write_json(self.store.task_dir(record["id"]) / "request.json", payload)
        self.store.save(record)
        return record

    def cancel(self, task_id):
        record = self.store.load(task_id)
        record.update({"status": "cancelled", "stage": "cancelled", "finished_at": utc_now()})
        self.store.save(record)
        return record

    def resume(self, task_id, metadata, *, max_waiting=None):
        record = self.store.load(task_id)
        if record["status"] != "waiting_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "状态不允许")
        record.update({"status": "pending", "stage": "queued", "review": metadata})
        self.store.save(record)
        return record

    def enqueue_review_ai(self, task_id, metadata, *, max_waiting=None):
        """模拟 AI 请求进入共享队列。"""

        record = self.store.load(task_id)
        if record["status"] != "waiting_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "状态不允许")
        record.update({"status": "pending", "stage": "review_ai_queued", "review_ai": metadata})
        record.setdefault("internal", {})["execution_kind"] = "review_ai"
        self.store.save(record)
        return record

    def cancel_review_ai(self, task_id):
        """模拟 AI 子阶段取消后回到 Review。"""

        record = self.store.load(task_id)
        record.update({"status": "waiting_review", "stage": "review_ai_cancelled"})
        record.setdefault("review_ai", {})["status"] = "cancelled"
        self.store.save(record)
        return record

    def enqueue_case_review_ai(self, task_id, metadata, *, max_waiting=None):
        """模拟用例 AI 请求进入公共队列。"""

        record = self.store.load(task_id)
        if record["status"] != "waiting_case_review":
            raise ServiceError(409, "INVALID_TASK_STATE", "状态不允许")
        record.update({"status": "pending", "stage": "case_review_ai_queued", "case_review_ai": metadata})
        record.setdefault("internal", {})["execution_kind"] = "case_review_ai"
        self.store.save(record)
        return record

    def cancel_case_review_ai(self, task_id):
        """模拟取消用例 AI 后回到用例 Review。"""

        record = self.store.load(task_id)
        record.update({"status": "waiting_case_review", "stage": "case_review_ai_cancelled"})
        record.setdefault("case_review_ai", {})["status"] = "cancelled"
        self.store.save(record)
        return record


def settings(tmp_path: Path, agent_type: str) -> ServiceSettings:
    tool = "functional-test-agent" if agent_type == "functional" else "api-test-agent"
    return ServiceSettings(
        tool_id=tool, agent_type=agent_type, base_path=f"/{tool}", host="127.0.0.1",
        port=5004 if agent_type == "functional" else 5005, data_dir=tmp_path / agent_type,
        platform_api_url="http://unused", platform_client_token_file=tmp_path / "unused",
        runtime_environment="dev", platform_home_url="/", app_revision="test",
    )


def headers(user: str = "user_1", permissions: str = "tool.view,tool.execute,tool.result.view,task.cancel") -> dict[str, str]:
    return {
        "X-Platform-User-ID": user,
        "X-Platform-Username": user,
        "X-Platform-Display-Name": user,
        "X-Platform-Permissions": permissions,
        "X-CSRF-Token": "csrf",
    }


def make_client(tmp_path: Path, agent_type: str):
    active = settings(tmp_path, agent_type)
    fake = FakePlatformClient()
    fake.snapshot = {**fake.snapshot, "tool_id": active.tool_id}
    factory = lambda store, _loader: FakeManager(store)
    app = (create_functional_app if agent_type == "functional" else create_api_app)(
        settings=active, platform_client=fake,
        safe_config_loader=lambda: fake.runtime_config(include_secrets=False), manager_factory=factory,
    )
    app.config["TESTING"] = True
    client = app.test_client()
    client.set_cookie("tp_csrf", "csrf")
    return client, app


@pytest.mark.parametrize("agent_type,filename", [("functional", "requirement.md"), ("api", "openapi.yaml")])
def test_create_list_owner_and_version_visibility(tmp_path: Path, agent_type: str, filename: str) -> None:
    client, _app = make_client(tmp_path, agent_type)
    operation = "generate_test_points" if agent_type == "functional" else "generate_api_cases"
    response = client.post(
        f"/{'functional-test-agent' if agent_type == 'functional' else 'api-test-agent'}/api/v1/tasks",
        headers=headers(),
        data={
            "operation": operation, "project_name": "项目 A", "module_name": "登录", "environment": "dev",
            "additional_context": "重点覆盖重复提交",
            "document_file": (io.BytesIO(b"# document" if filename.endswith(".md") else b"openapi: 3.0.0"), filename),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    task = response.get_json()
    assert "internal" not in task
    assert task["config_release_id"] == "rel_test"
    request_payload = json.loads(
        (_app.extensions["task_store"].task_dir(task["id"]) / "request.json").read_text(encoding="utf-8")
    )
    assert request_payload["additional_info"]["context"] == "重点覆盖重复提交"
    base = "/functional-test-agent" if agent_type == "functional" else "/api-test-agent"
    assert client.get(f"{base}/api/v1/tasks/{task['id']}", headers=headers()).status_code == 200
    assert client.get(f"{base}/api/v1/tasks/{task['id']}", headers=headers("user_2")).status_code == 404
    assert client.get(f"{base}/api/v1/tasks/{task['id']}", headers=headers("admin", "tool.result.view,task.view.all")).status_code == 200


def test_csrf_permissions_and_api_execution_disabled(tmp_path: Path) -> None:
    client, _app = make_client(tmp_path, "api")
    missing_csrf = headers()
    missing_csrf["X-CSRF-Token"] = "wrong"
    response = client.post("/api-test-agent/api/v1/tasks", headers=missing_csrf, data={})
    assert response.status_code == 403

    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "parse_api_document", "project_name": "A", "module_name": "B", "environment": "dev",
            "document_file": (io.BytesIO(b"{}"), "api.json"),
        }, content_type="multipart/form-data",
    ).get_json()
    execute_headers = headers(permissions="tool.execute,tool.result.view,api-test-agent.execute")
    disabled = client.post(f"/api-test-agent/api/v1/tasks/{created['id']}/execute", headers=execute_headers)
    assert disabled.status_code == 403
    assert disabled.get_json()["error"]["code"] == "EXECUTION_NOT_READY"
    task_dir = _app.extensions["task_store"].task_dir(created["id"])
    assert not (task_dir / "runs").exists() or not list((task_dir / "runs").glob("run_*"))


def test_api_v2_pages_render_review_and_safety_boundaries(tmp_path: Path) -> None:
    """API 专属 Jinja 页面展示 Review 阶段和 S1 安全边界。"""

    client, _app = make_client(tmp_path, "api")
    home = client.get("/api-test-agent/", headers=headers())
    assert home.status_code == 200
    assert "不支持 Postman" in home.get_data(as_text=True)
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "parse_api_document", "project_name": "A", "module_name": "B", "environment": "dev",
            "document_file": (io.BytesIO(b"openapi: 3.0.0\npaths: {}"), "api.yaml"),
        }, content_type="multipart/form-data",
    ).get_json()
    page = client.get(f"/api-test-agent/tasks/{created['id']}", headers=headers())
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "接口契约" in html and "覆盖矩阵与基础用例" in html
    assert "本机 S2 试点" in html and "api-v2-workbench.js" in html


def test_functional_review_version_and_direct_test_points_upload(tmp_path: Path) -> None:
    """Review 原稿与修改稿共存，相同 SHA 重试不重复生成版本。"""

    client, app = make_client(tmp_path, "functional")
    base = "/functional-test-agent"
    direct = client.post(
        f"{base}/api/v1/tasks", headers=headers(),
        data={
            "operation": "generate_test_cases", "project_name": "A", "module_name": "B", "environment": "dev",
            "test_points_file": (io.BytesIO(b'[{"test_point":"login"}]'), "points.json"),
        }, content_type="multipart/form-data",
    )
    assert direct.status_code == 202
    direct_id = direct.get_json()["id"]
    request_payload = json.loads((app.extensions["task_store"].task_dir(direct_id) / "request.json").read_text(encoding="utf-8"))
    assert request_payload["input_kind"] == "test_points"

    record = app.extensions["task_store"].load(direct_id)
    record.update({"status": "waiting_review", "stage": "waiting_for_review"})
    app.extensions["task_store"].save(record)
    review_data = b'[{"test_point":"login reviewed"}]'
    resumed = client.post(
        f"{base}/api/v1/tasks/{direct_id}/resume", headers=headers(),
        data={"review_file": (io.BytesIO(review_data), "review.json")}, content_type="multipart/form-data",
    )
    assert resumed.status_code == 202
    first = app.extensions["task_store"].load(direct_id)["review_draft"]
    record = app.extensions["task_store"].load(direct_id)
    record["status"] = "waiting_review"
    app.extensions["task_store"].save(record)
    client.post(
        f"{base}/api/v1/tasks/{direct_id}/resume", headers=headers(),
        data={"review_file": (io.BytesIO(review_data), "review.json")}, content_type="multipart/form-data",
    )
    second = app.extensions["task_store"].load(direct_id)["review_draft"]
    assert first["version"] == second["version"] == 1
    assert (app.extensions["task_store"].task_dir(direct_id) / first["relative_path"]).is_file()


def test_artifact_expired_and_missing_identity_fail_closed(tmp_path: Path) -> None:
    """过期产物返回 410，缺失可信身份时失败关闭。"""

    client, app = make_client(tmp_path, "api")
    assert client.get("/api-test-agent/").status_code == 401
    created = client.post(
        "/api-test-agent/api/v1/tasks", headers=headers(),
        data={
            "operation": "parse_api_document", "project_name": "A", "module_name": "B", "environment": "dev",
            "document_file": (io.BytesIO(b"{}"), "api.json"),
        }, content_type="multipart/form-data",
    ).get_json()
    record = app.extensions["task_store"].load(created["id"])
    record["artifacts_expired"] = True
    app.extensions["task_store"].save(record)
    response = client.get(f"/api-test-agent/api/v1/tasks/{created['id']}/artifacts", headers=headers())
    assert response.status_code == 410
    assert response.get_json()["error"]["code"] == "ARTIFACT_EXPIRED"


def test_online_review_cas_confirm_and_ai_queue(tmp_path: Path) -> None:
    """在线草稿使用 CAS，确认只读不可变版本，AI 只进入建议子阶段。"""

    client, app = make_client(tmp_path, "functional")
    base = "/functional-test-agent"
    created = client.post(
        f"{base}/api/v1/tasks", headers=headers(),
        data={"operation": "generate_test_points", "project_name": "A", "module_name": "登录", "environment": "dev", "document_text": "# 登录需求"},
        content_type="multipart/form-data",
    ).get_json()
    task_id = created["id"]
    store = app.extensions["task_store"]
    task_dir = store.task_dir(task_id)
    points = [{"id": "TP001", "module": "登录", "feature": "密码", "scenario": "正常", "test_point": "登录成功", "risk_level": "P1", "extra": {"kept": True}}]
    source = task_dir / "published" / "test-points" / "points.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(points, ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "artifact_points", "type": "test_points_json", "name": "points.json", "relative_path": "published/test-points/points.json", "created_at": utc_now(), "expired": False}]})
    record = store.load(task_id)
    record.update({"status": "waiting_review", "stage": "waiting_for_review"})
    store.save(record)

    page = client.get(f"{base}/tasks/{task_id}", headers=headers())
    assert page.status_code == 200
    assert b"data-review-workbench" in page.data
    assert b"review-workbench.js" in page.data
    assert "下载本地副本" in page.get_data(as_text=True)

    loaded = client.get(f"{base}/api/v1/tasks/{task_id}/review", headers=headers())
    assert loaded.status_code == 200
    initial = loaded.get_json()
    assert initial["revision"] == 0
    saved = client.put(
        f"{base}/api/v1/tasks/{task_id}/review-draft", headers={**headers(), "Content-Type": "application/json"},
        json={"revision": 0, "sha256": initial["sha256"], "points": points},
    )
    assert saved.status_code == 200
    draft = saved.get_json()
    assert draft["revision"] == 1
    assert draft["points"][0]["extra"] == {"kept": True}
    conflict = client.put(
        f"{base}/api/v1/tasks/{task_id}/review-draft", headers={**headers(), "Content-Type": "application/json"},
        json={"revision": 0, "sha256": initial["sha256"], "points": points},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["error"]["details"]["current_revision"] == 1

    ai = client.post(
        f"{base}/api/v1/tasks/{task_id}/review-ai", headers={**headers(), "Content-Type": "application/json", "Idempotency-Key": "ai-request-0001"},
        json={"revision": 1, "sha256": draft["sha256"], "operation": "supplement", "selected_ids": [], "scope": {}, "instruction": ""},
    )
    assert ai.status_code == 202
    assert store.load(task_id)["status"] == "pending"
    cancelled = client.post(f"{base}/api/v1/tasks/{task_id}/review-ai/cancel", headers=headers())
    assert cancelled.status_code == 200
    assert store.load(task_id)["status"] == "waiting_review"

    resumed = client.post(
        f"{base}/api/v1/tasks/{task_id}/resume", headers={**headers(), "Content-Type": "application/json", "Idempotency-Key": "review-confirm-0001"},
        json={"revision": 1, "sha256": draft["sha256"], "accept_warnings": True},
    )
    assert resumed.status_code == 202
    confirmed = store.load(task_id)["review"]
    assert confirmed["version"] == 1
    assert (task_dir / confirmed["relative_path"]).is_file()
    assert hashlib.sha256((task_dir / confirmed["relative_path"]).read_bytes()).hexdigest()
    assert "relative_path" not in resumed.get_json()["review"]


def test_online_review_owner_csrf_and_api_agent_fail_closed(tmp_path: Path) -> None:
    """在线 Review 写操作继续受所有权、CSRF 和工具类型限制。"""

    client, app = make_client(tmp_path, "functional")
    task_id = app.extensions["task_store"].task_dir if False else "task_20260813_00000000000000000000"
    assert client.get(f"/functional-test-agent/api/v1/tasks/{task_id}/review", headers=headers("other")).status_code == 404
    api_client, _ = make_client(tmp_path, "api")
    assert api_client.get(f"/api-test-agent/api/v1/tasks/{task_id}/review", headers=headers()).status_code == 404


def test_online_case_review_ai_and_confirm_publish(tmp_path: Path) -> None:
    """用例工作台保存、AI 入队、确认和同源发布形成闭环。"""

    client, app = make_client(tmp_path, "functional")
    base = "/functional-test-agent"
    created = client.post(
        f"{base}/api/v1/tasks", headers=headers(),
        data={"operation": "generate_test_cases", "project_name": "A", "module_name": "登录", "environment": "dev", "test_points_file": (io.BytesIO(b'[{"id":"TP001","module":"login","feature":"password","scenario":"normal","test_point":"success","risk_level":"P1"}]'), "points.json")},
        content_type="multipart/form-data",
    ).get_json()
    task_id = created["id"]
    store = app.extensions["task_store"]
    task_dir = store.task_dir(task_id)
    cases = [{"case_id": "TC001", "test_point_id": "TP001", "module": "login", "feature": "password", "scenario": "normal", "case_name": "login succeeds", "priority": "P1", "preconditions": [], "test_steps": ["click login"], "test_data": {}, "expected_result": "home visible", "actual_result": ""}]
    source = task_dir / "published" / "test-cases" / "generated.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(cases), encoding="utf-8")
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "artifact_cases", "type": "test_cases_json", "name": "generated.json", "relative_path": "published/test-cases/generated.json", "created_at": utc_now(), "expired": False}]})
    request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
    request_payload["review_relative_path"] = request_payload["input_relative_path"]
    store.atomic_write_json(task_dir / "request.json", request_payload)
    record = store.load(task_id)
    record.update({"status": "waiting_case_review", "stage": "case_review_editing", "review": {"relative_path": request_payload["review_relative_path"]}})
    store.save(record)

    page = client.get(f"{base}/tasks/{task_id}", headers=headers())
    assert page.status_code == 200
    assert b"data-case-review-workbench" in page.data
    assert b"case-review-workbench.js" in page.data
    loaded = client.get(f"{base}/api/v1/tasks/{task_id}/case-review", headers=headers()).get_json()
    saved_response = client.put(
        f"{base}/api/v1/tasks/{task_id}/case-review-draft", headers={**headers(), "Content-Type": "application/json"},
        json={"revision": 0, "sha256": loaded["sha256"], "cases": cases},
    )
    assert saved_response.status_code == 200
    saved = saved_response.get_json()
    ai = client.post(
        f"{base}/api/v1/tasks/{task_id}/case-review-ai", headers={**headers(), "Content-Type": "application/json", "Idempotency-Key": "case-ai-0001"},
        json={"revision": 1, "sha256": saved["sha256"], "operation": "supplement", "selected_ids": [], "scope": {}, "instruction": ""},
    )
    assert ai.status_code == 202
    assert store.load(task_id)["status"] == "pending"
    assert client.post(f"{base}/api/v1/tasks/{task_id}/case-review-ai/cancel", headers=headers()).status_code == 200
    confirmed = client.post(
        f"{base}/api/v1/tasks/{task_id}/case-review/confirm", headers={**headers(), "Content-Type": "application/json", "Idempotency-Key": "case-confirm-0001"},
        json={"revision": 1, "sha256": saved["sha256"], "accept_warnings": True},
    )
    assert confirmed.status_code == 200
    assert store.load(task_id)["status"] == "succeeded"
    types = {item["type"] for item in confirmed.get_json()["artifacts"]}
    assert types == {"test_cases_json", "test_cases_xlsx"}
    assert "relative_path" not in confirmed.get_json()["case_review"]
    retried = client.post(
        f"{base}/api/v1/tasks/{task_id}/case-review/confirm", headers={**headers(), "Content-Type": "application/json", "Idempotency-Key": "case-confirm-0001"},
        json={"revision": 1, "sha256": saved["sha256"], "accept_warnings": True},
    )
    assert retried.status_code == 200
    assert retried.get_json()["case_review"]["version"] == confirmed.get_json()["case_review"]["version"]


def test_admin_task_list_survives_schema_incompatible_records(tmp_path: Path) -> None:
    """
    手工写入的最小 schema 任务记录不得打挂管理员任务列表。

    功能说明:
        复现线上故障:S2 安全评审曾在运行时目录手工构造仅含少数字段的
        任务记录(缺 PublicTaskModel 大部分必填字段)。管理员持有
        task.view.all 权限会遍历全部可见记录,public_task() 校验抛
        ValidationError 导致首页与列表接口整体 500,网关再误报为
        AUTH_SERVICE_UNAVAILABLE。加固后列表渲染应跳过这类
        schema 不兼容记录,而不是让整个页面崩溃。

    验证点:
        - 管理员首页 HTML 渲染返回 200
        - 管理员列表 API 返回 200,且正常任务仍在、坏记录被跳过
    """
    client, app = make_client(tmp_path, "api")
    store = app.extensions["task_store"]
    # 先经生产路由创建一个正常任务,保证列表中存在合法数据。
    created = client.post(
        "/api-test-agent/api/v1/tasks",
        headers=headers(),
        data={
            "operation": "generate_api_cases", "project_name": "项目 A", "module_name": "登录", "environment": "dev",
            "document_file": (io.BytesIO(b"openapi: 3.0.0"), "openapi.yaml"),
        },
        content_type="multipart/form-data",
    )
    assert created.status_code == 202
    good_task_id = created.get_json()["id"]
    # 写入一条缺 PublicTaskModel 必填字段的最小 schema 记录,模拟 S2 测试残留。
    bad_task_id = "task_20260813_" + "0" * 20
    store.task_dir(bad_task_id, create=True)
    store.save({
        "id": bad_task_id, "schema_version": 2, "status": "waiting_execution_confirmation",
        "stage": "execution_confirmation", "created_by_user_id": "s2_tester",
        "environment": "dev", "current_versions": {}, "completed_stages": [],
    })
    admin_headers = headers("admin", "tool.view,tool.result.view,task.view.all")
    # 首页 HTML 与列表 JSON 接口都不得被坏记录打挂。
    page = client.get("/api-test-agent/", headers=admin_headers)
    assert page.status_code == 200
    listing = client.get("/api-test-agent/api/v1/tasks", headers=admin_headers)
    assert listing.status_code == 200
    listed_ids = {item["id"] for item in listing.get_json()["items"]}
    assert good_task_id in listed_ids
    assert bad_task_id not in listed_ids
