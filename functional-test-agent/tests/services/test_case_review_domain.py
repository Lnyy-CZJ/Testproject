"""测试用例 Review 规范化、校验、CAS 和确认测试。"""

import json
from pathlib import Path

import pytest

from services.common.case_review import CaseReviewService, case_content_sha256, normalize_cases, validate_cases
from services.common.errors import ServiceError
from services.common.task_store import TaskStore, new_task_id


def case(case_id: str = "TC001", point_id: str = "TP001", **updates):
    value = {
        "case_id": case_id, "test_point_id": point_id, "module": "登录", "feature": "密码",
        "scenario": "正常", "case_name": "登录成功", "priority": "P1",
        "preconditions": ["用户存在"], "test_steps": ["输入账号", "点击登录"],
        "test_data": {"user": "tester"}, "expected_result": "进入首页", "actual_result": "",
        "extension": {"keep": True},
    }
    value.update(updates)
    return value


def prepare(tmp_path: Path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    points = task_dir / "input" / "review-test-points-v1.json"
    points.write_text(json.dumps([{"id": "TP001"}, {"id": "TP002"}], ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "request.json", {"review_relative_path": "input/review-test-points-v1.json"})
    source = task_dir / "published" / "test-cases" / "generated.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps([case(), case("TC002", "TP002")], ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "artifact_cases", "type": "test_cases_json", "relative_path": "published/test-cases/generated.json", "created_at": "2026-01-01", "expired": False}]})
    store.save({"id": task_id, "status": "waiting_case_review", "review": {"relative_path": "input/review-test-points-v1.json"}, "internal": {}})
    return store, task_id, CaseReviewService(store)


def test_normalize_validation_coverage_and_extensions() -> None:
    normalized = normalize_cases([case(preconditions="用户存在\n系统可用", test_steps="1. 输入账号\n2、点击登录")])
    assert normalized[0]["preconditions"] == ["用户存在", "系统可用"]
    assert normalized[0]["test_steps"] == ["输入账号", "点击登录"]
    assert normalized[0]["extension"] == {"keep": True}
    result = validate_cases(normalized, confirmed_point_ids={"TP001", "TP002"})
    assert not result.valid_for_confirm
    assert result.coverage.uncovered_ids == ["TP002"]
    duplicate = validate_cases([case(), case("TC002")], confirmed_point_ids={"TP001"})
    assert any(issue.code == "CASE_EXACT_DUPLICATE" for issue in duplicate.errors)
    reused = validate_cases([case(), case("TC002", test_data={"user": "other"})], confirmed_point_ids={"TP001"})
    assert any(issue.code == "CASE_NAME_REUSED" for issue in reused.warnings)


def test_case_draft_cas_and_confirmation(tmp_path: Path) -> None:
    store, task_id, service = prepare(tmp_path)
    loaded = service.load(task_id)
    changed = [case(case_name="正常登录"), case("TC002", "TP002")]
    saved = service.save_draft(task_id, changed, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester")
    assert saved["revision"] == 1
    assert saved["cases"][0]["extension"] == {"keep": True}
    with pytest.raises(ServiceError) as conflict:
        service.save_draft(task_id, changed, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester")
    assert conflict.value.code == "CASE_REVIEW_REVISION_CONFLICT"
    confirmed = service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)
    assert confirmed["version"] == 1
    assert service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)["version"] == 1
    assert case_content_sha256(service.read_confirmed(task_id, confirmed)) == saved["sha256"]
