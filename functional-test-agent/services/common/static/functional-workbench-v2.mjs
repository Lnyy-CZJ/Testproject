import {
  buildMoveCommand,
  applyPatch,
  compileMindmapRows,
  CommandHistory,
  cleanRows,
  executeCommand,
  filterRows,
  flattenTree,
  newRowContext,
  executeMindmapCommand,
  mindmapTree,
  projectMindmap,
  projectTestCases,
  projectTestPoints,
  syncMindmapRows,
  wrapRows,
} from "./mindmap-domain.mjs?v=20260819-free-review-4";
import { MindmapView } from "./mindmap-view.mjs?v=20260819-free-review-4";

const base = document.body.dataset.basePath;
const STATUS_LABELS = {
  pending: "排队中", running: "生成中", waiting_review: "测试点待评审", waiting_case_review: "用例待评审",
  succeeded: "已完成", partial_success: "部分完成", failed: "失败", cancelled: "已取消",
};
const STAGE_LABELS = {
  queued: "等待执行", waiting_for_review: "等待测试点评审",
  review_ai_queued: "测试点 AI 排队", review_ai_ready: "测试点 AI 建议就绪",
  review_ai_cancelled: "测试点 AI 已取消", case_review_editing: "测试用例评审",
  case_review_ai_queued: "用例 AI 排队", case_review_ai_running: "用例 AI 生成中",
  case_review_ai_ready: "用例 AI 建议就绪", case_review_ai_cancelled: "用例 AI 已取消",
  case_review_published: "产物已发布", completed: "生成完成", workflow: "智能生成",
  configuration: "配置检查", execution_confirmation: "等待确认", worker: "执行中",
  timeout: "执行超时", interrupted: "执行中断", cancelled: "已取消",
};

function element(tag, className, text) {
  const value = document.createElement(tag);
  if (className) value.className = className;
  if (text !== undefined) value.textContent = text;
  return value;
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function setupTaskIndex() {
  const root = document.querySelector("[data-functional-task-index]");
  if (!root) return;
  const dialog = document.querySelector("#new-task-dialog");
  document.querySelector("#open-task-dialog")?.addEventListener("click", () => dialog?.showModal());
  document.querySelector("#close-task-dialog")?.addEventListener("click", () => dialog?.close());
  document.querySelector("#close-task-dialog-bottom")?.addEventListener("click", () => dialog?.close());
  const search = document.querySelector("#task-list-search");
  const status = document.querySelector("#task-list-status");
  const date = document.querySelector("#task-list-date");
  const table = root.querySelector(".platform-task-table");
  const empty = document.querySelector("#task-list-empty-filter");
  const totalLabel = document.querySelector("#task-list-total");
  const pageInfo = document.querySelector("#task-list-page-info");
  const previous = document.querySelector("#task-list-prev");
  const next = document.querySelector("#task-list-next");
  let page = 1;
  let total = Number(root.dataset.total || totalLabel?.textContent.match(/\d+/)?.[0] || 0);

  function taskRow(item) {
    const row = element("div", "platform-task-row"); row.dataset.taskRow = ""; row.setAttribute("role", "row");
    const task = element("div"); const link = element("a", "task-title-link", item.title); link.href = `${base}/tasks/${item.id}`;
    task.append(link, element("code", "", item.id));
    const documentCell = element("div"); documentCell.append(element("span", "", item.project_name), element("small", "", item.module_name));
    const state = element("div"); state.append(element("strong", `status-pill status-${item.status}`, STATUS_LABELS[item.status] || item.status), element("small", "task-stage", STAGE_LABELS[item.stage] || item.stage));
    const time = element("time", "", formatTime(item.created_at)); time.title = item.created_at || "";
    const actions = element("div", "task-row-actions"); const view = element("a", "", "查看"); view.href = `${base}/tasks/${item.id}`;
    const copy = element("button", "", "复制重跑"); copy.type = "button"; copy.dataset.copyTask = "";
    Object.assign(copy.dataset, { title: item.title, project: item.project_name, module: item.module_name, operation: item.operation });
    actions.append(view, copy);
    row.append(task, documentCell, state, element("strong", "", String(item.test_point_count || 0)), element("strong", "", String(item.test_case_count || 0)), element("span", "", item.model_name || "等待执行"), element("span", "", `v${item.test_case_review_version || item.test_point_review_version || 0}`), time, actions);
    return row;
  }

  function updatePagination() {
    const pages = Math.max(1, Math.ceil(total / 20));
    pageInfo.textContent = `第 ${page} / ${pages} 页`;
    previous.disabled = page <= 1;
    next.disabled = page >= pages;
    totalLabel.textContent = `共 ${total} 项，仅显示你有权限查看的任务。`;
  }

  async function loadTasks() {
    root.setAttribute("aria-busy", "true");
    const params = new URLSearchParams({ page: String(page), page_size: "20" });
    if (search.value.trim()) params.set("q", search.value.trim());
    if (status.value) params.set("status", status.value);
    if (date.value) params.set("date", date.value);
    try {
      const result = await globalThis.agentFetch(`/api/v1/tasks?${params}`);
      total = result.total; page = result.page;
      table.querySelectorAll("[data-task-row]").forEach((row) => row.remove());
      result.items.forEach((item) => table.append(taskRow(item)));
      empty.hidden = result.items.length > 0;
      empty.querySelector("h3").textContent = "没有匹配任务";
      empty.querySelector("p").textContent = "调整搜索词、状态或日期后重试。";
      updatePagination();
    } catch (error) {
      empty.hidden = false;
      empty.querySelector("h3").textContent = "任务加载失败";
      empty.querySelector("p").textContent = error.message;
    } finally {
      root.removeAttribute("aria-busy");
    }
  }

  let debounce;
  search.addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => { page = 1; loadTasks(); }, 250); });
  [status, date].forEach((control) => control.addEventListener("change", () => { page = 1; loadTasks(); }));
  previous.addEventListener("click", () => { if (page > 1) { page -= 1; loadTasks(); } });
  next.addEventListener("click", () => { if (page * 20 < total) { page += 1; loadTasks(); } });
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy-task]");
    if (!button) return;
    const form = document.querySelector("#task-form");
    form.elements.title.value = `${button.dataset.title} 副本`;
    form.elements.project_name.value = button.dataset.project;
    form.elements.module_name.value = button.dataset.module;
    form.elements.operation.value = button.dataset.operation;
    dialog.showModal();
    form.elements.title.focus();
  });
  root.querySelectorAll(".status-pill").forEach((pill) => { const value = pill.closest("[data-task-row]")?.dataset.status; if (value) pill.textContent = STATUS_LABELS[value] || value; });
  root.querySelectorAll(".task-stage[data-stage]").forEach((stage) => { stage.textContent = STAGE_LABELS[stage.dataset.stage] || stage.dataset.stage; });
  root.querySelectorAll("time").forEach((time) => { time.title = time.textContent.trim(); time.textContent = formatTime(time.textContent.trim()); });
  updatePagination();

  const fileDrop = document.querySelector(".file-drop");
  ["dragenter", "dragover"].forEach((name) => fileDrop?.addEventListener(name, () => fileDrop.classList.add("is-dragging")));
  ["dragleave", "drop"].forEach((name) => fileDrop?.addEventListener(name, () => fileDrop.classList.remove("is-dragging")));
}

class ReviewMindmapController {
  constructor(host) {
    this.host = host;
    this.kind = host.dataset.mindmapKind;
    this.legacyRoot = document.querySelector(this.kind === "points" ? "[data-review-workbench]" : "[data-case-review-workbench]");
    this.rows = [];
    this.mindmap = null;
    this.testPoints = [];
    this.validation = { errors: [], warnings: [] };
    this.diff = {};
    this.coverage = {};
    this.selectedKey = null;
    this.selectedMeta = null;
    this.selectedKeys = new Set();
    this.clipboard = [];
    this.history = new CommandHistory();
    this.query = "";
    this.level = "";
    this.activeTab = "mindmap";
    this.viewMode = "draft";
    this.page = 1;
    this.pageSize = 100;
    this.build();
    this.bind();
  }

  build() {
    this.host.replaceChildren();
    const header = element("div", "mindmap-v2-header");
    const tabs = element("div", "mindmap-tabs");
    [["mindmap", "脑图"], ["table", "表格"], ["versions", "版本"]].forEach(([name, label]) => {
      const button = element("button", "mindmap-tab", label);
      button.type = "button";
      button.dataset.tab = name;
      button.setAttribute("role", "tab");
      tabs.append(button);
    });
    this.mode = element("span", "mindmap-mode", "当前草稿");
    header.append(tabs, this.mode);

    const toolbar = element("div", "mindmap-toolbar");
    const searchLabel = element("label", "compact-field");
    searchLabel.append(element("span", "", "搜索"));
    this.search = element("input"); this.search.type = "search"; this.search.placeholder = this.kind === "points" ? "ID、模块、场景或测试点" : "用例、测试点或模块";
    searchLabel.append(this.search);
    const levelLabel = element("label", "compact-field"); levelLabel.append(element("span", "", this.kind === "points" ? "风险" : "优先级"));
    this.levelSelect = element("select");
    ["", "P0", "P1", "P2", "P3"].forEach((value) => { const option = element("option", "", value || "全部"); option.value = value; this.levelSelect.append(option); });
    levelLabel.append(this.levelSelect);
    toolbar.append(searchLabel, levelLabel);
    [["duplicate", "复制"], ["delete", "删除"], ["undo", "撤销"], ["expand-all", "全部展开"], ["collapse-all", "全部收起"], ["zoom-out", "缩小"], ["zoom-in", "放大"], ["fit", "适应画布"]].forEach(([action, label]) => {
      const button = element("button", "secondary-button compact-button", label); button.type = "button"; button.dataset.mindmapAction = action; toolbar.append(button);
      if (action === "zoom-out") {
        this.zoomValue = element("output", "mindmap-zoom-value", "100%");
        this.zoomValue.setAttribute("aria-live", "polite");
        toolbar.append(this.zoomValue);
      }
    });
    this.notice = element("div", "mindmap-notice"); this.notice.setAttribute("role", "status");

    const layout = element("div", "mindmap-layout");
    this.canvasPane = element("section", "mindmap-canvas-pane");
    this.breadcrumb = element("nav", "mindmap-breadcrumb", "未选择节点"); this.breadcrumb.setAttribute("aria-label", "当前节点层级");
    this.canvas = element("div", "mindmap-canvas"); this.canvas.setAttribute("role", "tree"); this.canvas.setAttribute("aria-label", this.kind === "points" ? "测试点脑图" : "测试用例脑图");
    this.canvasPane.append(this.breadcrumb, this.canvas);
    this.detail = element("aside", "mindmap-detail"); this.detail.setAttribute("aria-label", "当前节点详情");
    layout.append(this.canvasPane, this.detail);

    this.tablePane = element("section", "mindmap-table-pane"); this.tablePane.hidden = true;
    this.versionPane = element("section", "mindmap-version-pane"); this.versionPane.hidden = true;
    this.host.append(header, toolbar, this.notice, layout, this.tablePane, this.versionPane);
    this.layout = layout;
    this.toolbar = toolbar;
    this.view = new MindmapView(this.canvas, {
      maxVisible: 500,
      onSelect: (meta, options) => this.select(meta, options),
      onMove: (operation) => this.move(operation),
      onCanMove: ({ sources, target }) => Boolean(target?.nodeId && sources?.every((item) => item?.nodeId && item.kind !== "root")),
      onRename: (meta, value) => this.renameNode(meta, value),
      onAdd: (meta, relation) => this.addRow(relation, meta),
      onBoxSelect: (metas) => this.selectMany(metas),
      onContext: (meta, point) => this.showContextMenu(meta, point),
      onScale: (scale) => { if (this.zoomValue) this.zoomValue.textContent = `${Math.round(scale * 100)}%`; },
      onError: (message) => this.setNotice(message, true),
    });
  }

  bind() {
    const stateEvent = this.kind === "points" ? "review-v2-state" : "case-review-v2-state";
    const requestEvent = this.kind === "points" ? "review-v2-request-state" : "case-review-v2-request-state";
    this.legacyRoot.addEventListener(stateEvent, (event) => this.acceptState(event.detail));
    this.legacyRoot.dispatchEvent(new CustomEvent(requestEvent));
    this.search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault(); this.query = this.search.value.trim(); this.searchOffset = 0; this.page = 1; this.render();
        if (this.query && !this.filtered().length) this.setNotice("未找到匹配节点", true);
      } else if (event.key === "Escape") {
        this.search.value = ""; this.query = ""; this.searchOffset = 0; this.page = 1; this.render();
      }
    });
    this.levelSelect.addEventListener("change", () => { this.level = this.levelSelect.value; this.page = 1; this.render(); });
    this.host.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => this.switchTab(button.dataset.tab)));
    this.toolbar.addEventListener("click", (event) => {
      const action = event.target.closest("[data-mindmap-action]")?.dataset.mindmapAction;
      if (action) this.handleAction(action);
    });
    this.canvas.addEventListener("keydown", (event) => this.handleShortcut(event));
    document.addEventListener("click", () => this.contextMenu?.remove());
  }

  acceptState(detail) {
    if (this.viewMode !== "draft") return;
    const values = this.kind === "points" ? detail.points : detail.cases;
    const previous = new Map(this.rows.map((row) => [this.identity(row), row.__uiKey]));
    this.rows = wrapRows(values, this.kind).map((row) => ({ ...row, __uiKey: previous.get(this.identity(row)) || this.identity(row) || row.__uiKey }));
    this.testPoints = detail.testPoints || this.testPoints;
    this.validation = detail.validation || { errors: [], warnings: [] };
    this.diff = detail.diff || {};
    this.coverage = detail.coverage || {};
    this.versions = detail.versions || this.versions || [];
    this.editable = Boolean(detail.editable);
    this.mindmap = detail.mindmap
      ? syncMindmapRows(this.kind, detail.mindmap, this.rows, this.testPoints)
      : projectMindmap(this.kind, this.rows, this.testPoints, this.host.dataset.title);
    this.render();
  }

  identity(row) {
    return String(this.kind === "points" ? row.id : row.case_id);
  }

  filtered() {
    return filterRows(this.rows, { query: this.query, level: this.level });
  }

  treeData() {
    const rows = this.filtered();
    const filteredIds = new Set(rows.map((row) => this.identity(row)));
    const projectedMindmap = structuredClone(this.mindmap || projectMindmap(this.kind, this.rows, this.testPoints, this.host.dataset.title));
    if (this.query || this.level) {
      const leafType = this.kind === "points" ? "test_point" : "case";
      const matched = projectedMindmap.nodes.filter((node) => node.node_type === leafType && filteredIds.has(String(node.binding_id || "")));
      const keep = new Set(matched.map((node) => node.node_id));
      for (const leaf of matched) projectedMindmap.nodes.filter((node) => node.parent_id === leaf.node_id).forEach((node) => keep.add(node.node_id));
      const byId = new Map(projectedMindmap.nodes.map((node) => [node.node_id, node]));
      let changed = true;
      while (changed) {
        changed = false;
        for (const nodeId of [...keep]) { const parentId = byId.get(nodeId)?.parent_id; if (parentId && parentId !== projectedMindmap.root.node_id && !keep.has(parentId)) { keep.add(parentId); changed = true; } }
      }
      projectedMindmap.nodes = projectedMindmap.nodes.filter((node) => keep.has(node.node_id));
    }
    const data = mindmapTree(projectedMindmap);
    const issues = new Map();
    [...(this.validation.errors || []), ...(this.validation.warnings || [])].forEach((issue) => {
      const row = this.rows[issue.row_index]; if (row) issues.set(this.identity(row), issue.level === "error" ? "错误" : "警告");
    });
    const rowByKey = new Map(this.rows.map((row) => [row.__uiKey, row]));
    const uncovered = new Set(this.coverage.uncovered_test_point_ids || []);
    flattenTree(data.nodeData).forEach((node) => {
      if (node.meta.uiKey && ["point", "test_point", "case"].includes(node.meta.kind)) {
        const row = rowByKey.get(node.meta.uiKey);
        if (row) node.meta.statusLabel = [row.risk_level || row.priority, issues.get(this.identity(row))].filter(Boolean).join(" · ");
      }
      if (this.kind === "cases" && node.meta.kind === "test_point") {
        node.meta.statusLabel = uncovered.has(node.meta.pointId) ? "未覆盖" : "已覆盖";
      }
    });
    this.nodeIdByUiKey = new Map(flattenTree(data.nodeData)
      .filter((node) => node.meta.uiKey && ["point", "test_point", "case"].includes(node.meta.kind))
      .map((node) => [node.meta.uiKey, node.id]));
    const projected = flattenTree(data.nodeData).length;
    if (projected > 500) {
      data.nodeData.children.forEach((node) => { node.expanded = false; });
      this.setNotice("节点超过500个，已按模块折叠；可使用搜索缩小范围", false);
    } else if (projected > (this.kind === "points" ? 60 : 24)) {
      const foldKind = this.kind === "points" ? "scenario" : "test_point";
      const branches = flattenTree(data.nodeData).filter((node) => node.meta.kind === foldKind);
      branches.forEach((node) => { node.expanded = false; });
      if (branches[0]) branches[0].expanded = true;
      this.setNotice("数据量较大，已展开一个代表分组；可逐层展开或使用搜索定位", false);
    } else {
      this.setNotice("", false);
    }
    return data;
  }

  render() {
    this.host.querySelectorAll("[data-tab]").forEach((button) => {
      const active = button.dataset.tab === this.activeTab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
    });
    if (this.activeTab === "mindmap") {
      this.view.render(this.treeData());
      setTimeout(() => { this.view.markSelected(this.selectedKeys); if (this.query) this.view.find(this.query, this.searchOffset || 0); }, 0);
    }
    if (this.activeTab === "table") this.renderTable();
    if (this.activeTab === "versions") this.renderVersions();
    this.renderDetail();
    this.updateButtons();
  }

  switchTab(tab) {
    this.activeTab = tab;
    this.layout.hidden = tab !== "mindmap";
    this.toolbar.hidden = tab !== "mindmap";
    this.tablePane.hidden = tab !== "table";
    this.versionPane.hidden = tab !== "versions";
    this.render();
  }

  select(meta, options = {}) {
    this.selectedMeta = meta || null;
    this.selectedKey = meta?.uiKey || null;
    if (!options.toggle) this.selectedKeys.clear();
    if (meta?.uiKey) {
      if (options.toggle && this.selectedKeys.has(meta.uiKey)) this.selectedKeys.delete(meta.uiKey);
      else this.selectedKeys.add(meta.uiKey);
    }
    this.renderBreadcrumb();
    this.renderDetail();
    this.syncSelection();
    this.view.markSelected(this.selectedKeys);
    if (meta?.kind === "case" && options.revealDetails) this.view.expand(this.nodeIdByUiKey?.get(meta.uiKey), true);
  }

  selectMany(metas) {
    const compatible = metas.filter((meta) => meta?.uiKey);
    this.selectedKeys = new Set(compatible.map((meta) => meta.uiKey));
    const last = compatible.at(-1); this.selectedMeta = last || null; this.selectedKey = last?.uiKey || null;
    this.renderBreadcrumb(); this.renderDetail(); this.syncSelection();
    this.setNotice(this.selectedKeys.size ? `已选择 ${this.selectedKeys.size} 个节点` : "未选择节点", false);
  }

  renderBreadcrumb() {
    const meta = this.selectedMeta;
    if (!meta) { this.breadcrumb.textContent = "未选择节点"; return; }
    const parts = this.kind === "points"
      ? [meta.module, meta.feature, meta.scenario, meta.value || this.current()?.test_point]
      : [meta.module, meta.feature, meta.pointId, meta.value || this.current()?.case_name];
    this.breadcrumb.textContent = parts.filter(Boolean).join(" / ") || "任务根节点";
  }

  current() {
    return this.rows.find((row) => row.__uiKey === this.selectedKey) || null;
  }

  renderDetail() {
    this.detail.replaceChildren();
    const row = this.current();
    const group = !row && this.selectedMeta && ["module", "feature", "scenario", "test_point"].includes(this.selectedMeta.kind)
      ? this.selectedMeta : null;
    if (group) {
      this.detail.append(element("h3", "", `${group.kind} 分组`));
      const label = element("label", "mindmap-field"); label.append(element("span", "", "名称"));
      const input = element("input"); input.value = group.value || "";
      input.disabled = !this.editable || this.viewMode !== "draft";
      input.addEventListener("change", () => this.renameGroup(group, input.value));
      label.append(input); this.detail.append(label);
      const count = this.groupKeys(group).length;
      this.detail.append(element("p", "muted", group.kind === "test_point"
        ? `输入另一个已确认测试点的 ID 或名称，将同步重新关联 ${count} 条用例。`
        : `该操作将同步影响 ${count} 条${this.kind === "points" ? "测试点" : "用例"}。`));
      return;
    }
    if (!row) {
      this.detail.append(element("h3", "", "节点详情"), element("p", "muted", "选择一个叶子节点查看和修改内容。"));
      return;
    }
    this.detail.append(element("h3", "", this.identity(row) || "未命名节点"));
    const controls = new Map();
    const fields = this.kind === "points"
      ? ["id", "module", "feature", "scenario", "test_point", "risk_level"]
      : ["case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result"];
    fields.forEach((field) => {
      const label = element("label", "mindmap-field"); label.append(element("span", "", field));
      const complex = ["test_point", "preconditions", "test_steps", "test_data", "expected_result", "actual_result"].includes(field);
      const control = element(complex ? "textarea" : (field === "risk_level" || field === "priority" ? "select" : "input"));
      if (control.tagName === "SELECT") ["P0", "P1", "P2", "P3"].forEach((value) => { const option = element("option", "", value); option.value = value; control.append(option); });
      const value = row[field];
      control.value = Array.isArray(value) ? value.join("\n") : (field === "test_data" && typeof value === "object" ? JSON.stringify(value, null, 2) : String(value ?? ""));
      control.disabled = !this.editable || this.viewMode !== "draft" || field === "actual_result";
      controls.set(field, control);
      label.append(control); this.detail.append(label);
    });
    if (this.editable && this.viewMode === "draft") {
      const apply = element("button", "primary-button", "应用节点修改"); apply.type = "button";
      apply.addEventListener("click", () => this.applyDetail(controls));
      this.detail.append(apply);
    }
  }

  applyDetail(controls) {
    if (!this.current()) return;
    const updates = {};
    for (const [field, control] of controls) {
      if (field === "actual_result") continue;
      let value = control.value;
      if (["preconditions", "test_steps"].includes(field)) value = value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
      if (field === "test_data") {
        try { value = JSON.parse(value || "{}"); }
        catch (_error) { value = control.value; this.setNotice("测试数据不是 JSON，将按普通文本保存并在发布前提示", false); }
      }
      updates[field] = value;
    }
    this.execute({ type: "update", uiKey: this.selectedKey, updates, label: "修改节点详情" });
  }

  groupMatch(meta) {
    /** 将树分组转换为平面字段匹配，禁止依赖脑图库导出的树数据。 */
    if (meta.kind === "module") return { module: meta.value };
    if (meta.kind === "feature") return { module: meta.module, feature: meta.value };
    if (meta.kind === "test_point") return { test_point_id: meta.pointId };
    return { module: meta.module, feature: meta.feature, scenario: meta.value };
  }

  groupKeys(meta) {
    const match = this.groupMatch(meta);
    return this.rows.filter((row) => Object.entries(match).every(([key, value]) => row[key] === value)).map((row) => row.__uiKey);
  }

  renameGroup(meta, value) {
    if (this.kind === "cases" && meta.kind === "test_point") {
      const point = this.testPoints.find((item) => String(item.id) === String(value).trim() || String(item.test_point) === String(value).trim());
      if (!point) { this.setNotice("请输入已确认测试点的 ID 或完整名称", true); this.render(); return; }
      this.execute({ type: "bulk_update", match: this.groupMatch(meta), updates: { test_point_id: point.id, module: point.module, feature: point.feature, scenario: point.scenario }, label: "重新关联测试点" });
      this.selectedMeta = null;
      return;
    }
    this.execute({ type: "rename_group", field: meta.kind, match: this.groupMatch(meta), value, label: `重命名 ${meta.kind}` });
    this.selectedMeta = null;
  }

  renameNode(meta, value) {
    /** 所有可见节点统一按稳定 node_id 原位改名，再由自由树编译标准 rows。 */
    if (!this.editable || this.viewMode !== "draft") { this.render(); return; }
    if (!meta?.nodeId) { this.setNotice("节点定位信息已失效，请重新选择", true); return; }
    this.executeMindmap({ type: "rename_node", nodeId: meta.nodeId, text: value, label: "脑图内修改节点" });
  }

  execute(command) {
    if (!this.editable || this.viewMode !== "draft") return;
    try {
      const result = executeCommand(this.rows, command);
      this.rows = result.rows;
      const nextMindmap = syncMindmapRows(this.kind, this.mindmap, this.rows, this.testPoints);
      const patch = { label: result.patch.label, changes: [{ kind: "replace_state", before: { rows: applyPatch(this.rows, result.patch, true), mindmap: this.mindmap }, after: { rows: this.rows, mindmap: nextMindmap } }] };
      patch.bytes = JSON.stringify(patch.changes).length;
      this.mindmap = nextMindmap;
      this.history.push(patch);
      this.emitReplace();
      this.render();
    } catch (error) {
      this.setNotice(error.message, true);
    }
  }

  executeMindmap(command) {
    if (!this.editable || this.viewMode !== "draft") return;
    try {
      const result = executeMindmapCommand({ rows: this.rows, mindmap: this.mindmap, kind: this.kind, testPoints: this.testPoints }, command);
      this.rows = result.rows.map((row) => ({ ...row, __uiKey: this.identity(row) || row.__uiKey }));
      this.mindmap = result.mindmap;
      this.history.push(result.patch);
      this.emitReplace();
      this.render();
      if (result.issues?.length) this.setNotice(`已保存自由结构，发现 ${result.issues.length} 个待校验问题`, false);
    } catch (error) { this.setNotice(error.message, true); }
  }

  handleAction(action) {
    if (action === "fit") { this.view.fit(); return; }
    if (action === "zoom-out") { this.view.zoomBy(-0.05); return; }
    if (action === "zoom-in") { this.view.zoomBy(0.05); return; }
    if (action === "center") { this.view.center(); return; }
    if (action === "expand-all") { this.view.expandAll(true); return; }
    if (action === "collapse-all") { this.view.expandAll(false); return; }
    if (action === "fullscreen") { this.view.fullscreen(); return; }
    if (action === "focus") { this.view.focusBranch(this.nodeIdForSelection()); return; }
    if (action === "undo") { const state = this.history.undoState({ rows: this.rows, mindmap: this.mindmap }); this.rows = state.rows; this.mindmap = state.mindmap; this.emitReplace(); this.render(); return; }
    if (action === "redo") { const state = this.history.redoState({ rows: this.rows, mindmap: this.mindmap }); this.rows = state.rows; this.mindmap = state.mindmap; this.emitReplace(); this.render(); return; }
    if (["add-child", "add-sibling"].includes(action)) { this.addRow(action === "add-child" ? "child" : "sibling"); return; }
    if (action === "duplicate") {
      if (!this.selectedMeta?.nodeId) { this.setNotice("请先选择要复制的节点", true); return; }
      this.executeMindmap({ type: "duplicate_node", nodeId: this.selectedMeta.nodeId, label: "复制节点及分支" });
      return;
    }
    if (action === "normalize") {
      if (!confirm(`整理后将按推荐层级重建当前 ${this.rows.length} 条业务数据，空分组会被移除。确定继续吗？`)) return;
      this.executeMindmap({ type: "normalize_structure", label: "整理为推荐结构" });
      return;
    }
    if (action === "delete") {
      const meta = this.selectedMeta;
      if (!meta?.nodeId) { this.setNotice("请先选择要删除的节点", true); return; }
      if (meta.kind === "root") {
        if (!confirm(`删除中心根节点将清空当前草稿的 ${this.rows.length} 条业务数据，并重建空白根。历史版本和产物不受影响，确定继续吗？`)) return;
        if (!confirm("请再次确认：清空当前草稿全部节点？")) return;
        this.executeMindmap({ type: "delete_root_and_reset", title: this.kind === "points" ? "测试点" : "测试用例", label: "删除根节点并重置" });
      } else if (confirm("确定删除该节点及其全部子节点吗？")) this.executeMindmap({ type: "delete_node", nodeId: meta.nodeId, label: "删除节点" });
      this.selectedKey = null; this.selectedMeta = null; this.selectedKeys.clear();
    }
  }

  move({ sources, target, placement }) {
    const source = sources?.[0];
    if (!source?.nodeId || !target?.nodeId) { this.setNotice("拖动节点已变化，请重试", true); return; }
    this.executeMindmap({ type: "move_node", nodeId: source.nodeId, targetId: target.nodeId, placement: placement || "inside", label: "移动脑图节点" });
  }

  nodeIdForSelection() {
    if (this.selectedMeta?.nodeId) return this.selectedMeta.nodeId;
    if (this.selectedKey) return this.nodeIdByUiKey?.get(this.selectedKey);
    const entry = [...(this.view.metaById || [])].find(([, meta]) => meta === this.selectedMeta);
    return entry?.[0]?.replace(/^me/, "");
  }

  addRow(relation = "child", meta = this.selectedMeta || {}) {
    if (!this.editable || this.viewMode !== "draft") return;
    if (!meta.nodeId) meta = { ...meta, nodeId: this.mindmap.root.node_id, kind: "root" };
    const context = newRowContext(this.kind, meta, this.current(), this.testPoints);
    const ids = this.rows.map((row) => Number(/\d+/.exec(this.identity(row))?.[0] || 0));
    const next = Math.max(0, ...ids) + 1;
    let row = this.kind === "points" ? {
      id: `TP${String(next).padStart(3, "0")}`, module: context.module || "新模块", feature: context.feature || "新功能",
      scenario: context.scenario || "新场景", test_point: "新测试点", risk_level: "P2",
    } : {
      case_id: `TC${String(next).padStart(3, "0")}`, test_point_id: context.test_point_id,
      module: context.module || "", feature: context.feature || "", scenario: context.scenario || "", case_name: "新测试用例", priority: "P2",
      preconditions: [], test_steps: ["执行测试操作"], test_data: {}, expected_result: "符合预期", actual_result: "",
    };
    const nextType = relation === "sibling" ? (meta.kind === "point" ? "test_point" : meta.kind) : (this.kind === "points"
      ? ({ root: "module", module: "feature", feature: "scenario" }[meta.kind] || "test_point")
      : ({ root: "module", module: "feature", feature: "test_point" }[meta.kind] || "case"));
    if (!["test_point", "case"].includes(nextType) || (this.kind === "cases" && nextType === "test_point")) row = null;
    const label = row ? (this.kind === "points" ? row.test_point : row.case_name) : `新${({ module: "模块", feature: "功能", scenario: "场景", test_point: "测试点" })[nextType] || "节点"}`;
    this.executeMindmap({ type: "insert_node", targetId: meta.nodeId, relation, nodeType: nextType, text: label, row, label: relation === "sibling" ? "新增同级节点" : "新增子节点" });
    if (row) {
      this.selectedKey = this.identity(row); this.selectedKeys = new Set([this.selectedKey]);
      setTimeout(() => { const nodeId = this.nodeIdByUiKey?.get(this.selectedKey); this.view.focus(nodeId); this.view.edit(nodeId); }, 0);
    }
  }

  copySelection() {
    const fallback = this.selectedKey ? [this.selectedKey] : this.groupKeys(this.selectedMeta || {});
    const keys = this.selectedKeys.size ? this.selectedKeys : new Set(fallback);
    this.clipboard = cleanRows(this.rows.filter((row) => keys.has(row.__uiKey)));
    if (this.clipboard.length) this.setNotice(`已复制 ${this.clipboard.length} 个节点`, false);
  }

  pasteSelection() {
    if (!this.clipboard.length) { this.setNotice("剪贴板中没有可粘贴节点", true); return; }
    let next = Math.max(0, ...this.rows.map((row) => Number(/\d+/.exec(this.identity(row))?.[0] || 0)));
    const copies = this.clipboard.map((source) => {
      const copy = structuredClone(source); next += 1;
      copy[this.kind === "points" ? "id" : "case_id"] = `${this.kind === "points" ? "TP" : "TC"}${String(next).padStart(3, "0")}`;
      Object.assign(copy, newRowContext(this.kind, this.selectedMeta || {}, this.current(), this.testPoints));
      return copy;
    });
    this.execute({ type: "insert_many", rows: copies, label: "批量粘贴" });
  }

  showContextMenu(meta, point) {
    this.select(meta); this.contextMenu?.remove();
    const menu = element("div", "mindmap-context-menu"); menu.setAttribute("role", "menu");
    [["edit", "编辑"], ["add-child", "新增子节点"], ["add-sibling", "新增同级"], ["duplicate", "复制节点及分支"], ["toggle", "展开/收起"], ["move-parent", "移动到指定父级"], ["normalize", "整理为推荐结构"], ["focus", "聚焦分支"], ["delete", "删除"]].forEach(([action, label]) => {
      const button = element("button", "", label); button.type = "button"; button.setAttribute("role", "menuitem");
      button.addEventListener("click", () => {
        menu.remove();
        if (action === "edit") this.view.edit(this.nodeIdForSelection());
        else if (action === "toggle") this.view.toggle(this.nodeIdForSelection());
        else if (action === "move-parent") this.moveToParent();
        else this.handleAction(action);
      }); menu.append(button);
    });
    Object.assign(menu.style, { left: `${point.x}px`, top: `${point.y}px` }); document.body.append(menu); this.contextMenu = menu;
  }

  moveToParent() {
    /** 只列出当前节点类型允许的父级，提交后仍由统一领域命令执行原子校验。 */
    const source = this.selectedMeta;
    if (!source || source.kind === "root") { this.setNotice("当前节点不能移动", true); return; }
    const seen = new Set();
    const candidates = [...this.view.metaById.values()].filter((meta) => {
      const key = JSON.stringify([meta?.kind, meta?.module, meta?.feature, meta?.scenario, meta?.pointId]);
      if (!meta || seen.has(key)) return false;
      seen.add(key);
      if (this.kind === "cases") return meta.kind === "test_point" && meta.pointId !== source.pointId;
      if (source.kind === "point") return meta.kind === "scenario";
      if (source.kind === "scenario") return meta.kind === "feature";
      if (source.kind === "feature") return meta.kind === "module";
      return false;
    });
    if (!candidates.length) { this.setNotice("没有可用的目标父级", true); return; }
    const labels = candidates.map((meta, index) => `${index + 1}. ${[meta.module, meta.feature, meta.scenario, meta.label].filter(Boolean).join(" / ")}`);
    const choice = Number(prompt(`请输入目标序号：\n${labels.join("\n")}`, "1"));
    if (!Number.isInteger(choice) || choice < 1 || choice > candidates.length) return;
    const sources = source.uiKey && this.selectedKeys.size > 1
      ? this.rows.filter((row) => this.selectedKeys.has(row.__uiKey)).map((row) => ({ uiKey: row.__uiKey, kind: this.kind === "points" ? "point" : "case", pointId: row.test_point_id }))
      : [source];
    this.move({ sources, target: candidates[choice - 1], placement: "inside" });
  }

  handleShortcut(event) {
    if (event.target.matches("input,textarea,select,[contenteditable]")) return;
    const mod = event.metaKey || event.ctrlKey;
    const action = mod && event.key.toLowerCase() === "z" ? (event.shiftKey ? "redo" : "undo")
      : mod && event.key.toLowerCase() === "c" ? "copy" : mod && event.key.toLowerCase() === "v" ? "paste"
        : event.key === "Tab" ? "add-child" : event.key === "Enter" ? "add-sibling" : event.key === "F2" ? "edit"
          : ["Delete", "Backspace"].includes(event.key) ? "delete" : event.key === "0" ? "fit" : event.key === "1" ? "center" : null;
    if (action) {
      event.preventDefault();
      if (action === "copy") this.copySelection(); else if (action === "paste") this.pasteSelection();
      else if (action === "edit") this.view.edit(this.nodeIdForSelection()); else this.handleAction(action);
      return;
    }
    if (["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"].includes(event.key)) {
      event.preventDefault(); const meta = this.view.navigate(this.nodeIdForSelection(), ["ArrowUp", "ArrowLeft"].includes(event.key) ? -1 : 1); if (meta) this.select(meta);
    }
  }

  emitReplace() {
    const eventName = this.kind === "points" ? "review-v2-replace" : "case-review-v2-replace";
    this.legacyRoot.dispatchEvent(new CustomEvent(eventName, { detail: { rows: cleanRows(this.rows), mindmap: structuredClone(this.mindmap) } }));
  }

  syncSelection() {
    const eventName = this.kind === "points" ? "review-v2-selection" : "case-review-v2-selection";
    const ids = this.rows.filter((row) => this.selectedKeys.has(row.__uiKey)).map((row) => this.identity(row));
    this.legacyRoot.dispatchEvent(new CustomEvent(eventName, { detail: { ids } }));
  }

  renderTable() {
    this.tablePane.replaceChildren();
    const rows = this.filtered();
    const fields = this.kind === "points"
      ? ["id", "module", "feature", "scenario", "test_point", "risk_level"]
      : ["case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result"];
    const table = element("table", `editable-review-table ${this.kind === "cases" ? "is-case-table" : "is-point-table"}`);
    const head = element("thead"); const headRow = element("tr"); fields.forEach((field) => { const cell = element("th", "", field); cell.dataset.field = field; headRow.append(cell); }); headRow.append(element("th", "", "定位")); head.append(headRow);
    const body = element("tbody");
    const pages = Math.max(1, Math.ceil(rows.length / this.pageSize)); this.page = Math.min(this.page, pages);
    rows.slice((this.page - 1) * this.pageSize, this.page * this.pageSize).forEach((row) => {
      const tr = element("tr");
      const locate = () => {
        this.selectedKey = row.__uiKey;
        this.selectedMeta = { uiKey: row.__uiKey, kind: this.kind === "points" ? "point" : "case" };
        this.switchTab("mindmap");
        setTimeout(() => this.view.focus(this.nodeIdByUiKey?.get(row.__uiKey)), 0);
      };
      fields.forEach((field) => {
        const value = row[field];
        const cell = element("td"); cell.dataset.field = field;
        const readonly = !this.editable || this.viewMode !== "draft" || field === "actual_result";
        const multiline = ["test_point", "preconditions", "test_steps", "test_data", "expected_result", "actual_result"].includes(field);
        const control = element(field === "risk_level" || field === "priority" ? "select" : (multiline ? "textarea" : "input"));
        if (control.tagName === "SELECT") ["P0", "P1", "P2", "P3"].forEach((level) => { const option = element("option", "", level); option.value = level; control.append(option); });
        control.value = Array.isArray(value) ? value.join("\n") : (field === "test_data" && typeof value === "object" ? JSON.stringify(value) : String(value ?? ""));
        control.disabled = readonly;
        control.setAttribute("aria-label", `${this.identity(row)} ${field}`);
        let committed = false;
        const commit = () => {
          if (committed || readonly) return;
          committed = true;
          let next = control.value;
          if (["preconditions", "test_steps"].includes(field)) next = next.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
      if (field === "test_data") {
        try { next = JSON.parse(next || "{}"); }
        catch (_error) { next = control.value; this.setNotice(`${this.identity(row)} 的测试数据将按普通文本保存`, false); }
          }
          this.execute({ type: "update", uiKey: row.__uiKey, updates: { [field]: next }, label: `表格修改 ${field}` });
        };
        control.addEventListener("change", commit);
        control.addEventListener("blur", commit);
        cell.append(control); tr.append(cell);
      });
      const locateCell = element("td"); const locateButton = element("button", "secondary-button compact-button", "脑图定位"); locateButton.type = "button"; locateButton.addEventListener("click", locate); locateCell.append(locateButton); tr.append(locateCell);
      body.append(tr);
    });
    table.append(head, body);
    const wrap = element("div", "readonly-table-wrap"); wrap.append(table);
    const footer = element("div", "readonly-table-footer");
    footer.append(element("span", "", `第 ${this.page}/${pages} 页，共 ${rows.length} 条。表格与脑图实时同步，修改后仍需显式保存草稿。`));
    const pagination = element("div", "readonly-table-pagination");
    const previous = element("button", "secondary-button compact-button", "上一页"); previous.type = "button"; previous.disabled = this.page <= 1;
    const next = element("button", "secondary-button compact-button", "下一页"); next.type = "button"; next.disabled = this.page >= pages;
    previous.addEventListener("click", () => { this.page -= 1; this.renderTable(); });
    next.addEventListener("click", () => { this.page += 1; this.renderTable(); });
    pagination.append(previous, next); footer.append(pagination);
    this.tablePane.append(wrap, footer);
  }

  renderVersions() {
    this.versionPane.replaceChildren(element("h3", "", "版本查看"), element("p", "muted", "原稿和确认版本只读；返回当前草稿后才能继续编辑。"));
    const controls = element("div", "version-controls");
    const select = element("select");
    [["draft", "当前草稿"], ["generated", "模型原稿"], ...(this.versions || []).map((version) => [`confirmed:${version}`, `确认版本 v${version}`])].forEach(([value, label]) => { const option = element("option", "", label); option.value = value; select.append(option); });
    select.value = this.viewMode;
    const button = element("button", "secondary-button", "加载版本"); button.type = "button";
    button.addEventListener("click", () => this.loadVersion(select.value));
    controls.append(select, button); this.versionPane.append(controls);
  }

  async loadVersion(value) {
    if (value === "draft") {
      this.viewMode = "draft"; this.mode.textContent = "当前草稿";
      this.legacyRoot.dispatchEvent(new CustomEvent(this.kind === "points" ? "review-v2-request-state" : "case-review-v2-request-state"));
      return;
    }
    const [kind, version] = value.split(":");
    const endpoint = this.kind === "points" ? "review" : "case-review";
    try {
      const result = await globalThis.agentFetch(`/api/v1/tasks/${this.host.dataset.taskId}/${endpoint}?kind=${kind}${version ? `&version=${version}` : ""}`);
      this.rows = wrapRows(this.kind === "points" ? result.points : result.cases, this.kind);
      this.rows = this.rows.map((row) => ({ ...row, __uiKey: this.identity(row) || row.__uiKey }));
      this.mindmap = result.mindmap || projectMindmap(this.kind, this.rows, this.testPoints, this.host.dataset.title);
      this.validation = result.validation;
      this.diff = result.diff_summary || {};
      this.coverage = result.coverage || {};
      this.editable = false;
      this.viewMode = value;
      this.mode.textContent = kind === "generated" ? "模型原稿（只读）" : `确认版本 v${version}（只读）`;
      this.switchTab("mindmap");
    } catch (error) { this.setNotice(error.message, true); }
  }

  updateButtons() {
    this.host.querySelectorAll("[data-mindmap-action]").forEach((button) => {
      const action = button.dataset.mindmapAction;
      if (["fit", "zoom-in", "zoom-out", "expand-all", "collapse-all"].includes(action)) button.hidden = this.activeTab !== "mindmap";
      if (action === "undo") button.disabled = !this.history.undoStack.length;
      else if (action === "redo") button.disabled = !this.history.redoStack.length;
      else if (!["fit", "zoom-in", "zoom-out", "expand-all", "collapse-all"].includes(action)) button.disabled = !this.editable || this.viewMode !== "draft";
    });
  }

  setNotice(message, error) {
    this.notice.textContent = message;
    this.notice.classList.toggle("is-error", Boolean(error));
    this.notice.hidden = !message;
  }
}

function setupTaskWorkbench() {
  const status = document.querySelector("#task-status[data-status]");
  if (status) {
    status.title = `${status.dataset.status} · ${status.dataset.stage}`;
    status.textContent = STATUS_LABELS[status.dataset.status] || status.dataset.status;
  }
  document.querySelectorAll("[data-mindmap-kind]").forEach((host) => new ReviewMindmapController(host));
  document.querySelectorAll("[data-v2-proxy]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector(button.dataset.v2Proxy)?.click();
  }));
}

setupTaskIndex();
setupTaskWorkbench();
