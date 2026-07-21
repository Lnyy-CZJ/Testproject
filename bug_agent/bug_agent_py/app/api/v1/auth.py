"""
认证与用户 API

功能说明:
    实现第一阶段账号、个人资料和用户管理接口。所有响应统一使用
    ApiResult，保持 Go 版前端契约。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequirePermission, get_current_user
from app.infrastructure.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    TempPasswordResponse,
    UpdateAgentTypesRequest,
    UpdatePlatformRoleRequest,
    UpdateProfileRequest,
    UserProfile,
)
from app.schemas.common import ApiResult, PaginatedResponse
from app.services.auth_service import AuthService, user_to_profile

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=ApiResult[LoginResponse])
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResult[LoginResponse]:
    """
    注册用户。

    功能说明:
        创建普通平台成员并直接返回登录 Token。
    """
    token, user = await AuthService(db).register(body)
    return ApiResult.success(LoginResponse(token=token, user=user))


@router.post("/auth/login", response_model=ApiResult[LoginResponse])
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResult[LoginResponse]:
    """用户名密码登录"""
    token, user = await AuthService(db).login(body.username, body.password)
    return ApiResult.success(LoginResponse(token=token, user=user))


@router.post("/auth/logout", response_model=ApiResult[None])
async def logout(current_user: User = Depends(get_current_user)) -> ApiResult[None]:
    """
    登出接口。

    第一阶段暂不写 Token 黑名单，保留兼容入口。
    """
    return ApiResult.success(None)


@router.get("/users/me", response_model=ApiResult[UserProfile])
async def get_profile(current_user: User = Depends(get_current_user)) -> ApiResult[UserProfile]:
    """获取当前用户资料"""
    return ApiResult.success(user_to_profile(current_user))


@router.put("/users/me", response_model=ApiResult[UserProfile])
async def update_profile(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[UserProfile]:
    """更新当前用户资料"""
    profile = await AuthService(db).update_profile(current_user, body)
    return ApiResult.success(profile)


@router.put("/users/me/password", response_model=ApiResult[None])
async def change_my_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """修改当前用户密码"""
    await AuthService(db).change_password(
        current_user=current_user,
        current_password=body.current_password_value(),
        new_password=body.newPassword,
    )
    return ApiResult.success(None)


@router.put("/users/me/agent-types", response_model=ApiResult[UserProfile])
async def update_my_agent_types(
    body: UpdateAgentTypesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[UserProfile]:
    """更新当前用户 Agent 身份"""
    profile = await AuthService(db).update_my_agent_types(current_user, body)
    return ApiResult.success(profile)


@router.get("/users", response_model=ApiResult[PaginatedResponse[UserProfile]])
async def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    _: bool = Depends(RequirePermission("users:read")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[PaginatedResponse[UserProfile]]:
    """分页查询用户"""
    users, total = await AuthService(db).list_users(page=page, size=size, keyword=keyword)
    return ApiResult.success(PaginatedResponse.from_items(users, total, page, size))


@router.get("/users/{user_id}", response_model=ApiResult[UserProfile])
async def get_user(
    user_id: int,
    _: bool = Depends(RequirePermission("users:read")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[UserProfile]:
    """获取指定用户详情"""
    user = await AuthService(db).get_user_by_id(user_id)
    return ApiResult.success(user_to_profile(user))


@router.post("/users", response_model=ApiResult[TempPasswordResponse])
async def create_user(
    body: CreateUserRequest,
    _: bool = Depends(RequirePermission("users:manage")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[TempPasswordResponse]:
    """管理员创建用户"""
    _, temporary_password = await AuthService(db).create_user(body)
    return ApiResult.success(TempPasswordResponse(temporaryPassword=temporary_password))


@router.put("/users/{user_id}/agent-types", response_model=ApiResult[UserProfile])
async def update_user_agent_types(
    user_id: int,
    body: UpdateAgentTypesRequest,
    _: bool = Depends(RequirePermission("users:manage")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[UserProfile]:
    """管理员更新用户 Agent 身份"""
    profile = await AuthService(db).update_user_agent_types(user_id, body)
    return ApiResult.success(profile)


@router.put("/users/{user_id}/platform-role", response_model=ApiResult[UserProfile])
async def update_user_platform_role(
    user_id: int,
    body: UpdatePlatformRoleRequest,
    _: bool = Depends(RequirePermission("users:manage")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[UserProfile]:
    """管理员更新用户平台角色"""
    profile = await AuthService(db).update_platform_role(user_id, body)
    return ApiResult.success(profile)


@router.post("/users/{user_id}/reset-password", response_model=ApiResult[TempPasswordResponse])
async def reset_user_password(
    user_id: int,
    _: bool = Depends(RequirePermission("users:manage")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[TempPasswordResponse]:
    """管理员重置用户密码"""
    temporary_password = await AuthService(db).reset_password(user_id)
    return ApiResult.success(TempPasswordResponse(temporaryPassword=temporary_password))
