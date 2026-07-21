import React from 'react';
import { Tag, Switch, Button, Space, Popconfirm } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { AgentMemory } from '../types';

const categoryLabels: Record<string, string> = {
  architecture: '架构', convention: '规范', common_error: '常见错误',
  fix_strategy: '修复策略', avoid_strategy: '规避策略', iteration_context: '迭代上下文',
};
const categoryColors: Record<string, string> = {
  architecture: 'purple', convention: 'blue', common_error: 'red',
  fix_strategy: 'green', avoid_strategy: 'orange', iteration_context: 'cyan',
};
const sourceLabels: Record<string, string> = {
  auto_extract: '自动提取', manual: '手动录入', pr_rejection: 'PR拒绝',
};

interface MemoryCardProps {
  memory: AgentMemory;
  onEdit: (memory: AgentMemory) => void;
  onDelete: (memoryId: number) => void;
  onToggle: (memoryId: number) => void;
}

const MemoryCard: React.FC<MemoryCardProps> = ({ memory, onEdit, onDelete, onToggle }) => {
  return (
    <div
      style={{
        border: '1px solid #e2e8f0',
        borderRadius: 12,
        padding: '12px 16px',
        marginBottom: 8,
        opacity: memory.enabled ? 1 : 0.55,
        transition: 'opacity 0.2s',
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <Space size={[6, 6]}>
          <Tag color={categoryColors[memory.category] || 'default'} style={{ borderRadius: 6 }}>
            {categoryLabels[memory.category] || memory.category}
          </Tag>
          <Tag style={{ borderRadius: 6, fontSize: 11 }}>
            {sourceLabels[memory.source] || memory.source}
          </Tag>
        </Space>
        <Space size={4}>
          <Switch
            size="small"
            checked={memory.enabled}
            onChange={() => onToggle(memory.id)}
          />
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => onEdit(memory)} />
          <Popconfirm title="确定删除此记忆？" onConfirm={() => onDelete(memory.id)}>
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      </div>
      <div className="text-sm text-slate-700 leading-6">{memory.content}</div>
    </div>
  );
};

export default MemoryCard;
