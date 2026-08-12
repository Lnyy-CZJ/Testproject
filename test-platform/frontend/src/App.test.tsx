import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const auth = {
  user: { id: "usr_1", username: "admin", display_name: "平台管理员", status: "active", must_change_password: false },
  roles: ["role_platform_admin"],
  platform_permissions: ["platform.user.manage", "platform.role.manage", "platform.audit.view", "platform.config.manage", "platform.secret.manage"],
  tool_permissions: { trackevents: ["tool.view", "tool.execute", "tool.result.view"] },
  session_expires_at: "2026-08-11T00:00:00Z",
};

const tool = {
  id: "trackevents", name: "埋点测试", description: "解析埋点日志",
  entry_url: "/trackevents/", short_code: "EVENT", icon_key: "event",
  category: "analysis", features: ["事件统计"], sort_order: 10,
};

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

describe("第二阶段平台", () => {
  it("未登录时强制进入登录页，不显示匿名工具入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => jsonResponse({ code: "AUTH_REQUIRED", message: "请先登录" }, 401));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "登录工程工作台" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /打开工具/ })).not.toBeInTheDocument();
  });

  it("已登录用户只看到 API 授权目录和健康状态", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [tool] });
      return jsonResponse({ tool_id: tool.id, status: "healthy", checked_at: "2026-08-10T00:00:00Z" });
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "埋点测试" })).toBeInTheDocument();
    expect(await screen.findByText("正常")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开工具/ })).toHaveAttribute("href", "/trackevents/");
  });

  it("工具目录异常时失败关闭，不恢复静态入口", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => String(input).endsWith("/auth/me") ? jsonResponse(auth) : jsonResponse({ code: "DATABASE_UNAVAILABLE", message: "数据库不可用" }, 503));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("已停止工具导航");
    expect(screen.queryByRole("link", { name: /打开工具/ })).not.toBeInTheDocument();
  });

  it("重新检测只刷新当前工具健康状态", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [tool] });
      return jsonResponse({ tool_id: tool.id, status: "healthy", checked_at: "2026-08-10T00:00:00Z" });
    });
    render(<App />);
    await screen.findByText("正常");
    fireEvent.click(screen.getByRole("button", { name: "重新检测状态" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/tools"))).toHaveLength(1);
  });

  it("按平台权限展示管理导航", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/auth/me")) return jsonResponse(auth);
      if (url.endsWith("/tools")) return jsonResponse({ items: [] });
      return jsonResponse({});
    });
    render(<App />);
    expect(await screen.findByRole("link", { name: "配置" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "权限" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "审计" })).toBeInTheDocument();
  });

  it("没有管理权限时不显示管理导航", async () => {
    const readonly = { ...auth, platform_permissions: [] };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => String(input).endsWith("/auth/me") ? jsonResponse(readonly) : jsonResponse({ items: [] }));
    render(<App />);
    await screen.findByText("平台管理员");
    expect(screen.queryByRole("link", { name: "配置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "权限" })).not.toBeInTheDocument();
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
});
