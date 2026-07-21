import { Card, Tabs, Tag } from 'antd';
import MarkdownContent from '../../components/MarkdownContent';
import DefectAnalysisPanel from './components/DefectAnalysisPanel';
import DefectFixTaskPanel from './components/DefectFixTaskPanel';
import DefectCommentSection from './components/DefectCommentSection';
import DefectTokenUsagePanel from './components/DefectTokenUsagePanel';
import type { Defect, FixTask, Comment } from '../../types';
import type { ReportSummary } from './types';
import type { ThinkingStep } from '../../api/types';

interface DefectTabsProps {
  defect: Defect;
  reportSummaries: ReportSummary[];
  latestReport: ReportSummary | undefined;
  historicalReports: ReportSummary[];
  latestAnalysis: ReportSummary['analysisData'];
  analyzing: boolean;
  thinkingSteps: ThinkingStep[];
  currentPhase: string;
  analysisError: string | null;
  latestAffectedFiles: string[];
  latestEvidenceFiles?: string[];
  latestValidationSuggestions: string[];
  fixTasks: FixTask[];
  latestFixTask: FixTask | undefined;
  historicalFixTasks: FixTask[];
  latestFixTaskMarkdown: string;
  latestFixTaskCodeChanges: { filePath?: string; description?: string; diff?: string; oldContent?: string; newContent?: string; content?: string }[];
  latestFixTaskValidation: string[];
  latestFixTaskRaw: string;
  comments: Comment[];
  commentText: string;
  onCommentTextChange: (text: string) => void;
  onSubmitComment: () => void;
  onRefresh: () => void;
  onStartAnalysis: () => void;
}

export default function DefectTabs({
  defect,
  reportSummaries,
  latestReport,
  historicalReports,
  latestAnalysis,
  analyzing,
  thinkingSteps,
  currentPhase,
  analysisError,
  latestAffectedFiles,
  latestEvidenceFiles = [],
  latestValidationSuggestions,
  fixTasks,
  latestFixTask,
  historicalFixTasks,
  latestFixTaskMarkdown,
  latestFixTaskCodeChanges,
  latestFixTaskValidation,
  latestFixTaskRaw,
  comments,
  commentText,
  onCommentTextChange,
  onSubmitComment,
  onRefresh,
  onStartAnalysis,
}: DefectTabsProps) {
  const sortedComments = comments;
  const recentComments = sortedComments.slice(0, 3);
  const archivedComments = sortedComments.slice(3);

  return (
    <Card className="scene-card overflow-hidden">
      <Tabs
        defaultActiveKey="desc"
        items={[
          {
            key: 'desc',
            label: '描述',
            children: (
              <div className="tab-content">
                <MarkdownContent content={defect.description} emptyText="暂无描述" className="max-w-[78ch]" />
                {defect.tags ? (
                  <div className="mt-4 flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
                    {(defect.tags || []).map((tag: string) => (
                      <Tag key={tag.trim()} className="tag-rounded">{tag.trim()}</Tag>
                    ))}
                  </div>
                ) : null}
              </div>
            ),
          },
          {
            key: 'analysis',
            label: `AI分析${reportSummaries.length ? ` (${reportSummaries.length})` : ''}`,
            children: (
              <DefectAnalysisPanel
                reportSummaries={reportSummaries}
                latestReport={latestReport}
                historicalReports={historicalReports}
                latestAnalysis={latestAnalysis}
                analyzing={analyzing}
                thinkingSteps={thinkingSteps}
                currentPhase={currentPhase}
                analysisError={analysisError}
                latestAffectedFiles={latestAffectedFiles}
                latestEvidenceFiles={latestEvidenceFiles}
                latestValidationSuggestions={latestValidationSuggestions}
                onRefresh={onRefresh}
                onStartAnalysis={onStartAnalysis}
              />
            ),
          },
          {
            key: 'fix',
            label: `修复任务${fixTasks.length ? ` (${fixTasks.length})` : ''}`,
            children: (
              <DefectFixTaskPanel
                fixTasks={fixTasks}
                latestFixTask={latestFixTask}
                historicalFixTasks={historicalFixTasks}
                latestFixTaskMarkdown={latestFixTaskMarkdown}
                latestFixTaskCodeChanges={latestFixTaskCodeChanges}
                latestFixTaskValidation={latestFixTaskValidation}
                latestFixTaskRaw={latestFixTaskRaw}
              />
            ),
          },
          {
            key: 'activity',
            label: `动态${sortedComments.length ? ` (${sortedComments.length})` : ''}`,
            children: (
              <DefectCommentSection
                recentComments={recentComments}
                archivedComments={archivedComments}
                commentText={commentText}
                onCommentTextChange={onCommentTextChange}
                onSubmitComment={onSubmitComment}
              />
            ),
          },
          {
            key: 'token-usage',
            label: 'Token 消耗',
            children: (
              <DefectTokenUsagePanel defectId={defect.id} />
            ),
          },
        ]}
      />
    </Card>
  );
}
