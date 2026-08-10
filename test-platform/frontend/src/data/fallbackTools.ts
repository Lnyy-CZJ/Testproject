import type { Tool } from "../types/tool";

/**
 * 平台 API 不可用时的只读工具目录。
 *
 * 关键逻辑:
 *   只保留已经存在且可以直接访问的四个工具，避免数据库或 API 故障
 *   导致测试入口完全消失。该配置不承担动态工具管理职责。
 */
export const fallbackTools: Tool[] = [
  {
    id: "trackevents",
    name: "埋点测试",
    description: "解析 TrackEvents 日志，检查事件触发次数、业务字段和公共参数。",
    entry_url: "/trackevents/",
    short_code: "EVENT",
    icon_key: "event",
    category: "analysis",
    features: ["事件统计", "字段校验", "结果报告"],
    sort_order: 10,
    fallback_health_path: "/trackevents/health",
  },
  {
    id: "log-filter",
    name: "日志分析",
    description: "按接口筛选请求与响应日志，快速查看状态码、成功率和异常请求。",
    entry_url: "/log-filter/",
    short_code: "LOG",
    icon_key: "log",
    category: "analysis",
    features: ["接口筛选", "状态统计", "日志导出"],
    sort_order: 20,
    fallback_health_path: "/log-filter/health",
  },
  {
    id: "truthy-search",
    name: "检索评测",
    description: "运行检索任务，对比基准结果并生成评测报告。",
    entry_url: "/truthy-search/",
    short_code: "SEARCH",
    icon_key: "search",
    category: "evaluation",
    features: ["检索执行", "字段对比", "评测报告"],
    sort_order: 30,
    fallback_health_path: "/truthy-search/health",
  },
  {
    id: "api-autotest",
    name: "接口自动化",
    description: "触发 Gateway 接口自动化执行，查看回归结果与 Allure 报告。",
    entry_url: "/api-autotest/",
    short_code: "API",
    icon_key: "api",
    category: "automation",
    features: ["执行触发", "结果统计", "报告查看"],
    sort_order: 40,
    fallback_health_path: "/api-autotest/health",
  },
];
