import { useState, useRef, useCallback, useEffect } from 'react';
import { triggerAnalysisStream, triggerAnalysis, cancelAnalysis, listReports, getDefect } from '../api/defect';
import { useSSEEvent } from './useSSE';
import type { StreamEvent, ThinkingStep } from '../api/types';

interface UseAnalysisStreamReturn {
  steps: ThinkingStep[];
  currentPhase: string;
  analyzing: boolean;
  error: string | null;
  startStream: (defectId: number, agentTypes: string[]) => Promise<void>;
  stopStream: () => Promise<void>;
  restorePolling: (defectId: number) => void;
}

export function useAnalysisStream(): UseAnalysisStreamReturn {
  const [steps, setSteps] = useState<ThinkingStep[]>([]);
  const [currentPhase, setCurrentPhase] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingActiveRef = useRef(false);
  const streamingRef = useRef(false);
  const stepCounterRef = useRef(0);
  const mountedRef = useRef(true);
  const activeDefectIdRef = useRef<number | null>(null);

  const resetStreamState = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    pollingActiveRef.current = false;
    streamingRef.current = false;
    activeDefectIdRef.current = null;
    if (pollingTimerRef.current) {
      clearTimeout(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
    if (mountedRef.current) {
      setAnalyzing(false);
    }
  }, []);

  const stopStream = useCallback(async () => {
    const defectId = activeDefectIdRef.current;
    resetStreamState();
    activeDefectIdRef.current = null;
    if (defectId == null) return;
    try {
      await cancelAnalysis(defectId);
    } catch (err) {
      if (mountedRef.current) {
        setError((err as { message?: string })?.message || '取消分析失败');
      }
    }
  }, [resetStreamState]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      pollingActiveRef.current = false;
      streamingRef.current = false;
      activeDefectIdRef.current = null;
      if (pollingTimerRef.current) {
        clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    };
  }, []);

  const startPollingFallback = useCallback((defectId: number) => {
    pollingActiveRef.current = true;
    let rounds = 0;
    const maxRounds = 40;

    const poll = async () => {
      if (!pollingActiveRef.current || !mountedRef.current) return;
      try {
        rounds += 1;
        const reportsRes = await listReports(defectId);
        if (!mountedRef.current) return;
        // Python 后端按契约直接返回报告数组，不使用旧版分页包装。
        const reportList = reportsRes.data || [];
        let reportCompleted = false;
        if (reportList.length > 0) {
          const latest = reportList[0];
          if (latest.status === 'completed' || latest.status === 'completed_fallback') {
            reportCompleted = true;
          }
        }

        const defectRes = await getDefect(defectId);
        if (!mountedRef.current) return;
        const currentStatus = defectRes?.data?.defect?.status;

        if (currentStatus === 'pending_analysis' && rounds > 2) {
          resetStreamState();
          if (mountedRef.current) setError('AI分析失败，状态已回退到待分析');
          return;
        }

        if (reportCompleted && currentStatus !== 'analyzing') {
          resetStreamState();
          return;
        }

        if (rounds >= maxRounds) {
          resetStreamState();
          return;
        }

        stepCounterRef.current += 1;
        if (mountedRef.current) {
          setSteps(prev => [...prev, {
            id: `step-fallback-${stepCounterRef.current}`,
            type: 'thinking',
            content: '正在等待AI分析结果...',
            stepIndex: stepCounterRef.current,
            timestamp: Date.now(),
            phase: 'analysis',
          }]);
        }
      } catch {
        if (rounds >= maxRounds) {
          resetStreamState();
          if (mountedRef.current) setError('分析轮询失败');
          return;
        }
      }

      if (pollingActiveRef.current && mountedRef.current) {
        pollingTimerRef.current = setTimeout(poll, 3000);
      }
    };

    pollingTimerRef.current = setTimeout(poll, 3000);
  }, [resetStreamState]);

  useSSEEvent('analysis:started', useCallback((data: any) => {
    if (!data || !mountedRef.current) return;
    if (!analyzing) {
      setAnalyzing(true);
      setError(null);
      setCurrentPhase('retrieval');
      stepCounterRef.current += 1;
      setSteps(prev => [...prev, {
        id: `step-sse-${stepCounterRef.current}`,
        type: 'thinking',
        content: 'AI分析已启动，正在检索代码上下文...',
        stepIndex: stepCounterRef.current,
        timestamp: Date.now(),
        phase: 'retrieval',
      }]);
    }
  }, [analyzing]));

  useSSEEvent('analysis:completed', useCallback((_data: any) => {
    if (!mountedRef.current || streamingRef.current) return;
    stepCounterRef.current += 1;
    setSteps(prev => [...prev, {
      id: `step-sse-done-${stepCounterRef.current}`,
      type: 'final',
      content: '分析完成',
      stepIndex: stepCounterRef.current,
      timestamp: Date.now(),
      phase: 'analysis',
    }]);
    setAnalyzing(false);
    setCurrentPhase('analysis');
  }, []));

  useSSEEvent('analysis:failed', useCallback((data: any) => {
    if (!mountedRef.current || streamingRef.current) return;
    setError(data?.error || 'AI分析失败');
    setAnalyzing(false);
  }, []));

  const startStream = useCallback(async (defectId: number, agentTypes: string[]) => {
    if (!mountedRef.current) return;
    setSteps([]);
    setCurrentPhase('retrieval');
    setAnalyzing(true);
    setError(null);
    streamingRef.current = true;
    activeDefectIdRef.current = defectId;
    stepCounterRef.current = 0;

    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    try {
      const response = await triggerAnalysisStream(
        { defectId, agentTypes },
        abortController.signal,
      );

      if (!mountedRef.current) return;

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No readable stream');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!mountedRef.current) return;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            continue;
          } else if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            try {
              const event: StreamEvent = JSON.parse(jsonStr);
              stepCounterRef.current += 1;
              const step: ThinkingStep = {
                id: `step-${stepCounterRef.current}`,
                type: event.type,
                content: event.content || '',
                toolName: event.toolName,
                toolInput: event.toolInput,
                toolOutput: event.toolOutput,
                phase: event.phase,
                stepIndex: event.stepIndex || stepCounterRef.current,
                timestamp: Date.now(),
              };

              if (mountedRef.current) {
                setSteps(prev => [...prev, step]);
              }

              if (event.phase && mountedRef.current) {
                setCurrentPhase(event.phase);
              }

              if (event.type === 'final' && event.done) {
                streamingRef.current = false;
                activeDefectIdRef.current = null;
                if (mountedRef.current) setAnalyzing(false);
                return;
              }

              if (event.type === 'error') {
                streamingRef.current = false;
                activeDefectIdRef.current = null;
                if (mountedRef.current) {
                  setError(event.error || '分析失败');
                  setAnalyzing(false);
                }
                return;
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    } catch (err: any) {
      streamingRef.current = false;
      if (err.name === 'AbortError') {
        return;
      }
      if (!mountedRef.current) return;
      try {
        await triggerAnalysis({ defectId, agentTypes });
        if (!mountedRef.current) return;
        stepCounterRef.current += 1;
        setSteps(prev => [...prev, {
          id: `step-fallback-${stepCounterRef.current}`,
          type: 'thinking',
          content: 'SSE不可用，已切换到异步模式，正在等待分析结果...',
          stepIndex: stepCounterRef.current,
          timestamp: Date.now(),
          phase: 'analysis',
        }]);
        setCurrentPhase('analysis');
        startPollingFallback(defectId);
      } catch {
        if (mountedRef.current) {
          setError(err.message || '分析流连接失败');
          setAnalyzing(false);
        }
      }
    }
  }, [startPollingFallback]);

  const restorePolling = useCallback((defectId: number) => {
    if (!mountedRef.current) return;
    if (pollingActiveRef.current) return;
    activeDefectIdRef.current = defectId;
    setAnalyzing(true);
    setError(null);
    setCurrentPhase('analysis');
    stepCounterRef.current += 1;
    setSteps([{
      id: `step-restore-${stepCounterRef.current}`,
      type: 'thinking',
      content: '检测到分析进行中，正在恢复状态...',
      stepIndex: stepCounterRef.current,
      timestamp: Date.now(),
      phase: 'analysis',
    }]);
    startPollingFallback(defectId);
  }, [startPollingFallback]);

  return { steps, currentPhase, analyzing, error, startStream, stopStream, restorePolling };
}
