import {
  createContext,
  Fragment,
  type FormEvent,
  type PropsWithChildren,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  AUTH_REQUIRED_EVENT,
  ApiError,
  advanceAuthGeneration,
  apiJson,
  currentAuthGeneration,
  describeApiError,
  fetchTools,
  request,
  type AuthRequiredEventDetail,
} from "./api/client";
import { accessApi } from "./api/access";
import versionsManifest from "../../versions.json";
import { AppShell } from "./components/AppShell";
import { CapabilityCard } from "./components/CapabilityCard";
import { CapabilityDomainPage } from "./components/CapabilityDomainPage";
import { ToolGrid } from "./components/ToolGrid";
import { ToolCatalogProvider, useToolCatalog } from "./context/ToolCatalogContext";
import type {
  AdminUser,
  AuditEvent,
  AuthState,
  ConfigDefinition,
  ConfigRelease,
  CredentialReadiness,
  CredentialMetadata,
  PermissionDefinition,
  LlmBinding,
  LlmEffectiveConfig,
  LlmProfile,
  PersonalCredential,
  PersonalLlmBinding,
  PersonalLlmProfile,
  Role,
  RoleGrant,
  RuntimeScope,
  SecretMetadata,
  UserSession,
} from "./types/platform";
import type { Tool } from "./types/tool";
import type { ImpactPreview, PlatformRole, ProjectMember, ProjectRecord, ProjectSummary, ToolAccessRecord, ToolGrantSummary } from "./types/access";

const PLATFORM_VERSION = versionsManifest.product.version;
const AUTH_SESSION_SEEN_KEY = "tp_session_seen";
const AUTH_EXPIRED_NOTICE_KEY = "tp_auth_expired_notice";

type RegistrationMode = "open" | "disabled" | "invite";

/**
 * 校验所有“设置新密码”入口共享的 6–18 个 Unicode code point 规则。
 * 不 trim 密码；Array.from 避免把一个辅助平面字符按两个 UTF-16 code unit 计算。
 */
function validateNewPassword(value: string): string | null {
  const length = Array.from(value).length;
  return length >= 6 && length <= 18
    ? null
    : "密码长度必须为 6 到 18 个字符";
}

interface RuntimeIdentity {
  version: string;
  component_version: string;
  revision: string;
  dirty: boolean;
  content_sha256: string;
  runtime_environment: string;
}

interface ComponentIdentity {
  version: string;
  revision: string;
  dirty: boolean | null;
  runtime_environment: string;
  health: string;
  digest?: string | null;
  content_sha256?: string | null;
  config_sha256?: string | null;
  config_scopes?: string[];
}

interface DatabaseIdentity {
  alembic_revision?: string | null;
  schema_sha256?: string | null;
  tables?: number;
  columns?: number;
  constraints?: number;
  indexes?: number;
  data_compared?: false;
}

interface VersionMatrixRow {
  component_id: string;
  manifest_version: string;
  dev: ComponentIdentity | null;
  prod: ComponentIdentity | null;
  prod_expected: ComponentIdentity | null;
  issues: string[];
  primary_status: string;
}

interface VersionMatrix {
  checked_at: string;
  product_version: string;
  runtime_environment: string;
  prod_error?: string | null;
  dev?: { release?: string | null; database: DatabaseIdentity; config_releases: Record<string, string> } | null;
  prod?: { release?: string | null; database: DatabaseIdentity; config_releases: Record<string, string> } | null;
  rows: VersionMatrixRow[];
  database_comparison: { dev: DatabaseIdentity; prod: DatabaseIdentity; issues: string[]; primary_status: string; data_compared: false };
}

interface AuthContextValue {
  auth: AuthState | null;
  loading: boolean;
  registrationMode: RegistrationMode;
  reload: () => Promise<void>;
  setAuth: (value: AuthState | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("认证上下文未初始化");
  return value;
}

/** 统一加载当前用户，401 仅表示未登录，其他异常保留为平台错误。 */
function AuthProvider({ children }: PropsWithChildren) {
  const [auth, setAuthState] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(true);
  const [registrationMode, setRegistrationMode] = useState<RegistrationMode>("disabled");
  const setAuth = useCallback((value: AuthState | null) => {
    // 成功登录、注册或恢复会话时只持久化一个非敏感布尔标记；显式退出则
    // 同时清掉标记和一次性提示，避免下一次匿名恢复被误报为过期。
    advanceAuthGeneration();
    if (value) {
      localStorage.setItem(AUTH_SESSION_SEEN_KEY, "1");
    } else {
      localStorage.removeItem(AUTH_SESSION_SEEN_KEY);
      sessionStorage.removeItem(AUTH_EXPIRED_NOTICE_KEY);
    }
    setAuthState(value);
  }, []);
  const reload = useCallback(async () => {
    const reloadGeneration = currentAuthGeneration();
    setLoading(true);
    try {
      const result = await apiJson<AuthState>("/auth/me");
      // 登录/注册可能在恢复请求尚未返回时已建立新认证态；无论旧响应是
      // 200 还是 401，都不能覆盖更高代次的新会话。
      if (reloadGeneration === currentAuthGeneration()) setAuth(result);
    } catch (error) {
      // 初次匿名 401 已由全局事件区分是否曾有会话；这里仅完成状态收敛，
      // 不能调用显式退出语义的 setAuth(null) 清掉刚写入的一次性提示。
      if (error instanceof ApiError && error.status === 401) {
        if (reloadGeneration === currentAuthGeneration()) setAuthState(null);
      }
      else throw error;
    } finally {
      setLoading(false);
    }
  }, [setAuth]);

  // 监听器必须早于初次 /auth/me effect 注册，保证页面恢复请求的 401 也能被处理。
  useEffect(() => {
    function handleAuthRequired(event: Event) {
      const detail = (event as CustomEvent<AuthRequiredEventDetail>).detail;
      if (!detail || detail.generation !== currentAuthGeneration()) return;
      if (localStorage.getItem(AUTH_SESSION_SEEN_KEY) === "1") {
        localStorage.removeItem(AUTH_SESSION_SEEN_KEY);
        sessionStorage.setItem(AUTH_EXPIRED_NOTICE_KEY, "1");
        // 第一个同代 401 推进代次；随后迟到的并发 401 会因代次不一致被忽略。
        advanceAuthGeneration();
      }
      setAuthState(null);
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, handleAuthRequired);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void apiJson<unknown>("/auth/registration-status")
      .then((payload) => {
        if (cancelled) return;
        const mode = payload && typeof payload === "object" && "mode" in payload
          ? (payload as { mode?: unknown }).mode
          : null;
        setRegistrationMode(
          mode === "open" || mode === "disabled" || mode === "invite"
            ? mode
            : "disabled",
        );
      })
      .catch(() => {
        if (!cancelled) setRegistrationMode("disabled");
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    void reload().catch(() => setLoading(false));
  }, [reload]);
  return (
    <AuthContext.Provider value={{ auth, loading, registrationMode, reload, setAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

function LoadingPage({ label = "正在加载工作台…" }: { label?: string }) {
  return <div className="full-page-state" role="status"><span className="loading-indicator" />{label}</div>;
}

function InlineMessage({ kind = "info", children }: PropsWithChildren<{ kind?: "info" | "error" | "success" }>) {
  return <p className={`inline-message inline-message-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</p>;
}

/**
 * 为桌面对话框提供 Esc 关闭、焦点循环和关闭后的焦点恢复。
 *
 * ``onClose`` 与 ``closeDisabled`` 通过 ref 保持为最新值；若只把 ``open`` 放入
 * effect 依赖而直接捕获回调，提交开始后的 busy 状态会被旧闭包忽略，Esc 可能
 * 在写请求中途关闭弹窗并丢失恢复上下文。
 */
function useModal(open: boolean, onClose: () => void, closeDisabled = false) {
  const onCloseRef = useRef(onClose);
  const closeDisabledRef = useRef(closeDisabled);
  onCloseRef.current = onClose;
  closeDisabledRef.current = closeDisabled;
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = document.querySelector<HTMLElement>(".modal-backdrop .dialog");
    const focusable = () => [...(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])') ?? [])];
    focusable()[0]?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!closeDisabledRef.current) onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = focusable();
      if (!nodes.length) return;
      const first = nodes[0]; const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", handleKey);
    return () => { document.removeEventListener("keydown", handleKey); previous?.focus(); };
  }, [open]);
}

function LoginPage() {
  const { auth, registrationMode, setAuth } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [expiredNotice] = useState(() => {
    const visible = sessionStorage.getItem(AUTH_EXPIRED_NOTICE_KEY) === "1";
    if (visible) sessionStorage.removeItem(AUTH_EXPIRED_NOTICE_KEY);
    return visible;
  });
  if (auth) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const result = await apiJson<AuthState>("/auth/login", {
        method: "POST", body: JSON.stringify({ username, password }),
      });
      setAuth(result);
      const next = new URLSearchParams(location.search).get("next");
      navigate(next?.startsWith("/") && !next.startsWith("//") ? next : "/", { replace: true });
    } catch (requestError) {
      const apiError = requestError instanceof ApiError ? requestError : null;
      if (apiError?.code === "INVALID_CREDENTIALS") setError("用户名或密码错误");
      else if (apiError?.code === "ACCOUNT_LOCKED") setError("登录尝试过多，请稍后再试");
      else setError("登录失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <LoginLayout>
      <form className="auth-form login-form" onSubmit={submit}>
        <label>用户名<input autoFocus autoComplete="username" placeholder="请输入用户名" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
        <label>密码<input type="password" autoComplete="current-password" placeholder="请输入密码" aria-invalid={Boolean(error)} aria-describedby={error ? "login-error" : undefined} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {expiredNotice && <InlineMessage>登录状态已过期，请重新登录。</InlineMessage>}
        {error && <div id="login-error"><InlineMessage kind="error">{error}</InlineMessage></div>}
        <button className="primary-button" disabled={submitting}>{submitting ? "正在验证…" : "登录"}</button>
      </form>
      {registrationMode === "open" && <p className="login-register-link"><NavLink to="/register">创建测试人员账号</NavLink></p>}
    </LoginLayout>
  );
}

/** 自助注册永远只提交身份基础字段，角色与项目范围只能由服务端决定。 */
function RegisterPage() {
  const { auth, registrationMode, setAuth } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({
    username: "",
    display_name: "",
    password: "",
    confirm_password: "",
  });
  const [fieldErrors, setFieldErrors] = useState<{
    display_name?: string;
    password?: string;
    confirm_password?: string;
  }>({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  if (auth) return <Navigate to="/" replace />;
  if (registrationMode !== "open") {
    return (
      <LoginLayout
        title="暂未开放注册"
        copy="请使用已有账号登录，或联系平台管理员。"
      >
        <p className="login-register-link"><NavLink to="/login">返回登录</NavLink></p>
      </LoginLayout>
    );
  }

  function clearPasswordFields() {
    setValues((current) => ({ ...current, password: "", confirm_password: "" }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setError("");
    const nextErrors: typeof fieldErrors = {};
    if (!values.display_name.trim()) nextErrors.display_name = "显示名称不能为空";
    const passwordError = validateNewPassword(values.password);
    if (passwordError) nextErrors.password = passwordError;
    if (values.password !== values.confirm_password) nextErrors.confirm_password = "两次输入的密码不一致";
    setFieldErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      clearPasswordFields();
      return;
    }
    setSubmitting(true);
    try {
      // 显式构造三字段 body，确认密码和任何未来 UI 状态都不能越权提交给后端。
      const result = await apiJson<AuthState>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: values.username,
          display_name: values.display_name.trim(),
          password: values.password,
        }),
      });
      setAuth(result); navigate("/", { replace: true });
    } catch (requestError) {
      const apiError = requestError instanceof ApiError ? requestError : null;
      if (apiError?.status === 429 || apiError?.code === "REGISTRATION_RATE_LIMITED") {
        setError("操作过于频繁，请稍后重试。");
      } else if (apiError?.status === 422) {
        setError("请检查注册信息后重试。");
      } else if ([409, 503].includes(apiError?.status ?? 0) || apiError?.code === "REGISTRATION_UNAVAILABLE") {
        setError("暂时无法创建账号，请稍后重试。");
      } else {
        setError("注册失败，请稍后重试。");
      }
      clearPasswordFields();
    } finally { setSubmitting(false); }
  }
  return <LoginLayout title="创建测试人员账号" copy="账号创建后可立即使用已开放的公共工具。"><form className="auth-form login-form" onSubmit={submit}>
    <label>用户名<input autoFocus autoComplete="username" minLength={3} value={values.username} onChange={(event) => setValues({ ...values, username: event.target.value })} required /></label>
    <label>显示名称<input autoComplete="name" aria-invalid={Boolean(fieldErrors.display_name)} aria-describedby={fieldErrors.display_name ? "register-display-name-error" : undefined} value={values.display_name} onChange={(event) => setValues({ ...values, display_name: event.target.value })} required /></label>
    {fieldErrors.display_name && <span className="field-error" id="register-display-name-error" role="alert">{fieldErrors.display_name}</span>}
    <label>密码<input type="password" autoComplete="new-password" aria-invalid={Boolean(fieldErrors.password)} aria-describedby={fieldErrors.password ? "register-password-error" : undefined} value={values.password} onChange={(event) => setValues({ ...values, password: event.target.value })} required /></label>
    {fieldErrors.password && <span className="field-error" id="register-password-error" role="alert">{fieldErrors.password}</span>}
    <label>确认密码<input type="password" autoComplete="new-password" aria-invalid={Boolean(fieldErrors.confirm_password)} aria-describedby={fieldErrors.confirm_password ? "register-confirm-password-error" : undefined} value={values.confirm_password} onChange={(event) => setValues({ ...values, confirm_password: event.target.value })} required /></label>
    {fieldErrors.confirm_password && <span className="field-error" id="register-confirm-password-error" role="alert">{fieldErrors.confirm_password}</span>}
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <button className="primary-button" disabled={submitting}>{submitting ? "正在创建…" : "创建账号"}</button>
  </form><p className="login-register-link"><NavLink to="/login">返回登录</NavLink></p></LoginLayout>;
}

function LoginLayout({
  children,
  title = "欢迎回来",
  copy = "登录后继续你的测试工作",
}: PropsWithChildren<{ title?: string; copy?: string }>) {
  const [runtimeEnvironment, setRuntimeEnvironment] = useState("UNKNOWN");
  useEffect(() => {
    fetch("/version.json")
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((identity: Pick<RuntimeIdentity, "runtime_environment">) => setRuntimeEnvironment(identity.runtime_environment.toUpperCase()))
      .catch(() => undefined);
  }, []);
  return <div className="login-shell">
    <header className="login-header">
      <div className="login-header-content">
        <span className="brand"><span className="brand-mark" aria-hidden="true">T</span><span>测试开发平台</span></span>
        <nav className="login-capabilities" aria-label="平台能力预览"><span>工作台</span><span>AI 测试</span><span>自动化</span><span>质量分析</span><span>专项评测</span></nav>
        <div className="login-header-meta"><span>{runtimeEnvironment}</span><span>工程工作台</span></div>
      </div>
    </header>
    <main className="login-page">
      <section className="login-intro" aria-labelledby="login-platform-title">
        <div className="login-intro-content">
          <span className="brand-mark" aria-hidden="true">T</span>
          <h1 id="login-platform-title">测试开发平台</h1>
          <p>让每一次质量验证，都更高效。</p>
          <div className="login-value"><span aria-hidden="true" /><div><strong>统一管理测试资产</strong><small>用更清晰的方式推进质量协作</small></div></div>
          <p className="login-workspace">TEST PLATFORM · QUALITY WORKSPACE</p>
        </div>
      </section>
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-panel-heading"><h1 id="login-title">{title}</h1><p>{copy}</p></div>
        {children}
        <p className="login-help">遇到问题？请联系平台管理员</p>
      </section>
    </main>
    <footer className="login-footer">© {new Date().getFullYear()} Test Platform</footer>
  </div>;
}

function SetupPage() {
  const { auth, setAuth } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({ bootstrap_token: "", username: "", display_name: "", password: "" });
  const [error, setError] = useState("");
  if (auth) return <Navigate to="/" replace />;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    const passwordError = validateNewPassword(values.password);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    try {
      const result = await apiJson<AuthState>("/setup", { method: "POST", body: JSON.stringify(values) });
      setAuth(result);
      navigate("/", { replace: true });
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "初始化失败");
    }
  }
  return (
    <AuthLayout eyebrow="ONE-TIME SETUP" title="初始化平台管理员" copy="此入口仅在平台没有用户时有效。Bootstrap Token 不会保存在浏览器。">
      <form className="auth-form" onSubmit={submit}>
        <label>Bootstrap Token<input autoFocus type="password" autoComplete="off" value={values.bootstrap_token} onChange={(event) => setValues({ ...values, bootstrap_token: event.target.value })} required /></label>
        <label>用户名<input value={values.username} onChange={(event) => setValues({ ...values, username: event.target.value })} required /></label>
        <label>显示名<input value={values.display_name} onChange={(event) => setValues({ ...values, display_name: event.target.value })} required /></label>
        <label>密码<input type="password" autoComplete="new-password" value={values.password} onChange={(event) => setValues({ ...values, password: event.target.value })} required /></label>
        {error && <InlineMessage kind="error">{error}</InlineMessage>}
        <button className="primary-button">创建管理员</button>
      </form>
    </AuthLayout>
  );
}

function AuthLayout({ eyebrow, title, copy, children }: PropsWithChildren<{ eyebrow: string; title: string; copy: string }>) {
  return <main className="auth-page"><section className="auth-intro"><span className="brand-mark">T</span><p className="section-label">{eyebrow}</p><h1>{title}</h1><p>{copy}</p></section><section className="auth-panel">{children}</section></main>;
}

function Protected({ children, permission, roles }: PropsWithChildren<{ permission?: string; roles?: PlatformRole[] }>) {
  const { auth, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingPage />;
  if (!auth) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (auth.user.must_change_password && location.pathname !== "/account/password") return <Navigate to="/account/password" replace />;
  if (permission && !auth.platform_permissions.includes(permission)) return <Navigate to="/403" replace />;
  if (roles && (!auth.role || !roles.includes(auth.role))) return <Navigate to="/403" replace />;
  return children;
}

function ChangePasswordPage() {
  const { reload } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    const passwordError = validateNewPassword(values.new_password);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    try { await apiJson("/auth/change-password", { method: "POST", body: JSON.stringify(values) }); await reload(); navigate("/", { replace: true }); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "修改密码失败"); }
  }
  return <WorkspaceShell><section className="workspace-page narrow-page"><PageHeader eyebrow="ACCOUNT SECURITY" title="修改密码" copy="首次登录或管理员重置密码后，必须先设置只有你知道的新密码。" />{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="settings-card"><form className="auth-form" onSubmit={submit}><label>当前密码<input autoFocus type="password" autoComplete="current-password" value={values.current_password} onChange={(event) => setValues({ ...values, current_password: event.target.value })} required /></label><label>新密码<input type="password" autoComplete="new-password" value={values.new_password} onChange={(event) => setValues({ ...values, new_password: event.target.value })} required /></label><button className="primary-button">保存并撤销其他会话</button></form></div></section></WorkspaceShell>;
}

function AccountPage() {
  const { auth } = useAuth();
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(() => apiJson<UserSession[]>("/auth/sessions").then(setSessions), []);
  useEffect(() => { void load().catch((requestError) => setError(requestError.message)); }, [load]);
  async function revoke(session: UserSession) {
    setError(""); setMessage("");
    try { await apiJson(`/auth/sessions/${session.id}`, { method: "DELETE" }); setMessage("会话已撤销。"); await load(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "撤销失败"); }
  }
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow="ACCOUNT" title="账号与会话" copy={`${auth?.user.display_name ?? "当前用户"} · ${auth?.user.username ?? ""}`} actions={<NavLink className="secondary-button button-link" to="/account/password">修改密码</NavLink>} />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="data-panel"><div className="table-header"><span>会话</span><span>最近活动</span><span>绝对过期</span><span>操作</span></div>{sessions.map((session) => <div className="table-row" key={session.id}><strong>{session.current ? "当前会话" : "其他会话"}<small>{session.ip_address ?? "未知来源"}</small></strong><span>{new Date(session.last_seen_at).toLocaleString()}</span><span>{new Date(session.absolute_expires_at).toLocaleString()}</span>{session.current ? <StatusBadge value="active" /> : <button className="link-button" onClick={() => void revoke(session)}>撤销</button>}</div>)}</div></section></WorkspaceShell>;
}

function WorkspaceShell({ children }: PropsWithChildren) {
  const { auth, setAuth } = useAuth();
  const [environment, setEnvironment] = useState(() => sessionStorage.getItem("tp_environment") || "dev");
  const navigate = useNavigate();
  async function logout() {
    try { await apiJson("/auth/logout", { method: "POST" }); } finally {
      setAuth(null);
      navigate("/login", { replace: true });
    }
  }
  function changeEnvironment(value: string) {
    sessionStorage.setItem("tp_environment", value);
    setEnvironment(value);
    window.dispatchEvent(new CustomEvent("platform-environment-change", { detail: value }));
  }
  return <AppShell auth={auth} environment={environment} onEnvironmentChange={changeEnvironment} onLogout={() => void logout()}>{children}</AppShell>;
}

function HomePage() {
  const { tools, groups, unknownTools, healthStates, loading, refreshing, error, refreshHealth, reloadCatalog } = useToolCatalog();
  const [runtimeEnvironment, setRuntimeEnvironment] = useState("…");
  const aiCapabilities = groups["ai-testing"];
  const professionalCapabilities = [
    ...groups.automation,
    ...groups["quality-analysis"],
    ...groups["domain-evaluation"],
  ];
  const healthCounts = tools.reduce((counts, tool) => {
    counts[healthStates[tool.id] ?? "checking"] += 1;
    return counts;
  }, { checking: 0, healthy: 0, unhealthy: 0 });

  const refreshStatus = useCallback(async () => {
    const [, identity] = await Promise.all([
      refreshHealth(),
      apiJson<RuntimeIdentity>("/health/live"),
    ]);
    setRuntimeEnvironment(identity.runtime_environment.toUpperCase());
  }, [refreshHealth]);

  useEffect(() => {
    void apiJson<RuntimeIdentity>("/health/live")
      .then((identity) => setRuntimeEnvironment(identity.runtime_environment.toUpperCase()))
      .catch(() => setRuntimeEnvironment("未知"));
  }, []);

  return <WorkspaceShell><section className="workbench-home" aria-labelledby="workbench-title"><div className="workbench-intro"><div><p className="section-label">AI TESTING WORKSPACE</p><h1 id="workbench-title">AI 测试与质量工程工作台</h1><p>使用 AI 设计测试，通过自动化持续验证，并借助专业工具分析质量问题。</p></div><aside className="platform-status" aria-label="平台状态"><div className="status-panel-heading"><span>平台状态</span><button className="link-button" type="button" disabled={refreshing || loading} onClick={() => void refreshStatus()}>{refreshing ? "刷新中…" : "刷新状态"}</button></div><dl><div><dt>版本</dt><dd>{PLATFORM_VERSION}</dd></div><div><dt>运行环境</dt><dd>{runtimeEnvironment}</dd></div><div><dt>已授权</dt><dd>{tools.length}</dd></div><div><dt>异常</dt><dd>{healthCounts.unhealthy}</dd></div></dl><p>{healthCounts.healthy} 项正常 · {healthCounts.checking} 项检测中</p></aside></div>
    {error && <div className="catalog-state catalog-state-error" role="alert"><div><strong>平台身份或数据服务暂时不可用</strong><p>已停止工具导航，不会恢复匿名入口。{error}</p></div><button className="secondary-button" type="button" onClick={() => void reloadCatalog()}>重新加载目录</button></div>}
    {loading ? <div className="catalog-state" role="status"><span className="loading-indicator" />正在读取权限与能力目录…</div> : !error && <><section className="mission-section" aria-labelledby="mission-title"><div className="section-heading"><div><p className="section-label">我现在想做什么</p><h2 id="mission-title">从测试目标进入能力</h2></div></div>{aiCapabilities.length > 0 ? <div className="primary-capability-grid">{aiCapabilities.map((capability) => <CapabilityCard key={capability.toolId} capability={capability} />)}</div> : <EmptyState title="当前没有 AI 测试能力" copy="平台只展示服务端已授权的能力。" />}</section><section className="professional-section" aria-labelledby="professional-title"><div className="section-heading"><div><p className="section-label">持续验证与专业工具</p><h2 id="professional-title">让每项能力完成自己的使命</h2></div><span className="section-count">{professionalCapabilities.length} 项能力</span></div>{professionalCapabilities.length > 0 && <div className="professional-capability-grid">{professionalCapabilities.map((capability) => <CapabilityCard key={capability.toolId} capability={capability} compact />)}</div>}</section>{unknownTools.length > 0 && <section className="unknown-tools" aria-labelledby="unknown-tools-title"><h2 id="unknown-tools-title">其他已授权工具</h2><ToolGrid tools={unknownTools} healthStates={healthStates} /></section>}</>}
  </section></WorkspaceShell>;
}

/**
 * 权限与项目的功能总览。
 *
 * 这里仅聚合平台既有入口，不复制工具目录。可见性沿用固定角色和显式平台权限，
 * 因而前端导航不会把测试人员误导到只有平台管理员才能访问的控制面页面。
 */
function AccessHubPage() {
  const { auth } = useAuth();
  const has = (permission: string) => Boolean(auth?.platform_permissions.includes(permission));
  const isPlatformAdmin = auth?.role === "platform_admin";
  const groups = [
    {
      title: "项目与权限",
      copy: "查看所属项目；具备管理职责时可继续管理成员、工具范围与额外授权。",
      items: [
        { label: "我的项目", to: "/projects?scope=mine", description: "查看我参与或负责的项目" },
        ...(isPlatformAdmin ? [{ label: "项目管理", to: "/projects", description: "管理项目、人员及项目工具" }] : []),
        ...(isPlatformAdmin ? [
          { label: "用户管理", to: "/admin/users", description: "查看账号角色与权限全景" },
          { label: "工具管理", to: "/admin/tool-access", description: "设置公共或项目工具及归属" },
          { label: "额外授权", to: "/admin/tool-grants", description: "管理临时单工具访问" },
          { label: "固定角色", to: "/admin/roles", description: "查看三种固定角色权限矩阵" },
        ] : []),
      ],
    },
    {
      title: "个人设置",
      copy: "管理当前账号、个人凭证与个人模型配置。",
      items: [
        { label: "账号与会话", to: "/account", description: "查看账号信息和登录会话" },
        { label: "修改密码", to: "/account/password", description: "更新当前账号密码" },
        { label: "我的凭证", to: "/account/credentials", description: "维护个人工具凭证" },
        { label: "我的 LLM", to: "/account/llm", description: "维护个人模型与密钥" },
      ],
    },
    {
      title: "平台配置与运行",
      copy: "这些入口继续使用现有服务端权限校验，只向具备对应权限的账号展示。",
      items: [
        ...(isPlatformAdmin ? [{ label: "平台 LLM 配置", to: "/settings/platform-llm", description: "管理公共 Profile 与工具绑定" }] : []),
        ...(has("platform.config.manage") ? [{ label: "普通配置", to: "/settings/config", description: "管理非敏感平台配置" }] : []),
        ...(has("platform.secret.manage") ? [{ label: "Secret", to: "/settings/secrets", description: "管理共享 Secret 与版本" }] : []),
        ...(isPlatformAdmin ? [{ label: "凭证代理", to: "/settings/credential-agents", description: "管理平台凭证代理" }] : []),
        ...(has("platform.credential.readiness.view") ? [{ label: "凭证就绪度", to: "/settings/credentials", description: "检查工具凭证缺失与临期状态" }] : []),
        ...(has("platform.audit.view") ? [
          { label: "审计日志", to: "/audit", description: "追溯权限、配置与高风险操作" },
          { label: "版本状态", to: "/system/versions", description: "核对组件、配置和数据库版本" },
        ] : []),
      ],
    },
  ].filter((group) => group.items.length > 0);

  return <WorkspaceShell><section className="workspace-page access-page access-hub"><PageHeader eyebrow="ACCESS & PROJECTS" title="权限与项目" copy="集中查看项目、授权、个人设置及平台配置入口；工具仍从原工作台进入。" />
    <div className="access-hub-groups">{groups.map((group) => <section className="access-card access-hub-section" key={group.title}><div className="card-heading"><h2>{group.title}</h2><p>{group.copy}</p></div><div className="access-hub-grid">{group.items.map((item) => <NavLink className="access-hub-link" key={item.to} to={item.to}><strong>{item.label}</strong><span>{item.description}</span><span aria-hidden="true">→</span></NavLink>)}</div></section>)}</div>
  </section></WorkspaceShell>;
}

/** 权限控制台统一指标卡，避免每个列表页复制视觉结构。 */
function MetricCard({ label, value, note }: { label: string; value: ReactNode; note: string }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong><small>{note}</small></article>;
}

function PageHeader({ eyebrow, title, copy, actions }: { eyebrow: string; title: string; copy: string; actions?: ReactNode }) {
  return <div className="workspace-heading"><div><p className="section-label">{eyebrow}</p><h1>{title}</h1><p>{copy}</p></div>{actions}</div>;
}

function ManagementNav() {
  // 平台管理入口已统一进入 AppShell 左侧导航，页面内部不再重复一套横向菜单。
  return null;
}

function useEnvironment(): string {
  const [environment, setEnvironment] = useState(() => sessionStorage.getItem("tp_environment") || "dev");
  useEffect(() => {
    const listener = (event: Event) => setEnvironment((event as CustomEvent<string>).detail);
    window.addEventListener("platform-environment-change", listener);
    return () => window.removeEventListener("platform-environment-change", listener);
  }, []);
  return environment;
}

const API_AUTOTEST_TOOL_ID = "api-autotest";

type ConfigurationOwnerType = "tool" | "tool_project_scope";

interface ConfigurationToolOption {
  id: string;
  name: string;
  sortOrder: number;
}

/** 后端切换期间兼容列表数组与分页包装，未识别响应一律视为不可用而不猜测 Scope。 */
function runtimeScopesFromPayload(payload: unknown): RuntimeScope[] {
  if (Array.isArray(payload)) return payload as RuntimeScope[];
  if (payload && typeof payload === "object" && Array.isArray((payload as { items?: unknown }).items)) {
    return (payload as { items: RuntimeScope[] }).items;
  }
  return [];
}

/**
 * 统一解析配置控制面的工具与资源归属。
 *
 * 历史工具继续使用 ``owner_type=tool``，已有 Runtime Scope 的工具则使用
 * ``owner_type=tool_project_scope``。两类配置必须共存：Runtime Scope 的接入不能
 * 隐藏或迁移其他智能体已经发布的工具级 Release、Secret 与 Credential。
 *
 * Scope 深链仍只持久化 ``scope_id``；工具级页面只持久化非敏感的 ``tool_id``。
 * 平台项目、目标环境和 Release 等运行事实始终由服务端重新解析。
 */
function useConfigurationOwnerSelection(definitions: ConfigDefinition[]) {
  const environment = useEnvironment();
  const { tools, loading: toolsLoading } = useToolCatalog();
  const [searchParams, setSearchParams] = useSearchParams();
  const [scopes, setScopes] = useState<RuntimeScope[]>([]);
  const [loading, setLoading] = useState(true);
  const [scopeError, setScopeError] = useState("");
  const requestedScopeId = searchParams.get("scope_id");
  const requestedToolId = searchParams.get("tool_id");

  const load = useCallback(async () => {
    setLoading(true);
    setScopeError("");
    try {
      // 一次读取当前环境内所有授权 Scope，才能动态判断哪个工具采用项目级配置。
      const query = new URLSearchParams({ environment_id: environment });
      const payload = await apiJson<unknown>(`/runtime-scopes?${query.toString()}`);
      setScopes(runtimeScopesFromPayload(payload));
    } catch (requestError) {
      const message = requestError instanceof ApiError && requestError.status === 403
        ? "无权读取 Runtime Scope。平台不会显示未授权项目或配置。"
        : describeApiError(requestError, "无法加载 Runtime Scope，请稍后重试。");
      setScopes([]);
      setScopeError(message);
    } finally {
      setLoading(false);
    }
  }, [environment]);

  useEffect(() => { void load(); }, [load]);

  // 工具目录提供可读名称；定义与 Scope 兜底补回目录加载期间或兼容数据中的工具。
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  const toolIds = new Set<string>([
    ...tools.map((tool) => tool.id),
    ...definitions.filter((item) => item.owner_type === "tool").map((item) => item.owner_id),
    ...scopes.map((scope) => scope.tool_id),
  ]);
  const toolOptions: ConfigurationToolOption[] = [...toolIds]
    .map((toolId) => ({
      id: toolId,
      name: toolById.get(toolId)?.name ?? toolId,
      sortOrder: toolById.get(toolId)?.sort_order ?? Number.MAX_SAFE_INTEGER,
    }))
    .sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id));

  const requestedScope = scopes.find((scope) => scope.id === requestedScopeId) ?? null;
  const selectedToolId = requestedScope?.tool_id
    ?? (toolOptions.some((tool) => tool.id === requestedToolId) ? requestedToolId : null)
    ?? (toolOptions.some((tool) => tool.id === API_AUTOTEST_TOOL_ID) ? API_AUTOTEST_TOOL_ID : null)
    ?? toolOptions[0]?.id
    ?? "";
  const selectedTool = toolOptions.find((tool) => tool.id === selectedToolId) ?? null;
  const toolScopes = scopes.filter((scope) => scope.tool_id === selectedToolId);
  // api-autotest 即使尚无 Scope 也必须保持 Scope 模式，防止错误回退到工具级配置。
  const usesRuntimeScope = selectedToolId === API_AUTOTEST_TOOL_ID || toolScopes.length > 0;
  const selectedScope = usesRuntimeScope
    ? (requestedScope?.tool_id === selectedToolId ? requestedScope : null)
      ?? toolScopes.find((scope) => scope.status === "active" && scope.is_default)
      ?? toolScopes.find((scope) => scope.status === "active")
      ?? toolScopes[0]
      ?? null
    : null;
  const ownerType: ConfigurationOwnerType = usesRuntimeScope ? "tool_project_scope" : "tool";
  const ownerId = usesRuntimeScope ? selectedScope?.id ?? "" : selectedToolId;
  const ownerLabel = selectedScope?.display_name || selectedScope?.project_id || selectedTool?.name || selectedToolId;
  const ownerDisabled = !ownerId || (usesRuntimeScope && selectedScope?.status !== "active");

  useEffect(() => {
    if (loading || !selectedToolId) return;
    if (usesRuntimeScope && selectedScope) {
      if (requestedScopeId !== selectedScope.id || requestedToolId) {
        setSearchParams({ scope_id: selectedScope.id }, { replace: true });
      }
      return;
    }
    if (requestedToolId !== selectedToolId || requestedScopeId) {
      setSearchParams({ tool_id: selectedToolId }, { replace: true });
    }
  }, [loading, requestedScopeId, requestedToolId, selectedScope, selectedToolId, setSearchParams, usesRuntimeScope]);

  const selectTool = useCallback((toolId: string) => {
    const nextScopes = scopes.filter((scope) => scope.tool_id === toolId);
    const nextScope = nextScopes.find((scope) => scope.status === "active" && scope.is_default)
      ?? nextScopes.find((scope) => scope.status === "active")
      ?? nextScopes[0]
      ?? null;
    if (nextScope) setSearchParams({ scope_id: nextScope.id });
    else setSearchParams({ tool_id: toolId });
  }, [scopes, setSearchParams]);
  const selectScope = useCallback((scopeId: string) => setSearchParams({ scope_id: scopeId }), [setSearchParams]);

  return {
    environment,
    scopes,
    toolOptions,
    selectedTool,
    selectedToolId,
    toolScopes,
    selectedScope,
    usesRuntimeScope,
    ownerType,
    ownerId,
    ownerLabel,
    ownerDisabled,
    loading: loading || toolsLoading,
    scopeError,
    selectTool,
    selectScope,
    reloadScopes: load,
  };
}

function scopeTargetEnvironment(scope: RuntimeScope): string {
  return `${scope.target_env.toUpperCase()}（由 ${scope.environment_id.toUpperCase()} 平台固定）`;
}

/**
 * 所有配置页面共用一个工具选择器；只有采用项目隔离的工具才追加 Scope 字段。
 * 这样既保留旧工具的配置入口，也让后续新增 Scope 工具无需复制一套页面。
 */
function ConfigurationOwnerSelector({ selection, disabled = false }: {
  selection: ReturnType<typeof useConfigurationOwnerSelection>;
  disabled?: boolean;
}) {
  const {
    toolOptions, selectedTool, selectedToolId, toolScopes, selectedScope,
    usesRuntimeScope, loading, scopeError, selectTool, selectScope, environment,
  } = selection;
  if (loading && toolOptions.length === 0) return <div className="panel-loading scope-loading" role="status">正在加载配置归属…</div>;
  if (!selectedTool) return <EmptyState title="没有可管理的工具配置" copy="当前账号没有可管理工具，或平台尚未登记配置定义。" />;

  const platformProjects = [...new Map(toolScopes.map((scope) => [scope.platform_project_id, scope.platform_project_name ?? scope.platform_project_id])).entries()];
  const projectScopes = selectedScope
    ? toolScopes.filter((scope) => scope.platform_project_id === selectedScope.platform_project_id)
    : [];
  return <section className="scope-selector config-owner-selector" aria-label="配置归属选择">
    <label className="compact-field config-tool-field">工具 / 智能体<select aria-label="工具 / 智能体" value={selectedToolId} disabled={disabled} onChange={(event) => selectTool(event.target.value)}>{toolOptions.map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}</select></label>
    {usesRuntimeScope ? <>
      {scopeError && <div className="config-selector-wide"><InlineMessage kind="error">{scopeError}</InlineMessage></div>}
      {!scopeError && !selectedScope && <div className="config-selector-wide"><EmptyState title="没有可管理的 Runtime Scope" copy="请为该工具创建并授权 Scope；平台不会回退到工具级配置。" /></div>}
      {selectedScope && <>
        <label className="compact-field">平台项目<select aria-label="平台项目" value={selectedScope.platform_project_id} disabled={disabled} onChange={(event) => selectScope(toolScopes.find((scope) => scope.platform_project_id === event.target.value)?.id ?? selectedScope.id)}>{platformProjects.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label className="compact-field">工具项目<select aria-label="工具项目" value={selectedScope.id} disabled={disabled} onChange={(event) => selectScope(event.target.value)}>{projectScopes.map((scope) => <option key={scope.id} value={scope.id}>{scope.display_name || scope.project_id}</option>)}</select></label>
        <label className="compact-field">接口环境<input aria-label="接口环境" value={scopeTargetEnvironment(selectedScope)} readOnly disabled /></label>
        <div className="scope-selector-meta"><strong>{selectedScope.display_name || selectedScope.project_id}</strong><span>项目 Scope · <code>{selectedScope.id}</code> · Release: {selectedScope.active_release ? `v${selectedScope.active_release.version} ${selectedScope.active_release.status}` : "尚未发布"}</span><StatusBadge value={selectedScope.status} /></div>
      </>}
    </> : <>
      <label className="compact-field">配置归属<input aria-label="配置归属" value="工具级配置" readOnly disabled /></label>
      <label className="compact-field">平台环境<input aria-label="平台环境" value={environment.toUpperCase()} readOnly disabled /></label>
      <div className="scope-selector-meta"><strong>{selectedTool.name}</strong><span>工具级配置 · <code>{selectedTool.id}</code> · 继续使用已有 Release、Secret 与 Credential</span><StatusBadge value="active" /></div>
    </>}
  </section>;
}

function PersonalNav() {
  // 个人入口已统一进入“权限与项目”左侧导航，页面内部不再重复横向菜单。
  return null;
}

function providerDisplayName(providerType: string): string {
  if (providerType === "gateway_session") return "Gateway Session";
  if (providerType === "admin_login") return "Admin Login";
  return providerType;
}

/** 构造只携带 Scope 与逻辑 Provider 的个人凭证深链。 */
function credentialManagementPath(scopeId: string, providerType: string): string {
  const query = new URLSearchParams({ scope_id: scopeId, provider_type: providerType });
  return `/account/credentials?${query.toString()}`;
}

interface PersonalCredentialGroup {
  key: string;
  toolId: string;
  providerType: string;
  definitions: ConfigDefinition[];
  credential: PersonalCredential | null;
}

/**
 * 当前用户的个人凭证工作台。
 *
 * 首次配置所需字段来自服务端 user-scope 白名单；已保存值永不进入响应，所以
 * 所有输入每次打开都为空。留空代表沿用当前个人版本，成功后立即销毁输入状态。
 */
function PersonalCredentialsPage() {
  const environment = useEnvironment();
  const [definitions, setDefinitions] = useState<ConfigDefinition[]>([]);
  const ownerSelection = useConfigurationOwnerSelection(definitions);
  const [searchParams] = useSearchParams();
  const providerFilter = searchParams.get("provider_type");
  const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [editing, setEditing] = useState<PersonalCredentialGroup | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const [definitionRows, credentialRows] = await Promise.all([
      apiJson<ConfigDefinition[]>("/config/definitions"),
      apiJson<PersonalCredential[]>(`/me/credentials?environment_id=${encodeURIComponent(environment)}`),
    ]);
    setDefinitions(definitionRows.filter((row) => (
      row.owner_type === "tool"
      && row.value_scope === "user"
      && Boolean(row.credential_provider_type)
      && row.validation_schema?.runtime_config_excluded !== true
    )));
    setCredentials(credentialRows);
    setLoading(false);
  }, [environment]);

  useEffect(() => {
    let active = true;
    setError("");
    void load().catch((requestError) => {
      if (!active) return;
      setLoading(false);
      setError(describeApiError(requestError, "个人凭证加载失败"));
    });
    return () => { active = false; };
  }, [load]);
  useEffect(() => {
    setEditing(null);
    setValues({});
  }, [environment, ownerSelection.ownerId]);
  useModal(Boolean(editing), () => {
    setEditing(null);
    setValues({});
  });

  const groupMap = new Map<string, Omit<PersonalCredentialGroup, "credential">>();
  const hasCredentialOwner = !ownerSelection.usesRuntimeScope || Boolean(ownerSelection.selectedScope);
  if (hasCredentialOwner) {
    for (const definition of definitions) {
      if (!definition.credential_provider_type) continue;
      if (definition.owner_id !== ownerSelection.selectedToolId) continue;
      if (providerFilter && definition.credential_provider_type !== providerFilter) continue;
      const key = `${ownerSelection.ownerId}:${definition.owner_id}:${definition.credential_provider_type}`;
      const current = groupMap.get(key) ?? {
        key,
        toolId: definition.owner_id,
        providerType: definition.credential_provider_type,
        definitions: [],
      };
      current.definitions.push(definition);
      groupMap.set(key, current);
    }
  }
  const groups: PersonalCredentialGroup[] = [...groupMap.values()]
    .map((group) => ({
      ...group,
        definitions: [...group.definitions].sort((left, right) => left.sort_order - right.sort_order),
        credential: credentials.find((row) => (
          row.tool_id === group.toolId
          && row.provider_type === group.providerType
          && (row.runtime_scope_id ?? null) === (
            ownerSelection.usesRuntimeScope
              ? ownerSelection.selectedScope?.id ?? null
              : null
          )
        )) ?? null,
      }))
    .sort((left, right) => left.key.localeCompare(right.key));

  function openEditor(group: PersonalCredentialGroup) {
    setMessage("");
    setError("");
    setValues({});
    setEditing(group);
  }

  async function saveCredential(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setBusy(true);
    setError("");
    const submittedValues: Record<string, unknown> = {};
    for (const definition of editing.definitions) {
      const raw = values[definition.key] ?? "";
      if (raw === "") continue;
      if (definition.value_type === "int" || definition.value_type === "float") {
        submittedValues[definition.key] = Number(raw);
      } else if (definition.value_type === "bool") {
        submittedValues[definition.key] = raw === "true";
      } else {
        submittedValues[definition.key] = raw;
      }
    }
    try {
      await apiJson(`/me/credentials/${encodeURIComponent(editing.toolId)}/${encodeURIComponent(editing.providerType)}`, {
        method: "PUT",
        body: JSON.stringify({
          environment_id: environment,
          ...(ownerSelection.usesRuntimeScope && ownerSelection.selectedScope
            ? { runtime_scope_id: ownerSelection.selectedScope.id }
            : {}),
          expected_version: editing.credential?.current_version ?? 0,
          values: submittedValues,
        }),
      });
      // 成功后先销毁明文状态，再触发任何后续请求或 UI 更新。
      setValues({});
      setEditing(null);
      setMessage("凭证已保存，新任务将使用新版本。");
      await load();
    } catch (requestError) {
      // VERSION_CONFLICT 必须保留输入，便于用户刷新确认后决定是否重试。
      setError(describeApiError(requestError, "个人凭证保存失败"));
    } finally {
      setBusy(false);
    }
  }

  async function validateCredential(group: PersonalCredentialGroup) {
    if (!group.credential) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await apiJson<{ validation_state: string }>(
        `/me/credentials/${encodeURIComponent(group.credential.id)}/validate`,
        { method: "POST" },
      );
      setMessage(result.validation_state === "unsupported"
        ? "当前 Provider 暂不支持独立验证，刷新 Agent 会继续维护状态。"
        : "凭证验证已完成。");
      await load();
    } catch (requestError) {
      setError(describeApiError(requestError, "凭证验证失败"));
    } finally {
      setBusy(false);
    }
  }

  return <WorkspaceShell><section className="workspace-page personal-settings-page">
    <PageHeader eyebrow={`${environment.toUpperCase()} / PERSONAL CREDENTIALS`} title="我的凭证" copy="个人凭证按工具与 Runtime Scope 隔离。保存后平台只显示状态，不会再次回显账号、密码或 Token。" />
    <PersonalNav />
    <ConfigurationOwnerSelector selection={ownerSelection} />
    {message && <InlineMessage kind="success">{message}</InlineMessage>}
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    {ownerSelection.usesRuntimeScope && !ownerSelection.loading && !ownerSelection.selectedScope
      && <InlineMessage kind="error">当前工具没有可用的 Runtime Scope，不能读取或配置工具级兜底凭证。</InlineMessage>}
    {loading || ownerSelection.loading ? <div className="panel-loading" role="status">正在加载个人凭证…</div> : groups.length === 0
      ? <EmptyState title="没有可配置的个人凭证" copy="当前 Scope 没有匹配的 Provider，或工具尚未登记个人凭证字段。" />
      : <div className="personal-credential-grid">{groups.map((group) => {
        const configuredFields = new Map(
          (group.credential?.fields ?? []).map((field) => [field.key, field.configured]),
        );
        return <article className="personal-credential-card" key={group.key}>
          <header><div><h2>{providerDisplayName(group.providerType)}</h2><p>{ownerSelection.ownerLabel} · {group.toolId}</p></div><StatusBadge value={group.credential?.status ?? "missing"} /></header>
          <dl className="credential-summary"><div><dt>版本</dt><dd>v{group.credential?.current_version ?? 0}</dd></div><div><dt>过期时间</dt><dd>{group.credential?.expires_at ? new Date(group.credential.expires_at).toLocaleString() : "未提供"}</dd></div></dl>
          <ul className="credential-field-list">{group.definitions.map((definition) => <li key={definition.id}><span>{definition.display_name}<small>{definition.required ? "必填" : "可选"}</small></span><StatusBadge value={configuredFields.get(definition.key) ? "已配置" : "缺失"} /></li>)}</ul>
          {group.credential?.last_error_code && <p className="credential-error-code">最近错误：{group.credential.last_error_code}</p>}
          <div className="row-actions">
            <button className="primary-button" type="button" aria-label={`配置 ${group.toolId} ${providerDisplayName(group.providerType)}`} onClick={() => openEditor(group)}>配置</button>
            {group.credential && <button className="secondary-button" type="button" disabled={busy} onClick={() => void validateCredential(group)}>验证</button>}
          </div>
        </article>;
      })}</div>}
    {editing && <div className="modal-backdrop" role="presentation"><section className="dialog dialog-wide credential-dialog" role="dialog" aria-modal="true" aria-labelledby="personal-credential-dialog-title">
      <p className="section-label">{environment.toUpperCase()} / {editing.toolId}</p>
      <h2 id="personal-credential-dialog-title">配置 {providerDisplayName(editing.providerType)}</h2>
      <p>已配置字段可留空以沿用当前版本。Secret 保存成功后会立即从页面内存清除。</p>
      <form className="credential-form" onSubmit={saveCredential}>{editing.definitions.map((definition) => {
        const configured = editing.credential?.fields.some((field) => field.key === definition.key && field.configured) ?? false;
        const inputId = `personal-credential-${definition.id.replaceAll(".", "-")}`;
        return <div className="credential-input" key={definition.id}>
          <label htmlFor={inputId}>{definition.display_name}</label>
          <small>{definition.required ? "必填" : "可选"}，{configured ? "已配置，留空保留原值" : "尚未配置"}</small>
          {definition.value_type === "bool" ? <select id={inputId} value={values[definition.key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [definition.key]: event.target.value }))} required={definition.required && !configured}><option value="">请选择</option><option value="true">启用</option><option value="false">停用</option></select> : <input id={inputId} type={definition.sensitivity === "secret" ? "password" : definition.value_type === "int" || definition.value_type === "float" ? "number" : "text"} autoComplete={definition.sensitivity === "secret" ? "new-password" : "off"} value={values[definition.key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [definition.key]: event.target.value }))} required={definition.required && !configured} />}
        </div>;
      })}<div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => { setEditing(null); setValues({}); }}>取消</button><button className="primary-button" disabled={busy}>保存凭证</button></div></form>
    </section></div>}
  </section></WorkspaceShell>;
}

function LlmSettingsPage() {
  const { auth } = useAuth();
  const environment = useEnvironment();
  const canManageProfiles = Boolean(auth?.platform_permissions.includes("platform.llm.manage"));
  const canManageProfileSecrets = Boolean(auth?.platform_permissions.includes("platform.llm.secret.manage"));
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [bindings, setBindings] = useState<LlmBinding[]>([]);
  const [selection, setSelection] = useState<{ type: "llm_profile" | "llm_binding"; id: string } | null>(null);
  const [definitions, setDefinitions] = useState<ConfigDefinition[]>([]);
  const [releases, setReleases] = useState<ConfigRelease[]>([]);
  const [draft, setDraft] = useState<ConfigRelease | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [secretMetadata, setSecretMetadata] = useState<Record<string, SecretMetadata>>({});
  const [secretDefinition, setSecretDefinition] = useState<ConfigDefinition | null>(null);
  const [secretValue, setSecretValue] = useState("");
  const [creatingProfile, setCreatingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState({ name: "", description: "" });
  const [effective, setEffective] = useState<LlmEffectiveConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useModal(creatingProfile || Boolean(secretDefinition), () => {
    setCreatingProfile(false); setSecretDefinition(null); setSecretValue("");
  });

  const loadCatalog = useCallback(async () => {
    setError("");
    const [profileRows, bindingRows] = await Promise.all([
      canManageProfiles
        ? apiJson<LlmProfile[]>(`/llm/profiles?environment_id=${environment}`)
        : Promise.resolve([]),
      apiJson<LlmBinding[]>(`/llm/bindings?environment_id=${environment}`),
    ]);
    setProfiles(profileRows); setBindings(bindingRows);
    setSelection((current) => {
      const stillVisible = current && (current.type === "llm_profile"
        ? profileRows.some((item) => item.id === current.id)
        : bindingRows.some((item) => item.id === current.id));
      if (stillVisible) return current;
      if (profileRows[0]) return { type: "llm_profile", id: profileRows[0].id };
      if (bindingRows[0]) return { type: "llm_binding", id: bindingRows[0].id };
      return null;
    });
  }, [canManageProfiles, environment]);

  useEffect(() => { void loadCatalog().catch((requestError) => setError(requestError.message)); }, [loadCatalog]);
  useEffect(() => {
    if (!selection) { setDefinitions([]); setReleases([]); setDraft(null); return; }
    let active = true;
    setEffective(null);
    void Promise.all([
      apiJson<ConfigDefinition[]>(`/config/definitions?owner_type=${selection.type}&owner_id=${encodeURIComponent(selection.id)}`),
      apiJson<ConfigRelease[]>(`/config/releases?environment_id=${environment}&owner_type=${selection.type}&owner_id=${encodeURIComponent(selection.id)}`),
      apiJson<SecretMetadata[]>(`/secrets?environment_id=${environment}&owner_type=${selection.type}&owner_id=${encodeURIComponent(selection.id)}`).catch(() => []),
      selection.type === "llm_binding"
        ? apiJson<LlmEffectiveConfig>(`/llm/effective-config?environment_id=${environment}&binding_id=${encodeURIComponent(selection.id)}`).catch(() => null)
        : Promise.resolve(null),
    ]).then(([definitionRows, releaseRows, secrets, effectiveConfig]) => {
      if (!active) return;
      setDefinitions(definitionRows); setReleases(releaseRows);
      const currentDraft = releaseRows.find((row) => row.status === "draft") ?? null;
      setDraft(currentDraft);
      setValues(currentDraft ? Object.fromEntries(currentDraft.items.map((item) => [item.definition_id, item.value])) : {});
      setSecretMetadata(Object.fromEntries(secrets.map((item) => [item.definition_id, item])));
      setEffective(effectiveConfig);
    }).catch((requestError) => { if (active) setError(requestError.message); });
    return () => { active = false; };
  }, [selection, environment, message]);

  const selectedBinding = selection?.type === "llm_binding" ? bindings.find((item) => item.id === selection.id) : null;
  const selectedProfile = selection?.type === "llm_profile" ? profiles.find((item) => item.id === selection.id) : null;
  const normalDefinitions = definitions.filter((item) => item.sensitivity === "normal");
  const secretDefinitions = definitions.filter((item) => item.sensitivity === "secret");

  function valueFor(definition: ConfigDefinition): string {
    const value = values[definition.id] ?? definition.default_value ?? "";
    return definition.value_type === "json" && typeof value !== "string" ? JSON.stringify(value) : String(value);
  }
  function updateValue(definition: ConfigDefinition, raw: string) {
    let value: unknown = raw;
    if (["int", "float"].includes(definition.value_type)) value = raw === "" ? null : Number(raw);
    else if (definition.value_type === "bool") value = raw === "true";
    else if (definition.value_type === "json") {
      try { value = JSON.parse(raw); } catch { value = raw; }
    }
    setValues((current) => ({ ...current, [definition.id]: value }));
  }
  async function reloadSelection(success: string) {
    setMessage(success);
    await loadCatalog();
  }
  async function createProfile(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const created = await apiJson<LlmProfile>("/llm/profiles", { method: "POST", body: JSON.stringify({ ...profileForm, environment_id: environment }) });
      setCreatingProfile(false); setProfileForm({ name: "", description: "" });
      setSelection({ type: "llm_profile", id: created.id });
      await reloadSelection("公共 LLM Profile 已创建，请配置草稿和 API Key 后发布。");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建失败"); }
    finally { setBusy(false); }
  }
  async function createDraft() {
    if (!selection) return; setBusy(true); setError("");
    try {
      await apiJson("/config/releases", { method: "POST", body: JSON.stringify({ environment_id: environment, owner_type: selection.type, owner_id: selection.id }) });
      await reloadSelection("草稿已创建。");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建草稿失败"); }
    finally { setBusy(false); }
  }
  async function saveDraft() {
    if (!draft) return; setBusy(true); setError("");
    try {
      const items = normalDefinitions.flatMap((definition) => {
        const value = values[definition.id] ?? definition.default_value;
        return value === "" || value === null || value === undefined ? [] : [{ definition_id: definition.id, value }];
      });
      await apiJson(`/config/releases/${draft.id}/items`, { method: "PUT", body: JSON.stringify({ revision: draft.revision, items }) });
      await reloadSelection("草稿已保存。");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function releaseAction(action: "validate" | "publish" | "rollback", release = draft) {
    if (!release) return; setBusy(true); setError("");
    if (environment === "prod" && action !== "validate" && !window.confirm("确认在 PROD 执行此高风险配置操作？")) { setBusy(false); return; }
    try {
      await apiJson(`/config/releases/${release.id}/${action}`, { method: "POST" });
      await reloadSelection(action === "validate" ? "配置校验通过。" : action === "publish" ? "配置已发布，新任务将使用新快照。" : "已创建并激活新的回滚版本。");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "操作失败"); }
    finally { setBusy(false); }
  }
  async function saveSecret(event: FormEvent) {
    event.preventDefault(); if (!selection || !secretDefinition) return; setBusy(true); setError("");
    try {
      const secretId = `sec_${environment}_${secretDefinition.id.replaceAll(".", "_")}`;
      await apiJson(`/secrets/${encodeURIComponent(secretId)}`, { method: "PUT", body: JSON.stringify({
        environment_id: environment, owner_type: selection.type, owner_id: selection.id,
        definition_id: secretDefinition.id, value: secretValue,
      }) });
      setSecretValue(""); setSecretDefinition(null);
      await reloadSelection("API Key 新版本已加密保存；发布 Release 后任务才会使用该固定版本。");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Secret 保存失败"); }
    finally { setBusy(false); }
  }
  async function testConnection() {
    if (!selectedBinding) return; setBusy(true); setError(""); setMessage("");
    try {
      const result = await apiJson<{ checked_at: string }>("/llm/test-connection", { method: "POST", body: JSON.stringify({ environment_id: environment, binding_id: selectedBinding.id }) });
      setMessage(`连接验证成功 · ${new Date(result.checked_at).toLocaleString()}`);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "连接验证失败"); }
    finally { setBusy(false); }
  }
  async function toggleProfileArchive() {
    if (!selectedProfile) return;
    const action = selectedProfile.is_archived ? "restore" : "archive";
    if (!selectedProfile.is_archived && !window.confirm("归档后不能用于新绑定；确认继续？")) return;
    setBusy(true); setError("");
    try {
      await apiJson(`/llm/profiles/${selectedProfile.id}/${action}?environment_id=${environment}`, { method: "POST" });
      await reloadSelection(selectedProfile.is_archived ? "Profile 已恢复。" : "Profile 已归档。");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "操作失败"); }
    finally { setBusy(false); }
  }

  return <WorkspaceShell><section className="workspace-page llm-settings"><PageHeader eyebrow={`${environment.toUpperCase()} / LLM CONTROL PLANE`} title="LLM 统一配置" copy="公共 Profile 保存连接与模型；工具绑定只覆盖真实需要不同的参数。每次任务固定使用已发布快照。" actions={canManageProfiles ? <button className="primary-button" onClick={() => setCreatingProfile(true)}>创建 Profile</button> : undefined} /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="llm-layout"><aside className="llm-sidebar" aria-label="LLM 配置范围">{canManageProfiles && <section><h2>公共配置</h2>{profiles.map((profile) => <button key={profile.id} className={selection?.id === profile.id ? "selected" : ""} onClick={() => setSelection({ type: "llm_profile", id: profile.id })}><strong>{profile.name}</strong><span>{profile.active_release_version ? `v${profile.active_release_version}` : "未发布"} · {profile.api_key_configured ? "Key 已配置" : "缺少 Key"}</span></button>)}</section>}<section><h2>工具绑定</h2>{bindings.map((binding) => <button key={binding.id} className={selection?.id === binding.id ? "selected" : ""} onClick={() => setSelection({ type: "llm_binding", id: binding.id })}><strong>{binding.display_name}</strong><span>{binding.tool_id} / {binding.capability_key}</span></button>)}</section></aside><div className="llm-editor">{!selection ? <EmptyState title="没有可见的 LLM 配置" copy="当前账号没有 Profile 管理或工具查看权限。" /> : <><div className="config-toolbar"><div><strong>{selection.type === "llm_profile" ? selectedProfile?.name : selectedBinding?.display_name}</strong><span>{draft ? `v${draft.version} 草稿 · revision ${draft.revision}` : "当前没有草稿"}</span></div><div className="dialog-actions">{selectedProfile && <button className="secondary-button" disabled={busy} onClick={() => void toggleProfileArchive()}>{selectedProfile.is_archived ? "恢复" : "归档"}</button>}{selectedBinding?.active_release_id && <button className="secondary-button" disabled={busy} onClick={() => void testConnection()}>测试连接</button>}{!draft ? <button className="primary-button" disabled={busy} onClick={() => void createDraft()}>创建草稿</button> : <><button className="secondary-button" disabled={busy} onClick={() => void saveDraft()}>保存</button><button className="secondary-button" disabled={busy} onClick={() => void releaseAction("validate")}>校验</button><button className="primary-button" disabled={busy} onClick={() => void releaseAction("publish")}>发布</button></>}</div></div>{effective && <dl className="llm-effective"><div><dt>当前模型</dt><dd>{effective.model}</dd></div><div><dt>公共配置</dt><dd>{effective.profile_name}</dd></div><div><dt>快照</dt><dd>{effective.snapshot_id.slice(0, 18)}…</dd></div><div><dt>Secret</dt><dd>{effective.api_key_configured ? "已配置" : "缺失"}</dd></div></dl>}<div className="config-grid">{normalDefinitions.map((definition) => <label className="config-field" key={definition.id}><span>{definition.display_name}<small>{definition.key} · {definition.required ? "必填" : "留空沿用 Provider 默认"}</small></span>{definition.key === "PROFILE_ID" && profiles.length > 0 ? <select disabled={!draft} value={valueFor(definition)} onChange={(event) => updateValue(definition, event.target.value)}>{profiles.filter((item) => !item.is_archived).map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select> : definition.value_type === "bool" ? <select disabled={!draft} value={valueFor(definition)} onChange={(event) => updateValue(definition, event.target.value)}><option value="true">启用</option><option value="false">停用</option></select> : <input disabled={!draft} type={["int", "float"].includes(definition.value_type) ? "number" : "text"} step={definition.value_type === "float" ? "any" : undefined} value={valueFor(definition)} onChange={(event) => updateValue(definition, event.target.value)} />}</label>)}</div>{secretDefinitions.length > 0 && <section className="llm-secret-panel" aria-labelledby="llm-secret-title"><div><h2 id="llm-secret-title">API Key</h2><p>Secret 保存后不回显；发布时固定当前版本。</p></div>{secretDefinitions.map((definition) => <div key={definition.id}><span>{definition.display_name}</span><StatusBadge value={secretMetadata[definition.id]?.configured ? `v${secretMetadata[definition.id].version}` : "missing"} /><button className="secondary-button" disabled={selection.type === "llm_profile" ? !canManageProfileSecrets : false} onClick={() => setSecretDefinition(definition)}>替换</button></div>)}</section>}<section className="release-history"><h2>版本历史</h2>{releases.length === 0 ? <EmptyState title="尚无版本" copy="创建草稿后在这里完成校验、发布和回滚。" /> : releases.map((release) => <div className="release-row" key={release.id}><div><strong>v{release.version}</strong><span>{new Date(release.created_at).toLocaleString()}</span></div><StatusBadge value={release.status} /><div className="row-actions">{["active", "superseded"].includes(release.status) && <button className="secondary-button" onClick={() => void releaseAction("rollback", release)}>回滚到此版本</button>}</div></div>)}</section></>}</div></div>{creatingProfile && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="profile-dialog-title"><p className="section-label">{environment.toUpperCase()} / PROFILE</p><h2 id="profile-dialog-title">创建公共 LLM Profile</h2><form className="auth-form" onSubmit={createProfile}><label>名称<input autoFocus value={profileForm.name} onChange={(event) => setProfileForm({ ...profileForm, name: event.target.value })} required /></label><label>说明<textarea value={profileForm.description} onChange={(event) => setProfileForm({ ...profileForm, description: event.target.value })} /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setCreatingProfile(false)}>取消</button><button className="primary-button" disabled={busy}>创建</button></div></form></section></div>}{secretDefinition && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="llm-secret-dialog-title"><p className="section-label">{environment.toUpperCase()} / SECRET</p><h2 id="llm-secret-dialog-title">替换 {secretDefinition.display_name}</h2><p>明文只停留在当前输入组件内存，保存后立即清空。</p><form className="auth-form" onSubmit={saveSecret}><label>API Key<input autoFocus type="password" autoComplete="off" value={secretValue} onChange={(event) => setSecretValue(event.target.value)} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => { setSecretDefinition(null); setSecretValue(""); }}>取消</button><button className="primary-button" disabled={busy}>加密保存</button></div></form></section></div>}</section></WorkspaceShell>;
}

interface PersonalProfileForm {
  name: string;
  description: string;
  base_url: string;
  model: string;
  api_key: string;
  temperature: string;
  max_tokens: string;
  timeout_seconds: string;
  enabled: boolean;
}

const emptyPersonalProfileForm = (): PersonalProfileForm => ({
  name: "",
  description: "",
  base_url: "",
  model: "",
  api_key: "",
  temperature: "",
  max_tokens: "",
  timeout_seconds: "",
  enabled: true,
});

/** 个人 LLM Profile 与能力 Binding 编辑器，不调用 legacy 公共 LLM 接口。 */
function PersonalLlmPage() {
  const environment = useEnvironment();
  const [profiles, setProfiles] = useState<PersonalLlmProfile[]>([]);
  const [bindings, setBindings] = useState<PersonalLlmBinding[]>([]);
  const [selection, setSelection] = useState<{ kind: "profile" | "binding"; id: string } | null>(null);
  const [profileDialog, setProfileDialog] = useState<"create" | "edit" | null>(null);
  const [profileForm, setProfileForm] = useState<PersonalProfileForm>(emptyPersonalProfileForm);
  const [bindingDialog, setBindingDialog] = useState<PersonalLlmBinding | null>(null);
  const [bindingForm, setBindingForm] = useState({ profile_id: "", enabled: true, model_override: "", temperature_override: "", max_tokens_override: "", timeout_seconds_override: "", api_key_override: "" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const clearDialogs = useCallback(() => {
    setProfileDialog(null);
    setProfileForm(emptyPersonalProfileForm());
    setBindingDialog(null);
    setBindingForm({ profile_id: "", enabled: true, model_override: "", temperature_override: "", max_tokens_override: "", timeout_seconds_override: "", api_key_override: "" });
  }, []);
  useModal(Boolean(profileDialog || bindingDialog), clearDialogs);

  const load = useCallback(async () => {
    setLoading(true);
    const [profileRows, bindingRows] = await Promise.all([
      apiJson<PersonalLlmProfile[]>(`/me/llm/profiles?environment_id=${encodeURIComponent(environment)}`),
      apiJson<PersonalLlmBinding[]>(`/me/llm/bindings?environment_id=${encodeURIComponent(environment)}`),
    ]);
    setProfiles(profileRows);
    setBindings(bindingRows);
    setSelection((current) => {
      if (current?.kind === "profile" && profileRows.some((row) => row.id === current.id)) return current;
      if (current?.kind === "binding" && bindingRows.some((row) => row.binding_id === current.id)) return current;
      if (profileRows[0]) return { kind: "profile", id: profileRows[0].id };
      if (bindingRows[0]) return { kind: "binding", id: bindingRows[0].binding_id };
      return null;
    });
    setLoading(false);
  }, [environment]);

  useEffect(() => {
    let active = true;
    setError("");
    clearDialogs();
    void load().catch((requestError) => {
      if (!active) return;
      setLoading(false);
      setError(describeApiError(requestError, "个人 LLM 加载失败"));
    });
    return () => { active = false; };
  }, [clearDialogs, load]);

  const selectedProfile = selection?.kind === "profile"
    ? profiles.find((row) => row.id === selection.id) ?? null
    : null;
  const selectedBinding = selection?.kind === "binding"
    ? bindings.find((row) => row.binding_id === selection.id) ?? null
    : null;

  function optionalNumber(value: string): number | null {
    return value.trim() ? Number(value) : null;
  }

  function openCreateProfile() {
    setError("");
    setMessage("");
    setProfileForm(emptyPersonalProfileForm());
    setProfileDialog("create");
  }

  function openEditProfile(profile: PersonalLlmProfile) {
    setError("");
    setMessage("");
    setProfileForm({
      name: profile.name,
      description: profile.description,
      base_url: profile.base_url ?? "",
      model: profile.model ?? "",
      // API 只返回 configured 状态，编辑表单永远不能从响应回填 Key。
      api_key: "",
      temperature: profile.temperature?.toString() ?? "",
      max_tokens: profile.max_tokens?.toString() ?? "",
      timeout_seconds: profile.timeout_seconds?.toString() ?? "",
      enabled: profile.enabled ?? true,
    });
    setProfileDialog("edit");
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const payload: Record<string, unknown> = {
      name: profileForm.name,
      description: profileForm.description,
      environment_id: environment,
      provider: "openai_compatible",
      base_url: profileForm.base_url,
      model: profileForm.model,
      temperature: optionalNumber(profileForm.temperature),
      max_tokens: optionalNumber(profileForm.max_tokens),
      timeout_seconds: optionalNumber(profileForm.timeout_seconds),
      enabled: profileForm.enabled,
    };
    if (profileForm.api_key) payload.api_key = profileForm.api_key;
    try {
      const saved = profileDialog === "create"
        ? await apiJson<PersonalLlmProfile>("/me/llm/profiles", { method: "POST", body: JSON.stringify(payload) })
        : await apiJson<PersonalLlmProfile>(`/me/llm/profiles/${encodeURIComponent(selectedProfile?.id ?? "")}`, { method: "PATCH", body: JSON.stringify(payload) });
      setProfileForm(emptyPersonalProfileForm());
      setProfileDialog(null);
      setSelection({ kind: "profile", id: saved.id });
      setMessage(profileDialog === "create" ? "个人 LLM 连接已创建并发布。" : "个人 LLM 连接已更新，新任务将使用新版本。");
      await load();
    } catch (requestError) {
      setError(describeApiError(requestError, "个人 LLM 保存失败"));
    } finally {
      setBusy(false);
    }
  }

  function openBinding(binding: PersonalLlmBinding) {
    setError("");
    setMessage("");
    setBindingForm({
      profile_id: binding.profile_id ?? "",
      enabled: binding.enabled ?? true,
      model_override: binding.model_override ?? "",
      temperature_override: binding.temperature_override?.toString() ?? "",
      max_tokens_override: binding.max_tokens_override?.toString() ?? "",
      timeout_seconds_override: binding.timeout_seconds_override?.toString() ?? "",
      api_key_override: "",
    });
    setBindingDialog(binding);
  }

  async function saveBinding(event: FormEvent) {
    event.preventDefault();
    if (!bindingDialog) return;
    setBusy(true);
    setError("");
    const payload: Record<string, unknown> = {
      environment_id: environment,
      expected_version: bindingDialog.current_version,
      profile_id: bindingForm.profile_id || null,
      enabled: bindingForm.enabled,
      model_override: bindingForm.model_override || null,
      temperature_override: optionalNumber(bindingForm.temperature_override),
      max_tokens_override: optionalNumber(bindingForm.max_tokens_override),
      timeout_seconds_override: optionalNumber(bindingForm.timeout_seconds_override),
      clear_api_key_override: false,
    };
    if (bindingForm.api_key_override) payload.api_key_override = bindingForm.api_key_override;
    try {
      await apiJson(`/me/llm/bindings/${encodeURIComponent(bindingDialog.binding_id)}`, { method: "PUT", body: JSON.stringify(payload) });
      setBindingForm((current) => ({ ...current, api_key_override: "" }));
      setBindingDialog(null);
      setMessage("个人能力绑定已发布，新任务将使用固定快照。");
      await load();
    } catch (requestError) {
      setError(describeApiError(requestError, "能力绑定保存失败"));
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchive(profile: PersonalLlmProfile) {
    if (!profile.is_archived && !window.confirm("该连接归档后不能用于新绑定，确认继续？")) return;
    setBusy(true);
    setError("");
    const action = profile.is_archived ? "restore" : "archive";
    try {
      await apiJson(`/me/llm/profiles/${encodeURIComponent(profile.id)}/${action}?environment_id=${encodeURIComponent(environment)}`, { method: "POST" });
      setMessage(profile.is_archived ? "个人 LLM 连接已恢复。" : "个人 LLM 连接已归档。");
      await load();
    } catch (requestError) {
      setError(describeApiError(requestError, "连接状态更新失败"));
    } finally {
      setBusy(false);
    }
  }

  async function testBinding(binding: PersonalLlmBinding) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await apiJson<{ checked_at: string; model: string }>("/me/llm/test-connection", { method: "POST", body: JSON.stringify({ environment_id: environment, binding_id: binding.binding_id }) });
      setMessage(`连接验证成功，模型 ${result.model}，检查时间 ${new Date(result.checked_at).toLocaleString()}。`);
    } catch (requestError) {
      setError(describeApiError(requestError, "连接验证失败"));
    } finally {
      setBusy(false);
    }
  }

  return <WorkspaceShell><section className="workspace-page llm-settings personal-settings-page">
    <PageHeader eyebrow={`${environment.toUpperCase()} / PERSONAL LLM`} title="我的 LLM" copy="连接、API Key 和工具能力绑定仅供你自己的任务使用。每次保存都会发布不可变新版本。" actions={<button className="primary-button" onClick={openCreateProfile}>创建连接</button>} />
    <PersonalNav />
    {message && <InlineMessage kind="success">{message}</InlineMessage>}
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    {loading ? <div className="panel-loading" role="status">正在加载个人 LLM…</div> : <div className="llm-layout"><aside className="llm-sidebar" aria-label="个人 LLM 配置范围">
      <section><h2>我的连接</h2>{profiles.map((profile) => <button key={profile.id} className={selection?.kind === "profile" && selection.id === profile.id ? "selected" : ""} onClick={() => setSelection({ kind: "profile", id: profile.id })}><strong>{profile.name}</strong><span>v{profile.active_release_version ?? 0} / {profile.api_key_configured ? "Key 已配置" : "缺少 Key"}</span></button>)}</section>
      <section><h2>能力绑定</h2>{bindings.map((binding) => <button key={binding.binding_id} className={selection?.kind === "binding" && selection.id === binding.binding_id ? "selected" : ""} onClick={() => setSelection({ kind: "binding", id: binding.binding_id })}><strong>{binding.display_name}</strong><span>{binding.tool_id} / {binding.capability_key}</span></button>)}</section>
    </aside><div className="llm-editor">{!selection ? <EmptyState title="尚未配置个人 LLM" copy="创建一个连接后，再把它绑定到你有执行权限的工具能力。" /> : selectedProfile ? <>
      <div className="config-toolbar"><div><strong>{selectedProfile.name}</strong><span>仅你的任务使用 / v{selectedProfile.active_release_version ?? 0}</span></div><div className="dialog-actions"><button className="secondary-button" disabled={busy} onClick={() => void toggleArchive(selectedProfile)}>{selectedProfile.is_archived ? "恢复" : "归档"}</button><button className="primary-button" onClick={() => openEditProfile(selectedProfile)}>编辑连接</button></div></div>
      <dl className="llm-effective"><div><dt>模型</dt><dd>{selectedProfile.model ?? "未配置"}</dd></div><div><dt>Provider</dt><dd>{selectedProfile.provider}</dd></div><div><dt>API Key</dt><dd>{selectedProfile.api_key_configured ? "已配置" : "缺失"}</dd></div><div><dt>绑定数</dt><dd>{selectedProfile.binding_count}</dd></div></dl>
      <section className="personal-llm-details"><h2>连接参数</h2><dl><div><dt>Base URL</dt><dd>{selectedProfile.base_url ?? "未配置"}</dd></div><div><dt>Temperature</dt><dd>{selectedProfile.temperature ?? "Provider 默认"}</dd></div><div><dt>Max Tokens</dt><dd>{selectedProfile.max_tokens ?? "Provider 默认"}</dd></div><div><dt>超时</dt><dd>{selectedProfile.timeout_seconds ? `${selectedProfile.timeout_seconds} 秒` : "Provider 默认"}</dd></div></dl></section>
    </> : selectedBinding ? <>
      <div className="config-toolbar"><div><strong>{selectedBinding.display_name}</strong><span>{selectedBinding.tool_id} / {selectedBinding.capability_key} / v{selectedBinding.current_version}</span></div><div className="dialog-actions">{selectedBinding.current_version > 0 && <button className="secondary-button" disabled={busy} onClick={() => void testBinding(selectedBinding)}>测试连接</button>}<button className="primary-button" onClick={() => openBinding(selectedBinding)}>配置能力绑定</button></div></div>
      <dl className="llm-effective"><div><dt>状态</dt><dd>{selectedBinding.enabled ? "启用" : "停用"}</dd></div><div><dt>个人连接</dt><dd>{profiles.find((profile) => profile.id === selectedBinding.profile_id)?.name ?? "未绑定"}</dd></div><div><dt>模型覆盖</dt><dd>{selectedBinding.model_override ?? "无"}</dd></div><div><dt>独立 Key</dt><dd>{selectedBinding.api_key_override_configured ? "已配置" : "沿用连接"}</dd></div></dl>
    </> : <EmptyState title="配置已不可用" copy="请刷新页面后重新选择。" />}</div></div>}
    {profileDialog && <div className="modal-backdrop" role="presentation"><section className="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="personal-profile-dialog-title"><p className="section-label">{environment.toUpperCase()} / PERSONAL PROFILE</p><h2 id="personal-profile-dialog-title">{profileDialog === "create" ? "创建个人 LLM 连接" : `编辑 ${selectedProfile?.name ?? "个人连接"}`}</h2><p>API Key 不会回填。编辑时留空即可沿用已发布版本。</p><form className="profile-form" onSubmit={saveProfile}><div className="profile-form-grid"><label>名称<input autoFocus value={profileForm.name} onChange={(event) => setProfileForm({ ...profileForm, name: event.target.value })} required /></label><label>模型<input value={profileForm.model} onChange={(event) => setProfileForm({ ...profileForm, model: event.target.value })} required /></label><label className="profile-form-wide">Base URL<input type="url" value={profileForm.base_url} onChange={(event) => setProfileForm({ ...profileForm, base_url: event.target.value })} required /></label><label className="profile-form-wide">{profileDialog === "create" ? "API Key" : "API Key（留空沿用现有值）"}<input type="password" autoComplete="new-password" value={profileForm.api_key} onChange={(event) => setProfileForm({ ...profileForm, api_key: event.target.value })} required={profileDialog === "create"} /></label><label>Temperature<input type="number" step="any" value={profileForm.temperature} onChange={(event) => setProfileForm({ ...profileForm, temperature: event.target.value })} /></label><label>Max Tokens<input type="number" value={profileForm.max_tokens} onChange={(event) => setProfileForm({ ...profileForm, max_tokens: event.target.value })} /></label><label>超时秒数<input type="number" value={profileForm.timeout_seconds} onChange={(event) => setProfileForm({ ...profileForm, timeout_seconds: event.target.value })} /></label><label className="checkbox-row"><input type="checkbox" checked={profileForm.enabled} onChange={(event) => setProfileForm({ ...profileForm, enabled: event.target.checked })} />启用连接</label><label className="profile-form-wide">说明<textarea value={profileForm.description} onChange={(event) => setProfileForm({ ...profileForm, description: event.target.value })} /></label></div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={clearDialogs}>取消</button><button className="primary-button" disabled={busy}>保存连接</button></div></form></section></div>}
    {bindingDialog && <div className="modal-backdrop" role="presentation"><section className="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="personal-binding-dialog-title"><p className="section-label">{environment.toUpperCase()} / PERSONAL BINDING</p><h2 id="personal-binding-dialog-title">配置 {bindingDialog.display_name}</h2><p>发布后只影响你在该工具上的新任务，不会改变其他用户配置。</p><form className="profile-form" onSubmit={saveBinding}><div className="profile-form-grid"><label className="profile-form-wide">个人 Profile<select value={bindingForm.profile_id} onChange={(event) => setBindingForm({ ...bindingForm, profile_id: event.target.value })} required={bindingForm.enabled}><option value="">不绑定</option>{profiles.filter((profile) => !profile.is_archived).map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label><label>模型覆盖<input value={bindingForm.model_override} onChange={(event) => setBindingForm({ ...bindingForm, model_override: event.target.value })} /></label><label>Temperature 覆盖<input type="number" step="any" value={bindingForm.temperature_override} onChange={(event) => setBindingForm({ ...bindingForm, temperature_override: event.target.value })} /></label><label>Max Tokens 覆盖<input type="number" value={bindingForm.max_tokens_override} onChange={(event) => setBindingForm({ ...bindingForm, max_tokens_override: event.target.value })} /></label><label>超时秒数覆盖<input type="number" value={bindingForm.timeout_seconds_override} onChange={(event) => setBindingForm({ ...bindingForm, timeout_seconds_override: event.target.value })} /></label><label className="profile-form-wide">独立 API Key（留空沿用当前设置）<input type="password" autoComplete="new-password" value={bindingForm.api_key_override} onChange={(event) => setBindingForm({ ...bindingForm, api_key_override: event.target.value })} /></label><label className="checkbox-row"><input type="checkbox" checked={bindingForm.enabled} onChange={(event) => setBindingForm({ ...bindingForm, enabled: event.target.checked })} />启用该能力</label></div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={clearDialogs}>取消</button><button className="primary-button" disabled={busy}>保存能力绑定</button></div></form></section></div>}
  </section></WorkspaceShell>;
}

/** 判断 Tool 级 Definition 是否属于当前工具项目；未声明项目白名单时保持兼容。 */
function definitionAppliesToProject(definition: ConfigDefinition, projectId: string | null): boolean {
  const projectIds = definition.validation_schema.project_ids;
  if (projectIds === undefined) return true;
  return Boolean(projectId) && Array.isArray(projectIds) && projectIds.includes(projectId);
}

/** 把不可变 Release 的普通配置项转换为页面值；切换历史版本时不会复用旧草稿状态。 */
function valuesFromRelease(release: ConfigRelease | null): Record<string, unknown> {
  return release ? Object.fromEntries(release.items.map((item) => [item.definition_id, item.value])) : {};
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function stringRecord(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"));
}

/**
 * Gateway comm 结构化编辑器。
 *
 * 已登记字段按服务端 field_order 展示，项目新增的未知静态字段也可直接添加；
 * 会话与单次请求字段由 forbidden_keys 排除，页面从不把它们当成可配置值。
 */
function GatewayCommEditor({
  definition,
  value,
  editable,
  onChange,
}: {
  definition: ConfigDefinition;
  value: unknown;
  editable: boolean;
  onChange: (value: Record<string, string>) => void;
}) {
  const schema = definition.validation_schema;
  const fieldOrder = stringArray(schema.field_order);
  const fieldLabels = stringRecord(schema.field_labels);
  const requiredKeys = new Set(stringArray(schema.required_keys));
  const forbiddenKeys = new Set(stringArray(schema.forbidden_keys));
  const comm = stringRecord(value);
  const extraKeys = Object.keys(comm)
    .filter((key) => !fieldOrder.includes(key) && !forbiddenKeys.has(key))
    .sort((left, right) => left.localeCompare(right));
  const keys = [...fieldOrder, ...extraKeys];
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [fieldError, setFieldError] = useState("");

  function replaceField(key: string, nextValue: string) {
    const next = Object.fromEntries(
      Object.entries({ ...comm, [key]: nextValue }).filter(([itemKey]) => !forbiddenKeys.has(itemKey)),
    );
    onChange(next);
  }

  function removeField(key: string) {
    const next = { ...comm };
    delete next[key];
    onChange(next);
  }

  function addField(event: FormEvent) {
    event.preventDefault();
    const key = newKey.trim();
    if (forbiddenKeys.has(key)) {
      setFieldError(`${key} 由运行时生成，不能保存为静态配置。`);
      return;
    }
    const pattern = typeof schema.property_name_pattern === "string"
      ? new RegExp(schema.property_name_pattern)
      : /^[a-z][a-z0-9_]{0,63}$/;
    if (!pattern.test(key)) {
      setFieldError("参数名必须以小写字母开头，且只能包含小写字母、数字和下划线。");
      return;
    }
    if (keys.includes(key)) {
      setFieldError(`${key} 已存在，请直接修改现有值。`);
      return;
    }
    setFieldError("");
    onChange({ ...comm, [key]: newValue });
    setNewKey("");
    setNewValue("");
  }

  return <section className="config-field config-field-wide gateway-comm-editor" aria-labelledby={`comm-title-${definition.id}`}>
    <div className="gateway-comm-heading"><div><strong id={`comm-title-${definition.id}`}>{definition.display_name}</strong><small>{definition.key} · 仅静态参数</small></div><p>Token、用户 ID 与请求 ID 由每次任务运行时生成，不在 Release 中配置。</p></div>
    <div className="gateway-comm-grid">{keys.map((key) => {
      const label = fieldLabels[key] ?? key;
      const custom = !fieldOrder.includes(key);
      return <label className="gateway-comm-item" key={key}>
        <span>{label}<small>{key} · {requiredKeys.has(key) ? "必填" : "可选"}</small></span>
        <span className="gateway-comm-control"><input aria-label={label} disabled={!editable} value={comm[key] ?? ""} onChange={(event) => replaceField(key, event.target.value)} required={requiredKeys.has(key)} />{editable && custom && <button type="button" className="link-button destructive-link" aria-label={`删除 ${key}`} onClick={() => removeField(key)}>删除</button>}</span>
      </label>;
    })}</div>
    {editable && <form className="gateway-comm-add" onSubmit={addField}>
      <label>静态参数名<input aria-label="静态参数名" value={newKey} onChange={(event) => setNewKey(event.target.value)} placeholder="例如 channel" required /></label>
      <label>静态参数值<input aria-label="静态参数值" value={newValue} onChange={(event) => setNewValue(event.target.value)} placeholder="字符串值" required /></label>
      <button className="secondary-button" type="submit">添加静态参数</button>
    </form>}
    {fieldError && <p className="gateway-comm-error" role="alert">{fieldError}</p>}
  </section>;
}

function ConfigPage() {
  const [items, setItems] = useState<ConfigDefinition[]>([]);
  const ownerSelection = useConfigurationOwnerSelection(items);
  const {
    environment, selectedScope: scope, selectedToolId, ownerType, ownerId,
    ownerLabel, ownerDisabled, usesRuntimeScope,
  } = ownerSelection;
  const [releases, setReleases] = useState<ConfigRelease[]>([]);
  const [draft, setDraft] = useState<ConfigRelease | null>(null);
  const [viewedReleaseId, setViewedReleaseId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [scopeEditor, setScopeEditor] = useState<"create" | "edit" | null>(null);
  const [scopeForm, setScopeForm] = useState({ platform_project_id: "", project_id: "", display_name: "", status: "active", is_default: false });
  const [scopeCredentials, setScopeCredentials] = useState<PersonalCredential[]>([]);
  const [scopeCredentialsLoading, setScopeCredentialsLoading] = useState(false);
  const [scopeCredentialsError, setScopeCredentialsError] = useState("");
  const ownerItems = items.filter((item) => (
    item.owner_type === "tool"
    && item.owner_id === selectedToolId
    && item.value_scope === "system"
    && item.sensitivity === "normal"
    && definitionAppliesToProject(item, usesRuntimeScope ? scope?.project_id ?? null : null)
  ));
  const viewedRelease = releases.find((release) => release.id === viewedReleaseId) ?? null;
  const editingDraft = Boolean(draft && viewedRelease?.id === draft.id);

  const loadReleases = useCallback(async (selectedOwnerType: ConfigurationOwnerType, selectedOwnerId: string, enabled: boolean) => {
    if (!selectedOwnerId || !enabled) {
      setReleases([]); setDraft(null); setViewedReleaseId(null); setValues({}); return;
    }
    const query = new URLSearchParams({ environment_id: environment, owner_type: selectedOwnerType, owner_id: selectedOwnerId });
    const rows = await apiJson<ConfigRelease[]>(`/config/releases?${query.toString()}`);
    setReleases(rows);
    const currentDraft = rows.find((row) => row.status === "draft") ?? null;
    const currentRelease = currentDraft ?? rows.find((row) => row.status === "active") ?? rows[0] ?? null;
    setDraft(currentDraft);
    setViewedReleaseId(currentRelease?.id ?? null);
    setValues(valuesFromRelease(currentRelease));
  }, [environment]);

  useEffect(() => {
    void apiJson<ConfigDefinition[]>("/config/definitions").then((rows) => {
      setItems(rows);
    }).catch((requestError) => setError(requestError.message));
  }, []);
  useEffect(() => {
    const enabled = !ownerDisabled && ownerItems.length > 0;
    void loadReleases(ownerType, ownerId, enabled).catch((requestError) => setError(describeApiError(requestError, "无法读取当前配置归属的 Release。")));
  }, [loadReleases, ownerDisabled, ownerId, ownerItems.length, ownerType]);
  useEffect(() => {
    if (!usesRuntimeScope || !scope || scope.status !== "active") {
      setScopeCredentials([]);
      setScopeCredentialsError("");
      setScopeCredentialsLoading(false);
      return;
    }
    let active = true;
    setScopeCredentialsLoading(true);
    setScopeCredentialsError("");
    const query = new URLSearchParams({
      environment_id: environment,
      runtime_scope_id: scope.id,
    });
    void apiJson<PersonalCredential[]>(`/me/credentials?${query.toString()}`)
      .then((rows) => {
        if (active) setScopeCredentials(rows.filter((row) => (
          row.tool_id === selectedToolId && row.runtime_scope_id === scope.id
        )));
      })
      .catch((requestError) => {
        if (active) {
          setScopeCredentials([]);
          setScopeCredentialsError(describeApiError(requestError, "当前 Scope 的个人凭证状态加载失败。"));
        }
      })
      .finally(() => { if (active) setScopeCredentialsLoading(false); });
    return () => { active = false; };
  }, [environment, scope, selectedToolId, usesRuntimeScope]);
  useEffect(() => { setConfirmPublish(false); }, [environment]);

  function inputValue(definition: ConfigDefinition): string | number {
    const value = values[definition.id] ?? definition.default_value ?? "";
    if (definition.value_type === "json" && typeof value !== "string") return JSON.stringify(value);
    return typeof value === "number" ? value : String(value);
  }
  function updateValue(definition: ConfigDefinition, rawValue: string) {
    let value: unknown = rawValue;
    if (["int", "integer", "float"].includes(definition.value_type)) value = rawValue === "" ? null : Number(rawValue);
    if (["bool", "boolean"].includes(definition.value_type)) value = rawValue === "true";
    setValues((current) => ({ ...current, [definition.id]: value }));
  }
  function payloadValue(definition: ConfigDefinition): unknown {
    const value = values[definition.id] ?? definition.default_value;
    let parsed = value;
    if (definition.value_type === "json" && typeof value === "string") {
      try { parsed = JSON.parse(value); }
      catch { throw new Error(`${definition.display_name} 必须是有效 JSON。`); }
    }
    if (definition.key === "gateway.comm" && parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const forbiddenKeys = new Set(stringArray(definition.validation_schema.forbidden_keys));
      return Object.fromEntries(Object.entries(parsed).filter(([key]) => !forbiddenKeys.has(key)));
    }
    return parsed;
  }
  function viewRelease(release: ConfigRelease) {
    setError("");
    setMessage("");
    setViewedReleaseId(release.id);
    setValues(valuesFromRelease(release));
  }
  /** Scope 身份字段只在创建时提交；编辑始终带 revision，避免覆盖其他管理员的并发变更。 */
  function openScopeEditor(mode: "create" | "edit") {
    setError("");
    setScopeEditor(mode);
    setScopeForm(mode === "edit" && scope ? {
      platform_project_id: scope.platform_project_id, project_id: scope.project_id, display_name: scope.display_name,
      status: scope.status, is_default: scope.is_default,
    } : { platform_project_id: "", project_id: "", display_name: "", status: "active", is_default: false });
  }
  async function saveScope(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      if (scopeEditor === "edit" && scope) {
        await apiJson(`/runtime-scopes/${encodeURIComponent(scope.id)}`, { method: "PATCH", body: JSON.stringify({ display_name: scopeForm.display_name, status: scopeForm.status, is_default: scopeForm.is_default, revision: scope.revision }) });
        setMessage("Runtime Scope 已更新。Release、Secret 与 Credential 将继续按该 Scope 隔离。");
      } else if (scopeEditor === "create") {
        // target_env 为只读派生值，服务端仍会忽略客户端推导并强制校验 dev→test / prod→prod。
        const targetEnv = environment === "prod" ? "prod" : "test";
        const next = await apiJson<RuntimeScope>("/runtime-scopes", { method: "POST", body: JSON.stringify({ environment_id: environment, tool_id: selectedToolId, platform_project_id: scopeForm.platform_project_id, project_id: scopeForm.project_id, target_env: targetEnv, display_name: scopeForm.display_name, is_default: scopeForm.is_default }) });
        ownerSelection.selectScope(next.id);
        setMessage("Runtime Scope 已创建。请创建并发布首个 Release 后再提交新任务。");
      }
      setScopeEditor(null);
      await ownerSelection.reloadScopes();
    } catch (requestError) { setError(describeApiError(requestError, "Runtime Scope 保存失败。")); }
  }
  async function createDraft() {
    if (!ownerId || ownerDisabled || ownerItems.length === 0) return;
    setError(""); setMessage("");
    try {
      const next = await apiJson<ConfigRelease>("/config/releases", { method: "POST", body: JSON.stringify({ environment_id: environment, owner_type: ownerType, owner_id: ownerId }) });
      setDraft(next); setViewedReleaseId(next.id); setValues(valuesFromRelease(next)); setMessage(`已创建 v${next.version} 草稿。`);
      await loadReleases(ownerType, ownerId, true);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建草稿失败"); }
  }
  async function saveDraft() {
    if (!draft || !ownerId || ownerDisabled) return;
    setError(""); setMessage("");
    try {
      const releaseItems = ownerItems.flatMap((item) => {
        const value = payloadValue(item);
        return value === undefined || value === null ? [] : [{ definition_id: item.id, value }];
      });
      const updated = await apiJson<ConfigRelease>(`/config/releases/${draft.id}/items`, { method: "PUT", body: JSON.stringify({ revision: draft.revision, items: releaseItems }) });
      setDraft(updated); setMessage(`v${updated.version} 草稿已保存。`); await loadReleases(ownerType, ownerId, true);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "保存失败"); }
  }
  async function releaseAction(action: "validate" | "publish", target = draft) {
    if (!target || !ownerId || ownerDisabled) return;
    if (action === "publish" && environment === "prod" && !confirmPublish) {
      setConfirmPublish(true); setMessage("这是 PROD 发布。请复核差异后再次点击“确认发布 PROD”。"); return;
    }
    setError(""); setMessage("");
    try {
      await apiJson(`/config/releases/${target.id}/${action}`, { method: "POST" });
      setMessage(action === "validate" ? "配置校验通过。" : `v${target.version} 已发布；新任务将使用该版本。`);
      setConfirmPublish(false);
      await loadReleases(ownerType, ownerId, true);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "操作失败"); }
  }
  async function rollback(target: ConfigRelease) {
    if (!ownerId || ownerDisabled) return;
    setError(""); setMessage("");
    try {
      const next = await apiJson<ConfigRelease>(`/config/releases/${target.id}/rollback`, { method: "POST" });
      setMessage(`已基于 v${target.version} 创建回滚版本 v${next.version}。`); await loadReleases(ownerType, ownerId, true);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "回滚失败"); }
  }
  async function promote(target: ConfigRelease) {
    setError(""); setMessage("");
    try {
      const next = await apiJson<ConfigRelease>(`/config/releases/${target.id}/promote?target_environment=prod`, { method: "POST" });
      setMessage(`已从 DEV v${target.version} 创建 PROD v${next.version} 草稿；Secret 未复制。`);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "提升失败"); }
  }

  const scopeActions = usesRuntimeScope ? <div className="dialog-actions">
    <button className="secondary-button" disabled={!scope} onClick={() => openScopeEditor("edit")}>编辑 Scope</button>
    <button className="primary-button" onClick={() => openScopeEditor("create")}>新建 Scope</button>
  </div> : undefined;

  return <WorkspaceShell><section className="workspace-page">
    <PageHeader eyebrow={`${environment.toUpperCase()} / CONFIGURATION`} title="配置控制面" copy="统一管理所有工具与智能体配置；多项目工具按 Runtime Scope 隔离，其他工具继续使用原有工具级版本。" actions={scopeActions} />
    <ManagementNav />
    {message && <InlineMessage kind="success">{message}</InlineMessage>}
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <ConfigurationOwnerSelector selection={ownerSelection} />
    {scope?.status === "disabled" && <InlineMessage kind="error">该 Runtime Scope 已停用。为避免新任务误用历史配置，不能读取或修改它的 Release、Secret 或 Credential。</InlineMessage>}
    {scope?.status === "disabled" && ownerItems.length === 0 && <div className="config-toolbar"><div><strong>{ownerLabel}</strong><span>Scope 已停用，不读取配置值</span></div><button className="primary-button" disabled>创建草稿</button></div>}
    {ownerSelection.selectedTool && ownerItems.length === 0 && <EmptyState title="该工具尚未登记普通配置" copy="工具入口仍然保留；登记 ConfigDefinition 后即可在此创建、校验和发布版本。" />}
    {ownerId && ownerItems.length > 0 && <>
      <div className="config-toolbar"><div><strong>{ownerLabel}</strong><span>{viewedRelease
        ? viewedRelease.status === "draft" ? `v${viewedRelease.version} 草稿 · revision ${viewedRelease.revision}`
          : viewedRelease.status === "active" ? `v${viewedRelease.version} · 当前生效`
            : `v${viewedRelease.version} · 历史版本`
        : "当前没有已发布版本"}</span></div><div className="dialog-actions">{!draft
        ? <button className="primary-button" disabled={ownerDisabled} onClick={() => void createDraft()}>创建草稿</button>
        : editingDraft
          ? <><button className="secondary-button" disabled={ownerDisabled} onClick={() => void saveDraft()}>保存草稿</button><button className="secondary-button" disabled={ownerDisabled} onClick={() => void releaseAction("validate")}>校验</button><button className="primary-button" disabled={ownerDisabled} onClick={() => void releaseAction("publish")}>{environment === "prod" && confirmPublish ? "确认发布 PROD" : "发布"}</button></>
          : <button className="primary-button" disabled={ownerDisabled} onClick={() => draft && viewRelease(draft)}>继续编辑 v{draft.version} 草稿</button>}</div></div>
      <div className="config-grid">{ownerItems.map((item) => item.key === "gateway.comm"
        ? <GatewayCommEditor key={`${viewedRelease?.id ?? "none"}:${item.id}`} definition={item} value={values[item.id] ?? item.default_value} editable={editingDraft && !ownerDisabled} onChange={(value) => setValues((current) => ({ ...current, [item.id]: value }))} />
        : <label className="config-field" key={item.id}><span>{item.display_name}<small>{item.key} · {item.apply_mode}</small></span>{["bool", "boolean"].includes(item.value_type)
          ? <select disabled={!editingDraft || ownerDisabled} value={String(values[item.id] ?? item.default_value ?? false)} onChange={(event) => updateValue(item, event.target.value)}><option value="true">true</option><option value="false">false</option></select>
          : <input disabled={!editingDraft || ownerDisabled} type={["int", "integer", "float"].includes(item.value_type) ? "number" : "text"} step={item.value_type === "float" ? "any" : undefined} value={inputValue(item)} onChange={(event) => updateValue(item, event.target.value)} required={item.required} />}</label>)}</div>
      {usesRuntimeScope && scope && <section className="scope-credential-panel" aria-labelledby="scope-credential-title">
        <header><div><h2 id="scope-credential-title">个人凭证（不属于普通 Release）</h2><p>Secret 与会话由个人凭证独立管理；这里只显示当前 Scope 的非敏感状态。</p></div></header>
        {scopeCredentialsError && <InlineMessage kind="error">{scopeCredentialsError}</InlineMessage>}
        {scopeCredentialsLoading ? <div className="panel-loading" role="status">正在加载当前 Scope 的凭证状态…</div> : scopeCredentials.length === 0
          ? <EmptyState title="当前 Scope 尚未配置个人凭证" copy="任务实际需要哪个 Profile 由资产预检决定；请从任务错误中的入口定位。" />
          : <div className="scope-credential-list">{scopeCredentials.map((credential) => <article className="scope-credential-row" key={credential.id}>
            <div><strong>{providerDisplayName(credential.provider_type)}</strong><span>v{credential.current_version} · 过期时间 {credential.expires_at ? new Date(credential.expires_at).toLocaleString() : "未提供"}</span>{credential.last_error_code && <code>最近错误：{credential.last_error_code}</code>}</div>
            <StatusBadge value={credential.status} />
            <NavLink className="secondary-button" aria-label={`管理 ${providerDisplayName(credential.provider_type)}`} to={credentialManagementPath(scope.id, credential.provider_type)}>管理</NavLink>
          </article>)}</div>}
      </section>}
      <section className="release-history" aria-labelledby="release-history-title"><h2 id="release-history-title">版本历史</h2>{releases.length === 0
        ? <EmptyState title="尚无版本" copy="创建首个草稿后，版本记录会显示在这里。" />
        : releases.map((release) => <div className={`release-row ${viewedRelease?.id === release.id ? "release-row-selected" : ""}`} key={release.id}><div><strong>v{release.version}</strong><span>revision {release.revision} · {new Date(release.created_at).toLocaleString()}</span></div><StatusBadge value={release.status} /><div className="row-actions"><button className="link-button" disabled={viewedRelease?.id === release.id} aria-label={`查看 v${release.version} 配置`} onClick={() => viewRelease(release)}>查看配置</button>{release.status === "active" || release.status === "superseded" ? <button className="secondary-button" disabled={ownerDisabled} onClick={() => void rollback(release)}>回滚到此版本</button> : null}{environment === "dev" && release.status === "active" ? <button className="secondary-button" disabled={ownerDisabled} onClick={() => void promote(release)}>提升为 PROD 草稿</button> : null}</div></div>)}</section>
    </>}
    {scopeEditor && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="scope-dialog-title"><p className="section-label">{environment.toUpperCase()} / RUNTIME SCOPE</p><h2 id="scope-dialog-title">{scopeEditor === "create" ? "新建 Runtime Scope" : "编辑 Runtime Scope"}</h2><p>接口环境由平台固定，不能在此切换；所有 Release、Secret 与 Credential 都归属此 Scope。</p><form className="auth-form" onSubmit={saveScope}>{scopeEditor === "create" && <><label>平台项目 ID<input value={scopeForm.platform_project_id} onChange={(event) => setScopeForm({ ...scopeForm, platform_project_id: event.target.value })} required /></label><label>工具项目键<input value={scopeForm.project_id} onChange={(event) => setScopeForm({ ...scopeForm, project_id: event.target.value })} pattern="[a-z][a-z0-9-]{0,31}" required /></label></>}<label>Scope 显示名称<input autoFocus value={scopeForm.display_name} onChange={(event) => setScopeForm({ ...scopeForm, display_name: event.target.value })} required /></label><label>接口环境<input value={environment === "prod" ? "PROD（由 PROD 平台固定）" : "TEST（由 DEV 平台固定）"} readOnly disabled /></label>{scopeEditor === "edit" && <label>状态<select value={scopeForm.status} onChange={(event) => setScopeForm({ ...scopeForm, status: event.target.value })}><option value="active">启用</option><option value="disabled">停用</option></select></label>}<label className="checkbox-row"><input type="checkbox" checked={scopeForm.is_default} onChange={(event) => setScopeForm({ ...scopeForm, is_default: event.target.checked })} />作为当前平台项目默认 Scope</label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setScopeEditor(null)}>取消</button><button className="primary-button">保存 Scope</button></div></form></section></div>}
  </section></WorkspaceShell>;
}

function SecretsPage() {
  const [definitions, setDefinitions] = useState<ConfigDefinition[]>([]);
  const ownerSelection = useConfigurationOwnerSelection(definitions);
  const {
    environment, selectedScope: scope, selectedToolId, ownerType, ownerId,
    ownerLabel, ownerDisabled,
  } = ownerSelection;
  const [metadata, setMetadata] = useState<Record<string, SecretMetadata>>({});
  const [selected, setSelected] = useState<ConfigDefinition | null>(null);
  const [secretValue, setSecretValue] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const secretDefinitions = definitions.filter((row) => (
    row.owner_type === "tool"
    && row.owner_id === selectedToolId
    && row.sensitivity === "secret"
    && row.value_scope === "system"
  ));
  useModal(Boolean(selected), () => { setSelected(null); setSecretValue(""); });
  useEffect(() => { void apiJson<ConfigDefinition[]>("/config/definitions").then(setDefinitions).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    if (!ownerId || ownerDisabled || secretDefinitions.length === 0) { setMetadata({}); return; }
    const query = new URLSearchParams({ environment_id: environment, owner_type: ownerType, owner_id: ownerId });
    void apiJson<SecretMetadata[]>(`/secrets?${query.toString()}`)
      .then((rows) => setMetadata(Object.fromEntries(rows.map((item) => [item.definition_id, item]))))
      .catch((requestError) => setError(describeApiError(requestError, "无法读取当前配置归属的 Secret 状态。")));
  }, [environment, message, ownerDisabled, ownerId, ownerType, secretDefinitions.length]);
  async function save(event: FormEvent) {
    event.preventDefault(); if (!selected || !ownerId || ownerDisabled) return;
    setError(""); setMessage("");
    // 工具级 Secret 沿用历史稳定 ID；Scope Secret 使用 scope_id，避免项目间冲突。
    const secretOwnerKey = ownerType === "tool_project_scope" ? ownerId : environment;
    const secretId = `sec_${secretOwnerKey}_${selected.id.replaceAll(".", "_")}`;
    try {
      await apiJson(`/secrets/${encodeURIComponent(secretId)}`, { method: "PUT", body: JSON.stringify({ environment_id: environment, owner_type: ownerType, owner_id: ownerId, definition_id: selected.id, value: secretValue }) });
      setSecretValue(""); setSelected(null); setMessage("Secret 新版本已加密保存并激活。");
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
  }
  const editable = !ownerDisabled && secretDefinitions.length > 0;
  return <WorkspaceShell><section className="workspace-page">
    <PageHeader eyebrow={`${environment.toUpperCase()} / SECRETS`} title="Secret 管理" copy="按工具或项目 Scope 管理 Secret；明文只停留在当前输入组件内存，保存后不会再次回显。" />
    <ManagementNav />
    {message && <InlineMessage kind="success">{message}</InlineMessage>}
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <ConfigurationOwnerSelector selection={ownerSelection} />
    {scope?.status === "disabled" && <InlineMessage kind="error">该 Runtime Scope 已停用，Secret 仅保留历史审计，不可读取或替换。</InlineMessage>}
    {ownerSelection.selectedTool && <div className="data-panel">{secretDefinitions.length === 0
      ? <EmptyState title="该工具尚未登记平台 Secret" copy="个人凭证字段请在“我的凭证”维护；工具级或 Scope 级 Secret 需先登记系统配置定义。" />
      : <><div className="table-header secret-columns"><span>Secret</span><span>配置归属</span><span>状态</span><span>操作</span></div>{secretDefinitions.map((item) => <div className="table-row secret-columns" key={item.id}><strong>{item.display_name}<small>{item.key}</small></strong><span>{ownerLabel}</span><StatusBadge value={metadata[item.id]?.configured ? `v${metadata[item.id].version}` : "missing"} /><button className="secondary-button" disabled={!editable} onClick={() => { setSelected(item); setSecretValue(""); setMessage(""); }}>替换</button></div>)}</>}</div>}
    {selected && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="secret-dialog-title"><p className="section-label">{environment.toUpperCase()} / {ownerId}</p><h2 id="secret-dialog-title">替换 {selected.display_name}</h2><p>新版本保存成功后立即激活，旧版本只用于历史追溯；平台不会回显现有值。</p><form className="auth-form" onSubmit={save}><label>Secret 新值<textarea autoFocus value={secretValue} onChange={(event) => setSecretValue(event.target.value)} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setSelected(null)}>取消</button><button className="primary-button">加密保存</button></div></form></section></div>}
  </section></WorkspaceShell>;
}

function CredentialsPage() {
  const [definitions, setDefinitions] = useState<ConfigDefinition[]>([]);
  const ownerSelection = useConfigurationOwnerSelection(definitions);
  const {
    environment, selectedScope: scope, selectedToolId, ownerId, ownerLabel,
    ownerDisabled, usesRuntimeScope,
  } = ownerSelection;
  const [items, setItems] = useState<CredentialMetadata[]>([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ provider_type: "gateway_session" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useModal(creating, () => setCreating(false));
  useEffect(() => { void apiJson<ConfigDefinition[]>("/config/definitions").then(setDefinitions).catch((requestError) => setError(describeApiError(requestError, "无法加载工具凭证定义。"))); }, []);
  const load = useCallback(() => {
    if (!selectedToolId || ownerDisabled) { setItems([]); return Promise.resolve(); }
    const query = new URLSearchParams({ environment_id: environment });
    if (usesRuntimeScope && scope) query.set("runtime_scope_id", scope.id);
    return apiJson<CredentialMetadata[]>(`/credentials?${query.toString()}`).then((rows) => {
      // 后端兼容接口暂不接受 tool_id；工具级结果必须在前端再次收窄且排除 Scope 数据。
      setItems(usesRuntimeScope ? rows : rows.filter((row) => row.tool_id === selectedToolId && !row.runtime_scope_id));
    });
  }, [environment, ownerDisabled, scope, selectedToolId, usesRuntimeScope]);
  useEffect(() => { void load().catch((requestError) => setError(requestError.message)); }, [load]);
  async function createCredential(event: FormEvent) {
    event.preventDefault(); setError(""); setMessage("");
    if (!selectedToolId || !ownerId || ownerDisabled) return;
    const payload = { ...form, tool_id: selectedToolId, environment_id: environment, ...(usesRuntimeScope && scope ? { runtime_scope_id: scope.id } : {}) };
    try { await apiJson("/credentials", { method: "POST", body: JSON.stringify(payload) }); setCreating(false); setMessage("Credential 已创建，Agent 将在下一轮执行首次验证。 "); await load(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建失败"); }
  }
  const editable = Boolean(ownerId) && !ownerDisabled;
  return <WorkspaceShell><section className="workspace-page">
    <PageHeader eyebrow={`${environment.toUpperCase()} / CREDENTIALS`} title="凭证健康" copy="统一查看工具级与项目 Scope 凭证；平台只展示状态、版本和过期时间，不显示 Token 或密码。" actions={<button className="primary-button" disabled={!editable} onClick={() => setCreating(true)}>创建 Credential</button>} />
    <ManagementNav />
    {message && <InlineMessage kind="success">{message}</InlineMessage>}
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <ConfigurationOwnerSelector selection={ownerSelection} />
    {scope?.status === "disabled" && <InlineMessage kind="error">该 Runtime Scope 已停用，Credential 状态不再对新任务可用。</InlineMessage>}
    {ownerSelection.selectedTool && <div className="data-panel">{items.length === 0
      ? <EmptyState title="尚未创建 Credential" copy={`完成${usesRuntimeScope ? "当前 Scope" : "当前工具"}的 Secret 导入后创建 Credential，刷新 Agent 会负责登录和续期。`} />
      : items.map((item) => <div className="table-row" key={item.id}><strong>{ownerLabel}<small>{item.provider_type}</small></strong><span>{usesRuntimeScope && scope ? scope.target_env.toUpperCase() : environment.toUpperCase()}</span><StatusBadge value={item.status} /><span>{item.expires_at ? new Date(item.expires_at).toLocaleString() : "无过期时间"}</span></div>)}</div>}
    {creating && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="credential-dialog-title"><p className="section-label">{environment.toUpperCase()} / {ownerId}</p><h2 id="credential-dialog-title">创建自动维护凭证</h2><p>先在 Secret 页面导入当前配置归属所需的账号或 Token。创建后 Agent 才会尝试验证、登录和续期。</p><form className="auth-form" onSubmit={createCredential}><label>工具<input autoFocus value={selectedToolId} readOnly /></label><label>Provider<select value={form.provider_type} onChange={(event) => setForm({ ...form, provider_type: event.target.value })}><option value="gateway_session">Gateway Session</option><option value="admin_login">Admin Login</option></select></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setCreating(false)}>取消</button><button className="primary-button">创建并等待验证</button></div></form></section></div>}
  </section></WorkspaceShell>;
}

/** 管理员只读就绪度视图，所有筛选均只传元数据且页面不提供代改入口。 */
function CredentialReadinessPage() {
  const environment = useEnvironment();
  const [items, setItems] = useState<CredentialReadiness[]>([]);
  const [filters, setFilters] = useState({ user_id: "", tool_id: "", provider_type: "", status: "" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const query = new URLSearchParams({ environment_id: environment });
    for (const [key, value] of Object.entries(filters)) {
      if (value) query.set(key, value);
    }
    const rows = await apiJson<CredentialReadiness[]>(`/admin/credential-readiness?${query.toString()}`);
    setItems(rows);
    setLoading(false);
  }, [environment, filters]);

  useEffect(() => {
    let active = true;
    setError("");
    void load().catch((requestError) => {
      if (!active) return;
      setLoading(false);
      setError(describeApiError(requestError, "凭证就绪度加载失败"));
    });
    return () => { active = false; };
  }, [load]);

  return <WorkspaceShell><section className="workspace-page readiness-page">
    <PageHeader eyebrow={`${environment.toUpperCase()} / READINESS`} title="凭证就绪度" copy="只读查看全员个人凭证与 LLM 能力是否可用。平台不会解密、导出或代替用户修改 Secret。" />
    <ManagementNav />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <div className="readiness-filters" aria-label="就绪度筛选">
      <label>用户 ID<input aria-label="筛选用户" value={filters.user_id} onChange={(event) => setFilters((current) => ({ ...current, user_id: event.target.value }))} /></label>
      <label>工具<input aria-label="筛选工具" value={filters.tool_id} onChange={(event) => setFilters((current) => ({ ...current, tool_id: event.target.value }))} /></label>
      <label>Provider<input aria-label="筛选 Provider" value={filters.provider_type} onChange={(event) => setFilters((current) => ({ ...current, provider_type: event.target.value }))} /></label>
      <label>状态<select aria-label="筛选状态" value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}><option value="">全部</option><option value="configured">已配置</option><option value="missing">缺失</option><option value="invalid">异常</option><option value="expiring">临期</option></select></label>
    </div>
    {loading ? <div className="panel-loading" role="status">正在汇总就绪度…</div> : items.length === 0 ? <EmptyState title="没有匹配结果" copy="调整用户、工具、Provider 或状态筛选后重试。" /> : <div className="readiness-table-wrap"><table className="readiness-table"><thead><tr><th>用户</th><th>范围</th><th>环境</th><th>工具 / Provider</th><th>状态</th><th>字段</th><th>版本</th><th>检查与错误</th></tr></thead><tbody>{items.map((item) => <tr key={`${item.resource_type}:${item.user_id}:${item.environment_id}:${item.tool_id}:${item.provider_type}:${item.capability_key ?? ""}`}><td><strong>{item.username}</strong><small>{item.user_status}</small></td><td>{item.resource_type === "credential" ? "Credential" : <>LLM<small>{item.capability_key}</small></>}</td><td>{item.environment_id.toUpperCase()}</td><td><strong>{item.tool_id}</strong><small>{item.provider_type}{item.capability_key ? ` / ${item.capability_key}` : ""}</small></td><td><StatusBadge value={item.readiness_status} /></td><td>{item.configured_field_count} / {item.required_field_count}</td><td>v{item.current_version}</td><td><span>{item.last_checked_at ? new Date(item.last_checked_at).toLocaleString() : "尚未检查"}</span>{item.last_error_code && <small>{item.last_error_code}</small>}{item.expires_at && <small>过期：{new Date(item.expires_at).toLocaleString()}</small>}</td></tr>)}</tbody></table></div>}
  </section></WorkspaceShell>;
}


const roleLabel: Record<PlatformRole, string> = { platform_admin: "平台管理员", admin: "管理员", tester: "测试人员" };

/** 项目范围页面共用的日期输入值，默认额外授权 7 天且不超过产品上限。 */
function grantExpiry(days = 7): string {
  const value = new Date(Date.now() + days * 86400000);
  return value.toISOString().slice(0, 16);
}

function ProjectsPage() {
  const { auth } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [items, setItems] = useState<ProjectRecord[]>([]);
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [error, setError] = useState("");
  const load = useCallback(() => accessApi.listProjects().then(setItems), []);
  useEffect(() => { void load().catch((reason) => setError(reason.message)); }, [load]);
  async function create(event: FormEvent) {
    event.preventDefault(); setError("");
    try { const project = await accessApi.createProject(form); setForm({ code: "", name: "", description: "" }); navigate(`/projects/${encodeURIComponent(project.id)}/overview`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "创建项目失败"); }
  }
  const canCreate = auth?.role === "platform_admin";
  const creating = location.pathname.endsWith("/new");
  const mine = new URLSearchParams(location.search).get("scope") === "mine" || auth?.role !== "platform_admin";
  if (creating) return <WorkspaceShell><section className="workspace-page access-page"><PageHeader eyebrow="03 / ACCESS CONTROL" title="创建项目" copy="项目编码创建后不可修改；新项目可以暂时没有负责人、成员或工具。" />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <section className="access-card project-create-card"><div className="card-heading"><h2>基础信息</h2><p>创建授权边界，后续成员将自动继承项目中的全部工具。</p></div><form className="project-create-form" onSubmit={create}>
      <div className="form-grid"><label>项目编码<input autoFocus value={form.code} pattern="[A-Za-z0-9_-]{2,64}" placeholder="PAY-QA" onChange={(event) => setForm({ ...form, code: event.target.value })} required /><small>用于接口、审计和迁移引用，创建后不可修改。</small></label><label>项目名称<input value={form.name} placeholder="支付测试" onChange={(event) => setForm({ ...form, name: event.target.value })} required /><small>名称可在项目详情中修改。</small></label></div>
      <label>项目描述<textarea rows={5} value={form.description} placeholder="描述项目覆盖的业务范围、工具与成员。" onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
      <fieldset className="project-status-options"><legend>初始状态</legend><label><input type="radio" name="project-status" checked readOnly aria-label="Active（默认）" /><span>Active（默认）</span></label><label className="disabled"><input type="radio" name="project-status" disabled aria-label="Inactive" /><span>Inactive</span></label></fieldset>
      <div className="next-step-note"><strong>创建后下一步</strong><span>分配负责人 → 加入测试成员 → 关联项目工具</span></div>
      <div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => navigate("/projects")}>取消</button><button className="primary-button">创建项目</button></div>
    </form></section>
  </section></WorkspaceShell>;

  const activeCount = items.filter((item) => item.status === "active").length;
  const managerCount = items.reduce((total, item) => total + item.manager_count, 0);
  const memberCount = items.reduce((total, item) => total + item.member_count, 0);
  const toolCount = items.reduce((total, item) => total + item.tool_count, 0);
  return <WorkspaceShell><section className="workspace-page access-page"><PageHeader eyebrow={`${mine ? "01" : "02"} / ACCESS CONTROL`} title={mine ? "我的项目" : "项目管理"} copy={mine ? "查看你已加入或负责的项目；项目工具会随成员关系自动获得。" : "统一查看项目状态、人员、工具和临时授权影响。"} actions={!mine && canCreate ? <NavLink className="primary-button button-link" to="/projects/new">创建项目</NavLink> : mine ? <NavLink className="secondary-button button-link" to="/">了解访问规则</NavLink> : undefined} />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <div className={`metric-grid ${mine ? "metric-grid-three" : "metric-grid-four"}`}><MetricCard label={mine ? "负责的项目" : "全部项目"} value={mine ? items.filter((item) => item.relation === "manager").length : items.length} note={`${activeCount} 个处于 Active`} /><MetricCard label={mine ? "可见项目工具" : "项目负责人"} value={mine ? toolCount : managerCount} note={mine ? "自动继承访问" : `覆盖 ${items.length} 个项目`} /><MetricCard label={mine ? "临时授权" : "测试成员"} value={items.reduce((total, item) => total + item.active_grant_count, 0)} note={mine ? "仅本人业务资源" : `${memberCount} 人次项目关系`} />{!mine && <MetricCard label="项目工具" value={toolCount} note="公共工具不计入" />}</div>
    {items.length === 0 ? <EmptyState title="暂无项目" copy="你尚未负责或加入项目，仍可使用公共工具。" /> : mine ? <div className="project-card-grid">{items.map((item) => <article className="project-card" key={item.id}><div><span className="project-avatar">{item.name.slice(0, 1)}</span><div><h2>{item.name}</h2><p>{item.code}</p></div><StatusBadge value={item.status} /></div><dl><div><dt>负责人</dt><dd>{item.manager_count}</dd></div><div><dt>测试成员</dt><dd>{item.member_count}</dd></div><div><dt>项目工具</dt><dd>{item.tool_count}</dd></div></dl><small>最近更新 · {new Date(item.updated_at).toLocaleString()}</small><NavLink to={`/projects/${encodeURIComponent(item.id)}/overview`}>查看项目</NavLink></article>)}</div> : <><div className="access-toolbar"><input type="search" placeholder="搜索项目名称或编码" /><select aria-label="全部状态"><option>全部状态</option><option>Active</option><option>Inactive</option></select></div><AccessTable headers={["项目", "状态", "负责人", "成员", "工具", "额外授权", "操作"]}>{items.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.code}</small></td><td><StatusBadge value={item.status} /></td><td>{item.manager_count}</td><td>{item.member_count}</td><td>{item.tool_count}</td><td>{item.active_grant_count}</td><td><NavLink to={`/projects/${encodeURIComponent(item.id)}/overview`}>查看 · {item.status === "active" ? "编辑" : "恢复"}</NavLink></td></tr>)}</AccessTable></>}
  </section></WorkspaceShell>;
}

function AccessTable({ headers, children }: PropsWithChildren<{ headers: string[] }>) {
  return <div className="access-table-wrap"><table className="access-table"><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}

function ProjectDetailPage() {
  const { projectId = "" } = useParams(); const { auth } = useAuth(); const location = useLocation();
  const [project, setProject] = useState<ProjectRecord | null>(null); const [members, setMembers] = useState<ProjectMember[]>([]); const [managers, setManagers] = useState<ProjectMember[]>([]); const [tools, setTools] = useState<ToolAccessRecord[]>([]); const [impact, setImpact] = useState<ImpactPreview | null>(null); const [error, setError] = useState("");
  const [personDialog, setPersonDialog] = useState<"members" | "managers" | null>(null);
  const [personUsername, setPersonUsername] = useState("");
  const [personError, setPersonError] = useState("");
  const [personBusy, setPersonBusy] = useState(false);
  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [forceUnknownImpact, setForceUnknownImpact] = useState(false);
  const canManageMembers = auth?.role === "platform_admin" || auth?.role === "admin";
  const canManageProject = auth?.role === "platform_admin";
  const load = useCallback(async () => { const [detail, toolRows, memberRows, managerRows] = await Promise.all([accessApi.getProject(projectId), accessApi.listProjectTools(projectId), (auth?.role === "admin" || auth?.role === "platform_admin") ? accessApi.listProjectMembers(projectId, "members") : Promise.resolve([]), auth?.role === "platform_admin" ? accessApi.listProjectMembers(projectId, "managers") : Promise.resolve([])]); setProject(detail); setTools(toolRows); setMembers(memberRows); setManagers(managerRows); }, [auth?.role, projectId]);
  useEffect(() => { void load().catch((reason) => setError(reason.message)); }, [load]);
  useModal(Boolean(impact), () => setImpact(null));
  useModal(Boolean(personDialog), () => { setPersonDialog(null); setPersonError(""); }, personBusy);
  async function previewDeactivate() { try { setForceUnknownImpact(false); setImpact(await accessApi.projectImpact(projectId)); } catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取影响范围"); } }
  async function confirmDeactivate() { if (!impact) return; try { await accessApi.setProjectStatus(projectId, { status: "inactive", reason: "项目停用", expected_revision: impact.expected_revision, impact_token: impact.impact_token, force_unknown_impact: forceUnknownImpact }); setImpact(null); await load(); } catch (reason) { const stale = reason instanceof ApiError && reason.code === "STALE_IMPACT"; setImpact(null); setError(stale ? "资源状态已变化，请重新确认影响范围" : reason instanceof Error ? reason.message : "项目停用失败"); } }
  /** 删除关系期间锁住人员操作，避免重复点击把已成功请求误报为冲突。 */
  async function removePerson(member: ProjectMember, relation: "members" | "managers") {
    if (removingUserId) return;
    setRemovingUserId(member.id); setError("");
    try {
      await accessApi.removeProjectMember(projectId, relation, member.id, relation === "members" ? "移出项目成员" : "移除项目负责人");
      await load();
    } catch (reason) {
      setError(describeApiError(reason, "移除人员失败"));
    } finally {
      setRemovingUserId(null);
    }
  }

  /** 添加失败时保留弹窗与用户名，并把服务端原因放在用户当前视线内。 */
  async function addPerson(event: FormEvent) {
    event.preventDefault();
    if (!personDialog || personBusy) return;
    setPersonBusy(true); setPersonError(""); setError("");
    let relationCreated = false;
    try {
      await accessApi.addProjectMember(projectId, personDialog, personUsername.trim());
      relationCreated = true;
      await load();
      setPersonDialog(null); setPersonUsername("");
    } catch (reason) {
      if (relationCreated) {
        // 写入已经成功时不能让用户继续提交同一关系；关闭弹窗并明确要求刷新确认。
        setPersonDialog(null); setPersonUsername("");
        setError(`人员已添加，但列表刷新失败：${describeApiError(reason, "请刷新页面确认最新成员列表")}`);
      } else {
        setPersonError(describeApiError(reason, "添加人员失败"));
      }
    } finally {
      setPersonBusy(false);
    }
  }
  if (!project && !error) return <LoadingPage label="正在加载项目…" />;
  if (!project) return <WorkspaceShell><section className="workspace-page"><InlineMessage kind="error">{error}</InlineMessage></section></WorkspaceShell>;
  const unknownRunning = impact?.running_task_count == null || impact.running_task_count === "unknown";
  const isMembersPage = location.pathname.endsWith("/members");
  const isToolsPage = location.pathname.endsWith("/tools");
  const isManagersView = isMembersPage && auth?.role === "platform_admin" && new URLSearchParams(location.search).get("view") === "managers";
  const pageNumber = isMembersPage ? "05" : isToolsPage ? "06" : "04";
  const pageTitle = isMembersPage ? "项目详情 · 人员" : isToolsPage ? "项目详情 · 工具与授权" : "项目详情 · 概览";
  return <WorkspaceShell><section className="workspace-page access-page"><PageHeader eyebrow={`${pageNumber} / ACCESS CONTROL`} title={pageTitle} copy={`${project.name} · ${project.code}`} actions={!isMembersPage && !isToolsPage && canManageProject ? <button className="secondary-button" disabled title="项目资料编辑接口尚未开放">编辑项目</button> : undefined} />
    <nav className="project-tabs" aria-label="项目详情"><NavLink to={`/projects/${encodeURIComponent(projectId)}/overview`}>概览</NavLink>{auth?.role === "platform_admin" && <Link aria-current={isManagersView ? "page" : undefined} className={isManagersView ? "active" : ""} to={`/projects/${encodeURIComponent(projectId)}/members?view=managers`}>负责人</Link>}{(auth?.role === "admin" || auth?.role === "platform_admin") && <Link aria-current={isMembersPage && !isManagersView ? "page" : undefined} className={isMembersPage && !isManagersView ? "active" : ""} to={`/projects/${encodeURIComponent(projectId)}/members`}>测试成员</Link>}<NavLink to={`/projects/${encodeURIComponent(projectId)}/tools`}>项目工具</NavLink><NavLink to={`/projects/${encodeURIComponent(projectId)}/tools?view=grants`}>额外授权</NavLink><a href="#audit">审计</a></nav>{error && <InlineMessage kind="error">{error}</InlineMessage>}
    {!isMembersPage && !isToolsPage && <><div className="metric-grid metric-grid-four"><MetricCard label="负责人" value={project.manager_count} note={auth?.role === "platform_admin" ? managers.map((item) => item.display_name).join(" · ") || "尚未分配" : project.manager_count ? `${project.manager_count} 位，由平台管理员维护` : "尚未分配"} /><MetricCard label="测试成员" value={project.member_count} note="成员仅操作本人资源" /><MetricCard label="项目工具" value={project.tool_count} note="全部项目关系自动继承" /><MetricCard label="额外授权" value={project.active_grant_count} note="临时单工具访问" /></div><div className="project-overview-grid"><section className="access-card"><h2>项目资料</h2><dl className="detail-list"><div><dt>项目编码</dt><dd>{project.code}（不可修改）</dd></div><div><dt>项目名称</dt><dd>{project.name}</dd></div><div><dt>创建时间</dt><dd>—</dd></div><div><dt>最近更新</dt><dd>{new Date(project.updated_at).toLocaleString()}</dd></div></dl></section><section className="access-card"><h2>访问规则</h2><span className="scope-badge project">项目范围</span><dl className="detail-list"><div><dt>负责人</dt><dd>使用并管理项目工具</dd></div><div><dt>测试成员</dt><dd>使用工具，仅操作本人资源</dd></div><div><dt>临时授权</dt><dd>单工具使用，不获得项目数据</dd></div></dl></section></div>{project.status === "active" && canManageProject && <section className="deactivate-banner"><div><strong>停用项目将立即收敛工具访问</strong><p>{project.tool_count} 个项目工具将从普通用户目录隐藏，{project.active_grant_count} 条额外授权暂时失效；运行中任务不会自动取消。</p></div><button className="secondary-button" onClick={() => void previewDeactivate()}>预览停用影响</button></section>}</>}
    {isMembersPage && isManagersView && <section className="access-card member-section"><div className="section-heading"><div><h2>项目负责人</h2><p>仅平台管理员可以分配 active 管理员。</p></div><button className="secondary-button" disabled={personBusy || Boolean(removingUserId)} onClick={() => { setPersonUsername(""); setPersonError(""); setPersonDialog("managers"); }}>分配负责人</button></div>{managers.length ? <MemberList members={managers} relation="managers" canRemove onRemove={(member) => void removePerson(member, "managers")} removingUserId={removingUserId} /> : <EmptyState title="尚未分配负责人" copy="平台管理员可为项目分配管理员负责人。" />}</section>}
    {isMembersPage && !isManagersView && <section className="access-card member-section"><div className="section-heading"><div><h2>测试成员</h2><p>普通管理员只能通过精确用户名查找并加入 active 测试人员。</p></div>{canManageMembers && <div className="row-actions"><NavLink className="secondary-button button-link" to={`/admin/users?project_id=${encodeURIComponent(projectId)}`}>创建测试人员</NavLink><button className="primary-button" disabled={personBusy || Boolean(removingUserId)} onClick={() => { setPersonUsername(""); setPersonError(""); setPersonDialog("members"); }}>添加成员</button></div>}</div>{members.length ? <MemberList members={members} relation="members" canRemove={canManageMembers} onRemove={(member) => void removePerson(member, "members")} removingUserId={removingUserId} /> : <EmptyState title="暂无测试成员" copy="成员加入后会自动获得该项目的启用工具。" />}</section>}
    {isToolsPage && <><div className="section-heading project-tools-heading"><div><h2>项目工具</h2><p>项目工具自动授予负责人和成员；额外授权只提供单工具业务使用权。</p></div>{canManageProject && <button className="secondary-button" disabled title="工具归属只能由平台管理员在工具管理中修改">关联项目工具</button>}</div>{tools.length ? <AccessTable headers={["工具", "状态", "分类", "成员覆盖", "临时授权", "操作"]}>{tools.map((tool) => <tr key={tool.id}><td><strong>{tool.name}</strong><small>{tool.description}</small></td><td><StatusBadge value={tool.is_enabled ? "enabled" : "disabled"} /></td><td>工具</td><td>{project.manager_count + project.member_count} 人</td><td>0</td><td>{canManageProject ? <NavLink to={`/admin/tool-access/${encodeURIComponent(tool.id)}`}>进入控制面</NavLink> : "查看"}</td></tr>)}</AccessTable> : <EmptyState title="项目暂无工具" copy="启用并归属本项目的工具会在这里显示。" />}<section className="access-card grant-readonly"><div><h2>额外授权只读汇总</h2><p>授权由平台管理员在“额外授权”模块统一管理。</p></div>{project.active_grant_count ? <span className="status-badge status-badge-warning">{project.active_grant_count} 条有效授权</span> : <span>暂无临时授权</span>}<span>仅本人资源</span></section></>}
    {personDialog && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="add-project-person-title"><h2 id="add-project-person-title">{personDialog === "managers" ? "添加项目负责人" : "添加测试人员"}</h2><p>请输入完整用户名。平台不会提供全局用户候选列表。</p>{personError && <InlineMessage kind="error">{personError}</InlineMessage>}<form className="auth-form" onSubmit={addPerson}><label>完整用户名<input autoFocus value={personUsername} onChange={(event) => setPersonUsername(event.target.value)} minLength={3} disabled={personBusy} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" disabled={personBusy} onClick={() => { setPersonDialog(null); setPersonError(""); }}>取消</button><button className="primary-button" disabled={personBusy || !personUsername.trim()}>{personBusy ? "添加中…" : "确认添加"}</button></div></form></section></div>}
    {impact && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="deactivate-project-title"><p className="section-label">HIGH-RISK ACTION</p><h2 id="deactivate-project-title">停用 {project.name}</h2><p>将影响 {impact.manager_count ?? 0} 位负责人、{impact.member_count ?? 0} 位成员、{impact.tool_count ?? 0} 个工具及 {impact.active_grant_count ?? 0} 条额外授权。</p><p>{unknownRunning ? "运行中任务状态未知，默认阻止停用。" : `当前运行中任务：${impact.running_task_count}`}</p>{unknownRunning && <label className="checkbox-row"><input type="checkbox" checked={forceUnknownImpact} onChange={(event) => setForceUnknownImpact(event.target.checked)} />我已核对外部运行状态并承担继续停用的影响</label>}<div className="dialog-actions"><button className="secondary-button" onClick={() => setImpact(null)}>取消</button><button className="primary-button" disabled={unknownRunning && !forceUnknownImpact} onClick={() => void confirmDeactivate()}>确认停用</button></div></section></div>}
  </section></WorkspaceShell>;
}

/** 项目根路由只负责稳定跳转，避免概览、人员和工具页共享易变的查询参数。 */
function ProjectOverviewRedirect() {
  const { projectId = "" } = useParams();
  return <Navigate to={`/projects/${encodeURIComponent(projectId)}/overview`} replace />;
}

function MemberList({ members, relation, canRemove = false, onRemove, removingUserId = null }: { members: ProjectMember[]; relation: "members" | "managers"; canRemove?: boolean; onRemove?: (member: ProjectMember) => void; removingUserId?: string | null }) {
  const removeLabel = relation === "managers" ? "移除负责人" : "移除成员";
  return <div className="data-panel">{members.map((member) => <div className="table-row" key={member.id}><strong>{member.display_name}<small>{member.username}</small></strong><span>{roleLabel[member.role]}</span><StatusBadge value={member.status} />{canRemove ? <button className="link-button" aria-label={`${removeLabel} ${member.display_name}（${member.username}）`} disabled={Boolean(removingUserId)} onClick={() => onRemove?.(member)}>{removingUserId === member.id ? "移除中…" : removeLabel}</button> : <span />}</div>)}</div>;
}

function ToolAccessAdminPage() {
  const { toolId } = useParams(); const location = useLocation(); const [tools, setTools] = useState<ToolAccessRecord[]>([]); const [projects, setProjects] = useState<ProjectSummary[]>([]); const [grants, setGrants] = useState<ToolGrantSummary[]>([]); const [loaded, setLoaded] = useState(false); const [editing, setEditing] = useState<ToolAccessRecord | null>(null); const [impact, setImpact] = useState<ImpactPreview | null>(null); const [confirmingImpact, setConfirmingImpact] = useState(false); const [grantDialog, setGrantDialog] = useState<ToolGrantSummary | "new" | null>(null); const [error, setError] = useState("");
  const [accessForm, setAccessForm] = useState({ access_scope: "project" as "public" | "project", project_id: "", is_enabled: true, reason: "", force_unknown_impact: false }); const [grantForm, setGrantForm] = useState({ user_id: "", tool_id: "", reason: "", expires_at: grantExpiry() });
  const load = useCallback(async () => {
    const [toolRows, projectRows, grantRows] = await Promise.all([
      accessApi.listToolAccess(),
      accessApi.projectChoices(),
      accessApi.listGrants(),
    ]);
    // 三个权限集合并行加载；若旧网关或测试桩返回异常结构，则失败关闭为空集合，
    // 避免错误载荷进入 filter/map 后让整个管理页白屏。
    setTools(Array.isArray(toolRows) ? toolRows : []);
    setProjects(Array.isArray(projectRows) ? projectRows : []);
    setGrants(Array.isArray(grantRows) ? grantRows : []);
    setLoaded(true);
  }, []);
  useEffect(() => { void load().catch((reason) => { setLoaded(true); setError(reason.message); }); }, [load]);
  useEffect(() => {
    if (!toolId) { setEditing(null); return; }
    if (!loaded) return;
    const item = tools.find((row) => row.id === toolId) ?? null;
    setEditing(item);
    if (item) void openTool(item);
  }, [loaded, toolId, tools]);
  useModal(Boolean(confirmingImpact || grantDialog), () => { setConfirmingImpact(false); setGrantDialog(null); });
  async function refreshToolImpact(tool: ToolAccessRecord, scope: "public" | "project", projectId: string) { setImpact(null); try { setImpact(await accessApi.toolImpact(tool.id, scope, scope === "public" ? null : projectId || null)); } catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取工具影响范围"); } }
  async function openTool(tool: ToolAccessRecord) { setEditing(tool); setAccessForm({ access_scope: tool.access_scope, project_id: tool.project_id ?? "", is_enabled: tool.is_enabled, reason: "", force_unknown_impact: false }); setImpact(null); }
  async function previewToolImpact() { if (!editing) return; await refreshToolImpact(editing, accessForm.access_scope, accessForm.project_id); setConfirmingImpact(true); }
  async function saveTool(event: FormEvent) { event.preventDefault(); if (!editing || !impact) return; try { await accessApi.updateToolAccess(editing.id, { ...accessForm, project_id: accessForm.access_scope === "public" ? null : accessForm.project_id, revision: impact.expected_revision, impact_token: impact.impact_token }); setConfirmingImpact(false); setImpact(null); await load(); } catch (reason) { const stale = reason instanceof ApiError && reason.code === "STALE_IMPACT"; setConfirmingImpact(false); setImpact(null); setError(stale ? "影响预览已过期，请重新计算影响" : reason instanceof Error ? reason.message : "保存工具范围失败"); } }
  async function saveGrant(event: FormEvent) { event.preventDefault(); try { const expires = new Date(grantForm.expires_at); const days = Math.ceil((expires.getTime() - Date.now()) / 86400000); if (days < 1 || days > 90) throw new Error("额外授权期限必须在未来 1 至 90 天内"); if (grantDialog === "new") await accessApi.createGrant({ user_id: grantForm.user_id, tool_id: grantForm.tool_id, reason: grantForm.reason, days, idempotency_key: crypto.randomUUID() }); else if (grantDialog) await accessApi.renewGrant(grantDialog.id, { reason: grantForm.reason, expires_at: expires.toISOString() }); setGrantDialog(null); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "保存额外授权失败"); } }
  const isGrantPage = location.pathname.startsWith("/admin/tool-grants");
  const selectedTool = toolId ? tools.find((tool) => tool.id === toolId) ?? null : null;
  const grantCounts = { active: grants.filter((grant) => grant.status === "active").length, expired: grants.filter((grant) => grant.status === "expired").length, revoked: grants.filter((grant) => grant.status === "revoked").length, expiring: grants.filter((grant) => grant.status === "active" && new Date(grant.expires_at).getTime() - Date.now() <= 7 * 86400000).length };

  if (toolId && !loaded) return <WorkspaceShell><LoadingPage label="正在读取工具权限…" /></WorkspaceShell>;
  if (toolId && !selectedTool) return <WorkspaceShell><section className="workspace-page access-page"><EmptyState title="工具不可见或不存在" copy="请返回工具管理后重新选择。" /></section></WorkspaceShell>;
  return <WorkspaceShell><section className="workspace-page access-page">{selectedTool ? <>
    <PageHeader eyebrow="10 / ACCESS CONTROL" title="工具详情 · 范围与归属" copy={`${selectedTool.name} · tool.${selectedTool.id}`} />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <section className="access-card tool-identity"><span className="project-avatar">AI</span><div><h2>{selectedTool.name}</h2><p>{selectedTool.description || "健康正常 · 最近发布版本可用"}</p></div><StatusBadge value={selectedTool.is_enabled ? "enabled" : "disabled"} /><button className="danger-button" type="button" disabled title="工具启停接口尚未开放">{selectedTool.is_enabled ? "停用工具" : "启用工具"}</button></section>
    <div className="tool-scope-layout"><section className="access-card"><div className="card-heading"><h2>访问范围</h2><p>每个工具必须且只能选择一种范围。</p></div><div className="scope-options"><label className={accessForm.access_scope === "project" ? "selected" : ""}><input type="radio" name="scope" value="project" checked={accessForm.access_scope === "project"} onChange={() => setAccessForm({ ...accessForm, access_scope: "project", force_unknown_impact: false })} /><span><strong>项目工具</strong><small>项目关系自动授予访问；可创建临时单工具授权</small></span></label><label className={accessForm.access_scope === "public" ? "selected" : ""}><input type="radio" name="scope" value="public" checked={accessForm.access_scope === "public"} disabled={!selectedTool.public_eligible} onChange={() => setAccessForm({ ...accessForm, access_scope: "public", project_id: "", force_unknown_impact: false })} /><span><strong>公共工具</strong><small>全部 active 用户可用；不允许个别关闭</small></span></label></div>{accessForm.access_scope === "project" && <label className="stacked-field">所属项目<select value={accessForm.project_id} onChange={(event) => setAccessForm({ ...accessForm, project_id: event.target.value, force_unknown_impact: false })} required><option value="">选择项目</option>{projects.filter((project) => project.status === "active").map((project) => <option key={project.id} value={project.id}>{project.name} · {project.code}</option>)}</select></label>}<p className="warning-copy">范围或归属变更前必须预览影响。</p></section>
      <aside className="access-card impact-summary"><h2>当前影响</h2><dl><div><dt>项目负责人</dt><dd>{impact?.manager_count ?? "未知"}</dd></div><div><dt>测试成员</dt><dd>{impact?.member_count ?? "未知"}</dd></div><div><dt>额外授权</dt><dd>{grants.filter((grant) => grant.tool_id === selectedTool.id && grant.status === "active").length}</dd></div><div><dt>运行中任务</dt><dd>{impact?.running_task_count ?? "—"}</dd></div><div><dt>历史资源</dt><dd>保留快照</dd></div></dl><button className="primary-button" type="button" onClick={() => void previewToolImpact()}>预览变更影响</button></aside></div>
  </> : isGrantPage ? <>
    <PageHeader eyebrow="12 / ACCESS CONTROL" title="额外工具授权" copy="只处理少量跨项目例外，不替代项目成员关系。" actions={<button className="primary-button" onClick={() => { setGrantForm({ user_id: "", tool_id: tools.find((tool) => tool.access_scope === "project")?.id ?? "", reason: "", expires_at: grantExpiry() }); setGrantDialog("new"); }}>创建额外授权</button>} />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <div className="metric-grid metric-grid-four"><MetricCard label="有效授权" value={grantCounts.active} note="默认 7 天" /><MetricCard label="即将到期" value={grantCounts.expiring} note="未来 7 天" /><MetricCard label="已过期" value={grantCounts.expired} note="不自动恢复" /><MetricCard label="已撤销" value={grantCounts.revoked} note="保留审计" /></div>
    <div className="access-toolbar"><input type="search" placeholder="搜索用户或工具" /><select aria-label="全部状态"><option>全部状态</option></select></div>
    {grants.length ? <AccessTable headers={["用户", "项目工具", "所属项目", "状态", "到期时间", "原因", "操作"]}>{grants.map((grant) => <tr key={grant.id}><td><strong>{grant.username ?? grant.user_id ?? "—"}</strong></td><td>{grant.tool_name}</td><td>{grant.project_name}</td><td><StatusBadge value={grant.status} /></td><td>{new Date(grant.expires_at).toLocaleString()}</td><td>{grant.grant_reason}</td><td><button className="link-button" onClick={() => { setGrantForm({ user_id: grant.user_id ?? "", tool_id: grant.tool_id, reason: "", expires_at: grantExpiry() }); setGrantDialog(grant); }}>续期</button>{grant.status === "active" && <button className="link-button" onClick={() => void accessApi.revokeGrant(grant.id, "撤销额外授权").then(load).catch((reason) => setError(reason.message))}>撤销</button>}</td></tr>)}</AccessTable> : <EmptyState title="没有额外授权" copy="项目成员会自动继承项目工具，无需逐工具授权。" />}
  </> : <>
    <PageHeader eyebrow="09 / ACCESS CONTROL" title="工具管理" copy="平台管理员管理范围与归属；项目负责人只看到本项目普通控制面。" actions={<button className="primary-button" disabled title="工具接入流程尚未开放">接入工具</button>} />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    <div className="metric-grid metric-grid-four"><MetricCard label="全部工具" value={tools.length} note={`Enabled ${tools.filter((tool) => tool.is_enabled).length}`} /><MetricCard label="公共工具" value={tools.filter((tool) => tool.access_scope === "public").length} note="全部 active 用户" /><MetricCard label="项目工具" value={tools.filter((tool) => tool.access_scope === "project").length} note={`归属 ${new Set(tools.map((tool) => tool.project_id).filter(Boolean)).size} 个项目`} /><MetricCard label="未分类" value={tools.filter((tool) => tool.access_scope === "project" && !tool.project_id).length} note="不允许启用" /></div>
    <div className="access-toolbar"><input type="search" placeholder="搜索工具名称" /><select aria-label="全部访问范围"><option>全部访问范围</option></select></div>
    <AccessTable headers={["工具", "状态", "访问范围", "所属项目", "临时授权", "健康", "操作"]}>{tools.map((tool) => <tr key={tool.id}><td><strong>{tool.name}</strong><small>{tool.id}</small></td><td><StatusBadge value={tool.is_enabled ? "enabled" : "disabled"} /></td><td><span className={`scope-badge ${tool.access_scope}`}>{tool.access_scope === "public" ? "公共工具" : "项目工具"}</span></td><td>{tool.project_name ?? "—"}</td><td>{grants.filter((grant) => grant.tool_id === tool.id && grant.status === "active").length}</td><td>{tool.is_enabled ? "正常" : "未知"}</td><td><NavLink to={`/admin/tool-access/${encodeURIComponent(tool.id)}`}>管理</NavLink></td></tr>)}</AccessTable>
  </>}
    {confirmingImpact && editing && impact && <div className="modal-backdrop" role="presentation"><section className="dialog impact-dialog" role="dialog" aria-modal="true" aria-labelledby="tool-access-title"><span className="risk-badge">高风险操作</span><h2 id="tool-access-title">将 {editing.name} 改为{accessForm.access_scope === "public" ? "公共工具" : "项目工具"}？</h2><p>高风险变更会在提交前重新校验 revision 与 impact token。</p><form onSubmit={saveTool}><div className="impact-change"><span>范围变化</span><strong>{editing.access_scope === "public" ? "公共工具" : `项目工具 · ${editing.project_name ?? "未归属"}`} → {accessForm.access_scope === "public" ? "公共工具" : `项目工具 · ${projects.find((project) => project.id === accessForm.project_id)?.name ?? "未归属"}`}</strong></div><dl className="impact-list"><div><dt>新增可访问用户</dt><dd>{impact.affected_user_count ?? 0}</dd></div><div><dt>历史资源范围</dt><dd>保持原项目快照</dd></div><div><dt>运行中任务</dt><dd>{impact.running_task_count ?? "unknown"}</dd></div><div><dt>将撤销额外授权</dt><dd>{grants.filter((grant) => grant.tool_id === editing.id && grant.status === "active").length}</dd></div></dl><label className="stacked-field">操作原因<input value={accessForm.reason} onChange={(event) => setAccessForm({ ...accessForm, reason: event.target.value })} required /></label>{impact.running_task_count === "unknown" && <label className="checkbox-row"><input type="checkbox" checked={accessForm.force_unknown_impact} onChange={(event) => setAccessForm({ ...accessForm, force_unknown_impact: event.target.checked })} />我已核对外部运行状态并承担继续变更的影响</label>}<label className="checkbox-row"><input type="checkbox" required />我已确认对象、影响数量和历史资源不会迁移</label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setConfirmingImpact(false)}>取消</button><button className="danger-button" disabled={impact.running_task_count === "unknown" && !accessForm.force_unknown_impact}>确认变更</button></div></form></section></div>}
    {grantDialog && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="grant-title"><h2 id="grant-title">{grantDialog === "new" ? "创建额外工具授权" : "续期额外工具授权"}</h2><form className="auth-form" onSubmit={saveGrant}>{grantDialog === "new" && <><label>用户 ID<input value={grantForm.user_id} onChange={(event) => setGrantForm({ ...grantForm, user_id: event.target.value })} required /></label><label>项目工具<select value={grantForm.tool_id} onChange={(event) => setGrantForm({ ...grantForm, tool_id: event.target.value })} required><option value="">选择项目工具</option>{tools.filter((tool) => tool.access_scope === "project" && tool.is_enabled).map((tool) => <option key={tool.id} value={tool.id}>{tool.name}</option>)}</select></label></>}<label>到期时间<input type="datetime-local" value={grantForm.expires_at} onChange={(event) => setGrantForm({ ...grantForm, expires_at: event.target.value })} required /></label><label>原因<textarea value={grantForm.reason} onChange={(event) => setGrantForm({ ...grantForm, reason: event.target.value })} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setGrantDialog(null)}>取消</button><button className="primary-button">{grantDialog === "new" ? "创建授权" : "确认续期"}</button></div></form></section></div>}
  </section></WorkspaceShell>;
}

function FixedUsersPage() {
  const { auth } = useAuth();
  const { userId } = useParams(); const location = useLocation(); const navigate = useNavigate();
  const projectIdToJoin = new URLSearchParams(location.search).get("project_id");
  const [items, setItems] = useState<AdminUser[]>([]); const [selected, setSelected] = useState<AdminUser | null>(null); const [detailLoading, setDetailLoading] = useState(false); const [creating, setCreating] = useState(false); const [error, setError] = useState("");
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "tester" as PlatformRole });
  const [createError, setCreateError] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createdUsername, setCreatedUsername] = useState<string | null>(null);
  const [createdUserId, setCreatedUserId] = useState<string | null>(null);
  const load = useCallback(() => apiJson<AdminUser[]>("/admin/users").then(setItems), []);
  useEffect(() => { void load().catch((reason) => setError(reason.message)); }, [load]);
  useEffect(() => {
    if (!projectIdToJoin || userId) return;
    // 从项目进入时只能创建 tester，防止平台管理员在同一入口误建管理员后又尝试加入成员关系。
    setForm((current) => ({ ...current, role: "tester" }));
    setCreateError(""); setCreatedUsername(null); setCreatedUserId(null); setCreating(true);
  }, [projectIdToJoin, userId]);
  useEffect(() => {
    setSelected(null);
    setError("");
    if (!userId) { setDetailLoading(false); return; }
    setDetailLoading(true);
    void apiJson<AdminUser>(`/admin/users/${encodeURIComponent(userId)}`)
      .then(setSelected)
      .catch((reason) => setError(reason.message))
      .finally(() => setDetailLoading(false));
  }, [userId]);
  useModal(creating, () => { setCreating(false); setCreateError(""); }, createBusy);
  /**
   * 项目入口包含“创建账号”和“加入项目”两次写入。若第二步失败，保留已创建用户名并只重试加入，
   * 避免用户再次提交时得到用户名重复、却不知道账号其实已经创建成功的半完成状态。
   */
  async function createFixedUser(event: FormEvent) {
    event.preventDefault();
    if (createBusy) return;
    if (!createdUsername) {
      const passwordError = validateNewPassword(form.password);
      if (passwordError) {
        setCreateError(passwordError);
        return;
      }
    }
    setCreateBusy(true); setCreateError(""); setError("");
    let accountCreated = Boolean(createdUsername);
    let accountUserId = createdUserId;
    try {
      if (!accountCreated) {
        const created = await apiJson<{ id: string }>("/admin/users", { method: "POST", body: JSON.stringify({ ...form, role: projectIdToJoin ? "tester" : form.role, must_change_password: true }) });
        accountCreated = true;
        accountUserId = created.id;
        setCreatedUsername(form.username);
        setCreatedUserId(created.id);
      }
      if (projectIdToJoin) {
        try {
          await accessApi.addProjectMember(projectIdToJoin, "members", createdUsername ?? form.username);
        } catch (relationError) {
          if (!(relationError instanceof ApiError) || relationError.code !== "PROJECT_RELATION_EXISTS") throw relationError;
          // 首次响应可能在服务端提交后丢失。只有重新读取确认“刚创建的同一账号”已经是
          // 当前项目成员，才把重复关系视为幂等成功；不能仅凭 409 猜测写入结果。
          const currentMembers = await accessApi.listProjectMembers(projectIdToJoin, "members");
          const relationExists = currentMembers.some((member) => (
            accountUserId ? member.user_id === accountUserId : member.username === (createdUsername ?? form.username)
          ));
          if (!relationExists) throw relationError;
        }
      }
      setCreating(false); setCreatedUsername(null); setCreatedUserId(null); setCreateError("");
      setForm({ username: "", display_name: "", password: "", role: "tester" });
      if (projectIdToJoin) navigate(`/projects/${encodeURIComponent(projectIdToJoin)}/members`);
      else await load();
    } catch (reason) {
      const message = describeApiError(reason, accountCreated ? "加入项目失败" : "创建用户失败");
      setCreateError(accountCreated && projectIdToJoin ? `账号已创建，但加入项目失败：${message}。请修复问题后重试加入。` : message);
    } finally {
      setCreateBusy(false);
    }
  }
  if (userId && detailLoading) return <WorkspaceShell><LoadingPage label="正在读取用户权限…" /></WorkspaceShell>;
  if (userId && !selected) return <WorkspaceShell><section className="workspace-page access-page"><EmptyState title="用户不可见或不存在" copy="请返回用户管理后重新选择。" /></section></WorkspaceShell>;
  if (userId && selected) return <WorkspaceShell><section className="workspace-page access-page"><PageHeader eyebrow="08 / ACCESS CONTROL" title="用户详情 · 权限全景" copy={`${selected.display_name} · ${selected.username}`} />{error && <InlineMessage kind="error">{error}</InlineMessage>}
    <section className="access-card user-identity"><span className="project-avatar">{selected.display_name.slice(0, 1)}</span><div><h2>{selected.display_name}</h2><p>{selected.username} · 最近登录 {selected.last_login_at ? new Date(selected.last_login_at).toLocaleString() : "尚未登录"}</p></div><span className="role-badge admin">{roleLabel[selected.role]}</span><StatusBadge value={selected.status} /><button className="secondary-button" disabled title="角色切换流程尚未开放">切换角色</button><button className="danger-button" disabled title="账号安全操作流程尚未开放">安全操作</button></section>
    <div className="user-access-grid"><section className="access-card"><div className="card-heading"><h2>项目关系</h2><p>负责项目决定管理范围</p></div>{selected.projects.length ? <ul className="relationship-list">{selected.projects.map((project) => <li key={project.id}><strong>{project.name}</strong><span>{project.code} · {project.relation === "manager" ? "项目负责人" : "测试成员"}</span></li>)}</ul> : <p className="muted-copy">当前没有项目关系。</p>}</section><section className="access-card"><div className="card-heading"><h2>额外授权</h2><p>不增加项目或配置管理能力</p></div>{selected.extra_tool_grants.length ? selected.extra_tool_grants.map((grant) => <div className="grant-highlight" key={grant.id}><StatusBadge value={grant.status} /><strong>{grant.tool_name}</strong><span>仅本人资源 · {new Date(grant.expires_at).toLocaleDateString()} 到期</span></div>) : <p className="muted-copy">当前没有额外授权。</p>}</section></div>
    <section className="access-card permission-explanation"><div className="card-heading"><h2>权限解释</h2><p>为什么可以访问工具？</p></div><div className="explanation-source"><span className="source-dot" /><div><strong>主要来源：{selected.projects.some((project) => project.relation === "manager") ? "项目负责人" : roleLabel[selected.role]}</strong><p>{selected.projects[0] ? `${selected.projects[0].name}（${selected.projects[0].code}）` : "公共工具"} · 业务资源严格按本人或项目快照过滤</p></div></div><div className="warning-note">额外授权访问其他项目工具时，能力始终降级为“仅本人业务资源”。</div></section>
  </section></WorkspaceShell>;

  const platformAdmins = items.filter((item) => item.role === "platform_admin").length;
  const admins = items.filter((item) => item.role === "admin").length;
  const testers = items.filter((item) => item.role === "tester").length;
  return <WorkspaceShell><section className="workspace-page access-page"><PageHeader eyebrow="07 / ACCESS CONTROL" title="用户管理" copy="固定全局角色一人一个；项目关系和额外授权决定工具范围。" actions={<button className="primary-button" onClick={() => { setCreateError(""); if (!projectIdToJoin) { setCreatedUsername(null); setCreatedUserId(null); } setCreating(true); }}>创建用户</button>} />{error && <InlineMessage kind="error">{error}</InlineMessage>}
    <div className="metric-grid metric-grid-four"><MetricCard label="全部用户" value={items.length} note={`Active ${items.filter((item) => item.status === "active").length}`} /><MetricCard label="平台管理员" value={platformAdmins} note="至少保留 1 位 active" /><MetricCard label="管理员" value={admins} note={`负责 ${items.reduce((sum, item) => sum + item.projects.filter((project) => project.relation === "manager").length, 0)} 个项目`} /><MetricCard label="测试人员" value={testers} note={`${items.filter((item) => item.role === "tester" && item.projects.length === 0).length} 人无项目`} /></div>
    <div className="access-toolbar"><input type="search" placeholder="搜索用户名或显示名" /><select aria-label="全部角色"><option>全部角色</option></select><select aria-label="全部用户状态"><option>全部状态</option></select></div>
    <AccessTable headers={["用户", "固定角色", "状态", "项目关系", "额外授权", "最近登录", "操作"]}>{items.map((item) => <tr key={item.id}><td><strong>{item.display_name} {item.username}</strong></td><td><span className={`role-badge ${item.role}`}>{roleLabel[item.role]}</span></td><td><StatusBadge value={item.status} /></td><td>{item.role === "platform_admin" ? "全平台" : `${item.projects.some((project) => project.relation === "manager") ? "负责" : "加入"} ${item.projects.length} 个项目`}</td><td>{item.extra_tool_grants.length}</td><td>{item.last_login_at ? new Date(item.last_login_at).toLocaleString() : "尚未登录"}</td><td><NavLink to={`/admin/users/${encodeURIComponent(item.id)}`}>查看</NavLink></td></tr>)}</AccessTable>
    {creating && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="create-fixed-user-title"><h2 id="create-fixed-user-title">{projectIdToJoin ? "创建测试人员" : "创建用户"}</h2>{projectIdToJoin && <p>{createdUsername ? `账号 ${createdUsername} 已创建，当前仅需完成加入项目。` : "账号固定创建为测试人员，创建成功后将立即加入当前项目。"}</p>}{createError && <InlineMessage kind="error">{createError}</InlineMessage>}<form className="auth-form" onSubmit={createFixedUser}><label>用户名<input autoFocus value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} minLength={3} disabled={createBusy || Boolean(createdUsername)} required /></label><label>显示名称<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} disabled={createBusy || Boolean(createdUsername)} required /></label><label>初始密码<input type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} disabled={createBusy || Boolean(createdUsername)} required /></label>{auth?.role === "platform_admin" && !projectIdToJoin && <label>固定角色<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as PlatformRole })} disabled={createBusy}><option value="tester">测试人员</option><option value="admin">管理员</option><option value="platform_admin">平台管理员</option></select></label>}<div className="dialog-actions"><button type="button" className="secondary-button" disabled={createBusy} onClick={() => { setCreating(false); setCreateError(""); }}>取消</button><button className="primary-button" disabled={createBusy}>{createBusy ? "提交中…" : createdUsername ? "重试加入项目" : "确认创建"}</button></div></form></section></div>}
  </section></WorkspaceShell>;
}

function FixedRolesPage() {
  const rows = [
    ["使用公共工具", "✓", "✓", "✓"],
    ["使用项目工具", "全平台", "负责项目", "所属项目"],
    ["管理项目成员", "全部项目", "负责项目 tester", "—"],
    ["管理工具配置", "全部工具", "负责项目普通配置", "—"],
    ["额外单工具授权", "创建 / 撤销", "仅查看自身来源", "仅查看自身来源"],
    ["查看业务资源", "全平台", "负责项目快照 + 本人", "仅本人"],
    ["平台配置 / 审计", "✓", "—", "—"],
  ];
  return <WorkspaceShell><section className="workspace-page access-page"><PageHeader eyebrow="14 / ACCESS CONTROL" title="固定角色矩阵" copy="角色只表达管理级别，不允许新增、删除、重命名或任意绑定细粒度权限。" /><section className="access-card role-overview"><div><h2>三种固定全局角色</h2><p>每个用户恰好一个角色；项目和额外授权负责工具范围。</p></div><div><span className="role-badge platform_admin">平台管理员</span><span className="role-badge admin">管理员</span><span className="role-badge tester">测试人员</span></div></section><AccessTable headers={["能力", "平台管理员", "管理员", "测试人员"]}>{rows.map((row) => <tr key={row[0]}>{row.map((cell, index) => <td key={cell}><strong>{index === 0 ? cell : undefined}</strong>{index === 0 ? null : cell}</td>)}</tr>)}</AccessTable><p className="role-example">权限解释示例：管理员可以管理自己负责项目的工具，但额外授权始终只允许操作本人业务资源。</p></section></WorkspaceShell>;
}

function UsersPage() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<AdminUser | null>(null);
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role_ids: [] as string[] });
  const [resetPassword, setResetPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useModal(creating || Boolean(resetting), () => { setCreating(false); setResetting(null); setResetPassword(""); });
  const load = useCallback(() => apiJson<AdminUser[]>("/admin/users").then(setItems).catch((e) => setError(e.message)), []);
  useEffect(() => { void load(); void apiJson<Role[]>("/admin/roles").then(setRoles).catch((e) => setError(e.message)); }, [load]);
  function toggleRole(roleId: string) {
    setForm((current) => ({ ...current, role_ids: current.role_ids.includes(roleId) ? current.role_ids.filter((id) => id !== roleId) : [...current.role_ids, roleId] }));
  }
  async function createUser(event: FormEvent) {
    event.preventDefault(); setError(""); setMessage("");
    const passwordError = validateNewPassword(form.password);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    try {
      await apiJson("/admin/users", { method: "POST", body: JSON.stringify({ ...form, must_change_password: true }) });
      setCreating(false); setForm({ username: "", display_name: "", password: "", role_ids: [] }); setMessage("用户已创建，首次登录必须修改密码。"); await load();
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建失败"); }
  }
  async function updateUser(user: AdminUser, payload: Record<string, unknown>, successMessage: string) {
    setError(""); setMessage("");
    try { await apiJson(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(payload) }); setMessage(successMessage); await load(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "更新失败"); }
  }
  async function submitReset(event: FormEvent) {
    event.preventDefault(); if (!resetting) return;
    setError(""); setMessage("");
    const passwordError = validateNewPassword(resetPassword);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    try { await apiJson(`/admin/users/${resetting.id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: resetPassword }) }); setResetPassword(""); setResetting(null); setMessage("密码已重置，目标用户的全部会话已撤销。"); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "重置失败"); }
  }
  async function revokeUserSessions(user: AdminUser) {
    setError(""); setMessage("");
    try { await apiJson(`/admin/users/${user.id}/sessions`, { method: "DELETE" }); setMessage(`${user.display_name} 的会话已全部撤销。`); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "撤销失败"); }
  }
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow="IDENTITY" title="用户管理" copy="本地账号的状态、角色和会话都由平台统一管理。" actions={<button className="primary-button" onClick={() => setCreating(true)}>创建用户</button>} /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="data-panel user-table"><div className="table-header"><span>用户</span><span>角色</span><span>状态 / 最近登录</span><span>操作</span></div>{items.length === 0 ? <EmptyState title="尚无用户" copy="创建本地用户并分配最小必要角色。" /> : items.map((item) => <div className="table-row" key={item.id}><strong>{item.display_name}<small>{item.username}</small></strong><span>{item.role_ids.length ? item.role_ids.map((id) => roles.find((role) => role.id === id)?.name ?? id).join("、") : "未分配"}</span><span><StatusBadge value={item.status} /><small>{item.last_login_at ? new Date(item.last_login_at).toLocaleString() : "尚未登录"}</small></span><div className="row-actions"><button className="link-button" onClick={() => void updateUser(item, { status: item.status === "active" ? "disabled" : "active" }, item.status === "active" ? "用户已禁用并撤销会话。" : "用户已启用。")}>{item.status === "active" ? "禁用" : "启用"}</button><button className="link-button" onClick={() => setResetting(item)}>重置密码</button><button className="link-button" onClick={() => void revokeUserSessions(item)}>强制退出</button></div></div>)}</div>{creating && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="create-user-title"><p className="section-label">LOCAL IDENTITY</p><h2 id="create-user-title">创建用户</h2><form className="auth-form" onSubmit={createUser}><label>用户名<input autoFocus value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} minLength={3} required /></label><label>显示名<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required /></label><label>初始密码<input type="password" autoComplete="new-password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required /></label><fieldset><legend>角色</legend>{roles.map((role) => <label className="checkbox-row" key={role.id}><input type="checkbox" checked={form.role_ids.includes(role.id)} onChange={() => toggleRole(role.id)} />{role.name}</label>)}</fieldset><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setCreating(false)}>取消</button><button className="primary-button">创建用户</button></div></form></section></div>}{resetting && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="reset-password-title"><p className="section-label">HIGH-RISK ACTION</p><h2 id="reset-password-title">重置 {resetting.display_name} 的密码</h2><p>提交后该用户所有会话会立即失效。</p><form className="auth-form" onSubmit={submitReset}><label>新密码<input autoFocus type="password" autoComplete="new-password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setResetting(null)}>取消</button><button className="primary-button">确认重置</button></div></form></section></div>}</section></WorkspaceShell>;
}

function RolesPage() {
  const [items, setItems] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<PermissionDefinition[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [editing, setEditing] = useState<Role | null | undefined>(undefined);
  const [roleForm, setRoleForm] = useState({ name: "", description: "", grants: [] as RoleGrant[] });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useModal(editing !== undefined, () => setEditing(undefined));
  const load = useCallback(() => apiJson<Role[]>("/admin/roles").then(setItems), []);
  useEffect(() => { void Promise.all([load(), apiJson<PermissionDefinition[]>("/admin/permissions").then(setPermissions), fetchTools().then(setTools)]).catch((requestError) => setError(requestError.message)); }, [load]);
  function openRole(role?: Role, copy = false) {
    setEditing(copy ? null : role ?? null);
    setRoleForm({ name: copy ? `${role?.name ?? ""} 副本` : role?.name ?? "", description: role?.description ?? "", grants: role?.grants.map((grant) => ({ ...grant })) ?? [] });
  }
  function hasGrant(permissionCode: string, resourceType: "platform" | "tool", resourceId: string) {
    return roleForm.grants.some((grant) => grant.permission_code === permissionCode && grant.resource_type === resourceType && grant.resource_id === resourceId);
  }
  function toggleGrant(permissionCode: string, resourceType: "platform" | "tool", resourceId: string) {
    setRoleForm((current) => {
      const exists = current.grants.some((grant) => grant.permission_code === permissionCode && grant.resource_type === resourceType && grant.resource_id === resourceId);
      return { ...current, grants: exists ? current.grants.filter((grant) => !(grant.permission_code === permissionCode && grant.resource_type === resourceType && grant.resource_id === resourceId)) : [...current.grants, { permission_code: permissionCode, resource_type: resourceType, resource_id: resourceId }] };
    });
  }
  async function saveRole(event: FormEvent) {
    event.preventDefault(); setError(""); setMessage("");
    try {
      if (editing) await apiJson(`/admin/roles/${editing.id}`, { method: "PATCH", body: JSON.stringify({ name: editing.is_builtin ? undefined : roleForm.name, description: roleForm.description, grants: roleForm.grants }) });
      else await apiJson("/admin/roles", { method: "POST", body: JSON.stringify(roleForm) });
      setEditing(undefined); setMessage(editing ? "角色权限已更新，后续请求立即使用新权限。" : "角色已创建。"); await load();
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "保存失败"); }
  }
  async function deleteRole(role: Role) {
    setError(""); setMessage("");
    try { await apiJson(`/admin/roles/${role.id}`, { method: "DELETE" }); setMessage("角色已删除。"); await load(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "删除失败"); }
  }
  const toolScopes = [{ id: "*", name: "全部工具" }, ...tools.map((tool) => ({ id: tool.id, name: tool.name }))];
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow="RBAC" title="角色与工具权限" copy="用户多角色权限取并集；工具权限可授予单一工具或全部工具。" actions={<button className="primary-button" onClick={() => openRole()}>创建角色</button>} /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="role-grid">{items.map((role) => <article className="role-card" key={role.id}><div><p className="section-label">{role.is_builtin ? "BUILT-IN" : "CUSTOM"}</p><h2>{role.name}</h2><p>{role.description}</p></div><ul>{role.grants.map((grant) => <li key={`${grant.permission_code}:${grant.resource_id}`}><code>{grant.permission_code}</code><span>{grant.resource_id}</span></li>)}</ul><div className="row-actions"><button className="link-button" onClick={() => openRole(role)}>编辑</button><button className="link-button" onClick={() => openRole(role, true)}>复制</button>{!role.is_builtin && <button className="link-button" onClick={() => void deleteRole(role)}>删除</button>}</div></article>)}</div>{editing !== undefined && <div className="modal-backdrop" role="presentation"><section className="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="role-dialog-title"><p className="section-label">PERMISSION MATRIX</p><h2 id="role-dialog-title">{editing ? `编辑 ${editing.name}` : "创建角色"}</h2><form className="auth-form" onSubmit={saveRole}><label>角色名称<input autoFocus disabled={Boolean(editing?.is_builtin)} value={roleForm.name} onChange={(event) => setRoleForm({ ...roleForm, name: event.target.value })} required /></label><label>说明<textarea value={roleForm.description} onChange={(event) => setRoleForm({ ...roleForm, description: event.target.value })} /></label><div className="permission-matrix">{permissions.map((permission) => <section key={permission.code}><div><strong>{permission.name}</strong><code>{permission.code}</code><small>{permission.description}</small></div><div>{permission.resource_type === "platform" ? <label className="checkbox-row"><input type="checkbox" checked={hasGrant(permission.code, "platform", "*")} onChange={() => toggleGrant(permission.code, "platform", "*")} />允许</label> : toolScopes.map((scope) => <label className="checkbox-row" key={scope.id}><input type="checkbox" checked={hasGrant(permission.code, "tool", scope.id)} onChange={() => toggleGrant(permission.code, "tool", scope.id)} />{scope.name}</label>)}</div></section>)}</div><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setEditing(undefined)}>取消</button><button className="primary-button">保存角色</button></div></form></section></div>}</section></WorkspaceShell>;
}

function AuditPage() {
  const now = new Date();
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [startDate, setStartDate] = useState(() => new Date(now.getTime() - 7 * 86400000).toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(() => now.toISOString().slice(0, 10));
  const [error, setError] = useState("");
  useEffect(() => { void apiJson<{ items: AuditEvent[] }>("/audit/events?page=1&page_size=100").then((result) => setItems(result.items)).catch((e) => setError(e.message)); }, []);
  async function exportAudit() {
    setError("");
    try {
      const start = new Date(`${startDate}T00:00:00`).toISOString();
      const end = new Date(`${endDate}T23:59:59.999`).toISOString();
      const response = await request(`/api/v1/audit/exports?start_at=${encodeURIComponent(start)}&end_at=${encodeURIComponent(end)}`, { method: "POST" });
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `audit-${startDate}-${endDate}.csv`; anchor.click(); URL.revokeObjectURL(url);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "导出失败"); }
  }
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow="AUDIT TRAIL" title="审计日志" copy="审计日志用于回答“谁在什么时间对哪个工具做了什么，结果如何”，便于安全追溯和故障复盘。" actions={<div className="audit-export"><label>开始日期<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>结束日期<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label><button className="secondary-button" onClick={() => void exportAudit()}>导出 CSV</button></div>} /><ManagementNav />{error ? <InlineMessage kind="error">{error}</InlineMessage> : <div className="data-panel audit-table"><div className="table-header"><span>时间 / 操作人</span><span>动作</span><span>资源</span><span>结果</span></div>{items.length === 0 ? <EmptyState title="尚无审计事件" copy="登录、权限和配置变更后会显示在这里。" /> : items.map((item) => <div className="table-row" key={item.id}><strong>{new Date(item.occurred_at).toLocaleString()}<small>{String(item.actor_snapshot.username ?? item.actor_id ?? item.actor_type)}</small></strong><code>{item.action}</code><span>{item.tool_id ?? item.resource_type}{item.resource_id ? ` / ${item.resource_id}` : ""}</span><StatusBadge value={item.outcome} /></div>)}</div>}</section></WorkspaceShell>;
}

function identityLabel(identity: ComponentIdentity | null): string {
  if (!identity) return "—";
  const suffix = identity.dirty ? " · dirty" : "";
  return `${identity.version || "未知"}${suffix}`;
}

function VersionDetailsPage() {
  const [matrix, setMatrix] = useState<VersionMatrix | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setMatrix(await apiJson<VersionMatrix>("/system/version-matrix")); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "版本状态加载失败"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return <WorkspaceShell><section className="workspace-page version-page"><PageHeader eyebrow="RELEASE IDENTITY" title="版本状态" copy="比较代码内容、有效配置与数据库结构；组件版本便于阅读，内容哈希和镜像 digest 提供可验证证据。" actions={<button className="secondary-button" disabled={loading} onClick={() => void load()}>{loading ? "刷新中…" : "刷新状态"}</button>} /><ManagementNav />
    {error && <InlineMessage kind="error">{error}</InlineMessage>}
    {matrix?.prod_error && <InlineMessage>{matrix.prod_error}，Dev 状态仍可正常查看。</InlineMessage>}
    {loading && !matrix ? <LoadingPage label="正在核对组件版本…" /> : matrix && <>
      <div className="version-summary"><span>产品 <strong>{matrix.product_version}</strong></span><span>运行环境 <strong>{matrix.runtime_environment.toUpperCase()}</strong></span><span>检查时间 <strong>{new Date(matrix.checked_at).toLocaleString()}</strong></span></div>
      <div className="version-table-wrap"><table className="version-table"><thead><tr><th scope="col">组件</th><th scope="col">Dev 实际</th><th scope="col">Prod 实际</th><th scope="col">Prod 期望</th><th scope="col">健康</th><th scope="col">状态</th><th scope="col"><span className="visually-hidden">详情</span></th></tr></thead><tbody>{matrix.rows.map((row) => <Fragment key={row.component_id}>
        <tr><th scope="row"><code>{row.component_id}</code></th><td>{identityLabel(row.dev)}</td><td>{identityLabel(row.prod)}</td><td>{row.prod_expected?.version ?? "旧发布记录 / 版本未知"}</td><td>{row.prod?.health ?? row.dev?.health ?? "未知"}</td><td><StatusBadge value={row.primary_status} /></td><td><button className="link-button" type="button" aria-expanded={expanded === row.component_id} aria-controls={`version-${row.component_id}`} onClick={() => setExpanded(expanded === row.component_id ? null : row.component_id)}>{expanded === row.component_id ? "收起" : "详情"}</button></td></tr>
        {expanded === row.component_id && <tr id={`version-${row.component_id}`} className="version-detail-row"><td colSpan={7}><dl><div><dt>Dev SHA</dt><dd>{row.dev?.revision ?? "—"}</dd></div><div><dt>Prod SHA</dt><dd>{row.prod?.revision ?? "—"}</dd></div><div><dt>Dev 内容哈希</dt><dd>{row.dev?.content_sha256 ?? "未验证"}</dd></div><div><dt>Prod 内容哈希</dt><dd>{row.prod?.content_sha256 ?? "未验证"}</dd></div><div><dt>Dev 配置哈希</dt><dd>{row.dev?.config_sha256 ?? "不适用 / 未验证"}</dd></div><div><dt>Prod 配置哈希</dt><dd>{row.prod?.config_sha256 ?? "不适用 / 未验证"}</dd></div><div><dt>Dev digest</dt><dd>{row.dev?.digest ?? "—"}</dd></div><div><dt>Prod digest</dt><dd>{row.prod?.digest ?? "—"}</dd></div><div><dt>问题</dt><dd>{row.issues.join("、")}</dd></div></dl></td></tr>}
      </Fragment>)}</tbody></table></div>
      <div className="version-footnotes"><p>数据库结构 <StatusBadge value={matrix.database_comparison.primary_status} /></p><p>Dev migration：{matrix.dev?.database.alembic_revision ?? "—"}</p><p>Prod migration：{matrix.prod?.database.alembic_revision ?? "—"}</p><p>Dev schema hash：{matrix.dev?.database.schema_sha256 ?? "—"}</p><p>Prod schema hash：{matrix.prod?.database.schema_sha256 ?? "—"}</p><p>Dev Config Releases：{Object.keys(matrix.dev?.config_releases ?? {}).length}</p><p>Prod Config Releases：{Object.keys(matrix.prod?.config_releases ?? {}).length}</p><p>业务数据归各环境所有，不参与一致性比较。</p></div>
    </>}
  </section></WorkspaceShell>;
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const tone = ["healthy", "active", "enabled", "success", "ok", "configured", "已配置", "一致"].includes(normalized) || normalized.startsWith("v") ? "success" : ["missing", "invalid", "expiring", "failed", "disabled", "unhealthy", "不可用", "不兼容", "环境漂移", "配置不一致", "内容不一致", "结构不一致", "迁移不一致"].includes(normalized) ? "danger" : "neutral";
  return <span className={`status-badge status-badge-${tone}`}>{value}</span>;
}

function EmptyState({ title, copy }: { title: string; copy: string }) { return <div className="empty-state"><strong>{title}</strong><p>{copy}</p></div>; }

function ForbiddenPage() {
  return <WorkspaceShell><section className="workspace-page access-page access-state-page">
    <PageHeader eyebrow="15 / ACCESS CONTROL" title="状态与异常" copy="权限拒绝、空状态和失效预览均使用清晰的下一步操作。" />
    <section className="access-card permission-denied-card" aria-labelledby="permission-denied-title">
      <span className="state-code">403 / PERMISSION DENIED</span>
      <h2 id="permission-denied-title">没有管理权限</h2>
      <p>当前账号没有访问此平台管理功能的权限。不可见资源与不存在资源仍统一返回 404，避免泄露对象是否存在。</p>
      <NavLink className="secondary-button" to="/">返回工作台</NavLink>
    </section>
  </section></WorkspaceShell>;
}
function NotFoundPage() { return <WorkspaceShell><section className="not-found"><p className="section-label">404</p><h1>页面不存在</h1><NavLink className="tool-link" to="/">返回平台首页</NavLink></section></WorkspaceShell>; }

function DomainRoute({ domainId }: { domainId: "ai-testing" | "automation" | "quality-analysis" | "domain-evaluation" }) {
  return <WorkspaceShell><CapabilityDomainPage domainId={domainId} /></WorkspaceShell>;
}

function AppRoutes() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route path="/register" element={<RegisterPage />} />
    <Route path="/setup" element={<SetupPage />} />
    <Route path="/account" element={<Protected><AccountPage /></Protected>} />
    <Route path="/account/password" element={<Protected><ChangePasswordPage /></Protected>} />
    <Route path="/account/credentials" element={<Protected><PersonalCredentialsPage /></Protected>} />
    <Route path="/account/llm" element={<Protected><PersonalLlmPage /></Protected>} />
    <Route path="/" element={<Protected><HomePage /></Protected>} />
    <Route path="/access" element={<Protected><AccessHubPage /></Protected>} />
    <Route path="/ai-testing" element={<Protected><DomainRoute domainId="ai-testing" /></Protected>} />
    <Route path="/automation" element={<Protected><DomainRoute domainId="automation" /></Protected>} />
    <Route path="/quality-analysis" element={<Protected><DomainRoute domainId="quality-analysis" /></Protected>} />
    <Route path="/domain-evaluation" element={<Protected><DomainRoute domainId="domain-evaluation" /></Protected>} />
    {/* 旧书签只做安全重定向，不再挂载 legacy 公共 LLM 编辑器。 */}
    <Route path="/settings/llm" element={<Protected><Navigate to="/account/llm" replace /></Protected>} />
    <Route path="/settings/platform-llm" element={<Protected roles={["platform_admin"]}><LlmSettingsPage /></Protected>} />
    <Route path="/settings/config" element={<Protected permission="platform.config.manage"><ConfigPage /></Protected>} />
    <Route path="/settings/secrets" element={<Protected permission="platform.secret.manage"><SecretsPage /></Protected>} />
    <Route path="/settings/credential-agents" element={<Protected roles={["platform_admin"]}><CredentialsPage /></Protected>} />
    <Route path="/settings/credentials" element={<Protected permission="platform.credential.readiness.view"><CredentialReadinessPage /></Protected>} />
    <Route path="/projects" element={<Protected><ProjectsPage /></Protected>} />
    <Route path="/projects/new" element={<Protected roles={["platform_admin"]}><ProjectsPage /></Protected>} />
    <Route path="/projects/:projectId" element={<Protected><ProjectOverviewRedirect /></Protected>} />
    <Route path="/projects/:projectId/overview" element={<Protected><ProjectDetailPage /></Protected>} />
    <Route path="/projects/:projectId/members" element={<Protected><ProjectDetailPage /></Protected>} />
    <Route path="/projects/:projectId/tools" element={<Protected><ProjectDetailPage /></Protected>} />
    <Route path="/admin/tool-access" element={<Protected roles={["platform_admin"]}><ToolAccessAdminPage /></Protected>} />
    <Route path="/admin/tool-access/:toolId" element={<Protected roles={["platform_admin"]}><ToolAccessAdminPage /></Protected>} />
    <Route path="/admin/tool-grants" element={<Protected roles={["platform_admin"]}><ToolAccessAdminPage /></Protected>} />
    <Route path="/admin/users" element={<Protected roles={["platform_admin", "admin"]}><FixedUsersPage /></Protected>} />
    <Route path="/admin/users/:userId" element={<Protected roles={["platform_admin", "admin"]}><FixedUsersPage /></Protected>} />
    <Route path="/admin/roles" element={<Protected roles={["platform_admin"]}><FixedRolesPage /></Protected>} />
    <Route path="/audit" element={<Protected permission="platform.audit.view"><AuditPage /></Protected>} />
    <Route path="/system/versions" element={<Protected permission="platform.audit.view"><VersionDetailsPage /></Protected>} />
    <Route path="/403" element={<Protected><ForbiddenPage /></Protected>} />
    <Route path="*" element={<Protected><NotFoundPage /></Protected>} />
  </Routes>;
}

function PlatformProviders() {
  const { auth } = useAuth();
  return <ToolCatalogProvider enabled={Boolean(auth)}><AppRoutes /></ToolCatalogProvider>;
}

/** 第二阶段平台入口：统一会话、权限路由和管理工作台。 */
export function App() {
  return <BrowserRouter><AuthProvider><PlatformProviders /></AuthProvider></BrowserRouter>;
}
