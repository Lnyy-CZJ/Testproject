"""平台 Alembic 迁移的空库、幂等和精确降级测试。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def run_alembic(database_url: str, *arguments: str) -> None:
    """在独立进程执行迁移，避免测试配置缓存污染 FastAPI 测试。"""

    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_empty_database_upgrade_is_repeatable_and_downgrade_is_scoped(
    tmp_path: Path,
) -> None:
    """空库可重复升级，第二阶段种子正确，各迁移可精确降级。"""

    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    run_alembic(database_url, "upgrade", "head")
    run_alembic(database_url, "upgrade", "head")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT * FROM tools ORDER BY sort_order, name"
    ).fetchall()
    assert [row["id"] for row in rows] == [
        "trackevents",
        "log-filter",
        "truthy-search",
        "api-autotest",
        "functional-test-agent",
        "api-test-agent",
    ]
    truthy = rows[2]
    assert truthy["entry_url"] == "/truthy-search/"
    assert truthy["health_url"] == (
        "http://truthy-search:5002/truthy-search/health"
    )
    assert truthy["short_code"] == "SEARCH"
    assert truthy["icon_key"] == "search"
    assert truthy["category"] == "evaluation"
    assert json.loads(truthy["features"]) == [
        "检索执行",
        "字段对比",
        "评测报告",
    ]
    api_autotest = rows[3]
    assert api_autotest["name"] == "接口自动化"
    assert api_autotest["entry_url"] == "/api-autotest/"
    assert api_autotest["health_url"] == (
        "http://api-autotest:5003/api-autotest/health"
    )
    assert api_autotest["short_code"] == "API"
    assert api_autotest["icon_key"] == "api"
    assert api_autotest["category"] == "automation"
    assert json.loads(api_autotest["features"]) == [
        "执行触发",
        "结果统计",
        "报告查看",
    ]

    assert [row[0] for row in connection.execute(
        "SELECT id FROM environments ORDER BY sort_order"
    ).fetchall()] == ["dev", "prod"]
    assert connection.execute("SELECT COUNT(*) FROM permissions").fetchone()[0] == 17
    assert connection.execute("SELECT COUNT(*) FROM roles WHERE is_builtin = 1").fetchone()[0] == 5
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 98
    review_defaults = connection.execute(
        "SELECT key, default_value FROM config_definitions "
        "WHERE owner_id='functional-test-agent' AND key IN ('ONLINE_REVIEW_ENABLED','REVIEW_AI_ENABLED') ORDER BY key"
    ).fetchall()
    assert [(row[0], json.loads(row[1])) for row in review_defaults] == [
        ("ONLINE_REVIEW_ENABLED", False), ("REVIEW_AI_ENABLED", False),
    ]
    dev_review_values = connection.execute(
        "SELECT d.key, i.value_json FROM config_activations a "
        "JOIN config_release_items i ON i.release_id=a.active_release_id "
        "JOIN config_definitions d ON d.id=i.definition_id "
        "WHERE a.environment_id='dev' AND a.owner_id='functional-test-agent' "
        "AND d.key IN ('ONLINE_REVIEW_ENABLED','REVIEW_AI_ENABLED') ORDER BY d.key"
    ).fetchall()
    assert [(row[0], bool(row[1])) for row in dev_review_values] == [
        ("ONLINE_REVIEW_ENABLED", True), ("REVIEW_AI_ENABLED", True),
    ]

    case_review_defaults = connection.execute(
        "SELECT key, default_value FROM config_definitions WHERE owner_id='functional-test-agent' "
        "AND key IN ('ONLINE_CASE_REVIEW_ENABLED','CASE_REVIEW_AI_ENABLED') ORDER BY key"
    ).fetchall()
    assert [(row[0], json.loads(row[1])) for row in case_review_defaults] == [
        ("CASE_REVIEW_AI_ENABLED", False), ("ONLINE_CASE_REVIEW_ENABLED", False),
    ]
    dev_case_values = connection.execute(
        "SELECT d.key, i.value_json FROM config_activations a "
        "JOIN config_release_items i ON i.release_id=a.active_release_id "
        "JOIN config_definitions d ON d.id=i.definition_id "
        "WHERE a.environment_id='dev' AND a.owner_id='functional-test-agent' "
        "AND d.key IN ('ONLINE_CASE_REVIEW_ENABLED','CASE_REVIEW_AI_ENABLED') ORDER BY d.key"
    ).fetchall()
    assert [(row[0], bool(row[1])) for row in dev_case_values] == [
        ("CASE_REVIEW_AI_ENABLED", True), ("ONLINE_CASE_REVIEW_ENABLED", True),
    ]

    # 0012 可精确回滚到 0011，并保留已有测试点 Review 配置。
    connection.close()
    run_alembic(database_url, "downgrade", "20260813_0011")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 87
    assert connection.execute("SELECT COUNT(*) FROM config_definitions WHERE key='ONLINE_REVIEW_ENABLED'").fetchone()[0] == 1
    connection.close()
    run_alembic(database_url, "upgrade", "head")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    # 0011 可精确回滚到 0010 并重新升级，且不触碰两个工具本身。
    connection.close()
    run_alembic(database_url, "downgrade", "20260813_0010")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 82
    connection.close()
    run_alembic(database_url, "upgrade", "head")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("DELETE FROM config_activations WHERE environment_id='dev' AND owner_id='functional-test-agent'")

    # 模拟已发布 dev 配置、Secret 和 Credential，验证 0009 在真实使用后仍可回滚。
    connection.execute(
        "INSERT INTO config_releases "
        "(id, environment_id, owner_type, owner_id, version, revision, status, created_by) "
        "VALUES ('rel_ai_test', 'dev', 'tool', 'functional-test-agent', 99, 1, 'active', 'test')"
    )
    connection.execute(
        "INSERT INTO config_release_items (release_id, definition_id, value_json) "
        "VALUES ('rel_ai_test', 'functional-test-agent.LLM_MODEL', '\"test-model\"')"
    )
    connection.execute(
        "INSERT INTO config_activations (environment_id, owner_type, owner_id, active_release_id) "
        "VALUES ('dev', 'tool', 'functional-test-agent', 'rel_ai_test')"
    )
    connection.execute(
        "INSERT INTO secrets (id, environment_id, owner_type, owner_id, definition_id, status) "
        "VALUES ('sec_ai_test', 'dev', 'tool', 'functional-test-agent', "
        "'functional-test-agent.LLM_API_KEY', 'healthy')"
    )
    connection.execute(
        "INSERT INTO secret_versions "
        "(id, secret_id, version, ciphertext, cipher_nonce, wrapped_dek, wrap_nonce, kek_version, aad_version, status, created_by) "
        "VALUES ('secv_ai_test', 'sec_ai_test', 1, X'01', X'02', X'03', X'04', 'dev-v1', 1, 'active', 'test')"
    )
    connection.execute("UPDATE secrets SET current_version_id = 'secv_ai_test' WHERE id = 'sec_ai_test'")
    connection.execute(
        "INSERT INTO credentials "
        "(id, tool_id, environment_id, provider_type, status, current_version) "
        "VALUES ('cred_ai_test', 'functional-test-agent', 'dev', 'test', 'active', 1)"
    )
    connection.execute(
        "INSERT INTO credential_items (credential_id, credential_version, key, secret_version_id) "
        "VALUES ('cred_ai_test', 1, 'LLM_API_KEY', 'secv_ai_test')"
    )
    connection.commit()

    # 新工具迁移可单独回滚并重新升级，不触碰既有四个工具。
    run_alembic(database_url, "downgrade", "20260811_0008")
    assert [row[0] for row in connection.execute(
        "SELECT id FROM tools ORDER BY sort_order"
    ).fetchall()] == ["trackevents", "log-filter", "truthy-search", "api-autotest"]
    run_alembic(database_url, "upgrade", "head")

    # 第二阶段降级不得触碰 0003 已接入的接口自动化工具。
    run_alembic(database_url, "downgrade", "20260807_0003")
    phase1_ids = [row[0] for row in connection.execute(
        "SELECT id FROM tools ORDER BY sort_order"
    ).fetchall()]
    assert phase1_ids == ["trackevents", "log-filter", "truthy-search", "api-autotest"]

    run_alembic(database_url, "downgrade", "-1")
    remaining_ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM tools ORDER BY sort_order"
        ).fetchall()
    ]
    connection.close()
    assert remaining_ids == ["trackevents", "log-filter", "truthy-search"]
