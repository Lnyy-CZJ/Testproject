import type { PropsWithChildren } from "react";
import { NavLink } from "react-router-dom";

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
              <NavLink to="/" end>概览</NavLink>
              <NavLink to="/#tools">工具</NavLink>
              {(has("platform.config.manage") || has("platform.secret.manage")) && (
                <NavLink to="/settings/config">配置</NavLink>
              )}
              {(has("platform.user.manage") || has("platform.role.manage")) && (
                <NavLink to="/admin/users">权限</NavLink>
              )}
              {has("platform.audit.view") && <NavLink to="/audit">审计</NavLink>}
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
              <button className="text-button" type="button" onClick={onLogout}>退出</button>
            </div>
          )}
        </div>
      </header>
      <main>{children}</main>
      <footer>
        <span>测试开发平台</span>
        <span>工具独立运行，平台统一身份与配置</span>
      </footer>
    </>
  );
}
