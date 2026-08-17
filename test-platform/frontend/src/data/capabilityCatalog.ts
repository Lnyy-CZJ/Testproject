import type {
  CapabilityDefinition,
  CapabilityDomainId,
  CapabilityViewModel,
  Tool,
  ToolHealthState,
} from "../types/tool";

export const domainOrder: CapabilityDomainId[] = [
  "ai-testing",
  "automation",
  "quality-analysis",
  "domain-evaluation",
];

export const domainMeta: Record<CapabilityDomainId, { title: string; eyebrow: string; description: string }> = {
  "ai-testing": {
    title: "AI 测试",
    eyebrow: "AI TESTING",
    description: "让 AI 参与测试设计与接口验证，同时保留工程师 Review 和最终判断。",
  },
  automation: {
    title: "自动化",
    eyebrow: "CONTINUOUS VERIFICATION",
    description: "把已经稳定的接口沉淀为可重复、可持续执行的回归检查。",
  },
  "quality-analysis": {
    title: "质量分析",
    eyebrow: "QUALITY ANALYSIS",
    description: "围绕埋点和运行日志定位质量问题，两项任务与数据彼此独立。",
  },
  "domain-evaluation": {
    title: "专项评测",
    eyebrow: "DOMAIN EVALUATION",
    description: "面向具体项目、账号和环境，对检索结果执行可追溯的专项评测。",
  },
};

export const capabilityCatalog: CapabilityDefinition[] = [
  {
    toolId: "functional-test-agent",
    domainId: "ai-testing",
    displayName: "功能测试智能体",
    mission: "从需求中提炼可执行的测试设计",
    scenario: "适合需求评审后快速梳理测试范围和覆盖重点。",
    inputSummary: "需求文档、功能说明与测试约束",
    outputSummary: "测试点、测试用例与导出文件",
    boundary: "生成结果需要工程师 Review，不自动执行功能测试。",
    actionLabel: "生成测试用例",
    visualPriority: "primary",
  },
  {
    toolId: "api-test-agent",
    domainId: "ai-testing",
    displayName: "API 测试智能体",
    mission: "围绕接口契约完成探索式验证",
    scenario: "适合新接口或变更接口的首轮验证和问题发现。",
    inputSummary: "API 文档、环境与测试数据",
    outputSummary: "契约、用例、执行结果与缺陷草稿",
    boundary: "面向探索和问题分析，不替代长期自动化回归。",
    actionLabel: "开始接口测试",
    visualPriority: "primary",
  },
  {
    toolId: "api-autotest",
    domainId: "automation",
    displayName: "接口自动化",
    mission: "持续验证已经稳定的接口",
    scenario: "适合修复确认后沉淀回归场景并周期执行。",
    inputSummary: "稳定接口、用例数据与目标环境",
    outputSummary: "执行记录、断言结果与回归报告",
    boundary: "不接收 AI 测试智能体的任务数据，两者独立运行。",
    actionLabel: "进入接口自动化",
    visualPriority: "standard",
  },
  {
    toolId: "trackevents",
    domainId: "quality-analysis",
    displayName: "埋点分析",
    mission: "校验事件上报和字段质量",
    scenario: "适合客户端埋点联调、版本验收和数据质量核对。",
    inputSummary: "TrackEvents 日志与校验规则",
    outputSummary: "事件统计、字段校验与分析结果",
    boundary: "只分析当前提交的埋点数据。",
    actionLabel: "开始埋点分析",
    visualPriority: "standard",
  },
  {
    toolId: "log-filter",
    domainId: "quality-analysis",
    displayName: "日志分析",
    mission: "从运行日志中提取故障线索",
    scenario: "适合问题排查、关键链路定位和日志结果导出。",
    inputSummary: "运行日志、筛选条件与分析规则",
    outputSummary: "过滤结果、异常线索与导出文件",
    boundary: "与埋点分析共享能力域，但任务和数据完全独立。",
    actionLabel: "开始日志分析",
    visualPriority: "standard",
  },
  {
    toolId: "truthy-search",
    domainId: "domain-evaluation",
    displayName: "检索评测",
    mission: "评估特定项目的检索质量",
    scenario: "适合结合专用账号、环境和基准数据执行专项评测。",
    inputSummary: "查询样本、候选结果与评测基准",
    outputSummary: "字段对比、准确性分析与评测报告",
    boundary: "能力与具体项目、账号和环境强相关。",
    actionLabel: "开始检索评测",
    visualPriority: "standard",
  },
];

const definitionByToolId = new Map(capabilityCatalog.map((item) => [item.toolId, item]));

/** 只接受站内绝对路径，避免把后端目录误用为外部导航。 */
export function isSafeEntryUrl(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !value.includes("\\");
}

/** 只合并后端实际返回且入口安全的工具，Catalog 不补回未授权能力。 */
export function mergeCapabilities(
  tools: Tool[],
  healthStates: Record<string, ToolHealthState>,
): { capabilities: CapabilityViewModel[]; unknownTools: Tool[] } {
  const capabilities: CapabilityViewModel[] = [];
  const unknownTools: Tool[] = [];
  tools.forEach((tool) => {
    if (!isSafeEntryUrl(tool.entry_url)) return;
    const definition = definitionByToolId.get(tool.id);
    if (!definition) {
      unknownTools.push(tool);
      if (import.meta.env.DEV) console.warn(`[tool-catalog] 未登记工具：${tool.id}`);
      return;
    }
    capabilities.push({ ...definition, tool, health: healthStates[tool.id] ?? "checking" });
  });
  return { capabilities, unknownTools };
}
