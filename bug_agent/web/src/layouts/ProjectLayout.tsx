import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { Outlet, useParams, useNavigate, useLocation } from 'react-router-dom';
import { Breadcrumb, Spin, Modal } from 'antd';
import { message } from '../utils/appMessage';
import {
  DashboardOutlined, BugOutlined, SyncOutlined, TeamOutlined,
  CodeOutlined, BellOutlined, LeftOutlined, DeploymentUnitOutlined, ApartmentOutlined, SafetyCertificateOutlined, BarChartOutlined, SettingOutlined,
} from '@ant-design/icons';
import { getProject, listIterations } from '../api';
import PageLoadState from '../components/PageLoadState';
import UserCenterModal from '../components/UserCenterModal';
import AppShell from '../components/layout/AppShell';
import ShellNavigation from '../components/layout/ShellNavigation';
import ShellSidebarHeader from '../components/layout/ShellSidebarHeader';
import ShellTopbarHeading from '../components/layout/ShellTopbarHeading';
import ShellUserTrigger from '../components/layout/ShellUserTrigger';
import IterationSummaryList from '../components/layout/IterationSummaryList';
import UserMenuDropdown, { useUserState } from '../components/layout/UserMenuDropdown';
import NotificationCenter from '../components/NotificationCenter';
import { getProjectColor } from '../utils/credential';
import { ProjectContext } from '../contexts/projectContext';
import dayjs from 'dayjs';
import type { Iteration, Project, ProjectMember } from '../types';

interface ProjectDetailPayload {
  project: Project;
  members: ProjectMember[];
  iterations: Iteration[];
}

export default function ProjectLayout() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [project, setProject] = useState<Project | null>(null);
  const [iterations, setIterations] = useState<Iteration[]>([]);
  const [currentIteration, setCurrentIteration] = useState<Iteration | null>(null);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { user, setUser, profileOpen, setProfileOpen, forcePasswordChange, isProfileOpen, handleLogout } = useUserState();
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const loadingRef = useRef(false);
  const lastProjectIdRef = useRef<string | undefined>(undefined);

  const pid = projectId ? Number(projectId) : undefined;

  const activeIterations = iterations
    .filter(i => i.status === 'active')
    .slice(0, 3);

  const refreshProject = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setLoadError(null);
    try {
      const currentPid = Number(projectId);
      if (!currentPid) return;
      const projectRes = await getProject(currentPid);
      setProject(projectRes.data?.project || null);
      setMembers(projectRes.data?.members || []);
      const iterList = projectRes.data?.iterations || [];
      setIterations(iterList);
      const active = iterList.find((i) => i.status === 'active');
      setCurrentIteration(active || (iterList.length > 0 ? iterList[0] : null));
    } catch {
      setLoadError('获取项目数据失败，请重试');
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, [projectId]);

  const loadProjectData = useCallback(async () => {
    await refreshProject();
  }, [refreshProject]);

  useEffect(() => {
    void loadProjectData();
  }, [loadProjectData]);

  const refreshIterations = useCallback(async () => {
    if (!pid) return;
    try {
      const res = await listIterations(pid);
      const iterList = res.data || [];
      setIterations(iterList);
      const active = iterList.find((i) => i.status === 'active');
      setCurrentIteration(active || null);
    } catch {
      // ignore iteration refresh failure
    }
  }, [pid]);

  const refreshMembers = useCallback(async () => {
    if (!pid) return;
    try {
      const res = await getProject(pid);
      setMembers(res.data?.members || []);
    } catch {
      // ignore member refresh failure
    }
  }, [pid]);

  const getSelectedKey = () => {
    const path = location.pathname;
    if (path.endsWith('/defects') || path.includes('/defects/')) return 'defects';
    if (path.endsWith('/issue-pool')) return 'issue-pool';
    if (path.endsWith('/integrations')) return 'integrations';
    if (path.endsWith('/regression')) return 'regression';
    if (path.endsWith('/quality-insights')) return 'quality-insights';
    if (path.endsWith('/routing')) return 'routing';
    if (path.endsWith('/iterations')) return 'iterations';
    if (path.endsWith('/members')) return 'members';
    if (path.endsWith('/repos')) return 'repos';
    if (path.endsWith('/notifications')) return 'notifications';
    if (path.endsWith('/settings')) return 'settings';
    return 'dashboard';
  };

  const getIterationProgressForIteration = (iteration: Iteration) => {
    const start = dayjs(iteration.startDate);
    const end = dayjs(iteration.endDate);
    const now = dayjs();
    if (now.isBefore(start)) return 0;
    if (now.isAfter(end)) return 100;
    const total = end.diff(start, 'day');
    const elapsed = now.diff(start, 'day');
    return Math.round((elapsed / total) * 100);
  };

  const handleSwitchIteration = (iteration: Iteration) => {
    if (iteration.id === currentIteration?.id) {
      navigate(`/projects/${projectId}/iterations`);
      return;
    }

    Modal.confirm({
      title: '切换当前迭代',
      content: `确定将"${iteration.name}"设为当前迭代吗?`,
      okText: '确定',
      cancelText: '取消',
      onOk: async () => {
        setCurrentIteration(iteration);
        message.info(`已切换到"${iteration.name}"（仅当前会话生效）`);
      },
    });
  };

  const navItems = useMemo(() => {
    const selectedKey = getSelectedKey();
    return [
      {
        key: 'dashboard',
        icon: <DashboardOutlined />,
        label: '工作台',
        onClick: () => navigate(`/projects/${projectId}`),
        active: selectedKey === 'dashboard',
      },
      {
        key: 'defects',
        icon: <BugOutlined />,
        label: '缺陷管理',
        onClick: () => navigate(`/projects/${projectId}/defects`),
        active: selectedKey === 'defects',
      },
      {
        key: 'issue-pool',
        icon: <DeploymentUnitOutlined />,
        label: '问题池',
        onClick: () => navigate(`/projects/${projectId}/issue-pool`),
        active: selectedKey === 'issue-pool',
      },
      {
        key: 'integrations',
        icon: <DeploymentUnitOutlined />,
        label: '信号接入',
        onClick: () => navigate(`/projects/${projectId}/integrations`),
        active: selectedKey === 'integrations',
      },
      { type: 'divider' as const, key: 'divider-1' },
      {
        key: 'iterations',
        icon: <SyncOutlined />,
        label: '迭代管理',
        onClick: () => navigate(`/projects/${projectId}/iterations`),
        active: selectedKey === 'iterations',
      },
      {
        key: 'routing',
        icon: <ApartmentOutlined />,
        label: '路由治理',
        onClick: () => navigate(`/projects/${projectId}/routing`),
        active: selectedKey === 'routing',
      },
      {
        key: 'regression',
        icon: <SafetyCertificateOutlined />,
        label: '回归预防',
        onClick: () => navigate(`/projects/${projectId}/regression`),
        active: selectedKey === 'regression',
      },
      {
        key: 'quality-insights',
        icon: <BarChartOutlined />,
        label: '质量情报',
        onClick: () => navigate(`/projects/${projectId}/quality-insights`),
        active: selectedKey === 'quality-insights',
      },
      { type: 'divider' as const, key: 'divider-2' },
      {
        key: 'members',
        icon: <TeamOutlined />,
        label: '成员管理',
        onClick: () => navigate(`/projects/${projectId}/members`),
        active: selectedKey === 'members',
      },
      {
        key: 'repos',
        icon: <CodeOutlined />,
        label: '仓库管理',
        onClick: () => navigate(`/projects/${projectId}/repos`),
        active: selectedKey === 'repos',
      },
      {
        key: 'notifications',
        icon: <BellOutlined />,
        label: '通知管理',
        onClick: () => navigate(`/projects/${projectId}/notifications`),
        active: selectedKey === 'notifications',
      },
      {
        key: 'settings',
        icon: <SettingOutlined />,
        label: 'AI配置',
        onClick: () => navigate(`/projects/${projectId}/settings`),
        active: selectedKey === 'settings',
      },
    ];
  }, [projectId, location.pathname, navigate]);

  const pageTitleMap: Record<string, string> = {
    dashboard: '工作台',
    defects: '缺陷管理',
    'issue-pool': '问题池',
    integrations: '信号接入',
    iterations: '迭代管理',
    routing: '路由治理',
    regression: '回归预防',
    'quality-insights': '质量情报',
    members: '成员管理',
    repos: '仓库管理',
    notifications: '通知管理',
    settings: 'AI配置',
  };
  const currentPageTitle = pageTitleMap[getSelectedKey()] || '工作台';

  const contextValue = useMemo(() => ({
    project,
    projectId: pid,
    iterations,
    currentIteration,
    members,
    refreshProject,
    refreshIterations,
    refreshMembers,
  }), [project, pid, iterations, currentIteration, members, refreshProject, refreshIterations, refreshMembers]);

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!project) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
        {loadError ? (
          <PageLoadState subTitle={loadError} onRetry={() => void loadProjectData()} />
        ) : (
          <span style={{ color: '#64748b' }}>项目不存在</span>
        )}
      </div>
    );
  }

  const sidebar = (
    <div className="shell-panel">
      <div className="shell-panel__section">
        <ShellSidebarHeader
          action={
            <a
              className="shell-sidebar-backlink"
              onClick={() => navigate('/projects')}
            >
              <LeftOutlined />
              返回项目列表
            </a>
          }
          badge={project.code?.substring(0, 2).toUpperCase()}
          badgeStyle={{ background: getProjectColor(project.code) }}
          title={project.name}
          align="start"
          truncate
        />
      </div>

      <div className="shell-panel__section shell-panel__section--scroll">
        <ShellNavigation items={navItems} />
      </div>

      {activeIterations.length > 0 && (
        <div className="shell-panel__section shell-panel__section--bottom">
          <div className="section-label" style={{ marginBottom: 6 }}>Active Iterations</div>
          <IterationSummaryList
            iterations={activeIterations}
            currentIterationId={currentIteration?.id}
            compact
            getProgress={getIterationProgressForIteration}
            onSelect={handleSwitchIteration}
          />
        </div>
      )}
    </div>
  );

  const topbar = (
    <div className="topbar">
      <div className="topbar__group">
        <ShellTopbarHeading
          title={currentPageTitle}
          leading={(
            <Breadcrumb
              items={[
                { title: <a onClick={() => navigate('/projects')} style={{ color: '#94a3b8', cursor: 'pointer' }}>项目列表</a> },
                { title: <span style={{ color: '#64748b' }}>{project.name}</span> },
                { title: <span style={{ color: '#0f172a', fontWeight: 600 }}>{currentPageTitle}</span> },
              ]}
            />
          )}
        />
      </div>
      <div className="topbar__group">
        <NotificationCenter />
        <div style={{ position: 'relative' }}>
          <ShellUserTrigger
            name={user.nickname || user.username || '用户'}
            role={user.platformRole === 'super_admin' ? '超级管理员' : user.platformRole === 'admin' ? '管理员' : '成员'}
            initial={user.nickname?.[0] || user.username?.[0] || 'U'}
            onClick={() => setUserMenuOpen((v) => !v)}
          />
          <UserMenuDropdown
            open={userMenuOpen}
            onClose={() => setUserMenuOpen(false)}
            onProfile={() => setProfileOpen(true)}
            onLogout={handleLogout}
          />
        </div>
      </div>
    </div>
  );

  return (
    <AppShell sidebar={sidebar} topbar={topbar}>
      <ProjectContext.Provider value={contextValue}>
        <Outlet />
      </ProjectContext.Provider>
      <UserCenterModal
        open={isProfileOpen}
        onClose={() => setProfileOpen(false)}
        onUserUpdated={setUser}
        forcePasswordChange={forcePasswordChange}
      />
    </AppShell>
  );
}
