import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
} from 'antd';
import {
  BranchesOutlined,
  ExclamationCircleOutlined,
  LinkOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { formatDateTime } from '../../utils/formatDate';
import dayjs from 'dayjs';
import {
  autoTriageClusters,
  batchAssignIssueClusters,
  batchConvertIssueClusters,
  batchIgnoreIssueClusters,
  assignIssueCluster,
  createRegressionItemFromCluster,
  convertIssueCluster,
  getProject,
  ignoreIssueCluster,
  listAppReleases,
  listIssueClusterReleases,
  listIssueClusterReleaseSummary,
  listIssueClusters,
  listIssueSignals,
  mergeIssueCluster,
} from '../../api';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageFilterBar from '../../components/layout/PageFilterBar';
import PageLoadState from '../../components/PageLoadState';
import PageLayout from '../../components/layout/PageLayout';
import { message } from '../../utils/appMessage';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';
import type {
  AppRelease,
  IssueCluster,
  IssueClusterReleaseMatch,
  IssuePoolReleaseSummary,
  IssueSignal,
  User,
} from '../../types';
import type { ProjectDetail } from '../../api';

const statusColorMap: Record<string, string> = {
  new: 'default',
  triaging: 'processing',
  clustered: 'purple',
  converted: 'success',
  ignored: 'warning',
  closed: 'default',
};

const severityColorMap: Record<string, string> = {
  fatal: 'red',
  major: 'volcano',
  normal: 'gold',
  minor: 'blue',
};

const anomalyLevelMap: Record<string, { color: string; label: string }> = {
  baseline: { color: 'default', label: '基线版本' },
  normal: { color: 'blue', label: '平稳' },
  watch: { color: 'gold', label: '关注抬升' },
  high: { color: 'red', label: '异常抬升' },
};

const defectStatusColorMap: Record<string, string> = {
  pending_assign: 'default',
  pending_analysis: 'processing',
  analyzing: 'processing',
  pending_fix: 'warning',
  fixing: 'orange',
  pending_verify: 'cyan',
  fixed: 'success',
};

const releaseMatchModeMap: Record<string, { color: string; label: string }> = {
  exact_build: { color: 'success', label: '精确构建' },
  app_version: { color: 'processing', label: '版本回退' },
};

const sourceTypeLabelMap: Record<string, string> = {
  manual_chat: '对话创建',
  manual_form: '高级模式',
  bugly: 'Bugly',
  webhook: 'Webhook',
  dingtalk: '钉钉',
  feishu: '飞书',
  aliyun_log: '阿里云日志',
};

const statusOptions = [
  { label: '待分诊', value: 'new' },
  { label: '处理中', value: 'triaging' },
  { label: '已聚类', value: 'clustered' },
  { label: '已转缺陷', value: 'converted' },
  { label: '已忽略', value: 'ignored' },
  { label: '已关闭', value: 'closed' },
];

const ProjectIssuePool: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const pid = Number(projectId);
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [merging, setMerging] = useState(false);
  const [convertingId, setConvertingId] = useState<number | null>(null);
  const [batchActing, setBatchActing] = useState(false);
  const [autoTriaging, setAutoTriaging] = useState(false);
  const [creatingRegressionId, setCreatingRegressionId] = useState<number | null>(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [assignVisible, setAssignVisible] = useState(false);
  const [mergeVisible, setMergeVisible] = useState(false);
  const [clusters, setClusters] = useState<IssueCluster[]>([]);
  const [mergeCandidates, setMergeCandidates] = useState<IssueCluster[]>([]);
  const [signals, setSignals] = useState<IssueSignal[]>([]);
  const [releases, setReleases] = useState<AppRelease[]>([]);
  const [releaseMatches, setReleaseMatches] = useState<IssueClusterReleaseMatch[]>([]);
  const [releaseSummary, setReleaseSummary] = useState<IssuePoolReleaseSummary[]>([]);
  const [members, setMembers] = useState<Array<{ memberId: number; userId: number; role: string; username: string; nickname: string; agentTypes: string[] }>>([]);
  const [selectedCluster, setSelectedCluster] = useState<IssueCluster | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [platformFilter, setPlatformFilter] = useState<string>('');
  const [appVersionFilter, setAppVersionFilter] = useState('');
  const [releaseFilter, setReleaseFilter] = useState<number>(0);
  const [anomalyFilter, setAnomalyFilter] = useState<string>('');
  const [keyword, setKeyword] = useState('');
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [assignTargetIds, setAssignTargetIds] = useState<number[]>([]);
  const [assignForm] = Form.useForm<{ ownerUserId: number }>();
  const [mergeForm] = Form.useForm<{ targetClusterId: number; reason?: string }>();


  const memberOptions = useMemo(
    () => members.map((member) => ({
      label: member.nickname || member.username || `用户 #${member.userId}`,
      value: member.userId,
    })),
    [members],
  );

  const mergeTargetOptions = useMemo(
    () => mergeCandidates
      .filter((item) => item.id !== selectedCluster?.id)
      .map((item) => ({ label: `${item.title} (#${item.id})`, value: item.id })),
    [mergeCandidates, selectedCluster?.id],
  );

  const releaseOptions = useMemo(
    () => releases.map((release) => ({
      label: `${release.platform || '未知平台'} / ${release.appVersion || '未知版本'}${release.buildNumber ? ` / ${release.buildNumber}` : ''}${release.channel ? ` / ${release.channel}` : ''}`,
      value: release.id,
    })),
    [releases],
  );

  const logContextSignal = useMemo(() => {
    return [...signals]
      .filter((signal) => signal.logExcerpt || signal.stackTrace)
      .sort((left, right) => dayjs(right.lastSeenAt).valueOf() - dayjs(left.lastSeenAt).valueOf())[0];
  }, [signals]);

  const selectedClusterIds = useMemo(
    () => selectedRowKeys.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0),
    [selectedRowKeys],
  );

  const fetchProjectMeta = useCallback(async () => {
    if (!pid) {
      setLoadError('无效的项目 ID');
      return;
    }
    try {
      const [projectRes, releasesRes] = await Promise.all([
        getProject(pid),
        listAppReleases(pid),
      ]);
      setMembers(projectRes.data?.members || []);
      setReleases(releasesRes.data || []);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '获取项目基础信息失败');
      setLoadError(errorMessage);
      message.error(errorMessage);
    }
  }, [pid]);

  const fetchClusters = useCallback(async () => {
    if (!pid) {
      setLoadError('无效的项目 ID');
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const params = {
        status: statusFilter,
        q: keyword.trim() || undefined,
        platform: platformFilter,
        appVersion: appVersionFilter.trim() || undefined,
        releaseId: releaseFilter,
        anomalyLevel: anomalyFilter,
      };
      const [clusterRes, summaryRes] = await Promise.all([
        listIssueClusters(pid, params),
        listIssueClusterReleaseSummary(pid, params),
      ]);
      const clusterPayload = clusterRes;
      setClusters(clusterPayload.data?.items || []);
      setReleaseSummary(summaryRes.data || []);
    } catch (error: unknown) {
      const errorMessage = getErrorMessage(error, '获取项目问题池失败');
      setLoadError(errorMessage);
      message.error(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [anomalyFilter, appVersionFilter, keyword, pid, platformFilter, releaseFilter, statusFilter]);

  useEffect(() => {
    void fetchProjectMeta();
  }, [fetchProjectMeta]);

  useEffect(() => {
    void fetchClusters();
  }, [fetchClusters]);

  const openDetails = async (cluster: IssueCluster) => {
    setSelectedCluster(cluster);
    setDetailVisible(true);
    setSignals([]);
    setReleaseMatches([]);

    const [signalsResult, releaseResult] = await Promise.allSettled([
      listIssueSignals(pid, cluster.id),
      listIssueClusterReleases(pid, cluster.id),
    ]);

    if (signalsResult.status === 'fulfilled') {
      setSignals(signalsResult.value.data?.items || []);
    } else {
      message.error(getErrorMessage(signalsResult.reason, '获取问题信号失败'));
      setSignals([]);
    }

    if (releaseResult.status === 'fulfilled') {
      setReleaseMatches(releaseResult.value.data || []);
    } else {
      message.error(getErrorMessage(releaseResult.reason, '获取版本影响失败'));
      setReleaseMatches([]);
    }
  };

  const closeDetails = () => {
    setDetailVisible(false);
    setSignals([]);
    setReleaseMatches([]);
  };

  useEffect(() => {
    if (!assignVisible || !selectedCluster) {
      return;
    }
    assignForm.setFieldsValue({ ownerUserId: selectedCluster.ownerUserId || undefined });
  }, [assignForm, assignVisible, selectedCluster]);

  useEffect(() => {
    if (!mergeVisible || !selectedCluster) {
      return;
    }
    mergeForm.setFieldsValue({
      targetClusterId: mergeCandidates.find((item) => item.id !== selectedCluster.id)?.id,
      reason: '疑似重复问题，合并到已有问题簇',
    });
  }, [mergeCandidates, mergeForm, mergeVisible, selectedCluster]);

  const openAssign = (cluster: IssueCluster) => {
    setSelectedCluster(cluster);
    setAssignTargetIds([cluster.id]);
    setAssignVisible(true);
  };

  const openBatchAssign = () => {
    if (!selectedClusterIds.length) {
      return;
    }
    setAssignTargetIds(selectedClusterIds);
    setAssignVisible(true);
  };

  const openMerge = async (cluster: IssueCluster) => {
    setSelectedCluster(cluster);
    setMergeVisible(true);
    try {
      const res = await listIssueClusters(pid, {});
      const payload = res;
      setMergeCandidates(payload.data?.items || []);
    } catch (error: unknown) {
      setMergeCandidates([]);
      message.error(getErrorMessage(error, '获取可合并问题簇失败'));
    }
  };

  const handleAssign = async () => {
    if (!assignTargetIds.length) return;
    try {
      const values = await assignForm.validateFields();
      setAssigning(true);
      if (assignTargetIds.length === 1) {
        await assignIssueCluster(pid, assignTargetIds[0], values);
      } else {
        await batchAssignIssueClusters(pid, {
          clusterIds: assignTargetIds,
          ownerUserId: values.ownerUserId,
        });
      }
      message.success(assignTargetIds.length === 1 ? '问题簇已指派' : `已批量指派 ${assignTargetIds.length} 个问题簇`);
      setAssignVisible(false);
      setAssignTargetIds([]);
      setSelectedRowKeys([]);
      await fetchClusters();
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) {
        return;
      }
      message.error(getErrorMessage(error, '指派问题簇失败'));
    } finally {
      setAssigning(false);
    }
  };

  const handleMerge = async () => {
    if (!selectedCluster) return;
    try {
      const values = await mergeForm.validateFields();
      setMerging(true);
      await mergeIssueCluster(pid, selectedCluster.id, values);
      message.success('问题簇已合并');
      setMergeVisible(false);
      setDetailVisible(false);
      await fetchClusters();
    } catch (error: unknown) {
      if ((error as RequestError | undefined)?.errorFields) {
        return;
      }
      message.error(getErrorMessage(error, '合并问题簇失败'));
    } finally {
      setMerging(false);
    }
  };

  const handleIgnore = async (cluster: IssueCluster) => {
    try {
      await ignoreIssueCluster(pid, cluster.id, { reason: '人工忽略' });
      message.success('问题簇已忽略');
      await fetchClusters();
      if (selectedCluster?.id === cluster.id) {
        setDetailVisible(false);
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '忽略问题簇失败'));
    }
  };

  const handleBatchIgnore = async () => {
    if (!selectedClusterIds.length) {
      return;
    }
    Modal.confirm({
      title: '确定忽略选中的问题簇？',
      content: `将忽略 ${selectedClusterIds.length} 个问题簇。`,
      onOk: async () => {
        setBatchActing(true);
        try {
          await batchIgnoreIssueClusters(pid, {
            clusterIds: selectedClusterIds,
            reason: '批量忽略',
          });
          message.success(`已忽略 ${selectedClusterIds.length} 个问题簇`);
          setSelectedRowKeys([]);
          await fetchClusters();
        } catch (error: unknown) {
          message.error(getErrorMessage(error, '批量忽略问题簇失败'));
        } finally {
          setBatchActing(false);
        }
      },
    });
  };

  const handleConvert = async (cluster: IssueCluster) => {
    setConvertingId(cluster.id);
    try {
      const res = await convertIssueCluster(pid, cluster.id);
      const defectId = res.data?.defect?.id;
      message.success('问题簇已转为缺陷');
      await fetchClusters();
      if (defectId) {
        navigate(`/projects/${pid}/defects/${defectId}`);
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '问题簇转缺陷失败'));
    } finally {
      setConvertingId(null);
    }
  };

  const handleAutoTriage = async () => {
    Modal.confirm({
      title: '自动分诊',
      content: '系统将根据路由规则自动对未分诊的问题簇执行分诊操作。确认继续？',
      okText: '确认执行',
      cancelText: '取消',
      onOk: async () => {
        setAutoTriaging(true);
        try {
          const res = await autoTriageClusters(pid);
          message.success(res.data?.message || `自动分诊完成：成功 ${res.data?.triaged || 0} 个`);
          await fetchClusters();
        } catch (error: unknown) {
          message.error(getErrorMessage(error, '自动分诊失败'));
        } finally {
          setAutoTriaging(false);
        }
      },
    });
  };

  const handleBatchConvert = async () => {
    if (!selectedClusterIds.length) {
      return;
    }
    setBatchActing(true);
    try {
      const res = await batchConvertIssueClusters(pid, { clusterIds: selectedClusterIds });
      const defectIds = Array.isArray(res.data?.defectIds) ? res.data.defectIds : [];
      message.success(`已转缺陷 ${selectedClusterIds.length} 个问题簇`);
      setSelectedRowKeys([]);
      await fetchClusters();
      if (defectIds.length === 1) {
        navigate(`/projects/${pid}/defects/${defectIds[0]}`);
      }
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '批量转缺陷失败'));
    } finally {
      setBatchActing(false);
    }
  };

  const openLinkedDefect = (cluster: IssueCluster) => {
    if (!cluster.linkedDefectId) {
      return;
    }
    navigate(`/projects/${pid}/defects/${cluster.linkedDefectId}`);
  };

  const routingConfidenceText = (value?: number) => {
    if (typeof value !== 'number' || Number.isNaN(value)) {
      return '未评估';
    }
    return `${Math.round(value * 100)}%`;
  };

  const sourceTypeLabel = (value?: string) => {
    if (!value) {
      return '未知来源';
    }
    return sourceTypeLabelMap[value] || value;
  };

  const openClusterCount = clusters.filter((item) => ['new', 'triaging', 'clustered'].includes(item.status)).length;
  const anomalyClusterCount = clusters.filter((item) => item.anomalyLevel === 'high' || item.anomalyLevel === 'watch').length;
  const linkedDefectCount = clusters.filter((item) => item.defect || item.linkedDefectId).length;
  const hasActiveFilters = Boolean(
    statusFilter || platformFilter || appVersionFilter || anomalyFilter || releaseFilter || keyword.trim(),
  );

  const clearFilters = () => {
    setStatusFilter('');
    setPlatformFilter('');
    setAppVersionFilter('');
    setAnomalyFilter('');
    setReleaseFilter(0);
    setKeyword('');
  };

  const handleCreateRegression = async (cluster: IssueCluster) => {
    setCreatingRegressionId(cluster.id);
    try {
      await createRegressionItemFromCluster(pid, cluster.id);
      message.success('回归预防项已创建');
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '创建回归预防项失败'));
    } finally {
      setCreatingRegressionId(null);
    }
  };

  return (
    <PageLayout>
      <PageMetricSection
        items={[
          { key: 'total', label: '问题簇总量', value: clusters.length, icon: <BranchesOutlined />, tone: 'purple' },
          { key: 'open', label: '待分诊', value: openClusterCount, icon: <ExclamationCircleOutlined />, tone: 'amber' },
          { key: 'linked', label: '已进缺陷流', value: linkedDefectCount, icon: <LinkOutlined />, tone: 'cyan' },
          { key: 'anomaly', label: '异常风险簇', value: anomalyClusterCount, icon: <ExclamationCircleOutlined />, tone: 'rose' },
        ]}
        actions={(
          <Button icon={<ReloadOutlined />} onClick={() => void fetchClusters()}>
            刷新列表
          </Button>
        )}
      />

      <PageFilterBar
        compact
        filters={(
          <>
            <Select
              data-testid="issue-pool-status-filter"
              allowClear
              value={statusFilter}
              onChange={(value) => setStatusFilter(value)}
              style={{ width: 120 }}
              placeholder="按状态筛选"
              options={statusOptions}
            />
            <Select
              data-testid="issue-pool-platform-filter"
              allowClear
              value={platformFilter}
              onChange={(value) => setPlatformFilter(value)}
              style={{ width: 110 }}
              placeholder="按平台筛选"
              options={[
                { label: 'Android', value: 'android' },
                { label: 'iOS', value: 'ios' },
              ]}
            />
            <Input
              data-testid="issue-pool-version-filter"
              allowClear
              value={appVersionFilter}
              onChange={(event) => setAppVersionFilter(event.target.value)}
              style={{ width: '100%', maxWidth: 130 }}
              placeholder="按版本号筛选"
            />
            <Select
              data-testid="issue-pool-anomaly-filter"
              allowClear
              value={anomalyFilter}
              onChange={(value) => setAnomalyFilter(value)}
              style={{ width: 120 }}
              placeholder="按异常筛选"
              options={[
                { label: '基线版本', value: 'baseline' },
                { label: '平稳', value: 'normal' },
                { label: '关注抬升', value: 'watch' },
                { label: '异常抬升', value: 'high' },
              ]}
            />
            <Select
              data-testid="issue-pool-release-filter"
              allowClear
              value={releaseFilter}
              onChange={(value) => setReleaseFilter(value)}
              style={{ width: 180 }}
              placeholder="按已登记发布筛选"
              options={releaseOptions}
            />
            <Input
              data-testid="issue-pool-search"
              allowClear
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索标题 / 摘要"
              prefix={<SearchOutlined className="text-slate-400" />}
              style={{ width: '100%', maxWidth: 180 }}
            />
            {hasActiveFilters ? (
              <Button size="small" onClick={clearFilters}>
                清除筛选
              </Button>
            ) : null}
          </>
        )}
        result={<Tag>{clusters.length} 条结果</Tag>}
      />

      <Card
        className="scene-card"
        title="问题簇列表"
      >
        <div style={{ color: '#64748b', marginBottom: 16 }}>
          外部渠道接入的问题会先汇聚到问题池。你可以在这里完成指派、合并、忽略和转缺陷，再进入现有分析与修复流程。
        </div>

        {loadError ? (
          <PageLoadState subTitle={loadError} onRetry={() => { void fetchProjectMeta(); void fetchClusters(); }} />
        ) : (
        <>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, gap: 12, flexWrap: 'wrap' }}>
          <div style={{ color: '#64748b', fontSize: 13 }}>
            {selectedClusterIds.length ? `已选择 ${selectedClusterIds.length} 个问题簇` : '可多选后批量指派、忽略或转缺陷'}
          </div>
          <Space wrap>
            <Button onClick={openBatchAssign} disabled={!selectedClusterIds.length} loading={batchActing}>
              批量指派
            </Button>
            <Button onClick={() => void handleBatchIgnore()} disabled={!selectedClusterIds.length} loading={batchActing}>
              批量忽略
            </Button>
            <Button
              type="primary"
              onClick={() => void handleBatchConvert()}
              disabled={!selectedClusterIds.length}
              loading={batchActing}
            >
              批量转缺陷
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              onClick={() => void handleAutoTriage()}
              loading={autoTriaging}
            >
              自动分诊
            </Button>
          </Space>
        </div>

        <div data-testid="issue-pool-release-summary-card">
          <Card
            size="small"
            title="版本影响汇总"
            style={{ marginBottom: 16 }}
          >
            {releaseSummary.length ? (
              <Table
                rowKey={(record) => record.release.id}
                dataSource={releaseSummary}
                pagination={false}
                size="small"
                columns={[
                  {
                    title: '版本发布',
                    key: 'release',
                    render: (_: unknown, record: IssuePoolReleaseSummary) => (
                      <Space direction="vertical" size={2}>
                        <span>{record.release.platform || '未识别'}</span>
                        <span style={{ color: '#64748b' }}>
                          {record.release.appVersion || '未识别'}
                          {record.release.buildNumber ? ` / ${record.release.buildNumber}` : ''}
                        </span>
                      </Space>
                    ),
                  },
                  {
                    title: '渠道',
                    dataIndex: ['release', 'channel'],
                    width: 120,
                    render: (value?: string) => value || <span style={{ color: '#cbd5e1' }}>未登记</span>,
                  },
                  { title: '问题簇', dataIndex: 'clusterCount', width: 100 },
                  { title: '信号数', dataIndex: 'signalCount', width: 100 },
                  { title: '影响用户', dataIndex: 'affectedUserCount', width: 110 },
                  {
                    title: '最近发生',
                    dataIndex: 'lastSeenAt',
                    width: 180,
                    render: (value: string) => formatDateTime(value),
                  },
                ]}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={releaseFilter ? '当前筛选下未命中已登记版本' : '当前还没有版本影响汇总'}
              />
            )}
          </Card>
        </div>

        <Table
          rowKey="id"
          loading={loading}
          dataSource={clusters}
          rowSelection={{
            selectedRowKeys,
            onChange: (keys) => setSelectedRowKeys(keys),
          }}
          locale={{
            emptyText: (
              <Empty description="当前还没有接入问题信号">
                <Button type="primary" onClick={() => navigate(`/projects/${pid}/integrations`)}>
                  去配置信号接入
                </Button>
              </Empty>
            ),
          }}
          pagination={false}
          columns={[
            {
              title: '问题簇',
              dataIndex: 'title',
              render: (value: string, record: IssueCluster) => (
                <Space direction="vertical" size={2}>
                  <Space size={8}>
                    <BranchesOutlined style={{ color: '#1677ff' }} />
                    <span style={{ fontWeight: 600 }}>{value}</span>
                  </Space>
                  <Space size={8} wrap>
                    <span style={{ fontSize: 12, color: '#64748b' }}>Cluster #{record.id}</span>
                    {record.primarySourceType ? (
                      <Tag color="geekblue">{sourceTypeLabel(record.primarySourceType)}</Tag>
                    ) : null}
                  </Space>
                </Space>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 120,
              render: (value: string) => <Tag color={statusColorMap[value] || 'default'}>{value}</Tag>,
            },
            {
              title: '平台 / 版本',
              key: 'version',
              width: 180,
              render: (_: unknown, record: IssueCluster) => (
                <Space direction="vertical" size={2}>
                  <span>{record.platform || '未识别'}</span>
                  <span style={{ fontSize: 12, color: '#64748b' }}>
                    {record.appVersion || '未识别'}
                    {record.buildNumber ? ` / ${record.buildNumber}` : ''}
                  </span>
                </Space>
              ),
            },
            { title: '信号数', dataIndex: 'signalCount', width: 100 },
            { title: '影响用户', dataIndex: 'affectedUserCount', width: 100 },
            {
              title: '发布视角',
              key: 'releaseMatch',
              width: 140,
              render: (_: unknown, record: IssueCluster) => (
                record.releaseMatchCount ? (
                  <Tag color="success">命中 {record.releaseMatchCount} 个版本</Tag>
                ) : (
                  <span style={{ color: '#94a3b8' }}>未登记版本</span>
                )
              ),
            },
            {
              title: '异常级别',
              key: 'anomalyLevel',
              width: 130,
              render: (_: unknown, record: IssueCluster) => {
                const config = record.anomalyLevel ? anomalyLevelMap[record.anomalyLevel] : undefined;
                return config ? (
                  <Tag color={config.color}>{config.label}</Tag>
                ) : (
                  <span style={{ color: '#94a3b8' }}>未评估</span>
                );
              },
            },
            {
              title: '严重级别',
              dataIndex: 'severity',
              width: 120,
              render: (value?: string) => value ? <Tag color={severityColorMap[value] || 'default'}>{value}</Tag> : <span style={{ color: '#cbd5e1' }}>未识别</span>,
            },
            {
              title: '负责人',
              key: 'owner',
              width: 140,
              render: (_: unknown, record: IssueCluster) => record.owner?.nickname || record.owner?.username || <span style={{ color: '#cbd5e1' }}>未指派</span>,
            },
            {
              title: '路由建议',
              key: 'routing',
              width: 220,
              render: (_: unknown, record: IssueCluster) => (
                <Space direction="vertical" size={2}>
                  <Space size={6} wrap>
                    <Tag color={record.routingConfidence && record.routingConfidence >= 0.85 ? 'success' : 'processing'}>
                      置信度 {routingConfidenceText(record.routingConfidence)}
                    </Tag>
                    {record.routingRuleId ? <Tag color="purple">规则 #{record.routingRuleId}</Tag> : null}
                  </Space>
                  <span style={{ color: '#64748b', fontSize: 12 }}>
                    {record.routingEvidence?.[0] || '暂无建议依据'}
                  </span>
                </Space>
              ),
            },
            {
              title: '处置进展',
              key: 'progress',
              width: 220,
              render: (_: unknown, record: IssueCluster) => (
                record.defect ? (
                  <Space direction="vertical" size={2}>
                    <span style={{ fontWeight: 600 }}>{record.defect.code}</span>
                    <Space size={6} wrap>
                      <Tag color={defectStatusColorMap[record.defect.status] || 'default'}>
                        {record.defect.status}
                      </Tag>
                      <span style={{ color: '#64748b', fontSize: 12 }}>
                        {record.defect.assignee?.nickname || record.defect.assignee?.username || '未指派'}
                      </span>
                    </Space>
                  </Space>
                ) : (
                  <span style={{ color: '#94a3b8' }}>未进入缺陷流</span>
                )
              ),
            },
            {
              title: '最近发生',
              dataIndex: 'lastSeenAt',
              width: 180,
              render: (value: string) => formatDateTime(value),
            },
            {
              title: '操作',
              key: 'action',
              width: 360,
              render: (_: unknown, record: IssueCluster) => (
                <Space wrap>
                  <Button type="link" onClick={() => void openDetails(record)}>详情</Button>
                  <Button type="link" onClick={() => openAssign(record)}>指派</Button>
                  <Button type="link" onClick={() => void openMerge(record)}>合并</Button>
                  <Popconfirm title="确定忽略该问题簇？" onConfirm={() => void handleIgnore(record)}>
                    <Button type="link">忽略</Button>
                  </Popconfirm>
                  {record.linkedDefectId ? (
                    <Button type="link" icon={<LinkOutlined />} onClick={() => openLinkedDefect(record)}>
                      查看缺陷
                    </Button>
                  ) : (
                    <Button
                      type="link"
                      icon={<LinkOutlined />}
                      loading={convertingId === record.id}
                      onClick={() => void handleConvert(record)}
                    >
                      转缺陷
                    </Button>
                  )}
                </Space>
              ),
            },
          ]}
        />
        </>
        )}
      </Card>

      <Drawer
        title={selectedCluster ? `问题簇详情 · ${selectedCluster.title}` : '问题簇详情'}
        size="large"
        open={detailVisible}
        onClose={closeDetails}
      >
        {selectedCluster ? (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="状态">
                <Tag color={statusColorMap[selectedCluster.status] || 'default'}>{selectedCluster.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="严重级别">
                {selectedCluster.severity ? <Tag color={severityColorMap[selectedCluster.severity] || 'default'}>{selectedCluster.severity}</Tag> : '未识别'}
              </Descriptions.Item>
              <Descriptions.Item label="信号数">{selectedCluster.signalCount}</Descriptions.Item>
              <Descriptions.Item label="影响用户">{selectedCluster.affectedUserCount}</Descriptions.Item>
              <Descriptions.Item label="负责人">
                {selectedCluster.owner?.nickname || selectedCluster.owner?.username || '未指派'}
              </Descriptions.Item>
              <Descriptions.Item label="路由建议">
                <Space size={6} wrap>
                  <Tag color={selectedCluster.routingConfidence && selectedCluster.routingConfidence >= 0.85 ? 'success' : 'processing'}>
                    置信度 {routingConfidenceText(selectedCluster.routingConfidence)}
                  </Tag>
                  {selectedCluster.routingRuleId ? <Tag color="purple">规则 #{selectedCluster.routingRuleId}</Tag> : null}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="最近发生">
                {formatDateTime(selectedCluster.lastSeenAt)}
              </Descriptions.Item>
              <Descriptions.Item label="摘要">
                {selectedCluster.summary || '暂无摘要'}
              </Descriptions.Item>
            </Descriptions>

            <Card size="small" title="建议依据">
              {selectedCluster.routingEvidence?.length ? (
                <ul style={{ margin: 0, paddingLeft: 18, color: '#334155' }}>
                  {selectedCluster.routingEvidence.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有可解释的路由建议依据" />
              )}
            </Card>

            <Card size="small" title="原始信号">
              <Table
                rowKey="id"
                dataSource={signals}
                pagination={false}
                locale={{ emptyText: '暂无原始信号' }}
                columns={[
                  { title: '事件ID', dataIndex: 'sourceEventId', width: 160 },
                  {
                    title: '来源',
                    dataIndex: 'sourceType',
                    width: 120,
                    render: (value: string) => sourceTypeLabel(value),
                  },
                  { title: '标题', dataIndex: 'title' },
                  { title: '平台', dataIndex: 'platform', width: 100 },
                  { title: '版本', dataIndex: 'appVersion', width: 120 },
                  { title: '次数', dataIndex: 'occurrenceCount', width: 80 },
                  {
                    title: '最近发生',
                    dataIndex: 'lastSeenAt',
                    width: 180,
                    render: (value: string) => formatDateTime(value),
                  },
                ]}
              />
            </Card>

            <Card size="small" title="版本影响">
              {releaseMatches.length ? (
                <Table
                  rowKey={(record) => record.release.id}
                  dataSource={releaseMatches}
                  pagination={false}
                  size="small"
                  columns={[
                    {
                      title: '平台 / 版本 / 构建',
                      key: 'version',
                      render: (_: unknown, record: IssueClusterReleaseMatch) => (
                        <Space direction="vertical" size={2}>
                          <span>{record.release.platform || '未识别'}</span>
                          <span style={{ color: '#64748b' }}>
                            {record.release.appVersion || '未识别'}
                            {record.release.buildNumber ? ` / ${record.release.buildNumber}` : ''}
                          </span>
                        </Space>
                      ),
                    },
                    {
                      title: '渠道',
                      dataIndex: ['release', 'channel'],
                      width: 120,
                      render: (value?: string) => value || <span style={{ color: '#cbd5e1' }}>未登记</span>,
                    },
                    {
                      title: '发布时间',
                      dataIndex: ['release', 'releaseTime'],
                      width: 180,
                      render: (value: string) => value ? formatDateTime(value) : <span style={{ color: '#cbd5e1' }}>未登记</span>,
                    },
                    {
                      title: '匹配方式',
                      dataIndex: 'matchMode',
                      width: 120,
                      render: (value: string) => {
                        const config = releaseMatchModeMap[value] || { color: 'default', label: value };
                        return <Tag color={config.color}>{config.label}</Tag>;
                      },
                    },
                    { title: '信号数', dataIndex: 'signalCount', width: 90 },
                    { title: '影响用户', dataIndex: 'affectedUserCount', width: 100 },
                  ]}
                />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未命中已登记版本"
                />
              )}
            </Card>

            {selectedCluster.defect ? (
              <div data-testid="issue-pool-defect-progress-card">
                <Card size="small" title="修复闭环进展">
                  <Descriptions bordered column={1} size="small">
                    <Descriptions.Item label="缺陷编号">
                      <Space size={8}>
                        <span style={{ fontWeight: 600 }}>{selectedCluster.defect.code}</span>
                        <Tag color={defectStatusColorMap[selectedCluster.defect.status] || 'default'}>
                          {selectedCluster.defect.status}
                        </Tag>
                      </Space>
                    </Descriptions.Item>
                    <Descriptions.Item label="标题">
                      {selectedCluster.defect.title}
                    </Descriptions.Item>
                    <Descriptions.Item label="负责人">
                      {selectedCluster.defect.assignee?.nickname || selectedCluster.defect.assignee?.username || '未指派'}
                    </Descriptions.Item>
                    <Descriptions.Item label="报告人">
                      {selectedCluster.defect.reporter?.nickname || selectedCluster.defect.reporter?.username || '未识别'}
                    </Descriptions.Item>
                    <Descriptions.Item label="创建时间">
                      {formatDateTime(selectedCluster.defect.createdAt)}
                    </Descriptions.Item>
                    <Descriptions.Item label="最后更新">
                      {formatDateTime(selectedCluster.defect.updatedAt)}
                    </Descriptions.Item>
                  </Descriptions>
                  <div style={{ marginTop: 12 }}>
                    <Button
                      data-testid="issue-pool-defect-progress-open"
                      type="link"
                      icon={<LinkOutlined />}
                      onClick={() => openLinkedDefect(selectedCluster)}
                      style={{ paddingInline: 0 }}
                    >
                      查看缺陷详情
                    </Button>
                  </div>
                </Card>
              </div>
            ) : null}

            {logContextSignal ? (
              <Card size="small" title="日志上下文">
                  <Descriptions bordered column={1} size="small">
                  <Descriptions.Item label="来源">{sourceTypeLabel(logContextSignal.sourceType)}</Descriptions.Item>
                  <Descriptions.Item label="最近发生">
                    {formatDateTime(logContextSignal.lastSeenAt)}
                  </Descriptions.Item>
                  <Descriptions.Item label="平台">{logContextSignal.platform || '未识别'}</Descriptions.Item>
                  <Descriptions.Item label="版本">
                    {logContextSignal.appVersion || '未识别'}
                    {logContextSignal.buildNumber ? ` / ${logContextSignal.buildNumber}` : ''}
                  </Descriptions.Item>
                  <Descriptions.Item label="日志摘要">
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'SFMono-Regular, Consolas, monospace' }}>
                      {logContextSignal.logExcerpt || '暂无日志摘要'}
                    </pre>
                  </Descriptions.Item>
                  <Descriptions.Item label="堆栈">
                    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'SFMono-Regular, Consolas, monospace' }}>
                      {logContextSignal.stackTrace || '暂无堆栈'}
                    </pre>
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            ) : null}

            <Space>
              <Button data-testid="issue-pool-drawer-assign" onClick={() => openAssign(selectedCluster)}>指派</Button>
              <Button data-testid="issue-pool-drawer-merge" onClick={() => void openMerge(selectedCluster)}>合并</Button>
              <Button
                data-testid="issue-pool-create-regression"
                loading={creatingRegressionId === selectedCluster.id}
                onClick={() => void handleCreateRegression(selectedCluster)}
              >
                生成回归项
              </Button>
              <Popconfirm title="确定忽略该问题簇？" onConfirm={() => void handleIgnore(selectedCluster)}>
                <Button icon={<ExclamationCircleOutlined />}>忽略</Button>
              </Popconfirm>
              {selectedCluster.linkedDefectId ? (
                <Button
                  data-testid="issue-pool-open-defect"
                  type="primary"
                  icon={<LinkOutlined />}
                  onClick={() => openLinkedDefect(selectedCluster)}
                >
                  查看缺陷
                </Button>
              ) : (
                <Button
                  data-testid="issue-pool-drawer-convert"
                  type="primary"
                  loading={convertingId === selectedCluster.id}
                  onClick={() => void handleConvert(selectedCluster)}
                >
                  转为缺陷
                </Button>
              )}
            </Space>
          </Space>
        ) : null}
      </Drawer>

      <Modal
        title="指派问题簇"
        open={assignVisible}
        onCancel={() => {
          setAssignVisible(false);
          setAssignTargetIds([]);
        }}
        onOk={() => void handleAssign()}
        okText="确认指派"
        cancelText="取消"
        confirmLoading={assigning}
        destroyOnHidden
      >
        <Form form={assignForm} layout="vertical">
          <Form.Item label="负责人" name="ownerUserId" rules={[{ required: true, message: '请选择负责人' }]}>
            <Select data-testid="issue-pool-assign-owner" options={memberOptions} placeholder="请选择项目成员" />
          </Form.Item>
          {assignTargetIds.length === 1 && selectedCluster ? (
            <Form.Item>
              <Input.TextArea value={selectedCluster.summary} rows={4} readOnly />
            </Form.Item>
          ) : (
            <div style={{ color: '#64748b' }}>
              将把所选 {assignTargetIds.length} 个问题簇统一指派给该负责人。
            </div>
          )}
        </Form>
      </Modal>

      <Modal
        title="合并问题簇"
        open={mergeVisible}
        onCancel={() => setMergeVisible(false)}
        onOk={() => void handleMerge()}
        okText="确认合并"
        cancelText="取消"
        confirmLoading={merging}
        destroyOnHidden
      >
        <Form form={mergeForm} layout="vertical">
          <Form.Item label="目标问题簇" name="targetClusterId" rules={[{ required: true, message: '请选择目标问题簇' }]}>
            <Select data-testid="issue-pool-merge-target" options={mergeTargetOptions} placeholder="请选择要合并到的目标问题簇" />
          </Form.Item>
          <Form.Item label="原因" name="reason">
            <Input.TextArea rows={4} placeholder="例如：同一崩溃指纹的重复问题" />
          </Form.Item>
        </Form>
      </Modal>
    </PageLayout>
  );
};

export default ProjectIssuePool;
