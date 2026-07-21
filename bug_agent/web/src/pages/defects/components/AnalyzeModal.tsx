import { Modal, Checkbox, Space, Button } from 'antd';
import type { AgentRecommendation } from '../../../api';
import { AGENT_TYPES } from '../../../types';

interface AnalyzeModalProps {
  open: boolean;
  onCancel: () => void;
  onOk: () => void;
  selectedAgentTypes: string[];
  onSelectedAgentTypesChange: (values: string[]) => void;
  agentRecommendations: AgentRecommendation[];
  agentRecommendLoading: boolean;
}

export default function AnalyzeModal({
  open,
  onCancel,
  onOk,
  selectedAgentTypes,
  onSelectedAgentTypesChange,
  agentRecommendations,
  agentRecommendLoading,
}: AnalyzeModalProps) {
  return (
    <Modal
      title="选择 AGENT 类型"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
    >
      {agentRecommendations.length ? (
        <div className="mb-3">
          <div className="text-slate-500 text-sm mb-2">推荐组合</div>
          <Space wrap>
            {agentRecommendations.map((item) => (
              <Button
                key={item.agentType}
                size="small"
                onClick={() => onSelectedAgentTypesChange([item.agentType])}
              >
                {item.label} · {Math.round(item.confidence * 100)}%
              </Button>
            ))}
          </Space>
        </div>
      ) : null}
      <div className="mb-2 text-slate-500 text-sm">选择要使用的 AGENT 类型：</div>
      <Checkbox.Group
        value={selectedAgentTypes}
        onChange={(values) => onSelectedAgentTypesChange(values as string[])}
        options={AGENT_TYPES.map((agent) => ({
          label: agent.label,
          value: agent.key,
        }))}
        className="flex flex-col gap-2"
      />
      {agentRecommendLoading ? <div className="text-xs text-slate-400 mt-2">推荐加载中...</div> : null}
    </Modal>
  );
}
