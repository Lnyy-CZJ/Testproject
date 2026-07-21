"""
Pydantic Schema 统一导出

字段命名约定: camelCase (与前端 Go 版完全兼容)
所有 Schema 配置 model_config = {"populate_by_name": True} 以同时接受 snake_case 和 camelCase 输入
"""

from app.schemas.common import ApiResult, PaginatedResponse
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UpdateAgentTypesRequest,
    UserProfile,
)
from app.schemas.defect import (
    AssignDefectRequest,
    DefectCreate,
    DefectDetail,
    DefectListItem,
    DefectStatusChangeRequest,
    DefectUpdate,
    VerifyDefectRequest,
)
from app.schemas.project import (
    AIConfigCreate,
    IterationCreate,
    IterationDetail,
    ProjectCreate,
    ProjectDetail,
    ProjectMemberItem,
    ProjectStats,
    ProjectUpdate,
    RepoCreate,
)

__all__ = [
    "ApiResult",
    "PaginatedResponse",
    "LoginRequest",
    "LoginResponse",
    "RegisterRequest",
    "ChangePasswordRequest",
    "UpdateAgentTypesRequest",
    "UserProfile",
    "DefectCreate",
    "DefectUpdate",
    "DefectListItem",
    "DefectDetail",
    "AssignDefectRequest",
    "VerifyDefectRequest",
    "DefectStatusChangeRequest",
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectDetail",
    "ProjectMemberItem",
    "ProjectStats",
    "IterationCreate",
    "IterationDetail",
    "RepoCreate",
    "AIConfigCreate",
]