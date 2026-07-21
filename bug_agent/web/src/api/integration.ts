import { get, post, put, del } from './request';
import type {
  CredentialTestResult, UpdateCredentialData,
  YunxiaoRepo, YunxiaoMember,
} from './types';
import type { RepoCredential, IntegrationConnector, IntegrationSyncRecord } from '../types';

// Repo Credential
export const listCredentials = (params?: { projectId?: number }) =>
  get<RepoCredential[]>('/credentials', { params });
export const createCredential = (data: {
  name: string; type: string; provider: string; content: string; extraConfig?: string;
}) =>
  post<RepoCredential>('/credentials', data);
export const updateCredential = (id: number, data: UpdateCredentialData) =>
  put<RepoCredential>(`/credentials/${id}`, data);
export const deleteCredential = (id: number) =>
  del<void>(`/credentials/${id}`);
export const testCredentialConnection = (data: { provider: string; repoUrl: string; content?: string }) =>
  post<CredentialTestResult>('/credentials/test-connection', data);
export const testRepoConnection = (repoId: number) =>
  post<CredentialTestResult>(`/repos/${repoId}/test-connection`);

// Platform Credentials
export const listPlatformCredentials = () =>
  get<RepoCredential[]>('/admin/platform-credentials');
export const createPlatformCredential = (data: {
  name: string; type: string; provider: string; content: string;
  extraConfig?: string; status?: 'active' | 'inactive'; allowedProjectIds: number[];
}) =>
  post<RepoCredential>('/admin/platform-credentials', data);
export const updatePlatformCredential = (id: number, data: {
  name?: string; type?: string; provider?: string; content?: string;
  extraConfig?: string; status?: 'active' | 'inactive'; allowedProjectIds?: number[];
}) =>
  put<RepoCredential>(`/admin/platform-credentials/${id}`, data);
export const deletePlatformCredential = (id: number) =>
  del<void>(`/admin/platform-credentials/${id}`);

// Integration Connectors
export const listIntegrationConnectors = (projectId: number) =>
  get<IntegrationConnector[]>(`/projects/${projectId}/integrations`);
export const createIntegrationConnector = (projectId: number, data: {
  name: string; type: 'webhook' | 'bugly' | 'dingtalk' | 'feishu' | 'aliyun_log';
  status?: 'active' | 'inactive'; config?: Record<string, unknown>;
}) =>
  post<IntegrationConnector>(`/projects/${projectId}/integrations`, data);
export const updateIntegrationConnector = (projectId: number, id: number, data: {
  name?: string; type?: 'webhook' | 'bugly' | 'dingtalk' | 'feishu' | 'aliyun_log';
  status?: 'active' | 'inactive'; config?: Record<string, unknown>;
}) =>
  put<IntegrationConnector>(`/projects/${projectId}/integrations/${id}`, data);
export const deleteIntegrationConnector = (projectId: number, id: number) =>
  del<void>(`/projects/${projectId}/integrations/${id}`);
export const testIntegrationConnector = (projectId: number, id: number) =>
  post<CredentialTestResult>(`/projects/${projectId}/integrations/${id}/test`, {});
export const syncIntegrationConnector = (projectId: number, id: number, data?: {
  items?: Array<Record<string, unknown>>;
}) =>
  post<IntegrationSyncRecord>(`/projects/${projectId}/integrations/${id}/sync`, data || {});
export const listIntegrationSyncRecords = (projectId: number, id: number) =>
  get<IntegrationSyncRecord[]>(`/projects/${projectId}/integrations/${id}/sync-records`);

// Yunxiao Integration
export const testYunxiaoConnection = (data: {
  credentialId: number; projectId?: number; endpoint?: string; organizationId?: string;
}) =>
  post<CredentialTestResult>('/integrations/yunxiao/test-connection', data);

export const listYunxiaoRepos = (params: {
  credentialId: number; projectId?: number; endpoint?: string;
  organizationId?: string; page?: number; size?: number; search?: string;
}) =>
  get<import('./types').PaginatedData<YunxiaoRepo>>('/integrations/yunxiao/repos', { params });

export const importYunxiaoRepos = (projectId: number, data: {
  credentialId: number; items: Array<{
    externalId?: string; name: string; repoUrl: string;
    defaultBranch?: string; description?: string;
  }>; agentTypes?: string;
}) =>
  post<{ imported: number }>(`/projects/${projectId}/repos/import/yunxiao`, data);

export const listYunxiaoMembers = (params: {
  credentialId: number; projectId?: number; endpoint?: string;
  organizationId?: string; page?: number; size?: number; search?: string;
}) =>
  get<import('./types').PaginatedData<YunxiaoMember>>('/integrations/yunxiao/members', { params });

export const importYunxiaoMembers = (projectId: number, data: {
  credentialId: number; updateExisting?: boolean;
  items: Array<{
    externalId?: string; name: string; username?: string;
    email?: string; role?: string;
  }>;
}) =>
  post<{ imported: number }>(`/projects/${projectId}/members/import/yunxiao`, data);
