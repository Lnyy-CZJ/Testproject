import type { ReactNode } from 'react';

interface PageContentProps {
  children: ReactNode;
  className?: string;
}

export default function PageContent({ children, className }: PageContentProps) {
  return (
    <div className={`page-content ${className || ''}`}>
      {children}
    </div>
  );
}
