(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const json = async (response) => {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error_code || body.message || `HTTP_${response.status}`);
    return body;
  };
  const showAlert = (message) => {
    const node = $("#global-alert");
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  };
  const setText = (selector, value) => { const node = $(selector); if (node) node.textContent = value ?? "—"; };
  const escapeNewlines = (value) => String(value ?? "");
  const statusClass = (status) => ["running", "completed", "failed", "cancelled", "cleanup_pending"].includes(status) ? status : "neutral";

  function initNewRun() {
    const form = $("#run-form");
    if (!form) return;
    let mode = "e2e";
    const modeInput = $("#run-mode");
    const e2eFields = $("#e2e-fields");
    const evalFields = $("#eval-fields");
    const mediaInput = $("#media");
    const datasetInput = $("#dataset");
    const kind = $("#task-kind");
    const renderMode = () => {
      modeInput.value = mode;
      $$("[data-mode-tab]").forEach((button) => {
        const active = button.dataset.modeTab === mode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
      e2eFields.hidden = mode !== "e2e";
      evalFields.hidden = mode !== "eval";
      mediaInput.disabled = mode !== "e2e";
      datasetInput.disabled = mode !== "eval";
      setText("#summary-mode", mode === "e2e" ? "完整 E2E" : "快速批量");
      setText("#summary-flow", mode === "e2e" ? "Identity → Media → Task → Result → Delete" : "Create → Poll → Result → Diagnostics → Delete");
      $("#form-title").textContent = mode === "e2e" ? "完整 E2E 小规模验证" : "快速批量评测";
      $("#form-description").textContent = mode === "e2e" ? "上传一组脱敏截图，验证公开协议和真实异步 Task 生命周期。" : "上传 dating.transcript.v1 JSONL，跳过截图和 OCR，直接验证 Reply / Analysis Evaluation。";
      updateKindFields();
    };
    const updateKindFields = () => {
      const reply = kind.value === "reply";
      $$(".reply-options").forEach((node) => { node.hidden = mode !== "e2e" || !reply; });
      $$(".analysis-options").forEach((node) => { node.hidden = mode !== "e2e" || reply; });
      setText("#summary-kind", kind.value === "reply" ? "Reply" : "Analysis");
    };
    $$("[data-mode-tab]").forEach((button) => button.addEventListener("click", () => { mode = button.dataset.modeTab; renderMode(); }));
    kind.addEventListener("change", updateKindFields);
    mediaInput.addEventListener("change", () => {
      const list = $("#media-list"); list.replaceChildren();
      Array.from(mediaInput.files).forEach((file, index) => { const item = document.createElement("li"); item.textContent = `${String(index + 1).padStart(2, "0")} · ${file.name} · ${file.size} bytes`; list.appendChild(item); });
      setText("#summary-input", `${mediaInput.files.length} 张图片`);
    });
    datasetInput.addEventListener("change", () => setText("#dataset-name", datasetInput.files[0] ? datasetInput.files[0].name : "尚未选择文件"));
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); showAlert("");
      const preflight = $("#preflight"); preflight.className = "preflight"; preflight.innerHTML = '<span class="dot"></span><span>正在执行本地校验…</span>';
      const data = new FormData(form);
      try {
        if (mode === "e2e" && !mediaInput.files.length) throw new Error("E2E 至少选择一张图片");
        if (mode === "eval" && !datasetInput.files.length) throw new Error("Eval 必须上传 JSONL 数据集");
        const validation = await json(await fetch("/api/runs/validate", { method: "POST", body: data }));
        const summary = validation.summary || {};
        setText("#summary-cases", summary.case_count);
        setText("#summary-input", mode === "e2e" ? `${summary.media_count || 0} 张图片` : `${summary.message_count || 0} 条消息`);
        preflight.className = "preflight ok"; preflight.innerHTML = '<span class="dot"></span><span>本地校验通过，可以提交 Run</span>';
        $("#form-status").textContent = "已校验"; $("#form-status").className = "status-badge completed";
        const created = await json(await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ draft_id: validation.draft_id }) }));
        window.location.href = `/runs/${encodeURIComponent(created.run_id)}`;
      } catch (error) {
        preflight.className = "preflight error"; preflight.innerHTML = `<span class="dot"></span><span>校验或提交失败：${error.message}</span>`;
        $("#form-status").textContent = "需要处理"; $("#form-status").className = "status-badge failed";
      }
    });
    renderMode();
  }

  async function loadRuns() {
    const body = $("#runs-body"); if (!body) return;
    const params = new URLSearchParams(); ["mode", "kind", "status"].forEach((key) => { const node = $(`#filter-${key}`); if (node && node.value) params.set(key === "kind" ? "task_kind" : key, node.value); });
    try {
      const data = await json(await fetch(`/api/runs?${params}`)); body.replaceChildren();
      setText("#runs-count", `${data.total || 0} 个 Run`);
      if (!data.items?.length) { body.innerHTML = '<tr><td colspan="6" class="table-state">还没有运行记录，先创建一个评测 Run。</td></tr>'; return; }
      data.items.forEach((item) => { const row = document.createElement("tr"); row.innerHTML = `<td><a href="/runs/${encodeURIComponent(item.run_id)}">${item.run_id}</a></td><td>${item.mode || "—"} / ${item.task_kind || "—"}</td><td>${item.case_count ?? "—"}</td><td><span class="status-badge ${statusClass(item.status)}">${item.status || "—"}</span></td><td>${item.cleanup_status || "—"}</td><td>${item.updated_at || item.created_at || "—"}</td>`; body.appendChild(row); });
    } catch (error) { body.innerHTML = `<tr><td colspan="6" class="table-state">读取失败：${error.message}</td></tr>`; }
  }

  function initRuns() { if (!$("#runs-body")) return; $("#runs-refresh")?.addEventListener("click", loadRuns); ["#filter-mode", "#filter-kind", "#filter-status"].forEach((selector) => $(selector)?.addEventListener("change", loadRuns)); loadRuns(); }

  async function loadDetail() {
    const root = $("#run-detail"); if (!root) return;
    const runId = root.dataset.runId;
    try {
      const data = await json(await fetch(`/api/runs/${encodeURIComponent(runId)}`)); const manifest = data.manifest || {}; const status = manifest.status || data.active?.status || "—";
      setText("#detail-status", status); $("#detail-status").className = `status-badge ${statusClass(status)}`; setText("#detail-updated", manifest.updated_at); setText("#detail-cases", manifest.case_count ?? data.cases?.length ?? 0); setText("#detail-cleanup", manifest.cleanup_status || "—"); setText("#detail-summary", `${manifest.mode || "—"} / ${manifest.task_kind || "—"}`); $("#detail-manifest").textContent = JSON.stringify(manifest, null, 2);
      const eventList = $("#detail-events"); eventList.replaceChildren(); (data.events || []).forEach((event) => { const item = document.createElement("li"); item.textContent = `${event.timestamp || ""} · ${event.event || ""}`; eventList.appendChild(item); }); if (!data.events?.length) eventList.innerHTML = "<li>暂无状态事件</li>";
      const caseBody = $("#detail-cases-body"); caseBody.replaceChildren(); (data.cases || []).forEach((item) => { const metadata = item.metadata || {}; const task = item.task || {}; const cleanup = item.cleanup || {}; const row = document.createElement("tr"); row.innerHTML = `<td><a href="#case-artifact" data-case-id="${encodeURIComponent(item.case_id)}">${item.case_id}</a></td><td>${task.task_id || "—"}</td><td><span class="status-badge ${statusClass(task.status)}">${task.status || "—"}</span></td><td>${task.error_code || metadata.error_code || "—"}</td><td>${cleanup.status || "—"}</td>`; caseBody.appendChild(row); }); if (!data.cases?.length) caseBody.innerHTML = '<tr><td colspan="5" class="table-state">暂无 Case 产物</td></tr>'; $$("[data-case-id]", caseBody).forEach((link) => link.addEventListener("click", async () => { const caseId = decodeURIComponent(link.dataset.caseId); try { const artifact = await json(await fetch(`/api/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`)); $("#case-artifact-json").textContent = JSON.stringify(artifact, null, 2); $("#case-artifact").open = true; } catch (error) { $("#case-artifact-json").textContent = `Case Artifact 读取失败：${error.message}`; } }));
      await loadLog(runId);
      const canCancel = ["waiting", "running", "cancelling"].includes(status); $("#cancel-run").disabled = !canCancel;
      return status;
    } catch (error) { showAlert(`读取 Run 失败：${error.message}`); return "failed"; }
  }
  async function loadLog(runId) { const node = $("#detail-log"); if (!node) return; try { const tail = $("#log-tail")?.value || "200"; const data = await json(await fetch(`/api/runs/${encodeURIComponent(runId)}/logs?tail=${tail}`)); node.textContent = escapeNewlines((data.lines || []).join("\n")); } catch (error) { node.textContent = `日志暂不可用：${error.message}`; } }
  function initDetail() { const root = $("#run-detail"); if (!root) return; const runId = root.dataset.runId; $("#cancel-run")?.addEventListener("click", async () => { try { await json(await fetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" })); await loadDetail(); } catch (error) { showAlert(`取消失败：${error.message}`); } }); $("#refresh-log")?.addEventListener("click", () => loadLog(runId)); const poll = async () => { const status = await loadDetail(); if (!["completed", "failed", "cancelled", "blocked", "cleanup_pending"].includes(status)) window.setTimeout(poll, 3000); }; poll(); }

  document.addEventListener("DOMContentLoaded", () => { initNewRun(); initRuns(); initDetail(); });
})();
