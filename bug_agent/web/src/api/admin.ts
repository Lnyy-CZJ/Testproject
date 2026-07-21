import { get, post, put, del } from './request';
import type {
  QueryParams, CredentialTestResult, RoleInfo, PermissionInfo,
  AIProviderCatalog, AIModelCatalog, AIModelTestResult,
  AuditLogItem, AuditStats,
} from './types';

// Platform Email Settings
export const getPlatformEmailSettings = () =>
  get<import('../types').PlatformEmailSettings>('/admin/platform-settings/email');
export const updatePlatformEmailSettings = (data: {
  smtpHost: string; smtpPort: number; smtpUser?: string;
  smtpPassword?: string; smtpFrom: string; securityType?: string;
}) =>
  put<void>('/admin/platform-settings/email', data);
export const testPlatformEmailSettings = (data: {
  smtpHost: string; smtpPort: number; smtpUser?: string;
  smtpPassword?: string; smtpFrom: string; securityType?: string; to: string;
}) =>
  post<CredentialTestResult>('/admin/platform-settings/email/test', data);

// AI Catalog Admin
export const listAdminAIProviders = (params?: { status?: string; keyword?: string }) =>
  get<AIProviderCatalog[]>('/admin/ai/providers', { params });

export const createAdminAIProvider = (data: {
  providerKey: string; displayName: string; defaultEndpoint?: string;
  status?: 'active' | 'inactive'; sortOrder?: number;
}) =>
  post<AIProviderCatalog>('/admin/ai/providers', data);

export const updateAdminAIProvider = (id: number, data: {
  displayName?: string; defaultEndpoint?: string;
  status?: 'active' | 'inactive'; sortOrder?: number;
}) =>
  put<AIProviderCatalog>(`/admin/ai/providers/${id}`, data);
export const deleteAdminAIProvider = (id: number) =>
  del<void>(`/admin/ai/providers/${id}`);

export const listAdminAIModels = (params?: {
  providerKey?: string; status?: string; keyword?: string;
}) =>
  get<AIModelCatalog[]>('/admin/ai/models', { params });

export const createAdminAIModel = (data: {
  providerKey: string; modelName: string; endpoint?: string;
  capabilityTags?: string; status?: 'active' | 'deprecated' | 'inactive';
  isDefault?: boolean; sortOrder?: number;
}) =>
  post<AIModelCatalog>('/admin/ai/models', data);

export const updateAdminAIModel = (id: number, data: {
  providerKey?: string; modelName?: string; endpoint?: string;
  capabilityTags?: string; status?: 'active' | 'deprecated' | 'inactive';
  isDefault?: boolean; sortOrder?: number;
}) =>
  put<AIModelCatalog>(`/admin/ai/models/${id}`, data);
export const deleteAdminAIModel = (id: number) =>
  del<void>(`/admin/ai/models/${id}`);
export const testAdminAIModel = (id: number, data: { apiKey: string; apiEndpoint?: string }) =>
  post<AIModelTestResult>(`/admin/ai/models/${id}/test`, data);

// Audit Log
export const listAuditLogs = (params?: QueryParams) =>
  get<import('./types').PaginatedData<AuditLogItem>>('/audit-logs', { params });
export const getRecentAuditLogs = (params?: QueryParams) =>
  get<{ items: AuditLogItem[]; total: number }>('/audit-logs/recent', { params });
export const getAuditStats = () =>
  get<AuditStats>('/audit-logs/stats');

// RBAC
export const listRoles = (params?: { tier?: string }) =>
  get<RoleInfo[]>('/rbac/roles', { params });
export const createRole = (data: { name: string; displayName: string; tier: string; description?: string }) =>
  post<RoleInfo>('/rbac/roles', data);
export const getRole = (id: number) =>
  get<RoleInfo>(`/rbac/roles/${id}`);
export const updateRole = (id: number, data: { displayName?: string; tier?: string; description?: string }) =>
  put<RoleInfo>(`/rbac/roles/${id}`, data);
export const updateRolePermissions = (id: number, permissionIds: number[]) =>
  put<void>(`/rbac/roles/${id}/permissions`, { permissionIds });
export const listPermissions = () =>
  get<Record<string, PermissionInfo[]>>('/rbac/permissions');
export const getUserPermissions = () =>
  get<PermissionInfo[]>('/rbac/my-permissions');
export const getUserRoles = () =>
  get<RoleInfo[]>('/rbac/my-roles');
