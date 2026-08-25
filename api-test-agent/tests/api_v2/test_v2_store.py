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


def test_execution_plan_versions_are_append_only_and_use_own_directory(tmp_path):
    """执行计划必须像契约一样不可变保存，不能混入 Run 目录。"""

    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "schema_version": 2, "current_versions": {}})
    versions = ApiV2Store(store)

    first = versions.save_version(
        task_id, kind="execution-plans", items={"plan_id": "plan_1"},
        source_versions={"executable-cases": 1}, artifact_schema_version=1,
    )
    second = versions.save_version(
        task_id, kind="execution-plans", items={"plan_id": "plan_2"},
        source_versions={"executable-cases": 2}, artifact_schema_version=1,
    )

    assert first["version"] == 1
    assert second["version"] == 2
    assert first["artifact_schema_version"] == 1
    assert (store.task_dir(task_id) / "versions" / "execution-plans" / "v1.json").exists()
