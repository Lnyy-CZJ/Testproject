"""
项目域 API

功能说明:
    实现第一阶段项目、成员、迭代、仓库和项目 AI 配置接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, RequireProjectPermission, get_current_user
from app.infrastructure.database import get_db
from app.models.user import User
from app.schemas.common import ApiResult, PaginatedResponse
from app.schemas.project import (
    AIConfigCreate,
    AIConfigDetail,
    AIConfigUpdate,
    AIProviderOption,
    AddProjectMemberRequest,
    BindRepoRequest,
    IterationCreate,
    IterationDetail,
    IterationDetailResponse,
    IterationRepoItem,
    IterationUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectDetailResponse,
    ProjectStats,
    ProjectUpdate,
    RepoCreate,
    RepoDetail,
    RepoUpdate,
    UpdateIterationRepoBranchRequest,
)
from app.services.project_service import ProjectService

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=ApiResult[PaginatedResponse[ProjectDetail]])
async def list_projects(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[PaginatedResponse[ProjectDetail]]:
    """查询当前用户可见项目"""
    projects, total = await ProjectService(db).list_projects(current_user, page, size)
    return ApiResult.success(PaginatedResponse.from_items(projects, total, page, size))


@router.post("/projects", response_model=ApiResult[ProjectDetail])
async def create_project(
    body: ProjectCreate,
    _: bool = Depends(RequirePermission("projects:create")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[ProjectDetail]:
    """创建项目"""
    project = await ProjectService(db).create_project(current_user, body.name, body.description)
    return ApiResult.success(project)


@router.get("/user/projects", response_model=ApiResult[PaginatedResponse[ProjectDetail]])
async def list_user_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[PaginatedResponse[ProjectDetail]]:
    """查询当前用户项目，用于前端项目切换器"""
    projects, total = await ProjectService(db).list_projects(current_user, page=1, size=100)
    return ApiResult.success(PaginatedResponse.from_items(projects, total, 1, 100))


@router.get("/projects/{id}", response_model=ApiResult[ProjectDetailResponse])
async def get_project(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[ProjectDetailResponse]:
    """获取项目详情"""
    detail = await ProjectService(db).get_project_detail(id)
    return ApiResult.success(detail)


@router.put("/projects/{id}", response_model=ApiResult[ProjectDetail])
async def update_project(
    id: int,
    body: ProjectUpdate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[ProjectDetail]:
    """更新项目"""
    project = await ProjectService(db).update_project(id, body)
    return ApiResult.success(project)


@router.post("/projects/{id}/members", response_model=ApiResult[None])
async def add_project_member(
    id: int,
    body: AddProjectMemberRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """添加项目成员"""
    await ProjectService(db).add_member(id, body)
    return ApiResult.success(None)


@router.delete("/projects/{id}/members/{member_id}", response_model=ApiResult[None])
async def remove_project_member(
    id: int,
    member_id: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """移除项目成员"""
    await ProjectService(db).remove_member(id, member_id)
    return ApiResult.success(None)


@router.get("/projects/{id}/stats", response_model=ApiResult[ProjectStats])
async def get_project_stats(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[ProjectStats]:
    """获取项目统计"""
    stats = await ProjectService(db).get_project_stats(id)
    return ApiResult.success(stats)


@router.post("/projects/{id}/iterations", response_model=ApiResult[IterationDetail])
async def create_iteration(
    id: int,
    body: IterationCreate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IterationDetail]:
    """创建迭代"""
    iteration = await ProjectService(db).create_iteration(id, body)
    return ApiResult.success(iteration)


@router.get("/projects/{id}/iterations", response_model=ApiResult[list[IterationDetail]])
async def list_iterations(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[IterationDetail]]:
    """查询迭代列表"""
    iterations = await ProjectService(db).list_iterations(id)
    return ApiResult.success(iterations)


@router.get(
    "/projects/{id}/iterations/{iteration_id}",
    response_model=ApiResult[IterationDetailResponse],
)
async def get_iteration(
    id: int,
    iteration_id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IterationDetailResponse]:
    """获取迭代详情"""
    detail = await ProjectService(db).get_iteration_detail(id, iteration_id)
    return ApiResult.success(detail)


@router.put("/projects/{id}/iterations/{iteration_id}", response_model=ApiResult[IterationDetail])
async def update_iteration(
    id: int,
    iteration_id: int,
    body: IterationUpdate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IterationDetail]:
    """更新迭代"""
    iteration = await ProjectService(db).update_iteration(id, iteration_id, body)
    return ApiResult.success(iteration)


@router.post(
    "/projects/{id}/iterations/{iteration_id}/repos",
    response_model=ApiResult[IterationRepoItem],
)
async def bind_repo(
    id: int,
    iteration_id: int,
    body: BindRepoRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IterationRepoItem]:
    """绑定仓库到迭代"""
    binding = await ProjectService(db).bind_repo(id, iteration_id, body)
    return ApiResult.success(binding)


@router.delete("/projects/{id}/iterations/{iteration_id}/repos/{repo_id}", response_model=ApiResult[None])
async def unbind_repo(
    id: int,
    iteration_id: int,
    repo_id: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """解除迭代仓库绑定"""
    await ProjectService(db).unbind_repo(id, iteration_id, repo_id)
    return ApiResult.success(None)


@router.put(
    "/projects/{id}/iterations/{iteration_id}/repos/{iter_repo_id}/branch",
    response_model=ApiResult[dict],
)
async def update_iteration_repo_branch(
    id: int,
    iteration_id: int,
    iter_repo_id: int,
    body: UpdateIterationRepoBranchRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[dict]:
    """更新迭代仓库分支"""
    result = await ProjectService(db).update_iteration_repo_branch(id, iteration_id, iter_repo_id, body)
    return ApiResult.success(result)


@router.get("/projects/{id}/repos", response_model=ApiResult[list[RepoDetail]])
async def list_project_repos(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[RepoDetail]]:
    """查询项目仓库列表"""
    repos = await ProjectService(db).list_repos(id)
    return ApiResult.success(repos)


@router.post("/projects/{id}/repos", response_model=ApiResult[RepoDetail])
async def create_project_repo(
    id: int,
    body: RepoCreate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[RepoDetail]:
    """创建项目仓库"""
    repo = await ProjectService(db).create_repo(id, body)
    return ApiResult.success(repo)


@router.put("/projects/{id}/repos/{repo_id}", response_model=ApiResult[RepoDetail])
async def update_project_repo(
    id: int,
    repo_id: int,
    body: RepoUpdate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[RepoDetail]:
    """更新项目仓库"""
    repo = await ProjectService(db).update_repo(id, repo_id, body)
    return ApiResult.success(repo)


@router.delete("/projects/{id}/repos/{repo_id}", response_model=ApiResult[None])
async def delete_project_repo(
    id: int,
    repo_id: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """删除项目仓库"""
    await ProjectService(db).delete_repo(id, repo_id)
    return ApiResult.success(None)


@router.get("/projects/{id}/repos/{repo_id}/branches", response_model=ApiResult[list[str]])
async def list_repo_branches(
    id: int,
    repo_id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[str]]:
    """查询仓库分支，第一阶段返回默认分支"""
    branches = await ProjectService(db).list_repo_branches(id, repo_id)
    return ApiResult.success(branches)


@router.get("/projects/{id}/ai-configs", response_model=ApiResult[list[AIConfigDetail]])
async def list_project_ai_configs(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AIConfigDetail]]:
    """查询项目 AI 配置"""
    configs = await ProjectService(db).list_ai_configs(id)
    return ApiResult.success(configs)


@router.post("/projects/{id}/ai-configs", response_model=ApiResult[AIConfigDetail])
async def create_project_ai_config(
    id: int,
    body: AIConfigCreate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AIConfigDetail]:
    """创建项目 AI 配置"""
    config = await ProjectService(db).create_ai_config(id, body)
    return ApiResult.success(config)


@router.put("/projects/{id}/ai-configs/{config_id}", response_model=ApiResult[AIConfigDetail])
async def update_project_ai_config(
    id: int,
    config_id: int,
    body: AIConfigUpdate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AIConfigDetail]:
    """更新项目 AI 配置"""
    config = await ProjectService(db).update_ai_config(id, config_id, body)
    return ApiResult.success(config)


@router.delete("/projects/{id}/ai-configs/{config_id}", response_model=ApiResult[None])
async def delete_project_ai_config(
    id: int,
    config_id: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """删除项目 AI 配置"""
    await ProjectService(db).delete_ai_config(id, config_id)
    return ApiResult.success(None)


@router.get("/ai/providers", response_model=ApiResult[list[AIProviderOption]])
async def list_ai_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AIProviderOption]]:
    """查询 AI 厂商模型选项"""
    providers = await ProjectService(db).list_ai_providers()
    return ApiResult.success(providers)
