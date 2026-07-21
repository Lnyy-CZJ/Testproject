import { Alert, Button, Card, Form, Input, Select, Tag } from 'antd';
import { RobotOutlined, EditOutlined } from '@ant-design/icons';
import type { DefectDraft, Iteration } from '../../../types';
import { message } from '../../../utils/appMessage';
import { getErrorMessage } from '../../../utils/error';

const { TextArea } = Input;

export interface DefectConfirmValues {
  iterationId: number;
  title: string;
  descriptionMarkdown: string;
  severity: string;
  priority: string;
  type: string;
  tags?: string[];
}

interface DefectDraftConfirmProps {
  draft: DefectDraft;
  iterations: Iteration[];
  loading: boolean;
  onBack: () => void;
  onSubmit: (values: DefectConfirmValues) => Promise<void>;
  onSwitchAdvanced: (values: DefectConfirmValues) => void;
  onCancel: () => void;
}

const severityOptions = [
  { value: 'fatal', label: '🟥 致命' },
  { value: 'major', label: '🟧 严重' },
  { value: 'normal', label: '🟦 一般' },
  { value: 'minor', label: '🟩 轻微' },
  { value: 'suggest', label: '⬜ 建议' },
];

const priorityOptions = [
  { value: 'P0', label: '🔴 P0 - 紧急' },
  { value: 'P1', label: '🟠 P1 - 高' },
  { value: 'P2', label: '🔵 P2 - 中' },
  { value: 'P3', label: '🟢 P3 - 低' },
  { value: 'P4', label: '⚪ P4 - 可选' },
];

const typeOptions = [
  { value: 'functional', label: '功能缺陷' },
  { value: 'ui', label: 'UI问题' },
  { value: 'performance', label: '性能问题' },
  { value: 'security', label: '安全问题' },
  { value: 'compatibility', label: '兼容性问题' },
  { value: 'other', label: '其他' },
];

export default function DefectDraftConfirm({
  draft,
  iterations,
  loading,
  onBack,
  onSubmit,
  onSwitchAdvanced,
  onCancel,
}: DefectDraftConfirmProps) {
  const [form] = Form.useForm<DefectConfirmValues>();

  return (
    <div className="defect-draft-confirm" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* DraftBanner */}
      <div
        style={{
          borderRadius: 18,
          background: 'linear-gradient(135deg, #faf5ff 0%, #ecfeff 100%)',
          border: '1px solid rgba(139,92,246,0.16)',
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 12,
            background: 'var(--color-brand-gradient)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            boxShadow: '0 4px 12px rgba(124,58,237,0.18)',
          }}
        >
          <RobotOutlined style={{ color: '#fff', fontSize: 16 }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Tag color="purple" style={{ margin: 0, fontWeight: 600 }}>AI 草稿</Tag>
            <span style={{ color: 'var(--purple-600)', fontSize: 13, fontWeight: 500 }}>
              置信度 {Math.round(draft.confidence * 100)}%
            </span>
          </div>
          <div style={{ marginTop: 4, fontSize: 13, color: 'var(--slate-500)' }}>
            AI 已根据你的描述整理出缺陷报告，请确认后创建
          </div>
        </div>
        <Button type="text" size="small" onClick={onBack} style={{ color: 'var(--purple-600)', fontWeight: 500 }}>
          重新描述
        </Button>
      </div>

      {/* FallbackAlert */}
      {draft.fallbackUsed && draft.fallbackReason ? (
        <Alert
          type="warning"
          showIcon
          message="AI 整理未完成，已切换基础草稿"
          description={draft.fallbackReason}
          style={{ borderRadius: 16 }}
        />
      ) : null}

      {/* MissingInfoAlert */}
      {draft.missingInformation && draft.missingInformation.length > 0 ? (
        <Alert
          type={draft.fallbackUsed ? 'warning' : 'info'}
          showIcon
          message="建议补充信息"
          description={draft.missingInformation.join('；')}
          style={{ borderRadius: 16 }}
        />
      ) : null}

      {/* Draft Summary Card */}
      <Card
        className="utility-card"
        size="small"
        title={
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--slate-600)' }}>
            草稿预览
          </span>
        }
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div>
            <span style={{ fontSize: 12, color: 'var(--slate-400)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              标题
            </span>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--slate-800)', marginTop: 2 }}>
              {draft.title}
            </div>
          </div>
          <div>
            <span style={{ fontSize: 12, color: 'var(--slate-400)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              描述
            </span>
            <div style={{
              fontSize: 13,
              color: 'var(--slate-600)',
              marginTop: 2,
              lineHeight: 1.7,
              maxHeight: 120,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {draft.descriptionMarkdown.length > 300
                ? draft.descriptionMarkdown.slice(0, 300) + '...'
                : draft.descriptionMarkdown}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
            <Tag color="purple">{severityOptions.find((o) => o.value === draft.severity)?.label || draft.severity}</Tag>
            <Tag color="blue">{priorityOptions.find((o) => o.value === draft.priority)?.label || draft.priority}</Tag>
            <Tag color="cyan">{typeOptions.find((o) => o.value === draft.type)?.label || draft.type}</Tag>
            {draft.tags?.map((tag) => (
              <Tag key={tag}>{tag}</Tag>
            ))}
          </div>
        </div>
      </Card>

      {/* Form */}
      <Form<DefectConfirmValues>
        form={form}
        layout="vertical"
        initialValues={{
          iterationId: draft.suggestedIterationId,
          title: draft.title,
          descriptionMarkdown: draft.descriptionMarkdown,
          severity: draft.severity,
          priority: draft.priority,
          type: draft.type,
          tags: draft.tags,
        }}
        onFinish={(values) => { onSubmit(values).catch((err: unknown) => { message.error(getErrorMessage(err, '提交失败')); }); }}
      >
        {/* Iteration + Title in one row */}
        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 16, marginBottom: 16 }}>
          <Form.Item label="迭代" name="iterationId" rules={[{ required: true, message: '请选择迭代' }]} style={{ marginBottom: 16 }}>
            <Select options={iterations.map((iteration) => ({ value: iteration.id, label: iteration.name }))} />
          </Form.Item>
          <Form.Item label="标题" name="title" rules={[{ required: true, message: '请输入标题' }, { max: 100, message: '标题不能超过 100 字' }]} style={{ marginBottom: 16 }}>
            <Input showCount maxLength={100} />
          </Form.Item>
        </div>

        {/* Description */}
        <Form.Item label="描述" name="descriptionMarkdown" rules={[{ required: true, message: '请输入描述' }]} style={{ marginBottom: 16 }}>
          <TextArea rows={10} showCount maxLength={5000} />
        </Form.Item>

        {/* 3-column grid: severity, priority, type */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16, marginBottom: 16 }}>
          <Form.Item label="严重级别" name="severity" rules={[{ required: true, message: '请选择严重级别' }]} style={{ marginBottom: 16 }}>
            <Select options={severityOptions} />
          </Form.Item>
          <Form.Item label="优先级" name="priority" rules={[{ required: true, message: '请选择优先级' }]} style={{ marginBottom: 16 }}>
            <Select options={priorityOptions} />
          </Form.Item>
          <Form.Item label="缺陷类型" name="type" rules={[{ required: true, message: '请选择缺陷类型' }]} style={{ marginBottom: 16 }}>
            <Select options={typeOptions} />
          </Form.Item>
        </div>

        {/* Tags */}
        <Form.Item label="标签" name="tags" style={{ marginBottom: 16 }}>
          <Select mode="tags" tokenSeparators={[',']} />
        </Form.Item>

        {/* Action bar */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            paddingTop: 16,
            borderTop: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <div style={{ display: 'flex', gap: 8 }}>
            <Button onClick={onCancel}>取消</Button>
            <Button onClick={() => {
              const values = form.getFieldsValue();
              onSwitchAdvanced(values);
            }} icon={<EditOutlined />}>
              编辑草稿
            </Button>
          </div>
          <Button type="primary" className="brand-button" htmlType="submit" loading={loading}>
            确认创建缺陷
          </Button>
        </div>
      </Form>
    </div>
  );
}
