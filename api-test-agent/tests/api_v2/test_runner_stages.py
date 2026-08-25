"""API V2 Runner 阶段产物、Review 门禁和重试保留测试。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import services.api_agent.runner as runner_module
from services.api_agent.runner import _run
from services.api_agent.task_manager import ApiTaskManager
from services.api_agent.v2_store import ApiV2Store
from services.common.artifacts import load_registry
from services.common.task_store import TaskStore, new_task_id


def _prepare(tmp_path, monkeypatch):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    source = Path(__file__).parent / "fixtures" / "openapi3.yaml"
    (task_dir / "input" / "source.yaml").write_bytes(source.read_bytes())
    store.save({"id": task_id, "schema_version": 2, "current_versions": {}, "completed_stages": []})
    attempt = ApiV2Store(store).create_attempt(task_id, stage="document_preflight")
    TaskStore.atomic_write_json(task_dir / "request.json", {
        "input_relative_path": "input/source.yaml", "input_original_name": "source.yaml",
        "input_sha256": "source-sha", "from_stage": "document_preflight", "attempt_id": attempt["id"],
    })
    TaskStore.atomic_write_json(task_dir / "execution.json", {"sequence": 1, "kind": "initial"})
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    return store, task_id


def test_runner_preserves_each_stage_and_requires_review(tmp_path, monkeypatch):
    store, task_id = _prepare(tmp_path, monkeypatch)

    parsed = _run(task_id)
    assert parsed["next_status"] == "waiting_contract_review"
    assert len(load_registry(store, task_id)) >= 2

    versions = ApiV2Store(store)
    contracts = versions.load_version(task_id, "contracts")["items"]
    contracts[0]["status"] = "confirmed"
    reviewed = versions.save_version(task_id, kind="contracts", items=contracts, created_by="reviewer")
    request_path = store.task_dir(task_id) / "request.json"
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    attempt = versions.create_attempt(task_id, stage="base_case_generation", source_versions={"contracts": reviewed["version"]})
    request_payload.update({
        "from_stage": "base_case_generation", "attempt_id": attempt["id"],
        "source_versions": {"contracts": reviewed["version"]},
        "generation_kernel": "v2_fused",
    })
    TaskStore.atomic_write_json(request_path, request_payload)
    TaskStore.atomic_write_json(store.task_dir(task_id) / "execution.json", {"sequence": 2, "kind": "base_case_generation"})

    generated = _run(task_id)
    assert generated["next_status"] == "waiting_case_review"
    assert versions.load_version(task_id, "coverage")["items"]["round_count"] <= 3
    base_cases = versions.load_version(task_id, "base-cases")["items"]
    assert all(item["steps"] and item["expected_results"] for item in base_cases)
    assert all(item["generation_kernel"] == "v2_fused" for item in base_cases)
    assert (store.task_dir(task_id) / "attempts" / attempt["id"] / "events.jsonl").is_file()
    assert (store.task_dir(task_id) / "attempts" / attempt["id"] / "generation-provenance.json").is_file()
    assert len(load_registry(store, task_id)) >= 4


def test_runner_failure_preserves_the_actual_failed_stage(tmp_path, monkeypatch):
    """阶段异常写回真实阶段，避免失败任务被错误展示为报告阶段。"""

    store, task_id = _prepare(tmp_path, monkeypatch)
    request_path = store.task_dir(task_id) / "request.json"
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["from_stage"] = "base_case_generation"
    TaskStore.atomic_write_json(request_path, request_payload)
    monkeypatch.setattr(runner_module, "_run", lambda _task_id: (_ for _ in ()).throw(ValueError("bad candidate")))
    monkeypatch.setattr(sys, "argv", ["runner", "--task-id", task_id])

    assert runner_module.main() == 1
    result = json.loads((store.task_dir(task_id) / "runner-result.json").read_text(encoding="utf-8"))
    assert result["stage"] == "base_case_generation"


def test_development_attempts_default_to_v24_core_workflow(monkeypatch):
    """开发/测试新 Attempt 必须真实接入核心 Workflow，生产仍保持最小内核。"""

    monkeypatch.delenv("API_GENERATION_KERNEL", raising=False)
    monkeypatch.setenv("PLATFORM_RUNTIME_ENV", "dev")
    assert ApiTaskManager._generation_kernel() == "v2_core_workflow"
    monkeypatch.setenv("PLATFORM_RUNTIME_ENV", "production")
    assert ApiTaskManager._generation_kernel() == "v2_minimal"


def test_runner_subprocess_emits_structured_stage_log(tmp_path, monkeypatch):
    """成功阶段也必须向 stdout 输出可供 Runner 日志窗口读取的结构化记录。"""

    _store, task_id = _prepare(tmp_path, monkeypatch)
    result = subprocess.run(
        [sys.executable, "-m", "services.api_agent.runner", "--task-id", task_id],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "AGENT_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert [item["event"] for item in records] == ["stage_started", "stage_completed"]
    assert all(item["task_id"] == task_id for item in records)
