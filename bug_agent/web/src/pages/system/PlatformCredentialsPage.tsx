import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
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
import { EditOutlined, KeyOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { message } from '../../utils/appMessage';
import {
  createPlatformCredential,
  deletePlatformCredential,
  listPlatformCredentials,
  listProjects,
  updatePlatformCredential,
} from '../../api';
import type { Project, RepoCredential } from '../../types';
import { credentialScopeLabel } from '../../utils/credential';
import PageLayout from '../../components/layout/PageLayout';
import PageContent from '../../components/layout/PageContent';
import PageMetricSection from '../../components/layout/PageMetricSection';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

const PROVIDER_OPTIONS = [
  { value: 'github', label: 'GitHub' },
  { value: 'gitlab', label: 'GitLab' },
  { value: 'gitea', label: 'Gitea' },
  { value: 'yunxiao', label: '云效' },
  { value: 'generic', label: '通用/自定义' },
];

const TYPE_OPTIONS = [
  { value: 'pat', label: 'Token / PAT' },
  { value: 'username_password', label: '用户名 + 密码' },
  { value: 'oauth', label: 'OAuth 令牌' },
  { value: 'ssh_key', label: 'SSH Key' },
];

const STATUS_OPTIONS = [
  { value: 'active', label: '启用' },
  { value: 'inactive', label: '停用' },
];

interface FormValues {
  name: string;
  provider: string;
  type: string;
  status: 'active' | 'inactive';
  tokenContent?: string;
  username?: string;
  password?: string;
  extraConfig?: string;
  allowedProjectIds: number[];
}



const PlatformCredentialsPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [credentials, setCredentials] = useState<RepoCredential[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [editing, setEditing] = useState<RepoCredential | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [credentialType, setCredentialType] = useState<'pat' | 'username_password' | 'oauth' | 'ssh_key'>('pat');
  const [credentialProvider, setCredentialProvider] = useState('github');
  const [form] = Form.useForm<FormValues>();


  const projectMap = useMemo(() => {
    return projects.reduce<Record<number, Project>>((acc, project) => {
      acc[project.id] = project;
      return acc;
    }, {});
  }, [projects]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [credentialRes, projectRes] = await Promise.all([
        listPlatformCredentials(),
        listProjects(),
      ]);
      setCredentials(credentialRes.data || []);
      setProjects(projectRes.data?.items || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取平台凭证失败'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const YUNXIAO_EXTRA_CONFIG_TEMPLATE = '{"organizationId":"","endpoint":"https://openapi-rdc.aliyuncs.com"}';

  const handleProviderChange = (provider: string) => {
    setCredentialProvider(provider);
    if (provider === 'yunxiao') {
      const current = form.getFieldValue('extraConfig');
      if (!current || !current.trim()) {
        form.setFieldsValue({ extraConfig: YUNXIAO_EXTRA_CONFIG_TEMPLATE });
      }
    }
  };

  const openModal = (credential?: RepoCredential) => {
    setEditing(credential || null);
    if (credential) {
      setCredentialType((credential.type as 'pat' | 'username_password') || 'pat');
      setCredentialProvider(credential.provider || 'github');
      form.setFieldsValue({
        name: credential.name,
        provider: credential.provider,
        type: credential.type,
        status: credential.status || 'active',
        extraConfig: credential.extraConfig || '',
        allowedProjectIds: credential.allowedProjectIds || [],
        tokenContent: '',
        username: '',
        password: '',
      });
    } else {
      form.resetFields();
      setCredentialType('pat');
      setCredentialProvider('github');
      form.setFieldsValue({
        provider: 'github',
        type: 'pat',
        status: 'active',
        allowedProjectIds: [],
      });
    }
    setModalVisible(true);
  };

  const buildCredentialContent = (values: FormValues) => {
    if (values.type === 'username_password') {
      const username = String(values.username || '').trim();
      const password = String(values.password || '');
      if (!editing && (!username || !password)) {
        throw new Error('请输入用户名和密码');
      }
      if (editing && !username && !password) {
        return '';
      }
      if (!username || !password) {
        throw new Error('用户名和密码需要同时填写');
      }
      return JSON.stringify({ username, password });
    }

    const token = String(values.tokenContent || '').trim();
    if (!editing && !token) {
      throw new Error('请输入凭证内容');
    }
    return token;
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const content = buildCredentialContent(values);
      setSaving(true);

      const payload = {
        name: values.name.trim(),
        provider: values.provider,
        type: values.type,
        status: values.status,
        content,
        extraConfig: values.extraConfig?.trim() || '',
        allowedProjectIds: values.allowedProjectIds || [],
      };

      if (editing) {
        await updatePlatformCredential(editing.id, payload);
        message.success('平台凭证已更新');
      } else {
        await createPlatformCredential(payload);
        message.success('平台凭证已创建');
      }
      setModalVisible(false);
      void fetchData();
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) {
        return;
      }
      message.error(getErrorMessage(error, '保存平台凭证失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (credential: RepoCredential) => {
    try {
      await deletePlatformCredential(credential.id);
      message.success('平台凭证已删除');
      void fetchData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除平台凭证失败'));
    }
  };

  const activeCredentialCount = credentials.filter((credential) => credential.status === 'active').length;
  const authorizedProjectCount = new Set(credentials.flatMap((credential) => credential.allowedProjectIds || [])).size;

  return (
    <PageLayout>
      <PageContent>

      <PageMetricSection
        items={[
          { key: 'credentials', label: '凭证总数', value: credentials.length, icon: <KeyOutlined />, tone: 'purple' },
          { key: 'active', label: '启用中', value: activeCredentialCount, icon: <ReloadOutlined />, tone: 'green' },
          { key: 'projects', label: '授权项目', value: authorizedProjectCount, icon: <PlusOutlined />, tone: 'cyan' },
          { key: 'providers', label: '提供商', value: new Set(credentials.map((credential) => credential.provider)).size, icon: <EditOutlined />, tone: 'amber' },
        ]}
        actions={(
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={fetchData}>
              刷新
            </Button>
            <Button type="primary" className="brand-button" icon={<PlusOutlined />} onClick={() => openModal()}>
              新增平台凭证
            </Button>
          </Space>
        )}
      />

      <Card className="scene-card">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={credentials}
          pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            {
              title: '凭证名称',
              dataIndex: 'name',
              width: 220,
              render: (value: string) => (
                <Space size={8}>
                  <KeyOutlined style={{ color: '#1677ff' }} />
                  <span style={{ fontWeight: 600 }}>{value}</span>
                </Space>
              ),
            },
            {
              title: '来源',
              dataIndex: 'scope',
              width: 100,
              render: (value: string) => <Tag color="gold">{credentialScopeLabel(value)}</Tag>,
            },
            {
              title: '提供商',
              dataIndex: 'provider',
              width: 120,
              render: (value: string) => String(value || '').toUpperCase(),
            },
            { title: '类型', dataIndex: 'type', width: 160 },
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
              title: '授权项目',
              dataIndex: 'allowedProjectIds',
              render: (projectIDs?: number[]) => {
                if (!projectIDs?.length) {
                  return <span style={{ color: '#94a3b8' }}>未授权项目</span>;
                }
                return (
                  <Space size={[4, 4]} wrap>
                    {projectIDs.map((projectID) => (
                      <Tag key={projectID} style={{ marginRight: 0 }}>
                        {projectMap[projectID]?.name || `项目#${projectID}`}
                      </Tag>
                    ))}
                  </Space>
                );
              },
            },
            {
              title: '掩码',
              dataIndex: 'maskedValue',
              width: 180,
              render: (value: string) => value || <span style={{ color: '#94a3b8' }}>-</span>,
            },
            {
              title: '操作',
              key: 'action',
              width: 160,
              render: (_: unknown, record: RepoCredential) => (
                <Space>
                  <Button type="link" icon={<EditOutlined />} onClick={() => openModal(record)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="删除该平台凭证？"
                    description="已绑定仓库的项目将立即失去访问能力。"
                    onConfirm={() => handleDelete(record)}
                  >
                    <Button type="link" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editing ? '编辑平台凭证' : '新增平台凭证'}
        open={modalVisible}
        forceRender
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={760}
      >
        <Form<FormValues> form={form} layout="vertical">
          <Space style={{ width: '100%' }} align="start">
            <Form.Item
              name="name"
              label="凭证名称"
              rules={[{ required: true, message: '请输入凭证名称' }]}
              style={{ flex: 1 }}
            >
              <Input placeholder="例如：平台 GitHub 生产凭证" />
            </Form.Item>
            <Form.Item name="provider" label="提供商" rules={[{ required: true }]} style={{ width: 180 }}>
              <Select options={PROVIDER_OPTIONS} onChange={handleProviderChange} />
            </Form.Item>
            <Form.Item name="status" label="状态" rules={[{ required: true }]} style={{ width: 140 }}>
              <Select options={STATUS_OPTIONS} />
            </Form.Item>
          </Space>

          <Space style={{ width: '100%' }} align="start">
            <Form.Item name="type" label="凭证类型" rules={[{ required: true }]} style={{ width: 220 }}>
              <Select
                options={TYPE_OPTIONS}
                onChange={(value) => setCredentialType(value as 'pat' | 'username_password' | 'oauth' | 'ssh_key')}
              />
            </Form.Item>
            <Form.Item
              name="allowedProjectIds"
              label="允许使用的项目"
              rules={[{ required: true, message: '请至少选择一个项目' }]}
              style={{ flex: 1 }}
            >
              <Select
                mode="multiple"
                placeholder="选择可使用该平台凭证的项目"
                optionFilterProp="label"
                options={projects.map((project) => ({
                  value: project.id,
                  label: `${project.name} (${project.code})`,
                }))}
              />
            </Form.Item>
          </Space>

          {credentialType === 'username_password' ? (
            <Space style={{ width: '100%' }} align="start">
              <Form.Item name="username" label="用户名" style={{ flex: 1 }}>
                <Input placeholder={editing ? '留空表示不修改' : '输入用户名'} />
              </Form.Item>
              <Form.Item name="password" label="密码" style={{ flex: 1 }}>
                <Input.Password placeholder={editing ? '留空表示不修改' : '输入密码'} />
              </Form.Item>
            </Space>
          ) : credentialType === 'ssh_key' ? (
            <Form.Item
              name="tokenContent"
              label={editing ? 'SSH 私钥（留空表示不修改）' : 'SSH 私钥'}
            >
              <Input.TextArea
                rows={4}
                placeholder={editing ? '留空表示不修改' : '-----BEGIN OPENSSH PRIVATE KEY-----\n...'}
              />
            </Form.Item>
          ) : credentialType === 'oauth' ? (
            <Form.Item
              name="tokenContent"
              label={editing ? 'OAuth 令牌（留空表示不修改）' : 'OAuth 令牌'}
            >
              <Input.Password
                placeholder={editing ? '留空表示不修改' : '输入 OAuth access token'}
              />
            </Form.Item>
          ) : (
            <Form.Item
              name="tokenContent"
              label={editing ? '凭证内容（留空表示不修改）' : '凭证内容'}
            >
              <Input.Password
                placeholder={editing ? '留空表示不修改' : '输入 token / PAT / access token'}
              />
            </Form.Item>
          )}

          <Form.Item name="extraConfig" label="扩展配置 JSON（可选）" extra={credentialProvider === 'yunxiao' ? '请填写 organizationId（组织ID），endpoint 已预填云效默认地址' : undefined}>
            <Input.TextArea
              rows={4}
              placeholder={credentialProvider === 'yunxiao' ? '' : '例如：{"key":"value"}'}
            />
          </Form.Item>
        </Form>
      </Modal>
      </PageContent>
    </PageLayout>
  );
};

export default PlatformCredentialsPage;
