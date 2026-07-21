"""
账号与用户服务

功能说明:
    承载第一阶段账号相关业务逻辑，包括注册、登录、个人资料、
    管理员创建用户和平台角色更新。

设计约束:
    - Router 只负责 HTTP 参数和响应封装，业务规则集中在 Service。
    - 密码只存储 bcrypt 哈希。
    - 第一阶段权限采用平台角色最小实现，完整 RBAC 留到后续阶段。
"""

from __future__ import annotations

import secrets
import string

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.security import create_access_token, hash_password, verify_password
from app.models.project import ProjectMember
from app.models.user import User
from app.schemas.auth import (
    CreateUserRequest,
    RegisterRequest,
    UpdateAgentTypesRequest,
    UpdatePlatformRoleRequest,
    UpdateProfileRequest,
    UserProfile,
)


def user_to_profile(user: User) -> UserProfile:
    """
    将 ORM 用户对象转换为 API 用户资料。

    参数说明:
        user (User): 数据库用户对象。

    返回值:
        UserProfile: 前端可直接消费的 camelCase 用户资料。
    """
    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        nickname=user.nickname,
        avatar=user.avatar,
        agent_types=user.agent_types,
        platform_role=user.platform_role,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class AuthService:
    """账号服务，封装用户相关数据库操作"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_id(self, user_id: int) -> User:
        """
        根据 ID 获取用户。

        异常说明:
            HTTPException(404): 用户不存在。
        """
        user = await self.db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    async def get_user_by_username(self, username: str) -> User | None:
        """根据用户名查询用户，不存在时返回 None"""
        result = await self.db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def register(self, body: RegisterRequest) -> tuple[str, UserProfile]:
        """
        注册用户并返回登录态。

        参数说明:
            body: 注册请求，包含 username/email/password/nickname。

        返回值:
            tuple[str, UserProfile]: JWT token 和用户资料。

        异常说明:
            HTTPException(409): 用户名或邮箱已存在。
        """
        existing = await self._find_by_username_or_email(body.username, body.email)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在")

        user = User(
            username=body.username,
            email=body.email,
            password=hash_password(body.password),
            nickname=body.nickname or body.username,
            platform_role="member",
            agent_types="",
            must_change_password=False,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        token = create_access_token(user.id, user.username)
        return token, user_to_profile(user)

    async def login(self, username: str, password: str) -> tuple[str, UserProfile]:
        """
        用户登录。

        异常说明:
            HTTPException(401): 用户不存在或密码错误。
        """
        user = await self.get_user_by_username(username)
        if user is None or not verify_password(password, user.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        token = create_access_token(user.id, user.username)
        return token, user_to_profile(user)

    async def update_profile(self, current_user: User, body: UpdateProfileRequest) -> UserProfile:
        """
        更新当前用户资料。

        参数说明:
            current_user: 当前登录用户。
            body: 可更新 nickname/avatar/agentTypes。
        """
        if body.nickname is not None:
            current_user.nickname = body.nickname
        if body.avatar is not None:
            current_user.avatar = body.avatar
        if body.agentTypes is not None:
            current_user.agent_types = body.agentTypes
        await self.db.flush()
        await self.db.refresh(current_user)
        return user_to_profile(current_user)

    async def update_my_agent_types(
        self,
        current_user: User,
        body: UpdateAgentTypesRequest,
    ) -> UserProfile:
        """更新当前用户绑定的 Agent 身份"""
        current_user.agent_types = ",".join(body.agentTypes)
        await self.db.flush()
        await self.db.refresh(current_user)
        return user_to_profile(current_user)

    async def change_password(self, current_user: User, current_password: str, new_password: str) -> None:
        """
        修改当前用户密码。

        异常说明:
            HTTPException(400): 当前密码为空或不匹配。
        """
        if not current_password or not verify_password(current_password, current_user.password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
        current_user.password = hash_password(new_password)
        current_user.must_change_password = False
        await self.db.flush()

    async def list_users(self, page: int, size: int, keyword: str | None = None) -> tuple[list[UserProfile], int]:
        """
        分页查询用户。

        参数说明:
            page: 页码，从 1 开始。
            size: 每页条数。
            keyword: 用户名/邮箱/昵称模糊搜索。
        """
        stmt: Select[tuple[User]] = select(User)
        count_stmt = select(func.count()).select_from(User)
        if keyword:
            condition = or_(
                User.username.ilike(f"%{keyword}%"),
                User.email.ilike(f"%{keyword}%"),
                User.nickname.ilike(f"%{keyword}%"),
            )
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)
        stmt = stmt.order_by(User.id.desc()).offset((page - 1) * size).limit(size)

        total = int(await self.db.scalar(count_stmt) or 0)
        users = (await self.db.execute(stmt)).scalars().all()
        return [user_to_profile(user) for user in users], total

    async def create_user(self, body: CreateUserRequest) -> tuple[UserProfile, str]:
        """
        管理员创建用户。

        返回值:
            tuple[UserProfile, str]: 新用户资料和临时密码。
        """
        existing = await self._find_by_username_or_email(body.username, body.email)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已存在")

        temporary_password = body.password or self._generate_temp_password()
        user = User(
            username=body.username,
            email=body.email,
            password=hash_password(temporary_password),
            nickname=body.nickname or body.username,
            platform_role=body.platformRole,
            agent_types="",
            must_change_password=body.password is None,
        )
        self.db.add(user)
        await self.db.flush()

        for project_id in body.projectIds:
            self.db.add(
                ProjectMember(
                    project_id=project_id,
                    user_id=user.id,
                    role=body.projectRole or "developer",
                )
            )
        await self.db.flush()
        await self.db.refresh(user)
        return user_to_profile(user), temporary_password

    async def update_user_agent_types(self, user_id: int, body: UpdateAgentTypesRequest) -> UserProfile:
        """管理员更新指定用户 Agent 身份"""
        user = await self.get_user_by_id(user_id)
        user.agent_types = ",".join(body.agentTypes)
        await self.db.flush()
        await self.db.refresh(user)
        return user_to_profile(user)

    async def update_platform_role(
        self,
        user_id: int,
        body: UpdatePlatformRoleRequest,
    ) -> UserProfile:
        """管理员更新指定用户的平台角色"""
        user = await self.get_user_by_id(user_id)
        user.platform_role = body.platformRole
        await self.db.flush()
        await self.db.refresh(user)
        return user_to_profile(user)

    async def reset_password(self, user_id: int) -> str:
        """管理员重置用户密码并返回临时密码"""
        user = await self.get_user_by_id(user_id)
        temporary_password = self._generate_temp_password()
        user.password = hash_password(temporary_password)
        user.must_change_password = True
        await self.db.flush()
        return temporary_password

    async def _find_by_username_or_email(self, username: str, email: str) -> User | None:
        """按用户名或邮箱查重"""
        result = await self.db.execute(
            select(User).where(or_(User.username == username, User.email == email))
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _generate_temp_password(length: int = 12) -> str:
        """
        生成临时密码。

        返回值:
            str: 包含字母和数字的临时密码。
        """
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))
