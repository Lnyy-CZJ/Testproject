import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Row, Col, Button, Input, Spin, Empty, Modal, Form } from 'antd';
import { message } from '../../utils/appMessage';
import {
  PlusOutlined, SearchOutlined, RightOutlined, AppstoreOutlined, ClockCircleOutlined, SyncOutlined, TeamOutlined,
} from '@ant-design/icons';
import { listUserProjects, createProject } from '../../api';
import PageLayout from '../../components/layout/PageLayout';
import PageContent from '../../components/layout/PageContent';
import PageMetricSection from '../../components/layout/PageMetricSection';
import PageFilterBar from '../../components/layout/PageFilterBar';
import { getErrorMessage } from '../../utils/error';
import type { RequestError } from '../../utils/error';
import { getProjectColor } from '../../utils/credential';

interface ProjectMember {
  id: number;
  nickname: string;
  avatar?: string;
}

interface Project {
  id: number;
  name: string;
  code: string;
  description?: string;
  status: string;
  memberCount: number;
  pendingDefects: number;
  activeDefects: number;
  members: ProjectMember[];
}

interface CreateProjectValues {
  name: string;
  code: string;
  description?: string;
}

export default function ProjectList() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [creatingProject, setCreatingProject] = useState(false);
  const [createForm] = Form.useForm();
  
  // 防止 StrictMode 双重请求
  const loadingRef = useRef(false);
  const loadedRef = useRef(false);


  const loadProjects = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const res = await listUserProjects();
      setProjects(res.data?.items || []);
    } catch {
      message.error('加载项目失败');
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    // 只加载一次
    if (loadedRef.current) return;
    loadedRef.current = true;
    void loadProjects();
  }, [loadProjects]);

  const filteredProjects = useMemo(() => projects.filter(p =>
    p.name.toLowerCase().includes(searchKeyword.toLowerCase()) ||
    p.code.toLowerCase().includes(searchKeyword.toLowerCase())
  ), [projects, searchKeyword]);
  const activeProjectCount = useMemo(() => projects.filter((p) => p.status === 'active').length, [projects]);
  const totalActiveDefects = useMemo(() => projects.reduce((sum, project) => sum + (project.activeDefects || 0), 0), [projects]);
  const totalMembers = useMemo(() => projects.reduce((sum, project) => sum + (project.memberCount || 0), 0), [projects]);

  // 项目头像颜色
  const getStatusLabel = (status: string) => (status === 'active' ? '活跃' : '归档');

  const handleCreateProject = async () => {
    try {
      const values = await createForm.validateFields() as CreateProjectValues;
      setCreatingProject(true);
      const payload = {
        name: values.name,
        code: String(values.code || '').trim().toUpperCase(),
        description: values.description || '',
      };
      const res = await createProject(payload);
      message.success('项目创建成功');
      setCreateModalOpen(false);
      createForm.resetFields();
      await loadProjects();
    } catch (err: unknown) {
      if ((err as RequestError | undefined)?.errorFields) {
        return;
      }
      message.error(getErrorMessage(err, '创建项目失败'));
    } finally {
      setCreatingProject(false);
    }
  };

  return (
    <PageLayout>
      <PageContent>

      <PageMetricSection
        items={[
          { key: 'projects', label: '全部项目', value: projects.length, icon: <AppstoreOutlined />, tone: 'purple' },
          { key: 'active', label: '活跃项目', value: activeProjectCount, icon: <ClockCircleOutlined />, tone: 'cyan' },
          { key: 'fixing', label: '进行中缺陷', value: totalActiveDefects, icon: <SyncOutlined />, tone: 'amber' },
          { key: 'members', label: '协作成员', value: totalMembers, icon: <TeamOutlined />, tone: 'green' },
        ]}
        actions={(
          <Button
            type="primary"
            icon={<PlusOutlined />}
            className="brand-button"
            onClick={() => setCreateModalOpen(true)}
          >
            新建项目
          </Button>
        )}
      />



      <PageFilterBar
        compact
        filters={(
          <>
          <Input
            placeholder="搜索项目名称或代码..."
            prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            style={{ maxWidth: 320 }}
            allowClear
          />
          </>
        )}
        actions={searchKeyword ? <Button onClick={() => setSearchKeyword('')}>清空搜索</Button> : null}
        result={<span className="action-rail__result">{filteredProjects.length} 个结果</span>}
      />

      {loading ? (
        <div className="text-center py-16">
          <Spin size="large" />
        </div>
      ) : filteredProjects.length === 0 ? (
        <Card className="scene-card" styles={{ body: { padding: 36 } }}>
          <Empty
            description={searchKeyword ? '未找到匹配的项目' : '暂无项目'}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            {!searchKeyword && (
              <Button type="primary" className="brand-button" onClick={() => setCreateModalOpen(true)}>
                创建项目
              </Button>
            )}
          </Empty>
        </Card>
      ) : (
        <Row gutter={[20, 20]}>
          {filteredProjects.map((project) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={project.id}>
              <Card
                hoverable
                className="scene-card project-card cursor-pointer transition-all duration-200 hover:shadow-lg"
                onClick={() => {
                  localStorage.setItem('lastProjectId', String(project.id));
                  navigate(`/projects/${project.id}`);
                }}
              >
                <div className="project-card__header">
                  <div
                    className="project-card__badge project-card__badge--muted"
                    style={{ background: getProjectColor(project.code) }}
                  >
                    {project.code.substring(0, 2).toUpperCase()}
                  </div>
                  <div className={`project-card__status project-card__status--${project.status === 'active' ? 'active' : 'archived'}`}>
                    <span className="project-card__status-dot" aria-hidden="true" />
                    {getStatusLabel(project.status)}
                  </div>
                </div>

                <h3 className="text-base font-semibold text-slate-900 mb-1 truncate">
                  {project.name}
                </h3>
                <p className="text-slate-500 text-sm mb-3 line-clamp-2" style={{ minHeight: 40 }}>
                  {project.description || '暂无描述'}
                </p>

                {project.members && project.members.length > 0 && (
                  <div className="project-card__members">
                    <div className="project-card__avatars" aria-hidden="true">
                      {project.members.slice(0, 3).map((m, index) => (
                        <span
                          key={m.id}
                          className="project-card__avatar"
                          style={{ zIndex: 3 - index }}
                        >
                          {m.nickname?.[0] || '?'}
                        </span>
                      ))}
                    </div>
                    <span className="project-card__members-text">{project.memberCount} 位成员协作</span>
                  </div>
                )}

                <div className="project-card__stats">
                  <div className="project-card__stat">
                    <div className="project-card__stat-label">待处理</div>
                    <div className="project-card__stat-value">{project.pendingDefects || 0}</div>
                  </div>
                  <div className="project-card__stat">
                    <div className="project-card__stat-label">进行中</div>
                    <div className="project-card__stat-value">{project.activeDefects || 0}</div>
                  </div>
                </div>

                <div className="project-card__footer">
                  <div className="project-card__meta">
                    <span className="project-card__meta-item">{project.memberCount} 成员</span>
                    <span className="project-card__meta-separator" aria-hidden="true" />
                    <span className="project-card__meta-item">{project.code}</span>
                  </div>
                  <RightOutlined className="text-slate-400 text-xs" />
                </div>
              </Card>
            </Col>
          ))}

          {/* 新建项目卡片 */}
          <Col xs={24} sm={12} lg={8} xl={6}>
            <Card
              hoverable
              className="utility-card cursor-pointer transition-all"
              style={{ 
                borderRadius: 28, 
                border: '2px dashed #cbd5e1',
                background: 'rgba(255,255,255,0.58)',
              }}
              styles={{ body: { padding: 20, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: 240 } }}
              onClick={() => setCreateModalOpen(true)}
            >
              <div className="w-14 h-14 bg-gradient-to-br from-purple-100 to-cyan-100 rounded-2xl flex items-center justify-center mb-4">
                <PlusOutlined className="text-slate-400 text-lg" />
              </div>
              <span className="text-slate-900 font-semibold">新建项目</span>
              <span className="mt-2 text-sm text-slate-500 text-center">创建新的质量工作区，把缺陷、成员和 Agent 协作放到同一舞台。</span>
            </Card>
          </Col>
        </Row>
      )}

      <Modal
        title="新建项目"
        open={createModalOpen}
        forceRender
        onOk={handleCreateProject}
        onCancel={() => {
          setCreateModalOpen(false);
          createForm.resetFields();
        }}
        okText="创建"
        cancelText="取消"
        confirmLoading={creatingProject}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item
            name="name"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="请输入项目名称" />
          </Form.Item>
          <Form.Item
            name="code"
            label="项目代码"
            rules={[{ required: true, message: '请输入项目代码' }]}
          >
            <Input
              placeholder="如 BUGAGENT"
              maxLength={20}
              onBlur={(e) => {
                const v = e.target.value?.trim().toUpperCase();
                createForm.setFieldValue('code', v);
              }}
            />
          </Form.Item>
          <Form.Item name="description" label="项目描述">
            <Input.TextArea rows={3} placeholder="描述项目（可选）" />
          </Form.Item>
        </Form>
      </Modal>
      </PageContent>
    </PageLayout>
  );
}
