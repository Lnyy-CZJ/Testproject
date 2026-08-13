from __future__ import annotations

import json
from pathlib import Path

from requirement_decomposition.models.schema import (
    DecompositionResult,
    EvidenceSummary,
    TestSeed as RequirementTestSeed,
    TestSeedRecord as RequirementTestSeedRecord,
)

from agents.functional_test.workflows import case_generator_workflow as workflow


def test_build_requirement_context_prefers_structured_requirement_context():
    state = {
        "document": "原始需求文档",
        "requirement_context": "结构化 test_seed 上下文",
    }

    assert workflow.build_requirement_context(state) == "结构化 test_seed 上下文"


def test_build_test_seed_requirement_context_formats_seed_for_test_point_generation():
    seed = RequirementTestSeedRecord(
        requirement_id="SEED-001",
        requirement_ids=["REQ-001", "REQ-002"],
        module="账号模块",
        feature="密码登录",
        source_trace={"source_ids": ["SRC-001"], "section_ids": ["SEC-001"]},
        test_seed=RequirementTestSeed(
            objects=["用户名", "密码"],
            conditions=["用户已注册"],
            constraints=["用户名不能为空", "密码长度为 8 到 20 位"],
            permissions=["普通用户"],
            state_transitions=["未登录 -> 已登录"],
            invalid_state_transitions=["锁定 -> 已登录"],
            risk_tags=["权限", "异常流程"],
            expected_results=["登录成功后进入首页"],
            negative_suggestions=["连续输错密码后账号锁定"],
            requirement_titles=["密码登录主流程"],
            uncertain_items=["REQ-002: 未确定 - 锁定次数未定义"],
        ),
        evidence_summary=EvidenceSummary(
            fact_fields_grounded=True,
            suggestions_include_inferred_items=True,
        ),
        status_tags=["候选确认", "存在未确定项"],
    )

    context = workflow.build_test_seed_requirement_context([seed])

    assert "模块: 账号模块" in context
    assert "功能: 密码登录" in context
    assert "需求ID: REQ-001, REQ-002" in context
    assert "测试对象: 用户名；密码" in context
    assert "业务约束: 用户名不能为空；密码长度为 8 到 20 位" in context
    assert "权限规则: 普通用户" in context
    assert "有效状态流转: 未登录 -> 已登录" in context
    assert "无效状态流转: 锁定 -> 已登录" in context
    assert "预期结果: 登录成功后进入首页" in context
    assert "不确定项: REQ-002: 未确定 - 锁定次数未定义" in context
    assert "不确定项只能作为需确认或建议类测试方向" in context


def test_prepare_requirement_context_returns_empty_context_when_decomposition_fails(tmp_path):
    source_file = tmp_path / "login.md"
    source_file.write_text("# 登录\n\n用户可以使用密码登录。", encoding="utf-8")

    def failing_runner(source_path: str, config_path: str):
        assert Path(source_path) == source_file
        assert config_path == "requirement_decomposition.yaml"
        return DecompositionResult(success=False, errors=["LLM unavailable"])

    context, report = workflow.prepare_requirement_context_from_document_path(
        document_path=str(source_file),
        decomposition_runner=failing_runner,
    )

    assert context == ""
    assert report["success"] is False
    assert report["errors"] == ["LLM unavailable"]


def test_prepare_requirement_context_reuses_cached_test_seed(tmp_path):
    source_file = tmp_path / "历史记录需求功能.md"
    source_file.write_text("# 历史记录\n\n用户可以查看历史记录。", encoding="utf-8")
    output_dir = tmp_path / "requirements_docs" / "历史记录"
    output_dir.mkdir(parents=True)
    seed = RequirementTestSeedRecord(
        requirement_id="SEED-001",
        requirement_ids=["REQ-001"],
        module="历史记录",
        feature="历史记录列表",
        source_trace={"source_ids": ["SRC-001"], "section_ids": ["SEC-001"]},
        test_seed=RequirementTestSeed(objects=["历史记录列表"]),
        evidence_summary=EvidenceSummary(fact_fields_grounded=True),
        status_tags=["候选确认"],
    )
    (output_dir / "test_seed.json").write_text(
        json.dumps([seed.model_dump(mode="json")], ensure_ascii=False),
        encoding="utf-8",
    )

    def unexpected_runner(**kwargs):
        raise AssertionError("已有 test_seed.json 时不应重新执行需求拆解")

    context, report = workflow.prepare_requirement_context_from_document_path(
        document_path=str(source_file),
        requirements_output_dir=str(output_dir),
        decomposition_runner=unexpected_runner,
    )

    assert "模块: 历史记录" in context
    assert report["success"] is True
    assert report["reused_cached_decomposition"] is True
    assert report["output_dir"] == str(output_dir.resolve())


def test_resolve_requirement_output_dir_defaults_to_requirements_docs_feature_folder(tmp_path):
    source_file = tmp_path / "历史记录需求功能.md"
    source_file.write_text("# 历史记录", encoding="utf-8")

    output_dir = workflow.resolve_requirement_output_dir(
        document_path=str(source_file),
        feature_name="历史记录",
        output_base_dir=str(tmp_path / "output" / "requirements_docs"),
    )

    assert output_dir == (tmp_path / "output" / "requirements_docs" / "历史记录").resolve()


def test_build_case_generation_points_preserves_structured_test_point_fields():
    test_points = [
        {
            "id": "TP001",
            "module": "个人中心",
            "feature": "订阅状态",
            "scenario": "订阅状态卡片",
            "test_point": "UI显示检查",
            "risk_level": "P3",
        }
    ]

    case_points = workflow.build_case_generation_points(test_points)

    assert case_points == [
        {
            "id": "TP001",
            "module": "个人中心",
            "feature": "订阅状态",
            "scenario": "订阅状态卡片",
            "test_point": "UI显示检查",
            "risk_level": "P3",
        }
    ]


def test_merge_unique_cases_preserves_cases_for_different_test_points_with_same_name():
    existing_cases = [
        {
            "case_id": "TC001",
            "test_point_id": "TP001",
            "case_name": "界面功能模块-UI显示检查",
            "expected_result": "页面展示符合设计",
        }
    ]
    new_cases = [
        {
            "case_id": "TC002",
            "test_point_id": "TP002",
            "case_name": "界面功能模块-UI显示检查",
            "expected_result": "另一个功能页面展示符合设计",
        }
    ]

    merged_cases = workflow.merge_unique_cases(existing_cases, new_cases)

    assert [case["test_point_id"] for case in merged_cases] == ["TP001", "TP002"]


def test_bind_cases_to_test_points_fills_missing_mapping_fields_by_batch_order():
    test_points = [
        {
            "id": "TP001",
            "module": "历史记录页入口",
            "feature": "历史查询记录入口",
            "scenario": "默认场景",
            "test_point": "点击跳转",
            "risk_level": "P3",
        }
    ]
    generated_cases = [
        {
            "case_id": "TC001",
            "case_name": "点击历史查询记录入口跳转",
            "priority": "",
            "preconditions": ["用户打开应用"],
            "test_steps": ["点击历史记录入口"],
            "test_data": {},
            "expected_result": "成功跳转",
            "actual_result": "",
        }
    ]

    bound_cases = workflow.bind_cases_to_test_points(generated_cases, test_points)

    assert bound_cases[0]["test_point_id"] == "TP001"
    assert bound_cases[0]["module"] == "历史记录页入口"
    assert bound_cases[0]["feature"] == "历史查询记录入口"
    assert bound_cases[0]["scenario"] == "默认场景"
    assert bound_cases[0]["priority"] == "P3"
