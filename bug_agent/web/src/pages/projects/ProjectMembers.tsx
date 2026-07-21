import React, { useMemo, useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Space,
  Popconfirm,
  Empty,
  Tag,
  Avatar,
  Select,
  Input,
  Switch,
  Alert,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import {
  PlusOutlined, DeleteOutlined, UserOutlined,
  CrownOutlined, CodeOutlined, BugOutlined, EyeOutlined, CloudDownloadOutlined, ReloadOutlined,
} from '@ant-design/icons';
import {
  addProjectMember,
  removeProjectMember,
  listUsers,
  listCredentials,
  listYunxiaoMembers,
  importYunxiaoMembers,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLayout from '../../components/layout/PageLayout';
import type { ProjectMember, RepoCredential, User } from '../../types';
import { useProject } from '../../contexts/projectContext';
import { isYunxiaoCredential, renderCredentialOptionLabel, parseCredentialExtraConfig } from '../../utils/credential';
import { getAgentTagColor, getAgentShortLabel, normalizeAgentTypes } from '../../utils/agentType';
import { getErrorMessage } from '../../utils/error';
import type { YunxiaoMember } from '../../api';

interface YunxiaoImportItem extends YunxiaoMember {
  reason?: string;
}

interface YunxiaoImportResult {
  summary?: {
    added?: number;
    updated?: number;
    unmatched?: number;
    failed?: number;
  };
  unmatched?: YunxiaoImportItem[];
}

type ProjectRole = keyof typeof roleConfig;
type PreviewStatus = 'add' | 'update' | 'skip' | 'unmatched';
type PreviewColor = 'success' | 'processing' | 'default' | 'warning';

interface MemberPreview {
  label: string;
  color: PreviewColor;
  detail: string;
  status: PreviewStatus;
}

interface AddMemberValues {
  userId: number;
  role: string;
}


const normalizeUsers = (data?: User[] | { items?: User[]; list?: User[] }) =>
  Array.isArray(data) ? data : data?.items || data?.list || [];

const roleConfig: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  project_admin: { label: '项目管理员', color: 'purple', icon: <CrownOutlined /> },
  developer: { label: '开发', color: 'blue', icon: <CodeOutlined /> },
  tester: { label: '测试', color: 'green', icon: <BugOutlined /> },
  viewer: { label: '只读', color: 'default', icon: <EyeOutlined /> },
};

const ProjectMembers: React.FC = () => {
  const { projectId, members, refreshMembers } = useProject();

  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();
  const [importModalVisible, setImportModalVisible] = useState(false);
  const [importing, setImporting] = useState(false);
  const [loadingYunxiaoMembers, setLoadingYunxiaoMembers] = useState(false);
  const [yunxiaoMembers, setYunxiaoMembers] = useState<YunxiaoMember[]>([]);
  const [selectedYunxiaoMemberKeys, setSelectedYunxiaoMemberKeys] = useState<React.Key[]>([]);
  const [importForm] = Form.useForm();
  const updateExisting = Form.useWatch('updateExisting', importForm);
  const [lastImportResult, setLastImportResult] = useState<YunxiaoImportResult | null>(null);

  // 可选用户列表
  const [availableUsers, setAvailableUsers] = useState<User[]>([]);
  const [credentials, setCredentials] = useState<RepoCredential[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);

  const fetchAvailableUsers = useCallback(async () => {
    try {
      const res = await listUsers();
      // 过滤掉已是成员的用户
      const memberUserIds = new Set(members.map((member) => member.userId));
      const users = normalizeUsers(res.data).filter((user) => !memberUserIds.has(user.id));
      setAvailableUsers(users);
    } catch {
      message.error('获取用户列表失败');
    }
  }, [members]);

  useEffect(() => {
    if (modalVisible) {
      void fetchAvailableUsers();
    }
  }, [fetchAvailableUsers, modalVisible]);

  const openModal = () => {
    form.resetFields();
    setModalVisible(true);
  };

  const openImportModal = async () => {
    importForm.resetFields();
    setYunxiaoMembers([]);
    setSelectedYunxiaoMemberKeys([]);
    setLastImportResult(null);
    setImportModalVisible(true);
    try {
      const [credRaw, userRaw] = await Promise.all([
        listCredentials({ projectId }),
        listUsers(),
      ]);
      const credRes = credRaw;
      const userRes = userRaw;
      const list = credRes.data || [];
      setCredentials(list);
      setAllUsers(normalizeUsers(userRes.data));
      const defaultCredential = list.find((c: RepoCredential) => isYunxiaoCredential(c));
      if (defaultCredential) {
        const extra = parseCredentialExtraConfig(defaultCredential?.extraConfig);
        importForm.setFieldsValue({
          credentialId: defaultCredential.id,
          updateExisting: true,
          organizationId: extra.organizationId || undefined,
          endpoint: extra.endpoint || undefined,
        });
      }
    } catch {
      // ignore
    }
  };

  const mapYunxiaoRoleToProjectRole = (raw?: string): ProjectRole => {
    const role = String(raw || '').toLowerCase();
    if (role.includes('admin') || role.includes('owner') || role.includes('管理员') || role.includes('负责人')) {
      return 'project_admin';
    }
    if (role.includes('test') || role.includes('qa') || role.includes('测试')) {
      return 'tester';
    }
    if (role.includes('dev') || role.includes('rd') || role.includes('开发') || role.includes('engineer')) {
      return 'developer';
    }
    return 'viewer';
  };

  const memberPreviewByKey = useMemo(() => {
    const emailMap = new Map<string, User>();
    const usernameMap = new Map<string, User>();
    allUsers.forEach((user) => {
      const email = String(user.email || '').trim().toLowerCase();
      const username = String(user.username || '').trim();
      if (email) emailMap.set(email, user);
      if (username) usernameMap.set(username, user);
    });

    const projectMemberMap = new Map<number, ProjectMember>();
    members.forEach((member) => projectMemberMap.set(member.userId, member));

    const previews: Record<string, MemberPreview> = {};
    yunxiaoMembers.forEach((item) => {
      const key = String(item.externalId || item.email || item.username || item.name || '');
      if (!key) return;

      const targetRole = mapYunxiaoRoleToProjectRole(item.role);
      const email = String(item.email || '').trim().toLowerCase();
      const username = String(item.username || '').trim();
      const user = (email ? emailMap.get(email) : undefined) || (username ? usernameMap.get(username) : undefined);

      if (!user) {
        previews[key] = {
          status: 'unmatched',
          label: '本地未匹配',
          color: 'warning',
          detail: '未匹配到本地用户，导入后会进入未匹配结果',
        };
        return;
      }

      const existed = projectMemberMap.get(user.id);
      if (!existed) {
        previews[key] = {
          status: 'add',
          label: '将新增',
          color: 'success',
          detail: `将新增为 ${roleConfig[targetRole]?.label || targetRole}`,
        };
        return;
      }

      if (Boolean(updateExisting) && existed.role !== targetRole) {
        previews[key] = {
          status: 'update',
          label: '将更新',
          color: 'processing',
          detail: `角色 ${roleConfig[existed.role || 'viewer']?.label || existed.role} -> ${roleConfig[targetRole]?.label || targetRole}`,
        };
        return;
      }

      previews[key] = {
        status: 'skip',
        label: '已存在',
        color: 'default',
        detail: '项目成员已存在，导入后将跳过',
      };
    });
    return previews;
  }, [allUsers, members, updateExisting, yunxiaoMembers]);

  const previewSummary = useMemo(() => {
    const summary = { add: 0, update: 0, skip: 0, unmatched: 0 };
    yunxiaoMembers.forEach((item) => {
      const key = String(item.externalId || item.email || item.username || item.name || '');
      const preview = key ? memberPreviewByKey[key] : undefined;
      if (!preview) return;
      if (preview.status === 'add') summary.add += 1;
      if (preview.status === 'update') summary.update += 1;
      if (preview.status === 'skip') summary.skip += 1;
      if (preview.status === 'unmatched') summary.unmatched += 1;
    });
    return summary;
  }, [memberPreviewByKey, yunxiaoMembers]);

  const handleAddMember = async () => {
    setLoading(true);
    try {
      const values = await form.validateFields() as AddMemberValues;
      await addProjectMember(projectId, {
        userId: values.userId,
        role: values.role,
      });
      message.success('成员已添加');
      setModalVisible(false);
      refreshMembers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '添加失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveMember = async (memberId: number) => {
    setLoading(true);
    try {
      await removeProjectMember(projectId, memberId);
      message.success('成员已移除');
      refreshMembers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '移除失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleFetchYunxiaoMembers = async () => {
    try {
      const values = await importForm.validateFields(['credentialId']);
      setLoadingYunxiaoMembers(true);
      const res = await listYunxiaoMembers({
        credentialId: values.credentialId,
        projectId,
        endpoint: values.endpoint || undefined,
        organizationId: values.organizationId || undefined,
        search: values.search || undefined,
        page: 1,
        size: 100,
      });
      const list = res.data?.items || [];
      setYunxiaoMembers(list);
      setSelectedYunxiaoMemberKeys(list.map((member) => member.externalId || member.email || member.username || member.name));
      message.success(`已拉取 ${list.length} 个云效成员`);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '拉取云效成员失败'));
    } finally {
      setLoadingYunxiaoMembers(false);
    }
  };

  const handleImportYunxiaoMembers = async () => {
    try {
      await importForm.validateFields(['credentialId']);
      const values = importForm.getFieldsValue(['credentialId', 'updateExisting']);
      const selected = yunxiaoMembers.filter((member) =>
        selectedYunxiaoMemberKeys.includes(member.externalId || member.email || member.username || member.name)
      );
      if (selected.length === 0) {
        message.warning('请至少选择一个成员');
        return;
      }
      setImporting(true);
      const res = await importYunxiaoMembers(projectId, {
        credentialId: values.credentialId,
        updateExisting: Boolean(values.updateExisting),
        items: selected.map((member) => ({
          externalId: member.externalId,
          name: member.name,
          username: member.username,
          email: member.email,
          role: member.role,
        })),
      });
      setLastImportResult(res.data || null);
      message.success(`导入完成：新增 ${res.data?.imported || 0} 个成员`);
      setImportModalVisible(false);
      refreshMembers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '导入失败'));
    } finally {
      setImporting(false);
    }
  };

  const exportUnmatchedMembers = () => {
    const unmatched = lastImportResult?.unmatched || [];
    if (!unmatched.length) {
      message.info('暂无未匹配成员可导出');
      return;
    }

    const escapeCSV = (value: unknown) => {
      const text = String(value ?? '');
      return `"${text.replace(/"/g, '""')}"`;
    };

    const lines = [
      ['externalId', 'name', 'email', 'username', 'role', 'reason'].map(escapeCSV).join(','),
      ...unmatched.map((item) => [
        item.externalId || '',
        item.name || '',
        item.email || '',
        item.username || '',
        item.role || '',
        item.reason || '',
      ].map(escapeCSV).join(',')),
    ];

    const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `yunxiao-unmatched-members-${Date.now()}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const getRoleTag = (role: string) => {
    const config = roleConfig[role] || { label: role, color: 'default', icon: null };
    return (
      <Tag color={config.color} icon={config.icon}>
        {config.label}
      </Tag>
    );
  };

  const getAgentTypeTags = (agentTypes?: string | string[]) => {
    const types = normalizeAgentTypes(agentTypes);
    if (types.length === 0) return <span style={{ color: '#cbd5e1' }}>未分配</span>;
    return (
      <Space size={4}>
        {types.map(type => (
          <Tag key={type} color={getAgentTagColor(type)} style={{ fontSize: 11 }}>
            {getAgentShortLabel(type)}
          </Tag>
        ))}
      </Space>
    );
  };

  const columns: TableColumnsType<ProjectMember> = [
    {
      title: 'ID',
      dataIndex: 'memberId',
      key: 'memberId',
      width: 60,
    },
    { 
      title: '成员', 
      key: 'user',
      render: (_, record) => (
        <Space>
          <Avatar 
            style={{ background: 'linear-gradient(135deg, #a855f7, #0ea5e9)' }}
            icon={<UserOutlined />}
          >
            {record.nickname?.[0] || record.username?.[0] || 'U'}
          </Avatar>
          <div>
            <div style={{ fontWeight: 500 }}>
              {record.nickname || record.username}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8' }}>
              @{record.username}
            </div>
          </div>
        </Space>
      ),
    },
    { 
      title: '角色', 
      dataIndex: 'role', 
      key: 'role',
      width: 100,
      render: (role?: string) => getRoleTag(role || 'viewer'),
    },
    { 
      title: 'AGENT身份', 
      dataIndex: 'agentTypes', 
      key: 'agentTypes',
      render: (agentTypes?: string) => getAgentTypeTags(agentTypes || ''),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Popconfirm 
          title="确定移除此成员？" 
          onConfirm={() => handleRemoveMember(record.memberId)}
        >
          <Button type="link" danger icon={<DeleteOutlined />}>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const adminCount = members.filter((member) => member.role === 'project_admin').length;
  const developerCount = members.filter((member) => member.role === 'developer').length;
  const testerCount = members.filter((member) => member.role === 'tester').length;
  const viewerCount = members.filter((member) => member.role === 'viewer').length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'admin', label: '项目管理员', value: adminCount, icon: <CrownOutlined />, tone: 'purple' },
          { key: 'developer', label: '开发成员', value: developerCount, icon: <CodeOutlined />, tone: 'cyan' },
          { key: 'tester', label: '测试成员', value: testerCount, icon: <BugOutlined />, tone: 'green' },
          { key: 'viewer', label: '只读成员', value: viewerCount, icon: <EyeOutlined />, tone: 'amber' },
        ]}
        actions={(
          <Space wrap>
            <Button
              type="primary"
              className="brand-button"
              icon={<PlusOutlined />}
              onClick={openModal}
            >
              添加成员
            </Button>
            <Button icon={<CloudDownloadOutlined />} onClick={openImportModal}>
              从云效导入
            </Button>
          </Space>
        )}
      />

      {/* 成员列表 */}
      <Card className="scene-card">
        {(!members || members.length === 0) && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无成员"
            style={{ padding: '40px 0' }}
          >
            <Button type="primary" onClick={openModal}>
              添加第一个成员
            </Button>
          </Empty>
        ) : (
          <Table 
            columns={columns} 
            dataSource={members} 
            rowKey="memberId" 
            loading={loading}
            pagination={false}
          />
        )}
      </Card>

      {/* 添加成员弹窗 */}
      <Modal
        title="添加成员"
        open={modalVisible}
        onOk={handleAddMember}
        onCancel={() => setModalVisible(false)}
        okText="添加"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="userId" label="选择用户" rules={[{ required: true, message: '请选择用户' }]}>
            <Select 
              placeholder="搜索用户"
              showSearch
              optionFilterProp="children"
              filterOption={(input, option) =>
                String(option?.children)?.toLowerCase().includes(input.toLowerCase())
              }
            >
              {availableUsers.map(user => (
                <Select.Option key={user.id} value={user.id}>
                  {user.nickname || user.username} (@{user.username})
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="role" label="角色" initialValue="developer" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="project_admin">
                <Space>
                  <CrownOutlined style={{ color: '#a855f7' }} />
                  项目管理员
                </Space>
              </Select.Option>
              <Select.Option value="developer">
                <Space>
                  <CodeOutlined style={{ color: '#3b82f6' }} />
                  开发人员
                </Space>
              </Select.Option>
              <Select.Option value="tester">
                <Space>
                  <BugOutlined style={{ color: '#22c55e' }} />
                  测试人员
                </Space>
              </Select.Option>
              <Select.Option value="viewer">
                <Space>
                  <EyeOutlined style={{ color: '#94a3b8' }} />
                  只读
                </Space>
              </Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* 云效成员导入 */}
      <Modal
        title="从云效导入成员"
        open={importModalVisible}
        onOk={handleImportYunxiaoMembers}
        onCancel={() => setImportModalVisible(false)}
        okText="导入选中成员"
        cancelText="取消"
        confirmLoading={importing}
        width={900}
      >
        <Form form={importForm} layout="vertical">
          <Space style={{ width: '100%' }} direction="vertical" size={8}>
            <Space style={{ width: '100%' }} align="start">
              <Form.Item
                name="credentialId"
                label="云效凭证"
                rules={[{ required: true, message: '请选择凭证' }]}
                style={{ minWidth: 260 }}
              >
                <Select
                  placeholder="选择云效凭证"
                  onChange={(credentialId: number) => {
                    const selected = credentials.find((c) => c.id === credentialId);
                    const extra = parseCredentialExtraConfig(selected?.extraConfig);
                    importForm.setFieldsValue({
                      organizationId: extra.organizationId || undefined,
                      endpoint: extra.endpoint || undefined,
                    });
                  }}
                  options={credentials
                    .filter((c) => isYunxiaoCredential(c))
                    .map((c) => ({
                      value: c.id,
                      label: renderCredentialOptionLabel(c),
                    }))}
                />
              </Form.Item>
              <Form.Item name="organizationId" label="组织ID（可选）" style={{ minWidth: 220 }}>
                <Input placeholder="可留空（从凭证内容读取）" />
              </Form.Item>
              <Form.Item name="endpoint" label="API Endpoint（可选）" style={{ minWidth: 260 }}>
                <Input placeholder="默认 https://openapi-rdc.aliyuncs.com" />
              </Form.Item>
            </Space>
            <Space style={{ width: '100%' }} align="end">
              <Form.Item name="search" label="成员搜索（可选）" style={{ flex: 1 }}>
                <Input placeholder="按姓名/邮箱/用户名过滤" />
              </Form.Item>
              <Form.Item
                name="updateExisting"
                label="更新已有成员角色"
                valuePropName="checked"
                initialValue={true}
              >
                <Switch />
              </Form.Item>
              <Form.Item label=" ">
                <Button
                  icon={<ReloadOutlined />}
                  loading={loadingYunxiaoMembers}
                  onClick={handleFetchYunxiaoMembers}
                >
                  拉取成员
                </Button>
              </Form.Item>
            </Space>
          </Space>
        </Form>
        {yunxiaoMembers.length > 0 && (
          <Alert
            style={{ marginBottom: 12 }}
            type={previewSummary.unmatched > 0 ? 'warning' : 'info'}
            showIcon
            title={`预估：新增 ${previewSummary.add}，更新 ${previewSummary.update}，已存在 ${previewSummary.skip}，未匹配 ${previewSummary.unmatched}`}
          />
        )}
        {Boolean(lastImportResult?.unmatched?.length) && (
          <Alert
            style={{ marginBottom: 12 }}
            type="warning"
            showIcon
            title={`导入结果：未匹配 ${lastImportResult?.unmatched?.length || 0} 人`}
            action={(
              <Button size="small" onClick={exportUnmatchedMembers}>
                导出未匹配成员
              </Button>
            )}
          />
        )}
	        <Table<YunxiaoMember>
	          rowKey={(record) => record.externalId || record.email || record.username || record.name}
          dataSource={yunxiaoMembers}
          loading={loadingYunxiaoMembers}
          size="small"
          pagination={{ pageSize: 8 }}
          rowSelection={{
            selectedRowKeys: selectedYunxiaoMemberKeys,
            onChange: (keys) => setSelectedYunxiaoMemberKeys(keys),
          }}
          columns={[
            { title: '姓名', dataIndex: 'name', key: 'name', width: 180 },
            { title: '邮箱', dataIndex: 'email', key: 'email', width: 240, render: (v: string) => v || '-' },
            { title: '用户名', dataIndex: 'username', key: 'username', width: 180, render: (v: string) => v || '-' },
            { title: '角色', dataIndex: 'role', key: 'role', width: 120, render: (v: string) => v || '-' },
            {
              title: '预估结果',
              key: 'preview',
              width: 260,
	              render: (_, record) => {
	                const key = String(record.externalId || record.email || record.username || record.name || '');
	                const preview = memberPreviewByKey[key];
	                if (!preview) return '-';
	                return (
	                  <div style={{ display: 'grid', gap: 2 }}>
	                    <Tag color={preview.color} style={{ width: 'fit-content', marginRight: 0 }}>
	                      {preview.label}
	                    </Tag>
                    <span style={{ color: '#64748b', fontSize: 12 }}>{preview.detail}</span>
                  </div>
                );
              },
            },
          ]}
        />
      </Modal>
    </PageLayout>
  );
};

export default ProjectMembers;
