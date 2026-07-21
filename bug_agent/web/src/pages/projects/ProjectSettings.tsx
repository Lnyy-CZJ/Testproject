import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Card, Tabs, Table, Button, Modal, Form, Input, Space, Popconfirm, Switch, Empty, Tag, Select, Spin } from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import { EditOutlined, DeleteOutlined, SettingOutlined, ApiOutlined, BulbOutlined, SearchOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { useProject } from '../../contexts/projectContext';
import {
  listProjectAIConfigs,
  createProjectAIConfig,
  updateProjectAIConfig,
  deleteProjectAIConfig,
  listMCPServers,
  createMCPServer,
  updateMCPServer,
  deleteMCPServer,
  toggleMCPServer,
  testMCPServerConnection,
  listSkills,
  createSkill,
  updateSkill,
  deleteSkill,
  toggleSkill,
  updateProject,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLayout from '../../components/layout/PageLayout';
import MemoryManager from '../../components/MemoryManager';
import type { ProjectAIConfig, MCPServerItem, SkillItem } from '../../api/types';
import { AGENT_TYPES } from '../../types';
import { getErrorMessage } from '../../utils/error';
import ProjectRetrieverPlugins from './ProjectRetrieverPlugins';

interface ProjectAIConfigFormValues {
  provider: string;
  modelName: string;
  apiKey?: string;
  apiEndpoint?: string;
  functionCallingMode?: 'auto' | 'enabled' | 'disabled';
  isDefault?: boolean;
}

const ProjectSettings: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);
  const { project, refreshProject } = useProject();

  const [aiConfigs, setAiConfigs] = useState<ProjectAIConfig[]>([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiModalVisible, setAiModalVisible] = useState(false);
  const [editingAI, setEditingAI] = useState<ProjectAIConfig | null>(null);
  const [aiForm] = Form.useForm();

  const [mcpServers, setMcpServers] = useState<MCPServerItem[]>([]);
  const [mcpLoading, setMcpLoading] = useState(false);
  const [mcpModalVisible, setMcpModalVisible] = useState(false);
  const [editingMcp, setEditingMcp] = useState<MCPServerItem | null>(null);
  const [mcpForm] = Form.useForm();
  const [testingMcpId, setTestingMcpId] = useState<number | null>(null);
  const mcpLoadingRef = useRef(false);

  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillModalVisible, setSkillModalVisible] = useState(false);
  const [editingSkill, setEditingSkill] = useState<SkillItem | null>(null);
  const [skillForm] = Form.useForm();
  const skillsLoadingRef = useRef(false);

  const agentTypeOptions = AGENT_TYPES.map(a => ({ value: a.key, label: a.label }));

  const fetchAIConfigs = useCallback(async () => {
    setAiLoading(true);
    try {
      const res = await listProjectAIConfigs(pid);
      setAiConfigs(res.data || []);
    } catch {
      message.error('获取模型配置失败');
    } finally {
      setAiLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    if (pid) {
      void fetchAIConfigs();
    }
  }, [fetchAIConfigs, pid]);

  const fetchMcpServers = useCallback(async () => {
    if (mcpLoadingRef.current) return;
    mcpLoadingRef.current = true;
    setMcpLoading(true);
    try {
      const res = await listMCPServers(pid);
      setMcpServers(res.data || []);
    } catch {
      message.error('获取 MCP 服务列表失败');
    } finally {
      setMcpLoading(false);
      mcpLoadingRef.current = false;
    }
  }, [pid]);

  const fetchSkills = useCallback(async () => {
    if (skillsLoadingRef.current) return;
    skillsLoadingRef.current = true;
    setSkillsLoading(true);
    try {
      const res = await listSkills(pid);
      setSkills(res.data || []);
    } catch {
      message.error('获取技能列表失败');
    } finally {
      setSkillsLoading(false);
      skillsLoadingRef.current = false;
    }
  }, [pid]);

  useEffect(() => {
    if (pid) {
      void fetchMcpServers();
      void fetchSkills();
    }
  }, [fetchMcpServers, fetchSkills, pid]);

  const openAIModal = (config?: ProjectAIConfig) => {
    setEditingAI(config || null);
    if (config) {
      aiForm.setFieldsValue({
        ...config,
        apiKey: '',
      });
    } else {
      aiForm.resetFields();
    }
    setAiModalVisible(true);
  };

  const handleSaveAI = async () => {
    try {
      const values = await aiForm.validateFields() as ProjectAIConfigFormValues;
      if (editingAI) {
        await updateProjectAIConfig(pid, editingAI.id, values);
        message.success('模型配置已更新');
      } else {
        await createProjectAIConfig(pid, {
          ...values,
          apiKey: values.apiKey || '',
        });
        message.success('模型配置已添加');
      }
      setAiModalVisible(false);
      void fetchAIConfigs();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleDeleteAI = async (configId: number) => {
    try {
      await deleteProjectAIConfig(pid, configId);
      message.success('模型配置已删除');
      void fetchAIConfigs();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除失败'));
    }
  };

  const handleAddMcp = () => { setEditingMcp(null); mcpForm.resetFields(); setMcpModalVisible(true); };
  const handleEditMcp = (record: MCPServerItem) => {
    setEditingMcp(record);
    mcpForm.setFieldsValue({ name: record.name, command: record.command, args: record.args, description: record.description });
    setMcpModalVisible(true);
  };
  const handleSubmitMcp = async () => {
    try {
      const values = await mcpForm.validateFields();
      if (editingMcp) {
        await updateMCPServer(pid, editingMcp.id, values);
        message.success('更新成功');
      } else {
        await createMCPServer(pid, values);
        message.success('创建成功');
      }
      setMcpModalVisible(false);
      void fetchMcpServers();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(getErrorMessage(err, '操作失败'));
    }
  };
  const handleDeleteMcp = async (id: number) => {
    try { await deleteMCPServer(pid, id); message.success('删除成功'); void fetchMcpServers(); } catch (err) { message.error(getErrorMessage(err, '删除失败')); }
  };
  const handleToggleMcp = async (id: number) => {
    try { await toggleMCPServer(pid, id); void fetchMcpServers(); } catch (err) { message.error(getErrorMessage(err, '切换状态失败')); }
  };
  const handleTestMcp = async (id: number) => {
    setTestingMcpId(id);
    try {
      const res = await testMCPServerConnection(pid, id);
      if (res.data?.connected) { message.success('连接测试成功'); } else { message.warning(res.data?.error || '连接测试失败'); }
    } catch (err) { message.error(getErrorMessage(err, '连接测试失败')); } finally { setTestingMcpId(null); }
  };

  const handleToggleMemory = async (checked: boolean) => {
    try {
      await updateProject(pid, { memoryEnabled: checked });
      message.success(checked ? '记忆功能已开启' : '记忆功能已关闭');
      void refreshProject();
    } catch (err) {
      message.error(getErrorMessage(err, '操作失败'));
    }
  };

  const handleAddSkill = () => { setEditingSkill(null); skillForm.resetFields(); setSkillModalVisible(true); };
  const handleEditSkill = (record: SkillItem) => {
    setEditingSkill(record);
    skillForm.setFieldsValue({ name: record.name, agentType: record.agentType, instruction: record.instruction, tools: record.tools, mcpServerIds: record.mcpServerIds, memoryCategories: record.memoryCategories });
    setSkillModalVisible(true);
  };
  const handleSubmitSkill = async () => {
    try {
      const values = await skillForm.validateFields();
      if (editingSkill) {
        await updateSkill(pid, editingSkill.id, values);
        message.success('更新成功');
      } else {
        await createSkill(pid, values);
        message.success('创建成功');
      }
      setSkillModalVisible(false);
      void fetchSkills();
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error(getErrorMessage(err, '操作失败'));
    }
  };
  const handleDeleteSkill = async (id: number) => {
    try { await deleteSkill(pid, id); message.success('删除成功'); void fetchSkills(); } catch (err) { message.error(getErrorMessage(err, '删除失败')); }
  };
  const handleToggleSkill = async (id: number) => {
    try { await toggleSkill(pid, id); void fetchSkills(); } catch (err) { message.error(getErrorMessage(err, '切换状态失败')); }
  };
  const getAgentLabel = (key: string) => { const found = AGENT_TYPES.find(a => a.key === key); return found ? found.label : key; };

  const aiColumns: TableColumnsType<ProjectAIConfig> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: '默认',
      dataIndex: 'isDefault',
      key: 'isDefault',
      width: 80,
      render: (v: boolean) => (v ? <span style={{ color: '#52c41a' }}>★ 默认</span> : '-'),
    },
    { title: 'AI厂商', dataIndex: 'provider', key: 'provider' },
    { title: '模型名称', dataIndex: 'modelName', key: 'modelName' },
    { title: 'API密钥', dataIndex: 'apiKey', key: 'apiKey', render: (key: string) => <code>{key && key.length > 8 ? key.substring(0,4) + '****' + key.substring(key.length-4) : key ? '****' : '-'}</code> },
    { title: 'API端点', dataIndex: 'apiEndpoint', key: 'apiEndpoint' },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_value: unknown, record) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openAIModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此模型配置？" onConfirm={() => handleDeleteAI(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const defaultAiCount = aiConfigs.filter((config) => config.isDefault).length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'ai', label: '模型配置', value: aiConfigs.length, icon: <ApiOutlined />, tone: 'cyan' },
          { key: 'default-ai', label: '默认模型', value: defaultAiCount, icon: <SettingOutlined />, tone: 'amber' },
        ]}
      />

      <Card className="scene-card" title={<><SettingOutlined /> AI配置</>}>
        <Tabs
          defaultActiveKey="ai-configs"
          items={[
            {
              key: 'ai-configs',
              label: (
                <span>
                  <ApiOutlined />
                  模型配置
                </span>
              ),
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Button type="primary" icon={<EditOutlined />} onClick={() => openAIModal()}>
                      添加模型配置
                    </Button>
                  </div>
                  <Table columns={aiColumns} dataSource={aiConfigs} rowKey="id" loading={aiLoading} />
                </>
              ),
            },
            {
              key: 'agent-memory',
              label: (
                <span>
                  <BulbOutlined />
                  Agent 记忆
                </span>
              ),
              children: (
                <>
                  <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span>启用 Agent 记忆</span>
                    <Switch
                      checked={project?.memoryEnabled ?? true}
                      onChange={handleToggleMemory}
                    />
                    <span style={{ fontSize: 13, color: '#888' }}>
                      {project?.memoryEnabled ? '开启后，Agent 会自动记录和引用分析修复经验' : '关闭后，Agent 不记录也不使用历史记忆'}
                    </span>
                  </div>
                  <MemoryManager projectId={pid} />
                </>
              ),
            },
            {
              key: 'mcp-servers',
              label: (
                <span>
                  <ApiOutlined />
                  MCP 服务
                </span>
              ),
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={handleAddMcp}>添加 MCP 服务</Button>
                  </div>
                  {mcpLoading ? (
                    <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
                  ) : mcpServers.length === 0 ? (
                    <Empty description="暂无 MCP 服务" />
                  ) : (
                    <Table rowKey="id" size="small" dataSource={mcpServers} pagination={false} columns={[
                      { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
                      { title: '命令', dataIndex: 'command', key: 'command', ellipsis: true },
                      { title: '参数', dataIndex: 'args', key: 'args', ellipsis: true, width: 200, render: (v: string) => v || '-' },
                      { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true, width: 200, render: (v: string) => v || '-' },
                      { title: '状态', dataIndex: 'enabled', key: 'enabled', width: 100, render: (v: boolean, record) => <Switch size="small" checked={v} onChange={() => handleToggleMcp(record.id)} /> },
                      { title: '操作', key: 'action', width: 200, render: (_: unknown, record) => (
                        <Space size={4}>
                          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditMcp(record)}>编辑</Button>
                          <Button type="link" size="small" icon={<ThunderboltOutlined />} loading={testingMcpId === record.id} onClick={() => handleTestMcp(record.id)}>测试</Button>
                          <Popconfirm title="确认删除？" onConfirm={() => handleDeleteMcp(record.id)}>
                            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                          </Popconfirm>
                        </Space>
                      )},
                    ]} />
                  )}
                </>
              ),
            },
            {
              key: 'skills',
              label: (
                <span>
                  <BulbOutlined />
                  技能管理
                </span>
              ),
              children: (
                <>
                  <div style={{ marginBottom: 16 }}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={handleAddSkill}>添加技能</Button>
                  </div>
                  {skillsLoading ? (
                    <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
                  ) : skills.length === 0 ? (
                    <Empty description="暂无技能" />
                  ) : (
                    <Table rowKey="id" size="small" dataSource={skills} pagination={false} columns={[
                      { title: '名称', dataIndex: 'name', key: 'name', width: 180 },
                      { title: 'Agent 类型', dataIndex: 'agentType', key: 'agentType', width: 120, render: (v: string) => <Tag>{getAgentLabel(v)}</Tag> },
                      { title: '指令', dataIndex: 'instruction', key: 'instruction', ellipsis: true, width: 250, render: (v: string) => v || '-' },
                      { title: '默认', dataIndex: 'isDefault', key: 'isDefault', width: 80, render: (v: boolean) => v ? <Tag color="blue">默认</Tag> : '-' },
                      { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 80, render: (v: boolean, record) => <Switch size="small" checked={v} onChange={() => handleToggleSkill(record.id)} /> },
                      { title: '操作', key: 'action', width: 140, render: (_: unknown, record) => (
                        <Space size={4}>
                          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEditSkill(record)}>编辑</Button>
                          <Popconfirm title="确认删除？" onConfirm={() => handleDeleteSkill(record.id)}>
                            <Button type="link" size="small" danger icon={<DeleteOutlined />}>删除</Button>
                          </Popconfirm>
                        </Space>
                      )},
                    ]} />
                  )}
                </>
              ),
            },
            {
              key: 'retriever-plugins',
              label: (
                <span>
                  <SearchOutlined />
                  检索配置
                </span>
              ),
              children: <ProjectRetrieverPlugins projectId={pid} />,
            },
          ]}
        />
      </Card>

      <Modal
        title={editingAI ? '编辑模型配置' : '添加模型配置'}
        open={aiModalVisible}
        onOk={handleSaveAI}
        onCancel={() => setAiModalVisible(false)}
        width={600}
      >
        <Form form={aiForm} layout="vertical">
          <Form.Item name="provider" label="AI厂商" rules={[{ required: true, message: '请选择AI厂商' }]}>
            <Input placeholder="如 OpenAI、智谱AI" />
          </Form.Item>
          <Form.Item name="modelName" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
            <Input placeholder="如 gpt-4o、glm-4" />
          </Form.Item>
          <Form.Item
            name="apiKey"
            label="访问密钥"
            rules={editingAI ? [] : [{ required: true, message: '请输入API密钥' }]}
            extra={editingAI ? '留空则保留原密钥' : '密钥将加密存储'}
          >
            <Input.Password placeholder="API Key" />
          </Form.Item>
          <Form.Item name="apiEndpoint" label="API端点" extra="留空使用厂商默认端点">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item name="isDefault" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingMcp ? '编辑 MCP 服务' : '添加 MCP 服务'}
        open={mcpModalVisible}
        onOk={handleSubmitMcp}
        onCancel={() => setMcpModalVisible(false)}
        okText="确定"
        cancelText="取消"
        width={560}
      >
        <Form form={mcpForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如: filesystem, github" />
          </Form.Item>
          <Form.Item name="command" label="启动命令" rules={[{ required: true, message: '请输入启动命令' }]}>
            <Input placeholder="如: npx @modelcontextprotocol/server-filesystem" />
          </Form.Item>
          <Form.Item name="args" label="参数">
            <Input placeholder="如: /path/to/dir" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="服务功能描述" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingSkill ? '编辑技能' : '添加技能'}
        open={skillModalVisible}
        onOk={handleSubmitSkill}
        onCancel={() => setSkillModalVisible(false)}
        okText="确定"
        cancelText="取消"
        width={600}
      >
        <Form form={skillForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如: code-review, security-scan" />
          </Form.Item>
          <Form.Item name="agentType" label="Agent 类型" rules={[{ required: true, message: '请选择 Agent 类型' }]}>
            <Select options={agentTypeOptions} placeholder="选择 Agent 类型" />
          </Form.Item>
          <Form.Item name="instruction" label="指令">
            <Input.TextArea rows={4} placeholder="定义 Agent 的行为指令" />
          </Form.Item>
          <Form.Item name="tools" label="可用工具">
            <Input placeholder="如: read_file,write_file,run_command（逗号分隔）" />
          </Form.Item>
          <Form.Item name="mcpServerIds" label="MCP 服务 ID">
            <Input placeholder="关联的 MCP 服务 ID（逗号分隔）" />
          </Form.Item>
          <Form.Item name="memoryCategories" label="记忆分类">
            <Input placeholder="如: architecture,convention（逗号分隔）" />
          </Form.Item>
        </Form>
      </Modal>
    </PageLayout>
  );
};

export default ProjectSettings;
