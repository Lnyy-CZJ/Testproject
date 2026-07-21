import React, { useCallback, useEffect, useState } from 'react';
import { Table, Card, Input, Select, Button, Modal, Form, Checkbox, Tag, Space, Typography, InputNumber, DatePicker, App as AntApp } from 'antd';
import type { TableColumnsType } from 'antd';
import type { Dayjs } from 'dayjs';
import { message } from '../../utils/appMessage';
import { EditOutlined, PlusOutlined, LinkOutlined, CopyOutlined, KeyOutlined, TeamOutlined, SafetyCertificateOutlined, UserOutlined, RobotOutlined, SearchOutlined } from '@ant-design/icons';
import {
  listUsers,
  updateUserAgentTypes,
  createUser,
  listProjects,
  updateUserPlatformRole,
  resetUserPassword,
  createInvite,
  listInvites,
  listRoles,
} from '../../api';
import { AGENT_TYPES } from '../../types';
import { getAgentTagColor, getAgentFullLabel, normalizeAgentTypes } from '../../utils/agentType';
import type { Project, User } from '../../types';
import PageLayout from '../../components/layout/PageLayout';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageFilterBar from '../../components/layout/PageFilterBar';
import { getErrorMessage } from '../../utils/error';
import { formatDateTime } from '../../utils/formatDate';

interface InviteRecord {
  id: number;
  code: string;
  usedCount?: number;
  maxUses?: number;
  expiresAt?: string;
  createdAt?: string;
}



interface CreateInviteValues {
  maxUses?: number | null;
  expiresAt?: Dayjs;
}

interface CreateUserValues {
  username: string;
  email: string;
  password?: string;
  nickname?: string;
  platformRole?: 'super_admin' | 'admin' | 'member';
  projectIds?: number[];
  projectRole?: 'project_admin' | 'developer' | 'tester' | 'viewer';
}

interface RoleOption {
  id: number;
  name: string;
  displayName: string;
  tier: string;
}


const UserManagement: React.FC = () => {
  const { modal } = AntApp.useApp();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [agentTypeFilter, setAgentTypeFilter] = useState<string>('');
  const [projectFilter, setProjectFilter] = useState<number | undefined>();
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [roleModalVisible, setRoleModalVisible] = useState(false);
  const [inviteModalVisible, setInviteModalVisible] = useState(false);
  const [invites, setInvites] = useState<InviteRecord[]>([]);
  const [loadingInvites, setLoadingInvites] = useState(false);
  const [creatingInvite, setCreatingInvite] = useState(false);
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [assignableProjects, setAssignableProjects] = useState<Project[]>([]);
  const [platformRoles, setPlatformRoles] = useState<RoleOption[]>([]);
  const [projectRoles, setProjectRoles] = useState<RoleOption[]>([]);
  const [form] = Form.useForm();
  const [createForm] = Form.useForm();
  const [roleForm] = Form.useForm();
  const [inviteForm] = Form.useForm();

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const params: { page: number; size: number; keyword?: string; agentType?: string; projectId?: number } = { page, size };
      if (keyword) params.keyword = keyword;
      if (agentTypeFilter) params.agentType = agentTypeFilter;
      if (projectFilter) params.projectId = projectFilter;
      const res = await listUsers(params);
      setUsers(res.data?.items || []);
      setTotal(res.data?.total || 0);
    } catch {
      message.error('获取用户列表失败');
    } finally {
      setLoading(false);
    }
  }, [agentTypeFilter, keyword, page, projectFilter, size]);

  useEffect(() => {
    void fetchUsers();
  }, [fetchUsers]);

  const fetchAssignableProjects = useCallback(async () => {
    try {
      const res = await listProjects({ page: 1, pageSize: 200, all: true });
      setAssignableProjects(res.data?.items || []);
    } catch {
      // ignore
    }
  }, []);

  const fetchRoles = useCallback(async () => {
    try {
      const [platformRes, projectRes] = await Promise.all([
        listRoles({ tier: 'platform' }),
        listRoles({ tier: 'project' }),
      ]);
      setPlatformRoles(platformRes.data || []);
      setProjectRoles(projectRes.data || []);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void fetchAssignableProjects();
  }, [fetchAssignableProjects]);

  useEffect(() => {
    void fetchRoles();
  }, [fetchRoles]);

  const fetchInvites = useCallback(async () => {
    setLoadingInvites(true);
    try {
      const res = await listInvites();
      setInvites(res.data || []);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '获取邀请码列表失败'));
    } finally {
      setLoadingInvites(false);
    }
  }, []);

  const handleSearch = () => {
    setPage(1);
    fetchUsers();
  };

  const openEditModal = (user: User) => {
    setCurrentUser(user);
    const agentTypes = Array.isArray(user.agentTypes) ? user.agentTypes : (user.agentTypes ? (user.agentTypes as string).split(',').map((t: string) => t.trim()).filter(Boolean) : []);
    form.setFieldsValue({ agentTypes });
    setEditModalVisible(true);
  };

  const openRoleModal = (user: User) => {
    setCurrentUser(user);
    roleForm.setFieldsValue({ platformRole: user.platformRole || 'member' });
    setRoleModalVisible(true);
  };

  const handleSaveAgentTypes = async () => {
    if (!currentUser) return;
    try {
      const values = await form.validateFields();
      await updateUserAgentTypes(currentUser.id, { agentTypes: values.agentTypes });
      message.success('AGENT身份已更新');
      setEditModalVisible(false);
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '更新失败'));
    }
  };

  const handleCreateUser = async () => {
    try {
      const values = await createForm.validateFields() as CreateUserValues;
      const res = await createUser(values);
      message.success('用户创建成功');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchUsers();

      const tempPassword = res.data?.temporaryPassword;
      if (tempPassword) {
        modal.info({
          title: '系统已自动生成初始密码',
          content: (
            <div>
              <Typography.Paragraph style={{ marginBottom: 8 }}>
                请将以下密码通过安全渠道发送给用户：
              </Typography.Paragraph>
              <Typography.Paragraph copyable={{ text: tempPassword }} style={{ marginBottom: 0 }}>
                <code>{tempPassword}</code>
              </Typography.Paragraph>
            </div>
          ),
          okText: '知道了',
        });
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '创建失败'));
    }
  };

  const handleSavePlatformRole = async () => {
    if (!currentUser) return;
    try {
      const values = await roleForm.validateFields();
      await updateUserPlatformRole(currentUser.id, values);
      message.success('平台角色已更新');
      setRoleModalVisible(false);
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '更新失败'));
    }
  };

  const handleResetPassword = async (user: User) => {
    if (resettingUserId === user.id) {
      return;
    }
    try {
      setResettingUserId(user.id);
      const res = await resetUserPassword(user.id);
      const tempPassword = res.data?.temporaryPassword;
      message.success('密码已重置');
      modal.info({
        title: `已为 ${user.username} 重置密码`,
        content: (
          <div>
            <Typography.Paragraph style={{ marginBottom: 8 }}>
              请将以下临时密码通过安全渠道发送给用户。用户下次登录后将被强制修改密码。
            </Typography.Paragraph>
            <Typography.Paragraph copyable={{ text: tempPassword }} style={{ marginBottom: 0 }}>
              <code>{tempPassword}</code>
            </Typography.Paragraph>
          </div>
        ),
        okText: '知道了',
      });
      fetchUsers();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '重置密码失败'));
    } finally {
      setResettingUserId(null);
    }
  };

  const openInviteModal = async () => {
    inviteForm.resetFields();
    setInviteModalVisible(true);
    await fetchInvites();
  };

  const handleCreateInvite = async () => {
    try {
      const values = await inviteForm.validateFields() as CreateInviteValues;
      const payload: { maxUses?: number; expiresAt?: string } = {};
      if (values.maxUses !== undefined && values.maxUses !== null) {
        payload.maxUses = Number(values.maxUses);
      }
      if (values.expiresAt) {
        payload.expiresAt = values.expiresAt.toDate().toISOString();
      }

      setCreatingInvite(true);
      await createInvite(payload);
      message.success('邀请码已生成');
      inviteForm.resetFields();
      await fetchInvites();
    } catch (error: unknown) {
      if (typeof error === 'object' && error !== null && 'errorFields' in error) {
        return;
      }
      message.error(getErrorMessage(error, '生成邀请码失败'));
    } finally {
      setCreatingInvite(false);
    }
  };

  const inviteColumns: TableColumnsType<InviteRecord> = [
    {
      title: '邀请码',
      dataIndex: 'code',
      key: 'code',
      width: 300,
      render: (code: string) => (
        <Typography.Paragraph style={{ marginBottom: 0 }} copyable={{ text: code, icon: <CopyOutlined /> }}>
          <code>{code}</code>
        </Typography.Paragraph>
      ),
    },
    {
      title: '邀请链接',
      key: 'link',
      render: (_, record) => {
        const link = `${window.location.origin}/register?invite=${record.code}`;
        return (
          <Typography.Paragraph style={{ marginBottom: 0 }} copyable={{ text: link }}>
            <span style={{ color: '#64748b' }}>
              <LinkOutlined style={{ marginRight: 6 }} />
              复制注册链接
            </span>
          </Typography.Paragraph>
        );
      },
    },
    {
      title: '已用/上限',
      key: 'usage',
      width: 120,
      render: (_, record) => (
        <span>{record.usedCount || 0}/{record.maxUses === 0 ? '∞' : record.maxUses}</span>
      ),
    },
    {
      title: '过期时间',
      dataIndex: 'expiresAt',
      key: 'expiresAt',
      width: 180,
      render: (v: string) => (v ? formatDateTime(v, '永不过期') : '永不过期'),
    },
    {
      title: '创建时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 180,
      render: (v: string) => formatDateTime(v),
    },
  ];

  const getAgentTags = (agentTypes: string | string[]) => {
    const types = normalizeAgentTypes(agentTypes);
    if (types.length === 0) return [];
    return types.map((t: string) => ({
      key: t,
      label: getAgentFullLabel(t),
      color: getAgentTagColor(t),
    }));
  };

  const getPlatformRoleTag = (role?: string) => {
    const roleText = role || 'member';
    const match = platformRoles.find((r) => r.name === roleText);
    const colorMap: Record<string, string> = {
      super_admin: 'red',
      admin: 'blue',
      member: 'default',
    };
    return <Tag color={colorMap[roleText] || 'geekblue'}>{match?.displayName || roleText}</Tag>;
  };

  const columns: TableColumnsType<User> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
      width: 120,
    },
    {
      title: '昵称',
      dataIndex: 'nickname',
      key: 'nickname',
      width: 120,
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      width: 200,
    },
    {
      title: '平台角色',
      dataIndex: 'platformRole',
      key: 'platformRole',
      width: 120,
      render: (role: string) => getPlatformRoleTag(role),
    },
    {
      title: '最近登录时间',
      dataIndex: 'lastLoginAt',
      key: 'lastLoginAt',
      width: 180,
      render: (text?: string) => formatDateTime(text, '未登录'),
    },
    {
      title: 'AGENT身份',
      dataIndex: 'agentTypes',
      key: 'agentTypes',
      render: (text: string) => (
        <Space size={[0, 4]} wrap>
          {getAgentTags(text).map((tag) => (
            <Tag key={tag.key} color={tag.color}>
              {tag.label}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '注册时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 180,
      render: (text: string) => formatDateTime(text),
    },
    {
      title: '操作',
      key: 'action',
      width: 320,
      render: (_, record) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openEditModal(record)}>
            编辑AGENT身份
          </Button>
          <Button type="link" onClick={() => openRoleModal(record)}>
            平台角色
          </Button>
          <Button
            type="link"
            icon={<KeyOutlined />}
            onClick={() => handleResetPassword(record)}
            loading={resettingUserId === record.id}
            disabled={resettingUserId === record.id}
          >
            重置密码
          </Button>
        </Space>
      ),
    },
  ];

  const superAdminCount = users.filter((item) => item.platformRole === 'super_admin').length;
  const adminCount = users.filter((item) => item.platformRole === 'admin').length;
  const memberCount = users.filter((item) => !item.platformRole || item.platformRole === 'member').length;
  const agentEnabledCount = users.filter((item) => {
    if (!item.agentTypes) return false;
    if (Array.isArray(item.agentTypes)) return item.agentTypes.length > 0;
    return Boolean((item.agentTypes as string).trim());
  }).length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '用户总数', value: total || users.length, icon: <TeamOutlined />, tone: 'purple' },
          { key: 'super-admin', label: '超级管理员', value: superAdminCount, icon: <SafetyCertificateOutlined />, tone: 'rose' },
          { key: 'admin', label: '管理员', value: adminCount, icon: <UserOutlined />, tone: 'cyan' },
          { key: 'agent', label: '已配置AGENT', value: agentEnabledCount, icon: <RobotOutlined />, tone: 'green' },
          { key: 'member', label: '成员', value: memberCount, icon: <UserOutlined />, tone: 'amber' },
        ]}
      />

      <Card
        title="用户管理"
        extra={
          <Space>
            <Button icon={<LinkOutlined />} onClick={openInviteModal}>邀请码</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>创建用户</Button>
          </Space>
        }
      >
        <PageFilterBar
          compact
          testId="user-management-filter-rail"
          filters={(
            <>
              <Input
                placeholder="搜索用户名/昵称/邮箱"
                prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={handleSearch}
                style={{ width: '100%', maxWidth: 340 }}
                allowClear
              />
              <Select
                placeholder="按AGENT类型筛选"
                value={agentTypeFilter}
                onChange={(val) => {
                  setAgentTypeFilter(val);
                  setPage(1);
                }}
                allowClear
                style={{ width: 220 }}
                options={AGENT_TYPES.map((agent) => ({
                  value: agent.key,
                  label: agent.label,
                }))}
              />
              <Select
                aria-label="按项目归属筛选"
                placeholder="按项目归属筛选"
                value={projectFilter}
                onChange={(val) => {
                  setProjectFilter(val);
                  setPage(1);
                }}
                allowClear
                style={{ width: 240 }}
                options={assignableProjects.map((project) => ({
                  value: project.id,
                  label: `${project.name} (${project.code})`,
                }))}
              />
              <Button onClick={handleSearch}>刷新</Button>
            </>
          )}
          result={<span>共 {total} 条</span>}
        />

        <Table
          columns={columns}
          dataSource={users}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize: size,
            total,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (p, s) => {
              setPage(p);
              setSize(s);
            },
          }}
        />
      </Card>

      <Modal
        title={`编辑AGENT身份 — ${currentUser?.username}`}
        open={editModalVisible}
        onOk={handleSaveAgentTypes}
        onCancel={() => setEditModalVisible(false)}
        width={500}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="agentTypes" label="选择AGENT身份" rules={[{ required: true, message: '至少选择一个' }]}>
            <Checkbox.Group style={{ width: '100%' }}>
              {AGENT_TYPES.map((agent) => (
                <div key={agent.key} style={{ marginBottom: 12 }}>
                  <Checkbox value={agent.key}>
                    <Tag color={getAgentTagColor(agent.key)}>{agent.label}</Tag>
                  </Checkbox>
                  <div style={{ marginLeft: 24, color: '#888', fontSize: 12 }}>{agent.desc}</div>
                </div>
              ))}
            </Checkbox.Group>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑平台角色 — ${currentUser?.username}`}
        open={roleModalVisible}
        onOk={handleSavePlatformRole}
        onCancel={() => setRoleModalVisible(false)}
        width={420}
      >
        <Form form={roleForm} layout="vertical">
          <Form.Item name="platformRole" label="平台角色" rules={[{ required: true, message: '请选择平台角色' }]}>
            <Select
              options={platformRoles.map((r) => ({
                value: r.name,
                label: r.displayName,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="创建新用户"
        open={createModalVisible}
        onOk={handleCreateUser}
        onCancel={() => { setCreateModalVisible(false); createForm.resetFields(); }}
        okText="创建"
        cancelText="取消"
        width={500}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="2-50个字符" />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input placeholder="user@example.com" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码（可选）"
            tooltip="留空时系统将自动生成安全随机密码（长度至少8位）"
            rules={[{
              validator: async (_rule, value) => {
                if (!value) return;
                if (value.length < 8) throw new Error('手动输入密码需至少8位，或留空自动生成');
              },
            }]}
          >
            <Input.Password placeholder="可留空自动生成；手动输入需至少8位" />
          </Form.Item>
          <Form.Item name="nickname" label="昵称">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="platformRole" label="平台角色" initialValue="member">
            <Select
              options={platformRoles.map((r) => ({
                value: r.name,
                label: r.displayName,
              }))}
            />
          </Form.Item>
          <Form.Item name="projectIds" label="分配项目（可选）">
            <Select
              mode="multiple"
              allowClear
              placeholder="选择可参与的项目"
              options={assignableProjects.map((project) => ({
                value: project.id,
                label: `${project.name} (${project.code})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="projectRole" label="项目角色" initialValue="developer">
            <Select
              options={projectRoles.map((r) => ({
                value: r.name,
                label: r.displayName,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="邀请码管理"
        open={inviteModalVisible}
        onCancel={() => setInviteModalVisible(false)}
        footer={null}
        width={980}
      >
        <Card size="small" style={{ marginBottom: 12 }}>
          <Form form={inviteForm} layout="inline" style={{ rowGap: 8 }}>
            <Form.Item name="maxUses" label="最大使用次数">
              <InputNumber min={0} placeholder="0 表示无限" style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="expiresAt" label="过期时间">
              <DatePicker showTime placeholder="可选，不填则不过期" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" loading={creatingInvite} onClick={handleCreateInvite}>
                生成邀请码
              </Button>
            </Form.Item>
            <Form.Item>
              <Button onClick={fetchInvites}>刷新列表</Button>
            </Form.Item>
          </Form>
        </Card>

        <Table
          rowKey="id"
          columns={inviteColumns}
          dataSource={invites}
          loading={loadingInvites}
          pagination={{ pageSize: 6 }}
        />
      </Modal>
    </PageLayout>
  );
};

export default UserManagement;
