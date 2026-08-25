#!/usr/bin/env python3
"""从五个第一方工具的只读存储生成历史根资源清单。

脚本不猜测 owner/project；缺失字段按空值输出，随后必须由平台迁移校验器阻断并
人工补齐。每个源端始终输出精确枚举计数，空目录也会明确写入 0，防止用空
manifest 绕过全量性检查。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def _snapshot_row(environment: str, tool_id: str, resource_type: str, resource_id: str, snapshot: dict) -> dict:
    """把各工具快照转换为平台统一 manifest 行，不补造缺失归属。"""

    return {
        "environment_id": environment,
        "tool_id": tool_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "root_resource_id": resource_id,
        "owner_user_id": snapshot.get("owner_user_id") or "",
        "project_id_snapshot": snapshot.get("project_id_snapshot"),
        "authorization_source_snapshot": snapshot.get("authorization_source_snapshot") or "",
    }


def _agent_tasks(root: Path, tool_id: str, environment: str) -> list[dict]:
    if not root.is_dir() or not (root / "tasks").is_dir():
        raise FileNotFoundError(f"{tool_id} 任务目录不存在: {root / 'tasks'}")
    rows = []
    for path in sorted((root / "tasks").glob("*/task.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        rows.append(_snapshot_row(environment, tool_id, "task", str(record.get("id") or path.parent.name), record.get("internal") or {}))
    return rows


def _api_autotest_tasks(tasks_dir: Path, environment: str) -> list[dict]:
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"api-autotest 任务目录不存在: {tasks_dir}")
    rows = []
    for path in sorted(tasks_dir.glob("*.json")):
        if path.name.startswith("."):
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        rows.append(_snapshot_row(environment, "api-autotest", "task", str(record.get("id") or path.stem), record.get("resource_snapshot") or {}))
    return rows


def _truthy_runs(database_path: Path, environment: str) -> list[dict]:
    if not database_path.is_file():
        raise FileNotFoundError(f"Truthy Search 数据库不存在: {database_path}")
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        required = {"run_id", "owner_user_id", "project_id_snapshot", "authorization_source_snapshot"}
        if not required.issubset(columns):
            raise RuntimeError("Truthy Search runs 表尚未扩展资源快照列")
        return [_snapshot_row(environment, "truthy-search", "run", row["run_id"], dict(row)) for row in connection.execute(
            "SELECT run_id, owner_user_id, project_id_snapshot, authorization_source_snapshot FROM runs ORDER BY run_id"
        )]
    finally:
        connection.close()


def _log_exports(root: Path, environment: str) -> list[dict]:
    if not root.is_dir():
        raise FileNotFoundError(f"log-filter 导出目录不存在: {root}")
    rows = []
    for owner_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for export_dir in sorted(path for path in owner_dir.iterdir() if path.is_dir()):
            rows.append(_snapshot_row(environment, "log-filter", "export", export_dir.name, {
                "owner_user_id": owner_dir.name,
                "authorization_source_snapshot": "unknown",
            }))
    # 旧版根目录平铺文件没有可靠 owner，逐文件输出 blocker 而不是静默忽略。
    for path in sorted(root.glob("*.log")):
        rows.append(_snapshot_row(environment, "log-filter", "export", f"legacy-{path.stem}", {}))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True)
    parser.add_argument("--functional-data", type=Path, required=True)
    parser.add_argument("--api-agent-data", type=Path, required=True)
    parser.add_argument("--api-autotest-tasks", type=Path, required=True)
    parser.add_argument("--truthy-search-db", type=Path, required=True)
    parser.add_argument("--log-export-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    grouped = {
        "functional-test-agent": _agent_tasks(args.functional_data, "functional-test-agent", args.environment),
        "api-test-agent": _agent_tasks(args.api_agent_data, "api-test-agent", args.environment),
        "api-autotest": _api_autotest_tasks(args.api_autotest_tasks, args.environment),
        "truthy-search": _truthy_runs(args.truthy_search_db, args.environment),
        "log-filter": _log_exports(args.log_export_dir, args.environment),
    }
    payload = {
        "user_roles": {},
        "required_environments": [args.environment],
        "tool_projects": {},
        "memberships": [],
        "approved_permission_widenings": [],
        "source_counts": {f"{args.environment}:{tool_id}": len(rows) for tool_id, rows in grouped.items()},
        "resources": [row for rows in grouped.values() for row in rows],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
