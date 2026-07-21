import { useState, useEffect, useCallback, useMemo } from 'react';
import { logger } from '../../utils/logger';
import { useNavigate } from 'react-router-dom';
import { Card, Typography, Space, Button, Spin, Progress, Row, Col } from 'antd';
import {
  BugOutlined, CheckCircleOutlined, ClockCircleOutlined,
  ExclamationCircleOutlined, SyncOutlined, ArrowRightOutlined,
} from '@ant-design/icons';
import { listDefects, getProjectStats } from '../../api';
import { useProject } from '../../contexts/projectContext';
import type { Defect } from '../../types';
import { AGENT_TYPES } from '../../types';
import { appStorage } from '../../utils/storage';
import { getAgentTagColor, getAgentShortLabel } from '../../utils/agentType';
import dayjs from 'dayjs';
import PageLayout from '../../components/layout/PageLayout';
import PageContent from '../../components/layout/PageContent';
import PageMetricSection from '../../components/layout/PageMetricSection';
import RecentDefectList from '../../components/RecentDefectList';

const { Text } = Typography;

interface ProjectStatsData {
  total: number;
  pending: number;
  fixing: number;
  completed: number;
  urgent: number;
}

export default function ProjectDashboard() {
  const { project, projectId, currentIteration } = useProject();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [recentDefects, setRecentDefects] = useState<Defect[]>([]);
  const [stats, setStats] = useState({
    total: 0, pending: 0, fixing: 0, completed: 0, urgent: 0,
  });
  
  const loadData = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const [statsRes, defectsRes] = await Promise.all([
        getProjectStats(projectId),
        listDefects({ projectId, size: 5, sortBy: 'created_at', orderBy: 'desc' }),
      ]);

      setStats(statsRes.data || { total: 0, pending: 0, fixing: 0, completed: 0, urgent: 0 });
      setRecentDefects(defectsRes.data?.items || []);
    } catch (err) { logger.error('加载仪表盘失败:', err); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    loadData();
  }, [projectId, loadData]);

  const iterationProgress = useMemo(() => {
    if (!currentIteration) return { percent: 0, completed: 0, total: 0, remainingDays: 0 };
    const start = dayjs(currentIteration.startDate);
    const end = dayjs(currentIteration.endDate);
    const now = dayjs();
    const total = end.diff(start, 'day');
    const elapsed = now.diff(start, 'day');
    const remainingDays = end.diff(now, 'day');
    const percent = total > 0 ? Math.min(100, Math.max(0, Math.round((elapsed / total) * 100))) : 0;
    return { percent, completed: elapsed, total, remainingDays: Math.max(0, remainingDays) };
  }, [currentIteration]);

  if (loading) return <div className="text-center py-20"><Spin size="large" /></div>;

  return (
    <PageLayout>
      <PageContent>

      <PageMetricSection
        items={[
          { key: 'total', label: '全部缺陷', value: stats.total, icon: <BugOutlined />, tone: 'purple' },
          { key: 'pending', label: '待处理', value: stats.pending, icon: <ClockCircleOutlined />, tone: 'amber' },
          { key: 'fixing', label: '处理中', value: stats.fixing, icon: <SyncOutlined />, tone: 'cyan' },
          { key: 'completed', label: '已完成', value: stats.completed, icon: <CheckCircleOutlined />, tone: 'green' },
          { key: 'urgent', label: '紧急缺陷', value: stats.urgent, icon: <ExclamationCircleOutlined />, tone: 'rose' },
        ]}
        actions={(
          <Space wrap>
            <Button type="primary" className="brand-button" icon={<BugOutlined />} onClick={() => navigate(`/projects/${projectId}/defects/create`)}>
              新建缺陷
            </Button>
            <Button icon={<ArrowRightOutlined />} onClick={() => navigate(`/projects/${projectId}/defects`)}>
              进入缺陷列表
            </Button>
          </Space>
        )}
      />



      <Row gutter={[24, 24]}>
        <Col xs={24} lg={16}>
          <Card 
            className="scene-card"
            title="最近缺陷"
            extra={
              <Button type="link" onClick={() => navigate(`/projects/${projectId}/defects`)}>
                查看全部 <ArrowRightOutlined />
              </Button>
            }
          >
            <RecentDefectList
              defects={recentDefects}
              onSelect={(defect) => navigate(`/projects/${projectId}/defects/${defect.id}`)}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card 
            className="utility-card"
            title="迭代进度" 
          >
            {currentIteration ? (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <Text type="secondary">{currentIteration.name}</Text>
                  <Text strong>{iterationProgress.percent}%</Text>
                </div>
                <Progress percent={iterationProgress.percent} size="small" showInfo={false} strokeColor="#a855f7" />
                <div className="flex items-center justify-between text-xs text-slate-400 mt-1">
                  <span>{currentIteration.status === 'active' ? '进行中' : currentIteration.status === 'completed' ? '已完成' : '计划中'}</span>
                  <span>剩余 {iterationProgress.remainingDays} 天</span>
                </div>
              </div>
            ) : (
              <div className="text-center py-4">
                <Text type="secondary">暂无迭代</Text>
              </div>
            )}
          </Card>

          <Card 
            className="utility-card"
            title="我的 AGENT" 
          >
            <div className="space-y-3">
              {(() => {
                const user = appStorage.getUser<{ agentTypes?: string[] }>();
                const myTypes = user?.agentTypes?.length ? user.agentTypes : [];
                const displayTypes = myTypes.length > 0
                  ? AGENT_TYPES.filter(a => myTypes.includes(a.key))
                  : AGENT_TYPES;
                const colorMap: Record<string, { bg: string; iconBg: string; text: string }> = {
                  purple: { bg: '#faf5ff', iconBg: '#f3e8ff', text: '#7e22ce' },
                  pink:   { bg: '#fdf2f8', iconBg: '#fce7f3', text: '#be185d' },
                  blue:   { bg: '#eff6ff', iconBg: '#dbeafe', text: '#1d4ed8' },
                  cyan:   { bg: '#ecfeff', iconBg: '#cffafe', text: '#0e7490' },
                  green:  { bg: '#f0fdf4', iconBg: '#dcfce7', text: '#15803d' },
                  orange: { bg: '#fff7ed', iconBg: '#ffedd5', text: '#c2410c' },
                };
                return displayTypes.map(agent => {
                  const color = getAgentTagColor(agent.key);
                  const shortLabel = getAgentShortLabel(agent.key);
                  const palette = colorMap[color] || colorMap.purple;
                  return (
                    <div key={agent.key} className="flex items-center gap-3 p-3 rounded-lg" style={{ background: palette.bg }}>
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: palette.iconBg }}>
                        <span className="text-sm font-medium" style={{ color: palette.text }}>{shortLabel}</span>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-slate-900">{agent.label}</div>
                        <div className="text-xs text-slate-400">{agent.desc}</div>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          </Card>
        </Col>
      </Row>
      </PageContent>
    </PageLayout>
  );
}
