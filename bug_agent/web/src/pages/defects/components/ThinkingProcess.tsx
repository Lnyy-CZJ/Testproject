import { useState, useRef, useEffect, useCallback } from 'react';
import { Collapse, Spin } from 'antd';
import {
  SearchOutlined,
  BulbOutlined,
  SafetyCertificateOutlined,
  LoadingOutlined,
  CheckCircleFilled,
  ToolOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type { ThinkingStep } from '../../../api/types';
import '../defect-detail.css';

interface ThinkingProcessProps {
  steps: ThinkingStep[];
  currentPhase: string;
  analyzing: boolean;
  error: string | null;
}

const PHASES = [
  { key: 'retrieval', label: '检索', icon: SearchOutlined, color: 'var(--blue-500)' },
  { key: 'analysis', label: '分析', icon: BulbOutlined, color: 'var(--purple-500)' },
  { key: 'validation', label: '验证', icon: SafetyCertificateOutlined, color: 'var(--green-500)' },
];

const PHASE_ORDER: Record<string, number> = { retrieval: 0, analysis: 1, validation: 2 };

function getPhaseIcon(phase?: string) {
  switch (phase) {
    case 'retrieval': return <SearchOutlined style={{ color: 'var(--blue-500)' }} />;
    case 'analysis': return <BulbOutlined style={{ color: 'var(--purple-500)' }} />;
    case 'validation': return <SafetyCertificateOutlined style={{ color: 'var(--green-500)' }} />;
    default: return <LoadingOutlined spin style={{ color: 'var(--purple-400)' }} />;
  }
}

function truncate(str: string, max: number) {
  if (!str) return '';
  return str.length > max ? str.slice(0, max) + '…' : str;
}

function relativeTime(ts: number) {
  const diff = Date.now() - ts;
  if (diff < 1000) return '刚刚';
  if (diff < 60000) return `${Math.floor(diff / 1000)}s`;
  return `${Math.floor(diff / 60000)}m`;
}

function StepTimeline({ steps }: { steps: ThinkingStep[] }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [steps.length]);

  const toggle = useCallback((id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  if (!steps.length) return null;

  return (
    <div ref={containerRef} className="thinking-steps-container">
      {steps.map((step, idx) => {
        const isLast = idx === steps.length - 1;
        const isExpanded = expanded[step.id];

        if (step.type === 'tool_call' || step.type === 'tool_result') {
          const isCall = step.type === 'tool_call';
          const content = isCall ? step.toolInput : step.toolOutput;
          const displayContent = truncate(content || '', 200);

          return (
            <div key={step.id} className="thinking-step-item thinking-step-fade-in">
              <div className="thinking-step-line">
                <div className="thinking-step-dot" style={{ background: isCall ? 'var(--purple-400)' : 'var(--green-400)' }}>
                  <ToolOutlined style={{ fontSize: 10, color: '#fff' }} />
                </div>
                {!isLast && <div className="thinking-step-connector" />}
              </div>
              <div className="thinking-step-body" style={{ flex: 1, minWidth: 0 }}>
                {isCall ? (
                  <div
                    className="thinking-tool-card"
                    onClick={() => toggle(step.id)}
                  >
                    <div className="thinking-tool-header">
                      <span className="thinking-tool-name">🔧 {step.toolName || 'tool'}</span>
                      <span className="thinking-tool-toggle">{isExpanded ? '收起' : '展开'}</span>
                    </div>
                    <div className="thinking-tool-content">
                      <pre className="thinking-tool-code">{isExpanded ? (content || '') : displayContent}</pre>
                    </div>
                  </div>
                ) : (
                  <div
                    className="thinking-tool-card thinking-tool-result"
                    onClick={() => toggle(step.id)}
                  >
                    <div className="thinking-tool-header">
                      <span className="thinking-tool-name">📋 输出结果</span>
                      <span className="thinking-tool-toggle">{isExpanded ? '收起' : '展开'}</span>
                    </div>
                    <div className="thinking-tool-content">
                      <pre className="thinking-tool-code">{isExpanded ? (content || '') : displayContent}</pre>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        }

        if (step.type === 'thinking' || step.type === 'partial') {
          return (
            <div key={step.id} className="thinking-step-item thinking-step-fade-in">
              <div className="thinking-step-line">
                <div className="thinking-step-dot" style={{ background: 'var(--purple-100)', border: '2px solid var(--purple-400)' }} />
                {!isLast && <div className="thinking-step-connector" />}
              </div>
              <div className="thinking-step-body thinking-reasoning-block">
                <div className="thinking-reasoning-text">{step.content}</div>
                <span className="thinking-step-time">{relativeTime(step.timestamp)}</span>
              </div>
            </div>
          );
        }

        if (step.type === 'error') {
          return (
            <div key={step.id} className="thinking-step-item thinking-step-fade-in">
              <div className="thinking-step-line">
                <div className="thinking-step-dot" style={{ background: '#ef4444' }}>
                  <WarningOutlined style={{ fontSize: 10, color: '#fff' }} />
                </div>
                {!isLast && <div className="thinking-step-connector" />}
              </div>
              <div className="thinking-step-body thinking-error-block">
                {step.content}
              </div>
            </div>
          );
        }

        return (
          <div key={step.id} className="thinking-step-item thinking-step-fade-in">
            <div className="thinking-step-line">
              {getPhaseIcon(step.phase)}
              {!isLast && <div className="thinking-step-connector" />}
            </div>
            <div className="thinking-step-body">
              <span className="text-sm text-slate-700">{step.content}</span>
              <span className="thinking-step-time">{relativeTime(step.timestamp)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProgressIndicator({ currentPhase }: { currentPhase: string }) {
  const currentIdx = PHASE_ORDER[currentPhase] ?? -1;

  return (
    <div className="thinking-progress-bar">
      {PHASES.map((phase, idx) => {
        const isActive = idx === currentIdx;
        const isPast = idx < currentIdx;
        const isFuture = idx > currentIdx;
        const Icon = phase.icon;

        return (
          <div key={phase.key} className="thinking-progress-phase">
            <div className="thinking-progress-node-wrap">
              <div
                className="thinking-progress-node"
                style={{
                  background: isPast || isActive ? phase.color : 'var(--color-surface-muted)',
                  borderColor: isPast || isActive ? phase.color : 'var(--color-border-default)',
                  opacity: isFuture ? 0.4 : 1,
                }}
              >
                <Icon style={{ fontSize: 14, color: isPast || isActive ? '#fff' : 'var(--color-text-tertiary)' }} />
              </div>
              {isActive && <div className="thinking-progress-pulse" style={{ borderColor: phase.color }} />}
            </div>
            <span
              className="thinking-progress-label"
              style={{
                color: isActive ? phase.color : isPast ? 'var(--color-text-secondary)' : 'var(--color-text-quaternary)',
                fontWeight: isActive ? 600 : 400,
              }}
            >
              {phase.label}
            </span>
            {idx < PHASES.length - 1 && (
              <div
                className="thinking-progress-line"
                style={{
                  background: isPast ? phase.color : 'var(--color-border-default)',
                  opacity: isFuture ? 0.3 : 1,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function ThinkingProcess({ steps, currentPhase, analyzing, error }: ThinkingProcessProps) {
  const isComplete = steps.length > 0 && steps[steps.length - 1].type === 'final';

  return (
    <div className="thinking-process-root">
      <ProgressIndicator currentPhase={currentPhase} />

      {error && (
        <div className="thinking-error-banner">
          <WarningOutlined style={{ color: '#ef4444' }} />
          <span>{error}</span>
        </div>
      )}

      <StepTimeline steps={steps} />

      {isComplete && (
        <div className="thinking-complete-banner thinking-step-fade-in">
          <CheckCircleFilled style={{ color: 'var(--green-500)', fontSize: 18 }} />
          <span className="text-sm font-medium text-slate-700">分析完成</span>
        </div>
      )}

      {analyzing && !steps.length && (
        <div className="text-center py-10">
          <Spin indicator={<LoadingOutlined style={{ fontSize: 28 }} spin />} />
          <div className="mt-3 text-sm text-slate-500">正在启动分析…</div>
        </div>
      )}
    </div>
  );
}
