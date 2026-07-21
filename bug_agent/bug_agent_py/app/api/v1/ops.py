"""
上线门禁与运维 API

功能说明:
    提供第六阶段灰度上线前的生产预检、双跑比较和回滚计划查询入口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import RequirePermission
from app.schemas.common import ApiResult
from app.schemas.ops import (
    DualRunCompareRequest,
    DualRunCompareResponse,
    PreflightCheckDetail,
    PreflightReportDetail,
    RollbackPlanResponse,
)
from scripts.dual_run_compare import compare_response_pair
from scripts.preflight_check import run_preflight_checks

router = APIRouter(tags=["ops"])


@router.get("/ops/preflight", response_model=ApiResult[PreflightReportDetail])
async def run_preflight(
    _: bool = Depends(RequirePermission("system:read")),
) -> ApiResult[PreflightReportDetail]:
    """
    运行生产上线预检。

    权限说明:
        仅平台管理员可执行，避免普通成员读取环境配置状态。
    """
    report = run_preflight_checks()
    return ApiResult.success(
        PreflightReportDetail(
            passed=report.passed,
            checks=[
                PreflightCheckDetail(key=item.key, passed=item.passed, message=item.message)
                for item in report.checks
            ],
        )
    )


@router.post("/ops/dual-run/compare", response_model=ApiResult[DualRunCompareResponse])
async def compare_dual_run(
    body: DualRunCompareRequest,
    _: bool = Depends(RequirePermission("system:read")),
) -> ApiResult[DualRunCompareResponse]:
    """比较 Go/Python 双跑响应兼容性"""
    result = compare_response_pair(body.goResponse, body.pythonResponse)
    return ApiResult.success(
        DualRunCompareResponse(compatible=result.compatible, differences=result.differences)
    )


@router.get("/ops/rollback-plan", response_model=ApiResult[RollbackPlanResponse])
async def get_rollback_plan(
    _: bool = Depends(RequirePermission("system:read")),
) -> ApiResult[RollbackPlanResponse]:
    """查询灰度回滚计划"""
    return ApiResult.success(
        RollbackPlanResponse(
            strategy="切流回 Go 版服务，数据库保持兼容前滚状态",
            requiresDatabaseRollback=False,
            steps=[
                "停止继续放量 Python 服务",
                "将网关或负载均衡流量切回 Go 服务池",
                "保留 Python 服务只读观察 30 分钟",
                "确认 Go 服务错误率、延迟和核心流程恢复正常",
            ],
            verification=[
                "healthz/readyz 均正常",
                "登录、项目、缺陷、分析、修复核心接口可访问",
                "schema diff 无阻断差异",
                "无需执行数据库回滚脚本",
            ],
        )
    )
