import { useEffect, useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { appStorage } from '../utils/storage';
import {
  AppstoreOutlined, TeamOutlined,
  LogoutOutlined, RobotOutlined, FileTextOutlined, ApiOutlined, KeyOutlined, SettingOutlined,
  SafetyOutlined,
} from '@ant-design/icons';
import NotificationCenter from '../components/NotificationCenter';
import ProjectSwitcher from '../components/ProjectSwitcher';
import UserCenterModal from '../components/UserCenterModal';
import AppShell from '../components/layout/AppShell';
import ShellNavigation from '../components/layout/ShellNavigation';
import ShellSidebarHeader from '../components/layout/ShellSidebarHeader';
import ShellTopbarHeading from '../components/layout/ShellTopbarHeading';
import ShellSearchField from '../components/layout/ShellSearchField';
import ShellUserTrigger from '../components/layout/ShellUserTrigger';
import ContextSummaryCard from '../components/layout/ContextSummaryCard';
import UserMenuDropdown, { useUserState } from '../components/layout/UserMenuDropdown';

export default function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, setUser, profileOpen, setProfileOpen, forcePasswordChange, isProfileOpen, handleLogout } = useUserState();
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const getSelectedKey = () => {
    const path = location.pathname;
    if (path === '/' || path === '/projects') return 'projects';
    if (path.startsWith('/users')) return 'users';
    if (path.startsWith('/audit-logs')) return 'audit-logs';
    if (path.startsWith('/ai-catalog')) return 'ai-catalog';
    if (path.startsWith('/platform-credentials')) return 'platform-credentials';
    if (path.startsWith('/platform-settings')) return 'platform-settings';
    if (path.startsWith('/role-permissions')) return 'role-permissions';
    return 'projects';
  };

  const pageTitleMap: Record<string, string> = {
    projects: '项目列表',
    users: '用户管理',
    'audit-logs': '审计日志',
    'ai-catalog': 'AI目录管理',
    'platform-credentials': '平台凭证管理',
    'platform-settings': '平台配置',
    'role-permissions': '角色权限管理',
  };

  const navItems = [
    {
      key: 'projects',
      icon: <AppstoreOutlined />,
      label: '项目列表',
      onClick: () => navigate('/projects'),
      active: getSelectedKey() === 'projects',
    },
    {
      key: 'users',
      icon: <TeamOutlined />,
      label: '用户管理',
      onClick: () => navigate('/users'),
      active: getSelectedKey() === 'users',
    },
    { type: 'divider' as const, key: 'divider-1' },
    {
      key: 'audit-logs',
      icon: <FileTextOutlined />,
      label: '审计日志',
      onClick: () => navigate('/audit-logs'),
      active: getSelectedKey() === 'audit-logs',
    },
    {
      key: 'ai-catalog',
      icon: <ApiOutlined />,
      label: 'AI目录',
      onClick: () => navigate('/ai-catalog'),
      active: getSelectedKey() === 'ai-catalog',
    },
    {
      key: 'platform-credentials',
      icon: <KeyOutlined />,
      label: '平台凭证',
      onClick: () => navigate('/platform-credentials'),
      active: getSelectedKey() === 'platform-credentials',
    },
    {
      key: 'platform-settings',
      icon: <SettingOutlined />,
      label: '平台配置',
      onClick: () => navigate('/platform-settings'),
      active: getSelectedKey() === 'platform-settings',
    },
    ...(user?.platformRole === 'super_admin'
      ? [
          { type: 'divider' as const, key: 'divider-admin' },
          {
            key: 'role-permissions',
            icon: <SafetyOutlined />,
            label: '角色权限管理',
            onClick: () => navigate('/role-permissions'),
            active: getSelectedKey() === 'role-permissions',
          },
        ]
      : []),
  ];

  const sidebar = (
    <div className="shell-panel">
      <div className="shell-panel__section">
        <ShellSidebarHeader
          badge={
            <svg style={{ width: 22, height: 22, color: 'white' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          }
          title="Bug Agent"
          align="start"
        />
      </div>

      <div className="shell-panel__section" style={{ flex: 1, overflowY: 'auto' }}>
        <ShellNavigation items={navItems} />
      </div>

      <div className="shell-panel__section">
        <ContextSummaryCard
          eyebrow={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'var(--brand-gradient)',
              }}>
                <RobotOutlined style={{ color: 'white', fontSize: 14 }} />
              </div>
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--brand-purple-deep, #7c3aed)' }}>AI AGENT 能力</span>
            </div>
          }
          signals={[
            { key: 'pm', label: '产品', tone: 'purple' },
            { key: 'fe', label: '前端', tone: 'cyan' },
            { key: 'be', label: '后端', tone: 'rose' },
            { key: 'ui', label: 'UI', tone: 'amber' },
            { key: 'qa', label: '测试', tone: 'green' },
            { key: 'client', label: '客户端', tone: 'slate' },
          ]}
        />
      </div>
    </div>
  );

  const topbar = (
    <div className="topbar">
      <div className="topbar__group">
        <ShellTopbarHeading title={pageTitleMap[getSelectedKey()] || '平台管理'} />
        <ProjectSwitcher />
      </div>
      <div className="topbar__group">
        <ShellSearchField ariaLabel="搜索" placeholder="搜索项目、缺陷..." />
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
      <Outlet />
      <UserCenterModal
        open={isProfileOpen}
        onClose={() => setProfileOpen(false)}
        onUserUpdated={setUser}
        forcePasswordChange={forcePasswordChange}
      />
    </AppShell>
  );
}
