import inspect
import hashlib
import json
import operator
import os
import re
import sys
import threading
from datetime import datetime
from typing import Annotated, Any, List, Optional, TypedDict
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
from agents.api_test.cases.executable import validate_executable_cases
from agents.common.config.settings import llm
from agents.common.tools import global_tools
from services.api_agent.models import (
    ApiContract,
    AssertionDefinition,
    BaseTestCase,
    ExecutableCase,
    ExecutableRequest,
    GenerationRejection,
    ReviewIssue,
    StageEvent,
    VariableConsumer,
    VariableDefinition,
    VariableProducer,
    WorkflowProvenance,
    WorkflowResult,
    WorkflowRuntimeContext,
)

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
    generation_kernel: str  # v2_fused 时委托共享纯生成内核
    v2_contract: dict  # 已确认的 V2 契约；旧 CLI 可不传


class PlatformApiState(TypedDict, total=False):
    """V2.4 阶段三 LangGraph 进程内状态，不含路径、数据库或目标网络能力。"""

    base_cases: list[BaseTestCase]
    contracts: list[ApiContract]
    controlled_manifest: dict[str, Any]
    runtime: WorkflowRuntimeContext
    confirmed_cases: list[BaseTestCase]
    contracts_by_id: dict[str, ApiContract]
    manifest: dict[str, Any]
    raw_candidates: list[tuple[int, BaseTestCase, ApiContract, dict[str, Any]]]
    candidates: list[ExecutableCase]
    rejections: list[GenerationRejection]
    error_code: str
    error_message: str
    workflow_result: WorkflowResult


class ApiRunCaseGeneratorWorkFlow:
    """可运行的接口用例生成的工作流 - 已移除断言相关逻辑，支持数据驱动"""

    # 平台主图的节点列表。保留本文件的旧 CLI 图，平台则显式使用 ``run``，
    # 从而不会继承旧图的目录扫描、MySQL 保存或直接执行副作用。
    _PLATFORM_NODES = (
        "validate_confirmed_inputs", "load_controlled_manifest", "legacy_generate_api_cases",
        "load_controlled_test_data", "normalize_request_candidates", "repair_invalid_candidate",
        "validate_request_completeness", "validate_dependencies_and_variables",
        "validate_assertions_and_grounding", "validate_script_ast", "output_executable_candidates",
    )

    def __init__(self, *, legacy_case_generator=None):
        """初始化平台适配入口；旧 CLI 仍可无参数调用 ``create_workflow``。

        ``legacy_case_generator`` 是旧完整请求生成节点的受控注入点。它只接收当前
        confirmed BaseCase、对应 Contract 和受控 manifest，避免获得任务路径、DB
        配置、Host 或真实 Credential。
        """

        self._legacy_case_generator = legacy_case_generator

    def run(
        self,
        *,
        base_cases: list[BaseTestCase],
        contracts: list[ApiContract],
        controlled_manifest: dict,
        runtime: WorkflowRuntimeContext,
    ) -> WorkflowResult:
        """运行 V2.4 平台阶段三主链，并只返回内存中的可执行候选。

        所有单条候选均在独立 try/except 中处理：一条模型输出或静态门禁失败只能
        令该项 disabled，不能让已通过的候选丢失。函数不调用旧图中的文件扫描、
        MySQL 保存节点或任何真实 API 执行入口。
        """

        state = self.create_platform_workflow().invoke({
            "base_cases": base_cases,
            "contracts": contracts,
            "controlled_manifest": controlled_manifest,
            "runtime": runtime,
            "candidates": [],
            "rejections": [],
            "raw_candidates": [],
        })
        result = state.get("workflow_result")
        return result if isinstance(result, WorkflowResult) else self._failed_result(
            runtime, "WORKFLOW_RESULT_INVALID", "阶段三 Workflow 未返回有效结果",
        )

    def create_platform_workflow(self):
        """构建平台无副作用 LangGraph；旧 ``create_workflow`` 继续服务 legacy CLI。

        每个节点只读写传入的进程内状态。图中没有 TaskStore、MySQL、目录扫描、
        Executor 或目标网络入口，因此 Runner 仍是版本持久化和状态切换的唯一主体。
        """

        graph = StateGraph(PlatformApiState)
        graph.add_node("validate_confirmed_inputs", self._platform_validate_inputs)
        graph.add_node("load_controlled_manifest", self._platform_load_manifest)
        graph.add_node("legacy_generate_api_cases", self._platform_generate_candidates)
        graph.add_node("load_controlled_test_data", self._platform_load_test_data)
        graph.add_node("normalize_request_candidates", self._platform_normalize_candidates)
        graph.add_node("repair_invalid_candidate", self._platform_repair_candidates)
        for node_name in (
            "validate_request_completeness", "validate_dependencies_and_variables",
            "validate_assertions_and_grounding", "validate_script_ast",
        ):
            graph.add_node(node_name, self._platform_validation_node(node_name))
        graph.add_node("output_executable_candidates", self._platform_output)
        graph.add_edge(START, self._PLATFORM_NODES[0])
        for source, target in zip(self._PLATFORM_NODES, self._PLATFORM_NODES[1:]):
            graph.add_edge(source, target)
        graph.add_edge(self._PLATFORM_NODES[-1], END)
        return graph.compile()

    def _platform_validate_inputs(self, state: PlatformApiState) -> dict[str, Any]:
        runtime = state["runtime"]
        self._emit(runtime, "validate_confirmed_inputs", "started", "running", "")
        contracts_by_id = {item.contract_id: item for item in state["contracts"] if item.status == "confirmed"}
        confirmed_cases = [item for item in state["base_cases"] if item.status == "confirmed"]
        if not confirmed_cases or not contracts_by_id:
            return {
                "error_code": "CONFIRMED_INPUT_REQUIRED",
                "error_message": "至少需要已确认的契约和基础用例",
                "contracts_by_id": contracts_by_id,
                "confirmed_cases": confirmed_cases,
            }
        self._emit(runtime, "validate_confirmed_inputs", "completed", "completed", "")
        return {"contracts_by_id": contracts_by_id, "confirmed_cases": confirmed_cases}

    def _platform_load_manifest(self, state: PlatformApiState) -> dict[str, Any]:
        runtime = state["runtime"]
        if state.get("error_code"):
            self._emit(runtime, "load_controlled_manifest", "skipped", "completed", "上游输入无效")
            return {}
        self._emit(runtime, "load_controlled_manifest", "started", "running", "")
        manifest = self._normalise_manifest(state.get("controlled_manifest", {}))
        self._emit(runtime, "load_controlled_manifest", "completed", "completed", "")
        return {"manifest": manifest}

    def _platform_generate_candidates(self, state: PlatformApiState) -> dict[str, Any]:
        runtime = state["runtime"]
        if state.get("error_code"):
            self._emit(runtime, "legacy_generate_api_cases", "skipped", "completed", "上游输入无效")
            return {}
        raw_candidates = []
        rejections = list(state.get("rejections", []))
        for index, base_case in enumerate(state.get("confirmed_cases", [])):
            contract = state.get("contracts_by_id", {}).get(base_case.contract_id)
            if contract is None:
                rejections.append(self._rejection(base_case.contract_id, index, "CONTRACT_NOT_CONFIRMED"))
                continue
            try:
                self._emit(runtime, "legacy_generate_api_cases", "started", "running", base_case.case_id)
                raw = self._legacy_generate_api_cases(base_case, contract, state["manifest"])
                raw_candidates.append((index, base_case, contract, raw))
                self._emit(runtime, "legacy_generate_api_cases", "completed", "completed", base_case.case_id)
            except Exception:
                rejections.append(self._rejection(base_case.contract_id, index, "EXECUTABLE_CANDIDATE_INVALID"))
        return {"raw_candidates": raw_candidates, "rejections": rejections}

    def _platform_load_test_data(self, state: PlatformApiState) -> dict[str, Any]:
        self._emit(state["runtime"], "load_controlled_test_data", "completed", "completed", "仅使用 manifest data_refs")
        return {}

    def _platform_normalize_candidates(self, state: PlatformApiState) -> dict[str, Any]:
        candidates = list(state.get("candidates", []))
        rejections = list(state.get("rejections", []))
        for index, base_case, contract, raw in state.get("raw_candidates", []):
            try:
                candidates.append(self._normalise_candidate(base_case, contract, raw, state["manifest"]))
            except Exception:
                rejections.append(self._rejection(contract.contract_id, index, "EXECUTABLE_CANDIDATE_INVALID"))
        self._emit(state["runtime"], "normalize_request_candidates", "completed", "completed", "")
        return {"candidates": candidates, "rejections": rejections}

    def _platform_repair_candidates(self, state: PlatformApiState) -> dict[str, Any]:
        self._emit(state["runtime"], "repair_invalid_candidate", "skipped", "completed", "平台模式不进行越权重试")
        return {}

    def _platform_validation_node(self, node_name: str):
        def validate(state: PlatformApiState) -> dict[str, Any]:
            # 完整静态校验已由 normalize 节点统一调用，后续节点保留旧图的职责边界
            # 和可观察事件，不能在图外伪造“节点已运行”。
            self._emit(state["runtime"], node_name, "completed", "completed", "")
            return {}
        return validate

    def _platform_output(self, state: PlatformApiState) -> dict[str, Any]:
        runtime = state["runtime"]
        if state.get("error_code"):
            result = self._failed_result(runtime, state["error_code"], state.get("error_message", ""))
            return {"workflow_result": result}
        candidates = state.get("candidates", [])
        ready_count = sum(item.validation_status == "ready" for item in candidates)
        status = "ready" if candidates and ready_count == len(candidates) else "partial_ready" if ready_count else "failed"
        self._emit(runtime, "output_executable_candidates", "completed", "completed", f"输出 {len(candidates)} 条")
        return {"workflow_result": WorkflowResult(
            status=status,
            items=[item.model_dump(mode="json") for item in candidates],
            rejections=state.get("rejections", []),
            quality_summary={
                "candidate_count": len(candidates), "ready_count": ready_count,
                "disabled_count": len(candidates) - ready_count,
            },
            workflow_provenance=self._provenance(runtime),
        )}

    def _legacy_generate_api_cases(self, base_case, contract, manifest):
        """执行旧完整请求生成语义的受控节点，而不是调用外部主生成器。"""

        if self._legacy_case_generator is None:
            raise ValueError("平台模式必须注入受控 legacy_case_generator")
        return self._legacy_case_generator(base_case, contract, manifest)

    @staticmethod
    def _normalise_manifest(manifest: dict) -> dict:
        """仅保留阶段三允许的资源元数据，拒绝路径、Host 和凭证注入。"""

        value = manifest if isinstance(manifest, dict) else {}
        return {
            "data_refs": [str(item) for item in value.get("data_refs", []) if str(item).strip()],
            "capabilities": [str(item) for item in value.get("capabilities", []) if str(item).strip()],
            "precondition_case_ids": [str(item) for item in value.get("precondition_case_ids", []) if str(item).strip()],
        }

    def _normalise_candidate(self, base_case, contract, raw, manifest) -> ExecutableCase:
        """将旧节点输出规范化，并将 V2 静态校验作为图内工具执行。"""

        if not isinstance(raw, dict) or not isinstance(raw.get("request"), dict):
            raise ValueError("旧生成节点必须返回包含 request 的对象")
        request_data = dict(raw["request"])
        raw_path = str(request_data.get("path", ""))
        issues: list[ReviewIssue] = []
        if urlsplit(raw_path).scheme or urlsplit(raw_path).netloc:
            issues.append(self._issue("request.path", "HOST_FORBIDDEN", "执行定义不得包含 Host"))
            request_data["path"] = contract.path
        if not str(request_data.get("path", "")).startswith("/"):
            request_data["path"] = contract.path

        if self._has_plaintext_credential(request_data, raw.get("variable_consumers", [])):
            issues.append(self._issue(
                "request", "PLAINTEXT_CREDENTIAL_FORBIDDEN",
                "请求或变量默认值不得包含明文凭证，请改用受控运行时变量",
            ))

        data_refs = [str(item) for item in raw.get("data_refs", []) if str(item).strip()]
        unknown_refs = sorted(set(data_refs) - set(manifest["data_refs"]))
        if unknown_refs:
            issues.append(self._issue("data_refs", "DATA_REF_FORBIDDEN", f"未登记 data_ref: {unknown_refs}"))

        producers = [VariableProducer.model_validate(item) for item in raw.get("variable_producers", [])]
        consumers = [VariableConsumer.model_validate(item) for item in raw.get("variable_consumers", [])]
        variables = [
            VariableDefinition(name=item.name, source="precondition", source_path=item.source_path)
            for item in producers
        ]
        declared = {item.name for item in variables}
        for name in self._template_names(request_data):
            if name not in declared:
                variables.append(VariableDefinition(
                    name=name, source="input", source_path=data_refs[0] if data_refs else "",
                ))
                declared.add(name)

        raw_assertions = raw.get("assertions") if isinstance(raw.get("assertions"), list) else []
        # 旧模型偶尔遗漏断言。正常场景只能从已确认契约的 2xx 响应补齐，绝不
        # 使用固定 200；负向或探索场景没有明确预期时仍由静态门禁阻断。
        if not raw_assertions and base_case.scenario_type == "normal":
            documented_success = next((
                item.status_code for item in contract.responses
                if str(item.status_code).isdigit() and 200 <= int(item.status_code) < 300
            ), None)
            if documented_success is not None:
                raw_assertions = [{"operator": "status_code", "expected": int(documented_success)}]

        case = ExecutableCase(
            executable_case_id=f"exec_{base_case.case_id.removeprefix('case_')}",
            artifact_schema_version=3,
            base_case_id=base_case.case_id,
            contract_id=contract.contract_id,
            name=base_case.name,
            risk_level=base_case.risk_level,
            document_sla_ms=contract.sla_ms,
            request=ExecutableRequest.model_validate(request_data),
            precondition_case_ids=[str(item) for item in raw.get("precondition_case_ids", [])],
            assertions=[AssertionDefinition.model_validate(item) for item in raw_assertions],
            variables=variables,
            variable_producers=producers,
            variable_consumers=consumers,
            data_refs=data_refs,
            observation_targets=[str(item) for item in raw.get("observation_targets", []) if str(item).strip()],
            generation_kernel="v2_core_workflow",
            generation_sources=["legacy_generate_api_cases", f"contract:{contract.contract_id}"],
            validation_issues=issues,
        )
        # 复用既有契约、变量、依赖、断言和 AST 校验；跨批次已确认前置用例由受控
        # manifest 显式声明，避免把其当成缺失依赖。
        case = validate_executable_cases([case], [contract])[0]
        external_dependencies = set(manifest["precondition_case_ids"])
        case.validation_issues = [
            issue for issue in case.validation_issues
            if not (issue.code == "DEPENDENCY_MISSING" and set(case.precondition_case_ids) <= external_dependencies)
        ]
        case.validation_status = "disabled" if case.validation_issues else "ready"
        case.enabled = case.validation_status == "ready"
        if case.validation_status == "disabled":
            case.review_status = "disabled"
        return case

    @staticmethod
    def _template_names(value) -> set[str]:
        """提取受控 ``{{name}}`` 占位符，用于补齐 data_ref 输入声明。"""

        return set(re.findall(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}", json.dumps(value, ensure_ascii=False)))

    @staticmethod
    def _has_plaintext_credential(request_data: dict, consumers: list | None = None) -> bool:
        """递归检查 Header、Query、Cookie、Body 及变量默认值中的明文凭证。"""

        sensitive = re.compile(
            r"(?i)(?:authorization|proxy[_-]?authorization|api[_-]?key|token|password|passwd|secret|cookie|session|csrf)"
        )
        placeholder = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.-]*\s*\}\}")

        def unsafe(value, key=""):
            if isinstance(value, dict):
                return any(unsafe(child, str(child_key)) for child_key, child in value.items())
            if isinstance(value, list):
                return any(unsafe(child, key) for child in value)
            if not sensitive.search(key) or value is None or value == "":
                return False
            text = str(value).strip()
            remainder = placeholder.sub("", text).strip().lower()
            return not placeholder.search(text) or remainder not in {"", "bearer", "basic"}

        if unsafe(request_data):
            return True
        for consumer in consumers if isinstance(consumers, list) else []:
            if not isinstance(consumer, dict) or consumer.get("default_policy") != "use_default":
                continue
            key = f"{consumer.get('name', '')}.{consumer.get('field_path', '')}"
            if unsafe(consumer.get("default_value"), key):
                return True
        return False

    @staticmethod
    def _issue(field_path: str, code: str, message: str) -> ReviewIssue:
        return ReviewIssue(code=code, field_path=field_path, message=message, severity="blocker")

    @staticmethod
    def _rejection(contract_id: str, index: int, code: str) -> GenerationRejection:
        return GenerationRejection(
            contract_id=contract_id, item_index=index, prompt_id="api_case_generator.v2.4",
            prompt_sha256="", error_code=code, rejection_stage="schema",
            suggestion="修复该条完整请求候选后重试",
        )

    @classmethod
    def _provenance(cls, runtime: WorkflowRuntimeContext) -> WorkflowProvenance:
        return WorkflowProvenance(
            workflow_id=runtime.workflow_id, workflow_version=runtime.workflow_version,
            workflow_sha256=hashlib.sha256("|".join(cls._PLATFORM_NODES).encode()).hexdigest(),
            input_versions=runtime.input_versions, node_ids=list(cls._PLATFORM_NODES),
        )

    @classmethod
    def _emit(cls, runtime, node, event_type, status, message):
        runtime.event_sink(StageEvent(
            event_id=f"workflow_{hashlib.sha256(f'{runtime.attempt_id}|{node}|{event_type}'.encode()).hexdigest()[:20]}",
            task_id=runtime.task_id, attempt_id=runtime.attempt_id, stage="executable_generation",
            node=node, event_type=event_type, status=status, message=message,
            input_versions=runtime.input_versions, workflow_id=runtime.workflow_id,
            workflow_version=runtime.workflow_version,
            workflow_sha256=hashlib.sha256("|".join(cls._PLATFORM_NODES).encode()).hexdigest(),
        ))

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
        if state.get("generation_kernel") == "v2_fused" and state.get("v2_contract"):
            # 仅显式融合模式委托无副作用适配层，保持旧 CLI 默认输出路径不变。
            from agents.api_test.cases.executable import build_executable_cases
            from services.api_agent.models import ApiContract, BaseTestCase

            contract = ApiContract.model_validate(state["v2_contract"])
            base_case = BaseTestCase.model_validate(state.get("base_case"))
            generated = build_executable_cases([base_case], [contract])
            if generated:
                case = generated[0]
                return {
                    "api_case": {
                        "name": case.name,
                        "description": base_case.objective,
                        "interface": case.request.path,
                        "preconditions": case.precondition_case_ids,
                        "request": {
                            "method": case.request.method,
                            "url": case.request.path,
                            "base_url": "${{base_url}}",
                            "headers": case.request.headers,
                            "params": case.request.query,
                            "cookies": case.request.cookies,
                            "body": case.request.body,
                            "setup_script": case.setup_script,
                            "teardown_script": case.teardown_script,
                        },
                        "assertions": [item.model_dump(mode="json") for item in case.assertions],
                        "observation_targets": case.observation_targets,
                        "validation_status": case.validation_status,
                    },
                    "generator_count": state.get("generator_count", 0) + 1,
                }
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

        if not state.get("persist_to_database", False):
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
