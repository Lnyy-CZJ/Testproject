"""
FastAPI 依赖注入

功能说明:
    提供账号、权限和数据库会话相关 Depends。第一阶段实现最小可用权限:
    - 平台管理员可访问管理类接口
    - 普通用户可访问自己加入的项目
    - 缺陷级权限通过缺陷所属迭代回溯项目成员关系
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import security
from app.infrastructure.database import get_db
from app.models.defect import Defect
from app.models.project import Iteration, Project, ProjectMember
from app.models.user import User

security_scheme = HTTPBearer(auto_error=False)


async def bind_db_to_request(request: Request, db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """
    将数据库会话绑定到 request.state。

    功能说明:
        多个认证和权限依赖都需要数据库会话。绑定后可避免在一个请求中
        重复创建 session，并保持事务边界一致。

    返回值:
        AsyncSession: 当前请求数据库会话。
    """
    request.state.db = db
    return db


async def get_current_user(
    request: Request,
    _: AsyncSession = Depends(bind_db_to_request),
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> User:
    """
    解析当前登录用户。

    参数说明:
        request: 当前 HTTP 请求，用于读取已绑定的数据库会话。
        credentials: Authorization Bearer Token。

    返回值:
        User: 当前登录用户 ORM 对象。

    异常说明:
        HTTPException(401): 未登录、Token 无效或用户已不存在。
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    payload = security.decode_access_token(credentials.credentials)
    if payload is None or payload.get("sub") is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")

    db: AsyncSession = request.state.db
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    return user


def is_platform_admin(user: User) -> bool:
    """判断用户是否具备平台管理员能力"""
    return user.platform_role in {"super_admin", "admin"}


def _requires_platform_admin(permission: str) -> bool:
    """
    判断某个权限是否必须平台管理员。

    第一阶段只实现粗粒度权限保护。完整 RBAC 权限码会在后续阶段接入。
    """
    return permission.startswith(("users:", "rbac:", "audit:", "system:")) or permission in {
        "notifications:send",
        "reports:export",
    }


class RequirePermission:
    """
    全局权限校验 Depends。

    参数说明:
        permission: 权限码，例如 users:read、projects:create。
    """

    def __init__(self, permission: str):
        self.permission = permission

    async def __call__(self, current_user: User = Depends(get_current_user)) -> bool:
        """
        执行全局权限校验。

        返回值:
            bool: 校验通过返回 True。

        异常说明:
            HTTPException(403): 当前用户无权访问管理类接口。
        """
        if _requires_platform_admin(self.permission) and not is_platform_admin(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
        return True


class RequireProjectPermission:
    """
    项目级权限校验。

    参数说明:
        permission: 权限码。
        path_param: URL path 中项目 ID 参数名，默认 id。
    """

    def __init__(self, permission: str, path_param: str = "id"):
        self.permission = permission
        self.path_param = path_param

    async def __call__(
        self,
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> bool:
        """
        执行项目级权限校验。

        平台管理员直接通过；普通用户必须是项目 owner 或项目成员。
        """
        if is_platform_admin(current_user):
            return True

        raw_project_id = request.path_params.get(self.path_param)
        if raw_project_id is None:
            return True
        project_id = int(raw_project_id)
        db: AsyncSession = request.state.db

        owned = await db.scalar(
            select(Project.id).where(Project.id == project_id, Project.owner_id == current_user.id)
        )
        if owned is not None:
            return True

        member_id = await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if member_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
        return True


class RequireDefectPermission:
    """
    缺陷级权限校验。

    通过缺陷 -> 迭代 -> 项目链路校验访问范围。
    """

    def __init__(self, permission: str, path_param: str = "id"):
        self.permission = permission
        self.path_param = path_param

    async def __call__(
        self,
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> bool:
        """
        执行缺陷级权限校验。

        返回值:
            bool: 当前用户具备该缺陷所属项目访问权时返回 True。

        异常说明:
            HTTPException(403): 当前用户不是项目 Owner 或成员。
            HTTPException(404): 缺陷不存在。
        """
        if is_platform_admin(current_user):
            return True

        raw_defect_id = request.path_params.get(self.path_param)
        if raw_defect_id is None:
            return True

        db: AsyncSession = request.state.db
        defect_id = int(raw_defect_id)
        project_id = await db.scalar(
            select(Iteration.project_id)
            .join(Defect, Defect.iteration_id == Iteration.id)
            .where(Defect.id == defect_id)
        )
        if project_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="缺陷不存在")

        owned = await db.scalar(
            select(Project.id).where(Project.id == project_id, Project.owner_id == current_user.id)
        )
        if owned is not None:
            return True

        member_id = await db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if member_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限访问")
        return True
