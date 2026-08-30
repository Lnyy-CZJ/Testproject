"""task_store 单元测试：原子落盘、列表、保留与关联产物清理。"""

from __future__ import annotations

import threading
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import stat

import pytest

from web.task_store import TaskInputError, TaskStore, is_valid_task_id, new_task_id


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


class TestTaskInputs:
    """锁定新版 Dating 协议的十进制 7,000,000 字节单图边界。"""

    @staticmethod
    def _png_upload(size_bytes: int):
        """构造具有真实 PNG 文件头、指定总大小的上传对象。"""

        header = b"\x89PNG\r\n\x1a\n"
        return SimpleNamespace(
            filename="chat.png",
            content_type="image/png",
            stream=BytesIO(header + b"x" * (size_bytes - len(header))),
        )

    def test_exact_protocol_limit_is_accepted_and_next_byte_is_rejected(
        self, store: TaskStore
    ) -> None:
        """7,000,000 字节可保存，7,000,001 字节必须在落盘阶段拒绝。"""

        accepted, _manifest = store.save_inputs(
            "20260828-190000-a1b2",
            "dating",
            [self._png_upload(7_000_000)],
        )
        assert accepted[0]["size_bytes"] == 7_000_000

        with pytest.raises(TaskInputError) as error:
            store.save_inputs(
                "20260828-190001-a1b3",
                "dating",
                [self._png_upload(7_000_001)],
            )
        assert error.value.error_code == "TASK_INPUT_TOO_LARGE"


class TestExecutionAsset:
    """任务私有执行资产与 console 共用目录但有独立生命周期。"""

    def test_execution_asset_is_0600_and_cleanup_keeps_console(
        self,
        store: TaskStore,
    ) -> None:
        """精准清理执行 JSON 时必须保留 console 和其他任务产物。"""
        task_id = "20260829-120000-abcd"
        project_id = "dating"
        console = store.console_log_path(task_id, project_id)
        console.parent.mkdir(parents=True)
        console.write_text("keep", encoding="utf-8")

        path = store.save_execution_asset(
            task_id,
            project_id,
            {"schema_version": 1, "task_id": task_id, "project_id": project_id},
        )

        assert path == console.parent / "execution-asset.json"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        store.cleanup_execution_asset(task_id, project_id)
        assert not path.exists()
        assert console.read_text(encoding="utf-8") == "keep"

    @pytest.mark.parametrize(
        ("task_id", "project_id"),
        [("../escape", "dating"), ("20260829-120000-abcd", "../dating")],
    )
    def test_execution_asset_reuses_task_and_project_path_validation(
        self,
        store: TaskStore,
        task_id: str,
        project_id: str,
    ) -> None:
        """执行文件路径不能绕过现有任务/项目边界。"""
        with pytest.raises(ValueError):
            store.execution_asset_path(task_id, project_id)


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
        """删除任务同步清理 console、JUnit 与任务专属报告。"""
        task_id = "20260807-163012-a1b2"
        store.save(_record(task_id))
        console_directory = store.console_dir(task_id)
        console_directory.mkdir(parents=True)
        store.console_log_path(task_id).write_text("output", encoding="utf-8")
        junit = tmp_path / "reports" / f"junit-task-{task_id}.xml"
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.write_text("<xml/>", encoding="utf-8")
        task_report = tmp_path / "reports" / "task-reports" / task_id / "current"
        task_report.mkdir(parents=True)
        (task_report / "index.html").write_text("report", encoding="utf-8")

        assert store.delete(task_id) is True
        assert store.load(task_id) is None
        assert not console_directory.exists()
        assert not junit.exists()
        assert not (tmp_path / "reports" / "task-reports" / task_id).exists()

    def test_delete_v2_task_removes_retained_inputs(
        self, store: TaskStore, tmp_path: Path
    ) -> None:
        """V2 输入位于任务 runtime 边界内，显式删除任务时必须一并清理。"""

        task_id = "20260807-163012-a1b2"
        record = {
            **_record(task_id),
            "schema_version": 2,
            "project": {"project_id": "dating"},
            "junit_file": f"reports/junit/dating/{task_id}.xml",
        }
        store.save(record)
        input_directory = store.console_dir(task_id, "dating") / "inputs"
        input_directory.mkdir(parents=True)
        (input_directory / "001-example.png").write_bytes(b"image")

        assert store.delete(task_id) is True
        assert not input_directory.exists()
        assert not (tmp_path / "runtime" / "dating" / task_id).exists()

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

    def test_enforce_retention_never_deletes_non_terminal_tasks(
        self, store: TaskStore
    ) -> None:
        """即使排队任务最旧，Retention 也只能清理终态历史。"""

        store.save(_record("20260807-163010-a1b2", "pending"))
        for index in range(1, 5):
            store.save(_record(f"20260807-16301{index}-a1b2"))

        removed = store.enforce_retention(2)

        assert store.load("20260807-163010-a1b2")["status"] == "pending"
        assert len(removed) == 2

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
