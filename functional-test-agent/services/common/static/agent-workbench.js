/** 两个智能体工作台共用的 CSRF、提交、轮询和日志交互。 */
const body = document.body;
const base = body.dataset.basePath;
const csrf = body.dataset.csrf;
const workbenchStatusLabels = {
  pending: "排队中", running: "生成中", waiting_review: "测试点待评审", waiting_case_review: "用例待评审",
  succeeded: "已完成", partial_success: "部分完成", failed: "失败", cancelled: "已取消",
};
const tokenStageLabels = {
  requirement_decomposition: "需求拆解", test_points_generation: "测试点生成", test_points_coverage: "测试点覆盖校验",
  test_points_supplement: "测试点补全", test_points_review_ai: "测试点 AI Review", test_cases_generation: "测试用例生成",
  test_cases_coverage: "测试用例覆盖校验", test_cases_supplement: "测试用例补全", test_cases_review_ai: "测试用例 AI Review",
};

function renderTokenUsage(usage) {
  const root = document.querySelector("#token-usage"); if (!root) return;
  root.replaceChildren();
  const title = document.createElement("h3"); title.textContent = "本次 Token 消耗"; root.append(title);
  const stages = Object.entries(usage?.stages || {});
  if (!stages.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "尚未产生 Token 统计；模型供应商未返回用量时会标记为未报告。"; root.append(empty); return; }
  const table = document.createElement("table"); table.className = "token-usage-table";
  const head = document.createElement("thead"); head.innerHTML = "<tr><th>阶段</th><th>输入</th><th>输出</th><th>合计</th><th>调用</th></tr>"; table.append(head);
  const body = document.createElement("tbody");
  stages.forEach(([stage, value]) => { const row = document.createElement("tr"); [tokenStageLabels[stage] || stage, value.reported_calls ? value.input_tokens.toLocaleString() : "未报告", value.reported_calls ? value.output_tokens.toLocaleString() : "未报告", value.reported_calls ? value.total_tokens.toLocaleString() : "未报告", String(value.calls || 0)].forEach((text) => { const cell = document.createElement("td"); cell.textContent = text; row.append(cell); }); body.append(row); });
  table.append(body); root.append(table);
}

async function agentFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) {
    headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(`${base}${path}`, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("json") ? await response.json() : null;
  if (!response.ok) {
    const error = new Error(payload?.error?.message || `请求失败 (${response.status})`);
    error.code = payload?.error?.code;
    error.details = payload?.error?.details;
    throw error;
  }
  return payload;
}

// ES Module 工作台复用同一 CSRF/错误协议，不复制第二套请求封装。
globalThis.agentFetch = agentFetch;
let toastTimer = null;
globalThis.showAgentToast = (message, error = false) => {
  /** 全站只复用一个状态提示，连续保存时重新计时，避免堆叠遮挡工作台。 */
  let toast = document.querySelector(".agent-toast");
  if (!toast) {
    toast = document.createElement("div"); toast.className = "agent-toast";
    toast.setAttribute("role", "status"); toast.setAttribute("aria-live", "polite"); document.body.append(toast);
    Object.assign(toast.style, { position: "fixed", top: "72px", right: "24px", zIndex: "1200", maxWidth: "420px", padding: "12px 16px", borderRadius: "10px", boxShadow: "0 12px 32px rgba(0,0,0,.14)", fontSize: "14px", fontWeight: "650" });
  }
  clearTimeout(toastTimer); toast.textContent = message; toast.classList.toggle("is-error", Boolean(error));
  Object.assign(toast.style, error
    ? { border: "1px solid #fecdca", background: "#fff3f2", color: "#b42318" }
    : { border: "1px solid rgba(24,121,78,.24)", background: "#f0faf5", color: "#18794e" });
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 3000);
};
const initialTokenUsage = document.querySelector("#token-usage")?.dataset.tokenUsage;
if (initialTokenUsage) { try { renderTokenUsage(JSON.parse(initialTokenUsage)); } catch (_error) { renderTokenUsage({}); } }

document.querySelectorAll("[data-artifact-preview-url]").forEach((button) => {
  button.addEventListener("click", async (event) => {
    event.preventDefault(); event.stopPropagation();
    const item = button.closest("details"); const preview = item.querySelector(".artifact-preview");
    item.open = true;
    if (preview.dataset.loaded === "true") { preview.hidden = !preview.hidden; return; }
    preview.hidden = false; preview.textContent = "正在读取产物…";
    try {
      const result = await agentFetch(button.dataset.artifactPreviewUrl);
      preview.textContent = `${result.content}${result.truncated ? "\n\n[预览已截断，请下载查看完整内容]" : ""}`;
      preview.dataset.loaded = "true";
    } catch (error) { preview.textContent = error.message; }
  });
});

async function waitForTaskVisible(taskId) {
  /** Docker bind mount 原子替换期间极短暂不可见时重试，避免创建成功后落到 404。 */
  for (let attempt = 0; attempt < 10; attempt += 1) {
    try {
      await agentFetch(`/api/v1/tasks/${taskId}`);
      return;
    } catch (error) {
      if (attempt === 9) throw error;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
}

const taskForm = document.querySelector("#task-form");
if (taskForm) {
  taskForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#form-message");
    message.textContent = "正在创建任务…";
    message.className = "inline-message";
    try {
      const task = await agentFetch("/api/v1/tasks", { method: "POST", body: new FormData(taskForm) });
      await waitForTaskVisible(task.id);
      location.href = `${base}/tasks/${task.id}`;
    } catch (error) {
      message.textContent = error.message;
      message.className = "inline-message error";
    }
  });
}

const heading = document.querySelector("[data-task-id]");
if (heading) {
  const id = heading.dataset.taskId;
  const initialStatus = document.querySelector("#task-status")?.dataset.status;
  let cursor = 0;

  async function refreshTask() {
    try {
      const task = await agentFetch(`/api/v1/tasks/${id}`);
      const status = document.querySelector("#task-status");
      status.dataset.status = task.status;
      status.dataset.stage = task.stage;
      status.title = `${task.status} · ${task.stage}`;
      status.textContent = body.classList.contains("functional-workbench-v2-page")
        ? (workbenchStatusLabels[task.status] || task.status)
        : `${task.status} · ${task.stage}`;
      document.querySelector("#model-name").textContent = task.model_name || "等待任务启动";
      document.querySelector("#prompt-version").textContent = task.prompt_bundle_sha256?.slice(0, 12) || "等待任务启动";
      document.querySelector("#release-version").textContent = task.config_release_version || "未发布";
      renderTokenUsage(task.token_usage || {});
      const pageStates = ["waiting_review", "waiting_case_review", "succeeded", "partial_success", "failed", "cancelled"];
      if (body.classList.contains("functional-workbench-v3-page") && task.status !== initialStatus && pageStates.includes(task.status)) {
        location.reload();
        return;
      }
      if (!["succeeded", "failed", "cancelled", "partial_success", "waiting_review", "waiting_contract_review", "waiting_case_review", "waiting_execution_confirmation"].includes(task.status) && !document.hidden) {
        setTimeout(refreshTask, 5000);
      }
    } catch (_error) {
      setTimeout(refreshTask, 10000);
    }
  }

  async function refreshLog() {
    try {
      const result = await agentFetch(`/api/v1/tasks/${id}/logs?cursor=${cursor}`);
      const log = document.querySelector("#task-log");
      if (cursor === 0) log.textContent = "";
      log.textContent += result.content;
      cursor = result.next_cursor;
      log.scrollTop = log.scrollHeight;
    } catch (error) {
      document.querySelector("#task-log").textContent = error.message;
    }
  }

  document.querySelector("#refresh-log")?.addEventListener("click", refreshLog);
  document.querySelector('[data-action="cancel"]')?.addEventListener("click", async () => {
    if (!confirm("取消会终止当前工作流，确定继续吗？")) return;
    await agentFetch(`/api/v1/tasks/${id}/cancel`, { method: "POST" });
    location.reload();
  });
  const review = document.querySelector("#review-form");
  review?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#review-message");
    message.textContent = "正在校验并重新排队…";
    try {
      await agentFetch(`/api/v1/tasks/${id}/resume`, { method: "POST", body: new FormData(review) });
      location.reload();
    } catch (error) {
      message.textContent = error.message;
      message.className = "inline-message error";
    }
  });
  refreshTask();
  refreshLog();
}
