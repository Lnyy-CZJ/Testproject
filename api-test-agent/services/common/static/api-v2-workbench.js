/** API V2 阶段工作台；写操作统一携带版本、确认摘要与 CSRF。 */
(() => {
  const root = document.querySelector("[data-api-v2-workbench]");
  if (!root) return;
  const taskId = root.dataset.taskId;
  const taskStatus = root.dataset.taskStatus;
  const taskStage = root.dataset.taskStage;
  const base = document.body.dataset.basePath;
  const csrf = document.body.dataset.csrf;
  let contracts = null;
  let cases = null;
  let executionPreview = null;
  let activeRunId = "";
  const selectedFailureIds = new Set();

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (!["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && typeof options.body === "string") headers.set("Content-Type", "application/json");
    const response = await fetch(`${base}${path}`, {...options, headers});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload?.error?.message || `请求失败 (${response.status})`);
      error.code = payload?.error?.code || "REQUEST_FAILED";
      throw error;
    }
    return payload;
  }

  function showMessage(selector, text, isError = false) {
    const node = document.querySelector(selector);
    if (!node) return;
    node.textContent = text;
    node.className = `inline-message${isError ? " error" : " success"}`;
  }

  function currentStageIndex() {
    if (["succeeded", "partial_success"].includes(taskStatus)) return 3;
    if (taskStatus === "waiting_execution_confirmation") return 2;
    if (taskStatus === "waiting_case_review") return 1;
    if (taskStatus === "waiting_contract_review") return 0;
    if (taskStatus === "failed") {
      if (/contract|document|parse/i.test(taskStage)) return 0;
      if (/case|coverage/i.test(taskStage) && !/executable/i.test(taskStage)) return 1;
      if (/executable|execution/i.test(taskStage)) return 2;
      return 3;
    }
    if (/case|coverage/i.test(taskStage)) return 1;
    if (/executable|execution/i.test(taskStage)) return 2;
    return 0;
  }

  let reachableStage = currentStageIndex();
  function showStage(index, focus = false) {
    if (index > reachableStage) return;
    document.querySelectorAll("[data-stage-panel]").forEach((panel) => { panel.hidden = Number(panel.dataset.stagePanel) !== index; });
    document.querySelectorAll("[data-stage-link]").forEach((link) => {
      const stage = Number(link.dataset.stageLink);
      link.classList.toggle("active", stage === index);
      link.classList.toggle("complete", stage < reachableStage);
      link.setAttribute("aria-disabled", stage > reachableStage ? "true" : "false");
      if (stage === index) link.setAttribute("aria-current", "step"); else link.removeAttribute("aria-current");
    });
    if (focus) document.querySelector(`[data-stage-panel="${index}"]`)?.focus({preventScroll: true});
  }

  document.querySelectorAll("[data-stage-link]").forEach((link) => link.addEventListener("click", (event) => {
    event.preventDefault();
    const stage = Number(link.dataset.stageLink);
    if (stage <= reachableStage) showStage(stage, true);
  }));
  showStage(reachableStage);

  function renderContractDetails(contract) {
    const editor = document.querySelector("#contract-editor");
    const evidence = document.querySelector("#contract-evidence");
    const issues = [...(contract.conflict_items || []), ...(contract.ambiguity_notes || []), ...(contract.unresolved || [])];
    editor.innerHTML = `<h3>契约字段</h3><label>名称<input id="contract-edit-name" value="${escapeHtml(contract.name)}"></label><label>方法<select id="contract-edit-method">${["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"].map((method) => `<option ${method === contract.method ? "selected" : ""}>${method}</option>`).join("")}</select></label><label>相对路径<input id="contract-edit-path" value="${escapeHtml(contract.path)}"></label><label>说明<textarea id="contract-edit-summary" rows="4">${escapeHtml(contract.summary || "")}</textarea></label><div class="compact-actions"><button class="primary-button" id="save-contract-edit" type="button">保存修改</button><button class="secondary-button" id="return-contract" type="button">退回候选</button><button class="danger-button" id="deprecate-contract" type="button">忽略接口</button></div>`;
    evidence.innerHTML = `<h3>Evidence 与质量门禁</h3><div class="quality-state ${issues.length ? "has-issues" : "ready"}"><strong>${issues.length ? `${issues.length} 个待处理项` : "关键事实具备证据"}</strong><span>${contractStatusLabel(contract.status)}</span></div><h4>字段证据</h4><ul class="evidence-list">${(contract.field_evidence || []).map((item) => `<li><code>${escapeHtml(item.field_path)}</code><span>${escapeHtml(item.source_pointer || item.source_type)}</span></li>`).join("") || "<li>暂无 Evidence</li>"}</ul><h4>冲突与未解决项</h4><ul class="evidence-list">${issues.map((item) => `<li><strong>${escapeHtml(item.code)}</strong><span>${escapeHtml(item.message)}</span></li>`).join("") || "<li>无阻断项</li>"}</ul>`;
    editor.querySelector("#save-contract-edit").addEventListener("click", () => reviewSingleContract(contract.contract_id, "edit", {name: editor.querySelector("#contract-edit-name").value, method: editor.querySelector("#contract-edit-method").value, path: editor.querySelector("#contract-edit-path").value, summary: editor.querySelector("#contract-edit-summary").value}));
    editor.querySelector("#return-contract").addEventListener("click", () => reviewSingleContract(contract.contract_id, "return"));
    editor.querySelector("#deprecate-contract").addEventListener("click", () => reviewSingleContract(contract.contract_id, "deprecate"));
  }

  function renderContracts() {
    document.querySelector("#contract-version").textContent = `版本 ${contracts.version}`;
    const counts = contracts.items.reduce((result, item) => ({...result, [item.status]: (result[item.status] || 0) + 1}), {});
    const unresolved = contracts.items.reduce((total, item) => total + (item.unresolved || []).length, 0);
    document.querySelector("#contract-overview").innerHTML = `<span><strong>${contracts.items.length}</strong> 个接口</span><span><strong>${counts.confirmed_candidate || 0}</strong> 待确认</span><span><strong>${counts.confirmed || 0}</strong> 已确认</span><span class="${unresolved ? "attention" : ""}"><strong>${unresolved}</strong> 未解决</span>`;
    const list = document.querySelector("#contract-list");
    list.innerHTML = contracts.items.map((item, index) => `<button class="contract-card" type="button" data-contract-index="${index}"><span class="method-chip">${escapeHtml(item.method)}</span><span><strong>${escapeHtml(item.name)}</strong><small class="contract-path">${escapeHtml(item.path)}</small></span><span class="issue-count">${contractStatusLabel(item.status)}<br>${(item.unresolved || []).length} 未解决</span></button>`).join("") || '<div class="skeleton-row">未解析到接口。</div>';
    list.querySelectorAll("[data-contract-index]").forEach((button) => button.addEventListener("click", () => {
      list.querySelectorAll("[aria-current]").forEach((item) => item.removeAttribute("aria-current"));
      button.setAttribute("aria-current", "true");
      renderContractDetails(contracts.items[Number(button.dataset.contractIndex)]);
    }));
    list.querySelector("[data-contract-index]")?.click();
  }

  async function loadContracts() {
    try { contracts = await api(`/api/v1/tasks/${taskId}/contracts`); renderContracts(); }
    catch (error) { showMessage("#contract-message", error.message, error.code !== "ARTIFACT_NOT_READY"); }
  }

  async function reviewSingleContract(contractId, action, fields = undefined) {
    try {
      contracts = await api(`/api/v1/tasks/${taskId}/contracts/review`, {method: "PUT", body: JSON.stringify({base_version: contracts.version, changes: [{contract_id: contractId, action, fields, reason: "人工 Review"}]})});
      renderContracts();
      showMessage("#contract-message", "契约 Review 已保存为新版本。");
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  }

  function renderCoverage() {
    const coverage = cases.coverage?.items || [];
    const covered = coverage.filter((item) => item.covered).length;
    document.querySelector("#coverage-matrix").innerHTML = `<div class="coverage-summary"><span><strong>${coverage.length}</strong> 个覆盖项</span><span><strong>${covered}</strong> 已覆盖</span><span class="${covered < coverage.length ? "attention" : ""}"><strong>${coverage.length - covered}</strong> 个缺口</span></div><div class="coverage-grid">${coverage.map((item) => `<div class="coverage-item"><span class="coverage-state ${item.covered ? "covered" : "gap"}">${item.covered ? "已覆盖" : "缺口"}</span><strong>${escapeHtml(item.dimension)}</strong><small>${escapeHtml(item.rule)}</small><span>${escapeHtml(item.decision_source)}</span></div>`).join("") || '<div class="skeleton-row">暂无覆盖矩阵。</div>'}</div>`;
  }

  function renderCases() {
    const search = document.querySelector("#case-search").value.toLowerCase();
    const risk = document.querySelector("#case-risk").value;
    const visible = cases.items.filter((item) => (!risk || item.risk_level === risk) && `${item.name} ${item.dimension} ${item.contract_id}`.toLowerCase().includes(search));
    document.querySelector("#case-list").innerHTML = visible.map((item) => `<tr><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.contract_id)}</small></td><td>${escapeHtml(item.dimension)}</td><td>${escapeHtml(item.source)}</td><td><span class="risk-label risk-${escapeHtml(item.risk_level)}">${riskLabel(item.risk_level)}</span></td><td>${contractStatusLabel(item.status)}</td><td><button class="secondary-button" data-case-confirm="${escapeHtml(item.case_id)}" type="button">确认</button> <button class="danger-button" data-case-disable="${escapeHtml(item.case_id)}" type="button">禁用</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">没有符合筛选条件的用例。</td></tr>';
    document.querySelectorAll("[data-case-confirm]").forEach((button) => button.addEventListener("click", () => reviewSingleCase(button.dataset.caseConfirm, "confirm")));
    document.querySelectorAll("[data-case-disable]").forEach((button) => button.addEventListener("click", () => reviewSingleCase(button.dataset.caseDisable, "disable")));
  }

  async function loadCases() {
    if (reachableStage < 1) return;
    try {
      cases = await api(`/api/v1/tasks/${taskId}/cases`);
      document.querySelector("#case-version").textContent = `版本 ${cases.version}`;
      renderCoverage();
      renderCases();
    } catch (error) {
      const waiting = ["ARTIFACT_NOT_READY", "CASE_NOT_GENERATED"].includes(error.code);
      showMessage("#case-message", waiting ? "契约确认后才能生成基础用例。" : `${error.code}: ${error.message}`, !waiting);
    }
  }

  async function reviewSingleCase(caseId, action) {
    try {
      cases = await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes: [{case_id: caseId, action, reason: "人工 Review"}]})});
      renderCoverage(); renderCases(); showMessage("#case-message", "用例 Review 已保存为新版本。");
    } catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  }

  async function loadPreview() {
    if (reachableStage < 2) return;
    try {
      executionPreview = await api(`/api/v1/tasks/${taskId}/execute/preview`);
      document.querySelector("#preview-cards").innerHTML = `<div><span>可执行用例</span><strong>${executionPreview.ready_case_ids.length}</strong></div><div><span>写请求</span><strong>${executionPreview.write_case_count}</strong></div><div><span>高风险</span><strong>${executionPreview.high_risk_count}</strong></div><div><span>脚本</span><strong>${executionPreview.script_count}</strong></div>`;
      document.querySelector("#preview-blockers").innerHTML = `<strong>${executionPreview.blocking_reasons.length ? "阻断原因" : "目标与授权"}</strong><p>${executionPreview.blocking_reasons.length ? executionPreview.blocking_reasons.map(escapeHtml).join(" · ") : `${escapeHtml(executionPreview.target)} · 写请求 ${executionPreview.write_case_count} 条 · 请核对后确认`}</p>`;
      document.querySelector("#confirm-execution").disabled = !executionPreview.execution_enabled || executionPreview.blocking_reasons.length > 0;
    } catch (error) { document.querySelector("#preview-blockers").innerHTML = `<strong>预览不可用</strong><p>${escapeHtml(error.message)}</p>`; }
  }

  function updateDraftSelection() {
    const button = document.querySelector("#create-draft");
    const summary = document.querySelector("#draft-selection");
    if (!button || !summary) return;
    button.disabled = !activeRunId || selectedFailureIds.size === 0;
    summary.textContent = selectedFailureIds.size ? `已从 ${activeRunId} 选择 ${selectedFailureIds.size} 条失败结果。` : "尚未选择失败用例。";
  }

  async function loadRun(runId) {
    try {
      const payload = await api(`/api/v1/tasks/${taskId}/runs/${runId}`);
      activeRunId = runId;
      selectedFailureIds.clear();
      document.querySelectorAll("[data-run-id]").forEach((item) => item.classList.toggle("active", item.dataset.runId === runId));
      const run = payload.run;
      const report = payload.report;
      const results = report?.case_results || [];
      const classifications = run.summary?.classifications || {};
      document.querySelector("#run-detail").innerHTML = `<div class="run-summary"><div><span>状态</span><strong>${runStatusLabel(run.status)}</strong></div><div><span>用例</span><strong>${run.summary?.total || 0}</strong></div><div><span>通过</span><strong>${run.summary?.passed || 0}</strong></div><div><span>失败</span><strong>${run.summary?.failed || 0}</strong></div></div><div class="classification-row">${Object.entries(classifications).map(([name, count]) => `<span>${failureLabel(name)} <strong>${count}</strong></span>`).join("") || "暂无失败分类"}</div><div class="result-list">${results.map((item) => { const failed = item.status !== "passed"; const performance = item.performance_evaluation; return `<article class="case-result ${failed ? "failed" : "passed"}"><div class="result-heading">${failed ? `<label class="result-select"><input type="checkbox" data-failed-case="${escapeHtml(item.case_id)}">选择</label>` : ""}<div><strong>${escapeHtml(item.case_id)}</strong><small>${failureLabel(item.failure_classification)} · ${item.duration_ms}ms</small></div><span class="status-pill status-${escapeHtml(item.status)}">${runStatusLabel(item.status)}</span></div>${performance ? `<p class="performance-note">阈值 ${performance.threshold_ms}ms（${thresholdLabel(performance.threshold_source)}）· ${performanceLabel(performance.status)} · ${escapeHtml(performance.basis)}</p>` : ""}<details><summary>查看脱敏请求与响应摘要</summary><pre>${escapeHtml(JSON.stringify({request: item.request_summary, response: item.response_summary}, null, 2))}</pre></details></article>`; }).join("") || '<div class="empty-state"><h3>结果尚未生成</h3><p>Run 终态后会在此展示脱敏报告。</p></div>'}</div><div class="run-actions">${["created","validating","provisioning","running","reporting"].includes(run.status) ? '<button class="danger-button" id="cancel-run" type="button">取消 Run</button>' : ""}${["failed","cancelled","timed_out"].includes(run.status) ? '<button class="secondary-button" id="retry-run" type="button">重试为新 Run</button>' : ""}</div>`;
      document.querySelectorAll("[data-failed-case]").forEach((checkbox) => checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedFailureIds.add(checkbox.dataset.failedCase); else selectedFailureIds.delete(checkbox.dataset.failedCase);
        updateDraftSelection();
      }));
      document.querySelector("#cancel-run")?.addEventListener("click", async () => { await api(`/api/v1/tasks/${taskId}/runs/${runId}/cancel`, {method: "POST"}); await loadRuns(); });
      document.querySelector("#retry-run")?.addEventListener("click", async () => { showMessage("#execution-message", "正在创建新的重试 Run…"); await api(`/api/v1/tasks/${taskId}/runs/${runId}/retry`, {method: "POST"}); await loadRuns(); });
      updateDraftSelection();
    } catch (error) { document.querySelector("#run-detail").innerHTML = `<div class="error-panel"><strong>${escapeHtml(error.code)}</strong><p>${escapeHtml(error.message)}</p></div>`; }
  }

  async function loadRuns(selectRunId = "") {
    try {
      const payload = await api(`/api/v1/tasks/${taskId}/runs`);
      if (payload.items.length) reachableStage = Math.max(reachableStage, 3);
      document.querySelectorAll("[data-stage-link]").forEach((link) => link.setAttribute("aria-disabled", Number(link.dataset.stageLink) > reachableStage ? "true" : "false"));
      document.querySelector("#latest-run-status").textContent = payload.items.length ? `${runStatusLabel(payload.items[0].status)} · ${payload.items[0].run_id}` : "尚无 Run";
      document.querySelector("#run-list").innerHTML = payload.items.map((item) => `<button type="button" class="run-item" data-run-id="${escapeHtml(item.run_id)}"><span><strong>${escapeHtml(item.run_id)}</strong><small>${formatDate(item.created_at)}</small></span><span class="status-pill status-${escapeHtml(item.status)}">${runStatusLabel(item.status)}</span><small>${item.passed_cases}/${item.total_cases} 通过</small></button>`).join("") || '<div class="empty-state"><h3>还没有执行记录</h3><p>完成执行确认后会生成独立 Run。</p></div>';
      document.querySelectorAll("[data-run-id]").forEach((button) => button.addEventListener("click", () => loadRun(button.dataset.runId)));
      const target = selectRunId || payload.latest_run_id;
      if (target) await loadRun(target);
    } catch (error) { document.querySelector("#run-list").innerHTML = `<div class="error-panel"><strong>${escapeHtml(error.code)}</strong><p>${escapeHtml(error.message)}</p></div>`; }
  }

  async function loadDrafts() {
    try {
      const payload = await api(`/api/v1/tasks/${taskId}/defect-drafts`);
      document.querySelector("#draft-list").innerHTML = payload.items.map((item) => `<div class="artifact-row"><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.draft_id)} · v${item.version} · ${escapeHtml(item.environment)}</small></div><div class="compact-actions"><button class="secondary-button" data-draft-edit="${escapeHtml(item.draft_id)}" data-version="${item.version}" type="button">编辑标题</button><a href="${base}/api/v1/tasks/${taskId}/defect-drafts/${item.draft_id}/download?format=json">JSON</a><a href="${base}/api/v1/tasks/${taskId}/defect-drafts/${item.draft_id}/download?format=markdown">Markdown</a></div></div>`).join("") || '<p class="muted">还没有本地 Bug 草稿。</p>';
      document.querySelectorAll("[data-draft-edit]").forEach((button) => button.addEventListener("click", async () => {
        const dialog = document.querySelector("#draft-edit-dialog");
        const titleInput = document.querySelector("#draft-edit-title");
        titleInput.value = button.closest(".artifact-row").querySelector("strong").textContent;
        dialog.showModal();
        const result = await new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue), {once: true}));
        if (result !== "confirm" || !titleInput.value.trim()) return;
        try { await api(`/api/v1/tasks/${taskId}/defect-drafts/${button.dataset.draftEdit}`, {method: "PUT", body: JSON.stringify({base_version: Number(button.dataset.version), fields: {title: titleInput.value.trim()}})}); await loadDrafts(); showMessage("#draft-message", "草稿已保存为新版本。"); }
        catch (error) { showMessage("#draft-message", `${error.code}: ${error.message}`, true); }
      }));
    } catch (error) { showMessage("#draft-message", error.message, true); }
  }

  document.querySelector("#confirm-execution")?.addEventListener("click", () => {
    if (!executionPreview) return;
    const dialog = document.querySelector("#execution-confirm-dialog");
    const risk = document.querySelector("#execution-risk-confirm");
    risk.checked = false;
    document.querySelector("#execution-dialog-submit").disabled = true;
    document.querySelector("#execution-confirm-summary").innerHTML = `<dl><div><dt>执行目标</dt><dd>${escapeHtml(executionPreview.target)}</dd></div><div><dt>可执行用例</dt><dd>${executionPreview.ready_case_ids.length}</dd></div><div><dt>写操作 / 高风险</dt><dd>${executionPreview.write_case_count} / ${executionPreview.high_risk_count}</dd></div><div><dt>确认 SHA</dt><dd><code>${escapeHtml(executionPreview.confirmation_sha256.slice(0, 16))}</code></dd></div></dl>`;
    dialog.showModal();
  });
  document.querySelector("#execution-risk-confirm")?.addEventListener("change", (event) => { document.querySelector("#execution-dialog-submit").disabled = !event.target.checked; });
  document.querySelector("#execution-confirm-dialog")?.addEventListener("close", async (event) => {
    if (event.target.returnValue !== "confirm" || !executionPreview) return;
    const button = document.querySelector("#confirm-execution");
    button.disabled = true;
    showMessage("#execution-message", "已提交受控执行，正在等待真实结果…");
    try {
      const run = await api(`/api/v1/tasks/${taskId}/execute`, {method: "POST", body: JSON.stringify({target_id: executionPreview.target_id, confirmation_sha256: executionPreview.confirmation_sha256})});
      reachableStage = 3; showStage(3); await loadRuns(run.run_id); await loadDrafts();
    } catch (error) { showMessage("#execution-message", `${error.code}: ${error.message}`, true); button.disabled = false; }
  });

  document.querySelector("#confirm-contracts")?.addEventListener("click", async () => {
    if (!contracts) return;
    const changes = contracts.items.filter((item) => item.status === "confirmed_candidate").map((item) => ({contract_id: item.contract_id, action: "confirm"}));
    try { contracts = await api(`/api/v1/tasks/${taskId}/contracts/review`, {method: "PUT", body: JSON.stringify({base_version: contracts.version, changes})}); renderContracts(); showMessage("#contract-message", `已确认 ${changes.length} 个候选契约。`); }
    catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#generate-cases")?.addEventListener("click", async () => { try { await api(`/api/v1/tasks/${taskId}/cases/generate`, {method: "POST"}); location.reload(); } catch (error) { showMessage("#contract-message", error.message, true); } });
  document.querySelector("#confirm-cases")?.addEventListener("click", async () => {
    if (!cases) return;
    const changes = cases.items.filter((item) => item.status === "confirmed_candidate" && item.risk_level !== "high").map((item) => ({case_id: item.case_id, action: "confirm"}));
    try { cases = await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes})}); renderCases(); showMessage("#case-message", `已确认 ${changes.length} 个普通候选用例。`); }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#generate-executable")?.addEventListener("click", async () => { try { await api(`/api/v1/tasks/${taskId}/executable-cases/generate`, {method: "POST"}); location.reload(); } catch (error) { showMessage("#case-message", error.message, true); } });
  document.querySelector("#case-search")?.addEventListener("input", () => cases && renderCases());
  document.querySelector("#case-risk")?.addEventListener("change", () => cases && renderCases());
  document.querySelector("#add-case")?.addEventListener("click", async () => {
    if (!cases || !contracts) return;
    const dialog = document.querySelector("#case-dialog");
    const contractSelect = document.querySelector("#new-case-contract");
    contractSelect.innerHTML = contracts.items.filter((item) => item.status === "confirmed").map((item) => `<option value="${escapeHtml(item.contract_id)}">${escapeHtml(item.method)} ${escapeHtml(item.path)}</option>`).join("");
    if (!contractSelect.value) { showMessage("#case-message", "没有已确认契约，不能新增用例。", true); return; }
    dialog.showModal();
    const result = await new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue), {once: true}));
    if (result !== "confirm") return;
    const fields = {contract_id: contractSelect.value, name: document.querySelector("#new-case-name").value, objective: document.querySelector("#new-case-objective").value, dimension: document.querySelector("#new-case-dimension").value, risk_level: document.querySelector("#new-case-risk").value};
    try { cases = await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes: [{action: "add", fields}]})}); renderCoverage(); renderCases(); showMessage("#case-message", "人工用例已新增为候选版本。"); }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#create-draft")?.addEventListener("click", async () => {
    try {
      await api(`/api/v1/tasks/${taskId}/defect-drafts`, {method: "POST", body: JSON.stringify({run_id: activeRunId, case_ids: [...selectedFailureIds], manual_reason: document.querySelector("#draft-reason").value.trim()})});
      selectedFailureIds.clear(); updateDraftSelection(); await loadDrafts(); showMessage("#draft-message", "本地 Bug 草稿已生成。");
    } catch (error) { showMessage("#draft-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#retry-stage")?.addEventListener("click", async () => {
    try { await api(`/api/v1/tasks/${taskId}/retry`, {method: "POST", body: JSON.stringify({stage: taskStage, source_versions: {}})}); location.reload(); }
    catch (error) { document.querySelector(".error-panel p").textContent = `${error.code}: ${error.message}`; }
  });

  function label(value, labels) { return escapeHtml(labels[value] || value || "未知"); }
  function contractStatusLabel(value) { return label(value, {draft: "草稿", confirmed_candidate: "候选待确认", confirmed: "已确认", disabled: "已禁用", deprecated: "已忽略"}); }
  function riskLabel(value) { return label(value, {low: "低", medium: "中", high: "高"}); }
  function runStatusLabel(value) { return label(value, {created: "已创建", validating: "校验中", provisioning: "准备中", running: "执行中", reporting: "生成报告", succeeded: "已完成", passed: "通过", failed: "失败", error: "错误", cancelled: "已取消", timed_out: "已超时", skipped: "已跳过"}); }
  function failureLabel(value) { return label(value, {product_defect_candidate: "接口缺陷候选", environment_blocked: "环境阻塞", test_data_issue: "测试数据问题", test_case_issue: "测试用例问题", performance_candidate: "性能候选", unknown: "待归因", none: "无"}); }
  function performanceLabel(value) { return label(value, {within_threshold: "阈值内", warning: "单次慢响应告警", performance_candidate: "连续慢响应候选", not_applicable: "不适用"}); }
  function thresholdLabel(value) { return label(value, {document: "文档 SLA", project: "项目配置", environment: "环境配置", default: "默认"}); }
  function formatDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? escapeHtml(value) : escapeHtml(date.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"})); }
  function escapeHtml(value) { const node = document.createElement("span"); node.textContent = String(value ?? ""); return node.innerHTML; }
  loadContracts(); loadCases(); loadPreview(); loadRuns(); loadDrafts();
})();
