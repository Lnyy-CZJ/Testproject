from __future__ import annotations

from urllib.parse import urlsplit


PLATFORM_PERMISSIONS = {
    "platform.user.manage",
    "platform.role.manage",
    "platform.audit.view",
    "platform.audit.export",
    "platform.config.manage",
    "platform.secret.manage",
}

TOOL_PERMISSIONS = {
    "tool.view",
    "tool.execute",
    "tool.result.view",
    "tool.config.manage",
    "tool.secret.manage",
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
        "trackevents": (),
        "log-filter": (),
    }
    if any(fragment in path for fragment in result_fragments.get(tool_id, ())):
        return "tool.result.view"
    return "tool.view"
