import { Modal, Input } from 'antd';

const { TextArea } = Input;

interface RejectModalProps {
  open: boolean;
  onCancel: () => void;
  onOk: () => void;
  rejectReason: string;
  onRejectReasonChange: (value: string) => void;
}

export default function RejectModal({
  open,
  onCancel,
  onOk,
  rejectReason,
  onRejectReasonChange,
}: RejectModalProps) {
  return (
    <Modal
      title="驳回缺陷"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      okButtonProps={{ danger: true }}
    >
      <div className="mb-2 text-slate-500">请输入驳回原因：</div>
      <TextArea
        rows={3}
        value={rejectReason}
        onChange={(e) => onRejectReasonChange(e.target.value)}
        placeholder="驳回原因..."
      />
    </Modal>
  );
}
