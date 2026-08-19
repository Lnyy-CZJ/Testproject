/** 测试用例在线 Review：列表、嵌套详情、CAS、确认发布与 AI 建议。 */
(() => {
  "use strict";
  const root = document.querySelector("[data-case-review-workbench]");
  if (!root) return;
  const taskId = root.dataset.taskId;
  const state = {
    cases: [], mindmap: null, original: [], testPoints: [], revision: 0, sha256: "", baselineBody: "[]", validation: {}, coverage: {}, diff: {},
    currentId: null, selected: new Set(), search: "", priority: "", onlyErrors: false, page: 1, pageSize: 50,
    dirty: false, saving: false, editable: root.dataset.editable === "true", aiEnabled: root.dataset.aiEnabled === "true",
    ai: null, lastDeleted: null,
  };
  const standardFields = ["case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result"];
  const listEl = document.querySelector("#case-review-list");
  const detailEl = document.querySelector("#case-review-detail");

  function setStatus(message, error = false) { const target = document.querySelector("#case-review-save-state"); target.textContent = message; target.classList.toggle("error", error); }
  function cleanCases() { return state.cases.map((item) => Object.fromEntries(Object.entries(item).filter(([key]) => !key.startsWith("_")))); }
  function canonical(value) { return JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item); }
  function markDirty() {
    /** 使用规范化正文比较，使撤销到服务端草稿时恢复非 dirty 状态。 */
    state.dirty = canonical({ rows: cleanCases(), mindmap: state.mindmap }) !== state.baselineBody;
    document.querySelector("#case-review-download-local").classList.toggle("is-hidden", !state.dirty);
    updateControls();
  }
  function currentCase() { return state.cases.find((item) => item.case_id === state.currentId) || state.cases[0] || null; }
  function nextId() { const highest = Math.max(0, ...state.cases.map((item) => /^TC(\d+)$/i.exec(item.case_id || "")?.[1] || 0).map(Number)); return `TC${String(highest + 1).padStart(3, "0")}`; }
  function errorRows() { return new Set((state.validation.errors || []).map((item) => item.row_index).filter((value) => Number.isInteger(value))); }
  function filtered() {
    const errors = errorRows(); const needle = state.search.trim().toLocaleLowerCase();
    return state.cases.map((item, index) => ({ item, index })).filter(({ item, index }) => {
      const text = [item.case_id, item.test_point_id, item.module, item.feature, item.scenario, item.case_name].join(" ").toLocaleLowerCase();
      return (!needle || text.includes(needle)) && (!state.priority || item.priority === state.priority) && (!state.onlyErrors || errors.has(index));
    });
  }
  function renderSummary() {
    const target = document.querySelector("#case-review-summary"); target.replaceChildren();
    const values = [["用例", state.cases.length], ["覆盖测试点", state.coverage.covered_test_points || 0], ["未覆盖", state.coverage.uncovered_test_points || 0], ["错误", (state.validation.errors || []).length], ["警告", (state.validation.warnings || []).length], ["新增", state.diff.added || 0], ["修改", state.diff.modified || 0]];
    values.forEach(([label, value]) => { const box = document.createElement("div"); const span = document.createElement("span"); span.textContent = label; const strong = document.createElement("strong"); strong.textContent = String(value); box.append(span, strong); target.append(box); });
  }
  function renderIssues() {
    const target = document.querySelector("#case-review-errors"); target.replaceChildren();
    const issues = [...(state.validation.errors || []), ...(state.validation.warnings || [])]; target.classList.toggle("has-content", issues.length > 0);
    issues.slice(0, 30).forEach((issue) => { const button = document.createElement("button"); button.type = "button"; button.textContent = `${issue.level === "error" ? "错误" : "警告"} · ${issue.message}`; button.addEventListener("click", () => focusIssue(issue)); target.append(button); });
  }
  function renderList() {
    listEl.replaceChildren(); const rows = filtered(); const pages = Math.max(1, Math.ceil(rows.length / state.pageSize)); state.page = Math.min(state.page, pages);
    const pageRows = rows.slice((state.page - 1) * state.pageSize, state.page * state.pageSize); const errors = errorRows();
    pageRows.forEach(({ item, index }) => {
      const row = document.createElement("tr"); row.dataset.caseId = item.case_id; row.classList.toggle("is-current", item.case_id === currentCase()?.case_id); row.classList.toggle("has-error", errors.has(index));
      const selectCell = document.createElement("td"); const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = state.selected.has(item.case_id); checkbox.setAttribute("aria-label", `选择 ${item.case_id || index + 1}`); checkbox.addEventListener("click", (event) => event.stopPropagation()); checkbox.addEventListener("change", () => checkbox.checked ? state.selected.add(item.case_id) : state.selected.delete(item.case_id)); selectCell.append(checkbox);
      const nameCell = document.createElement("td"); const name = document.createElement("span"); name.className = "case-list-name"; name.textContent = item.case_name || "未命名用例"; const id = document.createElement("span"); id.className = "case-list-id"; id.textContent = item.case_id || "缺少 ID"; nameCell.append(name, id);
      const point = document.createElement("td"); point.textContent = item.test_point_id || "未引用"; const priority = document.createElement("td"); priority.textContent = item.priority || "-"; const status = document.createElement("td"); status.textContent = errors.has(index) ? "需处理" : (state.dirty ? "已修改" : "有效");
      row.append(selectCell, nameCell, point, priority, status); row.addEventListener("click", () => { state.currentId = item.case_id; renderList(); renderDetail(); }); listEl.append(row);
    });
    document.querySelector("#case-review-page-info").textContent = `第 ${state.page}/${pages} 页 · ${rows.length} 条`;
    document.querySelector("#case-review-prev").disabled = state.page <= 1; document.querySelector("#case-review-next").disabled = state.page >= pages;
  }
  function control(label, field, item, options = null, readonly = false) {
    const wrapper = document.createElement("label"); wrapper.textContent = label; let input;
    if (options) { input = document.createElement("select"); options.forEach((value) => { const option = document.createElement("option"); option.value = value; option.textContent = value || "请选择"; input.append(option); }); input.value = item[field] || ""; }
    else if (["scenario", "expected_result", "actual_result"].includes(field)) { input = document.createElement("textarea"); input.rows = field === "expected_result" ? 4 : 3; input.value = item[field] || ""; }
    else { input = document.createElement("input"); input.value = item[field] || ""; }
    input.dataset.caseField = field; input.disabled = !state.editable || readonly; if (readonly) input.classList.add("readonly-field");
    input.addEventListener("input", () => { const oldId = item.case_id; item[field] = input.value; if (field === "case_id") { if (state.selected.delete(oldId)) state.selected.add(input.value); state.currentId = input.value; } markDirty(); localValidate(); renderSummary(); renderIssues(); renderList(); }); wrapper.append(input); return wrapper;
  }
  function listEditor(title, field, item) {
    const section = document.createElement("section"); section.className = "case-detail-section"; const heading = document.createElement("h3"); heading.textContent = title; section.append(heading); const list = document.createElement("div"); list.className = "case-list-editor";
    (Array.isArray(item[field]) ? item[field] : []).forEach((value, index) => { const row = document.createElement("div"); row.className = "case-list-editor-row"; const number = document.createElement("span"); number.textContent = String(index + 1); const textarea = document.createElement("textarea"); textarea.value = value; textarea.disabled = !state.editable; textarea.setAttribute("aria-label", `${title} ${index + 1}`); textarea.addEventListener("input", () => { item[field][index] = textarea.value; markDirty(); }); const remove = document.createElement("button"); remove.type = "button"; remove.className = "text-button danger"; remove.textContent = "删除"; remove.disabled = !state.editable; remove.addEventListener("click", () => { item[field].splice(index, 1); markDirty(); renderDetail(); }); row.append(number, textarea, remove); list.append(row); });
    const add = document.createElement("button"); add.type = "button"; add.className = "secondary-button"; add.textContent = `新增${title}`; add.disabled = !state.editable; add.addEventListener("click", () => { if (!Array.isArray(item[field])) item[field] = []; item[field].push(""); markDirty(); renderDetail(); }); section.append(list, add); return section;
  }
  function renderDetail() {
    detailEl.replaceChildren(); const item = currentCase(); if (!item) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "请选择一条测试用例。"; detailEl.append(empty); return; }
    state.currentId = item.case_id; const title = document.createElement("h3"); title.textContent = `${item.case_id || "未编号"} · ${item.case_name || "未命名"}`; const grid = document.createElement("div"); grid.className = "case-detail-grid";
    grid.append(control("用例 ID", "case_id", item), control("测试点 ID", "test_point_id", item), control("模块", "module", item), control("功能", "feature", item), control("场景", "scenario", item), control("优先级", "priority", item, ["", "P0", "P1", "P2", "P3"]), control("用例名称", "case_name", item)); grid.lastElementChild.classList.add("full"); grid.append(control("预期结果", "expected_result", item)); grid.lastElementChild.classList.add("full");
    detailEl.append(title, grid, listEditor("前置条件", "preconditions", item), listEditor("测试步骤", "test_steps", item));
    const dataSection = document.createElement("section"); dataSection.className = "case-detail-section"; const dataTitle = document.createElement("h3"); dataTitle.textContent = "测试数据"; const data = document.createElement("textarea"); data.className = "case-json-editor"; data.disabled = !state.editable; data.value = typeof item.test_data === "string" ? item.test_data : JSON.stringify(item.test_data ?? {}, null, 2); data.addEventListener("change", () => { try { item.test_data = JSON.parse(data.value); data.setCustomValidity(""); } catch (_error) { item.test_data = data.value; data.setCustomValidity(""); } markDirty(); localValidate(); renderIssues(); }); dataSection.append(dataTitle, data); detailEl.append(dataSection);
    const actual = document.createElement("section"); actual.className = "case-detail-section"; actual.append(control("实际结果（本期只读）", "actual_result", item, null, true)); detailEl.append(actual);
    const extras = Object.fromEntries(Object.entries(item).filter(([key]) => !standardFields.includes(key) && !key.startsWith("_"))); if (Object.keys(extras).length) { const section = document.createElement("section"); section.className = "case-detail-section"; const heading = document.createElement("h3"); heading.textContent = "扩展字段（只读）"; const pre = document.createElement("pre"); pre.textContent = JSON.stringify(extras, null, 2); section.append(heading, pre); detailEl.append(section); }
  }
  function emitV2State() {
    root.dispatchEvent(new CustomEvent("case-review-v2-state", { detail: {
      cases: cleanCases(), testPoints: state.testPoints, validation: state.validation,
      coverage: state.coverage, diff: state.diff, revision: state.revision,
      sha256: state.sha256, editable: state.editable, versions: state.versions || [],
      mindmap: state.mindmap,
    } }));
  }
  function render() { renderSummary(); renderIssues(); renderList(); renderDetail(); updateControls(); emitV2State(); }
  function updateControls() {
    document.querySelector("#case-review-save").disabled = !state.editable || !state.dirty || state.saving;
    document.querySelector("#case-review-confirm").disabled = !state.editable || state.saving;
    document.querySelectorAll("[data-case-ai-operation]").forEach((button) => { button.disabled = !state.aiEnabled || !state.editable || state.dirty || ["queued", "running"].includes(state.ai?.status); button.title = state.dirty ? "请先保存草稿" : ""; });
  }
  function localValidate() {
    const errors = []; const ids = new Map();
    state.cases.forEach((item, index) => { ["case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "expected_result"].forEach((field) => { if (!String(item[field] || "").trim()) errors.push({ level: "error", code: "CASE_FIELD_REQUIRED", message: `${field} 不能为空`, row_index: index, field }); }); const id = String(item.case_id || ""); ids.set(id, [...(ids.get(id) || []), index]); if (!Array.isArray(item.test_steps) || !item.test_steps.length) errors.push({ level: "error", code: "CASE_STEPS_EMPTY", message: "测试步骤不能为空", row_index: index, field: "test_steps" }); });
    ids.forEach((indexes, id) => { if (id && indexes.length > 1) indexes.forEach((index) => errors.push({ level: "error", code: "CASE_ID_DUPLICATE", message: "测试用例 ID 重复", row_index: index, field: "case_id" })); }); state.validation = { ...state.validation, errors, valid_for_confirm: errors.length === 0 };
  }
  function focusIssue(issue) { if (!Number.isInteger(issue.row_index)) return; const item = state.cases[issue.row_index]; if (!item) return; state.search = ""; state.priority = ""; state.onlyErrors = false; document.querySelector("#case-review-search").value = ""; document.querySelector("#case-review-priority").value = ""; document.querySelector("#case-review-only-errors").checked = false; state.currentId = item.case_id; state.page = Math.floor(issue.row_index / state.pageSize) + 1; render(); requestAnimationFrame(() => detailEl.querySelector(`[data-case-field="${issue.field || "case_name"}"]`)?.focus()); }
  function applyServer(result) { state.cases = result.cases || []; state.mindmap = result.mindmap || null; state.baselineBody = canonical({ rows: state.cases, mindmap: state.mindmap }); state.original = result.original_cases || state.original; state.testPoints = result.test_points || state.testPoints; state.revision = result.revision; state.sha256 = result.sha256; state.validation = result.validation || {}; state.coverage = result.coverage || {}; state.diff = result.diff_summary || {}; state.versions = result.versions || state.versions || []; state.currentId = currentCase()?.case_id || state.cases[0]?.case_id || null; }
  async function saveDraft() { state.saving = true; setStatus("正在保存…"); updateControls(); try { const result = await agentFetch(`/api/v1/tasks/${taskId}/case-review-draft`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: state.revision, sha256: state.sha256, rows: cleanCases(), mindmap: state.mindmap }) }); applyServer(result); state.dirty = false; document.querySelector("#case-review-download-local").classList.add("is-hidden"); setStatus(`已保存 revision ${state.revision}`); globalThis.showAgentToast?.(`测试用例草稿已保存，revision ${state.revision}`); render(); return true; } catch (error) { if (error.code === "CASE_REVIEW_REVISION_CONFLICT") document.querySelector("#case-review-download-local").classList.remove("is-hidden"); setStatus(error.message, true); return false; } finally { state.saving = false; updateControls(); } }
  function dialog(title, message, withInput = false) { const modal = document.querySelector("#case-review-dialog"); document.querySelector("#case-review-dialog-title").textContent = title; document.querySelector("#case-review-dialog-message").textContent = message; const input = document.querySelector("#case-review-dialog-input"); input.classList.toggle("is-hidden", !withInput); input.value = ""; modal.showModal(); return new Promise((resolve) => modal.addEventListener("close", () => resolve(modal.returnValue === "confirm" ? (withInput ? input.value : true) : false), { once: true })); }
  async function confirmPublish() {
    if ((state.revision === 0 || state.dirty) && !(await saveDraft())) return;
    const errors = (state.validation.errors || []).length;
    const warnings = (state.validation.warnings || []).length;
    const uncovered = Number(state.coverage.uncovered_test_points || 0);
    if ((errors || warnings || uncovered) && !(await dialog("带质量风险发布", `当前有 ${errors} 个错误、${warnings} 个警告、${uncovered} 个未覆盖测试点。发布不会修改这些内容，确定生成新版本吗？`))) return;
    try { setStatus("正在确认并发布 JSON/XLSX…"); await agentFetch(`/api/v1/tasks/${taskId}/case-review/confirm`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `case-confirm-${taskId}-${state.sha256.slice(0, 16)}` }, body: JSON.stringify({ revision: state.revision, sha256: state.sha256, accept_warnings: true }) }); state.dirty = false; location.reload(); } catch (error) { if (error.details?.validation) { state.validation = error.details.validation; render(); } setStatus(error.message, true); }
  }
  function downloadLocal() { const url = URL.createObjectURL(new Blob([JSON.stringify(cleanCases(), null, 2)], { type: "application/json;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `case-review-local-${taskId}.json`; link.click(); URL.revokeObjectURL(url); }
  function addCase(source = null) { const point = state.testPoints[0] || {}; const value = source ? { ...structuredClone(source), case_id: nextId() } : { case_id: nextId(), test_point_id: point.id || "", module: point.module || "", feature: point.feature || "", scenario: point.scenario || "", case_name: "", priority: point.risk_level || "P2", preconditions: [], test_steps: [""], test_data: {}, expected_result: "", actual_result: "" }; state.cases.push(value); state.currentId = value.case_id; state.page = Math.ceil(state.cases.length / state.pageSize); markDirty(); localValidate(); render(); }
  function removeCurrent() { const index = state.cases.findIndex((item) => item.case_id === state.currentId); if (index < 0) return; state.lastDeleted = { index, item: state.cases[index] }; state.cases.splice(index, 1); state.currentId = state.cases[Math.min(index, state.cases.length - 1)]?.case_id || null; document.querySelector("#case-review-undo").disabled = false; markDirty(); localValidate(); render(); }
  async function requestAI(operation) { let instruction = ""; if (operation === "generate_from_instruction") { instruction = await dialog("按说明生成建议", "说明不会被视为已确认需求事实。", true); if (!instruction) return; } const selectedIds = [...state.selected]; try { setStatus("正在提交用例 AI 请求…"); await agentFetch(`/api/v1/tasks/${taskId}/case-review-ai`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `case-ai-${Date.now()}` }, body: JSON.stringify({ revision: state.revision, sha256: state.sha256, operation, selected_ids: selectedIds, scope: {}, instruction }) }); state.ai = { status: "queued" }; updateControls(); pollAI(); } catch (error) { setStatus(error.message, true); } }
  async function pollAI() { try { const result = await agentFetch(`/api/v1/tasks/${taskId}/case-review-ai`); state.ai = result; const active = ["queued", "running"].includes(result.status); document.querySelector("#case-review-ai-cancel").classList.toggle("is-hidden", !active); updateControls(); if (active) { setStatus(result.status === "queued" ? "用例 AI 排队中" : "用例 AI 正在生成建议"); setTimeout(pollAI, 5000); return; } if (result.status === "ready") showSuggestions(result); else if (result.status) setStatus(result.error_message || "AI 辅助未完成，可继续人工 Review", true); } catch (error) { setStatus(error.message, true); } }
  function showSuggestions(result) { const panel = document.querySelector("#case-review-suggestions"); panel.classList.remove("is-hidden"); document.querySelector("#case-review-ai-summary").textContent = `${result.summary || "建议已生成"} · 模型 ${result.model_name || "unknown"} · Prompt ${(result.prompt_bundle_sha256 || "").slice(0, 12)}`; const list = document.querySelector("#case-review-suggestion-list"); list.replaceChildren(); (result.suggestions || []).forEach((suggestion) => { const item = document.createElement("label"); item.className = "suggestion-item"; const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.dataset.caseSuggestionId = suggestion.suggestion_id; const action = document.createElement("strong"); action.textContent = suggestion.action === "add" ? "新增" : "改写"; const detail = document.createElement("div"); const pre = document.createElement("pre"); pre.textContent = JSON.stringify(suggestion.case, null, 2); const reason = document.createElement("p"); reason.textContent = `${suggestion.reason || ""} ${suggestion.source_basis || ""}`; detail.append(pre, reason); item.append(checkbox, action, detail); list.append(item); }); setStatus("用例 AI 建议已就绪，默认未选择"); }
  function applySuggestions() { if (state.ai?.base_revision !== state.revision || state.ai?.base_sha256 !== state.sha256) { setStatus("AI 建议基准已变化，请重新生成", true); return; } const chosen = new Set([...document.querySelectorAll("[data-case-suggestion-id]:checked")].map((item) => item.dataset.caseSuggestionId)); (state.ai.suggestions || []).filter((item) => chosen.has(item.suggestion_id)).forEach((suggestion) => { if (suggestion.action === "add") state.cases.push(structuredClone(suggestion.case)); else { const index = state.cases.findIndex((item) => item.case_id === suggestion.target_id); if (index >= 0) state.cases[index] = { ...state.cases[index], ...structuredClone(suggestion.case), case_id: suggestion.target_id, test_point_id: state.cases[index].test_point_id, actual_result: state.cases[index].actual_result }; } }); if (chosen.size) { markDirty(); localValidate(); render(); setStatus(`已应用 ${chosen.size} 条建议，尚未保存`); } }
  async function load() { try { const result = await agentFetch(`/api/v1/tasks/${taskId}/case-review`); applyServer(result); state.ai = result.case_review_ai || null; render(); setStatus(state.editable ? `已加载 revision ${state.revision}` : "只读模式"); if (["queued", "running", "ready"].includes(state.ai?.status)) pollAI(); } catch (error) { setStatus(error.message, true); listEl.replaceChildren(); detailEl.replaceChildren(); } }

  document.querySelector("#case-review-search").addEventListener("input", (event) => { state.search = event.target.value; state.page = 1; renderList(); });
  document.querySelector("#case-review-priority").addEventListener("change", (event) => { state.priority = event.target.value; state.page = 1; renderList(); });
  document.querySelector("#case-review-only-errors").addEventListener("change", (event) => { state.onlyErrors = event.target.checked; state.page = 1; renderList(); });
  document.querySelector("#case-review-page-size").addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; renderList(); });
  document.querySelector("#case-review-prev").addEventListener("click", () => { state.page -= 1; renderList(); }); document.querySelector("#case-review-next").addEventListener("click", () => { state.page += 1; renderList(); });
  document.querySelector("#case-review-add").addEventListener("click", () => addCase()); document.querySelector("#case-review-duplicate").addEventListener("click", () => currentCase() && addCase(currentCase())); document.querySelector("#case-review-delete").addEventListener("click", async () => { if (currentCase() && await dialog("删除测试用例", `确定删除 ${currentCase().case_id} 吗？`)) removeCurrent(); });
  document.querySelector("#case-review-undo").addEventListener("click", () => { if (!state.lastDeleted) return; state.cases.splice(state.lastDeleted.index, 0, state.lastDeleted.item); state.currentId = state.lastDeleted.item.case_id; state.lastDeleted = null; document.querySelector("#case-review-undo").disabled = true; markDirty(); localValidate(); render(); });
  document.querySelector("#case-review-save").addEventListener("click", saveDraft); document.querySelector("#case-review-confirm").addEventListener("click", confirmPublish); document.querySelector("#case-review-download-local").addEventListener("click", downloadLocal);
  document.querySelectorAll("[data-case-ai-operation]").forEach((button) => button.addEventListener("click", () => requestAI(button.dataset.caseAiOperation))); document.querySelector("#case-review-ai-cancel").addEventListener("click", async () => { await agentFetch(`/api/v1/tasks/${taskId}/case-review-ai/cancel`, { method: "POST" }); location.reload(); }); document.querySelector("#case-review-apply-suggestions").addEventListener("click", applySuggestions); document.querySelector("#case-review-suggestions-close").addEventListener("click", () => document.querySelector("#case-review-suggestions").classList.add("is-hidden"));
  document.querySelector("#case-review-import-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = new FormData(event.target); form.set("revision", state.revision); form.set("sha256", state.sha256); try { const result = await agentFetch(`/api/v1/tasks/${taskId}/case-review-draft/import`, { method: "POST", body: form }); applyServer(result); state.dirty = false; render(); setStatus("测试用例 JSON 已导入为草稿"); } catch (error) { setStatus(error.message, true); } });
  root.addEventListener("case-review-v2-request-state", emitV2State);
  root.addEventListener("case-review-v2-replace", (event) => {
    state.cases = event.detail.rows || [];
    state.mindmap = event.detail.mindmap || state.mindmap;
    state.currentId = state.cases.find((item) => item.case_id === state.currentId)?.case_id || state.cases[0]?.case_id || null;
    markDirty(); localValidate(); render();
  });
  root.addEventListener("case-review-v2-selection", (event) => {
    state.selected = new Set(event.detail.ids || []);
    if (state.selected.size) state.currentId = [...state.selected][0];
    renderSummary(); updateControls();
  });
  addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } }); load();
})();
