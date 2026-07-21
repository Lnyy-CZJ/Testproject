import { get, getApiUrl, post, put, patch, del } from './request';
import type {
  QueryParams, DefectDetail, AssigneeRecommendation,
  AgentRecommendation, UpdateFixTaskData, DefectRepoItem,
  TokenUsageSummary, TokenUsageRecord,
} from './types';
import type { Defect, Comment, FixTask, FixTaskGroup, AnalysisReport, PRRejection } from '../types';
import { appStorage } from '../utils/storage';

/** Python Token 汇总接口的原始结构。 */
interface PythonTokenUsageSummary {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  count: number;
}

/** Python Token 明细接口的原始结构。 */
interface PythonTokenUsageDetail {
  id: number;
  projectId: number;
  iterationId?: number | null;
  defectId?: number | null;
  provider: string;
  model: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  isFallback: boolean;
  durationMs?: number | null;
  source: string;
  createdAt: string;
}

export const listDefects = (params?: QueryParams) =>
  get<import('./types').PaginatedData<Defect>>('/defects', { params });
export const getDefect = (id: number) =>
  get<DefectDetail>(`/defects/${id}`);
export const createDefect = (data: {
  title: string; description: string; severity: string; priority: string;
  type: string; iterationId: number; tags?: string[];
}) =>
  post<Defect>('/defects', data);
export const createDefectDraftFromChat = (projectId: number, data: {
  iterationId?: number; message: string; tags?: string[];
}) =>
  post<import('../types').DefectDraft>(`/projects/${projectId}/defects/draft-from-chat`, data, {
    timeout: 120000,
  });
export const confirmCreateDefect = (projectId: number, data: {
  iterationId: number; title: string; descriptionMarkdown: string;
  severity: string; priority: string; type: string; tags?: string[];
  sourceMode?: 'manual_chat';
}) =>
  post<Defect>(`/projects/${projectId}/defects/confirm-create`, data);
export const updateDefect = (id: number, data: {
  title?: string; description?: string; severity?: string; priority?: string;
  type?: string; tags?: string[];
}) =>
  put<Defect>(`/defects/${id}`, data);
export const assignDefect = (id: number, data: { assigneeId: number; agentTypes?: string[]; recommendationAdopted?: boolean; recommendationStrategy?: string }) =>
  put<{ defect: Defect; status: string; agentAnalysisTriggered?: boolean }>(`/defects/${id}/assign`, data);
export const changeDefectStatus = (id: number, data: { status: string; comment?: string }) =>
  put<Defect>(`/defects/${id}/status`, data);
export const verifyDefect = (id: number, data: { passed: boolean; comment?: string }) =>
  put<{ defect: Defect; status: string }>(`/defects/${id}/verify`, data);
export const rejectDefect = (id: number, data: { reason: string }) =>
  put<{ status: string }>(`/defects/${id}/reject`, data);
export const mergeDefect = (id: number) =>
  put<{ defect: Defect; status: string; merged: boolean; mergedPRs?: string[]; failedPRs?: string[] }>(`/defects/${id}/merge`);
export const getDefectAssigneeRecommendations = (id: number, params?: { limit?: number }) =>
  get<{ list: AssigneeRecommendation[] }>(`/defects/${id}/recommend-assignees`, { params });
export const getDefectAgentRecommendations = (id: number, params?: { limit?: number }) =>
  get<{ list: AgentRecommendation[] }>(`/defects/${id}/recommend-agents`, { params });

// Comment
export const createComment = (defectId: number, data: { content: string; mentions?: number[] }) =>
  post<Comment>(`/defects/${defectId}/comments`, data);
export const listComments = (defectId: number) =>
  get<Comment[]>(`/defects/${defectId}/comments`);

// Agent Analysis
export const triggerAnalysis = (data: { defectId: number; agentTypes: string[] }) =>
  post<{ message: string; defectId: number; agentTypes: string[]; status: string }>('/agents/analyze', data);
export const cancelAnalysis = (defectId: number) =>
  post<{ message: string }>(`/agents/analyze/${defectId}/cancel`);
export const triggerAnalysisStream = (data: { defectId: number; agentTypes: string[] }, signal?: AbortSignal) =>
  fetch(getApiUrl('/agents/analyze/stream'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${appStorage.getToken()}`,
    },
    body: JSON.stringify(data),
    signal,
  });
export const getReport = (reportId: string) =>
  get<AnalysisReport>(`/agents/reports/${reportId}`);
export const listReports = (defectId: number) =>
  // Python 接口按 Go 契约直接返回报告数组，不额外套分页结构。
  get<AnalysisReport[]>(`/defects/${defectId}/reports`);

// FixTask
export const createFixTask = (defectId: number, data?: { targetBranch?: string; agentType?: string }) =>
  post<{
    groupId?: number;
    taskCode: string;
    status: string;
    defectId: number;
    units?: Array<{ id: number; taskCode: string; agentType: string; analysisReportId: number; projectRepoId: number; status: string }>;
  }>(`/defects/${defectId}/fix-tasks`, data);
export const listFixTasks = (defectId: number) =>
  get<FixTask[]>(`/defects/${defectId}/fix-tasks`);
export const listFixTaskGroups = (defectId: number) =>
  get<FixTaskGroup[]>(`/defects/${defectId}/fix-task-groups`);
export const getFixTask = (taskId: number) =>
  get<FixTask>(`/fix-tasks/${taskId}`);
export const updateFixTask = (taskId: number, data: UpdateFixTaskData) =>
  put<FixTask>(`/fix-tasks/${taskId}`, data);

// Attachment
export const uploadAttachment = (defectId: number, file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return post<{ id: number; fileUrl: string; fileName: string }>(`/defects/${defectId}/attachments`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const listAttachments = (defectId: number) =>
  get<Array<{ id: number; fileName: string; fileUrl: string; fileSize: number; fileType: string; createdAt: string }>>(`/defects/${defectId}/attachments`);
export const deleteAttachment = (defectId: number, attachmentId: number) =>
  del<void>(`/defects/${defectId}/attachments/${attachmentId}`);

// Manual Fix (v5.4)
export const startManualFix = (defectId: number) =>
  post<{ message: string }>(`/defects/${defectId}/manual-fix/start`);
export const completeManualFix = (defectId: number, data: { description: string; prUrl?: string; fixBranch?: string }) =>
  post<{ message: string }>(`/defects/${defectId}/manual-fix/complete`, data);
export const abandonManualFix = (defectId: number) =>
  post<{ message: string }>(`/defects/${defectId}/manual-fix/abandon`);
export const updateFixTaskPR = (defectId: number, taskId: number, data: { prUrl: string }) =>
  patch<{ message: string }>(`/defects/${defectId}/fix-tasks/${taskId}/pr`, data);

// PR Lifecycle (v5.4)
export const listPRRejections = (defectId: number, taskId: number) =>
  get<{ items: PRRejection[]; total: number }>(`/defects/${defectId}/fix-tasks/${taskId}/rejections`);
export const manualRejectPR = (defectId: number, taskId: number, data: { rejectedBy?: string; rejectReason: string }) =>
  post<{ message: string }>(`/defects/${defectId}/fix-tasks/${taskId}/reject`, data);
export const manualMergePR = (defectId: number, taskId: number) =>
  post<{ message: string }>(`/defects/${defectId}/fix-tasks/${taskId}/merge`);

// Defect Reopen & Reanalyze (v5.5)
export const reopenDefect = (defectId: number, data: { targetStatus: string; comment?: string }) =>
  post<{ defect: Defect; status: string }>(`/defects/${defectId}/reopen`, data);
export const reanalyzeDefect = (defectId: number) =>
  post<{ message: string; defectId: number; status: string }>(`/defects/${defectId}/reanalyze`);

// Token Usage (v5.5)
export const getDefectTokenUsage = async (defectId: number) => {
  const result = await get<PythonTokenUsageSummary>(`/defects/${defectId}/token-usage`);
  const summary = result.data;

  // 旧前端按消费类型展示，Python 当前提供总汇；转换为单条 analysis 记录供视图复用。
  return {
    ...result,
    data: summary ? [{
      consumptionType: 'analysis',
      promptTokens: summary.promptTokens,
      completionTokens: summary.completionTokens,
      totalTokens: summary.totalTokens,
      estimatedCostUsd: summary.estimatedCostUsd,
      callCount: summary.count,
      durationMs: 0,
    }] satisfies TokenUsageSummary[] : [],
  };
};

export const getDefectTokenUsageDetails = async (defectId: number) => {
  const result = await get<PythonTokenUsageDetail[]>(`/defects/${defectId}/token-usage/details`);

  // 补齐旧视图使用的字段名，未由 Python 持久化的旧字段使用稳定默认值。
  return {
    ...result,
    data: (result.data || []).map((item) => ({
      id: item.id,
      projectId: item.projectId,
      iterationId: item.iterationId,
      defectId: item.defectId || 0,
      consumptionType: item.source,
      sourceId: item.id,
      attemptIndex: 1,
      isFinalAttempt: true,
      provider: item.provider,
      modelName: item.model,
      promptTokens: item.promptTokens,
      completionTokens: item.completionTokens,
      totalTokens: item.totalTokens,
      estimatedCostUsd: item.estimatedCostUsd,
      durationMs: item.durationMs || 0,
      createdAt: item.createdAt,
    })) satisfies TokenUsageRecord[],
  };
};

// Defect Repos (v5.5)
export const listDefectRepos = (defectId: number) =>
  get<DefectRepoItem[]>(`/defects/${defectId}/repos`);
export const deleteDefectRepo = (defectId: number, repoId: number) =>
  del<void>(`/defects/${defectId}/repos/${repoId}`);
