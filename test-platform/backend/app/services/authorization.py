from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import RoleGrant, UserRole


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

    return any(
        grant.permission_code == code
        and grant.resource_type == "platform"
        and grant.resource_id == "*"
        for grant in user_grants(database, user_id)
    )


def tool_permissions(database: Session, user_id: str, tool_id: str) -> set[str]:
    """返回用户在指定工具上的权限代码集合。"""

    return {
        grant.permission_code
        for grant in user_grants(database, user_id)
        if grant.resource_type == "tool" and grant.resource_id in {tool_id, "*"}
    }


def has_tool_permission(database: Session, user_id: str, code: str, tool_id: str) -> bool:
    """判断用户是否具有指定工具权限。"""

    return code in tool_permissions(database, user_id, tool_id)
