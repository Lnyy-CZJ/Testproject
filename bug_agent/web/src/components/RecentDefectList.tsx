import type { ReactNode } from 'react';
import { BugOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Defect } from '../types';
import { severityLabels, statusLabels } from '../constants/defect';

const severityLabelMap = severityLabels;
const statusLabelMap = statusLabels;

function getSeverityTone(severity: string) {
  if (severity === 'fatal') return 'fatal';
  if (severity === 'major') return 'major';
  if (severity === 'minor') return 'minor';
  if (severity === 'suggest') return 'suggest';
  return 'normal';
}

function getStatusTone(status: string) {
  if (['completed', 'fixed'].includes(status)) return 'positive';
  if (['fixing', 'analyzing'].includes(status)) return 'active';
  if (['rejected', 'suspended'].includes(status)) return 'muted';
  return 'pending';
}

interface RecentDefectListProps {
  defects: Defect[];
  testId?: string;
  emptyText?: ReactNode;
  emptyAction?: ReactNode;
  onSelect?: (defect: Defect) => void;
}

export default function RecentDefectList({
  defects,
  testId = 'recent-defect-list',
  emptyText = '暂无缺陷记录',
  emptyAction,
  onSelect,
}: RecentDefectListProps) {
  if (defects.length === 0) {
    return (
      <div className="recent-defect-list recent-defect-list--empty" data-testid={testId}>
        <BugOutlined className="recent-defect-list__empty-icon" />
        <div className="recent-defect-list__empty-text">{emptyText}</div>
        {emptyAction ? <div className="recent-defect-list__empty-action">{emptyAction}</div> : null}
      </div>
    );
  }

  return (
    <div className="recent-defect-list" data-testid={testId}>
      {defects.map((defect) => {
        const assigneeName = defect.assignee?.nickname || defect.assignee?.username;
        const content = (
          <>
            <div className="recent-defect-row__main">
              <div className="recent-defect-row__title-line">
                <span className={`recent-defect-row__severity recent-defect-row__severity--${getSeverityTone(defect.severity)}`}>
                  {severityLabelMap[defect.severity] || defect.severity}
                </span>
                <span className="recent-defect-row__title">{defect.title}</span>
              </div>
              <div className="recent-defect-row__meta">
                <span className="recent-defect-row__meta-item">{defect.code}</span>
                <span className="recent-defect-row__meta-separator" aria-hidden="true" />
                <span className={`recent-defect-row__status recent-defect-row__status--${getStatusTone(defect.status)}`}>
                  {statusLabelMap[defect.status] || defect.status}
                </span>
                {assigneeName ? (
                  <>
                    <span className="recent-defect-row__meta-separator" aria-hidden="true" />
                    <span className="recent-defect-row__meta-item">{assigneeName}</span>
                  </>
                ) : null}
              </div>
            </div>
            <span className="recent-defect-row__time">{dayjs(defect.createdAt).format('MM-DD HH:mm')}</span>
          </>
        );

        if (onSelect) {
          return (
            <button
              key={defect.id}
              type="button"
              className="recent-defect-row"
              data-testid="recent-defect-row"
              onClick={() => onSelect(defect)}
            >
              {content}
            </button>
          );
        }

        return (
          <div key={defect.id} className="recent-defect-row" data-testid="recent-defect-row">
            {content}
          </div>
        );
      })}
    </div>
  );
}
