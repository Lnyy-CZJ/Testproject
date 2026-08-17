/** API V2 契约、用例和执行预览工作台；所有写操作都携带版本与 CSRF。 */
(() => {
  const root = document.querySelector("[data-api-v2-workbench]");
  if (!root) return;
  const taskId = root.dataset.taskId;
  const base = document.body.dataset.basePath;
  const csrf = document.body.dataset.csrf;
  let contracts = null;
  let cases = null;
  let executionPreview = null;

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

  function showMessage(id, text, isError = false) {
    const node = document.querySelector(id);
    if (!node) return;
    node.textContent = text;
    node.className = `inline-message${isError ? " error" : ""}`;
  }

  function renderEvidence(contract) {
    const pane = document.querySelector("#contract-evidence");
    const issues = [...(contract.conflict_items || []), ...(contract.ambiguity_notes || []), ...(contract.unresolved || [])];
    pane.innerHTML = `<h3>契约事实</h3><label>名称<input id="contract-edit-name" value="${escapeHtml(contract.name)}"></label><label>方法<select id="contract-edit-method">${["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"].map((method) => `<option ${method === contract.method ? "selected" : ""}>${method}</option>`).join("")}</select></label><label>相对路径<input id="contract-edit-path" value="${escapeHtml(contract.path)}"></label><label>说明<textarea id="contract-edit-summary" rows="3">${escapeHtml(contract.summary || "")}</textarea></label><div class="compact-actions"><button class="primary-button" id="save-contract-edit" type="button">保存修改</button><button class="secondary-button" id="return-contract" type="button">退回候选</button><button class="danger-button" id="deprecate-contract" type="button">忽略接口</button></div><h4>字段证据</h4><ul class="evidence-list">${(contract.field_evidence || []).map((item) => `<li><code>${escapeHtml(item.field_path)}</code><span>${escapeHtml(item.source_pointer || item.source_type)}</span></li>`).join("") || "<li>暂无 Evidence</li>"}</ul><h4>冲突与未解决项</h4><ul class="evidence-list">${issues.map((item) => `<li><strong>${escapeHtml(item.code)}</strong><span>${escapeHtml(item.message)}</span></li>`).join("") || "<li>无阻断项</li>"}</ul>`;
    pane.querySelector("#save-contract-edit").addEventListener("click", () => reviewSingleContract(contract.contract_id, "edit", {name: pane.querySelector("#contract-edit-name").value, method: pane.querySelector("#contract-edit-method").value, path: pane.querySelector("#contract-edit-path").value, summary: pane.querySelector("#contract-edit-summary").value}));
    pane.querySelector("#return-contract").addEventListener("click", () => reviewSingleContract(contract.contract_id, "return"));
    pane.querySelector("#deprecate-contract").addEventListener("click", () => reviewSingleContract(contract.contract_id, "deprecate"));
  }

  async function reviewSingleContract(contractId, action, fields = undefined) {
    try {
      contracts = await api(`/api/v1/tasks/${taskId}/contracts/review`, {method: "PUT", body: JSON.stringify({base_version: contracts.version, changes: [{contract_id: contractId, action, fields, reason: "人工 Review"}]})});
      renderContracts(); showMessage("#contract-message", "契约 Review 已保存为新版本。");
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  }

  function renderContracts() {
    document.querySelector("#contract-version").textContent = `版本 ${contracts.version}`;
    const list = document.querySelector("#contract-list");
    list.innerHTML = contracts.items.map((item, index) => `<button class="contract-card" type="button" data-contract-index="${index}"><span class="method-chip">${escapeHtml(item.method)}</span><span><strong>${escapeHtml(item.name)}</strong><small class="contract-path">${escapeHtml(item.path)}</small></span><span class="issue-count">${escapeHtml(item.status)}<br>${(item.unresolved || []).length} 未解决</span></button>`).join("") || '<div class="skeleton-row">未解析到接口。</div>';
    list.querySelectorAll("[data-contract-index]").forEach((button) => button.addEventListener("click", () => {
      list.querySelectorAll("[aria-current]").forEach((item) => item.removeAttribute("aria-current"));
      button.setAttribute("aria-current", "true");
      renderEvidence(contracts.items[Number(button.dataset.contractIndex)]);
    }));
    list.querySelector("[data-contract-index]")?.click();
  }

  async function loadContracts() {
    try { contracts = await api(`/api/v1/tasks/${taskId}/contracts`); renderContracts(); }
    catch (error) { showMessage("#contract-message", error.message, error.code !== "ARTIFACT_NOT_READY"); }
  }

  async function loadCases() {
    try {
      cases = await api(`/api/v1/tasks/${taskId}/cases`);
      document.querySelector("#case-version").textContent = `版本 ${cases.version}`;
      renderCases();
    } catch (error) { showMessage("#case-message", error.message, false); }
  }

  function renderCases() {
    const search = document.querySelector("#case-search").value.toLowerCase();
    const risk = document.querySelector("#case-risk").value;
    const visible = cases.items.filter((item) => (!risk || item.risk_level === risk) && `${item.name} ${item.dimension} ${item.contract_id}`.toLowerCase().includes(search));
    document.querySelector("#case-list").innerHTML = visible.map((item) => `<tr><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.contract_id)}</small></td><td>${escapeHtml(item.dimension)}</td><td>${escapeHtml(item.source)}</td><td class="risk-${escapeHtml(item.risk_level)}">${escapeHtml(item.risk_level)}</td><td>${escapeHtml(item.status)}</td><td><button class="secondary-button" data-case-confirm="${escapeHtml(item.case_id)}" type="button">确认</button> <button class="danger-button" data-case-disable="${escapeHtml(item.case_id)}" type="button">禁用</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">没有符合筛选条件的用例。</td></tr>';
    document.querySelectorAll("[data-case-confirm]").forEach((button) => button.addEventListener("click", () => reviewSingleCase(button.dataset.caseConfirm, "confirm")));
    document.querySelectorAll("[data-case-disable]").forEach((button) => button.addEventListener("click", () => reviewSingleCase(button.dataset.caseDisable, "disable")));
  }

  async function reviewSingleCase(caseId, action) {
    try { cases = await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes: [{case_id: caseId, action, reason: "人工 Review"}]})}); renderCases(); showMessage("#case-message", "用例 Review 已保存为新版本。"); }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  }

  async function loadPreview() {
    try {
      const preview = await api(`/api/v1/tasks/${taskId}/execute/preview`);
      executionPreview = preview;
      document.querySelector("#preview-cards").innerHTML = `<div><span>可执行用例</span><strong>${preview.ready_case_ids.length}</strong></div><div><span>写请求</span><strong>${preview.write_case_count}</strong></div><div><span>高风险</span><strong>${preview.high_risk_count}</strong></div><div><span>脚本</span><strong>${preview.script_count}</strong></div>`;
      document.querySelector("#preview-blockers").innerHTML = `<strong>${preview.blocking_reasons.length ? "阻断原因" : "目标与授权"}</strong><p>${preview.blocking_reasons.length ? preview.blocking_reasons.map(escapeHtml).join(" · ") : `${escapeHtml(preview.target)} · 写请求 ${preview.write_case_count} 条 · 请核对后确认`}</p>`;
      document.querySelector("#confirm-execution").disabled = !preview.execution_enabled || preview.blocking_reasons.length > 0;
    } catch (error) { document.querySelector("#preview-blockers").innerHTML = `<strong>预览不可用</strong><p>${escapeHtml(error.message)}</p>`; }
  }

  document.querySelector("#confirm-execution")?.addEventListener("click", async () => {
    if (!executionPreview || !confirm(`确认向 ${executionPreview.target} 执行 ${executionPreview.ready_case_ids.length} 条用例，其中写请求 ${executionPreview.write_case_count} 条？`)) return;
    try {
      const run = await api(`/api/v1/tasks/${taskId}/execute`, {method: "POST", body: JSON.stringify({target_id: executionPreview.target_id, confirmation_sha256: executionPreview.confirmation_sha256})});
      showMessage("#execution-message", `Run ${run.run_id} 已完成，状态：${run.status}。`);
      await loadPreview();
    } catch (error) { showMessage("#execution-message", `${error.code}: ${error.message}`, true); }
  });

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
    try { cases = await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes: [{action: "add", fields}]})}); renderCases(); showMessage("#case-message", "人工用例已新增为候选版本。"); }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#create-draft")?.addEventListener("click", async () => {
    const caseIds = document.querySelector("#draft-case-ids").value.split(",").map((item) => item.trim()).filter(Boolean);
    try { await api(`/api/v1/tasks/${taskId}/defect-drafts`, {method: "POST", body: JSON.stringify({run_id: document.querySelector("#draft-run-id").value.trim(), case_ids: caseIds, manual_reason: document.querySelector("#draft-reason").value.trim()})}); await loadDrafts(); showMessage("#draft-message", "本地 Bug 草稿已生成。"); }
    catch (error) { showMessage("#draft-message", `${error.code}: ${error.message}`, true); }
  });

  function escapeHtml(value) { const node = document.createElement("span"); node.textContent = String(value ?? ""); return node.innerHTML; }
  loadContracts(); loadCases(); loadPreview(); loadDrafts();
})();
