import React, { useCallback, useEffect, useState } from 'react';
import {
  Card,
  Form,
  Input,
  Avatar,
  Button,
  Tabs,
  Table,
  Select,
  Space,
  Popconfirm,
  Modal,
  Tag,
  Empty,
  Checkbox,
  Upload,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../utils/appMessage';
import { appStorage } from '../utils/storage';
import {
  UserOutlined, MailOutlined, EditOutlined, PlusOutlined,
  DeleteOutlined, SaveOutlined, UploadOutlined
} from '@ant-design/icons';
import {
  getProfile, updateProfile, listCredentials, createCredential,
  updateCredential, deleteCredential, getNotificationPrefs, batchUpdateNotificationPrefs, uploadMyAvatar,
  updateMyAgentTypes, testYunxiaoConnection, changeMyPassword,
  getUserWebhookSettings, updateUserWebhookSettings, testUserWebhookSettings,
} from '../api';
import { AGENT_TYPES } from '../types';
import type { RepoCredential, User, UserWebhookSettings } from '../types';
import { getErrorMessage } from '../utils/error';
import { parseCredentialExtraConfig } from '../utils/credential';
import { formatDateTime } from '../utils/formatDate';

interface UserCenterContentProps {
  mode?: 'page' | 'modal';
  onUserUpdated?: (user: User) => void;
  initialTab?: string;
  restrictToPassword?: boolean;
  onPasswordChanged?: () => void;
}

interface NotificationPreference {
  id: string;
  category: string;
  channels: string[];
}

interface CredentialExtraConfigValues {
  organizationId?: string;
  workspaceId?: string;
  endpoint?: string;
}

interface CredentialFormValues extends CredentialExtraConfigValues {
  name: string;
  type: string;
  provider: string;
  content?: string;
  username?: string;
  password?: string;
}

interface PasswordFormValues {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

interface AvatarUploadOptions {
  file: File;
  onSuccess?: (response?: unknown, file?: File) => void;
  onError?: (error?: unknown) => void;
}


const UserCenterContent: React.FC<UserCenterContentProps> = ({
  mode = 'page',
  onUserUpdated,
  initialTab = 'basic',
  restrictToPassword = false,
  onPasswordChanged,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState(initialTab);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [form] = Form.useForm();
  const [agentForm] = Form.useForm();
  const [passwordForm] = Form.useForm();

  const [credentials, setCredentials] = useState<RepoCredential[]>([]);
  const [credModalVisible, setCredModalVisible] = useState(false);
  const [editingCred, setEditingCred] = useState<RepoCredential | null>(null);
  const [testingYunxiaoCredentialId, setTestingYunxiaoCredentialId] = useState<number | null>(null);
  const [credForm] = Form.useForm();
  const [notifPrefs, setNotifPrefs] = useState<NotificationPreference[]>([]);
  const [userWebhook, setUserWebhook] = useState<UserWebhookSettings>({ url: '', enabled: false, secretConfigured: false });
  const [userWebhookSaving, setUserWebhookSaving] = useState(false);
  const [userWebhookTesting, setUserWebhookTesting] = useState(false);
  const [webhookForm] = Form.useForm();
  const [credentialType, setCredentialType] = useState<string>();
  const [credentialProvider, setCredentialProvider] = useState<string>();

  const syncUser = useCallback((nextUser: Partial<User>) => {
    if (!nextUser || typeof nextUser !== 'object') return;
    const currentUser = appStorage.getUser() || {};
    const mergedUser = {
      ...currentUser,
      ...nextUser,
    } as User;
    setUser(mergedUser);
    appStorage.setUser(mergedUser);
    window.dispatchEvent(new CustomEvent('user-profile-updated', { detail: mergedUser }));
    onUserUpdated?.(mergedUser);
  }, [onUserUpdated]);

  const fetchProfile = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getProfile();
      syncUser(res.data);
    } catch {
      message.error('获取用户信息失败');
    } finally {
      setLoading(false);
    }
  }, [syncUser]);

  const fetchCredentials = useCallback(async () => {
    try {
      const res = await listCredentials();
      setCredentials(res.data || []);
    } catch {
      // 凭证获取失败不阻塞主流程
    }
  }, []);

  const fetchNotifPrefs = useCallback(async () => {
    try {
      const res = await getNotificationPrefs();
      if (res.data && typeof res.data === 'object' && !Array.isArray(res.data)) {
        const arr = Object.entries(res.data).map(([category, channels]) => ({
          id: category,
          category,
          channels: Array.isArray(channels) ? channels : (typeof channels === 'string' ? channels.split(',').map((c: string) => c.trim()).filter(Boolean) : []),
        }));
        setNotifPrefs(arr);
      } else {
        setNotifPrefs([]);
      }
    } catch {
      // 获取失败不阻塞
    }
  }, []);

  const fetchUserWebhookSettings = useCallback(async () => {
    try {
      const res = await getUserWebhookSettings();
      const next = res.data || { url: '', enabled: false, secretConfigured: false };
      setUserWebhook(next);
      if (restrictToPassword) {
        return;
      }
      webhookForm.setFieldsValue({
        url: next.url || '',
        secret: '',
        enabled: Boolean(next.enabled),
      });
    } catch {
      // 获取失败不阻塞
    }
  }, [restrictToPassword, webhookForm]);

  useEffect(() => {
    fetchProfile();
    if (restrictToPassword) {
      return;
    }
    fetchCredentials();
    fetchNotifPrefs();
    fetchUserWebhookSettings();
  }, [fetchCredentials, fetchNotifPrefs, fetchProfile, fetchUserWebhookSettings, restrictToPassword]);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    if (loading || !user) return;
    if (restrictToPassword) {
      return;
    }
    form.setFieldsValue({
      nickname: user.nickname,
    });
    agentForm.setFieldsValue({
      agentTypes: user.agentTypes?.length ? user.agentTypes : [],
    });
  }, [loading, user, form, agentForm, restrictToPassword]);

  const handleSaveBasic = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const res = await updateProfile(values);
      message.success('基本信息已更新');
      syncUser(res.data);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '更新失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarUpload = async (options: AvatarUploadOptions) => {
    const { file, onSuccess, onError } = options;
    setUploadingAvatar(true);
    try {
      const res = await uploadMyAvatar(file);
      const avatar = res?.data?.avatar;
      if (avatar) {
        syncUser({ ...(user || {}), avatar });
      }
      message.success('头像上传成功');
      onSuccess?.(res, file);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '头像上传失败'));
      onError?.(error);
    } finally {
      setUploadingAvatar(false);
    }
  };

  const handleSaveAgentTypes = async () => {
    try {
      const values = await agentForm.validateFields();
      setSaving(true);
      const res = await updateMyAgentTypes({ agentTypes: values.agentTypes });
      message.success('AGENT 身份已更新');
      syncUser(res.data);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '更新失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleChangePassword = async () => {
    try {
      const values = await passwordForm.validateFields() as PasswordFormValues;
      setSaving(true);
      await changeMyPassword({
        currentPassword: values.currentPassword,
        newPassword: values.newPassword,
      });
      message.success('密码已修改');
      passwordForm.resetFields();
      syncUser({ ...(user || {}), mustChangePassword: false });
      onPasswordChanged?.();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '修改密码失败'));
    } finally {
      setSaving(false);
    }
  };

  const openCredModal = (cred?: RepoCredential) => {
    setEditingCred(cred || null);
    if (cred) {
      setCredentialType(cred.type);
      setCredentialProvider(cred.provider);
      const extra = parseCredentialExtraConfig(cred.extraConfig);
      credForm.setFieldsValue({
        name: cred.name,
        type: cred.type,
        provider: cred.provider,
        content: '',
        organizationId: extra.organizationId || undefined,
        workspaceId: extra.workspaceId || undefined,
        endpoint: extra.endpoint || undefined,
      });
    } else {
      setCredentialType(undefined);
      setCredentialProvider(undefined);
      credForm.resetFields();
    }
    setCredModalVisible(true);
  };

  const handleSaveCred = async () => {
    try {
      const values = await credForm.validateFields() as CredentialFormValues;
      const payload: {
        name: string;
        type: string;
        provider: string;
        content: string;
        extraConfig?: string;
      } = {
        name: values.name,
        type: values.type,
        provider: values.provider,
        content: String(values.content || ''),
      };
      if (values.type === 'username_password') {
        const username = String(values.username || '').trim();
        const password = String(values.password || '');
        payload.content = JSON.stringify({ username, password });
      }
      if (values.provider === 'yunxiao') {
        payload.extraConfig = buildCredentialExtraConfig(values);
      } else {
        payload.extraConfig = '';
      }
      if (editingCred) {
        await updateCredential(editingCred.id, payload);
        message.success('凭证已更新');
      } else {
        await createCredential(payload);
        message.success('凭证已添加');
      }
      setCredModalVisible(false);
      setCredentialType(undefined);
      setCredentialProvider(undefined);
      fetchCredentials();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleDeleteCred = async (id: number) => {
    try {
      await deleteCredential(id);
      message.success('凭证已删除');
      fetchCredentials();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除失败'));
    }
  };

  const buildCredentialExtraConfig = (values: CredentialExtraConfigValues) => {
    const organizationId = String(values.organizationId || '').trim();
    const workspaceId = String(values.workspaceId || '').trim();
    const endpoint = String(values.endpoint || '').trim();
    const payload: Record<string, string> = {};
    if (organizationId) payload.organizationId = organizationId;
    if (workspaceId) payload.workspaceId = workspaceId;
    if (endpoint) payload.endpoint = endpoint;
    return Object.keys(payload).length > 0 ? JSON.stringify(payload) : '';
  };

  const handleTestYunxiaoCredential = async (record: RepoCredential) => {
    try {
      setTestingYunxiaoCredentialId(record.id);
      const extra = parseCredentialExtraConfig(record.extraConfig);
      const res = await testYunxiaoConnection({
        credentialId: record.id,
        organizationId: extra.organizationId || undefined,
        endpoint: extra.endpoint || undefined,
      });
      if (res.data?.success) {
        message.success(res.data?.message || '云效连接成功');
        fetchCredentials();
      } else {
        message.error(res.data?.message || '云效连接失败');
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '云效连接测试失败'));
    } finally {
      setTestingYunxiaoCredentialId(null);
    }
  };

  const updatePrefChannels = async (record: NotificationPreference, channel: 'in_app' | 'email' | 'webhook', enabled: boolean) => {
    const current = record.channels || [];
    const nextSet = new Set(current);
    if (enabled) {
      nextSet.add(channel);
    } else {
      nextSet.delete(channel);
    }
    const ordered = ['in_app', 'email', 'webhook'].filter((c) => nextSet.has(c));

    try {
      await batchUpdateNotificationPrefs({ [record.category]: ordered.join(',') });
      setNotifPrefs((prev) => prev.map((pref) => (
        pref.id === record.id ? { ...pref, channels: ordered } : pref
      )));
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '更新通知偏好失败'));
    }
  };

  const handleSaveUserWebhook = async () => {
    try {
      const values = await webhookForm.validateFields();
      setUserWebhookSaving(true);
      const payload: { url: string; enabled: boolean; secret?: string } = {
        url: String(values.url || '').trim(),
        enabled: Boolean(values.enabled),
      };
      if (String(values.secret || '').trim()) {
        payload.secret = String(values.secret || '').trim();
      }
      const res = await updateUserWebhookSettings(payload);
      const next = res.data || { url: payload.url, enabled: payload.enabled, secretConfigured: Boolean(payload.secret) };
      setUserWebhook(next);
      webhookForm.setFieldsValue({
        url: next.url || '',
        secret: '',
        enabled: Boolean(next.enabled),
      });
      message.success('个人Webhook配置已保存');
    } catch (error: unknown) {
      if (typeof error === 'object' && error !== null && 'errorFields' in error) return;
      message.error(getErrorMessage(error, '保存个人Webhook配置失败'));
    } finally {
      setUserWebhookSaving(false);
    }
  };

  const handleTestUserWebhook = async () => {
    try {
      const values = webhookForm.getFieldsValue();
      const payload: { url: string; enabled: boolean; secret?: string } = {
        url: String(values.url || '').trim(),
        enabled: Boolean(values.enabled),
      };
      if (String(values.secret || '').trim()) {
        payload.secret = String(values.secret || '').trim();
      }
      setUserWebhookTesting(true);
      const res = await testUserWebhookSettings(payload);
      if (res.data?.success) {
        message.success(res.data?.message || '个人Webhook测试成功');
      } else {
        message.error(res?.data?.message || '个人Webhook测试失败');
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '个人Webhook测试失败'));
    } finally {
      setUserWebhookTesting(false);
    }
  };

  const credColumns: TableColumnsType<RepoCredential> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <span style={{ fontWeight: 500 }}>{name}</span>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 120,
      render: (type: string) => {
        const labels: Record<string, string> = {
          pat: 'Personal Access Token',
          oauth: 'OAuth',
          ssh_key: 'SSH Key',
          username_password: '用户名密码',
        };
        return <Tag>{labels[type] || type}</Tag>;
      },
    },
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      width: 100,
      render: (provider: string) => {
        const colors: Record<string, string> = {
          github: '#171515',
          gitlab: '#FC6D26',
          gitea: '#609926',
          yunxiao: '#1677ff',
        };
        return <Tag color={colors[provider] || '#64748b'}>{provider.toUpperCase()}</Tag>;
      },
    },
    {
      title: '凭证值',
      dataIndex: 'maskedValue',
      key: 'maskedValue',
      render: (value: string) => (
        <span style={{ fontFamily: 'monospace', color: '#64748b' }}>{value}</span>
      ),
    },
    {
      title: '最后使用',
      dataIndex: 'lastUsedAt',
      key: 'lastUsedAt',
      width: 160,
      render: (time: string) => formatDateTime(time),
    },
    {
      title: '操作',
      key: 'action',
      width: 230,
      render: (_, record) => (
        <Space>
          {record.provider === 'yunxiao' && (
            <Button
              type="link"
              loading={testingYunxiaoCredentialId === record.id}
              onClick={() => handleTestYunxiaoCredential(record)}
            >
              测试云效
            </Button>
          )}
          <Button type="link" icon={<EditOutlined />} onClick={() => openCredModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此凭证？" onConfirm={() => handleDeleteCred(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const tabItems = [
    {
      key: 'basic',
      label: '基本信息',
      forceRender: true,
      children: (
        <Form form={form} layout="vertical" style={{ maxWidth: 500 }}>
          <Form.Item name="nickname" label="昵称" rules={[{ required: true, message: '请输入昵称' }]}>
            <Input placeholder="显示的昵称" prefix={<UserOutlined />} />
          </Form.Item>
          <Form.Item label="邮箱">
            <Input value={user?.email || ''} disabled prefix={<MailOutlined />} />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSaveBasic}
              loading={saving}
            >
              保存基本信息
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'agent',
      label: 'AGENT 身份',
      forceRender: true,
      children: (
        <Form form={agentForm} layout="vertical">
          <Form.Item name="agentTypes" label="选择您的 AGENT 身份" rules={[{ required: true, message: '请至少选择一个' }]}>
            <Checkbox.Group style={{ display: 'block' }}>
              {AGENT_TYPES.map(opt => (
                <div key={opt.key} style={{ marginBottom: 16 }}>
                  <Checkbox value={opt.key}>
                    <span style={{ fontWeight: 500 }}>{opt.label}</span>
                  </Checkbox>
                  <div style={{ marginLeft: 24, color: '#64748b', fontSize: 13 }}>{opt.desc}</div>
                </div>
              ))}
            </Checkbox.Group>
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSaveAgentTypes}
              loading={saving}
            >
              保存 AGENT 身份
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'password',
      label: '修改密码',
      forceRender: true,
      children: (
        <Form form={passwordForm} layout="vertical" style={{ maxWidth: 480 }}>
          <Form.Item
            name="currentPassword"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password placeholder="输入当前密码" />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 8, message: '新密码长度至少 8 位' },
            ]}
          >
            <Input.Password placeholder="输入新密码" />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error('两次输入的新密码不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleChangePassword}
              loading={saving}
            >
              保存新密码
            </Button>
          </Form.Item>
        </Form>
      ),
    },
    {
      key: 'security',
      label: '安全设置',
      forceRender: true,
      children: (
        <div style={{ maxWidth: 480 }}>
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>密码安全</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: '#f8fafc', borderRadius: 12 }}>
              <div>
                <div style={{ fontSize: 14, color: '#0f172a' }}>登录密码</div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>定期更换密码有助于保护账户安全</div>
              </div>
              <Button size="small" onClick={() => setActiveTab('password')}>修改密码</Button>
            </div>
          </div>
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8 }}>强制改密</div>
            <div style={{ padding: '12px 16px', background: '#f8fafc', borderRadius: 12 }}>
              <div style={{ fontSize: 14, color: '#0f172a' }}>
                当前状态：
                {user?.mustChangePassword ? (
                  <span style={{ color: '#dc2626', fontWeight: 500 }}>需要修改密码</span>
                ) : (
                  <span style={{ color: '#16a34a', fontWeight: 500 }}>正常</span>
                )}
              </div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>管理员可要求你在下次登录时强制修改密码</div>
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'credentials',
      label: '访问凭证',
      forceRender: true,
      children: (
        <>
          <div style={{ marginBottom: 16 }}>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => openCredModal()}
            >
              添加凭证
            </Button>
          </div>
          <Card variant="borderless" style={{ background: '#f8fafc' }}>
            {credentials.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无凭证"
                style={{ padding: '40px 0' }}
              />
            ) : (
              <Table
                columns={credColumns}
                dataSource={credentials}
                rowKey="id"
                pagination={false}
                scroll={{ x: 900 }}
              />
            )}
          </Card>
        </>
      ),
    },
    {
      key: 'notif',
      label: '通知偏好',
      forceRender: true,
      children: (
        <Card variant="borderless" style={{ background: '#f8fafc' }}>
          <p style={{ color: '#64748b', marginBottom: 16 }}>
            个人 webhook 会镜像所有成功写入站内消息中心的通知，下方表格仅控制站内消息与邮件偏好。
          </p>
          <Card variant="outlined" style={{ marginBottom: 16 }}>
            <Form form={webhookForm} layout="vertical">
              <Form.Item
                name="url"
                label="个人 Webhook 地址"
                rules={[
                  {
                    validator(_, value) {
                      if (!value || /^https?:\/\//i.test(String(value).trim())) {
                        return Promise.resolve();
                      }
                      return Promise.reject(new Error('请输入有效的 http/https 地址'));
                    },
                  },
                ]}
              >
                <Input placeholder="https://example.com/bugagent/webhook" />
              </Form.Item>
              <Form.Item
                name="secret"
                label="Webhook Secret（可选）"
                extra={userWebhook.secretConfigured ? '留空则保留当前 Secret' : '可选，用于接收端校验来源'}
              >
                <Input.Password placeholder={userWebhook.secretConfigured ? '留空保留当前 Secret' : '输入 Secret'} />
              </Form.Item>
              <Form.Item name="enabled" label="启用个人 Webhook" valuePropName="checked">
                <Checkbox>启用后，所有站内消息将异步镜像一份到该地址</Checkbox>
              </Form.Item>
              <Space style={{ marginBottom: 8 }}>
                <Button type="primary" onClick={handleSaveUserWebhook} loading={userWebhookSaving}>
                  保存个人Webhook
                </Button>
                <Button onClick={handleTestUserWebhook} loading={userWebhookTesting}>
                  测试发送
                </Button>
              </Space>
            </Form>
          </Card>
          <Table
            dataSource={notifPrefs}
            rowKey="id"
            pagination={false}
            size="middle"
            columns={[
              {
                title: '通知类别',
                dataIndex: 'category',
                width: 180,
                render: (cat: string) => {
                  const labels: Record<string, string> = {
                    defect_assigned: '被指派缺陷',
                    defect_status_change: '缺陷状态变更',
                    defect_mention: '评论中被@提及',
                    defect_due_soon: '缺陷即将到期',
                    iteration_start: '迭代开始',
                    iteration_end: '迭代即将结束',
                    collaboration_complete: '协作任务完成',
                    system_announce: '系统公告',
                  };
                  return <span style={{ fontWeight: 500 }}>{labels[cat] || cat}</span>;
                },
              },
              {
                title: '站内消息',
                width: 100,
                align: 'center' as const,
	                render: (_, record: NotificationPreference) => (
                  <Checkbox
                    checked={record.channels?.includes('in_app')}
                    onChange={(e) => updatePrefChannels(record, 'in_app', e.target.checked)}
                  />
                ),
              },
              {
                title: '邮件',
                width: 80,
                align: 'center' as const,
	                render: (_, record: NotificationPreference) => (
                  <Checkbox
                    checked={record.channels?.includes('email')}
                    onChange={(e) => updatePrefChannels(record, 'email', e.target.checked)}
                  />
                ),
              },
            ]}
          />
        </Card>
      ),
    },
  ];
  const visibleTabItems = restrictToPassword
    ? tabItems.filter((item) => item.key === 'password')
    : tabItems;

  if (loading || !user) {
    return (
      <div style={{ padding: mode === 'page' ? '40px' : '24px 8px', textAlign: 'center' }}>
        加载中...
      </div>
    );
  }

  const content = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
        <Avatar size={80} src={user.avatar || undefined} icon={<UserOutlined />} style={{ marginRight: 16 }} />
        <div>
          <h2 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>{user.nickname || user.username}</h2>
          <div style={{ color: '#64748b', marginTop: 4 }}>
            <MailOutlined style={{ marginRight: 4 }} />
            {user?.email || '未设置'}
          </div>
          <div style={{ marginTop: 12 }}>
            <Upload
              accept=".jpg,.jpeg,.png,.gif,.webp"
              showUploadList={false}
              customRequest={async ({ file }) => {
                await handleAvatarUpload({ file: file as File });
              }}
            >
              <Button icon={<UploadOutlined />} loading={uploadingAvatar}>
                上传头像
              </Button>
            </Upload>
          </div>
        </div>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={visibleTabItems} />

      <Modal
        title={editingCred ? '编辑凭证' : '添加凭证'}
        open={credModalVisible}
        forceRender
        onOk={handleSaveCred}
        onCancel={() => setCredModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={credForm}
          layout="vertical"
          onValuesChange={(changedValues, allValues) => {
            if (Object.prototype.hasOwnProperty.call(changedValues, 'type')) {
              setCredentialType(allValues.type);
            }
            if (Object.prototype.hasOwnProperty.call(changedValues, 'provider')) {
              setCredentialProvider(allValues.provider);
            }
          }}
        >
          <Form.Item name="name" label="凭证名称" rules={[{ required: true, message: '请输入凭证名称' }]}>
            <Input placeholder="如 GitHub Token" />
          </Form.Item>
          <Form.Item name="type" label="凭证类型" rules={[{ required: true, message: '请选择凭证类型' }]}>
            <Select placeholder="选择类型">
              <Select.Option value="pat">Personal Access Token</Select.Option>
              <Select.Option value="oauth">OAuth</Select.Option>
              <Select.Option value="ssh_key">SSH Key</Select.Option>
              <Select.Option value="username_password">用户名密码</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true, message: '请选择提供商' }]}>
            <Select
              placeholder="选择提供商"
              onChange={(provider) => {
                setCredentialProvider(provider);
                if (provider !== 'yunxiao') {
                  credForm.setFieldsValue({
                    organizationId: undefined,
                    workspaceId: undefined,
                    endpoint: undefined,
                  });
                }
              }}
            >
              <Select.Option value="github">GitHub</Select.Option>
              <Select.Option value="gitlab">GitLab</Select.Option>
              <Select.Option value="gitea">Gitea</Select.Option>
              <Select.Option value="yunxiao">云效</Select.Option>
              <Select.Option value="generic">通用</Select.Option>
            </Select>
          </Form.Item>
          {credentialProvider === 'yunxiao' && (
            <>
              <Form.Item name="organizationId" label="组织ID（可选）">
                <Input placeholder="如：your-org-id（建议填写）" />
              </Form.Item>
              <Form.Item name="workspaceId" label="空间ID（可选）">
                <Input placeholder="如：your-workspace-id" />
              </Form.Item>
              <Form.Item name="endpoint" label="API Endpoint（可选）">
                <Input placeholder="默认 https://openapi-rdc.aliyuncs.com" />
              </Form.Item>
            </>
          )}
          {credentialType === 'username_password' ? (
            <>
              <Form.Item
                name="username"
                label="用户名"
                rules={[{ required: true, message: '请输入用户名' }]}
              >
                <Input placeholder="输入用户名" />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[{ required: true, message: '请输入密码' }]}
              >
                <Input.Password placeholder="输入密码（将加密存储）" />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="content" label="凭证内容" rules={[{ required: true, message: '请输入凭证内容' }]}>
              <Input.Password placeholder="输入凭证内容（将加密存储）" />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );

  return (
    mode === 'page' ? (
      <div style={{ maxWidth: 1000, margin: '0 auto', padding: '24px' }}>
        <Card>{content}</Card>
      </div>
    ) : (
      <div style={{ padding: '8px 4px 0' }}>
        {content}
      </div>
    )
  );
};

export default UserCenterContent;
