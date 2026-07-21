import { get, post, put } from './request';
import type { QueryParams, LoginData, InviteInfo, InviteValidation, TempPassword } from './types';
import type { User } from '../types';

export const login = (data: { username: string; password: string }) =>
  post<LoginData>('/auth/login', data);
export const register = (data: { username: string; email: string; password: string; nickname?: string }) =>
  post<LoginData>('/auth/register', data);
export const validateInvite = (code: string) =>
  get<InviteValidation>(`/invites/${code}/validate`);
export const acceptInvite = (code: string, data: { username: string; email: string; password: string; nickname?: string }) =>
  post<LoginData>(`/invites/${code}/accept`, data);
export const createInvite = (data?: { maxUses?: number; expiresAt?: string }) =>
  post<InviteInfo>('/invites', data || {});
export const listInvites = () =>
  get<InviteInfo[]>('/invites');
export const getProfile = () =>
  get<User>('/users/me');
export const updateProfile = (data: { nickname?: string; avatar?: string; agentTypes?: string }) =>
  put<User>('/users/me', data);
export const changeMyPassword = (data: { currentPassword: string; newPassword: string }) =>
  put<void>('/users/me/password', data);
export const updateMyAgentTypes = (data: { agentTypes: string[] }) =>
  put<User>('/users/me/agent-types', data);
export const uploadMyAvatar = (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  return post<{ avatar: string }>('/users/me/avatar', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const listUsers = (params?: QueryParams) =>
  get<import('./types').PaginatedData<User>>('/users', { params });
export const getUser = (id: number) =>
  get<User>(`/users/${id}`);
export const updateUserAgentTypes = (id: number, data: { agentTypes: string[] }) =>
  put<User>(`/users/${id}/agent-types`, data);
export const createUser = (data: {
  username: string;
  email: string;
  password?: string;
  nickname?: string;
  platformRole?: 'super_admin' | 'admin' | 'member';
  projectIds?: number[];
  projectRole?: 'project_admin' | 'developer' | 'tester' | 'viewer';
}) =>
  post<TempPassword>('/users', data);
export const updateUserPlatformRole = (id: number, data: { platformRole: 'super_admin' | 'admin' | 'member' }) =>
  put<void>(`/users/${id}/platform-role`, data);
export const resetUserPassword = (id: number) =>
  post<TempPassword>(`/users/${id}/reset-password`);
