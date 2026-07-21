import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const data = JSON.parse(await fs.readFile("tmp_trackevents_checklist/checklist_data.json", "utf8"));
const outputPath = "outputs/trackevents_checklist/埋点测试与检查清单.xlsx";

function colName(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function rangeAddress(rowCount, colCount) {
  return `A1:${colName(colCount)}${rowCount}`;
}

function writeSheet(sheet, rows, widths = []) {
  const rowCount = rows.length;
  const colCount = Math.max(...rows.map((row) => row.length));
  const normalized = rows.map((row) => {
    const copy = [...row];
    while (copy.length < colCount) copy.push("");
    return copy;
  });
  sheet.getRange(rangeAddress(rowCount, colCount)).values = normalized;
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  const all = sheet.getRange(rangeAddress(rowCount, colCount));
  all.format.font = { name: "Arial", size: 10, color: "#1F2937" };
  all.format.wrapText = true;
  all.format.verticalAlignment = "top";
  const header = sheet.getRange(`A1:${colName(colCount)}1`);
  header.format.fill = { color: "#1F4E79" };
  header.format.font = { color: "#FFFFFF", bold: true };
  header.format.horizontalAlignment = "center";
  header.format.verticalAlignment = "middle";
  header.format.rowHeight = 28;
  all.format.borders = { preset: "all", style: "thin", color: "#D9E2F3" };
  widths.forEach((width, index) => {
    sheet.getRange(`${colName(index + 1)}:${colName(index + 1)}`).format.columnWidth = width;
  });
  return { rowCount, colCount };
}

const workbook = Workbook.create();

const overview = workbook.worksheets.add("概览");
const overviewRows = [
  ["项目", "内容"],
  ["清单来源", data.source],
  ["Action 总数", data.action_count],
  ["用途", "按产品埋点需求文档执行测试、检查 TrackEvents log、记录测试结果"],
  ["使用方式", "按“埋点测试清单”逐条执行；上传 log 到本地工具；在本表填写实际次数、结果和问题"],
  ["通用检查", "只看 method=TrackEvents；检查 event_name、业务子参、公参一致性、响应 accepted_count"],
  ["状态说明", "未测试 / 通过 / 不通过 / 阻塞 / 不适用"],
];
writeSheet(overview, overviewRows, [18, 110]);

const summary = workbook.worksheets.add("模块汇总");
const summaryRows = [["module", "Action 数量"], ...data.summary.map((item) => [item.module, item.action_count])];
writeSheet(summary, summaryRows, [24, 16]);

const checklist = workbook.worksheets.add("埋点测试清单");
const checklistHeader = [
  "用例ID",
  "优先级",
  "module",
  "模块/页面",
  "Action",
  "上报时机",
  "业务子参 Key",
  "业务子参说明",
  "测试前置条件",
  "测试执行步骤",
  "预期检查点",
  "log 检查方法",
  "预期触发次数",
  "实际触发次数",
  "测试状态",
  "测试结果",
  "问题记录",
  "测试人",
  "来源行",
  "产品备注",
];
const checklistRows = [
  checklistHeader,
  ...data.rows.map((row) => [
    row.case_id,
    row.priority,
    row.module,
    row.module_name,
    row.action,
    row.trigger,
    row.params.length ? row.params.join("\n") : "无",
    row.param_desc.length ? row.param_desc.join("\n") : "无",
    row.precondition,
    row.test_steps,
    row.expected_result,
    row.log_check,
    row.expected_count,
    row.actual_count,
    row.status,
    row.result,
    row.issue,
    row.tester,
    row.source_row,
    row.remark,
  ]),
];
const checklistInfo = writeSheet(
  checklist,
  checklistRows,
  [12, 10, 14, 24, 30, 36, 24, 46, 42, 70, 64, 52, 26, 14, 14, 16, 42, 12, 10, 42],
);
checklist.getRange(`A1:${colName(checklistInfo.colCount)}${checklistInfo.rowCount}`).format.autofitRows();
checklist.getRange(`O2:O${checklistInfo.rowCount}`).dataValidation = {
  rule: { type: "list", values: ["未测试", "通过", "不通过", "阻塞", "不适用"] },
};
checklist.getRange(`B2:B${checklistInfo.rowCount}`).dataValidation = {
  rule: { type: "list", values: ["P0", "P1", "P2"] },
};

const checks = workbook.worksheets.add("字段检查规则");
writeSheet(checks, data.checks, [26, 68, 68]);

const source = workbook.worksheets.add("来源说明");
const sourceRows = [
  ["来源文件", "说明"],
  ["产品埋点需求文档/1.0.0埋点.xlsx", "Action、上报时机、业务子参 Key/Value、产品备注"],
  ["产品埋点需求文档/需求埋点list(维护最新版).xlsx", "公参定义、Action 命名规则、page_from 定义"],
  ["请求与响应log格式.log", "TrackEvents 请求/响应样例；method=TrackEvents 才是埋点请求"],
  ["本地工具页面", "http://127.0.0.1:8000"],
];
writeSheet(source, sourceRows, [50, 80]);

const inspect = await workbook.inspect({
  kind: "sheet",
  include: "name",
  maxChars: 2000,
});
console.log(inspect.ndjson);

await fs.mkdir("outputs/trackevents_checklist", { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);
