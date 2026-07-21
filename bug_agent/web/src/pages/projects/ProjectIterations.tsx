import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Modal, Form, Input, Space, Popconfirm, Empty, Tag, Progress, DatePicker, Select, Badge, Spin } from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, LinkOutlined,
  CalendarOutlined, SyncOutlined, UnorderedListOutlined,
  AppstoreOutlined, BulbOutlined,
} from '@ant-design/icons';
import {
  createIteration,
  updateIteration,
  getIteration,
  bindRepo,
  unbindRepo,
  listProjectRepos,
  updateIterRepoBranch,
  listRepoBranches,
  listDefects,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLayout from '../../components/layout/PageLayout';
import MemoryManager from '../../components/MemoryManager';
import { useProject } from '../../contexts/projectContext';
import type { Iteration, ProjectRepo, IterationRepo, Defect } from '../../types';
import dayjs, { type Dayjs } from 'dayjs';
import { getErrorMessage, type RequestError } from '../../utils/error';

const { RangePicker } = DatePicker;
const { TextArea } = Input;

const statusConfig: Record<string, { label: string; color: string }> = {
  planning: { label: '计划中', color: 'default' },
  active: { label: '进行中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  archived: { label: '已归档', color: 'warning' },
};

interface IterationFormValues {
  name: string;
  dateRange: [Dayjs, Dayjs];
  goal?: string;
  status: Iteration['status'];
}

interface RepoBindFormValues {
  repoId: number;
  branch?: string;
}



const ProjectIterations: React.FC = () => {
  const { projectId, iterations, refreshIterations } = useProject();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingIteration, setEditingIteration] = useState<Iteration | null>(null);
  const [form] = Form.useForm();

  // 仓库绑定相关
  const [repoModalVisible, setRepoModalVisible] = useState(false);
  const [kanbanVisible, setKanbanVisible] = useState(false);
  const [kanbanIterationId, setKanbanIterationId] = useState<number | null>(null);
  const [kanbanDefects, setKanbanDefects] = useState<Defect[]>([]);
  const [kanbanLoading, setKanbanLoading] = useState(false);
  const [currentIterationId, setCurrentIterationId] = useState<number | null>(null);
  const [projectRepos, setProjectRepos] = useState<ProjectRepo[]>([]);
  const [boundRepos, setBoundRepos] = useState<IterationRepo[]>([]);
  const [branchLoadingMap, setBranchLoadingMap] = useState<Record<number, boolean>>({});
  const [branchOptionsMap, setBranchOptionsMap] = useState<Record<number, string[]>>({});
  const [repoForm] = Form.useForm();

  const [memoryModalVisible, setMemoryModalVisible] = useState(false);
  const [memoryIterationId, setMemoryIterationId] = useState<number | null>(null);


  const openModal = (iteration?: Iteration) => {
    setEditingIteration(iteration || null);
    if (iteration) {
      form.setFieldsValue({
        name: iteration.name,
        dateRange: [dayjs(iteration.startDate), dayjs(iteration.endDate)],
        goal: iteration.goal,
        status: iteration.status,
      });
    } else {
      form.resetFields();
      // 新增迭代时,默认设置为进行中(当前迭代)
      form.setFieldsValue({ status: 'active' });
    }
    setModalVisible(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields() as IterationFormValues;
      const data = {
        name: values.name,
        startDate: values.dateRange[0].format('YYYY-MM-DD'),
        endDate: values.dateRange[1].format('YYYY-MM-DD'),
        goal: values.goal,
        status: values.status,
      };
      if (editingIteration) {
        await updateIteration(projectId, editingIteration.id, data);
        message.success('迭代已更新');
      } else {
        await createIteration(projectId, data);
        message.success('迭代已创建');
      }
      setModalVisible(false);
      setLoading(true);
      await refreshIterations();
      setLoading(false);
      window.dispatchEvent(new Event('project-iterations-updated'));
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const getProgress = (startDate: string, endDate: string) => {
    const start = dayjs(startDate);
    const end = dayjs(endDate);
    const now = dayjs();
    if (now.isBefore(start)) return 0;
    if (now.isAfter(end)) return 100;
    const total = end.diff(start, 'day');
    if (total <= 0) return 100;
    const elapsed = now.diff(start, 'day');
    return Math.round((elapsed / total) * 100);
  };

  const getRemainingDays = (endDate: string) => {
    const end = dayjs(endDate);
    const now = dayjs();
    return Math.max(0, end.diff(now, 'day'));
  };

  // 打开仓库绑定弹窗
  const openKanban = async (iterationId: number) => {
    setKanbanIterationId(iterationId);
    setKanbanVisible(true);
    setKanbanLoading(true);
    try {
      const res = await listDefects({ projectId, iterationId: String(iterationId), size: 200 });
      setKanbanDefects(res.data?.items || []);
    } catch {
      message.error('加载看板数据失败');
    } finally {
      setKanbanLoading(false);
    }
  };

  const openRepoModal = async (iterationId: number) => {
    setCurrentIterationId(iterationId);
    try {
      // 获取项目仓库列表
      const reposRes = await listProjectRepos(projectId);
      setProjectRepos(reposRes.data || []);

      // 获取已绑定的仓库
      const iterRes = await getIteration(projectId, iterationId);
      setBoundRepos(iterRes.data?.repos || []);

      repoForm.resetFields();
      setRepoModalVisible(true);
    } catch {
      message.error('获取仓库信息失败');
    }
  };

  // 绑定仓库
  const handleBindRepo = async () => {
    if (!currentIterationId) { message.error('请先选择迭代'); return; }
    try {
      const values = await repoForm.validateFields() as RepoBindFormValues;
      await bindRepo(projectId, currentIterationId, { repoId: values.repoId, branch: values.branch });
      message.success('仓库已绑定');
      const iterRes = await getIteration(projectId, currentIterationId);
      setBoundRepos(iterRes.data?.repos || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '绑定失败'));
    }
  };

  const handleUnbindRepo = async (repoId: number) => {
    if (!currentIterationId) { message.error('请先选择迭代'); return; }
    try {
      await unbindRepo(projectId, currentIterationId, repoId);
      message.success('仓库已解绑');
      const iterRes = await getIteration(projectId, currentIterationId);
      setBoundRepos(iterRes.data?.repos || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '解绑失败'));
    }
  };

  const handleFetchBranches = async (record: IterationRepo) => {
    if (branchOptionsMap[record.id]) return;
    if (!currentIterationId) return;
    setBranchLoadingMap(prev => ({ ...prev, [record.id]: true }));
    try {
      const res = await listRepoBranches(projectId, record.repoId);
      if (res.data) {
        setBranchOptionsMap(prev => ({ ...prev, [record.id]: res.data! }));
      }
    } catch { message.error('获取分支列表失败'); }
    finally { setBranchLoadingMap(prev => ({ ...prev, [record.id]: false })); }
  };

  const handleUpdateBranch = async (iterRepoId: number, branch: string) => {
    if (!currentIterationId) { message.error('请先选择迭代'); return; }
    try {
      const res = await updateIterRepoBranch(projectId, currentIterationId, iterRepoId, { branch });
      message.success('分支已更新');
      const iterRes = await getIteration(projectId, currentIterationId);
      setBoundRepos(iterRes.data?.repos || []);
    } catch (error: unknown) { message.error(getErrorMessage(error, '更新分支失败')); }
  };

  const columns: TableColumnsType<Iteration> = [
    { 
      title: 'ID', 
      dataIndex: 'id', 
      key: 'id', 
      width: 60,
    },
    { 
      title: '迭代名称', 
      dataIndex: 'name', 
      key: 'name',
      width: 220,
      render: (name: string, record: Iteration) => (
        <Space>
          <SyncOutlined style={{ color: '#a855f7' }} />
          <span style={{ fontWeight: 500 }}>{name}</span>
          {record.status === 'active' && (
            <Badge status="processing" />
          )}
        </Space>
      ),
    },
    { 
      title: '时间范围', 
      key: 'dateRange',
      width: 200,
      render: (_value: unknown, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontSize: 13 }}>
            <CalendarOutlined style={{ marginRight: 4, color: '#94a3b8' }} />
            {dayjs(record.startDate).format('MM/DD')} - {dayjs(record.endDate).format('MM/DD')}
          </span>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            {getRemainingDays(record.endDate)} 天后结束
          </span>
        </Space>
      ),
    },
    { 
      title: '进度', 
      key: 'progress',
      width: 150,
      render: (_value: unknown, record) => {
        const progress = getProgress(record.startDate, record.endDate);
        return (
          <Progress 
            percent={progress} 
            size="small" 
            showInfo={false}
            strokeColor={{
              '0%': '#a855f7',
              '100%': '#0ea5e9',
            }}
          />
        );
      },
    },
    { 
      title: '状态', 
      dataIndex: 'status', 
      key: 'status',
      width: 100,
      render: (status: string) => {
        const config = statusConfig[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      },
    },
    { 
      title: '目标', 
      dataIndex: 'goal', 
      key: 'goal',
      width: 260,
      ellipsis: true,
      render: (goal: string) => goal || <span style={{ color: '#cbd5e1' }}>未设置</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 360,
      render: (_value: unknown, record) => (
        <Space size={8}>
          <Button 
            type="link" 
            icon={<AppstoreOutlined />} 
            onClick={() => openKanban(record.id)}
          >
            看板
          </Button>
          <Button 
            type="link" 
            icon={<LinkOutlined />} 
            onClick={() => openRepoModal(record.id)}
          >
            仓库
          </Button>
          <Button
            type="link"
            icon={<BulbOutlined />}
            onClick={() => { setMemoryIterationId(record.id); setMemoryModalVisible(true); }}
          >
            记忆
          </Button>
          <Button type="link" icon={<EditOutlined />} onClick={() => openModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此迭代？" onConfirm={() => message.info('删除功能暂未实现')}>
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const activeCount = iterations.filter((item) => item.status === 'active').length;
  const completedCount = iterations.filter((item) => item.status === 'completed').length;
  const archivedCount = iterations.filter((item) => item.status === 'archived').length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '全部迭代', value: iterations.length, icon: <CalendarOutlined />, tone: 'purple' },
          { key: 'active', label: '进行中', value: activeCount, icon: <SyncOutlined />, tone: 'cyan' },
          { key: 'completed', label: '已完成', value: completedCount, icon: <CalendarOutlined />, tone: 'green' },
          { key: 'archived', label: '已归档', value: archivedCount, icon: <UnorderedListOutlined />, tone: 'amber' },
        ]}
        actions={(
          <Button
            type="primary"
            className="brand-button"
            icon={<PlusOutlined />}
            onClick={() => openModal()}
          >
            创建迭代
          </Button>
        )}
      />

      {/* 迭代列表 */}
      <Card className="scene-card">
        {iterations.length === 0 && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无迭代"
            style={{ padding: '40px 0' }}
          >
            <Button type="primary" onClick={() => openModal()}>
              创建第一个迭代
            </Button>
          </Empty>
        ) : (
          <Table 
            columns={columns} 
            dataSource={iterations} 
            rowKey="id" 
            loading={loading}
            pagination={false}
            scroll={{ x: 1360 }}
          />
        )}
      </Card>

      {/* 迭代编辑弹窗 */}
      <Modal
        title={editingIteration ? '编辑迭代' : '创建迭代'}
        open={modalVisible}
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="迭代名称" rules={[{ required: true, message: '请输入迭代名称' }]}>
            <Input placeholder="如 Sprint 1、v1.0.0" />
          </Form.Item>
          <Form.Item name="dateRange" label="时间范围" rules={[{ required: true, message: '请选择时间范围' }]}>
            <RangePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="goal" label="迭代目标">
            <TextArea rows={3} placeholder="本次迭代的目标和预期成果" />
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="planning">
            <Select>
              <Select.Option value="planning">计划中</Select.Option>
              <Select.Option value="active">进行中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
              <Select.Option value="archived">已归档</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* 仓库绑定弹窗 */}
      <Modal
        title="仓库绑定"
        open={repoModalVisible}
        onCancel={() => setRepoModalVisible(false)}
        footer={null}
        width={700}
      >
        <div style={{ marginBottom: 16 }}>
          <Form form={repoForm} layout="inline">
            <Form.Item name="repoId" rules={[{ required: true, message: '请选择仓库' }]}>
              <Select 
                placeholder="选择要绑定的仓库" 
                style={{ width: 300 }}
                showSearch
                optionFilterProp="children"
              >
                {projectRepos.map(repo => (
                  <Select.Option key={repo.id} value={repo.id}>
                    {repo.name}
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item>
              <Button type="primary" onClick={handleBindRepo}>
                绑定
              </Button>
            </Form.Item>
          </Form>
        </div>

        <div style={{ marginBottom: 8, fontWeight: 500 }}>
          <UnorderedListOutlined style={{ marginRight: 8 }} />
          已绑定仓库
        </div>
        {boundRepos.length === 0 ? (
          <Empty description="暂未绑定仓库" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div style={{ border: '1px solid #e2e8f0', borderRadius: 8 }}>
            {boundRepos.map((repo, index) => (
              <div 
                key={repo.id}
                style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  justifyContent: 'space-between',
                  padding: '12px 16px',
                  borderBottom: index < boundRepos.length - 1 ? '1px solid #f1f5f9' : 'none',
                }}
              >
                <div>
                  <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>
                      <LinkOutlined style={{ marginRight: 8, color: '#a855f7' }} />
                      {repo.repoName}
                    </span>
                    <Select
                      size="small"
                      value={repo.branch || undefined}
                      placeholder="默认分支"
                      style={{ width: 130 }}
                      loading={branchLoadingMap[repo.id]}
                      onFocus={() => handleFetchBranches(repo)}
                      onChange={(val: string) => handleUpdateBranch(repo.id, val)}
                      options={(branchOptionsMap[repo.id] || []).map(b => ({ value: b, label: b }))}
                      allowClear
                      onClear={() => handleUpdateBranch(repo.id, '')}
                    />
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>
                    {repo.repoUrl}
                  </div>
                </div>
                <Popconfirm title="确定解绑此仓库？" onConfirm={() => handleUnbindRepo(repo.id)}>
                  <Button type="link" danger size="small">
                    解绑
                  </Button>
                </Popconfirm>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* 迭代看板 */}
      <Modal
        title={`迭代看板 - ${iterations.find(i => i.id === kanbanIterationId)?.name || ''}`}
        open={kanbanVisible}
        onCancel={() => setKanbanVisible(false)}
        footer={null}
        width={1100}
      >
        {kanbanLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div>
        ) : (
          <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 8 }}>
            {(['new', 'pending_analysis', 'analyzing', 'pending_fix', 'fixing', 'pending_verify', 'fixed', 'completed'] as const).map(status => {
              const statusDefects = kanbanDefects.filter(d => d.status === status);
              const statusLabel: Record<string, string> = {
                new: '新建', pending_analysis: '待分析', analyzing: '分析中',
                pending_fix: '待修复', fixing: '修复中', pending_verify: '待验证',
                fixed: '已修复', completed: '已完成',
              };
              const statusColor: Record<string, string> = {
                new: '#64748b', pending_analysis: '#8b5cf6', analyzing: '#f59e0b',
                pending_fix: '#ea580c', fixing: '#dc2626', pending_verify: '#2563eb',
                fixed: '#16a34a', completed: '#10b981',
              };
              return (
                <div key={status} style={{ minWidth: 220, flex: 1 }}>
                  <div style={{
                    padding: '10px 14px',
                    borderRadius: '12px 12px 0 0',
                    background: statusColor[status] || '#64748b',
                    color: 'white',
                    fontWeight: 600,
                    fontSize: 13,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}>
                    <span>{statusLabel[status] || status}</span>
                    <span style={{
                      background: 'rgba(255,255,255,0.25)',
                      borderRadius: 8,
                      padding: '1px 8px',
                      fontSize: 12,
                    }}>
                      {statusDefects.length}
                    </span>
                  </div>
                  <div style={{
                    background: '#f8fafc',
                    borderRadius: '0 0 12px 12px',
                    padding: 8,
                    minHeight: 120,
                    maxHeight: 400,
                    overflowY: 'auto',
                  }}>
                    {statusDefects.length === 0 ? (
                      <div style={{ textAlign: 'center', padding: 20, color: '#cbd5e1', fontSize: 12 }}>
                        暂无缺陷
                      </div>
                    ) : statusDefects.map(defect => (
                      <div
                        key={defect.id}
                        style={{
                          background: 'white',
                          borderRadius: 10,
                          padding: '10px 12px',
                          marginBottom: 6,
                          border: '1px solid #e2e8f0',
                          cursor: 'pointer',
                        }}
                        onClick={() => navigate(`/projects/${projectId}/defects/${defect.id}`)}
                      >
                        <div style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace', marginBottom: 4 }}>
                          {defect.code}
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 500, color: '#0f172a', lineHeight: 1.4 }}>
                          {defect.title}
                        </div>
                        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                          <Tag style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                            {defect.severity === 'fatal' ? '致命' : defect.severity === 'major' ? '严重' : defect.severity === 'normal' ? '一般' : defect.severity === 'minor' ? '轻微' : '建议'}
                          </Tag>
                          {defect.assignee ? (
                            <Tag style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                              {defect.assignee.nickname || defect.assignee.username}
                            </Tag>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Modal>

      {/* 迭代 Agent 记忆 */}
      <Modal
        title={`Agent 记忆 - ${iterations.find(i => i.id === memoryIterationId)?.name || ''}`}
        open={memoryModalVisible}
        onCancel={() => { setMemoryModalVisible(false); setMemoryIterationId(null); }}
        footer={null}
        width={700}
      >
        {memoryIterationId ? (
          <MemoryManager projectId={projectId} iterationId={memoryIterationId} />
        ) : null}
      </Modal>
    </PageLayout>
  );
};

export default ProjectIterations;
