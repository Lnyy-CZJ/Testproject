import type { PropsWithChildren } from "react";
import { NavLink } from "react-router-dom";

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
  const has = (permission: string) => auth?.platform_permissions.includes(permission);
  const { groups, loading, error } = useToolCatalog();
  const managementPath = has("platform.user.manage")
    ? "/admin/users"
    : has("platform.role.manage")
      ? "/admin/roles"
      : has("platform.llm.manage") || has("platform.llm.secret.manage")
        ? "/settings/llm"
        : has("platform.config.manage") || has("platform.secret.manage")
          ? "/settings/config"
          : has("platform.audit.view") ? "/audit" : null;

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
              <NavLink className="current-user" to="/account">{auth.user.display_name}</NavLink>
              {managementPath && <NavLink className="management-link" to={managementPath}>平台管理</NavLink>}
              <button className="text-button" type="button" onClick={onLogout}>退出</button>
            </div>
          )}
        </div>
      </header>
      <main>{children}</main>
      <footer>
        <span>测试开发平台</span>
        <span>能力独立运行，平台统一身份、权限与配置</span>
      </footer>
    </>
  );
}
