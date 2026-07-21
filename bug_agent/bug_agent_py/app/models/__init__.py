"""
SQLAlchemy ORM 模型统一注册

按依赖顺序导入所有模型，确保 Alembic 自动迁移能发现全部表。
导入顺序: 先基础模型，后业务模型（外键依赖在前）。
"""

from app.models.base import Base, TimestampMixin

# 基础模型（无外键依赖或仅依赖 users）
from app.models.user import InviteCode, User

# 项目与权限（依赖 users）
from app.models.auth import AuditLog, Permission, Role, RolePermission, UserRole
from app.models.credential import PlatformCredentialProject, PlatformSetting, RepoCredential
from app.models.project import (
    Iteration,
    IterationRepo,
    Project,
    ProjectAIConfig,
    ProjectAgentSkill,
    ProjectMCPServer,
    ProjectMember,
    ProjectModule,
    ProjectNotificationPolicy,
    ProjectRepo,
    ProjectWebhook,
)

# 缺陷与修复（依赖 projects, iterations, users）
from app.models.analysis_report import AnalysisReport, AnalysisTask, AITokenUsage, RolloutRecord
from app.models.defect import Attachment, Comment, Defect, DefectRepo
from app.models.fix_task import FixTask, FixTaskGroup, PRRejection
from app.models.workflow import StatusChange

# 信号与集成（依赖 projects, defects, users）
from app.models.signal import (
    AppRelease,
    IntegrationConnector,
    IntegrationSyncRecord,
    IssueCluster,
    IssueRoutingRule,
    IssueSignal,
    RegressionItem,
)

# Agent 记忆与协作（依赖 projects, iterations, users）
from app.models.agent_memory import AgentMemory
from app.models.catalog import (
    AIProviderCatalog,
    AIModelCatalog,
    CollaborationReport,
    CollaborationTask,
    RetrieverPlugin,
)

# 通知（依赖 users）
from app.models.notification import Notification, NotificationPreference, NotificationTemplate, UserWebhookSetting

__all__ = [
    "Base",
    "TimestampMixin",
    # 用户
    "User",
    "InviteCode",
    # 权限
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "AuditLog",
    # 凭证
    "RepoCredential",
    "PlatformCredentialProject",
    "PlatformSetting",
    # 项目
    "Project",
    "ProjectMember",
    "ProjectRepo",
    "ProjectAIConfig",
    "Iteration",
    "IterationRepo",
    "ProjectMCPServer",
    "ProjectAgentSkill",
    "ProjectModule",
    "ProjectWebhook",
    "ProjectNotificationPolicy",
    # 缺陷
    "Defect",
    "Attachment",
    "Comment",
    "DefectRepo",
    # 修复
    "FixTaskGroup",
    "FixTask",
    "PRRejection",
    # 分析
    "AnalysisReport",
    "AITokenUsage",
    "AnalysisTask",
    "RolloutRecord",
    # 工作流
    "StatusChange",
    # 信号
    "IssueCluster",
    "IssueSignal",
    "IntegrationConnector",
    "IntegrationSyncRecord",
    "IssueRoutingRule",
    "AppRelease",
    "RegressionItem",
    # 记忆
    "AgentMemory",
    # 目录
    "AIProviderCatalog",
    "AIModelCatalog",
    "CollaborationTask",
    "CollaborationReport",
    "RetrieverPlugin",
    # 通知
    "Notification",
    "NotificationTemplate",
    "NotificationPreference",
    "UserWebhookSetting",
]