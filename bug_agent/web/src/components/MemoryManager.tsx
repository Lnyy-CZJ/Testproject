import React, { useState, useEffect, useCallback } from 'react';
import { Button, Modal, Form, Input, Select, Empty, Spin, Space } from 'antd';
import { message } from '../utils/appMessage';
import { getErrorMessage } from '../utils/error';
import { PlusOutlined, BulbOutlined } from '@ant-design/icons';
import MemoryCard from './MemoryCard';
import type { AgentMemory } from '../types';
import {
  listProjectMemories, listIterationMemories,
  createProjectMemory, createIterationMemory,
  updateMemory, deleteMemory, toggleMemory,
} from '../api';

const { TextArea } = Input;

const categoryOptions = [
  { value: 'architecture', label: '架构' },
  { value: 'convention', label: '规范' },
  { value: 'common_error', label: '常见错误' },
  { value: 'fix_strategy', label: '修复策略' },
  { value: 'avoid_strategy', label: '规避策略' },
  { value: 'iteration_context', label: '迭代上下文' },
];

interface MemoryManagerProps {
  projectId: number;
  iterationId?: number;
}

const MemoryManager: React.FC<MemoryManagerProps> = ({ projectId, iterationId }) => {
  const [memories, setMemories] = useState<AgentMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingMemory, setEditingMemory] = useState<AgentMemory | null>(null);
  const [form] = Form.useForm();

  const fetchMemories = useCallback(async () => {
    setLoading(true);
    try {
      const res = iterationId
        ? await listIterationMemories(projectId, iterationId)
        : await listProjectMemories(projectId);
      setMemories(res.data?.items || []);
    } catch {
      message.error('获取记忆列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId, iterationId]);

  useEffect(() => {
    if (projectId) void fetchMemories();
  }, [fetchMemories, projectId]);

  const openModal = (memory?: AgentMemory) => {
    setEditingMemory(memory || null);
    if (memory) {
      form.setFieldsValue({ category: memory.category, content: memory.content });
    } else {
      form.resetFields();
    }
    setModalVisible(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields() as { category: string; content: string };
      if (editingMemory) {
        await updateMemory(projectId, editingMemory.id, values);
        message.success('记忆已更新');
      } else if (iterationId) {
        await createIterationMemory(projectId, iterationId, values);
        message.success('记忆已添加');
      } else {
        await createProjectMemory(projectId, values);
        message.success('记忆已添加');
      }
      setModalVisible(false);
      void fetchMemories();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleDelete = async (memoryId: number) => {
    try {
      await deleteMemory(projectId, memoryId);
      message.success('记忆已删除');
      void fetchMemories();
    } catch {
      message.error('删除失败');
    }
  };

  const handleToggle = async (memoryId: number) => {
    try {
      await toggleMemory(projectId, memoryId);
      void fetchMemories();
    } catch {
      message.error('操作失败');
    }
  };

  const enabledCount = memories.filter(m => m.enabled).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <Space>
          <BulbOutlined style={{ color: '#a855f7' }} />
          <span className="text-sm text-slate-500">
            共 {memories.length} 条记忆，{enabledCount} 条已启用
          </span>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal()} className="brand-button">
          添加记忆
        </Button>
      </div>

      {loading ? (
        <div className="text-center py-10"><Spin /></div>
      ) : memories.length === 0 ? (
        <Empty description="暂无 Agent 记忆" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Button type="primary" onClick={() => openModal()} className="brand-button">添加第一条记忆</Button>
        </Empty>
      ) : (
        <div>
          {memories.map((memory) => (
            <MemoryCard
              key={memory.id}
              memory={memory}
              onEdit={openModal}
              onDelete={handleDelete}
              onToggle={handleToggle}
            />
          ))}
        </div>
      )}

      <Modal
        title={editingMemory ? '编辑记忆' : '添加记忆'}
        open={modalVisible}
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        okText="保存"
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="category" label="类别" rules={[{ required: true, message: '请选择类别' }]}>
            <Select options={categoryOptions} placeholder="选择记忆类别" />
          </Form.Item>
          <Form.Item
            name="content"
            label="内容"
            rules={[
              { required: true, message: '请输入记忆内容' },
              { max: 500, message: '内容不能超过500字' },
            ]}
          >
            <TextArea rows={4} placeholder="输入记忆内容，如：登录模块使用 JWT 认证，token 存储在 httpOnly cookie 中" maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default MemoryManager;
