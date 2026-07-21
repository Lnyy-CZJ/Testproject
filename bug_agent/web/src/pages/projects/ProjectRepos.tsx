import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { logger } from '../../utils/logger';
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Space,
  Popconfirm,
  Empty,
  Tag,
  Checkbox,
  Row,
  Col,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { message } from '../../utils/appMessage';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, BranchesOutlined,
  LinkOutlined, KeyOutlined, CloudDownloadOutlined, ReloadOutlined,
  CodeOutlined,
} from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import {
  listProjectRepos,
  createProjectRepo,
  updateProjectRepo,
  deleteProjectRepo,
  listCredentials,
  testRepoConnection,
  listYunxiaoRepos,
  importYunxiaoRepos,
} from '../../api';
import type { ProjectRepo, RepoCredential } from '../../types';
import type { YunxiaoRepo } from '../../api';
import { renderCredentialOptionLabel, parseCredentialExtraConfig } from '../../utils/credential';
import { getAgentShortLabel, getAgentTagColor, normalizeAgentTypes } from '../../utils/agentType';
import PageLayout from '../../components/layout/PageLayout';
import PageMetricSection from '../../components/layout/PageMetricSection';
import { getErrorMessage } from '../../utils/error';

const { TextArea } = Input;

const SOURCE_TYPES = [
  { value: 'github', label: 'GitHub', color: '#171515' },
  { value: 'gitlab', label: 'GitLab', color: '#FC6D26' },
  { value: 'gitea', label: 'Gitea', color: '#609926' },
  { value: 'yunxiao', label: '云效', color: '#1677ff' },
  { value: 'custom', label: '自定义/其他', color: '#64748b' },
];

const AGENT_TYPE_OPTIONS = [
  { value: 'product', label: '产品经理' },
  { value: 'ui', label: 'UI设计师' },
  { value: 'frontend', label: '前端开发' },
  { value: 'client', label: '客户端开发' },
  { value: 'backend', label: '后端开发' },
  { value: 'test', label: '测试工程师' },
];

interface RepoFormValues {
  name: string;
  sourceType: string;
  repoUrl: string;
  defaultBranch?: string;
  credentialId?: number;
  agentTypes: string[];
  description?: string;
}

interface YunxiaoImportFormValues {
  credentialId: number;
  organizationId?: string;
  endpoint?: string;
  search?: string;
}

const YUNXIAO_PAGE_SIZE = 8;


const ProjectRepos: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);

  const [repos, setRepos] = useState<ProjectRepo[]>([]);
  const [loading, setLoading] = useState(false);
  const [testingRepoId, setTestingRepoId] = useState<number | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingRepo, setEditingRepo] = useState<ProjectRepo | null>(null);
  const [form] = Form.useForm();
  const [credentials, setCredentials] = useState<RepoCredential[]>([]);
  const [importModalVisible, setImportModalVisible] = useState(false);
  const [importing, setImporting] = useState(false);
  const [loadingYunxiaoRepos, setLoadingYunxiaoRepos] = useState(false);
  const [yunxiaoRepos, setYunxiaoRepos] = useState<YunxiaoRepo[]>([]);
  const [selectedYunxiaoRepoKeys, setSelectedYunxiaoRepoKeys] = useState<React.Key[]>([]);
  const [yunxiaoSearchKeyword, setYunxiaoSearchKeyword] = useState('');
  const [yunxiaoPage, setYunxiaoPage] = useState(1);
  const [importForm] = Form.useForm();
  const [repoPage, setRepoPage] = useState(1);
  const [repoPageSize, setRepoPageSize] = useState(10);

  const loadingRef = useRef(false);

  const fetchRepos = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const res = await listProjectRepos(pid);
      setRepos(res.data || []);
    } catch {
      message.error('获取仓库列表失败');
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, [pid]);

  const fetchCredentials = useCallback(async () => {
    try {
      const res = await listCredentials({ projectId: pid });
      setCredentials(res.data || []);
    } catch (err) { logger.error('加载凭证列表失败:', err); }
  }, [pid]);

  const yunxiaoCredentials = useMemo(
    () => credentials.filter((credential) => String(credential.provider || '').toLowerCase() === 'yunxiao'),
    [credentials],
  );

  const filteredYunxiaoRepos = useMemo(() => {
    const keyword = yunxiaoSearchKeyword.trim().toLowerCase();
    if (!keyword) {
      return yunxiaoRepos;
    }
    return yunxiaoRepos.filter((repo) => {
      const haystacks = [
        repo.name,
        repo.repoUrl,
        repo.defaultBranch,
        repo.description,
      ];
      return haystacks.some((value) => String(value || '').toLowerCase().includes(keyword));
    });
  }, [yunxiaoRepos, yunxiaoSearchKeyword]);

  const currentPageYunxiaoRepos = useMemo(() => {
    const start = (yunxiaoPage - 1) * YUNXIAO_PAGE_SIZE;
    return filteredYunxiaoRepos.slice(start, start + YUNXIAO_PAGE_SIZE);
  }, [filteredYunxiaoRepos, yunxiaoPage]);

  useEffect(() => {
    if (pid) {
      void fetchRepos();
      void fetchCredentials();
    }
  }, [fetchCredentials, fetchRepos, pid]);

  const openModal = (repo?: ProjectRepo) => {
    setEditingRepo(repo || null);
    if (repo) {
      form.setFieldsValue({
        ...repo,
        agentTypes: repo.agentTypes?.length ? repo.agentTypes : ['backend', 'test'],
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        sourceType: 'custom',
        defaultBranch: 'main',
        agentTypes: ['backend', 'test'],
      });
    }
    setModalVisible(true);
  };

  const openImportModal = () => {
    importForm.resetFields();
    const defaultCredential = yunxiaoCredentials[0];
    if (defaultCredential) {
      const extra = parseCredentialExtraConfig(defaultCredential?.extraConfig);
      importForm.setFieldsValue({
        credentialId: defaultCredential.id,
        organizationId: extra.organizationId || undefined,
        endpoint: extra.endpoint || undefined,
      });
    }
    setYunxiaoSearchKeyword('');
    setYunxiaoPage(1);
    setYunxiaoRepos([]);
    setSelectedYunxiaoRepoKeys([]);
    setImportModalVisible(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields() as RepoFormValues;
      const agentTypes = Array.isArray(values.agentTypes) ? values.agentTypes : [];
      if (agentTypes.length === 0) {
        message.error('请至少选择一个 AGENT 类型');
        return;
      }

      const payload: {
        name: string;
        sourceType: string;
        repoUrl: string;
        defaultBranch?: string;
        credentialId?: number | null;
        agentTypes: string;
        description?: string;
      } = {
        ...values,
        agentTypes: agentTypes.join(','),
      };

      if (editingRepo && values.credentialId === undefined && editingRepo.credentialId) {
        payload.credentialId = null;
      }
      if (!editingRepo && values.credentialId === undefined) {
        delete payload.credentialId;
      }

      if (editingRepo) {
        await updateProjectRepo(pid, editingRepo.id, payload);
        message.success('仓库已更新');
      } else {
        await createProjectRepo(pid, payload);
        message.success('仓库已添加');
      }
      setModalVisible(false);
      fetchRepos();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleDelete = async (repoId: number) => {
    try {
      await deleteProjectRepo(pid, repoId);
      message.success('仓库已删除');
      fetchRepos();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除失败'));
    }
  };

  const handleFetchYunxiaoRepos = async () => {
    try {
      await importForm.validateFields(['credentialId']);
      const values = importForm.getFieldsValue() as YunxiaoImportFormValues;
      setLoadingYunxiaoRepos(true);
      const res = await listYunxiaoRepos({
        credentialId: values.credentialId,
        projectId: pid,
        endpoint: values.endpoint || undefined,
        organizationId: values.organizationId || undefined,
        page: 1,
        size: 100,
      });
      const list = res.data?.items || [];
      setYunxiaoRepos(list);
      setYunxiaoPage(1);
      setSelectedYunxiaoRepoKeys([]);
      message.success(`已拉取 ${list.length} 个云效仓库`);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '拉取云效仓库失败'));
    } finally {
      setLoadingYunxiaoRepos(false);
    }
  };

  const handleImportYunxiaoRepos = async () => {
    try {
      const values = await importForm.validateFields(['credentialId']) as YunxiaoImportFormValues;
      const selectedRepos = filteredYunxiaoRepos.filter((repo) =>
        selectedYunxiaoRepoKeys.includes(repo.externalId || repo.repoUrl),
      );
      if (selectedRepos.length === 0) {
        message.warning('请勾选当前页至少一个仓库');
        return;
      }
      setImporting(true);
      const res = await importYunxiaoRepos(pid, {
        credentialId: values.credentialId,
        items: selectedRepos.map((repo) => ({
          externalId: repo.externalId,
          name: repo.name,
          repoUrl: repo.repoUrl,
          defaultBranch: repo.defaultBranch,
          description: repo.description,
        })),
      });
      message.success(`导入完成：新增 ${res.data?.imported || 0} 个仓库`);
      setImportModalVisible(false);
      fetchRepos();
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '导入失败'));
    } finally {
      setImporting(false);
    }
  };

  const handleTestConnection = async (repo: ProjectRepo) => {
    try {
      setTestingRepoId(repo.id);
      const res = await testRepoConnection(repo.id);
      if (res?.data?.success) {
        message.success(res.data.message || '连接成功');
        return;
      }
      message.error(res?.data?.message || '连接失败');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '连接测试失败'));
    } finally {
      setTestingRepoId(null);
    }
  };

  const getSourceTypeTag = (type: string) => {
    const found = SOURCE_TYPES.find(s => s.value === type);
    return (
      <Tag color={found?.color || '#64748b'} style={{ borderRadius: 4 }}>
        {found?.label || type}
      </Tag>
    );
  };

  const getAgentTypeTags = (types: string | string[]) => {
    const arr = normalizeAgentTypes(types);
    if (arr.length === 0) return null;
    return arr.map((t: string) => (
      <Tag key={t} color={getAgentTagColor(t)} style={{ borderRadius: 4 }}>{getAgentShortLabel(t)}</Tag>
    ));
  };

  const credentialByID = useMemo(() => {
    return credentials.reduce<Record<number, RepoCredential>>((acc, credential) => {
      acc[credential.id] = credential;
      return acc;
    }, {});
  }, [credentials]);

  const columns: TableColumnsType<ProjectRepo> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, align: 'center' as const },
    {
      title: '仓库名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      render: (name: string) => (
        <span className="font-medium">
          <BranchesOutlined className="mr-2 text-purple-500" />
          {name}
        </span>
      ),
    },
    {
      title: '来源',
      dataIndex: 'sourceType',
      key: 'sourceType',
      width: 100,
      render: (type: string) => getSourceTypeTag(type),
    },
    {
      title: '仓库地址',
      dataIndex: 'repoUrl',
      key: 'repoUrl',
      ellipsis: true,
      render: (url: string) => (
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-cyan-600">
          <LinkOutlined className="mr-1" />
          {url}
        </a>
      ),
    },
    {
      title: '凭证',
      dataIndex: 'credentialId',
      key: 'credentialId',
      width: 100,
      render: (_, record) =>
        (
          <Tag icon={<KeyOutlined />} color={record.credentialId ? 'blue' : 'default'}>
            {record.credentialId ? '已绑定' : '未绑定'}
          </Tag>
        ),
    },
    {
      title: 'AGENT',
      dataIndex: 'agentTypes',
      key: 'agentTypes',
      width: 160,
      render: (types: string | string[]) => getAgentTypeTags(types),
    },
    { title: '默认分支', dataIndex: 'defaultBranch', key: 'defaultBranch', width: 100, ellipsis: true },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            onClick={() => handleTestConnection(record)}
            loading={testingRepoId === record.id}
          >
            测试连接
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openModal(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此仓库？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '仓库总数', value: repos.length, icon: <CodeOutlined />, tone: 'purple' },
          { key: 'bound', label: '已绑定凭证', value: repos.filter(r => r.credentialId).length, icon: <KeyOutlined />, tone: 'cyan' },
        ]}
        actions={(
          <Space>
            <Button
              type="primary"
              className="brand-button"
              icon={<PlusOutlined />}
              onClick={() => openModal()}
            >
              添加仓库
            </Button>
            <Button
              icon={<CloudDownloadOutlined />}
              onClick={openImportModal}
            >
              从云效导入
            </Button>
          </Space>
        )}
      />

      <Card
        className="scene-card"
        title="仓库列表"
      >
        {repos.length === 0 && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无仓库"
            style={{ padding: '40px 0' }}
          >
            <Button type="primary" onClick={() => openModal()}>
              添加第一个仓库
            </Button>
          </Empty>
        ) : (
          <Table
            columns={columns}
            dataSource={repos}
            rowKey="id"
            loading={loading}
            pagination={{
              current: repoPage,
              pageSize: repoPageSize,
              total: repos.length,
              showSizeChanger: true,
              showTotal: (t) => `共 ${t} 个仓库`,
              onChange: (p, ps) => { setRepoPage(p); setRepoPageSize(ps); },
            }}
            scroll={{ x: 1100 }}
          />
        )}
      </Card>

      {/* 编辑弹窗 */}
      <Modal
        title={editingRepo ? '编辑仓库' : '添加仓库'}
        open={modalVisible}
        onOk={handleSave}
        onCancel={() => setModalVisible(false)}
        okText="保存"
        cancelText="取消"
        width={650}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label="仓库名称" rules={[{ required: true, message: '请输入仓库名称' }]}>
                <Input placeholder="如 bug-agent-server" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="sourceType" label="来源类型" rules={[{ required: true, message: '请选择来源类型' }]}>
                <Select placeholder="选择代码托管平台">
                  {SOURCE_TYPES.map(s => (
                    <Select.Option key={s.value} value={s.value}>{s.label}</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="repoUrl" label="仓库地址" rules={[{ required: true, message: '请输入仓库地址' }]}>
            <Input placeholder="https://github.com/example/repo" />
          </Form.Item>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="defaultBranch" label="默认分支">
                <Input placeholder="main / master / develop" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="credentialId" label="访问凭证">
                <Select
                  placeholder="选择凭证（可选）"
                  allowClear
                  options={credentials.map((c) => ({
                    value: c.id,
                    label: renderCredentialOptionLabel(c),
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="agentTypes"
            label="绑定的 AGENT 类型"
            rules={[{ required: true, message: '请至少选择一个 AGENT 类型' }]}
          >
            <Checkbox.Group options={AGENT_TYPE_OPTIONS} />
          </Form.Item>

          <Form.Item name="description" label="描述">
            <TextArea rows={3} placeholder="仓库描述（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 云效导入弹窗 */}
      <Modal
        title="从云效导入仓库"
        open={importModalVisible}
        onOk={handleImportYunxiaoRepos}
        onCancel={() => setImportModalVisible(false)}
        okText="导入选中仓库"
        cancelText="取消"
        confirmLoading={importing}
        width={900}
      >
        <Form form={importForm} layout="vertical">
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item
                name="credentialId"
                label="云效凭证"
                rules={[{ required: true, message: '请选择凭证' }]}
              >
                <Select
                  placeholder="选择云效凭证"
                  onChange={(credentialId: number) => {
                    const selected = yunxiaoCredentials.find((c) => c.id === credentialId);
                    const extra = parseCredentialExtraConfig(selected?.extraConfig);
                    importForm.setFieldsValue({
                      organizationId: extra.organizationId || undefined,
                      endpoint: extra.endpoint || undefined,
                    });
                  }}
                  options={yunxiaoCredentials.map((c) => ({
                      value: c.id,
                      label: renderCredentialOptionLabel(c),
                    }))}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="organizationId" label="组织ID（可选）">
                <Input placeholder="若凭证内容未包含 organizationId，请填写" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="endpoint" label="API Endpoint（可选）">
                <Input placeholder="默认 https://openapi-rdc.aliyuncs.com" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={16}>
              <Form.Item label="仓库搜索（本地）">
                <Input
                  value={yunxiaoSearchKeyword}
                  onChange={(event) => {
                    setYunxiaoSearchKeyword(event.target.value);
                    setYunxiaoPage(1);
                    setSelectedYunxiaoRepoKeys([]);
                  }}
                  placeholder="对已拉取仓库做本地过滤"
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label=" ">
                <Button
                  icon={<ReloadOutlined />}
                  loading={loadingYunxiaoRepos}
                  onClick={handleFetchYunxiaoRepos}
                  block
                >
                  拉取仓库
                </Button>
              </Form.Item>
            </Col>
          </Row>
        </Form>
	        <Table<YunxiaoRepo>
	          rowKey={(record) => record.externalId || record.repoUrl}
          dataSource={filteredYunxiaoRepos}
          loading={loadingYunxiaoRepos}
          pagination={{
            pageSize: YUNXIAO_PAGE_SIZE,
            current: yunxiaoPage,
            onChange: (page) => {
              setYunxiaoPage(page);
              setSelectedYunxiaoRepoKeys([]);
            },
          }}
          size="small"
          rowSelection={{
            selectedRowKeys: selectedYunxiaoRepoKeys,
            onChange: (keys) => setSelectedYunxiaoRepoKeys(keys),
            preserveSelectedRowKeys: false,
          }}
          columns={[
            { title: '仓库名', dataIndex: 'name', key: 'name', width: 220 },
            { title: '仓库地址', dataIndex: 'repoUrl', key: 'repoUrl', ellipsis: true },
            { title: '默认分支', dataIndex: 'defaultBranch', key: 'defaultBranch', width: 100, render: (v: string) => v || 'main' },
          ]}
        />
      </Modal>
    </PageLayout>
  );
};

export default ProjectRepos;
