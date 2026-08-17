from __future__ import annotations

from urllib.parse import urlsplit


PLATFORM_PERMISSIONS = {
    "platform.user.manage",
    "platform.role.manage",
    "platform.audit.view",
    "platform.audit.export",
    "platform.config.manage",
    "platform.secret.manage",
    "platform.llm.manage",
    "platform.llm.secret.manage",
}

TOOL_PERMISSIONS = {
    "tool.view",
    "tool.execute",
    "tool.result.view",
    "tool.config.manage",
    "tool.secret.manage",
    "task.cancel",
    "task.view.all",
    "api-test-agent.execute",
    "api-test-agent.contract.review",
    "api-test-agent.case.review",
    "api-test-agent.defect.create",
}


def required_tool_permission(tool_id: str, method: str, original_uri: str) -> str:
    """
    把受控工具路径映射为稳定权限代码。

    参数说明:
        tool_id: Nginx location 固定注入的工具 ID。
        method: 浏览器原始 HTTP 方法。
        original_uri: 浏览器原始 URI，查询参数会被忽略。
    返回值:
        str: 当前请求必须具备的工具权限。
    """

    path = urlsplit(original_uri).path
    if tool_id == "api-test-agent":
        write_method = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        if write_method and (path.endswith("/execute") or "/runs/" in path):
            return "api-test-agent.execute"
        if write_method and path.endswith("/contracts/review"):
            return "api-test-agent.contract.review"
        if write_method and (path.endswith("/cases/review") or path.endswith("/cases/generate") or path.endswith("/executable-cases/generate")):
            return "api-test-agent.case.review"
        if write_method and "/defect-drafts" in path:
            return "api-test-agent.defect.create"
    if method.upper() == "POST" and path.endswith("/cancel"):
        return "task.cancel"
    if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        return "tool.execute"

    result_fragments = {
        "truthy-search": (
            "/runs/", "/candidates/", "/reports", "/downloads/", "/api/raw/",
            "/api/runs/", "/api/processes/", "/evaluations/",
        ),
        "api-autotest": (
            "/tasks/", "/api/tasks", "/reports/", "/api/report/",
        ),
        "functional-test-agent": ("/tasks/", "/api/v1/tasks", "/artifacts", "/logs"),
        "api-test-agent": ("/tasks/", "/api/v1/tasks", "/artifacts", "/logs"),
        "trackevents": (),
        "log-filter": (),
    }
    if any(fragment in path for fragment in result_fragments.get(tool_id, ())):
        return "tool.result.view"
    return "tool.view"
