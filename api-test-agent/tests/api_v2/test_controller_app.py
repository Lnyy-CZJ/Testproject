"""真实 Controller HTTP 边界的内部鉴权和窄契约测试。"""

from services.execution_controller.app import create_app
from services.execution_controller.fake_runtime import FakeRuntimeAdapter


def payload():
    return {
        "run_id": "run_123", "input_id": "task_20260813_0123456789abcdef0123/run_123/input.json",
        "output_id": "task_20260813_0123456789abcdef0123/run_123/executor-output.json",
        "input_sha256": "a" * 64, "resource_policy_id": "resource_1",
        "egress_policy_id": "egress_1", "timeout_seconds": 30,
    }


def test_controller_requires_token_and_rejects_escape_fields(tmp_path, monkeypatch):
    """无 Token、错误 Token 和运行时逃逸字段都必须在 Controller 边界拒绝。"""

    token = tmp_path / "token"
    token.write_text("controller-secret", encoding="utf-8")
    monkeypatch.setenv("CONTROLLER_TOKEN_FILE", str(token))
    app = create_app(runtime=FakeRuntimeAdapter())
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/internal/v1/runs", json=payload()).status_code == 401
    headers = {"Authorization": "Bearer controller-secret"}
    escaped = {**payload(), "command": ["curl"]}
    response = client.post("/internal/v1/runs", json=escaped, headers=headers)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "CONTROLLER_REQUEST_INVALID"
    assert client.post("/internal/v1/runs", json=payload(), headers=headers).status_code == 200
