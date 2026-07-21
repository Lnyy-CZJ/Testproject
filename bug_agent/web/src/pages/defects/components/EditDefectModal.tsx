import { Modal, Select, Input } from 'antd';
import type { EditDefectForm } from '../types';
import { severityLabels, typeLabels } from '../../../constants/defect';

const { TextArea } = Input;

interface EditDefectModalProps {
  open: boolean;
  onCancel: () => void;
  onOk: () => void;
  form: EditDefectForm;
  onFormChange: (form: EditDefectForm) => void;
}

export default function EditDefectModal({
  open,
  onCancel,
  onOk,
  form,
  onFormChange,
}: EditDefectModalProps) {
  return (
    <Modal
      title="编辑缺陷"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      width={600}
    >
      <div className="space-y-4">
        <div>
          <span className="ant-typography ant-typography-secondary">标题</span>
          <Input
            value={form.title}
            onChange={(e) => onFormChange({ ...form, title: e.target.value })}
          />
        </div>
        <div>
          <span className="ant-typography ant-typography-secondary">描述</span>
          <TextArea
            rows={4}
            value={form.description}
            onChange={(e) => onFormChange({ ...form, description: e.target.value })}
          />
        </div>
        <div className="flex gap-4">
          <div className="flex-1">
            <span className="ant-typography ant-typography-secondary">严重程度</span>
            <Select
              className="select-full"
              value={form.severity}
              onChange={(v) => onFormChange({ ...form, severity: v })}
              options={Object.entries(severityLabels).map(([k, v]) => ({ value: k, label: v }))}
            />
          </div>
          <div className="flex-1">
            <span className="ant-typography ant-typography-secondary">优先级</span>
            <Select
              className="select-full"
              value={form.priority}
              onChange={(v) => onFormChange({ ...form, priority: v })}
              options={['P0', 'P1', 'P2', 'P3', 'P4'].map(v => ({ value: v, label: v }))}
            />
          </div>
        </div>
        <div>
          <span className="ant-typography ant-typography-secondary">类型</span>
          <Select
            className="select-full"
            value={form.type}
            onChange={(v) => onFormChange({ ...form, type: v })}
            options={Object.entries(typeLabels).map(([k, v]) => ({ value: k, label: v }))}
          />
        </div>
        <div>
          <span className="ant-typography ant-typography-secondary">标签（逗号分隔）</span>
          <Input
            value={form.tags}
            onChange={(e) => onFormChange({ ...form, tags: e.target.value })}
          />
        </div>
      </div>
    </Modal>
  );
}
