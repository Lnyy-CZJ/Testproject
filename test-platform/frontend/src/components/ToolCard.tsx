import type { Tool, ToolHealthState } from "../types/tool";
import { ServiceStatus } from "./ServiceStatus";

/** 将单个工具元数据和运行状态渲染为可访问的导航卡片。 */
export function ToolCard({
  tool,
  health,
}: {
  tool: Tool;
  health: ToolHealthState;
}) {
  const iconClass = tool.icon_key === "log" ? "tool-icon-log" : "tool-icon-event";
  return (
    <article className="tool-card" data-tool={tool.id}>
      <div className="tool-card-header">
        <div className={`tool-icon ${iconClass}`} aria-hidden="true">
          {tool.icon_key === "log" ? "LG" : "EV"}
        </div>
        <div className="card-topline">
          <span className="tool-code">{tool.short_code}</span>
          <ServiceStatus state={health} />
        </div>
      </div>
      <h3>{tool.name}</h3>
      <p>{tool.description}</p>
      <ul className="feature-list" aria-label={`${tool.name}能力`}>
        {tool.features.map((feature) => (
          <li key={feature}>{feature}</li>
        ))}
      </ul>
      <a className="tool-link" href={tool.entry_url}>
        打开工具 <span aria-hidden="true">›</span>
      </a>
    </article>
  );
}
