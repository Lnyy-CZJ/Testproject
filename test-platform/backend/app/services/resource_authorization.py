from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.access import BusinessResourceSnapshot, Project, ProjectMembership
from app.models.identity import User


@dataclass(frozen=True)
class ResourceAccessDecision:
    """业务对象授权结果；工具访问权不能替代该判定。"""

    allowed: bool
    scope: str | None = None


def decide_resource_access(
    database: Session,
    user: User,
    resource: BusinessResourceSnapshot,
) -> ResourceAccessDecision:
    """计算 own/project/global 数据范围，测试人员始终不能读取他人资源。"""

    if user.status != "active":
        return ResourceAccessDecision(False)
    if user.platform_role == "platform_admin":
        return ResourceAccessDecision(True, "global")
    if resource.owner_user_id == user.id:
        return ResourceAccessDecision(True, "own")
    if user.platform_role != "admin" or not resource.project_id_snapshot:
        return ResourceAccessDecision(False)
    project = database.get(Project, resource.project_id_snapshot)
    membership = database.get(ProjectMembership, (resource.project_id_snapshot, user.id))
    if project is None or project.status != "active" or membership is None or membership.relation != "manager":
        return ResourceAccessDecision(False)
    return ResourceAccessDecision(True, "project")
