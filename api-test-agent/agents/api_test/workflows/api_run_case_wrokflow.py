import inspect
import json
import operator
import os
import sys
import threading
from datetime import datetime
from typing import Annotated, List, Optional, TypedDict
from urllib.parse import urlsplit

import pymysql
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langgraph.config import get_stream_writer
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agents.api_test.prompts import api_case_generator
from agents.common.config.settings import llm
from agents.common.tools import global_tools

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 【重要修复】：引入线程隔离的数据库连接管理器，避免多线程环境下数据库连接冲突
_sys_db_local = threading.local()


def get_system_db_connection():
    """获取系统数据库的线程级单例连接，避免高并发导致连接耗尽或线程冲突"""
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


def get_module_functions(module):
    return [
        name
        for name, obj in inspect.getmembers(module)
        if inspect.isfunction(obj) and not name.startswith("_")
    ]


def inspect_test_files():
    datas_dir = os.path.join(BASE_DIR, "datas")
    file_list = []
    for root, _, files in os.walk(datas_dir):
        for file_name in files:
            file_list.append(os.path.join(root, file_name))
    return file_list


class APICaseRuntimeParser(BaseModel):
    """解析生成的接口用例 - 已移除assertions断言字段"""
    name: str = Field(..., description="用例名称")
    description: str = Field(..., description="用例描述")
    interface: str = Field(..., description="接口名称或接口路径")
    preconditions: list = Field(default_factory=list, description="前置依赖接口信息")
    request: dict = Field(..., description="用例请求数据")
    data_ref: Optional[str] = Field(default=None, description="测试数据引用路径，例如 test_data.boundary.pwd_min_minus")


class ApiState(TypedDict):
    """定义工作流的数据"""
    api_doc: str  # 主接口的文档
    base_case: str  # 基础用例
    preconditions_api_doc: list  # 前置依赖接口的文档
    test_data: dict  # 测试数据
    db_config: list  # 数据库的配置信息
    additional_info: str  # 额外的补充信息
    test_files_list: list  # 文件上传相关接口可以用文件列表
    function_list: list  # 前后置脚本中可以引用的工具函数列表
    api_case: dict  # 生成的接口用例
    # 标记用例的状态(可用性)
    status: str
    # 记录重新生成的次数
    generator_count: int
    base_case_id: int
    interface_id: int
    saved: bool  # 是否已保存到数据库
    message: str  # 生成用例的提示信息
    case_id: int  # 用例的ID标识
    persist_to_database: bool  # 是否把可执行用例写入 MySQL
    database_persist_status: str  # 数据库写入结果
    cases: Annotated[List, operator.add]  # 用例列表，用于存储所有生成的用例
    # 数据驱动相关字段
    data_file_path: str  # 数据文件路径
    loaded_test_data: dict  # 已加载的测试数据
    data_lineage: dict  # 测试数据继承与覆盖来源


class ApiRunCaseGeneratorWorkFlow:
    """可运行的接口用例生成的工作流 - 已移除断言相关逻辑，支持数据驱动"""

    @staticmethod
    def _safe_json_loads(value):
        """
        Parse JSON text when workflow state stores API info as a string.

        Args:
            value: API info in dict or JSON string form.

        Returns:
            dict/list/str: Parsed JSON when possible; otherwise the original value.
        """
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @staticmethod
    def _normalize_relative_url(raw_url, base_url=None, fallback_url=None):
        """
        Convert generated URL variants into a relative executable path.

        Args:
            raw_url: URL from generated request, e.g. /index.php?s=/api/user/login.
            base_url: Environment/document base URL used to remove duplication.
            fallback_url: API document path used when raw_url is empty or invalid.

        Returns:
            str: Relative path, always prefixed with / when non-empty.
        """
        candidates = [raw_url, fallback_url]
        for candidate in candidates:
            if candidate is None:
                continue
            path = str(candidate).strip()
            if not path:
                continue

            for prefix in ("${{base_url}}", "{{base_url}}", "${base_url}", "{base_url}"):
                if path.startswith(prefix):
                    path = path[len(prefix):].strip()

            if base_url:
                base_url_text = str(base_url).strip()
                if base_url_text and path.startswith(base_url_text):
                    path = path[len(base_url_text):].strip()

            parts = urlsplit(path)
            if parts.scheme in {"http", "https"}:
                if base_url and path.startswith(str(base_url).strip()):
                    path = path[len(str(base_url).strip()):].strip()
                elif parts.query.startswith("s="):
                    path = parts.query[2:]
                else:
                    path = parts.path or ""
                    if parts.query:
                        path = f"{path}?{parts.query}"

            for marker in ("/index.php?s=", "index.php?s="):
                if path.startswith(marker):
                    path = path[len(marker):]

            if path.startswith("?s="):
                path = path[3:]

            if path:
                return path if path.startswith("/") else f"/{path}"
        return ""

    @classmethod
    def _normalize_request_endpoint(cls, request, api_info, test_data):
        """
        Normalize request endpoint fields before a generated case is saved.

        Args:
            request: The request dictionary generated by the LLM.
            api_info: Parsed API document data.
            test_data: Runtime environment data containing base_url.

        Returns:
            dict: The same request dictionary with unified base_url/url fields.
        """
        if not isinstance(request, dict):
            return request

        api_info = api_info if isinstance(api_info, dict) else {}
        test_data = test_data if isinstance(test_data, dict) else {}
        base_url_value = (
            api_info.get("base_url")
            or api_info.get("baseURL")
            or api_info.get("baseUrl")
            or test_data.get("base_url")
        )
        fallback_url = api_info.get("path") or api_info.get("raw_url") or api_info.get("url")

        request["base_url"] = "${{base_url}}"
        request["url"] = cls._normalize_relative_url(
            request.get("url"),
            base_url=base_url_value,
            fallback_url=fallback_url,
        )
        return request

    @classmethod
    def _normalize_case_endpoints(cls, api_case, state):
        """
        Apply deterministic URL normalization to main and precondition requests.

        Args:
            api_case: Generated executable case.
            state: Workflow state with api_info and test_data.

        Returns:
            dict: Normalized executable case.
        """
        if not isinstance(api_case, dict):
            return api_case

        api_info = cls._safe_json_loads(state.get("api_info"))
        if isinstance(api_info, list):
            api_info = api_info[0] if api_info else {}
        test_data = state.get("test_data")

        cls._normalize_request_endpoint(api_case.get("request"), api_info, test_data)
        for precondition in api_case.get("preconditions") or []:
            if isinstance(precondition, dict):
                cls._normalize_request_endpoint(precondition.get("request"), api_info, test_data)
        return api_case

    @staticmethod
    def get_functions_and_files(state: ApiState):
        """加载用例生成需要用到的脚本工具函数和可用测试文件的列表"""
        return {
            "test_files_list": inspect_test_files(),
            "function_list": get_module_functions(global_tools),
        }

    @staticmethod
    def load_test_data(state: ApiState):
        """
        【新增节点】加载测试数据文件

        根据用例中包含的data_ref字段，从对应的数据文件中加载测试数据
        """
        writer = get_safe_stream_writer()
        writer("【数据加载】：开始加载测试数据文件")

        # 尝试导入数据管理器
        try:
            from agents.common.utils.test_data_hub import get_test_data_hub
            data_hub = get_test_data_hub()
        except ImportError:
            writer("【数据加载】：未安装数据驱动模块，跳过数据加载")
            return {"loaded_test_data": {}}

        # 获取用例中的data_ref信息
        base_case = state.get("base_case", {})
        api_case = state.get("api_case", {})
        data_ref = None

        # 如果 api_case 是列表，取第一个元素或空字典
        if isinstance(api_case, list):
            api_case = api_case[0] if api_case else {}
        
        if isinstance(api_case, dict):
            data_ref = api_case.get("data_ref") or api_case.get("dataRef")

        # 支持从base_case字符串中提取data_ref
        if not data_ref and isinstance(base_case, str):
            import re
            match = re.search(r'data_ref["\s:]+([^"\'\s,}]+)', base_case)
            if match:
                data_ref = match.group(1).strip()
        elif not data_ref and isinstance(base_case, dict):
            data_ref = base_case.get("data_ref")

        # 获取API名称作为命名空间
        api_info = state.get("api_info", {})
        api_name = None
        if isinstance(api_info, dict):
            api_name = api_info.get("name") or api_info.get("path", "").replace("/", "_").strip("_")
        elif isinstance(api_info, str):
            import re
            match = re.search(r'["\']?(?:name|path)["\']?\s*[:\s]+["\']([^"\']+)["\']', api_info)
            if match:
                api_name = match.group(1).replace("/", "_")

        if data_ref and api_name:
            # 构建数据文件路径
            data_file = f"{api_name}_data.yaml"
            data_dir = os.path.join(BASE_DIR, "datas", "TestData")

            # 尝试加载数据文件
            loaded = data_hub.load_data_file(data_file, namespace=api_name)
            if not loaded:
                project_data_dir = os.path.join(os.path.dirname(BASE_DIR), "datas", "TestData")
                for root, _, files in os.walk(project_data_dir):
                    for file_name in files:
                        if file_name.endswith((".yaml", ".yml", ".json")):
                            data_hub.load_data_file(os.path.join(root, file_name))

            if loaded or data_hub.list_namespaces():
                # 解析数据引用
                data_result = data_hub.resolve_case_data_with_lineage(data_ref, namespace=api_name)
                if not data_result.get("resolved_data"):
                    data_result = data_hub.resolve_case_data_with_lineage(data_ref)
                test_data = data_result.get("resolved_data", {})
                data_lineage = data_result.get("lineage", {})
                if isinstance(api_case, dict):
                    api_case["_test_data"] = test_data
                    api_case["_data_lineage"] = data_lineage
                    api_case["data_ref"] = data_ref
                writer(f"【数据加载】：已加载数据引用 {data_ref}, 包含 {len(test_data)} 个字段")
                return {
                    "loaded_test_data": test_data,
                    "data_lineage": data_lineage,
                    "api_case": api_case,
                    "data_file_path": os.path.join(data_dir, data_file)
                }

        writer("【数据加载】：无数据引用或数据文件，跳过")
        return {"loaded_test_data": {}, "data_file_path": ""}

    @staticmethod
    def generator_api_case(state: ApiState):
        """生成可执行的接口用例"""
        for _ in range(3):
            try:
                parser = JsonOutputParser(pydantic_object=APICaseRuntimeParser)
                chain = api_case_generator.prompt | llm | parser
                response = chain.invoke(
                    {
                        "api_case_output_format": json.dumps(api_case_generator.api_case_output_format, ensure_ascii=False, indent=2),
                        "case_info": state.get("base_case"),
                        "case_api": state.get("api_info"),
                        "other_api": state.get("preconditions_api_doc"),
                        "test_data": state.get("test_data"),
                        "files_list": state.get("test_files_list"),
                        "function_list": state.get("function_list"),
                        "additional_info": state.get("additional_info"),
                    }
                )
            except OutputParserException as exc:
                writer = get_safe_stream_writer()
                writer(f"【接口用例生成失败】：JSON 解析错误: {exc}")
                continue
            else:
                if response:
                    response = ApiRunCaseGeneratorWorkFlow._normalize_case_endpoints(response, state)
                    return {
                        "api_case": response,
                        "generator_count": state.get("generator_count", 0) + 1,
                    }

        writer = get_safe_stream_writer()
        writer("【接口用例生成失败】：多次尝试后仍未生成可执行用例")
        return {"api_case": {}, "generator_count": state.get("generator_count", 0) + 1}

    @staticmethod
    def _iter_scripts(case_info):
        for index, precondition in enumerate(case_info.get("preconditions", []) or [], start=1):
            request = precondition.get("request", {}) if isinstance(precondition, dict) else {}
            yield f"前置依赖[{index}]", request.get("setup_script", ""), "setup_script"
            yield f"前置依赖[{index}]", request.get("teardown_script", ""), "teardown_script"

        request = case_info.get("request", {}) or {}
        yield "主请求", request.get("setup_script", ""), "setup_script"
        yield "主请求", request.get("teardown_script", ""), "teardown_script"

    @staticmethod
    def static_syntax_check(state: ApiState):
        writer = get_safe_stream_writer()
        writer("【静态语法校验】：开始校验用例脚本语法")

        case_info = state.get("api_case", {}) or {}
        # 如果 api_case 是列表，取第一个元素
        if isinstance(case_info, list):
            case_info = case_info[0] if case_info else {}
        if not case_info or not isinstance(case_info, dict):
            message = "未生成有效用例，无法执行静态语法校验"
            writer(f"【静态语法校验失败】：{message}")
            return {"status": "disabled", "message": message}

        for scope, script_content, script_name in ApiRunCaseGeneratorWorkFlow._iter_scripts(case_info):
            if not script_content:
                continue
            if not isinstance(script_content, str):
                message = f"{scope} 的 {script_name} 不是字符串，无法通过语法校验"
                writer(f"【静态语法校验失败】：{message}")
                return {"status": "disabled", "message": message}
            try:
                compile(script_content, "<string>", "exec")
            except SyntaxError as exc:
                message = (
                    f"{scope} 的 {script_name} 存在语法错误: {exc.msg} "
                    f"(line {exc.lineno}, offset {exc.offset})"
                )
                writer(f"【静态语法校验失败】：{message}")
                return {"status": "disabled", "message": message}

        writer("【静态语法校验通过】：用例可保存为 ready")
        return {"status": "ready", "message": "静态语法校验通过"}

    @staticmethod
    def check_case_is_pass(state: ApiState):
        if state.get("status") == "ready":
            return "保存用例"
        if state.get("generator_count", 0) <= 3:
            return "生成接口用例"
        return "保存用例"

    @staticmethod
    def sava_api_case(state: ApiState):
        cases = state.get("api_case", {})
        status = state.get("status", "disabled")
        base_case_id = state.get("base_case_id")
        writer = get_safe_stream_writer()

        if not cases:
            writer("【保存用例跳过】：没有可保存的用例数据")
            return {"saved": False, "message": "没有用例数据"}

        if not state.get("persist_to_database", bool(state.get("interface_id"))):
            writer("【保存用例跳过】：数据库持久化已关闭，保留内存可执行用例")
            return {
                "saved": False,
                "skipped": True,
                "database_persist_status": "skipped",
                "message": "数据库持久化已关闭",
            }

        result = ApiRunCaseGeneratorWorkFlow._save_api_case_to_db(cases, status, base_case_id)
        result["database_persist_status"] = "succeeded" if result.get("saved") else "failed"
        writer(f"【保存用例结果】：{result}")
        return result

    @staticmethod
    def _save_api_case_to_db(case_data, status, base_case_id=None):
        """将接口用例数据保存到数据库 - 已移除assertions字段"""
        writer = get_safe_stream_writer()
        if not case_data:
            return {"saved": False, "message": "用例数据为空"}

        cursor = None
        try:
            connection = get_system_db_connection()
            cursor = connection.cursor()

            case_name = case_data.get(
                "name", f"接口测试用例_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            case_description = case_data.get("description", "")
            case_interface = case_data.get("interface", "")
            case_preconditions = case_data.get("preconditions", [])
            case_request = case_data.get("request", {})

            cursor.execute(
                """
                INSERT INTO api_test_case (
                    base_case_id, name, description, interface_name,
                    preconditions, request, assertions, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    base_case_id,
                    case_name,
                    case_description,
                    case_interface,
                    json.dumps(case_preconditions, ensure_ascii=False) if case_preconditions else "[]",
                    json.dumps(case_request, ensure_ascii=False) if case_request else "{}",
                    "{}",  # assertions字段已移除，保存空对象
                    status,
                ),
            )

            case_id = cursor.lastrowid
            writer(f"【保存成功】：接口测试用例已保存，ID={case_id}")
            return {
                "saved": True,
                "case_id": case_id,
                "message": f"成功保存用例: {case_name}",
                "case_data": {"id": case_id, "name": case_name, "status": status},
            }
        except Exception as exc:
            error_message = f"保存接口测试用例失败: {exc}"
            writer(error_message)
            return {"saved": False, "message": error_message}
        finally:
            if cursor:
                cursor.close()

    def create_workflow(self):
        graph = StateGraph(ApiState)
        graph.add_node("加载工具函数和文件列表", self.get_functions_and_files)
        graph.add_node("生成接口用例", self.generator_api_case)
        graph.add_node("加载测试数据", self.load_test_data)  # 新增数据加载节点
        graph.add_node("静态语法校验", self.static_syntax_check)
        graph.add_node("保存用例", self.sava_api_case)

        graph.add_edge(START, "加载工具函数和文件列表")
        graph.add_edge("加载工具函数和文件列表", "生成接口用例")
        graph.add_edge("生成接口用例", "加载测试数据")  # 新增边
        graph.add_edge("加载测试数据", "静态语法校验")
        graph.add_conditional_edges(
            "静态语法校验",
            self.check_case_is_pass,
            ["保存用例", "生成接口用例"],
        )
        graph.add_edge("保存用例", END)
        return graph.compile()

if __name__ == '__main__':
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    app = ApiRunCaseGeneratorWorkFlow().create_workflow()
    # 接口文档(从接口表中查询)
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
      """
    # 基础用例(从数据库中查询) - 已移除expected字段
    base_case = {
        "name": "登录成功-正确账号密码",
        "steps": [
            "发送POST请求到登录URL，请求体包含正确的用户名(czj11)和密码(czj111)",
            "验证响应状态码和响应体"
        ],
        "dependencies": []
    }
    # 从测试环境的数据库配置表中查询数据库配置
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
                "database": "test",
            }
        }
    ]
    # 额外的加信息(前端用户输入的参数中传递)
    additional_info = {
        "项目名称": "test_project01",
        "模块名称": "登录模块",
        "备注": "11"
    }
    # 从测试环境表中获取测试数据
    test_data = {
        "base_url": "http://shop-xo.hctestedu.com/index.php?s=",
    }
    # 当前接口的前置依赖接口(从数据库中查询当前接口的依赖分组中的前置依赖接口)
    preconditions_api_doc = []

    response = app.stream({
        "api_doc": api_info,
        "base_case": str(base_case),
        "preconditions_api_doc": preconditions_api_doc,
        "db_config": db_config,
        "test_data": test_data,
        "additional_info": str(additional_info),
    },
        stream_mode=["messages", "custom"]
    )
    for item in response:
        if item[0] == "messages":
            print(item[1][0].content, end="")
        elif item[0] == "custom":
            print(item[1])
