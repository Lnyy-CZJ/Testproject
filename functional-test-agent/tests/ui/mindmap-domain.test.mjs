import test from "node:test";
import assert from "node:assert/strict";

import {
  CommandHistory,
  buildMoveCommand,
  cleanRows,
  executeCommand,
  flattenTree,
  newRowContext,
  projectTestCases,
  projectTestPoints,
  wrapRows,
} from "../../services/common/static/mindmap-domain.mjs";
import { MindmapView } from "../../services/common/static/mindmap-view.mjs";

const point = (id, updates = {}) => ({
  id, module: "账号", feature: "登录", scenario: "正常", test_point: `测试点${id}`,
  risk_level: "P1", extension: { keep: true }, ...updates,
});

const testCase = (id, pointId, updates = {}) => ({
  case_id: id, test_point_id: pointId, module: "账号", feature: "登录", scenario: "正常",
  case_name: `用例${id}`, priority: "P1", preconditions: ["用户存在"], test_steps: ["登录"],
  test_data: {}, expected_result: "成功", actual_result: "", extension: { keep: true }, ...updates,
});

test("测试点投影保持固定层级和扩展字段", () => {
  const rows = wrapRows([point("TP001"), point("TP002", { scenario: "异常" })], "point");
  const data = projectTestPoints(rows, "登录测试");
  assert.equal(data.nodeData.children[0].children[0].children.length, 2);
  assert.equal(flattenTree(data.nodeData).filter((node) => node.meta.kind === "point").length, 2);
  assert.deepEqual(cleanRows(rows)[0].extension, { keep: true });
  assert.equal("__uiKey" in cleanRows(rows)[0], false);
});

test("用户文本只作为普通 topic 投影且不启用富文本", () => {
  const payload = '<img src=x onerror="globalThis.compromised=true">';
  const rows = wrapRows([point("TP001", { module: payload, test_point: payload })], "points");
  const nodes = flattenTree(projectTestPoints(rows).nodeData);
  assert.ok(nodes.some((node) => node.topic.includes(payload)));
  assert.ok(nodes.every((node) => !("dangerouslySetInnerHTML" in node)));
  assert.equal(globalThis.compromised, undefined);
});

test("用例投影保留未覆盖测试点并提供可回写的分组元数据", () => {
  const points = [point("TP001"), point("TP002")];
  const rows = wrapRows([testCase("TC001", "TP001")], "case");
  const data = projectTestCases(rows, points);
  const pointNodes = flattenTree(data.nodeData).filter((node) => node.meta.kind === "test_point");
  assert.equal(pointNodes.length, 2);
  assert.ok(pointNodes.every((node) => node.meta.pointId));
  assert.equal(pointNodes[0].meta.module, "账号");
  assert.equal(pointNodes.find((node) => node.meta.pointId === "TP002").children.length, 0);
});

test("用例测试点分组可用单个原子 patch 重新关联", () => {
  const rows = wrapRows([testCase("TC001", "TP001"), testCase("TC002", "TP001")], "case");
  const result = executeCommand(rows, {
    type: "bulk_update", match: { test_point_id: "TP001" },
    updates: { test_point_id: "TP002", module: "订单", feature: "退款", scenario: "失败" },
    label: "重新关联测试点",
  });
  assert.equal(result.patch.changes.length, 2);
  assert.ok(result.rows.every((row) => row.test_point_id === "TP002" && row.module === "订单"));
});

test("任意分组节点都能为新增记录提供正确上下文", () => {
  const points = [point("TP001"), point("TP002", { module: "订单", feature: "退款", scenario: "失败" })];
  assert.deepEqual(newRowContext("points", { kind: "feature", module: "账号", value: "登录" }, null, points), {
    module: "账号", feature: "登录",
  });
  assert.equal(newRowContext("cases", { kind: "module", value: "订单" }, null, points).test_point_id, "TP002");
  assert.equal(newRowContext("cases", { kind: "test_point", pointId: "TP001" }, null, points).test_point_id, "TP001");
});

test("测试点分组和用例分组拖动转换为原子领域命令", () => {
  assert.deepEqual(buildMoveCommand("points", {
    kind: "feature", module: "账号", value: "登录",
  }, { kind: "module", value: "认证" }, []), {
    type: "bulk_update", match: { module: "账号", feature: "登录" }, updates: { module: "认证" }, label: "移动功能分组",
  });
  assert.deepEqual(buildMoveCommand("points", {
    kind: "scenario", module: "账号", feature: "登录", value: "正常",
  }, { kind: "feature", module: "认证", value: "单点登录" }, []), {
    type: "bulk_update", match: { module: "账号", feature: "登录", scenario: "正常" },
    updates: { module: "认证", feature: "单点登录" }, label: "移动场景分组",
  });
  assert.equal(buildMoveCommand("cases", { kind: "test_point", pointId: "TP001" }, {
    kind: "test_point", pointId: "TP002",
  }, [point("TP002", { module: "订单", feature: "退款", scenario: "失败" })]).updates.test_point_id, "TP002");
});

test("脑图缩放按钮按固定步长并限制在画布范围内", () => {
  const view = new MindmapView({ addEventListener() {}, querySelector() { return null; } });
  let applied = 0;
  view.instance = { scaleVal: 1, scaleMin: 0.5, scaleMax: 1.1, scale(value) { applied = value; this.scaleVal = value; } };
  view.zoomBy(0.1);
  assert.equal(applied, 1.1);
  view.zoomBy(0.1);
  assert.equal(applied, 1.1);
});

test("缩放以5个百分点对称变化", () => {
  const view = new MindmapView({ addEventListener() {}, querySelector() { return null; } });
  view.instance = { scaleVal: 0.45, scaleMin: 0.2, scaleMax: 2.5, scale(value) { this.scaleVal = value; } };
  view.zoomBy(0.05);
  assert.equal(view.instance.scaleVal, 0.5);
  view.zoomBy(-0.05);
  assert.equal(view.instance.scaleVal, 0.45);
});

test("同级排序是原子命令并可撤销", () => {
  const rows = wrapRows([point("TP001"), point("TP002"), point("TP003")], "point");
  const result = executeCommand(rows, {
    type: "reorder", uiKeys: [rows[0].__uiKey], targetKey: rows[2].__uiKey, placement: "after", label: "同级排序",
  });
  assert.deepEqual(result.rows.map((row) => row.id), ["TP002", "TP003", "TP001"]);
  const history = new CommandHistory(); history.push(result.patch);
  assert.deepEqual(history.undo(result.rows).map((row) => row.id), ["TP001", "TP002", "TP003"]);
});

test("多个叶子节点可一次移动且目标包含在来源时原子拒绝", () => {
  const rows = wrapRows([point("TP001"), point("TP002"), point("TP003")], "point");
  const result = executeCommand(rows, {
    type: "bulk_move", uiKeys: [rows[0].__uiKey, rows[1].__uiKey],
    updates: { module: "订单", feature: "退款", scenario: "失败" }, label: "批量移动",
  });
  assert.equal(result.patch.changes.length, 2);
  assert.ok(result.rows.slice(0, 2).every((row) => row.module === "订单"));
  assert.throws(() => executeCommand(rows, {
    type: "reorder", uiKeys: [rows[0].__uiKey], targetKey: rows[0].__uiKey, placement: "before",
  }), /目标不能包含/);
});

test("批量粘贴只产生一个可撤销事务", () => {
  const rows = wrapRows([point("TP001")], "point");
  const result = executeCommand(rows, {
    type: "insert_many", rows: [point("TP002"), point("TP003")], label: "批量粘贴",
  });
  assert.equal(result.rows.length, 3);
  assert.equal(result.patch.changes.length, 2);
  const history = new CommandHistory(); history.push(result.patch);
  assert.equal(history.undo(result.rows).length, 1);
});

test("命令原子执行且 patch 可撤销重做", () => {
  let rows = wrapRows([point("TP001")], "point");
  const history = new CommandHistory();
  const result = executeCommand(rows, { type: "update", uiKey: rows[0].__uiKey, updates: { test_point: "已修改" } });
  rows = result.rows;
  history.push(result.patch);
  assert.equal(rows[0].test_point, "已修改");
  rows = history.undo(rows);
  assert.equal(rows[0].test_point, "测试点TP001");
  rows = history.redo(rows);
  assert.equal(rows[0].test_point, "已修改");
  assert.throws(() => executeCommand(rows, { type: "update", uiKey: "missing", updates: {} }), /不存在/);
  assert.equal(rows[0].test_point, "已修改");
});

test("用例移动同步测试点引用但不允许修改实际结果", () => {
  const rows = wrapRows([testCase("TC001", "TP001", { actual_result: "历史结果" })], "case");
  const moved = executeCommand(rows, {
    type: "move", uiKey: rows[0].__uiKey,
    updates: { test_point_id: "TP002", module: "订单", feature: "退款", scenario: "异常" },
  });
  assert.equal(moved.rows[0].test_point_id, "TP002");
  assert.throws(() => executeCommand(rows, {
    type: "update", uiKey: rows[0].__uiKey, updates: { actual_result: "篡改" },
  }), /只读/);
});

test("测试点分组重命名以单个原子 patch 批量更新", () => {
  const rows = wrapRows([
    { id: "TP001", module: "登录", feature: "密码", scenario: "正常", test_point: "成功登录", risk_level: "P0" },
    { id: "TP002", module: "登录", feature: "密码", scenario: "异常", test_point: "密码错误", risk_level: "P1" },
    { id: "TP003", module: "搜索", feature: "查询", scenario: "正常", test_point: "关键字搜索", risk_level: "P2" },
  ], "points");
  const result = executeCommand(rows, {
    type: "rename_group", field: "module", match: { module: "登录" }, value: "账号登录", label: "重命名模块",
  });
  assert.deepEqual(result.rows.map((row) => row.module), ["账号登录", "账号登录", "搜索"]);
  assert.equal(result.patch.changes.length, 2);
  const history = new CommandHistory(); history.push(result.patch);
  assert.deepEqual(history.undo(result.rows).map((row) => row.module), ["登录", "登录", "搜索"]);
});

test("5000条投影为线性处理并可统计可见节点", () => {
  const rows = wrapRows(Array.from({ length: 5000 }, (_, index) => point(`TP${String(index + 1).padStart(4, "0")}`)), "point");
  const started = performance.now();
  const count = flattenTree(projectTestPoints(rows).nodeData).length;
  assert.equal(count, 5004);
  assert.ok(performance.now() - started < 2000);
});
