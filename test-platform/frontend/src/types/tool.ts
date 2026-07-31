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
  fallback_health_path?: string;
}

/** 工具列表接口响应。 */
export interface ToolListResponse {
  items: Tool[];
}

/** 工具在首页展示的健康状态。 */
export type ToolHealthState = "checking" | "healthy" | "unhealthy";

/** 平台后端健康检查响应。 */
export interface PlatformToolHealthResponse {
  tool_id: string;
  status: "healthy" | "unhealthy";
  checked_at: string;
}
