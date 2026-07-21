import React, { useCallback, useEffect, useState } from 'react';
import { Button, Card, Empty, Input, Select, Space, Table, Tag } from 'antd';
import { CheckCircleOutlined, LinkOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { listRegressionItems, updateRegressionItem } from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageFilterBar from '../../components/layout/PageFilterBar';
import PageLoadState from '../../components/PageLoadState';
import PageLayout from '../../components/layout/PageLayout';
import { message } from '../../utils/appMessage';
import type { RegressionItem } from '../../types';
import { getErrorMessage } from '../../utils/error';

const regressionStatusMap: Record<RegressionItem['status'], { color: string; label: string }> = {
  draft: { color: 'default', label: 'draft' },
  active: { color: 'processing', label: 'active' },
  verified: { color: 'success', label: 'verified' },
  archived: { color: 'warning', label: 'archived' },
};

const ProjectRegressionCenter: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);
  const navigate = useNavigate();

  const [items, setItems] = useState<RegressionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [keyword, setKeyword] = useState('');


  const fetchItems = useCallback(async () => {
    if (!pid) {
      setLoadError('无效的项目 ID');
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const res = await listRegressionItems(pid, {
        status: statusFilter,
        q: keyword.trim() || undefined,
      });
      setItems(res.data || []);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '获取回归预防列表失败');
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [keyword, pid, statusFilter]);

  useEffect(() => {
    void fetchItems();
  }, [fetchItems]);

  const handleVerify = async (item: RegressionItem) => {
    setSavingId(item.id);
    try {
      await updateRegressionItem(pid, item.id, { status: 'verified' });
      message.success('回归项已标记为 verified');
      await fetchItems();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '更新回归项失败'));
    } finally {
      setSavingId(null);
    }
  };

  const verifiedCount = items.filter((item) => item.status === 'verified').length;
  const activeCount = items.filter((item) => item.status === 'active').length;
  const linkedDefectCount = items.filter((item) => item.defectId).length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '全部回归项', value: items.length, icon: <ReloadOutlined />, tone: 'purple' },
          { key: 'active', label: '激活中', value: activeCount, icon: <LinkOutlined />, tone: 'cyan' },
          { key: 'verified', label: '已验证', value: verifiedCount, icon: <CheckCircleOutlined />, tone: 'green' },
          { key: 'linked', label: '已关联缺陷', value: linkedDefectCount, icon: <LinkOutlined />, tone: 'amber' },
        ]}
      />

      <PageFilterBar
        testId="project-regression-filter-rail"
        filters={(
          <>
          <Select
            allowClear
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
            style={{ width: 160 }}
            placeholder="按状态筛选"
            options={[
              { label: 'draft', value: 'draft' },
              { label: 'active', value: 'active' },
              { label: 'verified', value: 'verified' },
              { label: 'archived', value: 'archived' },
            ]}
          />
          <Input
            allowClear
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onPressEnter={() => void fetchItems()}
            placeholder="搜索标题 / 指纹"
            prefix={<SearchOutlined className="text-slate-400" />}
            style={{ width: '100%', maxWidth: 220 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void fetchItems()}>
            刷新
          </Button>
          </>
        )}
      />

      <Card className="scene-card" title="回归项列表">
        {loadError ? (
          <PageLoadState subTitle={loadError} onRetry={() => void fetchItems()} />
        ) : (
        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          locale={{ emptyText: <Empty description="当前还没有回归项" /> }}
          pagination={false}
          columns={[
            {
              title: '回归项',
              dataIndex: 'title',
              render: (value: string, record: RegressionItem) => (
                <Space direction="vertical" size={2}>
                  <span style={{ fontWeight: 600 }}>{value}</span>
                  <span style={{ color: '#64748b', fontSize: 12 }}>
                    {record.sourceFingerprint || '未登记指纹'}
                  </span>
                </Space>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 120,
              render: (value: RegressionItem['status']) => {
                const config = regressionStatusMap[value];
                return <Tag color={config.color}>{config.label}</Tag>;
              },
            },
            {
              title: '来源问题簇',
              key: 'cluster',
              width: 120,
              render: (_: unknown, record: RegressionItem) => (
                record.clusterId ? `#${record.clusterId}` : <span style={{ color: '#94a3b8' }}>未关联</span>
              ),
            },
            {
              title: '关联缺陷',
              key: 'defect',
              width: 180,
              render: (_: unknown, record: RegressionItem) => (
                record.defect ? (
                  <Space direction="vertical" size={2}>
                    <span style={{ fontWeight: 600 }}>{record.defect.code}</span>
                    <span style={{ color: '#64748b', fontSize: 12 }}>{record.defect.status}</span>
                  </Space>
                ) : (
                  <span style={{ color: '#94a3b8' }}>未关联缺陷</span>
                )
              ),
            },
            {
              title: '负责人',
              key: 'owner',
              width: 140,
              render: (_: unknown, record: RegressionItem) => (
                record.owner?.nickname || record.owner?.username || <span style={{ color: '#94a3b8' }}>未指派</span>
              ),
            },
            {
              title: '最近验证',
              dataIndex: 'lastVerifiedAt',
              width: 180,
              render: (value?: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : <span style={{ color: '#94a3b8' }}>未验证</span>,
            },
            {
              title: '操作',
              key: 'action',
              width: 240,
              render: (_: unknown, record: RegressionItem) => (
                <Space>
                  {record.status !== 'verified' ? (
                    <Button
                      data-testid={`regression-verify-${record.id}`}
                      type="link"
                      icon={<CheckCircleOutlined />}
                      loading={savingId === record.id}
                      onClick={() => void handleVerify(record)}
                    >
                      标记已验证
                    </Button>
                  ) : null}
                  {record.defectId ? (
                    <Button
                      type="link"
                      icon={<LinkOutlined />}
                      onClick={() => navigate(`/projects/${pid}/defects/${record.defectId}`)}
                    >
                      查看缺陷
                    </Button>
                  ) : null}
                </Space>
              ),
            },
          ]}
        />
        )}
      </Card>
    </PageLayout>
  );
};

export default ProjectRegressionCenter;
