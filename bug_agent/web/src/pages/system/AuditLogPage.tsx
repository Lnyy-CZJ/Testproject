import { logger } from '../../utils/logger';
import { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Tag, Space, Input, Select, DatePicker, Button, Typography, message
} from 'antd';
import type { TableColumnsType } from 'antd';
import {
  SearchOutlined, UserOutlined, FileTextOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { listAuditLogs, getAuditStats } from '../../api';
import type { AuditLogItem, AuditStats } from '../../api';
import PageLayout from '../../components/layout/PageLayout';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageFilterBar from '../../components/layout/PageFilterBar';
import { formatDateTime } from '../../utils/formatDate';
import dayjs from 'dayjs';

const { RangePicker } = DatePicker;
const { Text } = Typography;

const actionLabels: Record<string, string> = {
  create_defect: 'Create Defect',
  update_defect: 'Update Defect',
  change_status: 'Change Status',
  assign_defect: 'Assign Defect',
  verify_defect: 'Verify Defect',
  reject_defect: 'Reject Defect',
  create_comment: 'Add Comment',
  trigger_analysis: 'Trigger Analysis',
  create_fix_task: 'Create Fix Task',
  update_ai_config: 'Update AI Config',
  assign_role: 'Assign Role',
  start_collaboration: 'Start Collaboration',
};

const targetTypeLabels: Record<string, string> = {
  defect: 'Defect',
  project: 'Project',
  user: 'User',
  ai_config: 'AI Config',
  fix_task: 'Fix Task',
  collaboration: 'Collaboration',
  role: 'Role',
};

const statusColorMap: Record<number, string> = {
  200: 'green', 201: 'green', 204: 'green',
  400: 'orange', 401: 'red', 403: 'red', 404: 'gold',
  500: 'red', 502: 'red', 503: 'orange',
};

interface AuditFilters {
  action: string;
  targetType: string;
  startDate: string;
  endDate: string;
}

export default function AuditLogPage() {
  const [logs, setLogs] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [filters, setFilters] = useState<AuditFilters>({
    action: '',
    targetType: '',
    startDate: '',
    endDate: '',
  });

  // 修复：重构数据请求逻辑，移除不安全的类型断言与强依赖 code 字段的判断
  // 增加防御性解析，确保无论后端返回 { data: { list: [] } }、{ data: [] } 或直接 []，Table 都能接收到合法数组
  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAuditLogs({
        page,
        pageSize,
        ...filters,
      });
      
      const paginated = res.data;
      const logsArray: AuditLogItem[] = paginated?.items ?? [];

      setLogs(logsArray);

      const totalVal = paginated?.total ?? logsArray.length;
      setTotal(typeof totalVal === 'number' && totalVal >= 0 ? totalVal : 0);
    } catch (err) {
      logger.error('Failed to load audit logs:', err);
      message.error('获取审核日志失败');
      // 异常时强制重置数据状态，防止渲染残留旧数据或 undefined
      setLogs([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filters, page, pageSize]);

  const loadStats = useCallback(async () => {
    try {
      const res = await getAuditStats();
      if (res.data) {
        setStats(res.data);
      }
    } catch (err) {
      logger.error('Failed to load stats:', err);
    }
  }, []);

  useEffect(() => {
    void loadLogs();
    void loadStats();
  }, [loadLogs, loadStats]);

  const hasActiveFilters = filters.action || filters.targetType || filters.startDate || filters.endDate;

  const clearFilters = () => {
    setFilters({ action: '', targetType: '', startDate: '', endDate: '' });
  };

  const columns: TableColumnsType<AuditLogItem> = [
    {
      title: 'Time',
      dataIndex: 'createdAt',
      width: 170,
      render: (t: string) => formatDateTime(t),
    },
    {
      title: 'User',
      dataIndex: 'username',
      width: 120,
      render: (name: string) => (
        <Space><UserOutlined className="text-slate-400" />{name || '-'}</Space>
      ),
    },
    {
      title: 'Action',
      dataIndex: 'action',
      width: 180,
      render: (action: string) => {
        const displayLabel = actionLabels[action.replace(/^(GET|POST|PUT|DELETE)\s+/, '')] || action;
        const method = action.match(/^(GET|POST|PUT|DELETE)/)?.[1];
        return (
          <Space>
            {method && <Tag color={
              method === 'GET' ? 'blue' : method === 'POST' ? 'green' :
              method === 'PUT' ? 'orange' : 'red'
            }>{method}</Tag>}
            <span>{displayLabel}</span>
          </Space>
        );
      },
    },
    {
      title: 'Target',
      width: 150,
      render: (_value: unknown, record) => (
        <Space>
          <Tag>{targetTypeLabels[record.targetType] || record.targetType}</Tag>
          {record.targetId && <Text code>{record.targetId}</Text>}
        </Space>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'statusCode',
      width: 80,
      render: (code: number) => (
        <Tag color={statusColorMap[code] || 'default'}>{code}</Tag>
      ),
    },
    {
      title: 'Duration',
      dataIndex: 'durationMs',
      width: 90,
      render: (ms: number) => ms > 0 ? `${ms}ms` : '-',
    },
    {
      title: 'IP',
      dataIndex: 'ipAddress',
      width: 140,
      ellipsis: true,
    },
    {
      title: 'Error',
      dataIndex: 'errorMessage',
      ellipsis: true,
      render: (err: string) => err ? (
        <Text type="danger" style={{ fontSize: 12 }}>{err}</Text>
      ) : null,
    },
  ];

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '操作总量', value: stats?.totalLogs || 0, icon: <FileTextOutlined />, tone: 'purple' },
          { key: 'actions', label: '操作类型', value: stats?.topActions?.length || 0, icon: <SearchOutlined />, tone: 'cyan' },
          { key: 'users', label: '活跃用户', value: stats?.activeUsers?.length || 0, icon: <UserOutlined />, tone: 'green' },
        ]}
        actions={(
          <Button icon={<ReloadOutlined />} onClick={() => { void loadLogs(); void loadStats(); }}>
            刷新
          </Button>
        )}
      />

      <PageFilterBar
        filters={(
          <>
            <Input
              placeholder="搜索操作..."
              prefix={<SearchOutlined />}
              allowClear
              style={{ width: 200 }}
              value={filters.action}
              onChange={(e) => setFilters(f => ({ ...f, action: e.target.value }))}
            />
            <Select
              placeholder="目标类型"
              allowClear
              style={{ width: 140 }}
              value={filters.targetType || undefined}
              onChange={(v) => setFilters(f => ({ ...f, targetType: v || '' }))}
              options={Object.entries(targetTypeLabels).map(([k, v]) => ({ value: k, label: v }))}
            />
            <RangePicker
              onChange={(dates) => setFilters(f => ({
                ...f,
                startDate: dates?.[0]?.format('YYYY-MM-DD') || '',
                endDate: dates?.[1]?.format('YYYY-MM-DD') || '',
              }))}
            />
          </>
        )}
        actions={
          hasActiveFilters ? (
            <Button size="small" onClick={clearFilters}>清除筛选</Button>
          ) : undefined
        }
        result={<span className="text-slate-500 text-sm">共 {total} 条记录</span>}
      />

      <Card className="scene-card" title="审计日志">
        <Table
          columns={columns}
          dataSource={logs}
          rowKey={(record, index) => record.id?.toString() ?? String(index)}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => {
              // 修复：优化分页状态更新逻辑，避免 pageSize 变更时 page 状态覆盖冲突
              if (ps !== pageSize) {
                setPageSize(ps);
                setPage(1);
              } else {
                setPage(p);
              }
            },
          }}
          size="middle"
          scroll={{ x: 1200 }}
          locale={{ emptyText: '暂无审计日志数据' }}
        />
      </Card>
    </PageLayout>
  );
}