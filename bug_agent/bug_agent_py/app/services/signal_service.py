"""
信号接入、问题池、检索器与质量洞察服务

功能说明:
    实现第五阶段外部信号入站、问题簇聚类管理、连接器管理、
    检索器插件配置和质量洞察聚合。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import RetrieverPlugin
from app.models.defect import Defect
from app.models.project import Iteration, Project
from app.models.signal import (
    IntegrationConnector,
    IntegrationSyncRecord,
    IssueCluster,
    IssueRoutingRule,
    IssueSignal,
)
from app.models.user import User
from app.retrieval.keyword import KeywordRetriever
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


class SignalService:
    """第五阶段信号、检索和洞察服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ingest(self, token: str, body: InboundSignalRequest) -> InboundSignalResponse:
        """
        接收入站信号并聚类。

        参数说明:
            token: IntegrationConnector.token。
            body: 外部平台推送的规范化或半规范化 payload。
        """
        if not self._valid_connector_token(token):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="连接器不存在")

        connector = await self.db.scalar(
            select(IntegrationConnector).where(IntegrationConnector.token == token)
        )
        if connector is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="连接器不存在")
        if connector.status != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="连接器未启用")

        source_event_id = body.sourceEventId or self._fingerprint(
            connector.id,
            body.title,
            body.stackTrace or "",
            body.payload,
        )
        existing_signal = await self.db.scalar(
            select(IssueSignal).where(
                IssueSignal.connector_id == connector.id,
                IssueSignal.source_event_id == source_event_id,
            )
        )
        if existing_signal is not None:
            existing_signal.last_seen_at = datetime.now()
            cluster = await self.db.get(IssueCluster, existing_signal.cluster_id)
            if cluster is not None:
                cluster.last_seen_at = datetime.now()
            await self.db.flush()
            return InboundSignalResponse(
                cluster_id=existing_signal.cluster_id,
                signal_id=existing_signal.id,
                fingerprint=existing_signal.fingerprint,
                duplicated=True,
            )

        fingerprint = self._fingerprint(body.title, body.stackTrace or "", body.platform or "")
        cluster = await self.db.scalar(
            select(IssueCluster).where(
                IssueCluster.project_id == connector.project_id,
                IssueCluster.fingerprint == fingerprint,
            )
        )
        if cluster is None:
            cluster = IssueCluster(
                project_id=connector.project_id,
                fingerprint=fingerprint,
                title=body.title,
                severity=body.severity,
                triage_status="new",
                signal_count=0,
            )
            self.db.add(cluster)
            await self.db.flush()
            await self.db.refresh(cluster)
        cluster.signal_count = (cluster.signal_count or 0) + 1
        cluster.last_seen_at = datetime.now()
        if body.severity and not cluster.severity:
            cluster.severity = body.severity

        signal = IssueSignal(
            cluster_id=cluster.id,
            connector_id=connector.id,
            source_event_id=source_event_id,
            payload=body.payload,
            platform=body.platform or connector.type,
            app_version=body.appVersion,
            stack_trace=body.stackTrace,
            fingerprint=fingerprint,
        )
        self.db.add(signal)
        await self.db.flush()
        await self.db.refresh(signal)
        return InboundSignalResponse(
            cluster_id=cluster.id,
            signal_id=signal.id,
            fingerprint=fingerprint,
            duplicated=False,
        )

    async def list_clusters(self, project_id: int) -> list[IssueClusterDetail]:
        """查询项目问题簇列表"""
        result = await self.db.execute(
            select(IssueCluster)
            .where(IssueCluster.project_id == project_id)
            .order_by(IssueCluster.last_seen_at.desc(), IssueCluster.id.desc())
        )
        return [self._to_cluster_detail(item) for item in result.scalars().all()]

    async def get_cluster(self, project_id: int, cluster_id: int) -> IssueClusterDetail:
        """获取问题簇详情"""
        cluster = await self._get_cluster(project_id, cluster_id)
        return self._to_cluster_detail(cluster)

    async def list_signals(self, project_id: int, cluster_id: int) -> list[IssueSignalDetail]:
        """查询问题簇下的信号列表"""
        await self._get_cluster(project_id, cluster_id)
        result = await self.db.execute(
            select(IssueSignal).where(IssueSignal.cluster_id == cluster_id).order_by(IssueSignal.id.desc())
        )
        return [self._to_signal_detail(item) for item in result.scalars().all()]

    async def assign_cluster(
        self,
        project_id: int,
        cluster_id: int,
        body: AssignClusterRequest,
    ) -> IssueClusterDetail:
        """分配问题簇并补充分诊信息"""
        cluster = await self._get_cluster(project_id, cluster_id)
        cluster.assignee_id = body.assigneeId
        cluster.triage_status = "assigned"
        if body.severity is not None:
            cluster.severity = body.severity
        if body.priority is not None:
            cluster.priority = body.priority
        await self.db.flush()
        await self.db.refresh(cluster)
        return self._to_cluster_detail(cluster)

    async def ignore_cluster(self, project_id: int, cluster_id: int) -> IssueClusterDetail:
        """忽略问题簇"""
        cluster = await self._get_cluster(project_id, cluster_id)
        cluster.triage_status = "ignored"
        await self.db.flush()
        await self.db.refresh(cluster)
        return self._to_cluster_detail(cluster)

    async def merge_cluster(
        self,
        project_id: int,
        cluster_id: int,
        body: MergeClusterRequest,
    ) -> IssueClusterDetail:
        """合并问题簇，将当前簇信号迁移到目标簇"""
        source = await self._get_cluster(project_id, cluster_id)
        target = await self._get_cluster(project_id, body.targetClusterId)
        signal_count = await self.db.scalar(
            select(func.count()).select_from(IssueSignal).where(IssueSignal.cluster_id == source.id)
        )
        await self.db.execute(
            update(IssueSignal).where(IssueSignal.cluster_id == source.id).values(cluster_id=target.id)
        )
        target.signal_count = (target.signal_count or 0) + int(signal_count or 0)
        target.last_seen_at = datetime.now()
        source.triage_status = "merged"
        await self.db.flush()
        await self.db.refresh(target)
        return self._to_cluster_detail(target)

    async def convert_cluster(
        self,
        project_id: int,
        cluster_id: int,
        body: ConvertClusterRequest,
        user: User,
    ) -> IssueClusterDetail:
        """将问题簇转换为正式缺陷"""
        cluster = await self._get_cluster(project_id, cluster_id)
        iteration = await self.db.get(Iteration, body.iterationId)
        if iteration is None or iteration.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="迭代不属于当前项目")
        code = await self._next_defect_code(project_id)
        defect = Defect(
            code=code,
            iteration_id=iteration.id,
            title=body.title or cluster.title,
            description=body.description or f"由问题簇 {cluster.id} 转换，指纹：{cluster.fingerprint}",
            severity=body.severity or cluster.severity or "一般",
            priority=body.priority or cluster.priority or "P2",
            type="外部信号",
            status="new",
            reporter_id=user.id,
            tags="external_signal",
        )
        self.db.add(defect)
        await self.db.flush()
        await self.db.refresh(defect)
        cluster.linked_defect_id = defect.id
        cluster.triage_status = "converted"
        await self.db.flush()
        await self.db.refresh(cluster)
        return self._to_cluster_detail(cluster)

    async def auto_triage(self, project_id: int) -> dict:
        """按路由规则自动分诊新问题簇"""
        rules = (
            await self.db.execute(
                select(IssueRoutingRule)
                .where(IssueRoutingRule.project_id == project_id, IssueRoutingRule.enabled.is_(True))
                .order_by(IssueRoutingRule.sort_order.asc(), IssueRoutingRule.id.asc())
            )
        ).scalars().all()
        clusters = (
            await self.db.execute(
                select(IssueCluster).where(
                    IssueCluster.project_id == project_id,
                    IssueCluster.triage_status == "new",
                )
            )
        ).scalars().all()
        matched = 0
        for cluster in clusters:
            signals = (
                await self.db.execute(select(IssueSignal).where(IssueSignal.cluster_id == cluster.id).limit(1))
            ).scalars().all()
            signal = signals[0] if signals else None
            for rule in rules:
                if self._rule_matches(rule, cluster, signal):
                    cluster.assignee_id = rule.suggested_assignee_id
                    cluster.severity = rule.suggested_severity or cluster.severity
                    cluster.priority = rule.suggested_priority or cluster.priority
                    cluster.triage_status = "assigned"
                    matched += 1
                    break
        await self.db.flush()
        return {"matched": matched, "total": len(clusters)}

    async def list_integrations(self, project_id: int) -> list[IntegrationDetail]:
        """查询项目连接器"""
        result = await self.db.execute(
            select(IntegrationConnector)
            .where(IntegrationConnector.project_id == project_id)
            .order_by(IntegrationConnector.id.desc())
        )
        return [self._to_integration_detail(item) for item in result.scalars().all()]

    async def create_integration(self, project_id: int, body: IntegrationCreate) -> IntegrationDetail:
        """创建连接器"""
        connector = IntegrationConnector(
            project_id=project_id,
            type=body.type,
            name=body.name,
            config=body.config,
            status=body.status,
            token=secrets.token_hex(16),
        )
        self.db.add(connector)
        await self.db.flush()
        await self.db.refresh(connector)
        return self._to_integration_detail(connector)

    async def update_integration(
        self,
        project_id: int,
        connector_id: int,
        body: IntegrationUpdate,
    ) -> IntegrationDetail:
        """更新连接器"""
        connector = await self._get_connector(project_id, connector_id)
        if body.name is not None:
            connector.name = body.name
        if body.config is not None:
            connector.config = body.config
        if body.status is not None:
            connector.status = body.status
        if body.healthMessage is not None:
            connector.health_message = body.healthMessage
        await self.db.flush()
        await self.db.refresh(connector)
        return self._to_integration_detail(connector)

    async def delete_integration(self, project_id: int, connector_id: int) -> None:
        """删除连接器"""
        connector = await self._get_connector(project_id, connector_id)
        await self.db.delete(connector)

    async def test_integration(self, project_id: int, connector_id: int) -> dict:
        """测试连接器可用性"""
        connector = await self._get_connector(project_id, connector_id)
        return {"ok": connector.status == "active", "status": connector.status}

    async def sync_integration(self, project_id: int, connector_id: int) -> dict:
        """创建一次连接器同步记录"""
        connector = await self._get_connector(project_id, connector_id)
        record = IntegrationSyncRecord(
            connector_id=connector.id,
            status="completed",
            total_count=0,
            success_count=0,
            error_count=0,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return {"syncRecordId": record.id, "status": record.status}

    async def list_retriever_plugins(self, project_id: int) -> list[RetrieverPluginDetail]:
        """查询检索器插件；为空时创建默认关键词检索器"""
        result = await self.db.execute(
            select(RetrieverPlugin)
            .where(RetrieverPlugin.project_id == project_id)
            .order_by(RetrieverPlugin.sort_order.asc(), RetrieverPlugin.id.asc())
        )
        plugins = result.scalars().all()
        if not plugins:
            plugin = RetrieverPlugin(
                project_id=project_id,
                name="Keyword Retriever",
                plugin_type="keyword",
                config={},
                enabled=True,
                sort_order=0,
            )
            self.db.add(plugin)
            await self.db.flush()
            await self.db.refresh(plugin)
            plugins = [plugin]
        return [self._to_plugin_detail(item) for item in plugins]

    async def update_retriever_plugin(
        self,
        project_id: int,
        plugin_id: int,
        body: RetrieverPluginUpdate,
    ) -> RetrieverPluginDetail:
        """更新检索器插件配置"""
        plugin = await self._get_plugin(project_id, plugin_id)
        if body.name is not None:
            plugin.name = body.name
        if body.pluginType is not None:
            plugin.plugin_type = body.pluginType
        if body.config is not None:
            plugin.config = body.config
        if body.enabled is not None:
            plugin.enabled = body.enabled
        if body.sortOrder is not None:
            plugin.sort_order = body.sortOrder
        await self.db.flush()
        await self.db.refresh(plugin)
        return self._to_plugin_detail(plugin)

    async def toggle_retriever_plugin(self, project_id: int, plugin_id: int) -> RetrieverPluginDetail:
        """启用或禁用检索器插件"""
        plugin = await self._get_plugin(project_id, plugin_id)
        plugin.enabled = not plugin.enabled
        await self.db.flush()
        await self.db.refresh(plugin)
        return self._to_plugin_detail(plugin)

    async def sort_retriever_plugins(self, project_id: int, body: RetrieverSortRequest) -> list[RetrieverPluginDetail]:
        """更新检索器插件排序"""
        for index, plugin_id in enumerate(body.pluginIds):
            plugin = await self._get_plugin(project_id, plugin_id)
            plugin.sort_order = index
        await self.db.flush()
        return await self.list_retriever_plugins(project_id)

    async def test_retriever_plugin(self, project_id: int, plugin_id: int, body: RetrieverTestRequest) -> dict:
        """测试检索器插件"""
        plugin = await self._get_plugin(project_id, plugin_id)
        if plugin.plugin_type != "keyword":
            return {"ok": False, "message": "当前仅支持 keyword 检索器测试", "items": []}
        items = KeywordRetriever(body.documents).retrieve(body.text, body.keywords, body.topK)
        return {"ok": True, "items": [item.__dict__ for item in items]}

    async def quality_overview(self, project_id: int) -> QualityInsightOverview:
        """查询项目质量洞察概览"""
        cluster_count = int(
            await self.db.scalar(
                select(func.count()).select_from(IssueCluster).where(IssueCluster.project_id == project_id)
            )
            or 0
        )
        signal_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(IssueSignal)
                .join(IssueCluster, IssueCluster.id == IssueSignal.cluster_id)
                .where(IssueCluster.project_id == project_id)
            )
            or 0
        )
        defect_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(Defect)
                .join(Iteration, Iteration.id == Defect.iteration_id)
                .where(Iteration.project_id == project_id)
            )
            or 0
        )
        status_rows = await self.db.execute(
            select(IssueCluster.triage_status, func.count())
            .where(IssueCluster.project_id == project_id)
            .group_by(IssueCluster.triage_status)
        )
        status_counts = {row[0]: int(row[1] or 0) for row in status_rows.all()}
        return QualityInsightOverview(
            project_id=project_id,
            clusterCount=cluster_count,
            openClusterCount=status_counts.get("new", 0) + status_counts.get("assigned", 0),
            ignoredClusterCount=status_counts.get("ignored", 0),
            convertedClusterCount=status_counts.get("converted", 0),
            signalCount=signal_count,
            defectCount=defect_count,
        )

    async def _get_cluster(self, project_id: int, cluster_id: int) -> IssueCluster:
        """获取问题簇，不存在返回 404"""
        cluster = await self.db.get(IssueCluster, cluster_id)
        if cluster is None or cluster.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="问题簇不存在")
        return cluster

    async def _get_connector(self, project_id: int, connector_id: int) -> IntegrationConnector:
        """获取连接器，不存在返回 404"""
        connector = await self.db.get(IntegrationConnector, connector_id)
        if connector is None or connector.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="连接器不存在")
        return connector

    async def _get_plugin(self, project_id: int, plugin_id: int) -> RetrieverPlugin:
        """获取检索器插件，不存在返回 404"""
        plugin = await self.db.get(RetrieverPlugin, plugin_id)
        if plugin is None or plugin.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="检索器插件不存在")
        return plugin

    async def _next_defect_code(self, project_id: int) -> str:
        """生成项目内递增缺陷编号"""
        project = await self.db.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        year_month = datetime.now().strftime("%Y%m")
        if project.defect_seq_year_month != year_month:
            project.defect_seq = 0
            project.defect_seq_year_month = year_month
        project.defect_seq += 1
        return f"BUG-{project_id}-{year_month}-{project.defect_seq:04d}"

    @staticmethod
    def _fingerprint(*parts: object) -> str:
        """根据输入片段生成稳定 SHA256 指纹"""
        normalized = "|".join(str(part or "").strip().lower() for part in parts)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_connector_token(token: str) -> bool:
        """校验连接器 token 基础格式，明显非法时避免无效数据库访问"""
        if len(token) != 32:
            return False
        return all(char in "0123456789abcdef" for char in token.lower())

    @staticmethod
    def _rule_matches(rule: IssueRoutingRule, cluster: IssueCluster, signal: IssueSignal | None) -> bool:
        """判断路由规则是否命中问题簇和信号"""
        if rule.fingerprint_pattern and rule.fingerprint_pattern not in cluster.fingerprint:
            return False
        if signal is None:
            return True
        if rule.platform and rule.platform != signal.platform:
            return False
        if rule.app_version and rule.app_version != signal.app_version:
            return False
        if rule.stack_keyword and rule.stack_keyword not in (signal.stack_trace or ""):
            return False
        return True

    @staticmethod
    def _to_cluster_detail(cluster: IssueCluster) -> IssueClusterDetail:
        """转换问题簇 DTO"""
        return IssueClusterDetail(
            id=cluster.id,
            project_id=cluster.project_id,
            fingerprint=cluster.fingerprint,
            title=cluster.title,
            triage_status=cluster.triage_status,
            severity=cluster.severity,
            priority=cluster.priority,
            signal_count=cluster.signal_count,
            linked_defect_id=cluster.linked_defect_id,
            assignee_id=cluster.assignee_id,
            first_seen_at=cluster.first_seen_at,
            last_seen_at=cluster.last_seen_at,
        )

    @staticmethod
    def _to_signal_detail(signal: IssueSignal) -> IssueSignalDetail:
        """转换问题信号 DTO"""
        return IssueSignalDetail(
            id=signal.id,
            cluster_id=signal.cluster_id,
            connector_id=signal.connector_id,
            source_event_id=signal.source_event_id,
            payload=signal.payload,
            platform=signal.platform,
            app_version=signal.app_version,
            stack_trace=signal.stack_trace,
            fingerprint=signal.fingerprint,
            first_seen_at=signal.first_seen_at,
            last_seen_at=signal.last_seen_at,
        )

    @staticmethod
    def _to_integration_detail(connector: IntegrationConnector) -> IntegrationDetail:
        """转换连接器 DTO"""
        return IntegrationDetail(
            id=connector.id,
            project_id=connector.project_id,
            type=connector.type,
            name=connector.name,
            config=connector.config,
            status=connector.status,
            health_message=connector.health_message,
            token=connector.token,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )

    @staticmethod
    def _to_plugin_detail(plugin: RetrieverPlugin) -> RetrieverPluginDetail:
        """转换检索器插件 DTO"""
        return RetrieverPluginDetail(
            id=plugin.id,
            project_id=plugin.project_id,
            name=plugin.name,
            plugin_type=plugin.plugin_type,
            config=plugin.config,
            enabled=plugin.enabled,
            sort_order=plugin.sort_order,
            created_at=plugin.created_at,
            updated_at=plugin.updated_at,
        )
