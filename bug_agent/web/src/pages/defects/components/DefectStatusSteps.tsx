import { Steps } from 'antd';
import type { Defect } from '../../../types';
import type { StatusStep } from '../types';
import '../defect-detail.css';

const statusSteps: StatusStep[] = [
  { key: 'new', label: '新建' },
  { key: 'pending_analysis', label: '待分析' },
  { key: 'analyzing', label: '分析中' },
  { key: 'pending_fix', label: '待修复' },
  { key: 'fixing', label: '修复中' },
  { key: 'manual_fixing', label: '人工修复' },
  { key: 'fixed', label: '已修复' },
  { key: 'pending_verify', label: '待验证' },
  { key: 'completed', label: '已完成' },
];

const statusStepMap: Record<string, number> = {};
statusSteps.forEach((s, i) => { statusStepMap[s.key] = i; });

const getStatusStep = (status: string): { step: number; status: 'error' | 'wait' | 'process' | 'finish' } => {
  if (status === 'rejected') {
    return { step: statusStepMap['pending_verify'] ?? 6, status: 'error' };
  }
  if (status === 'suspended') {
    const lastStep = statusStepMap[status] ?? 1;
    return { step: lastStep, status: 'wait' };
  }
  if (status === 'reopened') {
    return { step: statusStepMap['pending_analysis'] ?? 1, status: 'process' };
  }
  const idx = statusStepMap[status];
  if (idx !== undefined) {
    return { step: idx, status: idx === statusSteps.length - 1 ? 'finish' : 'process' };
  }
  return { step: 0, status: 'process' };
};

interface DefectStatusStepsProps {
  defect: Defect;
}

export default function DefectStatusSteps({ defect }: DefectStatusStepsProps) {
  const { step, status } = getStatusStep(defect.status);

  return (
    <Steps
      size="small"
      current={step}
      status={status}
      items={statusSteps.map((s) => ({
        title: <span className="text-xs">{s.label}</span>,
      }))}
      className="steps-compact"
    />
  );
}
