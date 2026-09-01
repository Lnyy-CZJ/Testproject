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
    not_run: "未执行",
    cancelled: "已取消",
    timed_out: "已超时",
    ready: "已就绪",
    missing: "尚未配置",
    expired: "已过期",
    action_required: "需要处理",
    refreshing: "正在刷新",
    pending_validation: "等待验证",
    expiring: "即将过期",
  };

  function supportsRetrySchema(schemaVersion) {
    // Task V3 同时承载单条与批量任务；V2/V3 均有稳定的资产快照和重试
    // 契约。更早的历史记录字段不完整，必须保持只读，避免猜测参数。
    return [2, 3].includes(Number(schemaVersion));
  }

  function isRetryableBatchFailure(status) {
    // 与服务端 mode=failed 的复制集合保持一致。cancelled/timed_out/not_run
    // 仍照常展示，但它们不是已经执行并产出失败结果的可重试子项。
    return ["failed", "error"].includes(String(status || ""));
  }

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
  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function formatRuntimeValue(value) {
    if (typeof value === "string") return `“${value}”`;
    if (value === null || value === undefined) return "—";
    if (value && typeof value === "object" && !Array.isArray(value)) return "JSON 对象";
    return JSON.stringify(value);
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
    if (status === "failed" || status === "error" || status === "invalid" || status === "expired" || status === "action_required") return "failed";
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
  function formatFullTime(value) {
    if (!value) return "未提供";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    }).format(date);
  }
  function preflightErrorMarkup(preflight) {
    const first = ((preflight && preflight.errors) || [])[0] || {};
    const details = Array.isArray(first.profile_details) ? first.profile_details : [];
    if (!details.length) return escapeHtml(first.message || "预检未通过。");
    const cards = details.map((profile) => {
      const status = text(profile.status, "missing");
      const statusLabel = statusLabels[status] || status;
      return `<section class="credential-diagnostic-card" aria-label="${escapeHtml(text(profile.id))} 凭证问题"><div class="credential-diagnostic-heading"><strong>${escapeHtml(text(profile.id))}</strong>${statusBadge(status, statusLabel)}</div><p>${escapeHtml(profile.reason || first.message || "凭证不可用，请前往平台检查。")}</p><dl><div><dt>Provider</dt><dd>${escapeHtml(text(profile.provider_type))}</dd></div><div><dt>过期时间</dt><dd>${escapeHtml(formatFullTime(profile.expires_at))}</dd></div><div><dt>最近检查</dt><dd>${escapeHtml(formatFullTime(profile.last_checked_at))}</dd></div><div><dt>错误码</dt><dd><code>${escapeHtml(text(profile.last_error_code, "无"))}</code></dd></div><div><dt>Runtime Scope</dt><dd><code>${escapeHtml(text(first.scope_id))}</code></dd></div></dl>${profile.management_url ? managementLink(profile.management_url, "管理此凭证") : ""}</section>`;
    }).join("");
    return `<div class="credential-diagnostic"><strong class="credential-diagnostic-title">凭证未就绪，任务暂不能提交</strong>${cards}</div>`;
  }
  function renderPreflightFailure(node, preflight) {
    if (!node) return;
    node.className = "inline-status error preflight-diagnostic";
    node.setAttribute("role", "alert");
    node.innerHTML = preflightErrorMarkup(preflight);
    node.hidden = false;
  }
  function option(value, label) { return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`; }
  function selectionName(selection) {
    if (!selection) return "—";
    if (selection.run_type === "flow") return `Flow · ${text(selection.flow_id)}`;
    if (selection.run_type === "single") return `单接口 · ${text(selection.api_id)} / ${text(selection.case_id)}`;
    if (selection.run_type === "batch") {
      const batchType = selection.batch_type === "flows" ? "Flows" : "Cases";
      const selectionMode = selection.selection_mode === "all_safe" ? "全部安全项" : "手动选择";
      const itemCount = Number(selection.item_count || selection.items && selection.items.length || 0);
      return `批量 ${batchType} · ${selectionMode}${itemCount ? ` · ${itemCount} 项` : ""}`;
    }
    return "全部资产";
  }
  function flowTitle(item) {
    // ``name`` 为兼容旧 API 调用方继续等于 Flow ID；界面必须优先使用
    // 项目 YAML 提供的 display_name，才能让测试人员快速理解业务用途。
    return item ? (item.display_name || item.name || item.id) : "未命名 Flow";
  }

  function normalizedTags(value) {
    return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
  }

  function assetRiskTags(item) {
    if (!item || typeof item !== "object") return [];
    if (Object.prototype.hasOwnProperty.call(item, "risk_tags")) return normalizedTags(item.risk_tags);
    // 旧 catalog 没有公开 risk_tags 时，只从 YAML 标签推导现有后端认可的
    // 三类风险；新接口即使显式返回空数组，也绝不被本地猜测覆盖。
    return normalizedTags(item.tags).filter((tag) => ["explicit", "destructive", "interactive"].includes(tag));
  }

  function riskBadges(tags) {
    const values = normalizedTags(tags);
    return values.length
      ? values.map((tag) => `<span class="risk-badge risk-${escapeHtml(tag.toLowerCase().replace(/[^a-z0-9_-]+/g, "-"))}">${escapeHtml(tag)}</span>`).join("")
      : '<span class="muted">无</span>';
  }

  async function api(path, options) {
    const requestOptions = Object.assign({}, options || {});
    const headers = Object.assign({ "Accept": "application/json" }, requestOptions.headers || {});
    const isMultipart = typeof FormData !== "undefined" && requestOptions.body instanceof FormData;
    if (!isMultipart && !Object.keys(headers).some((name) => name.toLowerCase() === "content-type")) {
      headers["Content-Type"] = "application/json";
    }
    requestOptions.headers = headers;
    const response = await window.fetch(`${base}${path}`, requestOptions);
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
  function safeManagementUrl(url) {
    if (!url) return "";
    try {
      const raw = String(url);
      // 管理入口由平台返回，但仍只接受本站三个已知根路径。拒绝绝对 URL、
      // protocol-relative URL 与其它页面，避免异常响应把用户带到外部站点。
      if (!raw.startsWith("/") || raw.startsWith("//")) return "";
      const parsed = new URL(raw, window.location.origin);
      if (parsed.origin !== window.location.origin) return "";
      if (!["/account/credentials", "/settings/config", "/settings/secrets"].includes(parsed.pathname)) return "";
      return `${parsed.pathname}${parsed.search}`;
    } catch (_) {
      return "";
    }
  }
  function managementLink(url, label) {
    const target = safeManagementUrl(url);
    if (!target) return "";
    return `<a class="text-link" href="${escapeHtml(target)}">${escapeHtml(label || "前往平台配置中心")}</a>`;
  }
  function releaseLabel(release) {
    if (!release) return "未发布";
    return `v${text(release.version, "—")} · ${text(release.status, "active")}`;
  }
  function profileLabel(profiles) {
    if (!Array.isArray(profiles) || !profiles.length) return "无需凭证";
    return profiles.map((item) => {
      if (typeof item === "string") return item;
      const status = text(item.status, "ready");
      return `${text(item.id)} · ${statusLabels[status] || status}`;
    }).join("、");
  }

  function activateNavigation() {
    const active = page === "task-single" || page === "task-flow" || page === "task-batch"
      ? "task-new"
      : page === "task-detail" ? "tasks" : page;
    all("[data-nav]").forEach((link) => {
      if (link.dataset.nav === active) link.setAttribute("aria-current", "page");
    });
  }

  function activateTabKeyboardNavigation() {
    // 原生链接/按钮已经可通过 Tab 到达；方向键只在同一 tablist 内移动焦点，
    // Enter/Space 仍交给浏览器触发真实导航或按钮，避免制造第二套状态机。
    all('[role="tablist"]').forEach((tabList) => {
      tabList.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        const tabs = all('[role="tab"]', tabList).filter((tab) => !tab.disabled);
        const current = tabs.indexOf(document.activeElement);
        if (current < 0 || !tabs.length) return;
        event.preventDefault();
        const index = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
        tabs[index].focus();
      });
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
      renderPreflightFailure(runtimeNode, preflight);
      if (management && (first.management_url || runtime.management_url)) {
        const managementTarget = safeManagementUrl(first.management_url || runtime.management_url);
        if (managementTarget) {
          management.href = managementTarget;
          management.hidden = false;
        }
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
        contextNode.innerHTML = `<dl class="summary-list dense"><div><dt>项目</dt><dd>${escapeHtml(context.display_name)}</dd></div><div><dt>平台项目</dt><dd>${escapeHtml(text(context.platform_project_id))}</dd></div><div><dt>平台 / 接口环境</dt><dd>${escapeHtml(String(context.platform_environment || "").toUpperCase())} / ${escapeHtml(String(context.target_env || "").toUpperCase())}</dd></div><div><dt>Runtime Scope</dt><dd>${escapeHtml(text(context.scope_id))}</dd></div><div><dt>Release</dt><dd>${escapeHtml(releaseLabel(context.release || runtime.release))}</dd></div><div><dt>资产数量</dt><dd>${context.counts.apis} APIs · ${context.counts.cases} Cases · ${context.counts.flows} Flows</dd></div><div><dt>Profile</dt><dd>${escapeHtml(profileLabel(preflight.profiles || context.credential_profiles))}</dd></div></dl><div class="inline-status ${preflight.ready ? "success" : "error preflight-diagnostic"}">${preflight.ready ? escapeHtml("运行上下文已就绪，可切换到该项目。") : preflightErrorMarkup(preflight)}</div><div class="button-row context-actions"><button class="button primary" id="confirm-project" type="button" ${preflight.ready ? "" : "disabled"}>切换到 ${escapeHtml(context.display_name)}</button>${managementLink((errors[0] || {}).management_url || runtime.management_url)}</div>`;
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
    const mode = document.body.dataset.mode || root.dataset.taskMode || "single";
    const projects = await loadProjects();
    const selected = setCurrentProjectHeader(projects);
    const projectSelect = byId("task-project");
    const form = byId("task-form");
    const submit = byId("task-submit");
    let catalog = null;
    let lastPreflight = null;
    let selectedFiles = [];
    let fileInputContract = null;
    let selectedFlowId = "";
    let selectedRuntimeAsset = null;
    let runtimeOverrides = {};
    let runtimeDraftNotice = "";
    let runtimeInputTimer = null;
    const selectedBatchItems = new Map();
    let batchTagFilters = [];
    const searchParams = new URLSearchParams(window.location.search);
    const retryFrom = searchParams.get("retry_from") || "";
    const urlPreset = {
      apiId: searchParams.get("api_id") || "",
      caseId: searchParams.get("case_id") || "",
      flowId: searchParams.get("flow_id") || "",
    };
    projectSelect.innerHTML = option("", "请选择项目") + projects.map((item) => option(item.project_id, `${item.display_name} · ${String(item.target_env || "").toUpperCase()}`)).join("");
    if (selected) projectSelect.value = selected.project_id;

    function fileMetadata() {
      return selectedFiles.map((file) => ({ name: file.name, content_type: file.type, size_bytes: file.size }));
    }
    function batchType() {
      const control = form.querySelector('input[name="batch_type"]:checked');
      return control ? control.value : "cases";
    }
    function batchSelectionMode() {
      const control = form.querySelector('input[name="selection_mode"]:checked');
      return control ? control.value : "selected";
    }
    function batchSourceItems() {
      return catalog && Array.isArray(catalog[batchType()]) ? catalog[batchType()] : [];
    }
    function batchAssetId(item) {
      return String(item && (item.asset_id || item.id) || "");
    }
    function isBatchEligible(item) {
      return Boolean(item) && item.batch_eligible !== false;
    }
    function isAllSafeCandidate(item) {
      if (!isBatchEligible(item)) return false;
      if (assetRiskTags(item).some((tag) => ["explicit", "destructive", "interactive"].includes(tag))) return false;
      const contract = item && item.inputs && item.inputs.media_files;
      return !(contract && contract.required);
    }
    function matchesBatchTags(item) {
      const tags = new Set(normalizedTags(item && item.tags));
      return batchTagFilters.every((tag) => tags.has(tag));
    }
    function filteredBatchItems(includeSearch) {
      const query = includeSearch === false ? "" : byId("batch-search").value.trim().toLowerCase();
      return batchSourceItems().filter((item) => {
        if (!matchesBatchTags(item)) return false;
        return !query || `${batchAssetId(item)} ${text(item.name, "")} ${text(item.display_name, "")} ${text(item.api, "")}`.toLowerCase().includes(query);
      });
    }
    function resolvedBatchTargets() {
      if (batchSelectionMode() === "all_safe") return filteredBatchItems(false).filter(isAllSafeCandidate);
      return Array.from(selectedBatchItems.values());
    }
    function selectedRiskTags() {
      return Array.from(new Set(resolvedBatchTargets().flatMap(assetRiskTags))).sort();
    }
    function riskAcknowledgements() {
      return all('input[name="risk_acknowledgement"]:checked', byId("batch-risk-options")).map((input) => input.value);
    }
    function selection(includeInputs) {
      const payload = { project_id: projectSelect.value, run_type: mode };
      if (mode === "single") {
        payload.api_id = byId("task-api").value;
        payload.case_id = byId("task-case").value;
      } else if (mode === "flow") {
        payload.flow_id = byId("task-flow").value;
      } else {
        payload.batch_type = batchType();
        payload.selection_mode = batchSelectionMode();
        payload.items = payload.selection_mode === "selected"
          ? resolvedBatchTargets().map((item) => ({ asset_id: batchAssetId(item), asset_revision: item.asset_revision || null }))
          : [];
        payload.tag_filters = batchTagFilters.slice();
        payload.risk_acknowledgements = riskAcknowledgements();
      }
      if (includeInputs !== false && fileInputContract) payload.inputs = { media_files: fileMetadata() };
      if (Object.keys(runtimeOverrides).length && selectedRuntimeAsset) {
        payload.asset_revision = selectedRuntimeAsset.asset_revision;
        payload.runtime_overrides = Object.assign({}, runtimeOverrides);
      }
      // “修改参数后重试”仍创建不可变新任务，但必须把来源任务写入审计链。
      // 服务端会再次校验来源任务权限、终态、项目及 run_type。
      if (retryFrom && mode !== "batch") payload.retry_from = retryFrom;
      return payload;
    }
    function complete(payload) {
      if (!payload.project_id) return false;
      if (mode === "single") return Boolean(payload.api_id && payload.case_id);
      if (mode === "flow") return Boolean(payload.flow_id);
      return resolvedBatchTargets().length > 0;
    }
    function fileInputError() {
      if (!fileInputContract) return "";
      const minimum = Number(fileInputContract.min_items || 1);
      const maximum = Number(fileInputContract.max_items || 9);
      if (selectedFiles.length < minimum) return `请选择至少 ${minimum} 张图片。`;
      if (selectedFiles.length > maximum) return `最多选择 ${maximum} 张图片。`;
      const allowed = new Set(fileInputContract.allowed_content_types || ["image/jpeg", "image/png", "image/webp"]);
      const maxSize = Number(fileInputContract.max_size_bytes || 0);
      for (const file of selectedFiles) {
        if (!allowed.has(file.type)) return `${file.name} 不是支持的 JPEG、PNG 或 WebP。`;
        if (!file.size) return `${file.name} 是空文件，无法上传。`;
        if (maxSize && file.size > maxSize) return `${file.name} 超过 ${formatBytes(maxSize)}。`;
      }
      return "";
    }
    function renderMediaFiles() {
      if (mode !== "flow" && mode !== "batch") return;
      const block = byId("task-media-input");
      const input = byId("task-media-files");
      const summary = byId("task-input-summary");
      if (!fileInputContract) {
        block.hidden = true;
        input.disabled = true;
        summary.hidden = true;
        return;
      }
      block.hidden = false;
      input.disabled = false;
      input.accept = (fileInputContract.allowed_content_types || ["image/jpeg", "image/png", "image/webp"]).join(",");
      byId("task-media-label").textContent = fileInputContract.label || (mode === "batch" ? "共享输入图片" : "分析图片");
      byId("task-media-description").textContent = fileInputContract.description || (mode === "batch" ? "所选 Flow 输入契约兼容，本组图片会按顺序提供给每个目标。" : "按聊天顺序选择图片。");
      byId("task-media-count").textContent = selectedFiles.length ? `已选 ${selectedFiles.length} 张` : "尚未选择图片";
      const totalBytes = selectedFiles.reduce((sum, file) => sum + Number(file.size || 0), 0);
      byId("task-media-size").textContent = `总计 ${formatBytes(totalBytes)}`;
      byId("task-media-clear").hidden = selectedFiles.length === 0;
      byId("task-media-list").innerHTML = selectedFiles.map((file, index) => `<li><span class="media-order">${index + 1}</span><span class="media-file-copy"><strong>${escapeHtml(file.name)}</strong><small>${escapeHtml(file.type || "未知类型")} · ${escapeHtml(formatBytes(file.size))}</small></span><button class="text-button danger-text" type="button" data-remove-file="${index}" aria-label="移除 ${escapeHtml(file.name)}">移除</button></li>`).join("");
      all("[data-remove-file]", byId("task-media-list")).forEach((button) => button.addEventListener("click", () => {
        selectedFiles.splice(Number(button.dataset.removeFile), 1);
        // 原生 file input 仍保留上一次完整 FileList；移除单张后清空它，
        // 才能保证用户重新选择同一组图片时也会触发 change 并恢复顺序。
        input.value = "";
        renderMediaFiles();
        runPreflight();
      }));
      const error = fileInputError();
      const errorNode = byId("task-media-error");
      errorNode.hidden = !error;
      errorNode.textContent = error;
      summary.hidden = false;
      summary.querySelector("dd").textContent = selectedFiles.length ? `${selectedFiles.length} 张 · ${formatBytes(totalBytes)}` : "未选择";
    }
    function clearMediaFiles() {
      selectedFiles = [];
      if (byId("task-media-files")) byId("task-media-files").value = "";
      renderMediaFiles();
    }
    function normalizedFileExecutionContract(contract) {
      // label/description 只控制展示，不影响图片能否共享；MIME 列表顺序也
      // 没有执行语义。这里与 TaskManager 的批次契约投影保持同一字段集合，
      // 避免 Analysis/Reply 仅因文案不同就被浏览器误判为冲突。
      const source = contract && typeof contract === "object" ? contract : {};
      const read = (key) => Object.prototype.hasOwnProperty.call(source, key) ? source[key] : null;
      const contentTypes = read("allowed_content_types");
      return {
        type: read("type"),
        required: read("required"),
        min_items: read("min_items"),
        max_items: read("max_items"),
        allowed_content_types: Array.isArray(contentTypes)
          ? contentTypes.map((item) => String(item)).sort()
          : contentTypes,
        max_size_bytes: read("max_size_bytes"),
      };
    }
    function fileExecutionContractSignature(contract) {
      return JSON.stringify(normalizedFileExecutionContract(contract));
    }
    function setFileInputContract(contract) {
      const next = contract && typeof contract === "object" ? contract : null;
      const previousSignature = fileInputContract ? fileExecutionContractSignature(fileInputContract) : "";
      const nextSignature = next ? fileExecutionContractSignature(next) : "";
      if (previousSignature && previousSignature !== nextSignature) clearMediaFiles();
      fileInputContract = next;
      renderMediaFiles();
    }
    function localBatchInputContract() {
      if (mode !== "batch" || batchType() !== "flows") return null;
      const targets = resolvedBatchTargets();
      if (!targets.length) return null;
      const contracts = targets.map((item) => item && item.inputs && item.inputs.media_files)
        .filter((contract) => contract && typeof contract === "object" && contract.required);
      if (!contracts.length) return null;
      const signature = fileExecutionContractSignature(contracts[0]);
      return contracts.every((contract) => fileExecutionContractSignature(contract) === signature) ? contracts[0] : null;
    }
    function updateFlowInputContract() {
      if (mode !== "flow") return;
      const flowId = byId("task-flow").value;
      if (flowId !== selectedFlowId) clearMediaFiles();
      selectedFlowId = flowId;
      const flow = catalog && (catalog.flows || []).find((item) => item.id === flowId);
      const inputs = flow && flow.inputs;
      setFileInputContract(inputs && inputs.media_files ? inputs.media_files : null);
    }

    function selectedCatalogAsset() {
      if (!catalog) return null;
      if (mode === "single") {
        const apiId = byId("task-api").value;
        const caseId = byId("task-case").value;
        return (catalog.cases || []).find((item) => item.api === apiId && item.id === caseId) || null;
      }
      if (mode === "batch") return null;
      const flowId = byId("task-flow").value;
      return (catalog.flows || []).find((item) => item.id === flowId) || null;
    }

    function setRuntimeControlValue(control, field, value) {
      if (field.type === "boolean") control.value = value === true ? "true" : "false";
      else if (field.type === "json") control.value = JSON.stringify(value || {}, null, 2);
      else control.value = value === null || value === undefined ? "" : String(value);
    }

    function parseRuntimeControl(field, control) {
      const raw = control.value;
      if (field.type === "boolean") return { value: raw === "true", error: "" };
      if (field.type === "json") {
        if (!raw.trim()) return { value: null, error: "请输入 JSON 对象。" };
        try {
          const value = JSON.parse(raw);
          if (!value || typeof value !== "object" || Array.isArray(value)) {
            return { value, error: "JSON 根节点必须是对象，不能是数组或基础类型。" };
          }
          return { value, error: "" };
        } catch (error) {
          return { value: null, error: `JSON 格式错误：${error.message}` };
        }
      }
      if (field.type === "integer" || field.type === "number") {
        // P0 不支持“空值删除”。即使声明为非必填，用户也只能保留 YAML
        // 默认值或输入一个符合类型的显式数值，不能把已有叶子改成 null。
        if (!raw.trim()) return { value: null, error: "请输入数值。" };
        const value = Number(raw);
        if (!Number.isFinite(value)) return { value, error: "请输入有效数值。" };
        if (Math.abs(value) > Number.MAX_SAFE_INTEGER) return { value, error: `数值必须在 ±${Number.MAX_SAFE_INTEGER} 范围内。` };
        if (field.type === "integer" && !Number.isSafeInteger(value)) return { value, error: "请输入可无损传输的整数。" };
        return { value, error: "" };
      }
      if (field.required && !raw.length) return { value: raw, error: "此字段不能为空。" };
      return { value: raw, error: "" };
    }

    function validateRuntimeValue(field, value, parseError) {
      if (parseError) return parseError;
      const constraints = field.constraints || {};
      if (field.type === "json" && /{{[^{}]+}}/.test(JSON.stringify(value))) {
        return "JSON 中不能使用动态模板。";
      }
      if (typeof value === "string") {
        if (/{{[^{}]+}}/.test(value)) return "动态模板不能作为本次运行参数。";
        if (Number.isInteger(constraints.min_length) && value.length < constraints.min_length) return `至少输入 ${constraints.min_length} 个字符。`;
        if (Number.isInteger(constraints.max_length) && value.length > constraints.max_length) return `最多输入 ${constraints.max_length} 个字符。`;
        if (constraints.pattern) {
          try { if (!(new RegExp(constraints.pattern)).test(value)) return "输入值不符合格式要求。"; }
          catch (_error) { return "字段格式规则无效，请检查 YAML 声明。"; }
        }
      }
      if (field.type === "enum" && !(field.options || []).includes(value)) return "请选择允许的选项。";
      if ((field.type === "integer" || field.type === "number") && value !== null) {
        if (constraints.minimum !== undefined && value < Number(constraints.minimum)) return `最小值为 ${constraints.minimum}。`;
        if (constraints.maximum !== undefined && value > Number(constraints.maximum)) return `最大值为 ${constraints.maximum}。`;
      }
      return "";
    }

    function runtimeValueMatchesType(field, value) {
      if (field.type === "boolean") return typeof value === "boolean";
      if (field.type === "integer") return typeof value === "number" && Number.isSafeInteger(value);
      if (field.type === "number") return typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
      if (field.type === "string" || field.type === "enum") return typeof value === "string";
      if (field.type === "json") return Boolean(value) && typeof value === "object" && !Array.isArray(value);
      return false;
    }

    function compatibleRuntimeOverrides(previousFields, currentFields, values) {
      // Retry 与 YAML 热更新都只按逻辑键迁移草稿；类型变化、约束变化或字段
      // 删除时绝不做 string→boolean/number 等隐式转换，避免改写错误业务参数。
      const previousByKey = new Map((previousFields || []).map((field) => [field.key, field]));
      const currentByKey = new Map((currentFields || []).map((field) => [field.key, field]));
      const compatible = {};
      const skipped = [];
      Object.entries(values || {}).forEach(([key, value]) => {
        const previous = previousByKey.get(key);
        const current = currentByKey.get(key);
        if (
          !previous || !current || previous.type !== current.type ||
          !runtimeValueMatchesType(current, value) ||
          validateRuntimeValue(current, value, "")
        ) {
          skipped.push(key);
          return;
        }
        compatible[key] = value;
      });
      return { values: compatible, skipped };
    }

    function setRuntimeDraftNotice(message) {
      runtimeDraftNotice = message || "";
      const notice = byId("runtime-input-notice");
      if (!notice) return;
      notice.hidden = !runtimeDraftNotice;
      notice.textContent = runtimeDraftNotice;
    }

    function setRuntimeFieldError(key, message) {
      const wrapper = byId("runtime-input-fields").querySelector(`[data-runtime-field="${CSS.escape(key)}"]`);
      if (!wrapper) return;
      const control = wrapper.querySelector("input, select, textarea");
      const error = wrapper.querySelector(".runtime-input-field-error");
      wrapper.classList.toggle("has-error", Boolean(message));
      if (control) control.setAttribute("aria-invalid", message ? "true" : "false");
      if (error) { error.textContent = message || ""; error.hidden = !message; }
    }

    function collectRuntimeOverrides() {
      const fields = selectedRuntimeAsset && Array.isArray(selectedRuntimeAsset.runtime_inputs)
        ? selectedRuntimeAsset.runtime_inputs : [];
      const values = {};
      const errors = [];
      for (const field of fields) {
        const control = byId("runtime-input-fields").querySelector(`[data-runtime-key="${CSS.escape(field.key)}"]`);
        if (!control) continue;
        const parsed = parseRuntimeControl(field, control);
        const message = validateRuntimeValue(field, parsed.value, parsed.error);
        setRuntimeFieldError(field.key, message);
        if (message) errors.push({ key: field.key, message });
        else if (JSON.stringify(parsed.value) !== JSON.stringify(field.default_value)) values[field.key] = parsed.value;
      }
      runtimeOverrides = values;
      const summaryError = byId("runtime-input-error");
      summaryError.hidden = !errors.length;
      summaryError.textContent = errors.length ? `请修正 ${errors.length} 个参数后再提交。` : "";
      return errors;
    }

    function scheduleRuntimePreflight() {
      collectRuntimeOverrides();
      lastPreflight = null;
      submit.disabled = true;
      if (runtimeInputTimer) window.clearTimeout(runtimeInputTimer);
      runtimeInputTimer = window.setTimeout(runPreflight, 180);
    }

    function renderRuntimeInputs(presetOverrides, assetOverride) {
      if (mode === "batch") {
        selectedRuntimeAsset = null;
        runtimeOverrides = {};
        byId("task-runtime-inputs").hidden = true;
        return;
      }
      selectedRuntimeAsset = assetOverride || selectedCatalogAsset();
      runtimeOverrides = {};
      const panel = byId("task-runtime-inputs");
      const container = byId("runtime-input-fields");
      const empty = byId("runtime-input-empty");
      const resetAll = byId("runtime-input-reset-all");
      const fields = selectedRuntimeAsset && Array.isArray(selectedRuntimeAsset.runtime_inputs)
        ? selectedRuntimeAsset.runtime_inputs : [];
      container.innerHTML = "";
      byId("runtime-input-error").hidden = true;
      if (!fields.length) {
        // 单接口已经选定但没有安全静态参数时保留明确空态，避免用户误以为
        // 页面加载失败；尚未选择资产及无白名单 Flow 仍隐藏整块区域。
        const showAssetEmpty = Boolean(selectedRuntimeAsset);
        panel.hidden = !showAssetEmpty;
        empty.hidden = !showAssetEmpty;
        resetAll.hidden = true;
        return;
      }

      panel.hidden = false;
      empty.hidden = true;
      resetAll.hidden = false;
      fields.forEach((field, index) => {
        const wrapper = document.createElement("div");
        wrapper.className = "runtime-input-field";
        // JSON 是本次 Flow 的完整结构化输入，不适合被压缩到普通参数的右侧窄列；
        // 独立 class 让说明和编辑器纵向排列，在 1280px 桌面宽度仍可直接编辑长消息。
        if (field.type === "json") wrapper.classList.add("runtime-input-field-json");
        wrapper.dataset.runtimeField = field.key;
        const controlId = `runtime-input-${index}`;
        const group = field.group && (field.group.step_name || field.group.step_id);
        const required = field.required ? " · 必填" : "";
        wrapper.innerHTML = `<div class="runtime-input-copy"><label for="${controlId}">${escapeHtml(field.label)}</label><p>${escapeHtml(field.description || "仅用于当前任务。")}</p><small>${group ? `步骤：${escapeHtml(group)} · ` : ""}${escapeHtml(field.type)}${required} · YAML 默认 ${escapeHtml(formatRuntimeValue(field.default_value))}</small></div><div class="runtime-input-control"></div>`;
        const controlRoot = wrapper.querySelector(".runtime-input-control");
        let control;
        if (field.type === "enum" || field.type === "boolean") {
          control = document.createElement("select");
          const values = field.type === "boolean" ? [true, false] : (field.options || []);
          control.innerHTML = values.map((value) => option(String(value), field.type === "boolean" ? (value ? "是（true）" : "否（false）") : String(value))).join("");
        } else if (field.type === "json") {
          control = document.createElement("textarea");
          control.rows = 18;
          control.spellcheck = false;
          control.autocapitalize = "off";
          control.autocomplete = "off";
          control.className = "runtime-json-editor";
          control.setAttribute("aria-label", field.label);
        } else {
          control = document.createElement("input");
          control.type = field.type === "integer" || field.type === "number" ? "number" : "text";
          if (field.type === "integer") control.step = "1";
          else if (field.type === "number") control.step = "any";
          const constraints = field.constraints || {};
          if (field.type === "integer" || field.type === "number") {
            const minimum = constraints.minimum === undefined
              ? -Number.MAX_SAFE_INTEGER
              : Math.max(Number(constraints.minimum), -Number.MAX_SAFE_INTEGER);
            const maximum = constraints.maximum === undefined
              ? Number.MAX_SAFE_INTEGER
              : Math.min(Number(constraints.maximum), Number.MAX_SAFE_INTEGER);
            control.min = String(minimum);
            control.max = String(maximum);
          }
          if (constraints.max_length !== undefined) control.maxLength = Number(constraints.max_length);
        }
        control.id = controlId;
        control.dataset.runtimeKey = field.key;
        control.setAttribute("aria-describedby", `${controlId}-error`);
        const preset = presetOverrides && Object.prototype.hasOwnProperty.call(presetOverrides, field.key)
          ? presetOverrides[field.key] : field.default_value;
        setRuntimeControlValue(control, field, preset);
        const error = document.createElement("p");
        error.className = "runtime-input-field-error field-message";
        error.id = `${controlId}-error`;
        error.hidden = true;
        controlRoot.append(control, error);
        const reset = document.createElement("button");
        reset.className = "text-button runtime-input-reset";
        reset.type = "button";
        reset.textContent = "恢复默认";
        reset.addEventListener("click", () => { setRuntimeControlValue(control, field, field.default_value); scheduleRuntimePreflight(); control.focus(); });
        controlRoot.append(reset);
        control.addEventListener(control.tagName === "SELECT" ? "change" : "input", scheduleRuntimePreflight);
        container.append(wrapper);
      });
      collectRuntimeOverrides();
    }

    function updateCatalogRuntimeContract(asset) {
      const selectedAsset = selectedCatalogAsset();
      if (!selectedAsset || !asset) return;
      [
        "asset_revision",
        "runtime_input_schema_revision",
        "runtime_inputs",
        "runtime_input_count",
        "inputs",
      ].forEach((key) => {
        if (Object.prototype.hasOwnProperty.call(asset, key)) selectedAsset[key] = asset[key];
      });
    }

    function synchronizeFileInputContract(asset) {
      if (mode !== "flow" || !asset) return;
      const inputs = asset.inputs && typeof asset.inputs === "object" ? asset.inputs : {};
      const nextContract = inputs.media_files && typeof inputs.media_files === "object"
        ? inputs.media_files : null;
      setFileInputContract(nextContract);
    }

    function synchronizeRuntimeAsset(asset) {
      if (!asset || !asset.asset_revision) return { changed: false, skipped: [] };
      const previous = selectedRuntimeAsset;
      const changed = Boolean(previous && previous.asset_revision !== asset.asset_revision);
      updateCatalogRuntimeContract(asset);
      synchronizeFileInputContract(asset);
      if (!changed) {
        selectedRuntimeAsset = asset;
        return { changed: false, skipped: [] };
      }

      const compatibility = compatibleRuntimeOverrides(
        previous && previous.runtime_inputs,
        asset.runtime_inputs,
        runtimeOverrides,
      );
      renderRuntimeInputs(compatibility.values, asset);
      const skippedText = compatibility.skipped.length
        ? `；${compatibility.skipped.join("、")} 已因字段删除、类型或约束变化恢复 YAML 默认值`
        : "；兼容的草稿值已保留";
      setRuntimeDraftNotice(`YAML 运行参数声明已更新${skippedText}，请重新确认后提交。`);
      return { changed: true, skipped: compatibility.skipped };
    }

    function applyServerRuntimeErrors(preflight) {
      const fieldErrors = (preflight.errors || []).flatMap((item) => Array.isArray(item.field_errors) ? item.field_errors : []);
      fieldErrors.forEach((item) => setRuntimeFieldError(String(item.key || ""), item.message || "参数值无效。"));
      if (fieldErrors.length) {
        byId("runtime-input-error").hidden = false;
        byId("runtime-input-error").textContent = `服务端拒绝了 ${fieldErrors.length} 个参数，请修正后重试。`;
      }
    }

    function renderBatchTagFilters() {
      if (mode !== "batch") return;
      const container = byId("batch-tag-options");
      const available = Array.from(new Set(batchSourceItems().flatMap((item) => normalizedTags(item.tags)))).sort();
      batchTagFilters = batchTagFilters.filter((tag) => available.includes(tag));
      container.innerHTML = available.length
        ? available.map((tag) => `<label class="tag-choice"><input type="checkbox" value="${escapeHtml(tag)}" ${batchTagFilters.includes(tag) ? "checked" : ""}><span>${escapeHtml(tag)}</span></label>`).join("")
        : '<span class="muted">当前资产没有 YAML 标签。</span>';
      all('input[type="checkbox"]', container).forEach((input) => input.addEventListener("change", () => {
        batchTagFilters = all('input[type="checkbox"]:checked', container).map((item) => item.value);
        Array.from(selectedBatchItems.entries()).forEach(([id, item]) => {
          if (!matchesBatchTags(item)) selectedBatchItems.delete(id);
        });
        setFileInputContract(localBatchInputContract());
        renderBatchResults();
        runPreflight();
      }));
    }

    function renderRiskAcknowledgements() {
      if (mode !== "batch") return;
      const section = byId("batch-risk-acknowledgements");
      const container = byId("batch-risk-options");
      const previous = new Set(riskAcknowledgements());
      const tags = selectedRiskTags();
      section.hidden = !tags.length;
      container.innerHTML = tags.map((tag) => `<label class="risk-choice"><input name="risk_acknowledgement" type="checkbox" value="${escapeHtml(tag)}" ${previous.has(tag) ? "checked" : ""}><span>确认 <strong>${escapeHtml(tag)}</strong> 风险标签</span></label>`).join("");
      all('input[name="risk_acknowledgement"]', container).forEach((input) => input.addEventListener("change", runPreflight));
    }

    function renderBatchResults() {
      if (mode !== "batch") return;
      const items = filteredBatchItems(true);
      const selectionMode = batchSelectionMode();
      const allSafe = selectionMode === "all_safe";
      const selectedCount = allSafe ? resolvedBatchTargets().length : selectedBatchItems.size;
      submit.textContent = `加入执行队列（${selectedCount}）`;
      byId("batch-result-count").textContent = `${items.length} 项结果`;
      byId("batch-selected-count").textContent = allSafe ? `${selectedCount} 个安全项将由服务端解析` : `已选 ${selectedCount} 项`;
      byId("batch-select-visible").disabled = allSafe || !items.some(isBatchEligible);
      byId("batch-clear-selection").disabled = allSafe || selectedBatchItems.size === 0;
      const node = byId("batch-results");
      node.innerHTML = items.length ? items.map((item) => {
        const assetId = batchAssetId(item);
        const eligible = isBatchEligible(item);
        const checked = allSafe ? isAllSafeCandidate(item) : selectedBatchItems.has(assetId);
        const metadata = batchType() === "cases"
          ? `${text(item.api, "未知 API")} · ${normalizedTags(item.tags).join(" · ") || "无标签"}`
          : `${Number(item.step_count || item.steps && item.steps.length || 0)} 步 · ${normalizedTags(item.tags).join(" · ") || "无标签"}`;
        const risks = assetRiskTags(item);
        const safety = !eligible ? statusBadge("invalid", "不可批量")
          : risks.length ? statusBadge("pending", "需确认") : statusBadge("ready", "可批量");
        return `<label class="batch-result-row ${eligible ? "" : "is-ineligible"}"><input type="checkbox" data-batch-item="${escapeHtml(assetId)}" ${checked ? "checked" : ""} ${allSafe || !eligible ? "disabled" : ""}><span class="batch-result-copy"><strong>${escapeHtml(item.display_name || item.name || assetId)}</strong><small><code>${escapeHtml(assetId)}</code> · ${escapeHtml(metadata)}</small></span><span class="batch-result-safety">${safety}${riskBadges(risks)}</span></label>`;
      }).join("") : '<p class="empty-state">没有同时满足搜索与 YAML 标签的资产。</p>';
      all("[data-batch-item]", node).forEach((input) => input.addEventListener("change", () => {
        const item = batchSourceItems().find((candidate) => batchAssetId(candidate) === input.dataset.batchItem);
        if (input.checked && item && isBatchEligible(item)) selectedBatchItems.set(input.dataset.batchItem, item);
        else selectedBatchItems.delete(input.dataset.batchItem);
        setFileInputContract(localBatchInputContract());
        renderBatchResults();
        runPreflight();
      }));
      renderRiskAcknowledgements();
    }

    function resetBatchSelection() {
      selectedBatchItems.clear();
      batchTagFilters = [];
      setFileInputContract(null);
      renderBatchTagFilters();
      renderBatchResults();
    }

    function updateBatchPreview(preflight) {
      if (mode !== "batch") return;
      const batch = preflight && preflight.batch && typeof preflight.batch === "object" ? preflight.batch : {};
      const queue = preflight && preflight.queue && typeof preflight.queue === "object" ? preflight.queue : {};
      const excluded = Array.isArray(batch.excluded) ? batch.excluded : [];
      const resolvedCount = Number.isFinite(Number(batch.resolved_count)) ? Number(batch.resolved_count) : resolvedBatchTargets().length;
      submit.textContent = `加入执行队列（${resolvedCount}）`;
      byId("batch-preview-count").textContent = `${resolvedCount} 项`;
      byId("batch-preview-excluded").textContent = excluded.length ? `${excluded.length} 项` : "无";
      const position = queue.estimated_position === null || queue.estimated_position === undefined
        ? queue.position : queue.estimated_position;
      const capacity = queue.capacity === null || queue.capacity === undefined ? "—" : queue.capacity;
      byId("batch-preview-queue").textContent = position === null || position === undefined
        ? `${Number(queue.pending_count || 0)} 个等待中 · 容量 ${capacity}`
        : `预计第 ${position} 位 · 容量 ${capacity}`;
      const excludedNode = byId("batch-excluded-list");
      excludedNode.hidden = !excluded.length;
      excludedNode.innerHTML = excluded.map((item) => {
        const entry = item && typeof item === "object" ? item : { asset_id: item };
        return `<div><code>${escapeHtml(entry.asset_id || entry.id || "未知资产")}</code><span>${escapeHtml(entry.reason || entry.message || "未通过批量安全门禁")}</span></div>`;
      }).join("");
      if (Object.prototype.hasOwnProperty.call(batch, "input_contract")) setFileInputContract(batch.input_contract);
      else if (!fileInputContract) setFileInputContract(localBatchInputContract());
      if ((!preflight.profiles || !preflight.profiles.length) && Array.isArray(batch.required_profiles)) {
        byId("task-preview-profiles").textContent = batch.required_profiles.map((item) => typeof item === "string" ? item : text(item.id)).join("、") || "无需凭证";
      }
      byId("task-preview-asset-revision").textContent = resolvedCount ? `${resolvedCount} 个资产版本` : "—";
      byId("task-preview-overrides").textContent = "批量任务不支持临时参数";
    }

    function updatePreview(preflight) {
      const runtime = preflight.runtime || {};
      const asset = preflight.asset || {};
      byId("task-preview-platform").textContent = text(runtime.platform_environment).toUpperCase();
      byId("task-preview-target-env").textContent = text(runtime.target_env).toUpperCase();
      byId("task-preview-scope").textContent = text(runtime.scope_id);
      byId("task-preview-release").textContent = releaseLabel(runtime.release);
      byId("task-preview-profiles").textContent = profileLabel(preflight.profiles);
      byId("task-preview-asset-revision").textContent = text(asset.asset_revision);
      const differences = asset.applied_overrides || [];
      byId("task-preview-overrides").textContent = differences.length
        ? differences.map((item) => `${item.label || item.key}: ${formatRuntimeValue(item.base_value)} → ${formatRuntimeValue(item.resolved_value)}`).join("；")
        : "使用 YAML 默认值";
      updateBatchPreview(preflight);
    }
    let preflightGeneration = 0;
    async function runPreflight(allowSchemaRecovery) {
      const mayRecoverSchema = allowSchemaRecovery !== false;
      // 每次选择变化都会推进代次，包括尚未选完整的状态。较早请求即使较晚
      // 返回，也不能覆盖当前资产的预检结果或重新启用提交按钮。
      const generation = ++preflightGeneration;
      const runtimeErrors = collectRuntimeOverrides();
      const payload = selection(true);
      submit.disabled = true;
      lastPreflight = null;
      if (!complete(payload)) {
        if (mode === "batch") updateBatchPreview({ batch: { resolved_count: 0, excluded: [] }, queue: {} });
        setInlineStatus(byId("task-preflight"), "", mode === "batch" ? "选择至少一个批量资产或可解析的安全范围。" : "选择完整测试资产后执行预检。");
        return;
      }
      if (runtimeErrors.length) {
        setInlineStatus(byId("task-preflight"), "warning", "请先修正本次运行参数。平台运行上下文尚未提交校验。");
        return;
      }
      const localInputError = fileInputError();
      if (localInputError) {
        // 图片只以名称、MIME 和大小元数据进入 Preflight，不会上传文件。
        // 即使当前浏览器契约认为无效，也继续让服务端返回最新 Flow 输入契约；
        // 这样 YAML 在页面打开后放宽/收紧约束时可以自动恢复而无需整页刷新。
        setInlineStatus(byId("task-preflight"), "warning", "正在按服务端最新图片契约重新校验…");
      }
      setInlineStatus(byId("task-preflight"), "loading", "正在校验项目资产与平台运行上下文…");
      try {
        const preflight = await api("/api/preflight", { method: "POST", body: JSON.stringify(payload) });
        if (generation !== preflightGeneration) return;
        const schemaChanged = (preflight.errors || []).some((item) => item.code === "RUNTIME_OVERRIDE_SCHEMA_CHANGED");
        const synchronization = synchronizeRuntimeAsset(preflight.asset);
        if (schemaChanged && synchronization.changed && mayRecoverSchema) {
          // Preflight 已返回当前公开契约，无需整页刷新或重新读取平台配置。
          // 以新 revision 重新预检一次，但绝不自动提交任务。
          return runPreflight(false);
        }
        lastPreflight = preflight;
        updatePreview(preflight);
        applyServerRuntimeErrors(preflight);
        if (preflight.ready) {
          const inputLabel = fileInputContract ? `，${selectedFiles.length} 张图片已就绪` : "";
          const draftLabel = runtimeDraftNotice ? ` ${runtimeDraftNotice}` : "";
          const batchLabel = mode === "batch" && preflight.batch
            ? `，已解析 ${Number(preflight.batch.resolved_count || 0)} 个批量子项`
            : "";
          setInlineStatus(byId("task-preflight"), "success", `预检通过：Scope、Release 与所需 Profile 均已就绪${batchLabel}${inputLabel}。${draftLabel}`);
          submit.disabled = false;
        } else {
          renderPreflightFailure(byId("task-preflight"), preflight);
        }
      } catch (error) {
        if (generation !== preflightGeneration) return;
        setInlineStatus(byId("task-preflight"), "error", error.message);
      }
    }
    function renderFlowPreview() {
      if (mode !== "flow") return;
      const flowId = byId("task-flow").value;
      const flow = catalog && (catalog.flows || []).find((item) => item.id === flowId);
      const node = byId("flow-preview");
      if (!flow) { node.innerHTML = '<p class="empty-state">选择 Flow 后展示业务步骤。</p>'; return; }
      const steps = flow.steps || [];
      const count = Number(flow.step_count || steps.length || 0);
      node.innerHTML = `<p class="flow-summary"><strong>${escapeHtml(flow.display_name || flow.name || flow.id)}</strong><span>${count} 个业务步骤</span></p>${steps.map((step, index) => `<div class="flow-step"><span class="flow-step-index">${index + 1}</span><span><strong>${escapeHtml(step.name || step.api_id || step.action_type || `业务步骤 ${index + 1}`)}</strong><small>${escapeHtml(step.id)} · ${escapeHtml(step.api_id || step.action_type || step.kind)}${step.repeat_for ? " · 每张图片重复" : ""}</small></span></div>`).join("")}`;
    }
    function populateAssets() {
      if (mode === "single") {
        const apiSelect = byId("task-api");
        apiSelect.innerHTML = option("", "请选择 API") + (catalog.apis || []).map((item) => option(item.id, `${item.id} · ${item.name}`)).join("");
        apiSelect.disabled = false;
        byId("task-case").innerHTML = option("", "请先选择 API");
        byId("task-case").disabled = true;
      } else if (mode === "flow") {
        const flowSelect = byId("task-flow");
        flowSelect.innerHTML = option("", "请选择 Flow") + (catalog.flows || []).map((item) => option(item.id, `${item.id} · ${flowTitle(item)} · ${item.step_count} 步`)).join("");
        flowSelect.disabled = false;
        updateFlowInputContract();
        renderFlowPreview();
      } else {
        resetBatchSelection();
      }
    }
    async function loadCatalog() {
      rememberProject(projectSelect.value, projects);
      if (!projectSelect.value) {
        catalog = null;
        if (mode === "batch") {
          resetBatchSelection();
          byId("batch-results").innerHTML = '<p class="empty-state">选择项目后展示可执行资产。</p>';
        }
        setInlineStatus(byId("task-preflight"), "", "请先选择项目。");
        return;
      }
      selectedFlowId = "";
      fileInputContract = null;
      catalog = null;
      selectedRuntimeAsset = null;
      runtimeOverrides = {};
      selectedBatchItems.clear();
      batchTagFilters = [];
      setRuntimeDraftNotice("");
      renderRuntimeInputs();
      clearMediaFiles();
      if (mode === "batch") byId("batch-results").innerHTML = '<p class="empty-state">正在读取可批量执行的资产…</p>';
      setInlineStatus(byId("task-preflight"), "loading", "正在读取项目资产…");
      try {
        catalog = await api(`/api/catalog?project_id=${encodeURIComponent(projectSelect.value)}`);
        populateAssets();
        setInlineStatus(byId("task-preflight"), "", mode === "batch" ? "选择批量范围后执行预检。" : "选择测试资产后执行预检。");
      } catch (error) {
        if (mode === "batch") byId("batch-results").innerHTML = `<p class="empty-state error-text">${escapeHtml(error.message)}</p>`;
        setInlineStatus(byId("task-preflight"), "error", error.message);
      }
    }

    async function loadRetrySource() {
      if (mode === "batch") throw new Error("批量任务请在详情页选择“重试全部”或“仅重试失败项”。");
      const original = await api(`/api/tasks/${encodeURIComponent(retryFrom)}`);
      const originalSelection = original.selection || {};
      const projectId = original.project && original.project.project_id;
      if (!supportsRetrySchema(original.schema_version) || originalSelection.run_type !== mode) {
        throw new Error("原任务类型与当前创建页不一致，无法修改参数后重试。");
      }
      projectSelect.value = projectId || "";
      if (!projectSelect.value) throw new Error("原任务所属项目当前不可用或无访问权限。");
      await loadCatalog();
      if (mode === "single") {
        byId("task-api").value = originalSelection.api_id || "";
        const cases = (catalog && catalog.cases || []).filter((item) => item.api === byId("task-api").value);
        byId("task-case").innerHTML = option("", "请选择 Case") + cases.map((item) => option(item.id, `${item.id} · ${item.name}`)).join("");
        byId("task-case").disabled = !byId("task-api").value;
        byId("task-case").value = originalSelection.case_id || "";
      } else if (mode === "flow") {
        byId("task-flow").value = originalSelection.flow_id || "";
        updateFlowInputContract();
        renderFlowPreview();
      }
      if (!selectedCatalogAsset()) throw new Error("原任务资产已不存在，无法修改参数后重试。");
      const originalOverrides = original.input && original.input.runtime_overrides;
      const currentAsset = selectedCatalogAsset();
      const oldFields = original.asset_snapshot && Array.isArray(original.asset_snapshot.runtime_inputs)
        ? original.asset_snapshot.runtime_inputs : [];
      const compatibility = compatibleRuntimeOverrides(
        oldFields,
        currentAsset.runtime_inputs,
        originalOverrides && typeof originalOverrides === "object" ? originalOverrides : {},
      );
      if (compatibility.skipped.length) {
        setRuntimeDraftNotice(`原任务参数 ${compatibility.skipped.join("、")} 与当前 YAML 类型或约束不兼容，已恢复默认值；请重新确认。`);
      }
      renderRuntimeInputs(compatibility.values, currentAsset);
      await runPreflight();
    }
    projectSelect.addEventListener("change", loadCatalog);
    if (mode === "single") {
      byId("task-api").addEventListener("change", () => {
        const cases = (catalog && catalog.cases || []).filter((item) => item.api === byId("task-api").value);
        byId("task-case").innerHTML = option("", "请选择 Case") + cases.map((item) => option(item.id, `${item.id} · ${item.name}`)).join("");
        byId("task-case").disabled = !byId("task-api").value;
        setRuntimeDraftNotice("");
        renderRuntimeInputs();
        runPreflight();
      });
      byId("task-case").addEventListener("change", () => { setRuntimeDraftNotice(""); renderRuntimeInputs(); runPreflight(); });
    } else if (mode === "flow") {
      byId("task-flow").addEventListener("change", () => { setRuntimeDraftNotice(""); updateFlowInputContract(); renderFlowPreview(); renderRuntimeInputs(); runPreflight(); });
    } else {
      all('input[name="batch_type"]', form).forEach((input) => input.addEventListener("change", () => {
        resetBatchSelection();
        runPreflight();
      }));
      all('input[name="selection_mode"]', form).forEach((input) => input.addEventListener("change", () => {
        setFileInputContract(localBatchInputContract());
        renderBatchResults();
        runPreflight();
      }));
      byId("batch-search").addEventListener("input", renderBatchResults);
      byId("batch-select-visible").addEventListener("click", () => {
        filteredBatchItems(true).filter(isBatchEligible).forEach((item) => selectedBatchItems.set(batchAssetId(item), item));
        setFileInputContract(localBatchInputContract());
        renderBatchResults();
        runPreflight();
      });
      byId("batch-clear-selection").addEventListener("click", () => {
        selectedBatchItems.clear();
        setFileInputContract(null);
        renderBatchResults();
        runPreflight();
      });
    }
    if (mode === "flow" || mode === "batch") {
      byId("task-media-files").addEventListener("change", (event) => {
        selectedFiles = Array.from(event.target.files || []);
        renderMediaFiles();
        runPreflight();
      });
      byId("task-media-clear").addEventListener("click", () => {
        clearMediaFiles();
        runPreflight();
      });
    }
    byId("runtime-input-reset-all").addEventListener("click", () => {
      setRuntimeDraftNotice("");
      renderRuntimeInputs();
      runPreflight();
      const firstControl = byId("runtime-input-fields").querySelector("input, select, textarea");
      if (firstControl) firstControl.focus();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = selection(false);
      if (!lastPreflight || !lastPreflight.ready || !complete(payload)) return runPreflight();
      submit.disabled = true;
      submit.textContent = mode === "batch" ? "正在加入队列…" : "正在提交…";
      try {
        let task;
        if (fileInputContract) {
          const formData = new FormData();
          formData.append("task_payload", JSON.stringify(payload));
          selectedFiles.forEach((file) => formData.append("media_files", file, file.name));
          task = await api("/api/tasks", { method: "POST", body: formData });
        } else {
          task = await api("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
        }
        window.location.assign(`${base}/tasks/${encodeURIComponent(task.id)}`);
      } catch (error) {
        const fieldErrors = error.payload && Array.isArray(error.payload.field_errors)
          ? error.payload.field_errors : [];
        fieldErrors.forEach((item) => setRuntimeFieldError(String(item.key || ""), item.message || "参数值无效。"));
        if (fieldErrors.length) {
          byId("runtime-input-error").hidden = false;
          byId("runtime-input-error").textContent = `服务端拒绝了 ${fieldErrors.length} 个参数，请修正后重试。`;
        }
        const message = error.code === "RUNTIME_OVERRIDE_SCHEMA_CHANGED"
          ? `${error.message} 正在加载最新 YAML 声明并重新预检。`
          : error.message;
        setInlineStatus(byId("task-preflight"), "error", message);
        const requiresFreshPreflight = fieldErrors.length > 0 || error.code === "RUNTIME_OVERRIDE_SCHEMA_CHANGED";
        if (requiresFreshPreflight) lastPreflight = null;
        submit.disabled = requiresFreshPreflight;
        if (mode === "batch") {
          const selectedCount = lastPreflight && lastPreflight.batch
            ? Number(lastPreflight.batch.resolved_count || 0)
            : resolvedBatchTargets().length;
          submit.textContent = `加入执行队列（${selectedCount}）`;
        } else {
          submit.textContent = "提交任务";
        }
        if (error.code === "RUNTIME_OVERRIDE_SCHEMA_CHANGED") await runPreflight();
      }
    });
    if (retryFrom) await loadRetrySource();
    else if (selected) {
      await loadCatalog();
      if (mode === "single" && urlPreset.apiId) {
        byId("task-api").value = urlPreset.apiId;
        const cases = (catalog && catalog.cases || []).filter((item) => item.api === urlPreset.apiId);
        byId("task-case").innerHTML = option("", "请选择 Case") + cases.map((item) => option(item.id, `${item.id} · ${item.name}`)).join("");
        byId("task-case").disabled = false;
        byId("task-case").value = urlPreset.caseId;
        renderRuntimeInputs();
        await runPreflight();
      } else if (mode === "flow" && urlPreset.flowId) {
        byId("task-flow").value = urlPreset.flowId;
        updateFlowInputContract();
        renderFlowPreview();
        renderRuntimeInputs();
        await runPreflight();
      }
    }
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
      const apis = Array.isArray(snapshot.apis) ? snapshot.apis : [];
      const cases = Array.isArray(snapshot.cases) ? snapshot.cases : [];
      const flows = Array.isArray(snapshot.flows) ? snapshot.flows : [];
      byId("catalog-api-count").textContent = apis.length;
      byId("catalog-case-count").textContent = cases.length;
      byId("catalog-flow-count").textContent = flows.length;
      const query = search.value.trim().toLowerCase();
      const items = ({ apis, cases, flows }[type] || []).filter((item) => !query || JSON.stringify(item).toLowerCase().includes(query));
      const head = byId("catalog-table-head");
      const body = byId("catalog-table-body");
      if (type === "apis") {
        head.innerHTML = "<tr><th>ID</th><th>名称</th><th>Service / Method</th><th>Profile</th><th>状态</th><th><span class=\"sr-only\">操作</span></th></tr>";
        body.innerHTML = items.length ? items.map((item) => `<tr><td><code>${escapeHtml(item.id)}</code></td><td>${escapeHtml(item.name)}</td><td>${escapeHtml(text(item.service_name))}<br><span class="muted">${escapeHtml(text(item.method_name))}</span></td><td>${escapeHtml(text(item.credential_profile, "按资产解析"))}</td><td>${statusBadge(item.status, "可用")}</td><td><span class="muted">选择 Case 后运行</span></td></tr>`).join("") : '<tr><td colspan="6" class="table-state">没有匹配的 API。</td></tr>';
      } else if (type === "cases") {
        head.innerHTML = "<tr><th>Case ID</th><th>名称</th><th>API</th><th>标签</th><th>临时参数</th><th>批量安全</th><th>状态</th><th><span class=\"sr-only\">操作</span></th></tr>";
        body.innerHTML = items.length ? items.map((item) => {
          const count = Number(item.runtime_input_count || 0);
          const runUrl = `${base}/tasks/new?mode=single&api_id=${encodeURIComponent(item.api || "")}&case_id=${encodeURIComponent(item.id || "")}`;
          return `<tr><td><code>${escapeHtml(item.id)}</code></td><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.api)}</td><td>${escapeHtml(normalizedTags(item.tags).join(", ") || "—")}</td><td>${count ? `可修改 ${count} 项` : "未开放"}</td><td><div class="safety-cell">${item.batch_eligible === false ? statusBadge("invalid", "不可批量") : statusBadge("ready", "可批量")}${riskBadges(assetRiskTags(item))}</div></td><td>${statusBadge(item.status, "可用")}</td><td><a class="text-link row-run-link" href="${runUrl}">运行</a></td></tr>`;
        }).join("") : '<tr><td colspan="8" class="table-state">没有匹配的 Case。</td></tr>';
      } else {
        head.innerHTML = "<tr><th>Flow ID</th><th>名称</th><th>业务步骤</th><th>引用 API</th><th>临时参数</th><th>批量安全</th><th>状态</th><th><span class=\"sr-only\">操作</span></th></tr>";
        body.innerHTML = items.length ? items.map((item) => {
          const count = Number(item.runtime_input_count || 0);
          const runUrl = `${base}/tasks/new?mode=flow&flow_id=${encodeURIComponent(item.id || "")}`;
          return `<tr><td><code>${escapeHtml(item.id)}</code></td><td>${escapeHtml(flowTitle(item))}</td><td>${escapeHtml(text(item.step_count, "0"))}</td><td>${escapeHtml(normalizedTags(item.apis).join(", ") || "—")}</td><td>${count ? `可修改 ${count} 项` : "未开放"}</td><td><div class="safety-cell">${item.batch_eligible === false ? statusBadge("invalid", "不可批量") : statusBadge("ready", "可批量")}${riskBadges(assetRiskTags(item))}</div></td><td>${statusBadge(item.status, "可用")}</td><td><a class="text-link row-run-link" href="${runUrl}">运行</a></td></tr>`;
        }).join("") : '<tr><td colspan="8" class="table-state">没有匹配的 Flow。</td></tr>';
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
        const apiCount = Array.isArray(snapshot.apis) ? snapshot.apis.length : 0;
        const caseCount = Array.isArray(snapshot.cases) ? snapshot.cases.length : 0;
        const flowCount = Array.isArray(snapshot.flows) ? snapshot.flows.length : 0;
        setInlineStatus(byId("catalog-status"), errors.length ? "warning" : "success", errors.length ? `已加载，${errors.length} 个资产文件未通过校验。` : `已加载 ${apiCount} APIs、${caseCount} Cases、${flowCount} Flows。`);
        render();
      } catch (error) { setInlineStatus(byId("catalog-status"), "error", error.message); }
    }
    all("[data-catalog-type]").forEach((tab) => tab.addEventListener("click", () => {
      type = tab.dataset.catalogType;
      all("[data-catalog-type]").forEach((candidate) => { const active = candidate === tab; candidate.classList.toggle("active", active); candidate.setAttribute("aria-selected", active ? "true" : "false"); candidate.tabIndex = active ? 0 : -1; });
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
      byId("task-list-body").innerHTML = '<tr><td colspan="7" class="table-state">正在读取任务记录…</td></tr>';
      try {
        const data = await api(`/api/tasks?${params.toString()}`);
        const items = Array.isArray(data.items) ? data.items : [];
        const total = Number(data.total === null || data.total === undefined ? items.length : data.total);
        const pageSize = Math.max(1, Number(data.page_size || 20));
        const currentPage = Math.max(1, Number(data.page || pageNumber));
        byId("task-list-count").textContent = `共 ${total} 条记录`;
        byId("task-list-body").innerHTML = items.length ? items.map((task) => {
          const batch = task.batch && typeof task.batch === "object" ? task.batch : {};
          const taskSelection = Object.assign({}, task.selection || {});
          if (!taskSelection.run_type && task.batch) taskSelection.run_type = "batch";
          if (!taskSelection.batch_type && batch.type) taskSelection.batch_type = batch.type;
          if (!taskSelection.selection_mode && batch.selection_mode) taskSelection.selection_mode = batch.selection_mode;
          const itemCount = Number(batch.item_count || taskSelection.item_count || batch.items && batch.items.length || 0);
          const queuePosition = task.queue_position;
          const batchCell = taskSelection.run_type === "batch"
            ? `<strong>${itemCount || "—"} 个子项</strong><small>${queuePosition === null || queuePosition === undefined ? "未在队列中" : `队列第 ${queuePosition} 位`}</small>`
            : '<span class="muted">—</span>';
          return `<tr><td><a class="text-link" href="${base}/tasks/${encodeURIComponent(task.id)}"><code>${escapeHtml(task.id)}</code></a></td><td>${escapeHtml(task.project && (task.project.display_name || task.project.project_id) || "—")}</td><td>${escapeHtml(String(task.runtime && task.runtime.target_env || "—").toUpperCase())}</td><td>${escapeHtml(selectionName(taskSelection))}</td><td><span class="batch-queue-cell">${batchCell}</span></td><td>${statusBadge(task.status)}</td><td>${escapeHtml(formatTime(task.created_at))}</td></tr>`;
        }).join("") : '<tr><td colspan="7" class="table-state">没有符合条件的任务。</td></tr>';
        pageCount = Math.max(1, Math.ceil(total / pageSize));
        byId("task-pagination").hidden = total <= pageSize;
        byId("task-page-label").textContent = `第 ${currentPage} / ${pageCount} 页`;
        byId("task-page-prev").disabled = currentPage <= 1;
        byId("task-page-next").disabled = currentPage >= pageCount;
      } catch (error) { byId("task-list-body").innerHTML = `<tr><td colspan="7" class="table-state error-text">${escapeHtml(error.message)}</td></tr>`; }
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
    function renderAttachments(record) {
      const attachments = Array.isArray(record.attachments) ? record.attachments : [];
      const section = byId("detail-attachments");
      if (!attachments.length) {
        section.hidden = true;
        return;
      }
      section.hidden = false;
      byId("detail-attachment-count").textContent = `${attachments.length} 张 · 随任务保留`;
      byId("detail-attachment-list").innerHTML = attachments.map((item, index) => `<li><span class="media-order">${Number(item.order || index + 1)}</span><span class="media-file-copy"><strong>${escapeHtml(item.original_name || `图片 ${index + 1}`)}</strong><small>${escapeHtml(item.content_type || "未知类型")} · ${escapeHtml(formatBytes(item.size_bytes))} · SHA-256 ${escapeHtml(String(item.sha256 || "").slice(0, 12) || "—")}</small></span><span class="retention-label">随任务保留</span></li>`).join("");
    }
    function renderRuntimeDifferences(record) {
      const snapshot = record.asset_snapshot;
      const section = byId("detail-runtime-overrides");
      if (!snapshot || !snapshot.asset_revision) {
        section.hidden = true;
        return;
      }
      section.hidden = false;
      byId("detail-asset-revision").textContent = snapshot.asset_revision;
      const differences = Array.isArray(snapshot.applied_overrides) ? snapshot.applied_overrides : [];
      byId("detail-runtime-body").innerHTML = differences.length
        ? differences.map((item) => `<tr><td><strong>${escapeHtml(item.label || item.key)}</strong><br><code>${escapeHtml(item.key)}</code></td><td>${escapeHtml(item.step_id || "当前 Case")}</td><td>${escapeHtml(formatRuntimeValue(item.base_value))}</td><td>${escapeHtml(formatRuntimeValue(item.resolved_value))}</td></tr>`).join("")
        : '<tr><td colspan="4" class="table-state">本任务使用 YAML 默认值，没有临时修改。</td></tr>';
    }
    function renderBatch(record) {
      const selection = record.selection || {};
      const batch = record.batch && typeof record.batch === "object" ? record.batch : null;
      const section = byId("detail-batch");
      if (selection.run_type !== "batch" && !batch) {
        section.hidden = true;
        return null;
      }
      section.hidden = false;
      const items = batch && Array.isArray(batch.items) ? batch.items : [];
      const count = Number(batch && batch.item_count || items.length || 0);
      const stats = {
        total: count,
        passed: items.filter((item) => ["passed", "succeeded"].includes(String(item.status || ""))).length,
        failed: items.filter((item) => ["failed", "error"].includes(String(item.status || ""))).length,
        skipped: items.filter((item) => String(item.status || "") === "skipped").length,
        // 锁定的五类摘要没有单独“已取消”；取消项同样未完成业务执行，
        // 因此并入“未执行”，保证五类数量之和始终等于总数。
        notRun: items.filter((item) => ["not_run", "cancelled"].includes(String(item.status || ""))).length,
      };
      byId("detail-batch-counts").textContent = `总数 ${stats.total} · 通过 ${stats.passed} · 失败 ${stats.failed} · 跳过 ${stats.skipped} · 未执行 ${stats.notRun}`;
      byId("detail-batch-summary").textContent = `${batch && batch.type === "flows" ? "Flows" : "Cases"} · ${selection.selection_mode === "all_safe" || batch && batch.selection_mode === "all_safe" ? "全部安全项" : "手动选择"} · ${count} 个子项`;
      const batchFilter = byId("detail-batch-filter").value;
      const visibleItems = batchFilter === "failed"
        ? items.filter((item) => isRetryableBatchFailure(item.status))
        : items;
      byId("detail-batch-body").innerHTML = visibleItems.length ? visibleItems.map((item) => {
        const duration = item.duration_ms === null || item.duration_ms === undefined
          ? item.duration : Number(item.duration_ms) / 1000;
        const identity = `${text(item.asset_type, batch && batch.type === "flows" ? "flow" : "case")} · ${text(item.asset_id)}`;
        return `<tr><td><strong>${escapeHtml(identity)}</strong><br><code>${escapeHtml(text(item.pytest_id, item.asset_revision || "—"))}</code></td><td><div class="safety-cell">${riskBadges(assetRiskTags(item))}</div></td><td>${statusBadge(item.status)}</td><td>${escapeHtml(formatDuration(duration))}</td><td>${escapeHtml(item.error_summary || "—")}</td></tr>`;
      }).join("") : `<tr><td colspan="5" class="table-state">${batchFilter === "failed" ? "当前批次没有失败或错误子项。" : "此批量任务尚未返回子项明细。"}</td></tr>`;
      return stats;
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
        // 批次顶层指标来自 batch.items，那里还包含 JUnit 无法表达的 not_run；
        // 普通单条任务继续使用 JUnit 汇总。
        if (!task || (task.selection || {}).run_type !== "batch") {
          byId("detail-metric-cases").textContent = `${passed} / ${total}`;
          byId("detail-metric-result").textContent = failed ? `${failed} 项失败` : "全部通过";
        }
        const cases = Array.isArray(result.cases) ? result.cases : [];
        const caseRows = cases.map((item) => `<tr><td><code>${escapeHtml(item.name)}</code><br><span class="muted">${escapeHtml(item.classname || "pytest")}</span></td><td>${statusBadge(item.status)}</td><td>${escapeHtml(formatDuration(item.duration))}</td><td>${escapeHtml(item.message || "—")}</td></tr>`).join("");
        body.innerHTML = `<tr><td><strong>执行汇总</strong></td><td>${statusBadge(failed ? "failed" : "succeeded", failed ? "存在失败" : "通过")}</td><td>—</td><td>${failed ? `${failed} 项失败` : "全部断言通过"}</td></tr>${caseRows}`;
      } catch (error) { body.innerHTML = `<tr><td colspan="4" class="table-state error-text">${escapeHtml(error.message)}</td></tr>`; }
    }
    async function loadLogs() {
      const tail = byId("detail-log-tail").value;
      try {
        const logs = await api(`/api/tasks/${encodeURIComponent(taskId)}/logs?tail=${encodeURIComponent(tail)}`);
        byId("detail-log-view").textContent = (Array.isArray(logs.lines) ? logs.lines : []).join("\n") || "暂无日志。";
        byId("detail-log-source").textContent = logs.source === "framework_log" ? `框架原始日志 · ${logs.log_file}` : logs.source === "console" ? "Console 原始日志" : "暂无日志产物";
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
      const selection = Object.assign({}, task.selection || {});
      if (!selection.run_type && task.batch) selection.run_type = "batch";
      if (!selection.batch_type && task.batch && task.batch.type) selection.batch_type = task.batch.type;
      if (!selection.selection_mode && task.batch && task.batch.selection_mode) selection.selection_mode = task.batch.selection_mode;
      if (project.project_id) rememberProject(project.project_id, [{ project_id: project.project_id, display_name: project.display_name }]);
      const taskStatus = task.status || "pending";
      byId("detail-status").className = `status-badge ${statusClass(taskStatus)}`;
      byId("detail-status").textContent = statusLabels[taskStatus] || taskStatus;
      byId("detail-subtitle").textContent = `${project.display_name || project.project_id} · ${selectionName(selection)}`;
      byId("detail-metric-status").textContent = statusLabels[taskStatus] || taskStatus;
      byId("detail-metric-time").textContent = formatTime(task.finished_at || task.created_at);
      byId("detail-metric-duration").textContent = formatDuration(taskDuration(task));
      setListValues("detail-snapshot", [project.display_name || project.project_id, text(runtime.platform_environment).toUpperCase(), text(runtime.target_env).toUpperCase(), runtime.runtime_scope_id, runtime.release_version ? `v${runtime.release_version} · ${runtime.release_id || "active"}` : runtime.release_id, profileLabel(runtime.credential_profiles), selectionName(selection), task.retry_of]);
      setListValues("detail-timeline", [formatTime(task.created_at), formatTime(task.started_at), formatTime(task.finished_at), task.exit_code === null || task.exit_code === undefined ? "—" : task.exit_code]);
      renderAttachments(task);
      renderRuntimeDifferences(task);
      const batchStats = renderBatch(task);
      const batchItems = task.batch && Array.isArray(task.batch.items) ? task.batch.items : [];
      if (selection.run_type === "batch") {
        const itemCount = Number(task.batch && task.batch.item_count || batchItems.length || 0);
        const passed = Number(batchStats && batchStats.passed || 0);
        byId("detail-metric-cases").textContent = `${passed} / ${itemCount}`;
        byId("detail-metric-result").textContent = batchStats
          ? `${batchStats.failed} 失败 · ${batchStats.skipped} 跳过 · ${batchStats.notRun} 未执行`
          : "批量子项";
      }
      const queueBadge = byId("detail-queue");
      queueBadge.hidden = task.queue_position === null || task.queue_position === undefined;
      if (!queueBadge.hidden) queueBadge.textContent = `队列第 ${task.queue_position} 位`;
      const errorNode = byId("detail-error");
      if (task.error_message) { setInlineStatus(errorNode, "error", task.error_message); }
      else errorNode.hidden = true;
      byId("task-cancel").disabled = terminalStatuses.has(taskStatus);
      const terminal = terminalStatuses.has(taskStatus);
      const supportsRetry = terminal && supportsRetrySchema(task.schema_version);
      byId("task-retry").disabled = !supportsRetry;
      byId("task-retry").textContent = selection.run_type === "batch" ? "重试全部" : "按原参数重试";
      const retryFailed = byId("task-retry-failed");
      const hasFailedBatchItems = batchItems.some((item) => isRetryableBatchFailure(item.status));
      retryFailed.hidden = !(supportsRetry && selection.run_type === "batch" && hasFailedBatchItems);
      retryFailed.disabled = retryFailed.hidden;
      const retryEdit = byId("task-retry-edit");
      const canEditRetry = terminal && supportsRetrySchema(task.schema_version) && ["single", "flow"].includes(selection.run_type);
      retryEdit.hidden = !canEditRetry;
      if (canEditRetry) retryEdit.href = `${base}/tasks/new?mode=${encodeURIComponent(selection.run_type)}&retry_from=${encodeURIComponent(taskId)}`;
      if (terminal) { if (timer) window.clearInterval(timer); timer = null; await Promise.all([loadResult(), loadReport()]); }
      return task;
    }
    byId("detail-log-refresh").addEventListener("click", loadLogs);
    byId("detail-log-tail").addEventListener("change", loadLogs);
    byId("detail-batch-filter").addEventListener("change", () => {
      if (task) renderBatch(task);
    });
    byId("task-cancel").addEventListener("click", async () => {
      byId("task-cancel").disabled = true;
      try { await api(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST", body: "{}" }); await loadTask(); }
      catch (error) { showGlobalError(error); byId("task-cancel").disabled = false; }
    });
    all("[data-retry-mode]", root).forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const retried = await api(`/api/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST", body: JSON.stringify({ mode: button.dataset.retryMode || "all" }) });
        window.location.assign(`${base}/tasks/${encodeURIComponent(retried.id)}`);
      } catch (error) {
        showGlobalError(error);
        button.disabled = false;
      }
    }));
    await Promise.all([loadTask(), loadLogs()]);
    if (task && !terminalStatuses.has(task.status)) timer = window.setInterval(() => Promise.all([loadTask(), loadLogs()]).catch(showGlobalError), 3000);
  }

  async function start() {
    activateNavigation();
    activateTabKeyboardNavigation();
    clearGlobalError();
    try {
      if (page === "overview") await initOverview();
      else if (page === "projects") await initProjects();
      else if (page === "task-new" || page === "task-single" || page === "task-flow" || page === "task-batch") await initTaskForm();
      else if (page === "catalog") await initCatalog();
      else if (page === "tasks") await initTasks();
      else if (page === "task-detail") await initTaskDetail();
    } catch (error) { showGlobalError(error); }
  }

  start();
}());
