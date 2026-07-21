import { Tag, Empty, Space, Collapse } from 'antd';
import type { FixTask, FixTaskGroup } from '../../../types';
import type { TokenUsageRecord } from '../../../api/types';
import { fixTaskStatusLabels, fixTaskStatusColors } from '../../../constants/defect';
import { buildFixTaskMarkdown, truncateText, stringifyPrettyJson, parseStringArray } from '../utils';
import MarkdownContent from '../../../components/MarkdownContent';
import DiffView from '../../../components/DiffView';
import '../defect-detail.css';

interface DefectFixTaskPanelProps {
  fixTaskGroups?: FixTaskGroup[];
  fixTasks: FixTask[];
  latestFixTask: FixTask | undefined;
  historicalFixTasks: FixTask[];
  latestFixTaskMarkdown: string;
  latestFixTaskCodeChanges: Array<{ filePath?: string; description?: string; diff?: string; oldContent?: string; newContent?: string; content?: string }>;
  latestFixTaskValidation: string[];
  latestFixTaskRaw: string;
  tokenRecords?: TokenUsageRecord[];
}

const formatTokenNumber = (value?: number) => (value || 0).toLocaleString('en-US');
const formatCost = (value?: number) => `$${(value || 0).toFixed(4)}`;

function summarizeFixTaskTokens(records: TokenUsageRecord[], taskId?: number) {
  const matched = records.filter((record) => record.consumptionType === 'fix' && record.sourceId === taskId);
  const display = matched.find((record) => record.isFinalAttempt) || matched[matched.length - 1];
  return {
    provider: display?.provider,
    modelName: display?.modelName,
    durationMs: matched.reduce((sum, record) => sum + (record.durationMs || 0), 0),
    totalTokens: matched.reduce((sum, record) => sum + (record.totalTokens || 0), 0),
    estimatedCostUsd: matched.reduce((sum, record) => sum + (record.estimatedCostUsd || 0), 0),
    fallbackUsed: matched.some((record) => record.attemptIndex > 0),
  };
}

export default function DefectFixTaskPanel({
  fixTaskGroups = [],
  fixTasks,
  latestFixTask,
  historicalFixTasks,
  latestFixTaskMarkdown,
  latestFixTaskCodeChanges,
  latestFixTaskValidation,
  latestFixTaskRaw,
  tokenRecords = [],
}: DefectFixTaskPanelProps) {
  if (fixTasks.length === 0 && fixTaskGroups.length === 0) {
    return (
      <div className="tab-content">
        <Empty description="暂无修复任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <div className="tab-content">
      {fixTaskGroups.length ? (
        <div className="mb-4 pb-4 border-b border-slate-100">
          <div className="text-sm font-semibold text-slate-900 mb-3">修复任务组</div>
          <div className="space-y-3">
            {fixTaskGroups.map((group) => (
              <div key={group.id} className="utility-card">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="text-sm font-semibold text-slate-900">{group.taskCode}</span>
                    <span className="text-xs text-slate-400 ml-2">{group.targetBranch || '-'}</span>
                  </div>
                  <Tag color={fixTaskStatusColors[group.status]} className="tag-rounded">
                    {fixTaskStatusLabels[group.status] || group.status}
                  </Tag>
                </div>
                <div className="space-y-2">
                  {(group.units || []).map((unit) => {
                    const tokenSummary = summarizeFixTaskTokens(tokenRecords, unit.id);
                    return (
                      <div key={unit.id} className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2 first:border-t-0 first:pt-0">
                        <Tag color="blue" className="tag-rounded">{unit.agentType || 'agent'}</Tag>
                        <Tag color="cyan" className="tag-rounded">{unit.projectRepo?.name || `repo#${unit.projectRepoId || '-'}`}</Tag>
                        <span className="text-xs font-mono text-slate-500">{unit.taskCode}</span>
                        <Tag color={fixTaskStatusColors[unit.status]} className="tag-rounded">
                          {fixTaskStatusLabels[unit.status] || unit.status}
                        </Tag>
                        <span className="text-xs text-slate-400">{unit.fixBranch || unit.targetBranch || '-'}</span>
                        {unit.prUrl ? <a className="text-xs text-blue-600" href={unit.prUrl} target="_blank" rel="noreferrer">PR</a> : null}
                        <span className="text-xs text-slate-500">Tokens {formatTokenNumber(tokenSummary.totalTokens)}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {latestFixTask ? (
        (() => {
          const latestTokenSummary = summarizeFixTaskTokens(tokenRecords, latestFixTask.id);
          return (
        <div className="mb-4 pb-4 border-b border-slate-100">
          <div className="flex items-center justify-between mb-2">
            <div>
              <span className="text-sm font-semibold text-slate-900">最新修复任务</span>
              <span className="text-xs font-mono text-slate-400 ml-2">{latestFixTask.taskCode}</span>
              <span className="text-xs text-slate-400 ml-2">{latestFixTask.fixBranch || latestFixTask.targetBranch || '-'}</span>
            </div>
            <Tag color={fixTaskStatusColors[latestFixTask.status]} className="tag-rounded">
              {fixTaskStatusLabels[latestFixTask.status]}
            </Tag>
          </div>

          <Space wrap size={[6, 6]} className="mb-3">
            <Tag color="blue" className="tag-rounded">{latestTokenSummary.provider || '未记录'}</Tag>
            <Tag color="purple" className="tag-rounded">{latestTokenSummary.modelName || '-'}</Tag>
            <Tag className="tag-rounded">{latestTokenSummary.durationMs || 0}ms</Tag>
            <Tag className="tag-rounded">Tokens {formatTokenNumber(latestTokenSummary.totalTokens)}</Tag>
            <Tag className="tag-rounded">{formatCost(latestTokenSummary.estimatedCostUsd)}</Tag>
            {latestTokenSummary.fallbackUsed ? <Tag color="gold" className="tag-rounded">fallback</Tag> : null}
          </Space>

          <div className="grid gap-3 lg:grid-cols-2 mb-3">
            <div className="utility-card fix-info-card">
              <div className="text-xs font-semibold text-slate-400 mb-1">风险摘要</div>
              <div className="text-sm text-slate-700 leading-6">
                {truncateText(latestFixTask.aiRiskSummary || latestFixTaskMarkdown, 96) || '暂无'}
              </div>
            </div>
            <div className="utility-card fix-info-card">
              <div className="text-xs font-semibold text-slate-400 mb-1">验证建议</div>
              <div className="text-sm text-slate-700 leading-6">
                {latestFixTaskValidation.length ? latestFixTaskValidation.slice(0, 2).join('；') : '暂无'}
              </div>
            </div>
          </div>

          <Collapse
            ghost
            items={[{
              key: 'latest-fix-task',
              label: <span className="text-sm font-medium text-purple-700">展开任务详情</span>,
              children: (
                <div className="space-y-3 pt-1">
                  <MarkdownContent content={latestFixTaskMarkdown} emptyText="暂无风险摘要" />
                  {latestFixTaskCodeChanges.length > 0 && (
                    <Collapse
                      ghost
                      items={[{
                        key: 'diff',
                        label: `代码变更（${latestFixTaskCodeChanges.length} 个文件）`,
                        children: <DiffView codeChanges={latestFixTaskCodeChanges} />,
                      }]}
                    />
                  )}
                  {latestFixTaskRaw ? (
                    <Collapse
                      ghost
                      items={[{
                        key: 'raw',
                        label: '查看原始数据',
                        children: (
                          <pre className="overflow-x-auto bg-slate-950 p-3 text-xs leading-5 text-slate-100 rounded-xl">
                            <code>{latestFixTaskRaw}</code>
                          </pre>
                        ),
                      }]}
                    />
                  ) : null}
                </div>
              ),
            }]}
          />
        </div>
          );
        })()
      ) : null}

      {historicalFixTasks.length ? (
        <Collapse
          ghost
          items={[{
            key: 'history-fix-tasks',
            label: `历史修复任务（${historicalFixTasks.length}）`,
            children: (
              <div className="space-y-3 pt-1">
                {historicalFixTasks.map((task) => {
                  const tokenSummary = summarizeFixTaskTokens(tokenRecords, task.id);
                  const taskMarkdown = buildFixTaskMarkdown(task);
                  const rawResult = stringifyPrettyJson(task.result || task.plan);
                  const taskCodeChanges = (() => {
                    if (!task.result) return [];
                    try {
                      const parsed = JSON.parse(task.result);
                      return parsed.codeChanges || parsed.code_changes || [];
                    } catch { return []; }
                  })();
                  const taskValidation = parseStringArray(task.aiValidationSuggestions);
                  return (
                    <div key={task.id} className="border-b border-slate-100 pb-3 last:border-b-0">
                      <div className="flex items-center justify-between mb-1">
                        <div>
                          <span className="text-sm font-medium text-slate-900">{task.taskCode}</span>
                          <Tag color={task.source === 'manual' ? 'green' : 'blue'} className="tag-ml">{task.source === 'manual' ? '手动' : '自动'}</Tag>
                          {task.prStatus && <Tag color={task.prStatus === 'merged' ? 'green' : task.prStatus === 'rejected' ? 'red' : task.prStatus === 'open' ? 'orange' : 'default'} className="tag-rounded">{task.prStatus === 'open' ? '待审核' : task.prStatus === 'merged' ? '已合并' : task.prStatus === 'rejected' ? '已拒绝' : task.prStatus === 'closed' ? '已关闭' : task.prStatus}</Tag>}
                          <span className="text-xs font-mono text-slate-400 ml-2">{task.fixBranch || task.targetBranch || '-'}</span>
                        </div>
                        <Tag color={fixTaskStatusColors[task.status]} className="tag-rounded">{fixTaskStatusLabels[task.status]}</Tag>
                      </div>
                      <Collapse
                        ghost
                        items={[{
                          key: `history-task-${task.id}`,
                          label: <span className="text-sm text-slate-600">{truncateText(taskMarkdown || task.aiLastError || rawResult, 150) || '暂无摘要'}</span>,
                          children: (
                            <div className="space-y-3">
                              <MarkdownContent content={taskMarkdown} emptyText="暂无详情" />
                              {taskCodeChanges.length > 0 && (
                                <Collapse
                                  ghost
                                  items={[{
                                    key: `history-code-${task.id}`,
                                    label: `代码变更（${taskCodeChanges.length} 个文件）`,
                                    children: <DiffView codeChanges={taskCodeChanges} />,
                                  }]}
                                />
                              )}
                              {taskValidation.length > 0 && (
                                <div className="text-sm text-slate-600">
                                  <span className="font-medium">验证建议：</span>{taskValidation.join('；')}
                                </div>
                              )}
                              {rawResult && (
                                <Collapse
                                  ghost
                                  items={[{
                                    key: `history-raw-${task.id}`,
                                    label: '原始结果',
                                    children: (
                                      <pre className="text-xs bg-slate-50 p-3 rounded overflow-auto max-h-64">
                                        <code>{rawResult}</code>
                                      </pre>
                                    ),
                                  }]}
                                />
                              )}
                            </div>
                          ),
                        }]}
                      />
                      <Space wrap size={[6, 6]}>
                        <Tag color="blue" className="tag-rounded">{tokenSummary.provider || '未记录'}</Tag>
                        <Tag color="purple" className="tag-rounded">{tokenSummary.modelName || '-'}</Tag>
                        <Tag className="tag-rounded">{tokenSummary.durationMs || 0}ms</Tag>
                        <Tag className="tag-rounded">Tokens {formatTokenNumber(tokenSummary.totalTokens)}</Tag>
                      </Space>
                    </div>
                  );
                })}
              </div>
            ),
          }]}
        />
      ) : null}
    </div>
  );
}
