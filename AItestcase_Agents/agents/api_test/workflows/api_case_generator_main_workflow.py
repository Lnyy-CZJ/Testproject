"""
接口用例生成的主流程：
    包含将接口文档-->基础用例
    遍历基础用例---并发去生成可以执行的用例
"""
import os
import sys
import json
import operator
from typing import TypedDict, Annotated, List

from langgraph.constants import START, END
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph
from langgraph.types import Send

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from agents.api_test.workflows.api_basecase_workflow import ApiBaseCaseGeneratorWorkFlow, StateNode
from agents.api_test.workflows.api_run_case_wrokflow import ApiRunCaseGeneratorWorkFlow, ApiState
from concurrent.futures.thread import ThreadPoolExecutor


class MainState(TypedDict):
    api_info: str  # 接口文档信息
    preconditions: list  # 相关依赖接口文档
    base_cases: list  # 生成的基础用例(所有的基础用例)
    db_config: list  # 数据库配置
    additional_info: dict  # 额外补充信息
    test_data: dict  # 测试数据
    base_case: dict  # 基础用例
    api_case_list: Annotated[List, operator.add]
    interface_id: int  # 接口id
    persist_to_database: bool  # 是否写入数据库
    database_persist_statuses: Annotated[List, operator.add]

## 并发去生成可以执行的接口测试用例
class ApiCaseGeneratoMainWorkFlow:
    """接口用例生成的主流程"""

    @staticmethod
    def generator_base_case(state: MainState):
        """生成基础用例"""
        writer = get_stream_writer()
        writer("【工作流调用】：调用生成基础用例的工作流")
        api_info = state.get("api_info")
        preconditions = state.get("preconditions")
        # 调用子流程，去生成基础用例
        workflow = ApiBaseCaseGeneratorWorkFlow().create_workflow()
        basecase_state: StateNode = workflow.invoke({"api_doc": api_info, 
                                                    "preconditions": str(preconditions),
                                                    "interface_id": state.get("interface_id"),
                                                    "persist_to_database": state.get("persist_to_database", bool(state.get("interface_id"))),
                                                    }
                                                    )
        # 数据库中查询该接口所有的基础用例
        return {
            "base_cases": basecase_state.get("out_put_cases") or [],
            "database_persist_statuses": [basecase_state.get("database_persist_status", "unknown")],
        }

    @staticmethod
    def generate_run_api_case(state: MainState):
        """生成可以运行的接口用例"""
        writer = get_stream_writer()
        writer("【工作流调用】：调用生成可执行用例的工作流")
        workflow = ApiRunCaseGeneratorWorkFlow().create_workflow()
        api_case_state: ApiState = workflow.invoke({"base_case": state.get("base_case"),
                                                    "db_config": state.get("db_config", []),
                                                    "additional_info": state.get("additional_info"),
                                                    "test_data": state.get("test_data"),
                                                    "preconditions_api_doc": state.get("preconditions_api_doc", state.get("preconditions")),
                                                    "api_info": state.get("api_info"),
                                                    "interface_id": state.get("interface_id"),
                                                    "base_case_id": state.get("base_case", {}).get("id"),
                                                    "persist_to_database": state.get("persist_to_database", bool(state.get("interface_id"))),
                                                    })
        api_case = api_case_state.get("api_case")
        # 将数据库保存后生成的 case_id 注入到用例数据中，供执行阶段回写 real_response 使用
        saved_case_id = api_case_state.get("case_id")
        if saved_case_id and isinstance(api_case, dict):
            api_case["id"] = saved_case_id
        return {
            "api_case_list": [api_case] if api_case else [],
            "database_persist_statuses": [api_case_state.get("database_persist_status", "unknown")],
        }

    @staticmethod
    def api_case_generation_task_split(state: MainState):
        """并发去生成可以执行的接口测试用例"""
        writer = get_stream_writer()
        writer("【任务并发】：开始并发生可执行用例")
        task_list = []
        for base_case in state.get("base_cases"):
            task_list.append(
                Send("生成可执行用例", {
                    "api_info": state.get("api_info"),
                    "base_case": base_case,
                    "db_config": state.get("db_config", []),
                    "additional_info": state.get("additional_info"),
                    "test_data": state.get("test_data"),
                    "preconditions": state.get("preconditions"),
                    "preconditions_api_doc": state.get("preconditions"),
                    "interface_id": state.get("interface_id")
                    ,"persist_to_database": state.get("persist_to_database", bool(state.get("interface_id")))
                })
            )
        return task_list

    @staticmethod
    def output_save_all_case(state: MainState):
        """保存生成的所有用例"""
        writer = get_stream_writer()
        writer("【生成完成】：已保存基础用例与可执行用例")

    def create_workflow(self):
        """创建工作流"""
        graph = StateGraph(MainState)
        # 生成基础用例
        graph.add_node("生成基础用例", self.generator_base_case)
        graph.add_node("生成可执行用例", self.generate_run_api_case)
        # 对执行节点进行编排
        graph.add_edge(START, "生成基础用例")
        graph.add_conditional_edges("生成基础用例", self.api_case_generation_task_split, ['生成可执行用例'])
        graph.add_edge("生成可执行用例", END)
        return graph.compile()


if __name__ == '__main__':
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    api_case_info = {
        "name": "正常请求-登录成功",
        "description": "用户登录",
        "request": {
            "method": "POST",
            "url": "/api/user/login",
            "base_url": "${{base_url}}",
            "headers": {
                "Content-Type": "application/json",
                "application": "web",
                "application_client_type": "PC"
            },
            "body": {
                "type": "username",
                "accounts": "${{accounts}}",
                "pwd": "czj111"
            },
            "files": {},
            "setup_script": "",
            "treadown_script": ""
        }}
    preconditions = []
    db_config = [
        {
            # 数据库的类型
            "type": "mysql",
            # 连接名称(自定义的)
            "name": "localhost",
            "config": {
                "host": "localhost",
                "port": 3306,
                "user": "root",
                "password": "123456",
                "database": "test001",
            }
        }
    ]
    additional_info = {
        "项目名称": "czj项目",
        "模块名称": "登录模块",
        "备注": "对于登录模块的测试用例，请使用工具随机生成密码"
    }
    test_data = {
        "base_url": "http://shop-xo.hctestedu.com/index.php?s=",
        "accounts": "czj11",
    }
    interface_id = 999993

    workflow = ApiCaseGeneratoMainWorkFlow().create_workflow()
    response = workflow.stream({"api_info": api_case_info,
                                "preconditions": preconditions,
                                "db_config": db_config,
                                "additional_info": additional_info,
                                "test_data": test_data,
                                "interface_id": interface_id,
                                },
                               subgraphs=True,
                               stream_mode=["messages", "custom"]
                               )
    for item in response:
        if item[1] == "messages":
            print(item[2][0].content, end="")
        elif item[1] == "custom":
            print(item[2])
