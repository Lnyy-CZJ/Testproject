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
    assert case_content_sha256(service.read_confirmed(task_id, confirmed)) == confirmed["rows_sha256"]


def test_case_confirmation_allows_quality_errors_but_keeps_safety_limits(tmp_path: Path) -> None:
    """业务格式、覆盖和告警只提示；数量等技术边界仍必须拒绝发布。"""

    _store, task_id, service = prepare(tmp_path)
    loaded = service.load(task_id)
    risky = [case(case_name="", point_id="UNKNOWN", priority="PX", test_steps=[], expected_result="")]
    saved = service.save_draft(
        task_id, risky, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester",
    )
    assert saved["validation"]["errors"]
    confirmed = service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=False)
    assert confirmed["version"] == 1
    assert confirmed["quality_summary"]["errors"] > 0
    assert confirmed["quality_summary"]["uncovered"] == 2

    loaded_again = service.load(task_id)
    oversized = [case("TC001"), case("TC002", "TP002")]
    saved_again = service.save_draft(
        task_id, oversized, revision=loaded_again["revision"], sha256=loaded_again["sha256"],
        user_id="u1", username="tester", max_cases=1,
    )
    with pytest.raises(ServiceError) as blocked:
        service.confirm(
            task_id, revision=saved_again["revision"], sha256=saved_again["sha256"],
            accept_warnings=True, max_cases=1,
        )
    assert blocked.value.code == "CASE_REVIEW_SAFETY_LIMIT_FAILED"


def test_case_confirmation_rejects_non_object_array_items(tmp_path: Path) -> None:
    """用例发布的唯一业务结构硬条件是顶层对象数组。"""

    _store, task_id, service = prepare(tmp_path)
    loaded = service.load(task_id)
    saved = service.save_draft(
        task_id, ["not-an-object"], revision=0, sha256=loaded["sha256"],
        user_id="u1", username="tester",
    )
    with pytest.raises(ServiceError) as blocked:
        service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)
    assert blocked.value.code == "CASE_REVIEW_SAFETY_LIMIT_FAILED"
    assert any(issue["code"] == "CASE_ITEM_NOT_OBJECT" for issue in saved["validation"]["errors"])
