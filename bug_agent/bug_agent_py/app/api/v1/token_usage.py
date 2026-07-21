"""
Token 用量统计 API

功能说明:
    提供缺陷、项目和迭代维度的 Token/费用统计查询。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireDefectPermission, RequireProjectPermission
from app.infrastructure.database import get_db
from app.schemas.agent import TokenUsageDetail, TokenUsageSummary
from app.schemas.common import ApiResult
from app.services.token_usage_service import TokenUsageService

router = APIRouter(tags=["token_usage"])


@router.get("/defects/{id}/token-usage", response_model=ApiResult[TokenUsageSummary])
async def get_defect_token_usage(
    id: int,
    _: bool = Depends(RequireDefectPermission("token_usage:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[TokenUsageSummary]:
    """查询单个缺陷 Token 汇总"""
    summary = await TokenUsageService(db).summarize(defect_id=id)
    return ApiResult.success(summary)


@router.get("/defects/{id}/token-usage/details", response_model=ApiResult[list[TokenUsageDetail]])
async def list_defect_token_usage_details(
    id: int,
    _: bool = Depends(RequireDefectPermission("token_usage:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[TokenUsageDetail]]:
    """查询单个缺陷 Token 明细"""
    details = await TokenUsageService(db).list_details(defect_id=id)
    return ApiResult.success(details)


@router.get("/projects/{id}/token-usage", response_model=ApiResult[TokenUsageSummary])
async def get_project_token_usage(
    id: int,
    _: bool = Depends(RequireProjectPermission("token_usage:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[TokenUsageSummary]:
    """查询项目 Token 汇总"""
    summary = await TokenUsageService(db).summarize(project_id=id)
    return ApiResult.success(summary)


@router.get("/projects/{id}/token-usage/by-iteration", response_model=ApiResult[list[dict]])
async def get_project_token_usage_by_iteration(
    id: int,
    _: bool = Depends(RequireProjectPermission("token_usage:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[dict]]:
    """按迭代聚合项目 Token 用量"""
    rows = await TokenUsageService(db).group_by_iteration(id)
    return ApiResult.success(rows)


@router.get("/projects/{id}/token-usage/by-defect", response_model=ApiResult[list[dict]])
async def get_project_token_usage_by_defect(
    id: int,
    _: bool = Depends(RequireProjectPermission("token_usage:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[dict]]:
    """按缺陷聚合项目 Token 用量"""
    rows = await TokenUsageService(db).group_by_defect(id)
    return ApiResult.success(rows)
