/** 在线测试点 Review 工作台；用户正文始终通过 textContent/value 写入 DOM。 */
(() => {
  const root = document.querySelector("[data-review-workbench]");
  if (!root) return;
  const taskId = root.dataset.taskId;
  const state = { points: [], mindmap: null, original: [], revision: 0, sha256: "", validationSha256: "", baselineBody: "[]", validation: { errors: [], warnings: [] }, diff: {}, selected: new Set(), collapsedModules: new Set(), page: 1, pageSize: 100, search: "", risk: "", onlyErrors: false, dirty: false, saving: false, editable: root.dataset.editable === "true", aiEnabled: root.dataset.aiEnabled === "true", ai: null, lastDeleted: null };
  const fields = ["id", "module", "feature", "scenario", "test_point", "risk_level"];
  const labels = { total: "总数", added: "新增", modified: "修改", deleted: "删除", errors: "错误", warnings: "警告", revision: "Revision", selected: "已选" };
  const bodyEl = document.querySelector("#review-table-body");
  const saveState = document.querySelector("#review-save-state");

  function rowKey() { return globalThis.crypto?.randomUUID?.() || `row-${Date.now()}-${Math.random()}`; }
  function withKeys(points) { return points.map((point) => ({ ...point, _rowKey: rowKey() })); }
  function cleanPoints() { return state.points.map(({ _rowKey, ...point }) => point); }
  function setStatus(text, error = false) { saveState.textContent = text; saveState.style.color = error ? "var(--red)" : ""; }
  function canonical(value) { return JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item); }
  function markDirty() {
    /** dirty 由草稿正文决定，撤销回服务端基线时必须自动恢复干净状态。 */
    state.dirty = canonical({ rows: cleanPoints(), mindmap: state.mindmap }) !== state.baselineBody;
    document.querySelector("#review-download-local").classList.toggle("is-hidden", !state.dirty);
    setStatus(state.dirty ? "有未保存修改" : `已保存 revision ${state.revision}`);
    updateControls();
  }
  function issueRows() { return new Set([...(state.validation.errors || []), ...(state.validation.warnings || [])].map((item) => item.row_index).filter((value) => Number.isInteger(value))); }

  function filteredRows() {
    const errors = issueRows();
    const query = state.search.trim().toLocaleLowerCase();
    return state.points.map((point, index) => ({ point, index })).filter(({ point, index }) => {
      const matchesText = !query || fields.some((field) => String(point[field] || "").toLocaleLowerCase().includes(query));
      return matchesText && (!state.risk || point.risk_level === state.risk) && (!state.onlyErrors || errors.has(index));
    });
  }

  function renderSummary() {
    const values = { total: state.points.length, ...state.diff, errors: state.validation.errors?.length || 0, warnings: state.validation.warnings?.length || 0, revision: state.revision, selected: state.selected.size };
    const container = document.querySelector("#review-summary");
    container.replaceChildren();
    Object.entries(labels).forEach(([key, label]) => { const item = document.createElement("div"); const caption = document.createElement("span"); const value = document.createElement("strong"); caption.textContent = label; value.textContent = String(values[key] ?? 0); item.append(caption, value); container.append(item); });
  }

  function renderIssues() {
    const container = document.querySelector("#review-errors");
    container.replaceChildren();
    const issues = [...(state.validation.errors || []), ...(state.validation.warnings || [])].slice(0, 20);
    container.classList.toggle("has-content", issues.length > 0);
    issues.forEach((issue) => { const button = document.createElement("button"); button.type = "button"; button.textContent = `${issue.level === "error" ? "错误" : "警告"} · ${issue.message}`; button.addEventListener("click", () => focusIssue(issue)); container.append(button); });
  }

  function inputFor(point, field, index) {
    const control = field === "risk_level" ? document.createElement("select") : (field === "test_point" ? document.createElement("textarea") : document.createElement("input"));
    if (field === "risk_level") ["", "P0", "P1", "P2", "P3"].forEach((value) => { const option = document.createElement("option"); option.value = value; option.textContent = value || "请选择"; control.append(option); });
    control.value = point[field] ?? "";
    control.dataset.index = String(index); control.dataset.field = field; control.disabled = !state.editable;
    control.setAttribute("aria-label", `${point.id || `第${index + 1}行`} ${field}`);
    control.addEventListener("change", () => { point[field] = control.value; markDirty(); localValidate(); renderSummary(); });
    control.addEventListener("keydown", (event) => { if (event.key === "Enter" && field !== "test_point") focusAdjacent(index + 1, field); });
    return control;
  }

  function renderTable() {
    const rows = filteredRows();
    const pages = Math.max(1, Math.ceil(rows.length / state.pageSize));
    state.page = Math.min(state.page, pages);
    const pageRows = rows.slice((state.page - 1) * state.pageSize, state.page * state.pageSize);
    bodyEl.replaceChildren();
    const errorIndexes = issueRows();
    let previousModule = null;
    pageRows.forEach(({ point, index }) => {
      const moduleName = String(point.module || "未分组");
      if (moduleName !== previousModule) {
        const groupRow = document.createElement("tr"); const groupCell = document.createElement("td"); const toggle = document.createElement("button");
        groupRow.className = "module-group"; groupCell.colSpan = 9; toggle.type = "button"; toggle.className = "module-toggle";
        toggle.setAttribute("aria-expanded", String(!state.collapsedModules.has(moduleName))); toggle.textContent = `${state.collapsedModules.has(moduleName) ? "展开" : "折叠"} · ${moduleName}`;
        toggle.addEventListener("click", () => { state.collapsedModules.has(moduleName) ? state.collapsedModules.delete(moduleName) : state.collapsedModules.add(moduleName); renderTable(); });
        groupCell.append(toggle); groupRow.append(groupCell); bodyEl.append(groupRow); previousModule = moduleName;
      }
      if (state.collapsedModules.has(moduleName)) return;
      const tr = document.createElement("tr"); tr.dataset.index = String(index);
      if (errorIndexes.has(index)) tr.classList.add("row-error");
      const selectCell = document.createElement("td"); const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.checked = state.selected.has(point._rowKey); checkbox.setAttribute("aria-label", `选择 ${point.id || index + 1}`); checkbox.addEventListener("change", () => { checkbox.checked ? state.selected.add(point._rowKey) : state.selected.delete(point._rowKey); renderSummary(); }); selectCell.append(checkbox); tr.append(selectCell);
      fields.forEach((field) => { const td = document.createElement("td"); td.append(inputFor(point, field, index)); tr.append(td); });
      const status = document.createElement("td"); status.className = "row-status"; status.textContent = errorIndexes.has(index) ? "需处理" : (state.dirty ? "已修改" : "未修改"); tr.append(status);
      const actions = document.createElement("td"); actions.className = "row-actions";
      [["复制", () => duplicate(index), "text-button"], ["删除", () => removeRows([index]), "text-button danger"]].forEach(([label, action, className]) => { const button = document.createElement("button"); button.type = "button"; button.className = className; button.textContent = label; button.disabled = !state.editable; button.addEventListener("click", action); actions.append(button); });
      tr.append(actions); bodyEl.append(tr);
    });
    document.querySelector("#review-page-info").textContent = `第 ${state.page}/${pages} 页 · ${rows.length} 条`;
    document.querySelector("#review-prev").disabled = state.page <= 1;
    document.querySelector("#review-next").disabled = state.page >= pages;
  }

  function emitV2State() {
    root.dispatchEvent(new CustomEvent("review-v2-state", { detail: {
      points: cleanPoints(), validation: state.validation, diff: state.diff,
      revision: state.revision, sha256: state.sha256, editable: state.editable,
      mindmap: state.mindmap,
      versions: state.versions || [],
    } }));
  }
  function render() { renderSummary(); renderIssues(); renderTable(); updateControls(); emitV2State(); }
  function updateControls() {
    document.querySelector("#review-save").disabled = !state.editable || !state.dirty || state.saving;
    document.querySelector("#review-resume").disabled = !state.editable || state.saving;
    document.querySelectorAll("[data-ai-operation]").forEach((button) => { button.disabled = !state.aiEnabled || !state.editable || state.dirty || ["queued", "running"].includes(state.ai?.status); button.title = state.dirty ? "请先保存草稿" : ""; });
  }

  function localValidate() {
    const ids = new Map(); const exact = new Map(); const errors = [];
    state.points.forEach((point, index) => {
      fields.forEach((field) => { if (!String(point[field] || "").trim()) errors.push({ level: "error", code: "FIELD_REQUIRED", message: `${field} 不能为空`, row_index: index, field }); });
      if (point.risk_level && !["P0", "P1", "P2", "P3"].includes(point.risk_level)) errors.push({ level: "error", code: "RISK_LEVEL_INVALID", message: "风险等级不合法", row_index: index, field: "risk_level" });
      const id = String(point.id || ""); ids.set(id, [...(ids.get(id) || []), index]);
      const key = [point.module, point.feature, point.scenario, point.test_point].map((value) => String(value || "").trim().replace(/\s+/g, " ").toLocaleLowerCase()).join("\u001f"); exact.set(key, [...(exact.get(key) || []), index]);
    });
    [[ids, "POINT_ID_DUPLICATE", "测试点 ID 重复"], [exact, "POINT_EXACT_DUPLICATE", "测试点内容完全重复"]].forEach(([map, code, message]) => map.forEach((indexes, key) => { if (key && indexes.length > 1) indexes.forEach((index) => errors.push({ level: "error", code, message, row_index: index, related_rows: indexes })); }));
    state.validation = { ...state.validation, errors, valid_for_resume: errors.length === 0 };
  }

  function focusIssue(issue) { state.search = ""; state.risk = ""; state.onlyErrors = false; document.querySelector("#review-search").value = ""; document.querySelector("#review-risk").value = ""; document.querySelector("#review-only-errors").checked = false; const target = state.points[issue.row_index]; if (target) state.collapsedModules.delete(String(target.module || "未分组")); state.page = Math.floor((issue.row_index || 0) / state.pageSize) + 1; renderTable(); requestAnimationFrame(() => document.querySelector(`[data-index="${issue.row_index}"][data-field="${issue.field || "test_point"}"]`)?.focus()); }
  function focusAdjacent(index, field) { document.querySelector(`[data-index="${index}"][data-field="${field}"]`)?.focus(); }
  function nextId() { const highest = Math.max(0, ...state.points.map((point) => /^TP(\d+)$/.exec(point.id || "")?.[1] || 0).map(Number)); return `TP${String(highest + 1).padStart(3, "0")}`; }
  function addPoint(prefill = {}) { state.points.push({ id: nextId(), module: "", feature: "", scenario: "", test_point: "", risk_level: "P2", ...prefill, _rowKey: rowKey() }); state.page = Math.ceil(state.points.length / state.pageSize); markDirty(); localValidate(); render(); }
  function duplicate(index) { const source = state.points[index]; state.points.splice(index + 1, 0, { ...source, id: nextId(), _rowKey: rowKey() }); markDirty(); localValidate(); render(); }
  function removeRows(indexes) { const sorted = [...indexes].sort((a, b) => a - b); state.lastDeleted = sorted.map((index) => ({ index, point: state.points[index] })); state.points = state.points.filter((_point, index) => !sorted.includes(index)); state.selected.clear(); document.querySelector("#review-undo").disabled = false; markDirty(); localValidate(); render(); }

  async function saveDraft() {
    state.saving = true; setStatus("正在保存…"); updateControls();
    try { const result = await agentFetch(`/api/v1/tasks/${taskId}/review-draft`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision: state.revision, sha256: state.sha256, rows: cleanPoints(), mindmap: state.mindmap }) }); applyServerReview(result); state.dirty = false; document.querySelector("#review-download-local").classList.add("is-hidden"); setStatus(`已保存 revision ${state.revision}`); globalThis.showAgentToast?.(`测试点草稿已保存，revision ${state.revision}`); render(); return true; }
    catch (error) { if (error.code === "REVIEW_REVISION_CONFLICT") document.querySelector("#review-download-local").classList.remove("is-hidden"); setStatus(error.message, true); return false; }
    finally { state.saving = false; updateControls(); }
  }
  function applyServerReview(result) { state.points = withKeys(result.points); state.mindmap = result.mindmap || null; state.baselineBody = canonical({ rows: result.points || [], mindmap: state.mindmap }); state.original = result.original_points || state.original; state.revision = result.revision; state.sha256 = result.sha256; state.validationSha256 = result.validation_sha256 || ""; state.validation = result.validation; state.diff = result.diff_summary; state.versions = result.versions || state.versions || []; }
  function downloadLocalDraft() { const payload = JSON.stringify(cleanPoints(), null, 2); const url = URL.createObjectURL(new Blob([payload], { type: "application/json;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `review-local-${taskId}.json`; link.click(); URL.revokeObjectURL(url); }

  function confirmDialog(title, message, withInput = false) { const dialog = document.querySelector("#review-dialog"); document.querySelector("#review-dialog-title").textContent = title; document.querySelector("#review-dialog-message").textContent = message; const input = document.querySelector("#review-dialog-input"); input.classList.toggle("is-hidden", !withInput); input.value = ""; dialog.showModal(); return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm" ? (withInput ? input.value : true) : false), { once: true })); }
  async function resume() { if (state.dirty && !(await saveDraft())) return; const risks = (state.validation.errors || []).length + (state.validation.warnings || []).length; let acknowledged = false; if (risks) acknowledged = Boolean(await confirmDialog("确认质量风险", `当前有 ${state.validation.errors?.length || 0} 个错误、${state.validation.warnings?.length || 0} 个警告。问题会保留在版本记录中，仍然继续生成用例吗？`)); if (risks && !acknowledged) return; try { setStatus("正在确认并重新排队…"); await agentFetch(`/api/v1/tasks/${taskId}/resume`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `review-${taskId}-${state.sha256.slice(0, 16)}` }, body: JSON.stringify({ revision: state.revision, sha256: state.sha256, acknowledge_quality_risks: acknowledged, validation_sha256: state.validationSha256, accept_warnings: acknowledged }) }); state.dirty = false; location.reload(); } catch (error) { if (error.details?.validation) { state.validation = error.details.validation; render(); } setStatus(error.message, true); } }

  async function requestAI(operation) { let instruction = ""; if (operation === "generate_from_instruction") { instruction = await confirmDialog("按说明生成建议", "说明只用于测试设计，不会被当作已确认需求事实。", true); if (!instruction) return; } const selectedIds = state.points.filter((point) => state.selected.has(point._rowKey)).map((point) => point.id); try { setStatus("正在提交 AI 请求…"); await agentFetch(`/api/v1/tasks/${taskId}/review-ai`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `review-ai-${Date.now()}` }, body: JSON.stringify({ revision: state.revision, sha256: state.sha256, operation, selected_ids: selectedIds, scope: {}, instruction }) }); state.ai = { status: "queued" }; setReadonlyForAI(true); pollAI(); } catch (error) { setStatus(error.message, true); } }
  function setReadonlyForAI(active) { root.querySelectorAll("input,select,textarea,button").forEach((control) => { if (!control.closest("dialog") && control.id !== "review-ai-cancel") control.disabled = active || !state.editable; }); document.querySelector("#review-ai-cancel").classList.toggle("is-hidden", !active); }
  async function pollAI() { try { const result = await agentFetch(`/api/v1/tasks/${taskId}/review-ai`); state.ai = result; if (["queued", "running"].includes(result.status)) { setStatus(result.status === "queued" ? "AI 请求排队中" : "AI 正在生成建议"); setTimeout(pollAI, 5000); return; } setReadonlyForAI(false); if (result.status === "ready") showSuggestions(result); else setStatus(result.error_message || "AI 辅助未完成，可继续人工 Review", true); } catch (error) { setStatus(error.message, true); setReadonlyForAI(false); } }
  function showSuggestions(result) { const panel = document.querySelector("#review-suggestions"); panel.classList.remove("is-hidden"); document.querySelector("#review-ai-summary").textContent = `${result.summary || "建议已生成"} · 模型 ${result.model_name || "unknown"} · Prompt ${(result.prompt_bundle_sha256 || "").slice(0, 12)}`; const list = document.querySelector("#review-suggestion-list"); list.replaceChildren(); (result.suggestions || []).forEach((suggestion) => { const item = document.createElement("label"); item.className = "suggestion-item"; const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.dataset.suggestionId = suggestion.suggestion_id; const action = document.createElement("strong"); action.textContent = suggestion.action === "add" ? "新增" : "改写"; const detail = document.createElement("div"); const pre = document.createElement("pre"); pre.textContent = JSON.stringify(suggestion.point, null, 2); const reason = document.createElement("p"); reason.textContent = `${suggestion.reason || ""} ${suggestion.source_basis || ""}`; detail.append(pre, reason); item.append(checkbox, action, detail); list.append(item); }); setStatus("AI 建议已就绪，默认未选择"); }
  function applySuggestions() { if (state.ai?.base_revision !== state.revision || state.ai?.base_sha256 !== state.sha256) { setStatus("AI 建议基准已变化，请重新生成", true); return; } const chosen = new Set([...document.querySelectorAll("[data-suggestion-id]:checked")].map((item) => item.dataset.suggestionId)); (state.ai.suggestions || []).filter((item) => chosen.has(item.suggestion_id)).forEach((suggestion) => { if (suggestion.action === "add") state.points.push({ ...suggestion.point, _rowKey: rowKey() }); else { const index = state.points.findIndex((point) => point.id === suggestion.target_id); if (index >= 0) state.points[index] = { ...state.points[index], ...suggestion.point, id: suggestion.target_id }; } }); if (chosen.size) { markDirty(); localValidate(); render(); setStatus(`已应用 ${chosen.size} 条建议，尚未保存`); } }

  async function load() { try { const result = await agentFetch(`/api/v1/tasks/${taskId}/review`); applyServerReview(result); state.ai = result.review_ai || null; render(); setStatus(state.editable ? `已加载 revision ${state.revision}` : "只读模式"); if (["queued", "running"].includes(state.ai?.status)) { setReadonlyForAI(true); pollAI(); } else if (state.ai?.status === "ready") pollAI(); } catch (error) { setStatus(error.message, true); bodyEl.replaceChildren(); } }

  document.querySelector("#review-search").addEventListener("input", (event) => { state.search = event.target.value; state.page = 1; renderTable(); });
  document.querySelector("#review-risk").addEventListener("change", (event) => { state.risk = event.target.value; state.page = 1; renderTable(); });
  document.querySelector("#review-only-errors").addEventListener("change", (event) => { state.onlyErrors = event.target.checked; state.page = 1; renderTable(); });
  document.querySelector("#review-page-size").addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; renderTable(); });
  document.querySelector("#review-prev").addEventListener("click", () => { state.page -= 1; renderTable(); }); document.querySelector("#review-next").addEventListener("click", () => { state.page += 1; renderTable(); });
  document.querySelector("#review-add").addEventListener("click", () => addPoint()); document.querySelector("#review-delete-selected").addEventListener("click", async () => { const indexes = state.points.map((point, index) => state.selected.has(point._rowKey) ? index : -1).filter((index) => index >= 0); if (indexes.length && await confirmDialog("批量删除", `确定删除 ${indexes.length} 条测试点吗？`)) removeRows(indexes); });
  document.querySelector("#review-undo").addEventListener("click", () => { if (!state.lastDeleted) return; state.lastDeleted.forEach(({ index, point }, offset) => state.points.splice(index + offset, 0, point)); state.lastDeleted = null; document.querySelector("#review-undo").disabled = true; markDirty(); localValidate(); render(); });
  document.querySelector("#review-save").addEventListener("click", saveDraft); document.querySelector("#review-resume").addEventListener("click", resume);
  document.querySelector("#review-download-local").addEventListener("click", downloadLocalDraft);
  document.querySelectorAll("[data-ai-operation]").forEach((button) => button.addEventListener("click", () => requestAI(button.dataset.aiOperation)));
  document.querySelector("#review-ai-cancel").addEventListener("click", async () => { await agentFetch(`/api/v1/tasks/${taskId}/review-ai/cancel`, { method: "POST" }); location.reload(); });
  document.querySelector("#review-apply-suggestions").addEventListener("click", applySuggestions); document.querySelector("#review-suggestions-close").addEventListener("click", () => document.querySelector("#review-suggestions").classList.add("is-hidden"));
  document.querySelector("#review-import-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = new FormData(event.target); form.set("revision", state.revision); form.set("sha256", state.sha256); try { const result = await agentFetch(`/api/v1/tasks/${taskId}/review-draft/import`, { method: "POST", body: form }); applyServerReview(result); state.dirty = false; render(); setStatus("JSON 已导入为草稿"); } catch (error) { setStatus(error.message, true); } });
  root.addEventListener("review-v2-request-state", emitV2State);
  root.addEventListener("review-v2-replace", (event) => {
    state.points = withKeys(event.detail.rows || []);
    state.mindmap = event.detail.mindmap || state.mindmap;
    markDirty(); localValidate(); render();
  });
  root.addEventListener("review-v2-selection", (event) => {
    const ids = new Set(event.detail.ids || []);
    state.selected = new Set(state.points.filter((point) => ids.has(point.id)).map((point) => point._rowKey));
    renderSummary(); updateControls();
  });
  addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
  load();
})();
