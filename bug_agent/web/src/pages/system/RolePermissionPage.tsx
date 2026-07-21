import { logger } from '../../utils/logger';
import { getErrorMessage } from '../../utils/error';
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Tag,
  Space,
  Button,
  Modal,
  Form,
  Input,
  Checkbox,
  Row,
  Col,
  Typography,
  Spin,
  Tooltip,
  Divider,
  Select,
} from 'antd';
import { message } from '../../utils/appMessage';
import {
  SafetyOutlined,
  EditOutlined,
  KeyOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  listRoles,
  listPermissions,
  createRole,
  updateRole,
  updateRolePermissions,
} from '../../api';
import PageLayout from '../../components/layout/PageLayout';

import type { PermissionInfo } from '../../api';

const { Title, Text } = Typography;

interface Role {
  id: number;
  name: string;
  displayName: string;
  tier: string;
  description: string;
  isSystem: boolean;
  permissions?: PermissionInfo[];
}

const resourceLabels: Record<string, string> = {
  defects: '缺陷管理',
  agents: 'AI Agent',
  fixes: '修复任务',
  projects: '项目管理',
  users: '用户管理',
  system: '系统管理',
};

const resourceColors: Record<string, string> = {
  defects: 'red',
  agents: 'purple',
  fixes: 'orange',
  projects: 'blue',
  users: 'green',
  system: 'default',
};

const tierLabels: Record<string, string> = {
  platform: '平台角色',
  project: '项目角色',
};
const tierColors: Record<string, string> = {
  platform: 'gold',
  project: 'geekblue',
};

export default function RolePermissionPage() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Record<string, PermissionInfo[]>>({});
  const [loading, setLoading] = useState(true);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [permModalOpen, setPermModalOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const [createForm] = Form.useForm();
  const [selectedPermIds, setSelectedPermIds] = useState<number[]>([]);

  const loadAllData = useCallback(async () => {
    setLoading(true);
    try {
      const [rolesRes, permsRes] = await Promise.all([
        listRoles(),
        listPermissions(),
      ]);

      setRoles(rolesRes.data || []);
      setPermissions(permsRes.data || {});
    } catch (err) {
      logger.error('Failed to load data:', err);
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  const allPermissionsFlat = Object.values(permissions).flat();

  const handleCreateRole = () => {
    createForm.resetFields();
    setCreateModalOpen(true);
  };

  const handleSaveNewRole = async () => {
    try {
      const values = await createForm.validateFields();
      setSaving(true);
      await createRole(values);
      message.success('角色创建成功');
      setCreateModalOpen(false);
      loadAllData();
    } catch (error: unknown) {
      if ((error as { errorFields?: unknown } | undefined)?.errorFields) return;
      message.error(getErrorMessage(error, '创建失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleEditRole = (role: Role) => {
    setEditingRole(role);
    form.setFieldsValue({
      displayName: role.displayName,
      tier: role.tier,
      description: role.description,
    });
    setEditModalOpen(true);
  };

  const handleSaveRole = async () => {
    if (!editingRole) return;
    try {
      const values = await form.validateFields();
      setSaving(true);
      await updateRole(editingRole.id, values);
      message.success('角色更新成功');
      setEditModalOpen(false);
      loadAllData();
    } catch (error: unknown) {
      if ((error as { errorFields?: unknown } | undefined)?.errorFields) return;
      message.error(getErrorMessage(error, '更新失败'));
    } finally {
      setSaving(false);
    }
  };

  const handleEditPermissions = (role: Role) => {
    setEditingRole(role);
    setSelectedPermIds((role.permissions || []).map((p) => p.id));
    setPermModalOpen(true);
  };

  const handleSavePermissions = async () => {
    if (!editingRole) return;
    setSaving(true);
    try {
      await updateRolePermissions(editingRole.id, selectedPermIds);
      message.success('权限分配成功');
      setPermModalOpen(false);
      loadAllData();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '权限分配失败'));
    } finally {
      setSaving(false);
    }
  };

  const togglePermission = (permId: number) => {
    setSelectedPermIds((prev) =>
      prev.includes(permId)
        ? prev.filter((id) => id !== permId)
        : [...prev, permId],
    );
  };

  const toggleModuleAll = (modulePerms: PermissionInfo[]) => {
    const modulePermIds = modulePerms.map((p) => p.id);
    const allSelected = modulePermIds.every((id) => selectedPermIds.includes(id));
    if (allSelected) {
      setSelectedPermIds((prev) => prev.filter((id) => !modulePermIds.includes(id)));
    } else {
      setSelectedPermIds((prev) => [...new Set([...prev, ...modulePermIds])]);
    }
  };

  const roleColumns = [
    {
      title: '角色名称',
      dataIndex: 'displayName',
      width: 140,
      render: (name: string, record: Role) => (
        <Space>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            ({record.name})
          </Text>
        </Space>
      ),
    },
    {
      title: '层级',
      dataIndex: 'tier',
      width: 100,
      render: (tier: string) => (
        <Tag color={tierColors[tier] || 'default'}>
          {tierLabels[tier] || tier}
        </Tag>
      ),
    },
    {
      title: '类型',
      dataIndex: 'isSystem',
      width: 80,
      render: (sys: boolean) => (
        <Tag color={sys ? 'blue' : 'green'}>{sys ? '系统' : '自定义'}</Tag>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
    },
    {
      title: '权限数',
      dataIndex: 'permissions',
      width: 80,
      render: (perms: PermissionInfo[] | undefined) => (
        <Tag color={(perms?.length || 0) > 0 ? 'blue' : 'default'}>
          {perms?.length || 0}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 180,
      render: (_: unknown, record: Role) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEditRole(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={<KeyOutlined />}
            onClick={() => handleEditPermissions(record)}
          >
            分配权限
          </Button>
        </Space>
      ),
    },
  ];

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <Spin size="large" />
      </div>
    );
  }

  return (
    <PageLayout>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Title level={4} style={{ margin: 0 }}>
          <SafetyOutlined style={{ marginRight: 8 }} />
          角色权限管理
        </Title>
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateRole}>
            创建角色
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadAllData}>
            刷新
          </Button>
        </Space>
      </div>

      <Card>
        <Table
          columns={roleColumns}
          dataSource={roles}
          rowKey="id"
          size="middle"
          pagination={false}
          expandable={{
            expandedRowRender: (record: Role) => (
              <div style={{ padding: 12, background: '#fafafa', borderRadius: 8 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>
                  已分配权限 ({record.permissions?.length || 0})：
                </Text>
                {(record.permissions || []).length > 0 ? (
                  <Space size={[4, 4]} wrap>
                    {Object.entries(
                      (record.permissions || []).reduce(
                        (acc, p) => {
                          const mod = p.module || 'other';
                          if (!acc[mod]) acc[mod] = [];
                          acc[mod].push(p);
                          return acc;
                        },
                        {} as Record<string, PermissionInfo[]>,
                      ),
                    ).map(([module, perms]) => (
                      <div key={module} style={{ marginBottom: 4 }}>
                        <Tag color={resourceColors[module]} style={{ marginBottom: 2 }}>
                          {resourceLabels[module] || module}
                        </Tag>
                        {perms.map((perm) => (
                          <Tag key={perm.id} style={{ marginLeft: 2 }}>
                            <CheckCircleOutlined style={{ marginRight: 4, color: '#52c41a' }} />
                            {perm.name}
                          </Tag>
                        ))}
                      </div>
                    ))}
                  </Space>
                ) : (
                  <Text type="secondary">暂无权限</Text>
                )}
              </div>
            ),
          }}
        />
      </Card>

      {/* 创建角色 Modal */}
      <Modal
        title={
          <Space>
            <PlusOutlined />
            创建角色
          </Space>
        }
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleSaveNewRole}
        confirmLoading={saving}
        okText="创建"
        cancelText="取消"
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            label="角色标识"
            name="name"
            rules={[
              { required: true, message: '请输入角色标识' },
              { pattern: /^[a-z][a-z0-9_]*$/, message: '只能使用小写字母、数字和下划线，且以字母开头' },
            ]}
            extra="唯一标识，创建后不可修改，如：custom_viewer"
          >
            <Input placeholder="如：custom_viewer" />
          </Form.Item>
          <Form.Item
            label="显示名称"
            name="displayName"
            rules={[{ required: true, message: '请输入显示名称' }]}
          >
            <Input placeholder="请输入角色显示名称" />
          </Form.Item>
          <Form.Item
            label="角色层级"
            name="tier"
            rules={[{ required: true, message: '请选择角色层级' }]}
            extra="平台角色用于全局权限，项目角色用于项目内权限"
          >
            <Select placeholder="请选择角色层级">
              <Select.Option value="platform">平台角色</Select.Option>
              <Select.Option value="project">项目角色</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={3} placeholder="请输入角色描述" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑角色 Modal */}
      <Modal
        title={
          <Space>
            <EditOutlined />
            编辑角色 - {editingRole?.displayName}
          </Space>
        }
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSaveRole}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item label="角色标识" name="name">
            <Input disabled value={editingRole?.name} />
          </Form.Item>
          <Form.Item
            label="显示名称"
            name="displayName"
            rules={[{ required: true, message: '请输入显示名称' }]}
          >
            <Input placeholder="请输入角色显示名称" />
          </Form.Item>
          <Form.Item
            label="角色层级"
            name="tier"
            rules={[{ required: true, message: '请选择角色层级' }]}
          >
            <Select placeholder="请选择角色层级" disabled={editingRole?.isSystem}>
              <Select.Option value="platform">平台角色</Select.Option>
              <Select.Option value="project">项目角色</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={3} placeholder="请输入角色描述" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 分配权限 Modal */}
      <Modal
        title={
          <Space>
            <KeyOutlined />
            分配权限 - {editingRole?.displayName}
          </Space>
        }
        open={permModalOpen}
        onCancel={() => setPermModalOpen(false)}
        onOk={handleSavePermissions}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary">
            已选择 <Text strong>{selectedPermIds.length}</Text> / {allPermissionsFlat.length} 个权限
          </Text>
          <Divider style={{ margin: '8px 0' }} />
        </div>
        {Object.entries(permissions).map(([module, perms]) => {
          const modulePermIds = perms.map((p) => p.id);
          const allSelected = modulePermIds.every((id) =>
            selectedPermIds.includes(id),
          );
          const someSelected = modulePermIds.some((id) =>
            selectedPermIds.includes(id),
          );
          return (
            <div key={module} style={{ marginBottom: 16 }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  marginBottom: 8,
                  padding: '6px 8px',
                  background: '#f8fafc',
                  borderRadius: 6,
                }}
              >
                <Checkbox
                  indeterminate={someSelected && !allSelected}
                  checked={allSelected}
                  onChange={() => toggleModuleAll(perms)}
                />
                <Tag color={resourceColors[module]} style={{ margin: 0 }}>
                  {resourceLabels[module] || module}
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  ({perms.filter((p) => selectedPermIds.includes(p.id)).length}/{perms.length})
                </Text>
              </div>
              <Row gutter={[8, 8]} style={{ paddingLeft: 32 }}>
                {perms.map((perm) => {
                  const checked = selectedPermIds.includes(perm.id);
                  return (
                    <Col key={perm.id} span={12}>
                      <Checkbox
                        checked={checked}
                        onChange={() => togglePermission(perm.id)}
                      >
                        <Tooltip title={`${perm.action}${perm.displayName ? ` - ${perm.displayName}` : ''}`}>
                          <span style={{ color: checked ? undefined : '#999' }}>
                            {perm.name}
                          </span>
                        </Tooltip>
                      </Checkbox>
                    </Col>
                  );
                })}
              </Row>
            </div>
          );
        })}
      </Modal>
    </PageLayout>
  );
}
