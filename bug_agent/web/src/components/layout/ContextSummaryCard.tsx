import type { ReactNode } from 'react';
import ContextSignalList from './ContextSignalList';

interface ContextSummaryCardProps {
  testId?: string;
  eyebrow?: ReactNode;
  title?: ReactNode;
  text?: ReactNode;
  signals?: Array<{
    key: string;
    label: ReactNode;
    tone?: 'purple' | 'cyan' | 'amber' | 'green' | 'rose' | 'slate';
  }>;
  subtle?: boolean;
}

export default function ContextSummaryCard({
  testId,
  eyebrow,
  title,
  text,
  signals = [],
  subtle = false,
}: ContextSummaryCardProps) {
  return (
    <div
      className={`shell-context-card${subtle ? ' shell-context-card--subtle' : ''}`}
      data-testid={testId}
    >
      {eyebrow ? <div className="shell-context-card__eyebrow">{eyebrow}</div> : null}
      {title ? <div className="shell-context-card__title">{title}</div> : null}
      {text ? <div className="shell-context-card__text">{text}</div> : null}
      {signals.length > 0 ? (
        <div className="shell-context-card__signals">
          <ContextSignalList items={signals} compact={subtle} />
        </div>
      ) : null}
    </div>
  );
}
