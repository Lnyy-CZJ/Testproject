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
    assert connection.execute("SELECT COUNT(*) FROM permissions").fetchone()[0] == 11
    assert connection.execute("SELECT COUNT(*) FROM roles WHERE is_builtin = 1").fetchone()[0] == 5
    assert connection.execute("SELECT COUNT(*) FROM config_definitions").fetchone()[0] == 43

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
