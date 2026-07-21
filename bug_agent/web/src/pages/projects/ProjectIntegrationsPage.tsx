import React, { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  ApiOutlined,
  EditOutlined,
  HistoryOutlined,
  PlusOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons';
import { formatDateTime } from '../../utils/formatDate';
import dayjs from 'dayjs';
import {
  createIntegrationConnector,
  deleteIntegrationConnector,
  listIntegrationConnectors,
  listIntegrationSyncRecords,
  syncIntegrationConnector,
  testIntegrationConnector,
  updateIntegrationConnector,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLoadState from '../../components/PageLoadState';
import PageLayout from '../../components/layout/PageLayout';
import { message } from '../../utils/appMessage';
import { useParams } from 'react-router-dom';
import type { IntegrationConnector, IntegrationSyncRecord } from '../../types';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

type ConnectorType = 'webhook' | 'bugly' | 'dingtalk' | 'feishu' | 'aliyun_log';

const CONNECTOR_TYPE_OPTIONS: Array<{ value: ConnectorType; label: string }> = [
  { value: 'webhook', label: '通用 Webhook' },
  { value: 'bugly', label: 'Bugly' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'feishu', label: '飞书' },
  { value: 'aliyun_log', label: '阿里云日志' },
] ;

const STATUS_OPTIONS: Array<{ value: 'active' | 'inactive'; label: string }> = [
  { value: 'active', label: '启用' },
  { value: 'inactive', label: '停用' },
] ;

const healthStatusMap: Record<string, { color: string; label: string }> = {
  healthy: { color: 'success', label: '健康' },
  warning: { color: 'warning', label: '待同步' },
  error: { color: 'error', label: '异常' },
  inactive: { color: 'default', label: '停用' },
};

const supportsPullByType: Record<ConnectorType, boolean> = {
  webhook: false,
  bugly: true,
  dingtalk: false,
  feishu: false,
  aliyun_log: true,
};

interface ConnectorFormValues {
  name: string;
  type: ConnectorType;
  status: 'active' | 'inactive';
  endpoint?: string;
  project?: string;
  logstore?: string;
  query?: string;
  issuesPath?: string;
  appId?: string;
  appKey?: string;
  apiToken?: string;
  verificationToken?: string;
  secret?: string;
  accessKeyId?: string;
  accessKeySecret?: string;
  securityToken?: string;
  fromMinutes?: string;
  toDelaySeconds?: string;
  lines?: string;
}

const ProjectIntegrationsPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId || 0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [connectors, setConnectors] = useState<IntegrationConnector[]>([]);
  const [syncRecords, setSyncRecords] = useState<IntegrationSyncRecord[]>([]);
  const [recordsVisible, setRecordsVisible] = useState(false);
  const [recordsConnector, setRecordsConnector] = useState<IntegrationConnector | null>(null);
  const [editing, setEditing] = useState<IntegrationConnector | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm<ConnectorFormValues>();
  const selectedType = Form.useWatch('type', form) || editing?.type || 'webhook';


  const isValidationError = (error: unknown) => Boolean((error as RequestError | undefined)?.errorFields);

  const fetchData = useCallback(async () => {
    if (!pid) {
      setLoadError('无效的项目 ID');
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const connectorRes = await listIntegrationConnectors(pid);
      setConnectors(connectorRes.data || []);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '获取接入连接器失败');
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const toEditableValue = (value: unknown) => {
    if (typeof value !== 'string') {
      return '';
    }
    return value === '__configured__' ? '' : value;
  };

  const openModal = (connector?: IntegrationConnector) => {
    const config = connector?.config || {};
    setEditing(connector || null);
    form.setFieldsValue({
      name: connector?.name || '',
      type: connector?.type || 'webhook',
      status: connector?.status || 'active',
      endpoint: toEditableValue(config.endpoint),
      project: toEditableValue(config.project),
      logstore: toEditableValue(config.logstore),
      query: toEditableValue(config.query),
      issuesPath: toEditableValue(config.issuesPath || config.path),
      appId: toEditableValue(config.appId || config.productId),
      appKey: '',
      apiToken: '',
      verificationToken: toEditableValue(config.verificationToken),
      secret: '',
      accessKeyId: toEditableValue(config.accessKeyId),
      accessKeySecret: '',
      securityToken: '',
      fromMinutes: toEditableValue(config.fromMinutes),
      toDelaySeconds: toEditableValue(config.toDelaySeconds),
      lines: toEditableValue(config.lines),
    });
    setModalVisible(true);
  };

  const trimValue = (value?: string) => String(value || '').trim();
  const toPositiveInt = (value?: string) => {
    const parsed = Number.parseInt(trimValue(value), 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
  };

  const buildConfig = (values: ConnectorFormValues) => {
    const config: Record<string, unknown> = {};
    if (values.type === 'bugly') {
      if (trimValue(values.endpoint)) config.endpoint = trimValue(values.endpoint);
      if (trimValue(values.issuesPath)) config.issuesPath = trimValue(values.issuesPath);
      if (trimValue(values.appId)) config.appId = trimValue(values.appId);
      if (trimValue(values.appKey)) config.appKey = trimValue(values.appKey);
      if (trimValue(values.apiToken)) config.apiToken = trimValue(values.apiToken);
      return config;
    }
    if (values.type === 'dingtalk' || values.type === 'feishu') {
      if (trimValue(values.verificationToken)) config.verificationToken = trimValue(values.verificationToken);
      if (trimValue(values.secret)) config.secret = trimValue(values.secret);
      return config;
    }
    if (values.type === 'aliyun_log') {
      if (trimValue(values.endpoint)) config.endpoint = trimValue(values.endpoint);
      if (trimValue(values.project)) config.project = trimValue(values.project);
      if (trimValue(values.logstore)) config.logstore = trimValue(values.logstore);
      if (trimValue(values.query)) config.query = trimValue(values.query);
      if (trimValue(values.accessKeyId)) config.accessKeyId = trimValue(values.accessKeyId);
      if (trimValue(values.accessKeySecret)) config.accessKeySecret = trimValue(values.accessKeySecret);
      if (trimValue(values.securityToken)) config.securityToken = trimValue(values.securityToken);
      if (toPositiveInt(values.fromMinutes)) config.fromMinutes = toPositiveInt(values.fromMinutes);
      if (toPositiveInt(values.toDelaySeconds)) config.toDelaySeconds = toPositiveInt(values.toDelaySeconds);
      if (toPositiveInt(values.lines)) config.lines = toPositiveInt(values.lines);
      return config;
    }
    return config;
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const payload = {
        name: values.name.trim(),
        type: values.type,
        status: values.status,
        config: buildConfig(values),
      };

      if (editing) {
        await updateIntegrationConnector(pid, editing.id, payload);
        message.success('接入连接器已更新');
      } else {
        await createIntegrationConnector(pid, payload);
        message.success('接入连接器已创建');
      }

      setModalVisible(false);
      await fetchData();
    } catch (error: unknown) {
      if (isValidationError(error)) {
        return;
      }
      message.error(getErrorMessage(error, '保存接入连接器失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (connector: IntegrationConnector) => {
    try {
      await deleteIntegrationConnector(pid, connector.id);
      message.success('接入连接器已删除');
      await fetchData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除接入连接器失败'));
    }
  };

  const handleTest = async (connector: IntegrationConnector) => {
    setTestingId(connector.id);
    try {
      await testIntegrationConnector(pid, connector.id);
      message.success('连接器测试成功');
      await fetchData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '连接器测试失败'));
    } finally {
      setTestingId(null);
    }
  };

  const handleSync = async (connector: IntegrationConnector) => {
    setSyncingId(connector.id);
    try {
      await syncIntegrationConnector(pid, connector.id);
      const successText = connector.type === 'bugly'
        ? 'Bugly 问题同步完成'
        : connector.type === 'aliyun_log'
          ? '阿里云日志同步完成'
          : '手动同步已完成';
      message.success(successText);
      await fetchData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '手动同步失败'));
    } finally {
      setSyncingId(null);
    }
  };

  const handleRetry = async (connector: IntegrationConnector) => {
    await handleSync(connector);
  };

  const openSyncRecords = async (connector: IntegrationConnector) => {
    setRecordsConnector(connector);
    setRecordsVisible(true);
    setRecordsLoading(true);
    try {
      const res = await listIntegrationSyncRecords(pid, connector.id);
      setSyncRecords(res.data || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取同步记录失败'));
      setSyncRecords([]);
    } finally {
      setRecordsLoading(false);
    }
  };

  const getConfigSummary = (connector: IntegrationConnector) => {
    const config = connector.config || {};
    switch (connector.type) {
      case 'bugly':
        return trimValue(String(config.endpoint || '')) || '未配置 Bugly 拉取地址';
      case 'aliyun_log': {
        const project = trimValue(String(config.project || ''));
        const logstore = trimValue(String(config.logstore || ''));
        if (project && logstore) {
          return `${project} / ${logstore}`;
        }
        return '未配置项目 / 日志库';
      }
      case 'dingtalk':
      case 'feishu':
        return config.secret || config.verificationToken ? '已配置签名/校验参数' : '使用默认入站解析';
      default:
        return connector.inboundPath;
    }
  };

  const supportsPull = (connector: IntegrationConnector) => {
    if (typeof connector.supportsPull === 'boolean') {
      return connector.supportsPull;
    }
    return supportsPullByType[connector.type as ConnectorType] ?? false;
  };

  const renderTypeSpecificFields = () => {
    if (selectedType === 'bugly') {
      return (
        <>
          <Form.Item
            label="Bugly 拉取地址"
            name="endpoint"
            rules={[{ required: true, message: '请输入 Bugly 拉取地址' }]}
            extra="用于手动同步 Bugly 问题列表，例如测试环境可填 mock server。"
          >
            <Input data-testid="connector-bugly-endpoint" placeholder="https://bugly.example.com" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item label="Issues Path" name="issuesPath" style={{ flex: 1 }}>
              <Input data-testid="connector-bugly-issues-path" placeholder="/issues" />
            </Form.Item>
            <Form.Item label="App ID（可选）" name="appId" style={{ flex: 1 }}>
              <Input data-testid="connector-bugly-app-id" placeholder="demo-app" />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item
              label="App Key（可选）"
              name="appKey"
              style={{ flex: 1 }}
              extra={editing?.config?.appKey === '__configured__' ? '留空表示保留当前 App Key。' : undefined}
            >
              <Input.Password data-testid="connector-bugly-app-key" placeholder="demo-key" />
            </Form.Item>
            <Form.Item
              label="API Token（可选）"
              name="apiToken"
              style={{ flex: 1 }}
              extra={editing?.config?.apiToken === '__configured__' ? '留空表示保留当前 Token。' : undefined}
            >
              <Input.Password data-testid="connector-bugly-api-token" placeholder="token" />
            </Form.Item>
          </Space>
        </>
      );
    }
    if (selectedType === 'dingtalk' || selectedType === 'feishu') {
      return (
        <>
          <Form.Item label="校验 Token（可选）" name="verificationToken">
            <Input data-testid="connector-verification-token" placeholder="用于接收侧校验的 token" />
          </Form.Item>
          <Form.Item
            label="签名 Secret（可选）"
            name="secret"
            extra={editing?.config?.secret === '__configured__' ? '留空表示保留当前 Secret。' : '平台会按连接器类型解析入站消息，Secret 用于后续增强校验。'}
          >
            <Input.Password data-testid="connector-secret" placeholder="secret" />
          </Form.Item>
        </>
      );
    }
    if (selectedType === 'aliyun_log') {
      return (
        <>
          <Form.Item
            label="SLS Endpoint"
            name="endpoint"
            rules={[{ required: true, message: '请输入阿里云日志 Endpoint' }]}
            extra="正式环境可填类似 cn-hangzhou.log.aliyuncs.com；测试环境也可填本地 mock 地址。"
          >
            <Input data-testid="connector-aliyun-endpoint" placeholder="https://cn-hangzhou.log.aliyuncs.com" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item label="Project" name="project" style={{ flex: 1 }} rules={[{ required: true, message: '请输入 Project' }]}>
              <Input data-testid="connector-aliyun-project" placeholder="mobile-app" />
            </Form.Item>
            <Form.Item label="Logstore" name="logstore" style={{ flex: 1 }} rules={[{ required: true, message: '请输入 Logstore' }]}>
              <Input data-testid="connector-aliyun-logstore" placeholder="mobile-error" />
            </Form.Item>
          </Space>
          <Form.Item label="查询语句" name="query" rules={[{ required: true, message: '请输入查询语句' }]}>
            <Input data-testid="connector-aliyun-query" placeholder="level:error" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item label="Access Key ID" name="accessKeyId" style={{ flex: 1 }} rules={[{ required: true, message: '请输入 Access Key ID' }]}>
              <Input data-testid="connector-aliyun-ak" placeholder="LTAI..." />
            </Form.Item>
            <Form.Item
              label="Access Key Secret"
              name="accessKeySecret"
              style={{ flex: 1 }}
              rules={[{ required: !editing || editing.type !== 'aliyun_log', message: '请输入 Access Key Secret' }]}
              extra={editing?.config?.accessKeySecret === '__configured__' ? '留空表示保留当前 Secret。' : undefined}
            >
              <Input.Password data-testid="connector-aliyun-sk" placeholder="Access Key Secret" />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item
              label="Security Token（可选）"
              name="securityToken"
              style={{ flex: 1 }}
              extra={editing?.config?.securityToken === '__configured__' ? '留空表示保留当前 Token。' : undefined}
            >
              <Input.Password data-testid="connector-aliyun-token" placeholder="STS Token" />
            </Form.Item>
            <Form.Item label="最近拉取分钟数" name="fromMinutes" style={{ flex: 1 }}>
              <Input data-testid="connector-aliyun-from-minutes" placeholder="15" />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item label="回看延迟秒数" name="toDelaySeconds" style={{ flex: 1 }}>
              <Input data-testid="connector-aliyun-delay-seconds" placeholder="60" />
            </Form.Item>
            <Form.Item label="单次拉取条数" name="lines" style={{ flex: 1 }}>
              <Input data-testid="connector-aliyun-lines" placeholder="100" />
            </Form.Item>
          </Space>
        </>
      );
    }
    return (
      <Typography.Paragraph style={{ color: '#64748b', marginBottom: 0 }}>
        当前类型无需额外配置，保存后即可使用入站地址接收信号。
      </Typography.Paragraph>
    );
  };

  const activeCount = connectors.filter((item) => item.status === 'active').length;
  const pullEnabledCount = connectors.filter((item) => supportsPull(item)).length;
  const lastSyncFailedCount = connectors.filter((item) => item.lastSyncStatus === 'failed').length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '连接器总数', value: connectors.length, icon: <ApiOutlined />, tone: 'purple' },
          { key: 'active', label: '启用中', value: activeCount, icon: <SyncOutlined />, tone: 'cyan' },
          { key: 'pull', label: '支持主动拉取', value: pullEnabledCount, icon: <HistoryOutlined />, tone: 'amber' },
          { key: 'failed', label: '最近同步失败', value: lastSyncFailedCount, icon: <ReloadOutlined />, tone: 'rose' },
        ]}
        actions={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => void fetchData()}>
              刷新
            </Button>
            <Button type="primary" className="brand-button" icon={<PlusOutlined />} onClick={() => openModal()}>
              新增连接器
            </Button>
          </Space>
        )}
      />

      <Card className="scene-card" title="连接器列表">
        {loadError ? (
          <PageLoadState subTitle={loadError} onRetry={() => void fetchData()} />
        ) : (
        <Table
          rowKey="id"
          loading={loading}
          dataSource={connectors}
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            {
              title: '连接器',
              dataIndex: 'name',
              width: 240,
              render: (value: string) => (
                <Space direction="vertical" size={2}>
                  <Space size={8}>
                    <ApiOutlined style={{ color: '#1677ff' }} />
                    <span style={{ fontWeight: 600 }}>{value}</span>
                  </Space>
                </Space>
              ),
            },
            {
              title: '类型',
              dataIndex: 'type',
              width: 140,
              render: (value: string) => (
                <Tag color="blue">{CONNECTOR_TYPE_OPTIONS.find((item) => item.value === value)?.label || value}</Tag>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (value: string) => (
                <Tag color={value === 'active' ? 'success' : 'default'}>
                  {value === 'active' ? '启用' : '停用'}
                </Tag>
              ),
            },
            {
              title: '健康状态',
              key: 'health',
              width: 200,
              render: (_: unknown, record: IntegrationConnector) => {
                const config = healthStatusMap[record.healthStatus || 'warning'] || healthStatusMap.warning;
                return (
                  <Space direction="vertical" size={2}>
                    <Tag color={config.color}>{config.label}</Tag>
                    <span style={{ fontSize: 12, color: '#64748b' }}>{record.healthSummary || '等待首次同步'}</span>
                  </Space>
                );
              },
            },
            {
              title: '接入地址',
              dataIndex: 'inboundPath',
              render: (value: string, record: IntegrationConnector) => (
                <Space direction="vertical" size={2}>
                  <Typography.Text copyable style={{ fontSize: 12, color: '#64748b' }}>
                    {value}
                  </Typography.Text>
                  <span style={{ fontSize: 12, color: '#94a3b8' }}>{getConfigSummary(record)}</span>
                </Space>
              ),
            },
            {
              title: '最近同步',
              key: 'lastSync',
              width: 220,
              render: (_: unknown, record: IntegrationConnector) => (
                <Space direction="vertical" size={2}>
                  <Tag color={record.lastSyncStatus === 'failed' ? 'error' : record.lastSyncStatus === 'success' ? 'success' : 'default'}>
                    {record.lastSyncStatus || '未执行'}
                  </Tag>
                  <span style={{ color: '#64748b', fontSize: 12 }}>
                    {record.lastSyncAt ? formatDateTime(record.lastSyncAt) : '暂无'}
                  </span>
                  {record.lastError ? (
                    <span style={{ color: '#ef4444', fontSize: 12 }}>
                      {record.lastErrorKind ? `[${record.lastErrorKind}] ` : ''}{record.lastError}
                    </span>
                  ) : null}
                </Space>
              ),
            },
            {
              title: '操作',
              key: 'actions',
              width: 380,
              render: (_: unknown, record: IntegrationConnector) => (
                <Space wrap>
                  <Button type="link" onClick={() => void handleTest(record)} loading={testingId === record.id}>
                    测试
                  </Button>
                  <Button
                    type="link"
                    icon={<SyncOutlined />}
                    onClick={() => void handleSync(record)}
                    loading={syncingId === record.id}
                    disabled={!supportsPull(record)}
                  >
                    同步
                  </Button>
                  {supportsPull(record) && record.lastSyncStatus === 'failed' ? (
                    <Button type="link" onClick={() => void handleRetry(record)} loading={syncingId === record.id}>
                      重试
                    </Button>
                  ) : null}
                  <Button type="link" icon={<HistoryOutlined />} onClick={() => void openSyncRecords(record)}>
                    记录
                  </Button>
                  <Button type="link" icon={<EditOutlined />} onClick={() => openModal(record)}>
                    编辑
                  </Button>
                  <Popconfirm title="确定删除该连接器？" onConfirm={() => void handleDelete(record)}>
                    <Button type="link" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
        )}
      </Card>

      <Modal
        title={editing ? '编辑连接器' : '新增连接器'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={() => void handleSave()}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        destroyOnHidden
        width={720}
      >
        <Form form={form} layout="vertical" initialValues={{ type: 'webhook', status: 'active' }}>
          <Form.Item label="连接器名称" name="name" rules={[{ required: true, message: '请输入连接器名称' }]}>
            <Input data-testid="connector-name-input" placeholder="例如：Bugly Android 正式环境" />
          </Form.Item>
          <Space style={{ display: 'flex' }} size={16} align="start">
            <Form.Item label="连接器类型" name="type" rules={[{ required: true }]}> 
              <Select data-testid="connector-type-select" style={{ width: 220 }} options={CONNECTOR_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item label="状态" name="status" rules={[{ required: true }]}> 
              <Select data-testid="connector-status-select" style={{ width: 160 }} options={STATUS_OPTIONS} />
            </Form.Item>
          </Space>
          {renderTypeSpecificFields()}
        </Form>
      </Modal>

      <Drawer
        title={recordsConnector ? `同步记录 · ${recordsConnector.name}` : '同步记录'}
        open={recordsVisible}
        onClose={() => setRecordsVisible(false)}
        size="large"
      >
        <Table
          rowKey="id"
          loading={recordsLoading}
          dataSource={syncRecords}
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            { title: '触发方式', dataIndex: 'triggerType', width: 120 },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (value: string) => (
                <Tag color={value === 'failed' ? 'error' : value === 'success' ? 'success' : 'default'}>{value}</Tag>
              ),
            },
            { title: '导入数', dataIndex: 'importedCount', width: 90 },
            { title: '聚类数', dataIndex: 'clusteredCount', width: 90 },
            {
              title: '错误分类',
              dataIndex: 'errorKind',
              width: 140,
              render: (value?: string) => value ? <Tag color="error">{value}</Tag> : <span style={{ color: '#cbd5e1' }}>无</span>,
            },
            {
              title: '可重试',
              dataIndex: 'retryable',
              width: 90,
              render: (value?: boolean) => value ? '是' : '否',
            },
            {
              title: '开始时间',
              dataIndex: 'startedAt',
              width: 180,
              render: (value: string) => formatDateTime(value),
            },
            {
              title: '错误信息',
              dataIndex: 'errorMessage',
              render: (value?: string) => value || <span style={{ color: '#cbd5e1' }}>无</span>,
            },
          ]}
        />
      </Drawer>
    </PageLayout>
  );
};

export default ProjectIntegrationsPage;
