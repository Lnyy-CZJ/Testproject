import { useMemo } from 'react';
import { Typography } from 'antd';

interface CodeChange {
  filePath?: string;
  description?: string;
  diff?: string;
  oldContent?: string;
  newContent?: string;
}

interface DiffViewProps {
  codeChanges: CodeChange[];
}

export default function DiffView({ codeChanges }: DiffViewProps) {
  const parsedChanges = useMemo(() => {
    return codeChanges.map((change) => {
      let diffLines: { type: 'add' | 'remove' | 'context' | 'header'; content: string }[] = [];

      if (change.diff) {
        const lines = change.diff.split('\n');
        for (const line of lines) {
          if (line.startsWith('+++') || line.startsWith('---')) {
            diffLines.push({ type: 'header', content: line });
          } else if (line.startsWith('+')) {
            diffLines.push({ type: 'add', content: line.substring(1) });
          } else if (line.startsWith('-')) {
            diffLines.push({ type: 'remove', content: line.substring(1) });
          } else if (line.startsWith('@@')) {
            diffLines.push({ type: 'header', content: line });
          } else {
            diffLines.push({ type: 'context', content: line.startsWith(' ') ? line.substring(1) : line });
          }
        }
      } else if (change.oldContent && change.newContent) {
        const oldLines = change.oldContent.split('\n');
        const newLines = change.newContent.split('\n');
        const maxLen = Math.max(oldLines.length, newLines.length);
        for (let i = 0; i < maxLen; i++) {
          const oldLine = oldLines[i];
          const newLine = newLines[i];
          if (oldLine === undefined && newLine !== undefined) {
            diffLines.push({ type: 'add', content: newLine });
          } else if (oldLine !== undefined && newLine === undefined) {
            diffLines.push({ type: 'remove', content: oldLine });
          } else if (oldLine !== newLine) {
            diffLines.push({ type: 'remove', content: oldLine || '' });
            diffLines.push({ type: 'add', content: newLine || '' });
          } else {
            diffLines.push({ type: 'context', content: oldLine });
          }
        }
      }

      return { ...change, diffLines };
    });
  }, [codeChanges]);

  if (!codeChanges.length) {
    return <Typography.Text type="secondary">无代码变更记录</Typography.Text>;
  }

  return (
    <div className="space-y-4">
      {parsedChanges.map((change, idx) => (
        <div key={change.filePath || `change-${idx}`} style={{ borderRadius: 12, border: '1px solid #e2e8f0', overflow: 'hidden' }}>
          <div style={{
            padding: '8px 14px',
            background: '#f8fafc',
            borderBottom: '1px solid #e2e8f0',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <Typography.Text strong style={{ fontSize: 13, fontFamily: 'monospace' }}>
              {change.filePath || `变更 ${idx + 1}`}
            </Typography.Text>
            {change.description ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{change.description}</Typography.Text>
            ) : null}
          </div>
          <div style={{
            padding: 12,
            background: '#1e293b',
            overflowX: 'auto',
            fontFamily: 'Geist Mono, SFMono-Regular, Menlo, monospace',
            fontSize: 12,
            lineHeight: 1.7,
          }}>
            {change.diffLines.map((line, lineIdx) => (
              <div
                key={`${change.filePath || idx}-${lineIdx}`}
                style={{
                  padding: '0 8px',
                  background:
                    line.type === 'add' ? 'rgba(34,197,94,0.12)' :
                    line.type === 'remove' ? 'rgba(239,68,68,0.12)' :
                    line.type === 'header' ? 'rgba(139,92,246,0.12)' :
                    'transparent',
                  color:
                    line.type === 'add' ? '#4ade80' :
                    line.type === 'remove' ? '#f87171' :
                    line.type === 'header' ? '#c084fc' :
                    '#94a3b8',
                  whiteSpace: 'pre',
                }}
              >
                <span style={{ display: 'inline-block', width: 20, color: '#475569', userSelect: 'none' }}>
                  {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
                </span>
                {line.content}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
