import { get, post, put, del } from './request';
import type {
  IssueClusterListData, IssueSignalListData, AutoTriageResult,
} from './types';
import type {
  IssueCluster, IssueSignal, ProjectModule, IssueRoutingRule,
  AppRelease, AppReleaseTrend, RegressionItem, QualityInsightsOverview, Defect,
} from '../types';

// Issue Clusters
export const listIssueClusters = (projectId: number, params?: {
  status?: string; q?: string; platform?: string; appVersion?: string;
  releaseId?: number; anomalyLevel?: string; page?: number; pageSize?: number;
}) =>
  get<IssueClusterListData>(`/projects/${projectId}/issue-clusters`, { params });
export const listIssueClusterReleaseSummary = (projectId: number, params?: {
  status?: string; q?: string; platform?: string; appVersion?: string;
  releaseId?: number; anomalyLevel?: string;
}) =>
  get<import('../types').IssuePoolReleaseSummary[]>(`/projects/${projectId}/issue-clusters/release-summary`, { params });
export const getIssueCluster = (projectId: number, clusterId: number) =>
  get<IssueCluster>(`/projects/${projectId}/issue-clusters/${clusterId}`);
export const listIssueSignals = (projectId: number, clusterId: number) =>
  get<IssueSignalListData>(`/projects/${projectId}/issue-clusters/${clusterId}/signals`);
export const listIssueClusterReleases = (projectId: number, clusterId: number) =>
  get<import('../types').IssueClusterReleaseMatch[]>(`/projects/${projectId}/issue-clusters/${clusterId}/releases`);
export const assignIssueCluster = (projectId: number, clusterId: number, data: { ownerUserId: number }) =>
  post<void>(`/projects/${projectId}/issue-clusters/${clusterId}/assign`, data);
export const batchAssignIssueClusters = (projectId: number, data: { clusterIds: number[]; ownerUserId: number }) =>
  post<void>(`/projects/${projectId}/issue-clusters/batch-assign`, data);
export const ignoreIssueCluster = (projectId: number, clusterId: number, data?: { reason?: string }) =>
  post<void>(`/projects/${projectId}/issue-clusters/${clusterId}/ignore`, data || {});
export const batchIgnoreIssueClusters = (projectId: number, data: { clusterIds: number[]; reason?: string }) =>
  post<void>(`/projects/${projectId}/issue-clusters/batch-ignore`, data);
export const mergeIssueCluster = (projectId: number, clusterId: number, data: { targetClusterId: number; reason?: string }) =>
  post<void>(`/projects/${projectId}/issue-clusters/${clusterId}/merge`, data);
export const convertIssueCluster = (projectId: number, clusterId: number) =>
  post<{ cluster: IssueCluster; defect: Defect }>(`/projects/${projectId}/issue-clusters/${clusterId}/convert`, {});
export const batchConvertIssueClusters = (projectId: number, data: { clusterIds: number[] }) =>
  post<{ updatedCount: number; defectIds: number[] }>(`/projects/${projectId}/issue-clusters/batch-convert`, data);
export const autoTriageClusters = (projectId: number) =>
  post<AutoTriageResult>(`/projects/${projectId}/issue-clusters/auto-triage`, {});

// Modules
export const listProjectModules = (projectId: number) =>
  get<ProjectModule[]>(`/projects/${projectId}/modules`);
export const createProjectModule = (projectId: number, data: {
  name: string; code: string; description?: string; ownerUserId?: number | null;
  repoId?: number | null; pathPattern?: string; tags?: string;
}) =>
  post<ProjectModule>(`/projects/${projectId}/modules`, data);
export const updateProjectModule = (projectId: number, moduleId: number, data: {
  name: string; code: string; description?: string; ownerUserId?: number | null;
  repoId?: number | null; pathPattern?: string; tags?: string;
}) =>
  put<ProjectModule>(`/projects/${projectId}/modules/${moduleId}`, data);
export const deleteProjectModule = (projectId: number, moduleId: number) =>
  del<void>(`/projects/${projectId}/modules/${moduleId}`);

// Routing Rules
export const listIssueRoutingRules = (projectId: number) =>
  get<IssueRoutingRule[]>(`/projects/${projectId}/routing-rules`);
export const createIssueRoutingRule = (projectId: number, data: {
  matchType: string; matchValue: string; moduleId?: number | null;
  ownerUserId?: number | null; priorityOverride?: string;
  severityOverride?: string; enabled?: boolean; sortOrder?: number;
}) =>
  post<IssueRoutingRule>(`/projects/${projectId}/routing-rules`, data);
export const updateIssueRoutingRule = (projectId: number, ruleId: number, data: {
  matchType: string; matchValue: string; moduleId?: number | null;
  ownerUserId?: number | null; priorityOverride?: string;
  severityOverride?: string; enabled?: boolean; sortOrder?: number;
}) =>
  put<IssueRoutingRule>(`/projects/${projectId}/routing-rules/${ruleId}`, data);
export const deleteIssueRoutingRule = (projectId: number, ruleId: number) =>
  del<void>(`/projects/${projectId}/routing-rules/${ruleId}`);

// Releases
export const listAppReleases = (projectId: number) =>
  get<AppRelease[]>(`/projects/${projectId}/releases`);
export const listAppReleaseTrends = (projectId: number) =>
  get<AppReleaseTrend[]>(`/projects/${projectId}/releases/trends`);
export const createAppRelease = (projectId: number, data: {
  platform: string; appVersion: string; buildNumber?: string;
  channel?: string; releaseTime?: string; commitSha?: string;
  repoId?: number | null; metadata?: Record<string, unknown>;
}) =>
  post<AppRelease>(`/projects/${projectId}/releases`, data);
export const updateAppRelease = (projectId: number, releaseId: number, data: {
  platform: string; appVersion: string; buildNumber?: string;
  channel?: string; releaseTime?: string; commitSha?: string;
  repoId?: number | null; metadata?: Record<string, unknown>;
}) =>
  put<AppRelease>(`/projects/${projectId}/releases/${releaseId}`, data);
export const deleteAppRelease = (projectId: number, releaseId: number) =>
  del<void>(`/projects/${projectId}/releases/${releaseId}`);

// Regression
export const listRegressionItems = (projectId: number, params?: { status?: string; q?: string }) =>
  get<RegressionItem[]>(`/projects/${projectId}/regression-items`, { params });
export const createRegressionItemFromCluster = (projectId: number, clusterId: number) =>
  post<RegressionItem>(`/projects/${projectId}/issue-clusters/${clusterId}/regression-items`, {});
export const updateRegressionItem = (projectId: number, itemId: number, data: {
  title?: string; summary?: string; status?: 'draft' | 'active' | 'verified' | 'archived';
  ownerUserId?: number | null;
}) =>
  put<RegressionItem>(`/projects/${projectId}/regression-items/${itemId}`, data);
export const getQualityInsightsOverview = (projectId: number) =>
  get<QualityInsightsOverview>(`/projects/${projectId}/quality-insights/overview`);
