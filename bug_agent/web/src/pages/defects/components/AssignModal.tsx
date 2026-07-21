import { Modal, Select, Space, Button } from 'antd';
import type { User } from '../../../types';
import type { AssigneeRecommendation } from '../../../api';

interface AssignModalProps {
  open: boolean;
  onCancel: () => void;
  onOk: () => void;
  users: User[];
  selectedAssignee: number | null;
  onSelectedAssigneeChange: (value: number | null) => void;
  assigneeRecommendations: AssigneeRecommendation[];
  assigneeRecommendLoading: boolean;
}

export default function AssignModal({
  open,
  onCancel,
  onOk,
  users,
  selectedAssignee,
  onSelectedAssigneeChange,
  assigneeRecommendations,
  assigneeRecommendLoading,
}: AssignModalProps) {
  return (
    <Modal
      title="指派负责人"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
    >
      {assigneeRecommendations.length ? (
        <div className="mb-3">
          <div className="text-slate-500 text-sm mb-2">推荐负责人</div>
          <Space wrap>
            {assigneeRecommendations.map((item) => (
              <Button
                key={item.userId}
                size="small"
                type={selectedAssignee === item.userId ? 'primary' : 'default'}
                className={selectedAssignee === item.userId ? 'brand-button' : undefined}
                onClick={() => {
                  onSelectedAssigneeChange(item.userId);
                }}
              >
                {(item.nickname || item.username)} · {Math.round(item.confidence * 100)}%
              </Button>
            ))}
          </Space>
        </div>
      ) : null}
      <Select
        className="select-full"
        placeholder="选择负责人"
        showSearch
        optionFilterProp="label"
        value={selectedAssignee}
        onChange={(value) => {
          onSelectedAssigneeChange(value);
        }}
        options={users.map(u => ({ value: u.id, label: `${u.nickname || u.username} (${u.email})` }))}
      />
      {assigneeRecommendLoading ? <div className="text-xs text-slate-400 mt-2">推荐加载中...</div> : null}
    </Modal>
  );
}
