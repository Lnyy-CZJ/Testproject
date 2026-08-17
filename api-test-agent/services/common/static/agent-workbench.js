/** 两个智能体工作台共用的 CSRF、提交、轮询和日志交互。 */
const body = document.body;
const base = body.dataset.basePath;
const csrf = body.dataset.csrf;
const workbenchStatusLabels = {
  pending: "排队中", running: "生成中", waiting_review: "测试点待评审", waiting_case_review: "用例待评审",
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
