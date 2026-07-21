import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Space, Tag, Switch, InputNumber, Input, Spin, Empty, Form, Alert, Select } from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import { SettingOutlined, ThunderboltOutlined, ArrowUpOutlined, ArrowDownOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';
import { listRetrieverPlugins, updateRetrieverPlugin, toggleRetrieverPlugin, sortRetrieverPlugins, testRetrieverPlugin } from '../../api';
import type { RetrieverConfigSchema, RetrieverConfigSchemaProperty, RetrieverPluginItem } from '../../api/types';
import { getErrorMessage } from '../../utils/error';

interface ProjectRetrieverPluginsProps {
  projectId: number;
}

const ProjectRetrieverPlugins: React.FC<ProjectRetrieverPluginsProps> = ({ projectId }) => {
  const [configForm] = Form.useForm<ConfigFormValues>();
  const [plugins, setPlugins] = useState<RetrieverPluginItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingPlugin, setEditingPlugin] = useState<RetrieverPluginItem | null>(null);
  const [configText, setConfigText] = useState('');
  const [configSaving, setConfigSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, { connected: boolean; error?: string }>>({});
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [sortDrafts, setSortDrafts] = useState<Record<number, number>>({});

  const fetchPlugins = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listRetrieverPlugins(projectId);
      setPlugins(res.data || []);
      setSortDrafts({});
    } catch {
      message.error('获取检索插件列表失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void fetchPlugins(); }, [fetchPlugins]);

  const handleToggle = async (id: number) => {
    setTogglingId(id);
    try {
      await toggleRetrieverPlugin(projectId, id);
      void fetchPlugins();
    } catch (err) {
      message.error(getErrorMessage(err, '切换状态失败'));
    } finally {
      setTogglingId(null);
    }
  };

  const handleSortChange = async (pluginId: number, newOrder: number) => {
    const reordered = normalizeSortItems(
      plugins.map(plugin => ({
        ...plugin,
        sortOrder: plugin.id === pluginId ? newOrder : plugin.sortOrder,
      })),
    );
    try {
      await sortRetrieverPlugins(projectId, reordered);
      void fetchPlugins();
    } catch (err) {
      message.error(getErrorMessage(err, '更新排序失败'));
    }
  };

  const handleMoveUp = async (index: number) => {
    if (index <= 0) return;
    const sorted = sortPlugins(plugins);
    const current = sorted[index];
    const prev = sorted[index - 1];
    const items = [
      { id: current.id, sortOrder: prev.sortOrder },
      { id: prev.id, sortOrder: current.sortOrder },
    ];
    try {
      await sortRetrieverPlugins(projectId, items);
      void fetchPlugins();
    } catch (err) {
      message.error(getErrorMessage(err, '排序失败'));
    }
  };

  const handleMoveDown = async (index: number) => {
    const sorted = sortPlugins(plugins);
    if (index >= sorted.length - 1) return;
    const current = sorted[index];
    const next = sorted[index + 1];
    const items = [
      { id: current.id, sortOrder: next.sortOrder },
      { id: next.id, sortOrder: current.sortOrder },
    ];
    try {
      await sortRetrieverPlugins(projectId, items);
      void fetchPlugins();
    } catch (err) {
      message.error(getErrorMessage(err, '排序失败'));
    }
  };

  const handleOpenConfig = (record: RetrieverPluginItem) => {
    setEditingPlugin(record);
    setConfigText(record.config || '{}');
    configForm.resetFields();
    const parsed = parsePluginConfig(record.config);
    if (parsed.ok) {
      configForm.setFieldsValue(toFormValues(record.configSchema, parsed.value));
    }
    setConfigModalVisible(true);
  };

  const handleSaveConfig = async () => {
    if (!editingPlugin) return;
    let nextConfig = '{}';
    if (hasSchemaConfig(editingPlugin.configSchema)) {
      try {
        const values = await configForm.validateFields();
        nextConfig = JSON.stringify(toPluginConfig(editingPlugin.configSchema, values));
      } catch {
        return;
      }
    } else {
      try {
        JSON.parse(configText);
        nextConfig = configText;
      } catch {
        message.error('JSON 格式无效，请检查输入');
        return;
      }
    }
    setConfigSaving(true);
    try {
      await updateRetrieverPlugin(projectId, editingPlugin.id, { config: nextConfig });
      message.success('配置已更新');
      setConfigModalVisible(false);
      void fetchPlugins();
    } catch (err) {
      message.error(getErrorMessage(err, '保存配置失败'));
    } finally {
      setConfigSaving(false);
    }
  };

  const handleTest = async (id: number) => {
    setTestingId(id);
    setTestResults(prev => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    try {
      const res = await testRetrieverPlugin(projectId, id);
      setTestResults(prev => ({ ...prev, [id]: { connected: res.data?.connected ?? false, error: res.data?.error } }));
      if (res.data?.connected) {
        message.success('连接测试成功');
      } else {
        message.warning(res.data?.error || '连接测试失败');
      }
    } catch (err) {
      setTestResults(prev => ({ ...prev, [id]: { connected: false, error: getErrorMessage(err, '连接测试失败') } }));
      message.error(getErrorMessage(err, '连接测试失败'));
    } finally {
      setTestingId(null);
    }
  };

  const sortedPlugins = sortPlugins(plugins);

  const columns: TableColumnsType<RetrieverPluginItem> = [
    {
      title: '名称',
      dataIndex: 'displayName',
      key: 'displayName',
      width: 200,
      render: (name: string, record) => (
        <Space>
          <span>{name || record.name}</span>
          {record.isBuiltIn && <Tag color="blue">内置</Tag>}
        </Space>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      width: 250,
      render: (v: string) => v || '-',
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (v: boolean, record) => (
        <Switch size="small" checked={v} loading={togglingId === record.id} onChange={() => handleToggle(record.id)} />
      ),
    },
    {
      title: '排序',
      key: 'sortOrder',
      width: 160,
      render: (_: unknown, record, index) => (
        <Space size={4}>
          <InputNumber
            size="small"
            min={0}
            value={sortDrafts[record.id] ?? record.sortOrder}
            onChange={(v) => {
              if (v !== null) {
                setSortDrafts(prev => ({ ...prev, [record.id]: Number(v) }));
              }
            }}
            onBlur={() => {
              const draft = sortDrafts[record.id];
              if (draft !== undefined && draft !== record.sortOrder) {
                void handleSortChange(record.id, draft);
              }
            }}
            onPressEnter={(e) => {
              const v = Number((e.target as HTMLInputElement).value);
              if (!isNaN(v)) handleSortChange(record.id, v);
            }}
            style={{ width: 60 }}
          />
          <Button
            size="small"
            icon={<ArrowUpOutlined />}
            disabled={index === 0}
            onClick={() => handleMoveUp(index)}
          />
          <Button
            size="small"
            icon={<ArrowDownOutlined />}
            disabled={index === sortedPlugins.length - 1}
            onClick={() => handleMoveDown(index)}
          />
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: unknown, record) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<SettingOutlined />} onClick={() => handleOpenConfig(record)}>配置</Button>
          <Button
            type="link"
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testingId === record.id}
            onClick={() => handleTest(record.id)}
          >
            测试
          </Button>
          {testResults[record.id] && (
            testResults[record.id].connected
              ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
              : <CloseCircleOutlined style={{ color: '#ff4d4f' }} title={testResults[record.id].error} />
          )}
        </Space>
      ),
    },
  ];

  if (loading) {
    return <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>;
  }

  if (plugins.length === 0) {
    return <Empty description="暂无检索插件" />;
  }

  return (
    <>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={sortedPlugins}
        pagination={false}
        size="small"
      />

      <Modal
        title={`配置 - ${editingPlugin?.displayName || editingPlugin?.name || ''}`}
        open={configModalVisible}
        onOk={handleSaveConfig}
        onCancel={() => {
          setConfigModalVisible(false);
          configForm.resetFields();
        }}
        confirmLoading={configSaving}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        {editingPlugin && renderConfigEditor(editingPlugin, configForm, configText, setConfigText)}
      </Modal>
    </>
  );
};

export default ProjectRetrieverPlugins;

type ConfigFormValues = Record<string, unknown>;

function sortPlugins(plugins: RetrieverPluginItem[]): RetrieverPluginItem[] {
  return [...plugins].sort((a, b) => {
    if (a.sortOrder !== b.sortOrder) return a.sortOrder - b.sortOrder;
    return a.id - b.id;
  });
}

function normalizeSortItems(plugins: RetrieverPluginItem[]): { id: number; sortOrder: number }[] {
  return sortPlugins(plugins).map((plugin, index) => ({
    id: plugin.id,
    sortOrder: index * 10,
  }));
}

function hasSchemaConfig(schema?: RetrieverConfigSchema): boolean {
  return Boolean(schema && schema.type === 'object' && schema.properties);
}

function parsePluginConfig(config?: string): { ok: true; value: Record<string, unknown> } | { ok: false } {
  if (!config?.trim()) return { ok: true, value: {} };
  try {
    const value = JSON.parse(config) as unknown;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return { ok: true, value: value as Record<string, unknown> };
    }
  } catch {
    return { ok: false };
  }
  return { ok: true, value: {} };
}

function toFormValues(schema: RetrieverConfigSchema | undefined, config: Record<string, unknown>): ConfigFormValues {
  const values: ConfigFormValues = {};
  Object.entries(schema?.properties || {}).forEach(([key, property]) => {
    values[key] = config[key] ?? property.default;
  });
  return values;
}

function toPluginConfig(schema: RetrieverConfigSchema | undefined, values: ConfigFormValues): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  Object.entries(schema?.properties || {}).forEach(([key, property]) => {
    config[key] = normalizeValue(property, values[key]);
  });
  return compactConfig(config);
}

function compactConfig(config: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(config).filter(([, value]) => {
      if (value === undefined || value === null) return false;
      if (typeof value === 'string') return value.trim() !== '';
      return true;
    }).map(([key, value]) => [key, typeof value === 'string' ? value.trim() : value]),
  );
}

function normalizeValue(property: RetrieverConfigSchemaProperty, value: unknown): unknown {
  if (property.type === 'integer' || property.type === 'number') {
    if (value === '' || value === undefined || value === null) return undefined;
    return Number(value);
  }
  return value;
}

function renderConfigEditor(
  plugin: RetrieverPluginItem,
  form: ReturnType<typeof Form.useForm<ConfigFormValues>>[0],
  configText: string,
  setConfigText: (value: string) => void,
) {
  const parsed = parsePluginConfig(plugin.config);
  if (!parsed.ok || !hasSchemaConfig(plugin.configSchema)) {
    return (
      <Space direction="vertical" style={{ width: '100%' }}>
        {!parsed.ok && <Alert type="warning" showIcon message="当前配置不是有效 JSON，请修正后保存。" />}
        {parsed.ok && <Alert type="info" showIcon message="该插件未暴露配置 Schema，暂使用 JSON 配置。" />}
        <Input.TextArea
          value={configText}
          onChange={(e) => setConfigText(e.target.value)}
          rows={14}
          style={{ fontFamily: 'monospace' }}
        />
      </Space>
    );
  }

  const properties = Object.entries(plugin.configSchema?.properties || {});
  if (properties.length === 0) {
    return <Empty description="该插件无需配置" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return (
    <Form form={form} layout="vertical" preserve={false}>
      {properties.map(([key, property]) => renderSchemaField(plugin.configSchema, key, property))}
    </Form>
  );
}

function renderSchemaField(schema: RetrieverConfigSchema | undefined, key: string, property: RetrieverConfigSchemaProperty) {
  const required = schema?.required?.includes(key) ?? false;
  const rules = [
    ...(required ? [{ required: true, message: `请填写${property.title || key}` }] : []),
    ...(property.format === 'uri' ? [{ type: 'url' as const, message: '请输入有效 URL' }] : []),
  ];
  const commonProps = {
    key,
    name: key,
    label: property.title || key,
    extra: property.description,
    rules,
    valuePropName: property.type === 'boolean' ? 'checked' : 'value',
  };

  if (property.enum?.length) {
    return (
      <Form.Item {...commonProps}>
        <Select
          allowClear={!required}
          options={property.enum.map((value) => ({ label: String(value), value }))}
        />
      </Form.Item>
    );
  }

  if (property.type === 'boolean') {
    return (
      <Form.Item {...commonProps}>
        <Switch />
      </Form.Item>
    );
  }

  if (property.type === 'integer' || property.type === 'number') {
    return (
      <Form.Item {...commonProps}>
        <InputNumber
          min={property.minimum}
          max={property.maximum}
          precision={property.type === 'integer' ? 0 : undefined}
          style={{ width: '100%' }}
        />
      </Form.Item>
    );
  }

  if (property.format === 'password') {
    return (
      <Form.Item {...commonProps}>
        <Input.Password />
      </Form.Item>
    );
  }

  return (
    <Form.Item {...commonProps}>
      <Input />
    </Form.Item>
  );
}
