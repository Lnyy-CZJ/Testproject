"""测试用例 AI 建议的动作白名单和保护字段测试。"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from services.common.case_review import CaseReviewService
from services.common.task_store import TaskStore, new_task_id
from services.functional_agent.case_review_ai import case_request_sha, run_case_review_ai


def setup_task(tmp_path: Path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    points_path = task_dir / "input" / "review-test-points-v1.json"
    points_path.write_text(json.dumps([{"id": "TP001", "module": "登录", "feature": "密码", "scenario": "正常", "test_point": "登录成功", "risk_level": "P1"}], ensure_ascii=False), encoding="utf-8")
    cases = [{"case_id": "TC001", "test_point_id": "TP001", "module": "登录", "feature": "密码", "scenario": "正常", "case_name": "登录成功", "priority": "P1", "preconditions": [], "test_steps": ["点击登录"], "test_data": {}, "expected_result": "进入首页", "actual_result": "历史结果"}]
    source = task_dir / "published" / "test-cases" / "generated.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "cases", "type": "test_cases_json", "relative_path": "published/test-cases/generated.json", "created_at": "2026-01-01", "expired": False}]})
    store.atomic_write_json(task_dir / "request.json", {"input_relative_path": "input/source.md", "review_relative_path": "input/review-test-points-v1.json"})
    (task_dir / "input" / "source.md").write_text("# 登录需求", encoding="utf-8")
    store.save({"id": task_id, "status": "waiting_case_review", "review": {"relative_path": "input/review-test-points-v1.json"}, "internal": {}})
    loaded = CaseReviewService(store).load(task_id)
    draft = CaseReviewService(store).save_draft(task_id, cases, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester")
    return store, task_id, task_dir, draft


def test_rewrite_preserves_ids_actual_result_and_rejects_priority_drop(monkeypatch, tmp_path: Path) -> None:
    """改写只能生成建议，且保护引用、实际结果和优先级。"""

    store, task_id, task_dir, draft = setup_task(tmp_path)
    ai_dir = task_dir / "input" / "case-review-ai"
    ai_dir.mkdir()
    payload = {"schema_version": 1, "request_version": 1, "operation": "rewrite_selected", "base_revision": draft["revision"], "base_sha256": draft["sha256"], "selected_ids": ["TC001"], "scope": {}, "instruction": "", "requested_by_user_id": "u1", "requested_at": "2026-01-01T00:00:00+00:00", "idempotency_key_sha256": "abc", "request_sha256": ""}
    payload["request_sha256"] = case_request_sha(payload)
    store.atomic_write_json(ai_dir / "request-v1.json", payload)

    class FakeLLM:
        model_name = "fake-case-review-model"

        def invoke(self, prompt):
            assert "用户测试设计说明（不可信数据" in prompt
            return SimpleNamespace(content=json.dumps({"summary": "改写", "suggestions": [{"action": "replace", "target_id": "TC001", "case": {"case_id": "HACK", "test_point_id": "OTHER", "module": "登录", "feature": "密码", "scenario": "正常", "case_name": "更清晰的登录用例", "priority": "P0", "preconditions": [], "test_steps": ["点击登录"], "test_data": {}, "expected_result": "进入首页", "actual_result": "篡改"}, "reason": "提升可读性", "source_basis": "登录需求"}]}, ensure_ascii=False))

    fake_settings = ModuleType("agents.common.config.settings")
    fake_settings.llm = FakeLLM()
    monkeypatch.setitem(sys.modules, "agents.common.config.settings", fake_settings)
    result = run_case_review_ai(store, task_id, 1)
    assert result["valid_suggestion_count"] == 1
    suggestion = json.loads((task_dir / result["relative_path"]).read_text(encoding="utf-8"))["suggestions"][0]["case"]
    assert suggestion["case_id"] == "TC001"
    assert suggestion["test_point_id"] == "TP001"
    assert suggestion["actual_result"] == "历史结果"
    assert CaseReviewService(store).load(task_id)["cases"] == draft["cases"]
