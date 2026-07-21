"""
API v1 路由总注册

注册全部 22 个 API 分组，路由前缀 /api/v1。
每个分组对应一个独立的路由文件，后续阶段逐步实现。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.routing import APIRoute

api_router = APIRouter(prefix="/api/v1")

# ── 健康检查已在 main.py 中注册 ──

from app.api.v1 import agent_memory, agents, auth, defects, fix_tasks, ops, projects, signals, sse, token_usage


def _include_compat_router(router: APIRouter) -> None:
    """
    挂载子路由并统一输出 camelCase 响应字段。

    功能说明:
        Schema 使用 snake_case alias 从 ORM 读取数据，但 Go 版前端契约使用
        Schema 的 camelCase 字段名。FastAPI 默认按 alias 序列化，因此在挂载前
        关闭该选项；请求模型的 alias 解析逻辑不受影响。

    参数说明:
        router: 待挂载的业务子路由。

    返回值:
        None: 路由被添加到全局 `/api/v1` 路由器。
    """
    for route in router.routes:
        if isinstance(route, APIRoute):
            route.response_model_by_alias = False
    api_router.include_router(router)


_include_compat_router(agents.router)
_include_compat_router(auth.router)
_include_compat_router(defects.router)
_include_compat_router(fix_tasks.router)
_include_compat_router(ops.router)
_include_compat_router(signals.router)
_include_compat_router(sse.router)
_include_compat_router(token_usage.router)
_include_compat_router(agent_memory.router)
_include_compat_router(projects.router)

# ── 其余分组路由后续阶段逐步实现 ──
# from app.api.v1 import users, repos, ai_configs
# from app.api.v1 import iterations, defects, agents, fix_tasks, workflow
# from app.api.v1 import issue_pool, integrations, rbac_audit, notifications
# from app.api.v1 import agent_memory, mcp_servers, skills, retriever
# from app.api.v1 import reports, token_usage, collaborations, credentials, sse
# api_router.include_router(repos.router)
# api_router.include_router(ai_configs.router)
# api_router.include_router(iterations.router)
# api_router.include_router(defects.router)
# api_router.include_router(agents.router)
# api_router.include_router(fix_tasks.router)
# api_router.include_router(workflow.router)
# api_router.include_router(issue_pool.router)
# api_router.include_router(integrations.router)
# api_router.include_router(rbac_audit.router)
# api_router.include_router(notifications.router)
# api_router.include_router(agent_memory.router)
# api_router.include_router(mcp_servers.router)
# api_router.include_router(skills.router)
# api_router.include_router(retriever.router)
# api_router.include_router(reports.router)
# api_router.include_router(token_usage.router)
# api_router.include_router(collaborations.router)
# api_router.include_router(credentials.router)
# api_router.include_router(sse.router)
