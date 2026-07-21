import { Button } from 'antd';
import { CloseCircleOutlined } from '@ant-design/icons';
import DefectOverview from './components/DefectOverview';
import type { Defect } from '../../types';
import type { DefectAction } from './useDefectActions';

interface DefectActionPanelProps {
  defect: Defect;
  defectId: string;
  actions: DefectAction[];
  analyzing: boolean;
  onStopAnalysis: () => void;
  onEdit: () => void;
}

export default function DefectActionPanel({
  defect,
  defectId,
  actions,
  analyzing,
  onStopAnalysis,
  onEdit,
}: DefectActionPanelProps) {
  return (
    <div className="space-y-4">
      <DefectOverview defect={defect} onEdit={onEdit} />

      {actions.length > 0 && (
        <div className="action-card">
          <div className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 pb-2 border-b border-slate-100">
            快速操作
          </div>
          <div className="flex flex-col gap-2">
            {actions.map((action, idx) => (
              <Button
                key={action.label}
                block
                icon={action.icon}
                onClick={action.onClick}
                danger={action.danger}
                className={`action-btn ${idx === 0 && !action.danger ? 'brand-button' : ''}`}
                type={idx === 0 && !action.danger ? 'primary' : 'default'}
              >
                {action.label}
              </Button>
            ))}
            {analyzing && (
              <Button
                block
                icon={<CloseCircleOutlined />}
                onClick={onStopAnalysis}
                danger
                className="action-btn"
              >
                取消分析
              </Button>
            )}
          </div>
        </div>
      )}


    </div>
  );
}
