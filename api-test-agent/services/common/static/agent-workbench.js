/** 两个智能体工作台共用的 CSRF、提交、轮询和日志交互。 */
const body = document.body;
const base = body.dataset.basePath;
const csrf = body.dataset.csrf;
const workbenchStatusLabels = {
  pending: "排队中", running: "生成中", waiting_review: "测试点待评审", waiting_case_review: "用例待评审",
  waiting_contract_review: "契约待确认", waiting_execution_confirmation: "待执行确认",
  succeeded: "已完成", partial_success: "部分完成", failed: "失败", cancelled: "已取消",
};

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
const taskDialog = document.querySelector("#task-create-dialog");
if (taskDialog && taskForm) {
  let wizardStep = 1;
  const panels = [...taskDialog.querySelectorAll("[data-step]")];
  const labels = [...taskDialog.querySelectorAll("[data-step-label]")];
  const back = taskDialog.querySelector("#wizard-back");
  const next = taskDialog.querySelector("#wizard-next");
  const submit = taskDialog.querySelector("#wizard-submit");
  const boundary = taskDialog.querySelector("#task-boundary-confirm");
  const preflight = taskDialog.querySelector("#document-preflight");

  function showWizardStep(step) {
    wizardStep = step;
    panels.forEach((panel) => { panel.hidden = Number(panel.dataset.step) !== step; });
    labels.forEach((label) => {
      label.classList.toggle("active", Number(label.dataset.stepLabel) === step);
      label.classList.toggle("complete", Number(label.dataset.stepLabel) < step);
    });
    back.hidden = step === 1;
    next.hidden = step === 3;
    submit.hidden = step !== 3;
    submit.disabled = step === 3 && !boundary.checked;
  }

  async function validateDocument() {
    const file = taskForm.elements.document_file.files[0];
    const pasted = taskForm.elements.document_text.value.trim();
    if (Boolean(file) === Boolean(pasted)) {
      preflight.textContent = "上传文件和粘贴文本必须二选一。";
      preflight.className = "inline-message error";
      return false;
    }
    const sample = `${file?.name || ""}\n${file ? await file.text() : pasted}`.slice(0, 200000).toLowerCase();
    const unsupported = [
      ["postman", /postman|schema\.getpostman\.com/], ["AsyncAPI", /(^|\n)\s*asyncapi\s*:/],
      ["GraphQL", /__schema|__type|\bgraphql\b/], ["gRPC / proto", /syntax\s*=\s*["']proto|\bservice\s+\w+\s*\{/],
      ["WebSocket", /\bwebsocket\b|\bwss?:\/\//],
    ].find(([, pattern]) => pattern.test(sample));
    if (unsupported) {
      preflight.textContent = `识别到 ${unsupported[0]}，当前版本不支持导入。`;
      preflight.className = "inline-message error";
      return false;
    }
    preflight.textContent = file ? `已选择 ${file.name}，可继续确认分析范围。` : "已读取粘贴文档，可继续确认分析范围。";
    preflight.className = "inline-message success";
    return true;
  }

  document.querySelectorAll("#open-task-create, [data-open-task-create]").forEach((button) => button.addEventListener("click", () => {
    showWizardStep(1);
    taskDialog.showModal();
  }));
  taskDialog.querySelector("[data-close-dialog]").addEventListener("click", () => taskDialog.close());
  back.addEventListener("click", () => showWizardStep(Math.max(1, wizardStep - 1)));
  next.addEventListener("click", async () => {
    if (wizardStep === 1 && !(await validateDocument())) return;
    if (wizardStep === 2) {
      const required = [taskForm.elements.project_name, taskForm.elements.module_name];
      if (required.some((field) => !field.reportValidity())) return;
      taskDialog.querySelector("#task-create-summary").innerHTML = `<dl><div><dt>项目 / 模块</dt><dd>${escapeWorkbenchHtml(taskForm.elements.project_name.value)} / ${escapeWorkbenchHtml(taskForm.elements.module_name.value)}</dd></div><div><dt>任务目标</dt><dd>${escapeWorkbenchHtml(taskForm.elements.operation.selectedOptions[0].textContent)}</dd></div><div><dt>测试环境</dt><dd>${escapeWorkbenchHtml(taskForm.elements.environment.value)}</dd></div></dl>`;
    }
    showWizardStep(Math.min(3, wizardStep + 1));
  });
  boundary.addEventListener("change", () => { submit.disabled = !boundary.checked; });
  taskForm.addEventListener("submit", (event) => {
    if (wizardStep !== 3 || !boundary.checked) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  });
}

const taskSearch = document.querySelector("#task-search");
const taskStatusFilter = document.querySelector("#task-status-filter");
if (taskSearch && taskStatusFilter) {
  const filterTasks = () => {
    const query = taskSearch.value.trim().toLowerCase();
    const status = taskStatusFilter.value;
    let visible = 0;
    document.querySelectorAll("[data-task-row]").forEach((row) => {
      const matched = (!query || row.dataset.search.toLowerCase().includes(query)) && (!status || row.dataset.status === status);
      row.hidden = !matched;
      if (matched) visible += 1;
    });
    const empty = document.querySelector("#task-filter-empty");
    if (empty) empty.hidden = visible > 0;
  };
  taskSearch.addEventListener("input", filterTasks);
  taskStatusFilter.addEventListener("change", filterTasks);
}
document.querySelectorAll("[data-task-row] time").forEach((node) => {
  const date = new Date(node.textContent.trim());
  if (!Number.isNaN(date.getTime())) node.textContent = date.toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
});

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

function escapeWorkbenchHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

const heading = document.querySelector("[data-task-id]");
if (heading) {
  const id = heading.dataset.taskId;
  let cursor = 0;

  async function refreshTask() {
    try {
      const task = await agentFetch(`/api/v1/tasks/${id}`);
      const status = document.querySelector("#task-status");
      status.dataset.status = task.status;
      status.dataset.stage = task.stage;
      status.title = `${task.status} · ${task.stage}`;
      status.textContent = body.classList.contains("functional-workbench-v2-page") || body.classList.contains("api-v2-page")
        ? (workbenchStatusLabels[task.status] || task.status)
        : `${task.status} · ${task.stage}`;
      document.querySelector("#model-name").textContent = task.model_name || "等待任务启动";
      document.querySelector("#prompt-version").textContent = task.prompt_bundle_sha256?.slice(0, 12) || "等待任务启动";
      document.querySelector("#release-version").textContent = task.config_release_version || "未发布";
      // API V2 的 Workflow 运行中同时增量刷新技术日志；页面隐藏时 refreshTask
      // 本身会暂停高频轮询，避免后台标签持续请求。日志失败不影响任务状态展示。
      if (body.classList.contains("api-v2-page") && ["pending", "running"].includes(task.status) && !document.hidden) {
        await refreshLog();
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
      if (!log.textContent) log.textContent = result.complete ? "本次 Runner 未产生技术日志。" : "Runner 正在启动，暂未输出技术日志。";
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
