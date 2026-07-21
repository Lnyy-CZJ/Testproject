"""
信号接入、问题池、检索器与质量洞察 API

功能说明:
    提供第五阶段外部信号入站、问题池管理、集成连接器、
    检索器插件和质量洞察接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireProjectPermission, get_current_user
from app.infrastructure.database import get_db
from app.models.user import User
from app.schemas.common import ApiResult
from app.schemas.signal import (
    AssignClusterRequest,
    ConvertClusterRequest,
    InboundSignalRequest,
    InboundSignalResponse,
    IntegrationCreate,
    IntegrationDetail,
    IntegrationUpdate,
    IssueClusterDetail,
    IssueSignalDetail,
    MergeClusterRequest,
    QualityInsightOverview,
    RetrieverPluginDetail,
    RetrieverPluginUpdate,
    RetrieverSortRequest,
    RetrieverTestRequest,
)
from app.services.signal_service import SignalService

router = APIRouter(tags=["signals"])


@router.post("/inbound/connectors/{token}", response_model=ApiResult[InboundSignalResponse])
async def inbound_connector_signal(
    token: str,
    body: InboundSignalRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResult[InboundSignalResponse]:
    """接收外部连接器推送的问题信号"""
    result = await SignalService(db).ingest(token, body)
    return ApiResult.success(result)


@router.get("/projects/{id}/issue-clusters", response_model=ApiResult[list[IssueClusterDetail]])
async def list_issue_clusters(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[IssueClusterDetail]]:
    """查询问题簇列表"""
    clusters = await SignalService(db).list_clusters(id)
    return ApiResult.success(clusters)


@router.get("/projects/{id}/issue-clusters/{clusterId}", response_model=ApiResult[IssueClusterDetail])
async def get_issue_cluster(
    id: int,
    clusterId: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IssueClusterDetail]:
    """获取问题簇详情"""
    cluster = await SignalService(db).get_cluster(id, clusterId)
    return ApiResult.success(cluster)


@router.get("/projects/{id}/issue-clusters/{clusterId}/signals", response_model=ApiResult[list[IssueSignalDetail]])
async def list_issue_cluster_signals(
    id: int,
    clusterId: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[IssueSignalDetail]]:
    """查询问题簇关联信号"""
    signals = await SignalService(db).list_signals(id, clusterId)
    return ApiResult.success(signals)


@router.post("/projects/{id}/issue-clusters/{clusterId}/assign", response_model=ApiResult[IssueClusterDetail])
async def assign_issue_cluster(
    id: int,
    clusterId: int,
    body: AssignClusterRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IssueClusterDetail]:
    """分配问题簇"""
    cluster = await SignalService(db).assign_cluster(id, clusterId, body)
    return ApiResult.success(cluster)


@router.post("/projects/{id}/issue-clusters/{clusterId}/ignore", response_model=ApiResult[IssueClusterDetail])
async def ignore_issue_cluster(
    id: int,
    clusterId: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IssueClusterDetail]:
    """忽略问题簇"""
    cluster = await SignalService(db).ignore_cluster(id, clusterId)
    return ApiResult.success(cluster)


@router.post("/projects/{id}/issue-clusters/{clusterId}/merge", response_model=ApiResult[IssueClusterDetail])
async def merge_issue_cluster(
    id: int,
    clusterId: int,
    body: MergeClusterRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IssueClusterDetail]:
    """合并问题簇"""
    cluster = await SignalService(db).merge_cluster(id, clusterId, body)
    return ApiResult.success(cluster)


@router.post("/projects/{id}/issue-clusters/{clusterId}/convert", response_model=ApiResult[IssueClusterDetail])
async def convert_issue_cluster(
    id: int,
    clusterId: int,
    body: ConvertClusterRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IssueClusterDetail]:
    """将问题簇转换为正式缺陷"""
    cluster = await SignalService(db).convert_cluster(id, clusterId, body, current_user)
    return ApiResult.success(cluster)


@router.post("/projects/{id}/issue-clusters/auto-triage", response_model=ApiResult[dict])
async def auto_triage_issue_clusters(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[dict]:
    """按路由规则自动分诊问题簇"""
    result = await SignalService(db).auto_triage(id)
    return ApiResult.success(result)


@router.get("/projects/{id}/integrations", response_model=ApiResult[list[IntegrationDetail]])
async def list_integrations(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[IntegrationDetail]]:
    """查询项目集成连接器"""
    integrations = await SignalService(db).list_integrations(id)
    return ApiResult.success(integrations)


@router.post("/projects/{id}/integrations", response_model=ApiResult[IntegrationDetail])
async def create_integration(
    id: int,
    body: IntegrationCreate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IntegrationDetail]:
    """创建项目集成连接器"""
    integration = await SignalService(db).create_integration(id, body)
    return ApiResult.success(integration)


@router.put("/projects/{id}/integrations/{connectorId}", response_model=ApiResult[IntegrationDetail])
async def update_integration(
    id: int,
    connectorId: int,
    body: IntegrationUpdate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[IntegrationDetail]:
    """更新项目集成连接器"""
    integration = await SignalService(db).update_integration(id, connectorId, body)
    return ApiResult.success(integration)


@router.delete("/projects/{id}/integrations/{connectorId}", response_model=ApiResult[None])
async def delete_integration(
    id: int,
    connectorId: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[None]:
    """删除项目集成连接器"""
    await SignalService(db).delete_integration(id, connectorId)
    return ApiResult.success(None)


@router.post("/projects/{id}/integrations/{connectorId}/test", response_model=ApiResult[dict])
async def test_integration(
    id: int,
    connectorId: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[dict]:
    """测试项目集成连接器"""
    result = await SignalService(db).test_integration(id, connectorId)
    return ApiResult.success(result)


@router.post("/projects/{id}/integrations/{connectorId}/sync", response_model=ApiResult[dict])
async def sync_integration(
    id: int,
    connectorId: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[dict]:
    """触发项目集成连接器同步"""
    result = await SignalService(db).sync_integration(id, connectorId)
    return ApiResult.success(result)


@router.get("/projects/{id}/retriever-plugins", response_model=ApiResult[list[RetrieverPluginDetail]])
async def list_retriever_plugins(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[RetrieverPluginDetail]]:
    """查询项目检索器插件"""
    plugins = await SignalService(db).list_retriever_plugins(id)
    return ApiResult.success(plugins)


@router.put("/projects/{id}/retriever-plugins/{pluginId}", response_model=ApiResult[RetrieverPluginDetail])
async def update_retriever_plugin(
    id: int,
    pluginId: int,
    body: RetrieverPluginUpdate,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[RetrieverPluginDetail]:
    """更新项目检索器插件"""
    plugin = await SignalService(db).update_retriever_plugin(id, pluginId, body)
    return ApiResult.success(plugin)


@router.patch("/projects/{id}/retriever-plugins/{pluginId}/toggle", response_model=ApiResult[RetrieverPluginDetail])
async def toggle_retriever_plugin(
    id: int,
    pluginId: int,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[RetrieverPluginDetail]:
    """启用或禁用项目检索器插件"""
    plugin = await SignalService(db).toggle_retriever_plugin(id, pluginId)
    return ApiResult.success(plugin)


@router.put("/projects/{id}/retriever-plugins/sort", response_model=ApiResult[list[RetrieverPluginDetail]])
async def sort_retriever_plugins(
    id: int,
    body: RetrieverSortRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[list[RetrieverPluginDetail]]:
    """更新项目检索器插件排序"""
    plugins = await SignalService(db).sort_retriever_plugins(id, body)
    return ApiResult.success(plugins)


@router.post("/projects/{id}/retriever-plugins/{pluginId}/test", response_model=ApiResult[dict])
async def test_retriever_plugin(
    id: int,
    pluginId: int,
    body: RetrieverTestRequest,
    _: bool = Depends(RequireProjectPermission("projects:update", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[dict]:
    """测试项目检索器插件"""
    result = await SignalService(db).test_retriever_plugin(id, pluginId, body)
    return ApiResult.success(result)


@router.get("/projects/{id}/quality-insights/overview", response_model=ApiResult[QualityInsightOverview])
async def quality_insights_overview(
    id: int,
    _: bool = Depends(RequireProjectPermission("projects:read", "id")),
    db: AsyncSession = Depends(get_db),
) -> ApiResult[QualityInsightOverview]:
    """查询项目质量洞察概览"""
    overview = await SignalService(db).quality_overview(id)
    return ApiResult.success(overview)
