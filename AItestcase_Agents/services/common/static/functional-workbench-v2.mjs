import {
  CommandHistory,
  cleanRows,
  executeCommand,
  filterRows,
  flattenTree,
  projectTestCases,
  projectTestPoints,
  wrapRows,
} from "./mindmap-domain.mjs";
import { MindmapView } from "./mindmap-view.mjs";

const base = document.body.dataset.basePath;
const STATUS_LABELS = {
  pending: "排队中", running: "生成中", waiting_review: "测试点待评审", waiting_case_review: "用例待评审",
  succeeded: "已完成", partial_success: "部分完成", failed: "失败", cancelled: "已取消",
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
  const rows = [...root.querySelectorAll("[data-task-row]")];
  rows.forEach((row) => {
    const pill = row.querySelector(".status-pill");
    if (pill) pill.textContent = STATUS_LABELS[row.dataset.status] || row.dataset.status;
  });
  root.querySelectorAll("time").forEach((time) => {
    time.title = time.textContent.trim();
    time.textContent = formatTime(time.textContent.trim());
  });
  const apply = () => {
    const query = search.value.trim().toLocaleLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      const matched = (!query || row.dataset.search.includes(query))
        && (!status.value || row.dataset.status === status.value)
        && (!date.value || row.dataset.date === date.value);
      row.hidden = !matched;
      if (matched) visible += 1;
    });
    document.querySelector("#task-list-empty-filter").hidden = visible > 0;
  };
  [search, status, date].forEach((control) => control?.addEventListener("input", apply));
  root.querySelectorAll("[data-copy-task]").forEach((button) => button.addEventListener("click", () => {
    const form = document.querySelector("#task-form");
    form.elements.title.value = `${button.dataset.title} 副本`;
    form.elements.project_name.value = button.dataset.project;
    form.elements.module_name.value = button.dataset.module;
    form.elements.operation.value = button.dataset.operation;
    dialog.showModal();
    form.elements.title.focus();
  }));
}

class ReviewMindmapController {
  constructor(host) {
    this.host = host;
    this.kind = host.dataset.mindmapKind;
    this.legacyRoot = document.querySelector(this.kind === "points" ? "[data-review-workbench]" : "[data-case-review-workbench]");
    this.rows = [];
    this.testPoints = [];
    this.validation = { errors: [], warnings: [] };
    this.diff = {};
    this.coverage = {};
    this.selectedKey = null;
    this.selectedMeta = null;
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
    [["add", this.kind === "points" ? "新增测试点" : "新增用例"], ["duplicate", "复制"], ["delete", "删除"], ["undo", "撤销"], ["redo", "重做"], ["fit", "适应画布"]].forEach(([action, label]) => {
      const button = element("button", "secondary-button compact-button", label); button.type = "button"; button.dataset.mindmapAction = action; toolbar.append(button);
    });
    this.notice = element("div", "mindmap-notice"); this.notice.setAttribute("role", "status");

    const layout = element("div", "mindmap-layout");
    this.canvasPane = element("section", "mindmap-canvas-pane");
    this.canvas = element("div", "mindmap-canvas"); this.canvas.setAttribute("role", "tree"); this.canvas.setAttribute("aria-label", this.kind === "points" ? "测试点脑图" : "测试用例脑图");
    this.canvasPane.append(this.canvas);
    this.detail = element("aside", "mindmap-detail"); this.detail.setAttribute("aria-label", "当前节点详情");
    layout.append(this.canvasPane, this.detail);

    this.tablePane = element("section", "mindmap-table-pane"); this.tablePane.hidden = true;
    this.versionPane = element("section", "mindmap-version-pane"); this.versionPane.hidden = true;
    this.host.append(header, toolbar, this.notice, layout, this.tablePane, this.versionPane);
    this.layout = layout;
    this.toolbar = toolbar;
    this.view = new MindmapView(this.canvas, {
      maxVisible: 500,
      onSelect: (meta) => this.select(meta),
      onMove: (operation) => this.move(operation),
      onRename: (meta, value) => this.renameNode(meta, value),
      onError: (message) => this.setNotice(message, true),
    });
  }

  bind() {
    const stateEvent = this.kind === "points" ? "review-v2-state" : "case-review-v2-state";
    const requestEvent = this.kind === "points" ? "review-v2-request-state" : "case-review-v2-request-state";
    this.legacyRoot.addEventListener(stateEvent, (event) => this.acceptState(event.detail));
    this.legacyRoot.dispatchEvent(new CustomEvent(requestEvent));
    this.search.addEventListener("input", () => { this.query = this.search.value; this.page = 1; this.render(); });
    this.levelSelect.addEventListener("change", () => { this.level = this.levelSelect.value; this.page = 1; this.render(); });
    this.host.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => this.switchTab(button.dataset.tab)));
    this.toolbar.addEventListener("click", (event) => {
      const action = event.target.closest("[data-mindmap-action]")?.dataset.mindmapAction;
      if (action) this.handleAction(action);
    });
  }

  acceptState(detail) {
    if (this.viewMode !== "draft") return;
    const values = this.kind === "points" ? detail.points : detail.cases;
    const previous = new Map(this.rows.map((row) => [this.identity(row), row.__uiKey]));
    this.rows = wrapRows(values, this.kind).map((row) => ({ ...row, __uiKey: previous.get(this.identity(row)) || row.__uiKey }));
    this.testPoints = detail.testPoints || this.testPoints;
    this.validation = detail.validation || { errors: [], warnings: [] };
    this.diff = detail.diff || {};
    this.coverage = detail.coverage || {};
    this.versions = detail.versions || this.versions || [];
    this.editable = Boolean(detail.editable);
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
    const data = this.kind === "points"
      ? projectTestPoints(rows, this.host.dataset.title || "测试点")
      : projectTestCases(rows, this.testPoints, this.host.dataset.title || "测试用例");
    this.nodeIdByUiKey = new Map(flattenTree(data.nodeData).filter((node) => node.meta.uiKey).map((node) => [node.meta.uiKey, node.id]));
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
    if (this.activeTab === "mindmap") this.view.render(this.treeData());
    if (this.activeTab === "table") this.renderTable();
    if (this.activeTab === "versions") this.renderVersions();
    this.renderDetail();
    this.updateButtons();
  }

  switchTab(tab) {
    this.activeTab = tab;
    this.layout.hidden = tab !== "mindmap";
    this.toolbar.hidden = tab === "versions";
    this.tablePane.hidden = tab !== "table";
    this.versionPane.hidden = tab !== "versions";
    this.render();
  }

  select(meta) {
    this.selectedMeta = meta || null;
    this.selectedKey = meta?.uiKey || null;
    this.renderDetail();
    this.syncSelection();
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
        catch (_error) { this.setNotice("测试数据必须是合法 JSON", true); return; }
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
    /** 脑图双击编辑与详情面板共用领域命令和撤销栈。根节点仅是任务容器，不属于测试资产。 */
    if (!this.editable || this.viewMode !== "draft") { this.render(); return; }
    if (meta?.uiKey) {
      this.execute({ type: "update", uiKey: meta.uiKey, updates: { [this.kind === "points" ? "test_point" : "case_name"]: value }, label: "脑图内修改节点" });
      return;
    }
    if (["module", "feature", "scenario", "test_point"].includes(meta?.kind)) this.renameGroup(meta, value);
    else { this.setNotice("根节点是任务标题，请在任务信息中维护", true); this.render(); }
  }

  execute(command) {
    if (!this.editable || this.viewMode !== "draft") return;
    try {
      const result = executeCommand(this.rows, command);
      this.rows = result.rows;
      this.history.push(result.patch);
      this.emitReplace();
      this.render();
    } catch (error) {
      this.setNotice(error.message, true);
    }
  }

  handleAction(action) {
    if (action === "fit") { this.view.fit(); return; }
    if (action === "undo") { this.rows = this.history.undo(this.rows); this.emitReplace(); this.render(); return; }
    if (action === "redo") { this.rows = this.history.redo(this.rows); this.emitReplace(); this.render(); return; }
    if (action === "add") {
      const current = this.current() || {};
      const ids = this.rows.map((row) => Number(/\d+/.exec(this.identity(row))?.[0] || 0));
      const next = Math.max(0, ...ids) + 1;
      const row = this.kind === "points" ? {
        id: `TP${String(next).padStart(3, "0")}`, module: current.module || "新模块", feature: current.feature || "新功能",
        scenario: current.scenario || "新场景", test_point: "新测试点", risk_level: "P2",
      } : {
        case_id: `TC${String(next).padStart(3, "0")}`, test_point_id: current.test_point_id || this.testPoints[0]?.id || "",
        module: current.module || this.testPoints[0]?.module || "", feature: current.feature || this.testPoints[0]?.feature || "",
        scenario: current.scenario || this.testPoints[0]?.scenario || "", case_name: "新测试用例", priority: "P2",
        preconditions: [], test_steps: ["执行测试操作"], test_data: {}, expected_result: "符合预期", actual_result: "",
      };
      this.execute({ type: "insert", row, label: "新增" });
      this.selectedKey = this.rows[this.rows.length - 1]?.__uiKey;
      return;
    }
    if (!this.current()) {
      if (action === "delete" && this.kind === "points" && this.selectedMeta && ["module", "feature", "scenario"].includes(this.selectedMeta.kind)) {
        const keys = this.groupKeys(this.selectedMeta);
        if (keys.length && confirm(`确定删除该分组及其 ${keys.length} 条测试点吗？`)) {
          this.execute({ type: "delete", uiKeys: keys, label: "删除分组" });
          this.selectedMeta = null;
        }
        return;
      }
      this.setNotice("请先选择一个可编辑节点", true);
      return;
    }
    if (action === "duplicate") {
      const copy = cleanRows([this.current()])[0];
      const ids = this.rows.map((row) => Number(/\d+/.exec(this.identity(row))?.[0] || 0));
      const next = Math.max(0, ...ids) + 1;
      copy[this.kind === "points" ? "id" : "case_id"] = `${this.kind === "points" ? "TP" : "TC"}${String(next).padStart(3, "0")}`;
      this.execute({ type: "insert", row: copy, label: "复制" });
    }
    if (action === "delete") {
      if (confirm(`确定删除 ${this.identity(this.current())} 吗？`)) this.execute({ type: "delete", uiKeys: [this.selectedKey], label: "删除" });
    }
  }

  move({ sources, target }) {
    const source = sources.find((item) => item.uiKey);
    if (!source) return;
    if (this.kind === "points" && target.kind === "scenario") {
      this.execute({ type: "move", uiKey: source.uiKey, updates: { module: target.module, feature: target.feature, scenario: target.value }, label: "移动测试点" });
    } else if (this.kind === "cases" && target.kind === "test_point") {
      const point = this.testPoints.find((item) => String(item.id) === String(target.pointId));
      if (point) this.execute({ type: "move", uiKey: source.uiKey, updates: { test_point_id: point.id, module: point.module, feature: point.feature, scenario: point.scenario }, label: "移动用例" });
    } else {
      this.setNotice("只能把测试点移动到场景，或把用例移动到已确认测试点", true);
    }
  }

  emitReplace() {
    const eventName = this.kind === "points" ? "review-v2-replace" : "case-review-v2-replace";
    this.legacyRoot.dispatchEvent(new CustomEvent(eventName, { detail: { rows: cleanRows(this.rows) } }));
  }

  syncSelection() {
    const eventName = this.kind === "points" ? "review-v2-selection" : "case-review-v2-selection";
    const row = this.current();
    this.legacyRoot.dispatchEvent(new CustomEvent(eventName, { detail: { ids: row ? [this.identity(row)] : [] } }));
  }

  renderTable() {
    this.tablePane.replaceChildren();
    const rows = this.filtered();
    const fields = this.kind === "points"
      ? ["id", "module", "feature", "scenario", "test_point", "risk_level"]
      : ["case_id", "test_point_id", "module", "feature", "scenario", "case_name", "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result"];
    const table = element("table", "editable-review-table");
    const head = element("thead"); const headRow = element("tr"); fields.forEach((field) => headRow.append(element("th", "", field))); headRow.append(element("th", "", "定位")); head.append(headRow);
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
        const cell = element("td");
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
            catch (_error) { committed = false; this.setNotice(`${this.identity(row)} 的测试数据必须是合法 JSON`, true); control.focus(); return; }
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
      if (action === "undo") button.disabled = !this.history.undoStack.length;
      else if (action === "redo") button.disabled = !this.history.redoStack.length;
      else if (action !== "fit") button.disabled = !this.editable || this.viewMode !== "draft";
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
