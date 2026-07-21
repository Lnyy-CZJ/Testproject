import { Tag, Avatar, Typography, Tooltip, Button } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import type { Defect } from '../../../types';
import type { DetailMetaItem } from '../types';
import {
  severityLabels, severityColors, priorityColors, typeLabels,
} from '../../../constants/defect';
import dayjs from 'dayjs';
import '../defect-detail.css';

const { Text } = Typography;

interface DefectOverviewProps {
  defect: Defect;
  onEdit: () => void;
}

export default function DefectOverview({ defect, onEdit }: DefectOverviewProps) {
  const defectOverviewInfo: DetailMetaItem[] = [
    { label: '严重程度', value: <Tag color={severityColors[defect.severity]}>{severityLabels[defect.severity]}</Tag> },
    { label: '优先级', value: <Tag color={priorityColors[defect.priority]}>{defect.priority}</Tag> },
    { label: '类型', value: defect.type ? typeLabels[defect.type] || defect.type : <Text type="secondary">未设置</Text> },
    {
      label: '负责人',
      value: defect.assignee ? (
        <span className="inline-flex items-center gap-1">
          <Avatar size={18} className="brand-button">
            {defect.assignee.nickname?.[0] || defect.assignee.username?.[0]}
          </Avatar>
          <span>{defect.assignee.nickname || defect.assignee.username}</span>
        </span>
      ) : (
        <Text type="secondary">未指派</Text>
      ),
    },
    { label: '报告人', value: defect.reporter?.nickname || defect.reporter?.username || '未识别' },
    { label: '迭代', value: defect.iteration ? defect.iteration.name : <Text type="secondary">未关联</Text> },
    { label: '创建时间', value: dayjs(defect.createdAt).format('MM-DD HH:mm') },
    { label: '最后更新', value: dayjs(defect.updatedAt).format('MM-DD HH:mm') },
  ];

  return (
    <div className="utility-card action-card">
      <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-100">
        <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">缺陷信息</span>
        <Tooltip title="编辑">
          <Button type="text" size="small" icon={<EditOutlined />} onClick={onEdit} className="edit-btn-color" />
        </Tooltip>
      </div>
      <div className="space-y-0">
        {defectOverviewInfo.map((item, idx) => (
          <div
            key={item.label}
            className={`flex items-center justify-between gap-3 py-2 ${idx < defectOverviewInfo.length - 1 ? 'border-b border-slate-50' : ''}`}
          >
            <span className="shrink-0 text-xs text-slate-400">{item.label}</span>
            <span className="text-sm text-slate-700 text-right">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
