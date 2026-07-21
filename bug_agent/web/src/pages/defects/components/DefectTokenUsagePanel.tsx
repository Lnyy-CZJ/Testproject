import { useState, useEffect, useCallback } from 'react';
import { Card, Descriptions, Button, Table, Spin, Empty, Tag } from 'antd';
import { BarChartOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { getDefectTokenUsage, getDefectTokenUsageDetails } from '../../../api/defect';
import type { TokenUsageSummary, TokenUsageRecord } from '../../../api/types';
import { formatDateTime } from '../../../utils/formatDate';

interface DefectTokenUsagePanelProps {
  defectId: number;
}

const CONSUMPTION_TYPE_LABELS: Record<string, string> = {
  analysis: 'AI 分析',
  fix: 'AI 修复',
};

function formatTokenNumber(n: number): string {
  return n.toLocaleString('en-US');
}

function formatCost(n: number): string {
  return `$${n.toFixed(4)}`;
}

function getTypeLabel(type: string): string {
  return CONSUMPTION_TYPE_LABELS[type] || type;
}

function getTypeTagColor(type: string): string {
  switch (type) {
    case 'analysis': return 'blue';
    case 'fix': return 'green';
    default: return 'default';
  }
}

export default function DefectTokenUsagePanel({ defectId }: DefectTokenUsagePanelProps) {
  const [summaries, setSummaries] = useState<TokenUsageSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [details, setDetails] = useState<TokenUsageRecord[] | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getDefectTokenUsage(defectId);
      setSummaries(result.data || []);
    } catch {
      setSummaries([]);
    } finally {
      setLoading(false);
    }
  }, [defectId]);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  const handleShowDetails = async () => {
    if (details !== null) {
      setDetails(null);
      return;
    }
    setDetailsLoading(true);
    try {
      const result = await getDefectTokenUsageDetails(defectId);
      setDetails(result.data || []);
    } catch {
      setDetails([]);
    } finally {
      setDetailsLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="tab-content text-center py-10">
        <Spin />
      </div>
    );
  }

  if (summaries.length === 0) {
    return (
      <div className="tab-content">
        <Empty description="暂无 Token 消耗记录" />
      </div>
    );
  }

  const totalCost = summaries.reduce((s, r) => s + r.estimatedCostUsd, 0);
  const totalTokens = summaries.reduce((s, r) => s + r.totalTokens, 0);
  const totalCalls = summaries.reduce((s, r) => s + r.callCount, 0);

  const detailColumns = [
    {
      title: '时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
    {
      title: '类型',
      dataIndex: 'consumptionType',
      key: 'consumptionType',
      width: 100,
      render: (v: string) => <Tag color={getTypeTagColor(v)}>{getTypeLabel(v)}</Tag>,
    },
    {
      title: 'Provider',
      dataIndex: 'provider',
      key: 'provider',
      width: 100,
    },
    {
      title: 'Model',
      dataIndex: 'modelName',
      key: 'modelName',
      width: 140,
    },
    {
      title: 'Prompt Tokens',
      dataIndex: 'promptTokens',
      key: 'promptTokens',
      width: 120,
      align: 'right' as const,
      render: (v: number) => formatTokenNumber(v),
    },
    {
      title: 'Completion Tokens',
      dataIndex: 'completionTokens',
      key: 'completionTokens',
      width: 140,
      align: 'right' as const,
      render: (v: number) => formatTokenNumber(v),
    },
    {
      title: 'Total Tokens',
      dataIndex: 'totalTokens',
      key: 'totalTokens',
      width: 120,
      align: 'right' as const,
      render: (v: number) => formatTokenNumber(v),
    },
    {
      title: '费用',
      dataIndex: 'estimatedCostUsd',
      key: 'estimatedCostUsd',
      width: 100,
      align: 'right' as const,
      render: (v: number) => formatCost(v),
    },
    {
      title: '耗时(ms)',
      dataIndex: 'durationMs',
      key: 'durationMs',
      width: 100,
      align: 'right' as const,
      render: (v: number) => formatTokenNumber(v),
    },
  ];

  return (
    <div className="tab-content">
      {/* 汇总概览 */}
      <Card size="small" title={<><BarChartOutlined /> 汇总概览</>} className="mb-4">
        <Descriptions column={3} size="small">
          <Descriptions.Item label="总调用次数">{formatTokenNumber(totalCalls)}</Descriptions.Item>
          <Descriptions.Item label="总 Token 数">{formatTokenNumber(totalTokens)}</Descriptions.Item>
          <Descriptions.Item label="总预估费用">{formatCost(totalCost)}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 按类型分组 */}
      {summaries.map((item) => (
        <Card
          key={item.consumptionType}
          size="small"
          title={<Tag color={getTypeTagColor(item.consumptionType)}>{getTypeLabel(item.consumptionType)}</Tag>}
          className="mb-4"
        >
          <Descriptions column={3} size="small">
            <Descriptions.Item label="调用次数">{formatTokenNumber(item.callCount)}</Descriptions.Item>
            <Descriptions.Item label="Prompt Tokens">{formatTokenNumber(item.promptTokens)}</Descriptions.Item>
            <Descriptions.Item label="Completion Tokens">{formatTokenNumber(item.completionTokens)}</Descriptions.Item>
            <Descriptions.Item label="Total Tokens">{formatTokenNumber(item.totalTokens)}</Descriptions.Item>
            <Descriptions.Item label="预估费用">{formatCost(item.estimatedCostUsd)}</Descriptions.Item>
            <Descriptions.Item label="总耗时">{formatTokenNumber(item.durationMs)} ms</Descriptions.Item>
          </Descriptions>
        </Card>
      ))}

      {/* 查看详情按钮 */}
      <div className="text-center mt-2">
        <Button
          type="link"
          icon={<UnorderedListOutlined />}
          onClick={() => void handleShowDetails()}
          loading={detailsLoading}
        >
          {details !== null ? '收起详情' : '查看详情'}
        </Button>
      </div>

      {/* 详情列表 */}
      {details !== null && (
        <Table
          dataSource={details}
          columns={detailColumns}
          rowKey="id"
          size="small"
          pagination={details.length > 10 ? { pageSize: 10 } : false}
          scroll={{ x: 1100 }}
          className="mt-4"
        />
      )}
    </div>
  );
}
