import type { CSSProperties, ReactNode } from 'react';

interface ShellSidebarHeaderProps {
  action?: ReactNode;
  badge: ReactNode;
  badgeStyle?: CSSProperties;
  title: ReactNode;
  align?: 'center' | 'start';
  truncate?: boolean;
}

export default function ShellSidebarHeader({
  action,
  badge,
  badgeStyle,
  title,
  align = 'center',
  truncate = false,
}: ShellSidebarHeaderProps) {
  return (
    <div className={`shell-sidebar-header${align === 'start' ? ' shell-sidebar-header--start' : ''}`}>
      {action ? <div className="shell-sidebar-header__action">{action}</div> : null}
      <div className={`shell-sidebar-brand${align === 'start' ? ' shell-sidebar-brand--start' : ''}`}>
        <div className="shell-logo__badge" style={badgeStyle}>
          {badge}
        </div>
        <div className={`shell-sidebar-brand__text${truncate ? ' shell-sidebar-brand__text--truncate' : ''}`}>
          <div className="shell-logo__title">{title}</div>
        </div>
      </div>
    </div>
  );
}
