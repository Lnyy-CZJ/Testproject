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
    """空库可重复升级，第三条数据正确，降级只删除 Truthy_Search。"""

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

    run_alembic(database_url, "downgrade", "-1")
    remaining_ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM tools ORDER BY sort_order"
        ).fetchall()
    ]
    connection.close()
    assert remaining_ids == ["trackevents", "log-filter"]
