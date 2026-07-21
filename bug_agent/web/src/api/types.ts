import type {
  User, Project, Iteration, Defect, Comment, FixTask,
  AnalysisReport, ProjectRepo, RepoCredential, ProjectAIConfig,
  IntegrationConnector, IntegrationSyncRecord, IssueSignal,
  IssueCluster, ProjectModule, IssueRoutingRule, AppRelease,
  AppReleaseTrend, RegressionItem, QualityInsightsOverview,
  AgentMemory, PRRejection, IterationRepo,
} from '../types';
import type { CollaborationTask, AggregatedReport as AggregatedReportType } from '../types/collaboration';

export type QueryParams = Record<string, string | number | boolean | undefined>;

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface LoginData {
  token: string;
  user: User;
}

export interface ProjectDetail {
  project: Project;
  members: Array<{ memberId: number; userId: number; role: string; username: string; nickname: string; agentTypes: string[] }>;
  iterations: Iteration[];
}

export interface IterationDetail {
  iteration: Iteration;
  repos: IterationRepo[];
  defectStats?: { total: number; pending: number; fixing: number; completed: number };
}

export interface DefectDetail {
  defect: Defect;
  comments: Comment[];
  fixTasks: FixTask[];
  reports: AnalysisReport[];
  attachments: { id: number; fileName: string; fileUrl: string; fileSize: number; fileType: string; createdAt: string }[];
}

export interface ProjectStats {
  total: number;
  pending: number;
  fixing: number;
  completed: number;
  urgent: number;
}

export interface CredentialTestResult {
  success: boolean;
  message?: string;
}

export interface TempPassword {
  temporaryPassword: string;
}

export interface InviteInfo {
  id: number;
  code: string;
  maxUses: number;
  usedCount: number;
  expiresAt: string;
  createdAt: string;
}

export interface InviteValidation {
  valid: boolean;
  invite?: InviteInfo;
}

export interface NotificationItem {
  id: number;
  userId: number;
  type: string;
  title: string;
  content: string;
  read: boolean;
  createdAt: string;
  category?: string;
  relatedId?: number;
  metadata?: string;
}

export interface RoleInfo {
  id: number;
  name: string;
  displayName: string;
  tier: string;
  description?: string;
  permissions?: PermissionInfo[];
}

export interface PermissionInfo {
  id: number;
  code: string;
  name: string;
  module: string;
  description?: string;
}

export interface AIProviderCatalog {
  id: number;
  providerKey: string;
  displayName: string;
  defaultEndpoint?: string;
  status: string;
  sortOrder: number;
  models?: AIModelCatalog[];
}

export interface AIModelCatalog {
  id: number;
  providerKey: string;
  modelName: string;
  endpoint?: string;
  capabilityTags?: string;
  status: string;
  isDefault: boolean;
  sortOrder: number;
}

export interface AIModelTestResult {
  success: boolean;
  message?: string;
  responsePreview?: string;
  latencyMs?: number;
  endpoint?: string;
}

export interface AssigneeRecommendation {
  userId: number;
  username: string;
  nickname: string;
  agentTypes: string[];
  score: number;
  confidence: number;
  reasons: string[];
  currentOpenLoad: number;
  historicalHandled: number;
}

export interface AgentRecommendation {
  agentType: string;
  label: string;
  score: number;
  confidence: number;
  reasons: string[];
}

export interface AuditLogItem {
  id: number;
  userId: number;
  username: string;
  action: string;
  targetType: string;
  targetId?: number;
  oldValue?: string;
  newValue?: string;
  ipAddress?: string;
  userAgent?: string;
  requestMethod?: string;
  requestPath?: string;
  statusCode: number;
  errorMessage?: string;
  durationMs: number;
  createdAt: string;
}

export interface YunxiaoRepo {
  externalId: string;
  name: string;
  repoUrl: string;
  defaultBranch?: string;
  description?: string;
}

export interface YunxiaoMember {
  externalId: string;
  name: string;
  username?: string;
  email?: string;
  role?: string;
}

export interface IssueClusterListData {
  items: IssueCluster[];
  total: number;
}

export interface IssueSignalListData {
  items: IssueSignal[];
  total: number;
}

export interface AutoTriageResult {
  triaged: number;
  failed: number;
  message?: string;
}

export interface ReportAnalysisData {
  rootCause: string;
  impact: string;
  suggestion: string;
}

export interface AuditStats {
  totalLogs: number;
  topActions: Array<{ action: string; count: number }>;
  activeUsers: Array<{ userId: number; username: string; count: number }>;
}

export interface TokenUsageSummary {
  consumptionType: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  callCount: number;
  durationMs: number;
}

export interface TokenUsageByEntity {
  id: number;
  consumptionType: string;
  totalTokens: number;
  estimatedCostUsd: number;
  callCount: number;
}

export interface TokenUsageRecord {
  id: number;
  projectId: number;
  iterationId?: number | null;
  defectId: number;
  consumptionType: string;
  sourceId: number;
  attemptIndex: number;
  isFinalAttempt: boolean;
  provider: string;
  modelName: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedCostUsd: number;
  durationMs: number;
  createdAt: string;
}

export interface DefectRepoItem {
  id: number;
  defectId: number;
  projectId: number;
  repoUrl: string;
  branch: string;
  localPath: string;
  status: string;
  fixTaskId?: number | null;
  createdAt: string;
  deletedAt?: string | null;
}

export interface MCPServerItem {
  id: number;
  projectId: number;
  name: string;
  command: string;
  args?: string;
  description?: string;
  enabled: boolean;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
}

export interface SkillItem {
  id: number;
  projectId: number;
  name: string;
  agentType: string;
  instruction?: string;
  tools?: string;
  mcpServerIds?: string;
  memoryCategories?: string;
  enabled: boolean;
  isDefault: boolean;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
}

export interface RetrieverPluginItem {
  id: number;
  projectId: number;
  name: string;
  displayName: string;
  description: string;
  config: string;
  configSchema?: RetrieverConfigSchema;
  enabled: boolean;
  sortOrder: number;
  isBuiltIn: boolean;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
}

export interface RetrieverConfigSchema {
  type: 'object';
  title?: string;
  properties?: Record<string, RetrieverConfigSchemaProperty>;
  required?: string[];
}

export interface RetrieverConfigSchemaProperty {
  type: 'string' | 'number' | 'integer' | 'boolean';
  title?: string;
  description?: string;
  default?: unknown;
  format?: 'uri' | 'password' | string;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
}

export interface StreamEvent {
  type: 'thinking' | 'tool_call' | 'tool_result' | 'partial' | 'final' | 'error';
  agent?: string;
  content?: string;
  toolName?: string;
  toolInput?: string;
  toolOutput?: string;
  stepIndex?: number;
  phase?: 'retrieval' | 'analysis' | 'validation';
  partial?: boolean;
  done?: boolean;
  error?: string;
}

export interface ThinkingStep {
  id: string;
  type: StreamEvent['type'];
  content: string;
  toolName?: string;
  toolInput?: string;
  toolOutput?: string;
  phase?: string;
  stepIndex: number;
  timestamp: number;
}

export interface UpdateFixTaskData {
  status?: string;
  plan?: string;
  result?: string;
  prUrl?: string;
}

export interface UpdateProjectRepoData {
  name?: string; repoUrl?: string; sourceType?: string;
  credentialId?: number | null; agentTypes?: string;
  defaultBranch?: string; description?: string;
}

export interface UpdateCredentialData {
  name?: string; type?: string; provider?: string;
  content?: string; extraConfig?: string;
}

// Re-export types from ../types that are used in API signatures
export type {
  User, Project, Iteration, Defect, Comment, FixTask,
  AnalysisReport, ProjectRepo, RepoCredential, ProjectAIConfig,
  IntegrationConnector, IntegrationSyncRecord, IssueSignal,
  IssueCluster, ProjectModule, IssueRoutingRule, AppRelease,
  AppReleaseTrend, RegressionItem, QualityInsightsOverview,
  AgentMemory, PRRejection, IterationRepo,
};

export type { CollaborationTask, AggregatedReportType };
