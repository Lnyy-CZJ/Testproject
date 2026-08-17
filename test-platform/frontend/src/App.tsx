import {
  createContext,
  type FormEvent,
  type PropsWithChildren,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { ApiError, apiJson, fetchTools, request } from "./api/client";
import platformVersionSource from "../../VERSION?raw";
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
  CredentialMetadata,
  PermissionDefinition,
  LlmBinding,
  LlmEffectiveConfig,
  LlmProfile,
  Role,
  RoleGrant,
  SecretMetadata,
  UserSession,
} from "./types/platform";
import type { Tool } from "./types/tool";

const PLATFORM_VERSION = platformVersionSource.trim();

interface AuthContextValue {
  auth: AuthState | null;
  loading: boolean;
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
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setAuth(await apiJson<AuthState>("/auth/me"));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setAuth(null);
      else throw error;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload().catch(() => setLoading(false));
  }, [reload]);
  return (
    <AuthContext.Provider value={{ auth, loading, reload, setAuth }}>
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

/** 为桌面对话框提供 Esc 关闭、焦点循环和关闭后的焦点恢复。 */
function useModal(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = document.querySelector<HTMLElement>(".modal-backdrop .dialog");
    const focusable = () => [...(dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])') ?? [])];
    focusable()[0]?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
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
  const { auth, setAuth } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
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
      setError(requestError instanceof Error ? requestError.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <LoginLayout>
      <form className="auth-form login-form" onSubmit={submit}>
        <label>用户名<input autoFocus autoComplete="username" placeholder="请输入用户名" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
        <label>密码<input type="password" autoComplete="current-password" placeholder="请输入密码" aria-invalid={Boolean(error)} aria-describedby={error ? "login-error" : undefined} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <div id="login-error"><InlineMessage kind="error">{error}</InlineMessage></div>}
        <button className="primary-button" disabled={submitting}>{submitting ? "正在验证…" : "登录"}</button>
      </form>
    </LoginLayout>
  );
}

function LoginLayout({ children }: PropsWithChildren) {
  return <div className="login-shell">
    <header className="login-header">
      <div className="login-header-content">
        <span className="brand"><span className="brand-mark" aria-hidden="true">T</span><span>测试开发平台</span></span>
        <nav className="login-capabilities" aria-label="平台能力预览"><span>工作台</span><span>AI 测试</span><span>自动化</span><span>质量分析</span><span>专项评测</span></nav>
        <div className="login-header-meta"><span>DEV</span><span>工程工作台</span></div>
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
        <div className="login-panel-heading"><h1 id="login-title">欢迎回来</h1><p>登录后继续你的测试工作</p></div>
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
        <label>密码<input type="password" minLength={12} autoComplete="new-password" value={values.password} onChange={(event) => setValues({ ...values, password: event.target.value })} required /></label>
        {error && <InlineMessage kind="error">{error}</InlineMessage>}
        <button className="primary-button">创建管理员</button>
      </form>
    </AuthLayout>
  );
}

function AuthLayout({ eyebrow, title, copy, children }: PropsWithChildren<{ eyebrow: string; title: string; copy: string }>) {
  return <main className="auth-page"><section className="auth-intro"><span className="brand-mark">T</span><p className="section-label">{eyebrow}</p><h1>{title}</h1><p>{copy}</p></section><section className="auth-panel">{children}</section></main>;
}

function Protected({ children, permission }: PropsWithChildren<{ permission?: string }>) {
  const { auth, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingPage />;
  if (!auth) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (auth.user.must_change_password && location.pathname !== "/account/password") return <Navigate to="/account/password" replace />;
  if (permission && !auth.platform_permissions.includes(permission)) return <Navigate to="/403" replace />;
  return children;
}

function ChangePasswordPage() {
  const { reload } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    try { await apiJson("/auth/change-password", { method: "POST", body: JSON.stringify(values) }); await reload(); navigate("/", { replace: true }); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "修改密码失败"); }
  }
  return <WorkspaceShell><section className="workspace-page narrow-page"><PageHeader eyebrow="ACCOUNT SECURITY" title="修改密码" copy="首次登录或管理员重置密码后，必须先设置只有你知道的新密码。" />{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="settings-card"><form className="auth-form" onSubmit={submit}><label>当前密码<input autoFocus type="password" autoComplete="current-password" value={values.current_password} onChange={(event) => setValues({ ...values, current_password: event.target.value })} required /></label><label>新密码<input type="password" autoComplete="new-password" minLength={12} value={values.new_password} onChange={(event) => setValues({ ...values, new_password: event.target.value })} required /></label><button className="primary-button">保存并撤销其他会话</button></form></div></section></WorkspaceShell>;
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
  const { auth } = useAuth();
  const environment = useEnvironment();
  const { tools, groups, unknownTools, healthStates, loading, refreshing, error, refreshHealth, reloadCatalog } = useToolCatalog();
  const [credentialIssueCount, setCredentialIssueCount] = useState<number | null>(null);
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

  useEffect(() => {
    if (!auth?.platform_permissions.includes("platform.secret.manage")) {
      setCredentialIssueCount(null);
      return;
    }
    let active = true;
    void apiJson<CredentialMetadata[]>(`/credentials?environment_id=${environment}`).then((items) => {
      if (!active || !Array.isArray(items)) return;
      const soon = Date.now() + 24 * 60 * 60 * 1000;
      setCredentialIssueCount(items.filter((item) => item.status !== "active" || (item.expires_at && new Date(item.expires_at).getTime() <= soon)).length);
    }).catch(() => { if (active) setCredentialIssueCount(null); });
    return () => { active = false; };
  }, [auth, environment]);

  return <WorkspaceShell><section className="workbench-home" aria-labelledby="workbench-title"><div className="workbench-intro"><div><p className="section-label">AI TESTING WORKSPACE</p><h1 id="workbench-title">AI 测试与质量工程工作台</h1><p>使用 AI 设计测试，通过自动化持续验证，并借助专业工具分析质量问题。</p></div><aside className="platform-status" aria-label="平台状态"><div className="status-panel-heading"><span>平台状态</span><button className="link-button" type="button" disabled={refreshing || loading || tools.length === 0} onClick={() => void refreshHealth()}>{refreshing ? "检测中…" : "重新检测"}</button></div><dl><div><dt>版本</dt><dd>{PLATFORM_VERSION}</dd></div><div><dt>环境</dt><dd>{environment.toUpperCase()}</dd></div><div><dt>已授权</dt><dd>{tools.length}</dd></div><div><dt>异常</dt><dd>{healthCounts.unhealthy}</dd></div></dl><p>{healthCounts.healthy} 项正常 · {healthCounts.checking} 项检测中</p>{credentialIssueCount !== null && <NavLink to="/settings/credentials">凭证异常或临期 {credentialIssueCount} 项</NavLink>}</aside></div>
  {error && <div className="catalog-state catalog-state-error" role="alert"><div><strong>平台身份或数据服务暂时不可用</strong><p>已停止工具导航，不会恢复匿名入口。{error}</p></div><button className="secondary-button" type="button" onClick={() => void reloadCatalog()}>重新加载目录</button></div>}
  {loading ? <div className="catalog-state" role="status"><span className="loading-indicator" />正在读取权限与能力目录…</div> : !error && <><section className="mission-section" aria-labelledby="mission-title"><div className="section-heading"><div><p className="section-label">我现在想做什么</p><h2 id="mission-title">从测试目标进入能力</h2></div></div>{aiCapabilities.length > 0 ? <div className="primary-capability-grid">{aiCapabilities.map((capability) => <CapabilityCard key={capability.toolId} capability={capability} />)}</div> : <EmptyState title="当前没有 AI 测试能力" copy="平台只展示服务端已授权的能力。" />}</section><section className="professional-section" aria-labelledby="professional-title"><div className="section-heading"><div><p className="section-label">持续验证与专业工具</p><h2 id="professional-title">让每项能力完成自己的使命</h2></div><span className="section-count">{professionalCapabilities.length} 项能力</span></div>{professionalCapabilities.length > 0 && <div className="professional-capability-grid">{professionalCapabilities.map((capability) => <CapabilityCard key={capability.toolId} capability={capability} compact />)}</div>}</section>{unknownTools.length > 0 && <section className="unknown-tools" aria-labelledby="unknown-tools-title"><h2 id="unknown-tools-title">其他已授权工具</h2><ToolGrid tools={unknownTools} healthStates={healthStates} /></section>}</>}</section></WorkspaceShell>;
}

function PageHeader({ eyebrow, title, copy, actions }: { eyebrow: string; title: string; copy: string; actions?: ReactNode }) {
  return <div className="workspace-heading"><div><p className="section-label">{eyebrow}</p><h1>{title}</h1><p>{copy}</p></div>{actions}</div>;
}

function ManagementNav() {
  const { auth } = useAuth();
  const has = (permission: string) => Boolean(auth?.platform_permissions.includes(permission));
  return <nav className="subnav" aria-label="平台管理">
    {has("platform.user.manage") && <NavLink to="/admin/users">用户管理</NavLink>}
    {has("platform.role.manage") && <NavLink to="/admin/roles">角色与权限</NavLink>}
    {(has("platform.llm.manage") || has("platform.llm.secret.manage")) && <NavLink to="/settings/llm">LLM 配置</NavLink>}
    {has("platform.config.manage") && <NavLink to="/settings/config">普通配置</NavLink>}
    {has("platform.secret.manage") && <><NavLink to="/settings/secrets">Secret</NavLink><NavLink to="/settings/credentials">凭证状态</NavLink></>}
    {has("platform.audit.view") && <NavLink to="/audit">审计日志</NavLink>}
  </nav>;
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

function ConfigPage() {
  const environment = useEnvironment();
  const [items, setItems] = useState<ConfigDefinition[]>([]);
  const [owner, setOwner] = useState("");
  const [releases, setReleases] = useState<ConfigRelease[]>([]);
  const [draft, setDraft] = useState<ConfigRelease | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const owners = [...new Set(items.filter((item) => item.sensitivity === "normal").map((item) => item.owner_id))];
  const ownerItems = items.filter((item) => item.owner_id === owner && item.sensitivity === "normal");

  const loadReleases = useCallback(async (selectedOwner: string) => {
    if (!selectedOwner) return;
    const rows = await apiJson<ConfigRelease[]>(`/config/releases?environment_id=${environment}&owner_type=tool&owner_id=${encodeURIComponent(selectedOwner)}`);
    setReleases(rows);
    const currentDraft = rows.find((row) => row.status === "draft") ?? null;
    setDraft(currentDraft);
    if (currentDraft) setValues(Object.fromEntries(currentDraft.items.map((item) => [item.definition_id, item.value])));
    else setValues({});
  }, [environment]);

  useEffect(() => {
    void apiJson<ConfigDefinition[]>("/config/definitions").then((rows) => {
      setItems(rows);
      const firstOwner = rows.find((item) => item.sensitivity === "normal")?.owner_id ?? "";
      setOwner((current) => current || firstOwner);
    }).catch((requestError) => setError(requestError.message));
  }, []);
  useEffect(() => { void loadReleases(owner).catch((requestError) => setError(requestError.message)); }, [loadReleases, owner]);
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
    if (definition.value_type !== "json" || typeof value !== "string") return value;
    try { return JSON.parse(value); }
    catch { throw new Error(`${definition.display_name} 必须是有效 JSON。`); }
  }
  async function createDraft() {
    setError(""); setMessage("");
    try {
      const next = await apiJson<ConfigRelease>("/config/releases", { method: "POST", body: JSON.stringify({ environment_id: environment, owner_type: "tool", owner_id: owner }) });
      setDraft(next); setValues(Object.fromEntries(next.items.map((item) => [item.definition_id, item.value]))); setMessage(`已创建 v${next.version} 草稿。`);
      await loadReleases(owner);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建草稿失败"); }
  }
  async function saveDraft() {
    if (!draft) return;
    setError(""); setMessage("");
    try {
      const updated = await apiJson<ConfigRelease>(`/config/releases/${draft.id}/items`, { method: "PUT", body: JSON.stringify({ revision: draft.revision, items: ownerItems.map((item) => ({ definition_id: item.id, value: payloadValue(item) })) }) });
      setDraft(updated); setMessage(`v${updated.version} 草稿已保存。`); await loadReleases(owner);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "保存失败"); }
  }
  async function releaseAction(action: "validate" | "publish", target = draft) {
    if (!target) return;
    if (action === "publish" && environment === "prod" && !confirmPublish) {
      setConfirmPublish(true); setMessage("这是 PROD 发布。请复核差异后再次点击“确认发布 PROD”。"); return;
    }
    setError(""); setMessage("");
    try {
      await apiJson(`/config/releases/${target.id}/${action}`, { method: "POST" });
      setMessage(action === "validate" ? "配置校验通过。" : `v${target.version} 已发布；新任务将使用该版本。`);
      setConfirmPublish(false);
      await loadReleases(owner);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "操作失败"); }
  }
  async function rollback(target: ConfigRelease) {
    setError(""); setMessage("");
    try {
      const next = await apiJson<ConfigRelease>(`/config/releases/${target.id}/rollback`, { method: "POST" });
      setMessage(`已基于 v${target.version} 创建回滚版本 v${next.version}。`); await loadReleases(owner);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "回滚失败"); }
  }
  async function promote(target: ConfigRelease) {
    setError(""); setMessage("");
    try {
      const next = await apiJson<ConfigRelease>(`/config/releases/${target.id}/promote?target_environment=prod`, { method: "POST" });
      setMessage(`已从 DEV v${target.version} 创建 PROD v${next.version} 草稿；Secret 未复制。`);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "提升失败"); }
  }

  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow={`${environment.toUpperCase()} / CONFIGURATION`} title="配置控制面" copy="只有已登记的键可以在 Web 修改；发布与回滚始终保留可追溯版本。" actions={<label className="compact-field">工具<select value={owner} onChange={(event) => { setOwner(event.target.value); setConfirmPublish(false); }}>{owners.map((item) => <option key={item}>{item}</option>)}</select></label>} /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}{ownerItems.length === 0 ? <EmptyState title="没有可管理的配置" copy="请检查当前角色的工具配置权限。" /> : <><div className="config-toolbar"><div><strong>{owner}</strong><span>{draft ? `v${draft.version} 草稿 · revision ${draft.revision}` : "当前没有草稿"}</span></div><div className="dialog-actions">{!draft ? <button className="primary-button" onClick={() => void createDraft()}>创建草稿</button> : <><button className="secondary-button" onClick={() => void saveDraft()}>保存草稿</button><button className="secondary-button" onClick={() => void releaseAction("validate")}>校验</button><button className="primary-button" onClick={() => void releaseAction("publish")}>{environment === "prod" && confirmPublish ? "确认发布 PROD" : "发布"}</button></>}</div></div><div className="config-grid">{ownerItems.map((item) => <label className="config-field" key={item.id}><span>{item.display_name}<small>{item.key} · {item.apply_mode}</small></span>{["bool", "boolean"].includes(item.value_type) ? <select disabled={!draft} value={String(values[item.id] ?? item.default_value ?? false)} onChange={(event) => updateValue(item, event.target.value)}><option value="true">true</option><option value="false">false</option></select> : <input disabled={!draft} type={["int", "integer", "float"].includes(item.value_type) ? "number" : "text"} step={item.value_type === "float" ? "any" : undefined} value={inputValue(item)} onChange={(event) => updateValue(item, event.target.value)} required={item.required} />}</label>)}</div><section className="release-history" aria-labelledby="release-history-title"><h2 id="release-history-title">版本历史</h2>{releases.length === 0 ? <EmptyState title="尚无版本" copy="创建首个草稿后，版本记录会显示在这里。" /> : releases.map((release) => <div className="release-row" key={release.id}><div><strong>v{release.version}</strong><span>revision {release.revision} · {new Date(release.created_at).toLocaleString()}</span></div><StatusBadge value={release.status} /><div className="row-actions">{release.status === "active" || release.status === "superseded" ? <button className="secondary-button" onClick={() => void rollback(release)}>回滚到此版本</button> : null}{environment === "dev" && release.status === "active" ? <button className="secondary-button" onClick={() => void promote(release)}>提升为 PROD 草稿</button> : null}</div></div>)}</section></>}</section></WorkspaceShell>;
}

function SecretsPage() {
  const environment = useEnvironment();
  const [definitions, setDefinitions] = useState<ConfigDefinition[]>([]);
  const [metadata, setMetadata] = useState<Record<string, SecretMetadata>>({});
  const [selected, setSelected] = useState<ConfigDefinition | null>(null);
  const [secretValue, setSecretValue] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useModal(Boolean(selected), () => { setSelected(null); setSecretValue(""); });
  useEffect(() => { void apiJson<ConfigDefinition[]>("/config/definitions").then((rows) => setDefinitions(rows.filter((row) => row.sensitivity === "secret"))).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    const owners = [...new Set(definitions.map((item) => item.owner_id))];
    void Promise.all(owners.map((owner) => apiJson<SecretMetadata[]>(`/secrets?environment_id=${environment}&owner_type=tool&owner_id=${encodeURIComponent(owner)}`).catch(() => []))).then((groups) => setMetadata(Object.fromEntries(groups.flat().map((item) => [item.definition_id, item]))));
  }, [definitions, environment, message]);
  async function save(event: FormEvent) {
    event.preventDefault(); if (!selected) return;
    setError(""); setMessage("");
    const secretId = `sec_${environment}_${selected.id.replaceAll(".", "_")}`;
    try {
      await apiJson(`/secrets/${encodeURIComponent(secretId)}`, { method: "PUT", body: JSON.stringify({ environment_id: environment, owner_type: selected.owner_type, owner_id: selected.owner_id, definition_id: selected.id, value: secretValue }) });
      setSecretValue(""); setSelected(null); setMessage("Secret 新版本已加密保存并激活。");
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
  }
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow={`${environment.toUpperCase()} / SECRETS`} title="Secret 管理" copy="明文只停留在当前输入组件内存；保存后平台不会再次回显。" /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="data-panel"><div className="table-header secret-columns"><span>Secret</span><span>工具</span><span>状态</span><span>操作</span></div>{definitions.map((item) => <div className="table-row secret-columns" key={item.id}><strong>{item.display_name}<small>{item.key}</small></strong><span>{item.owner_id}</span><StatusBadge value={metadata[item.id]?.configured ? `v${metadata[item.id].version}` : "missing"} /><button className="secondary-button" onClick={() => { setSelected(item); setSecretValue(""); setMessage(""); }}>替换</button></div>)}</div>{selected && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="secret-dialog-title"><p className="section-label">{environment.toUpperCase()} / {selected.owner_id}</p><h2 id="secret-dialog-title">替换 {selected.display_name}</h2><p>新版本保存成功后立即激活，旧版本只用于历史追溯。</p><form className="auth-form" onSubmit={save}><label>Secret 新值<textarea autoFocus value={secretValue} onChange={(event) => setSecretValue(event.target.value)} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setSelected(null)}>取消</button><button className="primary-button">加密保存</button></div></form></section></div>}</section></WorkspaceShell>;
}

function CredentialsPage() {
  const environment = useEnvironment();
  const [items, setItems] = useState<CredentialMetadata[]>([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ tool_id: "truthy-search", provider_type: "gateway_session" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useModal(creating, () => setCreating(false));
  const load = useCallback(() => apiJson<CredentialMetadata[]>(`/credentials?environment_id=${environment}`).then(setItems), [environment]);
  useEffect(() => { void load().catch((requestError) => setError(requestError.message)); }, [load]);
  async function createCredential(event: FormEvent) {
    event.preventDefault(); setError(""); setMessage("");
    try { await apiJson("/credentials", { method: "POST", body: JSON.stringify({ ...form, environment_id: environment }) }); setCreating(false); setMessage("Credential 已创建，Agent 将在下一轮执行首次验证。 "); await load(); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "创建失败"); }
  }
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow={`${environment.toUpperCase()} / CREDENTIALS`} title="凭证健康" copy="平台只展示状态、版本和过期时间，不显示 Token 或密码。" actions={<button className="primary-button" onClick={() => setCreating(true)}>创建 Credential</button>} /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="data-panel">{items.length === 0 ? <EmptyState title="尚未创建 Credential" copy="完成 Secret 导入后创建 Credential，刷新 Agent 会负责登录和续期。" /> : items.map((item) => <div className="table-row" key={item.id}><strong>{item.tool_id}<small>{item.provider_type}</small></strong><span>{item.environment_id}</span><StatusBadge value={item.status} /><span>{item.expires_at ? new Date(item.expires_at).toLocaleString() : "无过期时间"}</span></div>)}</div>{creating && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="credential-dialog-title"><p className="section-label">{environment.toUpperCase()} / CREDENTIAL</p><h2 id="credential-dialog-title">创建自动维护凭证</h2><p>先在 Secret 页面导入该 Provider 需要的账号或 Token。创建后 Agent 才会尝试验证、登录和续期。</p><form className="auth-form" onSubmit={createCredential}><label>工具<select autoFocus value={form.tool_id} onChange={(event) => setForm({ ...form, tool_id: event.target.value })}><option value="truthy-search">truthy-search</option><option value="api-autotest">api-autotest</option></select></label><label>Provider<select value={form.provider_type} onChange={(event) => setForm({ ...form, provider_type: event.target.value })}><option value="gateway_session">Gateway Session</option><option value="admin_login">Admin Login</option></select></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setCreating(false)}>取消</button><button className="primary-button">创建并等待验证</button></div></form></section></div>}</section></WorkspaceShell>;
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
    try { await apiJson(`/admin/users/${resetting.id}/reset-password`, { method: "POST", body: JSON.stringify({ new_password: resetPassword }) }); setResetPassword(""); setResetting(null); setMessage("密码已重置，目标用户的全部会话已撤销。"); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "重置失败"); }
  }
  async function revokeUserSessions(user: AdminUser) {
    setError(""); setMessage("");
    try { await apiJson(`/admin/users/${user.id}/sessions`, { method: "DELETE" }); setMessage(`${user.display_name} 的会话已全部撤销。`); }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : "撤销失败"); }
  }
  return <WorkspaceShell><section className="workspace-page"><PageHeader eyebrow="IDENTITY" title="用户管理" copy="本地账号的状态、角色和会话都由平台统一管理。" actions={<button className="primary-button" onClick={() => setCreating(true)}>创建用户</button>} /><ManagementNav />{message && <InlineMessage kind="success">{message}</InlineMessage>}{error && <InlineMessage kind="error">{error}</InlineMessage>}<div className="data-panel user-table"><div className="table-header"><span>用户</span><span>角色</span><span>状态 / 最近登录</span><span>操作</span></div>{items.length === 0 ? <EmptyState title="尚无用户" copy="创建本地用户并分配最小必要角色。" /> : items.map((item) => <div className="table-row" key={item.id}><strong>{item.display_name}<small>{item.username}</small></strong><span>{item.role_ids.length ? item.role_ids.map((id) => roles.find((role) => role.id === id)?.name ?? id).join("、") : "未分配"}</span><span><StatusBadge value={item.status} /><small>{item.last_login_at ? new Date(item.last_login_at).toLocaleString() : "尚未登录"}</small></span><div className="row-actions"><button className="link-button" onClick={() => void updateUser(item, { status: item.status === "active" ? "disabled" : "active" }, item.status === "active" ? "用户已禁用并撤销会话。" : "用户已启用。")}>{item.status === "active" ? "禁用" : "启用"}</button><button className="link-button" onClick={() => setResetting(item)}>重置密码</button><button className="link-button" onClick={() => void revokeUserSessions(item)}>强制退出</button></div></div>)}</div>{creating && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="create-user-title"><p className="section-label">LOCAL IDENTITY</p><h2 id="create-user-title">创建用户</h2><form className="auth-form" onSubmit={createUser}><label>用户名<input autoFocus value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} minLength={3} required /></label><label>显示名<input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} required /></label><label>初始密码<input type="password" autoComplete="new-password" minLength={12} value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required /></label><fieldset><legend>角色</legend>{roles.map((role) => <label className="checkbox-row" key={role.id}><input type="checkbox" checked={form.role_ids.includes(role.id)} onChange={() => toggleRole(role.id)} />{role.name}</label>)}</fieldset><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setCreating(false)}>取消</button><button className="primary-button">创建用户</button></div></form></section></div>}{resetting && <div className="modal-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="reset-password-title"><p className="section-label">HIGH-RISK ACTION</p><h2 id="reset-password-title">重置 {resetting.display_name} 的密码</h2><p>提交后该用户所有会话会立即失效。</p><form className="auth-form" onSubmit={submitReset}><label>新密码<input autoFocus type="password" autoComplete="new-password" minLength={12} value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} required /></label><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => setResetting(null)}>取消</button><button className="primary-button">确认重置</button></div></form></section></div>}</section></WorkspaceShell>;
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

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const tone = ["healthy", "active", "success", "ok"].includes(normalized) || normalized.startsWith("v") ? "success" : ["missing", "failed", "disabled", "unhealthy"].includes(normalized) ? "danger" : "neutral";
  return <span className={`status-badge status-badge-${tone}`}>{value}</span>;
}

function EmptyState({ title, copy }: { title: string; copy: string }) { return <div className="empty-state"><strong>{title}</strong><p>{copy}</p></div>; }

function ForbiddenPage() { return <WorkspaceShell><section className="not-found"><p className="section-label">403 / PERMISSION DENIED</p><h1>没有访问权限</h1><p>当前账号没有访问此平台功能或工具资源的权限。</p><NavLink className="tool-link" to="/">返回工作台</NavLink></section></WorkspaceShell>; }
function NotFoundPage() { return <WorkspaceShell><section className="not-found"><p className="section-label">404</p><h1>页面不存在</h1><NavLink className="tool-link" to="/">返回平台首页</NavLink></section></WorkspaceShell>; }

function DomainRoute({ domainId }: { domainId: "ai-testing" | "automation" | "quality-analysis" | "domain-evaluation" }) {
  return <WorkspaceShell><CapabilityDomainPage domainId={domainId} /></WorkspaceShell>;
}

function AppRoutes() {
  return <Routes><Route path="/login" element={<LoginPage />} /><Route path="/setup" element={<SetupPage />} /><Route path="/account" element={<Protected><AccountPage /></Protected>} /><Route path="/account/password" element={<Protected><ChangePasswordPage /></Protected>} /><Route path="/" element={<Protected><HomePage /></Protected>} /><Route path="/ai-testing" element={<Protected><DomainRoute domainId="ai-testing" /></Protected>} /><Route path="/automation" element={<Protected><DomainRoute domainId="automation" /></Protected>} /><Route path="/quality-analysis" element={<Protected><DomainRoute domainId="quality-analysis" /></Protected>} /><Route path="/domain-evaluation" element={<Protected><DomainRoute domainId="domain-evaluation" /></Protected>} /><Route path="/settings/llm" element={<Protected><LlmSettingsPage /></Protected>} /><Route path="/settings/config" element={<Protected><ConfigPage /></Protected>} /><Route path="/settings/secrets" element={<Protected><SecretsPage /></Protected>} /><Route path="/settings/credentials" element={<Protected><CredentialsPage /></Protected>} /><Route path="/admin/users" element={<Protected permission="platform.user.manage"><UsersPage /></Protected>} /><Route path="/admin/roles" element={<Protected permission="platform.role.manage"><RolesPage /></Protected>} /><Route path="/audit" element={<Protected permission="platform.audit.view"><AuditPage /></Protected>} /><Route path="/403" element={<Protected><ForbiddenPage /></Protected>} /><Route path="*" element={<Protected><NotFoundPage /></Protected>} /></Routes>;
}

function PlatformProviders() {
  const { auth } = useAuth();
  return <ToolCatalogProvider enabled={Boolean(auth)}><AppRoutes /></ToolCatalogProvider>;
}

/** 第二阶段平台入口：统一会话、权限路由和管理工作台。 */
export function App() {
  return <BrowserRouter><AuthProvider><PlatformProviders /></AuthProvider></BrowserRouter>;
}
