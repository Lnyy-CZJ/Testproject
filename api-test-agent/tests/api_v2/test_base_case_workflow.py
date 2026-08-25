"""阶段二核心基础用例 Workflow 的无副作用与候选隔离测试。"""

from __future__ import annotations

from agents.api_test.workflows.api_basecase_workflow import ApiBaseCaseGeneratorWorkFlow
from services.api_agent.models import ApiContract, BaseTestCase, FieldEvidence, ResponseDefinition, SourceTrace


def login_contract() -> ApiContract:
    """构造仅描述登录能力的契约，作为跨业务幻觉的黄金输入。"""

    return ApiContract(
        contract_id="contract_login_core",
        name="用户登录",
        summary="使用账号密码登录并创建会话",
        method="POST",
        path="/api/login",
        responses=[ResponseDefinition(status_code="200", description="登录成功")],
        source_trace=SourceTrace(source_id="doc", section_id="login", quote="POST /api/login 用户登录"),
        field_evidence=[
            FieldEvidence(
                field_path="path", value="/api/login", source_type="source_quote",
                source_pointer="login", quote="POST /api/login 用户登录",
            ),
        ],
        status="confirmed",
    )


def _candidate(case_id: str, *, objective: str = "验证用户能够登录") -> BaseTestCase:
    """构造一个最小候选；生产 Workflow 应补齐来源、Evidence 和候选状态。"""

    return BaseTestCase(
        case_id=case_id,
        contract_id="contract_login_core",
        name="登录正常请求",
        objective=objective,
        dimension="positive",
        steps=[{"order": 1, "action": "提交账号密码", "method": "POST", "path": "/api/login"}],
        expected_results=["登录成功"],
        source="deterministic",
    )


class ControlledCoreWorkflow(ApiBaseCaseGeneratorWorkFlow):
    """用受控候选替代模型调用，保留被测 Workflow 节点与工具链为真实实现。"""

    def _generate_core_initial_candidates(self, _contract, _state):
        return [
            _candidate("case_login_good"),
            _candidate("case_login_foreign", objective="创建商品订单并完成支付"),
        ]


def test_v2_core_generator_records_real_node_and_rejects_foreign_login_candidate():
    """防止平台只标注 core 名称却绕过旧节点，或让登录候选跨到订单业务域。"""

    workflow = ControlledCoreWorkflow()
    result = workflow.generator_base_case({
        "generation_kernel": "v2_core_workflow",
        "v2_contract": login_contract().model_dump(mode="json"),
        "contract_version": 1,
    })

    assert result["workflow_nodes"] == ["generator_base_case"]
    assert [item["case_id"] for item in result["cases"]] == ["case_login_good"]
    assert result["cases"][0]["generation_kernel"] == "v2_core_workflow"
    assert result["cases"][0]["status"] == "confirmed_candidate"
    assert result["candidate_rejections"][0]["error_code"] == "CASE_GROUNDING_FAILED"


def test_core_coverage_router_never_requests_a_fourth_supplement_round():
    """防止覆盖率未满足时旧图无限回环并持续调用模型。"""

    workflow = ApiBaseCaseGeneratorWorkFlow()

    assert workflow.check_coverage_is_pass({"generation_kernel": "v2_core_workflow", "coverage_is_pass": False, "generation_round": 0}) == "补充生成测试用例"
    assert workflow.check_coverage_is_pass({"generation_kernel": "v2_core_workflow", "coverage_is_pass": False, "generation_round": 2}) == "补充生成测试用例"
    assert workflow.check_coverage_is_pass({"generation_kernel": "v2_core_workflow", "coverage_is_pass": False, "generation_round": 3}) == "输出基础测试用例"


def test_core_output_never_calls_legacy_database_save_even_if_old_flag_is_true(monkeypatch):
    """防止平台模式错误沿用旧 CLI 的 MySQL 保存节点。"""

    workflow = ApiBaseCaseGeneratorWorkFlow()

    def database_must_not_be_called(*_args, **_kwargs):
        raise AssertionError("平台 core Workflow 不得写入 MySQL")

    monkeypatch.setattr(workflow, "_save_base_cases_to_db", database_must_not_be_called)
    result = workflow.output_base_case({
        "generation_kernel": "v2_core_workflow",
        "persist_to_database": True,
        "interface_id": 123,
        "cases": [{"case_id": "case_login_good"}],
    })

    assert result["database_persist_status"] == "skipped"
    assert result["out_put_cases"] == [{"case_id": "case_login_good"}]


def test_core_graph_runs_legacy_nodes_and_marks_all_accepted_candidates_for_review():
    """防止核心路径退化成单一帮助函数，跳过覆盖检查与输出节点。"""

    workflow = ControlledCoreWorkflow().create_workflow()
    result = workflow.invoke({
        "generation_kernel": "v2_core_workflow",
        "v2_contract": login_contract().model_dump(mode="json"),
        "contract_version": 1,
        "persist_to_database": True,
        "preconditions": [],
        "api_doc": "POST /api/login 用户登录",
    })

    assert result["workflow_nodes"] == [
        "generator_base_case", "check_coverage", "supplement_case",
        "check_coverage", "output_base_case",
    ]
    assert result["database_persist_status"] == "skipped"
    assert result["out_put_cases"]
    assert {item["status"] for item in result["out_put_cases"]} == {"confirmed_candidate"}
