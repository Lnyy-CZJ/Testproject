"""确认测试用例 JSON/XLSX 同源发布测试。"""

import json
from pathlib import Path

from openpyxl import load_workbook

from services.common.case_review import CaseReviewService
from services.common.task_store import TaskStore, new_task_id
from services.functional_agent.case_review_publisher import publish_confirmed_cases


def test_publish_is_idempotent_and_escapes_formulas(tmp_path: Path) -> None:
    """同一确认版本重试不重复登记，XLSX 不执行用户公式。"""

    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    points = task_dir / "input" / "review-test-points-v1.json"
    points.write_text('[{"id":"TP001"}]', encoding="utf-8")
    cases = [{
        "case_id": "TC001", "test_point_id": "TP001", "module": "登录", "feature": "密码",
        "scenario": "正常", "case_name": "=危险公式", "priority": "P1", "preconditions": [],
        "test_steps": ["输入账号", "点击登录"], "test_data": {}, "expected_result": "进入首页", "actual_result": "",
        "custom": {"keep": True},
    }]
    source = task_dir / "published" / "test-cases" / "generated.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "request.json", {"review_relative_path": "input/review-test-points-v1.json"})
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "generated", "type": "test_cases_json", "relative_path": "published/test-cases/generated.json", "created_at": "2026-01-01", "expired": False}]})
    store.save({"id": task_id, "status": "waiting_case_review", "review": {"relative_path": "input/review-test-points-v1.json"}, "internal": {}})
    service = CaseReviewService(store)
    loaded = service.load(task_id)
    saved = service.save_draft(task_id, cases, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester")
    confirmed = service.confirm(task_id, revision=1, sha256=saved["sha256"], accept_warnings=True)
    first = publish_confirmed_cases(store, task_id, confirmed)
    second = publish_confirmed_cases(store, task_id, confirmed)
    assert [item["id"] for item in first] == [item["id"] for item in second]
    assert json.loads((task_dir / first[0]["relative_path"]).read_text(encoding="utf-8")) == cases
    workbook = load_workbook(task_dir / first[1]["relative_path"], data_only=False)
    assert workbook.active["F2"].value == "'=危险公式"
    assert workbook.active["I2"].value == "1. 输入账号\n2. 点击登录"
    assert workbook.active["M1"].value == "其他字段"
    assert workbook.active["M2"].value == '{"custom":{"keep":true}}'
