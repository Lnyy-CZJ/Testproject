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
      {safeEntry ? <a className="capability-action" href={capability.tool.entry_url}>{capability.actionLabel}</a> : <span className="capability-action capability-action-disabled">入口不可用</span>}
    </article>
  );
}
