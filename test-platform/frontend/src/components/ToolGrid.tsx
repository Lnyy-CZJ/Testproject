import type { Tool, ToolHealthState } from "../types/tool";
import { ToolCard } from "./ToolCard";

/** 渲染动态工具目录，并负责空目录提示。 */
export function ToolGrid({
  tools,
  healthStates,
}: {
  tools: Tool[];
  healthStates: Record<string, ToolHealthState>;
}) {
  if (tools.length === 0) {
    return <p className="empty-state">当前没有已启用的测试工具。</p>;
  }
  return (
    <div className="tool-grid">
      {tools.map((tool) => (
        <ToolCard
          key={tool.id}
          tool={tool}
          health={healthStates[tool.id] ?? "checking"}
        />
      ))}
    </div>
  );
}
