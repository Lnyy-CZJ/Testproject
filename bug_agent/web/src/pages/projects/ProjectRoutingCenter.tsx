import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from 'antd';
import { formatDateTime } from '../../utils/formatDate';
import dayjs, { type Dayjs } from 'dayjs';
import { AppstoreOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, ShareAltOutlined, CalendarOutlined, WarningOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import {
  createAppRelease,
  createIssueRoutingRule,
  createProjectModule,
  deleteAppRelease,
  deleteIssueRoutingRule,
  deleteProjectModule,
  listAppReleases,
  listAppReleaseTrends,
  listIssueRoutingRules,
  listProjectModules,
  listProjectRepos,
  updateAppRelease,
  updateIssueRoutingRule,
  updateProjectModule,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageLoadState from '../../components/PageLoadState';
import PageLayout from '../../components/layout/PageLayout';
import { useProject } from '../../contexts/projectContext';
import { message } from '../../utils/appMessage';
import type { AppRelease, AppReleaseTrend, IssueRoutingRule, ProjectModule, ProjectRepo } from '../../types';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';

interface ModuleFormValues {
  name: string;
  code: string;
  description?: string;
  ownerUserId?: number;
  repoId?: number;
  pathPattern?: string;
  tags?: string;
}

interface RuleFormValues {
  matchType: IssueRoutingRule['matchType'];
  matchValue: string;
  moduleId?: number;
  ownerUserId?: number;
  priorityOverride?: string;
  severityOverride?: string;
  enabled: boolean;
  sortOrder: number;
}

interface ReleaseFormValues {
  platform: string;
  appVersion: string;
  buildNumber?: string;
  channel?: string;
  releaseTime: Dayjs;
  commitSha?: string;
  repoId?: number;
  metadataJson?: string;
}

const matchTypeOptions = [
  { label: '来源类型', value: 'source_type' },
  { label: '平台', value: 'platform' },
  { label: '版本号', value: 'app_version' },
  { label: '指纹包含', value: 'fingerprint_pattern' },
  { label: '堆栈关键字', value: 'stack_keyword' },
] satisfies Array<{ label: string; value: IssueRoutingRule['matchType'] }>;

const severityOptions = [
  { label: 'fatal', value: 'fatal' },
  { label: 'major', value: 'major' },
  { label: 'normal', value: 'normal' },
  { label: 'minor', value: 'minor' },
];

const priorityOptions = [
  { label: 'P0', value: 'P0' },
  { label: 'P1', value: 'P1' },
  { label: 'P2', value: 'P2' },
  { label: 'P3', value: 'P3' },
];

const anomalyLevelMap: Record<AppReleaseTrend['anomalyLevel'], { color: string; label: string }> = {
  baseline: { color: 'default', label: '基线版本' },
  normal: { color: 'success', label: '平稳' },
  watch: { color: 'warning', label: '关注抬升' },
  high: { color: 'error', label: '异常抬升' },
};

const ProjectRoutingCenter: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);
  const { members } = useProject();

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savingModule, setSavingModule] = useState(false);
  const [savingRule, setSavingRule] = useState(false);
  const [savingRelease, setSavingRelease] = useState(false);
  const [modules, setModules] = useState<ProjectModule[]>([]);
  const [rules, setRules] = useState<IssueRoutingRule[]>([]);
  const [releases, setReleases] = useState<AppRelease[]>([]);
  const [releaseTrends, setReleaseTrends] = useState<AppReleaseTrend[]>([]);
  const [repos, setRepos] = useState<ProjectRepo[]>([]);
  const [moduleModalOpen, setModuleModalOpen] = useState(false);
  const [ruleModalOpen, setRuleModalOpen] = useState(false);
  const [releaseModalOpen, setReleaseModalOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<ProjectModule | null>(null);
  const [editingRule, setEditingRule] = useState<IssueRoutingRule | null>(null);
  const [editingRelease, setEditingRelease] = useState<AppRelease | null>(null);
  const [moduleForm] = Form.useForm<ModuleFormValues>();
  const [ruleForm] = Form.useForm<RuleFormValues>();
  const [releaseForm] = Form.useForm<ReleaseFormValues>();


  const memberOptions = useMemo(
    () => members.map((member) => ({
      label: member.nickname || member.username || `用户 #${member.userId}`,
      value: member.userId,
    })),
    [members],
  );

  const repoOptions = useMemo(
    () => repos.map((repo) => ({ label: `${repo.name} (${repo.defaultBranch})`, value: repo.id })),
    [repos],
  );

  const memberNameMap = useMemo(
    () => new Map(memberOptions.map((option) => [option.value, option.label])),
    [memberOptions],
  );

  const repoNameMap = useMemo(
    () => new Map(repos.map((repo) => [repo.id, repo.name])),
    [repos],
  );

  const fetchData = useCallback(async () => {
    if (!pid) {
      setLoadError('无效的项目 ID');
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const [moduleRes, ruleRes, releaseRes, releaseTrendRes, repoRes] = await Promise.all([
        listProjectModules(pid),
        listIssueRoutingRules(pid),
        listAppReleases(pid),
        listAppReleaseTrends(pid),
        listProjectRepos(pid),
      ]);
      setModules(moduleRes.data || []);
      setRules(ruleRes.data || []);
      setReleases(releaseRes.data || []);
      setReleaseTrends(releaseTrendRes.data || []);
      setRepos(repoRes.data || []);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '获取路由治理数据失败');
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!moduleModalOpen) return;
    moduleForm.setFieldsValue({
      name: editingModule?.name || '',
      code: editingModule?.code || '',
      description: editingModule?.description || '',
      ownerUserId: editingModule?.ownerUserId || undefined,
      repoId: editingModule?.repoId || undefined,
      pathPattern: editingModule?.pathPattern || '',
      tags: editingModule?.tags || '',
    });
  }, [editingModule, moduleForm, moduleModalOpen]);

  useEffect(() => {
    if (!ruleModalOpen) return;
    ruleForm.setFieldsValue({
      matchType: editingRule?.matchType || 'platform',
      matchValue: editingRule?.matchValue || '',
      moduleId: editingRule?.moduleId || undefined,
      ownerUserId: editingRule?.ownerUserId || undefined,
      priorityOverride: editingRule?.priorityOverride || undefined,
      severityOverride: editingRule?.severityOverride || undefined,
      enabled: editingRule?.enabled ?? true,
      sortOrder: editingRule?.sortOrder ?? 10,
    });
  }, [editingRule, ruleForm, ruleModalOpen]);

  useEffect(() => {
    if (!releaseModalOpen) return;
    releaseForm.setFieldsValue({
      platform: editingRelease?.platform || 'android',
      appVersion: editingRelease?.appVersion || '',
      buildNumber: editingRelease?.buildNumber || '',
      channel: editingRelease?.channel || '',
      releaseTime: editingRelease?.releaseTime ? dayjs(editingRelease.releaseTime) : dayjs(),
      commitSha: editingRelease?.commitSha || '',
      repoId: editingRelease?.repoId || undefined,
      metadataJson: editingRelease?.metadataJson || '',
    });
  }, [editingRelease, releaseForm, releaseModalOpen]);

  const openModuleModal = (item?: ProjectModule) => {
    setEditingModule(item || null);
    setModuleModalOpen(true);
  };

  const openRuleModal = (item?: IssueRoutingRule) => {
    setEditingRule(item || null);
    setRuleModalOpen(true);
  };

  const openReleaseModal = (item?: AppRelease) => {
    setEditingRelease(item || null);
    setReleaseModalOpen(true);
  };

  const handleSaveModule = async () => {
    try {
      const values = await moduleForm.validateFields();
      setSavingModule(true);
      const payload = {
        ...values,
        ownerUserId: values.ownerUserId || null,
        repoId: values.repoId || null,
      };
      if (editingModule) {
        await updateProjectModule(pid, editingModule.id, payload);
        message.success('项目模块已更新');
      } else {
        await createProjectModule(pid, payload);
        message.success('项目模块已创建');
      }
      setModuleModalOpen(false);
      await fetchData();
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) return;
      message.error(getErrorMessage(error, '保存项目模块失败'));
    } finally {
      setSavingModule(false);
    }
  };

  const handleSaveRule = async () => {
    try {
      const values = await ruleForm.validateFields();
      setSavingRule(true);
      const payload = {
        ...values,
        moduleId: values.moduleId || null,
        ownerUserId: values.ownerUserId || null,
      };
      if (editingRule) {
        await updateIssueRoutingRule(pid, editingRule.id, payload);
        message.success('路由规则已更新');
      } else {
        await createIssueRoutingRule(pid, payload);
        message.success('路由规则已创建');
      }
      setRuleModalOpen(false);
      await fetchData();
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) return;
      message.error(getErrorMessage(error, '保存路由规则失败'));
    } finally {
      setSavingRule(false);
    }
  };

  const handleSaveRelease = async () => {
    try {
      const values = await releaseForm.validateFields();
      let metadata: Record<string, unknown> | undefined;
      if (values.metadataJson?.trim()) {
        metadata = JSON.parse(values.metadataJson);
      }
      setSavingRelease(true);
      const payload = {
        platform: values.platform,
        appVersion: values.appVersion.trim(),
        buildNumber: values.buildNumber?.trim(),
        channel: values.channel?.trim(),
        releaseTime: values.releaseTime.toISOString(),
        commitSha: values.commitSha?.trim(),
        repoId: values.repoId || null,
        metadata,
      };
      if (editingRelease) {
        await updateAppRelease(pid, editingRelease.id, payload);
        message.success('版本发布已更新');
      } else {
        await createAppRelease(pid, payload);
        message.success('版本发布已创建');
      }
      setReleaseModalOpen(false);
      await fetchData();
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) return;
      if (error instanceof SyntaxError) {
        message.error('Metadata JSON 格式错误');
        return;
      }
      message.error(getErrorMessage(error, '保存版本发布失败'));
    } finally {
      setSavingRelease(false);
    }
  };

  const handleDeleteModule = useCallback(async (moduleId: number) => {
    try {
      await deleteProjectModule(pid, moduleId);
      await fetchData();
      message.success('项目模块已删除');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除项目模块失败'));
    }
  }, [pid, fetchData]);

  const handleDeleteRule = useCallback(async (ruleId: number) => {
    try {
      await deleteIssueRoutingRule(pid, ruleId);
      await fetchData();
      message.success('路由规则已删除');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除路由规则失败'));
    }
  }, [pid, fetchData]);

  const handleDeleteRelease = useCallback(async (releaseId: number) => {
    try {
      await deleteAppRelease(pid, releaseId);
      await fetchData();
      message.success('版本发布已删除');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '删除版本发布失败'));
    }
  }, [pid, fetchData]);

  const moduleColumns = [
    { title: '模块名称', dataIndex: 'name' },
    { title: '编码', dataIndex: 'code', width: 120 },
    {
      title: '负责人',
      key: 'owner',
      width: 160,
      render: (_: unknown, record: ProjectModule) => memberNameMap.get(record.ownerUserId || 0) || <span style={{ color: '#94a3b8' }}>未配置</span>,
    },
    {
      title: '仓库',
      key: 'repo',
      width: 180,
      render: (_: unknown, record: ProjectModule) => repoNameMap.get(record.repoId || 0) || <span style={{ color: '#94a3b8' }}>未绑定</span>,
    },
    {
      title: '路径匹配',
      dataIndex: 'pathPattern',
      render: (value?: string) => value || <span style={{ color: '#94a3b8' }}>未配置</span>,
    },
    {
      title: '标签',
      dataIndex: 'tags',
      render: (value?: string) => value ? value.split(',').filter(Boolean).map((tag) => <Tag key={tag}>{tag.trim()}</Tag>) : <span style={{ color: '#94a3b8' }}>无</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: ProjectModule) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openModuleModal(record)}>编辑</Button>
          <Popconfirm title="确定删除该模块？" onConfirm={() => void handleDeleteModule(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const ruleColumns = [
    {
      title: '匹配条件',
      key: 'match',
      render: (_: unknown, record: IssueRoutingRule) => (
        <Space direction="vertical" size={2}>
          <Tag color="blue">{matchTypeOptions.find((item) => item.value === record.matchType)?.label || record.matchType}</Tag>
          <span>{record.matchValue}</span>
        </Space>
      ),
    },
    {
      title: '模块 / 负责人',
      key: 'target',
      render: (_: unknown, record: IssueRoutingRule) => (
        <Space direction="vertical" size={2}>
          <span>{modules.find((item) => item.id === record.moduleId)?.name || '未绑定模块'}</span>
          <span style={{ color: '#64748b' }}>{memberNameMap.get(record.ownerUserId || 0) || '未指定负责人'}</span>
        </Space>
      ),
    },
    {
      title: '覆盖策略',
      key: 'override',
      render: (_: unknown, record: IssueRoutingRule) => (
        <Space>
          {record.priorityOverride ? <Tag color="gold">{record.priorityOverride}</Tag> : null}
          {record.severityOverride ? <Tag color="volcano">{record.severityOverride}</Tag> : null}
          {!record.priorityOverride && !record.severityOverride ? <span style={{ color: '#94a3b8' }}>无</span> : null}
        </Space>
      ),
    },
    { title: '顺序', dataIndex: 'sortOrder', width: 80 },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 100,
      render: (value: boolean) => <Tag color={value ? 'success' : 'default'}>{value ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: IssueRoutingRule) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openRuleModal(record)}>编辑</Button>
          <Popconfirm title="确定删除该路由规则？" onConfirm={() => void handleDeleteRule(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const releaseColumns = [
    {
      title: '平台 / 版本',
      key: 'version',
      render: (_: unknown, record: AppRelease) => (
        <Space direction="vertical" size={2}>
          <Tag color="purple">{record.platform}</Tag>
          <span>{record.appVersion}{record.buildNumber ? ` (${record.buildNumber})` : ''}</span>
        </Space>
      ),
    },
    {
      title: '渠道',
      dataIndex: 'channel',
      width: 120,
      render: (value?: string) => value || <span style={{ color: '#94a3b8' }}>默认</span>,
    },
    {
      title: '发布时间',
      dataIndex: 'releaseTime',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '仓库 / Commit',
      key: 'commit',
      render: (_: unknown, record: AppRelease) => (
        <Space direction="vertical" size={2}>
          <span>{repoNameMap.get(record.repoId || 0) || '未绑定仓库'}</span>
          <span style={{ color: '#64748b' }}>{record.commitSha || '未记录 Commit'}</span>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, record: AppRelease) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => openReleaseModal(record)}>编辑</Button>
          <Popconfirm title="确定删除该版本发布？" onConfirm={() => void handleDeleteRelease(record.id)}>
            <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const releaseTrendColumns = [
    {
      title: '平台 / 版本',
      key: 'version',
      render: (_: unknown, record: AppReleaseTrend) => (
        <Space direction="vertical" size={2}>
          <Tag color="purple">{record.release.platform}</Tag>
          <span>
            {record.release.appVersion}
            {record.release.buildNumber ? ` (${record.release.buildNumber})` : ''}
          </span>
        </Space>
      ),
    },
    {
      title: '渠道',
      dataIndex: ['release', 'channel'],
      width: 120,
      render: (value?: string) => value || <span style={{ color: '#94a3b8' }}>默认</span>,
    },
    { title: '问题簇', dataIndex: 'clusterCount', width: 90 },
    { title: '信号数', dataIndex: 'signalCount', width: 90 },
    { title: '影响用户', dataIndex: 'affectedUserCount', width: 100 },
    {
      title: '趋势',
      key: 'trend',
      width: 220,
      render: (_: unknown, record: AppReleaseTrend) => (
        <Space direction="vertical" size={2}>
          <Tag color={anomalyLevelMap[record.anomalyLevel]?.color || 'default'}>
            {anomalyLevelMap[record.anomalyLevel]?.label || record.anomalyLevel}
          </Tag>
          {record.previousRelease ? (
            <span style={{ color: '#64748b' }}>
              对比 {record.previousRelease.appVersion}
              {record.previousRelease.buildNumber ? ` (${record.previousRelease.buildNumber})` : ''}
              ，问题簇 {record.clusterDelta >= 0 ? '+' : ''}{record.clusterDelta}，影响用户 {record.affectedUserDelta >= 0 ? '+' : ''}{record.affectedUserDelta}
            </span>
          ) : (
            <span style={{ color: '#94a3b8' }}>首个基线版本</span>
          )}
        </Space>
      ),
    },
    {
      title: '最近发生',
      dataIndex: 'lastSeenAt',
      width: 180,
      render: (value?: string) => value ? formatDateTime(value) : <span style={{ color: '#94a3b8' }}>暂无问题</span>,
    },
  ];

  const anomalyReleaseCount = releaseTrends.filter((item) => item.anomalyLevel === 'high' || item.anomalyLevel === 'watch').length;

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'modules', label: '项目模块', value: modules.length, icon: <AppstoreOutlined />, tone: 'purple' },
          { key: 'rules', label: '路由规则', value: rules.length, icon: <ShareAltOutlined />, tone: 'cyan' },
          { key: 'releases', label: '版本发布', value: releases.length, icon: <CalendarOutlined />, tone: 'amber' },
          { key: 'trends', label: '异常趋势', value: anomalyReleaseCount, icon: <WarningOutlined />, tone: 'rose' },
        ]}
        actions={(
          <Button icon={<ReloadOutlined />} onClick={() => void fetchData()}>
            刷新
          </Button>
        )}
      />

      {loadError ? (
        <PageLoadState subTitle={loadError} onRetry={() => void fetchData()} />
      ) : null}
      <Card className="scene-card">
        <Tabs
          items={[
            {
              key: 'modules',
              label: '项目模块',
              children: (
                <Card
                  className="utility-card"
                  size="small"
                  extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openModuleModal()}>新增模块</Button>}
                >
                  <Table
                    rowKey="id"
                    loading={loading}
                    dataSource={modules}
                    pagination={false}
                    locale={{ emptyText: <Empty description="暂无项目模块" /> }}
                    columns={moduleColumns}
                  />
                </Card>
              ),
            },
            {
              key: 'rules',
              label: '路由规则',
              children: (
                <Card
                  className="utility-card"
                  size="small"
                  extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openRuleModal()}>新增规则</Button>}
                >
                  <Table
                    rowKey="id"
                    loading={loading}
                    dataSource={rules}
                    pagination={false}
                    locale={{ emptyText: <Empty description="暂无路由规则" /> }}
                    columns={ruleColumns}
                  />
                </Card>
              ),
            },
            {
              key: 'releases',
              label: '版本发布',
              children: (
                <Space direction="vertical" size={16} style={{ width: '100%' }}>
                  <div data-testid="release-trend-card">
                    <Card className="utility-card" size="small" title="发布趋势">
                      <Table
                        rowKey={(record) => record.release.id}
                        loading={loading}
                        dataSource={releaseTrends}
                        pagination={false}
                        locale={{ emptyText: <Empty description="暂无发布趋势数据" /> }}
                        columns={releaseTrendColumns}
                      />
                    </Card>
                  </div>
                  <Card
                    className="utility-card"
                    size="small"
                    extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openReleaseModal()}>新增版本</Button>}
                  >
                    <Table
                      rowKey="id"
                      loading={loading}
                      dataSource={releases}
                      pagination={false}
                      locale={{ emptyText: <Empty description="暂无版本发布记录" /> }}
                      columns={releaseColumns}
                    />
                  </Card>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editingModule ? '编辑项目模块' : '新增项目模块'}
        open={moduleModalOpen}
        onCancel={() => setModuleModalOpen(false)}
        onOk={() => void handleSaveModule()}
        confirmLoading={savingModule}
        destroyOnHidden
      >
        <Form form={moduleForm} layout="vertical">
          <Form.Item label="模块名称" name="name" rules={[{ required: true, message: '请输入模块名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item label="模块编码" name="code" rules={[{ required: true, message: '请输入模块编码' }]}>
            <Input />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item label="负责人" name="ownerUserId">
            <Select allowClear options={memberOptions} placeholder="可选，自动路由默认负责人" />
          </Form.Item>
          <Form.Item label="仓库" name="repoId">
            <Select allowClear options={repoOptions} placeholder="可选，绑定对应仓库" />
          </Form.Item>
          <Form.Item label="路径匹配" name="pathPattern">
            <Input placeholder="例如：app/startup/**" />
          </Form.Item>
          <Form.Item label="标签" name="tags">
            <Input placeholder="例如：android,startup" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingRule ? '编辑路由规则' : '新增路由规则'}
        open={ruleModalOpen}
        onCancel={() => setRuleModalOpen(false)}
        onOk={() => void handleSaveRule()}
        confirmLoading={savingRule}
        destroyOnHidden
      >
        <Form form={ruleForm} layout="vertical" initialValues={{ enabled: true, sortOrder: 10 }}>
          <Form.Item label="匹配类型" name="matchType" rules={[{ required: true, message: '请选择匹配类型' }]}>
            <Select options={matchTypeOptions} />
          </Form.Item>
          <Form.Item label="匹配值" name="matchValue" rules={[{ required: true, message: '请输入匹配值' }]}>
            <Input placeholder="例如：android / bugly / startup-fp" />
          </Form.Item>
          <Form.Item label="归属模块" name="moduleId">
            <Select allowClear options={modules.map((item) => ({ label: item.name, value: item.id }))} placeholder="可选，命中后自动归属" />
          </Form.Item>
          <Form.Item label="负责人" name="ownerUserId">
            <Select allowClear options={memberOptions} placeholder="可选，命中后自动指派" />
          </Form.Item>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item label="优先级覆盖" name="priorityOverride" style={{ flex: 1 }}>
              <Select allowClear options={priorityOptions} />
            </Form.Item>
            <Form.Item label="严重级别覆盖" name="severityOverride" style={{ flex: 1 }}>
              <Select allowClear options={severityOptions} />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item label="顺序" name="sortOrder" style={{ flex: 1 }}>
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="启用" name="enabled" valuePropName="checked" style={{ flex: 1 }}>
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title={editingRelease ? '编辑版本发布' : '新增版本发布'}
        open={releaseModalOpen}
        onCancel={() => setReleaseModalOpen(false)}
        onOk={() => void handleSaveRelease()}
        confirmLoading={savingRelease}
        destroyOnHidden
      >
        <Form form={releaseForm} layout="vertical" initialValues={{ platform: 'android', releaseTime: dayjs() }}>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item label="平台" name="platform" rules={[{ required: true, message: '请选择平台' }]} style={{ flex: 1 }}>
              <Select options={[{ label: 'android', value: 'android' }, { label: 'ios', value: 'ios' }]} />
            </Form.Item>
            <Form.Item label="版本号" name="appVersion" rules={[{ required: true, message: '请输入版本号' }]} style={{ flex: 1 }}>
              <Input placeholder="例如：5.0.0" />
            </Form.Item>
          </Space>
          <Space style={{ display: 'flex' }} align="start">
            <Form.Item label="构建号" name="buildNumber" style={{ flex: 1 }}>
              <Input placeholder="例如：50001" />
            </Form.Item>
            <Form.Item label="渠道" name="channel" style={{ flex: 1 }}>
              <Input placeholder="例如：prod / beta" />
            </Form.Item>
          </Space>
          <Form.Item label="发布时间" name="releaseTime" rules={[{ required: true, message: '请选择发布时间' }]}>
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="仓库" name="repoId">
            <Select allowClear options={repoOptions} placeholder="可选，关联代码仓库" />
          </Form.Item>
          <Form.Item label="Commit SHA" name="commitSha">
            <Input placeholder="例如：abc123def456" />
          </Form.Item>
          <Form.Item label="Metadata JSON" name="metadataJson">
            <Input.TextArea rows={4} placeholder='例如：{"branch":"release/5.0.0","operator":"ci"}' />
          </Form.Item>
        </Form>
      </Modal>
    </PageLayout>
  );
};

export default ProjectRoutingCenter;
