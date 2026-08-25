import type { PropsWithChildren } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { useToolCatalog } from "../context/ToolCatalogContext";
import { domainMeta, domainOrder } from "../data/capabilityCatalog";
import type { AuthState } from "../types/platform";

/** 提供统一的桌面工程工作台页头、权限导航、环境上下文和页脚。 */
export function AppShell({
  children,
  auth,
  environment,
  onEnvironmentChange,
  onLogout,
}: PropsWithChildren<{
  auth?: AuthState | null;
  environment?: string;
  onEnvironmentChange?: (environment: string) => void;
  onLogout?: () => void;
}>) {
  const location = useLocation();
  const { groups, loading, error } = useToolCatalog();
  // 权限与项目模块统一承接项目、授权、账号和平台配置入口；主页保持原工作台结构。
  const accessSurface = Boolean(auth) && (
    location.pathname === "/access"
    || location.pathname.startsWith("/projects")
    || location.pathname.startsWith("/admin/users")
    || location.pathname.startsWith("/admin/tool-access")
    || location.pathname.startsWith("/admin/tool-grants")
    || location.pathname.startsWith("/admin/roles")
    || location.pathname.startsWith("/account")
    || location.pathname.startsWith("/settings")
    || location.pathname.startsWith("/audit")
    || location.pathname.startsWith("/system/versions")
    || location.pathname === "/403"
  );
  const has = (permission: string) => Boolean(auth?.platform_permissions.includes(permission));
  const isPlatformAdmin = auth?.role === "platform_admin";

  return (
    <>
      <header className="site-header">
        <div className="header-content">
          <NavLink className="brand" to="/" aria-label="测试开发平台首页">
            <span className="brand-mark" aria-hidden="true">T</span>
            <span>测试开发平台</span>
          </NavLink>
          {auth && (
            <nav className="primary-nav" aria-label="主导航">
              <NavLink to="/" end>工作台</NavLink>
              {!loading && !error && domainOrder.map((domainId) => groups[domainId].length > 0 && (
                <NavLink key={domainId} to={`/${domainId}`}>{domainMeta[domainId].title}</NavLink>
              ))}
              <NavLink className={accessSurface ? "active" : undefined} to="/access">权限与项目</NavLink>
            </nav>
          )}
          {auth && (
            <div className="header-actions">
              {environment && onEnvironmentChange && (
                <label className="environment-picker">
                  <span>环境</span>
                  <select
                    value={environment}
                    onChange={(event) => onEnvironmentChange(event.target.value)}
                    aria-label="当前配置环境"
                  >
                    <option value="dev">DEV</option>
                    <option value="prod">PROD</option>
                  </select>
                </label>
              )}
              <nav className="account-nav" aria-label="个人设置">
                <NavLink to="/account/credentials">我的凭证</NavLink>
                <NavLink to="/account/llm">我的 LLM</NavLink>
              </nav>
              <NavLink className="current-user" to="/account">
                <span className="user-avatar" aria-hidden="true">{auth.user.display_name.slice(0, 1)}</span>
                <span>{auth.user.display_name}</span>
              </NavLink>
              <button className="text-button header-logout" type="button" onClick={onLogout}>退出</button>
            </div>
          )}
        </div>
      </header>
      {accessSurface ? <div className="access-layout">
        <aside className="access-sidebar">
          <p>权限与项目</p>
          <nav aria-label="权限与项目" className="access-sidebar-nav">
            <div className="access-sidebar-group">
              <span>功能</span>
              <NavLink to="/access" end>功能总览</NavLink>
              <Link className={location.pathname === "/projects" && location.search === "?scope=mine" ? "active" : ""} to="/projects?scope=mine">我的项目</Link>
              {isPlatformAdmin && <Link className={location.pathname.startsWith("/projects") && location.search !== "?scope=mine" ? "active" : ""} to="/projects">项目管理</Link>}
              {isPlatformAdmin && <NavLink to="/admin/users">用户管理</NavLink>}
              {isPlatformAdmin && <NavLink to="/admin/tool-access">工具管理</NavLink>}
              {isPlatformAdmin && <NavLink to="/admin/tool-grants">额外授权</NavLink>}
              {isPlatformAdmin && <NavLink to="/admin/roles">固定角色</NavLink>}
            </div>
            <div className="access-sidebar-group">
              <span>个人设置</span>
              <NavLink to="/account" end>账号与会话</NavLink>
              <NavLink to="/account/password">修改密码</NavLink>
              <NavLink to="/account/credentials">我的凭证</NavLink>
              <NavLink to="/account/llm">我的 LLM</NavLink>
            </div>
            {(isPlatformAdmin || has("platform.config.manage") || has("platform.secret.manage") || has("platform.credential.readiness.view") || has("platform.audit.view")) && <div className="access-sidebar-group">
              <span>平台配置</span>
              {isPlatformAdmin && <NavLink to="/settings/platform-llm">平台 LLM 配置</NavLink>}
              {has("platform.config.manage") && <NavLink to="/settings/config">普通配置</NavLink>}
              {has("platform.secret.manage") && <NavLink to="/settings/secrets">Secret</NavLink>}
              {isPlatformAdmin && <NavLink to="/settings/credential-agents">凭证代理</NavLink>}
              {has("platform.credential.readiness.view") && <NavLink to="/settings/credentials">凭证就绪度</NavLink>}
              {has("platform.audit.view") && <NavLink to="/audit">审计日志</NavLink>}
              {has("platform.audit.view") && <NavLink to="/system/versions">版本状态</NavLink>}
            </div>}
          </nav>
          {auth?.role === "tester" && <div className="sidebar-role-note"><strong>测试人员</strong><span>仅查看本人可用工具与项目</span></div>}
        </aside>
        <main className="access-main">{children}</main>
      </div> : <main>{children}</main>}
      {!accessSurface && <footer>
        <span>测试开发平台</span>
        <span>能力独立运行，平台统一身份、权限与配置</span>
      </footer>}
    </>
  );
}
