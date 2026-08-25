from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError
from app.models.access import Project, ProjectMembership, PublicToolUsage, UserToolGrant
from app.models.identity import RoleGrant, User, UserRole
from app.models.tool import Tool


FIXED_PLATFORM_PERMISSIONS: dict[str, frozenset[str]] = {
    "platform_admin": frozenset(
        {
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
        }
    ),
    "admin": frozenset({
        "platform.user.create_tester",
        "project.member.manage",
        "project.tool.manage",
    }),
    "tester": frozenset(),
}

BUSINESS_TOOL_PERMISSIONS = frozenset(
    {
        "tool.view",
        "tool.execute",
        "tool.result.view",
        "task.cancel",
        "api-test-agent.execute",
        "api-test-agent.contract.review",
        "api-test-agent.case.review",
        "api-test-agent.executable.generate",
        "api-test-agent.executable.review",
        "api-test-agent.defect.create",
    }
)
TOOL_MANAGEMENT_PERMISSIONS = frozenset({"tool.config.manage", "tool.secret.manage", "task.view.all"})


@dataclass(frozen=True)
class ToolAccessDecision:
    """一次工具访问判定的稳定结果，供目录、网关和管理页面共同使用。"""

    allowed: bool
    source: str | None = None
    project_id: str | None = None
    can_manage: bool = False


def platform_permissions_for_role(role: str | None) -> frozenset[str]:
    """返回固定角色权限；未知或迁移未完成的角色默认无权限。"""

    return FIXED_PLATFORM_PERMISSIONS.get(role or "", frozenset())


def _as_utc(value: datetime) -> datetime:
    """把 SQLite 返回的无时区时间按 UTC 解释。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def public_safety_policy_complete(tool: Tool) -> bool:
    """从真实策略内容派生公共开放状态，拒绝仅设置 ``complete`` 字符串。

    配额由入口/任务派发层消费，真实执行开关和白名单由工具出口层消费；这里
    负责在缺少任一强制门禁时阻止工具进入全员可访问范围。
    """

    policy = tool.public_safety_policy if isinstance(tool.public_safety_policy, dict) else {}
    quota_keys = ("request_quota_per_minute", "task_quota_per_day", "cost_quota_daily", "cost_reservation_per_task")
    allowlist = policy.get("target_allowlist")
    return (
        tool.public_safety_policy_status == "complete"
        and all(isinstance(policy.get(key), (int, float)) and not isinstance(policy.get(key), bool) and policy[key] > 0 for key in quota_keys)
        # v1 尚未接入统一真实目标出口代理，因此只允许明确关闭真实执行的
        # 公共策略；不能靠一段 allowlist JSON 宣称门禁已执行。
        and policy.get("real_execution_enabled") is False
        and isinstance(allowlist, list)
        and bool(allowlist)
        and all(isinstance(item, str) and item.strip() for item in allowlist)
    )


def consume_public_tool_usage(
    database: Session,
    user: User,
    tool: Tool,
    *,
    kind: str,
    now: datetime | None = None,
) -> None:
    """事务内消费公共工具请求/任务/成本配额，超限稳定失败关闭。"""

    if not public_safety_policy_complete(tool):
        raise PlatformError(429, "PUBLIC_TOOL_POLICY_UNAVAILABLE", "公共工具安全策略不可用")
    instant = now or datetime.now(UTC)
    usage_date = instant.date().isoformat()
    row = database.scalar(select(PublicToolUsage).where(
        PublicToolUsage.usage_date == usage_date,
        PublicToolUsage.user_id == user.id,
        PublicToolUsage.tool_id == tool.id,
    ).with_for_update())
    if row is None:
        row = PublicToolUsage(
            usage_date=usage_date, user_id=user.id, tool_id=tool.id,
            request_window_started_at=instant, request_count=0, task_count=0,
            reserved_cost=0.0,
        )
        database.add(row)
        database.flush()
    policy = tool.public_safety_policy
    window_start = _as_utc(row.request_window_started_at)
    if instant - window_start >= timedelta(minutes=1):
        row.request_window_started_at = instant
        row.request_count = 0
    if kind == "request":
        if row.request_count >= int(policy["request_quota_per_minute"]):
            raise PlatformError(429, "PUBLIC_REQUEST_QUOTA_EXCEEDED", "公共工具请求配额已用尽")
        row.request_count += 1
        return
    if kind != "task":
        raise ValueError("未知公共工具用量类型")
    reservation = float(policy["cost_reservation_per_task"])
    if row.task_count >= int(policy["task_quota_per_day"]):
        raise PlatformError(429, "PUBLIC_TASK_QUOTA_EXCEEDED", "公共工具任务配额已用尽")
    if row.reserved_cost + reservation > float(policy["cost_quota_daily"]):
        raise PlatformError(429, "PUBLIC_COST_QUOTA_EXCEEDED", "公共工具成本配额已用尽")
    row.task_count += 1
    row.reserved_cost += reservation


def decide_tool_access(database: Session, user: User, tool: Tool, *, now: datetime | None = None) -> ToolAccessDecision:
    """按固定顺序计算工具使用来源，额外授权永不产生控制面管理能力。"""

    if user.status != "active" or not tool.is_enabled:
        return ToolAccessDecision(False)
    if user.platform_role == "platform_admin":
        return ToolAccessDecision(True, "platform_admin", tool.project_id, True)
    if tool.access_scope == "public":
        # 公共范围会自动影响全部 active 用户，安全策略未完成时必须失败关闭。
        if not public_safety_policy_complete(tool):
            return ToolAccessDecision(False)
        return ToolAccessDecision(True, "public", None, False)
    if tool.access_scope != "project" or not tool.project_id:
        return ToolAccessDecision(False)
    project = database.get(Project, tool.project_id)
    if project is None or project.status != "active":
        return ToolAccessDecision(False)
    membership = database.get(ProjectMembership, (project.id, user.id))
    if membership is not None:
        if membership.relation == "manager" and user.platform_role == "admin":
            return ToolAccessDecision(True, "project_manager", project.id, True)
        if membership.relation == "member" and user.platform_role == "tester":
            return ToolAccessDecision(True, "project_member", project.id, False)
    instant = now or datetime.now(UTC)
    grant = database.scalar(
        select(UserToolGrant).where(
            UserToolGrant.user_id == user.id,
            UserToolGrant.tool_id == tool.id,
            UserToolGrant.project_id == project.id,
            UserToolGrant.status == "active",
        ).order_by(UserToolGrant.expires_at.desc())
    )
    if grant is not None and _as_utc(grant.expires_at) > instant:
        return ToolAccessDecision(True, "extra_grant", project.id, False)
    return ToolAccessDecision(False)


def decide_tool_access_batch(
    database: Session,
    user: User,
    tools: Sequence[Tool],
    *,
    now: datetime | None = None,
) -> dict[str, ToolAccessDecision]:
    """用固定数量查询批量计算目录权限，避免 `/tools` 随工具数产生 N+1。

    单工具入口仍复用 ``decide_tool_access``；目录场景预取项目、当前用户关系和
    有效额外授权，再按同一优先级生成可解释来源。
    """

    result: dict[str, ToolAccessDecision] = {}
    if user.status != "active":
        return {tool.id: ToolAccessDecision(False) for tool in tools}
    if user.platform_role == "platform_admin":
        return {
            tool.id: ToolAccessDecision(
                tool.is_enabled,
                "platform_admin" if tool.is_enabled else None,
                tool.project_id,
                tool.is_enabled,
            )
            for tool in tools
        }

    project_ids = {tool.project_id for tool in tools if tool.project_id}
    projects = {
        row.id: row
        for row in database.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    } if project_ids else {}
    memberships = {
        row.project_id: row
        for row in database.scalars(select(ProjectMembership).where(
            ProjectMembership.user_id == user.id,
            ProjectMembership.project_id.in_(project_ids),
        )).all()
    } if project_ids else {}
    tool_ids = [tool.id for tool in tools]
    grants_by_tool: dict[str, UserToolGrant] = {}
    if tool_ids:
        for grant in database.scalars(select(UserToolGrant).where(
            UserToolGrant.user_id == user.id,
            UserToolGrant.tool_id.in_(tool_ids),
            UserToolGrant.status == "active",
        ).order_by(UserToolGrant.expires_at.desc())).all():
            grants_by_tool.setdefault(grant.tool_id, grant)

    instant = now or datetime.now(UTC)
    for tool in tools:
        decision = ToolAccessDecision(False)
        if not tool.is_enabled:
            result[tool.id] = decision
            continue
        if tool.access_scope == "public":
            if public_safety_policy_complete(tool):
                decision = ToolAccessDecision(True, "public", None, False)
            result[tool.id] = decision
            continue
        project = projects.get(tool.project_id or "")
        if project is None or project.status != "active":
            result[tool.id] = decision
            continue
        membership = memberships.get(project.id)
        if membership is not None:
            if membership.relation == "manager" and user.platform_role == "admin":
                decision = ToolAccessDecision(True, "project_manager", project.id, True)
            elif membership.relation == "member" and user.platform_role == "tester":
                decision = ToolAccessDecision(True, "project_member", project.id, False)
        if not decision.allowed:
            grant = grants_by_tool.get(tool.id)
            if (
                grant is not None
                and grant.project_id == project.id
                and _as_utc(grant.expires_at) > instant
            ):
                decision = ToolAccessDecision(True, "extra_grant", project.id, False)
        result[tool.id] = decision
    return result


def user_grants(database: Session, user_id: str) -> list[RoleGrant]:
    """读取用户所有角色授权项，调用方据此计算平台和工具权限。"""

    statement = (
        select(RoleGrant)
        .join(UserRole, UserRole.role_id == RoleGrant.role_id)
        .where(UserRole.user_id == user_id)
    )
    return list(database.scalars(statement).all())


def has_platform_permission(database: Session, user_id: str, code: str) -> bool:
    """判断用户是否具有指定平台权限。"""

    user = database.get(User, user_id)
    if user is not None and user.platform_role is not None:
        return code in platform_permissions_for_role(user.platform_role)
    return any(
        grant.permission_code == code
        and grant.resource_type == "platform"
        and grant.resource_id == "*"
        for grant in user_grants(database, user_id)
    )


def tool_permissions(database: Session, user_id: str, tool_id: str) -> set[str]:
    """返回用户在指定工具上的权限代码集合。"""

    user = database.get(User, user_id)
    tool = database.get(Tool, tool_id)
    if user is not None and user.platform_role is not None:
        if tool is None:
            return set()
        decision = decide_tool_access(database, user, tool)
        if not decision.allowed:
            return set()
        permissions = set(BUSINESS_TOOL_PERMISSIONS)
        if decision.can_manage:
            permissions.update(TOOL_MANAGEMENT_PERMISSIONS)
        return permissions
    return {
        grant.permission_code
        for grant in user_grants(database, user_id)
        if grant.resource_type == "tool" and grant.resource_id in {tool_id, "*"}
    }


def has_tool_permission(database: Session, user_id: str, code: str, tool_id: str) -> bool:
    """判断用户是否具有指定工具权限。"""

    return code in tool_permissions(database, user_id, tool_id)
