"""在线 Review 领域规则与文件事务测试。"""

import json
from pathlib import Path

import pytest

from services.common.errors import ServiceError
from services.common.review import ReviewService, diff_points, review_content_sha256, validate_points
from services.common.task_store import TaskStore, new_task_id


def point(point_id: str = "TP001", **updates):
    value = {"id": point_id, "module": "登录", "feature": "密码", "scenario": "正常", "test_point": "登录成功", "risk_level": "P1", "extension": {"keep": True}}
    value.update(updates)
    return value


def prepare(tmp_path: Path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    published = task_dir / "published" / "test-points" / "points.json"
    published.parent.mkdir(parents=True)
    published.write_text(json.dumps([point()], ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "artifact_1", "type": "test_points_json", "relative_path": "published/test-points/points.json", "created_at": "2026-01-01", "expired": False}]})
    store.save({"id": task_id, "status": "waiting_review", "internal": {}})
    return store, task_id, ReviewService(store)


def test_validation_extensions_duplicates_and_diff():
    original = [point()]
    current = [point(test_point="登录失败"), point("TP002", scenario="异常", test_point="登录失败")]
    result = validate_points(current, original=original)
    assert result.valid_for_resume
    assert any(issue.code == "POINT_TEXT_REUSED" for issue in result.warnings)
    assert diff_points(original, current) == {"added": 1, "modified": 1, "deleted": 0, "unchanged": 0, "risk_changed": 0}
    duplicate = validate_points([point(), point("TP002")])
    assert any(issue.code == "POINT_EXACT_DUPLICATE" for issue in duplicate.errors)
    assert review_content_sha256([point()]) == review_content_sha256([point()])
    risk_changed = validate_points([point(risk_level="P0")], original=original)
    assert any(issue.code == "RISK_LEVEL_CHANGED" for issue in risk_changed.warnings)


def test_draft_cas_and_immutable_confirmation(tmp_path: Path):
    store, task_id, service = prepare(tmp_path)
    loaded = service.load(task_id)
    changed = [point(test_point="修改后")]
    saved = service.save_draft(task_id, changed, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester", max_bytes=1024 * 1024, max_characters=10000)
    assert saved["revision"] == 1
    assert saved["points"][0]["extension"] == {"keep": True}
    same = service.save_draft(task_id, changed, revision=1, sha256=saved["sha256"], user_id="u1", username="tester", max_bytes=1024 * 1024, max_characters=10000)
    assert same["revision"] == 1
    with pytest.raises(ServiceError) as conflict:
        service.save_draft(task_id, [point()], revision=0, sha256=loaded["sha256"], user_id="u1", username="tester", max_bytes=1024 * 1024, max_characters=10000)
    assert conflict.value.code == "REVIEW_REVISION_CONFLICT"
    confirmed = service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)
    assert confirmed["version"] == 1
    # 模拟确认文件成功发布、task.json 索引尚未更新的崩溃窗口，重试必须复用 v1。
    assert service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)["version"] == 1
    record = store.load(task_id)
    record["review"] = confirmed
    store.save(record)
    assert service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)["version"] == 1
