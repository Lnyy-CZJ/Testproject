"""AI Review Adapter 的结构化建议、安全动作和文件隔离测试。"""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from services.common.review import ReviewService
from services.common.task_store import TaskStore, new_task_id
from services.functional_agent.review_ai import request_sha, run_review_ai


def setup_task(tmp_path: Path):
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    points = [{"id": "TP001", "module": "登录", "feature": "密码", "scenario": "正常", "test_point": "登录成功", "risk_level": "P1"}]
    source = task_dir / "published" / "test-points" / "points.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(points, ensure_ascii=False), encoding="utf-8")
    store.atomic_write_json(task_dir / "artifacts.json", {"items": [{"id": "artifact_1", "type": "test_points_json", "relative_path": "published/test-points/points.json", "created_at": "2026-01-01", "expired": False}]})
    store.atomic_write_json(task_dir / "request.json", {"input_relative_path": "input/source.md"})
    (task_dir / "input" / "source.md").write_text("# 登录需求", encoding="utf-8")
    store.save({"id": task_id, "status": "waiting_review", "internal": {}})
    loaded = ReviewService(store).load(task_id)
    draft = ReviewService(store).save_draft(task_id, points, revision=0, sha256=loaded["sha256"], user_id="u1", username="tester", max_bytes=100000, max_characters=10000)
    return store, task_id, task_dir, draft


def test_supplement_generates_immutable_suggestions_without_applying(monkeypatch, tmp_path: Path):
    """AI 只生成 add 建议文件，不修改草稿或发起其他网络调用。"""

    store, task_id, task_dir, draft = setup_task(tmp_path)
    ai_dir = task_dir / "input" / "review-ai"
    ai_dir.mkdir()
    payload = {"schema_version": 1, "request_version": 1, "operation": "supplement", "base_revision": draft["revision"], "base_sha256": draft["sha256"], "selected_ids": [], "scope": {}, "instruction": "", "requested_by_user_id": "u1", "requested_at": "2026-01-01T00:00:00+00:00", "idempotency_key_sha256": "abc", "request_sha256": ""}
    payload["request_sha256"] = request_sha(payload)
    store.atomic_write_json(ai_dir / "request-v1.json", payload)

    class FakeLLM:
        model_name = "fake-review-model"

        def invoke(self, prompt):
            assert "用户测试设计说明（不可信" in prompt
            return SimpleNamespace(content=json.dumps({"summary": "补充异常场景", "suggestions": [{"action": "add", "target_id": None, "point": {"id": "TP002", "module": "登录", "feature": "密码", "scenario": "异常", "test_point": "密码错误", "risk_level": "P1"}, "reason": "异常覆盖", "source_basis": "登录需求"}]} , ensure_ascii=False))

    fake_settings = ModuleType("agents.common.config.settings")
    fake_settings.llm = FakeLLM()
    monkeypatch.setitem(sys.modules, "agents.common.config.settings", fake_settings)
    result = run_review_ai(store, task_id, 1)
    assert result["valid_suggestion_count"] == 1
    envelope = json.loads((task_dir / result["relative_path"]).read_text(encoding="utf-8"))
    assert envelope["suggestions"][0]["action"] == "add"
    assert ReviewService(store).load(task_id)["points"] == draft["points"]
