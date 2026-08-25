import type { PlatformRole, ProjectSummary, ToolGrantSummary } from "./access";

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string;
  status: string;
  must_change_password: boolean;
}

export interface AuthState {
  user: CurrentUser;
  /** 当前发布窗口兼容 roles，但固定角色判断只读取 role。 */
  role: PlatformRole | null;
  roles: string[];
  projects: ProjectSummary[];
  extra_tool_grants: ToolGrantSummary[];
  platform_permissions: string[];
  tool_permissions: Record<string, string[]>;
  permission_version: number;
  session_expires_at: string;
}

export interface UserSession {
  id: string;
  created_at: string;
  last_seen_at: string;
  absolute_expires_at: string;
  ip_address: string | null;
  current: boolean;
}

export interface AdminUser extends CurrentUser {
  role: PlatformRole;
  projects: ProjectSummary[];
  extra_tool_grants: ToolGrantSummary[];
  /** @deprecated 仅供旧页面过渡；固定角色页面不再读取。 */
  role_ids: string[];
  last_login_at: string | null;
  created_at: string;
}

export interface RoleGrant {
  permission_code: string;
  resource_type: "platform" | "tool";
  resource_id: string;
}

export interface Role {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  grants: RoleGrant[];
}

export interface ConfigDefinition {
  id: string;
  key: string;
  display_name: string;
  description: string;
  owner_type: string;
  owner_id: string;
  group_key: string;
  value_type: string;
  sensitivity: string;
  required: boolean;
  default_value: unknown;
  validation_schema: Record<string, unknown>;
  apply_mode: string;
  editable: boolean;
  sort_order: number;
  value_scope: "system" | "user";
  credential_provider_type: string | null;
}

export interface ConfigReleaseItem {
  definition_id: string;
  value: unknown;
}

export interface ConfigRelease {
  id: string;
  environment_id: string;
  owner_type: string;
  owner_id: string;
  version: number;
  revision: number;
  status: string;
  created_by: string;
  published_by: string | null;
  created_at: string;
  published_at: string | null;
  items: ConfigReleaseItem[];
}

export interface PermissionDefinition {
  code: string;
  name: string;
  description: string;
  resource_type: "platform" | "tool";
}

export interface SecretMetadata {
  id: string;
  environment_id: string;
  owner_type: string;
  owner_id: string;
  definition_id: string;
  configured: boolean;
  status: string;
  version: number | null;
  expires_at: string | null;
  updated_at: string;
}

export interface CredentialMetadata {
  id: string;
  tool_id: string;
  environment_id: string;
  provider_type: string;
  status: string;
  current_version: number;
  expires_at: string | null;
  refresh_expires_at: string | null;
  last_error_code: string | null;
  last_checked_at: string | null;
}

export interface PersonalCredentialField {
  key: string;
  display_name: string;
  required: boolean;
  configured: boolean;
}

/** 当前登录用户的 Credential 安全摘要，永不包含字段值或可反推指纹。 */
export interface PersonalCredential {
  id: string;
  tool_id: string;
  environment_id: string;
  provider_type: string;
  status: string;
  current_version: number;
  expires_at: string | null;
  refresh_expires_at: string | null;
  last_checked_at: string | null;
  last_error_code: string | null;
  fields: PersonalCredentialField[];
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_id: string | null;
  actor_snapshot: Record<string, unknown>;
  action: string;
  resource_type: string;
  resource_id: string | null;
  tool_id: string | null;
  environment_id: string | null;
  outcome: string;
  error_code: string | null;
  request_id: string | null;
  detail: string;
}

export interface LlmProfile {
  id: string;
  name: string;
  description: string;
  protocol: string;
  is_archived: boolean;
  environment_id: string;
  active_release_id: string | null;
  active_release_version: number | null;
  api_key_configured: boolean;
  binding_count: number;
}

export interface LlmBinding {
  id: string;
  tool_id: string;
  capability_key: string;
  display_name: string;
  description: string;
  environment_id: string;
  active_release_id: string | null;
  active_release_version: number | null;
  profile_id: string | null;
  enabled: boolean | null;
  api_key_override_configured: boolean;
}

export interface LlmEffectiveConfig {
  status: string;
  binding_id: string;
  profile_name: string;
  model: string;
  base_url: string;
  snapshot_id: string;
  api_key_configured: boolean;
}

/** 当前用户在指定环境的个人 LLM 连接摘要。 */
export interface PersonalLlmProfile {
  id: string;
  name: string;
  description: string;
  provider: string;
  is_archived: boolean;
  environment_id: string;
  active_release_id: string | null;
  active_release_version: number | null;
  base_url: string | null;
  model: string | null;
  temperature: number | null;
  max_tokens: number | null;
  timeout_seconds: number | null;
  enabled: boolean | null;
  api_key_configured: boolean;
  binding_count: number;
  created_at: string;
  updated_at: string;
}

/** 公共能力目录与当前用户个人 Binding 的安全合并视图。 */
export interface PersonalLlmBinding {
  id: string | null;
  binding_id: string;
  tool_id: string;
  capability_key: string;
  display_name: string;
  description: string;
  environment_id: string;
  active_release_id: string | null;
  current_version: number;
  profile_id: string | null;
  enabled: boolean | null;
  model_override: string | null;
  temperature_override: number | null;
  max_tokens_override: number | null;
  timeout_seconds_override: number | null;
  api_key_override_configured: boolean;
}

/** 管理员只读就绪度行，不包含 Credential、Profile 或 Secret 内部资源 ID。 */
export interface CredentialReadiness {
  resource_type: "credential" | "llm_binding";
  user_id: string;
  username: string;
  user_status: string;
  environment_id: string;
  tool_id: string;
  provider_type: string | null;
  capability_key: string | null;
  readiness_status: "configured" | "missing" | "invalid" | "expiring";
  credential_status: string | null;
  current_version: number;
  configured_field_count: number;
  required_field_count: number;
  expires_at: string | null;
  refresh_expires_at: string | null;
  last_checked_at: string | null;
  last_error_code: string | null;
}
