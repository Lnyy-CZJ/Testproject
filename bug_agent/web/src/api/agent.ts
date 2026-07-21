import { get, post, put, del, patch } from './request';
import type {
  TokenUsageSummary, TokenUsageByEntity,
  MCPServerItem, SkillItem, RetrieverPluginItem,
} from './types';
import type { AgentMemory } from '../types';

// Agent Memory (v5.4)
export const listProjectMemories = (projectId: number, params?: { category?: string }) =>
  get<{ items: AgentMemory[]; total: number }>(`/projects/${projectId}/memories`, { params });
export const listIterationMemories = (projectId: number, iterationId: number, params?: { category?: string }) =>
  get<{ items: AgentMemory[]; total: number }>(`/projects/${projectId}/iterations/${iterationId}/memories`, { params });
export const createProjectMemory = (projectId: number, data: { category: string; content: string }) =>
  post<AgentMemory>(`/projects/${projectId}/memories`, data);
export const createIterationMemory = (projectId: number, iterationId: number, data: { category: string; content: string }) =>
  post<AgentMemory>(`/projects/${projectId}/iterations/${iterationId}/memories`, data);
export const updateMemory = (projectId: number, memoryId: number, data: { category?: string; content?: string }) =>
  put<AgentMemory>(`/projects/${projectId}/memories/${memoryId}`, data);
export const deleteMemory = (projectId: number, memoryId: number) =>
  del<void>(`/projects/${projectId}/memories/${memoryId}`);
export const toggleMemory = (projectId: number, memoryId: number) =>
  patch<AgentMemory>(`/projects/${projectId}/memories/${memoryId}/toggle`);

// Token Usage (v5.5)
export const getIterationTokenUsage = (projectId: number, iterationId: number) =>
  get<TokenUsageSummary[]>(`/projects/${projectId}/iterations/${iterationId}/token-usage`);
export const getProjectTokenUsage = (projectId: number, params?: { startDate?: string; endDate?: string }) =>
  get<TokenUsageSummary[]>(`/projects/${projectId}/token-usage`, { params });
export const getProjectTokenUsageByIteration = (projectId: number, params?: { startDate?: string; endDate?: string }) =>
  get<TokenUsageByEntity[]>(`/projects/${projectId}/token-usage/by-iteration`, { params });
export const getProjectTokenUsageByDefect = (projectId: number, params?: { startDate?: string; endDate?: string }) =>
  get<TokenUsageByEntity[]>(`/projects/${projectId}/token-usage/by-defect`, { params });

// MCP Servers (v5.5)
export const listMCPServers = (projectId: number) =>
  get<MCPServerItem[]>(`/projects/${projectId}/mcp-servers`);
export const createMCPServer = (projectId: number, data: { name: string; command: string; args?: string; description?: string }) =>
  post<MCPServerItem>(`/projects/${projectId}/mcp-servers`, data);
export const updateMCPServer = (projectId: number, serverId: number, data: { name?: string; command?: string; args?: string; description?: string }) =>
  put<MCPServerItem>(`/projects/${projectId}/mcp-servers/${serverId}`, data);
export const deleteMCPServer = (projectId: number, serverId: number) =>
  del<void>(`/projects/${projectId}/mcp-servers/${serverId}`);
export const toggleMCPServer = (projectId: number, serverId: number) =>
  patch<MCPServerItem>(`/projects/${projectId}/mcp-servers/${serverId}/toggle`);
export const testMCPServerConnection = (projectId: number, serverId: number) =>
  post<{ connected: boolean; error?: string }>(`/projects/${projectId}/mcp-servers/${serverId}/test`);

// Skills (v5.5)
export const listSkills = (projectId: number) =>
  get<SkillItem[]>(`/projects/${projectId}/skills`);
export const createSkill = (projectId: number, data: { name: string; agentType: string; instruction?: string; tools?: string; mcpServerIds?: string; memoryCategories?: string }) =>
  post<SkillItem>(`/projects/${projectId}/skills`, data);
export const updateSkill = (projectId: number, skillId: number, data: { name?: string; agentType?: string; instruction?: string; tools?: string; mcpServerIds?: string; memoryCategories?: string }) =>
  put<SkillItem>(`/projects/${projectId}/skills/${skillId}`, data);
export const deleteSkill = (projectId: number, skillId: number) =>
  del<void>(`/projects/${projectId}/skills/${skillId}`);
export const toggleSkill = (projectId: number, skillId: number) =>
  patch<SkillItem>(`/projects/${projectId}/skills/${skillId}/toggle`);

export const listRetrieverPlugins = (projectId: number) =>
  get<RetrieverPluginItem[]>(`/projects/${projectId}/retriever-plugins`);

export const updateRetrieverPlugin = (projectId: number, pluginId: number, data: {
  config?: string; enabled?: boolean; sortOrder?: number; displayName?: string; description?: string;
}) => put<RetrieverPluginItem>(`/projects/${projectId}/retriever-plugins/${pluginId}`, data);

export const toggleRetrieverPlugin = (projectId: number, pluginId: number) =>
  patch<RetrieverPluginItem>(`/projects/${projectId}/retriever-plugins/${pluginId}/toggle`);

export const sortRetrieverPlugins = (projectId: number, items: { id: number; sortOrder: number }[]) =>
  put<void>(`/projects/${projectId}/retriever-plugins/sort`, { items });

export const testRetrieverPlugin = (projectId: number, pluginId: number) =>
  post<{ connected: boolean; error?: string }>(`/projects/${projectId}/retriever-plugins/${pluginId}/test`);
