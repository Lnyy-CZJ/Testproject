import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { fetchToolHealth, fetchTools } from "../api/client";
import { mergeCapabilities } from "../data/capabilityCatalog";
import type {
  CapabilityDomainId,
  CapabilityViewModel,
  Tool,
  ToolHealthState,
} from "../types/tool";

interface ToolCatalogValue {
  tools: Tool[];
  capabilities: CapabilityViewModel[];
  groups: Record<CapabilityDomainId, CapabilityViewModel[]>;
  unknownTools: Tool[];
  healthStates: Record<string, ToolHealthState>;
  loading: boolean;
  refreshing: boolean;
  error: string;
  refreshHealth: () => Promise<void>;
  reloadCatalog: () => Promise<void>;
}

const ToolCatalogContext = createContext<ToolCatalogValue | null>(null);

export function useToolCatalog(): ToolCatalogValue {
  const value = useContext(ToolCatalogContext);
  if (!value) throw new Error("工具目录上下文未初始化");
  return value;
}

const emptyGroups = (): Record<CapabilityDomainId, CapabilityViewModel[]> => ({
  "ai-testing": [],
  automation: [],
  "quality-analysis": [],
  "domain-evaluation": [],
});

/** 在登录会话内只维护一份授权目录和健康状态，路由切换不会重复请求。 */
export function ToolCatalogProvider({ enabled, children }: PropsWithChildren<{ enabled: boolean }>) {
  const [tools, setTools] = useState<Tool[]>([]);
  const [healthStates, setHealthStates] = useState<Record<string, ToolHealthState>>({});
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const refreshHealthFor = useCallback(async (items: Tool[]) => {
    if (!items.length) return;
    setRefreshing(true);
    setHealthStates(Object.fromEntries(items.map((tool) => [tool.id, "checking"])));
    const results = await Promise.all(items.map(async (tool) => ({
      id: tool.id,
      healthy: await fetchToolHealth(tool),
    })));
    setHealthStates(Object.fromEntries(results.map((item) => [item.id, item.healthy ? "healthy" : "unhealthy"])));
    setRefreshing(false);
  }, []);

  const reloadCatalog = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError("");
    try {
      const items = await fetchTools();
      setTools(items);
      setLoading(false);
      await refreshHealthFor(items);
    } catch (requestError) {
      setTools([]);
      setHealthStates({});
      setError(requestError instanceof Error ? requestError.message : "工具目录加载失败");
      setLoading(false);
    }
  }, [enabled, refreshHealthFor]);

  useEffect(() => {
    if (!enabled) {
      setTools([]);
      setHealthStates({});
      setError("");
      setLoading(false);
      return;
    }
    void reloadCatalog();
  }, [enabled, reloadCatalog]);

  const refreshHealth = useCallback(() => refreshHealthFor(tools), [refreshHealthFor, tools]);
  const merged = useMemo(() => mergeCapabilities(tools, healthStates), [healthStates, tools]);
  const groups = useMemo(() => {
    const next = emptyGroups();
    merged.capabilities.forEach((capability) => next[capability.domainId].push(capability));
    return next;
  }, [merged.capabilities]);

  return (
    <ToolCatalogContext.Provider value={{
      tools,
      capabilities: merged.capabilities,
      groups,
      unknownTools: merged.unknownTools,
      healthStates,
      loading,
      refreshing,
      error,
      refreshHealth,
      reloadCatalog,
    }}>
      {children}
    </ToolCatalogContext.Provider>
  );
}
