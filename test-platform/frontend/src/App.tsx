import { useCallback, useEffect, useState } from "react";

import { fetchToolHealth, fetchTools } from "./api/client";
import { AppShell } from "./components/AppShell";
import { Hero } from "./components/Hero";
import { Roadmap } from "./components/Roadmap";
import { ToolGrid } from "./components/ToolGrid";
import { fallbackTools } from "./data/fallbackTools";
import type { Tool, ToolHealthState } from "./types/tool";

const FALLBACK_MESSAGE = "平台服务暂时不可用，当前显示基础工具入口";

/** 平台首页：加载动态目录，并在 API 异常时安全退回已有工具入口。 */
function HomePage() {
  const [tools, setTools] = useState<Tool[]>(fallbackTools);
  const [useFallback, setUseFallback] = useState(false);
  const [warning, setWarning] = useState("");
  const [healthStates, setHealthStates] = useState<Record<string, ToolHealthState>>({});
  const [refreshing, setRefreshing] = useState(false);

  /**
   * 并行刷新所有工具状态。
   *
   * 参数说明:
   *   currentTools: 当前页面实际展示的工具目录。
   *   fallbackMode: true 时直接检查工具公开健康地址。
   *
   * 返回值:
   *   Promise<void>，所有工具状态均已写入页面状态后完成。
   */
  const refreshStatuses = useCallback(
    async (currentTools: Tool[], fallbackMode: boolean) => {
      setRefreshing(true);
      setHealthStates(
        Object.fromEntries(currentTools.map((tool) => [tool.id, "checking"])),
      );
      const results = await Promise.all(
        currentTools.map(async (tool) => ({
          id: tool.id,
          healthy: await fetchToolHealth(tool, fallbackMode),
        })),
      );
      setHealthStates(
        Object.fromEntries(
          results.map((result) => [
            result.id,
            result.healthy ? "healthy" : "unhealthy",
          ]),
        ),
      );
      setRefreshing(false);
    },
    [],
  );

  useEffect(() => {
    let active = true;
    async function loadDirectory() {
      try {
        const items = await fetchTools();
        if (!active) return;
        setTools(items);
        setUseFallback(false);
        setWarning("");
        await refreshStatuses(items, false);
      } catch {
        if (!active) return;
        setTools(fallbackTools);
        setUseFallback(true);
        setWarning(FALLBACK_MESSAGE);
        await refreshStatuses(fallbackTools, true);
      }
    }
    void loadDirectory();
    return () => {
      active = false;
    };
  }, [refreshStatuses]);

  return (
    <AppShell>
      <Hero toolCount={tools.length} />
      <section id="tools" className="tools-section" aria-labelledby="tools-title">
        <div className="section-heading">
          <div>
            <p className="section-label">已接入工具</p>
            <h2 id="tools-title">选择工具开始测试</h2>
          </div>
          <button
            className="refresh-button"
            type="button"
            disabled={refreshing}
            onClick={() => void refreshStatuses(tools, useFallback)}
          >
            {refreshing ? "检测中..." : "重新检测状态"}
          </button>
        </div>
        {warning && (
          <p className="platform-alert" role="status">
            {warning}
          </p>
        )}
        <ToolGrid tools={tools} healthStates={healthStates} />
      </section>
      <Roadmap />
    </AppShell>
  );
}

/** 未匹配的前端路由返回清晰页面，不影响 Nginx 工具路由。 */
function NotFoundPage() {
  return (
    <AppShell>
      <section className="not-found">
        <p className="section-label">404</p>
        <h1>页面不存在</h1>
        <a className="tool-link" href="/">
          返回平台首页
        </a>
      </section>
    </AppShell>
  );
}

/**
 * 定义第一轮平台前端路由。
 *
 * 关键逻辑:
 *   当前仅有首页和 404，直接按浏览器路径选择页面，避免为两个静态路由
 *   引入存在安全公告的路由依赖。Nginx 仍负责把前端路径回退到 index.html。
 */
export function App() {
  return window.location.pathname === "/" ? <HomePage /> : <NotFoundPage />;
}
