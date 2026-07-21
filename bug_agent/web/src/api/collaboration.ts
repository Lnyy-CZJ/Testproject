import { get, post } from './request';
import type { ApiResult } from './request';
import type { PaginatedData } from './types';
import type { CollaborationTask } from '../types/collaboration';
import type { AggregatedReport as AggregatedReportType } from '../types/collaboration';

export const startCollaboration = (data: { defectId: number; agentTypes?: string[]; triggerUserId?: number }) =>
  post<CollaborationTask>('/collaborations', data);
export const listCollaborations = (params?: { status?: string; defectId?: number; page?: number; pageSize?: number }) =>
  get<PaginatedData<CollaborationTask>>('/collaborations', { params });
export const getCollaborationTask = (taskId: number) =>
  get<CollaborationTask>(`/collaborations/${taskId}`);
export const getAggregatedReport = (taskId: number) =>
  get<AggregatedReportType>(`/collaborations/${taskId}/report`);
export const getDefectCollaborations = (defectId: number) =>
  get<{ items: CollaborationTask[]; total: number }>(`/defects/${defectId}/collaborations`);
