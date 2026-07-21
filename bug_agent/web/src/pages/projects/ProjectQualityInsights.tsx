import React, { useCallback, useEffect, useState } from 'react';
import { BugOutlined, CheckCircleOutlined, DeploymentUnitOutlined, ReloadOutlined, RobotOutlined } from '@ant-design/icons';
import { Button, Card, Col, Empty, Row, Space, Table, Tag } from 'antd';
import dayjs from 'dayjs';
import { useParams } from 'react-router-dom';
import { getQualityInsightsOverview } from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLoadState from '../../components/PageLoadState';
import PageLayout from '../../components/layout/PageLayout';
import { message } from '../../utils/appMessage';
import type { AppReleaseTrend, QualityInsightsOverview } from '../../types';
import { getErrorMessage } from '../../utils/error';

const anomalyLevelMap: Record<string, { color: string; label: string }> = {
  baseline: { color: 'default', label: '基线版本' },
  normal: { color: 'blue', label: '平稳' },
  watch: { color: 'gold', label: '关注抬升' },
  high: { color: 'red', label: '异常抬升' },
};

const emptyAISummary = {
  analysisCount: 0,
  fixTaskCount: 0,
  successfulCount: 0,
  fallbackCount: 0,
  failedCount: 0,
  averageDurationMs: 0,
  totalTokens: 0,
  estimatedCostUsd: 0,
};

const ProjectQualityInsights: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);

  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState<QualityInsightsOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const aiSummary = overview?.ai ?? emptyAISummary;
  const aiSuccessRate = (() => {
    const total = aiSummary.analysisCount + aiSummary.fixTaskCount;
    if (!total) return 0;
    return Number(((aiSummary.successfulCount / total) * 100).toFixed(1));
  })();


  const fetchOverview = useCallback(async () => {
    if (!pid) {
      setLoadError('无效的项目 ID');
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const res = await getQualityInsightsOverview(pid);
      setOverview(res.data || null);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '获取质量情报概览失败');
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    void fetchOverview();
  }, [fetchOverview]);

  return (
    <PageLayout>
      {loadError ? (
        <PageLoadState subTitle={loadError} onRetry={() => void fetchOverview()} />
      ) : (
      <>
      <PageMetricSection
        items={[
          { key: 'issue-total', label: '问题簇总量', value: overview?.issuePool.totalClusters || 0, icon: <BugOutlined />, tone: 'purple' },
          { key: 'release-high', label: '异常抬升版本', value: overview?.releaseHealth.highAnomalyCount || 0, icon: <DeploymentUnitOutlined />, tone: 'rose' },
          { key: 'regression-open', label: '待验证回归项', value: overview?.regression.openItems || 0, icon: <CheckCircleOutlined />, tone: 'amber' },
          { key: 'ai-success', label: 'AI 成功率', value: `${aiSuccessRate}%`, icon: <RobotOutlined />, tone: 'cyan' },
        ]}
        actions={(
          <Button icon={<ReloadOutlined />} onClick={() => void fetchOverview()}>
            刷新概览
          </Button>
        )}
      />

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card className="utility-card" loading={loading}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
              <div data-testid="quality-issue-total">
                <div className="section-label">Issue Pool</div>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 800, color: '#0f172a' }}>{overview?.issuePool.totalClusters || 0}</div>
                <div style={{ marginTop: 8, color: '#64748b', fontSize: 13 }}>
                  待处理 {overview?.issuePool.openClusters || 0} · 已转缺陷 {overview?.issuePool.convertedClusters || 0} · 已忽略 {overview?.issuePool.ignoredClusters || 0}
                </div>
              </div>
              <div data-testid="quality-release-high">
                <div className="section-label">Release Health</div>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 800, color: '#0f172a' }}>{overview?.releaseHealth.highAnomalyCount || 0}</div>
                <div style={{ marginTop: 8, color: '#64748b', fontSize: 13 }}>
                  关注抬升 {overview?.releaseHealth.watchAnomalyCount || 0} · 平稳 {overview?.releaseHealth.normalCount || 0}
                </div>
              </div>
              <div data-testid="quality-regression-open">
                <div className="section-label">Regression</div>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 800, color: '#0f172a' }}>{overview?.regression.openItems || 0}</div>
                <div style={{ marginTop: 8, color: '#64748b', fontSize: 13 }}>
                  已验证 {overview?.regression.verifiedItems || 0} · 已归档 {overview?.regression.archivedItems || 0}
                </div>
              </div>
              <div data-testid="quality-ai-success-rate">
                <div className="section-label">AI Throughput</div>
                <div style={{ marginTop: 10, fontSize: 28, fontWeight: 800, color: '#0f172a' }}>{aiSuccessRate}%</div>
                <div style={{ marginTop: 8, color: '#64748b', fontSize: 13 }}>
                  fallback {aiSummary.fallbackCount} · 失败 {aiSummary.failedCount} · 平均延迟 {aiSummary.averageDurationMs}ms
                </div>
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col span={14}>
          <Card className="scene-card" title="高风险发布" loading={loading}>
            {overview?.topReleaseAnomalies?.length ? (
              <Table
                rowKey={(record) => record.release.id}
                dataSource={overview.topReleaseAnomalies}
                pagination={false}
                size="small"
                columns={[
                  {
                    title: '版本发布',
                    key: 'release',
                    render: (_: unknown, record: AppReleaseTrend) => (
                      <Space direction="vertical" size={2}>
                        <span>{`${record.release.platform} / ${record.release.appVersion}${record.release.buildNumber ? ` / ${record.release.buildNumber}` : ''}`}</span>
                        <span style={{ color: '#64748b', fontSize: 12 }}>
                          {record.release.channel || '未登记渠道'} · {dayjs(record.release.releaseTime).format('YYYY-MM-DD HH:mm')}
                        </span>
                      </Space>
                    ),
                  },
                  {
                    title: '异常级别',
                    dataIndex: 'anomalyLevel',
                    width: 120,
                    render: (value: string) => {
                      const config = anomalyLevelMap[value] || { color: 'default', label: value };
                      return <Tag color={config.color}>{config.label}</Tag>;
                    },
                  },
                  { title: '问题簇', dataIndex: 'clusterCount', width: 90 },
                  { title: '影响用户', dataIndex: 'affectedUserCount', width: 100 },
                ]}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有异常发布" />
            )}
          </Card>
        </Col>
        <Col span={10}>
          <Card className="utility-card" title="来源分布" loading={loading}>
            {overview?.sourceBreakdowns?.length ? (
              <Table
                rowKey="sourceType"
                dataSource={overview.sourceBreakdowns}
                pagination={false}
                size="small"
                columns={[
                  { title: '来源', dataIndex: 'sourceType' },
                  { title: '信号数', dataIndex: 'signalCount', width: 90 },
                  { title: '问题簇', dataIndex: 'clusterCount', width: 90 },
                  { title: '影响用户', dataIndex: 'affectedUserCount', width: 100 },
                ]}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有来源分布数据" />
            )}
          </Card>
        </Col>
      </Row>

      <Card className="scene-card" title="模块热点" loading={loading}>
        {overview?.moduleHotspots?.length ? (
          <Table
            rowKey={(record) => `${record.moduleId || 'unmapped'}:${record.moduleName}`}
            dataSource={overview.moduleHotspots}
            pagination={false}
            columns={[
              { title: '模块', dataIndex: 'moduleName' },
              { title: '问题簇', dataIndex: 'clusterCount', width: 90 },
              { title: '待处理', dataIndex: 'openClusterCount', width: 90 },
              { title: '已转缺陷', dataIndex: 'convertedClusterCount', width: 100 },
              { title: '影响用户', dataIndex: 'affectedUserCount', width: 100 },
              { title: '高风险簇', dataIndex: 'highAnomalyClusterCount', width: 100 },
            ]}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有模块热点数据" />
        )}
      </Card>
      </>
      )}
    </PageLayout>
  );
};

export default ProjectQualityInsights;
