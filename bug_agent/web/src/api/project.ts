import { get, post, put, del } from './request';
import type { QueryParams, ProjectDetail, IterationDetail, ProjectStats } from './types';
import type { Project, Iteration, IterationRepo, ProjectRepo, ProjectAIConfig } from '../types';

export const createProject = (data: { name: string; code: string; description?: string }) =>
  post<Project>('/projects', data);
export const listProjects = (params?: QueryParams) =>
  get<import('./types').PaginatedData<Project>>('/projects', { params });
export const getProject = (id: number) =>
  get<ProjectDetail>(`/projects/${id}`);
export const updateProject = (id: number, data: { name?: string; description?: string; status?: string; memoryEnabled?: boolean }) =>
  put<Project>(`/projects/${id}`, data);
export const addProjectMember = (projectId: number, data: { userId: number; role: string }) =>
  post<void>(`/projects/${projectId}/members`, data);
export const removeProjectMember = (projectId: number, memberId: number) =>
  del<void>(`/projects/${projectId}/members/${memberId}`);

// User Projects
export const listUserProjects = () =>
  get<import('./types').PaginatedData<Project>>('/user/projects');
export const getProjectStats = (projectId: number) =>
  get<ProjectStats>(`/projects/${projectId}/stats`);

// Iteration
export const createIteration = (projectId: number, data: { name: string; startDate: string; endDate: string; goal?: string }) =>
  post<Iteration>(`/projects/${projectId}/iterations`, data);
export const getIteration = (projectId: number, iterationId: number) =>
  get<IterationDetail>(`/projects/${projectId}/iterations/${iterationId}`);
export const updateIteration = (projectId: number, iterationId: number, data: { name?: string; startDate?: string; endDate?: string; goal?: string }) =>
  put<Iteration>(`/projects/${projectId}/iterations/${iterationId}`, data);
export const listIterations = (projectId: number) =>
  get<Iteration[]>(`/projects/${projectId}/iterations`);
export const bindRepo = (projectId: number, iterationId: number, data: { repoId: number; branch?: string }) =>
  post<IterationRepo>(`/projects/${projectId}/iterations/${iterationId}/repos`, data);
export const unbindRepo = (projectId: number, iterationId: number, repoId: number) =>
  del<void>(`/projects/${projectId}/iterations/${iterationId}/repos/${repoId}`);
export const listRepoBranches = (projectId: number, _iterationId: number, repoId: number) =>
  get<string[]>(`/projects/${projectId}/repos/${repoId}/branches`);
export const updateIterRepoBranch = (projectId: number, iterationId: number, iterRepoId: number, data: { branch: string }) =>
  put<{ branch: string; projectId: number }>(`/projects/${projectId}/iterations/${iterationId}/repos/${iterRepoId}/branch`, data);

// Project Repo
export const listProjectRepos = (projectId: number) =>
  get<ProjectRepo[]>(`/projects/${projectId}/repos`);
export const createProjectRepo = (projectId: number, data: {
  name: string; repoUrl: string; sourceType: string; credentialId?: number | null;
  agentTypes?: string; defaultBranch?: string; description?: string;
}) =>
  post<ProjectRepo>(`/projects/${projectId}/repos`, data);
export const updateProjectRepo = (projectId: number, repoId: number, data: import('./types').UpdateProjectRepoData) =>
  put<ProjectRepo>(`/projects/${projectId}/repos/${repoId}`, data);
export const deleteProjectRepo = (projectId: number, repoId: number) =>
  del<void>(`/projects/${projectId}/repos/${repoId}`);

// Project AI Config
export const listAIProviders = () =>
  get<import('../types').AIProviderOption[]>('/ai/providers');
export const listProjectAIConfigs = (projectId: number) =>
  get<ProjectAIConfig[]>(`/projects/${projectId}/ai-configs`);
export const createProjectAIConfig = (projectId: number, data: {
  provider: string; modelName: string; apiKey: string;
  apiEndpoint?: string; functionCallingMode?: string; isDefault?: boolean;
}) =>
  post<ProjectAIConfig>(`/projects/${projectId}/ai-configs`, data);
export const updateProjectAIConfig = (projectId: number, configId: number, data: {
  provider?: string; modelName?: string; apiKey?: string;
  apiEndpoint?: string; functionCallingMode?: string; isDefault?: boolean;
}) =>
  put<ProjectAIConfig>(`/projects/${projectId}/ai-configs/${configId}`, data);
export const deleteProjectAIConfig = (projectId: number, configId: number) =>
  del<void>(`/projects/${projectId}/ai-configs/${configId}`);
