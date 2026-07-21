import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Modal } from 'antd';
import { message } from '../../utils/appMessage';
import {
  assignDefect, changeDefectStatus, verifyDefect, rejectDefect, mergeDefect,
  createComment, createFixTask,
  updateDefect, getDefectAssigneeRecommendations, getDefectAgentRecommendations,
  startManualFix, completeManualFix, abandonManualFix, reopenDefect,
} from '../../api';
import type { AssigneeRecommendation, AgentRecommendation } from '../../api';
import { getErrorMessage } from '../../utils/error';
import type { Defect, User } from '../../types';
import type { EditDefectForm } from './types';
import {
  UserSwitchOutlined, RobotOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ToolOutlined,
  PauseCircleOutlined, EditOutlined, ReloadOutlined,
  MergeCellsOutlined,
} from '@ant-design/icons';

interface UseDefectActionsParams {
  defectId: string | undefined;
  defect: Defect | null;
  loadDefect: (force?: boolean) => void;
  users: User[];
  commentEndRef: React.RefObject<HTMLDivElement | null>;
  onStartAnalysis: (agentTypes: string[]) => void;
}

export interface DefectAction {
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
  danger?: boolean;
}

export interface UseDefectActionsReturn {
  // Handlers
  handleAssign: () => Promise<void>;
  handleStatusChange: (status: string, comment?: string) => Promise<void>;
  handleTriggerAnalysis: () => Promise<void>;
  handleVerify: (passed: boolean, comment?: string) => Promise<void>;
  handleMerge: () => void;
  handleReject: () => Promise<void>;
  handleCreateFixTask: () => Promise<void>;
  handleStartManualFix: () => Promise<void>;
  handleCompleteManualFix: () => Promise<void>;
  handleAbandonManualFix: () => Promise<void>;
  handleEdit: () => Promise<void>;
  handleSubmitComment: () => Promise<void>;
  handleRefresh: () => void;
  openEditModal: () => void;

  // Modal states
  assignModalOpen: boolean;
  setAssignModalOpen: (open: boolean) => void;
  selectedAssignee: number | null;
  setSelectedAssignee: (id: number | null) => void;
  assigneeRecommendations: AssigneeRecommendation[];
  assigneeRecommendLoading: boolean;
  fixModalOpen: boolean;
  setFixModalOpen: (open: boolean) => void;
  fixBranch: string;
  setFixBranch: (branch: string) => void;
  manualFixCompleteOpen: boolean;
  setManualFixCompleteOpen: (open: boolean) => void;
  manualFixForm: { description: string; prUrl: string; fixBranch: string };
  setManualFixForm: (form: { description: string; prUrl: string; fixBranch: string }) => void;
  editModalOpen: boolean;
  setEditModalOpen: (open: boolean) => void;
  editForm: EditDefectForm;
  setEditForm: (form: EditDefectForm) => void;
  analyzeModalOpen: boolean;
  setAnalyzeModalOpen: (open: boolean) => void;
  selectedAgentTypes: string[];
  setSelectedAgentTypes: (types: string[]) => void;
  agentRecommendations: AgentRecommendation[];
  agentRecommendLoading: boolean;
  rejectModalOpen: boolean;
  setRejectModalOpen: (open: boolean) => void;
  rejectReason: string;
  setRejectReason: (reason: string) => void;

  // Computed
  availableActions: DefectAction[];
  commentText: string;
  setCommentText: (text: string) => void;
}

export default function useDefectActions({
  defectId,
  defect,
  loadDefect,
  users,
  commentEndRef,
  onStartAnalysis,
}: UseDefectActionsParams): UseDefectActionsReturn {

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

  const defectIdRef = useRef(defectId);
  defectIdRef.current = defectId;
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // --- Recommendation loaders ---

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

  // --- Action handlers ---

  const handleSubmitComment = useCallback(async () => {
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
  }, [commentText, defectId, users, loadDefect, commentEndRef]);

  const handleAssign = useCallback(async () => {
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
  }, [selectedAssignee, assigneeRecommendations, defectId, loadDefect]);

  const handleStatusChange = useCallback(async (status: string, comment?: string) => {
    try {
      await changeDefectStatus(Number(defectId), { status, comment });
      if (defectIdRef.current !== defectId) return;
      message.success('状态已更新');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  }, [defectId, loadDefect]);

  const handleTriggerAnalysis = useCallback(async () => {
    if (!selectedAgentTypes.length) {
      message.warning('请至少选择一个 AGENT');
      return;
    }
    onStartAnalysis(selectedAgentTypes);
    message.success('分析任务已启动，正在等待AI响应...');
    setAnalyzeModalOpen(false);
  }, [selectedAgentTypes, onStartAnalysis]);

  const handleVerify = useCallback(async (passed: boolean, comment?: string) => {
    try {
      await verifyDefect(Number(defectId), { passed, comment });
      message.success(passed ? '验证通过' : '验证未通过');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  }, [defectId, loadDefect]);

  const handleMerge = useCallback(() => {
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
  }, [defectId, loadDefect]);

  const handleReject = useCallback(async () => {
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
  }, [rejectReason, defectId, loadDefect]);

  const handleCreateFixTask = useCallback(async () => {
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
  }, [defect, defectId, fixBranch, loadDefect]);

  const handleStartManualFix = useCallback(async () => {
    try {
      await startManualFix(Number(defectId));
      message.success('已进入人工修复状态');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  }, [defectId, loadDefect]);

  const handleCompleteManualFix = useCallback(async () => {
    try {
      await completeManualFix(Number(defectId), manualFixForm);
      message.success('人工修复已提交');
      setManualFixCompleteOpen(false);
      setManualFixForm({ description: '', prUrl: '', fixBranch: '' });
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '提交失败'));
    }
  }, [defectId, manualFixForm, loadDefect]);

  const handleAbandonManualFix = useCallback(async () => {
    try {
      await abandonManualFix(Number(defectId));
      message.success('已放弃人工修复');
      loadDefect(true);
    } catch (error: unknown) {
      message.error(getErrorMessage(error, '操作失败'));
    }
  }, [defectId, loadDefect]);

  const handleEdit = useCallback(async () => {
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
  }, [defectId, editForm, loadDefect]);

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

  // --- Ref-based handlers to avoid stale closures in availableActions ---

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

  // --- Computed: availableActions ---

  const availableActions = useMemo<DefectAction[]>(() => {
    if (!defect) return [];
    const actions: DefectAction[] = [];

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
          onClick: () => {
            Modal.confirm({
              title: '重新打开缺陷',
              content: '确认重新打开此缺陷？缺陷将回到待分析状态。',
              okText: '确认',
              cancelText: '取消',
              onOk: async () => {
                try {
                  await reopenDefect(Number(defectId), { targetStatus: 'pending_analysis' });
                  message.success('已重新打开');
                  loadDefect(true);
                } catch (error: unknown) {
                  message.error(getErrorMessage(error, '操作失败'));
                }
              },
            });
          },
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
  }, [defect?.status, defectId, loadDefect]);

  return {
    // Handlers
    handleAssign,
    handleStatusChange,
    handleTriggerAnalysis,
    handleVerify,
    handleMerge,
    handleReject,
    handleCreateFixTask,
    handleStartManualFix,
    handleCompleteManualFix,
    handleAbandonManualFix,
    handleEdit,
    handleSubmitComment,
    handleRefresh,
    openEditModal,

    // Modal states
    assignModalOpen,
    setAssignModalOpen,
    selectedAssignee,
    setSelectedAssignee,
    assigneeRecommendations,
    assigneeRecommendLoading,
    fixModalOpen,
    setFixModalOpen,
    fixBranch,
    setFixBranch,
    manualFixCompleteOpen,
    setManualFixCompleteOpen,
    manualFixForm,
    setManualFixForm,
    editModalOpen,
    setEditModalOpen,
    editForm,
    setEditForm,
    analyzeModalOpen,
    setAnalyzeModalOpen,
    selectedAgentTypes,
    setSelectedAgentTypes,
    agentRecommendations,
    agentRecommendLoading,
    rejectModalOpen,
    setRejectModalOpen,
    rejectReason,
    setRejectReason,

    // Computed
    availableActions,
    commentText,
    setCommentText,
  };
}
