import json
import operator
import os
import sys
import threading
from dataclasses import dataclass
from typing import Annotated, Any, List, Optional, TypedDict

import pymysql
from langchain_core.output_parsers import JsonOutputParser
from langgraph.config import get_stream_writer
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from agents.api_test.prompts import (
    base_case_check_coverage,
    base_case_generator,
    supplement_case,
)
from agents.common.config.settings import llm

_sys_db_local = threading.local()


def get_system_db_connection():
    """Reuse a single pymysql connection per thread."""
    connection = getattr(_sys_db_local, "connection", None)
    if connection is None or not connection.open:
        _sys_db_local.connection = pymysql.connect(
            host=os.getenv("db_name", "localhost"),
            port=int(os.getenv("db_port", 3306)),
            user=os.getenv("db_user", "root"),
            password=os.getenv("db_password", "123456"),
            database=os.getenv("db_database", "test"),
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
            autocommit=True,
        )
    else:
        connection.ping(reconnect=True)
    return _sys_db_local.connection


def get_safe_stream_writer():
    try:
        return get_stream_writer()
    except RuntimeError:
        return lambda *_args, **_kwargs: None


@dataclass
class RuntimeContext:
    """运行时上下文参数"""
    interface_id: int


class StateNode(TypedDict):
    api_doc: str  # 接口文档
    preconditions: list  # 前置执行依赖接口的调用顺序
    cases: Annotated[List, operator.add]  # 保存生成的基础用例
    coverage_is_pass: bool  # 保存是否覆盖所有的测试点
    coverage_report: str  # 覆盖率分析报告
    project: str  # 项目名称
    module: str  # 模块名称
    env_config: dict  # 测试环境配置信息
    out_put_cases: list  # 输出的用例
    interface_id: int  # 接口ID
    persist_to_database: bool  # 是否把生成用例写入 MySQL
    database_persist_status: str  # 数据库写入结果
    generation_kernel: str  # v2_fused 时委托共享纯生成内核
    v2_contract: dict  # 已确认的 V2 契约；旧 CLI 可不传
    contract_version: int
    workflow_nodes: Annotated[List[str], operator.add]  # 实际运行节点证明，仅平台核心模式写入
    candidate_rejections: Annotated[List[dict], operator.add]  # 单条候选隔离后的脱敏拒绝摘要
    coverage_matrix: dict  # 结构化覆盖工具产物，供控制平面保存
    generation_round: int  # 补充生成轮次，核心模式严格上限为 3
    last_supplement_added: int  # 最近一轮实际接纳的候选数，用于无进展时提前结束
    base_case_model: Any  # Runner 注入的统一模型调用端口；未配置时仅生成确定性候选
    attempt_id: str  # 仅用于生成来源追踪，不用于访问 TaskStore


class BaseCaseParser(BaseModel):
    """基础用例解析模型 - 已移除expected预期结果字段"""
    name: str = Field(..., description="用例名称")
    steps: list = Field(..., description="用例步骤")
    dependencies: list = Field(default_factory=list, description="前置依赖接口顺序")
    data_ref: Optional[str] = Field(default=None, description="测试数据引用路径，例如 test_data.baseline")


class ApiBaseCaseGeneratorWorkFlow:
    parser = JsonOutputParser(pydantic_object=List[BaseCaseParser])

    @staticmethod
    def _is_core_workflow(state):
        """判断是否进入平台正式主链；legacy 与 v2_fused 保持原有兼容语义。"""

        # 是否禁止旧副作用只取决于明确的平台内核标记；生成节点再单独校验 v2_contract，
        # 避免无效输入意外退回 legacy DB 保存或无限补充路径。
        return state.get("generation_kernel") == "v2_core_workflow"

    @staticmethod
    def _get_interface_id(state, runtime=None):
        if runtime and hasattr(runtime, "context") and runtime.context:
            context = runtime.context
            if isinstance(context, dict):
                return context.get("interface_id")
            return getattr(context, "interface_id", None)
        return state.get("interface_id")

    def generator_base_case(self, state):
        writer = get_safe_stream_writer()
        writer("【执行节点】：生成基础测试用例")
        if self._is_core_workflow(state):
            return self._generate_core_cases(state, writer)
        if state.get("generation_kernel") == "v2_fused" and state.get("v2_contract"):
            # 融合模式只复用无副作用生成函数；旧 CLI 未显式选择时仍走原 Prompt。
            from agents.api_test.cases.fused_kernel import GenerationContext, generate_fused_cases
            from services.api_agent.models import ApiContract

            contract = ApiContract.model_validate(state["v2_contract"])
            cases, _provenance = generate_fused_cases(GenerationContext.from_contract(
                contract, contract_version=int(state.get("contract_version") or 1),
            ))
            return {"cases": [item.model_dump(mode="json") for item in cases]}
        for _ in range(3):
            try:
                chain = base_case_generator.prompt | llm | self.parser
                response = chain.invoke(
                    {
                        "api_doc": state.get("api_doc"),
                        "preconditions": state.get("preconditions"),
                    }
                )
            except Exception:
                writer("基础用例解析失败，正在重试")
                continue
            return {"cases": response or []}
        return {"cases": []}

    def _generate_core_cases(self, state, writer):
        """在旧生成节点内运行 V2 核心工具链，并隔离单条候选失败。

        该分支不把融合内核当作整阶段替代品：LangGraph 仍会继续经过覆盖检查、
        补充和输出节点。融合上下文、确定性覆盖与 Grounding 只作为各节点可组合的
        纯工具，所有合格候选均保持 ``confirmed_candidate`` 等待人工 Review。
        """

        from agents.api_test.cases.grounding import assess_case_grounding, contract_evidence_refs
        from services.api_agent.models import ApiContract, BaseTestCase

        contract = ApiContract.model_validate(state["v2_contract"])
        accepted = []
        rejections = []
        for index, raw_candidate in enumerate(self._generate_core_initial_candidates(contract, state)):
            try:
                candidate = (
                    raw_candidate.model_copy(deep=True)
                    if isinstance(raw_candidate, BaseTestCase)
                    else BaseTestCase.model_validate(raw_candidate)
                )
                # 候选必须绑定当前单接口上下文；跨接口或跨业务候选由 Grounding 拦截。
                candidate.contract_id = contract.contract_id
                candidate.generation_kernel = "v2_core_workflow"
                candidate.generation_sources = list(dict.fromkeys([
                    "core_workflow.generator_base_case", *candidate.generation_sources,
                ]))
                if not candidate.evidence_refs:
                    candidate.evidence_refs = contract_evidence_refs(contract)
                candidate.quality_report = assess_case_grounding(candidate, contract)
                if not candidate.quality_report.hard_gate_passed:
                    rejections.append({
                        "item_index": index,
                        "error_code": "CASE_GROUNDING_FAILED",
                        "field_path": candidate.quality_report.blockers[0].field_path if candidate.quality_report.blockers else "",
                        "message": "候选包含当前契约未支持的内容或缺少 Review 所需字段",
                    })
                    continue
                # 阶段二只产出候选，绝不在生成节点自动确认高风险或普通用例。
                candidate.status = "confirmed_candidate"
                accepted.append(candidate.model_dump(mode="json"))
            except Exception:
                # 单条坏候选不能让同一接口的其他已验证候选丢失。
                rejections.append({
                    "item_index": index,
                    "error_code": "CASE_PROMPT_ITEM_INVALID",
                    "field_path": "",
                    "message": "候选无法转换为基础用例结构",
                })
        writer(f"【核心基础用例】：接纳 {len(accepted)} 条，拒绝 {len(rejections)} 条")
        return {
            "cases": accepted,
            "candidate_rejections": rejections,
            "workflow_nodes": ["generator_base_case"],
            "generation_round": 0,
            "last_supplement_added": len(accepted),
        }

    def _generate_core_initial_candidates(self, contract, state):
        """调用融合生成工具取得初始候选，但不绕过本 Workflow 的后续节点。

        ``base_case_model`` 是 Runner 注入的受限模型调用器；未注入时只生成确定性
        覆盖骨架，保证平台在模型不可用时仍有可 Review 的基础候选。
        """

        from agents.api_test.cases.fused_kernel import GenerationContext, generate_fused_cases

        model = state.get("base_case_model")
        candidates, _provenance = generate_fused_cases(
            GenerationContext.from_contract(contract, contract_version=int(state.get("contract_version") or 1)),
            model=model if callable(model) else None,
            attempt_id=str(state.get("attempt_id") or ""),
        )
        return candidates

    def check_coverage(self, state):
        writer = get_safe_stream_writer()
        writer("【执行节点】：检查用例覆盖率")
        if self._is_core_workflow(state):
            return self._check_core_coverage(state)
        if state.get("generation_kernel") == "v2_fused":
            # 融合内核已保存结构化矩阵；兼容图在此直接结束，避免回到旧 100% 文本循环。
            return {"coverage_is_pass": True, "coverage_report": "V2.2 结构化覆盖由融合内核判定"}
        chain = base_case_check_coverage.prompt | llm
        response = chain.invoke(
            {"api_doc": state.get("api_doc"), "cases": str(state.get("cases"))}
        )
        if "100%" in response.content or "100 %" in response.content:
            return {"coverage_is_pass": True}
        return {"coverage_report": response.content, "coverage_is_pass": False}

    def _check_core_coverage(self, state):
        """使用结构化覆盖工具检查必选维度，而不是让模型决定是否无限循环。"""

        from agents.api_test.cases.coverage import build_coverage
        from services.api_agent.models import ApiContract

        contract = ApiContract.model_validate(state["v2_contract"])
        _skeleton_cases, matrix = build_coverage(
            [contract], contract_version=int(state.get("contract_version") or 1),
        )
        generated_dimensions = {
            str(case.get("dimension", ""))
            for case in state.get("cases", [])
            if isinstance(case, dict)
        }
        missing = [
            item.dimension for item in matrix.items
            if item.required and item.dimension not in generated_dimensions
        ]
        return {
            "coverage_is_pass": not missing,
            "coverage_report": "必选覆盖已满足" if not missing else f"缺少必选覆盖维度：{', '.join(missing)}",
            "coverage_matrix": matrix.model_dump(mode="json"),
            "workflow_nodes": ["check_coverage"],
        }

    def check_coverage_is_pass(self, state):
        writer = get_safe_stream_writer()
        writer("【执行节点】：判断覆盖率是否通过")
        if self._is_core_workflow(state):
            # 无新增候选时提前结束；即使模型持续返回无效结果也绝不超过三轮。
            if state.get("coverage_is_pass") or int(state.get("generation_round") or 0) >= 3:
                return "输出基础测试用例"
            if (
                int(state.get("generation_round") or 0) > 0
                and "last_supplement_added" in state
                and int(state.get("last_supplement_added") or 0) == 0
            ):
                return "输出基础测试用例"
            return "补充生成测试用例"
        if state.get("coverage_is_pass"):
            return "输出基础测试用例"
        return "补充生成测试用例"

    def supplement_case(self, state):
        writer = get_safe_stream_writer()
        if self._is_core_workflow(state):
            return self._supplement_core_cases(state, writer)
        for retry_index in range(3):
            writer(f"【执行节点】：补充生成测试用例，第 {retry_index + 1} 次尝试")
            try:
                chain = supplement_case.prompt | llm | self.parser
                response = chain.invoke(
                    {
                        "api_doc": state.get("api_doc"),
                        "cases": str(state.get("cases")),
                        "coverage_report": state.get("coverage_report"),
                        "preconditions": state.get("preconditions"),
                    }
                )
            except Exception:
                writer("补充用例解析失败，正在重试")
                continue
            return {"cases": response or []}
        return {"cases": []}

    def _supplement_core_cases(self, state, writer):
        """执行一轮受限补充，并复用与初始候选相同的 Grounding 隔离规则。"""

        from agents.api_test.cases.grounding import assess_case_grounding, contract_evidence_refs
        from services.api_agent.models import ApiContract, BaseTestCase

        round_number = int(state.get("generation_round") or 0) + 1
        contract = ApiContract.model_validate(state["v2_contract"])
        existing = {
            str(case.get("case_id", ""))
            for case in state.get("cases", [])
            if isinstance(case, dict)
        }
        accepted = []
        rejections = []
        for index, raw_candidate in enumerate(self._generate_core_supplement_candidates(contract, state, round_number)):
            try:
                candidate = (
                    raw_candidate.model_copy(deep=True)
                    if isinstance(raw_candidate, BaseTestCase)
                    else BaseTestCase.model_validate(raw_candidate)
                )
                candidate.contract_id = contract.contract_id
                candidate.generation_kernel = "v2_core_workflow"
                candidate.generation_sources = list(dict.fromkeys([
                    "core_workflow.supplement_case", *candidate.generation_sources,
                ]))
                if not candidate.evidence_refs:
                    candidate.evidence_refs = contract_evidence_refs(contract)
                candidate.quality_report = assess_case_grounding(candidate, contract)
                if candidate.case_id in existing or not candidate.quality_report.hard_gate_passed:
                    rejections.append({
                        "item_index": index,
                        "error_code": "CASE_GROUNDING_FAILED" if not candidate.quality_report.hard_gate_passed else "CASE_PROMPT_ITEM_INVALID",
                        "field_path": candidate.quality_report.blockers[0].field_path if candidate.quality_report.blockers else "case_id",
                        "message": "补充候选无效、跨域或与已有候选重复",
                    })
                    continue
                candidate.status = "confirmed_candidate"
                accepted.append(candidate.model_dump(mode="json"))
                existing.add(candidate.case_id)
            except Exception:
                rejections.append({
                    "item_index": index,
                    "error_code": "CASE_PROMPT_ITEM_INVALID",
                    "field_path": "",
                    "message": "补充候选无法转换为基础用例结构",
                })
        writer(f"【核心补充用例】：第 {round_number} 轮接纳 {len(accepted)} 条")
        return {
            "cases": accepted,
            "candidate_rejections": rejections,
            "workflow_nodes": ["supplement_case"],
            "generation_round": round_number,
            "last_supplement_added": len(accepted),
        }

    def _generate_core_supplement_candidates(self, _contract, _state, _round_number):
        """默认不臆造契约外补充场景；Runner 注入受限候选后才会进行下一轮。"""

        return []

    def output_base_case(self, state, runtime=None):
        writer = get_safe_stream_writer()
        cases = state.get("cases", [])
        writer(f"【基础用例生成完成】：共生成 {len(cases)} 条用例")
        interface_id = self._get_interface_id(state, runtime)
        # 平台融合路径和旧 CLI 默认都不写 MySQL；仅显式传 true 时保留旧能力。
        # 平台核心模式的唯一权威产物是控制平面版本文件，旧 MySQL 保存只保留给显式 legacy CLI。
        persist = bool(state.get("persist_to_database", False)) and not self._is_core_workflow(state)
        if not persist:
            writer("【保存用例跳过】：数据库持久化已关闭，保留内存基础用例")
            result = {"out_put_cases": cases, "database_persist_status": "skipped"}
            if self._is_core_workflow(state):
                result["workflow_nodes"] = ["output_base_case"]
            return result
        if not interface_id:
            writer("【保存用例失败】：启用数据库持久化时缺少 interface_id")
            return {"out_put_cases": cases, "database_persist_status": "failed"}
        saved_cases = self._save_base_cases_to_db(cases, interface_id)
        if saved_cases:
            return {"out_put_cases": saved_cases, "database_persist_status": "succeeded"}
        # 数据库失败不能清空已经成功生成的文件权威用例。
        return {"out_put_cases": cases, "database_persist_status": "failed"}

    def _save_base_cases_to_db(self, cases, interface_id):
        writer = get_safe_stream_writer()
        writer("【保存用例】：开始保存基础用例到数据库")
        if not interface_id:
            return []

        cursor = None
        try:
            connection = get_system_db_connection()
            cursor = connection.cursor()
            cursor.execute("DELETE FROM api_base_case WHERE interface_id = %s", (str(interface_id),))

            insert_sql = """
                INSERT INTO api_base_case (interface_id, name, steps, expected, status)
                VALUES (%s, %s, %s, %s, %s)
            """
            for index, case in enumerate(cases, start=1):
                case_name = case.get("name", f"基础用例_{index}")
                case_steps = case.get("steps", [])
                cursor.execute(
                    insert_sql,
                    (
                        str(interface_id),
                        case_name,
                        json.dumps(case_steps, ensure_ascii=False)
                        if isinstance(case_steps, (list, dict))
                        else json.dumps([case_steps], ensure_ascii=False),
                        "[]",  # expected字段已移除，保存空数组
                        "ready",
                    ),
                )
                writer(f"【用例保存】：{case_name}")

            cursor.execute("SELECT * FROM api_base_case WHERE interface_id = %s", (str(interface_id),))
            return cursor.fetchall()
        except Exception as exc:
            writer(f"【保存失败】：保存基础用例失败: {exc}")
            return []
        finally:
            if cursor:
                cursor.close()

    def create_workflow(self):
        graph = StateGraph(StateNode)
        graph.add_node("生成基础测试用例", self.generator_base_case)
        graph.add_node("检查用例覆盖率", self.check_coverage)
        graph.add_node("补充生成测试用例", self.supplement_case)
        graph.add_node("输出基础测试用例", self.output_base_case)

        graph.add_edge(START, "生成基础测试用例")
        graph.add_edge("生成基础测试用例", "检查用例覆盖率")
        graph.add_conditional_edges(
            "检查用例覆盖率",
            self.check_coverage_is_pass,
            ["输出基础测试用例", "补充生成测试用例"],
        )
        graph.add_edge("补充生成测试用例", "检查用例覆盖率")
        graph.add_edge("输出基础测试用例", END)
        return graph.compile()

if __name__ == '__main__':
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    api_info = """
     {
            case_common:
  login_URL: "http://shop-xo.hctestedu.com/index.php?s=/api/user/login"
  headers:
    "application": "web"
    "application_client_type": "PC"

login:
    description: 登录成功
    method: POST
    url: login_URL
    headers:
      "application": "web"
      "application_client_type": "PC"
      "Content-Type": "application/json"
    requestbody:
      type: username
      accounts: czj11
      pwd: czj111
    assertion:
      status_code: 1
      prompt_msg: 登录成功
  }



    """
    preconditions = []
    interface_id = 999991
    # 创建工作流
    workflow = ApiBaseCaseGeneratorWorkFlow().create_workflow()
    response = workflow.stream({"api_doc": api_info,
                                "preconditions": preconditions,
                                "interface_id": interface_id},
                               stream_mode=["messages", "custom"]
                               )
    for chunk in response:
        if chunk[0] == "messages":
            print(chunk[1][0].content, end='')
        elif chunk[0] == "custom":
            print(chunk[1])
