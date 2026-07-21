"""
信号、问题簇、连接器模型

对应 PRD 数据模型:
    - issue_clusters: 问题簇表
    - issue_signals: 问题信号表
    - integration_connectors: 集成连接器表
    - integration_sync_records: 集成同步记录表
    - issue_routing_rules: 信号路由规则表
    - app_releases: 应用发布版本表
    - regression_items: 回归预防项表
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IssueCluster(Base):
    """
    问题簇表

    通过 SHA256 指纹将相同信号聚类。
    fingerprint 为索引字段，用于快速查找和去重。
    """
    __tablename__ = "issue_clusters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    triage_status: Mapped[str] = mapped_column(String(20), default="new")
    severity: Mapped[str | None] = mapped_column(String(20))
    priority: Mapped[str | None] = mapped_column(String(10))
    signal_count: Mapped[int] = mapped_column(Integer, default=1)
    linked_defect_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("defects.id"))
    assignee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    first_seen_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IssueSignal(Base):
    """
    问题信号表

    (connector_id, source_event_id) 联合唯一约束，实现去重。
    payload 存储原始负载的 JSON 格式。
    """
    __tablename__ = "issue_signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("issue_clusters.id"), nullable=False)
    connector_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("integration_connectors.id"))
    source_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)
    platform: Mapped[str | None] = mapped_column(String(50))
    app_version: Mapped[str | None] = mapped_column(String(50))
    stack_trace: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IntegrationConnector(Base):
    __tablename__ = "integration_connectors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    health_message: Mapped[str | None] = mapped_column(Text)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IntegrationSyncRecord(Base):
    __tablename__ = "integration_sync_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    connector_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("integration_connectors.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class IssueRoutingRule(Base):
    __tablename__ = "issue_routing_rules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    source_type: Mapped[str | None] = mapped_column(String(30))
    platform: Mapped[str | None] = mapped_column(String(50))
    app_version: Mapped[str | None] = mapped_column(String(50))
    fingerprint_pattern: Mapped[str | None] = mapped_column(String(200))
    stack_keyword: Mapped[str | None] = mapped_column(String(200))
    target_module_id: Mapped[int | None] = mapped_column(BigInteger)
    suggested_assignee_id: Mapped[int | None] = mapped_column(BigInteger)
    suggested_severity: Mapped[str | None] = mapped_column(String(20))
    suggested_priority: Mapped[str | None] = mapped_column(String(10))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class AppRelease(Base):
    __tablename__ = "app_releases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    app_version: Mapped[str] = mapped_column(String(50), nullable=False)
    build_number: Mapped[str] = mapped_column(String(50), nullable=False)
    release_date: Mapped[DateTime | None] = mapped_column(DateTime)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class RegressionItem(Base):
    __tablename__ = "regression_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id"), nullable=False)
    cluster_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("issue_clusters.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    verified_at: Mapped[DateTime | None] = mapped_column(DateTime)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())