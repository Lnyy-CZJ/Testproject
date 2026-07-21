import { get, post, put, del } from './request';
import type { CredentialTestResult, NotificationItem } from './types';

// Notification Preferences
export const getNotificationPrefs = () =>
  get<Record<string, string>>('/notification-preferences');
export const batchUpdateNotificationPrefs = (updates: Record<string, string>) =>
  put<void>('/notification-preferences', { updates });
export const getUserWebhookSettings = () =>
  get<import('../types').UserWebhookSettings>('/notification-preferences/webhook');
export const updateUserWebhookSettings = (data: {
  url?: string; secret?: string; enabled: boolean;
}) =>
  put<void>('/notification-preferences/webhook', data);
export const testUserWebhookSettings = (data: {
  url?: string; secret?: string; enabled?: boolean;
}) =>
  post<CredentialTestResult>('/notification-preferences/webhook/test', data);
export const listNotifications = (params?: { page?: number; pageSize?: number }) =>
  get<import('./types').PaginatedData<NotificationItem>>('/notifications', { params });
export const getUnreadNotificationCount = () =>
  get<{ count: number }>('/notifications/unread-count');
export const markNotificationsRead = (ids: number[]) =>
  put<void>('/notifications/read', { ids });
export const markAllNotificationsRead = () =>
  put<void>('/notifications/read-all');

// Project Notification Management
export const listProjectNotificationPolicies = (projectId: number) =>
  get<import('../types').ProjectNotificationPolicy[]>(`/projects/${projectId}/notification-policies`);
export const batchUpdateProjectNotificationPolicies = (projectId: number, policies: Array<{
  category: string; inAppEnabled: boolean; emailEnabled: boolean; webhookId?: number | null;
}>) =>
  put<void>(`/projects/${projectId}/notification-policies`, { policies });
export const listProjectWebhooks = (projectId: number) =>
  get<import('../types').ProjectWebhook[]>(`/projects/${projectId}/notification-webhooks`);
export const createProjectWebhook = (projectId: number, data: {
  name: string; url: string; secret?: string; enabled?: boolean;
}) =>
  post<import('../types').ProjectWebhook>(`/projects/${projectId}/notification-webhooks`, data);
export const updateProjectWebhook = (projectId: number, webhookId: number, data: {
  name: string; url: string; secret?: string; enabled?: boolean;
}) =>
  put<import('../types').ProjectWebhook>(`/projects/${projectId}/notification-webhooks/${webhookId}`, data);
export const deleteProjectWebhook = (projectId: number, webhookId: number) =>
  del<void>(`/projects/${projectId}/notification-webhooks/${webhookId}`);
export const testProjectWebhook = (projectId: number, webhookId: number, data?: { event?: string }) =>
  post<CredentialTestResult>(`/projects/${projectId}/notification-webhooks/${webhookId}/test`, data || {});
