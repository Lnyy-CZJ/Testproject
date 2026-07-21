// Core domain union types
export type DefectSeverity = 'fatal' | 'major' | 'normal' | 'minor' | 'suggest';
export type DefectPriority = 'P0' | 'P1' | 'P2' | 'P3' | 'P4';
export type DefectStatus = 'new' | 'pending_assign' | 'pending_analysis' | 'analyzing' | 'pending_fix' | 'fixing' | 'manual_fixing' | 'pending_verify' | 'fixed' | 'completed' | 'rejected' | 'suspended' | 'reopened';
export type DefectType = 'functional' | 'ui' | 'performance' | 'security' | 'compatibility' | 'other';
export type IterationStatus = 'planning' | 'active' | 'completed' | 'archived';
export type AnalysisReportStatus = 'pending' | 'completed' | 'completed_fallback' | 'failed' | 'superseded';
export type PlatformRole = 'super_admin' | 'admin' | 'member';

export interface User {
  id: number;
  username: string;
  email: string;
  nickname?: string;
  avatar?: string;
  agentTypes?: string[];
  platformRole?: PlatformRole;
  mustChangePassword?: boolean;
  lastLoginAt?: string;
  createdAt: string;
}

export interface Project {
  id: number;
  name: string;
  code: string;
  description?: string;
  status: string;
  memoryEnabled: boolean;
  createdAt: string;
}

export interface ProjectMember {
  memberId: number;
  userId: number;
  role?: string;
  username?: string;
  nickname?: string;
  avatar?: string;
  agentTypes?: string[];
  user?: User;
  createdAt?: string;
}

export interface Iteration {
  id: number;
  projectId: number;
  name: string;
  startDate: string;
  endDate: string;
  goal?: string;
  status: IterationStatus;
  createdAt: string;
}

export interface Defect {
  id: number;
  code: string;
  iterationId: number;
  title: string;
  description: string;
  severity: DefectSeverity;
  priority: DefectPriority;
  type: DefectType;
  status: DefectStatus;
  assigneeId?: number;
  reporterId: number;
  tags?: string[];
  createdAt: string;
  updatedAt: string;
  iteration?: Iteration;
  assignee?: User;
  reporter?: User;
}

export interface DefectDraft {
  title: string;
  descriptionMarkdown: string;
  severity: DefectSeverity;
  priority: DefectPriority;
  type: DefectType;
  tags: string[];
  suggestedIterationId?: number;
  missingInformation?: string[];
  confidence: number;
  sourceMode: 'manual_chat';
  provider?: string;
  modelName?: string;
  promptVersion?: string;
  fallbackUsed?: boolean;
}

export interface Comment {
  id: number;
  defectId: number;
  userId: number;
  content: string;
  agentType?: string;
  isAgentMessage: boolean;
  createdAt: string;
  user?: User;
}

export interface FixTask {
  id: number;
  groupId?: number;
  taskCode: string;
  defectId: number;
  analysisReportId?: number;
  agentType: string;
  projectRepoId?: number;
  projectRepo?: ProjectRepo;
  status: string;
  targetBranch?: string;
  fixBranch?: string;
  repoPath?: string;
  aiProvider?: string;
  aiModelName?: string;
  aiPromptVersion?: string;
  aiFallbackUsed?: boolean;
  aiLastError?: string;
  aiDurationMs?: number;
  aiPromptTokens?: number;
  aiCompletionTokens?: number;
  aiTotalTokens?: number;
  aiEstimatedCostUsd?: number;
  aiRiskSummary?: string;
  aiValidationSuggestions?: string;
  plan?: string;
  result?: string;
  prUrl?: string;
  prNumber?: string;
  source?: string;
  manualDescription?: string;
  prStatus?: string;
  createdAt: string;
  completedAt?: string;
  defect?: Defect;
}

export interface FixTaskGroup {
  id: number;
  taskCode: string;
  defectId: number;
  status: string;
  targetBranch?: string;
  summary?: string;
  result?: string;
  createdBy?: number;
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
  units?: FixTask[];
}

export interface PRRejection {
  id: number;
  fixTaskId: number;
  prNumber?: string;
  prUrl?: string;
  rejectedBy?: string;
  rejectReason?: string;
  vcsProvider?: string;
  createdAt: string;
}

export interface AgentMemory {
  id: number;
  projectId: number;
  iterationId?: number | null;
  category: string;
  content: string;
  source: string;
  sourceRefId?: number | null;
  relevanceScore: number;
  enabled: boolean;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
}

export interface AnalysisReport {
  id: number;
  reportCode: string;
  defectId: number;
  agentType: string;
  status: AnalysisReportStatus;
  provider?: string;
  modelName?: string;
  promptVersion?: string;
  fallbackUsed?: boolean;
  errorMessage?: string;
  durationMs?: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
  estimatedCostUsd?: number;
  riskSummary?: string;
  validationSuggestions?: string;
  analysis?: string;
  solution?: string;
  createdAt: string;
}

// v1.1 新增类型

export interface ProjectRepo {
  id: number;
  projectId: number;
  name: string;
  repoUrl: string;
  externalRepoId?: string;
  sourceType: string;
  credentialId?: number;
  agentTypes?: string[];
  defaultBranch: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
}

export interface RepoCredential {
  id: number;
  userId: number;
  name: string;
  type: string;
  provider: string;
  scope: 'personal' | 'platform';
  status: 'active' | 'inactive';
  extraConfig?: string;
  maskedValue: string;
  allowedProjectIds?: number[];
  lastUsedAt?: string;
  createdAt: string;
}

export interface ProjectAIConfig {
  id: number;
  projectId: number;
  provider: string;
  modelName: string;
  apiKey: string; // 脱敏显示
  apiEndpoint?: string;
  functionCallingMode?: 'auto' | 'enabled' | 'disabled';
  isDefault: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectWebhook {
  id: number;
  projectId: number;
  name: string;
  url: string;
  hasSecret: boolean;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectNotificationPolicy {
  id: number;
  projectId: number;
  category: string;
  inAppEnabled: boolean;
  emailEnabled: boolean;
  webhookId?: number | null;
  webhook?: ProjectWebhook | null;
  createdAt: string;
  updatedAt: string;
}

export interface PlatformEmailSettings {
  smtpHost: string;
  smtpPort: number;
  smtpUser: string;
  smtpFrom: string;
  passwordConfigured: boolean;
  securityType?: string;
}

export interface AIProviderOption {
  name: string;
  value: string;
  models: Array<{
    name: string;
    endpoint: string;
    capabilityTags?: string;
  }>;
}

export interface UserWebhookSettings {
  url: string;
  enabled: boolean;
  secretConfigured: boolean;
}

export interface IterationRepo {
  id: number;
  iterationId: number;
  repoId: number;
  repoName: string;
  repoUrl: string;
  branch?: string;
  createdAt: string;
}

export interface IntegrationConnector {
  id: number;
  projectId: number;
  projectName?: string;
  name: string;
  type: 'webhook' | 'bugly' | 'dingtalk' | 'feishu' | 'aliyun_log';
  status: 'active' | 'inactive';
  inboundToken: string;
  inboundPath: string;
  lastSyncAt?: string;
  lastSyncStatus?: string;
  lastError?: string;
  lastErrorKind?: string;
  lastErrorRetryable?: boolean;
  healthStatus?: 'healthy' | 'warning' | 'error' | 'inactive';
  healthSummary?: string;
  supportsPull?: boolean;
  hasConfig: boolean;
  config?: Record<string, unknown>;
  createdBy: number;
  createdAt: string;
  updatedAt: string;
}

export interface IntegrationSyncRecord {
  id: number;
  connectorId: number;
  triggerType: string;
  status: 'success' | 'failed' | 'pending';
  requestSummary?: string;
  importedCount: number;
  clusteredCount: number;
  errorKind?: string;
  retryable?: boolean;
  errorMessage?: string;
  startedAt: string;
  finishedAt?: string;
  createdAt: string;
}

export interface IssueSignal {
  id: number;
  projectId: number;
  connectorId?: number | null;
  clusterId?: number | null;
  sourceType: string;
  sourceEventId: string;
  sourceInstance: string;
  title: string;
  description?: string;
  rawSeverity?: string;
  rawPriority?: string;
  appVersion?: string;
  buildNumber?: string;
  platform?: string;
  deviceInfoJson?: string;
  stackTrace?: string;
  logExcerpt?: string;
  fingerprint?: string;
  occurrenceCount: number;
  affectedUserCount: number;
  firstSeenAt: string;
  lastSeenAt: string;
  rawPayloadJson: string;
  triageStatus: string;
  linkedDefectId?: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface IssueCluster {
  id: number;
  projectId: number;
  clusterKey: string;
  title: string;
  summary?: string;
  status: string;
  signalCount: number;
  affectedUserCount: number;
  severity?: string;
  priority?: string;
  ownerUserId?: number | null;
  moduleId?: number | null;
  firstSeenAt: string;
  lastSeenAt: string;
  linkedDefectId?: number | null;
  createdAt: string;
  updatedAt: string;
  owner?: User | null;
  defect?: Defect | null;
  platform?: string;
  appVersion?: string;
  buildNumber?: string;
  primarySourceType?: string;
  releaseMatchCount?: number;
  anomalyLevel?: 'baseline' | 'normal' | 'watch' | 'high';
  routingConfidence?: number;
  routingEvidence?: string[];
  routingRuleId?: number | null;
}

export interface ProjectModule {
  id: number;
  projectId: number;
  name: string;
  code: string;
  description?: string;
  ownerUserId?: number | null;
  repoId?: number | null;
  pathPattern?: string;
  tags?: string;
  createdAt: string;
  updatedAt: string;
}

export interface IssueRoutingRule {
  id: number;
  projectId: number;
  matchType: 'source_type' | 'platform' | 'app_version' | 'fingerprint_pattern' | 'stack_keyword';
  matchValue: string;
  moduleId?: number | null;
  ownerUserId?: number | null;
  priorityOverride?: string;
  severityOverride?: string;
  enabled: boolean;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
}

export interface AppRelease {
  id: number;
  projectId: number;
  platform: string;
  appVersion: string;
  buildNumber?: string;
  channel?: string;
  releaseTime: string;
  commitSha?: string;
  repoId?: number | null;
  metadataJson?: string;
  createdAt: string;
  updatedAt: string;
}

export interface AppReleaseTrend {
  release: AppRelease;
  clusterCount: number;
  signalCount: number;
  affectedUserCount: number;
  lastSeenAt?: string;
  previousRelease?: AppRelease | null;
  previousClusterCount: number;
  previousAffectedUserCount: number;
  clusterDelta: number;
  affectedUserDelta: number;
  anomalyLevel: 'baseline' | 'normal' | 'watch' | 'high';
}

export interface IssueClusterReleaseMatch {
  release: AppRelease;
  matchMode: 'exact_build' | 'app_version';
  signalCount: number;
  affectedUserCount: number;
  lastSeenAt: string;
}

export interface IssuePoolReleaseSummary {
  release: AppRelease;
  clusterCount: number;
  signalCount: number;
  affectedUserCount: number;
  lastSeenAt: string;
}

export interface RegressionItem {
  id: number;
  projectId: number;
  clusterId?: number | null;
  defectId?: number | null;
  title: string;
  summary?: string;
  sourceFingerprint?: string;
  status: 'draft' | 'active' | 'verified' | 'archived';
  ownerUserId?: number | null;
  createdBy: number;
  lastVerifiedAt?: string | null;
  createdAt: string;
  updatedAt: string;
  cluster?: IssueCluster | null;
  defect?: Defect | null;
  owner?: User | null;
  creator?: User | null;
}

export interface QualityIssuePoolSummary {
  totalClusters: number;
  openClusters: number;
  convertedClusters: number;
  ignoredClusters: number;
  totalSignals: number;
  affectedUserCount: number;
}

export interface QualityRegressionSummary {
  totalItems: number;
  openItems: number;
  verifiedItems: number;
  archivedItems: number;
}

export interface QualityReleaseHealthSummary {
  baselineCount: number;
  normalCount: number;
  watchAnomalyCount: number;
  highAnomalyCount: number;
}

export interface QualityAISummary {
  analysisCount: number;
  fixTaskCount: number;
  successfulCount: number;
  fallbackCount: number;
  failedCount: number;
  averageDurationMs: number;
  totalTokens: number;
  estimatedCostUsd: number;
}

export interface QualitySourceBreakdown {
  sourceType: string;
  signalCount: number;
  clusterCount: number;
  affectedUserCount: number;
}

export interface QualityModuleHotspot {
  moduleId?: number | null;
  moduleName: string;
  clusterCount: number;
  openClusterCount: number;
  convertedClusterCount: number;
  affectedUserCount: number;
  highAnomalyClusterCount: number;
}

export interface QualityInsightsOverview {
  issuePool: QualityIssuePoolSummary;
  regression: QualityRegressionSummary;
  releaseHealth: QualityReleaseHealthSummary;
  ai: QualityAISummary;
  sourceBreakdowns: QualitySourceBreakdown[];
  moduleHotspots: QualityModuleHotspot[];
  topReleaseAnomalies: AppReleaseTrend[];
}

// AGENT类型枚举
export const AGENT_TYPES = [
  { key: 'product', label: '产品AGENT', desc: '需求理解、业务逻辑分析' },
  { key: 'ui', label: 'UI_AGENT', desc: '视觉规范分析、交互设计评估' },
  { key: 'frontend', label: '前端AGENT', desc: '前端代码分析、性能诊断' },
  { key: 'client', label: '客户端AGENT', desc: '移动端特性分析、平台适配' },
  { key: 'backend', label: '后端AGENT', desc: '服务端逻辑分析、API设计评估' },
  { key: 'test', label: '测试AGENT', desc: '测试用例分析、覆盖评估' },
] as const;
