import { useNavigate } from 'react-router-dom';
import { Tag, Button, Typography, Breadcrumb, Avatar } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import type { Defect } from '../../types';
import { useProject } from '../../contexts/projectContext';
import {
  severityLabels, severityColors, priorityColors, statusLabels, statusColors,
  typeLabels,
} from '../../constants/defect';
import DefectStatusSteps from './components/DefectStatusSteps';

const { Title } = Typography;

interface DefectHeaderProps {
  defect: Defect;
  onBack: () => void;
}

export default function DefectHeader({ defect, onBack }: DefectHeaderProps) {
  const navigate = useNavigate();
  const { project, projectId } = useProject();

  return (
    <div className="summary-header">
      <Breadcrumb
        className="mb-2"
        items={[
          { title: <a onClick={() => navigate('/projects')} className="text-slate-400 hover:text-purple-600">项目列表</a> },
          { title: <a onClick={() => navigate(`/projects/${projectId}`)} className="text-slate-400 hover:text-purple-600">{project?.name}</a> },
          { title: <a onClick={() => navigate(`/projects/${projectId}/defects`)} className="text-slate-400 hover:text-purple-600">缺陷管理</a> },
          { title: <span className="text-slate-600 font-medium">{defect.code}</span> },
        ]}
      />

      <div className="flex items-center gap-3 mb-3">
        <Button
          type="text"
          size="small"
          icon={<ArrowLeftOutlined />}
          onClick={onBack}
          style={{ color: 'var(--slate-400)' }}
        />
        <Title level={4} className="truncate m-0 flex-1 min-w-0">
          {defect.title}
        </Title>
        <Tag
          color={statusColors[defect.status]}
          className="tag-status"
        >
          {statusLabels[defect.status]}
        </Tag>
      </div>

      <div className="flex items-center flex-wrap gap-2 mb-4">
        <Tag color={severityColors[defect.severity]} className="tag-rounded">
          {severityLabels[defect.severity]}
        </Tag>
        <Tag color={priorityColors[defect.priority]} className="tag-rounded">
          {defect.priority}
        </Tag>
        {defect.type ? <Tag className="tag-rounded">{typeLabels[defect.type] || defect.type}</Tag> : null}
        {defect.assignee ? (
          <span className="inline-flex items-center gap-1 text-sm text-slate-600">
            <Avatar size={20} className="avatar-brand">
              {defect.assignee.nickname?.[0] || defect.assignee.username?.[0]}
            </Avatar>
            {defect.assignee.nickname || defect.assignee.username}
          </span>
        ) : (
          <span className="text-sm text-slate-400">未指派</span>
        )}
        <span className="text-xs text-slate-400">
          {defect.code} · {defect.iteration?.name || '未关联迭代'}
        </span>
      </div>

      <DefectStatusSteps defect={defect} />
    </div>
  );
}
