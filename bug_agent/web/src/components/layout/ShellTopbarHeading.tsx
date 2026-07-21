import type { ReactNode } from 'react';

interface ShellTopbarHeadingProps {
  title: ReactNode;
  leading?: ReactNode;
}

export default function ShellTopbarHeading({
  title,
  leading,
}: ShellTopbarHeadingProps) {
  return (
    <div className="shell-topbar-heading">
      {leading ? <div className="shell-topbar-heading__leading">{leading}</div> : null}
      <div>
        <div className="topbar__title">{title}</div>
      </div>
    </div>
  );
}
