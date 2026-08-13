import sys
import os
import time
import json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from langchain_core.tools import tool

from agents.functional_test.workflows.case_generator_workflow import (
    GeneratorPointWorkflow,
    GeneratorTestCaseWorkflow,
    ensure_list,
    prepare_requirement_context_from_document_path,
)

# 模块级配置变量，用于在 AgentExecutor 无法传递 config 时作为替代方案
# 调用方在调用 tool 前设置这些变量
_tool_config = {
    "project_name": "未知项目",
    "module_id": "未知模块",
    "thread_id": "default",
}


def set_tool_config(project_name: str = None, module_id: str = None, thread_id: str = None):
    """
    设置 tool 的运行时配置。

    功能说明:
        由于 AgentExecutor 不会将 config 传递给 tool，调用方需在调用前通过此函数设置配置。

    参数说明:
        project_name: 项目名称
        module_id: 模块标识
        thread_id: 线程/会话标识
    """
    if project_name is not None:
        _tool_config["project_name"] = project_name
    if module_id is not None:
        _tool_config["module_id"] = module_id
    if thread_id is not None:
        _tool_config["thread_id"] = thread_id


def _read_text_document(document_path: str = "", document: str = "") -> tuple[str, str, str]:
    """
    读取需求文档文本。

    功能说明:
        统一处理 document_path 和 document 两种输入来源，避免多个工具重复读文件逻辑。

    参数说明:
        document_path: 需求文档的本地文件路径，非空时优先读取该文件。
        document: 直接传入的需求文档内容，在 document_path 为空时使用。

    返回值:
        tuple[str, str, str]: 依次为文档内容、错误信息、解析后的绝对文档路径；
            错误信息为空表示读取成功。

    异常说明:
        文件不存在或读取异常时不抛出异常，返回错误信息供 tool 直接反馈给用户。
    """
    resolved_path = ""
    if document_path and document_path.strip():
        abs_path = os.path.abspath(document_path.strip())
        if not os.path.isfile(abs_path):
            return "", f"文档路径不存在: {abs_path}", ""
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                document = f.read()
            resolved_path = abs_path
            print(f"===============已从本地文件读取需求文档: {abs_path}，内容长度 {len(document)} 字符===============")
        except Exception as e:
            return "", f"读取文档失败: {abs_path}，原因: {e}", ""
    return document or "", "", resolved_path


def _read_test_points(test_points_path: str) -> tuple[list, str]:
    """
    读取人工修改后的测试点 JSON。

    功能说明:
        从测试点 JSON 文件读取列表，并兼容 {"test_point": [...]} 或 {"point": [...]} 包装格式。

    参数说明:
        test_points_path: 测试点 JSON 文件路径，通常来自 generator_test_points 的输出。

    返回值:
        tuple[list, str]: 第一个值为测试点列表，第二个值为错误信息；错误信息为空表示读取成功。

    异常说明:
        路径不存在、JSON 解析失败或内容为空时不抛出异常，返回错误信息供 tool 反馈。
    """
    abs_path = os.path.abspath(test_points_path.strip())
    if not os.path.isfile(abs_path):
        return [], f"测试点文件路径不存在: {abs_path}"

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return [], f"读取测试点文件失败: {abs_path}，原因: {e}"

    if isinstance(data, dict):
        data = data.get("test_point") or data.get("point") or data.get("test_points") or []

    test_points = ensure_list(data)
    if not test_points:
        return [], f"测试点文件为空或格式不正确: {abs_path}"
    return test_points, ""


@tool("generator_test_points", description="基于需求文档只生成测试点，并保存为可人工修改的 JSON 文件。")
async def generator_test_points(
    document_path: str = "",
    document: str = "",
    requirements_output_dir: str = "",
    requirement_feature_name: str = "",
    additional_context: str = "",
) -> str:
    """
    基于需求文档生成测试点文件。

    功能说明:
        只执行测试点生成子流程，不继续生成测试用例；生成结果会保存为 JSON，
        便于用户人工修改后再进入用例生成阶段。

    参数说明:
        document_path: 需求文档的本地文件路径（支持 .md / .txt 等文本文件），优先使用此参数读取文件内容。
        document: 直接传入的需求文档文本内容，当 document_path 为空时使用。
        requirements_output_dir: 可选，需求拆解产物输出目录；为空时默认 output/requirements_docs/<功能名或文档名>。
        requirement_feature_name: 可选，功能名称；用于自动生成默认拆解产物子目录名。
        additional_context: 可选，用户补充的测试设计侧重点；仅作为覆盖方向，不作为需求事实。

    返回值:
        str: 包含测试点数量和 JSON 文件路径的执行结果说明。

    异常说明:
        读取文档或工作流执行失败时返回错误信息，不向 AgentExecutor 抛出异常。
    """
    start_time = time.time()
    print(f"===============开始执行工具====generator_test_points，生成测试点===============")

    document, error, resolved_document_path = _read_text_document(
        document_path=document_path,
        document=document,
    )
    if error:
        return error
    if not document or document.strip() == "":
        return "需求文档为空，无法生成测试点。请提供 document_path（本地文件路径）或 document（文档内容）。"

    try:
        workflow = GeneratorPointWorkflow().create_workflow()
        requirement_context, decomposition_report = prepare_requirement_context_from_document_path(
            document_path=resolved_document_path,
            requirements_output_dir=requirements_output_dir,
            feature_name=requirement_feature_name,
            writer=print,
        )
        workflow_input = {
            "document": document,
            "round": 0,
            "document_path": resolved_document_path,
            "requirement_context": requirement_context,
            "decomposition_report": decomposition_report,
            "requirements_output_dir": requirements_output_dir,
            "requirement_feature_name": requirement_feature_name,
            "additional_context": additional_context,
        }
        response = await workflow.ainvoke(
            workflow_input,
            config={
                "configurable": {
                    "thread_id": _tool_config["thread_id"],
                    "project_id": _tool_config["project_name"],
                    "module_id": _tool_config["module_id"],
                }
            }
        )

        test_points = response.get("point", [])
        test_point_file = response.get("test_point_file", "")
        print(f"===============测试点生成完毕，耗时：{time.time() - start_time:.2f}秒，共 {len(test_points)} 条===============")
        return f"成功生成了 {len(test_points)} 条测试点，文件路径：{test_point_file}。请修改该 JSON 文件后，再使用 generator_case 传入 test_points_path 生成测试用例。"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"生成测试点时发生异常: {str(e)}"


@tool("generator_case", description="基于需求文档或人工测试点生成用例。可传入 document_path/document，或传入已修改的测试点 JSON 路径 test_points_path。")
async def generator_case(
    document_path: str = "",
    document: str = "",
    test_points_path: str = "",
    requirements_output_dir: str = "",
    requirement_feature_name: str = "",
    additional_context: str = "",
) -> str:
    """
    基于需求文档或人工测试点生成测试用例的服务。

    参数说明:
        document_path: 需求文档的本地文件路径（支持 .md / .txt 等文本文件），优先使用此参数读取文件内容。
        document: 直接传入的需求文档文本内容，当 document_path 为空时使用。
        test_points_path: 人工修改后的测试点 JSON 文件路径；传入后会跳过测试点生成阶段。
        requirements_output_dir: 可选，需求拆解产物输出目录；为空时默认 output/requirements_docs/<功能名或文档名>。
        requirement_feature_name: 可选，功能名称；用于自动生成默认拆解产物子目录名。
        additional_context: 可选，用户补充的测试设计侧重点；仅作为覆盖方向，不作为需求事实。
    """
    start_time = time.time()
    print(f"===============开始执行工具====generator_case，生成测试用例===============")
    # 从模块级变量读取配置（AgentExecutor 不会传递 config 给 tool）
    project_id = _tool_config["project_name"]
    module_id = _tool_config["module_id"]

    document, error, resolved_document_path = _read_text_document(
        document_path=document_path,
        document=document,
    )
    if error:
        return error

    test_points = []
    if test_points_path and test_points_path.strip():
        test_points, error = _read_test_points(test_points_path)
        if error:
            return error

    if (not document or document.strip() == "") and not test_points:
        return "需求文档和测试点均为空，无法生成测试用例。请提供 document_path/document，或提供 test_points_path。"

    try:
        workflow = GeneratorTestCaseWorkflow().create_workflow()
        workflow_input = {
            "document": document,
            "round": 0,
            "document_path": resolved_document_path,
            "requirements_output_dir": requirements_output_dir,
            "requirement_feature_name": requirement_feature_name,
            "additional_context": additional_context,
        }
        if test_points:
            workflow_input["test_point"] = test_points

        response = await workflow.ainvoke(
            workflow_input,
            config={
                "configurable": {
                    "thread_id": _tool_config["thread_id"],
                    "project_id": project_id,  # 传入真实参数
                    "module_id": module_id
                }
            }
        )

        test_cases = response.get("test_cases")
        print(f"===============用例生成完毕，耗时：{time.time() - start_time:.2f}秒，共 {len(test_cases)} 条===============")
        return f"成功生成了 {len(test_cases)} 条测试用例，并已自动保存到指定目录。"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"生成测试用例时发生异常: {str(e)}"
