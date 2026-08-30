from __future__ import annotations

import re
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
    "platform.credential.readiness.view",
    "platform.project.manage",
    "platform.tool_access.manage",
    "platform.tool_grant.manage",
    "platform.user.create_tester",
    "project.member.manage",
    "project.tool.manage",
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
    "api-test-agent.executable.generate",
    "api-test-agent.executable.review",
    "api-test-agent.defect.create",
}

# 路由权限注册表是唯一的网关映射源。新增工具端路由必须在此登记；没有匹配项
# 返回永远不会授予用户的 deny code，避免过去用字符串片段猜测权限而误放行。
READ_ROUTE_REGISTRY: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "truthy-search": (
        (re.compile(r"^/truthy-search/(?:|health|static/.*|threshold-profiles(?:/.*)?|imports|baselines|field-schemas(?:/.*)?)$"), "tool.view"),
        (re.compile(r"^/truthy-search/(?:runs|candidates|processes|reports|downloads|evaluations|api/(?:raw|runs|processes|field-schemas))(?:/.*)?$"), "tool.result.view"),
    ),
    "api-autotest": (
        (re.compile(r"^/api-autotest/(?:|health|static/.*|catalog|projects(?:/.*)?|api/(?:catalog|credentials/status|projects(?:/.*)?))$"), "tool.view"),
        # 创建页本身不改状态，但只有具备执行权限的用户才应看到提交入口。
        (re.compile(r"^/api-autotest/tasks/new/(?:single|flow)$"), "tool.execute"),
        (re.compile(r"^/api-autotest/(?:tasks|reports|api/(?:tasks|report))(?:/.*)?$"), "tool.result.view"),
    ),
    "functional-test-agent": (
        (re.compile(r"^/functional-test-agent/(?:|health|static/.*|api/v1/readiness)$"), "tool.view"),
        (re.compile(r"^/functional-test-agent/(?:tasks|api/v1/tasks|artifacts|logs)(?:/.*)?$"), "tool.result.view"),
    ),
    "api-test-agent": (
        (re.compile(r"^/api-test-agent/(?:|health|static/.*|api/v1/readiness)$"), "tool.view"),
        (re.compile(r"^/api-test-agent/(?:tasks|api/v1/tasks|artifacts|logs)(?:/.*)?$"), "tool.result.view"),
    ),
    "trackevents": ((re.compile(r"^/trackevents/(?:|health|static/.*)$"), "tool.view"),),
    "log-filter": ((re.compile(r"^/log-filter/(?:|health|sample|static/.*)$"), "tool.view"),),
}

WRITE_ROUTE_REGISTRY: dict[str, tuple[re.Pattern[str], ...]] = {
    "truthy-search": (
        re.compile(r"^/truthy-search/(?:threshold-profiles|evaluations|runs|imports|baselines|field-schemas|processes|reports)(?:/.*)?$"),
    ),
    "api-autotest": (re.compile(r"^/api-autotest/api/tasks(?:/.*)?$"),),
    "functional-test-agent": (re.compile(r"^/functional-test-agent/api/v1/tasks(?:/.*)?$"),),
    "api-test-agent": (re.compile(r"^/api-test-agent/api/v1/tasks(?:/.*)?$"),),
    "trackevents": (re.compile(r"^/trackevents/api(?:/.*)?$"),),
    "log-filter": (
        re.compile(r"^/log-filter/(?:|people-search/analyze|export)$"),
    ),
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
    if (
        tool_id == "api-autotest"
        and method.upper() == "POST"
        and path == "/api-autotest/api/preflight"
    ):
        # 预检只读取当前授权 Scope 和测试资产，不创建任务；页面概览和提交区
        # 共用该状态模型，因此保持 tool.view，真正提交仍要求 tool.execute。
        return "tool.view"
    if tool_id == "api-test-agent":
        write_method = method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        # V2.4 的组合确认在网关先校验阶段三生成权限，Agent 再叠加校验 case.review，
        # 这样不会因为网关单权限模型而弱化基础用例 Review 的能力边界。
        if write_method and (
            path.endswith("/cases/confirm-and-generate-executable")
            or path.endswith("/executable-cases/generate")
        ):
            return "api-test-agent.executable.generate"
        if write_method and path.endswith("/executable-cases/review"):
            return "api-test-agent.executable.review"
        if write_method and path.endswith("/cases/confirm-all"):
            return "api-test-agent.case.review"
        # preview 是只读编译，不应因 HTTP POST 被提升为真实执行权限。
        if write_method and path.endswith("/execution-plans/preview"):
            return "tool.result.view"
        if write_method and path.endswith("/execution-plans"):
            return "api-test-agent.executable.review"
        if write_method and "/execution-plans/" in path and (
            path.endswith("/confirm") or path.endswith("/runs")
        ):
            return "api-test-agent.execute"
        if write_method and (path.endswith("/execute") or "/runs/" in path):
            return "api-test-agent.execute"
        if write_method and path.endswith("/contracts/review"):
            return "api-test-agent.contract.review"
        if write_method and (path.endswith("/cases/review") or path.endswith("/cases/generate")):
            return "api-test-agent.case.review"
        if write_method and "/defect-drafts" in path:
            return "api-test-agent.defect.create"
    if method.upper() == "POST" and path.endswith("/cancel"):
        return "task.cancel"
    if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if any(pattern.fullmatch(path) for pattern in WRITE_ROUTE_REGISTRY.get(tool_id, ())):
            return "tool.execute"
        return "tool.route.unregistered"

    for pattern, permission in READ_ROUTE_REGISTRY.get(tool_id, ()):
        if pattern.fullmatch(path):
            return permission
    return "tool.route.unregistered"
