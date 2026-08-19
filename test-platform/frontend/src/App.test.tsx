import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const auth = {
  user: { id: "usr_1", username: "admin", display_name: "平台管理员", status: "active", must_change_password: false },
  roles: ["role_platform_admin"],
  platform_permissions: ["platform.user.manage", "platform.role.manage", "platform.audit.view", "platform.config.manage", "platform.secret.manage", "platform.llm.manage", "platform.llm.secret.manage"],
  tool_permissions: { trackevents: ["tool.view", "tool.execute", "tool.result.view"] },
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
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockAuthenticatedCatalog(items = allTools, currentAuth = auth) {
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
    expect(screen.getByText("1.1.0")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "平台状态" })).toHaveTextContent("运行环境DEV");
    expect(screen.getByRole("link", { name: "查看版本详情" })).toHaveAttribute("href", "/system/versions");
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
    mockAuthenticatedCatalog([]);
    render(<App />);
    expect(await screen.findByRole("link", { name: "平台管理" })).toHaveAttribute("href", "/admin/users");
    cleanup();
    const readonly = { ...auth, platform_permissions: [] };
    mockAuthenticatedCatalog([], readonly);
    render(<App />);
    await screen.findByText("平台管理员");
    expect(screen.queryByRole("link", { name: "平台管理" })).not.toBeInTheDocument();
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
    expect(screen.getByRole("link", { name: /打开工具/ })).toHaveAttribute("href", "/custom-tool/");
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
      if (url.includes("/config/definitions")) return jsonResponse([{ id: "truthy-search.AUTH_TOKEN", key: "AUTH_TOKEN", display_name: "Access Token", description: "", owner_type: "tool", owner_id: "truthy-search", group_key: "credentials", value_type: "secret", sensitivity: "secret", required: true, default_value: null, apply_mode: "next_task", editable: true }]);
      if (url.includes("/secrets?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByText("Access Token")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
    expect(screen.queryByText(/fake|token-value/i)).not.toBeInTheDocument();
  });

  it("LLM 配置页分开展示公共 Profile 与预登记工具绑定且不回显 Key", async () => {
    window.history.replaceState({}, "", "/settings/llm");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      if (url.includes("/llm/profiles?")) return jsonResponse([{ id: "llmp_shared_default", name: "DeepSeek Shared", description: "共享模型", protocol: "openai_compatible", is_archived: false, environment_id: "dev", active_release_id: "rel_profile", active_release_version: 1, api_key_configured: true, binding_count: 2 }]);
      if (url.includes("/llm/bindings?")) return jsonResponse([{ id: "llmb_functional_default", tool_id: "functional-test-agent", capability_key: "default", display_name: "功能测试智能体默认模型", description: "", environment_id: "dev", active_release_id: "rel_binding", active_release_version: 1, profile_id: "llmp_shared_default", enabled: true, api_key_override_configured: false }]);
      if (url.includes("/config/definitions?")) return jsonResponse([{ id: "llmp_shared_default.MODEL", key: "MODEL", display_name: "模型名称", description: "", owner_type: "llm_profile", owner_id: "llmp_shared_default", group_key: "model", value_type: "string", sensitivity: "normal", required: true, default_value: null, apply_mode: "next_task", editable: true }]);
      if (url.includes("/config/releases?")) return jsonResponse([{ id: "rel_profile", environment_id: "dev", owner_type: "llm_profile", owner_id: "llmp_shared_default", version: 1, revision: 1, status: "active", created_by: "admin", published_by: "admin", created_at: "2026-08-17T00:00:00Z", published_at: "2026-08-17T00:00:00Z", items: [{ definition_id: "llmp_shared_default.MODEL", value: "deepseek-v4-flash" }] }]);
      if (url.includes("/secrets?")) return jsonResponse([]);
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "LLM 统一配置" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "用户管理" })).toHaveAttribute("href", "/admin/users");
    expect((await screen.findAllByText("DeepSeek Shared")).length).toBeGreaterThan(0);
    expect(await screen.findByText("功能测试智能体默认模型")).toBeInTheDocument();
    expect(screen.queryByText(/sentinel-api-key/)).not.toBeInTheDocument();
  });
});
