/*
 * Gateway 接口自动化 Web 壳交互。
 *
 * 浏览器只提交项目与测试资产 ID；环境、Scope、Release、Credential 等运行
 * 上下文始终从服务端预检读取。localStorage 仅保存非敏感 project_id，方便
 * 页面之间保持用户选择，绝不缓存平台快照、凭证元数据或日志内容。
 */
(function () {
  "use strict";

  const config = window.__API_AUTOTEST__ || {};
  const base = String(config.basePath || "").replace(/\/$/, "");
  const page = document.body.dataset.page || "";
  const projectStorageKey = "api-autotest.selected-project";
  const terminalStatuses = new Set(["succeeded", "failed", "cancelled", "timed_out"]);
  const statusLabels = {
    pending: "等待中",
    running: "运行中",
    succeeded: "成功",
    passed: "通过",
    failed: "失败",
    error: "错误",
    skipped: "跳过",
    cancelled: "已取消",
    timed_out: "已超时",
  };

  function byId(id) { return document.getElementById(id); }
  function all(selector, root) { return Array.from((root || document).querySelectorAll(selector)); }
  function text(value, fallback) {
    // 空字符串是 select 占位项等场景的合法显式 fallback，不能再被 ``||``
    // 改写成破折号，否则浏览器会把“未选择”误当成真实资产 ID 提交预检。
    if (value === null || value === undefined || value === "") {
      return fallback === undefined ? "—" : fallback;
    }
    return String(value);
  }
  function escapeHtml(value) {
    const node = document.createElement("div");
    node.textContent = text(value, "");
    return node.innerHTML;
  }
  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false,
    }).format(date);
  }
  function formatDuration(seconds) {
    // Number(null) 会得到 0；历史任务缺少开始时间时必须显示未知，不能误报 0ms。
    if (seconds === null || seconds === undefined || seconds === "") return "—";
    const number = Number(seconds);
    if (!Number.isFinite(number) || number < 0) return "—";
    if (number < 1) return `${Math.round(number * 1000)}ms`;
    if (number < 60) return `${number.toFixed(number < 10 ? 1 : 0)}s`;
    const minutes = Math.floor(number / 60);
    return `${minutes}m ${Math.round(number % 60)}s`;
  }
  function taskDuration(task) {
    if (!task || !task.started_at) return null;
    const end = task.finished_at ? new Date(task.finished_at) : new Date();
    const start = new Date(task.started_at);
    const seconds = (end.getTime() - start.getTime()) / 1000;
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  }
  function statusClass(status) {
    if (status === "succeeded" || status === "passed" || status === "ready" || status === "active") return "success";
    if (status === "failed" || status === "error" || status === "invalid") return "failed";
    if (status === "running") return "running";
    if (status === "pending" || status === "timed_out" || status === "missing") return "warning";
    return "neutral";
  }
  function statusBadge(status, label) {
    return `<span class="status-badge ${statusClass(status)}">${escapeHtml(label || statusLabels[status] || status || "未知")}</span>`;
  }
  function getSelectedProject() {
    try { return window.localStorage.getItem(projectStorageKey) || ""; }
    catch (_error) { return ""; }
  }
  function rememberProject(projectId, projects) {
    if (!projectId) return;
    try { window.localStorage.setItem(projectStorageKey, projectId); }
    catch (_error) { /* 隐私模式禁用存储时只影响跨页记忆，不影响任务提交。 */ }
    const item = (projects || []).find((candidate) => candidate.project_id === projectId);
    if (byId("current-project-name")) byId("current-project-name").textContent = item ? item.display_name : projectId;
  }
  function showGlobalError(error) {
    const alert = byId("global-alert");
    if (!alert) return;
    alert.hidden = false;
    alert.textContent = error && error.message ? error.message : "页面数据加载失败，请稍后重试。";
  }
  function clearGlobalError() {
    const alert = byId("global-alert");
    if (alert) alert.hidden = true;
  }
  function setInlineStatus(node, kind, message) {
    if (!node) return;
    node.className = `inline-status ${kind || ""}`.trim();
    node.textContent = message;
    node.hidden = false;
  }
  function option(value, label) { return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`; }
  function selectionName(selection) {
    if (!selection) return "—";
    if (selection.run_type === "flow") return `Flow · ${text(selection.flow_id)}`;
    if (selection.run_type === "single") return `单接口 · ${text(selection.api_id)} / ${text(selection.case_id)}`;
    return "全部资产";
  }

  async function api(path, options) {
    const response = await window.fetch(`${base}${path}`, Object.assign({
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
    }, options || {}));
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.error || payload.message || `请求失败（HTTP ${response.status}）`);
      error.status = response.status;
      error.code = payload.error_code || payload.code;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  let projectsPromise = null;
  function loadProjects(force) {
    if (force || !projectsPromise) {
      projectsPromise = api("/api/projects").then((data) => data.items || []).catch((error) => {
        projectsPromise = null;
        throw error;
      });
    }
    return projectsPromise;
  }
  function usableProject(projects) {
    const selected = getSelectedProject();
    return projects.find((item) => item.project_id === selected) || projects[0] || null;
  }
  function setCurrentProjectHeader(projects) {
    const selected = usableProject(projects);
    if (selected) rememberProject(selected.project_id, projects);
    else if (byId("current-project-name")) byId("current-project-name").textContent = "无可用项目";
    return selected;
  }
  function managementLink(url) {
    if (!url) return "";
    const target = String(url).startsWith("http") ? url : url;
    return `<a class="text-link" href="${escapeHtml(target)}">前往平台配置中心</a>`;
  }
  function releaseLabel(release) {
    if (!release) return "未发布";
    return `v${text(release.version, "—")} · ${text(release.status, "active")}`;
  }
  function profileLabel(profiles) {
    if (!Array.isArray(profiles) || !profiles.length) return "无需凭证";
    return profiles.map((item) => `${text(item.id)} · ${text(item.status, "ready")}`).join("、");
  }

  function activateNavigation() {
    const active = page === "task-flow" ? "task-single" : page === "task-detail" ? "tasks" : page;
    all("[data-nav]").forEach((link) => {
      if (link.dataset.nav === active) link.setAttribute("aria-current", "page");
    });
  }

  async function initOverview() {
    const projects = await loadProjects();
    const current = setCurrentProjectHeader(projects);
    if (!current) {
      setInlineStatus(byId("runtime-context"), "warning", "当前没有同时满足平台授权与本地项目包校验的项目。");
      byId("metric-tasks").textContent = "0";
      byId("metric-cases").textContent = "0";
      byId("recent-tasks").innerHTML = '<p class="empty-state">暂无可执行项目。</p>';
      return;
    }

    const [catalog, tasks, preflight] = await Promise.all([
      api(`/api/catalog?project_id=${encodeURIComponent(current.project_id)}`),
      api(`/api/tasks?project_id=${encodeURIComponent(current.project_id)}&page_size=8`),
      api("/api/preflight", { method: "POST", body: JSON.stringify({ project_id: current.project_id, run_type: "all" }) }),
    ]);
    const today = new Date().toISOString().slice(0, 10);
    const todayTasks = (tasks.items || []).filter((item) => String(item.created_at || "").slice(0, 10) === today);
    const succeeded = todayTasks.filter((item) => item.status === "succeeded");
    byId("metric-tasks").textContent = String(todayTasks.length);
    byId("metric-success").textContent = todayTasks.length ? `成功率 ${Math.round(succeeded.length / todayTasks.length * 100)}%` : "今天暂无执行";
    byId("metric-cases").textContent = String((catalog.cases || []).length);
    byId("metric-project").textContent = `${current.display_name} · ${(catalog.apis || []).length} APIs`;
    const latestSuccess = (tasks.items || []).find((item) => item.status === "succeeded");
    byId("metric-duration").textContent = latestSuccess ? formatDuration(taskDuration(latestSuccess)) : "—";
    byId("quick-project").textContent = `${current.display_name} · ${current.target_env || "—"}`;
    const quickValues = byId("quick-summary").querySelectorAll("dd");
    quickValues[0].textContent = text(preflight.runtime && preflight.runtime.scope_id);
    quickValues[1].textContent = releaseLabel(preflight.runtime && preflight.runtime.release);

    const runtimeNode = byId("runtime-context");
    const management = byId("context-management-link");
    const runtime = preflight.runtime || {};
    if (preflight.ready) {
      setInlineStatus(runtimeNode, "success", `可执行：${current.display_name} · ${String(runtime.platform_environment || "").toUpperCase()} / ${String(runtime.target_env || "").toUpperCase()} · ${releaseLabel(runtime.release)} · ${profileLabel(preflight.profiles)}`);
    } else {
      const first = (preflight.errors || [])[0] || {};
      setInlineStatus(runtimeNode, "error", first.message || "当前运行上下文未就绪。");
      if (management && (first.management_url || runtime.management_url)) {
        management.href = first.management_url || runtime.management_url;
        management.hidden = false;
      }
    }
    const recent = tasks.items || [];
    byId("recent-tasks").innerHTML = recent.length ? recent.slice(0, 4).map((task) => `<a class="compact-item" href="${base}/tasks/${encodeURIComponent(task.id)}"><span><strong>${escapeHtml(selectionName(task.selection))}</strong><small>${escapeHtml(task.id)} · ${escapeHtml(formatTime(task.created_at))}</small></span>${statusBadge(task.status)}</a>`).join("") : '<p class="empty-state">当前项目暂无任务记录。</p>';
  }

  async function initProjects() {
    const projects = await loadProjects();
    const current = setCurrentProjectHeader(projects);
    const list = byId("project-list");
    const search = byId("project-search");

    async function showContext(projectId) {
      all(".project-item", list).forEach((item) => item.classList.toggle("active", item.dataset.projectId === projectId));
      const contextNode = byId("project-context");
      contextNode.innerHTML = '<p class="empty-state">正在读取项目上下文…</p>';
      try {
        const context = await api(`/api/projects/${encodeURIComponent(projectId)}/context`);
        const preflight = context.preflight || {};
        const runtime = preflight.runtime || {};
        const errors = preflight.errors || [];
        contextNode.innerHTML = `<dl class="summary-list dense"><div><dt>项目</dt><dd>${escapeHtml(context.display_name)}</dd></div><div><dt>平台项目</dt><dd>${escapeHtml(text(context.platform_project_id))}</dd></div><div><dt>平台 / 接口环境</dt><dd>${escapeHtml(String(context.platform_environment || "").toUpperCase())} / ${escapeHtml(String(context.target_env || "").toUpperCase())}</dd></div><div><dt>Runtime Scope</dt><dd>${escapeHtml(text(context.scope_id))}</dd></div><div><dt>Release</dt><dd>${escapeHtml(releaseLabel(context.release || runtime.release))}</dd></div><div><dt>资产数量</dt><dd>${context.counts.apis} APIs · ${context.counts.cases} Cases · ${context.counts.flows} Flows</dd></div><div><dt>Profile</dt><dd>${escapeHtml(profileLabel(preflight.profiles || context.credential_profiles))}</dd></div></dl><div class="inline-status ${preflight.ready ? "success" : "error"}">${escapeHtml(preflight.ready ? "运行上下文已就绪，可切换到该项目。" : ((errors[0] || {}).message || "运行上下文未就绪。"))}</div><div class="button-row context-actions"><button class="button primary" id="confirm-project" type="button" ${preflight.ready ? "" : "disabled"}>切换到 ${escapeHtml(context.display_name)}</button>${managementLink((errors[0] || {}).management_url || runtime.management_url)}</div>`;
        const button = byId("confirm-project");
        if (button) button.addEventListener("click", () => { rememberProject(projectId, projects); window.location.assign(`${base}/`); });
      } catch (error) {
        contextNode.innerHTML = `<div class="inline-status error">${escapeHtml(error.message)}</div>`;
      }
    }
    function render(query) {
      const normalized = String(query || "").trim().toLowerCase();
      const visible = projects.filter((item) => !normalized || `${item.project_id} ${item.display_name}`.toLowerCase().includes(normalized));
      byId("project-count").textContent = `${visible.length} 个可用项目`;
      list.innerHTML = visible.length ? visible.map((item) => `<button class="project-item ${current && item.project_id === current.project_id ? "active" : ""}" data-project-id="${escapeHtml(item.project_id)}" type="button"><span><strong>${escapeHtml(item.display_name)}</strong><span>${escapeHtml(item.project_id)} · ${item.counts.apis} APIs · ${item.counts.flows} Flows</span></span>${statusBadge(item.scope_status, item.target_env || "未知")}</button>`).join("") : '<p class="empty-state">未找到匹配项目。</p>';
      all(".project-item", list).forEach((item) => item.addEventListener("click", () => showContext(item.dataset.projectId)));
    }
    render("");
    search.addEventListener("input", () => render(search.value));
    byId("project-clear").addEventListener("click", () => { search.value = ""; render(""); search.focus(); });
    if (current) await showContext(current.project_id);
  }

  async function initTaskForm() {
    const root = document.querySelector(".form-layout");
    const mode = root.dataset.taskMode;
    const projects = await loadProjects();
    const selected = setCurrentProjectHeader(projects);
    const projectSelect = byId("task-project");
    const form = byId("task-form");
    const submit = byId("task-submit");
    let catalog = null;
    let lastPreflight = null;
    projectSelect.innerHTML = option("", "请选择项目") + projects.map((item) => option(item.project_id, `${item.display_name} · ${String(item.target_env || "").toUpperCase()}`)).join("");
    if (selected) projectSelect.value = selected.project_id;

    function selection() {
      const payload = { project_id: projectSelect.value, run_type: mode, tag: byId("task-tag").value.trim() || null };
      if (mode === "single") { payload.api_id = byId("task-api").value; payload.case_id = byId("task-case").value; }
      else payload.flow_id = byId("task-flow").value;
      return payload;
    }
    function complete(payload) { return Boolean(payload.project_id && (mode === "single" ? payload.api_id && payload.case_id : payload.flow_id)); }
    function updatePreview(preflight) {
      const values = byId("task-preview").querySelectorAll("dd");
      const runtime = preflight.runtime || {};
      values[0].textContent = text(runtime.platform_environment).toUpperCase();
      values[1].textContent = text(runtime.target_env).toUpperCase();
      values[2].textContent = text(runtime.scope_id);
      values[3].textContent = releaseLabel(runtime.release);
      values[4].textContent = profileLabel(preflight.profiles);
    }
    async function runPreflight() {
      const payload = selection();
      submit.disabled = true;
      lastPreflight = null;
      if (!complete(payload)) { setInlineStatus(byId("task-preflight"), "", "选择完整测试资产后执行预检。"); return; }
      setInlineStatus(byId("task-preflight"), "loading", "正在校验项目资产与平台运行上下文…");
      try {
        const preflight = await api("/api/preflight", { method: "POST", body: JSON.stringify(payload) });
        lastPreflight = preflight;
        updatePreview(preflight);
        if (preflight.ready) {
          setInlineStatus(byId("task-preflight"), "success", "预检通过：Scope、Release 与所需 Profile 均已就绪。");
          submit.disabled = false;
        } else {
          const first = (preflight.errors || [])[0] || {};
          setInlineStatus(byId("task-preflight"), "error", first.message || "预检未通过。");
        }
      } catch (error) { setInlineStatus(byId("task-preflight"), "error", error.message); }
    }
    function renderFlowPreview() {
      if (mode !== "flow") return;
      const flowId = byId("task-flow").value;
      const flow = catalog && (catalog.flows || []).find((item) => item.id === flowId);
      const node = byId("flow-preview");
      if (!flow) { node.innerHTML = '<p class="empty-state">选择 Flow 后展示业务步骤。</p>'; return; }
      const steps = flow.steps || [];
      const count = Number(flow.step_count || steps.length || 0);
      node.innerHTML = `<p class="flow-summary"><strong>${escapeHtml(flow.name || flow.id)}</strong><span>${count} 个业务步骤</span></p>${steps.map((step, index) => `<div class="flow-step"><span class="flow-step-index">${index + 1}</span><span><strong>${escapeHtml(step.name || step.api_id || step.action_type || `业务步骤 ${index + 1}`)}</strong><small>${escapeHtml(step.id)} · ${escapeHtml(step.api_id || step.action_type || step.kind)}</small></span></div>`).join("")}`;
    }
    function populateAssets() {
      if (mode === "single") {
        const apiSelect = byId("task-api");
        apiSelect.innerHTML = option("", "请选择 API") + (catalog.apis || []).map((item) => option(item.id, `${item.id} · ${item.name}`)).join("");
        apiSelect.disabled = false;
        byId("task-case").innerHTML = option("", "请先选择 API");
        byId("task-case").disabled = true;
      } else {
        const flowSelect = byId("task-flow");
        flowSelect.innerHTML = option("", "请选择 Flow") + (catalog.flows || []).map((item) => option(item.id, `${item.id} · ${item.step_count} 步`)).join("");
        flowSelect.disabled = false;
        renderFlowPreview();
      }
    }
    async function loadCatalog() {
      rememberProject(projectSelect.value, projects);
      if (!projectSelect.value) return;
      setInlineStatus(byId("task-preflight"), "loading", "正在读取项目资产…");
      try { catalog = await api(`/api/catalog?project_id=${encodeURIComponent(projectSelect.value)}`); populateAssets(); setInlineStatus(byId("task-preflight"), "", "选择测试资产后执行预检。"); }
      catch (error) { setInlineStatus(byId("task-preflight"), "error", error.message); }
    }
    projectSelect.addEventListener("change", loadCatalog);
    if (mode === "single") {
      byId("task-api").addEventListener("change", () => {
        const cases = (catalog && catalog.cases || []).filter((item) => item.api === byId("task-api").value);
        byId("task-case").innerHTML = option("", "请选择 Case") + cases.map((item) => option(item.id, `${item.id} · ${item.name}`)).join("");
        byId("task-case").disabled = !byId("task-api").value;
        runPreflight();
      });
      byId("task-case").addEventListener("change", runPreflight);
    } else {
      byId("task-flow").addEventListener("change", () => { renderFlowPreview(); runPreflight(); });
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = selection();
      if (!lastPreflight || !lastPreflight.ready || !complete(payload)) return runPreflight();
      submit.disabled = true;
      submit.textContent = "正在提交…";
      try {
        const task = await api("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
        window.location.assign(`${base}/tasks/${encodeURIComponent(task.id)}`);
      } catch (error) {
        setInlineStatus(byId("task-preflight"), "error", error.message);
        submit.disabled = false;
        submit.textContent = "提交任务";
      }
    });
    if (selected) await loadCatalog();
  }

  async function initCatalog() {
    const projects = await loadProjects();
    const current = setCurrentProjectHeader(projects);
    const select = byId("catalog-project");
    const search = byId("catalog-search");
    let snapshot = { apis: [], cases: [], flows: [], errors: [] };
    let type = "apis";
    select.innerHTML = option("", "请选择项目") + projects.map((item) => option(item.project_id, `${item.display_name} · ${item.counts.apis} APIs`)).join("");
    if (current) select.value = current.project_id;

    function render() {
      byId("catalog-api-count").textContent = snapshot.apis.length;
      byId("catalog-case-count").textContent = snapshot.cases.length;
      byId("catalog-flow-count").textContent = snapshot.flows.length;
      const query = search.value.trim().toLowerCase();
      const items = (snapshot[type] || []).filter((item) => !query || JSON.stringify(item).toLowerCase().includes(query));
      const head = byId("catalog-table-head");
      const body = byId("catalog-table-body");
      if (type === "apis") {
        head.innerHTML = "<tr><th>ID</th><th>名称</th><th>Service / Method</th><th>Profile</th><th>状态</th></tr>";
        body.innerHTML = items.length ? items.map((item) => `<tr><td><code>${escapeHtml(item.id)}</code></td><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.service_name)}<br><span class="muted">${escapeHtml(item.method_name)}</span></td><td>${escapeHtml(text(item.credential_profile, "按资产解析"))}</td><td>${statusBadge(item.status, "可用")}</td></tr>`).join("") : '<tr><td colspan="5" class="table-state">没有匹配的 API。</td></tr>';
      } else if (type === "cases") {
        head.innerHTML = "<tr><th>Case ID</th><th>名称</th><th>API</th><th>标签</th><th>状态</th></tr>";
        body.innerHTML = items.length ? items.map((item) => `<tr><td><code>${escapeHtml(item.id)}</code></td><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.api)}</td><td>${escapeHtml((item.tags || []).join(", ") || "—")}</td><td>${statusBadge(item.status, "可用")}</td></tr>`).join("") : '<tr><td colspan="5" class="table-state">没有匹配的 Case。</td></tr>';
      } else {
        head.innerHTML = "<tr><th>Flow ID</th><th>名称</th><th>业务步骤</th><th>引用 API</th><th>状态</th></tr>";
        body.innerHTML = items.length ? items.map((item) => `<tr><td><code>${escapeHtml(item.id)}</code></td><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.step_count)}</td><td>${escapeHtml((item.apis || []).join(", ") || "—")}</td><td>${statusBadge(item.status, "可用")}</td></tr>`).join("") : '<tr><td colspan="5" class="table-state">没有匹配的 Flow。</td></tr>';
      }
    }
    async function refresh() {
      if (!select.value) return;
      rememberProject(select.value, projects);
      setInlineStatus(byId("catalog-status"), "loading", "正在读取项目资产…");
      try {
        snapshot = await api(`/api/catalog?project_id=${encodeURIComponent(select.value)}`);
        const errors = snapshot.errors || [];
        const errorsNode = byId("catalog-errors");
        errorsNode.hidden = !errors.length;
        errorsNode.innerHTML = errors.map((item) => `<div class="inline-status error"><strong>${escapeHtml(item.file)}</strong>：${escapeHtml(item.message)}</div>`).join("");
        setInlineStatus(byId("catalog-status"), errors.length ? "warning" : "success", errors.length ? `已加载，${errors.length} 个资产文件未通过校验。` : `已加载 ${snapshot.apis.length} APIs、${snapshot.cases.length} Cases、${snapshot.flows.length} Flows。`);
        render();
      } catch (error) { setInlineStatus(byId("catalog-status"), "error", error.message); }
    }
    all("[data-catalog-type]").forEach((tab) => tab.addEventListener("click", () => {
      type = tab.dataset.catalogType;
      all("[data-catalog-type]").forEach((candidate) => { const active = candidate === tab; candidate.classList.toggle("active", active); candidate.setAttribute("aria-selected", active ? "true" : "false"); });
      render();
    }));
    search.addEventListener("input", render);
    select.addEventListener("change", refresh);
    byId("catalog-refresh").addEventListener("click", refresh);
    if (current) await refresh();
  }

  async function initTasks() {
    const projects = await loadProjects();
    setCurrentProjectHeader(projects);
    const form = byId("task-filters");
    const projectSelect = byId("filter-project");
    let pageNumber = 1;
    let pageCount = 1;
    projectSelect.innerHTML = option("", "全部项目") + projects.map((item) => option(item.project_id, item.display_name)).join("");

    async function refresh() {
      const params = new URLSearchParams({ page: String(pageNumber), page_size: "20" });
      new FormData(form).forEach((value, key) => { if (String(value)) params.set(key, String(value)); });
      byId("task-list-body").innerHTML = '<tr><td colspan="6" class="table-state">正在读取任务记录…</td></tr>';
      try {
        const data = await api(`/api/tasks?${params.toString()}`);
        const items = data.items || [];
        byId("task-list-count").textContent = `共 ${data.total} 条记录`;
        byId("task-list-body").innerHTML = items.length ? items.map((task) => `<tr><td><a class="text-link" href="${base}/tasks/${encodeURIComponent(task.id)}"><code>${escapeHtml(task.id)}</code></a></td><td>${escapeHtml(task.project && task.project.display_name)}</td><td>${escapeHtml(String(task.runtime && task.runtime.target_env || "—").toUpperCase())}</td><td>${escapeHtml(selectionName(task.selection))}</td><td>${statusBadge(task.status)}</td><td>${escapeHtml(formatTime(task.created_at))}</td></tr>`).join("") : '<tr><td colspan="6" class="table-state">没有符合条件的任务。</td></tr>';
        pageCount = Math.max(1, Math.ceil(data.total / data.page_size));
        byId("task-pagination").hidden = data.total <= data.page_size;
        byId("task-page-label").textContent = `第 ${data.page} / ${pageCount} 页`;
        byId("task-page-prev").disabled = data.page <= 1;
        byId("task-page-next").disabled = data.page >= pageCount;
      } catch (error) { byId("task-list-body").innerHTML = `<tr><td colspan="6" class="table-state error-text">${escapeHtml(error.message)}</td></tr>`; }
    }
    form.addEventListener("submit", (event) => { event.preventDefault(); pageNumber = 1; refresh(); });
    byId("task-filter-clear").addEventListener("click", () => { form.reset(); pageNumber = 1; refresh(); });
    byId("tasks-refresh").addEventListener("click", refresh);
    byId("task-page-prev").addEventListener("click", () => { if (pageNumber > 1) { pageNumber -= 1; refresh(); } });
    byId("task-page-next").addEventListener("click", () => { if (pageNumber < pageCount) { pageNumber += 1; refresh(); } });
    await refresh();
  }

  async function initTaskDetail() {
    const root = byId("task-detail-root");
    const taskId = root.dataset.taskId;
    let task = null;
    let timer = null;
    function setListValues(listId, values) {
      all("dd", byId(listId)).forEach((node, index) => { node.textContent = text(values[index]); });
    }
    async function loadResult() {
      const body = byId("detail-result-body");
      try {
        const result = await api(`/api/tasks/${encodeURIComponent(taskId)}/result`);
        if (!result.result_available) {
          body.innerHTML = `<tr><td colspan="4" class="table-state">结果暂不可用：${escapeHtml(result.reason_code || "JUNIT_NOT_GENERATED")}</td></tr>`;
          byId("detail-metric-cases").textContent = "—";
          return;
        }
        const summary = result.summary || {};
        const total = Number(summary.total || summary.tests || 0);
        const failed = Number(summary.failed || summary.failures || 0) + Number(summary.errors || 0);
        const passed = Number(summary.passed || Math.max(0, total - failed - Number(summary.skipped || 0)));
        byId("detail-metric-cases").textContent = `${passed} / ${total}`;
        byId("detail-metric-result").textContent = failed ? `${failed} 项失败` : "全部通过";
        const cases = result.cases || [];
        const caseRows = cases.map((item) => `<tr><td><code>${escapeHtml(item.name)}</code><br><span class="muted">${escapeHtml(item.classname || "pytest")}</span></td><td>${statusBadge(item.status)}</td><td>${escapeHtml(formatDuration(item.duration))}</td><td>${escapeHtml(item.message || "—")}</td></tr>`).join("");
        body.innerHTML = `<tr><td><strong>执行汇总</strong></td><td>${statusBadge(failed ? "failed" : "succeeded", failed ? "存在失败" : "通过")}</td><td>—</td><td>${failed ? `${failed} 项失败` : "全部断言通过"}</td></tr>${caseRows}`;
      } catch (error) { body.innerHTML = `<tr><td colspan="4" class="table-state error-text">${escapeHtml(error.message)}</td></tr>`; }
    }
    async function loadLogs() {
      const tail = byId("detail-log-tail").value;
      try {
        const logs = await api(`/api/tasks/${encodeURIComponent(taskId)}/logs?tail=${encodeURIComponent(tail)}`);
        byId("detail-log-view").textContent = (logs.lines || []).join("\n") || "暂无日志。";
        byId("detail-log-source").textContent = logs.source === "framework_log" ? `框架脱敏日志 · ${logs.log_file}` : logs.source === "console_redacted" ? "Console 二次脱敏日志" : "暂无日志产物";
      } catch (error) { byId("detail-log-view").textContent = `日志加载失败：${error.message}`; }
    }
    async function loadReport() {
      try {
        const report = await api(`/api/report/meta?task_id=${encodeURIComponent(taskId)}`);
        if (report.exists && report.report_url) { byId("task-report").href = report.report_url; byId("task-report").hidden = false; }
      } catch (_error) { /* 报告是可选产物，不遮盖任务主体。 */ }
    }
    async function loadTask() {
      task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
      const project = task.project || {};
      const runtime = task.runtime || {};
      const selection = task.selection || {};
      rememberProject(project.project_id, [{ project_id: project.project_id, display_name: project.display_name }]);
      byId("detail-status").className = `status-badge ${statusClass(task.status)}`;
      byId("detail-status").textContent = statusLabels[task.status] || task.status;
      byId("detail-subtitle").textContent = `${project.display_name || project.project_id} · ${selectionName(selection)}`;
      byId("detail-metric-status").textContent = statusLabels[task.status] || task.status;
      byId("detail-metric-time").textContent = formatTime(task.finished_at || task.created_at);
      byId("detail-metric-duration").textContent = formatDuration(taskDuration(task));
      setListValues("detail-snapshot", [project.display_name || project.project_id, text(runtime.platform_environment).toUpperCase(), text(runtime.target_env).toUpperCase(), runtime.runtime_scope_id, runtime.release_version ? `v${runtime.release_version} · ${runtime.release_id || "active"}` : runtime.release_id, profileLabel(runtime.credential_profiles), selectionName(selection), task.retry_of]);
      setListValues("detail-timeline", [formatTime(task.created_at), formatTime(task.started_at), formatTime(task.finished_at), task.exit_code === null || task.exit_code === undefined ? "—" : task.exit_code]);
      const errorNode = byId("detail-error");
      if (task.error_message) { setInlineStatus(errorNode, "error", task.error_message); }
      else errorNode.hidden = true;
      byId("task-cancel").disabled = terminalStatuses.has(task.status);
      byId("task-retry").disabled = !terminalStatuses.has(task.status) || task.schema_version !== 2;
      if (terminalStatuses.has(task.status)) { if (timer) window.clearInterval(timer); timer = null; await Promise.all([loadResult(), loadReport()]); }
      return task;
    }
    byId("detail-log-refresh").addEventListener("click", loadLogs);
    byId("detail-log-tail").addEventListener("change", loadLogs);
    byId("task-cancel").addEventListener("click", async () => {
      byId("task-cancel").disabled = true;
      try { await api(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST", body: "{}" }); await loadTask(); }
      catch (error) { showGlobalError(error); byId("task-cancel").disabled = false; }
    });
    byId("task-retry").addEventListener("click", async () => {
      byId("task-retry").disabled = true;
      try { const retried = await api(`/api/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST", body: "{}" }); window.location.assign(`${base}/tasks/${encodeURIComponent(retried.id)}`); }
      catch (error) { showGlobalError(error); byId("task-retry").disabled = false; }
    });
    await Promise.all([loadTask(), loadLogs()]);
    if (task && !terminalStatuses.has(task.status)) timer = window.setInterval(() => Promise.all([loadTask(), loadLogs()]).catch(showGlobalError), 3000);
  }

  async function start() {
    activateNavigation();
    clearGlobalError();
    try {
      if (page === "overview") await initOverview();
      else if (page === "projects") await initProjects();
      else if (page === "task-single" || page === "task-flow") await initTaskForm();
      else if (page === "catalog") await initCatalog();
      else if (page === "tasks") await initTasks();
      else if (page === "task-detail") await initTaskDetail();
    } catch (error) { showGlobalError(error); }
  }

  start();
}());
