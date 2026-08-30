"""用例库只读清单。

功能说明:
    复用框架既有加载器（api_loader/case_loader/flow_loader）解析
    ``data/`` 目录，产出 API、Case、Flow 三类清单。单个 Flow 文件解析
    失败进入 ``errors`` 数组而不导致整体失败；apis/cases 为目录级加载，
    失败时以目录级错误条目呈现。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from utils.custom.api_loader import ApiConfigError, load_api_definitions
from utils.custom.case_loader import CaseConfigError, load_single_cases
from utils.custom.flow_loader import FlowConfigError, load_flow_cases
from utils.custom.project_registry import (
    ProjectNotFoundError,
    ProjectRegistry,
    ProjectRegistryError,
)
from utils.custom.runtime_overrides import (
    build_case_asset_snapshot,
    build_flow_asset_snapshot,
    public_asset_contract,
)


def _foreach_input_name(items: Any) -> str | None:
    """把受 Flow Loader 校验过的 ``{{variable}}`` 表达式转成展示名。"""

    expression = str(items or "").strip()
    if expression.startswith("{{") and expression.endswith("}}"):
        name = expression[2:-2].strip()
        return name or None
    return None


def _summarize_flow_steps(
    steps: list[dict[str, Any]],
    definitions: dict[str, dict[str, Any]],
    *,
    parent_id: str | None = None,
    repeat_for: str | None = None,
) -> list[dict[str, Any]]:
    """递归展开 Flow 的业务步骤，foreach 容器本身不重复计数。

    foreach 只是控制结构，真正可执行的是内部 API/Action。目录和任务详情
    都按“步骤定义”统计一次，并通过 ``parent_id``/``repeat_for`` 告知界面
    这些步骤会按图片顺序重复，避免上传 9 张图时错误显示成 27 个固定步骤。
    """

    summaries: list[dict[str, Any]] = []
    for step in steps:
        step_id = str(step.get("id") or "")
        foreach = step.get("foreach")
        if isinstance(foreach, dict):
            nested = foreach.get("steps")
            if isinstance(nested, list):
                summaries.extend(
                    _summarize_flow_steps(
                        nested,
                        definitions,
                        parent_id=step_id or None,
                        repeat_for=_foreach_input_name(foreach.get("items")),
                    )
                )
            continue

        summary: dict[str, Any] | None = None
        api_id = step.get("api")
        if isinstance(api_id, str):
            definition = definitions.get(api_id) or {}
            summary = {
                "id": step.get("id"),
                "kind": "api",
                "api_id": api_id,
                "name": definition.get("name") or api_id,
            }
        else:
            action = step.get("action")
            if isinstance(action, dict):
                action_type = str(action.get("type") or "action")
                action_names = {
                    "signed_binary_upload": "上传二进制素材",
                    "validate_binary_inputs": "校验输入图片",
                }
                summary = {
                    "id": step.get("id"),
                    "kind": "action",
                    "action_type": action_type,
                    "name": action_names.get(action_type, action_type),
                }
        if summary is None:
            continue
        if parent_id is not None:
            summary["parent_id"] = parent_id
        if repeat_for is not None:
            summary["repeat_for"] = repeat_for
        summaries.append(summary)
    return summaries


def build_catalog(
    project_root: Path,
    project_id: str | None = None,
) -> dict[str, Any]:
    """解析指定项目包的 ``data/`` 目录生成只读用例库快照。

    参数说明:
        project_root: 自动化仓库根目录；兼容测试可直接传旧版单项目根目录。
        project_id: 工具项目 ID。显式传入时只读取
            ``projects/<project_id>``；不允许把多个项目目录合并扫描。

    返回值:
        ``{"apis": [...], "cases": [...], "flows": [...], "errors": [...]}``：
        apis 含 id/name/service_name/method_name；cases 含 api/id/name/tags；
        flows 含 name/tags/step_count/apis；errors 含 file/message。
    """
    project_root = Path(project_root)
    selected_project_id = project_id
    asset_root = project_root
    projects_root = project_root / "projects"
    if project_id is not None or projects_root.is_dir():
        selected_project_id = project_id or "truthy"
        try:
            asset_root = ProjectRegistry(projects_root).get(selected_project_id).root
        except (ProjectNotFoundError, ProjectRegistryError) as exc:
            return {
                "project_id": selected_project_id,
                "apis": [],
                "cases": [],
                "flows": [],
                "errors": [{"file": "project.yaml", "message": str(exc)}],
            }
    errors: list[dict[str, str]] = []
    apis: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []

    try:
        definitions = load_api_definitions(asset_root)
    except ApiConfigError as exc:
        errors.append({"file": "data/apis/", "message": str(exc)})
        definitions = {}
    for api_id, definition in definitions.items():
        request = definition.get("request", {})
        apis.append(
            {
                "id": api_id,
                "name": definition.get("name", ""),
                "service_name": request.get("service_name", ""),
                "method_name": request.get("method_name", ""),
                "credential_profile": definition.get("credential_profile"),
                "status": "available",
            }
        )

    try:
        for single_case in load_single_cases(asset_root):
            asset_contract = public_asset_contract(
                build_case_asset_snapshot(
                    str(selected_project_id or "truthy"),
                    single_case,
                    definitions,
                )
            )
            case_tags = [str(tag) for tag in single_case["tags"]]
            cases.append(
                {
                    "api": single_case["api_id"],
                    "id": single_case["case_id"],
                    "name": single_case["name"],
                    "tags": case_tags,
                    "status": "available",
                    "batch_eligible": True,
                    "risk_tags": [
                        tag
                        for tag in case_tags
                        if tag in {"explicit", "destructive", "interactive"}
                    ],
                    **asset_contract,
                }
            )
    except (ApiConfigError, CaseConfigError) as exc:
        errors.append({"file": "data/cases/", "message": str(exc)})

    # Flow 逐个解析，使单个坏文件只影响自身错误条目。
    flows_directory = asset_root / "data" / "flows"
    for flow_path in sorted(flows_directory.glob("*.yaml")):
        try:
            flow_cases = load_flow_cases(asset_root, selected_flow=flow_path.stem)
        except (ApiConfigError, FlowConfigError, ValueError) as exc:
            errors.append(
                {"file": f"data/flows/{flow_path.name}", "message": str(exc)}
            )
            continue
        for flow_case in flow_cases:
            flow_body = flow_case.get("flow", {})
            steps = flow_body.get("steps") or []
            flow_definitions = flow_case.get("api_definitions", {})
            flow_tags = [str(tag) for tag in flow_case.get("tags", [])]
            # isolated Flow 会在任务上下文中清空共享 Token、派生任务级
            # device_id，并以 CreateAnonymousSession 建立一次性会话。因此它
            # 实际不消费平台 anonymous_session；若仍把步骤 API Profile 并集
            # 暴露给预检，未配置共享凭证时会在执行前被错误拦截。
            credential_profiles = [] if "isolated" in flow_tags else sorted({
                str(definition.get("credential_profile"))
                for definition in flow_definitions.values()
                if definition.get("credential_profile") not in {None, "public"}
            })
            step_summaries = _summarize_flow_steps(steps, flow_definitions)
            asset_contract = public_asset_contract(
                build_flow_asset_snapshot(
                    str(selected_project_id or "truthy"),
                    flow_case,
                    definitions,
                )
            )
            flows.append(
                {
                    "id": flow_case["id"],
                    # ``name`` 历史上就是稳定 Flow ID，已有 API 调用方会据此
                    # 过滤；可读标题单独放在 display_name，避免 UI 改进破坏契约。
                    "name": flow_case["id"],
                    "display_name": flow_body.get("name") or flow_case["id"],
                    "tags": flow_tags,
                    "step_count": len(step_summaries),
                    "apis": sorted(flow_case.get("api_definitions", {}).keys()),
                    "steps": step_summaries,
                    # 只返回经过 Flow Loader 白名单校验的静态约束；图片内容、
                    # 路径与任何运行配置都不会进入 Catalog 响应。
                    "inputs": deepcopy(flow_body.get("inputs") or {}),
                    "credential_profiles": credential_profiles,
                    "status": "available",
                    "batch_eligible": True,
                    "risk_tags": [
                        tag
                        for tag in flow_tags
                        if tag in {"explicit", "destructive", "interactive"}
                    ],
                    **asset_contract,
                }
            )

    return {
        "project_id": selected_project_id,
        "apis": apis,
        "cases": cases,
        "flows": flows,
        "errors": errors,
    }
