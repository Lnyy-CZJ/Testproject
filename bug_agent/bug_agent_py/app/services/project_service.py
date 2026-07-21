"""
项目域服务

功能说明:
    实现第一阶段项目、成员、迭代、仓库和项目 AI 配置的基础 CRUD。

设计约束:
    - 保持前端 API 契约，不要求前端改字段名。
    - 只实现第一阶段基础项目域，不进入缺陷、Agent、修复链路。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.security import aes_encrypt, mask_key
from app.config import settings
from app.models.catalog import AIModelCatalog, AIProviderCatalog
from app.models.project import (
    Iteration,
    IterationRepo,
    Project,
    ProjectAIConfig,
    ProjectMember,
    ProjectRepo,
)
from app.models.user import User
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
    ProjectDetail,
    ProjectDetailResponse,
    ProjectMemberItem,
    ProjectStats,
    ProjectUpdate,
    RepoCreate,
    RepoDetail,
    RepoUpdate,
    UpdateIterationRepoBranchRequest,
)


def project_to_detail(project: Project) -> ProjectDetail:
    """将项目 ORM 对象转换为 API 项目详情"""
    return ProjectDetail(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        status=project.status,
        memory_enabled=project.memory_enabled,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def iteration_to_detail(iteration: Iteration) -> IterationDetail:
    """将迭代 ORM 对象转换为 API 迭代详情"""
    return IterationDetail(
        id=iteration.id,
        project_id=iteration.project_id,
        name=iteration.name,
        start_date=iteration.start_date,
        end_date=iteration.end_date,
        status=iteration.status,
        created_at=iteration.created_at,
        updated_at=iteration.updated_at,
    )


def repo_to_detail(repo: ProjectRepo) -> RepoDetail:
    """将仓库 ORM 对象转换为 API 仓库详情"""
    return RepoDetail(
        id=repo.id,
        project_id=repo.project_id,
        name=repo.name,
        repo_url=repo.repo_url,
        description=repo.description,
        default_branch=repo.default_branch,
        vcs_provider=repo.vcs_provider,
        credential_id=repo.credential_id,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
    )


def ai_config_to_detail(config: ProjectAIConfig, mask_secret: bool = True) -> AIConfigDetail:
    """将 AI 配置 ORM 对象转换为 API 详情，默认脱敏 API Key"""
    return AIConfigDetail(
        id=config.id,
        project_id=config.project_id,
        provider=config.provider,
        model_name=config.model_name,
        api_key=mask_key(config.api_key) if mask_secret else config.api_key,
        api_endpoint=config.api_endpoint,
        is_default=config.is_default,
        function_calling_mode=config.function_calling_mode,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


class ProjectService:
    """项目域服务，封装项目相关数据库操作"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_projects(self, current_user: User, page: int, size: int) -> tuple[list[ProjectDetail], int]:
        """
        查询当前用户可见项目。

        平台管理员可见全部项目，普通用户只看自己拥有或加入的项目。
        """
        stmt = select(Project)
        count_stmt = select(func.count()).select_from(Project)
        if current_user.platform_role not in {"super_admin", "admin"}:
            member_project_ids = select(ProjectMember.project_id).where(
                ProjectMember.user_id == current_user.id
            )
            stmt = stmt.where((Project.owner_id == current_user.id) | (Project.id.in_(member_project_ids)))
            count_stmt = count_stmt.where(
                (Project.owner_id == current_user.id) | (Project.id.in_(member_project_ids))
            )
        stmt = stmt.order_by(Project.id.desc()).offset((page - 1) * size).limit(size)
        total = int(await self.db.scalar(count_stmt) or 0)
        projects = (await self.db.execute(stmt)).scalars().all()
        return [project_to_detail(project) for project in projects], total

    async def create_project(self, current_user: User, name: str, description: str | None) -> ProjectDetail:
        """
        创建项目，并自动把创建人加入项目管理员。
        """
        project = Project(
            name=name,
            description=description,
            owner_id=current_user.id,
            status="active",
            memory_enabled=False,
        )
        self.db.add(project)
        await self.db.flush()
        self.db.add(ProjectMember(project_id=project.id, user_id=current_user.id, role="project_admin"))
        await self.db.flush()
        await self.db.refresh(project)
        return project_to_detail(project)

    async def get_project_detail(self, project_id: int) -> ProjectDetailResponse:
        """获取项目详情，包含成员和迭代"""
        project = await self._get_project(project_id)
        members = await self._list_project_members(project_id)
        iterations = await self.list_iterations(project_id)
        return ProjectDetailResponse(
            project=project_to_detail(project),
            members=members,
            iterations=iterations,
        )

    async def update_project(self, project_id: int, body: ProjectUpdate) -> ProjectDetail:
        """更新项目基础信息"""
        project = await self._get_project(project_id)
        if body.name is not None:
            project.name = body.name
        if body.description is not None:
            project.description = body.description
        if body.status is not None:
            project.status = body.status
        if body.memoryEnabled is not None:
            project.memory_enabled = body.memoryEnabled
        await self.db.flush()
        await self.db.refresh(project)
        return project_to_detail(project)

    async def add_member(self, project_id: int, body: AddProjectMemberRequest) -> None:
        """添加项目成员，重复添加时更新角色"""
        await self._get_project(project_id)
        user = await self.db.get(User, body.userId)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

        result = await self.db.execute(
            select(ProjectMember).where(
                and_(ProjectMember.project_id == project_id, ProjectMember.user_id == body.userId)
            )
        )
        member = result.scalar_one_or_none()
        if member is None:
            self.db.add(ProjectMember(project_id=project_id, user_id=body.userId, role=body.role))
        else:
            member.role = body.role
        await self.db.flush()

    async def remove_member(self, project_id: int, member_id: int) -> None:
        """移除项目成员"""
        member = await self.db.get(ProjectMember, member_id)
        if member is None or member.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目成员不存在")
        await self.db.delete(member)

    async def get_project_stats(self, project_id: int) -> ProjectStats:
        """获取项目统计，第一阶段缺陷域未实现时返回兼容零值"""
        await self._get_project(project_id)
        return ProjectStats()

    async def create_iteration(self, project_id: int, body: IterationCreate) -> IterationDetail:
        """创建项目迭代"""
        await self._get_project(project_id)
        iteration = Iteration(
            project_id=project_id,
            name=body.name,
            start_date=body.startDate,
            end_date=body.endDate,
            status="planning",
        )
        self.db.add(iteration)
        await self.db.flush()
        await self.db.refresh(iteration)
        return iteration_to_detail(iteration)

    async def list_iterations(self, project_id: int) -> list[IterationDetail]:
        """查询项目迭代列表"""
        result = await self.db.execute(
            select(Iteration).where(Iteration.project_id == project_id).order_by(Iteration.id.desc())
        )
        return [iteration_to_detail(iteration) for iteration in result.scalars().all()]

    async def get_iteration_detail(self, project_id: int, iteration_id: int) -> IterationDetailResponse:
        """获取迭代详情，包含绑定仓库"""
        iteration = await self._get_iteration(project_id, iteration_id)
        repos = await self._list_iteration_repos(iteration_id)
        return IterationDetailResponse(iteration=iteration_to_detail(iteration), repos=repos)

    async def update_iteration(
        self,
        project_id: int,
        iteration_id: int,
        body: IterationUpdate,
    ) -> IterationDetail:
        """更新迭代基础信息"""
        iteration = await self._get_iteration(project_id, iteration_id)
        if body.name is not None:
            iteration.name = body.name
        if body.startDate is not None:
            iteration.start_date = body.startDate
        if body.endDate is not None:
            iteration.end_date = body.endDate
        if body.status is not None:
            iteration.status = body.status
        await self.db.flush()
        await self.db.refresh(iteration)
        return iteration_to_detail(iteration)

    async def create_repo(self, project_id: int, body: RepoCreate) -> RepoDetail:
        """创建项目仓库"""
        await self._get_project(project_id)
        repo = ProjectRepo(
            project_id=project_id,
            name=body.name,
            repo_url=body.repoUrl,
            description=body.description,
            default_branch=body.defaultBranch or "main",
            vcs_provider=body.vcsProvider or body.sourceType or "github",
            credential_id=body.credentialId,
        )
        self.db.add(repo)
        await self.db.flush()
        await self.db.refresh(repo)
        return repo_to_detail(repo)

    async def list_repos(self, project_id: int) -> list[RepoDetail]:
        """查询项目仓库列表"""
        result = await self.db.execute(
            select(ProjectRepo).where(ProjectRepo.project_id == project_id).order_by(ProjectRepo.id.desc())
        )
        return [repo_to_detail(repo) for repo in result.scalars().all()]

    async def update_repo(self, project_id: int, repo_id: int, body: RepoUpdate) -> RepoDetail:
        """更新项目仓库"""
        repo = await self._get_repo(project_id, repo_id)
        if body.name is not None:
            repo.name = body.name
        if body.repoUrl is not None:
            repo.repo_url = body.repoUrl
        if body.description is not None:
            repo.description = body.description
        if body.defaultBranch is not None:
            repo.default_branch = body.defaultBranch
        if body.vcsProvider is not None:
            repo.vcs_provider = body.vcsProvider
        if body.credentialId is not None:
            repo.credential_id = body.credentialId
        await self.db.flush()
        await self.db.refresh(repo)
        return repo_to_detail(repo)

    async def delete_repo(self, project_id: int, repo_id: int) -> None:
        """删除项目仓库"""
        repo = await self._get_repo(project_id, repo_id)
        await self.db.delete(repo)

    async def bind_repo(
        self,
        project_id: int,
        iteration_id: int,
        body: BindRepoRequest,
    ) -> IterationRepoItem:
        """绑定仓库到迭代"""
        await self._get_iteration(project_id, iteration_id)
        await self._get_repo(project_id, body.repoId)
        binding = IterationRepo(iteration_id=iteration_id, repo_id=body.repoId, branch=body.branch)
        self.db.add(binding)
        await self.db.flush()
        await self.db.refresh(binding)
        return IterationRepoItem(
            id=binding.id,
            iteration_id=binding.iteration_id,
            repo_id=binding.repo_id,
            branch=binding.branch,
            created_at=binding.created_at,
        )

    async def unbind_repo(self, project_id: int, iteration_id: int, repo_id: int) -> None:
        """解除迭代仓库绑定"""
        await self._get_iteration(project_id, iteration_id)
        result = await self.db.execute(
            select(IterationRepo).where(
                and_(IterationRepo.iteration_id == iteration_id, IterationRepo.repo_id == repo_id)
            )
        )
        binding = result.scalar_one_or_none()
        if binding is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="迭代仓库绑定不存在")
        await self.db.delete(binding)

    async def update_iteration_repo_branch(
        self,
        project_id: int,
        iteration_id: int,
        iter_repo_id: int,
        body: UpdateIterationRepoBranchRequest,
    ) -> dict[str, int | str]:
        """更新迭代仓库绑定分支"""
        await self._get_iteration(project_id, iteration_id)
        binding = await self.db.get(IterationRepo, iter_repo_id)
        if binding is None or binding.iteration_id != iteration_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="迭代仓库绑定不存在")
        binding.branch = body.branch
        await self.db.flush()
        return {"branch": body.branch, "projectId": project_id}

    async def list_repo_branches(self, project_id: int, repo_id: int) -> list[str]:
        """查询仓库分支。第一阶段不连接远端仓库，返回默认分支兼容前端。"""
        repo = await self._get_repo(project_id, repo_id)
        return [repo.default_branch or "main"]

    async def list_ai_configs(self, project_id: int) -> list[AIConfigDetail]:
        """查询项目 AI 配置列表"""
        result = await self.db.execute(
            select(ProjectAIConfig)
            .where(ProjectAIConfig.project_id == project_id)
            .order_by(ProjectAIConfig.id.desc())
        )
        return [ai_config_to_detail(config) for config in result.scalars().all()]

    async def create_ai_config(self, project_id: int, body: AIConfigCreate) -> AIConfigDetail:
        """创建项目 AI 配置"""
        await self._get_project(project_id)
        await self._clear_default_ai_config(project_id, body.isDefault)
        config = ProjectAIConfig(
            project_id=project_id,
            provider=body.provider,
            model_name=body.modelName,
            api_key=aes_encrypt(body.apiKey, settings.secrets.ai_config_encryption_key),
            api_endpoint=body.apiEndpoint,
            is_default=body.isDefault,
            function_calling_mode=body.functionCallingMode,
        )
        self.db.add(config)
        await self.db.flush()
        await self.db.refresh(config)
        return ai_config_to_detail(config)

    async def update_ai_config(
        self,
        project_id: int,
        config_id: int,
        body: AIConfigUpdate,
    ) -> AIConfigDetail:
        """更新项目 AI 配置"""
        config = await self._get_ai_config(project_id, config_id)
        if body.provider is not None:
            config.provider = body.provider
        if body.modelName is not None:
            config.model_name = body.modelName
        if body.apiKey is not None:
            config.api_key = aes_encrypt(body.apiKey, settings.secrets.ai_config_encryption_key)
        if body.apiEndpoint is not None:
            config.api_endpoint = body.apiEndpoint
        if body.functionCallingMode is not None:
            config.function_calling_mode = body.functionCallingMode
        if body.isDefault is not None:
            await self._clear_default_ai_config(project_id, body.isDefault)
            config.is_default = body.isDefault
        await self.db.flush()
        await self.db.refresh(config)
        return ai_config_to_detail(config)

    async def delete_ai_config(self, project_id: int, config_id: int) -> None:
        """删除项目 AI 配置"""
        config = await self._get_ai_config(project_id, config_id)
        await self.db.delete(config)

    async def list_ai_providers(self) -> list[AIProviderOption]:
        """查询 AI 厂商选项，数据库为空时返回内置默认值"""
        providers = (await self.db.execute(select(AIProviderCatalog))).scalars().all()
        if not providers:
            return [
                AIProviderOption(providerKey="openai", displayName="OpenAI"),
                AIProviderOption(providerKey="anthropic", displayName="Anthropic"),
                AIProviderOption(providerKey="deepseek", displayName="DeepSeek"),
                AIProviderOption(providerKey="zhipu", displayName="智谱"),
                AIProviderOption(providerKey="dashscope", displayName="DashScope"),
            ]

        models = (await self.db.execute(select(AIModelCatalog))).scalars().all()
        models_by_provider: dict[str, list[dict]] = {}
        for model in models:
            models_by_provider.setdefault(model.provider_key, []).append(
                {"modelName": model.model_name, "supportsFc": model.supports_fc}
            )
        return [
            AIProviderOption(
                providerKey=provider.provider_key,
                displayName=provider.name,
                defaultEndpoint=provider.default_endpoint,
                models=models_by_provider.get(provider.provider_key, []),
            )
            for provider in providers
        ]

    async def _list_project_members(self, project_id: int) -> list[ProjectMemberItem]:
        """查询项目成员并补充用户展示信息"""
        result = await self.db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.id.asc())
        )
        return [
            ProjectMemberItem(
                id=member.id,
                user_id=member.user_id,
                username=user.username,
                nickname=user.nickname or "",
                role=member.role,
                agent_types=user.agent_types,
            )
            for member, user in result.all()
        ]

    async def _list_iteration_repos(self, iteration_id: int) -> list[IterationRepoItem]:
        """查询迭代仓库绑定列表"""
        result = await self.db.execute(
            select(IterationRepo).where(IterationRepo.iteration_id == iteration_id)
        )
        return [
            IterationRepoItem(
                id=binding.id,
                iteration_id=binding.iteration_id,
                repo_id=binding.repo_id,
                branch=binding.branch,
                created_at=binding.created_at,
            )
            for binding in result.scalars().all()
        ]

    async def _get_project(self, project_id: int) -> Project:
        """获取项目，不存在时返回 404"""
        project = await self.db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return project

    async def _get_iteration(self, project_id: int, iteration_id: int) -> Iteration:
        """获取迭代并校验归属项目"""
        iteration = await self.db.get(Iteration, iteration_id)
        if iteration is None or iteration.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="迭代不存在")
        return iteration

    async def _get_repo(self, project_id: int, repo_id: int) -> ProjectRepo:
        """获取仓库并校验归属项目"""
        repo = await self.db.get(ProjectRepo, repo_id)
        if repo is None or repo.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仓库不存在")
        return repo

    async def _get_ai_config(self, project_id: int, config_id: int) -> ProjectAIConfig:
        """获取 AI 配置并校验归属项目"""
        config = await self.db.get(ProjectAIConfig, config_id)
        if config is None or config.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 配置不存在")
        return config

    async def _clear_default_ai_config(self, project_id: int, should_clear: bool) -> None:
        """当新配置设为默认时，清理同项目其他默认配置"""
        if not should_clear:
            return
        result = await self.db.execute(
            select(ProjectAIConfig).where(
                and_(ProjectAIConfig.project_id == project_id, ProjectAIConfig.is_default.is_(True))
            )
        )
        for config in result.scalars().all():
            config.is_default = False
