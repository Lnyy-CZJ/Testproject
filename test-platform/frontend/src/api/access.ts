import { apiJson } from "./client";
import type { ImpactPreview, ProjectMember, ProjectRecord, ProjectSummary, ToolAccessRecord, ToolGrantSummary } from "../types/access";

/** 项目与授权接口只复用 apiJson，统一继承 CSRF、超时和错误码处理。 */
export const accessApi = {
  listProjects: () => apiJson<ProjectRecord[]>("/projects"),
  getProject: (projectId: string) => apiJson<ProjectRecord>(`/projects/${encodeURIComponent(projectId)}`),
  createProject: (payload: { code: string; name: string; description: string }) => apiJson<ProjectRecord>("/projects", { method: "POST", body: JSON.stringify({ ...payload, reason: "创建项目" }) }),
  projectImpact: (projectId: string) => apiJson<ImpactPreview>(`/projects/${encodeURIComponent(projectId)}/deactivation-impact`),
  setProjectStatus: (projectId: string, payload: Record<string, unknown>) => apiJson<ProjectRecord>(`/projects/${encodeURIComponent(projectId)}/${payload.status === "active" ? "activate" : "deactivate"}`, { method: "POST", body: JSON.stringify(payload) }),
  listProjectMembers: (projectId: string, relation: "members" | "managers") => apiJson<ProjectMember[]>(`/projects/${encodeURIComponent(projectId)}/${relation}`),
  addProjectMember: (projectId: string, relation: "members" | "managers", username: string) => apiJson(`/projects/${encodeURIComponent(projectId)}/${relation}`, { method: "POST", body: JSON.stringify({ username, reason: relation === "members" ? "添加项目成员" : "添加项目负责人" }) }),
  removeProjectMember: (projectId: string, relation: "members" | "managers", userId: string, reason: string) => apiJson(`/projects/${encodeURIComponent(projectId)}/${relation}/${encodeURIComponent(userId)}`, { method: "DELETE", body: JSON.stringify({ reason }) }),
  listProjectTools: (projectId: string) => apiJson<ToolAccessRecord[]>(`/projects/${encodeURIComponent(projectId)}/tools`),
  listToolAccess: () => apiJson<ToolAccessRecord[]>("/admin/tool-access"),
  toolImpact: (toolId: string, accessScope: "public" | "project", projectId: string | null) => apiJson<ImpactPreview>(`/admin/tool-access/${encodeURIComponent(toolId)}/impact`, { method: "POST", body: JSON.stringify({ access_scope: accessScope, project_id: projectId }) }),
  updateToolAccess: (toolId: string, payload: Record<string, unknown>) => apiJson<ToolAccessRecord>(`/admin/tool-access/${encodeURIComponent(toolId)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listGrants: () => apiJson<ToolGrantSummary[]>("/admin/tool-grants"),
  createGrant: (payload: Record<string, unknown>) => apiJson<ToolGrantSummary>("/admin/tool-grants", { method: "POST", body: JSON.stringify(payload) }),
  renewGrant: (grantId: string, payload: Record<string, unknown>) => apiJson<ToolGrantSummary>(`/admin/tool-grants/${encodeURIComponent(grantId)}/renew`, { method: "POST", body: JSON.stringify(payload) }),
  revokeGrant: (grantId: string, reason: string) => apiJson(`/admin/tool-grants/${encodeURIComponent(grantId)}/revoke`, { method: "POST", body: JSON.stringify({ reason }) }),
  projectChoices: () => apiJson<ProjectSummary[]>("/projects"),
};
