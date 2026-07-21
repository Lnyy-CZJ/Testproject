import type { ReactNode } from 'react';

interface PageActionBarProps {
  children: ReactNode;
  compact?: boolean;
  testId?: string;
  inline?: boolean;
}

export default function PageActionBar({
  children,
  compact = false,
  testId,
  inline = false,
}: PageActionBarProps) {
  if (!children) {
    return null;
  }

  return (
    <div
      className={`page-action-bar${compact ? ' page-action-bar--compact' : ''}${inline ? ' page-action-bar--inline' : ''}`}
      data-testid={testId}
    >
      <div className="page-action-bar__group">{children}</div>
    </div>
  );
}
