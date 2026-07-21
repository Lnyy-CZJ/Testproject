"""
上线门禁与运维 Schema

功能说明:
    定义第六阶段双跑验证、生产预检和回滚计划接口的数据结构。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PreflightCheckDetail(BaseModel):
    """生产预检单项结果"""

    key: str
    passed: bool
    message: str


class PreflightReportDetail(BaseModel):
    """生产预检报告"""

    passed: bool
    checks: list[PreflightCheckDetail]


class DualRunCompareRequest(BaseModel):
    """双跑比较请求"""

    goResponse: dict = Field(alias="go_response")
    pythonResponse: dict = Field(alias="python_response")

    model_config = {"populate_by_name": True}


class DualRunCompareResponse(BaseModel):
    """双跑比较响应"""

    compatible: bool
    differences: list[str] = Field(default_factory=list)


class RollbackPlanResponse(BaseModel):
    """回滚计划响应"""

    strategy: str
    requiresDatabaseRollback: bool
    steps: list[str]
    verification: list[str]

