import { logger } from '../../utils/logger';
import type { AnalysisReport, FixTask } from '../../types';
import type { ReportAnalysisData, ReportFileRef } from './types';

export const formatAnalysisFileRef = (value: unknown): string => {
  if (typeof value === 'string') {
    return value.trim();
  }
  if (!value || typeof value !== 'object') {
    return '';
  }
  const ref = value as ReportFileRef;
  const path = ref.filePath || ref.path || ref.targetFile || ref.file_path || ref.filepath || '';
  const repo = ref.repoHint || ref.repo || '';
  if (!path) {
    return '';
  }
  return repo && !path.startsWith(`${repo}/`) ? `${repo}/${path}` : path;
};

export const normalizeAnalysisFileRefs = (value?: Array<string | ReportFileRef>) => {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set<string>();
  return value
    .map(formatAnalysisFileRef)
    .filter((item) => {
      if (!item || seen.has(item)) {
        return false;
      }
      seen.add(item);
      return true;
    });
};

export const parseStringArray = (value?: string | string[]) => {
  if (Array.isArray(value)) {
    return value;
  }
  if (!value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
  } catch (err) { logger.error('解析JSON失败:', err); return []; }
};

export const stringifyPrettyJson = (value: unknown) => {
  if (!value) return '';
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

export const parseReportAnalysis = (report: AnalysisReport): ReportAnalysisData | null => {
  try {
    if (typeof report.analysis === 'string') {
      return JSON.parse(report.analysis) as ReportAnalysisData;
    }
    if (report.analysis && typeof report.analysis === 'object') {
      return report.analysis;
    }
    return null;
  } catch {
    return null;
  }
};

export const buildReportMarkdown = (report: AnalysisReport, analysisData: ReportAnalysisData | null) => {
  if (!analysisData) {
    return typeof report.analysis === 'string'
      ? report.analysis
      : typeof report.solution === 'string'
        ? report.solution
        : '暂无分析摘要';
  }

  const sections: string[] = [];

  if (analysisData.rootCause) {
    sections.push(`## 根本原因\n${analysisData.rootCause}`);
  }
  const affectedFiles = normalizeAnalysisFileRefs(analysisData.affectedFiles);
  if (affectedFiles.length) {
    sections.push(`## 影响文件\n${affectedFiles.map((file) => `- \`${file}\``).join('\n')}`);
  }
  const evidenceFiles = normalizeAnalysisFileRefs(analysisData.evidenceFiles);
  if (evidenceFiles.length) {
    sections.push(`## 代码证据候选文件\n${evidenceFiles.map((file) => `- \`${file}\``).join('\n')}`);
  }
  if (analysisData.riskLevel) {
    sections.push(`## 风险等级\n**${String(analysisData.riskLevel).toUpperCase()}**`);
  }
  if (analysisData.riskSummary || report.riskSummary) {
    sections.push(`## 风险摘要\n${analysisData.riskSummary || report.riskSummary}`);
  }
  if (analysisData.solution) {
    const solutionLines: string[] = [];
    if (analysisData.solution.description) {
      solutionLines.push(analysisData.solution.description);
    }
    if (analysisData.solution.steps?.length) {
      solutionLines.push(
        analysisData.solution.steps
          .map((step) => {
            const filePath = step.filePath || step.path || step.targetFile;
            const stepLabel = step.step ? `Step ${step.step}: ` : '';
            const action = step.action || '';
            return `- ${stepLabel}${filePath ? `\`${filePath}\`：` : ''}${action}`;
          })
          .join('\n'),
      );
    }
    if (analysisData.solution.estimatedEffort) {
      solutionLines.push(`预计工作量：${analysisData.solution.estimatedEffort}`);
    }
    sections.push(`## 修复方案\n${solutionLines.join('\n\n')}`);
  }

  const validationSuggestions = analysisData.validationSuggestions?.length
    ? analysisData.validationSuggestions
    : parseStringArray(report.validationSuggestions);
  if (validationSuggestions.length) {
    sections.push(`## 修复前验证建议\n${validationSuggestions.map((item) => `- ${item}`).join('\n')}`);
  }

  return sections.join('\n\n').trim();
};

export const buildFixTaskMarkdown = (task: FixTask) => {
  const sections: string[] = [];
  if (task.aiRiskSummary) {
    sections.push(`## 风险摘要\n${task.aiRiskSummary}`);
  }
  const validationSuggestions = parseStringArray(task.aiValidationSuggestions);
  if (validationSuggestions.length) {
    sections.push(`## 验证建议\n${validationSuggestions.map((item) => `- ${item}`).join('\n')}`);
  }
  if (task.aiLastError) {
    sections.push(`## 失败原因\n${task.aiLastError}`);
  }
  return sections.join('\n\n').trim();
};

export const buildCommentPreview = (content: string) => {
  const normalized = content.replace(/\s+/g, ' ').trim();
  if (normalized.length <= 120) {
    return normalized;
  }
  return `${normalized.slice(0, 120)}...`;
};

export const stripMarkdown = (content?: string | null) => {
  if (!content) return '';

  return content
    .replace(/```[\s\S]*?```/g, '[代码片段]')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/_{1,2}([^_]+)_{1,2}/g, '$1')
    .replace(/\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

export const truncateText = (content?: string | null, max = 160) => {
  const normalized = stripMarkdown(content);
  if (!normalized) return '';
  const chars = Array.from(normalized);
  if (chars.length <= max) return normalized;
  return `${chars.slice(0, max).join('').trim()}...`;
};
