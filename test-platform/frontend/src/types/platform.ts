export interface CurrentUser {
  id: string;
  username: string;
  display_name: string;
  status: string;
  must_change_password: boolean;
}

export interface AuthState {
  user: CurrentUser;
  roles: string[];
  platform_permissions: string[];
  tool_permissions: Record<string, string[]>;
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
  apply_mode: string;
  editable: boolean;
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
