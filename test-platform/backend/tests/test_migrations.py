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


def test_contract_requires_successful_manifest_readiness_marker(tmp_path: Path) -> None:
    """0020 即使被精确指定，也必须拒绝绕过 manifest/shadow apply。"""

    database_path = tmp_path / "contract-gate.db"
    database_url = f"sqlite:///{database_path}"
    run_alembic(database_url, "upgrade", "20260824_0019")
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    blocked = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260824_0020"],
        cwd=BACKEND_ROOT, env=environment, check=False, capture_output=True, text=True,
    )
    assert blocked.returncode != 0
    assert "manifest" in blocked.stderr
    connection = sqlite3.connect(database_path)
    tool_ids = [row[0] for row in connection.execute("SELECT id FROM tools")]
    manifest_path = tmp_path / "project-access-manifest.json"
    manifest_path.write_text(json.dumps({
        "user_roles": {},
        "tool_projects": {tool_id: "project_legacy" for tool_id in tool_ids},
        "memberships": [],
        "required_environments": ["prod"],
        "source_counts": {
            "prod:truthy-search": 0,
            "prod:api-autotest": 0,
            "prod:functional-test-agent": 0,
            "prod:api-test-agent": 0,
            "prod:log-filter": 0,
        },
        "resources": [],
    }), encoding="utf-8")
    connection.close()
    subprocess.run(
        [
            sys.executable, "-m", "app.migrate_project_access",
            "--manifest", str(manifest_path), "--required-environment", "prod", "--apply",
        ],
        cwd=BACKEND_ROOT, env=environment, check=True, capture_output=True, text=True,
    )
    # apply 与 contract 之间若发生任意授权写入，数据库状态摘要必须使旧 marker
    # 失效；重新 apply 后才能继续收紧约束。
    connection = sqlite3.connect(database_path)
    connection.execute("UPDATE tools SET authorization_epoch=authorization_epoch+1 WHERE id=(SELECT id FROM tools ORDER BY id LIMIT 1)")
    connection.commit()
    connection.close()
    drifted = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20260824_0020"],
        cwd=BACKEND_ROOT, env=environment, check=False, capture_output=True, text=True,
    )
    assert drifted.returncode != 0
    subprocess.run(
        [
            sys.executable, "-m", "app.migrate_project_access",
            "--manifest", str(manifest_path), "--required-environment", "prod", "--apply",
        ],
        cwd=BACKEND_ROOT, env=environment, check=True, capture_output=True, text=True,
    )
    run_alembic(database_url, "upgrade", "20260824_0020")


def test_contract_freezes_authorization_tables_before_digest_check() -> None:
    """生产 Contract 必须先阻写，再读取 marker/摘要，防止并发 TOCTOU。"""

    migration = (
        BACKEND_ROOT / "alembic/versions/20260824_0020_contract_project_access_control.py"
    ).read_text(encoding="utf-8")
    lock_position = migration.index("LOCK TABLE users, projects, tools")
    digest_position = migration.index("readiness = connection.execute")
    assert lock_position < digest_position
    assert "IN SHARE MODE" in migration
    assert "lock_timeout" in migration


def test_empty_database_upgrade_is_repeatable_and_downgrade_is_scoped(
    tmp_path: Path,
) -> None:
    """空库可重复升级，第二阶段种子正确，各迁移可精确降级。"""

    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path}"
    run_alembic(database_url, "upgrade", "20260824_0019")
    run_alembic(database_url, "upgrade", "20260824_0019")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT * FROM tools ORDER BY sort_order, name"
    ).fetchall()
    assert {
        "projects",
        "project_memberships",
        "user_tool_grants",
        "business_resource_snapshots",
    }.issubset(
        {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    )
    assert "platform_role" in {
        row[1] for row in connection.execute("PRAGMA table_info(users)")
    }
    assert {"access_scope", "project_id", "revision", "authorization_epoch"}.issubset(
        {row[1] for row in connection.execute("PRAGMA table_info(tools)")}
    )
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
    assert connection.execute("SELECT COUNT(*) FROM permissions").fetchone()[0] == 22
    assert connection.execute("SELECT COUNT(*) FROM roles WHERE is_builtin = 1").fetchone()[0] == 5
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 131
    assert connection.execute("SELECT COUNT(*) FROM llm_profiles").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM tool_llm_bindings").fetchone()[0] == 3
    assert [row[0] for row in connection.execute(
        "SELECT permission_code FROM role_grants WHERE role_id='role_platform_admin' "
        "AND permission_code LIKE 'platform.llm.%' ORDER BY permission_code"
    ).fetchall()] == ["platform.llm.manage", "platform.llm.secret.manage"]
    # V2.4 将执行定义生成和 Review 从基础用例 Review 中独立出来；只读角色不应获授权。
    executable_permissions = ["api-test-agent.executable.generate", "api-test-agent.executable.review"]
    for role_id, resource_id in (
        ("role_platform_admin", "*"),
        ("role_test_developer", "api-test-agent"),
        ("role_test_executor", "api-test-agent"),
    ):
        assert [row[0] for row in connection.execute(
            "SELECT permission_code FROM role_grants WHERE role_id=? "
            "AND permission_code LIKE 'api-test-agent.executable.%' ORDER BY permission_code",
            (role_id,),
        ).fetchall()] == executable_permissions
        assert connection.execute(
            "SELECT COUNT(*) FROM role_grants WHERE role_id=? AND resource_type='tool' "
            "AND resource_id=? AND permission_code='api-test-agent.executable.generate'",
            (role_id, resource_id),
        ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM role_grants WHERE role_id='role_readonly' "
        "AND permission_code LIKE 'api-test-agent.executable.%'"
    ).fetchone()[0] == 0
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

    workbench = connection.execute(
        "SELECT default_value, sensitivity, apply_mode FROM config_definitions "
        "WHERE id='functional-test-agent.FUNCTIONAL_WORKBENCH_V2_ENABLED'"
    ).fetchone()
    assert workbench is not None
    assert json.loads(workbench[0]) is False
    assert (workbench[1], workbench[2]) == ("normal", "next_task")

    workbench_v3 = connection.execute(
        "SELECT default_value, sensitivity, apply_mode FROM config_definitions "
        "WHERE id='functional-test-agent.FUNCTIONAL_WORKBENCH_V3_ENABLED'"
    ).fetchone()
    assert workbench_v3 is not None
    assert json.loads(workbench_v3[0]) is False
    assert (workbench_v3[1], workbench_v3[2]) == ("normal", "next_task")

    # 0016 只登记 V3 开关，降级到 0015 后保留配置中心和 V2 定义。
    connection.close()
    run_alembic(database_url, "downgrade", "20260817_0015")
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 130
    assert connection.execute(
        "SELECT COUNT(*) FROM config_definitions WHERE key='FUNCTIONAL_WORKBENCH_V3_ENABLED'"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM config_definitions WHERE key='FUNCTIONAL_WORKBENCH_V2_ENABLED'"
    ).fetchone()[0] == 1
    connection.close()
    run_alembic(database_url, "upgrade", "20260824_0019")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    # 0014 只登记工作台开关，精确降级后必须保留 0013 的两个定义。
    connection.close()
    run_alembic(database_url, "downgrade", "20260815_0013")
    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 100
    assert connection.execute(
        "SELECT COUNT(*) FROM config_definitions WHERE id LIKE 'api-autotest.ADMIN_OPERATOR_%'"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(*) FROM config_definitions WHERE key='FUNCTIONAL_WORKBENCH_V2_ENABLED'"
    ).fetchone()[0] == 0
    connection.close()
    run_alembic(database_url, "upgrade", "20260824_0019")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    # 0012 可精确回滚到 0011，并保留已有测试点 Review 配置。
    connection.close()
    run_alembic(database_url, "downgrade", "20260813_0011")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 87
    assert connection.execute("SELECT COUNT(*) FROM config_definitions WHERE key='ONLINE_REVIEW_ENABLED'").fetchone()[0] == 1
    connection.close()
    run_alembic(database_url, "upgrade", "20260824_0019")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row

    # 0011 可精确回滚到 0010 并重新升级，且不触碰两个工具本身。
    connection.close()
    run_alembic(database_url, "downgrade", "20260813_0010")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 82
    connection.close()
    run_alembic(database_url, "upgrade", "20260824_0019")
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
    run_alembic(database_url, "upgrade", "20260824_0019")

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


def _unique_index_columns(connection: sqlite3.Connection, table_name: str) -> set[tuple[str, ...]]:
    """返回 SQLite 表上的全部唯一索引列，用于验证迁移的真实数据库约束。"""

    unique_columns: set[tuple[str, ...]] = set()
    for index_row in connection.execute(f'PRAGMA index_list("{table_name}")').fetchall():
        if not index_row[2]:
            continue
        index_name = index_row[1]
        columns = tuple(
            row[2]
            for row in connection.execute(f'PRAGMA index_info("{index_name}")').fetchall()
        )
        unique_columns.add(columns)
    return unique_columns


def test_user_scope_migration_builds_isolated_tables_and_constraints(tmp_path: Path) -> None:
    """0018 必须创建用户私有表、所有权列和不可跨用户复用的唯一约束。"""

    database_path = tmp_path / "user-scope.db"
    database_url = f"sqlite:///{database_path}"
    run_alembic(database_url, "upgrade", "20260824_0019")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "user_credentials",
        "user_credential_items",
        "user_llm_bindings",
        "runtime_contexts",
    }.issubset(tables)

    definition_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(config_definitions)")
    }
    assert {"value_scope", "credential_provider_type"}.issubset(definition_columns)
    profile_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(llm_profiles)")
    }
    assert "owner_user_id" in profile_columns

    assert (
        "user_id", "tool_id", "environment_id", "provider_type"
    ) in _unique_index_columns(connection, "user_credentials")
    assert (
        "credential_id", "credential_version", "key"
    ) in _unique_index_columns(connection, "user_credential_items")
    assert ("user_id", "binding_id") in _unique_index_columns(
        connection, "user_llm_bindings"
    )
    assert ("owner_user_id", "name_normalized") in _unique_index_columns(
        connection, "llm_profiles"
    )

    readiness_grant = connection.execute(
        "SELECT COUNT(*) FROM role_grants "
        "WHERE role_id='role_platform_admin' "
        "AND permission_code='platform.credential.readiness.view'"
    ).fetchone()[0]
    assert readiness_grant == 1

    classifications = connection.execute(
        "SELECT owner_id, key, value_scope, credential_provider_type "
        "FROM config_definitions WHERE credential_provider_type IS NOT NULL "
        "ORDER BY owner_id, key"
    ).fetchall()
    assert classifications
    assert all(row["value_scope"] == "user" for row in classifications)
    connection.close()


def test_user_scope_migration_downgrade_is_scoped(tmp_path: Path) -> None:
    """回退 0018 只删除个人隔离结构，必须保留全部 legacy 回滚材料。"""

    database_path = tmp_path / "user-scope-downgrade.db"
    database_url = f"sqlite:///{database_path}"
    run_alembic(database_url, "upgrade", "20260824_0019")
    connection = sqlite3.connect(database_path)
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type='table' AND name='user_credentials'"
    ).fetchone()[0] == 1
    connection.close()

    run_alembic(database_url, "downgrade", "20260821_0017")
    connection = sqlite3.connect(database_path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert not {
        "user_credentials", "user_credential_items", "user_llm_bindings", "runtime_contexts"
    } & tables
    assert {"credentials", "credential_items", "config_releases", "secrets"}.issubset(tables)
    assert "owner_user_id" not in {
        row[1] for row in connection.execute("PRAGMA table_info(llm_profiles)")
    }
    assert {"value_scope", "credential_provider_type"}.isdisjoint({
        row[1] for row in connection.execute("PRAGMA table_info(config_definitions)")
    })
    assert connection.execute(
        "SELECT COUNT(*) FROM permissions "
        "WHERE code='platform.credential.readiness.view'"
    ).fetchone()[0] == 0
    connection.close()


def test_user_scope_downgrade_rejects_duplicate_profile_names_with_guidance(
    tmp_path: Path,
) -> None:
    """0018 降级遇到跨所有者同名 Profile 时必须在改表前给出可操作提示。"""

    database_path = tmp_path / "user-scope-duplicate-profile.db"
    database_url = f"sqlite:///{database_path}"
    run_alembic(database_url, "upgrade", "20260824_0019")
    connection = sqlite3.connect(database_path)
    connection.execute(
        "INSERT INTO llm_profiles "
        "(id, name, name_normalized, description, protocol, is_archived, created_by) "
        "SELECT 'llmp_duplicate_for_downgrade', name, name_normalized, description, "
        "protocol, is_archived, created_by FROM llm_profiles LIMIT 1"
    )
    connection.commit()
    connection.close()

    try:
        run_alembic(database_url, "downgrade", "20260821_0017")
    except subprocess.CalledProcessError as exc:
        assert "先重命名或合并同名 LLM Profile" in exc.stderr
    else:
        raise AssertionError("存在同名 LLM Profile 时 0018 降级必须被拒绝")
