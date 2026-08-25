from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform
from app.core.errors import PlatformError
from app.core.security import new_id, token_hash
from app.db.session import get_db
from app.models.access import BusinessResourceSnapshot, Project, ProjectMembership, UserToolGrant
from app.models.identity import User
from app.models.tool import Tool
from app.schemas.access import ToolAccessChangeRequest, ToolAccessResponse, ToolGrantCreateRequest, ToolGrantRenewRequest, ToolGrantResponse, ToolGrantRevokeRequest, ToolImpactPreviewRequest, ToolImpactPreviewResponse
from app.services.audit import add_audit_event
from app.services.authorization import public_safety_policy_complete


router = APIRouter(prefix="/admin", tags=["access-admin"])

# V1.1 只有完全本地处理、不会访问外部目标的日志导出工具具备公共资格。其余
# 第一方 Agent 在统一沙箱/出口策略接入前必须保持项目工具，避免 UI 声称可执行
# 而网关在任务创建阶段失败关闭的产品契约分裂。
PUBLIC_ELIGIBLE_TOOL_IDS = frozenset({"log-filter"})


def _tool_response(database: Session, tool: Tool) -> ToolAccessResponse:
    project = database.get(Project, tool.project_id) if tool.project_id else None
    return ToolAccessResponse(
        id=tool.id, name=tool.name, description=tool.description,
        is_enabled=tool.is_enabled, access_scope=tool.access_scope,
        project_id=tool.project_id, project_name=project.name if project else None,
        revision=tool.revision, authorization_epoch=tool.authorization_epoch,
        public_safety_policy_status="complete" if public_safety_policy_complete(tool) else "missing",
        public_policy_complete=public_safety_policy_complete(tool),
        public_eligible=tool.id in PUBLIC_ELIGIBLE_TOOL_IDS,
        updated_at=tool.updated_at,
    )


def _grant_response(database: Session, grant: UserToolGrant) -> ToolGrantResponse:
    """补齐授权列表所需名称，不向前端暴露内部关系对象。"""

    user = database.get(User, grant.user_id)
    tool = database.get(Tool, grant.tool_id)
    project = database.get(Project, grant.project_id)
    return ToolGrantResponse(
        id=grant.id,
        user_id=grant.user_id,
        username=user.username if user else None,
        tool_id=grant.tool_id,
        tool_name=tool.name if tool else None,
        project_id=grant.project_id,
        project_name=project.name if project else None,
        status=grant.status,
        grant_reason=grant.grant_reason,
        expires_at=grant.expires_at,
        granted_at=grant.created_at,
        revoked_at=grant.revoked_at,
        revoke_reason=grant.revoke_reason,
    )


def _impact_token(tool: Tool, scope: str, project_id: str | None, expires_at: datetime) -> str:
    """生成可自包含校验的影响确认令牌。

    到期秒数作为令牌前缀返回，但摘要仍由服务端密钥保护。提交接口因此可以
    校验预览时的原始到期点，避免用“当前时间加五分钟”重算导致令牌永远不匹配。
    """

    expires_timestamp = int(expires_at.timestamp())
    digest = token_hash(
        f"{tool.id}:{tool.revision}:{scope}:{project_id or ''}:{expires_timestamp}"
    )
    return f"{expires_timestamp}.{digest}"


def _impact_token_is_valid(
    tool: Tool,
    scope: str,
    project_id: str | None,
    token: str,
    now: datetime,
) -> bool:
    """校验令牌内容、目标范围、revision 与五分钟有效期。"""

    try:
        expires_timestamp = int(token.split(".", 1)[0])
    except (TypeError, ValueError):
        return False
    if expires_timestamp < int(now.timestamp()):
        return False
    # 即使签名合法，也拒绝异常遥远的到期时间，限制重放窗口。
    if expires_timestamp > int(now.timestamp()) + 5 * 60 + 5:
        return False
    expires_at = datetime.fromtimestamp(expires_timestamp, UTC)
    return _impact_token(tool, scope, project_id, expires_at) == token


@router.get("/tool-access", response_model=list[ToolAccessResponse])
def list_tool_access(_: Annotated[AuthContext, Depends(require_platform("platform.tool_access.manage"))], database: Annotated[Session, Depends(get_db)]) -> list[ToolAccessResponse]:
    return [_tool_response(database, row) for row in database.scalars(select(Tool).order_by(Tool.sort_order, Tool.name)).all()]


@router.get("/tool-access/{tool_id}", response_model=ToolAccessResponse)
def get_tool_access(tool_id: str, _: Annotated[AuthContext, Depends(require_platform("platform.tool_access.manage"))], database: Annotated[Session, Depends(get_db)]) -> ToolAccessResponse:
    tool = database.get(Tool, tool_id)
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    return _tool_response(database, tool)


@router.post("/tool-access/{tool_id}/impact", response_model=ToolImpactPreviewResponse)
def preview_tool_impact(tool_id: str, payload: ToolImpactPreviewRequest, _: Annotated[AuthContext, Depends(require_platform("platform.tool_access.manage"))], database: Annotated[Session, Depends(get_db)]) -> ToolImpactPreviewResponse:
    tool = database.get(Tool, tool_id)
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if payload.access_scope == "project" and not payload.project_id:
        raise PlatformError(422, "PROJECT_REQUIRED", "项目工具必须指定所属项目")
    if payload.access_scope == "public" and payload.project_id:
        raise PlatformError(422, "PROJECT_NOT_ALLOWED", "公共工具不能指定所属项目")
    if payload.access_scope == "public" and tool.id not in PUBLIC_ELIGIBLE_TOOL_IDS:
        raise PlatformError(
            409, "PUBLIC_SANDBOX_UNAVAILABLE",
            "该工具尚未接入公共沙箱与统一出口，只能设为项目工具",
        )
    if payload.access_scope == "public" and not public_safety_policy_complete(tool):
        raise PlatformError(
            409,
            "PUBLIC_SAFETY_POLICY_INCOMPLETE",
            "公共工具安全策略未完整配置，不能开放给全体用户",
        )
    expires_at = datetime.now(UTC) + timedelta(minutes=5)
    member_count = 0
    if payload.project_id:
        member_count = database.scalar(select(func.count()).select_from(ProjectMembership).where(ProjectMembership.project_id == payload.project_id)) or 0
    grant_count = database.scalar(select(func.count()).select_from(UserToolGrant).where(UserToolGrant.tool_id == tool.id, UserToolGrant.status == "active")) or 0
    history_count = database.scalar(select(func.count()).select_from(BusinessResourceSnapshot).where(BusinessResourceSnapshot.tool_id == tool.id)) or 0
    return ToolImpactPreviewResponse(
        revision=tool.revision, expected_revision=tool.revision,
        impact_token=_impact_token(tool, payload.access_scope, payload.project_id, expires_at), expires_at=expires_at,
        current_access_scope=tool.access_scope, next_access_scope=payload.access_scope,
        current_project_id=tool.project_id, next_project_id=payload.project_id,
        affected_user_count=member_count, extra_grant_count=grant_count,
        historical_resource_count=history_count, running_task_count="unknown",
    )


@router.patch("/tool-access/{tool_id}", response_model=ToolAccessResponse)
def change_tool_access(tool_id: str, payload: ToolAccessChangeRequest, request: Request, context: Annotated[AuthContext, Depends(require_platform("platform.tool_access.manage", csrf=True))], database: Annotated[Session, Depends(get_db)]) -> ToolAccessResponse:
    # 影响预览只能被消费一次：先锁定工具行，再在锁内重读 revision 和令牌。
    # PostgreSQL 下并发提交会串行化，后到请求将看到已递增的 revision 并返回 409。
    tool = database.scalar(select(Tool).where(Tool.id == tool_id).with_for_update())
    if tool is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if tool.revision != payload.revision:
        raise PlatformError(409, "STALE_IMPACT", "影响预览已过期，请重新计算")
    now = datetime.now(UTC)
    if not _impact_token_is_valid(
        tool,
        payload.access_scope,
        payload.project_id,
        payload.impact_token,
        now,
    ):
        raise PlatformError(409, "STALE_IMPACT", "影响预览已过期，请重新计算")
    if not payload.force_unknown_impact:
        raise PlatformError(
            409,
            "RUNNING_TASK_IMPACT_UNKNOWN",
            "运行任务数量未知，默认禁止变更工具范围",
        )
    if payload.access_scope == "project" and (not payload.project_id or database.get(Project, payload.project_id) is None):
        raise PlatformError(422, "PROJECT_REQUIRED", "项目工具必须指定有效项目")
    if payload.access_scope == "public" and tool.id not in PUBLIC_ELIGIBLE_TOOL_IDS:
        raise PlatformError(
            409, "PUBLIC_SANDBOX_UNAVAILABLE",
            "该工具尚未接入公共沙箱与统一出口，只能设为项目工具",
        )
    if payload.access_scope == "public" and not public_safety_policy_complete(tool):
        raise PlatformError(
            409,
            "PUBLIC_SAFETY_POLICY_INCOMPLETE",
            "公共工具安全策略未完整配置，不能开放给全体用户",
        )
    before = {"access_scope": tool.access_scope, "project_id": tool.project_id, "is_enabled": tool.is_enabled, "revision": tool.revision}
    tool.access_scope = payload.access_scope
    tool.project_id = payload.project_id if payload.access_scope == "project" else None
    if payload.is_enabled is not None:
        tool.is_enabled = payload.is_enabled
    tool.revision += 1
    tool.authorization_epoch += 1
    for grant in database.scalars(select(UserToolGrant).where(UserToolGrant.tool_id == tool.id, UserToolGrant.status == "active")).all():
        grant.status = "revoked"
        grant.revoke_reason = "工具范围或所属项目变化自动撤销"
        grant.revoked_at = now
    add_audit_event(
        database,
        action="tool.access.change",
        resource_type="tool",
        resource_id=tool.id,
        outcome="success",
        request=request,
        actor=context.user,
        before=before,
        after={"access_scope": tool.access_scope, "project_id": tool.project_id, "is_enabled": tool.is_enabled, "revision": tool.revision, "reason": payload.reason},
    )
    database.commit()
    return _tool_response(database, tool)


@router.get("/tool-grants", response_model=list[ToolGrantResponse])
def list_grants(_: Annotated[AuthContext, Depends(require_platform("platform.tool_grant.manage"))], database: Annotated[Session, Depends(get_db)]) -> list[ToolGrantResponse]:
    now = datetime.now(UTC)
    rows = list(database.scalars(select(UserToolGrant).order_by(UserToolGrant.created_at.desc())).all())
    for row in rows:
        expiry = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        if row.status == "active" and expiry <= now:
            row.status = "expired"
    database.commit()
    return [_grant_response(database, row) for row in rows]


@router.post("/tool-grants", response_model=ToolGrantResponse, status_code=201)
def create_grant(payload: ToolGrantCreateRequest, request: Request, context: Annotated[AuthContext, Depends(require_platform("platform.tool_grant.manage", csrf=True))], database: Annotated[Session, Depends(get_db)]) -> ToolGrantResponse:
    payload_hash = token_hash(f"{payload.user_id}:{payload.tool_id}:{payload.days}:{payload.reason.strip()}:{payload.renewed_from_grant_id or ''}")
    replay = database.scalar(select(UserToolGrant).where(UserToolGrant.idempotency_key == payload.idempotency_key))
    if replay is not None:
        # 相同幂等键只允许重放完全相同的用户/工具请求。
        if replay.idempotency_payload_hash != payload_hash:
            raise PlatformError(409, "IDEMPOTENCY_KEY_CONFLICT", "幂等键已用于其他请求")
        return _grant_response(database, replay)
    user = database.get(User, payload.user_id)
    tool = database.scalar(select(Tool).where(Tool.id == payload.tool_id).with_for_update())
    if user is None or tool is None or tool.access_scope != "project" or not tool.project_id:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if database.get(ProjectMembership, (tool.project_id, user.id)) is not None:
        raise PlatformError(409, "REDUNDANT_GRANT", "用户已通过项目关系获得该工具")
    now = datetime.now(UTC)
    existing = database.scalar(select(UserToolGrant).where(UserToolGrant.user_id == user.id, UserToolGrant.tool_id == tool.id, UserToolGrant.status == "active"))
    if existing is not None and (existing.expires_at if existing.expires_at.tzinfo else existing.expires_at.replace(tzinfo=UTC)) > now:
        raise PlatformError(409, "GRANT_EXISTS", "用户已有有效授权")
    if existing is not None:
        # 到期时间已过但尚未被列表懒更新的授权，先退出 active 唯一集合。
        existing.status = "expired"
        database.flush()
    row = UserToolGrant(
        id=new_id("grt"), user_id=user.id, tool_id=tool.id, project_id=tool.project_id,
        status="active", granted_by_user_id=context.user.id, grant_reason=payload.reason.strip(),
        expires_at=now + timedelta(days=payload.days), renewed_from_grant_id=payload.renewed_from_grant_id,
        idempotency_key=payload.idempotency_key,
        idempotency_payload_hash=payload_hash,
    )
    database.add(row)
    user.permission_version += 1
    tool.revision += 1
    tool.authorization_epoch += 1
    add_audit_event(database, action="tool.grant.create", resource_type="tool_grant", resource_id=row.id, outcome="success", request=request, actor=context.user, after={"user_id": row.user_id, "tool_id": row.tool_id, "project_id": row.project_id, "expires_at": row.expires_at.isoformat(), "reason": row.grant_reason})
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        # 部分唯一索引把并发重复创建收敛为稳定业务冲突，而不是泄漏 500。
        raise PlatformError(409, "GRANT_EXISTS", "用户已有有效授权") from None
    return _grant_response(database, row)


@router.post("/tool-grants/{grant_id}/revoke", response_model=ToolGrantResponse)
def revoke_grant(grant_id: str, payload: ToolGrantRevokeRequest, request: Request, context: Annotated[AuthContext, Depends(require_platform("platform.tool_grant.manage", csrf=True))], database: Annotated[Session, Depends(get_db)]) -> ToolGrantResponse:
    candidate = database.get(UserToolGrant, grant_id)
    if candidate is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    # 全部授权写统一 tool→grant 锁序，避免与工具范围变更形成循环等待。
    tool = database.scalar(select(Tool).where(Tool.id == candidate.tool_id).with_for_update())
    row = database.scalar(select(UserToolGrant).where(UserToolGrant.id == grant_id).with_for_update())
    if row is None or row.tool_id != candidate.tool_id:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if row.status == "active":
        row.status = "revoked"
        row.revoked_by_user_id = context.user.id
        row.revoke_reason = payload.reason.strip()
        row.revoked_at = datetime.now(UTC)
        user = database.get(User, row.user_id)
        if user:
            user.permission_version += 1
        if tool:
            tool.revision += 1
            tool.authorization_epoch += 1
        add_audit_event(database, action="tool.grant.revoke", resource_type="tool_grant", resource_id=row.id, outcome="success", request=request, actor=context.user, after={"reason": row.revoke_reason})
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "GRANT_EXISTS", "用户已有有效授权") from None
    return _grant_response(database, row)


@router.post("/tool-grants/{grant_id}/renew", response_model=ToolGrantResponse)
def renew_grant(
    grant_id: str,
    payload: ToolGrantRenewRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.tool_grant.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> ToolGrantResponse:
    """续期仍限制为未来 90 天，并保留原授权链路。"""

    candidate = database.get(UserToolGrant, grant_id)
    if candidate is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    # 与 create/revoke/change_tool_access 一致，始终先锁 Tool、再锁 Grant。
    tool = database.scalar(select(Tool).where(Tool.id == candidate.tool_id).with_for_update())
    row = database.scalar(select(UserToolGrant).where(UserToolGrant.id == grant_id).with_for_update())
    if row is None or row.tool_id != candidate.tool_id or row.status not in {"active", "expired"}:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    now = datetime.now(UTC)
    expires_at = payload.expires_at if payload.expires_at.tzinfo else payload.expires_at.replace(tzinfo=UTC)
    if expires_at <= now or expires_at > now + timedelta(days=90):
        raise PlatformError(422, "GRANT_EXPIRY_INVALID", "授权到期时间必须在未来 90 天内")
    other_active = database.scalar(select(UserToolGrant).where(
        UserToolGrant.user_id == row.user_id,
        UserToolGrant.tool_id == row.tool_id,
        UserToolGrant.status == "active",
        UserToolGrant.id != row.id,
    ))
    if other_active is not None:
        raise PlatformError(409, "GRANT_EXISTS", "用户已有有效授权")
    row.status = "active"
    row.expires_at = expires_at
    row.grant_reason = payload.reason.strip()
    user = database.get(User, row.user_id)
    if user:
        user.permission_version += 1
    if tool:
        tool.revision += 1
        tool.authorization_epoch += 1
    add_audit_event(database, action="tool.grant.renew", resource_type="tool_grant", resource_id=row.id, outcome="success", request=request, actor=context.user, after={"expires_at": expires_at.isoformat(), "reason": row.grant_reason})
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "GRANT_EXISTS", "用户已有有效授权") from None
    return _grant_response(database, row)
