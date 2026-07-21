"""
Agent 分析、Token 与记忆相关 Schema

功能说明:
    定义第三阶段 API 的请求/响应结构，字段采用前端兼容的 camelCase。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    """触发缺陷分析请求"""

    defectId: int = Field(..., alias="defect_id")
    agentTypes: list[str] = Field(default_factory=lambda: ["analysis_general"], alias="agent_types")
    force: bool = False

    model_config = {"populate_by_name": True}


class AnalyzeResponse(BaseModel):
    """触发分析响应"""

    taskId: int = Field(alias="task_id")
    defectId: int = Field(alias="defect_id")
    status: str
    reportIds: list[int] = Field(default_factory=list, alias="report_ids")

    model_config = {"populate_by_name": True}


class AnalysisReportDetail(BaseModel):
    """分析报告详情"""

    id: int
    defectId: int = Field(alias="defect_id")
    agentType: str = Field(alias="agent_type")
    analysis: dict | None = None
    solution: dict | None = None
    provider: str | None = None
    model: str | None = None
    status: str
    isObsolete: bool = Field(alias="is_obsolete")
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True}


class AnalysisTaskDetail(BaseModel):
    """分析任务详情"""

    id: int
    defectId: int = Field(alias="defect_id")
    agentTypes: list[str] = Field(default_factory=list)
    status: str
    error: str | None = None
    createdAt: datetime = Field(alias="created_at")
    startedAt: datetime | None = Field(default=None, alias="started_at")
    completedAt: datetime | None = Field(default=None, alias="completed_at")

    model_config = {"populate_by_name": True}


class TokenUsageDetail(BaseModel):
    """Token 用量明细"""

    id: int
    projectId: int = Field(alias="project_id")
    iterationId: int | None = Field(default=None, alias="iteration_id")
    defectId: int | None = Field(default=None, alias="defect_id")
    provider: str
    model: str
    promptTokens: int = Field(alias="prompt_tokens")
    completionTokens: int = Field(alias="completion_tokens")
    totalTokens: int = Field(alias="total_tokens")
    estimatedCostUsd: float = Field(default=0.0, alias="estimated_cost_usd")
    isFallback: bool = Field(default=False, alias="is_fallback")
    durationMs: int | None = Field(default=None, alias="duration_ms")
    source: str
    createdAt: datetime = Field(alias="created_at")

    model_config = {"populate_by_name": True}


class TokenUsageSummary(BaseModel):
    """Token 用量汇总"""

    promptTokens: int = 0
    completionTokens: int = 0
    totalTokens: int = 0
    estimatedCostUsd: float = 0.0
    count: int = 0


class AgentMemoryCreate(BaseModel):
    """创建 Agent 记忆请求"""

    category: str = Field(..., max_length=30)
    content: str = Field(..., min_length=1)
    source: str = "manual"
    relevanceScore: float = Field(default=0.8, alias="relevance_score")
    enabled: bool = True

    model_config = {"populate_by_name": True}


class AgentMemoryUpdate(BaseModel):
    """更新 Agent 记忆请求"""

    category: str | None = Field(default=None, max_length=30)
    content: str | None = Field(default=None, min_length=1)
    relevanceScore: float | None = Field(default=None, alias="relevance_score")
    enabled: bool | None = None

    model_config = {"populate_by_name": True}


class AgentMemoryDetail(BaseModel):
    """Agent 记忆详情"""

    id: int
    projectId: int = Field(alias="project_id")
    iterationId: int | None = Field(default=None, alias="iteration_id")
    category: str
    content: str
    source: str
    sourceRefId: int | None = Field(default=None, alias="source_ref_id")
    relevanceScore: float = Field(alias="relevance_score")
    enabled: bool
    createdBy: int = Field(alias="created_by")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}
