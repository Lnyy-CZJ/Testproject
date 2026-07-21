import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Empty, Form, Input, Select, Tabs, Typography } from 'antd';
import {
  ArrowLeftOutlined,
  BulbOutlined,
  MessageOutlined,
  SettingOutlined,
  CopyOutlined,
} from '@ant-design/icons';
import { message } from '../../utils/appMessage';
import { confirmCreateDefect, createDefect, createDefectDraftFromChat, listIterations } from '../../api';
import { useProject } from '../../contexts/projectContext';
import type { DefectDraft, Iteration } from '../../types';
import PageLayout from '../../components/layout/PageLayout';
import DefectDraftChat from './components/DefectDraftChat';
import DefectDraftConfirm, { type DefectConfirmValues } from './components/DefectDraftConfirm';
import { getErrorMessage } from '../../utils/error';

const { TextArea } = Input;

const commonTags = ['登录模块', '表单校验', '页面布局', '接口异常', '兼容性', '性能', '安全问题', '数据错误', 'UI样式', '交互逻辑'];

type CreateMode = 'chat' | 'advanced';

interface DefectCreateValues {
  iterationId: number;
  title: string;
  description: string;
  severity: string;
  priority: string;
  type: string;
  tags?: string[];
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

const tips = [
  { icon: '🎯', title: '描述具体现象', desc: '说明"发生了什么"而非"什么不好"' },
  { icon: '📍', title: '包含复现步骤', desc: '1-2-3 步骤让开发者能重现问题' },
  { icon: '🖥️', title: '注明环境信息', desc: '浏览器、设备、版本号等上下文' },
  { icon: '📎', title: '附上截图/日志', desc: '视觉问题截图，接口问题贴日志' },
];

const templates = [
  {
    key: 'functional',
    label: '功能缺陷',
    icon: '🐛',
    title: '【模块名】功能描述与预期不符',
    content: '## 问题描述\n\n在 [页面/模块] 进行 [操作] 时，出现 [异常现象]，预期应该 [正确行为]。\n\n## 复现步骤\n\n1. 进入 [页面]\n2. 点击 [按钮/链接]\n3. 输入 [数据]\n4. 观察到 [异常]\n\n## 预期结果\n\n[描述正确的行为]\n\n## 实际结果\n\n[描述实际发生的情况]\n\n## 环境信息\n\n- 浏览器：Chrome 120\n- 操作系统：macOS 14\n- 账号角色：[角色]',
  },
  {
    key: 'ui',
    label: 'UI 问题',
    icon: '🎨',
    title: '【页面名】UI显示异常',
    content: '## 问题描述\n\n[页面] 在 [条件] 下出现 [UI异常]，如布局错位/文字截断/样式缺失。\n\n## 截图\n\n[附上截图]\n\n## 环境信息\n\n- 浏览器及版本：\n- 屏幕分辨率：\n- 设备类型：',
  },
  {
    key: 'api',
    label: '接口异常',
    icon: '🔌',
    title: '【接口名】接口返回异常',
    content: '## 问题描述\n\n调用 [接口路径] 时返回 [状态码/错误信息]，导致 [影响]。\n\n## 请求信息\n\n- 接口：[URL]\n- 方法：[GET/POST]\n- 参数：\n```json\n{}\n```\n\n## 响应信息\n\n- 状态码：\n- 响应体：\n```json\n{}\n```',
  },
  {
    key: 'performance',
    label: '性能问题',
    icon: '⚡',
    title: '【模块名】加载/响应缓慢',
    content: '## 问题描述\n\n[页面/功能] 在 [条件] 下响应时间过长，耗时约 [X] 秒，影响用户体验。\n\n## 复现条件\n\n- 数据量：\n- 并发数：\n- 网络环境：\n\n## 性能数据\n\n- 页面加载时间：\n- 接口响应时间：\n- 内存占用：',
  },
];

export default function DefectCreate() {
  const navigate = useNavigate();
  const { project, projectId, iterations: projectIterations, currentIteration } = useProject();
  const [mode, setMode] = useState<CreateMode>('chat');
  const [loading, setLoading] = useState(false);
  const [draftLoading, setDraftLoading] = useState(false);
  const [iterations, setIterations] = useState<Iteration[]>([]);
  const [draft, setDraft] = useState<DefectDraft | null>(null);
  const [advancedSeed, setAdvancedSeed] = useState<Partial<DefectCreateValues>>({});
  const [formVersion, setFormVersion] = useState(0);


  const loadIterations = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await listIterations(projectId);
      setIterations(res.data || []);
    } catch {
      message.error('加载迭代失败');
    }
  }, [projectId]);

  useEffect(() => {
    if (projectIterations && projectIterations.length > 0) {
      setIterations(projectIterations);
      return;
    }
    void loadIterations();
  }, [loadIterations, projectIterations]);

  const initialIterationId = useMemo(() => currentIteration?.id || iterations.find((item) => item.status === 'active')?.id, [currentIteration?.id, iterations]);

  useEffect(() => {
    if (!advancedSeed.iterationId && initialIterationId) {
      setAdvancedSeed((prev) => ({ ...prev, iterationId: initialIterationId }));
    }
  }, [advancedSeed.iterationId, initialIterationId]);

  const handleGenerateDraft = async (values: { iterationId?: number; message: string; tags?: string[] }) => {
    if (!projectId) return;
    setDraftLoading(true);
    try {
      const res = await createDefectDraftFromChat(projectId, values);
      if (!res.data) {
        message.error('生成草稿失败');
        return;
      }
      setDraft(res.data);
      message.success('AI 草稿已生成，请确认后创建');
    } catch (error) {
      message.error(getErrorMessage(error, '生成草稿失败'));
    } finally {
      setDraftLoading(false);
    }
  };

  const handleConfirmDraft = async (values: DefectConfirmValues) => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await confirmCreateDefect(projectId, {
        ...values,
        sourceMode: 'manual_chat',
        tags: values.tags || [],
      });
      if (!res.data?.id) {
        message.error('创建缺陷失败');
        return;
      }
      message.success('缺陷创建成功');
      navigate(`/projects/${projectId}/defects/${res.data.id}`);
    } catch (error) {
      message.error(getErrorMessage(error, '创建缺陷失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleCreateAdvanced = async (values: DefectCreateValues) => {
    setLoading(true);
    try {
      const res = await createDefect({
        ...values,
        tags: values.tags || [],
      });
      if (!res.data?.id) {
        message.error('创建失败');
        return;
      }
      message.success('缺陷创建成功');
      navigate(`/projects/${projectId}/defects/${res.data.id}`);
    } catch (error) {
      message.error(getErrorMessage(error, '创建失败'));
    } finally {
      setLoading(false);
    }
  };

  const switchToAdvanced = (seed?: Partial<DefectCreateValues>) => {
    setMode('advanced');
    setDraft(null);
    setFormVersion((v) => v + 1);
    setAdvancedSeed({
      iterationId: seed?.iterationId ?? initialIterationId,
      title: seed?.title,
      description: seed?.description,
      severity: seed?.severity ?? 'normal',
      priority: seed?.priority ?? 'P2',
      type: seed?.type ?? 'functional',
      tags: seed?.tags,
    });
  };

  const switchToChat = () => {
    setMode('chat');
    setDraft(null);
  };

  const getCardTitle = () => {
    if (mode === 'chat') {
      return draft ? '确认 AI 草稿' : 'AI 对话创建';
    }
    return '高级创建';
  };

  const handleApplyTemplate = (tpl: typeof templates[number]) => {
    if (mode === 'advanced') {
      setAdvancedSeed((prev) => ({
        ...prev,
        title: tpl.title,
        description: tpl.content,
      }));
    }
    message.success(`已应用「${tpl.label}」模板`);
  };

  return (
    <PageLayout>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate(-1)}
          style={{ color: 'var(--slate-400)', padding: '4px 8px' }}
        />
        <Typography.Title level={4} style={{ margin: 0 }}>
          创建缺陷
        </Typography.Title>
        <div style={{ flex: 1 }} />
        <Tabs
          activeKey={mode}
          onChange={(key) => {
            if (key === 'advanced') {
              switchToAdvanced(advancedSeed);
            } else {
              switchToChat();
            }
          }}
          items={[
            { key: 'chat', label: <span><MessageOutlined style={{ marginRight: 6 }} />对话创建</span> },
            { key: 'advanced', label: <span><SettingOutlined style={{ marginRight: 6 }} />高级创建</span> },
          ]}
          size="small"
        />
      </div>

      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
        <div style={{ flex: '3 1 0%', minWidth: 0 }}>
          <Card
            className="scene-card"
            title={getCardTitle()}
            style={{ minHeight: 520 }}
          >
            {mode === 'chat' ? (
              draft ? (
                <DefectDraftConfirm
                  draft={draft}
                  iterations={iterations}
                  loading={loading}
                  onBack={() => setDraft(null)}
                  onSubmit={handleConfirmDraft}
                  onSwitchAdvanced={(values) => switchToAdvanced({
                    iterationId: values.iterationId,
                    title: values.title,
                    description: values.descriptionMarkdown,
                    severity: values.severity,
                    priority: values.priority,
                    type: values.type,
                    tags: values.tags,
                  })}
                  onCancel={() => navigate(-1)}
                />
              ) : (
                <DefectDraftChat
                  iterations={iterations}
                  loading={draftLoading}
                  initialIterationId={initialIterationId}
                  commonTags={commonTags}
                  onSubmit={handleGenerateDraft}
                  onSwitchAdvanced={() => switchToAdvanced(advancedSeed)}
                  onCancel={() => navigate(-1)}
                />
              )
            ) : (
              <Form<DefectCreateValues>
                layout="vertical"
                onFinish={(values) => void handleCreateAdvanced(values)}
                initialValues={{
                  iterationId: advancedSeed.iterationId ?? initialIterationId,
                  title: advancedSeed.title,
                  description: advancedSeed.description,
                  severity: advancedSeed.severity ?? 'normal',
                  priority: advancedSeed.priority ?? 'P2',
                  type: advancedSeed.type ?? 'functional',
                  tags: advancedSeed.tags,
                }}
                key={`advanced-form-${formVersion}`}
                style={{ marginBottom: 0 }}
              >
                {iterations.length === 0 ? <Empty description="当前项目暂无可用迭代，请先创建迭代" style={{ marginBottom: 24 }} /> : null}

                <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--slate-400)', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid rgba(226,232,240,0.6)' }}>
                  基本信息
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 16, marginBottom: 16 }}>
                  <Form.Item label="迭代" name="iterationId" rules={[{ required: true, message: '请选择迭代' }]} style={{ marginBottom: 16 }}>
                    <Select placeholder="请选择迭代" options={iterations.map((item) => ({ value: item.id, label: item.name }))} />
                  </Form.Item>
                  <Form.Item label="标题" name="title" rules={[{ required: true, max: 100, message: '请输入标题(限100字)' }]} style={{ marginBottom: 16 }}>
                    <Input placeholder="请输入缺陷标题" showCount maxLength={100} />
                  </Form.Item>
                </div>

                <Form.Item label="描述" name="description" rules={[{ required: true, message: '请输入描述' }]} style={{ marginBottom: 16 }}>
                  <TextArea rows={10} placeholder="请详细描述缺陷，支持 Markdown" showCount maxLength={5000} />
                </Form.Item>

                <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--slate-400)', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid rgba(226,232,240,0.6)' }}>
                  分类与优先级
                </div>

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

                <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--slate-400)', marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid rgba(226,232,240,0.6)' }}>
                  标签
                </div>

                <Form.Item label="标签" name="tags" style={{ marginBottom: 16 }}>
                  <Select
                    mode="tags"
                    tokenSeparators={[',']}
                    placeholder="选择或输入自定义标签"
                    options={commonTags.map((tag) => ({ value: tag, label: tag }))}
                  />
                </Form.Item>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 16, borderTop: '1px solid rgba(226,232,240,0.6)' }}>
                  <Button onClick={() => navigate(-1)}>取消</Button>
                  <Button type="primary" className="brand-button" htmlType="submit" loading={loading}>
                    创建缺陷
                  </Button>
                </div>
              </Form>
            )}
          </Card>
        </div>

        <div style={{ flex: '2 1 0%', minWidth: 280, position: 'sticky', top: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {mode === 'advanced' && (
            <Card
              className="utility-card"
              size="small"
              title={
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <CopyOutlined style={{ color: 'var(--purple-600)' }} />
                  <span>示例模板</span>
                </span>
              }
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {templates.map((tpl) => (
                  <div
                    key={tpl.key}
                    onClick={() => handleApplyTemplate(tpl)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 12,
                      background: 'rgba(248,250,252,0.72)',
                      border: '1px solid rgba(226,232,240,0.5)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(139,92,246,0.06)';
                      e.currentTarget.style.borderColor = 'rgba(139,92,246,0.15)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(248,250,252,0.72)';
                      e.currentTarget.style.borderColor = 'rgba(226,232,240,0.5)';
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 16 }}>{tpl.icon}</span>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--slate-700)' }}>{tpl.label}</span>
                    </div>
                    <div style={{
                      fontSize: 12,
                      color: 'var(--slate-400)',
                      marginTop: 4,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}>
                      {tpl.title}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card
            className="utility-card"
            size="small"
            title={
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <BulbOutlined style={{ color: 'var(--amber-500)' }} />
                <span>撰写技巧</span>
              </span>
            }
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {tips.map((tip) => (
                <div key={tip.title} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <span style={{ fontSize: 16, lineHeight: 1, flexShrink: 0, marginTop: 2 }}>{tip.icon}</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--slate-700)' }}>{tip.title}</div>
                    <div style={{ fontSize: 12, color: 'var(--slate-400)', marginTop: 2, lineHeight: 1.5 }}>{tip.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </PageLayout>
  );
}
