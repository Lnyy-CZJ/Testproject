"""
修复任务与 PR 生命周期 Schema

功能说明:
    定义第四阶段修复任务、人工修复和 PR 生命周期接口的数据结构。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateFixTaskRequest(BaseModel):
    """创建修复任务请求"""

    repoIds: list[int] = Field(default_factory=list, alias="repo_ids")
    agentTypes: list[str] = Field(default_factory=lambda: ["fix_general"], alias="agent_types")
    targetBranch: str | None = Field(default=None, alias="target_branch")
    summary: str | None = None

    model_config = {"populate_by_name": True}


class ManualFixRequest(BaseModel):
    """人工修复请求"""

    description: str | None = None
    repoId: int | None = Field(default=None, alias="repo_id")
    prUrl: str | None = Field(default=None, alias="pr_url")

    model_config = {"populate_by_name": True}


class UpdateFixTaskRequest(BaseModel):
    """更新修复任务请求"""

    status: str | None = None
    result: dict | None = None
    prUrl: str | None = Field(default=None, alias="pr_url")
    prStatus: str | None = Field(default=None, alias="pr_status")

    model_config = {"populate_by_name": True}


class UpdatePRRequest(BaseModel):
    """更新 PR 信息请求"""

    prUrl: str = Field(..., alias="pr_url")
    prStatus: str = Field(default="open", alias="pr_status")

    model_config = {"populate_by_name": True}


class RejectPRRequest(BaseModel):
    """标记 PR 拒绝请求"""

    prNumber: str | None = Field(default=None, alias="pr_number")
    rejectedBy: str | None = Field(default=None, alias="rejected_by")
    rejectReason: str = Field(..., min_length=1, alias="reject_reason")
    vcsProvider: str | None = Field(default=None, alias="vcs_provider")

    model_config = {"populate_by_name": True}


class FixTaskGroupDetail(BaseModel):
    """修复任务组详情"""

    id: int
    defectId: int = Field(alias="defect_id")
    targetBranch: str | None = Field(default=None, alias="target_branch")
    summary: str | None = None
    aiProvider: str | None = Field(default=None, alias="ai_provider")
    aiModel: str | None = Field(default=None, alias="ai_model")
    status: str
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class FixTaskDetail(BaseModel):
    """修复任务详情"""

    id: int
    fixTaskGroupId: int | None = Field(default=None, alias="fix_task_group_id")
    defectId: int = Field(alias="defect_id")
    repoId: int | None = Field(default=None, alias="repo_id")
    agentType: str | None = Field(default=None, alias="agent_type")
    source: str
    status: str
    plan: dict | None = None
    result: dict | None = None
    prUrl: str | None = Field(default=None, alias="pr_url")
    prStatus: str | None = Field(default=None, alias="pr_status")
    manualDescription: str | None = Field(default=None, alias="manual_description")
    createdAt: datetime = Field(alias="created_at")
    completedAt: datetime | None = Field(default=None, alias="completed_at")

    model_config = {"populate_by_name": True}


class CreateFixTaskResponse(BaseModel):
    """创建修复任务响应"""

    group: FixTaskGroupDetail
    tasks: list[FixTaskDetail]


class PRRejectionDetail(BaseModel):
    """PR 拒绝记录详情"""

    id: int
    fixTaskId: int = Field(alias="fix_task_id")
    prNumber: str | None = Field(default=None, alias="pr_number")
    prUrl: str | None = Field(default=None, alias="pr_url")
    rejectedBy: str | None = Field(default=None, alias="rejected_by")
    rejectReason: str | None = Field(default=None, alias="reject_reason")
    vcsProvider: str | None = Field(default=None, alias="vcs_provider")
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True}
