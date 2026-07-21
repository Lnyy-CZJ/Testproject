import type { ReactNode } from 'react';

interface MetricItem {
  key: string;
  label: ReactNode;
  value: ReactNode;
  icon?: ReactNode;
  tone?: 'purple' | 'cyan' | 'amber' | 'green' | 'rose' | 'slate';
}

interface MetricRailProps {
  items: MetricItem[];
  compact?: boolean;
}

export default function MetricRail({ items, compact = false }: MetricRailProps) {
  const visibleItems = items.slice(0, 5);

  return (
    <div className={`metric-rail${compact ? ' metric-rail--compact' : ''}`}>
      {visibleItems.map((item) => (
        <div key={item.key} className={`metric-pill metric-pill--${item.tone || 'slate'}`}>
          {item.icon ? <span className="metric-pill__icon">{item.icon}</span> : null}
          <span className="metric-pill__label">{item.label}</span>
          <strong className="metric-pill__value">{item.value}</strong>
        </div>
      ))}
    </div>
  );
}
