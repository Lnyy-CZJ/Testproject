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


def build_catalog(project_root: Path) -> dict[str, Any]:
    """解析当前 ``data/`` 目录生成用例库快照。

    参数说明:
        project_root: 项目根目录。

    返回值:
        ``{"apis": [...], "cases": [...], "flows": [...], "errors": [...]}``：
        apis 含 id/name/service_name/method_name；cases 含 api/id/name/tags；
        flows 含 name/tags/step_count/apis；errors 含 file/message。
    """
    project_root = Path(project_root)
    errors: list[dict[str, str]] = []
    apis: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []

    try:
        definitions = load_api_definitions(project_root)
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
            }
        )

    try:
        for single_case in load_single_cases(project_root):
            cases.append(
                {
                    "api": single_case["api_id"],
                    "id": single_case["case_id"],
                    "name": single_case["name"],
                    "tags": list(single_case["tags"]),
                }
            )
    except (ApiConfigError, CaseConfigError) as exc:
        errors.append({"file": "data/cases/", "message": str(exc)})

    # Flow 逐个解析，使单个坏文件只影响自身错误条目。
    flows_directory = project_root / "data" / "flows"
    for flow_path in sorted(flows_directory.glob("*.yaml")):
        try:
            flow_cases = load_flow_cases(project_root, selected_flow=flow_path.stem)
        except (ApiConfigError, FlowConfigError, ValueError) as exc:
            errors.append(
                {"file": f"data/flows/{flow_path.name}", "message": str(exc)}
            )
            continue
        for flow_case in flow_cases:
            flow_body = flow_case.get("flow", {})
            steps = flow_body.get("steps") or []
            flows.append(
                {
                    "name": flow_case["id"],
                    "tags": list(flow_case.get("tags", [])),
                    "step_count": len(steps),
                    "apis": sorted(flow_case.get("api_definitions", {}).keys()),
                }
            )

    return {"apis": apis, "cases": cases, "flows": flows, "errors": errors}
