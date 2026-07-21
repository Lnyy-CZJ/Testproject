import type { ReactNode } from 'react';
import type { AnalysisReport } from '../../types';

export interface EditDefectForm {
  title: string;
  description: string;
  severity: string;
  priority: string;
  type: string;
  tags: string;
}

export interface ReportSolutionStep {
  step?: string | number;
  action?: string;
  filePath?: string;
  path?: string;
  targetFile?: string;
  repoHint?: string;
}

export interface ReportFileRef {
  filePath?: string;
  path?: string;
  targetFile?: string;
  file_path?: string;
  filepath?: string;
  repoHint?: string;
  repo?: string;
}

export interface ReportAnalysisData {
  rootCause?: string;
  affectedFiles?: Array<string | ReportFileRef>;
  evidenceFiles?: Array<string | ReportFileRef>;
  riskLevel?: 'low' | 'medium' | 'high' | string;
  riskSummary?: string;
  validationSuggestions?: string[];
  solution?: {
    description?: string;
    steps?: ReportSolutionStep[];
    estimatedEffort?: string;
  };
}

export interface DetailMetaItem {
  label: string;
  value: ReactNode;
}

export interface ReportSummary {
  report: AnalysisReport;
  analysisData: ReportAnalysisData | null;
  summaryMarkdown: string;
  rawPayload: string;
}

export interface StatusStep {
  key: string;
  label: string;
}
