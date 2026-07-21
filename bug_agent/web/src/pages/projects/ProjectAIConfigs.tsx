import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Alert, Card, Table, Button, Modal, Form, Space, Popconfirm, Empty, Select, Tag, Switch, Input } from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import { PlusOutlined, EditOutlined, DeleteOutlined, RobotOutlined, KeyOutlined, ApiOutlined, SettingOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import {
  listAIProviders,
  listProjectAIConfigs,
  createProjectAIConfig,
  updateProjectAIConfig,
  deleteProjectAIConfig,
} from '../../api';
import type { AIProviderOption, ProjectAIConfig } from '../../types';
import PageLayout from '../../components/layout/PageLayout';
import PageMetricSection from '../../components/layout/PageMetricSection';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

type ProviderModelOption = AIProviderOption['models'][number];

interface ProjectAIConfigFormValues {
  provider: string;
  modelName: string;
  apiKey?: string;
  apiEndpoint?: string;
  functionCallingMode?: 'auto' | 'enabled' | 'disabled';
  isDefault?: boolean;
}

const ProjectAIConfigs: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);

  const [configs, setConfigs] = useState<ProjectAIConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingConfig, setEditingConfig] = useState<ProjectAIConfig | null>(null);
  const [form] = Form.useForm();
  
  const [providers, setProviders] = useState<AIProviderOption[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<string>('');
  const [models, setModels] = useState<ProviderModelOption[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [manualProvider, setManualProvider] = useState(false);
  const [manualModel, setManualModel] = useState(false);

  const loadingRef = useRef(false);


  const fetchConfigs = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const res = await listProjectAIConfigs(pid);
      setConfigs(res.data || []);
    } catch {
      message.error('获取AI配置失败');
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, [pid]);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const res = await listAIProviders();
      setProviders(res.data || []);
    } catch {
      message.error('获取AI厂商列表失败');
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  useEffect(() => {
    if (pid) {
      void fetchConfigs();
      void fetchProviders();
    }
  }, [fetchConfigs, fetchProviders, pid]);

  const openModal = (config?: ProjectAIConfig) => {
    setEditingConfig(config || null);
    if (config) {
      const providerValue = config.provider || '';
      const provider = providers.find(p => p.value === providerValue);
      const modelValue = config.modelName || '';
      form.setFieldsValue({
        ...config,
        apiKey: '',
      });
      if (provider) {
        setManualProvider(false);
        setSelectedProvider(providerValue);
        setModels(provider.models || []);
        const modelMatched = (provider.models || []).some((model) => model.name === modelValue);
        setManualModel(!modelMatched);
      } else {
        setManualProvider(true);
        setManualModel(true);
        setSelectedProvider('');
        setModels([]);
      }
    } else {
      form.resetFields();
      setSelectedProvider('');
      setModels([]);
      setManualProvider(!catalogReady);
      setManualModel(!catalogReady);
    }
    setModalVisible(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields() as ProjectAIConfigFormValues;
      const providerValue = String(values.provider || '').trim();
      const modelValue = String(values.modelName || '').trim();
      const provider = providers.find(p => p.value === providerValue);
      const inCatalog = provider
        ? (provider.models || []).some((model) => String(model.name || '').trim() === modelValue)
        : false;
      if (providerValue && modelValue && !inCatalog) {
        message.warning('当前厂商/模型不在目录中，将按非目录模型保存');
      }
      if (editingConfig && !values.apiKey) {
        delete values.apiKey;
      }
      if (editingConfig) {
        await updateProjectAIConfig(pid, editingConfig.id, values);
        message.success('AI配置已更新');
      } else {
        await createProjectAIConfig(pid, {
          ...values,
          apiKey: values.apiKey || '',
        });
        message.success('AI配置已添加');
      }
      setModalVisible(false);
      void fetchConfigs();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleDelete = async (configId: number) => {
    try {
      await deleteProjectAIConfig(pid, configId);
      message.success('AI配置已删除');
      void fetchConfigs();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除失败'));
    }
  };

  const updateModelsForProvider = (providerValue: string) => {
    if (providerValue === 'custom') {
      setModels([]);
      return;
    }
    const provider = providers.find(p => p.value === providerValue);
    if (provider) {
      setModels(provider.models || []);
    } else {
      setModels([]);
    }
  };

  const handleProviderChange = (value: string) => {
    setSelectedProvider(value);
    setManualProvider(false);
    setManualModel(false);
    updateModelsForProvider(value);
    form.setFieldsValue({ modelName: '', apiEndpoint: '' });
  };

  const handleModelChange = (value: string) => {
    const provider = providers.find(p => p.value === selectedProvider);
    if (provider) {
      const model = provider.models?.find((item) => item.name === value);
      if (model) {
        form.setFieldsValue({ apiEndpoint: model.endpoint || '' });
      }
    }
  };

  const getProviderColor = (provider: string) => {
    const colors: Record<string, string> = {
      'openai': '#10a37f',
      'zhipu': '#3b82f6',
      'deepseek': '#6366f1',
      'anthropic': '#d97706',
      'dashscope': '#fa8c16',
    };
    return colors[provider] || '#a855f7';
  };

  const columns: TableColumnsType<ProjectAIConfig> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { 
      title: '默认', 
      dataIndex: 'isDefault', 
      key: 'isDefault', 
      width: 80,
      render: (v: boolean) => v ? <Tag color="success">默认</Tag> : '-',
    },
    { 
      title: 'AI厂商', 
      dataIndex: 'provider', 
      key: 'provider',
      render: (provider: string) => (
        <Tag color={getProviderColor(provider)}>
          <RobotOutlined style={{ marginRight: 4 }} />
          {provider}
        </Tag>
      ),
    },
    { 
      title: '模型名称', 
      dataIndex: 'modelName', 
      key: 'modelName',
      render: (name: string) => <span style={{ fontWeight: 500 }}>{name}</span>,
    },
    { 
      title: 'API密钥', 
      dataIndex: 'apiKey', 
      key: 'apiKey',
      render: (key: string) => (
        <code style={{ 
          background: '#f1f5f9', 
          padding: '2px 8px', 
          borderRadius: 4, 
          fontSize: 12,
          color: '#64748b',
        }}>
          <KeyOutlined style={{ marginRight: 4 }} />
          {key && key.length > 8 ? `${key.substring(0, 4)}****${key.substring(key.length - 4)}` : key ? '****' : '-'}
        </code>
      ),
    },
    { 
      title: 'API端点', 
      dataIndex: 'apiEndpoint', 
      key: 'apiEndpoint',
      render: (endpoint: string) => endpoint ? (
        <span style={{ color: '#94a3b8', fontSize: 12 }}>
          <ApiOutlined style={{ marginRight: 4 }} />
          {endpoint}
        </span>
      ) : <span style={{ color: '#cbd5e1', fontSize: 12 }}>默认</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_value: unknown, record) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此AI配置？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const catalogReady = providers.some((provider) => provider.value !== 'custom');

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '配置总数', value: configs.length, icon: <SettingOutlined />, tone: 'purple' },
          { key: 'default', label: '默认配置', value: configs.filter(c => c.isDefault).length, icon: <RobotOutlined />, tone: 'cyan' },
        ]}
        actions={(
          <Button
            type="primary"
            className="brand-button"
            icon={<PlusOutlined />}
            onClick={() => openModal()}
          >
            添加配置
          </Button>
        )}
      />

      <Card
        className="scene-card"
        title="AI 配置列表"
      >
        {!loadingProviders && !catalogReady ? (
          <Alert
            style={{ marginBottom: 16 }}
            type="warning"
            showIcon
            title="AI 目录未初始化"
            description="当前数据库中没有可用的 AI 厂商/模型目录，请先在“AI目录”中维护。你仍可以通过下方表单手动填写厂商与模型。"
          />
        ) : null}
        {configs.length === 0 && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无AI配置"
            style={{ padding: '40px 0' }}
          >
            <Button type="primary" onClick={() => openModal()}>
              添加第一个配置
            </Button>
          </Empty>
        ) : (
          <Table 
            columns={columns} 
            dataSource={configs} 
            rowKey="id" 
            loading={loading}
            pagination={false}
          />
        )}
      </Card>

      <Modal
        title={editingConfig ? '编辑AI配置' : '添加AI配置'}
        open={modalVisible}
        forceRender
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="provider"
            label="AI厂商"
            rules={[{ required: true, message: '请选择AI厂商' }]}
          >
            {manualProvider ? (
              <Input placeholder="请输入AI厂商（如 openai / zhipu / deepseek）" />
            ) : (
              <Select
                placeholder="请选择AI厂商"
                loading={loadingProviders}
                onChange={handleProviderChange}
                value={selectedProvider}
                showSearch
              >
                {providers.map(p => (
                  <Select.Option key={p.value} value={p.value}>
                    {p.name}
                  </Select.Option>
                ))}
              </Select>
            )}
          </Form.Item>
          <div style={{ marginTop: -12, marginBottom: 12 }}>
            <Button
              type="link"
              size="small"
              onClick={() => {
                const next = !manualProvider;
                setManualProvider(next);
                setManualModel(next);
                setSelectedProvider('');
                setModels([]);
                form.setFieldsValue({ provider: '', modelName: '', apiEndpoint: '' });
              }}
            >
              {manualProvider ? '使用厂商下拉选项' : '手动填写厂商'}
            </Button>
          </div>

          <Form.Item
            name="modelName"
            label="模型名称"
            rules={[{ required: true, message: '请选择模型名称' }]}
          >
            {manualProvider || manualModel || selectedProvider === 'custom' ? (
              <Input placeholder="请输入模型名称（如 gpt-5.4 / deepseek-chat）" />
            ) : (
              <Select
                placeholder={selectedProvider ? '请选择模型' : '请先选择厂商'}
                disabled={!selectedProvider}
                loading={loadingProviders}
                onChange={handleModelChange}
                showSearch
              >
                {models.map(m => (
                  <Select.Option key={m.name} value={m.name}>
                    {m.name}
                  </Select.Option>
                ))}
              </Select>
            )}
          </Form.Item>
          {!manualProvider && selectedProvider && selectedProvider !== 'custom' && (
            <div style={{ marginTop: -12, marginBottom: 12 }}>
              <Button
                type="link"
                size="small"
                onClick={() => {
                  const next = !manualModel;
                  setManualModel(next);
                  if (!next) {
                    form.setFieldsValue({ modelName: '', apiEndpoint: '' });
                  }
                }}
              >
                {manualModel ? '使用模型下拉选项' : '手动填写模型'}
              </Button>
            </div>
          )}

          <Form.Item
            name="apiKey"
            label="API密钥"
            rules={editingConfig ? [] : [{ required: true, message: '请输入API密钥' }]}
            extra={editingConfig ? '留空则保留原密钥' : '密钥将加密存储，仅显示脱敏值'}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>

          <Form.Item
            name="apiEndpoint"
            label="API端点"
            extra={selectedProvider === 'custom' ? '自定义厂商请手动填写端点' : '留空使用厂商默认端点'}
          >
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item
            name="functionCallingMode"
            label="Function Calling"
            extra="auto: 根据模型目录自动判断 | enabled: 强制使用 | disabled: 使用文本解析模式"
          >
            <Select placeholder="auto" allowClear>
              <Select.Option value="auto">自动（推荐）</Select.Option>
              <Select.Option value="enabled">强制启用</Select.Option>
              <Select.Option value="disabled">禁用（文本解析）</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="isDefault"
            label="设为默认"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </PageLayout>
  );
};

export default ProjectAIConfigs;
