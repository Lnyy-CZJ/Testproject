import json
import operator
import os
import sys
import threading
from dataclasses import dataclass
from typing import Annotated, List, Optional, TypedDict

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


class BaseCaseParser(BaseModel):
    """基础用例解析模型 - 已移除expected预期结果字段"""
    name: str = Field(..., description="用例名称")
    steps: list = Field(..., description="用例步骤")
    dependencies: list = Field(default_factory=list, description="前置依赖接口顺序")
    data_ref: Optional[str] = Field(default=None, description="测试数据引用路径，例如 test_data.baseline")


class ApiBaseCaseGeneratorWorkFlow:
    parser = JsonOutputParser(pydantic_object=List[BaseCaseParser])

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

    def check_coverage(self, state):
        writer = get_safe_stream_writer()
        writer("【执行节点】：检查用例覆盖率")
        chain = base_case_check_coverage.prompt | llm
        response = chain.invoke(
            {"api_doc": state.get("api_doc"), "cases": str(state.get("cases"))}
        )
        if "100%" in response.content or "100 %" in response.content:
            return {"coverage_is_pass": True}
        return {"coverage_report": response.content, "coverage_is_pass": False}

    def check_coverage_is_pass(self, state):
        writer = get_safe_stream_writer()
        writer("【执行节点】：判断覆盖率是否通过")
        if state.get("coverage_is_pass"):
            return "输出基础测试用例"
        return "补充生成测试用例"

    def supplement_case(self, state):
        writer = get_safe_stream_writer()
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

    def output_base_case(self, state, runtime=None):
        writer = get_safe_stream_writer()
        cases = state.get("cases", [])
        writer(f"【基础用例生成完成】：共生成 {len(cases)} 条用例")
        interface_id = self._get_interface_id(state, runtime)
        persist = bool(state.get("persist_to_database", bool(interface_id)))
        if not persist:
            writer("【保存用例跳过】：数据库持久化已关闭，保留内存基础用例")
            return {"out_put_cases": cases, "database_persist_status": "skipped"}
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
