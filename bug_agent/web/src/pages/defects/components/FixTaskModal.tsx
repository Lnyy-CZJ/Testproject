import { Modal, Input } from 'antd';

interface FixTaskModalProps {
  open: boolean;
  onCancel: () => void;
  onOk: () => void;
  fixBranch: string;
  onFixBranchChange: (value: string) => void;
}

export default function FixTaskModal({
  open,
  onCancel,
  onOk,
  fixBranch,
  onFixBranchChange,
}: FixTaskModalProps) {
  return (
    <Modal
      title="创建修复任务"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      okText="创建修复任务"
    >
      <div className="mb-4">
        <span className="ant-typography ant-typography-secondary">分支名称（可选）：</span>
        <Input
          placeholder="如：fix/login-timeout"
          value={fixBranch}
          onChange={(e) => onFixBranchChange(e.target.value)}
        />
      </div>
    </Modal>
  );
}
