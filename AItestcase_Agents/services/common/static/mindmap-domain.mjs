/**
 * 功能测试脑图的纯数据投影与命令内核。
 *
 * 业务 JSON 始终保持平面数组；本模块只生成 Mind Elixir 可消费的树，
 * 并把用户操作转换为可撤销 patch。任何以双下划线开头的字段仅存在于
 * 浏览器内，保存前会被移除。
 */

const POINT_FIELDS = ["id", "module", "feature", "scenario", "test_point", "risk_level"];
const CASE_FIELDS = [
  "case_id", "test_point_id", "module", "feature", "scenario", "case_name",
  "priority", "preconditions", "test_steps", "test_data", "expected_result", "actual_result",
];

let localSequence = 0;

function nextUiKey(prefix = "row") {
  localSequence += 1;
  return `${prefix}-${Date.now().toString(36)}-${localSequence.toString(36)}`;
}

function clone(value) {
  return globalThis.structuredClone ? structuredClone(value) : JSON.parse(JSON.stringify(value));
}

function text(value, fallback) {
  const result = String(value ?? "").trim();
  return result || fallback;
}

function nodeId(kind, parts) {
  return `${kind}:${parts.map((part) => encodeURIComponent(String(part))).join("/")}`;
}

function treeNode(id, topic, kind, meta = {}) {
  return { id, topic: text(topic, "未命名"), expanded: true, children: [], meta: { kind, ...meta } };
}

function child(parent, id, topic, kind, meta = {}) {
  let value = parent.children.find((item) => item.id === id);
  if (!value) {
    value = treeNode(id, topic, kind, meta);
    parent.children.push(value);
  }
  return value;
}

export function wrapRows(rows, kind) {
  /** 保留扩展字段并为浏览器定位补充稳定 uiKey。 */
  if (!Array.isArray(rows)) return [];
  return rows.filter((row) => row && typeof row === "object" && !Array.isArray(row)).map((row) => ({
    ...clone(row),
    __uiKey: row.__uiKey || nextUiKey(kind),
  }));
}

export function cleanRows(rows) {
  /** 移除全部浏览器私有字段，返回可提交服务端的权威 JSON。 */
  return rows.map((row) => Object.fromEntries(
    Object.entries(row).filter(([key]) => !key.startsWith("__") && !key.startsWith("_rowKey")),
  ));
}

export function projectTestPoints(rows, rootTopic = "测试点") {
  /** 将测试点平面数组投影为根、模块、功能、场景、测试点五层树。 */
  const root = treeNode("point-root", rootTopic, "root");
  for (const row of rows) {
    const moduleName = text(row.module, "未分组模块");
    const featureName = text(row.feature, "未分组功能");
    const scenarioName = text(row.scenario, "未分组场景");
    const moduleNode = child(root, nodeId("module", [moduleName]), moduleName, "module", { value: moduleName });
    const featureNode = child(moduleNode, nodeId("feature", [moduleName, featureName]), featureName, "feature", { module: moduleName, value: featureName });
    const scenarioNode = child(featureNode, nodeId("scenario", [moduleName, featureName, scenarioName]), scenarioName, "scenario", { module: moduleName, feature: featureName, value: scenarioName });
    scenarioNode.children.push(treeNode(
      nodeId("point", [row.__uiKey]),
      text(row.test_point, "未命名测试点"),
      "point",
      { uiKey: row.__uiKey, pointId: row.id },
    ));
  }
  return { nodeData: root };
}

export function projectTestCases(rows, testPoints = [], rootTopic = "测试用例") {
  /** 将用例投影为根、模块、功能、确认测试点、用例五层树。 */
  const root = treeNode("case-root", rootTopic, "root");
  const pointMap = new Map(testPoints.map((point) => [String(point.id || ""), point]));
  const orderedPointIds = [];
  for (const point of testPoints) if (point.id && !orderedPointIds.includes(String(point.id))) orderedPointIds.push(String(point.id));
  for (const row of rows) if (row.test_point_id && !orderedPointIds.includes(String(row.test_point_id))) orderedPointIds.push(String(row.test_point_id));

  for (const pointId of orderedPointIds) {
    const point = pointMap.get(pointId) || rows.find((row) => String(row.test_point_id) === pointId) || {};
    const moduleName = text(point.module, "未分组模块");
    const featureName = text(point.feature, "未分组功能");
    const pointTopic = text(point.test_point, pointId || "未命名测试点");
    const moduleNode = child(root, nodeId("case-module", [moduleName]), moduleName, "module", { value: moduleName });
    const featureNode = child(moduleNode, nodeId("case-feature", [moduleName, featureName]), featureName, "feature", { module: moduleName, value: featureName });
    const pointNode = child(featureNode, nodeId("case-point", [pointId]), pointTopic, "test_point", { module: moduleName, feature: featureName, pointId, value: pointTopic });
    const cases = rows.filter((row) => String(row.test_point_id || "") === pointId);
    for (const row of cases) {
      pointNode.children.push(treeNode(
        nodeId("case", [row.__uiKey]),
        text(row.case_name, "未命名用例"),
        "case",
        { uiKey: row.__uiKey, caseId: row.case_id, pointId },
      ));
    }
  }
  return { nodeData: root };
}

export function flattenTree(nodeData) {
  /** 以深度优先顺序返回节点，供可见节点保护和测试使用。 */
  const nodes = [];
  const visit = (node) => {
    nodes.push(node);
    if (node.expanded !== false) (node.children || []).forEach(visit);
  };
  visit(nodeData);
  return nodes;
}

export function filterRows(rows, { query = "", level = "", issueIndexes = new Set() } = {}) {
  /** 对完整数据筛选；只影响视图，不改变业务数组。 */
  const needle = String(query).trim().toLocaleLowerCase();
  return rows.filter((row, index) => {
    const fields = "case_id" in row ? CASE_FIELDS : POINT_FIELDS;
    const matchesText = !needle || fields.some((field) => JSON.stringify(row[field] ?? "").toLocaleLowerCase().includes(needle));
    const matchesLevel = !level || row.risk_level === level || row.priority === level;
    const matchesIssue = !issueIndexes.size || issueIndexes.has(index);
    return matchesText && matchesLevel && matchesIssue;
  });
}

function locate(rows, uiKey) {
  const index = rows.findIndex((row) => row.__uiKey === uiKey);
  if (index < 0) throw new Error("目标节点不存在或已被删除");
  return index;
}

function makePatch(changes, label) {
  return { label, changes, bytes: JSON.stringify(changes).length };
}

export function executeCommand(currentRows, command) {
  /**
   * 执行一条领域命令并返回新数组和增量 patch。
   * 非法命令先抛错，因此调用方的原数组不会发生半更新。
   */
  const rows = clone(currentRows);
  const type = command?.type;
  if (type === "insert") {
    const index = Math.max(0, Math.min(Number(command.index ?? rows.length), rows.length));
    const row = { ...clone(command.row), __uiKey: command.row?.__uiKey || nextUiKey("insert") };
    rows.splice(index, 0, row);
    return { rows, patch: makePatch([{ kind: "insert", index, after: row }], command.label || "新增") };
  }
  if (type === "delete") {
    const keys = new Set(command.uiKeys || []);
    const indexes = rows.map((row, index) => keys.has(row.__uiKey) ? index : -1).filter((index) => index >= 0);
    if (!indexes.length) throw new Error("请选择要删除的节点");
    const changes = indexes.map((index) => ({ kind: "delete", index, before: clone(rows[index]) }));
    for (const index of [...indexes].sort((a, b) => b - a)) rows.splice(index, 1);
    return { rows, patch: makePatch(changes, command.label || "删除") };
  }
  if (["update", "move"].includes(type)) {
    const index = locate(rows, command.uiKey);
    const before = clone(rows[index]);
    const updates = clone(command.updates || {});
    if ("actual_result" in updates && updates.actual_result !== before.actual_result) throw new Error("实际结果为只读字段");
    rows[index] = { ...rows[index], ...updates, __uiKey: before.__uiKey };
    return { rows, patch: makePatch([{ kind: "update", index, before, after: clone(rows[index]) }], command.label || "修改") };
  }
  if (type === "rename_group") {
    if (!["module", "feature", "scenario"].includes(command.field)) throw new Error("不支持的分组字段");
    const value = String(command.value || "").trim();
    if (!value) throw new Error("分组名称不能为空");
    const changes = [];
    rows.forEach((row, index) => {
      const match = Object.entries(command.match || {}).every(([key, expected]) => row[key] === expected);
      if (!match) return;
      const before = clone(row);
      rows[index] = { ...row, [command.field]: value };
      changes.push({ kind: "update", index, before, after: clone(rows[index]) });
    });
    if (!changes.length) throw new Error("分组已变化，请刷新后重试");
    return { rows, patch: makePatch(changes, command.label || "重命名分组") };
  }
  if (type === "bulk_update") {
    const updates = clone(command.updates || {});
    if ("actual_result" in updates) throw new Error("实际结果为只读字段");
    const changes = [];
    rows.forEach((row, index) => {
      const matched = Object.entries(command.match || {}).every(([key, expected]) => row[key] === expected);
      if (!matched) return;
      const before = clone(row);
      rows[index] = { ...row, ...updates, __uiKey: before.__uiKey };
      changes.push({ kind: "update", index, before, after: clone(rows[index]) });
    });
    if (!changes.length) throw new Error("分组已变化，请刷新后重试");
    return { rows, patch: makePatch(changes, command.label || "批量修改") };
  }
  throw new Error("不支持的脑图操作");
}

export function applyPatch(currentRows, patch, reverse = false) {
  /** 应用或反向应用增量 patch；用于浏览器撤销/重做。 */
  const rows = clone(currentRows);
  const changes = reverse ? [...patch.changes].reverse() : patch.changes;
  for (const change of changes) {
    if (change.kind === "insert") reverse ? rows.splice(change.index, 1) : rows.splice(change.index, 0, clone(change.after));
    if (change.kind === "delete") reverse ? rows.splice(change.index, 0, clone(change.before)) : rows.splice(change.index, 1);
    if (change.kind === "update") rows[change.index] = clone(reverse ? change.before : change.after);
  }
  return rows;
}

export class CommandHistory {
  /** 最多保存50步且不超过20 MiB，超限时丢弃最旧记录。 */
  constructor(maxSteps = 50, maxBytes = 20 * 1024 * 1024) {
    this.maxSteps = maxSteps;
    this.maxBytes = maxBytes;
    this.undoStack = [];
    this.redoStack = [];
    this.bytes = 0;
  }

  push(patch) {
    if (!patch || patch.bytes > this.maxBytes) throw new Error("本次批量操作过大，请缩小范围");
    this.undoStack.push(patch);
    this.redoStack = [];
    this.bytes += patch.bytes;
    while (this.undoStack.length > this.maxSteps || this.bytes > this.maxBytes) {
      this.bytes -= this.undoStack.shift().bytes;
    }
  }

  undo(rows) {
    const patch = this.undoStack.pop();
    if (!patch) return rows;
    this.bytes -= patch.bytes;
    this.redoStack.push(patch);
    return applyPatch(rows, patch, true);
  }

  redo(rows) {
    const patch = this.redoStack.pop();
    if (!patch) return rows;
    this.undoStack.push(patch);
    this.bytes += patch.bytes;
    return applyPatch(rows, patch, false);
  }
}
