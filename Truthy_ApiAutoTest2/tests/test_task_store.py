"""task_store 单元测试：原子落盘、列表、保留与关联产物清理。"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from web.task_store import TaskStore, is_valid_task_id, new_task_id


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    """基于临时目录的存储器。"""
    return TaskStore(tmp_path / "tasks", tmp_path / "reports")


def _record(task_id: str, status: str = "succeeded") -> dict:
    """构造最小任务记录。"""
    return {"id": task_id, "status": status, "input": {"env": "test"}}


class TestTaskId:
    def test_new_task_id_format(self) -> None:
        """任务 ID 符合 日期-时间-4位十六进制 且可排序。"""
        task_id = new_task_id()
        assert is_valid_task_id(task_id)

    @pytest.mark.parametrize(
        "bad_id",
        ["", "../evil", "20260807-163012", "20260807-163012-XYZ!", "a/b.json"],
    )
    def test_invalid_ids_rejected(self, bad_id: str) -> None:
        """非法 ID 一律拒绝，防止路径穿越。"""
        assert not is_valid_task_id(bad_id)


class TestAtomicPersistence:
    def test_save_and_load_roundtrip(self, store: TaskStore) -> None:
        """保存后可完整读回。"""
        record = _record("20260807-163012-a1b2")
        store.save(record)
        assert store.load(record["id"]) == record

    def test_save_leaves_no_tmp_file(self, store: TaskStore) -> None:
        """os.replace 后不应残留临时文件。"""
        store.save(_record("20260807-163012-a1b2"))
        tmp_files = list(store.tasks_dir.glob(".*tmp*"))
        assert tmp_files == []

    def test_load_missing_returns_none(self, store: TaskStore) -> None:
        """不存在的任务返回 None。"""
        assert store.load("20260807-163012-ffff") is None

    def test_invalid_id_raises(self, store: TaskStore) -> None:
        """非法 ID 的读写均抛 ValueError。"""
        with pytest.raises(ValueError):
            store.save({"id": "../evil"})
        with pytest.raises(ValueError):
            store.load("../evil")

    def test_concurrent_reads_during_writes(self, store: TaskStore) -> None:
        """并发写与轮询读取不得看到半份 JSON。"""
        task_id = "20260807-163012-a1b2"
        store.save(_record(task_id))
        errors: list[Exception] = []

        def writer() -> None:
            for index in range(50):
                store.save({**_record(task_id), "seq": index})

        def reader() -> None:
            for _ in range(100):
                try:
                    data = store.load(task_id)
                    assert data is not None and "id" in data
                except Exception as exc:  # noqa: BLE001 - 收集任何并发异常
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []


class TestListAndRetention:
    def test_list_sorted_newest_first(self, store: TaskStore) -> None:
        """列表按 ID 倒序（时间倒序）。"""
        for suffix in ("aaa1", "aaa2", "aaa3"):
            store.save(_record(f"20260807-163012-{suffix}"))
        ids = [record["id"] for record in store.list()]
        assert ids == sorted(ids, reverse=True)

    def test_delete_removes_related_artifacts(
        self, store: TaskStore, tmp_path: Path
    ) -> None:
        """删除任务同步清理 console 目录与任务 JUnit。"""
        task_id = "20260807-163012-a1b2"
        store.save(_record(task_id))
        console_directory = store.console_dir(task_id)
        console_directory.mkdir(parents=True)
        store.console_log_path(task_id).write_text("output", encoding="utf-8")
        junit = tmp_path / "reports" / f"junit-task-{task_id}.xml"
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.write_text("<xml/>", encoding="utf-8")

        assert store.delete(task_id) is True
        assert store.load(task_id) is None
        assert not console_directory.exists()
        assert not junit.exists()

    def test_delete_missing_returns_false(self, store: TaskStore) -> None:
        """删除不存在的任务返回 False。"""
        assert store.delete("20260807-163012-ffff") is False

    def test_enforce_retention_keeps_newest(self, store: TaskStore) -> None:
        """保留策略只保留最新 N 条。"""
        for index in range(5):
            store.save(_record(f"20260807-16301{index}-a1b2"))
        removed = store.enforce_retention(3)
        assert len(removed) == 2
        assert len(store.list()) == 3

    def test_enforce_retention_rejects_non_positive(self, store: TaskStore) -> None:
        """保留条数必须为正整数。"""
        with pytest.raises(ValueError):
            store.enforce_retention(0)

    def test_corrupted_record_skipped_in_list(self, store: TaskStore) -> None:
        """损坏 JSON 不阻断列表接口。"""
        store.save(_record("20260807-163012-a1b2"))
        (store.tasks_dir / "20260807-163013-a1b3.json").write_text(
            "{broken", encoding="utf-8"
        )
        records = store.list()
        assert [record["id"] for record in records] == ["20260807-163012-a1b2"]
