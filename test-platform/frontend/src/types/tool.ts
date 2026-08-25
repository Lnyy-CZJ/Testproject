/** 平台工具目录接口返回的单个工具。 */
export interface Tool {
  id: string;
  name: string;
  description: string;
  entry_url: string;
  short_code: string;
  icon_key: string;
  category: string;
  features: string[];
  sort_order: number;
  /** 目录返回的主要来源仅用于解释，不可由前端推导授权。 */
  access_scope?: ToolAccessScope;
  access_source?: ToolAccessSource;
  project?: { id: string; code: string; name: string } | null;
  can_manage?: boolean;
  fallback_health_path?: string;
}

/** 工具列表接口响应。 */
export interface ToolListResponse {
  items: Tool[];
}

/** 工具在首页展示的健康状态。 */
export type ToolHealthState = "checking" | "healthy" | "unhealthy";

/** 平台产品层的四个稳定能力域。 */
export type CapabilityDomainId =
  | "ai-testing"
  | "automation"
  | "quality-analysis"
  | "domain-evaluation";

/** 工具在工作台中的使命、输入输出和边界定义。 */
export interface CapabilityDefinition {
  toolId: string;
  domainId: CapabilityDomainId;
  displayName: string;
  mission: string;
  scenario: string;
  inputSummary: string;
  outputSummary: string;
  boundary?: string;
  actionLabel: string;
  visualPriority: "primary" | "standard";
}

/** 后端授权目录与产品层定义合并后的页面模型。 */
export interface CapabilityViewModel extends CapabilityDefinition {
  tool: Tool;
  health: ToolHealthState;
}

/** 平台后端健康检查响应。 */
export interface PlatformToolHealthResponse {
  tool_id: string;
  status: "healthy" | "unhealthy";
  checked_at: string;
}
import type { ToolAccessScope, ToolAccessSource } from "./access";
