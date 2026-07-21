import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd';
import type { TableColumnsType } from 'antd';
import {
  BellOutlined,
  DeleteOutlined,
  EditOutlined,
  LinkOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import {
  batchUpdateProjectNotificationPolicies,
  createProjectWebhook,
  deleteProjectWebhook,
  listProjectNotificationPolicies,
  listProjectWebhooks,
  testProjectWebhook,
  updateProjectWebhook,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLayout from '../../components/layout/PageLayout';
import { message } from '../../utils/appMessage';
import type { ProjectNotificationPolicy, ProjectWebhook } from '../../types';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

const CATEGORY_LABELS: Record<string, string> = {
  defect_assigned: '缺陷被指派',
  defect_status_change: '缺陷状态变更',
  defect_mention: '评论中被提及',
  defect_due_soon: '缺陷即将到期',
  iteration_start: '迭代开始',
  iteration_end: '迭代结束提醒',
  collaboration_complete: '协作任务完成',
};

const NO_WEBHOOK_VALUE = '__none__';

type EditablePolicy = ProjectNotificationPolicy & {
  key: string;
  webhookId: number | null;
};

interface WebhookFormValues {
  name: string;
  url: string;
  secret?: string;
  enabled: boolean;
}

const ProjectNotifications: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);

  const [loading, setLoading] = useState(false);
  const [savingPolicies, setSavingPolicies] = useState(false);
  const [testingWebhookId, setTestingWebhookId] = useState<number | null>(null);
  const [webhooks, setWebhooks] = useState<ProjectWebhook[]>([]);
  const [policies, setPolicies] = useState<EditablePolicy[]>([]);
  const [webhookModalOpen, setWebhookModalOpen] = useState(false);
  const [editingWebhook, setEditingWebhook] = useState<ProjectWebhook | null>(null);
  const [form] = Form.useForm();


  const isFormValidationError = (error: unknown) => {
    return Boolean((error as RequestError | undefined)?.errorFields);
  };

  const webhookOptions = useMemo(
    () => webhooks.map((hook) => ({
      label: hook.enabled ? hook.name : `${hook.name}（已停用）`,
      value: hook.id,
    })),
    [webhooks],
  );

  const fetchData = useCallback(async () => {
    if (!pid) return;
    setLoading(true);
    try {
      const [webhookRes, policyRes] = await Promise.all([
        listProjectWebhooks(pid),
        listProjectNotificationPolicies(pid),
      ]);
      const nextWebhooks = webhookRes.data || [];
      const nextPolicies = (policyRes.data || []).map((item: ProjectNotificationPolicy) => ({
        ...item,
        key: item.category,
        webhookId: item.webhookId ?? null,
      }));
      setWebhooks(nextWebhooks);
      setPolicies(nextPolicies);
    } catch {
      message.error('获取项目通知配置失败');
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    if (pid) {
      void fetchData();
    }
  }, [fetchData, pid]);

  const openWebhookModal = (record?: ProjectWebhook) => {
    setEditingWebhook(record || null);
    form.setFieldsValue(record ? {
      name: record.name,
      url: record.url,
      secret: '',
      enabled: record.enabled,
    } : {
      name: '',
      url: '',
      secret: '',
      enabled: true,
    });
    setWebhookModalOpen(true);
  };

  const handleSaveWebhook = async () => {
    try {
      const values = await form.validateFields() as WebhookFormValues;
      if (editingWebhook) {
        const payload: Record<string, unknown> = {
          name: values.name,
          url: values.url,
          enabled: values.enabled,
        };
        if (values.secret) {
          payload.secret = values.secret;
        }
        await updateProjectWebhook(pid, editingWebhook.id, payload as WebhookFormValues);
        message.success('项目 Webhook 已更新');
      } else {
        await createProjectWebhook(pid, values);
        message.success('项目 Webhook 已创建');
      }
      setWebhookModalOpen(false);
      await fetchData();
    } catch (error: unknown) {
      if (isFormValidationError(error)) {
        return;
      }
      message.error(getErrorMessage(error, '保存项目 Webhook 失败'));
    }
  };

  const handleDeleteWebhook = async (webhookId: number) => {
    try {
      await deleteProjectWebhook(pid, webhookId);
      message.success('项目 Webhook 已删除');
      await fetchData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除项目 Webhook 失败'));
    }
  };

  const handleTestWebhook = async (webhookId: number) => {
    setTestingWebhookId(webhookId);
    try {
      await testProjectWebhook(pid, webhookId, { event: 'project_notification_test' });
      message.success('项目 Webhook 测试成功');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '项目 Webhook 测试失败'));
    } finally {
      setTestingWebhookId(null);
    }
  };

  const updatePolicy = (category: string, patch: Partial<EditablePolicy>) => {
    setPolicies((prev) => prev.map((item) => (
      item.category === category ? { ...item, ...patch } : item
    )));
  };

  const handleSavePolicies = async () => {
    setSavingPolicies(true);
    try {
      await batchUpdateProjectNotificationPolicies(pid, policies.map((item) => ({
        category: item.category,
        inAppEnabled: item.inAppEnabled,
        emailEnabled: item.emailEnabled,
        webhookId: item.webhookId || null,
      })));
      message.success('项目通知策略已保存');
      await fetchData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '保存项目通知策略失败'));
    } finally {
      setSavingPolicies(false);
    }
  };

  const webhookColumns: TableColumnsType<ProjectWebhook> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (value: string) => (
        <Space>
          <LinkOutlined style={{ color: '#0ea5e9' }} />
          <span style={{ fontWeight: 600, color: '#0f172a' }}>{value}</span>
        </Space>
      ),
    },
    {
      title: '地址',
      dataIndex: 'url',
      key: 'url',
      render: (value: string) => (
        <span style={{ color: '#64748b', fontSize: 12 }}>{value}</span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'success' : 'default'}>
          {enabled ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '密钥',
      dataIndex: 'hasSecret',
      key: 'hasSecret',
      width: 120,
      render: (hasSecret?: boolean) => hasSecret ? <Tag color="blue">已配置</Tag> : <span style={{ color: '#cbd5e1' }}>未配置</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      render: (_: unknown, record: ProjectWebhook) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'nowrap', whiteSpace: 'nowrap' }}>
          <Button
            type="link"
            onClick={() => handleTestWebhook(record.id)}
            loading={testingWebhookId === record.id}
            style={{ paddingInline: 0 }}
          >
            测试
          </Button>
          <Button type="link" icon={<EditOutlined />} onClick={() => openWebhookModal(record)} style={{ paddingInline: 0 }}>
            编辑
          </Button>
          <Popconfirm title="确定删除此项目 Webhook？" onConfirm={() => handleDeleteWebhook(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />} style={{ paddingInline: 0 }}>
              删除
            </Button>
          </Popconfirm>
        </div>
      ),
    },
  ];

  const policyColumns: TableColumnsType<EditablePolicy> = [
    {
      title: '通知类别',
      dataIndex: 'category',
      key: 'category',
      render: (category: string) => (
        <div>
          <div style={{ fontWeight: 600, color: '#0f172a' }}>{CATEGORY_LABELS[category] || category}</div>
          <div style={{ color: '#94a3b8', fontSize: 12 }}>{category}</div>
        </div>
      ),
    },
    {
      title: '站内消息',
      dataIndex: 'inAppEnabled',
      key: 'inAppEnabled',
      width: 120,
      render: (value: boolean, record: EditablePolicy) => (
        <Switch
          checked={value}
          aria-label={`站内消息-${record.category}`}
          onChange={(checked) => updatePolicy(record.category, { inAppEnabled: checked })}
        />
      ),
    },
    {
      title: '邮件',
      dataIndex: 'emailEnabled',
      key: 'emailEnabled',
      width: 120,
      render: (value: boolean, record: EditablePolicy) => (
        <Switch
          checked={value}
          aria-label={`邮件通知-${record.category}`}
          onChange={(checked) => updatePolicy(record.category, { emailEnabled: checked })}
        />
      ),
    },
    {
      title: 'Webhook',
      dataIndex: 'webhookId',
      key: 'webhookId',
      width: 260,
      render: (value: number | null, record: EditablePolicy) => (
        <Select
          value={value ?? NO_WEBHOOK_VALUE}
          style={{ width: '100%' }}
          placeholder="不发送 Webhook"
          options={[{ label: '不发送 Webhook', value: NO_WEBHOOK_VALUE }, ...webhookOptions]}
          onChange={(next) => updatePolicy(record.category, {
            webhookId: next === NO_WEBHOOK_VALUE ? null : Number(next),
          })}
        />
      ),
    },
  ];

  const enabledWebhookCount = webhooks.filter((hook) => hook.enabled).length;
  const emailEnabledPolicyCount = policies.filter((policy) => policy.emailEnabled).length;
  const webhookBoundPolicyCount = policies.filter((policy) => Boolean(policy.webhookId)).length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'webhooks', label: 'Webhook 总数', value: webhooks.length, icon: <BellOutlined />, tone: 'purple' },
          { key: 'enabled', label: '启用中的 Webhook', value: enabledWebhookCount, icon: <LinkOutlined />, tone: 'cyan' },
          { key: 'policies', label: '通知策略', value: policies.length, icon: <BellOutlined />, tone: 'amber' },
          { key: 'bound', label: '已绑定 Webhook 策略', value: webhookBoundPolicyCount + emailEnabledPolicyCount, icon: <PlusOutlined />, tone: 'green' },
        ]}
        actions={(
          <Button
            type="primary"
            className="brand-button"
            icon={<PlusOutlined />}
            onClick={() => openWebhookModal()}
          >
            新增 Webhook
          </Button>
        )}
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16, borderRadius: 12 }}
        title="项目通知作为上限，个人通知偏好只能在项目允许范围内细化；Webhook 为项目级单选目标。"
      />

      <Card
        title={<Space><BellOutlined /> 项目 Webhook</Space>}
        className="scene-card"
      >
        {webhooks.length === 0 && !loading ? (
          <Empty description="暂无项目 Webhook" image={Empty.PRESENTED_IMAGE_SIMPLE}>
            <Button type="primary" onClick={() => openWebhookModal()}>
              创建第一个 Webhook
            </Button>
          </Empty>
        ) : (
          <Table
            columns={webhookColumns}
            dataSource={webhooks}
            rowKey="id"
            pagination={false}
            loading={loading}
          />
        )}
      </Card>

      <Card
        title="通知策略"
        extra={(
          <Button type="primary" onClick={handleSavePolicies} loading={savingPolicies}>
            保存通知策略
          </Button>
        )}
        className="utility-card"
      >
        <Table
          columns={policyColumns}
          dataSource={policies}
          rowKey="category"
          pagination={false}
          loading={loading}
        />
      </Card>

      <Modal
        title={editingWebhook ? '编辑项目 Webhook' : '新增项目 Webhook'}
        open={webhookModalOpen}
        onCancel={() => setWebhookModalOpen(false)}
        onOk={handleSaveWebhook}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="Webhook 名称"
            rules={[{ required: true, message: '请输入 Webhook 名称' }]}
          >
            <Input placeholder="如：飞书群通知 / Slack 告警" />
          </Form.Item>
          <Form.Item
            name="url"
            label="Webhook 地址"
            rules={[{ required: true, message: '请输入 Webhook 地址' }]}
          >
            <Input placeholder="https://example.com/webhook" />
          </Form.Item>
          <Form.Item name="secret" label="签名密钥（可选）">
            <Input placeholder="如需签名校验可填写" />
          </Form.Item>
          <Form.Item name="enabled" label="启用状态" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </PageLayout>
  );
};

export default ProjectNotifications;
