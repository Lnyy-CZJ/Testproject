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
      { uiKey: row.__uiKey, pointId: row.id, module: moduleName, feature: featureName, scenario: scenarioName },
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
      const caseNode = treeNode(
        nodeId("case", [row.__uiKey]),
        text(row.case_name, "未命名用例"),
        "case",
        { uiKey: row.__uiKey, caseId: row.case_id, pointId, module: moduleName, feature: featureName },
      );
      caseNode.expanded = false;
      const details = [
        ["preconditions", contentText(row.preconditions)],
        ["test_steps", stepsText(row.test_steps)],
        ["expected_result", contentText(row.expected_result)],
        ["test_data", testDataText(row.test_data)],
      ];
      for (const [field, value] of details) caseNode.children.push(treeNode(
        nodeId("case-content", [row.__uiKey, field]), value || "点击补充", "case_content",
        { uiKey: row.__uiKey, detailField: field, caseId: row.case_id },
      ));
      pointNode.children.push(caseNode);
    }
  }
  return { nodeData: root };
}

function contentText(value) {
  if (Array.isArray(value)) return value.map((item) => String(item ?? "").trim()).filter(Boolean).join("\n");
  return String(value ?? "").trim();
}

function stepsText(value) {
  const items = Array.isArray(value) ? value : contentText(value).split(/\r?\n/).filter(Boolean);
  return items.map((item, index) => `${index + 1}. ${String(item).replace(/^\d+[.、]\s*/, "").trim()}`).join("\n");
}

function testDataText(value) {
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "").trim();
}

function businessId(kind, row) {
  return String(row[kind === "points" ? "id" : "case_id"] || row.__uiKey || nextUiKey(kind));
}

function flatNode(nodeType, parentId, order, value, bindingId = null) {
  return {
    node_id: `node_${nodeType}_${nextUiKey("mm")}`,
    node_type: nodeType,
    parent_id: parentId,
    order,
    binding_id: bindingId,
    text: String(value ?? ""),
  };
}

export function projectMindmap(kind, rows, testPoints = [], rootTopic = "") {
  /** 将旧 rows 按推荐层级投影为可持久化的自由脑图；不会修改传入记录。 */
  const root = { node_id: `root_${kind}`, node_type: "root", text: rootTopic || (kind === "points" ? "测试点" : "测试用例") };
  const nodes = [];
  const groups = new Map();
  const ensure = (nodeType, parentId, value, key, bindingId = null) => {
    if (groups.has(key)) return groups.get(key);
    const node = flatNode(nodeType, parentId, nodes.filter((item) => item.parent_id === parentId).length, value, bindingId);
    nodes.push(node); groups.set(key, node); return node;
  };
  for (const row of rows) {
    const moduleName = String(row.module ?? "");
    const featureName = String(row.feature ?? "");
    const moduleNode = ensure("module", root.node_id, moduleName || "未分组模块", `m:${moduleName}`);
    const featureNode = ensure("feature", moduleNode.node_id, featureName || "未分组功能", `f:${moduleName}:${featureName}`);
    if (kind === "points") {
      const scenarioName = String(row.scenario ?? "");
      const scenarioNode = ensure("scenario", featureNode.node_id, scenarioName || "未分组场景", `s:${moduleName}:${featureName}:${scenarioName}`);
      nodes.push(flatNode("test_point", scenarioNode.node_id, nodes.filter((item) => item.parent_id === scenarioNode.node_id).length, row.test_point || "未命名测试点", businessId(kind, row)));
      continue;
    }
    const pointId = String(row.test_point_id || "");
    const point = testPoints.find((item) => String(item.id || "") === pointId) || {};
    const pointNode = ensure("test_point", featureNode.node_id, point.test_point || pointId || "未关联测试点", `p:${moduleName}:${featureName}:${pointId}`, pointId || null);
    const caseNode = flatNode("case", pointNode.node_id, nodes.filter((item) => item.parent_id === pointNode.node_id).length, row.case_name || "未命名用例", businessId(kind, row));
    nodes.push(caseNode);
    [
      ["preconditions_content", contentText(row.preconditions)],
      ["steps_content", stepsText(row.test_steps)],
      ["expected_content", contentText(row.expected_result)],
      ["test_data_content", testDataText(row.test_data)],
    ].forEach(([nodeType, value], order) => nodes.push(flatNode(nodeType, caseNode.node_id, order, value, businessId(kind, row))));
  }
  return { root, nodes };
}

function mindmapIndex(mindmap) {
  const all = [mindmap.root, ...(mindmap.nodes || [])];
  const byId = new Map(all.map((node) => [node.node_id, node]));
  if (!mindmap.root?.node_id || byId.size !== all.length) throw new Error("脑图节点 ID 重复或根节点缺失");
  for (const node of mindmap.nodes || []) if (!byId.has(node.parent_id)) throw new Error("脑图存在孤立节点");
  return byId;
}

function ancestorOfType(node, type, byId) {
  let current = node;
  const seen = new Set();
  while (current && !seen.has(current.node_id)) {
    if (current.node_type === type) return current;
    seen.add(current.node_id); current = byId.get(current.parent_id);
  }
  return null;
}

function rowSource(kind, rows, bindingId) {
  const field = kind === "points" ? "id" : "case_id";
  return rows.find((row) => String(row[field] || "") === String(bindingId || "")) || {};
}

export function compileMindmapRows(kind, mindmap, sourceRows = []) {
  /** 从自由树确定性编译标准 rows；非推荐层级只产生可定位的质量问题。 */
  const byId = mindmapIndex(mindmap);
  const nodes = [...(mindmap.nodes || [])].sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
  const issues = [];
  const rows = [];
  const expectedParent = {
    module: "root", feature: "module", scenario: "feature", test_point: kind === "points" ? "scenario" : "feature",
    case: "test_point", preconditions_content: "case", steps_content: "case", expected_content: "case", test_data_content: "case",
  };
  for (const node of nodes) {
    const parent = byId.get(node.parent_id);
    if (expectedParent[node.node_type] && parent?.node_type !== expectedParent[node.node_type]) issues.push({
      level: "warning", code: "MINDMAP_HIERARCHY_INVALID", node_id: node.node_id,
      field: "parent_id", message: `${node.node_type} 位于非推荐层级`,
    });
  }
  const leaves = nodes.filter((node) => node.node_type === (kind === "points" ? "test_point" : "case"));
  for (const leaf of leaves) {
    const source = clone(rowSource(kind, sourceRows, leaf.binding_id));
    const moduleNode = ancestorOfType(leaf, "module", byId);
    const featureNode = ancestorOfType(leaf, "feature", byId);
    const scenarioNode = ancestorOfType(leaf, "scenario", byId);
    if (kind === "points") rows.push({
      ...source,
      id: source.id ?? leaf.binding_id ?? "",
      module: moduleNode?.text ?? "", feature: featureNode?.text ?? "", scenario: scenarioNode?.text ?? "",
      test_point: leaf.text ?? "", risk_level: source.risk_level ?? "",
    });
    else {
      const pointNode = ancestorOfType(leaf, "test_point", byId);
      const children = nodes.filter((node) => node.parent_id === leaf.node_id);
      const value = (type) => children.find((node) => node.node_type === type)?.text ?? "";
      const lines = (raw) => String(raw || "").split(/\r?\n/).map((item) => item.replace(/^\d+[.、]\s*/, "").trim()).filter(Boolean);
      const rawData = value("test_data_content");
      let testData = rawData;
      try { testData = rawData.trim() ? JSON.parse(rawData) : {}; }
      catch (_error) { issues.push({ level: "warning", code: "CASE_TEST_DATA_TEXT", node_id: children.find((node) => node.node_type === "test_data_content")?.node_id, field: "test_data", message: "测试数据不是 JSON，将按文本发布" }); }
      rows.push({
        ...source,
        case_id: source.case_id ?? leaf.binding_id ?? "", test_point_id: pointNode?.binding_id ?? source.test_point_id ?? "",
        module: moduleNode?.text ?? "", feature: featureNode?.text ?? "", scenario: scenarioNode?.text ?? source.scenario ?? "",
        case_name: leaf.text ?? "", priority: source.priority ?? "", preconditions: lines(value("preconditions_content")),
        test_steps: lines(value("steps_content")), test_data: testData, expected_result: value("expected_content"),
        actual_result: source.actual_result ?? "",
      });
    }
  }
  return { rows: wrapRows(rows, kind), issues };
}

export function mindmapTree(mindmap) {
  /** 把持久化平面节点转换为 Mind Elixir 树，并保留稳定 node_id 供命令定位。 */
  const byParent = new Map();
  for (const node of mindmap.nodes || []) byParent.set(node.parent_id, [...(byParent.get(node.parent_id) || []), node]);
  const build = (node) => ({
    id: node.node_id, topic: text(node.text, node.node_type === "root" ? "未命名脑图" : "点击补充"), expanded: node.node_type === "case" ? false : true,
    children: (byParent.get(node.node_id) || []).sort((a, b) => Number(a.order || 0) - Number(b.order || 0)).map(build),
    meta: {
      kind: node.node_type === "test_point" && !(byParent.get(node.node_id) || []).some((childNode) => childNode.node_type === "case") ? "point" : node.node_type,
      nodeId: node.node_id, bindingId: node.binding_id, uiKey: node.binding_id,
      label: String(node.text ?? ""),
      detailField: ({ preconditions_content: "preconditions", steps_content: "test_steps", expected_content: "expected_result", test_data_content: "test_data" })[node.node_type],
    },
  });
  return { nodeData: build(mindmap.root) };
}

export function syncMindmapRows(kind, mindmap, rows, testPoints = []) {
  /** 将表格/详情对 rows 的修改同步回现有自由树，尽量保留用户自定义层级与空分组。 */
  const updated = clone(mindmap);
  const idField = kind === "points" ? "id" : "case_id";
  const live = new Map(rows.map((row) => [String(row[idField] || ""), row]));
  const leafType = kind === "points" ? "test_point" : "case";
  const bound = new Set(updated.nodes.filter((node) => node.node_type === leafType).map((node) => String(node.binding_id || "")));
  const missing = rows.filter((row) => !bound.has(String(row[idField] || "")));
  if (missing.length) {
    const addition = projectMindmap(kind, missing, testPoints, updated.root.text);
    const remap = new Map([[addition.root.node_id, updated.root.node_id]]);
    for (const node of addition.nodes) {
      const copy = clone(node);
      copy.parent_id = remap.get(copy.parent_id) || copy.parent_id;
      if (updated.nodes.some((item) => item.node_id === copy.node_id)) copy.node_id = `${copy.node_id}_${nextUiKey("merge")}`;
      remap.set(node.node_id, copy.node_id);
      updated.nodes.push(copy);
    }
  }
  const removed = new Set(updated.nodes.filter((node) => node.node_type === leafType && !live.has(String(node.binding_id || ""))).map((node) => node.node_id));
  let changed = true;
  while (changed) { changed = false; for (const node of updated.nodes) if (removed.has(node.parent_id) && !removed.has(node.node_id)) { removed.add(node.node_id); changed = true; } }
  updated.nodes = updated.nodes.filter((node) => !removed.has(node.node_id));
  const byId = new Map([updated.root, ...updated.nodes].map((node) => [node.node_id, node]));
  for (const leaf of updated.nodes.filter((node) => node.node_type === leafType)) {
    const row = live.get(String(leaf.binding_id || "")); if (!row) continue;
    leaf.text = String(row[kind === "points" ? "test_point" : "case_name"] ?? "");
    const moduleNode = ancestorOfType(leaf, "module", byId); if (moduleNode) moduleNode.text = String(row.module ?? "");
    const featureNode = ancestorOfType(leaf, "feature", byId); if (featureNode) featureNode.text = String(row.feature ?? "");
    const scenarioNode = ancestorOfType(leaf, "scenario", byId); if (scenarioNode) scenarioNode.text = String(row.scenario ?? "");
    if (kind === "cases") {
      const values = {
        preconditions_content: contentText(row.preconditions), steps_content: stepsText(row.test_steps),
        expected_content: contentText(row.expected_result), test_data_content: testDataText(row.test_data),
      };
      updated.nodes.filter((node) => node.parent_id === leaf.node_id && node.node_type in values)
        .forEach((node) => { node.text = values[node.node_type]; });
    }
  }
  return updated;
}

function statePatch(before, after, label) {
  const changes = [{ kind: "replace_state", before: clone(before), after: clone(after) }];
  return { label, changes, bytes: JSON.stringify(changes).length };
}

export function executeMindmapCommand(state, command) {
  /** 执行自由脑图命令；仅循环、孤立引用和容量等结构安全问题硬阻止。 */
  const before = clone({ rows: state.rows, mindmap: state.mindmap });
  let sourceRows = clone(state.rows);
  const mindmap = clone(state.mindmap);
  const nodes = mindmap.nodes || [];
  const find = (id) => id === mindmap.root.node_id ? mindmap.root : nodes.find((node) => node.node_id === id);
  if (command.type === "rename_node") {
    const node = find(command.nodeId); if (!node) throw new Error("节点不存在或已被删除");
    node.text = String(command.text ?? "");
  } else if (command.type === "insert_node") {
    const target = find(command.targetId || mindmap.root.node_id);
    if (!target) throw new Error("新增位置已变化，请重新选择");
    const parent = command.relation === "sibling" ? find(target.parent_id) : target;
    if (!parent) throw new Error("中心根节点不能新增同级节点");
    const row = command.row ? clone(command.row) : null;
    const bindingId = row ? String(row[state.kind === "points" ? "id" : "case_id"] || "") : null;
    const node = flatNode(command.nodeType, parent.node_id, nodes.filter((item) => item.parent_id === parent.node_id).length, command.text || "新节点", bindingId);
    nodes.push(node);
    if (state.kind === "cases" && command.nodeType === "case") [
      ["preconditions_content", contentText(row?.preconditions)], ["steps_content", stepsText(row?.test_steps)],
      ["expected_content", contentText(row?.expected_result)], ["test_data_content", testDataText(row?.test_data)],
    ].forEach(([nodeType, value], order) => nodes.push(flatNode(nodeType, node.node_id, order, value, bindingId)));
    if (row) sourceRows = [...sourceRows, row];
  } else if (command.type === "move_node") {
    const node = find(command.nodeId); const target = find(command.targetId || command.parentId);
    const parent = ["before", "after"].includes(command.placement) ? find(target?.parent_id) : target;
    if (!node || !parent || node === mindmap.root) throw new Error("移动节点不存在");
    let cursor = parent; const index = mindmapIndex(mindmap);
    while (cursor) { if (cursor.node_id === node.node_id) throw new Error("不能把节点移动到自身后代"); cursor = index.get(cursor.parent_id); }
    node.parent_id = parent.node_id;
    const siblings = nodes.filter((item) => item.parent_id === parent.node_id && item.node_id !== node.node_id).sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
    let insertAt = siblings.length;
    if (["before", "after"].includes(command.placement)) {
      const targetIndex = siblings.findIndex((item) => item.node_id === target.node_id);
      insertAt = Math.max(0, targetIndex + (command.placement === "after" ? 1 : 0));
    }
    siblings.splice(insertAt, 0, node);
    siblings.forEach((item, order) => { item.order = order; });
  } else if (command.type === "duplicate_node") {
    const source = find(command.nodeId);
    if (!source || source === mindmap.root) throw new Error("中心根节点不能复制");
    const subtreeIds = new Set([source.node_id]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const node of nodes) if (subtreeIds.has(node.parent_id) && !subtreeIds.has(node.node_id)) {
        subtreeIds.add(node.node_id); changed = true;
      }
    }
    const subtree = nodes.filter((node) => subtreeIds.has(node.node_id));
    const leafType = state.kind === "points" ? "test_point" : "case";
    const idField = state.kind === "points" ? "id" : "case_id";
    let sequence = Math.max(0, ...sourceRows.map((row) => Number(/\d+/.exec(String(row[idField] || ""))?.[0] || 0)));
    const bindingMap = new Map();
    for (const leaf of subtree.filter((node) => node.node_type === leafType && node.binding_id)) {
      const original = rowSource(state.kind, sourceRows, leaf.binding_id);
      if (!Object.keys(original).length) continue;
      sequence += 1;
      const newBinding = `${state.kind === "points" ? "TP" : "TC"}${String(sequence).padStart(3, "0")}`;
      const row = clone(original); row[idField] = newBinding;
      if (state.kind === "cases") row.actual_result = "";
      sourceRows.push(row); bindingMap.set(String(leaf.binding_id), newBinding);
    }
    const nodeMap = new Map(subtree.map((node) => [node.node_id, `node_${node.node_type}_${nextUiKey("copy")}`]));
    for (const node of subtree) {
      const copy = clone(node);
      copy.node_id = nodeMap.get(node.node_id);
      copy.parent_id = nodeMap.get(node.parent_id) || node.parent_id;
      if (bindingMap.has(String(node.binding_id || ""))) copy.binding_id = bindingMap.get(String(node.binding_id));
      if (node.node_id === source.node_id) copy.order = nodes.filter((item) => item.parent_id === copy.parent_id).length;
      nodes.push(copy);
    }
  } else if (command.type === "normalize_structure") {
    const normalized = projectMindmap(state.kind, sourceRows, state.testPoints || [], mindmap.root.text);
    mindmap.root = normalized.root;
    mindmap.nodes = normalized.nodes;
  } else if (command.type === "delete_node") {
    if (command.nodeId === mindmap.root.node_id) throw new Error("请使用根节点重置命令");
    const ids = new Set([command.nodeId]); let changed = true;
    while (changed) { changed = false; for (const node of nodes) if (ids.has(node.parent_id) && !ids.has(node.node_id)) { ids.add(node.node_id); changed = true; } }
    if (!find(command.nodeId)) throw new Error("节点不存在或已被删除");
    mindmap.nodes = nodes.filter((node) => !ids.has(node.node_id));
  } else if (command.type === "delete_root_and_reset") {
    mindmap.root = { node_id: `root_${state.kind}_${nextUiKey("reset")}`, node_type: "root", text: command.title || (state.kind === "points" ? "测试点" : "测试用例") };
    mindmap.nodes = [];
  } else throw new Error("不支持的自由脑图操作");
  const compiled = compileMindmapRows(state.kind, mindmap, sourceRows);
  const after = { rows: compiled.rows, mindmap };
  return { ...after, issues: compiled.issues, patch: statePatch(before, after, command.label || "脑图修改") };
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

export function newRowContext(kind, meta = {}, current = null, testPoints = []) {
  /**
   * 根据当前选中的叶子或分组节点生成新记录上下文。
   * 只返回父级引用字段，调用方负责补齐 ID、标题和默认步骤。
   */
  if (kind === "points") {
    if (current) return { module: current.module, feature: current.feature, scenario: current.scenario };
    if (meta.kind === "module") return { module: meta.value };
    if (meta.kind === "feature") return { module: meta.module, feature: meta.value };
    if (meta.kind === "scenario") return { module: meta.module, feature: meta.feature, scenario: meta.value };
    return {};
  }
  if (current) return {
    test_point_id: current.test_point_id, module: current.module, feature: current.feature, scenario: current.scenario,
  };
  let point = null;
  if (!point && meta.kind === "test_point") point = testPoints.find((item) => String(item.id) === String(meta.pointId));
  if (!point && meta.kind === "feature") point = testPoints.find((item) => item.module === meta.module && item.feature === meta.value);
  if (!point && meta.kind === "module") point = testPoints.find((item) => item.module === meta.value);
  point ||= testPoints[0];
  return point ? {
    test_point_id: point.id, module: point.module, feature: point.feature, scenario: point.scenario,
  } : {};
}

export function buildMoveCommand(kind, source, target, testPoints = [], placement = "inside") {
  /**
   * 把脑图库的拖动手势转换为平面 JSON 的原子命令。
   * 只接受不会破坏固定层级和确认测试点引用的语义移动。
   */
  const sources = Array.isArray(source) ? source : [source];
  const primary = sources[0];
  if (!primary || !target) return null;
  if (["before", "after"].includes(placement) && primary.kind === target.kind) {
    if (primary.uiKey && target.uiKey) return {
      type: "reorder", uiKeys: sources.map((item) => item.uiKey).filter(Boolean),
      targetKey: target.uiKey, placement, label: "同级排序",
    };
    if (["module", "feature", "scenario", "test_point"].includes(primary.kind)) return {
      type: "reorder_group", sourceMatch: groupMatch(primary), targetMatch: groupMatch(target), placement, label: "分组排序",
    };
  }
  if (kind === "points") {
    if (sources.length > 1 && sources.every((item) => item.uiKey) && target.kind === "scenario") return {
      type: "bulk_move", uiKeys: sources.map((item) => item.uiKey),
      updates: { module: target.module, feature: target.feature, scenario: target.value }, label: "批量移动测试点",
    };
    if (primary.uiKey && target.kind === "scenario") return {
      type: "move", uiKey: primary.uiKey,
      updates: { module: target.module, feature: target.feature, scenario: target.value }, label: "移动测试点",
    };
    if (primary.kind === "feature" && target.kind === "module") return {
      type: "bulk_update", match: { module: primary.module, feature: primary.value },
      updates: { module: target.value }, label: "移动功能分组",
    };
    if (primary.kind === "scenario" && target.kind === "feature") return {
      type: "bulk_update", match: { module: primary.module, feature: primary.feature, scenario: primary.value },
      updates: { module: target.module, feature: target.value }, label: "移动场景分组",
    };
    return null;
  }
  if (sources.length > 1 && sources.every((item) => item.uiKey) && target.kind === "test_point") {
    const point = testPoints.find((item) => String(item.id) === String(target.pointId));
    if (!point) return null;
    return { type: "bulk_move", uiKeys: sources.map((item) => item.uiKey), updates: pointUpdates(point), label: "批量移动用例" };
  }
  if ((primary.uiKey || primary.kind === "test_point") && target.kind === "test_point") {
    const point = testPoints.find((item) => String(item.id) === String(target.pointId));
    if (!point || String(primary.pointId || "") === String(point.id)) return null;
    const updates = pointUpdates(point);
    return primary.uiKey
      ? { type: "move", uiKey: primary.uiKey, updates, label: "移动用例" }
      : { type: "bulk_update", match: { test_point_id: primary.pointId }, updates, label: "移动用例分组" };
  }
  return null;
}

function pointUpdates(point) {
  return { test_point_id: point.id, module: point.module, feature: point.feature, scenario: point.scenario };
}

function groupMatch(meta) {
  if (meta.kind === "module") return { module: meta.value };
  if (meta.kind === "feature") return { module: meta.module, feature: meta.value };
  if (meta.kind === "scenario") return { module: meta.module, feature: meta.feature, scenario: meta.value };
  return { test_point_id: meta.pointId };
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
  if (type === "insert_many") {
    const changes = [];
    (command.rows || []).forEach((source) => {
      const row = { ...clone(source), __uiKey: source?.__uiKey || nextUiKey("insert") };
      const index = rows.length;
      rows.push(row);
      changes.push({ kind: "insert", index, after: row });
    });
    if (!changes.length) throw new Error("没有可粘贴的节点");
    return { rows, patch: makePatch(changes, command.label || "批量新增") };
  }
  if (type === "insert_relative") {
    const targetIndex = locate(rows, command.targetKey);
    const index = command.placement === "before" ? targetIndex : targetIndex + 1;
    const row = { ...clone(command.row), __uiKey: command.row?.__uiKey || nextUiKey("insert") };
    rows.splice(index, 0, row);
    return { rows, patch: makePatch([{ kind: "insert", index, after: row }], command.label || "新增同级节点") };
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
  if (["update_nested", "delete_nested"].includes(type)) {
    const index = locate(rows, command.uiKey);
    const field = command.field;
    if (!["preconditions", "test_steps"].includes(field)) throw new Error("该结构节点不支持此操作");
    const before = clone(rows[index]);
    const values = Array.isArray(before[field]) ? [...before[field]] : [];
    const itemIndex = Number(command.index);
    if (!Number.isInteger(itemIndex) || itemIndex < 0 || itemIndex >= values.length) throw new Error("详情节点已变化，请刷新后重试");
    if (type === "update_nested") values[itemIndex] = String(command.value || "").trim();
    else values.splice(itemIndex, 1);
    rows[index] = { ...rows[index], [field]: values, __uiKey: before.__uiKey };
    return { rows, patch: makePatch([{ kind: "update", index, before, after: clone(rows[index]) }], command.label || "修改用例详情") };
  }
  if (type === "bulk_move") {
    const keys = new Set(command.uiKeys || []);
    if (!keys.size) throw new Error("请选择要移动的节点");
    const changes = [];
    rows.forEach((row, index) => {
      if (!keys.has(row.__uiKey)) return;
      const before = clone(row);
      rows[index] = { ...row, ...clone(command.updates || {}), __uiKey: before.__uiKey };
      changes.push({ kind: "update", index, before, after: clone(rows[index]) });
    });
    if (changes.length !== keys.size) throw new Error("部分节点已变化，请刷新后重试");
    return { rows, patch: makePatch(changes, command.label || "批量移动") };
  }
  if (type === "reorder" || type === "reorder_group") {
    let keys = new Set(command.uiKeys || []);
    if (type === "reorder_group") {
      keys = new Set(rows.filter((row) => Object.entries(command.sourceMatch || {}).every(([key, value]) => row[key] === value)).map((row) => row.__uiKey));
    }
    const targetKeys = type === "reorder_group"
      ? rows.filter((row) => Object.entries(command.targetMatch || {}).every(([key, value]) => row[key] === value)).map((row) => row.__uiKey)
      : [command.targetKey];
    if (!keys.size || !targetKeys.length) throw new Error("排序节点已变化，请刷新后重试");
    if (targetKeys.some((key) => keys.has(key))) throw new Error("排序目标不能包含在来源节点中");
    const before = clone(rows);
    const moving = rows.filter((row) => keys.has(row.__uiKey));
    const remaining = rows.filter((row) => !keys.has(row.__uiKey));
    const anchor = command.placement === "before" ? targetKeys[0] : targetKeys[targetKeys.length - 1];
    const targetIndex = remaining.findIndex((row) => row.__uiKey === anchor);
    if (targetIndex < 0) throw new Error("排序目标已变化，请刷新后重试");
    remaining.splice(targetIndex + (command.placement === "after" ? 1 : 0), 0, ...moving);
    return { rows: remaining, patch: makePatch([{ kind: "replace_all", before, after: clone(remaining) }], command.label || "排序") };
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
    if (change.kind === "replace_all") return clone(reverse ? change.before : change.after);
    if (change.kind === "insert") reverse ? rows.splice(change.index, 1) : rows.splice(change.index, 0, clone(change.after));
    if (change.kind === "delete") reverse ? rows.splice(change.index, 0, clone(change.before)) : rows.splice(change.index, 1);
    if (change.kind === "update") rows[change.index] = clone(reverse ? change.before : change.after);
  }
  return rows;
}

export function applyStatePatch(currentState, patch, reverse = false) {
  /** 应用包含 rows 与 mindmap 的整状态事务，供自由编辑撤销和重做。 */
  const replacement = patch?.changes?.find((change) => change.kind === "replace_state");
  return replacement ? clone(reverse ? replacement.before : replacement.after) : {
    ...currentState,
    rows: applyPatch(currentState.rows, patch, reverse),
  };
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

  undoState(state) {
    const patch = this.undoStack.pop();
    if (!patch) return state;
    this.bytes -= patch.bytes;
    this.redoStack.push(patch);
    return applyStatePatch(state, patch, true);
  }

  redoState(state) {
    const patch = this.redoStack.pop();
    if (!patch) return state;
    this.undoStack.push(patch);
    this.bytes += patch.bytes;
    return applyStatePatch(state, patch, false);
  }
}
