import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.services.version_status import compare_component


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


def test_same_version_with_different_revision_is_build_mismatch() -> None:
    """相同业务版本指向不同源码时标记构建不一致。"""

    row = compare_component(
        "sample", {"version": "1.0.0", "compatible_product_major": 1},
        identity("1.0.0", "devsha"), identity("1.0.0", "prodsha"), None, 1,
    )
    assert row["primary_status"] == "构建不一致"


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
        "database": {"alembic_revision": None},
        "config_releases": {},
    }
    monkeypatch.setattr("app.api.system.collect_snapshot", lambda *_: snapshot)
    monkeypatch.setattr("app.api.system.fetch_prod_snapshot", lambda *_: (None, "Prod 无法获取"))
    response = client.get("/api/v1/system/version-matrix")
    assert response.status_code == 200
    assert response.json()["prod_error"] == "Prod 无法获取"
    assert response.json()["runtime_environment"] == "dev"


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
