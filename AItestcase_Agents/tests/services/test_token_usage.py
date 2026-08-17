"""功能智能体 Token 用量采集测试。"""

from __future__ import annotations

from agents.common.utils.token_usage import load_token_usage, record_token_usage


def test_token_usage_accumulates_by_stage_atomically(tmp_path, monkeypatch) -> None:
    """同一阶段多次调用应累加，未报告调用不能伪造 Token。"""

    task_id = "task_20260817_1234567890abcdef1234"
    (tmp_path / task_id).mkdir()
    monkeypatch.setenv("AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TASK_ID", task_id)
    record_token_usage("test_points_generation", {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    record_token_usage("test_points_generation", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    usage = load_token_usage()
    assert usage["stages"]["test_points_generation"] == {
        "input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "calls": 2, "reported_calls": 1,
    }
    assert usage["totals"]["total_tokens"] == 15
