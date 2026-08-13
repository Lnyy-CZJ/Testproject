"""功能测试智能体任务子进程入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
import warnings
from pathlib import Path

from services.common.errors import classify_runner_exception
from services.common.task_store import TaskStore


def _write_result(path: Path, payload: dict) -> None:
    """原子保存 Runner 结果，终态仍由 TaskManager 提交。"""

    TaskStore.atomic_write_json(path, payload)


def _configure_dependency_warnings() -> None:
    """只过滤 LangGraph 当前已确认无行为影响的序列化默认值告警。

    异常策略:
        依赖版本不再暴露该告警类型时忽略 ImportError；其他 Warning 不过滤，
        保证真正的运行问题仍出现在任务日志中。
    """

    try:
        from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
    except ImportError:
        return
    warnings.filterwarnings(
        "ignore",
        message=r"The default value of `allowed_objects` will change.*",
        category=LangChainPendingDeprecationWarning,
    )


def _require_decomposition_success(result) -> None:
    """拒绝把 `success=false` 的需求拆解结果提交为成功任务。"""

    if bool(getattr(result, "success", False)):
        return
    errors = list(getattr(result, "errors", []) or [])
    summary = "；".join(str(item) for item in errors[:3]) or "未返回成功结果"
    raise RuntimeError(f"需求拆解失败：{summary}")


async def _run(task_id: str) -> dict:
    """根据服务端 request.json 执行一个明确的功能操作。"""

    store = TaskStore(Path(os.environ["AGENT_DATA_DIR"]))
    task_dir = store.task_dir(task_id)
    request_payload = json.loads((task_dir / "request.json").read_text(encoding="utf-8"))
    execution_path = task_dir / "execution.json"
    execution = json.loads(execution_path.read_text(encoding="utf-8")) if execution_path.exists() else {"kind": "initial", "sequence": 0}
    work_dir = task_dir / "work"
    work_dir.mkdir(exist_ok=True)
    os.chdir(work_dir)

    # 必须在任务环境变量、cwd 和精准告警过滤就绪后再导入依赖。
    _configure_dependency_warnings()
    if execution.get("kind") == "review_ai":
        from services.functional_agent.review_ai import run_review_ai

        metadata = run_review_ai(store, task_id, int(execution["review_ai_request_version"]), max_context=int(os.getenv("REVIEW_AI_MAX_CONTEXT_POINTS", "500")), max_suggestions=int(os.getenv("REVIEW_AI_MAX_SUGGESTIONS", "200")))
        return {"execution_kind": "review_ai", "execution_sequence": execution["sequence"], "next_status": "waiting_review", "stage": "review_ai_ready", "review_ai": metadata}
    if execution.get("kind") == "case_review_ai":
        from services.functional_agent.case_review_ai import run_case_review_ai

        metadata = run_case_review_ai(
            store, task_id, int(execution["case_review_ai_request_version"]),
            max_context_cases=int(os.getenv("CASE_REVIEW_AI_MAX_CONTEXT_CASES", "300")),
            max_context_points=int(os.getenv("CASE_REVIEW_AI_MAX_CONTEXT_POINTS", "300")),
            max_suggestions=int(os.getenv("CASE_REVIEW_AI_MAX_SUGGESTIONS", "100")),
        )
        return {"execution_kind": "case_review_ai", "execution_sequence": execution["sequence"], "next_status": "waiting_case_review", "stage": "case_review_ai_ready", "case_review_ai": metadata}
    from agents.common.tools.tools import generator_case, generator_test_points, set_tool_config
    from requirement_decomposition.pipeline import run_decomposition

    set_tool_config(
        project_name=request_payload["project_id"],
        module_id=request_payload["module_id"],
        thread_id=task_id,
    )
    source = task_dir / request_payload["input_relative_path"]
    requirements_dir = work_dir / "output" / "requirements_docs" / request_payload.get("feature_slug", "feature")
    operation = request_payload["operation"]
    resumed = bool(request_payload.get("review_relative_path")) or request_payload.get("input_kind") == "test_points"
    additional_context = str((request_payload.get("additional_info") or {}).get("context", "")).strip()

    if operation == "decompose_requirement":
        config_path = Path(__file__).resolve().parents[2] / "requirement_decomposition.yaml"
        result = run_decomposition(source_path=str(source), config_path=str(config_path), output_dir=str(requirements_dir))
        _require_decomposition_success(result)
        return {"execution_kind": execution.get("kind", "initial"), "execution_sequence": execution.get("sequence", 0), "next_status": "succeeded", "stage": "completed", "operation": operation}

    if operation in {"generate_test_points", "full_pipeline"} and not resumed:
        message = await generator_test_points.ainvoke({
            "document_path": str(source),
            "requirements_output_dir": str(requirements_dir),
            "requirement_feature_name": request_payload.get("feature_name", ""),
            "additional_context": additional_context,
        })
        if not list((work_dir / "output" / "test_points").glob("*.json")):
            raise RuntimeError(f"测试点产物缺失: {message}")
        return {"execution_kind": execution.get("kind", "initial"), "execution_sequence": execution.get("sequence", 0), "next_status": "waiting_review", "stage": "waiting_for_review", "operation": operation}

    review_relative = request_payload.get("review_relative_path") or (request_payload.get("input_relative_path") if request_payload.get("input_kind") == "test_points" else None)
    review_path = task_dir / review_relative if review_relative else None
    invoke_payload = {
        "document_path": str(source) if not review_path else "",
        "test_points_path": str(review_path) if review_path else "",
        "requirements_output_dir": str(requirements_dir),
        "requirement_feature_name": request_payload.get("feature_name", ""),
        "additional_context": additional_context,
    }
    message = await generator_case.ainvoke(invoke_payload)
    case_dir = work_dir / "output" / request_payload["project_id"] / request_payload["module_id"]
    if not list(case_dir.glob("*.json")):
        raise RuntimeError(f"测试用例产物缺失: {message}")
    online_case_review = os.getenv("ONLINE_CASE_REVIEW_ENABLED", "false").strip().lower() == "true"
    return {"execution_kind": execution.get("kind", "initial"), "execution_sequence": execution.get("sequence", 0), "next_status": "waiting_case_review" if online_case_review else "succeeded", "stage": "case_review_editing" if online_case_review else "completed", "operation": operation}


def main() -> int:
    """解析任务 ID、执行工作流并返回可由 TaskManager 判断的退出码。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    store = TaskStore(Path(os.environ["AGENT_DATA_DIR"]))
    result_path = store.task_dir(args.task_id) / "runner-result.json"
    try:
        result = asyncio.run(_run(args.task_id))
        _write_result(result_path, result)
        return 0
    except Exception as exc:
        # 完整堆栈仅写任务日志；HTTP 日志接口会二次脱敏并隐藏堆栈。
        traceback.print_exc()
        error_code, error_message = classify_runner_exception(
            exc,
            default_code="WORKFLOW_FAILED",
            default_message="功能测试工作流执行失败",
        )
        execution_path = store.task_dir(args.task_id) / "execution.json"
        execution = json.loads(execution_path.read_text(encoding="utf-8")) if execution_path.exists() else {"kind": "initial", "sequence": 0}
        _write_result(result_path, {
            "execution_kind": execution.get("kind", "initial"),
            "execution_sequence": execution.get("sequence", 0),
            "error_code": error_code,
            "error_message": error_message,
            "stage": "workflow",
            "exception_type": type(exc).__name__,
        })
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
