import type { ToolHealthState } from "../types/tool";

const labels: Record<ToolHealthState, string> = {
  checking: "检测中",
  healthy: "正常",
  unhealthy: "服务异常",
};

/** 显示工具状态，同时提供文字信息，避免只依赖颜色表达。 */
export function ServiceStatus({ state }: { state: ToolHealthState }) {
  const cssState = state === "healthy" ? "ok" : state === "unhealthy" ? "error" : "checking";
  return (
    <span className={`status status-${cssState}`} aria-live="polite">
      <span className="status-dot" aria-hidden="true" />
      <span>{labels[state]}</span>
    </span>
  );
}
