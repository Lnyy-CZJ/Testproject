"""公共版本化 Review 文件事务测试。"""

import json
from pathlib import Path

import pytest

from services.common.errors import ServiceError
from services.common.task_store import TaskStore, new_task_id
from services.common.versioned_review import TEST_CASE_SPEC, TEST_POINT_SPEC, VersionedReviewStore


def test_specs_are_isolated_and_confirmation_is_immutable(tmp_path: Path) -> None:
    """两类 Review 使用不同路径，确认文件不能被覆盖。"""

    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    points = VersionedReviewStore(store, TEST_POINT_SPEC)
    cases = VersionedReviewStore(store, TEST_CASE_SPEC)
    assert points.draft_path(task_id).name == "review-draft.json"
    assert cases.draft_path(task_id).name == "case-review-draft.json"
    path = cases.create_confirmed(task_id, 1, [{"case_id": "TC001"}])
    assert json.loads(path.read_text(encoding="utf-8"))[0]["case_id"] == "TC001"
    with pytest.raises(ServiceError):
        cases.create_confirmed(task_id, 1, [{"case_id": "TC002"}])
    assert cases.confirmed_files(task_id) == [(1, path)]
