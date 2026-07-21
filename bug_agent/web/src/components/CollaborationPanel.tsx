import { logger } from '../utils/logger';
import { useState, useCallback, useRef } from 'react';
import {
  Card,
  Tag,
  Button,
  Space,
  Progress,
  Spin,
  Typography,
  Empty,
  Alert,
  Descriptions,
  Collapse,
  Timeline,
} from 'antd';
import { message } from '../utils/appMessage';
import {
  TeamOutlined, ThunderboltOutlined, CheckCircleOutlined,
  ClockCircleOutlined, ExclamationCircleOutlined, ReloadOutlined,
} from '@ant-design/icons';
import { useSSEEvent, useSSE } from '../hooks/useSSE';
import { startCollaboration, getAggregatedReport } from '../api';
import type { CollaborationTask, AggregatedReport, AgentResult } from '../types/collaboration';
import { getErrorMessage } from '../utils/error';
import { getAgentTagColor, getAgentFullLabel } from '../utils/agentType';
import { AGENT_TYPES } from '../types';

const { Text, Paragraph } = Typography;

interface CollaborationPanelProps {
  defectId: number;
}

interface CollaborationProgressEvent {
  taskId: number;
  status?: CollaborationTask['status'];
}

interface CollaborationCompletedEvent {
  taskId: number;
}

const statusConfig: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  pending: { color: 'default', icon: <ClockCircleOutlined />, label: 'Pending' },
  running: { color: 'processing', icon: <ThunderboltOutlined />, label: 'Analyzing' },
  completed: { color: 'success', icon: <CheckCircleOutlined />, label: 'Completed' },
  failed: { color: 'error', icon: <ExclamationCircleOutlined />, label: 'Failed' },
  timeout: { color: 'warning', icon: <ClockCircleOutlined />, label: 'Timeout' },
};

export default function CollaborationPanel({ defectId }: CollaborationPanelProps) {
  const [task, setTask] = useState<CollaborationTask | null>(null);
  const [report, setReport] = useState<AggregatedReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const { connected: isConnected } = useSSE([`defect:${defectId}`]);

  const roomName = `defect:${defectId}`;

  const loadAggregatedReport = useCallback(async (taskId: number) => {
    try {
      const res = await getAggregatedReport(taskId);
      setReport(res.data ?? null);
    } catch (err) {
      logger.error('Failed to load aggregated report:', err);
    }
  }, []);

  useSSEEvent('collaboration:started', useCallback((data: unknown) => {
    if (!data || typeof data !== 'object') return;
    const d = data as Record<string, unknown>;
    if (typeof d.id !== 'number' && typeof d.id !== 'string') return;
    setTask(data as CollaborationTask);
    message.info('Multi-agent collaboration started');
  }, []));

  useSSEEvent('collaboration:progress', useCallback((data: unknown) => {
    if (!data || typeof data !== 'object') return;
    const d = data as Record<string, unknown>;
    if (!d.taskId) return;
    const progress = data as CollaborationProgressEvent;
    setTask((prev: CollaborationTask | null) => (
      prev && prev.id === progress.taskId
        ? { ...prev, status: progress.status || 'running' }
        : prev
    ));
  }, []));

  useSSEEvent('collaboration:completed', useCallback((data: unknown) => {
    if (!data || typeof data !== 'object') return;
    const d = data as Record<string, unknown>;
    if (!d.taskId) return;
    const completed = data as CollaborationCompletedEvent;
    setTask((prev: CollaborationTask | null) => (
      prev && prev.id === completed.taskId
        ? { ...prev, status: 'completed', completedAt: new Date().toISOString() }
        : prev
    ));
    message.success('Multi-agent collaboration completed!');
    void loadAggregatedReport(completed.taskId);
  }, [loadAggregatedReport]));

  const handleStartCollaboration = async () => {
    if (!selectedAgents.length) { message.warning('请至少选择一个 Agent 类型'); return; }
    setLoading(true);
    try {
      const res = await startCollaboration({
        defectId,
        agentTypes: selectedAgents,
      });
      setTask(res.data ?? null);
      message.success('Collaboration task launched');
    } catch (err: unknown) {
      message.error(getErrorMessage(err, 'Failed to start collaboration'));
    } finally {
      setLoading(false);
    }
  };

  const renderAgentStatus = (agent: AgentResult) => (
    <div key={agent.agentType} className="p-2 rounded bg-slate-50">
      <div className="flex items-center justify-between mb-1">
        <Space size={4}>
          <Tag color={getAgentTagColor(agent.agentType)} style={{ fontSize: 11, margin: 0 }}>{getAgentFullLabel(agent.agentType)}</Tag>
          <Text type="secondary" className="text-xs">
            {statusConfig[agent.status]?.label || agent.status}
          </Text>
        </Space>
        {statusConfig[agent.status]?.icon}
      </div>
      {agent.errorMsg && (
        <Alert type="error" title={agent.errorMsg} showIcon className="mt-1 text-xs" />
      )}
    </div>
  );

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200">
        <Space size={6}>
          <TeamOutlined className="text-slate-500" />
          <span className="text-sm font-medium text-slate-700">多Agent协作</span>
          {!isConnected && <Tag color="warning" style={{ fontSize: 11 }}>离线</Tag>}
          {isConnected && <Tag color="success" style={{ fontSize: 11 }}>在线</Tag>}
        </Space>
        {!task || task.status === 'completed' || task.status === 'failed' ? (
          <Button
            type="primary"
            size="small"
            icon={<ThunderboltOutlined />}
            loading={loading}
            onClick={handleStartCollaboration}
            style={{ background: 'linear-gradient(135deg, #a855f7, #0ea5e9)', border: 'none', fontSize: 12 }}
          >
            启动
          </Button>
        ) : (
          <Button
            icon={<ReloadOutlined />}
            onClick={() => task && loadAggregatedReport(task.id)}
            size="small"
            style={{ fontSize: 12 }}
          >
            刷新
          </Button>
        )}
      </div>
      <div className="px-4 py-3">
      {/* Agent Selection */}
      {(!task || task.status === 'completed' || task.status === 'failed') && (
        <div className="mb-3 p-2 bg-purple-50 rounded">
          <Text type="secondary" className="text-xs block mb-1">选择Agent:</Text>
          <Space wrap size={4}>
            {AGENT_TYPES.map((agent) => (
              <Tag.CheckableTag
                key={agent.key}
                checked={selectedAgents.includes(agent.key)}
                onChange={(checked) => {
                  if (checked) {
                    setSelectedAgents([...selectedAgents, agent.key]);
                  } else {
                    setSelectedAgents(selectedAgents.filter(a => a !== agent.key));
                  }
                }}
                style={{ fontSize: 11 }}
              >
                {agent.label}
              </Tag.CheckableTag>
            ))}
          </Space>
        </div>
      )}

      {/* Running Status */}
      {task && (task.status === 'running' || task.status === 'pending') && (
        <div className="mb-4 text-center py-4">
          <Spin size="large" />
          <div className="mt-3 font-medium text-slate-700">
            Multi-agent analysis in progress...
          </div>
          <Progress
            percent={task.status === 'running' ? 50 : 10}
            status="active"
            strokeColor={{ from: '#a855f7', to: '#0ea5e9' }}
            className="mt-2"
          />
          <Text type="secondary" className="text-xs">
            Task Code: {task.taskCode}
          </Text>
        </div>
      )}

      {/* Completed Report */}
      {report && (
        <Collapse
          defaultActiveKey={['summary']}
          items={[
            {
              key: 'summary',
              label: (
                <Space>
                  <CheckCircleOutlined style={{ color: '#52c41a' }} />
                  <span>Aggregated Report</span>
                  <Tag color={
                    report.riskLevel === 'high' ? 'red' :
                    report.riskLevel === 'medium' ? 'orange' : 'green'
                  }>
                    Risk: {report.riskLevel?.toUpperCase()}
                  </Tag>
                </Space>
              ),
              children: (
                <div className="space-y-4">
                  {/* Consensus */}
                  <Descriptions column={1} size="small" bordered>
                    <Descriptions.Item label="Participating Agents">
                      {report.agents.length}
                    </Descriptions.Item>
                    <Descriptions.Item label="Overall Risk Level">
                      <Tag color={
                        report.riskLevel === 'high' ? 'red' :
                        report.riskLevel === 'medium' ? 'orange' : 'green'
                      }>
                        {report.riskLevel?.toUpperCase()}
                      </Tag>
                    </Descriptions.Item>
                    {Object.entries(report.consensus).map(([level, pct]) => (
                      <Descriptions.Item key={level} label={`${level.toUpperCase()} Consensus`}>
                        <Progress percent={Math.round(pct as number)} size="small" />
                      </Descriptions.Item>
                    ))}
                  </Descriptions>

                  {/* Summary */}
                  {report.summary && (
                    <div className="p-3 bg-blue-50 rounded-lg">
                      <Text strong>Summary</Text>
                      <Paragraph className="mt-2 text-sm whitespace-pre-wrap">
                        {report.summary}
                      </Paragraph>
                    </div>
                  )}

                  {/* Recommendation */}
                  {report.recommendation && (
                    <div className="p-3 bg-green-50 rounded-lg">
                      <Text strong>Recommendation</Text>
                      <Paragraph className="mt-2 text-sm whitespace-pre-wrap">
                        {report.recommendation}
                      </Paragraph>
                    </div>
                  )}

                  {/* Individual Agent Results */}
                  <div>
                    <Text strong className="block mb-2">Agent Results</Text>
                    <Timeline
                      items={report.agents.map((agent: AgentResult) => ({
                        color: agent.status === 'completed' ? 'green' :
                               agent.status === 'failed' ? 'red' : 'blue',
                        children: renderAgentStatus(agent),
                      }))}
                    />
                  </div>
                </div>
              ),
            },
          ]}
        />
      )}

      {/* Failed State */}
      {task && task.status === 'failed' && (
        <Empty description="Collaboration failed" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Button type="primary" onClick={handleStartCollaboration}>
            Retry
          </Button>
        </Empty>
      )}

      {/* Initial State */}
      {!task && (
        <Empty description="Start multi-agent collaboration to analyze this defect from multiple perspectives" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleStartCollaboration}
            style={{ background: 'linear-gradient(135deg, #a855f7, #0ea5e9)', border: 'none' }}
          >
            Start Collaboration
          </Button>
        </Empty>
      )}
      </div>
    </div>
  );
}
