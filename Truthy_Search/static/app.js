/* 阶段3页面交互：Run 定时刷新、Raw 按需加载、折叠搜索与复制。 */

(() => {
  "use strict";

  const terminalStatuses = new Set([
    "COMPLETED",
    "PARTIAL_FAILED",
    "FAILED",
    "INTERRUPTED",
  ]);

  function updateText(selector, value) {
    const element = document.querySelector(selector);
    if (element) element.textContent = value ?? "—";
  }

  function startRunPolling() {
    const host = document.querySelector("[data-run-status-url]");
    if (!host) return;
    const statusUrl = host.dataset.runStatusUrl;
    let timer = null;

    const refresh = async () => {
      try {
        const response = await fetch(statusUrl, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) return;
        const state = await response.json();
        updateText("[data-run-status]", state.status);
        updateText("[data-total]", state.total_queries);
        updateText("[data-completed]", state.completed_queries);
        updateText("[data-success]", state.success_queries);
        updateText("[data-failed]", state.failed_queries);
        updateText("[data-current-query]", state.current_query_id || "—");
        updateText("[data-current-stage]", state.current_stage || "—");
        updateText("[data-progress-message]", state.message || "—");
        if (terminalStatuses.has(state.status)) {
          window.clearInterval(timer);
          window.location.reload();
        }
      } catch (_) {
        // 暂时网络错误不改变数据库状态；下一次定时刷新会继续尝试。
      }
    };

    refresh();
    timer = window.setInterval(refresh, 2000);
  }

  const rawDialog = document.querySelector("#raw-dialog");
  const rawTree = document.querySelector("#raw-tree");
  const rawLoading = document.querySelector("#raw-loading");
  const rawSearch = document.querySelector("#raw-search");
  let loadedRaw = null;

  function stringifyValue(value) {
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = value;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
  }

  function actionButton(label, value) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => copyText(value));
    return button;
  }

  function renderLeaf(key, value, path) {
    const row = document.createElement("div");
    row.className = "json-leaf";
    row.dataset.searchText = `${path} ${stringifyValue(value)}`.toLowerCase();

    const pathNode = document.createElement("span");
    pathNode.className = "json-path";
    pathNode.textContent = key;

    const valueNode = document.createElement("span");
    valueNode.className = "json-value";
    valueNode.textContent = stringifyValue(value);

    const actions = document.createElement("span");
    actions.className = "json-actions";
    actions.append(
      actionButton("路径", path),
      actionButton("值", stringifyValue(value)),
    );
    row.append(pathNode, valueNode, actions);
    return row;
  }

  function renderJsonNode(value, path = "root", label = "root", depth = 0) {
    if (value === null || typeof value !== "object") {
      return renderLeaf(label, value, path);
    }
    const details = document.createElement("details");
    details.open = depth < 2;
    details.dataset.searchText = path.toLowerCase();
    const summary = document.createElement("summary");
    const size = Array.isArray(value)
      ? `${value.length} items`
      : `${Object.keys(value).length} fields`;
    summary.textContent = `${label} · ${size}`;
    details.appendChild(summary);
    Object.entries(value).forEach(([key, child]) => {
      const childPath = Array.isArray(value)
        ? `${path}[${key}]`
        : `${path}.${key}`;
      details.appendChild(renderJsonNode(child, childPath, key, depth + 1));
    });
    return details;
  }

  function filterRawTree(term) {
    if (!rawTree) return;
    const normalized = term.trim().toLowerCase();
    rawTree.querySelectorAll(".json-leaf").forEach((leaf) => {
      leaf.hidden = Boolean(
        normalized && !leaf.dataset.searchText.includes(normalized),
      );
    });
    if (normalized) {
      rawTree.querySelectorAll("details").forEach((details) => {
        const hasVisibleLeaf = [...details.querySelectorAll(".json-leaf")].some(
          (leaf) => !leaf.hidden,
        );
        details.hidden = !hasVisibleLeaf;
        if (hasVisibleLeaf) details.open = true;
      });
    } else {
      rawTree.querySelectorAll("details").forEach((details) => {
        details.hidden = false;
      });
    }
  }

  async function openRaw(rawId, label) {
    if (!rawDialog || !rawTree || !rawLoading) return;
    rawTree.replaceChildren();
    rawLoading.hidden = false;
    loadedRaw = null;
    rawSearch.value = "";
    updateText("#raw-dialog-title", label || "Raw JSON");
    rawDialog.showModal();
    try {
      const response = await fetch(`/api/raw/${encodeURIComponent(rawId)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      loadedRaw = await response.json();
      rawTree.appendChild(renderJsonNode(loadedRaw));
    } catch (error) {
      const message = document.createElement("p");
      message.className = "error-list";
      message.textContent = `Raw 加载失败：${error.message}`;
      rawTree.appendChild(message);
    } finally {
      rawLoading.hidden = true;
    }
  }

  document.querySelectorAll("[data-raw-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openRaw(button.dataset.rawId, button.dataset.rawLabel);
    });
  });

  document.querySelector("[data-close-dialog]")?.addEventListener("click", () => {
    rawDialog?.close();
  });

  rawSearch?.addEventListener("input", () => filterRawTree(rawSearch.value));

  document.querySelector("[data-copy-json]")?.addEventListener("click", () => {
    if (loadedRaw !== null) {
      copyText(JSON.stringify(loadedRaw, null, 2));
    }
  });

  startRunPolling();
})();
