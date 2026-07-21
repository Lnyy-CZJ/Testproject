export const severityLabels: Record<string, string> = {
  fatal: '致命', major: '严重', normal: '一般', minor: '轻微', suggest: '建议',
};
export const severityColors: Record<string, string> = {
  fatal: 'red', major: 'orange', normal: 'blue', minor: 'green', suggest: 'default',
};
export const priorityColors: Record<string, string> = {
  P0: 'red', P1: 'orange', P2: 'blue', P3: 'green', P4: 'default',
};
export const statusLabels: Record<string, string> = {
  new: '新建', pending_assign: '待分配', pending_analysis: '待分析', analyzing: '分析中',
  pending_fix: '待修复', fixing: '修复中', manual_fixing: '人工修复中', pending_verify: '待验证', fixed: '已修复',
  completed: '已完成', rejected: '驳回', suspended: '暂停', reopened: '已重新打开',
};
export const statusColors: Record<string, string> = {
  new: 'default', pending_assign: 'processing', pending_analysis: 'processing', analyzing: 'warning',
  pending_fix: 'warning', fixing: 'error', manual_fixing: 'success', pending_verify: 'processing', fixed: 'success',
  completed: 'success', rejected: 'default', suspended: 'default', reopened: 'orange',
};
export const typeLabels: Record<string, string> = {
  functional: '功能缺陷', ui: 'UI问题', performance: '性能问题', security: '安全问题',
  compatibility: '兼容性问题', other: '其他',
};
export const fixTaskStatusLabels: Record<string, string> = {
  pending: '待处理', planning: '计划中', executing: '执行中', testing: '测试中',
  completed: '已完成', no_changes: '无需变更', completed_warning: '完成但有警告', partial_failed: '部分失败', failed: '失败',
};
export const fixTaskStatusColors: Record<string, string> = {
  pending: 'default', planning: 'processing', executing: 'warning', testing: 'processing',
  completed: 'success', no_changes: 'default', completed_warning: 'warning', partial_failed: 'orange', failed: 'error',
};

// Combined configs for list views (hex colors for custom styling)
export const severityConfig: Record<string, { color: string; label: string }> = {
  fatal: { color: '#dc2626', label: '致命' },
  major: { color: '#ea580c', label: '严重' },
  normal: { color: '#2563eb', label: '一般' },
  minor: { color: '#16a34a', label: '轻微' },
  suggest: { color: '#64748b', label: '建议' },
};

export const priorityConfig: Record<string, { color: string; label: string }> = {
  P0: { color: '#dc2626', label: '紧急' },
  P1: { color: '#ea580c', label: '高' },
  P2: { color: '#2563eb', label: '中' },
  P3: { color: '#16a34a', label: '低' },
  P4: { color: '#64748b', label: '最低' },
};

export const defectStatusConfig: Record<string, { color: string; label: string }> = {
  new: { color: '#64748b', label: '新建' },
  pending_assign: { color: '#8b5cf6', label: '待分配' },
  pending_analysis: { color: '#0891b2', label: '待分析' },
  analyzing: { color: '#f59e0b', label: '分析中' },
  pending_fix: { color: '#ea580c', label: '待修复' },
  fixing: { color: '#dc2626', label: '修复中' },
  manual_fixing: { color: '#e11d48', label: '人工修复中' },
  pending_verify: { color: '#2563eb', label: '待验证' },
  fixed: { color: '#16a34a', label: '已修复' },
  completed: { color: '#10b981', label: '已完成' },
  rejected: { color: '#64748b', label: '驳回' },
  suspended: { color: '#94a3b8', label: '暂停' },
  reopened: { color: '#ea580c', label: '已重新打开' },
};
