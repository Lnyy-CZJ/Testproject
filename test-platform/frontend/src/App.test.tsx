import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
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
    if (url.endsWith("/tools")) return jsonResponse({ items });
    if (url.endsWith("/health/live")) return jsonResponse({ status: "ok", version: "1.1.0", component_version: "1.1.0", revision: "abc", dirty: false, runtime_environment: "dev" });
    if (url.includes("/credentials?")) return jsonResponse([]);
    return jsonResponse({ tool_id: items[0]?.id, status: "healthy", checked_at: "2026-08-17T00:00:00Z" });
  });
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
    expect(screen.getByText(/1\.2\.0/)).toBeInTheDocument();
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
    window.history.replaceState({}, "", "/settings/secrets");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.includes("/runtime-scopes?")) return jsonResponse({ items: [{ id: "tps_search_dev_test", environment_id: "dev", tool_id: "api-autotest", platform_project_id: "project_search", platform_project_name: "检索项目", project_id: "search", display_name: "Search", target_env: "test", status: "active", is_default: true, revision: 1, active_release: null }] });
      if (url.includes("/config/definitions")) return jsonResponse([{ id: "truthy-search.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, validation_schema: {}, apply_mode: "next_task", editable: true, sort_order: 10, value_scope: "system", credential_provider_type: null }]);
      if (url.includes("/secrets?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByText("Access Token")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
    expect(screen.queryByText(/fake|token-value/i)).not.toBeInTheDocument();
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
    expect(localStorage.length).toBe(0);
    expect(fetchMock).toHaveBeenCalled();
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
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct-horse-battery" } });
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
