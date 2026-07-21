"""
项目相关 Pydantic Schema

与 Go 版 API 响应格式完全兼容，字段使用 camelCase。
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """创建项目请求"""
    name: str = Field(..., max_length=100, description="项目名称")
    code: str | None = Field(default=None, max_length=50, description="前端传入的项目编码，当前兼容接收")
    description: str | None = Field(default=None, description="项目描述")


class ProjectUpdate(BaseModel):
    """更新项目请求"""
    name: str | None = Field(default=None, max_length=100)
    description: str | None = None
    status: str | None = None
    memoryEnabled: bool | None = Field(default=None, alias="memory_enabled")

    model_config = {"populate_by_name": True}


class ProjectDetail(BaseModel):
    """项目详情"""
    id: int
    name: str
    description: str | None = None
    ownerId: int = Field(alias="owner_id")
    status: str = "active"
    memoryEnabled: bool = Field(default=False, alias="memory_enabled")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class ProjectMemberItem(BaseModel):
    """项目成员"""
    id: int
    userId: int = Field(alias="user_id")
    username: str = ""
    nickname: str = ""
    role: str
    agentTypes: str | None = Field(default=None, alias="agent_types")

    model_config = {"populate_by_name": True}


class ProjectListItem(ProjectDetail):
    """项目列表项"""
    pass


class AddProjectMemberRequest(BaseModel):
    """添加项目成员请求"""
    userId: int = Field(..., alias="user_id")
    role: str = Field(default="developer")

    model_config = {"populate_by_name": True}


class ProjectDetailResponse(BaseModel):
    """项目详情响应，兼容前端 ProjectDetail 类型"""
    project: ProjectDetail
    members: list[ProjectMemberItem] = Field(default_factory=list)
    iterations: list["IterationDetail"] = Field(default_factory=list)


class ProjectStats(BaseModel):
    """项目统计"""
    total: int = 0
    pending: int = 0
    fixing: int = 0
    completed: int = 0
    urgent: int = 0
    totalDefects: int = 0
    pendingDefects: int = 0
    inProgressDefects: int = 0
    completedDefects: int = 0
    urgentDefects: int = 0

    model_config = {"populate_by_name": True}


class IterationCreate(BaseModel):
    """创建迭代请求"""
    name: str = Field(..., max_length=100, description="迭代名称")
    startDate: date | None = Field(default=None, alias="start_date")
    endDate: date | None = Field(default=None, alias="end_date")
    goal: str | None = Field(default=None, description="前端传入的迭代目标，当前兼容接收")

    model_config = {"populate_by_name": True}


class IterationDetail(BaseModel):
    """迭代详情"""
    id: int
    projectId: int = Field(alias="project_id")
    name: str
    startDate: date | None = Field(default=None, alias="start_date")
    endDate: date | None = Field(default=None, alias="end_date")
    status: str = "planning"
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime | None = Field(default=None, alias="updated_at")

    model_config = {"populate_by_name": True}


class IterationUpdate(BaseModel):
    """更新迭代请求"""
    name: str | None = Field(default=None, max_length=100)
    startDate: date | None = Field(default=None, alias="start_date")
    endDate: date | None = Field(default=None, alias="end_date")
    status: str | None = None
    goal: str | None = None

    model_config = {"populate_by_name": True}


class IterationRepoItem(BaseModel):
    """迭代仓库绑定项"""
    id: int
    iterationId: int = Field(alias="iteration_id")
    repoId: int = Field(alias="repo_id")
    branch: str | None = None
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True}


class IterationDetailResponse(BaseModel):
    """迭代详情响应，兼容前端 IterationDetail 类型"""
    iteration: IterationDetail
    repos: list[IterationRepoItem] = Field(default_factory=list)
    defectStats: dict[str, int] = Field(
        default_factory=lambda: {"total": 0, "pending": 0, "fixing": 0, "completed": 0}
    )


class BindRepoRequest(BaseModel):
    """绑定迭代仓库请求"""
    repoId: int = Field(..., alias="repo_id")
    branch: str | None = None

    model_config = {"populate_by_name": True}


class UpdateIterationRepoBranchRequest(BaseModel):
    """更新迭代仓库分支请求"""
    branch: str = Field(..., max_length=100)


class RepoCreate(BaseModel):
    """创建仓库请求"""
    name: str = Field(..., max_length=100, description="仓库名称")
    repoUrl: str = Field(..., alias="repo_url", max_length=500, description="仓库地址")
    description: str | None = Field(default=None, description="仓库描述")
    defaultBranch: str | None = Field(default="main", alias="default_branch")
    vcsProvider: str | None = Field(default="github", alias="vcs_provider")
    sourceType: str | None = Field(default=None, alias="source_type", description="前端来源类型，兼容接收")
    credentialId: int | None = Field(default=None, alias="credential_id")
    agentTypes: str | None = Field(default=None, alias="agent_types")

    model_config = {"populate_by_name": True}


class RepoUpdate(BaseModel):
    """更新仓库请求"""
    name: str | None = Field(default=None, max_length=100)
    repoUrl: str | None = Field(default=None, alias="repo_url", max_length=500)
    description: str | None = None
    defaultBranch: str | None = Field(default=None, alias="default_branch")
    vcsProvider: str | None = Field(default=None, alias="vcs_provider")
    credentialId: int | None = Field(default=None, alias="credential_id")

    model_config = {"populate_by_name": True}


class RepoDetail(BaseModel):
    """项目仓库详情"""
    id: int
    projectId: int = Field(alias="project_id")
    name: str
    repoUrl: str = Field(alias="repo_url")
    description: str | None = None
    defaultBranch: str | None = Field(default="main", alias="default_branch")
    vcsProvider: str | None = Field(default="github", alias="vcs_provider")
    credentialId: int | None = Field(default=None, alias="credential_id")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class AIConfigCreate(BaseModel):
    """创建 AI 配置请求"""
    provider: str = Field(..., max_length=50, description="AI 厂商")
    modelName: str = Field(..., alias="model_name", max_length=100, description="模型名称")
    apiKey: str = Field(..., alias="api_key", description="API 密钥")
    apiEndpoint: str | None = Field(default=None, alias="api_endpoint")
    isDefault: bool = Field(default=False, alias="is_default")
    functionCallingMode: str = Field(default="auto", alias="function_calling_mode")

    model_config = {"populate_by_name": True}


class AIConfigUpdate(BaseModel):
    """更新 AI 配置请求"""
    provider: str | None = Field(default=None, max_length=50)
    modelName: str | None = Field(default=None, alias="model_name", max_length=100)
    apiKey: str | None = Field(default=None, alias="api_key")
    apiEndpoint: str | None = Field(default=None, alias="api_endpoint")
    isDefault: bool | None = Field(default=None, alias="is_default")
    functionCallingMode: str | None = Field(default=None, alias="function_calling_mode")

    model_config = {"populate_by_name": True}


class AIConfigDetail(BaseModel):
    """项目 AI 配置详情"""
    id: int
    projectId: int = Field(alias="project_id")
    provider: str
    modelName: str = Field(alias="model_name")
    apiKey: str = Field(alias="api_key")
    apiEndpoint: str | None = Field(default=None, alias="api_endpoint")
    isDefault: bool = Field(default=False, alias="is_default")
    functionCallingMode: str = Field(default="auto", alias="function_calling_mode")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class AIProviderOption(BaseModel):
    """前端 AI 厂商选项"""
    providerKey: str
    displayName: str
    defaultEndpoint: str | None = None
    models: list[dict] = Field(default_factory=list)
