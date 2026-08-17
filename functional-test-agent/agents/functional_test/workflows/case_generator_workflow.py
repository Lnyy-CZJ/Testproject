"""
测试用例生成工作流

包含两个核心部分：
  1. GeneratorPointWorkflow - 子工作流，负责生成测试点（分析需求 → 生成点 → 验证覆盖 → 补充缺失）
  2. GeneratorTestCaseWorkflow - 主工作流，调用子工作流获取测试点，然后生成测试用例
"""
import os
import operator
import json
import re
import warnings
import pandas as pd
from pathlib import Path
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from datetime import datetime
from dataclasses import dataclass
from typing import Callable, TypedDict, List, Annotated, Any, Optional
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.utils.json import parse_partial_json
from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

# Pandas/LangChain 导入过程会重排 warnings 过滤器，因此必须紧邻 LangGraph 导入设置。
# 这里只隐藏已确认无行为影响的 allowed_objects 默认值告警，其余告警继续正常输出。
warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change.*",
    category=LangChainPendingDeprecationWarning,
)

from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command
from langgraph.graph import StateGraph
from langgraph.constants import START, END
from pydantic import BaseModel
from agents.common.config.settings import llm
from agents.common.utils.token_usage import invoke_with_token_usage
from agents.functional_test.prompts import (
    generator_test_point,
    generator_testcase,
    supplement_missing_test_cases,
    supplement_missing_test_points,
    verify_test_points_coverage,
    verify_testcase_coverage,
)



class RelaxedJsonOutputParser(JsonOutputParser):
    """
    宽松 JSON 解析器。

    功能说明:
        先使用标准 JsonOutputParser；失败后尝试 parse_partial_json；仍失败时
        使用 json_repair 修复 LLM 常见 JSON 语法错误，例如中间缺少逗号。

    参数说明:
        result: LangChain 传入的模型输出列表。
        partial (bool): 是否允许部分解析，沿用 JsonOutputParser 参数。

    返回值:
        list | dict: 解析后的 JSON 数据。

    异常说明:
        三层解析均失败时抛出 OutputParserException，保留原始输出片段便于排查。
    """

    def parse_result(self, result, *, partial=False):
        text = result[0].text.strip() if hasattr(result[0], 'text') else str(result[0]).strip()

        try:
            return super().parse_result(result, partial=partial)
        except Exception:
            pass

        text = text.strip()
        if text.startswith('```'):
            lines = text.split('\n')
            text = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])

        try:
            return parse_partial_json(text)
        except Exception:
            pass

        try:
            from json_repair import repair_json
            repaired = repair_json(text, return_objects=True)
            if repaired not in ("", None):
                return repaired
        except Exception as e:
            raise OutputParserException(
                f"Invalid json output after repair: {text[:500]}..."
            ) from e

        raise OutputParserException(f"Invalid json output: {text[:500]}...")


@dataclass
class RuntimeContext:
    """运行时上下文参数"""
    project_id: str  # 测试环境ID
    module_id: str  # 测试模块ID


class State(TypedDict):
    """主工作流的状态"""
    # 输入需求文档
    document: str
    # 输入需求文档路径，用于触发 requirement_decomposition
    document_path: str
    # 需求拆解后的结构化测试点生成上下文
    requirement_context: str
    # 需求拆解报告摘要
    decomposition_report: dict
    # 需求拆解产物输出目录，为空时自动使用 output/requirements_docs/<功能名>
    requirements_output_dir: str
    # 手动指定的功能名称，用于自动生成需求拆解产物目录
    requirement_feature_name: str
    # 用户补充的测试设计侧重点，不得覆盖原始需求事实
    additional_context: str
    # 测试点
    test_point: List
    # 测试用例
    test_cases: Annotated[List, operator.add]
    # 测试用例覆盖率的报告分析
    test_case_coverage_report: dict
    # 缺失测试用例
    missing_testcases: List[str]
    # 覆盖分析循环轮次
    round: int


class State2(TypedDict):
    """子工作流的状态"""
    # 输入需求文档
    document: str
    # 输入需求文档路径，用于追溯结构化上下文来源
    document_path: str
    # 需求拆解后的结构化测试点生成上下文
    requirement_context: str
    # 需求拆解报告摘要
    decomposition_report: dict
    # 需求拆解产物输出目录
    requirements_output_dir: str
    # 手动指定的功能名称，用于自动生成需求拆解产物目录
    requirement_feature_name: str
    # 用户补充的测试设计侧重点，不得覆盖原始需求事实
    additional_context: str
    # 生成的测试点
    point: Annotated[List, operator.add]
    # 测试点文件路径
    test_point_file: str
    # 覆盖率分析报告
    coverage_report: dict
    # 缺失测试点
    missing_test_points: List[str]
    # 覆盖分析循环轮次
    round: int


class TestPointModel(BaseModel):
    """测试点数据模型"""
    type: str
    test_point: str


# 测试点覆盖率分析结果数据模型
class Coverage_test_points_Result(BaseModel):
    is_covered: bool
    missing_test_points: List[str]
    analysis: str


#"""测试用例数据模型"""
class TestCaseModel(BaseModel):
    case_id: str
    test_point_id: str
    module: str
    feature: str
    scenario: str
    case_name: str
    priority: str
    preconditions: str
    test_steps: str
    test_data: str
    expected_result: str
    actual_result: Optional[str]

# 测试用例覆盖率分析结果数据模型
class CoverageResult(BaseModel):
    is_covered: bool
    missing_testcases: List[str]
    analysis: str


def get_is_covered(report):
    """安全获取is_covered字段"""
    if isinstance(report, dict):
        return report.get("is_covered", False)
    elif hasattr(report, "is_covered"):
        return report.is_covered
    return False

def normalize_result(result: Any) -> dict:
    """标准化结果，处理列表或字典"""
    if isinstance(result, list) and len(result) > 0:
        return result[0] if isinstance(result[0], dict) else {}
    elif isinstance(result, dict):
        return result
    elif hasattr(result, "model_dump"):
        return result.model_dump()
    return {}

# 👈 新增这个函数：专门对抗大模型返回格式不稳定的问题.在所有执行 chain.invoke 的地方，套上 ensure_list
def ensure_list(data: Any) -> list:
    """确保大模型返回的数据永远是 list"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 如果大模型包了一层字典，比如 {"test_cases": [{...}, {...}]}，尝试提取里面的列表
        for val in data.values():
            if isinstance(val, list):
                return val
        # 如果就是一个单纯的字典，把它包裹进列表
        return [data]
    if not data:
        return []
    return [data]


def use_brief_context() -> bool:
    """
    功能说明:
        判断覆盖校验阶段是否使用轻量用例上下文。

    参数说明:
        无。读取环境变量 USE_BRIEF_CONTEXT，默认启用。

    返回值:
        bool: True 表示仅传递用例摘要，False 表示保留原完整用例上下文。

    异常说明:
        不抛出异常；缺失环境变量时使用默认值。
    """
    return os.getenv("USE_BRIEF_CONTEXT", "true").lower() != "false"


def build_test_cases_brief(test_cases: List) -> List[dict]:
    """
    功能说明:
        将完整测试用例压缩为覆盖校验所需的最小字段集合。

    参数说明:
        test_cases (List): 工作流中已生成的完整测试用例列表。

    返回值:
        List[dict]: 仅包含 case_id、case_name、priority、expected_result 的摘要列表。

    异常说明:
        不抛出异常；非字典用例会被转换为字符串摘要，保证流程不中断。
    """
    brief_cases = []
    for index, case in enumerate(test_cases or [], 1):
        if isinstance(case, dict):
            brief_cases.append({
                "case_id": case.get("case_id") or f"CASE_{index:03d}",
                "test_point_id": case.get("test_point_id", ""),
                "module": case.get("module", ""),
                "feature": case.get("feature", ""),
                "scenario": case.get("scenario", ""),
                "case_name": case.get("case_name", ""),
                "priority": case.get("priority", ""),
                "expected_result": case.get("expected_result", ""),
            })
        else:
            brief_cases.append({
                "case_id": f"CASE_{index:03d}",
                "test_point_id": "",
                "module": "",
                "feature": "",
                "scenario": "",
                "case_name": str(case),
                "priority": "",
                "expected_result": "",
            })
    return brief_cases

def use_coverage_matrix() -> bool:
    """
    功能说明:
        判断是否启用本地覆盖矩阵预过滤，减少进入 LLM 的测试点数量。

    参数说明:
        无。读取环境变量 USE_COVERAGE_MATRIX，默认启用。

    返回值:
        bool: True 表示启用矩阵预过滤，False 表示直接走原 LLM 校验。

    异常说明:
        不抛出异常；缺失环境变量时使用默认值。
    """
    return os.getenv("USE_COVERAGE_MATRIX", "true").lower() != "false"


def build_requirement_context(state: dict) -> str:
    """
    功能说明:
        构建传给 LLM 的需求上下文，优先使用 requirement_decomposition
        产出的结构化 test_seed 上下文；缺失时回退原始需求文档。

    参数说明:
        state (dict): LangGraph 工作流状态，包含 requirement_context 或 document 字段。

    返回值:
        str: 结构化需求上下文或原始需求文档内容。
    """
    requirement_context = state.get("requirement_context", "")
    if requirement_context:
        return requirement_context
    return state.get("document", "")


def _model_to_dict(value: Any) -> dict:
    """
    功能说明:
        将 Pydantic 模型或字典统一转换为普通 dict，便于格式化 test_seed。

    参数说明:
        value (Any): Pydantic 模型、dict 或其他对象。

    返回值:
        dict: 可安全读取的字典；无法转换时返回空字典。

    异常说明:
        不抛出异常，异常数据按空字典处理。
    """
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _join_text(values: Any, separator: str = "；") -> str:
    """
    功能说明:
        将列表字段格式化为紧凑文本，保持空值可读。

    参数说明:
        values (Any): 字符串、列表或其他可字符串化对象。
        separator (str): 多值拼接符。

    返回值:
        str: 拼接后的文本；无有效内容时返回“-”。

    异常说明:
        不抛出异常；None 和空列表返回“-”。
    """
    if isinstance(values, str):
        return values.strip() or "-"
    if not values:
        return "-"
    if isinstance(values, list):
        items = [str(item).strip() for item in values if str(item).strip()]
        return separator.join(items) if items else "-"
    return str(values).strip() or "-"


def build_test_seed_requirement_context(test_seeds: List[Any]) -> str:
    """
    功能说明:
        将 requirement_decomposition 输出的 test_seed 聚合记录转换为测试点生成上下文。

    参数说明:
        test_seeds (List[Any]): TestSeedRecord 模型或等价字典列表。

    返回值:
        str: 面向测试点生成和覆盖校验的结构化需求上下文。

    异常说明:
        不抛出异常；异常 seed 会按空字段输出，避免阻断原测试流程。
    """
    if not test_seeds:
        return ""

    lines = [
        "# 结构化需求测试点生成上下文",
        "说明: 以下内容来自 requirement_decomposition 的 test_seed 聚合结果。",
        "约束: 不确定项只能作为需确认或建议类测试方向，不能当作已确认需求事实。",
        "",
    ]

    for index, seed_item in enumerate(test_seeds, 1):
        seed_record = _model_to_dict(seed_item)
        test_seed = _model_to_dict(seed_record.get("test_seed", {}))
        source_trace = _model_to_dict(seed_record.get("source_trace", {}))
        evidence_summary = _model_to_dict(seed_record.get("evidence_summary", {}))

        requirement_ids = seed_record.get("requirement_ids") or [seed_record.get("requirement_id", "")]
        source_sections = source_trace.get("section_ids") or source_trace.get("section_id") or []
        source_ids = source_trace.get("source_ids") or source_trace.get("source_id") or []

        lines.extend([
            f"## Seed {index}: {seed_record.get('requirement_id', '-')}",
            f"模块: {seed_record.get('module', '-') or '-'}",
            f"功能: {seed_record.get('feature', '-') or '-'}",
            f"需求ID: {_join_text(requirement_ids, separator=', ')}",
            f"来源: source={_join_text(source_ids, separator=', ')} section={_join_text(source_sections, separator=', ')}",
            f"状态标签: {_join_text(seed_record.get('status_tags', []))}",
            f"证据摘要: fact_fields_grounded={evidence_summary.get('fact_fields_grounded', False)}, suggestions_include_inferred_items={evidence_summary.get('suggestions_include_inferred_items', False)}",
            f"需求标题: {_join_text(test_seed.get('requirement_titles', []))}",
            f"测试对象: {_join_text(test_seed.get('objects', []))}",
            f"前置条件: {_join_text(test_seed.get('conditions', []))}",
            f"业务约束: {_join_text(test_seed.get('constraints', []))}",
            f"权限规则: {_join_text(test_seed.get('permissions', []))}",
            f"有效状态流转: {_join_text(test_seed.get('state_transitions', []))}",
            f"无效状态流转: {_join_text(test_seed.get('invalid_state_transitions', []))}",
            f"风险标签: {_join_text(test_seed.get('risk_tags', []))}",
            f"预期结果: {_join_text(test_seed.get('expected_results', []))}",
            f"负向建议: {_join_text(test_seed.get('negative_suggestions', []))}",
            f"不确定项: {_join_text(test_seed.get('uncertain_items', []))}",
            "",
        ])

    return "\n".join(lines).strip()


def sanitize_requirement_folder_name(name: str) -> str:
    """
    功能说明:
        将功能名称转换为可用于目录名的安全文本。

    参数说明:
        name (str): 用户指定功能名或需求文档文件名。

    返回值:
        str: 清理后的目录名；空值返回“未命名功能”。

    异常说明:
        不抛出异常。
    """
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", str(name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or "未命名功能"


def infer_requirement_feature_name(document_path: str, feature_name: str = "") -> str:
    """
    功能说明:
        推断需求拆解产物目录使用的功能名称。

    参数说明:
        document_path (str): 需求文档路径。
        feature_name (str): 用户手动指定的功能名称，优先级最高。

    返回值:
        str: 安全目录名。
    """
    if feature_name:
        return sanitize_requirement_folder_name(feature_name)
    if document_path:
        return sanitize_requirement_folder_name(Path(document_path).stem)
    return "未命名功能"


def resolve_requirement_output_dir(
    document_path: str,
    requirements_output_dir: str = "",
    feature_name: str = "",
    output_base_dir: str = "",
) -> Path:
    """
    功能说明:
        解析本次需求拆解产物目录。用户指定 requirements_output_dir 时直接使用；
        否则默认使用 output/requirements_docs/<功能名>。

    参数说明:
        document_path (str): 需求文档路径。
        requirements_output_dir (str): 用户手动指定的拆解产物目录。
        feature_name (str): 用户手动指定功能名，用于默认目录命名。
        output_base_dir (str): 默认根目录，测试可注入；为空时使用当前工作目录下 output/requirements_docs。

    返回值:
        Path: 解析后的绝对目录路径。
    """
    if requirements_output_dir:
        return Path(requirements_output_dir).expanduser().resolve()

    base_dir = Path(output_base_dir or os.path.join(os.getcwd(), "output", "requirements_docs"))
    folder_name = infer_requirement_feature_name(document_path, feature_name)
    return (base_dir / folder_name).expanduser().resolve()


def load_cached_test_seeds(requirements_output_dir: Path) -> list:
    """
    功能说明:
        从需求拆解产物目录读取已缓存的 test_seed.json。

    参数说明:
        requirements_output_dir (Path): 需求拆解产物目录。

    返回值:
        list: test_seed 记录列表；不存在或格式不正确时返回空列表。

    异常说明:
        JSON 读取异常向上抛出，由调用方转换为降级报告。
    """
    test_seed_path = requirements_output_dir / "test_seed.json"
    if not test_seed_path.is_file():
        return []
    with open(test_seed_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("test_seeds") or data.get("items") or []
    return data if isinstance(data, list) else []


def _invoke_decomposition_runner(
    runner: Callable[..., Any],
    source_path: str,
    config_path: str,
    output_dir: str,
) -> Any:
    """
    功能说明:
        调用需求拆解函数，并兼容旧测试桩不支持 output_dir 参数的情况。

    参数说明:
        runner: run_decomposition 或测试桩。
        source_path (str): 需求文档路径。
        config_path (str): 配置路径。
        output_dir (str): 本次拆解输出目录。

    返回值:
        Any: 拆解结果对象。
    """
    try:
        return runner(source_path=source_path, config_path=config_path, output_dir=output_dir)
    except TypeError as exc:
        if "output_dir" not in str(exc):
            raise
        return runner(source_path=source_path, config_path=config_path)


def prepare_requirement_context_from_document_path(
    document_path: str,
    config_path: str | None = None,
    writer: Optional[Callable[[str], None]] = None,
    decomposition_runner: Optional[Callable[..., Any]] = None,
    requirements_output_dir: str = "",
    feature_name: str = "",
) -> tuple[str, dict]:
    """
    功能说明:
        基于本地需求文档路径执行 requirement_decomposition，并返回测试点生成上下文。

    参数说明:
        document_path (str): 原始需求文档路径；为空时不触发拆解。
        config_path (str | None): 需求拆解配置路径，默认读取环境变量
            REQUIREMENT_DECOMPOSITION_CONFIG，未配置时使用 requirement_decomposition.yaml。
        writer (Optional[Callable[[str], None]]): 可选日志输出函数。
        decomposition_runner (Optional[Callable[..., Any]]): 可注入拆解函数，便于测试。
        requirements_output_dir (str): 用户手动指定的拆解产物目录。
        feature_name (str): 用户手动指定的功能名称，用于自动生成默认目录。

    返回值:
        tuple[str, dict]: 结构化上下文和拆解报告摘要；失败时上下文为空。

    异常说明:
        拆解异常会被捕获并写入报告，不向 functional_test 主流程继续抛出。
    """
    if not document_path:
        return "", {"success": False, "errors": ["document_path 为空，跳过需求拆解"]}

    resolved_path = str(Path(document_path).expanduser().resolve())
    active_config_path = config_path or os.getenv(
        "REQUIREMENT_DECOMPOSITION_CONFIG",
        "requirement_decomposition.yaml",
    )
    output_dir = resolve_requirement_output_dir(
        document_path=resolved_path,
        requirements_output_dir=requirements_output_dir,
        feature_name=feature_name,
    )
    log = writer or (lambda message: None)

    try:
        cached_test_seeds = load_cached_test_seeds(output_dir)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}" if str(exc) else repr(exc)
        log(f"读取需求拆解缓存失败，将重新拆解：{message}")
        cached_test_seeds = []

    if cached_test_seeds:
        context = build_test_seed_requirement_context(cached_test_seeds)
        log(f"发现已存在需求拆解产物，复用缓存：{output_dir}")
        return context, {
            "success": True,
            "errors": [],
            "warnings": [],
            "quality_report": {},
            "test_seed_count": len(cached_test_seeds),
            "output_dir": str(output_dir),
            "reused_cached_decomposition": True,
        }

    try:
        runner = decomposition_runner
        if runner is None:
            from requirement_decomposition import run_decomposition

            runner = run_decomposition

        result = _invoke_decomposition_runner(
            runner=runner,
            source_path=resolved_path,
            config_path=active_config_path,
            output_dir=str(output_dir),
        )
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}" if str(exc) else repr(exc)
        log(f"需求拆解执行失败，降级使用原始需求文档：{message}")
        return "", {"success": False, "errors": [message], "test_seed_count": 0}

    report = {
        "success": bool(getattr(result, "success", False)),
        "errors": list(getattr(result, "errors", []) or []),
        "warnings": list(getattr(result, "warnings", []) or []),
        "quality_report": getattr(result, "quality_report", {}) or {},
        "test_seed_count": len(getattr(result, "test_seeds", []) or []),
        "output_dir": str(output_dir),
        "reused_cached_decomposition": False,
    }

    if not report["success"]:
        log(f"需求拆解未通过，降级使用原始需求文档：{report['errors']}")
        return "", report

    context = build_test_seed_requirement_context(getattr(result, "test_seeds", []) or [])
    if not context:
        report["success"] = False
        report["errors"].append("需求拆解未返回可消费的 test_seeds")
        log("需求拆解未返回 test_seeds，降级使用原始需求文档")
        return "", report

    log(f"需求拆解完成，生成结构化 test_seed 上下文，seed 数量：{report['test_seed_count']}")
    return context, report


def _compact_text(value: Any) -> str:
    """
    功能说明:
        将覆盖匹配字段标准化为小写紧凑字符串。

    参数说明:
        value (Any): 任意可字符串化的字段值。

    返回值:
        str: 去除常见空白符后的字符串。

    异常说明:
        不抛出异常；None 返回空字符串。
    """
    return re.sub(r"\s+", "", str(value or "").lower())


def _extract_point_terms(test_point: str) -> set[str]:
    """
    功能说明:
        从测试点中提取用于本地覆盖匹配的关键词和中文短语片段。

    参数说明:
        test_point (str): 单个测试点描述。

    返回值:
        set[str]: 关键词集合，用于和用例名称、预期结果做高置信匹配。

    异常说明:
        不抛出异常；空测试点返回空集合。
    """
    text = _compact_text(test_point)
    words = {word for word in re.findall(r"[\w\u4e00-\u9fff]+", text) if len(word) >= 2}
    if len(text) >= 4:
        words.update(text[i:i + 4] for i in range(0, max(0, len(text) - 3)))
    return words


def _test_point_id(test_point: Any) -> str:
    """
    功能说明:
        从测试点对象中提取稳定 ID，兼容 id 和 test_point_id 字段。

    参数说明:
        test_point (Any): 测试点字典或字符串。

    返回值:
        str: 测试点 ID；缺失时返回空字符串。

    异常说明:
        不抛出异常；非字典返回空字符串。
    """
    if isinstance(test_point, dict):
        return str(test_point.get("id") or test_point.get("test_point_id") or "").strip()
    return ""


def _test_point_text(test_point: Any) -> str:
    """
    功能说明:
        提取测试点核心文本，用于覆盖矩阵的保守匹配。

    参数说明:
        test_point (Any): 测试点字典或字符串。

    返回值:
        str: 测试点描述文本。

    异常说明:
        不抛出异常；异常对象按字符串处理。
    """
    if isinstance(test_point, dict):
        parts = [
            test_point.get("module", ""),
            test_point.get("feature", ""),
            test_point.get("scenario", ""),
            test_point.get("test_point", ""),
        ]
        return " ".join(str(part) for part in parts if str(part).strip())
    return str(test_point or "")


def build_case_generation_points(test_points: List) -> List[dict]:
    """
    功能说明:
        保留测试点结构，构建传给测试用例生成模型的输入列表。

    参数说明:
        test_points (List): 测试点列表，支持结构化 dict 或纯文本。

    返回值:
        List[dict]: 包含 id、module、feature、scenario、test_point、risk_level 的测试点列表。

    异常说明:
        不抛出异常；纯文本测试点会补齐最小字段和连续 ID。
    """
    case_points = []
    for index, point in enumerate(test_points or [], 1):
        if isinstance(point, dict):
            point_id = str(point.get("id") or point.get("test_point_id") or f"TP{index:03d}")
            case_points.append({
                "id": point_id,
                "module": str(point.get("module", "")),
                "feature": str(point.get("feature", "")),
                "scenario": str(point.get("scenario", "")),
                "test_point": str(point.get("test_point", "")),
                "risk_level": str(point.get("risk_level") or point.get("priority") or "P2"),
            })
        else:
            case_points.append({
                "id": f"TP{index:03d}",
                "module": "",
                "feature": "",
                "scenario": "",
                "test_point": str(point),
                "risk_level": "P2",
            })
    return case_points


def build_coverage_matrix(test_points: List[Any], test_cases: List[dict]) -> tuple[list[dict], list[Any]]:
    """
    功能说明:
        基于测试点和用例摘要构建本地覆盖矩阵，先筛掉高置信已覆盖项。

    参数说明:
        test_points (List[Any]): 测试点文本或结构化测试点列表。
        test_cases (List[dict]): 轻量用例摘要列表。

    返回值:
        tuple[list[dict], list[Any]]: 覆盖矩阵、需要 LLM 继续判断的测试点列表。

    异常说明:
        不抛出异常；异常数据会按空字段处理。
    """
    matrix = []
    unverified_points = []

    for point in test_points:
        point_id = _test_point_id(point)
        readable_point = _test_point_text(point)
        point_text = _compact_text(readable_point)
        point_terms = _extract_point_terms(readable_point)
        matched_cases = []

        for case in test_cases:
            case_test_point_id = str(case.get("test_point_id", "")).strip()
            if point_id and case_test_point_id == point_id:
                matched_cases.append({
                    "case_id": case.get("case_id", ""),
                    "case_name": case.get("case_name", ""),
                    "matched_reason": "test_point_id",
                })
                continue

            case_text = _compact_text(
                f"{case.get('case_name', '')} {case.get('expected_result', '')}"
            )
            exact_match = point_text and point_text in case_text
            term_hits = [term for term in point_terms if term in case_text]
            if exact_match or len(term_hits) >= 2:
                matched_cases.append({
                    "case_id": case.get("case_id", ""),
                    "case_name": case.get("case_name", ""),
                    "matched_reason": "exact" if exact_match else "keyword",
                })

        is_confident = bool(matched_cases)
        matrix.append({
            "test_point": point,
            "matched_cases": matched_cases,
            "is_confident": is_confident,
        })
        if not is_confident:
            unverified_points.append(point)

    return matrix, unverified_points


def get_case_generation_batch_size() -> int:
    """
    功能说明:
        获取测试用例生成批次大小，控制单次 LLM 输出 JSON 的长度。

    参数说明:
        无。读取环境变量 CASE_GENERATION_BATCH_SIZE，默认每批 5 个测试点。

    返回值:
        int: 限制在 1 到 20 之间的批次大小。

    异常说明:
        当环境变量不是合法整数时回退到 5。
    """
    try:
        batch_size = int(os.getenv("CASE_GENERATION_BATCH_SIZE", "5"))
    except ValueError:
        batch_size = 5
    return min(20, max(1, batch_size))


def chunk_items(items: List, batch_size: int) -> List[List]:
    """
    功能说明:
        将测试点或缺失用例方向拆分为小批次，降低长 JSON 输出风险。

    参数说明:
        items (List): 待处理项目列表。
        batch_size (int): 每批项目数量。

    返回值:
        List[List]: 分批后的二维列表。

    异常说明:
        不抛出异常；空列表返回空列表。
    """
    return [items[index:index + batch_size] for index in range(0, len(items or []), batch_size)]


def merge_unique_cases(existing_cases: List, new_cases: List) -> List[dict]:
    """
    功能说明:
        合并测试用例，优先按 test_point_id 保持“一个测试点一个用例”的映射。
        只有同一 test_point_id 的用例会被视为重复；缺少 test_point_id 时才按
        case_name + expected_result 的精确指纹去重。

    参数说明:
        existing_cases (List): 已累计的测试用例列表。
        new_cases (List): 当前批次新生成的测试用例列表。

    返回值:
        List[dict]: 合并后的测试用例列表，不会因为 case_name 相似误删不同测试点用例。

    异常说明:
        不抛出异常；非字典用例会被忽略。
    """
    merged = [case for case in existing_cases or [] if isinstance(case, dict)]
    existing_point_ids = {
        str(case.get("test_point_id", "")).strip()
        for case in merged
        if str(case.get("test_point_id", "")).strip()
    }
    existing_fingerprints = {
        (str(case.get("case_name", "")).strip(), str(case.get("expected_result", "")).strip())
        for case in merged
        if not str(case.get("test_point_id", "")).strip()
    }

    for case in new_cases or []:
        if not isinstance(case, dict):
            continue

        test_point_id = str(case.get("test_point_id", "")).strip()
        if test_point_id:
            if test_point_id not in existing_point_ids:
                merged.append(case)
                existing_point_ids.add(test_point_id)
            continue

        fingerprint = (
            str(case.get("case_name", "")).strip(),
            str(case.get("expected_result", "")).strip(),
        )
        if fingerprint != ("", "") and fingerprint not in existing_fingerprints:
            merged.append(case)
            existing_fingerprints.add(fingerprint)
    return merged


def bind_cases_to_test_points(cases: List, test_points: List) -> List[dict]:
    """
    功能说明:
        将模型生成的测试用例按批次顺序绑定回输入测试点，补齐关键映射字段。

    参数说明:
        cases (List): 当前批次模型生成的测试用例列表。
        test_points (List): 当前批次输入的结构化测试点或缺失测试点列表。

    返回值:
        List[dict]: 已补齐 test_point_id、module、feature、scenario、priority 的用例列表。

    异常说明:
        不抛出异常；非字典用例会被忽略，超出测试点数量的用例保留原字段。
    """
    bound_cases = []
    for index, case in enumerate(cases or []):
        if not isinstance(case, dict):
            continue
        bound_case = dict(case)
        point = test_points[index] if index < len(test_points or []) else {}
        if isinstance(point, dict):
            point_id = point.get("id") or point.get("test_point_id") or ""
            if point_id and not bound_case.get("test_point_id"):
                bound_case["test_point_id"] = point_id
            for field in ("module", "feature", "scenario"):
                if point.get(field) and not bound_case.get(field):
                    bound_case[field] = point.get(field)
            risk_level = point.get("risk_level") or point.get("priority")
            if risk_level and not bound_case.get("priority"):
                bound_case["priority"] = risk_level
        bound_cases.append(bound_case)
    return bound_cases


def get_dual_writer():
    """
    创建双通道 writer，既走流通道又打印控制台
    
    Returns:
        callable: 接收消息字符串的 writer 函数
    """
    try:
        _stream_writer = get_stream_writer()
        def writer(msg):
            _stream_writer(msg)
            print(f"[Workflow]: {msg}")
    except (KeyError, RuntimeError):
        def writer(msg):
            print(f"[Workflow]: {msg}")
    return writer


# 生成测试点的工作流
class GeneratorPointWorkflow:

    def generate_initial_test_points(self, state: State2):
        """首次生成测试点"""
        writer = get_dual_writer()
        writer("【子流程节点1-首次生成测试点】：开始首次生成测试点")

        document = build_requirement_context(state)
        parser = RelaxedJsonOutputParser(pydantic_schema=List[TestPointModel])
        format_instructions = parser.get_format_instructions()

        chain = generator_test_point.prompt | llm | parser
        raw_points = invoke_with_token_usage(chain, {
            "document": document,
            "point": None,
            "additional_context": state.get("additional_context", ""),
            "format_instructions": format_instructions
        }, "test_points_generation")
        new_points = ensure_list(raw_points) # 强制转列表
        writer(f"首次生成测试点数量：{len(new_points)}个")
        return {"point": new_points, "round": 1}

    def supplement_missing_test_points(self, state: State2):
        """补充缺失的测试点（只生成缺失的部分）"""
        writer = get_dual_writer()
        missing_test_points = state.get("missing_test_points", [])

        writer(f"【子流程节点4-补充缺失测试点】：需要补充 {len(missing_test_points)} 个缺失测试点")

        if not missing_test_points:
            writer("没有缺失测试点需要补充，跳过")
            return {}

        document = build_requirement_context(state)
        parser = RelaxedJsonOutputParser(pydantic_schema=List[TestPointModel])
        format_instructions = parser.get_format_instructions()

        existing_points_list = state.get("point", [])
        existing_points_str = [p["test_point"] if isinstance(p, dict) else str(p) for p in existing_points_list]

        chain = supplement_missing_test_points.prompt | llm | parser
        raw_points = invoke_with_token_usage(chain, {
            "document": document,
            "missing_points": missing_test_points,
            "existing_points": existing_points_str,
            "additional_context": state.get("additional_context", ""),
            "format_instructions": format_instructions
        }, "test_points_supplement")
        new_points = ensure_list(raw_points) # 强制转列表
        # 修改点 2：优化去重逻辑，防止因返回格式不一致造成的报错，拦截同义重复
        existing_points = state.get("point",[])
        existing_set = {p.get("test_point", "") if isinstance(p, dict) else str(p) for p in existing_points}
        
        filtered_new =[]
        for p in new_points:
            if isinstance(p, dict):
                tp = p.get("test_point", "")
                if tp and tp not in existing_set:
                    filtered_new.append(p)
                    # 动态更新 set，避免本次生成的列表内部自身重复
                    existing_set.add(tp)

        writer(f"本轮补充生成：{len(filtered_new)}个测试点")

        writer(f"本轮补充生成：{len(filtered_new)}个测试点")

        # 更新轮次
        current_round = state.get("round", 0) + 1
        return {"point": filtered_new, "round": current_round}

    def verify_test_points_coverage(self, state: State2):
        """验证测试点的覆盖率"""
        writer = get_dual_writer()
        writer("【子流程节点2-验证测试点覆盖率】：开始验证")

        parser = RelaxedJsonOutputParser(pydantic_schema=Coverage_test_points_Result)
        format_instructions = parser.get_format_instructions()

        chain = verify_test_points_coverage.prompt | llm | parser
        points = state.get("point", [])
        points_str = [p["test_point"] for p in points]

        result = invoke_with_token_usage(chain, {
            "test_points": points_str,
            "document": build_requirement_context(state),
            "additional_context": state.get("additional_context", ""),
            "format_instructions": format_instructions
        }, "test_points_coverage")

        # 统一转换为字典，处理可能的列表情况
        result_dict = normalize_result(result)

        writer(f"覆盖率验证结果：is_covered={result_dict.get('is_covered')}, missing_count={len(result_dict.get('missing_test_points', []))}")

        return {
            "coverage_report": result_dict,
            "missing_test_points": result_dict.get("missing_test_points", [])
        }

    def route_dispatch(self, state: State2):
        """测试点路由分派"""
        writer = get_dual_writer()
        writer("【子流程节点3-路由分发】：根据测试点的覆盖情况进行路由分发")

        report = state.get("coverage_report", {})
        current_round = state.get("round", 0)
        MAX_ROUND = 4

        is_covered = get_is_covered(report)

        if is_covered is True:
            writer("测试点已全部覆盖，结束")
            return "输出所有测试点"
        if current_round >= MAX_ROUND:
            writer(f"已达到最大轮次 {MAX_ROUND}，强制结束")
            return "输出所有测试点"
        else:
            writer(f"仍有缺失测试点，进入补充流程")
            return "补充缺失测试点"

    def output_all_test_points(self, state: State2):
        """
        输出所有测试点并返回保存路径。

        功能说明:
            将子流程生成并补齐后的测试点保存为 JSON 文件，同时把文件路径写回状态，
            供外层工具提示用户进行人工修改。

        参数说明:
            state (State2): 测试点子流程状态，包含 point 测试点列表。

        返回值:
            dict: 包含 test_point 和 test_point_file，分别表示测试点列表和保存路径。

        异常说明:
            保存失败时记录错误日志并返回空路径，避免影响工作流状态返回。
        """
        writer = get_dual_writer()
        points = state.get("point", [])
        writer(f"【子流程节点5-输出测试点】：输出 {len(points)} 个测试点")
            # 保存为 JSON 文件
        file_path = ""
        try:
            # 获取项目配置（需要从 config 传入或设置默认值）
            # 如果 State2 中没有项目信息，可以设置默认目录
            base_dir = os.path.join(os.getcwd(), "output", "test_points")
            os.makedirs(base_dir, exist_ok=True)
            
            # 文件名（带时间戳）
            file_name = f"test_points_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            file_path = os.path.join(base_dir, file_name)
            
            # 写入 JSON
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(points, f, ensure_ascii=False, indent=2)
            
            writer(f"[OK] 测试点已保存到：{file_path}")
            
            # # 可选：同时也转成 Excel
            # try:
            #     df = pd.DataFrame(points)
            #     excel_path = Path(file_path).with_suffix('.xlsx')
            #     df.to_excel(excel_path, index=False, engine='openpyxl')
            #     writer(f"[OK] 测试点已转换为 Excel：{excel_path}")
            # except Exception as e:
            #     writer(f"[WARN] 测试点转 Excel 失败：{e}")
                
        except Exception as e:
            writer(f"[ERROR] 保存测试点失败：{e}")
        return {"test_point": points, "test_point_file": file_path}

    def create_workflow(self):
        workflow = StateGraph(State2)
        workflow.add_node("首次生成测试点", self.generate_initial_test_points)
        workflow.add_node("补充缺失测试点", self.supplement_missing_test_points)
        workflow.add_node("验证测试点覆盖率", self.verify_test_points_coverage)
        workflow.add_node("路由分发", self.route_dispatch)
        workflow.add_node("输出所有测试点", self.output_all_test_points)

        workflow.add_edge(START, "首次生成测试点")
        workflow.add_edge("首次生成测试点", "验证测试点覆盖率")
        workflow.add_conditional_edges(
            "验证测试点覆盖率",
            self.route_dispatch,
            {
                "输出所有测试点": "输出所有测试点",
                "补充缺失测试点": "补充缺失测试点"
            }
        )
        workflow.add_edge("补充缺失测试点", "验证测试点覆盖率")
        workflow.add_edge("输出所有测试点", END)

        graph1 = workflow.compile()
        return graph1


# 生成测试用例的工作流
class GeneratorTestCaseWorkflow:

    def _invoke_case_generation_batch(
        self,
        chain,
        payload: dict,
        batch_items: List[str],
        batch_key: str,
        writer,
        stage_name: str,
        usage_stage: str,
    ) -> tuple[list, list[str]]:
        """
        功能说明:
            调用单个用例生成批次，并在解析失败时拆成单项重试。

        参数说明:
            chain: Prompt、LLM、Parser 组合后的 LangChain Runnable。
            payload (dict): 当前节点调用 LLM 所需的基础输入。
            batch_items (List[str]): 当前批次的测试点或缺失用例方向。
            batch_key (str): payload 中承载批次内容的字段名。
            writer: 工作流流式输出函数。
            stage_name (str): 日志中显示的阶段名称。

        返回值:
            tuple[list, list[str]]: 生成成功的用例列表、最终失败的项目列表。

        异常说明:
            批次级异常会被捕获并降级为单项重试；单项仍失败时记录失败项。
        """
        try:
            response = invoke_with_token_usage(chain, {**payload, batch_key: batch_items}, usage_stage)
            return ensure_list(response), []
        except Exception as exc:
            writer(f"{stage_name}批次解析失败，拆分为单项重试：{exc}")

        generated_cases = []
        failed_items = []
        for item in batch_items:
            try:
                response = invoke_with_token_usage(chain, {**payload, batch_key: [item]}, usage_stage)
                generated_cases = merge_unique_cases(generated_cases, ensure_list(response))
            except Exception as exc:
                writer(f"{stage_name}单项生成失败，已记录跳过：{item}，原因：{exc}")
                failed_items.append(item)

        return generated_cases, failed_items

    def get_test_points(self, state: State, config: RunnableConfig):
        """
        获取测试点，优先使用外部传入的人工测试点。

        功能说明:
            当 state 已包含 test_point 时，直接使用该列表生成测试用例；
            否则保持原流程，调用测试点子工作流从需求文档自动生成测试点。

        参数说明:
            state (State): 主工作流状态，可能包含 document 或人工传入的 test_point。
            config (RunnableConfig): LangGraph 运行配置，透传给测试点子工作流。

        返回值:
            dict: {"test_point": test_points}，供后续测试用例生成节点使用。

        异常说明:
            本方法不主动捕获异常；子工作流异常按原有 LangGraph 行为向上抛出。
        """
        writer = get_dual_writer()
        manual_test_points = state.get("test_point") or []
        if manual_test_points:
            writer("【主工作流节点1-获取测试点】：检测到人工测试点，跳过测试点生成子流程")
            writer(f"获取到人工测试点数量：{len(manual_test_points)}个")
            return {"test_point": manual_test_points}

        writer("【主工作流节点1-获取测试点】：调用子工作流生成测试点")

        requirement_context = state.get("requirement_context", "")
        decomposition_report = state.get("decomposition_report", {})
        if not requirement_context:
            requirement_context, decomposition_report = prepare_requirement_context_from_document_path(
                document_path=state.get("document_path", ""),
                requirements_output_dir=state.get("requirements_output_dir", ""),
                feature_name=state.get("requirement_feature_name", ""),
                writer=writer,
            )

        graph1 = GeneratorPointWorkflow().create_workflow()
        response_state = graph1.invoke({
            "document": state.get("document"),
            "document_path": state.get("document_path", ""),
            "requirement_context": requirement_context,
            "decomposition_report": decomposition_report,
            "requirements_output_dir": state.get("requirements_output_dir", ""),
            "requirement_feature_name": state.get("requirement_feature_name", ""),
            "additional_context": state.get("additional_context", ""),
        }, config=config)

        test_points = response_state.get("point", [])
        writer(f"获取到测试点数量：{len(test_points)}个")
        return {"test_point": test_points, "decomposition_report": decomposition_report}

    def generate_initial_test_cases(self, state: State):
        """首次生成测试用例"""
        writer = get_dual_writer()
        writer("【主工作流节点2-首次生成测试用例】：基于测试点生成初始测试用例")
        # 修改点:这里应限制返回一个由多个对象组成的 List（原本传的是单一的 TestCaseModel，可能会引起大模型解析行为异常）
        parser = RelaxedJsonOutputParser(pydantic_schema=List[TestCaseModel])
        format_instructions = parser.get_format_instructions()

        test_points = state.get("test_point", [])
        case_generation_points = build_case_generation_points(test_points)

        chain = generator_testcase.prompt | llm | parser
        batch_size = get_case_generation_batch_size()
        generated_cases = []
        failed_points = []

        for batch_index, batch_points in enumerate(chunk_items(case_generation_points, batch_size), 1):
            writer(f"首次生成测试用例批次 {batch_index}，测试点数量：{len(batch_points)}")
            batch_cases, batch_failed = self._invoke_case_generation_batch(
                chain=chain,
                payload={
                    "test_cases": build_test_cases_brief(generated_cases),
                    "additional_context": state.get("additional_context", ""),
                    "format_instructions": format_instructions,
                },
                batch_items=batch_points,
                batch_key="test_point",
                writer=writer,
                stage_name="首次生成测试用例",
                usage_stage="test_cases_generation",
            )
            batch_cases = bind_cases_to_test_points(batch_cases, batch_points)
            generated_cases = merge_unique_cases(generated_cases, batch_cases)
            failed_points.extend(batch_failed)

        if failed_points:
            writer(f"首次生成测试用例仍有 {len(failed_points)} 个测试点生成失败，后续覆盖校验可继续识别缺口")

        writer(f"首次生成测试用例数量：{len(generated_cases)}个")
        return {"test_cases": generated_cases, "round": 1}

    def supplement_missing_test_cases(self, state: State):
        """补充缺失的测试用例（只生成缺失的部分）"""
        writer = get_dual_writer()
        missing_testcases = state.get("missing_testcases", [])

        writer(f"【主工作流节点5-补充缺失测试用例】：需要补充 {len(missing_testcases)} 个缺失测试用例")

        if not missing_testcases:
            writer("没有缺失测试用例需要补充，跳过")
            return {}

        parser = RelaxedJsonOutputParser(pydantic_schema=List[TestCaseModel])
        format_instructions = parser.get_format_instructions()

        # 已有的测试用例（去重用）
        existing_cases = state.get("test_cases", [])
        # 为了避免 token 过大，只传 case_name 和简要的 expected_result 供 LLM 进行语义排重
        existing_cases_brief = [
            f"用例名:{c.get('case_name')} | 预期:{c.get('expected_result')}" 
            for c in existing_cases if isinstance(c, dict)
        ]

        chain = supplement_missing_test_cases.prompt | llm | parser
        batch_size = get_case_generation_batch_size()
        filtered_new = []
        failed_missing_items = []

        for batch_index, batch_missing in enumerate(chunk_items(missing_testcases, batch_size), 1):
            writer(f"补充测试用例批次 {batch_index}，缺失方向数量：{len(batch_missing)}")
            batch_cases, batch_failed = self._invoke_case_generation_batch(
                chain=chain,
                payload={
                    "document": build_requirement_context(state),
                    "existing_cases": existing_cases_brief + [
                        f"用例名:{case.get('case_name')} | 预期:{case.get('expected_result')}"
                        for case in filtered_new if isinstance(case, dict)
                    ],
                    "additional_context": state.get("additional_context", ""),
                    "format_instructions": format_instructions,
                },
                batch_items=batch_missing,
                batch_key="missing_testcases",
                writer=writer,
                stage_name="补充测试用例",
                usage_stage="test_cases_supplement",
            )
            batch_cases = bind_cases_to_test_points(batch_cases, batch_missing)
            filtered_new = merge_unique_cases(filtered_new, batch_cases)
            failed_missing_items.extend(batch_failed)

        if failed_missing_items:
            writer(f"补充测试用例仍有 {len(failed_missing_items)} 个缺失方向生成失败，将保留给后续人工或下一轮处理")

        writer(f"本轮补充生成：{len(filtered_new)}个测试用例")

        current_round = state.get("round", 0) + 1
        return {"test_cases": filtered_new, "round": current_round}

    def verify_testcase_coverage(self, state: State):
        """验证测试用例的覆盖率"""
        writer = get_dual_writer()
        writer("【主工作流节点3-验证测试用例覆盖率】：开始验证")

        parser = RelaxedJsonOutputParser(pydantic_schema=CoverageResult)
        format_instructions = parser.get_format_instructions()

        test_points = state.get("test_point", [])
        case_generation_points = build_case_generation_points(test_points)
        brief_cases = build_test_cases_brief(state.get("test_cases", []))
        coverage_matrix = []
        unverified_points = case_generation_points

        if use_coverage_matrix():
            coverage_matrix, unverified_points = build_coverage_matrix(case_generation_points, brief_cases)
            writer(
                f"覆盖矩阵预过滤完成：已确认 {len(case_generation_points) - len(unverified_points)} 个，待模型判断 {len(unverified_points)} 个"
            )
            if not unverified_points:
                result_dict = {
                    "is_covered": True,
                    "missing_testcases": [],
                    "analysis": "覆盖矩阵已确认全部测试点存在对应用例",
                    "coverage_matrix": coverage_matrix,
                }
                writer("覆盖率验证结果：is_covered=True, missing_count=0")
                return {
                    "test_case_coverage_report": result_dict,
                    "missing_testcases": []
                }

        test_cases_for_check = (
            {
                "coverage_matrix": coverage_matrix,
                "candidate_cases": brief_cases,
                "scope": "only judge unverified_points",
            }
            if use_coverage_matrix()
            else (brief_cases if use_brief_context() else state.get("test_cases"))
        )

        chain = verify_testcase_coverage.prompt | llm | parser
        result = invoke_with_token_usage(chain, {
            "test_cases": test_cases_for_check,
            "test_point": unverified_points,
            "format_instructions": format_instructions
        }, "test_cases_coverage")

        # 统一转换为字典，处理可能的列表情况
        result_dict = normalize_result(result)

        writer(f"覆盖率验证结果：is_covered={result_dict.get('is_covered')}, missing_count={len(result_dict.get('missing_testcases', []))}")

        return {
            "test_case_coverage_report": result_dict,
            "missing_testcases": result_dict.get("missing_testcases", [])
        }

    def route_after_verification(self, state: State):
        """测试用例路由函数"""
        writer = get_dual_writer()
        writer("【主工作流节点4-路由分发】：根据测试用例覆盖率验证结果决定下一步")

        coverage_report = state.get("test_case_coverage_report", {})
        current_round = state.get("round", 0)
        MAX_ROUND = 2

        is_covered = get_is_covered(coverage_report)

        if is_covered is True:
            writer("测试用例已100%覆盖，进入保存")
            return "保存测试用例"
        if current_round >= MAX_ROUND:
            writer(f"已达到最大轮次 {MAX_ROUND}，强制结束保存")
            return "保存测试用例"
        else:
            writer(f"仍有缺失测试用例，进入补充流程")
            return "补充缺失测试用例"

    def save_test_cases(self, state: State, config: RunnableConfig):
        """保存测试用例"""
        writer = get_dual_writer()
        writer("【主工作流节点6-保存测试用例】：开始保存测试用例")
        # 👈 从 config 中获取传入的变量
        configurable = config.get("configurable", {})
        project_id = configurable.get('project_id', '未知项目') 
        module_id = configurable.get('module_id', '未知模块')

        test_cases = state.get('test_cases', [])
        writer(f"待保存测试用例数量：{len(test_cases)}个")

        # 目录
        base_dir = os.path.join(os.getcwd(), "output", project_id, module_id)
        os.makedirs(base_dir, exist_ok=True)

        # 文件名（带时间戳）
        file_name = f"testcases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = os.path.join(base_dir, file_name)

        # 写入 JSON
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(test_cases, f, ensure_ascii=False, indent=2)

        writer(f"[OK] 已保存到：{file_path}")
        # JSON 转 Excel
        try:
            # 读取 JSON 文件
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 转换为 DataFrame
            df = pd.DataFrame(data)
            
            # 生成 Excel 文件路径（同名，扩展名改为 .xlsx）
            excel_path = Path(file_path).with_suffix('.xlsx')
            
            # 保存为 Excel
            df.to_excel(excel_path, index=False, engine='openpyxl')
            
            writer(f"[OK] JSON测试用例已转换为 Excel：{excel_path}")
    
        except Exception as e:
            writer(f"[ERROR] JSON测试用例转换为 Excel 失败：{e}")

        return {}

    def create_workflow(self):
        main_workflow = StateGraph(State)
        main_workflow.add_node("获取测试点", self.get_test_points)
        main_workflow.add_node("首次生成测试用例", self.generate_initial_test_cases)
        main_workflow.add_node("补充缺失测试用例", self.supplement_missing_test_cases)
        main_workflow.add_node("验证测试用例覆盖率", self.verify_testcase_coverage)
        main_workflow.add_node("路由分发", self.route_after_verification)
        main_workflow.add_node("保存测试用例", self.save_test_cases)

        main_workflow.add_edge(START, "获取测试点")
        main_workflow.add_edge("获取测试点", "首次生成测试用例")
        main_workflow.add_edge("首次生成测试用例", "验证测试用例覆盖率")
        main_workflow.add_conditional_edges(
            "验证测试用例覆盖率",
            self.route_after_verification,
            {
                "保存测试用例": "保存测试用例",
                "补充缺失测试用例": "补充缺失测试用例"
            }
        )
        main_workflow.add_edge("补充缺失测试用例", "验证测试用例覆盖率")
        main_workflow.add_edge("保存测试用例", END)

        graph = main_workflow.compile()
        return graph

if __name__ == '__main__':
    workflow = GeneratorTestCaseWorkflow().create_workflow()
    response = workflow.stream({
        "round": 0,
        "document": """
        ### 用户注册功能概述
        #### 主流程
        1. 用户填写注册信息（用户名/邮箱、密码）。
        2. 系统校验格式与唯一性：
           - 用户名：4~20位字母数字组合，唯一性校验。
        """
    },
        subgraphs=True,
        stream_mode=['messages', "custom"],
        config={"configurable": {"thread_id": "1"}},
        context={"project_id": "1234544", "module_id": "用户模块"}
    )
    for chunk in response:
        if chunk[1] == 'custom':
            print()
            print(chunk[2])
        elif chunk[1] == 'messages':
            print(chunk[2][0].content, end="", flush=True)
