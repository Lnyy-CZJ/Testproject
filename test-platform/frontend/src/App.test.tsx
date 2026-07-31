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

  it("平台 API 异常时保留两个基础工具入口", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("network error"))
      .mockImplementation(() => jsonResponse({ status: "ok" }));

    render(<App />);

    expect(await screen.findByText(/显示基础工具入口/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /打开工具/ })[0]).toHaveAttribute(
      "href",
      "/trackevents/",
    );
    expect(screen.getAllByRole("link", { name: /打开工具/ })).toHaveLength(2);
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
