/* eslint-disable react-refresh/only-export-components */
import { Suspense, lazy, useEffect, type ReactElement } from 'react';
import { createBrowserRouter, useNavigate, Link } from 'react-router-dom';

function HomeRedirect() {
  const navigate = useNavigate();
  useEffect(() => {
    const lastProjectId = localStorage.getItem('lastProjectId');
    if (lastProjectId) {
      navigate(`/projects/${lastProjectId}`, { replace: true });
    } else {
      navigate('/projects', { replace: true });
    }
  }, [navigate]);
  return null;
}

import AuthGuard from './components/AuthGuard';
const MainLayout = lazy(() => import('./layouts/MainLayout'));
const ProjectLayout = lazy(() => import('./layouts/ProjectLayout'));
const Login = lazy(() => import('./pages/auth/Login'));
const Register = lazy(() => import('./pages/auth/Register'));
const ProjectList = lazy(() => import('./pages/projects/ProjectList'));
const ProjectDashboard = lazy(() => import('./pages/projects/ProjectDashboard'));
const ProjectSettings = lazy(() => import('./pages/projects/ProjectSettings'));
const ProjectRepos = lazy(() => import('./pages/projects/ProjectRepos'));
const ProjectAIConfigs = lazy(() => import('./pages/projects/ProjectAIConfigs'));
const ProjectNotifications = lazy(() => import('./pages/projects/ProjectNotifications'));
const ProjectIterations = lazy(() => import('./pages/projects/ProjectIterations'));
const ProjectMembers = lazy(() => import('./pages/projects/ProjectMembers'));
const DefectList = lazy(() => import('./pages/defects/DefectList'));
const DefectDetail = lazy(() => import('./pages/defects/DefectDetail'));
const DefectCreate = lazy(() => import('./pages/defects/DefectCreate'));
const UserManagement = lazy(() => import('./pages/users'));
const AuditLogPage = lazy(() => import('./pages/system/AuditLogPage'));
const AICatalogPage = lazy(() => import('./pages/system/AICatalogPage'));
const PlatformCredentialsPage = lazy(() => import('./pages/system/PlatformCredentialsPage'));
const PlatformSettingsPage = lazy(() => import('./pages/system/PlatformSettingsPage'));
const RolePermissionPage = lazy(() => import('./pages/system/RolePermissionPage'));
const Profile = lazy(() => import('./pages/Profile'));
const ProjectIssuePool = lazy(() => import('./pages/projects/ProjectIssuePool'));
const ProjectRoutingCenter = lazy(() => import('./pages/projects/ProjectRoutingCenter'));
const ProjectRegressionCenter = lazy(() => import('./pages/projects/ProjectRegressionCenter'));
const ProjectQualityInsights = lazy(() => import('./pages/projects/ProjectQualityInsights'));
const ProjectIntegrationsPage = lazy(() => import('./pages/projects/ProjectIntegrationsPage'));

function NotFound() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
      <h1 style={{ fontSize: 72, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>404</h1>
      <p style={{ fontSize: 16, color: '#64748b', marginTop: 8 }}>页面不存在</p>
      <Link to="/" style={{ marginTop: 16, color: '#7c3aed' }}>返回首页</Link>
    </div>
  );
}

function withSuspense(element: ReactElement) {
  return (
    <Suspense fallback={<div style={{ padding: 24 }}>加载中...</div>}>
      {element}
    </Suspense>
  );
}

const router = createBrowserRouter([
  {
    path: '/login',
    element: withSuspense(<Login />),
  },
  {
    path: '/register',
    element: withSuspense(<Register />),
  },
  {
    path: '/',
    element: withSuspense(<AuthGuard><MainLayout /></AuthGuard>),
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: 'projects', element: withSuspense(<ProjectList />) },
      { path: 'users', element: withSuspense(<UserManagement />) },
      { path: 'audit-logs', element: withSuspense(<AuditLogPage />) },
      { path: 'ai-catalog', element: withSuspense(<AICatalogPage />) },
      { path: 'platform-credentials', element: withSuspense(<PlatformCredentialsPage />) },
      { path: 'platform-settings', element: withSuspense(<PlatformSettingsPage />) },
      { path: 'role-permissions', element: withSuspense(<RolePermissionPage />) },
      { path: 'profile', element: withSuspense(<Profile />) },
    ],
  },
  {
    path: 'projects/:projectId',
    element: withSuspense(<AuthGuard><ProjectLayout /></AuthGuard>),
    children: [
      { index: true, element: withSuspense(<ProjectDashboard />) },
      { path: 'defects', element: withSuspense(<DefectList />) },
      { path: 'issue-pool', element: withSuspense(<ProjectIssuePool />) },
      { path: 'integrations', element: withSuspense(<ProjectIntegrationsPage />) },
      { path: 'regression', element: withSuspense(<ProjectRegressionCenter />) },
      { path: 'quality-insights', element: withSuspense(<ProjectQualityInsights />) },
      { path: 'routing', element: withSuspense(<ProjectRoutingCenter />) },
      { path: 'defects/create', element: withSuspense(<DefectCreate />) },
      { path: 'defects/:defectId', element: withSuspense(<DefectDetail />) },
      { path: 'iterations', element: withSuspense(<ProjectIterations />) },
      { path: 'members', element: withSuspense(<ProjectMembers />) },
      { path: 'repos', element: withSuspense(<ProjectRepos />) },
      { path: 'ai-configs', element: withSuspense(<ProjectAIConfigs />) },
      { path: 'notifications', element: withSuspense(<ProjectNotifications />) },
      { path: 'settings', element: withSuspense(<ProjectSettings />) },
    ],
  },
  {
    path: '*',
    element: <NotFound />,
  },
]);

export default router;
