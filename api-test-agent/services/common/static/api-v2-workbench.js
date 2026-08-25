/** 根据持久化任务状态恢复工作台阶段，避免刷新后回退到契约 Review。 */
function resolveApiV2Stage(status, stage, completedStages, hasRuns = false) {
  if (hasRuns) return 4;
  if (status === "waiting_contract_review") return 0;
  if (status === "waiting_case_review") return 1;
  if (status === "waiting_executable_review") return 2;
  if (status === "waiting_execution_confirmation") return 3;
  if (/reporting|run_report|defect/i.test(stage)) return 4;
  if (/execution_plan|execution_ready/i.test(stage)) return 3;
  if (/executable/i.test(stage)) return 2;
  if (/base_case|case_review|coverage/i.test(stage)) return 1;
  if (/contract|document|preflight|parse/i.test(stage)) return 0;
  if (completedStages.has("execution-plans")) return 3;
  if (completedStages.has("executable-cases")) return 2;
  if (completedStages.has("base-cases") || completedStages.has("coverage")) return 1;
  if (completedStages.has("contracts")) return 1;
  return 0;
}

if (typeof module !== "undefined" && module.exports) module.exports = {resolveApiV2Stage};

/** API V2 阶段工作台；写操作统一携带版本、确认摘要与 CSRF。 */
(() => {
  if (typeof document === "undefined") return;
  const root = document.querySelector("[data-api-v2-workbench]");
  if (!root) return;
  const taskId = root.dataset.taskId;
  const taskStatus = root.dataset.taskStatus;
  let currentTaskStatus = taskStatus;
  let currentTaskStage = root.dataset.taskStage;
  const completedStages = new Set((root.dataset.completedStages || "").split(",").filter(Boolean));
  const base = document.body.dataset.basePath;
  const csrf = document.body.dataset.csrf;
  const canContractReview = root.dataset.canContractReview === "true";
  const canCaseReview = root.dataset.canCaseReview === "true";
  const canExecutableReview = root.dataset.canExecutableReview === "true";
  let contracts = null;
  let cases = null;
  let documents = null;
  let activeDocument = null;
  let reviewIssues = null;
  let executableCases = null;
  let executionPlanEnvelope = null;
  let executionPreview = null;
  let activeRunId = "";
  const selectedFailureIds = new Set();
  let stageCursor = 0;
  let stageItems = [];
  let stageRefreshTimer = null;
  let contractRefreshTimer = null;
  let taskRefreshTimer = null;

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (!["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && typeof options.body === "string") headers.set("Content-Type", "application/json");
    const response = await fetch(`${base}${path}`, {...options, headers});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload?.error?.message || `请求失败 (${response.status})`);
      error.code = payload?.error?.code || "REQUEST_FAILED";
      error.requestId = payload?.error?.request_id || response.headers.get("X-Request-ID") || "";
      error.retryable = Boolean(payload?.error?.retryable);
      error.suggestedAction = payload?.error?.suggested_action || "";
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

  function normalizeCasePayload(payload) {
    const modern = payload && payload.base_cases && payload.coverage_matrix;
    const baseCases = modern ? payload.base_cases : payload;
    let coverage = modern ? payload.coverage_matrix : (payload?.coverage || {});
    // 一个发布周期内兼容旧版 coverage.items.items 信封，避免再次触发 filter/map 崩溃。
    if (!Array.isArray(coverage?.items) && Array.isArray(coverage?.items?.items)) {
      coverage = {...coverage, ...coverage.items, items: coverage.items.items};
    }
    if (!Array.isArray(baseCases?.items) || !Array.isArray(coverage?.items)) {
      const error = new Error("覆盖矩阵或基础用例响应中的 items 不是数组，请刷新或联系管理员。");
      error.code = "CASE_RESPONSE_SCHEMA_INVALID";
      throw error;
    }
    return {
      stage_state: payload.stage_state || "ready",
      version: Number(baseCases.version || 0),
      sha256: baseCases.sha256 || "",
      lifecycle_status: baseCases.lifecycle_status || "current",
      items: baseCases.items,
      coverage: {...coverage, items: coverage.items},
    };
  }

  function currentStageIndex() {
    return resolveApiV2Stage(currentTaskStatus, currentTaskStage, completedStages);
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

  async function refreshTaskState() {
    // 轮询控制平面的持久化状态，而不是依赖当前页面内存状态。这样无论刷新发生在
    // 队列、Workflow 生成还是执行期间，都能恢复到真实阶段并加载新版本产物。
    try {
      const task = await api(`/api/v1/tasks/${taskId}`);
      currentTaskStatus = task.status || currentTaskStatus;
      currentTaskStage = task.stage || currentTaskStage;
      (task.completed_stages || []).forEach((item) => completedStages.add(item));
      const statusNode = document.querySelector("#task-status");
      if (statusNode) {
        statusNode.textContent = label(currentTaskStatus, {pending: "排队中", running: "处理中", waiting_contract_review: "契约待确认", waiting_case_review: "用例待 Review", waiting_executable_review: "执行定义待 Review", waiting_execution_confirmation: "执行计划待确认", succeeded: "已完成", partial_success: "部分成功", failed: "失败", cancelled: "已取消"});
        statusNode.className = `status-pill status-${currentTaskStatus}`;
      }
      const nextStage = resolveApiV2Stage(currentTaskStatus, currentTaskStage, completedStages);
      if (nextStage > reachableStage) {
        reachableStage = nextStage;
        showStage(nextStage);
      }
      if (nextStage >= 1) await loadCases();
      if (nextStage >= 2) await loadExecutableCases();
      if (nextStage >= 3) await loadPreview();
      if (nextStage >= 4) await loadRuns();
    } catch (_error) {
      // 状态轮询失败不能覆盖各阶段已经展示的产物；详细错误仍可通过手动日志查看。
    } finally {
      clearTimeout(taskRefreshTimer);
      if (["pending", "running"].includes(currentTaskStatus)) {
        taskRefreshTimer = setTimeout(refreshTaskState, document.hidden ? 10000 : 2500);
      }
    }
  }

  function renderContractDetails(contract) {
    const editor = document.querySelector("#contract-editor");
    const evidence = document.querySelector("#contract-evidence");
    const issues = reviewIssues?.items?.filter((item) => item.contract_id === contract.contract_id) || [...(contract.conflict_items || []), ...(contract.ambiguity_notes || []), ...(contract.unresolved || [])];
    const activeIssueTotal = issues.filter((item) => ["open", "reopened", undefined].includes(item.status)).length;
    const contractDisabled = canContractReview ? "" : "disabled";
    editor.innerHTML = `<h3>契约字段</h3><label>名称<input id="contract-edit-name" value="${escapeHtml(contract.name)}" ${contractDisabled}></label><label>方法<select id="contract-edit-method" ${contractDisabled}>${["GET","POST","PUT","PATCH","DELETE","HEAD","OPTIONS"].map((method) => `<option ${method === contract.method ? "selected" : ""}>${method}</option>`).join("")}</select></label><label>相对路径<input id="contract-edit-path" value="${escapeHtml(contract.path)}" ${contractDisabled}></label><label>说明<textarea id="contract-edit-summary" rows="4" ${contractDisabled}>${escapeHtml(contract.summary || "")}</textarea></label><div class="compact-actions" ${canContractReview ? "" : "hidden"}><button class="primary-button" id="save-contract-edit" type="button">保存修改</button><button class="secondary-button" id="return-contract" type="button">退回候选</button><button class="danger-button" id="deprecate-contract" type="button">忽略接口</button></div>`;
    const fieldLabel = (path) => {
      const match = String(path || "").match(/^parameters\[(\d+)\]\.(.+)$/);
      if (match) {
        const parameter = (contract.parameters || [])[Number(match[1])] || {};
        const labels = {required: "是否必填", location: "参数位置", name: "参数名称", schema: "参数类型"};
        return `${parameter.location === "header" ? "请求头 " : "参数 "}${parameter.name || `#${Number(match[1]) + 1}`} ${labels[match[2]] || match[2]}`;
      }
      return {method: "请求方法", path: "接口路径", request_body: "请求体", responses: "响应定义", security: "鉴权方式"}[path] || path;
    };
    const sourceLabel = (item) => item.evidence_type === "inferred" ? "AI 推断" : ({openapi_node: "OpenAPI", source_quote: "文档明确", human_override: "人工确认"}[item.source_type] || "AI 推断");
    const grouped = {conflict: [], pending: [], suggestion: []};
    issues.forEach((item) => {
      const group = item.status === "accepted_as_suggestion" || item.code === "AI_SUGGESTION" ? "suggestion" : (/CONFLICT/.test(item.code) ? "conflict" : "pending");
      grouped[group].push(item);
    });
    const issueCard = (item) => {
      const open = ["open", "reopened", undefined].includes(item.status);
      const requiredField = String(item.field_path).endsWith(".required");
      const actions = canContractReview && open && item.issue_id ? `<div class="issue-card-actions">${requiredField ? `<button class="secondary-button" data-review-issue="${escapeHtml(item.issue_id)}" data-issue-action="human_override" data-issue-value="true" type="button">确认必填</button><button class="secondary-button" data-review-issue="${escapeHtml(item.issue_id)}" data-issue-action="human_override" data-issue-value="false" type="button">确认非必填</button>` : ""}<button class="secondary-button" data-review-issue="${escapeHtml(item.issue_id)}" data-issue-action="bind_evidence" type="button">关联原文</button><button class="secondary-button" data-review-issue="${escapeHtml(item.issue_id)}" data-issue-action="accept_as_suggestion" type="button">转为测试建议</button><button class="danger-button" data-review-issue="${escapeHtml(item.issue_id)}" data-issue-action="remove_inference" type="button">删除 AI 推断</button></div>` : "";
      return `<li class="issue-card"><strong>${escapeHtml(fieldLabel(item.field_path))}</strong><p>${escapeHtml(item.message)}</p><dl><div><dt>当前值</dt><dd>${escapeHtml(JSON.stringify(item.current_value))}</dd></div><div><dt>来源</dt><dd>${escapeHtml(item.source_pointer || "AI 推断")}</dd></div><div><dt>影响</dt><dd>${item.severity === "blocker" ? "未处理前不能确认契约或生成有效用例" : "建议在 Review 时确认"}</dd></div></dl>${actions}<details><summary>技术详情</summary><code>${escapeHtml(item.code)} · ${escapeHtml(item.field_path)} · ${escapeHtml(item.issue_id || "-")}</code></details></li>`;
    };
    const issueGroup = (title, items) => `<section class="issue-group"><h4>${title} <span>${items.length}</span></h4><ul class="evidence-list">${items.map(issueCard).join("") || `<li>没有${title}</li>`}</ul></section>`;
    const sourceDocumentVersion = Number(contracts.source_versions?.documents || 0);
    evidence.innerHTML = `<h3>文档依据与确认项</h3><div class="quality-state ${activeIssueTotal ? "has-issues" : "ready"}"><strong>${activeIssueTotal ? `${activeIssueTotal} 个待处理项` : "关键事实已通过依据校验"}</strong><span>${contractStatusLabel(contract.status)}</span></div><h4>文档依据</h4><ul class="evidence-list">${(contract.field_evidence || []).map((item) => { const stale = sourceDocumentVersion && item.document_version && Number(item.document_version) !== sourceDocumentVersion; return `<li class="${stale ? "evidence-stale" : ""}"><strong>${escapeHtml(fieldLabel(item.field_path))}</strong><span>${escapeHtml(sourceLabel(item))}${item.start_line ? ` · L${item.start_line}-${item.end_line || item.start_line}` : ""}${stale ? " · 旧文档版本" : ""}</span>${item.quote ? `<button class="text-button" data-evidence-line="${item.start_line || ""}" data-evidence-version="${item.document_version || ""}" type="button">查看原文</button>` : ""}<details><summary>技术详情</summary><code>${escapeHtml(item.field_path)} · ${escapeHtml(item.source_pointer || item.source_type)}</code></details></li>`; }).join("") || "<li>暂无可定位的文档依据</li>"}</ul>${issueGroup("字段冲突", grouped.conflict)}${issueGroup("文档待确认", grouped.pending)}${issueGroup("AI 建议", grouped.suggestion)}`;
    editor.querySelector("#save-contract-edit")?.addEventListener("click", () => reviewSingleContract(contract.contract_id, "edit", {name: editor.querySelector("#contract-edit-name").value, method: editor.querySelector("#contract-edit-method").value, path: editor.querySelector("#contract-edit-path").value, summary: editor.querySelector("#contract-edit-summary").value}));
    editor.querySelector("#return-contract")?.addEventListener("click", () => reviewSingleContract(contract.contract_id, "return"));
    editor.querySelector("#deprecate-contract")?.addEventListener("click", () => reviewSingleContract(contract.contract_id, "deprecate"));
    evidence.querySelectorAll("[data-review-issue]").forEach((button) => button.addEventListener("click", () => openIssueDialog(button.dataset.reviewIssue, button.dataset.issueAction, button.dataset.issueValue)));
    evidence.querySelectorAll("[data-evidence-line]").forEach((button) => button.addEventListener("click", async () => {
      document.querySelector("#document-workspace").hidden = false;
      if (!activeDocument) await loadDocuments();
      const version = Number(button.dataset.evidenceVersion || activeDocument.version);
      if (version !== activeDocument.version) await loadDocument(version);
      document.querySelector(`#document-line-${button.dataset.evidenceLine}`)?.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center"});
    }));
  }

  function renderContracts() {
    document.querySelector("#contract-version").textContent = `版本 ${contracts.version}`;
    const counts = contracts.items.reduce((result, item) => ({...result, [item.status]: (result[item.status] || 0) + 1}), {});
    const unresolved = contracts.items.reduce((total, item) => total + [...(item.unresolved || []), ...(item.conflict_items || []), ...(item.ambiguity_notes || [])].filter((issue) => ["open", "reopened", undefined].includes(issue.status)).length, 0);
    document.querySelector("#contract-overview").innerHTML = `<span><strong>${contracts.items.length}</strong> 个接口</span><span><strong>${counts.confirmed_candidate || 0}</strong> 待确认</span><span><strong>${counts.confirmed || 0}</strong> 已确认</span><span class="${unresolved ? "attention" : ""}"><strong>${unresolved}</strong> 未解决</span>`;
    const list = document.querySelector("#contract-list");
    list.innerHTML = contracts.items.map((item, index) => { const count = [...(item.unresolved || []), ...(item.conflict_items || []), ...(item.ambiguity_notes || [])].filter((issue) => ["open", "reopened", undefined].includes(issue.status)).length; return `<button class="contract-card" type="button" data-contract-index="${index}"><span class="method-chip">${escapeHtml(item.method)}</span><span><strong>${escapeHtml(item.name)}</strong><small class="contract-path">${escapeHtml(item.path)}</small></span><span class="issue-count">${contractStatusLabel(item.status)}<br>${count} 未解决</span></button>`; }).join("") || '<div class="skeleton-row">未解析到接口。</div>';
    list.querySelectorAll("[data-contract-index]").forEach((button) => button.addEventListener("click", () => {
      list.querySelectorAll("[aria-current]").forEach((item) => item.removeAttribute("aria-current"));
      button.setAttribute("aria-current", "true");
      renderContractDetails(contracts.items[Number(button.dataset.contractIndex)]);
    }));
    list.querySelector("[data-contract-index]")?.click();
  }

  async function loadContracts() {
    try {
      contracts = await api(`/api/v1/tasks/${taskId}/contracts`);
      currentTaskStatus = contracts.task_status || currentTaskStatus;
      if (["generating", "not_generated"].includes(contracts.stage_state)) {
        document.querySelector("#contract-editor").innerHTML = '<div class="empty-state"><h3>正在分析接口文档</h3><p>契约尚未生成，无需重复创建任务。阶段记录会自动更新当前节点。</p></div>';
        document.querySelector("#contract-evidence").innerHTML = '<div class="empty-state"><h3>等待文档依据</h3><p>解析完成后将在这里展示字段依据和待确认项。</p></div>';
        showMessage("#contract-message", "分析正在进行，契约生成后会自动打开 Review 工作区。");
        clearTimeout(contractRefreshTimer);
        contractRefreshTimer = setTimeout(loadContracts, document.hidden ? 10000 : 2500);
        return;
      }
      if (contracts.stage_state === "failed") {
        showMessage("#contract-message", "契约生成失败，请从失败阶段重试。", true);
        return;
      }
      clearTimeout(contractRefreshTimer);
      reviewIssues = await api(`/api/v1/tasks/${taskId}/review-issues`).catch(() => ({items: []}));
      renderContracts();
    }
    catch (error) { showMessage("#contract-message", error.message, error.code !== "ARTIFACT_NOT_READY"); }
  }

  async function reviewSingleContract(contractId, action, fields = undefined) {
    try {
      contracts = await api(`/api/v1/tasks/${taskId}/contracts/review`, {method: "PUT", body: JSON.stringify({base_version: contracts.version, changes: [{contract_id: contractId, action, fields, reason: "人工 Review"}]})});
      renderContracts();
      showMessage("#contract-message", "契约 Review 已保存为新版本。");
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  }

  async function loadDocument(version) {
    activeDocument = await api(`/api/v1/tasks/${taskId}/documents/${version}`);
    document.querySelector("#document-content").innerHTML = activeDocument.content.split("\n").map((line, index) => `<span class="document-line" id="document-line-${index + 1}"><b>${index + 1}</b>${escapeHtml(line) || " "}</span>`).join("");
    document.querySelector("#document-meta").textContent = `${activeDocument.document_format} · v${activeDocument.version} · ${activeDocument.source_filename} · SHA ${activeDocument.content_sha256.slice(0, 12)}`;
    document.querySelector("#document-revision-content").value = activeDocument.content;
    document.querySelector("#document-diff").hidden = true;
  }

  async function loadDocuments() {
    documents = await api(`/api/v1/tasks/${taskId}/documents`);
    const options = documents.items.map((item) => `<option value="${item.version}">v${item.version} · ${escapeHtml(item.change_reason || item.source_filename)}</option>`).join("");
    document.querySelector("#document-version").innerHTML = options;
    document.querySelector("#reanalyze-document-version").innerHTML = options;
    await loadDocument(documents.current_version);
  }

  function openIssueDialog(issueId, preferredAction = "bind_evidence", presetValue = undefined) {
    const issue = reviewIssues?.items?.find((item) => item.issue_id === issueId);
    if (!issue) return;
    const dialog = document.querySelector("#review-issue-dialog");
    dialog.dataset.issueId = issueId;
    document.querySelector("#review-issue-summary").innerHTML = `<strong>${escapeHtml(issue.code)} · ${escapeHtml(issue.field_path)}</strong><p>${escapeHtml(issue.message)}<br>当前值：${escapeHtml(JSON.stringify(issue.current_value))}</p>`;
    document.querySelector("#review-issue-value").value = presetValue ?? issue.current_value ?? "";
    document.querySelector("#review-issue-action").value = preferredAction;
    document.querySelector("#review-issue-reason").value = "";
    dialog.showModal();
  }

  document.querySelector("#review-issue-dialog")?.addEventListener("close", async (event) => {
    if (event.target.returnValue !== "confirm") return;
    const issueId = event.target.dataset.issueId;
    const action = document.querySelector("#review-issue-action").value;
    const ranges = document.querySelector("#review-issue-lines").value.split(",").map((value) => value.match(/^\s*(\d+)\s*-\s*(\d+)\s*$/)).filter(Boolean).map((match) => ({start_line: Number(match[1]), end_line: Number(match[2])}));
    const rawValue = document.querySelector("#review-issue-value").value;
    const payload = {value: rawValue === "true" ? true : (rawValue === "false" ? false : rawValue)};
    if (ranges.length && activeDocument) Object.assign(payload, {document_version: activeDocument.version, ranges});
    try {
      contracts = await api(`/api/v1/tasks/${taskId}/review-issues/${issueId}`, {method: "PUT", body: JSON.stringify({base_contract_version: contracts.version, action, reason: document.querySelector("#review-issue-reason").value.trim(), payload})});
      await loadContracts();
      showMessage("#contract-message", "问题已保存为新的契约版本，并重新执行质量门禁。");
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#review-issue-lines")?.addEventListener("input", (event) => {
    if (!activeDocument) return;
    const ranges = event.target.value.split(",").map((value) => value.match(/^\s*(\d+)\s*-\s*(\d+)\s*$/)).filter(Boolean);
    const lines = activeDocument.content.split("\n");
    const preview = ranges.map((match) => lines.slice(Number(match[1]) - 1, Number(match[2])).join("\n")).filter(Boolean).join("\n…\n");
    document.querySelector("#review-issue-preview").textContent = preview || "填写行号后预览所选原文。";
  });

  function renderCoverage() {
    const coverage = cases.coverage?.items || [];
    const covered = coverage.filter((item) => item.covered).length;
    const accepted = new Set(cases.coverage.accepted_gap_ids || []);
    const dimension = document.querySelector("#coverage-dimension")?.value.toLowerCase() || "";
    const status = document.querySelector("#coverage-status")?.value || "";
    const source = document.querySelector("#coverage-source")?.value || "";
    const visible = coverage.filter((item) => {
      const itemStatus = item.covered ? "covered" : (accepted.has(item.coverage_id) ? "accepted" : "gap");
      return (!dimension || `${item.dimension} ${item.contract_id}`.toLowerCase().includes(dimension)) && (!status || status === itemStatus) && (!source || source === item.decision_source);
    });
    const readOnly = !canCaseReview || cases.stage_state === "stale";
    document.querySelector("#coverage-matrix").innerHTML = `<div class="coverage-summary"><span><strong>${coverage.length}</strong> 个覆盖项</span><span><strong>${covered}</strong> 已覆盖</span><span class="${covered < coverage.length ? "attention" : ""}"><strong>${coverage.length - covered}</strong> 个缺口</span></div><div class="coverage-grid">${visible.map((item) => { const isAccepted = accepted.has(item.coverage_id); return `<div class="coverage-item"><span class="coverage-state ${item.covered ? "covered" : "gap"}">${item.covered ? "已覆盖" : (isAccepted ? "已接受" : "缺口")}</span><strong>${escapeHtml(item.dimension)}</strong><small>${escapeHtml(item.rule)}${item.gap_reason ? ` · ${escapeHtml(item.gap_reason)}` : ""}</small><span>${escapeHtml(item.decision_source)} · 第 ${cases.coverage.round_count || 0} 轮${!item.covered && !isAccepted && !readOnly ? ` <button class="secondary-button" data-accept-gap="${escapeHtml(item.coverage_id)}" type="button">接受缺口</button>` : ""}</span></div>`; }).join("") || '<div class="skeleton-row">暂无符合筛选条件的覆盖项。</div>'}</div>`;
    document.querySelectorAll("[data-accept-gap]").forEach((button) => button.addEventListener("click", () => {
      const dialog = document.querySelector("#coverage-gap-dialog");
      dialog.dataset.gapId = button.dataset.acceptGap;
      document.querySelector("#coverage-gap-summary").textContent = `覆盖项 ${button.dataset.acceptGap} 将保留为缺口，但标记为人工接受。`;
      document.querySelector("#coverage-gap-reason").value = "";
      dialog.showModal();
    }));
  }

  function renderCases() {
    const search = document.querySelector("#case-search").value.toLowerCase();
    const risk = document.querySelector("#case-risk").value;
    const visible = cases.items.filter((item) => (!risk || item.risk_level === risk) && `${item.name} ${item.dimension} ${item.contract_id}`.toLowerCase().includes(search));
    const readOnly = !canCaseReview || cases.stage_state === "stale" || cases.lifecycle_status === "stale";
    document.querySelector("#case-list").innerHTML = visible.map((item) => `<tr><td><button class="case-name-button" data-case-detail="${escapeHtml(item.case_id)}" type="button"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.contract_id)}</small></button></td><td>${escapeHtml(item.dimension)}</td><td>${escapeHtml(item.source)}<small>${escapeHtml(item.generation_kernel || "v2_minimal")}</small></td><td><span class="risk-label risk-${escapeHtml(item.risk_level)}">${riskLabel(item.risk_level)}</span></td><td>${contractStatusLabel(item.status)}</td><td><button class="secondary-button" data-case-confirm="${escapeHtml(item.case_id)}" type="button" ${readOnly ? "disabled" : ""}>确认</button> <button class="danger-button" data-case-disable="${escapeHtml(item.case_id)}" type="button" ${readOnly ? "disabled" : ""}>禁用</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">没有符合筛选条件的用例。</td></tr>';
    document.querySelectorAll("[data-case-detail]").forEach((button) => button.addEventListener("click", () => openCaseDetail(button.dataset.caseDetail)));
    document.querySelectorAll("[data-case-confirm]").forEach((button) => button.addEventListener("click", () => reviewSingleCase(button.dataset.caseConfirm, "confirm")));
    document.querySelectorAll("[data-case-disable]").forEach((button) => button.addEventListener("click", () => reviewSingleCase(button.dataset.caseDisable, "disable")));
  }

  function openCaseDetail(caseId) {
    const item = cases?.items?.find((value) => value.case_id === caseId);
    if (!item) return;
    const dialog = document.querySelector("#case-detail-dialog");
    document.querySelector("#case-detail-title").textContent = item.name;
    const quality = item.quality_report || {};
    document.querySelector("#case-detail-content").innerHTML = `<div class="case-detail-meta"><span>${escapeHtml(item.dimension)}</span><span>${riskLabel(item.risk_level)}风险</span><span>${escapeHtml(item.scenario_type || "normal")}</span><span>${escapeHtml(item.generation_kernel || "v2_minimal")}</span></div><section><h4>测试目标</h4><p>${escapeHtml(item.objective)}</p></section><section><h4>前置条件与依赖</h4><ul>${(item.preconditions || []).map((value) => `<li>${escapeHtml(value)}</li>`).join("") || "<li>无前置条件</li>"}${(item.dependencies || []).map((value) => `<li>依赖 ${escapeHtml(value.contract_id)} · 变量 ${escapeHtml(value.variable || "-")}</li>`).join("")}</ul></section><section><h4>执行步骤</h4><ol>${(item.steps || []).map((value) => `<li><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></li>`).join("") || "<li>尚未生成步骤</li>"}</ol></section><section><h4>参数变化</h4><ul>${(item.parameter_mutations || []).map((value) => `<li><code>${escapeHtml(value.field_path)}</code> · ${escapeHtml(value.strategy)} · ${escapeHtml(value.description || "")}</li>`).join("") || "<li>使用契约有效值</li>"}</ul></section><section><h4>预期结果 / 观察目标</h4><ul>${(item.expected_results || []).map((value) => `<li>${escapeHtml(value)}</li>`).join("") || "<li>无已确认预期</li>"}</ul></section><section><h4>文档依据与质量门禁</h4><p class="quality-state ${quality.hard_gate_passed ? "ready" : "has-issues"}">${quality.hard_gate_passed ? "依据校验已通过" : "依据校验未通过"} · 文档依据覆盖率 ${Math.round((quality.evidence_rate || 0) * 100)}%</p><ul>${(item.evidence_refs || []).map((value) => `<li><code>${escapeHtml(value.field_path)}</code> · ${escapeHtml(value.source_pointer)}${value.quote ? ` · ${escapeHtml(value.quote)}` : ""}</li>`).join("") || "<li>暂无文档依据</li>"}${(quality.blockers || []).map((value) => `<li><strong>${escapeHtml(value.code)}</strong> · ${escapeHtml(value.message)}</li>`).join("")}</ul></section><section><h4>生成来源</h4><p>${(item.generation_sources || []).map(escapeHtml).join(" · ") || escapeHtml(item.source)}</p><p><code>Prompt SHA ${escapeHtml((item.prompt_sha256 || "未调用模型").slice(0, 16))}</code></p></section>`;
    dialog.showModal();
  }

  async function loadStageRecords(reset = true) {
    if (reset === true) { stageCursor = 0; stageItems = []; }
    const params = new URLSearchParams();
    const attempt = document.querySelector("#attempt-filter")?.value || "";
    const stage = document.querySelector("#stage-event-filter")?.value || "";
    const level = document.querySelector("#stage-level-filter")?.value || "";
    if (attempt) params.set("attempt_id", attempt);
    if (stage) params.set("stage", stage);
    if (level) params.set("level", level);
    params.set("cursor", String(stageCursor));
    params.set("limit", "100");
    const suffix = `?${params.toString()}`;
    const attemptSuffix = attempt ? `?attempt_id=${encodeURIComponent(attempt)}` : "";
    try {
      const [events, usage, provenance, statistics] = await Promise.all([
        api(`/api/v1/tasks/${taskId}/stage-events${suffix}`),
        api(`/api/v1/tasks/${taskId}/model-usage${attemptSuffix}`),
        api(`/api/v1/tasks/${taskId}/generation-provenance${attemptSuffix}`),
        api(`/api/v1/tasks/${taskId}/usage/summary?group_by=${encodeURIComponent(document.querySelector("#usage-group")?.value || "attempt")}`),
      ]);
      stageItems.push(...(events.items || []));
      stageCursor = events.next_cursor ?? stageItems.length;
      document.querySelector("#stage-event-list").innerHTML = stageItems.map((item) => `<li class="stage-event stage-event-${escapeHtml(item.status)}"><span class="stage-event-dot" aria-hidden="true"></span><div><strong>${escapeHtml(item.node)}</strong><small>${escapeHtml(item.stage)} · ${escapeHtml(item.level || "info")} · ${formatDate(item.created_at)}${item.duration_ms !== null && item.duration_ms !== undefined ? ` · ${item.duration_ms}ms` : ""}</small><p>${escapeHtml(item.message)}</p>${item.error_code ? `<code>${escapeHtml(item.error_code)}</code>` : ""}</div><span class="status-pill status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></li>`).join("") || '<li class="empty-state"><h3>暂无阶段记录</h3><p>历史任务可能没有事件；重新生成后会从当前 Attempt 开始记录。</p></li>';
      const summary = usage.summary || {};
      const unreported = (usage.items || []).filter((item) => !item.reported).length;
      document.querySelector("#model-usage-summary").innerHTML = `<div><span>模型调用</span><strong>${summary.call_count || 0}</strong></div><div><span>输入 Token</span><strong>${summary.input_tokens || 0}</strong></div><div><span>输出 Token</span><strong>${summary.output_tokens || 0}</strong></div><div><span>总 Token</span><strong>${summary.total_tokens || 0}</strong></div><div><span>Token 未报告</span><strong>${unreported}</strong></div>`;
      document.querySelector("#model-usage-list").innerHTML = (usage.items || []).map((item) => `<tr><td><strong>${escapeHtml(item.stage)}</strong><small>${escapeHtml(item.prompt_id)}</small></td><td>${escapeHtml(item.model_name)}</td><td>${item.reported ? item.input_tokens : "未报告"}</td><td>${item.reported ? item.output_tokens : "未报告"}</td><td>${item.reported ? item.total_tokens : "未报告"}</td><td>${item.duration_ms}ms</td><td>${escapeHtml(item.status)}${item.retry_number ? ` · 重试 ${item.retry_number}` : ""}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">当前 Attempt 没有模型调用记录。</td></tr>';
      document.querySelector("#generation-provenance").innerHTML = `<strong>生成来源 · ${escapeHtml(provenance.generation_kernel || "v2_minimal")}</strong><p>Attempt ${escapeHtml(provenance.attempt_id || "-")} · 契约 ${(provenance.contract_ids || []).length} 个 · Prompt ${(provenance.prompt_ids || []).map(escapeHtml).join("、") || "未调用模型"}${unreported ? ` · ${unreported} 次调用 Token 未报告` : ""}</p><p>确定性 ${provenance.deterministic_case_count || 0} 条 · AI ${provenance.llm_case_count || 0} 条 · 拒绝 ${provenance.rejected_case_count || 0} 条 · ${escapeHtml(provenance.ai_supplement_status || "历史版本未记录")}</p>${(provenance.rejections || []).length ? `<details><summary>查看拒绝原因</summary><ul>${provenance.rejections.map((item) => `<li>${escapeHtml(item.contract_id)} · ${escapeHtml(item.error_code)} · ${escapeHtml(item.field_path || item.rejection_stage)} · ${escapeHtml(item.suggestion)}</li>`).join("")}</ul></details>` : ""}`;
      const attemptSelect = document.querySelector("#attempt-filter");
      const selectedAttempt = attemptSelect.value;
      const attempts = statistics.available_attempts || [];
      attemptSelect.innerHTML = '<option value="">当前 Attempt</option>' + attempts.map((item) => `<option value="${escapeHtml(item.attempt_id)}">${escapeHtml(item.stage || "阶段")} · ${escapeHtml(item.attempt_id)}</option>`).join("");
      attemptSelect.value = selectedAttempt;
      document.querySelector("#usage-group-summary").innerHTML = `<div class="summary-grid">${(statistics.groups || []).map((item) => `<div><span>${escapeHtml(item.key)}</span><strong>${item.total_tokens} Token</strong><small>${item.call_count} 次调用 · 平均 ${item.average_duration_ms}ms</small></div>`).join("") || '<div><span>调用统计</span><strong>暂无记录</strong></div>'}</div><p class="muted">${statistics.usage_reliable ? "供应商用量已完整报告" : "包含 Token 未报告调用"} · 未配置模型价格，不估算金额成本。</p>`;
    } catch (error) {
      document.querySelector("#stage-event-list").innerHTML = `<li class="empty-state"><h3>${escapeHtml(error.code)}</h3><p>${escapeHtml(error.message)}</p></li>`;
      document.querySelector("#model-usage-summary").innerHTML = '<div><span>模型调用</span><strong>暂无记录</strong></div>';
    } finally {
      clearTimeout(stageRefreshTimer);
      if (["pending", "running"].includes(currentTaskStatus)) {
        stageRefreshTimer = setTimeout(() => loadStageRecords(false), document.hidden ? 10000 : 2500);
      }
    }
  }

  async function loadCases() {
    if (reachableStage < 1) return;
    try {
      cases = normalizeCasePayload(await api(`/api/v1/tasks/${taskId}/cases`));
      document.querySelector("#case-version").textContent = `版本 ${cases.version}`;
      const stageMessages = {
        blocked: "契约确认后才能生成基础用例。",
        not_generated: "基础用例尚未生成。",
        generating: "基础用例正在生成，已完成的契约仍可查看。",
        failed: "用例生成失败，可从失败阶段重试；上游产物未受影响。",
        stale: "当前用例基于旧契约，仅供查看。请基于最新契约重新生成。",
      };
      if (stageMessages[cases.stage_state]) showMessage("#case-message", stageMessages[cases.stage_state], cases.stage_state === "failed");
      document.querySelector("#generate-executable").disabled = ["blocked", "not_generated", "generating", "failed", "stale"].includes(cases.stage_state);
      renderCoverage();
      renderCases();
    } catch (error) {
      const suffix = error.requestId ? ` · 请求 ID ${error.requestId}` : "";
      showMessage("#case-message", `${error.code}: ${error.message}${suffix}`, true);
    }
  }

  async function reviewSingleCase(caseId, action) {
    try {
      cases = normalizeCasePayload(await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes: [{case_id: caseId, action, reason: "人工 Review"}]})}));
      renderCoverage(); renderCases(); showMessage("#case-message", "用例 Review 已保存为新版本。");
    } catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  }

  function renderExecutableDetail(item) {
    const request = item.request || {};
    const detail = document.querySelector("#executable-detail");
    detail.innerHTML = `<div class="section-heading"><div><p class="eyebrow">EXECUTABLE CASE</p><h3>${escapeHtml(item.name)}</h3><p><code>${escapeHtml(request.method)} ${escapeHtml(request.path)}</code></p></div><span class="status-pill status-${escapeHtml(item.validation_status)}">${escapeHtml(item.review_status || "confirmed_candidate")}</span></div><section><h4>完整请求</h4><dl class="request-definition"><div><dt>Header</dt><dd><pre>${escapeHtml(JSON.stringify(request.headers || {}, null, 2))}</pre></dd></div><div><dt>Query</dt><dd><pre>${escapeHtml(JSON.stringify(request.query || {}, null, 2))}</pre></dd></div><div><dt>Cookie</dt><dd><pre>${escapeHtml(JSON.stringify(request.cookies || {}, null, 2))}</pre></dd></div><div><dt>Body</dt><dd><pre>${escapeHtml(JSON.stringify(request.body ?? null, null, 2))}</pre></dd></div></dl></section><section><h4>依赖与变量</h4><p>前置节点：${(item.precondition_case_ids || []).map(escapeHtml).join("、") || "无"}</p><pre>${escapeHtml(JSON.stringify({producers: item.variable_producers || [], consumers: item.variable_consumers || [], data_refs: item.data_refs || []}, null, 2))}</pre></section><section><h4>断言 / 观察目标</h4><pre>${escapeHtml(JSON.stringify({assertions: item.assertions || [], observation_targets: item.observation_targets || []}, null, 2))}</pre></section><section><h4>静态校验</h4><p class="quality-state ${item.validation_status === "ready" ? "ready" : "has-issues"}">${item.validation_status === "ready" ? "静态校验通过" : "当前定义不可执行"}</p><ul>${(item.validation_issues || []).map((issue) => `<li><strong>${escapeHtml(issue.code)}</strong> · ${escapeHtml(issue.field_path || "-")} · ${escapeHtml(issue.message)}</li>`).join("") || "<li>没有阻断项</li>"}</ul></section><details><summary>Workflow 与 Prompt 来源</summary><p>${escapeHtml(item.generation_kernel || "历史版本未记录")} · ${(item.generation_sources || []).map(escapeHtml).join("、") || "未记录"}</p><code>${escapeHtml((item.prompt_sha256 || "未调用模型").slice(0, 16))}</code></details><div class="compact-actions" ${canExecutableReview ? "" : "hidden"}><button class="primary-button" data-executable-confirm="${escapeHtml(item.executable_case_id)}" type="button" ${item.validation_status !== "ready" || item.review_status === "confirmed" ? "disabled" : ""}>确认执行定义</button><button class="danger-button" data-executable-disable="${escapeHtml(item.executable_case_id)}" type="button">禁用</button></div>`;
    detail.querySelector("[data-executable-confirm]")?.addEventListener("click", () => reviewExecutable(item.executable_case_id, "confirm"));
    detail.querySelector("[data-executable-disable]")?.addEventListener("click", () => reviewExecutable(item.executable_case_id, "disable"));
  }

  function renderExecutableCases() {
    const items = executableCases?.items || [];
    const confirmed = items.filter((item) => item.review_status === "confirmed").length;
    const ready = items.filter((item) => item.validation_status === "ready" && item.enabled).length;
    const disabled = items.length - ready;
    document.querySelector("#executable-version").textContent = executableCases?.version ? `版本 ${executableCases.version}` : "尚未生成";
    document.querySelector("#executable-overview").innerHTML = `<div><span>执行定义</span><strong>${items.length}</strong></div><div><span>静态就绪</span><strong>${ready}</strong></div><div><span>已确认</span><strong>${confirmed}</strong></div><div><span>禁用 / 阻断</span><strong>${disabled}</strong></div>`;
    document.querySelector("#executable-list").innerHTML = items.map((item, index) => `<button class="contract-card" type="button" data-executable-index="${index}"><span class="method-chip">${escapeHtml(item.request?.method || "-")}</span><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.request?.path || "-")}</small></span><span class="issue-count">${escapeHtml(item.review_status || "候选")}<br>${escapeHtml(item.validation_status)}</span></button>`).join("") || '<div class="empty-state"><h3>执行定义尚未生成</h3><p>确认基础用例后，点击“确认并生成执行定义”。</p></div>';
    document.querySelectorAll("[data-executable-index]").forEach((button) => button.addEventListener("click", () => renderExecutableDetail(items[Number(button.dataset.executableIndex)])));
    document.querySelector("[data-executable-index]")?.click();
    const allReadyConfirmed = ready > 0 && items.filter((item) => item.validation_status === "ready" && item.enabled).every((item) => item.review_status === "confirmed");
    document.querySelector("#open-plan-stage").disabled = !allReadyConfirmed;
  }

  async function loadExecutableCases() {
    if (reachableStage < 2) return;
    try {
      executableCases = await api(`/api/v1/tasks/${taskId}/executable-cases`);
      renderExecutableCases();
      if (["not_generated", "generating"].includes(executableCases.stage_state)) {
        showMessage("#executable-message", executableCases.stage_state === "generating" ? "执行定义正在由核心 Workflow 生成，完成后会自动显示。" : "执行定义尚未生成。");
      } else if (["failed", "stale"].includes(executableCases.stage_state)) {
        showMessage("#executable-message", executableCases.stage_state === "stale" ? "执行定义已过期，请基于最新基础用例重新生成。" : "执行定义生成失败，请从失败阶段重试。", true);
      }
    } catch (error) { showMessage("#executable-message", `${error.code}: ${error.message}`, true); }
  }

  async function reviewExecutable(executableCaseId, action) {
    try {
      executableCases = await api(`/api/v1/tasks/${taskId}/executable-cases/review`, {method: "PUT", body: JSON.stringify({base_version: executableCases.version, changes: [{executable_case_id: executableCaseId, action, reason: "人工核对完整请求和静态校验"}]})});
      renderExecutableCases();
      showMessage("#executable-message", "执行定义 Review 已保存为新版本。");
    } catch (error) { showMessage("#executable-message", `${error.code}: ${error.message}`, true); }
  }

  function renderExecutionPlan(envelope) {
    const plan = envelope?.items || envelope?.plan || null;
    const blockers = envelope?.blockers || [];
    if (!plan) {
      document.querySelector("#preview-cards").innerHTML = "";
      document.querySelector("#preview-blockers").innerHTML = `<strong>计划阻断项</strong><p>${blockers.map((item) => `${escapeHtml(item.code)} · ${escapeHtml(item.field_path)} · ${escapeHtml(item.message || item.detail || "需要修复后重试")}`).join("<br>") || "执行计划尚未生成"}</p>`;
      document.querySelector("#confirm-execution-plan").disabled = true;
      document.querySelector("#confirm-execution").disabled = true;
      return;
    }
    executionPlanEnvelope = envelope.items ? envelope : {items: plan, version: envelope.version || 0};
    document.querySelector("#preview-cards").innerHTML = `<div><span>计划节点</span><strong>${plan.node_count ?? plan.nodes?.length ?? 0}</strong></div><div><span>依赖边</span><strong>${plan.edge_count ?? plan.edges?.length ?? 0}</strong></div><div><span>写请求</span><strong>${plan.write_operation_count || 0}</strong></div><div><span>高风险</span><strong>${plan.high_risk_count || 0}</strong></div>`;
    document.querySelector("#preview-blockers").innerHTML = `<strong>${blockers.length ? "计划阻断项" : `计划状态 · ${escapeHtml(plan.status || envelope.stage_state || "ready")}`}</strong><p>${blockers.length ? blockers.map((item) => `${escapeHtml(item.code)} · ${escapeHtml(item.field_path)} · ${escapeHtml(item.detail)}`).join("<br>") : `${escapeHtml(plan.target_id)} · SHA ${escapeHtml((plan.confirmation_sha256 || "").slice(0, 16))}`}</p>`;
    const edges = plan.edges || [];
    document.querySelector("#plan-topology").innerHTML = `<div class="plan-order"><h3>稳定拓扑顺序</h3><ol>${(plan.topological_order || []).map((node) => `<li><code>${escapeHtml(node)}</code></li>`).join("") || "<li>无可执行节点</li>"}</ol></div><div class="plan-edges"><h3>依赖与变量流</h3><ul>${edges.map((edge) => `<li><code>${escapeHtml(edge.from_node_id || edge.from_node || edge.source)}</code> → <code>${escapeHtml(edge.to_node_id || edge.to_node || edge.target)}</code><small>${escapeHtml(edge.reason || edge.edge_type || "依赖")}${edge.reference ? ` · ${escapeHtml(edge.reference)}` : ""}</small></li>`).join("") || "<li>节点间没有依赖边</li>"}</ul></div>`;
    document.querySelector("#confirm-execution-plan").disabled = blockers.length > 0 || plan.status === "confirmed" || !executionPlanEnvelope.version;
    document.querySelector("#confirm-execution").disabled = plan.status !== "confirmed" || !executionPreview?.execution_enabled;
  }

  async function loadPreview() {
    if (reachableStage < 3) return;
    try {
      executionPreview = await api(`/api/v1/tasks/${taskId}/execute/preview`);
      if (executionPreview.plan_id) {
        const envelope = await api(`/api/v1/tasks/${taskId}/execution-plans/${executionPreview.plan_id}`);
        renderExecutionPlan(envelope);
      } else {
        document.querySelector("#preview-cards").innerHTML = `<div><span>可执行用例</span><strong>${executionPreview.ready_case_ids?.length || 0}</strong></div><div><span>写请求</span><strong>${executionPreview.write_case_count || 0}</strong></div><div><span>高风险</span><strong>${executionPreview.high_risk_count || 0}</strong></div><div><span>目标</span><strong>${escapeHtml(executionPreview.target || "未登记")}</strong></div>`;
        document.querySelector("#preview-blockers").innerHTML = `<strong>尚未保存执行计划</strong><p>${(executionPreview.blocking_reasons || []).map(escapeHtml).join(" · ") || "请编译依赖拓扑后保存计划。"}</p>`;
      }
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
      const stepsPayload = await api(`/api/v1/tasks/${taskId}/runs/${runId}/steps`).catch(() => ({items: []}));
      activeRunId = runId;
      selectedFailureIds.clear();
      document.querySelectorAll("[data-run-id]").forEach((item) => item.classList.toggle("active", item.dataset.runId === runId));
      const run = payload.run;
      const report = payload.report;
      const results = report?.case_results || [];
      const classifications = run.summary?.classifications || {};
      const steps = stepsPayload.items || [];
      document.querySelector("#run-detail").innerHTML = `<div class="run-summary"><div><span>状态</span><strong>${runStatusLabel(run.status)}</strong></div><div><span>用例</span><strong>${run.summary?.total || 0}</strong></div><div><span>通过</span><strong>${run.summary?.passed || 0}</strong></div><div><span>失败</span><strong>${run.summary?.failed || 0}</strong></div></div><div class="classification-row">${Object.entries(classifications).map(([name, count]) => `<span>${failureLabel(name)} <strong>${count}</strong></span>`).join("") || "暂无失败分类"}</div>${steps.length ? `<section class="step-result-section"><h3>依赖步骤结果</h3><ol class="step-result-list">${steps.map((item) => `<li class="step-result step-${escapeHtml(item.status)}"><div><strong>${escapeHtml(item.node_id || item.case_id)}</strong><small>${runStatusLabel(item.status)} · ${item.duration_ms || 0}ms${item.blocked_by?.length ? ` · 被 ${item.blocked_by.map(escapeHtml).join("、")} 阻断` : ""}</small></div><details><summary>查看脱敏节点摘要</summary><pre>${escapeHtml(JSON.stringify({request: item.request_summary, response: item.response_summary, assertions: item.assertion_results, extracted_variables: item.extracted_variables}, null, 2))}</pre></details></li>`).join("")}</ol></section>` : ""}<div class="result-list">${results.map((item) => { const failed = item.status !== "passed"; const performance = item.performance_evaluation; return `<article class="case-result ${failed ? "failed" : "passed"}"><div class="result-heading">${failed ? `<label class="result-select"><input type="checkbox" data-failed-case="${escapeHtml(item.case_id)}">选择</label>` : ""}<div><strong>${escapeHtml(item.case_id)}</strong><small>${failureLabel(item.failure_classification)} · ${item.duration_ms}ms</small></div><span class="status-pill status-${escapeHtml(item.status)}">${runStatusLabel(item.status)}</span></div>${performance ? `<p class="performance-note">阈值 ${performance.threshold_ms}ms（${thresholdLabel(performance.threshold_source)}）· ${performanceLabel(performance.status)} · ${escapeHtml(performance.basis)}</p>` : ""}<details><summary>查看脱敏请求与响应摘要</summary><pre>${escapeHtml(JSON.stringify({request: item.request_summary, response: item.response_summary}, null, 2))}</pre></details></article>`; }).join("") || '<div class="empty-state"><h3>结果尚未生成</h3><p>Run 终态后会在此展示脱敏报告。</p></div>'}</div><div class="run-actions">${["created","validating","provisioning","running","reporting"].includes(run.status) ? '<button class="danger-button" id="cancel-run" type="button">取消 Run</button>' : ""}${["failed","cancelled","timed_out"].includes(run.status) ? '<button class="secondary-button" id="retry-run" type="button">重试为新 Run</button>' : ""}</div>`;
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
      if (payload.items.length) {
        reachableStage = resolveApiV2Stage(currentTaskStatus, currentTaskStage, completedStages, true);
        showStage(4);
      }
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
    const plan = executionPlanEnvelope?.items;
    if (!executionPreview || !plan || plan.status !== "confirmed") return;
    const dialog = document.querySelector("#execution-confirm-dialog");
    const risk = document.querySelector("#execution-risk-confirm");
    risk.checked = false;
    document.querySelector("#execution-dialog-submit").disabled = true;
    document.querySelector("#execution-confirm-summary").innerHTML = `<dl><div><dt>执行目标</dt><dd>${escapeHtml(executionPreview.target || plan.target_id)}</dd></div><div><dt>计划节点</dt><dd>${plan.nodes?.length || 0}</dd></div><div><dt>写操作 / 高风险</dt><dd>${plan.write_operation_count || 0} / ${plan.high_risk_count || 0}</dd></div><div><dt>确认 SHA</dt><dd><code>${escapeHtml(plan.confirmation_sha256.slice(0, 16))}</code></dd></div></dl>`;
    dialog.showModal();
  });
  document.querySelector("#execution-risk-confirm")?.addEventListener("change", (event) => { document.querySelector("#execution-dialog-submit").disabled = !event.target.checked; });
  document.querySelector("#execution-confirm-dialog")?.addEventListener("close", async (event) => {
    const plan = executionPlanEnvelope?.items;
    if (event.target.returnValue !== "confirm" || !executionPreview || !plan) return;
    const button = document.querySelector("#confirm-execution");
    button.disabled = true;
    showMessage("#execution-message", "已提交受控执行，正在等待真实结果…");
    try {
      const run = await api(`/api/v1/tasks/${taskId}/execution-plans/${plan.plan_id}/runs`, {method: "POST", body: JSON.stringify({confirmation_sha256: plan.confirmation_sha256})});
      reachableStage = 4; showStage(4); await loadRuns(run.run_id); await loadDrafts();
    } catch (error) { showMessage("#execution-message", `${error.code}: ${error.message}`, true); button.disabled = false; }
  });

  document.querySelector("#open-document")?.addEventListener("click", async () => {
    const workspace = document.querySelector("#document-workspace");
    workspace.hidden = !workspace.hidden;
    if (!workspace.hidden && !documents) {
      try { await loadDocuments(); }
      catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
    }
  });
  document.querySelector("#document-version")?.addEventListener("change", (event) => loadDocument(Number(event.target.value)).catch((error) => showMessage("#contract-message", error.message, true)));
  document.querySelector("#compare-document")?.addEventListener("click", async () => {
    if (!activeDocument || activeDocument.version <= 1) { showMessage("#contract-message", "当前版本没有上一版可比较。"); return; }
    try {
      const diff = await api(`/api/v1/tasks/${taskId}/documents/compare?from=${activeDocument.version - 1}&to=${activeDocument.version}`);
      const node = document.querySelector("#document-diff");
      node.textContent = diff.lines.join("\n") || "两个版本没有文本差异。";
      node.hidden = false;
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#create-document-revision")?.addEventListener("click", () => {
    if (!activeDocument) return;
    document.querySelector("#document-revision-reason").value = "";
    document.querySelector("#document-revision-dialog").showModal();
  });
  document.querySelector("#document-revision-dialog")?.addEventListener("close", async (event) => {
    if (event.target.returnValue !== "confirm" || !activeDocument) return;
    try {
      const saved = await api(`/api/v1/tasks/${taskId}/documents/revisions`, {method: "POST", body: JSON.stringify({base_version: activeDocument.version, content: document.querySelector("#document-revision-content").value, change_reason: document.querySelector("#document-revision-reason").value.trim()})});
      await loadDocuments();
      await loadDocument(saved.version);
      document.querySelector("#document-version").value = String(saved.version);
      showMessage("#contract-message", `文档修订 v${saved.version} 已保存；请重新确认范围后启动分析。`);
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  });

  document.querySelector("#open-reanalyze")?.addEventListener("click", async () => {
    try {
      if (!documents) await loadDocuments();
      const scope = await api(`/api/v1/tasks/${taskId}/analysis-scope`);
      const fields = scope.items;
      const dialog = document.querySelector("#reanalyze-dialog");
      dialog.dataset.scopeVersion = scope.version;
      dialog.dataset.previewSha = "";
      document.querySelector("#reanalyze-document-version").value = String(fields.document_version);
      document.querySelector("#scope-methods").value = (fields.include_methods || []).join(",");
      document.querySelector("#scope-modules").value = (fields.modules || []).join(",");
      document.querySelector("#scope-tags").value = (fields.tags || []).join(",");
      document.querySelector("#scope-include-paths").value = (fields.include_paths || []).join("\n");
      document.querySelector("#scope-exclude-paths").value = (fields.exclude_paths || []).join("\n");
      document.querySelector("#scope-request").checked = fields.analyze_request !== false;
      document.querySelector("#scope-response").checked = fields.analyze_response !== false;
      document.querySelector("#scope-security").checked = fields.analyze_security !== false;
      document.querySelector("#scope-errors").checked = fields.analyze_errors !== false;
      document.querySelector("#scope-dependencies").checked = fields.analyze_dependencies !== false;
      document.querySelector("#scope-reason").value = "";
      document.querySelector("#confirm-reanalyze").disabled = true;
      dialog.showModal();
    } catch (error) { showMessage("#contract-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#save-scope-preview")?.addEventListener("click", async () => {
    const dialog = document.querySelector("#reanalyze-dialog");
    const documentVersion = Number(document.querySelector("#reanalyze-document-version").value);
    const splitLines = (value) => value.split("\n").map((item) => item.trim()).filter(Boolean);
    const fields = {
      include_methods: document.querySelector("#scope-methods").value.split(",").map((item) => item.trim()).filter(Boolean),
      modules: document.querySelector("#scope-modules").value.split(",").map((item) => item.trim()).filter(Boolean),
      tags: document.querySelector("#scope-tags").value.split(",").map((item) => item.trim()).filter(Boolean),
      include_paths: splitLines(document.querySelector("#scope-include-paths").value),
      exclude_paths: splitLines(document.querySelector("#scope-exclude-paths").value),
      analyze_request: document.querySelector("#scope-request").checked,
      analyze_response: document.querySelector("#scope-response").checked,
      analyze_security: document.querySelector("#scope-security").checked,
      analyze_errors: document.querySelector("#scope-errors").checked,
      analyze_dependencies: document.querySelector("#scope-dependencies").checked,
    };
    try {
      const scope = await api(`/api/v1/tasks/${taskId}/analysis-scope`, {method: "PUT", body: JSON.stringify({base_version: Number(dialog.dataset.scopeVersion), document_version: documentVersion, fields, reason: document.querySelector("#scope-reason").value.trim()})});
      dialog.dataset.scopeVersion = scope.version;
      const preview = await api(`/api/v1/tasks/${taskId}/reanalyze/preview`, {method: "POST", body: JSON.stringify({document_version: documentVersion, scope_version: scope.version})});
      dialog.dataset.previewSha = preview.preview_sha256;
      document.querySelector("#reanalyze-impact").innerHTML = `<strong>预计接口 ${preview.estimated_interface_count} 个 · 将过期 ${preview.stale_versions.length} 类下游产物</strong><p>保留 ${preview.preserved_run_count} 个 Run、${preview.preserved_defect_version_count} 个草稿版本 · 文档 SHA ${preview.document_sha256.slice(0, 12)} · 范围 SHA ${preview.scope_sha256.slice(0, 12)}</p>`;
      document.querySelector("#confirm-reanalyze").disabled = false;
    } catch (error) { document.querySelector("#reanalyze-impact").innerHTML = `<strong>${escapeHtml(error.code)}</strong><p>${escapeHtml(error.message)}</p>`; }
  });
  document.querySelector("#confirm-reanalyze")?.addEventListener("click", async () => {
    const dialog = document.querySelector("#reanalyze-dialog");
    try {
      await api(`/api/v1/tasks/${taskId}/reanalyze`, {method: "POST", body: JSON.stringify({document_version: Number(document.querySelector("#reanalyze-document-version").value), scope_version: Number(dialog.dataset.scopeVersion), preview_sha256: dialog.dataset.previewSha, idempotency_key: crypto.randomUUID(), reason: document.querySelector("#scope-reason").value.trim()})});
      dialog.close();
      location.reload();
    } catch (error) { document.querySelector("#reanalyze-impact").innerHTML = `<strong>${escapeHtml(error.code)}</strong><p>${escapeHtml(error.message)}</p>`; }
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
    try {
      const preview = await api(`/api/v1/tasks/${taskId}/cases/confirmation-preview`);
      if (!preview.candidate_ids.length) { showMessage("#case-message", "没有可确认的候选用例。"); return; }
      const dialog = document.querySelector("#case-bulk-confirm-dialog");
      dialog.dataset.preview = JSON.stringify(preview);
      document.querySelector("#case-bulk-confirm-summary").innerHTML = `<strong>将确认 ${preview.candidate_ids.length} 条候选用例</strong><p>其中高风险 ${preview.high_risk_ids.length} 条；不可确认 ${preview.skipped.length} 条不会被静默跳过。</p>`;
      dialog.showModal();
    } catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#case-bulk-confirm-dialog")?.addEventListener("close", async (event) => {
    if (event.target.returnValue !== "confirm" || !cases) return;
    const preview = JSON.parse(event.target.dataset.preview || "{}");
    try {
      await api(`/api/v1/tasks/${taskId}/cases/confirm-all`, {method: "POST", body: JSON.stringify({base_version: preview.base_version, confirmation_sha256: preview.confirmation_sha256, reason: "批量确认全部候选用例"})});
      await loadCases();
      showMessage("#case-message", `已确认 ${preview.candidate_ids.length} 个候选用例。`);
    }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#generate-executable")?.addEventListener("click", async () => {
    try {
      const preview = await api(`/api/v1/tasks/${taskId}/cases/confirmation-preview`);
      await api(`/api/v1/tasks/${taskId}/cases/confirm-and-generate-executable`, {method: "POST", body: JSON.stringify({base_version: preview.base_version, confirmation_sha256: preview.confirmation_sha256, idempotency_key: crypto.randomUUID(), reason: "确认基础用例并生成执行定义"})});
      currentTaskStatus = "pending";
      reachableStage = 2;
      showStage(2);
      showMessage("#executable-message", "已创建阶段三 Attempt，核心 Workflow 正在生成执行定义。");
      setTimeout(refreshTaskState, 500);
      setTimeout(() => loadStageRecords(true), 700);
    } catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });

  document.querySelector("#confirm-executable-all")?.addEventListener("click", async () => {
    if (!executableCases) return;
    const changes = executableCases.items.filter((item) => item.validation_status === "ready" && item.enabled && item.review_status !== "confirmed").map((item) => ({executable_case_id: item.executable_case_id, action: "confirm", reason: "批量核对完整请求和静态校验"}));
    if (!changes.length) { showMessage("#executable-message", "没有待确认的就绪执行定义。"); return; }
    try {
      executableCases = await api(`/api/v1/tasks/${taskId}/executable-cases/review`, {method: "PUT", body: JSON.stringify({base_version: executableCases.version, changes})});
      renderExecutableCases();
      showMessage("#executable-message", `已确认 ${changes.length} 条执行定义。`);
    } catch (error) { showMessage("#executable-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#open-plan-stage")?.addEventListener("click", async () => {
    reachableStage = Math.max(reachableStage, 3);
    showStage(3, true);
    await loadPreview();
  });
  document.querySelector("#create-execution-plan")?.addEventListener("click", async () => {
    try {
      if (!executionPreview) executionPreview = await api(`/api/v1/tasks/${taskId}/execute/preview`);
      if (!executionPreview.target_id) throw Object.assign(new Error("当前环境没有已登记执行目标。"), {code: "EXECUTION_TARGET_DENIED"});
      const requestBody = {executable_version: executableCases?.version || 0, target_id: executionPreview.target_id};
      const preview = await api(`/api/v1/tasks/${taskId}/execution-plans/preview`, {method: "POST", body: JSON.stringify(requestBody)});
      if (preview.stage_state !== "ready") { renderExecutionPlan(preview); return; }
      executionPlanEnvelope = await api(`/api/v1/tasks/${taskId}/execution-plans`, {method: "POST", body: JSON.stringify({...requestBody, idempotency_key: crypto.randomUUID(), reason: "执行定义已复核，保存依赖计划"})});
      currentTaskStatus = "waiting_execution_confirmation";
      renderExecutionPlan(executionPlanEnvelope);
      showMessage("#execution-message", "执行计划已保存，请复核拓扑后确认。" );
    } catch (error) { showMessage("#execution-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#confirm-execution-plan")?.addEventListener("click", async () => {
    const plan = executionPlanEnvelope?.items;
    if (!plan) return;
    try {
      executionPlanEnvelope = await api(`/api/v1/tasks/${taskId}/execution-plans/${plan.plan_id}/confirm`, {method: "POST", body: JSON.stringify({plan_version: executionPlanEnvelope.version, confirmation_sha256: plan.confirmation_sha256, reason: "已核对目标、依赖拓扑、写操作和安全策略"})});
      executionPreview = await api(`/api/v1/tasks/${taskId}/execute/preview`);
      renderExecutionPlan(executionPlanEnvelope);
      showMessage("#execution-message", "执行计划已确认，可以创建受控 Run。" );
    } catch (error) { showMessage("#execution-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#retry-ai-supplement")?.addEventListener("click", async () => {
    try { await api(`/api/v1/tasks/${taskId}/cases/supplement/retry`, {method: "POST"}); location.reload(); }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#case-search")?.addEventListener("input", () => cases && renderCases());
  document.querySelector("#case-risk")?.addEventListener("change", () => cases && renderCases());
  document.querySelector("#coverage-dimension")?.addEventListener("input", () => cases && renderCoverage());
  document.querySelector("#coverage-status")?.addEventListener("change", () => cases && renderCoverage());
  document.querySelector("#coverage-source")?.addEventListener("change", () => cases && renderCoverage());
  document.querySelector("#stage-event-filter")?.addEventListener("change", () => loadStageRecords(true));
  document.querySelector("#stage-level-filter")?.addEventListener("change", () => loadStageRecords(true));
  document.querySelector("#attempt-filter")?.addEventListener("change", () => loadStageRecords(true));
  document.querySelector("#usage-group")?.addEventListener("change", () => loadStageRecords(true));
  document.querySelector("#refresh-stage-events")?.addEventListener("click", () => loadStageRecords(true));
  document.addEventListener("visibilitychange", () => {
    if (["pending", "running"].includes(currentTaskStatus)) {
      clearTimeout(stageRefreshTimer);
      stageRefreshTimer = setTimeout(() => loadStageRecords(false), document.hidden ? 10000 : 500);
    }
  });
  document.querySelector("#coverage-gap-dialog")?.addEventListener("close", async (event) => {
    if (event.target.returnValue !== "confirm" || !cases) return;
    try {
      cases = normalizeCasePayload(await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({coverage_base_version: cases.coverage.version, accept_gap_ids: [event.target.dataset.gapId], reason: document.querySelector("#coverage-gap-reason").value.trim()})}));
      renderCoverage();
      showMessage("#case-message", "覆盖缺口已记录人工接受理由，矩阵保存为新版本。");
    } catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
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
    try { cases = normalizeCasePayload(await api(`/api/v1/tasks/${taskId}/cases/review`, {method: "PUT", body: JSON.stringify({base_version: cases.version, changes: [{action: "add", fields}]})})); renderCoverage(); renderCases(); showMessage("#case-message", "人工用例已新增为候选版本。"); }
    catch (error) { showMessage("#case-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#create-draft")?.addEventListener("click", async () => {
    try {
      await api(`/api/v1/tasks/${taskId}/defect-drafts`, {method: "POST", body: JSON.stringify({run_id: activeRunId, case_ids: [...selectedFailureIds], manual_reason: document.querySelector("#draft-reason").value.trim()})});
      selectedFailureIds.clear(); updateDraftSelection(); await loadDrafts(); showMessage("#draft-message", "本地 Bug 草稿已生成。");
    } catch (error) { showMessage("#draft-message", `${error.code}: ${error.message}`, true); }
  });
  document.querySelector("#retry-stage")?.addEventListener("click", async () => {
    try { await api(`/api/v1/tasks/${taskId}/retry`, {method: "POST", body: JSON.stringify({stage: currentTaskStage, source_versions: {}})}); location.reload(); }
    catch (error) { document.querySelector(".error-panel p").textContent = `${error.code}: ${error.message}`; }
  });

  function label(value, labels) { return escapeHtml(labels[value] || value || "未知"); }
  function contractStatusLabel(value) { return label(value, {draft: "草稿", confirmed_candidate: "候选待确认", confirmed: "已确认", disabled: "已禁用", deprecated: "已忽略"}); }
  function issueStatusLabel(value) { return label(value, {open: "待处理", reopened: "已重新打开", resolved: "待复核", accepted_as_suggestion: "已转为建议"}); }
  function riskLabel(value) { return label(value, {low: "低", medium: "中", high: "高"}); }
  function runStatusLabel(value) { return label(value, {created: "已创建", validating: "校验中", provisioning: "准备中", running: "执行中", reporting: "生成报告", succeeded: "已完成", passed: "通过", failed: "失败", error: "错误", blocked: "依赖阻断", cancelled: "已取消", timed_out: "已超时", skipped: "已跳过"}); }
  function failureLabel(value) { return label(value, {product_defect_candidate: "接口缺陷候选", environment_blocked: "环境阻塞", test_data_issue: "测试数据问题", test_case_issue: "测试用例问题", performance_candidate: "性能候选", unknown: "待归因", none: "无"}); }
  function performanceLabel(value) { return label(value, {within_threshold: "阈值内", warning: "单次慢响应告警", performance_candidate: "连续慢响应候选", not_applicable: "不适用"}); }
  function thresholdLabel(value) { return label(value, {document: "文档 SLA", project: "项目配置", environment: "环境配置", default: "默认"}); }
  function formatDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? escapeHtml(value) : escapeHtml(date.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"})); }
  function escapeHtml(value) { const node = document.createElement("span"); node.textContent = String(value ?? ""); return node.innerHTML; }
  if (root.dataset.preReviewEnabled !== "true") {
    document.querySelector("#open-reanalyze").disabled = true;
    document.querySelector("#create-document-revision").disabled = true;
  }
  loadContracts(); loadCases(); loadExecutableCases(); loadPreview(); loadRuns(); loadDrafts(); loadStageRecords(); refreshTaskState();
})();
