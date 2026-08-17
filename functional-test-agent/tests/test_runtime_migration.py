"""旧 runtime 安全复制工具测试。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts.migrate_legacy_runtime import migrate


def arguments(source: Path, destination: Path, **overrides) -> argparse.Namespace:
    """构造迁移函数所需参数。"""

    values = {
        "source": str(source),
        "destination": str(destination),
        "environment": "dev",
        "dry_run": False,
        "verify_only": False,
        "manifest": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def make_source(tmp_path: Path) -> Path:
    """创建包含终态和 running 任务的最小旧数据。"""

    source = tmp_path / "legacy" / "runtime" / "dev" / "functional"
    for task_id, status in (("task_done", "succeeded"), ("task_running", "running")):
        task_dir = source / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text(json.dumps({"id": task_id, "status": status}), encoding="utf-8")
        (task_dir / "console.log").write_text(task_id, encoding="utf-8")
    return source


def test_dry_run_copy_verify_and_idempotency(tmp_path: Path) -> None:
    """dry-run 不写目标，复制后 SHA 可验证且重跑不重复写。"""

    source = make_source(tmp_path)
    destination = tmp_path / "new" / "runtime" / "dev" / "functional"
    dry = migrate(arguments(source, destination, dry_run=True))
    assert dry["missing_count"] == 4 and not destination.exists()
    copied = migrate(arguments(source, destination))
    assert copied["copied_count"] == 4
    verified = migrate(arguments(source, destination, verify_only=True))
    assert verified["missing_count"] == 0
    rerun = migrate(arguments(source, destination))
    assert rerun["copied_count"] == 0
    running = [item for item in copied["files"] if item.get("task_status") == "running"]
    assert running and "WORKER_INTERRUPTED" in running[0]["recovery"]


def test_conflict_and_symlink_are_rejected(tmp_path: Path) -> None:
    """同名异内容和源目录符号链接均阻断迁移。"""

    source = make_source(tmp_path)
    destination = tmp_path / "new" / "runtime" / "dev" / "functional"
    conflict = destination / "tasks" / "task_done" / "task.json"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("different", encoding="utf-8")
    with pytest.raises(FileExistsError):
        migrate(arguments(source, destination))
    conflict.unlink()
    (source / "linked").symlink_to(source / "tasks", target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        migrate(arguments(source, destination, dry_run=True))


def test_broad_or_cross_environment_path_is_rejected(tmp_path: Path) -> None:
    """路径必须严格匹配 environment/agent 末尾。"""

    source = make_source(tmp_path)
    with pytest.raises(ValueError, match="路径必须"):
        migrate(arguments(source, tmp_path / "functional", dry_run=True))
