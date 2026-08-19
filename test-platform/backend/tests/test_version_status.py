import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.main import app
from app.services.version_status import _database_structure, compare_component


VERSION_TOOL_PATH = Path(__file__).resolve().parents[2] / "scripts" / "version_tool.py"
SPEC = importlib.util.spec_from_file_location("version_tool", VERSION_TOOL_PATH)
assert SPEC and SPEC.loader
version_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(version_tool)


def identity(version: str, revision: str = "abc", **values):
    """构造最小组件运行身份。"""

    return {
        "version": version,
        "revision": revision,
        "dirty": False,
        "health": "healthy",
        "digest": None,
        "content_sha256": "content-a",
        **values,
    }


def test_strict_semver_rejects_leading_zeroes() -> None:
    """机器版本拒绝前导零，历史展示格式不能进入新清单。"""

    assert version_tool.validate_semver("1.1.0", "version") == (1, 1, 0)
    try:
        version_tool.validate_semver("1.01.000", "version")
    except ValueError as exc:
        assert "strict SemVer" in str(exc)
    else:
        raise AssertionError("leading zeroes must be rejected")


def test_comparison_status_priority_and_architecture_digest_rule() -> None:
    """不可用优先；Dev 与 Prod 不因跨架构 digest 不同产生漂移。"""

    component = {"version": "1.2.0", "compatible_product_major": 1}
    row = compare_component(
        "sample", component,
        identity("1.2.0", digest="sha256:arm"),
        identity("1.1.0", digest="sha256:amd", health="unavailable"),
        None,
        1,
    )
    assert row["primary_status"] == "不可用"
    assert "待发布" in row["issues"]
    assert "环境漂移" not in row["issues"]


def test_same_content_with_different_revision_is_consistent() -> None:
    """Dev/main 提交 SHA 可不同；内容哈希相同才表示源码一致。"""

    row = compare_component(
        "sample", {"version": "1.0.0", "compatible_product_major": 1},
        identity("1.0.0", "devsha"), identity("1.0.0", "prodsha"), None, 1,
    )
    assert row["primary_status"] == "一致"


def test_same_version_with_different_content_is_rejected() -> None:
    """相同业务版本承载不同源码内容时不能显示一致。"""

    row = compare_component(
        "sample", {"version": "1.0.0", "compatible_product_major": 1},
        identity("1.0.0", content_sha256="content-a"),
        identity("1.0.0", content_sha256="content-b"), None, 1,
    )
    assert row["primary_status"] == "内容不一致"


def test_configured_component_detects_effective_config_difference() -> None:
    """Release ID 可不同，但有效配置哈希不同时必须显示配置不一致。"""

    component = {
        "version": "1.0.0", "compatible_product_major": 1,
        "config_scopes": ["tool:functional-test-agent"],
    }
    row = compare_component(
        "sample", component,
        identity("1.0.0", config_sha256="dev-config"),
        identity("1.0.0", config_sha256="prod-config"), None, 1,
    )
    assert row["primary_status"] == "配置不一致"


def test_database_fingerprint_ignores_rows_but_detects_structure(
    database_factory: sessionmaker[Session],
) -> None:
    """数据库证据只覆盖表结构；各环境业务数据不同不会产生漂移。"""

    with database_factory() as database:
        before = _database_structure(database)["schema_sha256"]
        database.execute(text("INSERT INTO environments (id, name, is_active, sort_order) VALUES ('x', 'x', 1, 9)"))
        database.commit()
        assert _database_structure(database)["schema_sha256"] == before
        database.execute(text("CREATE TABLE schema_fingerprint_probe (id INTEGER PRIMARY KEY)"))
        assert _database_structure(database)["schema_sha256"] != before


def test_version_matrix_requires_audit_permission_and_degrades_prod(
    client: TestClient, monkeypatch,
) -> None:
    """版本矩阵保留权限保护，Prod 不可达时仍返回 Dev 数据。"""

    snapshot = {
        "checked_at": "2026-08-19T00:00:00+00:00",
        "product_version": "1.1.0",
        "runtime_environment": "dev",
        "release": None,
        "commit": "abc",
        "components": {},
        "database": {"alembic_revision": None, "schema_sha256": "schema", "data_compared": False},
        "config_releases": {},
    }
    monkeypatch.setattr("app.api.system.collect_snapshot", lambda *_: snapshot)
    monkeypatch.setattr("app.api.system.fetch_prod_snapshot", lambda *_: (None, "Prod 无法获取"))
    response = client.get("/api/v1/system/version-matrix")
    assert response.status_code == 200
    assert response.json()["prod_error"] == "Prod 无法获取"
    assert response.json()["runtime_environment"] == "dev"
    assert all(row["primary_status"] == "不可用" for row in response.json()["rows"])


def test_peer_snapshot_token_missing_wrong_and_correct(client: TestClient, monkeypatch) -> None:
    """环境互查接口只接受恒定时间校验通过的独立 Bearer Token。"""

    settings = Settings(version_peer_token="peer-secret")
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("app.api.system.collect_snapshot", lambda *_: {"runtime_environment": "dev"})
    assert client.get("/api/v1/internal/version-snapshot").status_code == 401
    assert client.get(
        "/api/v1/internal/version-snapshot", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401
    response = client.get(
        "/api/v1/internal/version-snapshot", headers={"Authorization": "Bearer peer-secret"}
    )
    assert response.status_code == 200
    assert response.json()["runtime_environment"] == "dev"
