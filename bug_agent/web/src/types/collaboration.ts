export interface CollaborationTask {
  id: number;
  taskCode: string;
  defectId: number;
  triggerUserId: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'timeout';
  agentTypes: string[];
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface AgentResult {
  agentType: string;
  status: string;
  analysis?: Record<string, unknown>;
  solution?: Record<string, unknown>;
  reportId?: number;
  errorMsg?: string;
}

export interface AggregatedReport {
  taskId: number;
  taskCode: string;
  agents: AgentResult[];
  consensus: Record<string, number>;
  summary: string;
  riskLevel: 'high' | 'medium' | 'low';
  recommendation: string;
  timestamp: string;
}
