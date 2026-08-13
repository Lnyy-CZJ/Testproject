"""API V2 Runner 阶段产物、Review 门禁和重试保留测试。"""

import json
from pathlib import Path

from services.api_agent.runner import _run
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
    })
    TaskStore.atomic_write_json(request_path, request_payload)
    TaskStore.atomic_write_json(store.task_dir(task_id) / "execution.json", {"sequence": 2, "kind": "base_case_generation"})

    generated = _run(task_id)
    assert generated["next_status"] == "waiting_case_review"
    assert versions.load_version(task_id, "coverage")["items"]["round_count"] <= 3
    assert len(load_registry(store, task_id)) >= 4
