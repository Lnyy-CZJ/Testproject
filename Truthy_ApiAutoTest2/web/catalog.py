"""用例库只读清单。

功能说明:
    复用框架既有加载器（api_loader/case_loader/flow_loader）解析
    ``data/`` 目录，产出 API、Case、Flow 三类清单。单个 Flow 文件解析
    失败进入 ``errors`` 数组而不导致整体失败；apis/cases 为目录级加载，
    失败时以目录级错误条目呈现。
"""

from __future__ import annotations

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
            cases.append(
                {
                    "api": single_case["api_id"],
                    "id": single_case["case_id"],
                    "name": single_case["name"],
                    "tags": list(single_case["tags"]),
                    "status": "available",
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
            credential_profiles = sorted({
                str(definition.get("credential_profile"))
                for definition in flow_definitions.values()
                if definition.get("credential_profile") not in {None, "public"}
            })
            step_summaries: list[dict[str, Any]] = []
            for step in steps:
                api_id = step.get("api")
                if isinstance(api_id, str):
                    definition = flow_definitions.get(api_id) or {}
                    step_summaries.append(
                        {
                            "id": step.get("id"),
                            "kind": "api",
                            "api_id": api_id,
                            "name": definition.get("name") or api_id,
                        }
                    )
                    continue
                action = step.get("action")
                if isinstance(action, dict):
                    action_type = str(action.get("type") or "action")
                    step_summaries.append(
                        {
                            "id": step.get("id"),
                            "kind": "action",
                            "action_type": action_type,
                            "name": (
                                "上传二进制素材"
                                if action_type == "signed_binary_upload"
                                else action_type
                            ),
                        }
                    )
            flows.append(
                {
                    "id": flow_case["id"],
                    "name": flow_case["id"],
                    "tags": list(flow_case.get("tags", [])),
                    "step_count": len(steps),
                    "apis": sorted(flow_case.get("api_definitions", {}).keys()),
                    "steps": step_summaries,
                    "credential_profiles": credential_profiles,
                    "status": "available",
                }
            )

    return {
        "project_id": selected_project_id,
        "apis": apis,
        "cases": cases,
        "flows": flows,
        "errors": errors,
    }
