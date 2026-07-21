import { useState } from 'react';
import { Button, Form, Input, Select, message } from 'antd';
import { SendOutlined, RobotOutlined } from '@ant-design/icons';
import type { Iteration } from '../../../types';

const { TextArea } = Input;

interface DraftChatValues {
  iterationId?: number;
  message: string;
  tags?: string[];
}

interface ChatMessage {
  id: string;
  role: 'ai' | 'user';
  content: string;
}

interface DefectDraftChatProps {
  iterations: Iteration[];
  loading: boolean;
  initialIterationId?: number;
  commonTags: string[];
  onSubmit: (values: DraftChatValues) => Promise<void>;
  onSwitchAdvanced: () => void;
  onCancel: () => void;
}

export default function DefectDraftChat({
  iterations,
  loading,
  initialIterationId,
  commonTags,
  onSubmit,
  onSwitchAdvanced,
  onCancel,
}: DefectDraftChatProps) {
  const [form] = Form.useForm<DraftChatValues>();
  const [inputValue, setInputValue] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'ai',
      content: '你好！描述你发现的问题，我来帮你整理成缺陷报告。比如："登录页面输入错误密码后没有提示信息，用户不知道为什么登录失败"',
    },
  ]);

  const handleSend = async () => {
    const trimmed = inputValue.trim();
    if (!trimmed || trimmed.length < 8) {
      message.warning('信息太少，至少写 8 个字');
      return;
    }

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue('');

    try {
      const formValues = form.getFieldsValue();
      await onSubmit({
        iterationId: formValues.iterationId,
        message: trimmed,
        tags: formValues.tags,
      });
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
      setInputValue(trimmed);
      message.error('生成草稿失败，请重试');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 460 }}>
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 0',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          minHeight: 200,
        }}
      >
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: 'flex',
              gap: 10,
              alignItems: 'flex-start',
              flexDirection: msg.role === 'ai' ? 'row' : 'row-reverse',
            }}
          >
            {/* Avatar */}
            {msg.role === 'ai' ? (
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
            ) : (
              <div
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 12,
                  background: 'var(--slate-200)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  color: 'var(--slate-500)',
                  fontWeight: 600,
                  fontSize: 14,
                }}
              >
                我
              </div>
            )}

            {/* Bubble */}
            <div
              style={{
                maxWidth: '75%',
                padding: '12px 16px',
                borderRadius: msg.role === 'ai'
                  ? '4px 18px 18px 18px'
                  : '18px 4px 18px 18px',
                background: msg.role === 'ai'
                  ? 'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(6,182,212,0.06))'
                  : 'rgba(241,245,249,0.92)',
                border: msg.role === 'ai'
                  ? '1px solid rgba(139,92,246,0.12)'
                  : '1px solid rgba(226,232,240,0.6)',
                fontSize: 14,
                lineHeight: 1.7,
                color: msg.role === 'ai' ? 'var(--slate-700)' : 'var(--slate-800)',
              }}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
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
            <div
              style={{
                padding: '12px 16px',
                borderRadius: '4px 18px 18px 18px',
                background: 'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(6,182,212,0.06))',
                border: '1px solid rgba(139,92,246,0.12)',
                fontSize: 14,
                color: 'var(--slate-500)',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <span className="ant-typography" style={{ color: 'var(--purple-600)', fontWeight: 500 }}>
                AI 正在整理缺陷报告
              </span>
              <span style={{ animation: 'pulse 1.5s infinite' }}>...</span>
            </div>
          </div>
        )}
      </div>

      {/* Iteration + Tags row */}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ iterationId: initialIterationId }}
        style={{ marginBottom: 0 }}
      >
        <div
          style={{
            display: 'flex',
            gap: 12,
            marginBottom: 12,
            padding: '12px 16px',
            borderRadius: 16,
            background: 'rgba(248,250,252,0.72)',
            border: '1px solid rgba(226,232,240,0.6)',
          }}
        >
          <Form.Item name="iterationId" style={{ marginBottom: 0, flex: '0 0 200px' }}>
            <Select
              allowClear
              placeholder="选择迭代"
              options={iterations.map((iteration) => ({ value: iteration.id, label: iteration.name }))}
            />
          </Form.Item>
          <Form.Item name="tags" style={{ marginBottom: 0, flex: 1 }}>
            <Select
              mode="tags"
              tokenSeparators={[',']}
              placeholder="选择或输入标签"
              options={commonTags.map((tag) => ({ value: tag, label: tag }))}
            />
          </Form.Item>
        </div>
      </Form>

      {/* Input area */}
      <div
        style={{
          display: 'flex',
          gap: 10,
          alignItems: 'flex-end',
          padding: '12px 16px',
          borderRadius: 18,
          background: 'rgba(255,255,255,0.86)',
          border: '1px solid rgba(226,232,240,0.78)',
          boxShadow: 'var(--shadow-xs)',
        }}
      >
        <TextArea
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="描述你发现的问题... (Enter 发送, Shift+Enter 换行)"
          autoSize={{ minRows: 2, maxRows: 5 }}
          maxLength={2000}
          style={{
            flex: 1,
            borderRadius: 14,
            borderColor: 'transparent',
            background: 'transparent',
            resize: 'none',
          }}
          styles={{
            textarea: {
              background: 'transparent',
            },
          }}
        />
        <Button
          type="primary"
          className="brand-button"
          icon={<SendOutlined />}
          loading={loading}
          onClick={() => void handleSend()}
          style={{
            borderRadius: 14,
            height: 44,
            width: 44,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        />
      </div>

      {/* Action bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          paddingTop: 16,
          marginTop: 8,
        }}
      >
        <Button onClick={onCancel}>取消</Button>
        <Button type="link" onClick={onSwitchAdvanced} style={{ color: 'var(--slate-400)', fontSize: 13 }}>
          切换到高级模式
        </Button>
      </div>
    </div>
  );
}
