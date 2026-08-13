"""API 用例数据库持久化开关回归测试。"""

from __future__ import annotations

from agents.api_test.workflows.api_basecase_workflow import ApiBaseCaseGeneratorWorkFlow
from agents.api_test.workflows.api_run_case_wrokflow import ApiRunCaseGeneratorWorkFlow


def test_database_disabled_keeps_cases_without_connecting(monkeypatch) -> None:
    def forbidden():
        raise AssertionError("数据库关闭时不允许建立连接")

    monkeypatch.setattr("agents.api_test.workflows.api_basecase_workflow.get_system_db_connection", forbidden)
    monkeypatch.setattr("agents.api_test.workflows.api_run_case_wrokflow.get_system_db_connection", forbidden)
    base = ApiBaseCaseGeneratorWorkFlow().output_base_case({"cases": [{"name": "case", "steps": []}], "persist_to_database": False})
    run = ApiRunCaseGeneratorWorkFlow.sava_api_case({"api_case": {"name": "case"}, "persist_to_database": False})
    assert base["out_put_cases"][0]["name"] == "case"
    assert base["database_persist_status"] == "skipped"
    assert run["skipped"] is True


def test_database_failure_does_not_drop_generated_cases(monkeypatch) -> None:
    monkeypatch.setattr(ApiBaseCaseGeneratorWorkFlow, "_save_base_cases_to_db", lambda *_args: [])
    result = ApiBaseCaseGeneratorWorkFlow().output_base_case({
        "cases": [{"name": "case", "steps": []}], "persist_to_database": True, "interface_id": 10,
    })
    assert result["out_put_cases"] == [{"name": "case", "steps": []}]
    assert result["database_persist_status"] == "failed"


def test_database_enabled_preserves_existing_success_path(monkeypatch) -> None:
    """开启写入时仍返回数据库结果，证明新开关没有改变原有成功语义。"""

    saved_cases = [{"id": 101, "name": "case", "steps": "[]"}]
    monkeypatch.setattr(
        ApiBaseCaseGeneratorWorkFlow,
        "_save_base_cases_to_db",
        lambda _self, cases, interface_id: saved_cases
        if cases and interface_id == 10
        else [],
    )
    result = ApiBaseCaseGeneratorWorkFlow().output_base_case({
        "cases": [{"name": "case", "steps": []}],
        "persist_to_database": True,
        "interface_id": 10,
    })
    assert result["out_put_cases"] == saved_cases
    assert result["database_persist_status"] == "succeeded"
