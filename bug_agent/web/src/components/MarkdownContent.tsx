import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useMemo } from 'react';

interface MarkdownContentProps {
  content?: string | null;
  emptyText?: string;
  className?: string;
}

export default function MarkdownContent({
  content,
  emptyText = '暂无内容',
  className = '',
}: MarkdownContentProps) {
  const normalized = content?.trim();

  const components: Components = useMemo(() => ({
    h1: ({ children }) => <h1 className="mb-4 text-2xl font-semibold tracking-tight text-slate-950">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-4 mt-8 text-xl font-semibold tracking-tight text-slate-950 first:mt-0">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-3 mt-6 text-[17px] font-semibold tracking-tight text-slate-900 first:mt-0">{children}</h3>,
    p: ({ children }) => <p className="mb-4 text-[15px] leading-8 text-slate-700 last:mb-0">{children}</p>,
    ul: ({ children }) => <ul className="mb-4 list-disc space-y-2 pl-6">{children}</ul>,
    ol: ({ children }) => <ol className="mb-4 list-decimal space-y-2 pl-6">{children}</ol>,
    li: ({ children }) => <li className="text-[15px] leading-8 text-slate-700">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className="my-5 rounded-r-xl border-l-4 border-slate-200 bg-slate-50 px-4 py-3 text-[15px] leading-8 text-slate-600">
        {children}
      </blockquote>
    ),
    a: ({ href, children }) => {
      if (href && /^\s*javascript:/i.test(href)) {
        return <span className="text-slate-700">{children}</span>;
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-sky-600 hover:text-sky-500 underline"
        >
          {children}
        </a>
      );
    },
    code: ({ className: codeClassName, children, ...props }) => {
      const inline = !String(codeClassName || '').includes('language-');
      if (inline) {
        return (
          <code
            className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[13px] text-slate-700"
            {...props}
          >
            {children}
          </code>
        );
      }

      return (
        <code className="block overflow-x-auto p-5 text-[13px] leading-7 text-slate-100" {...props}>
          {children}
        </code>
      );
    },
    pre: ({ children }) => (
      <pre className="mb-5 overflow-x-auto rounded-2xl bg-slate-900 shadow-inner">{children}</pre>
    ),
    table: ({ children }) => (
      <div className="mb-4 overflow-x-auto">
        <table className="min-w-full border-collapse overflow-hidden rounded-xl border border-slate-200 text-sm">
          {children}
        </table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
    th: ({ children }) => (
      <th className="border border-slate-200 px-3 py-2 text-left font-medium text-slate-700">{children}</th>
    ),
    td: ({ children }) => <td className="border border-slate-200 px-3 py-2 text-slate-600">{children}</td>,
    hr: () => <hr className="my-6 border-slate-200" />,
  }), []);

  if (!normalized) {
    return <div className={`text-sm text-slate-400 ${className}`}>{emptyText}</div>;
  }

  return (
    <div className={`markdown-content text-[15px] leading-8 tracking-[0.01em] text-slate-700 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={components}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
