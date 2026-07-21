import { logger } from '../../utils/logger';
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Tag,
  Button,
  Typography,
  Breadcrumb,
  Modal,
  Empty,
  Spin,
  Avatar,
  Card,
  Tabs,
  Collapse,
} from 'antd';
import { message } from '../../utils/appMessage';
import {
  ArrowLeftOutlined, UserSwitchOutlined, RobotOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ToolOutlined,
  PauseCircleOutlined, EditOutlined, ReloadOutlined,
  MergeCellsOutlined,
} from '@ant-design/icons';
import {
  getDefect, assignDefect, changeDefectStatus, verifyDefect, rejectDefect, mergeDefect,
  createComment, createFixTask,
  listUsers, listReports, listFixTaskGroups, updateDefect, getDefectAssigneeRecommendations, getDefectAgentRecommendations,
  startManualFix, completeManualFix, abandonManualFix,
} from '../../api';
import { getDefectTokenUsageDetails } from '../../api/defect';
import type { AssigneeRecommendation, AgentRecommendation } from '../../api';
import type { TokenUsageRecord } from '../../api/types';
import { useProject } from '../../contexts/projectContext';
import type { Defect, Comment, FixTask, FixTaskGroup, AnalysisReport, User } from '../../types';
import CollaborationPanel from '../../components/CollaborationPanel';
import MarkdownContent from '../../components/MarkdownContent';
import PageLayout from '../../components/layout/PageLayout';
import dayjs from 'dayjs';
import { getErrorMessage } from '../../utils/error';
import {
  severityLabels, severityColors, priorityColors, statusLabels, statusColors,
  typeLabels,
} from '../../constants/defect';
import './defect-detail.css';
import type { EditDefectForm, ReportSummary } from './types';
import {
  parseStringArray, stringifyPrettyJson, parseReportAnalysis, buildReportMarkdown,
  buildFixTaskMarkdown, normalizeAnalysisFileRefs,
} from './utils';
import DefectStatusSteps from './components/DefectStatusSteps';
import DefectOverview from './components/DefectOverview';
import DefectAnalysisPanel from './components/DefectAnalysisPanel';
import DefectFixTaskPanel from './components/DefectFixTaskPanel';
import DefectTokenUsagePanel from './components/DefectTokenUsagePanel';
import DefectCommentSection from './components/DefectCommentSection';
import DefectModals from './components/DefectModals';
import { useAnalysisStream } from '../../hooks/useAnalysisStream';
import { useSSE, useSSEEvent } from '../../hooks/useSSE';

const { Title } = Typography;



export default function DefectDetail() {
  const { defectId } = useParams<{ defectId: string }>();
  const { project, projectId } = useProject();
  const navigate = useNavigate();

  const [defect, setDefect] = useState<Defect | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [fixTasks, setFixTasks] = useState<FixTask[]>([]);
  const [fixTaskGroups, setFixTaskGroups] = useState<FixTaskGroup[]>([]);
  const [reports, setReports] = useState<AnalysisReport[]>([]);
  const [tokenRecords, setTokenRecords] = useState<TokenUsageRecord[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [commentText, setCommentText] = useState('');
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [selectedAssignee, setSelectedAssignee] = useState<number | null>(null);
  const [assigneeRecommendations, setAssigneeRecommendations] = useState<AssigneeRecommendation[]>([]);
  const [assigneeRecommendLoading, setAssigneeRecommendLoading] = useState(false);
  const [fixModalOpen, setFixModalOpen] = useState(false);
  const [fixBranch, setFixBranch] = useState('');
  const [manualFixCompleteOpen, setManualFixCompleteOpen] = useState(false);
  const [manualFixForm, setManualFixForm] = useState({ description: '', prUrl: '', fixBranch: '' });
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState<EditDefectForm>({
    title: '',
    description: '',
    severity: '',
    priority: '',
    type: '',
    tags: '',
  });
  const [analyzeModalOpen, setAnalyzeModalOpen] = useState(false);
  const [selectedAgentTypes, setSelectedAgentTypes] = useState<string[]>(['frontend']);
  const [agentRecommendations, setAgentRecommendations] = useState<AgentRecommendation[]>([]);
  const [agentRecommendLoading, setAgentRecommendLoading] = useState(false);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const commentEndRef = useRef<HTMLDivElement>(null);
  const defectIdRef = useRef(defectId);
  defectIdRef.current = defectId;
  const loadingRef = useRef(false);
  const isFirstLoad = useRef(true);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      loadingRef.current = false;
    };
  }, []);

  const analysisStream = useAnalysisStream();
  useSSE(defectId ? [`defect:${defectId}`] : []);

  const loadDefect = useCallback(async (force?: boolean) => {
    const id = Number(defectId);
    if (!id || isNaN(id)) {
      message.error('无效的缺陷 ID');
      return;
    }
    if (!force && loadingRef.current) return;
    loadingRef.current = true;
    if (force || !isFirstLoad.current) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const [defectRes, reportsRes, tokenUsageRes, fixTaskGroupsRes] = await Promise.allSettled([
        getDefect(id),
        listReports(id),
        getDefectTokenUsageDetails(id),
        listFixTaskGroups(id),
      ]);
      if (!mountedRef.current) return;
      if (defectRes.status === 'fulfilled') {
        setDefect(defectRes.value.data?.defect || null);
        setComments(defectRes.value.data?.comments || []);
        setFixTasks(defectRes.value.data?.fixTasks || []);
      } else {
        message.error('加载失败');
      }
      if (reportsRes.status === 'fulfilled') {
        setReports(reportsRes.value.data || []);
      } else {
        logger.warn('加载报告列表失败');
      }
      if (tokenUsageRes.status === 'fulfilled') {
        setTokenRecords(tokenUsageRes.value.data || []);
      } else {
        setTokenRecords([]);
        logger.warn('加载 Token 消耗详情失败');
      }
      if (fixTaskGroupsRes.status === 'fulfilled') {
        setFixTaskGroups(fixTaskGroupsRes.value.data || []);
      } else {
        setFixTaskGroups([]);
        logger.warn('加载修复任务组失败');
      }
    } catch {
      message.error('加载失败');
    }
    finally {
      setLoading(false);
      setRefreshing(false);
      loadingRef.current = false;
      isFirstLoad.current = false;
    }
  }, [defectId]);

  const loadUsers = useCallback(async () => {
    try {
      const res = await listUsers({ size: 100 });
      setUsers(res.data?.items || []);
    } catch (err) { logger.error('加载用户列表失败:', err); }
  }, []);

  useEffect(() => {
    void loadDefect();
    void loadUsers();
  }, [loadDefect, loadUsers]);

  useSSEEvent('fix_task:completed', useCallback((data: { defectId?: number }) => {
    if (Number(data?.defectId) === Number(defectIdRef.current)) {
      void loadDefect(true);
    }
  }, [loadDefect]));

  useSSEEvent('fix_task:progress', useCallback((data: { defectId?: number }) => {
    if (Number(data?.defectId) === Number(defectIdRef.current)) {
      void loadDefect(true);
    }
  }, [loadDefect]));

  useSSEEvent('fix_task:failed', useCallback((data: { defectId?: number }) => {
    if (Number(data?.defectId) === Number(defectIdRef.current)) {
      void loadDefect(true);
    }
  }, [loadDefect]));

  useEffect(() => {
    if (defect?.status === 'analyzing' || defect?.status === 'pending_analysis') {
      const id = Number(defectId);
      if (id && !isNaN(id) && !analysisStream.analyzing) {
        analysisStream.restorePolling(id);
      }
    }
  }, [defect?.status, defectId, analysisStream.restorePolling, analysisStream.analyzing]);

  const loadAssigneeRecommendations = useCallback(async () => {
    if (!defectId) return;
    setAssigneeRecommendLoading(true);
    try {
      const res = await getDefectAssigneeRecommendations(Number(defectId), { limit: 3 });
      setAssigneeRecommendations(res.data?.list || []);
    } catch {
      setAssigneeRecommendations([]);
    } finally {
      setAssigneeRecommendLoading(false);
    }
  }, [defectId]);

  const loadAgentRecommendations = useCallback(async () => {
    if (!defectId) return;
    setAgentRecommendLoading(true);
    try {
      const res = await getDefectAgentRecommendations(Number(defectId), { limit: 3 });
      const list = res.data?.list || [];
      setAgentRecommendations(list);
      if (list.length) {
        setSelectedAgentTypes((current) => current.length ? current : [list[0].agentType]);
      }
    } catch {
      setAgentRecommendations([]);
    } finally {
      setAgentRecommendLoading(false);
    }
  }, [defectId]);

  useEffect(() => {
    if (!assignModalOpen) return;
    void loadAssigneeRecommendations();
  }, [assignModalOpen, loadAssigneeRecommendations]);

  useEffect(() => {
    if (!analyzeModalOpen) return;
    void loadAgentRecommendations();
  }, [analyzeModalOpen, loadAgentRecommendations]);

  const handleSubmitComment = async () => {
    if (!commentText.trim()) return;
    try {
      const mentions = users
        .filter(u => commentText.includes(`@${u.nickname || u.username}`))
        .map(u => u.id);
      await createComment(Number(defectId), {
        content: commentText,
        mentions,
      });
      if (defectIdRef.current !== defectId) return;
      setCommentText('');
      loadDefect(true);
      setTimeout(() => commentEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '评论失败'));
    }
  };

  const handleAssign = async () => {
    if (!selectedAssignee) return;
    try {
      const isAdopted = assigneeRecommendations.some((item) => item.userId === selectedAssignee);
      await assignDefect(Number(defectId), {
        assigneeId: selectedAssignee,
        recommendationAdopted: isAdopted,
        recommendationStrategy: isAdopted ? 'assignee_v1' : 'manual',
      });
      if (defectIdRef.current !== defectId) return;
      message.success('已指派');
      setAssignModalOpen(false);
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '指派失败'));
    }
  };

  const handleStatusChange = async (status: string, comment?: string) => {
    try {
      await changeDefectStatus(Number(defectId), { status, comment });
      if (defectIdRef.current !== defectId) return;
      message.success('状态已更新');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleTriggerAnalysis = async () => {
    if (!selectedAgentTypes.length) {
      message.warning('请至少选择一个 AGENT');
      return;
    }
    try {
      setAnalyzeModalOpen(false);
      await analysisStream.startStream(Number(defectId), selectedAgentTypes);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const prevAnalyzingRef = useRef(false);
  useEffect(() => {
    if (prevAnalyzingRef.current && !analysisStream.analyzing) {
      loadDefect(true);
    }
    prevAnalyzingRef.current = analysisStream.analyzing;
  }, [analysisStream.analyzing, loadDefect]);

  const handleVerify = async (passed: boolean, comment?: string) => {
    try {
      await verifyDefect(Number(defectId), { passed, comment });
      message.success(passed ? '验证通过' : '验证未通过');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleMerge = async () => {
    Modal.confirm({
      title: '合并代码',
      content: '确认合并关联的Pull Request并完成缺陷？合并后缺陷状态将变为"已完成"。',
      okText: '确认合并',
      cancelText: '取消',
      onOk: async () => {
        try {
          await mergeDefect(Number(defectId));
          message.success('代码已合并，缺陷已完成');
          loadDefect(true);
        } catch (error: unknown) {
          message.error(getErrorMessage(error, '合并失败'));
        }
      },
    });
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      message.warning('请输入驳回原因');
      return;
    }
    try {
      await rejectDefect(Number(defectId), { reason: rejectReason });
      message.success('已驳回');
      setRejectModalOpen(false);
      setRejectReason('');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '驳回失败'));
    }
  };

  const handleCreateFixTask = async () => {
      if (!defect) return;
      try {
      await createFixTask(Number(defectId), { targetBranch: fixBranch || undefined });
      message.success('已创建修复任务');
      setFixModalOpen(false);
      setFixBranch('');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '创建失败'));
    }
  };

  const handleStartManualFix = async () => {
    try {
      await startManualFix(Number(defectId));
      message.success('已进入人工修复状态');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleCompleteManualFix = async () => {
    try {
      await completeManualFix(Number(defectId), manualFixForm);
      message.success('人工修复已提交');
      setManualFixCompleteOpen(false);
      setManualFixForm({ description: '', prUrl: '', fixBranch: '' });
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '提交失败'));
    }
  };

  const handleAbandonManualFix = async () => {
    try {
      await abandonManualFix(Number(defectId));
      message.success('已放弃人工修复');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  };

  const handleEdit = async () => {
    try {
      await updateDefect(Number(defectId), {
        ...editForm,
        tags: editForm.tags ? editForm.tags.split(',').map(t => t.trim()).filter(Boolean) : undefined,
      });
      message.success('保存成功');
      setEditModalOpen(false);
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '保存失败'));
    }
  };

  const handleRefresh = useCallback(() => loadDefect(true), [loadDefect]);

  const openEditModal = useCallback(() => {
    if (defect) {
      setEditForm({
        title: defect.title,
        description: defect.description || '',
        severity: defect.severity,
        priority: defect.priority,
        type: defect.type || '',
        tags: Array.isArray(defect.tags) ? defect.tags.join(',') : (defect.tags || ''),
      });
      setEditModalOpen(true);
    }
  }, [defect]);

  const handlersRef = useRef({
    handleStatusChange,
    handleStartManualFix,
    handleAbandonManualFix,
    handleVerify,
    handleMerge,
  });
  handlersRef.current = {
    handleStatusChange,
    handleStartManualFix,
    handleAbandonManualFix,
    handleVerify,
    handleMerge,
  };

  const availableActions = useMemo(() => {
    if (!defect) return [];
    const actions: { label: string; icon: React.ReactNode; onClick: () => void; danger?: boolean }[] = [];

    switch (defect.status) {
      case 'new':
      case 'pending_assign':
        actions.push({
          label: '指派',
          icon: <UserSwitchOutlined />,
          onClick: () => {
            setAssignModalOpen(true);
          },
        });
        break;
      case 'pending_analysis':
        actions.push({
          label: '开始分析',
          icon: <RobotOutlined />,
          onClick: () => {
            setAnalyzeModalOpen(true);
            setSelectedAgentTypes([]);
          },
        });
        break;
      case 'analyzing':
        actions.push({
          label: '完成分析',
          icon: <CheckCircleOutlined />,
          onClick: () => handlersRef.current.handleStatusChange('pending_fix'),
        });
        break;
      case 'pending_fix':
        actions.push({
          label: '开始修复',
          icon: <ToolOutlined />,
          onClick: () => {
            setFixModalOpen(true);
          },
        });
        actions.push({
          label: '人工修复',
          icon: <EditOutlined />,
          onClick: () => handlersRef.current.handleStartManualFix(),
        });
        break;
      case 'manual_fixing':
        actions.push({
          label: '提交修复完成',
          icon: <CheckCircleOutlined />,
          onClick: () => setManualFixCompleteOpen(true),
        });
        actions.push({
          label: '放弃人工修复',
          icon: <CloseCircleOutlined />,
          onClick: () => handlersRef.current.handleAbandonManualFix(),
          danger: true,
        });
        break;
      case 'fixing':
        actions.push({
          label: '完成修复',
          icon: <CheckCircleOutlined />,
          onClick: () => handlersRef.current.handleStatusChange('pending_verify'),
        });
        break;
      case 'pending_verify':
        actions.push({
          label: '验证通过',
          icon: <CheckCircleOutlined />,
          onClick: () => handlersRef.current.handleVerify(true),
        });
        actions.push({
          label: '验证不通过',
          icon: <CloseCircleOutlined />,
          onClick: () => handlersRef.current.handleVerify(false),
          danger: true,
        });
        break;
      case 'fixed':
        actions.push({
          label: '合并代码',
          icon: <MergeCellsOutlined />,
          onClick: () => handlersRef.current.handleMerge(),
        });
        actions.push({
          label: '重新打开',
          icon: <ReloadOutlined />,
          onClick: () => handlersRef.current.handleStatusChange('reopened'),
        });
        break;
    }

    if (['pending_analysis', 'analyzing', 'pending_fix', 'fixing', 'pending_verify'].includes(defect.status)) {
      actions.push({
        label: '驳回',
        icon: <CloseCircleOutlined />,
        onClick: () => setRejectModalOpen(true),
        danger: true,
      });
      actions.push({
        label: '暂停',
        icon: <PauseCircleOutlined />,
        onClick: () => handlersRef.current.handleStatusChange('suspended'),
      });
    }

    return actions;
  }, [defect?.status]);

  const sortedComments = useMemo(() => [...comments].sort((left, right) => dayjs(right.createdAt).valueOf() - dayjs(left.createdAt).valueOf()), [comments]);
  const sortedReports = useMemo(() => [...reports].sort((left, right) => dayjs(right.createdAt).valueOf() - dayjs(left.createdAt).valueOf()), [reports]);
  const reportSummaries: ReportSummary[] = useMemo(() => sortedReports.map((report) => {
    const analysisData = parseReportAnalysis(report);
    return {
      report,
      analysisData,
      summaryMarkdown: buildReportMarkdown(report, analysisData),
      rawPayload: stringifyPrettyJson(analysisData || report.analysis || report.solution),
    };
  }), [sortedReports]);
  const latestReport = reportSummaries[0];
  const historicalReports = reportSummaries.slice(1);
  const latestAnalysis = latestReport?.analysisData;
  const latestAffectedFiles = normalizeAnalysisFileRefs(latestAnalysis?.affectedFiles);
  const latestEvidenceFiles = normalizeAnalysisFileRefs(latestAnalysis?.evidenceFiles);
  const latestValidationSuggestions = latestAnalysis?.validationSuggestions?.length
    ? latestAnalysis.validationSuggestions
    : latestReport?.report.validationSuggestions
      ? parseStringArray(latestReport.report.validationSuggestions)
      : [];
  const groupedFixTaskIds = useMemo(() => new Set(fixTaskGroups.flatMap((group) => (group.units || []).map((unit) => unit.id))), [fixTaskGroups]);
  const standaloneFixTasks = useMemo(() => fixTasks.filter((task) => !task.groupId && !groupedFixTaskIds.has(task.id)), [fixTasks, groupedFixTaskIds]);
  const sortedFixTasks = useMemo(() => [...standaloneFixTasks].sort((left, right) => dayjs(right.createdAt).valueOf() - dayjs(left.createdAt).valueOf()), [standaloneFixTasks]);
  const latestFixTask = sortedFixTasks[0];
  const historicalFixTasks = sortedFixTasks.slice(1);
  const latestFixTaskMarkdown = latestFixTask ? buildFixTaskMarkdown(latestFixTask) : '';
  const latestFixTaskRaw = latestFixTask ? stringifyPrettyJson(latestFixTask.result || latestFixTask.plan) : '';
  const latestFixTaskCodeChanges = useMemo(() => {
    if (!latestFixTask?.result) return [];
    try {
      const parsed = JSON.parse(latestFixTask.result);
      return Array.isArray(parsed.codeChanges) ? parsed.codeChanges : [];
    } catch {
      return [];
    }
  }, [latestFixTask?.result]);
  const latestFixTaskValidation = latestFixTask ? parseStringArray(latestFixTask.aiValidationSuggestions) : [];
  const recentComments = sortedComments.slice(0, 3);
  const archivedComments = sortedComments.slice(3);

  if (loading) {
    return <div className="text-center py-20"><Spin size="large" /></div>;
  }

  if (!defect) {
    return <Empty description="缺陷不存在" />;
  }

  return (
    <PageLayout>
      <div className="summary-header">
        <Breadcrumb
          className="mb-2"
          items={[
            { title: <a onClick={() => navigate('/projects')} className="text-slate-400 hover:text-purple-600">项目列表</a> },
            { title: <a onClick={() => navigate(`/projects/${projectId}`)} className="text-slate-400 hover:text-purple-600">{project?.name}</a> },
            { title: <a onClick={() => navigate(`/projects/${projectId}/defects`)} className="text-slate-400 hover:text-purple-600">缺陷管理</a> },
            { title: <span className="text-slate-600 font-medium">{defect.code}</span> },
          ]}
        />

        <div className="flex items-center gap-3 mb-3">
          <Button
            type="text"
            size="small"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(`/projects/${projectId}/defects`)}
            style={{ color: 'var(--slate-400)' }}
          />
          <Title level={4} className="truncate m-0 flex-1 min-w-0">
            {defect.title}
          </Title>
          <Tag
            color={statusColors[defect.status]}
            className="tag-status"
          >
            {statusLabels[defect.status]}
          </Tag>
          {refreshing && <Spin size="small" />}
        </div>

        <div className="flex items-center flex-wrap gap-2 mb-4">
          <Tag color={severityColors[defect.severity]} className="tag-rounded">
            {severityLabels[defect.severity]}
          </Tag>
          <Tag color={priorityColors[defect.priority]} className="tag-rounded">
            {defect.priority}
          </Tag>
          {defect.type ? <Tag className="tag-rounded">{typeLabels[defect.type] || defect.type}</Tag> : null}
          {defect.assignee ? (
            <span className="inline-flex items-center gap-1 text-sm text-slate-600">
              <Avatar size={20} className="avatar-brand">
                {defect.assignee.nickname?.[0] || defect.assignee.username?.[0]}
              </Avatar>
              {defect.assignee.nickname || defect.assignee.username}
            </span>
          ) : (
            <span className="text-sm text-slate-400">未指派</span>
          )}
          <span className="text-xs text-slate-400">
            {defect.code} · {defect.iteration?.name || '未关联迭代'}
          </span>
        </div>

        <DefectStatusSteps defect={defect} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_280px] gap-5">
        <div className="min-w-0">
          <Card className="scene-card overflow-hidden">
            <Tabs
              defaultActiveKey="desc"
              items={[
                {
                  key: 'desc',
                  label: '描述',
                  children: (
                    <div className="tab-content">
                      <MarkdownContent content={defect.description} emptyText="暂无描述" className="max-w-[78ch]" />
                      {defect.tags ? (
                        <div className="mt-4 flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
                          {(defect.tags || []).map((tag: string) => (
                            <Tag key={tag.trim()} className="tag-rounded">{tag.trim()}</Tag>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ),
                },
                {
                  key: 'analysis',
                  label: `AI分析${reportSummaries.length ? ` (${reportSummaries.length})` : ''}`,
                  children: (
                    <DefectAnalysisPanel
                      reportSummaries={reportSummaries}
                      latestReport={latestReport}
                      historicalReports={historicalReports}
                      latestAnalysis={latestAnalysis}
                      analyzing={analysisStream.analyzing}
                      thinkingSteps={analysisStream.steps}
                      currentPhase={analysisStream.currentPhase}
                      analysisError={analysisStream.error}
                      latestAffectedFiles={latestAffectedFiles}
                      latestEvidenceFiles={latestEvidenceFiles}
                      latestValidationSuggestions={latestValidationSuggestions}
                      tokenRecords={tokenRecords}
                      onRefresh={handleRefresh}
                      onStartAnalysis={() => setAnalyzeModalOpen(true)}
                    />
                  ),
                },
                {
                  key: 'fix',
                  label: `修复任务${fixTaskGroups.length + standaloneFixTasks.length ? ` (${fixTaskGroups.length + standaloneFixTasks.length})` : ''}`,
                  children: (
                    <DefectFixTaskPanel
                      fixTaskGroups={fixTaskGroups}
                      fixTasks={standaloneFixTasks}
                      latestFixTask={latestFixTask}
                      historicalFixTasks={historicalFixTasks}
                      latestFixTaskMarkdown={latestFixTaskMarkdown}
                      latestFixTaskCodeChanges={latestFixTaskCodeChanges}
                      latestFixTaskValidation={latestFixTaskValidation}
                      latestFixTaskRaw={latestFixTaskRaw}
                      tokenRecords={tokenRecords}
                    />
                  ),
                },
                {
                  key: 'token-usage',
                  label: 'Token 消耗',
                  children: <DefectTokenUsagePanel defectId={defect.id} />,
                },
                {
                  key: 'activity',
                  label: `动态${sortedComments.length ? ` (${sortedComments.length})` : ''}`,
                  children: (
                    <DefectCommentSection
                      recentComments={recentComments}
                      archivedComments={archivedComments}
                      commentText={commentText}
                      onCommentTextChange={setCommentText}
                      onSubmitComment={handleSubmitComment}
                    />
                  ),
                },
              ]}
            />
          </Card>
        </div>

        <div className="space-y-4">
          <DefectOverview defect={defect} onEdit={openEditModal} />

          {availableActions.length > 0 && (
            <div className="action-card">
              <div className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 pb-2 border-b border-slate-100">
                快速操作
              </div>
              <div className="flex flex-col gap-2">
                {availableActions.map((action, idx) => (
                  <Button
                    key={action.label}
                    block
                    icon={action.icon}
                    onClick={action.onClick}
                    danger={action.danger}
                    className={`action-btn ${idx === 0 && !action.danger ? 'brand-button' : ''}`}
                    type={idx === 0 && !action.danger ? 'primary' : 'default'}
                  >
                    {action.label}
                  </Button>
                ))}
                {analysisStream.analyzing && (
                  <Button
                    block
                    icon={<CloseCircleOutlined />}
                    onClick={() => { void analysisStream.stopStream(); }}
                    danger
                    className="action-btn"
                  >
                    取消分析
                  </Button>
                )}
              </div>
            </div>
          )}

          <div className="action-card">
            <Collapse
              ghost
              items={[{
                key: 'collaboration',
                label: <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">AGENT 协作</span>,
                children: <CollaborationPanel defectId={Number(defectId)} />,
              }]}
            />
          </div>
        </div>
      </div>

      <DefectModals
        assignModalOpen={assignModalOpen}
        selectedAssignee={selectedAssignee}
        assigneeRecommendations={assigneeRecommendations}
        assigneeRecommendLoading={assigneeRecommendLoading}
        users={users}
        onAssignModalCancel={() => setAssignModalOpen(false)}
        onAssignModalOk={handleAssign}
        onSelectedAssigneeChange={setSelectedAssignee}
        analyzeModalOpen={analyzeModalOpen}
        selectedAgentTypes={selectedAgentTypes}
        agentRecommendations={agentRecommendations}
        agentRecommendLoading={agentRecommendLoading}
        onAnalyzeModalCancel={() => setAnalyzeModalOpen(false)}
        onAnalyzeModalOk={handleTriggerAnalysis}
        onSelectedAgentTypesChange={setSelectedAgentTypes}
        fixModalOpen={fixModalOpen}
        fixBranch={fixBranch}
        onFixModalCancel={() => setFixModalOpen(false)}
        onFixModalOk={handleCreateFixTask}
        onFixBranchChange={setFixBranch}
        manualFixCompleteOpen={manualFixCompleteOpen}
        manualFixForm={manualFixForm}
        onManualFixCompleteCancel={() => setManualFixCompleteOpen(false)}
        onManualFixCompleteOk={handleCompleteManualFix}
        onManualFixFormChange={setManualFixForm}
        editModalOpen={editModalOpen}
        editForm={editForm}
        onEditModalCancel={() => setEditModalOpen(false)}
        onEditModalOk={handleEdit}
        onEditFormChange={setEditForm}
        rejectModalOpen={rejectModalOpen}
        rejectReason={rejectReason}
        onRejectModalCancel={() => setRejectModalOpen(false)}
        onRejectModalOk={handleReject}
        onRejectReasonChange={setRejectReason}
      />
    </PageLayout>
  );
}
