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
  // 显式维护小型工具图标映射，未知类型安全回退到平台默认样式。
  const iconPresentation =
    {
      event: { className: "tool-icon-event", label: "EV" },
      log: { className: "tool-icon-log", label: "LG" },
      search: { className: "tool-icon-search", label: "SR" },
      api: { className: "tool-icon-api", label: "AP" },
      "functional-ai": { className: "tool-icon-functional-ai", label: "FT" },
      "api-ai": { className: "tool-icon-api-ai", label: "AI" },
    }[tool.icon_key] ?? { className: "tool-icon-event", label: "EV" };
  return (
    <article className="tool-card" data-tool={tool.id}>
      <div className="tool-card-header">
        <div
          className={`tool-icon ${iconPresentation.className}`}
          aria-hidden="true"
        >
          {iconPresentation.label}
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
