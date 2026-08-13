"""固定 Executor 的执行前脱敏和分类规则测试。"""

import importlib.util
from pathlib import Path


def load_runner():
    """从镜像入口源码加载纯函数，测试环境无需创建容器。"""

    path = Path(__file__).resolve().parents[2] / "executor" / "runner.py"
    spec = importlib.util.spec_from_file_location("api_executor_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_executor_redacts_request_and_json_response_fields():
    """敏感 Header、请求体和 JSON 响应在 stdout 形成前必须脱敏。"""

    runner = load_runner()
    request = runner.redact({"headers": {"Authorization": "Bearer secret"}, "body": {"password": "123"}})
    response = runner.redact_response_body('{"token":"response-secret","value":"ok"}')
    assert request["headers"]["Authorization"] == "[REDACTED]"
    assert request["body"]["password"] == "[REDACTED]"
    assert response == {"token": "[REDACTED]", "value": "ok"}
