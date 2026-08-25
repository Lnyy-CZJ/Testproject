"""公共任务存储和单槽位 FIFO 测试。"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.common.errors import classify_runner_exception
from services.common.task_manager import TaskManager
from services.common.task_store import TaskStore, is_valid_task_id, new_task_id
from services.functional_agent.runner import (
    _configure_dependency_warnings,
    _require_decomposition_success,
)


def record(task_id: str, created_at: str, status: str = "pending") -> dict:
    """创建公共运行时测试所需的最小内部记录。"""

    return {
        "id": task_id, "status": status, "stage": "queued", "created_at": created_at,
        "internal": {"revision": 0},
    }


def wait_status(store: TaskStore, task_id: str, expected: str, timeout: float = 10) -> dict:
    """等待异步任务达到指定状态。"""

    deadline = time.time() + timeout
    while time.time() < deadline:
        current = store.load(task_id)
        if current and current.get("status") == expected:
            return current
        time.sleep(0.05)
    raise AssertionError(f"任务未进入 {expected}: {store.load(task_id)}")


def test_runner_environment_prefers_llm_snapshot_and_omits_empty_options(tmp_path: Path) -> None:
    """新 LLM 快照优先于旧 flat 字段，可选空参数不覆盖 Provider 默认。"""
    store = TaskStore(tmp_path / "runtime")
    manager = TaskManager(
        store=store, runner_module="unused", config_loader=lambda _record: {},
        result_collector=lambda *_: {}, project_root=tmp_path, prompt_paths=[],
        app_revision="test", autostart=False,
    )
    environment = manager._runner_environment({
        "normal": {"LLM_MODEL": "legacy-model", "LLM_BASE_URL": "https://legacy.example/v1"},
        "secrets": {"LLM_API_KEY": "legacy-key"},
        "llm": {
            "model": "snapshot-model", "base_url": "https://provider.example/v1",
            "api_key": "snapshot-key", "temperature": 0.2,
            "max_tokens": None, "timeout_seconds": None,
        },
    }, "task_test")
    assert environment["LLM_MODEL"] == "snapshot-model"
    assert environment["base_url"] == "https://provider.example/v1"
    assert environment["DASHSCOPE_API_KEY"] == "snapshot-key"
    assert environment["LLM_TEMPERATURE"] == "0.2"
    assert "LLM_MAX_TOKENS" not in environment
    assert "LLM_TIMEOUT_SECONDS" not in environment


def test_task_store_atomic_recovery_and_retention(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "runtime")
    task_id = new_task_id()
    assert is_valid_task_id(task_id)
    store.task_dir(task_id, create=True)
    item = record(task_id, datetime.now(UTC).isoformat(), "running")
    store.save(item)
    assert not list(store.task_dir(task_id).glob("*.tmp"))
    assert store.recover_interrupted() == [task_id]
    assert store.load(task_id)["error_code"] == "WORKER_INTERRUPTED"

    old_id = new_task_id(datetime.now(UTC) - timedelta(days=200))
    store.task_dir(old_id, create=True)
    old = record(old_id, (datetime.now(UTC) - timedelta(days=200)).isoformat(), "succeeded")
    old["finished_at"] = old["created_at"]
    store.save(old)
    plan = store.retention_dry_run(now=datetime.now(UTC))
    assert old_id in plan["remove_tasks"]
    assert task_id not in plan["remove_tasks"]
    with pytest.raises(ValueError):
        store.task_dir("../../etc")

    corrupt_id = new_task_id()
    corrupt_dir = store.task_dir(corrupt_id, create=True)
    (corrupt_dir / "task.json").write_text("{broken", encoding="utf-8")
    store.list()
    assert not corrupt_dir.exists()
    assert len(list(store.corrupt_dir.glob(f"{corrupt_id}-*"))) == 1


def test_manager_runs_fifo_and_enforces_queue_limit(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "runtime")
    config = {
        "release_id": "rel_1", "release_version": 1,
        "normal": {"TASK_TIMEOUT_SECONDS": 5, "LLM_MODEL": "test-model"},
        "secrets": {"LLM_API_KEY": "sentinel"},
    }

    def collect(_task_id, _task_dir, _result):
        return {
            "status": "succeeded", "stage": "completed",
            "result_summary": {"artifact_count": 0}, "artifacts": [],
        }

    manager = TaskManager(
        store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: config,
        result_collector=collect, project_root=Path(__file__).resolve().parents[2],
        prompt_paths=["agents/api_test/prompts"], app_revision="test", autostart=False,
    )
    ids = []
    for index in range(2):
        task_id = new_task_id()
        store.task_dir(task_id, create=True)
        manager.submit(record(task_id, f"2026-01-01T00:00:0{index}+00:00"), {"sleep": 0.05}, max_waiting=2)
        ids.append(task_id)
    with pytest.raises(Exception) as error:
        extra = new_task_id()
        store.task_dir(extra, create=True)
        manager.submit(record(extra, "2026-01-01T00:00:03+00:00"), {}, max_waiting=2)
    assert getattr(error.value, "code", None) == "TASK_QUEUE_FULL"
    manager._thread.start()
    for task_id in ids:
        wait_status(store, task_id, "succeeded")
        assert store.load(task_id)["result_summary"] == {"artifact_count": 0}
    manager.stop()
    assert (store.data_dir / "order.log").read_text(encoding="utf-8").splitlines() == ids


def test_waiting_review_resume_reenters_queue(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "runtime")
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save(record(task_id, datetime.now(UTC).isoformat(), "waiting_review"))
    manager = TaskManager(
        store=store, runner_module="tests.services.fake_runner",
        config_loader=lambda _record: {}, result_collector=lambda *_: {},
        project_root=Path(__file__).resolve().parents[2], prompt_paths=[], app_revision="test", autostart=False,
    )
    resumed = manager.resume(task_id, {"sha256": "abc"}, max_waiting=5)
    assert resumed["status"] == "pending"
    assert store.pending_fifo()[0]["id"] == task_id


def test_resume_uses_new_queued_at_and_ai_failure_recovery(tmp_path: Path) -> None:
    """重新继续排到已有 pending 后，运行中 AI 重启后返回 Review。"""

    store = TaskStore(tmp_path / "runtime")
    pending_id = new_task_id()
    review_id = new_task_id()
    for task_id in (pending_id, review_id):
        store.task_dir(task_id, create=True)
    first = record(pending_id, "2026-08-13T00:00:00+00:00")
    first["queued_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.save(first)
    store.save(record(review_id, "2026-01-01T00:00:00+00:00", "waiting_review"))
    manager = TaskManager(store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: {}, result_collector=lambda *_: {}, project_root=Path(__file__).resolve().parents[2], prompt_paths=[], app_revision="test", autostart=False)
    manager.resume(review_id, {"version": 1}, max_waiting=5)
    assert [item["id"] for item in store.pending_fifo()] == [pending_id, review_id]

    ai_id = new_task_id()
    store.task_dir(ai_id, create=True)
    ai = record(ai_id, datetime.now(UTC).isoformat(), "running")
    ai["internal"]["execution_kind"] = "review_ai"
    ai["review_ai"] = {"status": "running"}
    store.save(ai)
    assert store.recover_interrupted() == [ai_id]
    recovered = store.load(ai_id)
    assert recovered["status"] == "waiting_review"
    assert recovered["review_ai"]["error_code"] == "WORKER_INTERRUPTED"


def test_review_ai_uses_shared_runner_and_returns_to_review(tmp_path: Path) -> None:
    """AI 执行占用公共槽位，成功后保留元数据并返回 waiting_review。"""

    store = TaskStore(tmp_path / "runtime")
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    store.atomic_write_json(task_dir / "request.json", {"sleep": 0.01})
    store.save(record(task_id, datetime.now(UTC).isoformat(), "waiting_review"))
    config = {"normal": {"REVIEW_AI_TIMEOUT_SECONDS": 5, "LLM_MODEL": "test"}, "secrets": {"LLM_API_KEY": "sentinel"}}
    manager = TaskManager(store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: config, result_collector=lambda *_: {}, project_root=Path(__file__).resolve().parents[2], prompt_paths=[], app_revision="test")
    manager.enqueue_review_ai(task_id, {"status": "queued", "request_version": 1, "base_revision": 2, "base_sha256": "sha"}, max_waiting=5)
    completed = wait_status(store, task_id, "waiting_review")
    manager.stop()
    assert completed["stage"] == "review_ai_ready"
    assert completed["review_ai"]["status"] == "ready"
    assert completed["review_ai"]["base_revision"] == 2


def test_review_ai_timeout_returns_to_review_without_main_failure(tmp_path: Path) -> None:
    """AI 超时是可恢复子阶段失败，不能写主任务终态。"""

    store = TaskStore(tmp_path / "runtime")
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    store.atomic_write_json(task_dir / "request.json", {"sleep": 30})
    store.save(record(task_id, datetime.now(UTC).isoformat(), "waiting_review"))
    config = {"normal": {"REVIEW_AI_TIMEOUT_SECONDS": 0, "LLM_MODEL": "test"}, "secrets": {"LLM_API_KEY": "sentinel"}}
    manager = TaskManager(store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: config, result_collector=lambda *_: {}, project_root=Path(__file__).resolve().parents[2], prompt_paths=[], app_revision="test")
    manager.enqueue_review_ai(task_id, {"status": "queued", "request_version": 1}, max_waiting=5)
    completed = wait_status(store, task_id, "waiting_review")
    manager.stop()
    assert completed["review_ai"]["error_code"] == "LLM_TIMEOUT"
    assert completed.get("finished_at") is None


def test_case_review_ai_uses_shared_fifo_and_recovers_to_case_review(tmp_path: Path) -> None:
    """用例 AI 使用同一运行槽位，成功和重启都回到 waiting_case_review。"""

    store = TaskStore(tmp_path / "case-runtime")
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    store.atomic_write_json(task_dir / "request.json", {"sleep": 0.01})
    store.save(record(task_id, datetime.now(UTC).isoformat(), "waiting_case_review"))
    config = {"normal": {"CASE_REVIEW_AI_TIMEOUT_SECONDS": 5, "LLM_MODEL": "test"}, "secrets": {"LLM_API_KEY": "sentinel"}}
    manager = TaskManager(store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: config, result_collector=lambda *_: {}, project_root=Path(__file__).resolve().parents[2], prompt_paths=[], app_revision="test")
    manager.enqueue_case_review_ai(task_id, {"status": "queued", "request_version": 1, "base_revision": 2, "base_sha256": "sha"}, max_waiting=5)
    completed = wait_status(store, task_id, "waiting_case_review")
    manager.stop()
    assert completed["stage"] == "case_review_ai_ready"
    assert completed["case_review_ai"]["status"] == "ready"
    assert completed["case_review_ai"]["suggestion_count"] == 1

    interrupted_id = new_task_id()
    store.task_dir(interrupted_id, create=True)
    interrupted = record(interrupted_id, datetime.now(UTC).isoformat(), "running")
    interrupted["internal"]["execution_kind"] = "case_review_ai"
    interrupted["case_review_ai"] = {"status": "running"}
    store.save(interrupted)
    assert store.recover_interrupted() == [interrupted_id]
    recovered = store.load(interrupted_id)
    assert recovered["status"] == "waiting_case_review"
    assert recovered["case_review_ai"]["error_code"] == "WORKER_INTERRUPTED"


def test_concurrent_submit_only_one_claims_last_queue_slot(tmp_path: Path) -> None:
    """两个并发提交竞争最后一个等待位时，只允许一个成功。"""

    store = TaskStore(tmp_path / "runtime")
    manager = TaskManager(
        store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: {},
        result_collector=lambda *_: {}, project_root=Path(__file__).resolve().parents[2],
        prompt_paths=[], app_revision="test", autostart=False,
    )
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def submit_one(index: int) -> None:
        task_id = new_task_id()
        store.task_dir(task_id, create=True)
        barrier.wait()
        try:
            manager.submit(record(task_id, f"2026-01-01T00:00:0{index}+00:00"), {}, max_waiting=1)
            outcomes.append("accepted")
        except Exception as exc:
            outcomes.append(getattr(exc, "code", type(exc).__name__))

    threads = [threading.Thread(target=submit_one, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["TASK_QUEUE_FULL", "accepted"]


def test_running_cancel_and_timeout_are_terminal(tmp_path: Path) -> None:
    """运行中取消会终止进程组，超时不会被迟到退出码覆盖。"""

    store = TaskStore(tmp_path / "runtime")
    config = {
        "normal": {"TASK_TIMEOUT_SECONDS": 5, "LLM_MODEL": "test"},
        "secrets": {"LLM_API_KEY": "sentinel"},
    }
    manager = TaskManager(
        store=store, runner_module="tests.services.fake_runner", config_loader=lambda _record: config,
        result_collector=lambda *_args: {"status": "succeeded", "stage": "completed", "artifacts": []},
        project_root=Path(__file__).resolve().parents[2], prompt_paths=[], app_revision="test",
    )
    cancel_id = new_task_id()
    store.task_dir(cancel_id, create=True)
    manager.submit(record(cancel_id, datetime.now(UTC).isoformat()), {"sleep": 30})
    wait_status(store, cancel_id, "running")
    manager.cancel(cancel_id)
    wait_status(store, cancel_id, "cancelled")
    manager.stop()

    timeout_store = TaskStore(tmp_path / "timeout-runtime")
    timeout_config = {"normal": {"TASK_TIMEOUT_SECONDS": 0}, "secrets": {"LLM_API_KEY": "sentinel"}}
    timeout_manager = TaskManager(
        store=timeout_store, runner_module="tests.services.fake_runner", config_loader=lambda _record: timeout_config,
        result_collector=lambda *_args: {}, project_root=Path(__file__).resolve().parents[2],
        prompt_paths=[], app_revision="test",
    )
    timeout_id = new_task_id()
    timeout_store.task_dir(timeout_id, create=True)
    timeout_manager.submit(record(timeout_id, datetime.now(UTC).isoformat()), {"sleep": 30})
    timed_out = wait_status(timeout_store, timeout_id, "failed")
    timeout_manager.stop()
    assert timed_out["error_code"] == "TASK_TIMEOUT"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("CONFIG_NOT_READY"), "CONFIG_NOT_READY"),
        (RuntimeError("429 insufficient_quota"), "LLM_RATE_LIMITED"),
        (TimeoutError("timed out"), "LLM_TIMEOUT"),
        (json.JSONDecodeError("bad", "{", 0), "LLM_RESPONSE_INVALID"),
    ],
)
def test_runner_exception_mapping_is_stable_and_redacted(error: Exception, expected: str) -> None:
    """Runner 错误只输出稳定码和中文摘要，不回显第三方异常原文。"""

    code, message = classify_runner_exception(
        error,
        default_code="WORKFLOW_FAILED",
        default_message="工作流执行失败",
    )
    assert code == expected
    assert str(error) not in message


def test_requirement_decomposition_failure_cannot_be_reported_as_success() -> None:
    """独立需求拆解返回 success=false 时，Runner 必须结束为失败。"""

    class FailedResult:
        success = False
        errors = ["FileNotFoundError: Prompt 文件不存在"]

    with pytest.raises(RuntimeError, match="需求拆解失败"):
        _require_decomposition_success(FailedResult())


def test_dependency_warning_filter_targets_only_langchain_pending_warning() -> None:
    """仅过滤已确认的 LangChain Pending 警告，不吞掉普通运行告警。"""

    import warnings
    from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

    _configure_dependency_warnings()
    with warnings.catch_warnings(record=True) as captured:
        warnings.warn(
            "The default value of `allowed_objects` will change in a future version.",
            LangChainPendingDeprecationWarning,
        )
        warnings.warn("ordinary warning", UserWarning)
    assert [str(item.message) for item in captured] == ["ordinary warning"]
