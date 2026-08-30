import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import {
  AUTH_REQUIRED_EVENT,
  currentAuthGeneration,
  request,
} from "./api/client";
import type { AuthState } from "./types/platform";

const auth: AuthState = {
  user: { id: "usr_1", username: "admin", display_name: "平台管理员", status: "active", must_change_password: false },
  role: "platform_admin",
  roles: ["platform_admin"],
  projects: [],
  extra_tool_grants: [],
  platform_permissions: ["platform.user.manage", "platform.role.manage", "platform.audit.view", "platform.config.manage", "platform.secret.manage", "platform.llm.manage", "platform.llm.secret.manage", "platform.credential.readiness.view"],
  tool_permissions: { trackevents: ["tool.view", "tool.execute", "tool.result.view"] },
  permission_version: 1,
  session_expires_at: "2026-08-11T00:00:00Z",
};

const tool = {
  id: "trackevents", name: "埋点测试", description: "解析埋点日志",
  entry_url: "/trackevents/", short_code: "EVENT", icon_key: "event",
  category: "analysis", features: ["事件统计"], sort_order: 10,
};

const allTools = [
  { ...tool, id: "functional-test-agent", name: "功能测试智能体", entry_url: "/functional-test-agent/", short_code: "FT AI", icon_key: "functional-ai", category: "ai-testing", sort_order: 10 },
  { ...tool, id: "api-test-agent", name: "API 测试智能体", entry_url: "/api-test-agent/", short_code: "API AI", icon_key: "api-ai", category: "ai-testing", sort_order: 20 },
  { ...tool, id: "api-autotest", name: "接口自动化", entry_url: "/api-autotest/", short_code: "API", icon_key: "api", category: "automation", sort_order: 30 },
  { ...tool, id: "trackevents", name: "埋点分析", entry_url: "/trackevents/", category: "analysis", sort_order: 40 },
  { ...tool, id: "log-filter", name: "日志分析", entry_url: "/log-filter/", short_code: "LOG", icon_key: "log", category: "analysis", sort_order: 50 },
  { ...tool, id: "truthy-search", name: "检索评测", entry_url: "/truthy-search/", short_code: "SEARCH", icon_key: "search", category: "evaluation", sort_order: 60 },
];

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }));
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  sessionStorage.clear();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockAuthenticatedCatalog(items = allTools, currentAuth: AuthState = auth) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/auth/me")) return jsonResponse(currentAuth);
    if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
    if (url.endsWith("/tools")) return jsonResponse({ items });
    if (url.endsWith("/health/live")) return jsonResponse({ status: "ok", version: "1.1.0", component_version: "1.1.0", revision: "abc", dirty: false, runtime_environment: "dev" });
    if (url.includes("/credentials?")) return jsonResponse([]);
    return jsonResponse({ tool_id: items[0]?.id, status: "healthy", checked_at: "2026-08-17T00:00:00Z" });
  });
}

/** 创建可由测试精确结算的 fetch 响应，用于复现旧请求迟到的认证竞态。 */
function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((complete) => { resolve = complete; });
  return { promise, resolve };
}

describe("第三阶段 AI 测试工作台", () => {
  it("恢复原主页，并把权限与项目放在专项评测之后", async () => {
    mockAuthenticatedCatalog();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "工具工作台" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "权限与项目" })).not.toBeInTheDocument();

    const primaryLinks = screen.getByRole("navigation", { name: "主导航" }).querySelectorAll("a");
    const labels = Array.from(primaryLinks, (link) => link.textContent);
    expect(labels.indexOf("权限与项目")).toBeGreaterThan(labels.indexOf("专项评测"));
    expect(screen.getByRole("link", { name: "权限与项目" })).toHaveAttribute("href", "/access");
  });

  it("权限与项目汇总当前平台的项目、权限、个人和配置入口", async () => {
    window.history.replaceState({}, "", "/access");
    mockAuthenticatedCatalog([]);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "权限与项目" })).toBeInTheDocument();
    const expectedLinks = [
      ["我的项目", "/projects?scope=mine"], ["项目管理", "/projects"], ["用户管理", "/admin/users"],
      ["工具管理", "/admin/tool-access"], ["额外授权", "/admin/tool-grants"], ["固定角色", "/admin/roles"],
      ["账号与会话", "/account"], ["修改密码", "/account/password"], ["我的凭证", "/account/credentials"],
      ["我的 LLM", "/account/llm"], ["平台 LLM 配置", "/settings/platform-llm"],
      ["普通配置", "/settings/config"], ["Secret", "/settings/secrets"],
      ["凭证代理", "/settings/credential-agents"], ["凭证就绪度", "/settings/credentials"],
      ["审计日志", "/audit"], ["版本状态", "/system/versions"],
    ];
    for (const [name, href] of expectedLinks) {
      expect(screen.getAllByRole("link", { name }).some((link) => link.getAttribute("href") === href)).toBe(true);
    }
  });

  it("创建项目使用独立页面而不是通用弹窗", async () => {
    window.history.replaceState({}, "", "/projects/new");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects")) return jsonResponse([]);
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "创建项目" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("基础信息")).toBeInTheDocument();
    expect(screen.getByLabelText("Active（默认）")).toBeChecked();
    expect(screen.getByText("分配负责人 → 加入测试成员 → 关联项目工具")).toBeInTheDocument();
  });

  it("项目人员页可按完整用户名添加测试人员并在成功后刷新列表", async () => {
    window.history.replaceState({}, "", "/projects/project_a/members");
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: null, revision: 1, manager_count: 0, member_count: 0, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    const tester = { id: "tester_1", username: "tester.one", display_name: "测试人员一", role: "tester", status: "active" };
    let memberAdded = false;
    let postBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/managers")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members") && init?.method === "POST") {
        postBody = JSON.parse(String(init.body)); memberAdded = true; return jsonResponse(tester, 201);
      }
      if (url.endsWith("/projects/project_a/members")) return jsonResponse(memberAdded ? [tester] : []);
      return jsonResponse({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "添加成员" }));
    const dialog = screen.getByRole("dialog", { name: "添加测试人员" });
    fireEvent.change(within(dialog).getByLabelText("完整用户名"), { target: { value: "tester.one" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认添加" }));

    await waitFor(() => expect(postBody).toEqual({ username: "tester.one", reason: "添加项目成员" }));
    expect(await screen.findByText("测试人员一")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("项目人员添加失败时在弹窗内展示错误并允许修正用户名", async () => {
    window.history.replaceState({}, "", "/projects/project_a/members");
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: null, revision: 1, manager_count: 0, member_count: 0, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/managers")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members") && init?.method === "POST") return jsonResponse({ code: "USER_NOT_FOUND", message: "用户不存在" }, 404);
      if (url.endsWith("/projects/project_a/members")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "添加成员" }));
    const dialog = screen.getByRole("dialog", { name: "添加测试人员" });
    fireEvent.change(within(dialog).getByLabelText("完整用户名"), { target: { value: "missing.user" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认添加" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("用户不存在");
    expect(within(dialog).getByLabelText("完整用户名")).toHaveValue("missing.user");
  });

  it("成员关系已创建但列表刷新失败时关闭弹窗并展示可恢复提示", async () => {
    window.history.replaceState({}, "", "/projects/project_a/members");
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: null, revision: 1, manager_count: 0, member_count: 0, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    const tester = { id: "tester_1", username: "tester.one", display_name: "测试人员一", role: "tester", status: "active" };
    let memberListReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/managers")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members") && init?.method === "POST") return jsonResponse(tester, 201);
      if (url.endsWith("/projects/project_a/members")) {
        memberListReads += 1;
        return memberListReads === 1 ? jsonResponse([]) : jsonResponse({ code: "READ_FAILED", message: "列表读取失败" }, 503);
      }
      return jsonResponse({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "添加成员" }));
    const dialog = screen.getByRole("dialog", { name: "添加测试人员" });
    fireEvent.change(within(dialog).getByLabelText("完整用户名"), { target: { value: "tester.one" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认添加" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("人员已添加，但列表刷新失败");
    expect(screen.queryByRole("dialog", { name: "添加测试人员" })).not.toBeInTheDocument();
  });

  it("普通管理员的人员页不伪造负责人空状态", async () => {
    window.history.replaceState({}, "", "/projects/project_a/members");
    const projectAdmin: AuthState = { ...auth, role: "admin", roles: ["admin"], platform_permissions: [], projects: [{ id: "project_a", code: "TEST-1", name: "test", status: "active", relation: "manager" }] };
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: "manager", revision: 1, manager_count: 1, member_count: 0, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(projectAdmin);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/members")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "测试成员" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "项目负责人" })).not.toBeInTheDocument();
    expect(screen.queryByText("尚未分配负责人")).not.toBeInTheDocument();
  });

  it("普通管理员在项目概览只看到负责人数量而非错误空状态", async () => {
    window.history.replaceState({}, "", "/projects/project_a/overview");
    const projectAdmin: AuthState = { ...auth, role: "admin", roles: ["admin"], platform_permissions: [], projects: [{ id: "project_a", code: "TEST-1", name: "test", status: "active", relation: "manager" }] };
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: "manager", revision: 1, manager_count: 1, member_count: 0, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(projectAdmin);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/members")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    expect(await screen.findByText("1 位，由平台管理员维护")).toBeInTheDocument();
    expect(screen.queryByText("尚未分配")).not.toBeInTheDocument();
  });

  it("删除成员兼容 204 空响应并在提交后刷新列表", async () => {
    window.history.replaceState({}, "", "/projects/project_a/members");
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: null, revision: 1, manager_count: 0, member_count: 1, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    const tester = { id: "tester_1", username: "tester.one", display_name: "测试人员一", role: "tester", status: "active" };
    let deleted = false;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/managers")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members/tester_1") && init?.method === "DELETE") { deleted = true; return Promise.resolve(new Response(null, { status: 204 })); }
      if (url.endsWith("/projects/project_a/members")) return jsonResponse(deleted ? [] : [tester]);
      return jsonResponse({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /移除成员/ }));
    expect(await screen.findByText("暂无测试成员")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("从项目创建测试人员时固定角色且不允许切换为管理员", async () => {
    window.history.replaceState({}, "", "/admin/users?project_id=project_a");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/admin/users")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    expect(await screen.findByRole("dialog", { name: "创建测试人员" })).toBeInTheDocument();
    expect(screen.queryByLabelText("固定角色")).not.toBeInTheDocument();
  });

  it("创建账号成功但加入项目失败时只重试项目关系", async () => {
    window.history.replaceState({}, "", "/admin/users?project_id=project_a");
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: null, revision: 1, manager_count: 0, member_count: 1, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    const tester = { id: "tester_1", username: "tester.retry", display_name: "重试测试人员", role: "tester", status: "active" };
    let userCreateCount = 0;
    let membershipCreateCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/admin/users") && init?.method === "POST") { userCreateCount += 1; return jsonResponse(tester, 201); }
      if (url.endsWith("/admin/users")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members") && init?.method === "POST") {
        membershipCreateCount += 1;
        return membershipCreateCount === 1
          ? jsonResponse({ code: "TEMPORARY_FAILURE", message: "临时写入失败" }, 503)
          : jsonResponse(tester, 201);
      }
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/managers")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members")) return jsonResponse([tester]);
      return jsonResponse({});
    });
    render(<App />);

    const dialog = await screen.findByRole("dialog", { name: "创建测试人员" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "tester.retry" } });
    fireEvent.change(within(dialog).getByLabelText("显示名称"), { target: { value: "重试测试人员" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: "StrongPassword!1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认创建" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("账号已创建，但加入项目失败");
    expect(within(dialog).getByLabelText("用户名")).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "重试加入项目" }));

    await waitFor(() => expect(membershipCreateCount).toBe(2));
    expect(userCreateCount).toBe(1);
    expect(await screen.findByRole("heading", { name: "测试成员" })).toBeInTheDocument();
  });

  it("关系首次结果未知、重试发现同一成员已存在时按成功恢复", async () => {
    window.history.replaceState({}, "", "/admin/users?project_id=project_a");
    const project = { id: "project_a", code: "TEST-1", name: "test", description: "", status: "active", relation: null, revision: 1, manager_count: 0, member_count: 1, tool_count: 0, active_grant_count: 0, updated_at: "2026-08-30T00:00:00Z" };
    const tester = { id: "tester_unknown", user_id: "tester_unknown", username: "tester.unknown", display_name: "未知结果测试人员", role: "tester", status: "active" };
    let userCreateCount = 0;
    let membershipCreateCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/admin/users") && init?.method === "POST") { userCreateCount += 1; return jsonResponse(tester, 201); }
      if (url.endsWith("/admin/users")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members") && init?.method === "POST") {
        membershipCreateCount += 1;
        return membershipCreateCount === 1
          ? Promise.reject(new TypeError("response lost after commit"))
          : jsonResponse({ code: "PROJECT_RELATION_EXISTS", message: "用户已在项目中" }, 409);
      }
      if (url.endsWith("/projects/project_a")) return jsonResponse(project);
      if (url.endsWith("/projects/project_a/tools") || url.endsWith("/projects/project_a/managers")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members")) return jsonResponse([tester]);
      return jsonResponse({});
    });
    render(<App />);

    const dialog = await screen.findByRole("dialog", { name: "创建测试人员" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "tester.unknown" } });
    fireEvent.change(within(dialog).getByLabelText("显示名称"), { target: { value: "未知结果测试人员" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: "StrongPassword!2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认创建" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("账号已创建，但加入项目失败");
    fireEvent.click(within(dialog).getByRole("button", { name: "重试加入项目" }));

    await waitFor(() => expect(membershipCreateCount).toBe(2));
    expect(userCreateCount).toBe(1);
    expect(await screen.findByRole("heading", { name: "测试成员" })).toBeInTheDocument();
  });

  it("重复关系属于其他用户时不得把未知提交结果误判为成功", async () => {
    window.history.replaceState({}, "", "/admin/users?project_id=project_a");
    const createdTester = { id: "tester_target", username: "tester.target", display_name: "目标测试人员", role: "tester", status: "active" };
    const otherTester = { id: "tester_other", user_id: "tester_other", username: "tester.other", display_name: "其他测试人员", role: "tester", status: "active" };
    let membershipCreateCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/admin/users") && init?.method === "POST") return jsonResponse(createdTester, 201);
      if (url.endsWith("/admin/users")) return jsonResponse([]);
      if (url.endsWith("/projects/project_a/members") && init?.method === "POST") {
        membershipCreateCount += 1;
        return membershipCreateCount === 1
          ? Promise.reject(new TypeError("response lost"))
          : jsonResponse({ code: "PROJECT_RELATION_EXISTS", message: "用户已在项目中" }, 409);
      }
      if (url.endsWith("/projects/project_a/members")) return jsonResponse([otherTester]);
      return jsonResponse({});
    });
    render(<App />);

    const dialog = await screen.findByRole("dialog", { name: "创建测试人员" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "tester.target" } });
    fireEvent.change(within(dialog).getByLabelText("显示名称"), { target: { value: "目标测试人员" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: "StrongPassword!4" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认创建" }));
    await within(dialog).findByRole("alert");
    fireEvent.click(within(dialog).getByRole("button", { name: "重试加入项目" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("用户已在项目中");
    expect(screen.getByRole("dialog", { name: "创建测试人员" })).toBeInTheDocument();
  });

  it("创建账号请求提交期间按 Esc 不关闭弹窗", async () => {
    window.history.replaceState({}, "", "/admin/users");
    let resolveCreate!: (response: Response) => void;
    const createResponse = new Promise<Response>((resolve) => { resolveCreate = resolve; });
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/admin/users") && init?.method === "POST") return createResponse;
      if (url.endsWith("/admin/users")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "创建用户" }));
    const dialog = screen.getByRole("dialog", { name: "创建用户" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "tester.busy" } });
    fireEvent.change(within(dialog).getByLabelText("显示名称"), { target: { value: "提交中测试人员" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: "StrongPassword!3" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认创建" }));

    expect(await within(dialog).findByRole("button", { name: "提交中…" })).toBeDisabled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "创建用户" })).toBeInTheDocument();
    void jsonResponse({ id: "tester_busy" }, 201).then(resolveCreate);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "创建用户" })).not.toBeInTheDocument());
  });

  it("工具详情按新版范围与归属页面展示影响预览入口", async () => {
    window.history.replaceState({}, "", "/admin/tool-access/functional-test-agent");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects")) return jsonResponse([{ id: "project_a", code: "PAY-QA", name: "支付测试", status: "active", relation: null }]);
      if (url.endsWith("/admin/tool-access")) return jsonResponse([{ id: "functional-test-agent", name: "功能测试智能体", description: "", access_scope: "project", project_id: "project_a", project_name: "支付测试", is_enabled: true, revision: 4, updated_at: "2026-08-24T00:00:00Z", public_eligible: true, public_policy_complete: true }]);
      if (url.endsWith("/admin/tool-grants")) return jsonResponse([]);
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "工具详情 · 范围与归属" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /项目工具/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "预览变更影响" })).toBeInTheDocument();
    expect(screen.getByText("历史资源")).toBeInTheDocument();
  });

  it("未登录时强制进入登录页，不显示匿名工具入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => String(input).endsWith("/version.json")
      ? jsonResponse({ runtime_environment: "prod" })
      : jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "欢迎回来" })).toBeInTheDocument();
    expect(await screen.findByText("PROD")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "测试开发平台" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("请输入用户名")).toHaveFocus();
    expect(screen.getByText("统一管理测试资产")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /打开工具/ })).not.toBeInTheDocument();
  });

  it("按使命展示六项已授权能力和五个业务导航", async () => {
    mockAuthenticatedCatalog();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "功能测试智能体" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "API 测试智能体" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "接口自动化" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "工作台" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI 测试" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "自动化" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "质量分析" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "专项评测" })).toBeInTheDocument();
    expect(screen.getByText(/1\.3\.0/)).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "平台状态" })).toHaveTextContent("运行环境DEV");
    expect(screen.queryByRole("link", { name: "查看版本详情" })).not.toBeInTheDocument();
  });

  it("只渲染服务端返回的能力，不由 Catalog 补回其余工具", async () => {
    mockAuthenticatedCatalog([allTools[3]]);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "埋点分析" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "功能测试智能体" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "AI 测试" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "质量分析" })).toBeInTheDocument();
  });

  it("工具目录异常时失败关闭，不恢复静态入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => String(input).endsWith("/auth/me") ? jsonResponse(auth) : jsonResponse({ code: "DATABASE_UNAVAILABLE", message: "数据库不可用" }, 503));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("不会恢复匿名入口");
    expect(screen.queryByRole("link", { name: "开始埋点分析" })).not.toBeInTheDocument();
  });

  it("路由切换和健康刷新都不重新请求目录", async () => {
    const fetchMock = mockAuthenticatedCatalog([allTools[0], allTools[1]]);
    render(<App />);
    await screen.findAllByText("正常");
    fireEvent.click(screen.getByRole("link", { name: "AI 测试" }));
    expect(await screen.findByRole("heading", { name: "AI 测试" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "工作台" }));
    fireEvent.click(await screen.findByRole("button", { name: "刷新状态" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/tools/") && String(url).endsWith("/health"))).toHaveLength(4));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/tools"))).toHaveLength(1);
  });

  it("能力路由无可见工具时展示通用无权限状态", async () => {
    window.history.replaceState({}, "", "/automation");
    mockAuthenticatedCatalog([allTools[3]]);
    render(<App />);
    expect(await screen.findByText("当前账号没有该能力域的可见工具")).toBeInTheDocument();
    expect(screen.queryByText("接口自动化")).not.toBeInTheDocument();
  });

  it("平台管理入口继续受平台权限控制", async () => {
    window.history.replaceState({}, "", "/access");
    mockAuthenticatedCatalog([]);
    render(<App />);
    expect((await screen.findAllByRole("link", { name: "用户管理" })).some((link) => link.getAttribute("href") === "/admin/users")).toBe(true);
    expect(screen.getAllByRole("link", { name: "工具管理" }).some((link) => link.getAttribute("href") === "/admin/tool-access")).toBe(true);
    cleanup();
    const readonly: AuthState = { ...auth, role: "tester", roles: ["tester"], platform_permissions: [] };
    mockAuthenticatedCatalog([], readonly);
    render(<App />);
    await screen.findByRole("heading", { name: "权限与项目" });
    expect(screen.queryByRole("link", { name: "用户管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "工具管理" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "我的凭证" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "我的 LLM" }).length).toBeGreaterThan(0);
    cleanup();
    const noRole: AuthState = { ...auth, role: null, roles: [], platform_permissions: [] };
    mockAuthenticatedCatalog([], noRole);
    render(<App />);
    await screen.findByRole("heading", { name: "权限与项目" });
    expect(screen.queryByRole("link", { name: "项目管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "用户管理" })).not.toBeInTheDocument();
  });

  it("配置环境切换不改变状态卡的真实运行环境", async () => {
    mockAuthenticatedCatalog([]);
    render(<App />);
    await waitFor(() => expect(screen.getByRole("complementary", { name: "平台状态" })).toHaveTextContent("运行环境DEV"));
    fireEvent.change(screen.getByLabelText("当前配置环境"), { target: { value: "prod" } });
    expect(screen.getByRole("complementary", { name: "平台状态" })).toHaveTextContent("运行环境DEV");
  });

  it("版本详情展示比较状态、展开身份且允许 Prod 部分失败", async () => {
    window.history.replaceState({}, "", "/system/versions");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/system/version-matrix")) return jsonResponse({
        checked_at: "2026-08-19T00:00:00Z", product_version: "1.1.0", runtime_environment: "dev",
        prod_error: "Prod 无法获取", dev: { database: { alembic_revision: "20260818_0016" }, config_releases: {} }, prod: null,
        database_comparison: { dev: { alembic_revision: "20260818_0016", schema_sha256: "schema-dev" }, prod: {}, issues: ["不可用"], primary_status: "不可用", data_compared: false },
        rows: [{ component_id: "functional-test-agent", manifest_version: "1.0.0", dev: { version: "1.0.0", revision: "devsha", dirty: true, runtime_environment: "dev", health: "healthy", digest: "sha256:arm" }, prod: null, prod_expected: null, issues: ["Dirty 构建"], primary_status: "Dirty 构建" }],
      });
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "版本状态" })).toBeInTheDocument();
    expect(await screen.findByText(/Prod 无法获取/)).toBeInTheDocument();
    expect(screen.getByText("Dirty 构建")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    expect(screen.getByText("devsha")).toBeInTheDocument();
    expect(screen.getByText("sha256:arm")).toBeInTheDocument();
  });

  it("拒绝不安全的工具入口", async () => {
    mockAuthenticatedCatalog([{ ...allTools[3], entry_url: "https://example.com/tool" }]);
    render(<App />);
    await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" });
    expect(screen.queryByRole("link", { name: "开始埋点分析" })).not.toBeInTheDocument();
  });

  it("未知工具使用通用卡片降级且不影响已登记能力", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const customTool = { ...tool, id: "custom-tool", name: "自定义工具", entry_url: "/custom-tool/" };
    mockAuthenticatedCatalog([allTools[3], customTool]);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "埋点分析" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "自定义工具" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /打开工具/ }).some((link) => link.getAttribute("href") === "/custom-tool/")).toBe(true);
  });

  it("单个健康请求失败只标记对应工具异常", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[0], allTools[1]] });
      if (url.includes("/credentials?")) return jsonResponse([]);
      if (url.includes("api-test-agent/health")) return jsonResponse({ code: "UPSTREAM_ERROR", message: "不可用" }, 503);
      return jsonResponse({ tool_id: allTools[0].id, status: "healthy", checked_at: "2026-08-17T00:00:00Z" });
    });
    render(<App />);
    expect(await screen.findByText("服务异常")).toBeInTheDocument();
    expect(screen.getByText("正常")).toBeInTheDocument();
  });

  it("支持一次性管理员初始化页", async () => {
    window.history.replaceState({}, "", "/setup");
    vi.spyOn(globalThis, "fetch").mockImplementation(() => jsonResponse({ code: "AUTH_REQUIRED" }, 401));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "初始化平台管理员" })).toBeInTheDocument();
    expect(screen.getByLabelText("Bootstrap Token")).toHaveAttribute("type", "password");
  });

  it("Secret 页仅展示元数据和替换入口", async () => {
    window.history.replaceState({}, "", "/settings/secrets?tool_id=truthy-search");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: allTools });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_search_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_search", platform_project_name: "检索项目", project_id: "search", display_name: "Search", target_env: "test", status: "active", is_default: true, revision: 1, active_release: null }] });
      if (url.includes("/config/definitions")) return jsonResponse([{ id: "truthy-search.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10, value_scope: "system", credential_provider_type: null }]);
      if (url.includes("/secrets?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByText("Access Token")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
    expect(screen.queryByText(/fake|token-value/i)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("owner_type=tool") && String(url).includes("owner_id=truthy-search"))).toBe(true);
  });

  it("配置控制面按 Runtime Scope 读取配置，并把固定 TEST 环境作为只读上下文", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_dating_dev_test");
    const scopes = {
      items: [{
        id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest",
        platform_project_id: "project_dating", platform_project_name: "Dating 平台项目",
        project_id: "dating", display_name: "Dating API", target_env: "test", status: "active",
        is_default: true, revision: 4, active_release: { id: "rel_dating_3", version: 3, status: "active" },
      }],
    };
    const definition = { id: "api-autotest.gateway.base_url", key: "gateway.base_url", display_name: "Gateway 地址", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "text", sensitivity: "normal", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/runtime-scopes?")) return jsonResponse(scopes);
      if (url.includes("/config/definitions")) return jsonResponse([definition]);
      if (url.includes("/config/releases?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    expect(await screen.findByLabelText("平台项目")).toHaveDisplayValue("Dating 平台项目");
    expect(screen.getByLabelText("工具项目")).toHaveDisplayValue("Dating API");
    expect(screen.getByLabelText("接口环境")).toHaveDisplayValue("TEST（由 DEV 平台固定）");
    expect(screen.getByLabelText("接口环境")).toBeDisabled();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("owner_type=tool_project_scope") && String(url).includes("owner_id=tps_dating_dev_test"))).toBe(true);
    expect(window.location.search).toBe("?scope_id=tps_dating_dev_test");
  });

  it("默认展示当前生效版本的 Dating Comm 静态值，并可查看历史版本", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_dating_dev_test");
    const definition = {
      id: "api-autotest.runtime.gateway.comm", key: "gateway.comm", display_name: "Gateway Comm 默认值",
      description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "json",
      sensitivity: "normal", required: true, default_value: null,
      validation_schema: {
        required_keys: ["device_id", "platform", "app_version"],
        forbidden_keys: ["auth_token", "user_id", "client_request_id"],
        field_order: ["device_id", "platform", "app_version", "locale", "timezone", "country", "app_package"],
        field_labels: { device_id: "Device ID", platform: "客户端平台", app_version: "客户端版本" },
      },
      apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null,
    };
    const release = (id: string, version: number, status: string, deviceId: string) => ({
      id, environment_id: "dev", owner_type: "tool_project_scope", owner_id: "tps_dating_dev_test",
      version, revision: 1, status, created_by: "admin", published_by: "admin",
      created_at: `2026-08-2${version}T00:00:00Z`, published_at: `2026-08-2${version}T00:00:00Z`,
      items: [{ definition_id: definition.id, value: {
        device_id: deviceId, platform: "ios", app_version: version === 3 ? "1.0.0" : "0.9.0",
        locale: "en-US", timezone: "UTC+08:00", country: "CN", app_package: "com.example.dating",
        client_request_id: "legacy-dynamic-value",
      } }],
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{
        id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest",
        platform_project_id: "project_dating", platform_project_name: "Dating 平台项目",
        project_id: "dating", display_name: "Dating AI Assistant", target_env: "test", status: "active",
        is_default: true, revision: 4, active_release: { id: "rel_dating_3", version: 3, status: "active" },
      }] });
      if (url.includes("/config/definitions")) return jsonResponse([definition]);
      if (url.includes("/config/releases?")) return jsonResponse([
        release("rel_dating_3", 3, "active", "dating-device-active"),
        release("rel_dating_2", 2, "superseded", "dating-device-history"),
      ]);
      return jsonResponse({});
    });
    render(<App />);

    await screen.findByLabelText("Device ID");
    await waitFor(() => expect(screen.getByLabelText("Device ID")).toHaveValue("dating-device-active"));
    const deviceInput = screen.getByLabelText("Device ID");
    expect(deviceInput).toBeDisabled();
    expect(screen.queryByDisplayValue("legacy-dynamic-value")).not.toBeInTheDocument();
    expect(screen.getByText("v3 · 当前生效")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看 v2 配置" }));
    expect(screen.getByLabelText("Device ID")).toHaveValue("dating-device-history");
    expect(screen.getByText("v2 · 历史版本")).toBeInTheDocument();
  });

  it("Dating 草稿可新增静态 Comm 参数，但不能配置运行时动态字段", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_dating_dev_test");
    let savedBody: { items?: Array<{ definition_id: string; value: unknown }> } | null = null;
    const definition = {
      id: "api-autotest.runtime.gateway.comm", key: "gateway.comm", display_name: "Gateway Comm 默认值",
      description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "json",
      sensitivity: "normal", required: true, default_value: null,
      validation_schema: {
        required_keys: ["device_id", "platform", "app_version"],
        forbidden_keys: ["auth_token", "user_id", "client_request_id"],
        property_name_pattern: "^[a-z][a-z0-9_]{0,63}$",
        field_order: ["device_id", "platform", "app_version"],
        field_labels: { device_id: "Device ID", platform: "客户端平台", app_version: "客户端版本" },
      },
      apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null,
    };
    const draft = {
      id: "rel_dating_4", environment_id: "dev", owner_type: "tool_project_scope", owner_id: "tps_dating_dev_test",
      version: 4, revision: 2, status: "draft", created_by: "admin", published_by: null,
      created_at: "2026-08-28T00:00:00Z", published_at: null,
      items: [{ definition_id: definition.id, value: { device_id: "dating-device", platform: "ios", app_version: "1.0.0" } }],
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{
        id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest",
        platform_project_id: "project_dating", platform_project_name: "Dating 平台项目",
        project_id: "dating", display_name: "Dating AI Assistant", target_env: "test", status: "active",
        is_default: true, revision: 4, active_release: null,
      }] });
      if (url.includes("/config/definitions")) return jsonResponse([definition]);
      if (url.includes("/config/releases/rel_dating_4/items") && init?.method === "PUT") {
        savedBody = JSON.parse(String(init.body));
        return jsonResponse({ ...draft, revision: 3, items: savedBody?.items ?? [] });
      }
      if (url.includes("/me/credentials?")) return jsonResponse([]);
      if (url.includes("/config/releases?")) return jsonResponse([draft]);
      return jsonResponse({});
    });
    render(<App />);

    await screen.findByLabelText("静态参数名");
    fireEvent.change(screen.getByLabelText("静态参数名"), { target: { value: "custom_channel" } });
    fireEvent.change(screen.getByLabelText("静态参数值"), { target: { value: "app-store" } });
    fireEvent.click(screen.getByRole("button", { name: "添加静态参数" }));
    expect(screen.getByLabelText("custom_channel")).toHaveValue("app-store");

    fireEvent.change(screen.getByLabelText("静态参数名"), { target: { value: "auth_token" } });
    fireEvent.change(screen.getByLabelText("静态参数值"), { target: { value: "must-not-save" } });
    fireEvent.click(screen.getByRole("button", { name: "添加静态参数" }));
    expect(screen.getByRole("alert")).toHaveTextContent("auth_token 由运行时生成，不能保存为静态配置");

    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() => expect(savedBody).not.toBeNull());
    const persistedBody = savedBody as { items?: Array<{ definition_id: string; value: unknown }> } | null;
    const commItem = persistedBody?.items?.find((item) => item.definition_id === definition.id);
    expect(commItem?.value).toMatchObject({ custom_channel: "app-store" });
    expect(commItem?.value).not.toHaveProperty("auth_token");
  });

  it("配置控制面保留全部既有工具，并按工具能力选择 Scope 或工具级归属", async () => {
    window.history.replaceState({}, "", "/settings/config?tool_id=functional-test-agent");
    const definitions = [
      { id: "api-autotest.gateway.base_url", key: "gateway.base_url", display_name: "Gateway 地址", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "text", sensitivity: "normal", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null },
      { id: "api-test-agent.timeout", key: "timeout", display_name: "API 智能体超时", description: "", owner_type: "tool", owner_id: "api-test-agent", group_key: "runtime", value_type: "int", sensitivity: "normal", required: true, default_value: 30, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null },
      { id: "functional-test-agent.timeout", key: "timeout", display_name: "功能智能体超时", description: "", owner_type: "tool", owner_id: "functional-test-agent", group_key: "runtime", value_type: "int", sensitivity: "normal", required: true, default_value: 60, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null },
      { id: "truthy-search.timeout", key: "timeout", display_name: "检索评测超时", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "runtime", value_type: "int", sensitivity: "normal", required: true, default_value: 45, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null },
    ];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: allTools });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_dating", platform_project_name: "Dating 平台项目", project_id: "dating", display_name: "Dating API", target_env: "test", status: "active", is_default: true, revision: 4, active_release: null }] });
      if (url.includes("/config/definitions")) return jsonResponse(definitions);
      if (url.includes("/config/releases?")) return jsonResponse([]);
      return jsonResponse({ status: "healthy" });
    });
    render(<App />);

    const toolSelector = await screen.findByLabelText("工具 / 智能体");
    expect(toolSelector).toHaveDisplayValue("功能测试智能体");
    expect(screen.getByRole("option", { name: "API 测试智能体" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "接口自动化" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "检索评测" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => {
      const value = String(url);
      return value.includes("/config/releases?")
        && value.includes("owner_type=tool")
        && value.includes("owner_id=functional-test-agent");
    })).toBe(true));
    expect(screen.getByLabelText("配置归属")).toHaveDisplayValue("工具级配置");

    fireEvent.change(toolSelector, { target: { value: "api-autotest" } });
    expect(await screen.findByLabelText("工具项目")).toHaveDisplayValue("Dating API");
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => {
      const value = String(url);
      return value.includes("/config/releases?")
        && value.includes("owner_type=tool_project_scope")
        && value.includes("owner_id=tps_dating_dev_test");
    })).toBe(true));
  });

  it("切换 Runtime Scope 后 Release 查询使用新 Scope，且不泄漏 Secret 值", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_truthy_dev_test");
    const scopes = {
      items: [
        { id: "tps_truthy_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_truthy", platform_project_name: "Truthy 平台项目", project_id: "truthy", display_name: "Truthy Gateway", target_env: "test", status: "active", is_default: true, revision: 2, active_release: null },
        { id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_dating", platform_project_name: "Dating 平台项目", project_id: "dating", display_name: "Dating API", target_env: "test", status: "active", is_default: false, revision: 4, active_release: null },
      ],
    };
    const definition = { id: "api-autotest.gateway.timeout", key: "request.timeout_seconds", display_name: "请求超时", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "int", sensitivity: "normal", required: true, default_value: 30, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/runtime-scopes?")) return jsonResponse(scopes);
      if (url.includes("/config/definitions")) return jsonResponse([definition]);
      if (url.includes("/config/releases?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    await screen.findByLabelText("工具项目");
    fireEvent.change(screen.getByLabelText("平台项目"), { target: { value: "project_dating" } });
    fireEvent.change(screen.getByLabelText("工具项目"), { target: { value: "tps_dating_dev_test" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("owner_id=tps_dating_dev_test"))).toBe(true));
    expect(window.location.search).toBe("?scope_id=tps_dating_dev_test");
    expect(screen.queryByText(/secret-value|token-value/i)).not.toBeInTheDocument();
  });

  it("编辑 Runtime Scope 只提交可变字段，并由 PATCH 保留固定环境映射", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_dating_dev_test");
    let patchBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/runtime-scopes/tps_dating_dev_test") && init?.method === "PATCH") { patchBody = JSON.parse(String(init.body)); return jsonResponse({ id: "tps_dating_dev_test" }); }
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_dating", platform_project_name: "Dating 平台项目", project_id: "dating", display_name: "Dating API", target_env: "test", status: "active", is_default: true, revision: 4, active_release: null }] });
      if (url.includes("/config/definitions") || url.includes("/config/releases?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);

    await screen.findByLabelText("工具项目");
    fireEvent.click(screen.getByRole("button", { name: "编辑 Scope" }));
    fireEvent.change(screen.getByLabelText("Scope 显示名称"), { target: { value: "Dating 自动化" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 Scope" }));
    await waitFor(() => expect(patchBody).toEqual({ display_name: "Dating 自动化", status: "active", is_default: true, revision: 4 }));
  });

  it("被禁用或无权读取的 Scope 不加载配置值，并展示明确的安全状态", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_disabled");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_disabled", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_disabled", platform_project_name: "已停用项目", project_id: "disabled-project", display_name: "停用项目", target_env: "test", status: "disabled", is_default: false, revision: 1, active_release: null }] });
      if (url.includes("/config/definitions")) return jsonResponse([]);
      if (url.includes("/config/releases?")) return jsonResponse({ code: "FORBIDDEN", message: "禁止访问" }, 403);
      return jsonResponse({});
    });
    render(<App />);

    expect(await screen.findByText(/该 Runtime Scope 已停用/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建草稿" })).toBeDisabled();
    expect(screen.queryByText(/secret-value|token-value/i)).not.toBeInTheDocument();
  });

  it("凭证代理恢复工具级 Credential，并且不会误绑定接口自动化 Scope", async () => {
    window.history.replaceState({}, "", "/settings/credential-agents?tool_id=truthy-search");
    let createBody: Record<string, unknown> | null = null;
    const definitions = [
      { id: "api-autotest.gateway.base_url", key: "gateway.base_url", display_name: "Gateway 地址", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "text", sensitivity: "normal", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null },
      { id: "truthy-search.timeout", key: "timeout", display_name: "检索超时", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "runtime", value_type: "int", sensitivity: "normal", required: true, default_value: 45, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null },
    ];
    const truthyCredential = { id: "cred_truthy", tool_id: "truthy-search", environment_id: "dev", runtime_scope_id: null, provider_type: "gateway_session", status: "healthy", current_version: 3, expires_at: null, refresh_expires_at: null, last_error_code: null, last_checked_at: null };
    const scopedCredential = { ...truthyCredential, id: "cred_api", tool_id: "api-autotest", runtime_scope_id: "tps_dating_dev_test" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: allTools });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_dating", platform_project_name: "Dating 平台项目", project_id: "dating", display_name: "Dating API", target_env: "test", status: "active", is_default: true, revision: 4, active_release: null }] });
      if (url.includes("/config/definitions")) return jsonResponse(definitions);
      if (url.endsWith("/credentials") && init?.method === "POST") { createBody = JSON.parse(String(init.body)); return jsonResponse({ ...truthyCredential, id: "cred_new", provider_type: "admin_login", status: "pending_validation" }, 201); }
      if (url.includes("/credentials?")) return jsonResponse([truthyCredential, scopedCredential]);
      return jsonResponse({ status: "healthy" });
    });
    render(<App />);

    expect(await screen.findByLabelText("工具 / 智能体")).toHaveDisplayValue("检索评测");
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/credentials?environment_id=dev") && !String(url).includes("runtime_scope_id"))).toBe(true));
    expect(screen.getByLabelText("配置归属")).toHaveDisplayValue("工具级配置");
    fireEvent.click(screen.getByRole("button", { name: "创建 Credential" }));
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "admin_login" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并等待验证" }));
    await waitFor(() => expect(createBody).toEqual({ provider_type: "admin_login", tool_id: "truthy-search", environment_id: "dev" }));
  });

  it("普通执行用户可从全局导航进入个人凭证与个人 LLM", async () => {
    const executorAuth = {
      ...auth,
      role: "tester" as const,
      roles: ["tester"],
      platform_permissions: [],
      tool_permissions: { "truthy-search": ["tool.view", "tool.execute"] },
    };
    mockAuthenticatedCatalog([allTools[5]], executorAuth);
    render(<App />);
    expect(await screen.findByRole("link", { name: "我的凭证" })).toHaveAttribute("href", "/account/credentials");
    expect(screen.getByRole("link", { name: "我的 LLM" })).toHaveAttribute("href", "/account/llm");
    expect(screen.queryByRole("link", { name: "平台管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Secret" })).not.toBeInTheDocument();
  });

  it("个人凭证页不回填 Secret，保存成功后清空输入", async () => {
    window.history.replaceState({}, "", "/account/credentials");
    let savedBody: Record<string, unknown> | null = null;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[5]] });
      if (url.includes("/config/definitions")) return jsonResponse([
        { id: "truthy-search.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10, value_scope: "user", credential_provider_type: "gateway_session" },
        { id: "truthy-search.DEVICE_ID", key: "DEVICE_ID", display_name: "设备 ID", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "credentials", value_type: "string", sensitivity: "normal", required: false, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 20, value_scope: "user", credential_provider_type: "gateway_session" },
      ]);
      if (url.includes("/me/credentials?")) return jsonResponse([{ id: "ucred_1", tool_id: "truthy-search", environment_id: "dev", provider_type: "gateway_session", status: "healthy", current_version: savedBody ? 4 : 3, expires_at: null, refresh_expires_at: null, last_checked_at: "2026-08-24T00:00:00Z", last_error_code: null, fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }, { key: "DEVICE_ID", display_name: "设备 ID", required: false, configured: true }] }]);
      if (url.includes("/me/credentials/truthy-search/gateway_session") && init?.method === "PUT") {
        savedBody = JSON.parse(String(init.body));
        return jsonResponse({ id: "ucred_1", tool_id: "truthy-search", environment_id: "dev", provider_type: "gateway_session", status: "pending_validation", current_version: 4, expires_at: null, refresh_expires_at: null, last_checked_at: null, last_error_code: null, fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }, { key: "DEVICE_ID", display_name: "设备 ID", required: false, configured: true }] });
      }
      return jsonResponse({ tool_id: "truthy-search", status: "healthy" });
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "我的凭证" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "配置 truthy-search Gateway Session" }));
    const secretInput = screen.getByLabelText("Access Token");
    expect(secretInput).toHaveAttribute("type", "password");
    expect(secretInput).toHaveAttribute("autocomplete", "new-password");
    expect(secretInput).toHaveValue("");
    fireEvent.change(secretInput, { target: { value: "frontend-secret-sentinel" } });
    fireEvent.click(screen.getByRole("button", { name: "保存凭证" }));
    await waitFor(() => expect(savedBody).toEqual({
      environment_id: "dev",
      expected_version: 3,
      values: { AUTH_TOKEN: "frontend-secret-sentinel" },
    }));
    expect(await screen.findByText("凭证已保存，新任务将使用新版本。")).toBeInTheDocument();
    expect(screen.queryByText("frontend-secret-sentinel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "配置 truthy-search Gateway Session" }));
    expect(screen.getByLabelText("Access Token")).toHaveValue("");
    // 认证层只允许保存“曾建立会话”的非敏感布尔标记；个人 Secret 仍不得落盘。
    expect(localStorage.getItem("tp_session_seen")).toBe("1");
    expect(JSON.stringify(localStorage)).not.toContain("new-token-value");
    expect(fetchMock).toHaveBeenCalled();
  });

  it("接口自动化个人凭证不再展示已项目化的 Device ID", async () => {
    window.history.replaceState({}, "", "/account/credentials");
    const apiAutotestAuth: AuthState = {
      ...auth,
      tool_permissions: {
        "api-autotest": ["tool.view", "tool.execute"],
      },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(apiAutotestAuth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[2]] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{
        id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest",
        platform_project_id: "project_dating", platform_project_name: "Dating 平台项目",
        project_id: "dating", display_name: "Dating AI Assistant", target_env: "test",
        status: "active", is_default: true, revision: 4, active_release: null,
      }] });
      if (url.includes("/config/definitions")) return jsonResponse([
        { id: "api-autotest.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10, value_scope: "user", credential_provider_type: "gateway_session" },
        { id: "api-autotest.DEVICE_ID", key: "DEVICE_ID", display_name: "设备 ID", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: false, default_value: null, validation_schema: { runtime_config_excluded: true, replacement_key: "gateway.comm.device_id" }, apply_mode: "next_task", editable: true, sort_order: 20, value_scope: "user", credential_provider_type: "gateway_session" },
      ]);
      if (url.includes("/me/credentials?")) return jsonResponse([{
        id: "ucred_api_autotest", tool_id: "api-autotest", environment_id: "dev",
        runtime_scope_id: "tps_dating_dev_test",
        provider_type: "gateway_session", status: "healthy", current_version: 19,
        expires_at: null, refresh_expires_at: null, last_checked_at: null,
        last_error_code: null, fields: [
          { key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true },
          { key: "DEVICE_ID", display_name: "设备 ID", required: false, configured: true },
        ],
      }]);
      return jsonResponse({ tool_id: "api-autotest", status: "healthy" });
    });

    render(<App />);

    fireEvent.click(await screen.findByRole("button", {
      name: "配置 api-autotest Gateway Session",
    }));
    expect(await screen.findByLabelText("Access Token")).toBeInTheDocument();
    expect(screen.queryByLabelText("设备 ID")).not.toBeInTheDocument();
  });

  it("接口自动化没有可用 Scope 时不回退展示工具级旧凭证", async () => {
    window.history.replaceState({}, "", "/account/credentials");
    const apiAutotestAuth: AuthState = {
      ...auth,
      tool_permissions: { "api-autotest": ["tool.view", "tool.execute"] },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(apiAutotestAuth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[2]] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [] });
      if (url.includes("/config/definitions")) return jsonResponse([{
        id: "api-autotest.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token",
        description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "credentials",
        value_type: "secret", sensitivity: "secret", required: true, default_value: null,
        validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10,
        value_scope: "user", credential_provider_type: "gateway_session",
      }]);
      if (url.includes("/me/credentials?")) return jsonResponse([{
        id: "ucred_legacy_api_autotest", tool_id: "api-autotest", environment_id: "dev",
        runtime_scope_id: null, provider_type: "gateway_session", status: "healthy",
        current_version: 9, expires_at: null, refresh_expires_at: null,
        last_checked_at: null, last_error_code: null, fields: [],
      }]);
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByText("当前工具没有可用的 Runtime Scope，不能读取或配置工具级兜底凭证。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "配置 api-autotest Gateway Session" })).not.toBeInTheDocument();
    expect(screen.queryByText("v9")).not.toBeInTheDocument();
  });

  it("接口自动化个人凭证按 Runtime Scope 隔离并从深链定位 Provider", async () => {
    window.history.replaceState(
      {},
      "",
      "/account/credentials?scope_id=tps_dating_dev_test&provider_type=gateway_session",
    );
    let savedBody: Record<string, unknown> | null = null;
    const apiAutotestAuth: AuthState = {
      ...auth,
      tool_permissions: { "api-autotest": ["tool.view", "tool.execute"] },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(apiAutotestAuth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[2]] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [
        { id: "tps_truthy_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_truthy", platform_project_name: "Truthy", project_id: "truthy", display_name: "Truthy Gateway", target_env: "test", status: "active", is_default: true, revision: 1, active_release: null },
        { id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_dating", platform_project_name: "Dating", project_id: "dating", display_name: "Dating AI Assistant", target_env: "test", status: "active", is_default: false, revision: 1, active_release: null },
      ] });
      if (url.includes("/config/definitions")) return jsonResponse([
        { id: "api-autotest.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10, value_scope: "user", credential_provider_type: "gateway_session" },
      ]);
      if (url.includes("/me/credentials?")) return jsonResponse([
        { id: "ucred_truthy", tool_id: "api-autotest", environment_id: "dev", runtime_scope_id: "tps_truthy_dev_test", provider_type: "gateway_session", status: "healthy", current_version: 3, expires_at: "2026-09-01T00:00:00Z", refresh_expires_at: null, last_checked_at: null, last_error_code: null, fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }] },
        { id: "ucred_dating", tool_id: "api-autotest", environment_id: "dev", runtime_scope_id: "tps_dating_dev_test", provider_type: "gateway_session", status: "action_required", current_version: 23, expires_at: "2026-08-29T08:36:30Z", refresh_expires_at: "2026-09-27T08:36:30Z", last_checked_at: "2026-08-29T09:07:30Z", last_error_code: "CREDENTIAL_REFRESH_HTTPSTATUSERROR", fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }] },
      ]);
      if (url.includes("/me/credentials/api-autotest/gateway_session") && init?.method === "PUT") {
        savedBody = JSON.parse(String(init.body));
        return jsonResponse({ id: "ucred_dating", tool_id: "api-autotest", environment_id: "dev", runtime_scope_id: "tps_dating_dev_test", provider_type: "gateway_session", status: "pending_validation", current_version: 24, expires_at: null, refresh_expires_at: null, last_checked_at: null, last_error_code: null, fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }] });
      }
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByLabelText("工具项目")).toHaveDisplayValue("Dating AI Assistant");
    expect(screen.getByText("v23")).toBeInTheDocument();
    expect(screen.getByText("CREDENTIAL_REFRESH_HTTPSTATUSERROR", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("v3")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "配置 api-autotest Gateway Session" }));
    fireEvent.change(screen.getByLabelText("Access Token"), { target: { value: "new-dating-token" } });
    fireEvent.click(screen.getByRole("button", { name: "保存凭证" }));
    await waitFor(() => expect(savedBody).toEqual({
      environment_id: "dev",
      runtime_scope_id: "tps_dating_dev_test",
      expected_version: 23,
      values: { AUTH_TOKEN: "new-dating-token" },
    }));
  });

  it("普通配置页展示当前 Scope 的个人凭证状态但不回显凭证值", async () => {
    window.history.replaceState({}, "", "/settings/config?scope_id=tps_dating_dev_test");
    const definition = {
      id: "api-autotest.gateway.base_url", key: "gateway.base_url", display_name: "Gateway Base URL",
      description: "", owner_type: "tool", owner_id: "api-autotest", group_key: "gateway", value_type: "string",
      sensitivity: "normal", required: true, default_value: null, validation_schema: {},
      apply_mode: "next_task", editable: true, sort_order: 1, value_scope: "system", credential_provider_type: null,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[2]] });
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_dating_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_dating", platform_project_name: "Dating", project_id: "dating", display_name: "Dating AI Assistant", target_env: "test", status: "active", is_default: true, revision: 1, active_release: { id: "rel_v7", version: 7, status: "active" } }] });
      if (url.includes("/config/definitions")) return jsonResponse([definition]);
      if (url.includes("/config/releases?")) return jsonResponse([{ id: "rel_v7", environment_id: "dev", owner_type: "tool_project_scope", owner_id: "tps_dating_dev_test", version: 7, revision: 1, status: "active", created_by: "admin", published_by: "admin", created_at: "2026-08-29T00:00:00Z", published_at: "2026-08-29T00:00:00Z", items: [{ definition_id: definition.id, value: "https://gateway.spark-jam.top" }] }]);
      if (url.includes("/me/credentials?")) return jsonResponse([{ id: "ucred_dating", tool_id: "api-autotest", environment_id: "dev", runtime_scope_id: "tps_dating_dev_test", provider_type: "gateway_session", status: "action_required", current_version: 23, expires_at: "2026-08-29T08:36:30Z", refresh_expires_at: "2026-09-27T08:36:30Z", last_checked_at: "2026-08-29T09:07:30Z", last_error_code: "CREDENTIAL_REFRESH_HTTPSTATUSERROR", fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }] }]);
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "个人凭证（不属于普通 Release）" })).toBeInTheDocument();
    // 配置主体会先完成渲染，个人凭证状态随后异步加载；等待状态行出现再断言，
    // 避免把正常的分阶段加载误判为“凭证未展示”。
    expect(await screen.findByText("Gateway Session")).toBeInTheDocument();
    expect(screen.getByText("CREDENTIAL_REFRESH_HTTPSTATUSERROR", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "管理 Gateway Session" })).toHaveAttribute(
      "href",
      "/account/credentials?scope_id=tps_dating_dev_test&provider_type=gateway_session",
    );
    expect(screen.queryByText("secret-sentinel")).not.toBeInTheDocument();
  });

  it("个人凭证版本冲突保留未提交输入并展示稳定错误码", async () => {
    window.history.replaceState({}, "", "/account/credentials");
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[5]] });
      if (url.includes("/config/definitions")) return jsonResponse([{ id: "truthy-search.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10, value_scope: "user", credential_provider_type: "gateway_session" }]);
      if (url.includes("/me/credentials?")) return jsonResponse([{ id: "ucred_1", tool_id: "truthy-search", environment_id: "dev", provider_type: "gateway_session", status: "healthy", current_version: 3, expires_at: null, refresh_expires_at: null, last_checked_at: null, last_error_code: null, fields: [{ key: "AUTH_TOKEN", display_name: "Access Token", required: true, configured: true }] }]);
      if (url.includes("/me/credentials/truthy-search/gateway_session") && init?.method === "PUT") return jsonResponse({ code: "VERSION_CONFLICT", message: "配置已更新，请刷新后重试" }, 409);
      return jsonResponse({ tool_id: "truthy-search", status: "healthy" });
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "配置 truthy-search Gateway Session" }));
    fireEvent.change(screen.getByLabelText("Access Token"), { target: { value: "keep-on-conflict" } });
    fireEvent.click(screen.getByRole("button", { name: "保存凭证" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("VERSION_CONFLICT");
    expect(screen.getByLabelText("Access Token")).toHaveValue("keep-on-conflict");
  });

  it("个人 LLM 只展示本人 Profile，API Key 保存后不回填", async () => {
    window.history.replaceState({}, "", "/account/llm");
    let updateBody: Record<string, unknown> | null = null;
    const profilePayload = () => ({ id: "llmp_personal", name: "Personal DeepSeek", description: "仅供本人任务", provider: "openai_compatible", is_archived: false, environment_id: "dev", active_release_id: "rel_profile", active_release_version: updateBody ? 3 : 2, base_url: "https://llm.example.com/v1", model: "deepseek-v3", temperature: 0.2, max_tokens: 2048, timeout_seconds: 30, enabled: true, api_key_configured: true, binding_count: 1, created_at: "2026-08-24T00:00:00Z", updated_at: "2026-08-24T00:00:00Z" });
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [allTools[0]] });
      if (url.includes("/me/llm/profiles?")) return jsonResponse([profilePayload()]);
      if (url.includes("/me/llm/bindings?")) return jsonResponse([{ id: "ullmb_1", binding_id: "llmb_functional_default", tool_id: "functional-test-agent", capability_key: "default", display_name: "功能测试智能体默认模型", description: "", environment_id: "dev", active_release_id: "rel_binding", current_version: 1, profile_id: "llmp_personal", enabled: true, model_override: null, temperature_override: null, max_tokens_override: null, timeout_seconds_override: null, api_key_override_configured: false }]);
      if (url.endsWith("/me/llm/profiles/llmp_personal") && init?.method === "PATCH") {
        updateBody = JSON.parse(String(init.body));
        return jsonResponse(profilePayload());
      }
      return jsonResponse({ tool_id: "functional-test-agent", status: "healthy" });
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "我的 LLM" })).toBeInTheDocument();
    expect((await screen.findAllByText("Personal DeepSeek")).length).toBeGreaterThan(0);
    expect(await screen.findByText("功能测试智能体默认模型")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
    const apiKey = screen.getByLabelText("API Key（留空沿用现有值）");
    expect(apiKey).toHaveAttribute("type", "password");
    expect(apiKey).toHaveAttribute("autocomplete", "new-password");
    expect(apiKey).toHaveValue("");
    fireEvent.change(apiKey, { target: { value: "personal-llm-secret-sentinel" } });
    fireEvent.click(screen.getByRole("button", { name: "保存连接" }));
    await waitFor(() => expect(updateBody).toMatchObject({
      environment_id: "dev",
      api_key: "personal-llm-secret-sentinel",
    }));
    expect(await screen.findByText("个人 LLM 连接已更新，新任务将使用新版本。")).toBeInTheDocument();
    expect(screen.queryByText("personal-llm-secret-sentinel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "编辑连接" }));
    expect(screen.getByLabelText("API Key（留空沿用现有值）")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: /功能测试智能体默认模型/ }));
    fireEvent.click(screen.getByRole("button", { name: "配置能力绑定" }));
    expect(screen.getByRole("option", { name: "Personal DeepSeek" })).toBeInTheDocument();
  });

  it("管理员就绪度页只读展示凭证与 LLM 状态", async () => {
    window.history.replaceState({}, "", "/settings/credentials");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/admin/credential-readiness?")) return jsonResponse([
        { resource_type: "credential", user_id: "usr_1", username: "admin", user_status: "active", environment_id: "dev", tool_id: "truthy-search", provider_type: "gateway_session", capability_key: null, readiness_status: "expiring", credential_status: "healthy", current_version: 4, configured_field_count: 3, required_field_count: 3, expires_at: "2026-08-25T00:00:00Z", refresh_expires_at: null, last_checked_at: "2026-08-24T00:00:00Z", last_error_code: null },
        { resource_type: "llm_binding", user_id: "usr_1", username: "admin", user_status: "active", environment_id: "dev", tool_id: "functional-test-agent", provider_type: "llm", capability_key: "default", readiness_status: "configured", credential_status: null, current_version: 2, configured_field_count: 1, required_field_count: 1, expires_at: null, refresh_expires_at: null, last_checked_at: null, last_error_code: null },
      ]);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "凭证就绪度" })).toBeInTheDocument();
    expect(await screen.findAllByText("admin")).toHaveLength(2);
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByLabelText("筛选状态")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /替换|编辑|代改/ })).not.toBeInTheDocument();
  });

  it("旧 LLM 设置地址重定向到个人 LLM", async () => {
    window.history.replaceState({}, "", "/settings/llm");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/me/llm/profiles?") || url.includes("/me/llm/bindings?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "我的 LLM" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/account/llm");
  });

  it("注册模式明确为 open 时显示注册链接", async () => {
    window.history.replaceState({}, "", "/login");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401);
    });

    render(<App />);

    expect(await screen.findByRole("link", { name: "创建测试人员账号" })).toBeInTheDocument();
  });

  it("注册页以唯一注册标题命名表单区域", async () => {
    window.history.replaceState({}, "", "/register");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401);
    });

    render(<App />);

    const panel = await screen.findByRole("region", { name: "创建测试人员账号" });
    expect(within(panel).getByRole("heading", { name: "创建测试人员账号" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "欢迎回来" })).not.toBeInTheDocument();
  });

  it.each(["disabled", "invite"])("注册模式 %s 时隐藏入口并阻止直达提交", async (mode) => {
    window.history.replaceState({}, "", "/register");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401);
    });

    render(<App />);

    expect(await screen.findByRole("region", { name: "暂未开放注册" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "欢迎回来" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建账号" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/register"))).toBe(false);
  });

  it.each([
    ["未知模式", { mode: "future-mode" }],
    ["错误响应", { mode: 1 }],
  ])("注册状态返回%s时默认关闭", async (_label, payload) => {
    window.history.replaceState({}, "", "/login");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse(payload);
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401);
    });

    render(<App />);

    await screen.findByRole("heading", { name: "欢迎回来" });
    await waitFor(() => expect(screen.queryByRole("link", { name: "创建测试人员账号" })).not.toBeInTheDocument());
  });

  it("注册状态查询失败时默认关闭但不阻塞已登录工作台", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ code: "UNAVAILABLE" }, 503);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ runtime_environment: "dev" });
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
  });

  it("初次匿名 auth me 401 不显示会话过期提示", async () => {
    window.history.replaceState({}, "", "/login");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401);
    });

    render(<App />);

    await screen.findByRole("heading", { name: "欢迎回来" });
    expect(screen.queryByText("登录状态已过期，请重新登录。")).not.toBeInTheDocument();
  });

  it("已有会话后受保护 tools 的 AUTH_REQUIRED 只显示一次过期提示", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/tools")) return jsonResponse({ code: "AUTH_REQUIRED", message: "需要登录" }, 401);
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({});
    });

    render(<App />);

    expect(await screen.findByText("登录状态已过期，请重新登录。")).toBeInTheDocument();
    expect(screen.getAllByText("登录状态已过期，请重新登录。")).toHaveLength(1);
    expect(localStorage.getItem("tp_session_seen")).toBeNull();
    expect(sessionStorage.getItem("tp_auth_expired_notice")).toBeNull();
  });

  it("登录成功后迟到的旧代 401 不得清空新认证态", async () => {
    window.history.replaceState({}, "", "/login");
    const oldTools = deferredResponse();
    let toolsCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/login") && init?.method === "POST") return jsonResponse(auth);
      if (url.endsWith("/tools")) {
        toolsCalls += 1;
        return toolsCalls === 1 ? oldTools.promise : jsonResponse({ items: [] });
      }
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });

    const oldGeneration = currentAuthGeneration();
    const lateRequest = request("/api/v1/tools").catch((error) => error);
    fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: "legacy-password-over-18" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
    expect(currentAuthGeneration()).toBeGreaterThan(oldGeneration);

    oldTools.resolve(new Response(JSON.stringify({ code: "AUTH_REQUIRED", message: "需要登录" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    }));
    await lateRequest;
    expect(screen.getByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
    expect(screen.queryByText("登录状态已过期，请重新登录。")).not.toBeInTheDocument();
  });

  it("登录成功后迟到的旧 auth me 401 不得覆盖新认证态", async () => {
    window.history.replaceState({}, "", "/login");
    const oldMe = deferredResponse();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return oldMe.promise;
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/login") && init?.method === "POST") return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });
    fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: "legacy-password-over-18" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    await waitFor(() => expect(localStorage.getItem("tp_session_seen")).toBe("1"));

    oldMe.resolve(new Response(JSON.stringify({ code: "AUTH_REQUIRED", message: "需要登录" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    }));
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
    });
    expect(screen.queryByText("登录状态已过期，请重新登录。")).not.toBeInTheDocument();
  });

  it.each([
    ["INVALID_CREDENTIALS", "用户名或密码错误"],
    ["ACCOUNT_LOCKED", "登录尝试过多，请稍后再试"],
  ])("登录错误码 %s 使用固定安全文案", async (code, message) => {
    window.history.replaceState({}, "", "/login");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/login")) return jsonResponse({ code, message: "不可信后端详情" }, 401);
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });
    fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).not.toHaveTextContent("不可信后端详情");
  });

  it("AuthProvider 卸载后移除 AUTH_REQUIRED 事件监听", async () => {
    mockAuthenticatedCatalog([]);
    const view = render(<App />);
    await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" });
    expect(localStorage.getItem("tp_session_seen")).toBe("1");
    const generation = currentAuthGeneration();

    view.unmount();
    window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT, { detail: { generation } }));

    expect(localStorage.getItem("tp_session_seen")).toBe("1");
    expect(sessionStorage.getItem("tp_auth_expired_notice")).toBeNull();
  });

  it.each([
    ["六位", "密码密码密码"],
    ["十八位", "密码密码密码密码密码密码密码密码密码"],
  ])("注册支持%s Unicode code point 密码", async (_label, password) => {
    window.history.replaceState({}, "", "/register");
    let registerBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/register")) {
        registerBody = JSON.parse(String(init?.body));
        return jsonResponse(auth, 201);
      }
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "unicode-user" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Unicode 用户" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: password } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: password } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    await waitFor(() => expect(registerBody).toEqual({
      username: "unicode-user",
      display_name: "Unicode 用户",
      password,
    }));
  });

  it.each(["12345", "1234567890123456789"])("注册拒绝 5/19 位密码 %s 且不请求 API", async (password) => {
    window.history.replaceState({}, "", "/register");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "invalid-user" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "无效用户" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: password } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: password } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    expect(await screen.findByText("密码长度必须为 6 到 18 个字符")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/register"))).toBe(false);
  });

  it("注册确认密码不一致时不发送请求并正确关联错误", async () => {
    window.history.replaceState({}, "", "/register");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "mismatch-user" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "不一致用户" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    const confirmation = screen.getByLabelText("确认密码");
    expect(await screen.findByText("两次输入的密码不一致")).toHaveAttribute("id", "register-confirm-password-error");
    expect(confirmation).toHaveAttribute("aria-describedby", "register-confirm-password-error");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/register"))).toBe(false);
  });

  it("注册拒绝仅含空格的显示名称并清空两个密码", async () => {
    window.history.replaceState({}, "", "/register");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "blank-name" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "   " } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    expect(await screen.findByText("显示名称不能为空")).toHaveAttribute("id", "register-display-name-error");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(screen.getByLabelText("确认密码")).toHaveValue("");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/register"))).toBe(false);
  });

  it("注册失败清空两个密码并保留用户名和显示名称", async () => {
    window.history.replaceState({}, "", "/register");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/register")) return jsonResponse({ code: "REGISTRATION_RATE_LIMITED", message: "内部阈值" }, 429);
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "preserved-user" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "保留身份" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("操作过于频繁，请稍后重试");
    expect(screen.getByLabelText("用户名")).toHaveValue("preserved-user");
    expect(screen.getByLabelText("显示名称")).toHaveValue("保留身份");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(screen.getByLabelText("确认密码")).toHaveValue("");
  });

  it("登录表单不拒绝存量 19 位以上密码", async () => {
    window.history.replaceState({}, "", "/login");
    let loginBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/login")) { loginBody = JSON.parse(String(init?.body)); return jsonResponse(auth); }
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/version.json")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });
    const legacyPassword = "legacy-password-over-eighteen";
    fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: legacyPassword } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(loginBody).toEqual({ username: "admin", password: legacyPassword }));
  });

  it("setup 使用共享 6 到 18 位密码规则", async () => {
    window.history.replaceState({}, "", "/setup");
    let setupBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "disabled" });
      if (url.endsWith("/setup")) { setupBody = JSON.parse(String(init?.body)); return jsonResponse(auth); }
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "初始化平台管理员" });
    fireEvent.change(screen.getByLabelText("Bootstrap Token"), { target: { value: "bootstrap-token" } });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "管理员" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "创建管理员" }));

    await waitFor(() => expect(setupBody).not.toBeNull());
  });

  it("用户改密使用共享 6 到 18 位密码规则", async () => {
    window.history.replaceState({}, "", "/account/password");
    let changeBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/auth/change-password")) { changeBody = JSON.parse(String(init?.body)); return jsonResponse({}); }
      return jsonResponse({});
    });
    render(<App />);
    await screen.findByRole("heading", { name: "修改密码" });
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "legacy-current-password" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并撤销其他会话" }));

    await waitFor(() => expect(changeBody).not.toBeNull());
  });

  it.each(["12345", "1234567890123456789"])("setup 拒绝越界新密码 %s 且不请求 API", async (password) => {
    window.history.replaceState({}, "", "/setup");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "disabled" });
      return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
    });
    render(<App />);
    await screen.findByRole("heading", { name: "初始化平台管理员" });
    fireEvent.change(screen.getByLabelText("Bootstrap Token"), { target: { value: "bootstrap-token" } });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("显示名"), { target: { value: "管理员" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: password } });
    fireEvent.click(screen.getByRole("button", { name: "创建管理员" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("密码长度必须为 6 到 18 个字符");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/setup"))).toBe(false);
  });

  it.each(["12345", "1234567890123456789"])("用户改密拒绝越界新密码 %s 且不请求 API", async (password) => {
    window.history.replaceState({}, "", "/account/password");
    const fetchMock = mockAuthenticatedCatalog([]);
    render(<App />);
    await screen.findByRole("heading", { name: "修改密码" });
    fireEvent.change(screen.getByLabelText("当前密码"), { target: { value: "legacy-current-password" } });
    fireEvent.change(screen.getByLabelText("新密码"), { target: { value: password } });
    fireEvent.click(screen.getByRole("button", { name: "保存并撤销其他会话" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("密码长度必须为 6 到 18 个字符");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/auth/change-password"))).toBe(false);
  });

  it.each(["123456", "123456789012345678"])("固定角色管理员建号接受边界密码 %s", async (password) => {
    window.history.replaceState({}, "", "/admin/users");
    let createdBody: Record<string, unknown> | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/admin/users") && init?.method === "POST") {
        createdBody = JSON.parse(String(init.body));
        return jsonResponse({ id: "created-user" }, 201);
      }
      if (url.endsWith("/admin/users")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "创建用户" }));
    const dialog = screen.getByRole("dialog", { name: "创建用户" });
    fireEvent.change(within(dialog).getByLabelText("用户名"), { target: { value: "boundary-user" } });
    fireEvent.change(within(dialog).getByLabelText("显示名称"), { target: { value: "边界用户" } });
    fireEvent.change(within(dialog).getByLabelText("初始密码"), { target: { value: password } });
    fireEvent.click(within(dialog).getByRole("button", { name: "确认创建" }));

    await waitFor(() => expect(createdBody).not.toBeNull());
  });

  it("注册提交中禁止重复请求", async () => {
    window.history.replaceState({}, "", "/register");
    const pendingRegister = deferredResponse();
    let registerCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/register")) { registerCalls += 1; return pendingRegister.promise; }
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "single-submit" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "单次提交" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "123456" } });
    const submit = screen.getByRole("button", { name: "创建账号" });
    fireEvent.click(submit);
    fireEvent.click(await screen.findByRole("button", { name: "正在创建…" }));

    expect(registerCalls).toBe(1);
    pendingRegister.resolve(new Response(JSON.stringify(auth), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }));
    expect(await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
  });

  it("注册成功自动进入工作台并只加载服务端可见工具", async () => {
    window.history.replaceState({}, "", "/register");
    const publicTool = allTools[3];
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/register")) return jsonResponse({ ...auth, role: "tester", roles: ["tester"], platform_permissions: [], tool_permissions: { [publicTool.id]: ["tool.view"] } }, 201);
      if (url.endsWith("/tools")) return jsonResponse({ items: [publicTool] });
      return jsonResponse({ tool_id: publicTool.id, status: "healthy" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "创建测试人员账号" });
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "public-user" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "公共用户" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    expect(await screen.findByRole("heading", { name: publicTool.name })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: allTools[0].name })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/tools"))).toBe(true);
  });

  it("主动退出清除曾登录标记且不显示过期提示", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/logout")) return Promise.resolve(new Response(null, { status: 204 }));
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" });
    fireEvent.click(screen.getByRole("button", { name: "退出" }));

    expect(await screen.findByRole("heading", { name: "欢迎回来" })).toBeInTheDocument();
    expect(screen.queryByText("登录状态已过期，请重新登录。")).not.toBeInTheDocument();
    expect(localStorage.getItem("tp_session_seen")).toBeNull();
    expect(sessionStorage.getItem("tp_auth_expired_notice")).toBeNull();
  });

  it("登录拒绝外部 next 并回到站内首页", async () => {
    window.history.replaceState({}, "", "/login?next=%2F%2Fevil.example");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse({ code: "AUTH_REQUIRED" }, 401);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/login")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({ runtime_environment: "dev" });
    });
    render(<App />);
    await screen.findByRole("heading", { name: "欢迎回来" });
    fireEvent.change(screen.getByPlaceholderText("请输入用户名"), { target: { value: "admin" } });
    fireEvent.change(screen.getByPlaceholderText("请输入密码"), { target: { value: "legacy-password-over-18" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" });
    expect(window.location.pathname).toBe("/");
  });

  it("AC-01：注册页固定创建测试人员且不暴露角色字段", async () => {
    window.history.replaceState({}, "", "/register");
    const registeredAuth = {
      ...auth,
      user: { ...auth.user, id: "usr_new", username: "new-tester", display_name: "新测试人员" },
      role: "tester",
      roles: ["tester"],
      projects: [],
      extra_tool_grants: [],
      permission_version: 1,
      platform_permissions: [],
      tool_permissions: {},
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401);
      if (url.endsWith("/auth/registration-status")) return jsonResponse({ mode: "open" });
      if (url.endsWith("/auth/register")) return jsonResponse(registeredAuth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/health/live")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse({ tool_id: "", status: "healthy" });
    });

    render(<App />);
    expect(await screen.findByRole("heading", { name: "创建测试人员账号" })).toBeInTheDocument();
    expect(screen.queryByLabelText("角色")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "new-tester" } });
    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "新测试人员" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct-pass-123" } });
    fireEvent.change(screen.getByLabelText("确认密码"), { target: { value: "correct-pass-123" } });
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
    expect(await screen.findByRole("heading", { name: "AI 测试与质量工程工作台" })).toBeInTheDocument();
  });

  it("AC-09：管理员有我的项目导航但没有全局用户和工具权限入口", async () => {
    window.history.replaceState({}, "", "/access");
    const projectAdmin: AuthState = {
      ...auth,
      role: "admin",
      roles: ["admin"],
      projects: [{ id: "project_a", code: "alpha", name: "Alpha 项目", status: "active", relation: "manager" }],
      extra_tool_grants: [],
      permission_version: 2,
      platform_permissions: [],
    };
    mockAuthenticatedCatalog([], projectAdmin);
    render(<App />);
    expect((await screen.findAllByRole("link", { name: "我的项目" })).some((link) => link.getAttribute("href") === "/projects?scope=mine")).toBe(true);
    expect(screen.queryByRole("link", { name: "项目管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "用户管理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "工具管理" })).not.toBeInTheDocument();
  });

  it("兼容期部分平台权限不会展示角色守卫下的平台 LLM 与凭证代理入口", async () => {
    window.history.replaceState({}, "", "/access");
    const partialAdmin: AuthState = {
      ...auth,
      role: "admin",
      roles: ["admin"],
      platform_permissions: ["platform.llm.manage", "platform.llm.secret.manage", "platform.secret.manage"],
    };
    mockAuthenticatedCatalog([], partialAdmin);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "权限与项目" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Secret" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "平台 LLM 配置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "凭证代理" })).not.toBeInTheDocument();
  });

  it("403 页面不再出现已删除的工具工作台名称", async () => {
    window.history.replaceState({}, "", "/403");
    mockAuthenticatedCatalog([]);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "状态与异常" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "没有管理权限" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回工作台" })).toHaveAttribute("href", "/");
    expect(screen.queryByText("工具工作台")).not.toBeInTheDocument();
  });

  it("AC-48：项目停用确认携带影响令牌，过期时关闭确认并要求重新预览", async () => {
    window.history.replaceState({}, "", "/projects/project_a");
    const platformAdmin: AuthState = {
      ...auth,
      role: "platform_admin",
      roles: ["platform_admin"],
      projects: [{ id: "project_a", code: "alpha", name: "Alpha 项目", status: "active", relation: null }],
      extra_tool_grants: [],
      permission_version: 2,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(platformAdmin);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.endsWith("/projects/project_a")) return jsonResponse({ id: "project_a", code: "alpha", name: "Alpha 项目", description: "", status: "active", revision: 4, manager_count: 1, member_count: 2, tool_count: 3, active_grant_count: 1, updated_at: "2026-08-24T00:00:00Z" });
      if (url.endsWith("/projects/project_a/deactivation-impact")) return jsonResponse({ expected_revision: 4, impact_token: "a".repeat(32), manager_count: 1, member_count: 2, tool_count: 3, active_grant_count: 1, running_task_count: 0 });
      if (url.endsWith("/projects/project_a/deactivate") && init?.method === "POST") return jsonResponse({ code: "STALE_IMPACT", message: "资源状态已变化，请重新确认影响范围" }, 409);
      if (url.endsWith("/health/live")) return jsonResponse({ runtime_environment: "dev" });
      return jsonResponse([]);
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "项目详情 · 概览" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "预览停用影响" }));
    expect(await screen.findByRole("dialog", { name: "停用 Alpha 项目" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认停用" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("重新确认影响范围");
    expect(screen.queryByRole("dialog", { name: "停用 Alpha 项目" })).not.toBeInTheDocument();
  });
});
