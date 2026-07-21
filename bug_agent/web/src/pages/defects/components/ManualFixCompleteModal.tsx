import { Modal, Input } from 'antd';

const { TextArea } = Input;

export interface ManualFixForm {
  description: string;
  prUrl: string;
  fixBranch: string;
}

interface ManualFixCompleteModalProps {
  open: boolean;
  onCancel: () => void;
  onOk: () => void;
  form: ManualFixForm;
  onFormChange: (form: ManualFixForm) => void;
}

export default function ManualFixCompleteModal({
  open,
  onCancel,
  onOk,
  form,
  onFormChange,
}: ManualFixCompleteModalProps) {
  return (
    <Modal
      title="提交人工修复"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      okText="提交修复完成"
    >
      <div className="space-y-4">
        <div>
          <span className="ant-typography ant-typography-secondary">修复描述（必填）：</span>
          <TextArea
            rows={3}
            placeholder="请描述修复内容"
            value={form.description}
            onChange={(e) => onFormChange({ ...form, description: e.target.value })}
          />
        </div>
        <div>
          <span className="ant-typography ant-typography-secondary">关联 PR URL（选填）：</span>
          <Input
            placeholder="https://github.com/org/repo/pull/123"
            value={form.prUrl}
            onChange={(e) => onFormChange({ ...form, prUrl: e.target.value })}
          />
        </div>
        <div>
          <span className="ant-typography ant-typography-secondary">修复分支名（选填）：</span>
          <Input
            placeholder="如：fix/login-bug"
            value={form.fixBranch}
            onChange={(e) => onFormChange({ ...form, fixBranch: e.target.value })}
          />
        </div>
      </div>
    </Modal>
  );
}
