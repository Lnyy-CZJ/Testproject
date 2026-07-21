import type { ReactNode } from 'react';

interface AppShellProps {
  testId?: string;
  sidebar: ReactNode;
  topbar: ReactNode;
  children: ReactNode;
  shellClassName?: string;
  sidebarClassName?: string;
  mainClassName?: string;
  contentClassName?: string;
}

const joinClassNames = (...values: Array<string | undefined>) => values.filter(Boolean).join(' ');

export default function AppShell({
  testId,
  sidebar,
  topbar,
  children,
  shellClassName,
  sidebarClassName,
  mainClassName,
  contentClassName,
}: AppShellProps) {
  return (
    <div data-testid={testId} className={joinClassNames('app-shell', shellClassName)}>
      <aside className={joinClassNames('app-shell__sidebar', sidebarClassName)}>{sidebar}</aside>
      <div className={joinClassNames('app-shell__main', mainClassName)}>
        <header className="app-shell__topbar">{topbar}</header>
        <main className={joinClassNames('app-shell__content', contentClassName)}>{children}</main>
      </div>
    </div>
  );
}
