import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const apiTool = {
  id: "trackevents",
  name: "数据库埋点工具",
  description: "来自平台 API 的工具",
  entry_url: "/trackevents/",
  short_code: "EVENT",
  icon_key: "event",
  category: "analysis",
  features: ["事件统计"],
  sort_order: 10,
};

const searchApiTool = {
  id: "truthy-search",
  name: "检索评测",
  description: "来自平台 API 的检索工具",
  entry_url: "/truthy-search/",
  short_code: "SEARCH",
  icon_key: "search",
  category: "evaluation",
  features: ["检索执行", "字段对比", "评测报告"],
  sort_order: 30,
};

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App", () => {
  it("目录加载期间保留三个入口并展示检测中状态", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    render(<App />);

    expect(screen.getAllByText("检测中")).toHaveLength(3);
    expect(screen.getAllByRole("link", { name: /打开工具/ })).toHaveLength(3);
  });

  it("API 返回空目录时展示可理解的空状态", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() =>
      jsonResponse({ items: [] }),
    );

    render(<App />);

    expect(
      await screen.findByText("当前没有已启用的测试工具。"),
    ).toBeInTheDocument();
  });

  it("使用 API 工具目录并展示健康状态", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => jsonResponse({ items: [apiTool] }))
      .mockImplementationOnce(() =>
        jsonResponse({
          tool_id: "trackevents",
          status: "healthy",
          checked_at: "2026-07-31T00:00:00Z",
        }),
      );

    render(<App />);

    expect(await screen.findByText("数据库埋点工具")).toBeInTheDocument();
    expect(await screen.findByText("正常")).toBeInTheDocument();
    expect(screen.queryByText(/显示基础工具入口/)).not.toBeInTheDocument();
  });

  it("平台 API 异常时保留三个基础工具入口", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockImplementation(() => jsonResponse({ status: "ok" }));

    render(<App />);

    expect(await screen.findByText(/显示基础工具入口/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /打开工具/ })[0]).toHaveAttribute(
      "href",
      "/trackevents/",
    );
    const toolLinks = screen.getAllByRole("link", { name: /打开工具/ });
    expect(toolLinks).toHaveLength(3);
    expect(toolLinks[2]).toHaveAttribute("href", "/truthy-search/");
    expect(screen.getByText("SR")).toBeInTheDocument();
  });

  it("动态目录以 SR 图标展示 Truthy_Search 卡片", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => jsonResponse({ items: [searchApiTool] }))
      .mockImplementationOnce(() =>
        jsonResponse({
          tool_id: "truthy-search",
          status: "healthy",
          checked_at: "2026-07-31T00:00:00Z",
        }),
      );

    render(<App />);

    expect(await screen.findByText("检索评测")).toBeInTheDocument();
    expect(screen.getByText("SR")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开工具/ })).toHaveAttribute(
      "href",
      "/truthy-search/",
    );
  });

  it("重新检测按钮只刷新当前工具健康状态", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => jsonResponse({ items: [apiTool] }))
      .mockImplementation(() =>
        jsonResponse({
          tool_id: "trackevents",
          status: "healthy",
          checked_at: "2026-07-31T00:00:00Z",
        }),
      );

    render(<App />);
    await screen.findByText("正常");
    fireEvent.click(screen.getByRole("button", { name: "重新检测状态" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(
      fetchMock.mock.calls.filter(([url]) => url === "/api/v1/tools"),
    ).toHaveLength(1);
  });
});
