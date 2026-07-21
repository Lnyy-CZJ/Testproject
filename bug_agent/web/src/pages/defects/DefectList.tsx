import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { logger } from '../../utils/logger';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Table,
  Button,
  Tag,
  Input,
  Select,
  Space,
  Avatar,
  Card,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import {
  PlusOutlined,
  SearchOutlined, ReloadOutlined,
  BugOutlined, ClockCircleOutlined, ToolOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import { listDefects, getProjectStats } from '../../api';
import { useProject } from '../../contexts/projectContext';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageFilterBar from '../../components/layout/PageFilterBar';
import PageLayout from '../../components/layout/PageLayout';
import type { Defect, Iteration } from '../../types';
import { severityConfig, priorityConfig, defectStatusConfig as statusConfig, typeLabels } from '../../constants/defect';
import { formatDateTime } from '../../utils/formatDate';

interface ProjectStatsData {
  total: number;
  pending: number;
  fixing: number;
  completed: number;
}

interface DefectQueryParams {
  [key: string]: string | number | undefined;
  projectId: number;
  page: number;
  pageSize: number;
  keyword?: string;
  status?: string;
  severity?: string;
  priority?: string;
  type?: string;
  assigneeId?: string;
  iterationId?: string;
  tags?: string;
}

export default function DefectList() {
  const { projectId: rawProjectId, iterations, currentIteration } = useProject();
  const projectId = rawProjectId ?? 0;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<Defect[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(Number(searchParams.get('page')) || 1);
  const [pageSize, setPageSize] = useState(20);
  const [stats, setStats] = useState({ total: 0, pending: 0, fixing: 0, done: 0 });

  const currentIterationId = searchParams.get('iterationId') || undefined;

  const loadingRef = useRef(false);
  const statsLoadingRef = useRef(false);
  const iterationInitRef = useRef(false);

  useEffect(() => {
    if (iterationInitRef.current) return;
    if (searchParams.get('iterationId')) {
      iterationInitRef.current = true;
      return;
    }
    const lastIterationId = localStorage.getItem('lastIterationId');
    const hasLastIteration = lastIterationId && (iterations || []).some((iteration: Iteration) => String(iteration.id) === lastIterationId);
    if (hasLastIteration) {
      iterationInitRef.current = true;
      const params = new URLSearchParams(searchParams);
      params.set('iterationId', String(lastIterationId));
      setSearchParams(params, { replace: true });
      return;
    }
    if (currentIteration?.id) {
      iterationInitRef.current = true;
      const params = new URLSearchParams(searchParams);
      params.set('iterationId', String(currentIteration.id));
      setSearchParams(params, { replace: true });
    }
  }, [currentIteration, iterations, searchParams, setSearchParams]);

  const loadStats = useCallback(async () => {
    if (!projectId || statsLoadingRef.current) return;
    statsLoadingRef.current = true;
    try {
      const res = await getProjectStats(projectId);
      setStats({
        total: res.data?.total || 0,
        pending: res.data?.pending || 0,
        fixing: res.data?.fixing || 0,
        done: res.data?.completed || 0,
      });
    } catch (err) { logger.error('加载统计数据失败:', err); }
    finally { statsLoadingRef.current = false; }
  }, [projectId]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  const fetchData = useCallback(async () => {
    if (!projectId || loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const params: DefectQueryParams = {
        projectId,
        page, pageSize,
        keyword: searchParams.get('keyword') || undefined,
        status: searchParams.get('status') || undefined,
        severity: searchParams.get('severity') || undefined,
        priority: searchParams.get('priority') || undefined,
        type: searchParams.get('type') || undefined,
        assigneeId: searchParams.get('assigneeId') || undefined,
        iterationId: searchParams.get('iterationId') || undefined,
        tags: searchParams.get('tags') || undefined,
      };
      const res = await listDefects(params);
      setData(res.data?.items || []);
      setTotal(res.data?.total || 0);
    } catch {
      message.error('加载失败');
    }
    finally { setLoading(false); loadingRef.current = false; }
  }, [page, pageSize, projectId, searchParams]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const updateParam = (key: string, value: string) => {
    if (key === 'iterationId') {
      if (value) {
        localStorage.setItem('lastIterationId', value);
      } else {
        localStorage.removeItem('lastIterationId');
      }
    }
    const params = new URLSearchParams(searchParams);
    if (value) params.set(key, value); else params.delete(key);
    if (key !== 'page') params.set('page', '1');
    setSearchParams(params);
  };

  const navigateToDefect = (record: Defect) => {
    navigate(`/projects/${projectId}/defects/${record.id}`);
  };

  const clearFilters = () => {
    setSearchParams({});
  };

  const hasActiveFilters = currentIterationId ||
    searchParams.get('keyword') || searchParams.get('status') || searchParams.get('severity') ||
    searchParams.get('priority') || searchParams.get('type') || searchParams.get('assigneeId') ||
    searchParams.get('tags');

  const columns: TableColumnsType<Defect> = useMemo(() => [
    {
      title: '缺陷信息',
      key: 'info',
      render: (_value: unknown, record) => {
        const severity = severityConfig[record.severity] || severityConfig.normal;
        const priority = priorityConfig[record.priority] || priorityConfig.P2;
        const status = statusConfig[record.status] || statusConfig.new;

        return (
          <div className="flex items-start gap-3 py-1">
            <div
              className="w-1 h-10 rounded-full flex-shrink-0 mt-0.5"
              style={{ background: severity.color }}
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-slate-400 text-xs font-mono">{record.code}</span>
                <span className="text-slate-800 font-medium text-sm truncate">{record.title}</span>
              </div>
              <div className="flex items-center gap-2">
                <Tag style={{ color: severity.color, borderColor: severity.color, fontSize: 11 }}>
                  {severity.label}
                </Tag>
                <Tag style={{ color: priority.color, borderColor: priority.color, fontSize: 11 }}>
                  {priority.label}
                </Tag>
                <Tag style={{ color: status.color, borderColor: status.color, fontSize: 11 }}>
                  {status.label}
                </Tag>
              </div>
            </div>
          </div>
        );
      },
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 110,
      render: (v: string) => v ? (
        <Tag style={{ fontSize: 11 }}>{typeLabels[v]}</Tag>
      ) : <span className="text-slate-300">-</span>,
    },
    {
      title: '指派给',
      dataIndex: ['assignee', 'nickname'],
      width: 120,
      render: (v: string) => v ? (
        <div className="flex items-center gap-2">
          <Avatar size={24} className="bg-purple-500 text-xs flex-shrink-0">
            {v[0]}
          </Avatar>
          <span className="text-slate-600 text-sm truncate">{v}</span>
        </div>
      ) : (
        <span className="text-slate-300 text-sm">未分配</span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      width: 150,
      render: (v: string) => (
        <span className="text-slate-500 text-sm">
          {v ? formatDateTime(v) : '-'}
        </span>
      ),
    },
  ], [projectId]);

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '全部', value: stats.total, icon: <BugOutlined />, tone: 'cyan' },
          { key: 'pending', label: '待处理', value: stats.pending, icon: <ClockCircleOutlined />, tone: 'amber' },
          { key: 'fixing', label: '进行中', value: stats.fixing, icon: <ToolOutlined />, tone: 'purple' },
          { key: 'done', label: '已完成', value: stats.done, icon: <CheckCircleOutlined />, tone: 'green' },
        ]}
        actions={(
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchData}>
              刷新
            </Button>
            <Button
              type="primary"
              className="brand-button"
              icon={<PlusOutlined />}
              onClick={() => navigate(`/projects/${projectId}/defects/create`)}
            >
              新建缺陷
            </Button>
          </Space>
        )}
      />

      <PageFilterBar
        filters={
          <>
            <Select
              placeholder="迭代" style={{ width: 130 }} allowClear
              value={currentIterationId ? Number(currentIterationId) : undefined}
              onChange={(v) => updateParam('iterationId', v ? String(v) : '')}
              options={(iterations || []).map((iteration: Iteration) => ({ value: iteration.id, label: iteration.name }))}
            />
            <Input
              placeholder="搜索标题或编号"
              prefix={<SearchOutlined className="text-slate-400" />}
              defaultValue={searchParams.get('keyword') || ''}
              onPressEnter={(e) => updateParam('keyword', (e.target as HTMLInputElement).value)}
              style={{ width: '100%', maxWidth: 200 }}
              allowClear
              onChange={(e) => { if (!e.target.value) updateParam('keyword', ''); }}
            />
            <Select placeholder="状态" style={{ width: 110 }} allowClear
              value={searchParams.get('status') || undefined}
              onChange={(v) => updateParam('status', v || '')}
              options={Object.entries(statusConfig).map(([k, v]) => ({ value: k, label: v.label }))}
            />
            <Select placeholder="严重级别" style={{ width: 110 }} allowClear
              value={searchParams.get('severity') || undefined}
              onChange={(v) => updateParam('severity', v || '')}
              options={Object.entries(severityConfig).map(([k, v]) => ({ value: k, label: v.label }))}
            />
            <Select placeholder="优先级" style={{ width: 100 }} allowClear
              value={searchParams.get('priority') || undefined}
              onChange={(v) => updateParam('priority', v || '')}
              options={Object.entries(priorityConfig).map(([k, v]) => ({ value: k, label: v.label }))}
            />
            <Select placeholder="类型" style={{ width: 110 }} allowClear
              value={searchParams.get('type') || undefined}
              onChange={(v) => updateParam('type', v || '')}
              options={Object.entries(typeLabels).map(([k, v]) => ({ value: k, label: v }))}
            />
          </>
        }
        actions={
          hasActiveFilters ? (
            <Button type="link" size="small" onClick={clearFilters}>
              清除筛选
            </Button>
          ) : undefined
        }
        result={<span className="text-slate-500 text-sm">共 {total} 条</span>}
      />

      <Card
        className="scene-card"
        title="缺陷列表"
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          size="middle"
          tableLayout="fixed"
          pagination={{
            current: page, pageSize, total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              setPage(p); setPageSize(ps);
              setSearchParams(prev => { const next = new URLSearchParams(prev); next.set('page', String(p)); return next; });
            },
          }}
          onRow={(record) => ({
            onClick: () => navigateToDefect(record),
            onKeyPress: (e: React.KeyboardEvent) => {
              if (e.key === 'Enter') navigateToDefect(record);
            },
            tabIndex: 0,
            role: 'button',
            'aria-label': `查看缺陷 ${record.code}`,
            style: { cursor: 'pointer' },
          })}
        />
      </Card>
    </PageLayout>
  );
}
