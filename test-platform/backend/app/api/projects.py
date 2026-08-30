from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, current_auth_context, require_csrf, require_platform
from app.core.errors import PlatformError
from app.core.security import new_id, normalize_username, token_hash
from app.db.session import get_db
from app.models.access import Project, ProjectMembership, UserToolGrant
from app.models.identity import User
from app.models.tool import Tool
from app.schemas.access import (
    ProjectCreateRequest,
    ProjectImpactPreviewResponse,
    ProjectMemberRequest,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectRelationRemoveRequest,
    ProjectStatusChangeRequest,
    ProjectUpdateRequest,
    ToolAccessResponse,
)
from app.services.audit import add_audit_event
from app.services.authorization import public_safety_policy_complete


router = APIRouter(prefix="/projects", tags=["projects"])


def _response(database: Session, project: Project, relation: str | None = None) -> ProjectResponse:
    """转换项目公开字段，避免返回内部迁移元数据。"""

    manager_count = database.scalar(select(func.count()).select_from(ProjectMembership).where(
        ProjectMembership.project_id == project.id,
        ProjectMembership.relation == "manager",
    )) or 0
    member_count = database.scalar(select(func.count()).select_from(ProjectMembership).where(
        ProjectMembership.project_id == project.id,
        ProjectMembership.relation == "member",
    )) or 0
    tool_count = database.scalar(select(func.count()).select_from(Tool).where(
        Tool.project_id == project.id,
    )) or 0
    active_grant_count = database.scalar(select(func.count()).select_from(UserToolGrant).where(
        UserToolGrant.project_id == project.id,
        UserToolGrant.status == "active",
    )) or 0
    return ProjectResponse(
        id=project.id,
        code=project.code,
        name=project.name,
        description=project.description,
        status=project.status,
        revision=project.revision,
        authorization_epoch=project.authorization_epoch,
        relation=relation,
        manager_count=manager_count,
        member_count=member_count,
        tool_count=tool_count,
        active_grant_count=active_grant_count,
        updated_at=project.updated_at,
    )


def _managed_project(database: Session, context: AuthContext, project_id: str) -> Project:
    """返回当前用户可管理项目；不可见与不存在统一 404。"""

    project = database.get(Project, project_id)
    if project is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if context.user.platform_role == "platform_admin":
        return project
    membership = database.get(ProjectMembership, (project_id, context.user.id))
    if context.user.platform_role != "admin" or membership is None or membership.relation != "manager":
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    return project


def _locked_managed_project(database: Session, context: AuthContext, project_id: str) -> Project:
    """串行化同一项目的管理写操作，并在取得锁后重新执行管理范围校验。"""

    project = database.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    return _managed_project(database, context, project_id)


def _locked_membership_scope(
    database: Session,
    context: AuthContext,
    project_id: str,
    *,
    username_normalized: str | None = None,
    user_id: str | None = None,
) -> tuple[Project, User]:
    """按“目标用户 → 项目”的固定顺序锁定一次成员关系写入范围。

    先做项目管理范围检查，可避免未授权管理员借用户名查询枚举全平台用户；
    随后才取得目标用户锁和项目锁，并在锁内再次检查项目管理范围。角色修改
    同样锁定目标用户，因此角色变更与成员关系增删不会基于彼此的旧状态提交。

    ``username_normalized`` 用于精确添加，``user_id`` 用于移除；调用方必须且
    只能提供其中一个。不可见项目、用户不存在都沿用统一的 404 语义。
    """

    _managed_project(database, context, project_id)
    if (username_normalized is None) == (user_id is None):
        raise ValueError("username_normalized 与 user_id 必须且只能提供一个")
    condition = (
        User.username_normalized == username_normalized
        if username_normalized is not None
        else User.id == user_id
    )
    user = database.scalar(select(User).where(condition).with_for_update())
    if user is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    project = database.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    _managed_project(database, context, project_id)
    return project, user


def _bump_permission_version(database: Session, user_id: str) -> None:
    """以数据库表达式递增权限版本，避免并发事务发生读改写丢失更新。"""

    database.execute(
        update(User)
        .where(User.id == user_id)
        .values(permission_version=User.permission_version + 1)
        .execution_options(synchronize_session=False)
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[ProjectResponse]:
    """平台管理员查看全部项目，其他角色只查看自己的项目关系。"""

    if context.user.platform_role == "platform_admin":
        return [_response(database, row) for row in database.scalars(select(Project).order_by(Project.name)).all()]
    memberships = list(database.scalars(select(ProjectMembership).where(ProjectMembership.user_id == context.user.id)).all())
    result = []
    for membership in memberships:
        project = database.get(Project, membership.project_id)
        if project is not None:
            result.append(_response(database, project, membership.relation))
    return sorted(result, key=lambda row: row.name)


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.project.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    """创建 code 不可变的新项目。"""

    if database.scalar(select(Project).where(Project.code == payload.code.upper())):
        raise PlatformError(409, "PROJECT_CODE_EXISTS", "项目标识已存在")
    project = Project(
        id=new_id("prj"),
        code=payload.code.upper(),
        name=payload.name.strip(),
        description=payload.description.strip(),
        status="active",
        created_by_user_id=context.user.id,
    )
    database.add(project)
    add_audit_event(database, action="project.create", resource_type="project", resource_id=project.id, outcome="success", request=request, actor=context.user, after={"code": project.code, "name": project.name, "reason": payload.reason})
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "PROJECT_CODE_EXISTS", "项目标识已存在") from None
    return _response(database, project)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, context: Annotated[AuthContext, Depends(current_auth_context)], database: Annotated[Session, Depends(get_db)]) -> ProjectResponse:
    """读取可见项目详情。"""

    if context.user.platform_role == "platform_admin":
        project = database.get(Project, project_id)
        if project is None:
            raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
        return _response(database, project)
    membership = database.get(ProjectMembership, (project_id, context.user.id))
    if membership is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    project = database.get(Project, project_id)
    if project is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    return _response(database, project, membership.relation)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, payload: ProjectUpdateRequest, request: Request, context: Annotated[AuthContext, Depends(require_csrf)], database: Annotated[Session, Depends(get_db)]) -> ProjectResponse:
    """按 revision 乐观锁更新项目展示信息。"""

    project = _locked_managed_project(database, context, project_id)
    if project.revision != payload.revision:
        raise PlatformError(409, "STALE_REVISION", "项目已发生变化，请刷新后重试")
    if payload.name is not None:
        project.name = payload.name.strip()
    if payload.description is not None:
        project.description = payload.description.strip()
    project.revision += 1
    add_audit_event(database, action="project.update", resource_type="project", resource_id=project.id, outcome="success", request=request, actor=context.user, after={"name": project.name, "description": project.description, "revision": project.revision, "reason": payload.reason})
    database.commit()
    return _response(database, project)


def _list_people(database: Session, project_id: str, relation: str) -> list[ProjectMemberResponse]:
    rows = database.scalars(select(ProjectMembership).where(ProjectMembership.project_id == project_id, ProjectMembership.relation == relation)).all()
    result = []
    for row in rows:
        user = database.get(User, row.user_id)
        if user:
            result.append(ProjectMemberResponse(
                id=user.id,
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                relation=relation,
                role=user.platform_role,
                status=user.status,
                created_at=row.created_at,
            ))
    return result


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_members(project_id: str, context: Annotated[AuthContext, Depends(current_auth_context)], database: Annotated[Session, Depends(get_db)]) -> list[ProjectMemberResponse]:
    _managed_project(database, context, project_id)
    return _list_people(database, project_id, "member")


@router.post("/{project_id}/members", response_model=ProjectMemberResponse, status_code=201)
def add_member(project_id: str, payload: ProjectMemberRequest, request: Request, context: Annotated[AuthContext, Depends(require_csrf)], database: Annotated[Session, Depends(get_db)]) -> ProjectMemberResponse:
    project, user = _locked_membership_scope(
        database,
        context,
        project_id,
        username_normalized=normalize_username(payload.username),
    )
    # 账号状态和固定角色必须在用户、项目均锁定后校验，防止与角色修改竞态。
    if user.status != "active" or user.platform_role != "tester":
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if database.get(ProjectMembership, (project_id, user.id)):
        raise PlatformError(409, "PROJECT_RELATION_EXISTS", "用户已在项目中")
    row = ProjectMembership(project_id=project_id, user_id=user.id, relation="member", created_by_user_id=context.user.id)
    database.add(row)
    _bump_permission_version(database, user.id)
    project.revision += 1
    project.authorization_epoch += 1
    add_audit_event(database, action="project.member.add", resource_type="project", resource_id=project_id, outcome="success", request=request, actor=context.user, after={"user_id": user.id, "reason": payload.reason})
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "PROJECT_RELATION_EXISTS", "用户已在项目中") from None
    return ProjectMemberResponse(
        id=user.id,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        relation="member",
        role="tester",
        status=user.status,
        created_at=row.created_at,
    )


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: str, user_id: str, payload: ProjectRelationRemoveRequest, request: Request, context: Annotated[AuthContext, Depends(require_csrf)], database: Annotated[Session, Depends(get_db)]) -> None:
    project, user = _locked_membership_scope(database, context, project_id, user_id=user_id)
    row = database.get(ProjectMembership, (project_id, user_id))
    if row is None or row.relation != "member":
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    database.delete(row)
    _bump_permission_version(database, user.id)
    project.revision += 1
    project.authorization_epoch += 1
    add_audit_event(database, action="project.member.remove", resource_type="project", resource_id=project_id, outcome="success", request=request, actor=context.user, before={"user_id": user_id, "reason": payload.reason})
    database.commit()


@router.get("/{project_id}/managers", response_model=list[ProjectMemberResponse])
def list_managers(
    project_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[ProjectMemberResponse]:
    """项目负责人仅对平台管理员开放，避免普通管理员枚举同级账号。"""

    if context.user.platform_role != "platform_admin":
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    _managed_project(database, context, project_id)
    return _list_people(database, project_id, "manager")


@router.post("/{project_id}/managers", response_model=ProjectMemberResponse, status_code=201)
def add_manager(
    project_id: str,
    payload: ProjectMemberRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.project.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> ProjectMemberResponse:
    """平台管理员通过完整用户名为项目分配固定角色 admin。"""

    project, user = _locked_membership_scope(
        database,
        context,
        project_id,
        username_normalized=normalize_username(payload.username),
    )
    # disabled 管理员不能通过项目关系重新获得任何管理范围。
    if user.status != "active" or user.platform_role != "admin":
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if database.get(ProjectMembership, (project_id, user.id)):
        raise PlatformError(409, "PROJECT_RELATION_EXISTS", "用户已在项目中")
    row = ProjectMembership(
        project_id=project_id,
        user_id=user.id,
        relation="manager",
        created_by_user_id=context.user.id,
    )
    database.add(row)
    _bump_permission_version(database, user.id)
    project.revision += 1
    project.authorization_epoch += 1
    add_audit_event(database, action="project.manager.add", resource_type="project", resource_id=project_id, outcome="success", request=request, actor=context.user, after={"user_id": user.id, "reason": payload.reason})
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise PlatformError(409, "PROJECT_RELATION_EXISTS", "用户已在项目中") from None
    return ProjectMemberResponse(
        id=user.id,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        relation="manager",
        role="admin",
        status=user.status,
        created_at=row.created_at,
    )


@router.delete("/{project_id}/managers/{user_id}", status_code=204)
def remove_manager(
    project_id: str,
    user_id: str,
    payload: ProjectRelationRemoveRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.project.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> None:
    """移除负责人关系，但不改变该用户的全局固定角色。"""

    project, user = _locked_membership_scope(database, context, project_id, user_id=user_id)
    row = database.get(ProjectMembership, (project_id, user_id))
    if row is None or row.relation != "manager":
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    database.delete(row)
    _bump_permission_version(database, user.id)
    project.revision += 1
    project.authorization_epoch += 1
    add_audit_event(database, action="project.manager.remove", resource_type="project", resource_id=project_id, outcome="success", request=request, actor=context.user, before={"user_id": user_id, "reason": payload.reason})
    database.commit()


@router.get("/{project_id}/tools", response_model=list[ToolAccessResponse])
def list_project_tools(
    project_id: str,
    context: Annotated[AuthContext, Depends(current_auth_context)],
    database: Annotated[Session, Depends(get_db)],
) -> list[ToolAccessResponse]:
    """返回项目当前工具归属；tester 只能读取，不获得工具管理能力。"""

    project = database.get(Project, project_id)
    if project is None:
        raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    if context.user.platform_role != "platform_admin":
        membership = database.get(ProjectMembership, (project_id, context.user.id))
        if membership is None:
            raise PlatformError(404, "NOT_FOUND", "请求的资源不存在")
    tools = database.scalars(select(Tool).where(
        Tool.project_id == project_id
    ).order_by(Tool.sort_order, Tool.name)).all()
    return [ToolAccessResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        is_enabled=tool.is_enabled,
        access_scope=tool.access_scope,
        project_id=project.id,
        project_name=project.name,
        revision=tool.revision,
        authorization_epoch=tool.authorization_epoch,
        public_safety_policy_status="complete" if public_safety_policy_complete(tool) else "missing",
        public_policy_complete=public_safety_policy_complete(tool),
        updated_at=tool.updated_at,
    ) for tool in tools]


def _project_impact_token(project: Project, target_status: str) -> str:
    """绑定项目 revision 与目标状态，防止预览后状态漂移。"""

    return token_hash(f"project:{project.id}:{project.revision}:{target_status}")


@router.get("/{project_id}/deactivation-impact", response_model=ProjectImpactPreviewResponse)
def preview_project_deactivation(
    project_id: str,
    context: Annotated[AuthContext, Depends(require_platform("platform.project.manage"))],
    database: Annotated[Session, Depends(get_db)],
) -> ProjectImpactPreviewResponse:
    """返回可验证影响清单；无法确认运行任务数量时明确标记 unknown。"""

    project = _managed_project(database, context, project_id)
    detail = _response(database, project)
    return ProjectImpactPreviewResponse(
        expected_revision=project.revision,
        impact_token=_project_impact_token(project, "inactive"),
        manager_count=detail.manager_count,
        member_count=detail.member_count,
        tool_count=detail.tool_count,
        active_grant_count=detail.active_grant_count,
        running_task_count="unknown",
    )


@router.post("/{project_id}/deactivate", response_model=ProjectResponse)
def deactivate_project(
    project_id: str,
    payload: ProjectStatusChangeRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.project.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    """按 revision 与影响令牌停用项目；未知运行态默认失败关闭。"""

    # 锁定项目行后再做管理范围和 revision 校验，避免两个预览令牌并发消费。
    project = _locked_managed_project(database, context, project_id)
    if (
        project.revision != payload.expected_revision
        or payload.impact_token != _project_impact_token(project, "inactive")
    ):
        raise PlatformError(409, "STALE_IMPACT", "影响预览已过期，请重新计算")
    if not payload.force_unknown_impact:
        raise PlatformError(409, "RUNNING_TASK_IMPACT_UNKNOWN", "运行任务数量未知，默认禁止停用")
    project.status = "inactive"
    project.revision += 1
    project.authorization_epoch += 1
    add_audit_event(database, action="project.deactivate", resource_type="project", resource_id=project.id, outcome="success", request=request, actor=context.user, after={"reason": payload.reason, "revision": project.revision})
    database.commit()
    return _response(database, project)


@router.post("/{project_id}/activate", response_model=ProjectResponse)
def activate_project(
    project_id: str,
    payload: ProjectStatusChangeRequest,
    request: Request,
    context: Annotated[AuthContext, Depends(require_platform("platform.project.manage", csrf=True))],
    database: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    """恢复项目时仍使用 revision，影响令牌沿用 active 目标绑定。"""

    # 恢复与停用共享相同的串行化边界，确保 revision 不发生后写覆盖。
    project = _locked_managed_project(database, context, project_id)
    if project.revision != payload.expected_revision:
        raise PlatformError(409, "STALE_IMPACT", "项目状态已变化，请刷新后重试")
    project.status = "active"
    project.revision += 1
    project.authorization_epoch += 1
    add_audit_event(database, action="project.activate", resource_type="project", resource_id=project.id, outcome="success", request=request, actor=context.user, after={"reason": payload.reason, "revision": project.revision})
    database.commit()
    return _response(database, project)
