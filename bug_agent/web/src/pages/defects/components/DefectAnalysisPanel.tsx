import { Tag, Button, Empty, Space, Collapse, Tooltip } from 'antd';
import { ReloadOutlined, ExclamationCircleOutlined, CodeOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import type { ReportSummary } from '../types';
import { getAgentTagColor, getAgentFullLabel } from '../../../utils/agentType';
import { truncateText } from '../utils';
import MarkdownContent from '../../../components/MarkdownContent';
import ThinkingProcess from './ThinkingProcess';
import type { ThinkingStep, TokenUsageRecord } from '../../../api/types';
import '../defect-detail.css';
import dayjs from 'dayjs';

interface DefectAnalysisPanelProps {
  reportSummaries: ReportSummary[];
  latestReport: ReportSummary | undefined;
  historicalReports: ReportSummary[];
  latestAnalysis: ReportSummary['analysisData'];
  analyzing: boolean;
  thinkingSteps: ThinkingStep[];
  currentPhase: string;
  analysisError: string | null;
  latestAffectedFiles: string[];
  latestEvidenceFiles: string[];
  latestValidationSuggestions: string[];
  tokenRecords?: TokenUsageRecord[];
  onRefresh: () => void;
  onStartAnalysis: () => void;
}

const formatTokenNumber = (value?: number) => (value || 0).toLocaleString('en-US');
const formatCost = (value?: number) => `$${(value || 0).toFixed(4)}`;

function getAnalysisTokenRecord(records: TokenUsageRecord[], reportId?: number) {
  if (!reportId) return undefined;
  return records
    .filter((record) => record.consumptionType === 'analysis' && record.sourceId === reportId)
    .sort((left, right) => right.attemptIndex - left.attemptIndex)[0];
}

export default function DefectAnalysisPanel({
  latestReport,
  historicalReports,
  latestAnalysis,
  analyzing,
  thinkingSteps,
  currentPhase,
  analysisError,
  latestAffectedFiles,
  latestEvidenceFiles,
  latestValidationSuggestions,
  tokenRecords = [],
  onRefresh,
  onStartAnalysis,
}: DefectAnalysisPanelProps) {
  const latestTokenRecord = getAnalysisTokenRecord(tokenRecords, latestReport?.report.id);
  const visibleAffectedFiles = latestAffectedFiles.slice(0, 3);

  return (
    <div className="tab-content">
      {analyzing ? (
        <ThinkingProcess steps={thinkingSteps} currentPhase={currentPhase} analyzing={analyzing} error={analysisError} />
      ) : latestReport ? (
        <div>
          <div className="flex items-center flex-wrap gap-2 mb-4 pb-3 border-b border-slate-100">
            <Tag color={getAgentTagColor(latestReport.report.agentType)} className="tag-rounded">
              {getAgentFullLabel(latestReport.report.agentType)}
            </Tag>
            <Tag color={latestReport.report.status === 'completed' ? 'success' : latestReport.report.status === 'completed_fallback' ? 'warning' : 'processing'} className="tag-rounded">
              {latestReport.report.status === 'completed' ? '分析完成' : latestReport.report.status === 'completed_fallback' ? '降级完成' : '分析中'}
            </Tag>
            <Tag color={latestAnalysis?.riskLevel === 'high' ? 'red' : latestAnalysis?.riskLevel === 'medium' ? 'gold' : 'green'} className="tag-rounded">
              风险 {String(latestAnalysis?.riskLevel || 'medium').toUpperCase()}
            </Tag>
            <span className="text-xs text-slate-400">{dayjs(latestReport.report.createdAt).format('MM-DD HH:mm')}</span>
            <div className="flex-1" />
            <Button size="small" type="text" icon={<ReloadOutlined />} onClick={onRefresh} />
          </div>

          <div className="grid gap-3 lg:grid-cols-3 mb-4">
            {[
              {
                icon: <ExclamationCircleOutlined style={{ color: 'var(--amber-500)' }} />,
                label: '风险摘要',
                value: (() => {
                  const fullText = latestAnalysis?.riskSummary || latestReport.report.riskSummary || '';
                  return fullText || '暂无';
                })(),
              },
	              {
	                icon: <CodeOutlined style={{ color: 'var(--blue-500)' }} />,
	                label: '影响文件',
	                value: latestAffectedFiles.length ? (
	                  <div className="flex flex-wrap gap-1">
                    {visibleAffectedFiles.map((file) => {
                      const fileName = file.split('/').pop() || file;
                      return (
                        <Tooltip key={file} title={file}>
                          <Tag className="tag-file">{fileName}</Tag>
                        </Tooltip>
                      );
                    })}
                    {latestAffectedFiles.length > 3 ? (
                      <Tag className="tag-file">+{latestAffectedFiles.length - 3}</Tag>
                    ) : null}
                  </div>
	                ) : latestEvidenceFiles.length ? (
	                  <div className="flex flex-wrap gap-1">
	                    {latestEvidenceFiles.slice(0, 3).map((file) => {
	                      const fileName = file.split('/').pop() || file;
	                      return (
	                        <Tooltip key={file} title={`代码证据候选：${file}`}>
	                          <Tag className="tag-file">{fileName}</Tag>
	                        </Tooltip>
	                      );
	                    })}
	                    {latestEvidenceFiles.length > 3 ? (
	                      <Tag className="tag-file">+{latestEvidenceFiles.length - 3}</Tag>
	                    ) : null}
	                  </div>
	                ) : '待补充',
	              },
              {
                icon: <SafetyCertificateOutlined style={{ color: 'var(--green-500)' }} />,
                label: '验证建议',
                value: latestValidationSuggestions.length ? (
                  <div className="flex flex-col gap-0.5">
                    {latestValidationSuggestions.slice(0, 2).map((suggestion) => {
                      const display = suggestion.length > 60 ? suggestion.slice(0, 60) + '...' : suggestion;
                      return suggestion.length > 60 ? (
                        <Tooltip key={suggestion} title={suggestion}>
                          <span className="text-sm leading-5 ellipsis-single">{display}</span>
                        </Tooltip>
                      ) : (
                        <span key={suggestion} className="text-sm leading-5 ellipsis-single">{suggestion}</span>
                      );
                    })}
                    {latestValidationSuggestions.length > 2 ? (
                      <span className="text-xs text-slate-400">+{latestValidationSuggestions.length - 2} 条</span>
                    ) : null}
                  </div>
                ) : '暂无',
              },
            ].map((item) => (
              <div key={item.label} className="utility-card analysis-info-card">
                <div className="flex items-center gap-1.5 mb-1">
                  {item.icon}
                  <span className="text-xs font-semibold text-slate-400">{item.label}</span>
                </div>
                <div className="text-sm text-slate-700 leading-6 overflow-hidden">{item.value}</div>
              </div>
            ))}
          </div>

          <Collapse
            ghost
            items={[{
              key: 'latest-report',
              label: <span className="text-sm font-medium text-purple-700">展开完整分析</span>,
              children: (
                <div className="space-y-3 pt-1">
                  <Space wrap size={[6, 6]}>
                    <Tag color="blue">{latestTokenRecord?.provider || '未记录'}</Tag>
                    <Tag color="purple">{latestTokenRecord?.modelName || '-'}</Tag>
                    <Tag>{latestTokenRecord?.durationMs || 0}ms</Tag>
                    <Tag>Tokens {formatTokenNumber(latestTokenRecord?.totalTokens)}</Tag>
                    <Tag>{formatCost(latestTokenRecord?.estimatedCostUsd)}</Tag>
                    {latestTokenRecord && latestTokenRecord.attemptIndex > 0 ? <Tag color="gold">fallback</Tag> : null}
                  </Space>
                  <MarkdownContent content={latestReport.summaryMarkdown} />
                  {latestReport.rawPayload ? (
                    <Collapse
                      ghost
                      items={[{
                        key: 'raw',
                        label: '查看原始数据',
                        children: (
                          <pre className="overflow-x-auto bg-slate-950 p-3 text-xs leading-5 text-slate-100 rounded-xl">
                            <code>{latestReport.rawPayload}</code>
                          </pre>
                        ),
                      }]}
                    />
                  ) : null}
                </div>
              ),
            }]}
          />

          {historicalReports.length ? (
            <Collapse
              ghost
              className="mt-3"
              items={[{
                key: 'history-reports',
                label: `历史分析记录（${historicalReports.length}）`,
                children: (
                  <div className="space-y-3 pt-1">
                    {historicalReports.map(({ report, summaryMarkdown, rawPayload }) => {
                      const tokenRecord = getAnalysisTokenRecord(tokenRecords, report.id);
                      return (
                      <div key={report.id} className="border-b border-slate-100 pb-3 last:border-b-0">
                        <div className="flex items-center justify-between mb-1">
                          <Space wrap size={[6, 6]}>
                            <Tag color={getAgentTagColor(report.agentType)} className="tag-rounded">
                              {getAgentFullLabel(report.agentType)}
                            </Tag>
                            <Tag color={report.status === 'completed' ? 'success' : report.status === 'completed_fallback' ? 'warning' : 'processing'} className="tag-rounded">
                              {report.status === 'completed' ? '完成' : report.status === 'completed_fallback' ? '降级' : '分析中'}
                            </Tag>
                            {report.fallbackUsed ? <Tag color="gold" className="tag-rounded">fallback</Tag> : null}
                          </Space>
                          <span className="text-xs text-slate-400">{dayjs(report.createdAt).format('MM-DD HH:mm')}</span>
                        </div>
                        <div className="text-sm text-slate-600 leading-6 mb-1">{truncateText(summaryMarkdown, 180)}</div>
                        <Space wrap size={[6, 6]}>
                          <Tag color="blue" className="tag-rounded">{tokenRecord?.provider || '未记录'}</Tag>
                          <Tag color="purple" className="tag-rounded">{tokenRecord?.modelName || '-'}</Tag>
                          <Tag className="tag-rounded">{tokenRecord?.durationMs || 0}ms</Tag>
                          <Tag className="tag-rounded">Tokens {formatTokenNumber(tokenRecord?.totalTokens)}</Tag>
                        </Space>
                        {rawPayload ? (
                          <Collapse
                            ghost
                            className="mt-1"
                            items={[{
                              key: `raw-${report.id}`,
                              label: '查看原始数据',
                              children: (
                                <pre className="overflow-x-auto bg-slate-950 p-3 text-xs leading-5 text-slate-100 rounded-xl">
                                  <code>{rawPayload}</code>
                                </pre>
                              ),
                            }]}
                          />
                        ) : null}
                      </div>
                      );
                    })}
                  </div>
                ),
              }]}
            />
          ) : null}
        </div>
      ) : (
        <Empty description="暂无分析报告" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Button type="primary" onClick={onStartAnalysis} className="brand-button">
            开始分析
          </Button>
        </Empty>
      )}
    </div>
  );
}
