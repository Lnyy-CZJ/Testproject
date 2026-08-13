"""API V2 版本存储和阶段产物保留测试。"""

from services.api_agent.v2_store import ApiV2Store
from services.common.artifacts import load_registry
from services.common.task_store import TaskStore, new_task_id


def test_version_is_append_only_and_artifacts_are_merged(tmp_path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "schema_version": 2, "current_versions": {}})
    versions = ApiV2Store(store)

    first = versions.save_version(task_id, kind="contracts", items=[{"id": "contract_1"}])
    second = versions.save_version(task_id, kind="base-cases", items=[{"id": "case_1"}])

    assert first["version"] == 1
    assert second["version"] == 1
    assert len(load_registry(store, task_id)) == 2
    assert versions.load_version(task_id, "contracts")["items"][0]["id"] == "contract_1"


def test_attempt_and_run_use_isolated_directories(tmp_path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "schema_version": 2})
    versions = ApiV2Store(store)

    attempt = versions.create_attempt(task_id, stage="contract_parsing")
    run_path = versions.save_run_document(task_id, "run_123", "input.json", {"case_ids": []})

    assert attempt["id"].startswith("attempt_")
    assert run_path.parent.name == "run_123"
