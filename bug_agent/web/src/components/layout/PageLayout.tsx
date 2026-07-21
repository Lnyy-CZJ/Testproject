import type { ReactNode } from 'react';

interface PageLayoutProps {
  children: ReactNode;
  className?: string;
}

export default function PageLayout({ children, className }: PageLayoutProps) {
  return (
    <div className={`page-layout${className ? ` ${className}` : ''}`}>
      {children}
    </div>
  );
}
