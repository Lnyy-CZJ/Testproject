import { isSafeEntryUrl } from "../data/capabilityCatalog";
import type { CapabilityViewModel } from "../types/tool";
import { ServiceStatus } from "./ServiceStatus";

/** 工作台的使命卡片只保留一个主入口，避免嵌套交互和重复焦点。 */
export function CapabilityCard({ capability, compact = false }: { capability: CapabilityViewModel; compact?: boolean }) {
  const safeEntry = isSafeEntryUrl(capability.tool.entry_url);
  return (
    <article className={`capability-card capability-card-${capability.visualPriority}${compact ? " capability-card-compact" : ""}`}>
      <div className="capability-card-topline">
        <span className="capability-code">{capability.tool.short_code}</span>
        <ToolSourceBadge tool={capability.tool} />
        <ServiceStatus state={capability.health} />
      </div>
      <h3>{capability.displayName}</h3>
      <p className="capability-mission">{capability.mission}</p>
      {!compact && <p className="capability-scenario">{capability.scenario}</p>}
      <dl className="capability-io">
        <div><dt>输入</dt><dd>{capability.inputSummary}</dd></div>
        <div><dt>输出</dt><dd>{capability.outputSummary}</dd></div>
      </dl>
      {capability.boundary && !compact && <p className="capability-boundary">{capability.boundary}</p>}
      {capability.tool.can_manage && <a className="tool-manage-link" href={`/admin/tool-access/${encodeURIComponent(capability.tool.id)}`}>管理此工具</a>}
      {safeEntry ? <a className="capability-action" href={capability.tool.entry_url}>{capability.actionLabel}</a> : <span className="capability-action capability-action-disabled">入口不可用</span>}
    </article>
  );
}

function ToolSourceBadge({ tool }: { tool: CapabilityViewModel["tool"] }) {
  const source = tool.access_source;
  const label = source === "extra_grant" ? "额外授权" : source === "public" ? "公共工具" : tool.project?.name ?? (tool.access_scope === "project" ? "项目工具" : "公共工具");
  return <span className="access-source-badge">{label}</span>;
}
