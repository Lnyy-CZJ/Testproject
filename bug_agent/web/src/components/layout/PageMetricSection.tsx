import type { ReactNode } from 'react';
import MetricRail from './MetricRail';
import PageActionBar from './PageActionBar';

type MetricTone = 'purple' | 'cyan' | 'amber' | 'green' | 'rose' | 'slate';

interface MetricItem {
  key: string;
  label: ReactNode;
  value: ReactNode;
  icon?: ReactNode;
  tone?: MetricTone;
}

interface PageMetricSectionProps {
  items: MetricItem[];
  actions?: ReactNode;
  compact?: boolean;
}

export default function PageMetricSection({
  items,
  actions,
  compact = false,
}: PageMetricSectionProps) {
  const actionClassName = `metric-actions metric-actions--equal${compact ? ' metric-actions--compact' : ''}`;

  return (
    <div className="metric-action-row">
      <MetricRail items={items} compact={compact} />
      {actions ? (
        <PageActionBar inline compact={compact}>
          <div className={actionClassName}>{actions}</div>
        </PageActionBar>
      ) : null}
    </div>
  );
}
