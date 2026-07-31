import type { PropsWithChildren } from "react";

/** 提供平台公共页头、内容区和页脚。 */
export function AppShell({ children }: PropsWithChildren) {
  return (
    <>
      <header className="site-header">
        <div className="header-content">
          <a className="brand" href="/" aria-label="测试开发平台首页">
            <span className="brand-mark" aria-hidden="true">
              T
            </span>
            <span>测试开发平台</span>
          </a>
          <nav className="primary-nav" aria-label="主导航">
            <a href="/" aria-current="page">
              概览
            </a>
            <a href="/#tools">工具</a>
          </nav>
        </div>
      </header>
      <main>{children}</main>
      <footer>
        <span>测试开发平台</span>
        <span>工具独立运行，平台统一连接</span>
      </footer>
    </>
  );
}
