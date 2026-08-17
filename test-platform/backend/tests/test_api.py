from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import get_db
from app.main import app
from app.models.tool import Tool


def make_tool(
    tool_id: str,
    name: str,
    sort_order: int,
    *,
    is_enabled: bool = True,
) -> Tool:
    """
    构造测试工具记录。

    参数说明:
        tool_id (str): 工具主键。
        name (str): 工具显示名称。
        sort_order (int): 工具排序权重。
        is_enabled (bool): 是否允许出现在目录和健康接口中。
    返回值:
        Tool: 可直接写入测试数据库的模型。
    """

    return Tool(
        id=tool_id,
        name=name,
        description=f"{name}描述",
        entry_url=f"/{tool_id}/",
        health_url=f"http://{tool_id}/health",
        short_code=tool_id.upper(),
        icon_key="tool",
        category="analysis",
        features=["功能"],
        sort_order=sort_order,
        is_enabled=is_enabled,
    )


def test_live_and_ready(client: TestClient) -> None:
    """验证存活接口不访问数据库，就绪接口能完成数据库检查。"""

    assert client.get("/api/v1/health/live").json() == {
        "service": "platform-api",
        "status": "ok",
        "version": "1.01.000",
    }
    ready_response = client.get("/api/v1/health/ready")
    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "service": "platform-api",
        "status": "ready",
        "version": "1.01.000",
    }


def test_platform_version_rejects_invalid_format(tmp_path) -> None:
    """验证错误位数的版本不会进入健康接口或发布产物。"""

    version_file = tmp_path / "VERSION"
    version_file.write_text("1.0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="平台版本必须符合"):
        Settings(platform_version_file=str(version_file)).read_platform_version()


def test_tools_are_sorted_and_disabled_items_are_hidden(
    client: TestClient,
    database_factory: sessionmaker[Session],
) -> None:
    """验证目录排序、禁用过滤及内部健康地址隐藏。"""

    with database_factory() as database:
        database.add_all(
            [
                make_tool("later", "后显示", 20),
                make_tool("disabled", "已禁用", 0, is_enabled=False),
                make_tool("first", "先显示", 10),
            ]
        )
        database.commit()

    response = client.get("/api/v1/tools")
    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["first", "later"]
    assert all("health_url" not in item for item in payload["items"])


def test_tool_health_success_and_upstream_failure(
    client: TestClient,
    database_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    """验证健康、异常和超时均按约定收敛为平台状态。"""

    with database_factory() as database:
        database.add(make_tool("target", "目标工具", 10))
        database.commit()

    healthy_response = httpx.Response(
        200,
        json={"status": "ok"},
        request=httpx.Request("GET", "http://target/health"),
    )
    monkeypatch.setattr("app.services.tool_health.httpx.get", lambda *args, **kwargs: healthy_response)
    response = client.get("/api/v1/tools/target/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    datetime.fromisoformat(response.json()["checked_at"])

    def raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.services.tool_health.httpx.get", raise_timeout)
    response = client.get("/api/v1/tools/target/health")
    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"


def test_unknown_tool_uses_uniform_error_structure(client: TestClient) -> None:
    """验证未知工具不会暴露内部实现并包含可追踪请求标识。"""

    response = client.get("/api/v1/tools/missing/health")
    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "NOT_FOUND"
    assert payload["message"] == "工具不存在"
    assert payload["request_id"].startswith("req_")
    assert response.headers["X-Request-ID"] == payload["request_id"]

    unknown_route_response = client.get("/api/v1/missing")
    assert unknown_route_response.status_code == 404
    assert unknown_route_response.json()["code"] == "NOT_FOUND"
    assert unknown_route_response.json()["message"] == "请求的资源不存在"
    assert unknown_route_response.json()["request_id"].startswith("req_")


def test_ready_returns_503_when_database_is_unavailable(
    database_factory: sessionmaker[Session],
) -> None:
    """验证数据库异常时就绪接口返回统一的 503 错误。"""

    engine = database_factory.kw["bind"]

    def fail_query(*args, **kwargs):
        """模拟数据库连接已建立但查询执行失败。"""

        raise OperationalError("SELECT 1", {}, Exception("database down"))

    def override_broken_database():
        database = database_factory()
        try:
            yield database
        finally:
            database.close()

    event.listen(engine, "before_cursor_execute", fail_query)
    app.dependency_overrides[get_db] = override_broken_database
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/v1/health/ready")
    app.dependency_overrides.clear()
    event.remove(engine, "before_cursor_execute", fail_query)

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"
