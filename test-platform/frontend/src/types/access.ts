/** 固定角色、项目范围与工具来源的前端领域类型。所有值均由平台 API 决定。 */
export type PlatformRole = "platform_admin" | "admin" | "tester";
export type ProjectStatus = "active" | "inactive";
export type ProjectRelation = "manager" | "member";
export type ToolAccessScope = "public" | "project";
export type ToolAccessSource = "platform_admin" | "public" | "project_manager" | "project_member" | "extra_grant";

export interface ProjectSummary {
  id: string;
  code: string;
  name: string;
  status: ProjectStatus;
  relation: ProjectRelation | null;
}

export interface ProjectRecord extends ProjectSummary {
  description: string;
  revision: number;
  manager_count: number;
  member_count: number;
  tool_count: number;
  active_grant_count: number;
  updated_at: string;
}

export interface ProjectMember {
  id: string;
  username: string;
  display_name: string;
  role: PlatformRole;
  status: "active" | "disabled";
}

export interface ImpactPreview {
  expected_revision: number;
  impact_token: string;
  manager_count?: number;
  member_count?: number;
  tool_count?: number;
  active_grant_count?: number;
  affected_user_count?: number;
  running_task_count: number | "unknown" | null;
}

export interface ToolGrantSummary {
  id: string;
  user_id?: string;
  username?: string;
  tool_id: string;
  tool_name: string;
  project_id: string;
  project_name: string;
  granted_at: string;
  expires_at: string;
  status: "active" | "expired" | "revoked";
  grant_reason: string;
}

export interface ToolAccessRecord {
  id: string;
  name: string;
  description: string;
  access_scope: ToolAccessScope;
  project_id: string | null;
  project_name: string | null;
  is_enabled: boolean;
  revision: number;
  updated_at: string;
  public_policy_complete?: boolean;
  public_eligible: boolean;
}
