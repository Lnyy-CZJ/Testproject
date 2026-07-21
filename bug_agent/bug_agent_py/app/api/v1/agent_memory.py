"""
Agent 记忆 API

功能说明:
    提供项目级和迭代级 Agent 记忆的新增、查询、编辑、删除和启禁用接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireProjectPermission, get_current_user
from app.infrastructure.database import get_db
from app.models.user import User
from app.schemas.agent import AgentMemoryCreate, AgentMemoryDetail, AgentMemoryUpdate
from app.schemas.common import ApiResult
from app.services.memory_service import AgentMemoryService

router = APIRouter(tags=["agent_memory"])


@router.get("/projects/{id}/memories", response_model=ApiResult[list[AgentMemoryDetail]])
async def list_project_memories(
    id: int,
    category: str | None = Query(default=None),
    _: bool = Depends(RequireProjectPermission("memories:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AgentMemoryDetail]]:
    """查询项目级 Agent 记忆"""
    memories = await AgentMemoryService(db).list_memories(id, category=category)
    return ApiResult.success(memories)


@router.post("/projects/{id}/memories", response_model=ApiResult[AgentMemoryDetail])
async def create_project_memory(
    id: int,
    body: AgentMemoryCreate,
    _: bool = Depends(RequireProjectPermission("memories:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AgentMemoryDetail]:
    """创建项目级 Agent 记忆"""
    memory = await AgentMemoryService(db).create_memory(id, None, body, current_user.id)
    return ApiResult.success(memory)


@router.get(
    "/projects/{id}/iterations/{iteration_id}/memories",
    response_model=ApiResult[list[AgentMemoryDetail]],
)
async def list_iteration_memories(
    id: int,
    iteration_id: int,
    category: str | None = Query(default=None),
    _: bool = Depends(RequireProjectPermission("memories:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[AgentMemoryDetail]]:
    """查询迭代级 Agent 记忆"""
    memories = await AgentMemoryService(db).list_memories(id, iteration_id, category)
    return ApiResult.success(memories)


@router.post(
    "/projects/{id}/iterations/{iteration_id}/memories",
    response_model=ApiResult[AgentMemoryDetail],
)
async def create_iteration_memory(
    id: int,
    iteration_id: int,
    body: AgentMemoryCreate,
    _: bool = Depends(RequireProjectPermission("memories:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AgentMemoryDetail]:
    """创建迭代级 Agent 记忆"""
    memory = await AgentMemoryService(db).create_memory(id, iteration_id, body, current_user.id)
    return ApiResult.success(memory)


@router.put("/projects/{id}/memories/{memory_id}", response_model=ApiResult[AgentMemoryDetail])
async def update_memory(
    id: int,
    memory_id: int,
    body: AgentMemoryUpdate,
    _: bool = Depends(RequireProjectPermission("memories:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AgentMemoryDetail]:
    """更新 Agent 记忆"""
    memory = await AgentMemoryService(db).update_memory(memory_id, body)
    return ApiResult.success(memory)


@router.delete("/projects/{id}/memories/{memory_id}", response_model=ApiResult[None])
async def delete_memory(
    id: int,
    memory_id: int,
    _: bool = Depends(RequireProjectPermission("memories:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """删除 Agent 记忆"""
    await AgentMemoryService(db).delete_memory(memory_id)
    return ApiResult.success(None)


@router.patch("/projects/{id}/memories/{memory_id}/toggle", response_model=ApiResult[AgentMemoryDetail])
async def toggle_memory(
    id: int,
    memory_id: int,
    _: bool = Depends(RequireProjectPermission("memories:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[AgentMemoryDetail]:
    """启用或禁用 Agent 记忆"""
    memory = await AgentMemoryService(db).toggle_memory(memory_id)
    return ApiResult.success(memory)
