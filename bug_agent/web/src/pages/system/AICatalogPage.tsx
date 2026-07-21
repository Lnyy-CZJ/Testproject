import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import { ApiOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  createAdminAIModel,
  createAdminAIProvider,
  deleteAdminAIModel,
  deleteAdminAIProvider,
  listAdminAIModels,
  listAdminAIProviders,
  testAdminAIModel,
  updateAdminAIModel,
  updateAdminAIProvider,
} from '../../api';
import type { AIModelTestResult } from '../../api';
import PageLayout from '../../components/layout/PageLayout';
import PageContent from '../../components/layout/PageContent';
import PageMetricSection from '../../components/layout/PageMetricSection';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

interface AIProviderCatalog {
  id: number;
  providerKey: string;
  displayName: string;
  defaultEndpoint: string;
  status: 'active' | 'inactive';
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
}

interface AIModelCatalog {
  id: number;
  providerKey: string;
  modelName: string;
  endpoint: string;
  capabilityTags: string;
  status: 'active' | 'deprecated' | 'inactive';
  isDefault: boolean;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
}

interface ProviderFormValues {
  providerKey: string;
  displayName: string;
  defaultEndpoint?: string;
  status: AIProviderCatalog['status'];
  sortOrder: number;
}

interface ModelFormValues {
  providerKey: string;
  modelName: string;
  endpoint?: string;
  capabilityTags?: string;
  status: AIModelCatalog['status'];
  isDefault?: boolean;
  sortOrder: number;
}

interface ModelTestFormValues {
  apiKey: string;
  apiEndpoint?: string;
}

const AICatalogPage: React.FC = () => {
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [providers, setProviders] = useState<AIProviderCatalog[]>([]);
  const [models, setModels] = useState<AIModelCatalog[]>([]);
  const [expandedRowKeys, setExpandedRowKeys] = useState<React.Key[]>([]);

  const [providerModalVisible, setProviderModalVisible] = useState(false);
  const [modelModalVisible, setModelModalVisible] = useState(false);
  const [testModalVisible, setTestModalVisible] = useState(false);
  const [providerEditing, setProviderEditing] = useState<AIProviderCatalog | null>(null);
  const [modelEditing, setModelEditing] = useState<AIModelCatalog | null>(null);
  const [testingModel, setTestingModel] = useState<AIModelCatalog | null>(null);
  const [testingAvailability, setTestingAvailability] = useState(false);
  const [availabilityResult, setAvailabilityResult] = useState<AIModelTestResult | null>(null);
  const [providerForm] = Form.useForm();
  const [modelForm] = Form.useForm();
  const [testForm] = Form.useForm();


  const isFormValidationError = (error: unknown) => {
    return Boolean((error as RequestError | undefined)?.errorFields);
  };

  const providerMap = useMemo(() => {
    const next = new Map<string, AIProviderCatalog>();
    providers.forEach((provider) => {
      next.set(provider.providerKey, provider);
    });
    return next;
  }, [providers]);

  const modelsByProvider = useMemo(() => {
    const next = new Map<string, AIModelCatalog[]>();
    models.forEach((model) => {
      const current = next.get(model.providerKey) || [];
      current.push(model);
      next.set(model.providerKey, current);
    });
    return next;
  }, [models]);

  const fetchProviders = useCallback(async () => {
    setLoadingProviders(true);
    try {
      const res = await listAdminAIProviders();
      setProviders(res.data || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取AI厂商目录失败'));
    } finally {
      setLoadingProviders(false);
    }
  }, []);

  const fetchModels = useCallback(async () => {
    setLoadingModels(true);
    try {
      const res = await listAdminAIModels();
      setModels(res.data || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取AI模型目录失败'));
    } finally {
      setLoadingModels(false);
    }
  }, []);

  useEffect(() => {
    void fetchProviders();
    void fetchModels();
  }, [fetchModels, fetchProviders]);

  const refreshAll = async () => {
    await Promise.all([fetchProviders(), fetchModels()]);
  };

  const openProviderModal = (item?: AIProviderCatalog) => {
    setProviderEditing(item || null);
    if (item) {
      providerForm.setFieldsValue({
        providerKey: item.providerKey,
        displayName: item.displayName,
        defaultEndpoint: item.defaultEndpoint,
        status: item.status,
        sortOrder: item.sortOrder,
      });
    } else {
      providerForm.resetFields();
      providerForm.setFieldsValue({
        status: 'active',
        sortOrder: 100,
      });
    }
    setProviderModalVisible(true);
  };

  const openModelModal = (item?: AIModelCatalog, providerKey?: string) => {
    setModelEditing(item || null);
    if (item) {
      modelForm.setFieldsValue({
        providerKey: item.providerKey,
        modelName: item.modelName,
        endpoint: item.endpoint,
        capabilityTags: item.capabilityTags,
        status: item.status,
        isDefault: item.isDefault,
        sortOrder: item.sortOrder,
      });
    } else {
      modelForm.resetFields();
      modelForm.setFieldsValue({
        providerKey,
        status: 'active',
        isDefault: false,
        sortOrder: 100,
      });
    }
    setModelModalVisible(true);
  };

  const openTestModal = (item: AIModelCatalog) => {
    setTestingModel(item);
    setAvailabilityResult(null);
    testForm.resetFields();
    setTestModalVisible(true);
  };

  const handleSaveProvider = async () => {
    try {
      const values = await providerForm.validateFields() as ProviderFormValues;
      if (providerEditing) {
        await updateAdminAIProvider(providerEditing.id, {
          displayName: values.displayName,
          defaultEndpoint: values.defaultEndpoint || '',
          status: values.status,
          sortOrder: values.sortOrder,
        });
        message.success('AI厂商目录已更新');
      } else {
        await createAdminAIProvider({
          providerKey: values.providerKey,
          displayName: values.displayName,
          defaultEndpoint: values.defaultEndpoint || '',
          status: values.status,
          sortOrder: values.sortOrder,
        });
        message.success('AI厂商目录已创建');
      }
      setProviderModalVisible(false);
      await fetchProviders();
    } catch (error: unknown) {
      if (isFormValidationError(error)) return;
      message.error(getErrorMessage(error, '保存厂商目录失败'));
    }
  };

  const handleSaveModel = async () => {
    try {
      const values = await modelForm.validateFields() as ModelFormValues;
      if (modelEditing) {
        await updateAdminAIModel(modelEditing.id, {
          providerKey: values.providerKey,
          modelName: values.modelName,
          endpoint: values.endpoint || '',
          capabilityTags: values.capabilityTags || '',
          status: values.status,
          isDefault: Boolean(values.isDefault),
          sortOrder: values.sortOrder,
        });
        message.success('AI模型目录已更新');
      } else {
        await createAdminAIModel({
          providerKey: values.providerKey,
          modelName: values.modelName,
          endpoint: values.endpoint || '',
          capabilityTags: values.capabilityTags || '',
          status: values.status,
          isDefault: Boolean(values.isDefault),
          sortOrder: values.sortOrder,
        });
        message.success('AI模型目录已创建');
      }
      setModelModalVisible(false);
      await fetchModels();
    } catch (error: unknown) {
      if (isFormValidationError(error)) return;
      message.error(getErrorMessage(error, '保存模型目录失败'));
    }
  };

  const handleDeleteProvider = async (item: AIProviderCatalog) => {
    try {
      await deleteAdminAIProvider(item.id);
      message.success('AI厂商目录已删除');
      await refreshAll();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除厂商目录失败'));
    }
  };

  const handleDeleteModel = async (item: AIModelCatalog) => {
    try {
      await deleteAdminAIModel(item.id);
      message.success('AI模型目录已删除');
      await fetchModels();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除模型目录失败'));
    }
  };

  const handleRunModelTest = async () => {
    if (!testingModel) {
      return;
    }
    try {
      const values = await testForm.validateFields() as ModelTestFormValues;
      setTestingAvailability(true);
      const res = await testAdminAIModel(testingModel.id, {
        apiKey: values.apiKey,
        apiEndpoint: values.apiEndpoint || '',
      });
      const result = res.data;
      setAvailabilityResult(result);
      if (result?.success) {
        message.success(result.message || '模型测试成功');
      } else {
        message.error(result?.message || '模型测试失败');
      }
    } catch (error: unknown) {
      if (isFormValidationError(error)) return;
      setAvailabilityResult({
        success: false,
        latencyMs: 0,
        message: getErrorMessage(error, '模型测试失败'),
        endpoint: '',
      });
      message.error(getErrorMessage(error, '模型测试失败'));
    } finally {
      setTestingAvailability(false);
    }
  };

  const renderCapabilityTags = (value: string) => {
    const tags = String(value || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);
    if (tags.length === 0) {
      return <span style={{ color: '#94a3b8' }}>-</span>;
    }
    return (
      <Space size={[4, 4]} wrap>
        {tags.map((tag) => (
          <Tag key={tag}>{tag}</Tag>
        ))}
      </Space>
    );
  };

  const modelColumns: TableColumnsType<AIModelCatalog> = [
    {
      title: '模型名称',
      dataIndex: 'modelName',
      width: 260,
      render: (value: string) => <span style={{ fontWeight: 500 }}>{value}</span>,
    },
    {
      title: '端点',
      dataIndex: 'endpoint',
      render: (_: string, record: AIModelCatalog) => {
        const fallback = providerMap.get(record.providerKey)?.defaultEndpoint || '';
        const resolved = record.endpoint || fallback;
        return resolved ? (
          <span style={{ color: '#475569', fontSize: 12 }}>
            <ApiOutlined style={{ marginRight: 6 }} />
            {resolved}
          </span>
        ) : (
          <span style={{ color: '#94a3b8' }}>未配置端点</span>
        );
      },
    },
    {
      title: '能力标签',
      dataIndex: 'capabilityTags',
      width: 220,
      render: renderCapabilityTags,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => {
        const color = value === 'active' ? 'success' : value === 'deprecated' ? 'warning' : 'default';
        return <Tag color={color}>{value}</Tag>;
      },
    },
    {
      title: '默认',
      dataIndex: 'isDefault',
      width: 90,
      render: (value: boolean) => (value ? <Tag color="processing">默认</Tag> : '-'),
    },
    {
      title: '排序',
      dataIndex: 'sortOrder',
      width: 90,
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      render: (_: unknown, record: AIModelCatalog) => (
        <Space>
          <Button type="link" onClick={() => openTestModal(record)}>
            测试可用性
          </Button>
          <Button type="link" icon={<EditOutlined />} onClick={() => openModelModal(record)}>
            编辑
          </Button>
          <Popconfirm title="删除该模型目录？" onConfirm={() => handleDeleteModel(record)}>
            <Button type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const providerColumns: TableColumnsType<AIProviderCatalog> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '标识', dataIndex: 'providerKey', width: 160 },
    { title: '名称', dataIndex: 'displayName', width: 180 },
    {
      title: '默认端点',
      dataIndex: 'defaultEndpoint',
      render: (value: string) => value || <span style={{ color: '#94a3b8' }}>-</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => <Tag color={value === 'active' ? 'success' : 'default'}>{value}</Tag>,
    },
    {
      title: '模型数',
      key: 'modelCount',
      width: 100,
      render: (_: unknown, record: AIProviderCatalog) => modelsByProvider.get(record.providerKey)?.length || 0,
    },
    { title: '排序', dataIndex: 'sortOrder', width: 90 },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: unknown, record: AIProviderCatalog) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openProviderModal(record)}>
            编辑
          </Button>
          <Popconfirm
            title="删除该厂商目录？"
            description="若该厂商下仍有模型目录，将禁止删除。"
            onConfirm={() => handleDeleteProvider(record)}
          >
            <Button type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const activeProviderCount = providers.filter((provider) => provider.status === 'active').length;
  const activeModelCount = models.filter((model) => model.status === 'active').length;
  const defaultModelCount = models.filter((model) => model.isDefault).length;

  return (
    <PageLayout>
      <PageContent>

      <PageMetricSection
        items={[
          { key: 'providers', label: '厂商总数', value: providers.length, icon: <ApiOutlined />, tone: 'purple' },
          { key: 'active-providers', label: '启用厂商', value: activeProviderCount, icon: <ReloadOutlined />, tone: 'cyan' },
          { key: 'active-models', label: '启用模型', value: activeModelCount, icon: <PlusOutlined />, tone: 'amber' },
          { key: 'default-models', label: '默认模型', value: defaultModelCount, icon: <EditOutlined />, tone: 'green' },
        ]}
        actions={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => void refreshAll()}>
              刷新
            </Button>
            <Button type="primary" ghost icon={<PlusOutlined />} onClick={() => openModelModal()}>
              新增模型
            </Button>
            <Button type="primary" className="brand-button" icon={<PlusOutlined />} onClick={() => openProviderModal()}>
              新增厂商
            </Button>
          </Space>
        )}
      />

      <Card className="scene-card">
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          showIcon
          title="AI 目录以数据库为唯一来源"
          description="点击“展开模型”查看厂商下的模型目录；模型测试使用临时 API Key，不会保存到平台配置。"
        />

        <Table
          rowKey="id"
          loading={loadingProviders || loadingModels}
          dataSource={providers}
          pagination={false}
          columns={providerColumns}
          expandable={{
            expandedRowKeys,
            onExpandedRowsChange: (keys) => setExpandedRowKeys([...keys]),
            expandRowByClick: false,
            expandIcon: ({ expanded, onExpand, record }) => (
              <Button type="link" onClick={(event) => onExpand(record, event)}>
                {expanded ? '收起模型' : '展开模型'}
              </Button>
            ),
            expandedRowRender: (record) => (
              <div style={{ padding: '4px 0 8px 8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <Typography.Text type="secondary">
                    {record.displayName} ({record.providerKey}) 的模型目录
                  </Typography.Text>
                  <Button type="primary" ghost size="small" onClick={() => openModelModal(undefined, record.providerKey)}>
                    新增模型
                  </Button>
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  pagination={false}
                  dataSource={modelsByProvider.get(record.providerKey) || []}
                  columns={modelColumns}
                  locale={{ emptyText: '当前厂商下暂无模型目录' }}
                />
              </div>
            ),
          }}
        />
      </Card>

      <Modal
        title={providerEditing ? '编辑 AI 厂商' : '新增 AI 厂商'}
        open={providerModalVisible}
        forceRender
        onOk={handleSaveProvider}
        onCancel={() => setProviderModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={providerForm} layout="vertical">
          {!providerEditing && (
            <Form.Item name="providerKey" label="厂商标识" rules={[{ required: true, message: '请输入厂商标识' }]}>
              <Input placeholder="如 openai / anthropic / dashscope" />
            </Form.Item>
          )}
          <Form.Item name="displayName" label="显示名称" rules={[{ required: true, message: '请输入显示名称' }]}>
            <Input placeholder="如 OpenAI" />
          </Form.Item>
          <Form.Item name="defaultEndpoint" label="默认端点">
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>
          <Form.Item name="status" label="状态" rules={[{ required: true, message: '请选择状态' }]}>
            <Select
              options={[
                { value: 'active', label: 'active' },
                { value: 'inactive', label: 'inactive' },
              ]}
            />
          </Form.Item>
          <Form.Item name="sortOrder" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={modelEditing ? '编辑 AI 模型' : '新增 AI 模型'}
        open={modelModalVisible}
        forceRender
        onOk={handleSaveModel}
        onCancel={() => setModelModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={modelForm} layout="vertical">
          <Form.Item name="providerKey" label="厂商标识" rules={[{ required: true, message: '请选择厂商' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              options={providers.map((provider) => ({
                value: provider.providerKey,
                label: `${provider.displayName} (${provider.providerKey})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="modelName" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
            <Input placeholder="如 gpt-5.4 / qwen-max-latest" />
          </Form.Item>
          <Form.Item name="endpoint" label="模型端点（可选）">
            <Input placeholder="留空继承厂商默认端点" />
          </Form.Item>
          <Form.Item name="capabilityTags" label="能力标签（可选）">
            <Input placeholder="如 chat,reasoning,code" />
          </Form.Item>
          <Form.Item name="status" label="状态" rules={[{ required: true, message: '请选择状态' }]}>
            <Select
              options={[
                { value: 'active', label: 'active' },
                { value: 'deprecated', label: 'deprecated' },
                { value: 'inactive', label: 'inactive' },
              ]}
            />
          </Form.Item>
          <Form.Item name="isDefault" label="默认模型" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="sortOrder" label="排序">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={testingModel ? `测试模型可用性 - ${testingModel.modelName}` : '测试模型可用性'}
        open={testModalVisible}
        onCancel={() => setTestModalVisible(false)}
        footer={null}
        destroyOnHidden
      >
        <Form form={testForm} layout="vertical">
          <Form.Item
            name="apiKey"
            label="临时 API Key"
            rules={[{ required: true, message: '请输入临时 API Key' }]}
          >
            <Input.Password placeholder="仅用于本次测试，不会保存" />
          </Form.Item>
          <Form.Item
            name="apiEndpoint"
            label="覆盖端点（可选）"
            extra={testingModel ? `留空将使用目录端点：${testingModel.endpoint || providerMap.get(testingModel.providerKey)?.defaultEndpoint || '未配置'}` : ''}
          >
            <Input placeholder="留空使用目录中的模型端点/厂商默认端点" />
          </Form.Item>

          {availabilityResult ? (
            <Alert
              style={{ marginBottom: 16 }}
              type={availabilityResult.success ? 'success' : 'error'}
              showIcon
              title={availabilityResult.success ? '测试成功' : '测试失败'}
              description={(
                <div>
                  <div>{availabilityResult.message}</div>
                  <div>耗时：{availabilityResult.latencyMs} ms</div>
                  {availabilityResult.endpoint ? <div>端点：{availabilityResult.endpoint}</div> : null}
                </div>
              )}
            />
          ) : null}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={() => setTestModalVisible(false)}>关闭</Button>
            <Button type="primary" loading={testingAvailability} onClick={handleRunModelTest}>
              开始测试
            </Button>
          </div>
        </Form>
      </Modal>
      </PageContent>
    </PageLayout>
  );
};

export default AICatalogPage;
