import dayjs from 'dayjs';
import type { CSSProperties } from 'react';
import type { Iteration } from '../../types';
import ContextSignalList from './ContextSignalList';

interface IterationSummaryListProps {
  iterations: Iteration[];
  currentIterationId?: number | null;
  testId?: string;
  compact?: boolean;
  getProgress: (iteration: Iteration) => number;
  onSelect: (iteration: Iteration) => void;
}

export default function IterationSummaryList({
  iterations,
  currentIterationId,
  testId = 'active-iteration-list',
  compact = false,
  getProgress,
  onSelect,
}: IterationSummaryListProps) {
  if (iterations.length === 0) return null;

  return (
    <div className={`iteration-summary-list${compact ? ' iteration-summary-list--compact' : ''}`} data-testid={testId}>
      {iterations.map((iteration) => {
        const isCurrent = iteration.id === currentIterationId;

        return (
          <button
            key={iteration.id}
            type="button"
            className={`iteration-summary-card${compact ? ' iteration-summary-card--compact' : ''}${isCurrent ? ' iteration-summary-card--current' : ''}`}
            data-testid="iteration-summary-card"
            onClick={() => onSelect(iteration)}
            style={{ '--iteration-progress': `${getProgress(iteration)}%` } as CSSProperties}
          >
            <div className="iteration-summary-card__header">
              <span className="iteration-summary-card__title">{iteration.name}</span>
              {isCurrent ? (
                compact ? (
                  <span className="iteration-summary-card__current">当前</span>
                ) : (
                  <ContextSignalList
                    compact
                    items={[{ key: `${iteration.id}-current`, label: '当前', tone: 'purple' }]}
                  />
                )
              ) : null}
            </div>
            <div className="iteration-summary-card__range">
              {dayjs(iteration.startDate).format('MM/DD')} - {dayjs(iteration.endDate).format('MM/DD')}
            </div>
          </button>
        );
      })}
    </div>
  );
}
