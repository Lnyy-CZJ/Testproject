import type { ReactNode } from 'react';

interface ContextSignalItem {
  key: string;
  label: ReactNode;
  tone?: 'purple' | 'cyan' | 'amber' | 'green' | 'rose' | 'slate';
}

interface ContextSignalListProps {
  items: ContextSignalItem[];
  compact?: boolean;
}

export default function ContextSignalList({ items, compact = false }: ContextSignalListProps) {
  if (items.length === 0) return null;

  return (
    <div className={`context-signal-list${compact ? ' context-signal-list--compact' : ''}`}>
      {items.map((item) => (
        <span key={item.key} className={`context-signal context-signal--${item.tone || 'slate'}`}>
          {item.label}
        </span>
      ))}
    </div>
  );
}
