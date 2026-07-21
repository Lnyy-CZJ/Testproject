"""
信号接入、问题池、检索器与质量洞察 Schema

功能说明:
    定义第五阶段 API 的请求/响应结构，保持 camelCase 兼容前端。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class InboundSignalRequest(BaseModel):
    """入站信号请求"""

    sourceEventId: str | None = Field(default=None, alias="source_event_id")
    title: str = Field(default="外部问题信号")
    payload: dict = Field(default_factory=dict)
    platform: str | None = None
    appVersion: str | None = Field(default=None, alias="app_version")
    stackTrace: str | None = Field(default=None, alias="stack_trace")
    severity: str | None = None

    model_config = {"populate_by_name": True}


class InboundSignalResponse(BaseModel):
    """入站信号响应"""

    clusterId: int = Field(alias="cluster_id")
    signalId: int = Field(alias="signal_id")
    fingerprint: str
    duplicated: bool = False

    model_config = {"populate_by_name": True}


class IssueClusterDetail(BaseModel):
    """问题簇详情"""

    id: int
    projectId: int = Field(alias="project_id")
    fingerprint: str
    title: str
    triageStatus: str = Field(alias="triage_status")
    severity: str | None = None
    priority: str | None = None
    signalCount: int = Field(alias="signal_count")
    linkedDefectId: int | None = Field(default=None, alias="linked_defect_id")
    assigneeId: int | None = Field(default=None, alias="assignee_id")
    firstSeenAt: datetime = Field(alias="first_seen_at")
    lastSeenAt: datetime = Field(alias="last_seen_at")

    model_config = {"populate_by_name": True}


class IssueSignalDetail(BaseModel):
    """问题信号详情"""

    id: int
    clusterId: int = Field(alias="cluster_id")
    connectorId: int | None = Field(default=None, alias="connector_id")
    sourceEventId: str = Field(alias="source_event_id")
    payload: dict | None = None
    platform: str | None = None
    appVersion: str | None = Field(default=None, alias="app_version")
    stackTrace: str | None = Field(default=None, alias="stack_trace")
    fingerprint: str
    firstSeenAt: datetime = Field(alias="first_seen_at")
    lastSeenAt: datetime = Field(alias="last_seen_at")

    model_config = {"populate_by_name": True}


class AssignClusterRequest(BaseModel):
    """分配问题簇请求"""

    assigneeId: int = Field(alias="assignee_id")
    severity: str | None = None
    priority: str | None = None

    model_config = {"populate_by_name": True}


class MergeClusterRequest(BaseModel):
    """合并问题簇请求"""

    targetClusterId: int = Field(alias="target_cluster_id")

    model_config = {"populate_by_name": True}


class ConvertClusterRequest(BaseModel):
    """问题簇转缺陷请求"""

    iterationId: int = Field(alias="iteration_id")
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    priority: str | None = None

    model_config = {"populate_by_name": True}


class IntegrationCreate(BaseModel):
    """创建集成连接器请求"""

    type: str
    name: str
    config: dict = Field(default_factory=dict)
    status: str = "active"


class IntegrationUpdate(BaseModel):
    """更新集成连接器请求"""

    name: str | None = None
    config: dict | None = None
    status: str | None = None
    healthMessage: str | None = Field(default=None, alias="health_message")

    model_config = {"populate_by_name": True}


class IntegrationDetail(BaseModel):
    """集成连接器详情"""

    id: int
    projectId: int = Field(alias="project_id")
    type: str
    name: str
    config: dict | None = None
    status: str
    healthMessage: str | None = Field(default=None, alias="health_message")
    token: str
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class RetrieverPluginUpdate(BaseModel):
    """更新检索器插件请求"""

    name: str | None = None
    pluginType: str | None = Field(default=None, alias="plugin_type")
    config: dict | None = None
    enabled: bool | None = None
    sortOrder: int | None = Field(default=None, alias="sort_order")

    model_config = {"populate_by_name": True}


class RetrieverPluginDetail(BaseModel):
    """检索器插件详情"""

    id: int
    projectId: int = Field(alias="project_id")
    name: str
    pluginType: str = Field(alias="plugin_type")
    config: dict | None = None
    enabled: bool
    sortOrder: int = Field(alias="sort_order")
    createdAt: datetime = Field(alias="created_at")
    updatedAt: datetime = Field(alias="updated_at")

    model_config = {"populate_by_name": True}


class RetrieverSortRequest(BaseModel):
    """检索器排序请求"""

    pluginIds: list[int] = Field(alias="plugin_ids")

    model_config = {"populate_by_name": True}


class RetrieverTestRequest(BaseModel):
    """检索器测试请求"""

    text: str = ""
    keywords: list[str] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)
    topK: int = Field(default=5, alias="top_k")

    model_config = {"populate_by_name": True}


class QualityInsightOverview(BaseModel):
    """质量洞察概览"""

    projectId: int = Field(alias="project_id")
    clusterCount: int = 0
    openClusterCount: int = 0
    ignoredClusterCount: int = 0
    convertedClusterCount: int = 0
    signalCount: int = 0
    defectCount: int = 0

    model_config = {"populate_by_name": True}
