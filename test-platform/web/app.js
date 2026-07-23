const tools = [
  {
    id: "trackevents",
    healthPath: "/trackevents/health",
    expectedService: "trackevents",
  },
  {
    id: "log-filter",
    healthPath: "/log-filter/health",
    expectedService: "log-filter",
  },
];

/**
 * 更新单个工具卡片的可见状态和无障碍文本。
 * @param {string} toolId 工具唯一标识，对应卡片的 data-tool。
 * @param {'checking'|'ok'|'error'} state 当前服务状态。
 */
function updateStatus(toolId, state) {
  const card = document.querySelector(`[data-tool="${toolId}"]`);
  const status = card?.querySelector("[data-status]");
  const statusText = card?.querySelector("[data-status-text]");
  if (!status || !statusText) return;

  const labels = { checking: "检测中", ok: "正常", error: "服务异常" };
  status.className = `status status-${state}`;
  statusText.textContent = labels[state];
}

/**
 * 调用工具健康检查，超时或响应内容不符合约定时统一标记为异常。
 * @param {{id: string, healthPath: string, expectedService: string}} tool 工具配置。
 * @returns {Promise<boolean>} 服务和代理链路均正常时返回 true。
 */
async function checkTool(tool) {
  updateStatus(tool.id, "checking");
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 3000);

  try {
    const response = await fetch(tool.healthPath, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const isHealthy = payload.status === "ok" && payload.service === tool.expectedService;
    updateStatus(tool.id, isHealthy ? "ok" : "error");
    return isHealthy;
  } catch (error) {
    updateStatus(tool.id, "error");
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/** 重新检查全部工具；单个工具失败不会中断其他状态更新。 */
async function refreshStatuses() {
  const button = document.getElementById("refresh-status");
  button.disabled = true;
  button.textContent = "检测中...";
  try {
    await Promise.all(tools.map(checkTool));
  } finally {
    button.disabled = false;
    button.textContent = "重新检测状态";
  }
}

document.getElementById("refresh-status").addEventListener("click", refreshStatuses);
refreshStatuses();
