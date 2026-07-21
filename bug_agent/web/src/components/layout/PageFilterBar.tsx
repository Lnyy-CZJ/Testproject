import type { ReactNode } from 'react';

interface PageFilterBarProps {
  filters: ReactNode;
  actions?: ReactNode;
  result?: ReactNode;
  compact?: boolean;
  testId?: string;
  className?: string;
}

export default function PageFilterBar({
  filters,
  actions,
  result,
  compact = false,
  testId,
  className,
}: PageFilterBarProps) {
  return (
    <div
      className={`action-rail page-filter-bar${compact ? ' action-rail--compact' : ''}${className ? ` ${className}` : ''}`}
      data-testid={testId}
    >
      <div className="action-rail__group page-filter-bar__filters">
        {filters}
        {actions}
      </div>
      {result ? (
        <div className="action-rail__group page-filter-bar__tail">
          <div className="page-filter-bar__result">{result}</div>
        </div>
      ) : null}
    </div>
  );
}
