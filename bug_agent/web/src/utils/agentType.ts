import { AGENT_TYPES } from '../types';

/** agent type -> antd Tag color */
const AGENT_TAG_COLORS: Record<string, string> = {
  product: 'purple',
  ui: 'pink',
  frontend: 'blue',
  client: 'cyan',
  backend: 'green',
  test: 'orange',
};

/** agent type -> 中文短标签 */
const AGENT_SHORT_LABELS: Record<string, string> = {
  product: '产品',
  ui: 'UI',
  frontend: '前端',
  client: '客户端',
  backend: '后端',
  test: '测试',
};

/** 获取 agent type 的 Tag 颜色 */
export function getAgentTagColor(type: string): string {
  return AGENT_TAG_COLORS[type] || 'default';
}

/** 获取 agent type 的短标签 */
export function getAgentShortLabel(type: string): string {
  return AGENT_SHORT_LABELS[type] || type;
}

/** 获取 agent type 的完整标签（从全局 AGENT_TYPES） */
export function getAgentFullLabel(type: string): string {
  return AGENT_TYPES.find((a) => a.key === type)?.label || type;
}

/** 将 agentTypes 字符串/数组标准化为数组 */
export function normalizeAgentTypes(agentTypes?: string | string[]): string[] {
  if (!agentTypes) return [];
  if (Array.isArray(agentTypes)) return agentTypes;
  return agentTypes.split(',').map((t) => t.trim()).filter(Boolean);
}

/** 缺陷类型 -> 默认 Agent 类型映射 */
export const DEFECT_TYPE_TO_AGENT: Record<string, string> = {
  performance: 'backend',
  security: 'backend',
  ui: 'ui',
  compatibility: 'client',
  functional: 'frontend',
  other: 'product',
};
