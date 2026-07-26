#!/usr/bin/env node

/**
 * Offline searchTool JSONL-to-Excel exporter.
 *
 * The script reads one or two result directories, builds a shared flattened data
 * model, and authors the workbook with @oai/artifact-tool. It never reads .env or
 * performs network requests.
 */

import fs from "node:fs/promises";
import fsSync from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const RAW_TRIGGER_LENGTH = 32000;
const RAW_CHUNK_LENGTH = 30000;
const SCRIPT_PATH = fileURLToPath(import.meta.url);

function printHelp() {
  console.log(`searchTool JSONL → Excel 导出工具

单 Run：
  python3 result_to_excel.py single --results-file FILE [--failures-file FILE] \\
    --run-label LABEL --system-version VERSION --evaluation-id ID --output FILE.xlsx

  兼容旧目录模式：--run-dir DIR

双 Run：
  python3 result_to_excel.py compare \\
    --baseline-results-file FILE --baseline-version VERSION \\
    --candidate-results-file FILE --candidate-version VERSION \\
    --evaluation-id ID [--metadata FILE] --output FILE.xlsx

  兼容旧目录模式：--baseline-dir DIR --candidate-dir DIR

处理结果：
  python3 result_to_excel.py processed --input-file processed_export.jsonl \\
    --report-model report_model.json --output report.xlsx

.env 模式：
  python3 result_to_excel.py single --env-file .env`);
}

/** Load artifact-tool, bootstrapping a temporary node_modules link when needed. */
async function loadArtifactTool() {
  try {
    return await import("@oai/artifact-tool");
  } catch (error) {
    if (process.env.SEARCHTOOL_ARTIFACT_BOOTSTRAPPED === "1") {
      throw new Error(`无法加载 @oai/artifact-tool: ${error.message}`);
    }

    const inferredModules = path.resolve(path.dirname(process.execPath), "..", "node_modules");
    const nodeModules = process.env.SEARCHTOOL_NODE_MODULES || inferredModules;
    const packagePath = path.join(nodeModules, "@oai", "artifact-tool");
    if (!fsSync.existsSync(packagePath)) {
      throw new Error(
        `未找到 @oai/artifact-tool。请设置 SEARCHTOOL_NODE_MODULES，当前检查路径: ${nodeModules}`,
      );
    }

    const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "searchtool-xlsx-"));
    const copiedScript = path.join(tempDir, "result_to_excel_builder.mjs");
    try {
      await fs.symlink(nodeModules, path.join(tempDir, "node_modules"), "dir");
      await fs.copyFile(SCRIPT_PATH, copiedScript);
      const child = spawnSync(process.execPath, [copiedScript, ...process.argv.slice(2)], {
        cwd: process.cwd(),
        env: { ...process.env, SEARCHTOOL_ARTIFACT_BOOTSTRAPPED: "1" },
        encoding: "utf8",
        stdio: "inherit",
      });
      process.exit(child.status ?? 1);
    } finally {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  }
}

/** Convert CLI tokens into a mode and named values. */
function parseArgs(argv) {
  const mode = argv[0];
  if (!mode || !["single", "compare", "processed"].includes(mode)) {
    throw new Error("第一个参数必须是 single、compare 或 processed");
  }
  const values = {};
  for (let index = 1; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error(`无效参数: ${key ?? ""}`);
    }
    values[key.slice(2)] = value;
  }

  const required =
    mode === "single"
      ? ["run-label", "system-version", "evaluation-id", "output"]
      : mode === "compare"
        ? [
          "baseline-version",
          "candidate-version",
          "evaluation-id",
          "output",
        ]
        : ["input-file", "report-model", "output"];
  const missing = required.filter((name) => !values[name]);
  if (missing.length) {
    throw new Error(`缺少必要参数: ${missing.map((name) => `--${name}`).join(", ")}`);
  }
  if (mode === "single" && !values["run-dir"] && !values["results-file"]) {
    throw new Error("single 模式必须提供 --run-dir 或 --results-file");
  }
  if (
    mode === "compare" &&
    (!values["baseline-dir"] || !values["candidate-dir"]) &&
    (!values["baseline-results-file"] || !values["candidate-results-file"])
  ) {
    throw new Error(
      "compare 模式必须同时提供两个 Run 目录，或同时提供 baseline/candidate results 文件",
    );
  }
  if (!values.output.toLowerCase().endsWith(".xlsx")) {
    throw new Error("--output 必须以 .xlsx 结尾");
  }
  return { mode, values };
}

/** Read JSONL while retaining per-line parse errors instead of stopping the file. */
async function readJsonl(filePath, required) {
  try {
    const text = await fs.readFile(filePath, "utf8");
    const records = [];
    const errors = [];
    text.split(/\r?\n/).forEach((rawLine, index) => {
      if (!rawLine.trim()) return;
      try {
        records.push({ line: index + 1, value: JSON.parse(rawLine) });
      } catch (error) {
        errors.push({ source_file: filePath, source_line: index + 1, error: error.message });
      }
    });
    return { records, errors, missing: false };
  } catch (error) {
    if (error.code === "ENOENT" && !required) return { records: [], errors: [], missing: true };
    if (error.code === "ENOENT") throw new Error(`必要输入文件不存在: ${filePath}`);
    throw error;
  }
}

/** Read one required JSON object file used as the immutable report snapshot. */
async function readJsonObject(filePath) {
  let text;
  try {
    text = await fs.readFile(filePath, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") throw new Error(`必要输入文件不存在: ${filePath}`);
    throw error;
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch (error) {
    throw new Error(`报告模型 JSON 格式错误: ${error.message}`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("报告模型必须是 JSON 对象");
  }
  return value;
}

function excelScalar(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

const PROCESSED_CANDIDATE_HEADERS = [
  "evaluation_id",
  "process_id",
  "run_id",
  "run_label",
  "system_version",
  "query_id",
  "person_id",
  "query_stage",
  "task_id",
  "query_status",
  "candidate_pk",
  "candidate_id",
  "candidate_rank",
  "rank_score",
  "detail_status",
  "detail_error",
  "judgement",
  "reason",
  "reviewer",
  "review_note",
  "reviewed_at",
];

const PROCESSED_QUERY_HEADERS = [
  "run_id",
  "run_label",
  "system_version",
  "evaluation_phase",
  "query_id",
  "person_id",
  "query_stage",
  "task_id",
  "query_status",
  "result_status",
  "candidate_count_total",
  "candidate_count_listed",
  "detail_success_count",
  "detail_failure_count",
  "llm_cost",
  "third_party_cost",
  "total_cost",
  "pdl_called",
  "search_duration_ms",
  "retrieval_success",
  "matched_completeness",
  "matched_accuracy",
  "formal_ready",
];

const PROCESSED_REVIEW_HEADERS = [
  "process_id",
  "query_id",
  "person_id",
  "candidate_pk",
  "candidate_id",
  "candidate_rank",
  "judgement",
  "reason",
  "evidence",
  "reviewer",
  "review_note",
  "reviewed_at",
  "field_scores",
];

const PROCESSED_FAILURE_HEADERS = [
  "query_id",
  "candidate_id",
  "scope",
  "stage",
  "field_key",
  "error_code",
  "error",
  "created_at",
];

const CORE_METRIC_HEADERS = [
  "section",
  "query_stage",
  "metric_key",
  "metric_name",
  "status",
  "value",
  "preview_value",
  "numerator",
  "denominator",
  "count",
  "total",
  "average",
  "minimum",
  "maximum",
  "missing_count",
  "invalid_count",
  "threshold",
  "threshold_status",
  "direction",
  "reason",
  "unit",
];

const SAME_CONDITION_HEADERS = [
  "person_id",
  "query_stage",
  "baseline_query_id",
  "candidate_query_id",
  "category",
  "reason",
  "baseline_hit",
  "candidate_hit",
  "baseline_matched_completeness",
  "candidate_matched_completeness",
  "matched_completeness_delta",
  "baseline_matched_accuracy",
  "candidate_matched_accuracy",
  "matched_accuracy_delta",
  "baseline_confidence",
  "candidate_confidence",
  "baseline_total_cost",
  "candidate_total_cost",
  "total_cost_delta",
  "baseline_search_duration_ms",
  "candidate_search_duration_ms",
  "search_duration_ms_delta",
  "baseline_pdl_called",
  "candidate_pdl_called",
  "baseline_candidate_count",
  "candidate_candidate_count",
  "formal_ready",
];

const NEW_CLUE_HEADERS = [
  "person_id",
  "query_stage",
  "candidate_query_id",
  "result_status",
  "retrieval_success",
  "matched_completeness",
  "matched_accuracy",
  "candidate_confidence",
  "candidate_count",
  "llm_cost",
  "third_party_cost",
  "total_cost",
  "pdl_called",
  "search_duration_ms",
];

const MODULE_FIELD_HEADERS = [
  "row_type",
  "metric_key",
  "field_key",
  "display_name",
  "module",
  "scoring_role",
  "compare_mode",
  "returned_count",
  "empty_count",
  "returned_candidate_count",
  "candidate_count",
  "hit_returned_count",
  "hit_returned_candidate_count",
  "hit_candidate_count",
  "nonmatched_returned_count",
  "nonmatched_returned_candidate_count",
  "nonmatched_candidate_count",
  "return_rate",
  "hit_return_rate",
  "nonmatched_return_rate",
  "nonmatched_nonempty_rate",
  "hit_completeness",
  "hit_accuracy",
  "baseline_return_rate",
  "candidate_return_rate",
  "return_rate_delta",
  "baseline_hit_return_rate",
  "candidate_hit_return_rate",
  "hit_return_rate_delta",
  "baseline_nonmatched_return_rate",
  "candidate_nonmatched_return_rate",
  "nonmatched_return_rate_delta",
  "baseline_nonmatched_nonempty_rate",
  "candidate_nonmatched_nonempty_rate",
  "nonmatched_nonempty_rate_delta",
  "baseline_hit_completeness",
  "candidate_hit_completeness",
  "hit_completeness_delta",
  "baseline_hit_accuracy",
  "candidate_hit_accuracy",
  "hit_accuracy_delta",
];

const METRIC_NAMES = {
  total_formal_queries: "正式 Query 数",
  has_candidates_count: "有候选人 Query 数",
  no_candidates_count: "无候选人 Query 数",
  execution_failed_count: "执行失败 Query 数",
  has_result_rate: "有结果率",
  no_result_rate: "无结果率",
  execution_failed_rate: "执行失败率",
  retrieval_success: "检索成功率",
  matched_completeness: "命中完整度",
  matched_accuracy: "命中准确率",
  nonmatched_completeness: "非命中完整度",
  llm_cost: "LLM 成本",
  third_party_cost: "第三方成本",
  total_cost: "总成本",
  search_duration_ms: "检索耗时",
  pdl_called: "PDL 调用",
};

/** 将 ReportModel 的单组指标展开为可审计的稳定行。 */
function appendMetricGroup(rows, metrics, queryStage = "ALL") {
  const resultMetrics = metrics?.result_status_metrics ?? {};
  for (const metricKey of [
    "total_formal_queries",
    "has_candidates_count",
    "no_candidates_count",
    "execution_failed_count",
    "has_result_rate",
    "no_result_rate",
    "execution_failed_rate",
  ]) {
    if (!(metricKey in resultMetrics)) continue;
    const isRate = metricKey.endsWith("_rate");
    rows.push({
      section: "结果状态",
      query_stage: queryStage,
      metric_key: metricKey,
      metric_name: METRIC_NAMES[metricKey] ?? metricKey,
      value: isRate ? excelScalar(resultMetrics[metricKey]) : null,
      count: isRate ? null : excelScalar(resultMetrics[metricKey]),
      unit: isRate ? "ratio" : "count",
    });
  }

  for (const [metricKey, item] of Object.entries(metrics?.quality_metrics ?? {})) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    rows.push({
      section: "质量指标",
      query_stage: queryStage,
      metric_key: metricKey,
      metric_name: METRIC_NAMES[metricKey] ?? metricKey,
      status: excelScalar(item.status),
      value: excelScalar(item.value),
      preview_value: excelScalar(item.preview_value),
      numerator: excelScalar(item.numerator),
      denominator: excelScalar(item.denominator),
      reason: Array.isArray(item.not_ready_reasons)
        ? item.not_ready_reasons.join("\n")
        : null,
      unit: "ratio",
    });
  }

  for (const [metricKey, item] of Object.entries(metrics?.cost_metrics ?? {})) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    rows.push({
      section: metricKey === "search_duration_ms" ? "耗时" : "成本",
      query_stage: queryStage,
      metric_key: metricKey,
      metric_name: METRIC_NAMES[metricKey] ?? metricKey,
      status: excelScalar(item.status),
      count: excelScalar(item.value_count),
      total: excelScalar(item.total),
      average: excelScalar(item.average),
      minimum: excelScalar(item.minimum),
      maximum: excelScalar(item.maximum),
      missing_count: excelScalar(item.missing_count),
      invalid_count: excelScalar(item.invalid_count),
      unit: metricKey === "search_duration_ms" ? "ms" : "接口单位待确认",
    });
  }

  const pdl = metrics?.pdl_metrics ?? {};
  if (Object.keys(pdl).length) {
    rows.push({
      section: "PDL",
      query_stage: queryStage,
      metric_key: "pdl_called",
      metric_name: METRIC_NAMES.pdl_called,
      value: excelScalar(pdl.call_rate),
      numerator: excelScalar(pdl.true_count),
      denominator: excelScalar(pdl.known_count),
      count: excelScalar(pdl.unknown_count),
      invalid_count: Array.isArray(pdl.invalid_query_ids)
        ? pdl.invalid_query_ids.length
        : null,
      unit: "ratio",
      reason: "count 列记录 unknown_count",
    });
  }

  for (const [scope, distribution] of Object.entries(metrics?.confidence_metrics ?? {})) {
    if (!distribution || typeof distribution !== "object" || Array.isArray(distribution)) {
      continue;
    }
    for (const [confidence, count] of Object.entries(distribution)) {
      rows.push({
        section: `Confidence:${scope}`,
        query_stage: queryStage,
        metric_key: confidence,
        metric_name: confidence,
        count: excelScalar(count),
        unit: "count",
      });
    }
  }
}

/** 将 ReportModel v2 转成 Excel 各报告 Sheet 使用的数据行。 */
function buildReportRows(reportModel) {
  const coreMetricRows = [];
  const legacyCandidate = reportModel.summary?.candidate;
  const overallMetrics =
    reportModel.quality_metrics || reportModel.result_status_metrics
      ? reportModel
      : legacyCandidate && typeof legacyCandidate === "object"
        ? {
          quality_metrics: Object.fromEntries(
            [
              "retrieval_success",
              "matched_completeness",
              "matched_accuracy",
              "nonmatched_completeness",
            ]
              .filter((metricKey) => legacyCandidate[metricKey])
              .map((metricKey) => [metricKey, legacyCandidate[metricKey]]),
          ),
        }
        : reportModel;
  appendMetricGroup(coreMetricRows, overallMetrics, "ALL");
  for (const group of reportModel.grouped_metrics ?? []) {
    appendMetricGroup(coreMetricRows, group, group.query_stage ?? "UNSPECIFIED");
  }

  const assessment = reportModel.threshold_assessment ?? {};
  for (const [queryStage, stage] of Object.entries(assessment.stages ?? {})) {
    for (const [metricKey, item] of Object.entries(stage?.items ?? {})) {
      coreMetricRows.push({
        section: "参考线",
        query_stage: queryStage,
        metric_key: metricKey,
        metric_name: METRIC_NAMES[metricKey] ?? metricKey,
        value: excelScalar(item.actual),
        threshold: excelScalar(item.threshold),
        threshold_status: excelScalar(item.status),
        direction: excelScalar(item.direction),
        reason: excelScalar(item.reason),
        unit: metricKey.includes("cost")
          ? "接口单位待确认"
          : metricKey.includes("duration")
            ? "ms"
            : "ratio",
      });
    }
  }
  if (assessment.recommendation || assessment.recommendation_code) {
    coreMetricRows.push({
      section: "参考线结论",
      query_stage: "ALL",
      metric_key: "recommendation",
      metric_name: "建议",
      status: excelScalar(assessment.recommendation_code),
      reason: excelScalar(assessment.recommendation),
    });
  }

  const comparison = reportModel.comparison ?? reportModel.paired_metrics ?? {};
  const sameConditionRows = [
    ...(comparison.same_condition?.pairs ?? []),
    ...(comparison.not_comparable?.queries ?? []).map((row) => ({
      ...row,
      category: "不可比",
      formal_ready: false,
    })),
  ].map((row) =>
    Object.fromEntries(
      SAME_CONDITION_HEADERS.map((header) => [header, excelScalar(row[header])]),
    ),
  );
  const newClueRows = (comparison.new_clue?.queries ?? []).map((row) => {
    const taskFields =
      row.task_fields && typeof row.task_fields === "object" && !Array.isArray(row.task_fields)
        ? row.task_fields
        : {};
    return Object.fromEntries(
      NEW_CLUE_HEADERS.map((header) => [
        header,
        excelScalar(header in row ? row[header] : taskFields[header]),
      ]),
    );
  });

  const moduleFieldRows = [];
  for (const [metricKey, item] of Object.entries(reportModel.module_metrics ?? {})) {
    moduleFieldRows.push({
      row_type: "MODULE",
      metric_key: metricKey,
      display_name: item.module ?? metricKey,
      module: item.module ?? metricKey,
      ...Object.fromEntries(
        MODULE_FIELD_HEADERS.slice(7).map((header) => [header, excelScalar(item[header])]),
      ),
    });
  }
  for (const [metricKey, item] of Object.entries(reportModel.field_metrics ?? {})) {
    moduleFieldRows.push({
      row_type: "FIELD",
      metric_key: metricKey,
      field_key: item.field_key ?? metricKey,
      display_name: item.display_name ?? metricKey,
      module: item.module ?? null,
      scoring_role: Array.isArray(item.scoring_role)
        ? item.scoring_role.join("\n")
        : excelScalar(item.scoring_role),
      compare_mode: excelScalar(item.compare_mode),
      ...Object.fromEntries(
        MODULE_FIELD_HEADERS.slice(7).map((header) => [header, excelScalar(item[header])]),
      ),
    });
  }
  return { coreMetricRows, sameConditionRows, newClueRows, moduleFieldRows };
}

/** Build the workbook-neutral model from AnalysisService processed records. */
async function buildProcessedModel(inputFile, reportModelFile) {
  const input = await readJsonl(inputFile, true);
  if (input.errors.length) {
    throw new Error(`processed_export.jsonl 存在 ${input.errors.length} 条 JSON 错误`);
  }
  const reportModel = await readJsonObject(reportModelFile);
  const candidates = [];
  const queries = [];
  const failures = [];
  const processingFailures = [];
  const dynamicFields = new Set(Object.keys(reportModel.field_metrics ?? {}));
  for (const { line, value } of input.records) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(`processed_export.jsonl 第 ${line} 行必须是对象`);
    }
    if (value.record_type === "candidate") {
      const fields =
        value.fields && typeof value.fields === "object" && !Array.isArray(value.fields)
          ? value.fields
          : {};
      Object.keys(fields).forEach((field) => dynamicFields.add(field));
      candidates.push({ ...value, fields });
      for (const error of value.processing_errors ?? []) {
        if (!error?.field_key) continue;
        processingFailures.push({
          query_id: value.query_id,
          candidate_id: value.candidate_id,
          scope: "CANDIDATE_FIELD",
          stage: "FIELD_PROCESSING",
          field_key: error.field_key,
          error_code: error.code,
          error: error.error ?? error.message ?? JSON.stringify(error),
          created_at: null,
        });
      }
    } else if (value.record_type === "query") {
      queries.push(value);
      for (const error of value.processing_errors ?? []) {
        if (!error?.field_key) continue;
        processingFailures.push({
          query_id: value.query_id,
          candidate_id: null,
          scope: "QUERY_FIELD",
          stage: "FIELD_PROCESSING",
          field_key: error.field_key,
          error_code: error.code,
          error: error.error ?? error.message ?? JSON.stringify(error),
          created_at: null,
        });
      }
    } else if (value.record_type === "failure") {
      failures.push(value);
    } else {
      throw new Error(`processed_export.jsonl 第 ${line} 行 record_type 无效`);
    }
  }
  const fieldHeaders = [...dynamicFields].sort((left, right) => left.localeCompare(right));
  const candidateRows = candidates.map((record) => {
    const row = {};
    PROCESSED_CANDIDATE_HEADERS.forEach((header) => {
      row[header] = excelScalar(record[header]);
    });
    fieldHeaders.forEach((field) => {
      row[field] = excelScalar(record.fields[field]);
    });
    return row;
  });
  const candidateHeaders = [...PROCESSED_CANDIDATE_HEADERS, ...fieldHeaders];
  const rawRows = extractRawRows(candidateRows, candidateHeaders);
  const queryRows = queries.map((record) =>
    Object.fromEntries(
      PROCESSED_QUERY_HEADERS.map((header) => [header, excelScalar(record[header])]),
    ),
  );
  const reviewRows = candidates.map((record) =>
    Object.fromEntries(
      PROCESSED_REVIEW_HEADERS.map((header) => [
        header,
        excelScalar(header === "field_scores" ? record.field_scores : record[header]),
      ]),
    ),
  );
  const failureRows = failures.map((record) =>
    Object.fromEntries(
      PROCESSED_FAILURE_HEADERS.map((header) => [header, excelScalar(record[header])]),
    ),
  );
  failureRows.push(...processingFailures);
  const reportRows = buildReportRows(reportModel);
  return {
    mode: "processed",
    reportModel,
    candidateHeaders,
    candidateRows,
    queryRows,
    reviewRows,
    failureRows,
    rawRows,
    ...reportRows,
  };
}

/** Load and index one run's result and failure files. */
async function loadRun(spec) {
  const resultsFile = spec.resultsFile
    ? path.resolve(spec.resultsFile)
    : path.join(path.resolve(spec.runDir), "results.jsonl");
  const failuresFile = spec.failuresFile
    ? path.resolve(spec.failuresFile)
    : resultsFile.endsWith("_results.jsonl")
      ? resultsFile.replace(/_results\.jsonl$/, "_failures.jsonl")
      : path.join(path.dirname(resultsFile), "failures.jsonl");
  const runDir = path.dirname(resultsFile);
  const stat = await fs.stat(runDir).catch(() => null);
  if (!stat?.isDirectory()) throw new Error(`Run 目录不存在: ${runDir}`);

  const resultInput = await readJsonl(resultsFile, true);
  const failureInput = await readJsonl(failuresFile, false);
  const resultsByQuery = new Map();
  const failuresByQuery = new Map();
  const conflicts = new Set();
  const inputErrors = [...resultInput.errors, ...failureInput.errors];

  for (const { line, value } of resultInput.records) {
    const queryId = typeof value?.input_id === "string" ? value.input_id : "";
    if (!queryId || !Array.isArray(value?.results)) {
      inputErrors.push({
        source_file: resultsFile,
        source_line: line,
        error: "记录缺少 input_id 或 results 数组",
      });
      continue;
    }
    if (resultsByQuery.has(queryId)) {
      conflicts.add(queryId);
      inputErrors.push({
        source_file: resultsFile,
        source_line: line,
        query_id: queryId,
        error: "同一 Run 出现重复 input_id",
      });
      continue;
    }
    resultsByQuery.set(queryId, value);
  }

  for (const { line, value } of failureInput.records) {
    const queryId = typeof value?.input_id === "string" ? value.input_id : "";
    if (!queryId) {
      inputErrors.push({
        source_file: failuresFile,
        source_line: line,
        error: "失败记录缺少 input_id",
      });
      continue;
    }
    const items = failuresByQuery.get(queryId) ?? [];
    items.push(value);
    failuresByQuery.set(queryId, items);
  }

  return {
    spec: { ...spec, runDir, resultsFile, failuresFile },
    resultsByQuery,
    failuresByQuery,
    conflicts,
    inputErrors,
    failuresMissing: failureInput.missing,
  };
}

/** Load optional Query metadata and enforce unique query_id values. */
async function loadMetadata(metadataPath) {
  if (!metadataPath) return new Map();
  const input = await readJsonl(metadataPath, true);
  if (input.errors.length) {
    const first = input.errors[0];
    throw new Error(`Query 元数据 JSON 错误: ${first.source_file}:${first.source_line} ${first.error}`);
  }
  const metadata = new Map();
  for (const { line, value } of input.records) {
    const queryId = typeof value?.query_id === "string" ? value.query_id : "";
    if (!queryId) throw new Error(`Query 元数据第 ${line} 行缺少 query_id`);
    if (metadata.has(queryId)) throw new Error(`Query 元数据 query_id 重复: ${queryId}`);
    if (value.tags !== undefined && !Array.isArray(value.tags)) {
      throw new Error(`Query 元数据 ${queryId} 的 tags 必须是数组`);
    }
    metadata.set(queryId, {
      query_id: queryId,
      person_id: stringValue(value.person_id),
      query_type: stringValue(value.query_type),
      person_group: stringValue(value.person_group),
      difficulty: stringValue(value.difficulty),
      tags: (value.tags ?? []).map(stringValue),
    });
  }
  return metadata;
}

function stringValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function arrayValue(value) {
  return Array.isArray(value) ? value : [];
}

function compactJson(value) {
  if (value === undefined || value === null) return "";
  return JSON.stringify(value);
}

/** Convert link objects to the requested one-link-per-line display. */
function titleUrlLines(value) {
  return arrayValue(value)
    .map((item) => {
      const link = objectValue(item);
      const title = stringValue(link.title);
      const url = stringValue(link.url);
      if (title && url) return `${title}：${url}`;
      return url || title;
    })
    .filter(Boolean)
    .join("\n");
}

/** Collect dynamic Profile columns in stable first-seen order across all runs. */
function collectProfileColumns(runs) {
  const columns = [];
  const seen = new Set();
  for (const run of runs) {
    for (const record of run.resultsByQuery.values()) {
      for (const candidate of record.results) {
        const sections = arrayValue(
          objectValue(objectValue(objectValue(candidate?.ui_sections).profile).data).sections,
        );
        for (const section of sections) {
          const title = stringValue(section?.title);
          for (const item of arrayValue(section?.items)) {
            const label = stringValue(item?.label);
            if (!title || !label) continue;
            const column = `profile.${title}.${label}`;
            if (!seen.has(column)) {
              seen.add(column);
              columns.push(column);
            }
          }
        }
      }
    }
  }
  return columns;
}

/** Flatten one candidate with the single shared field-mapping implementation. */
function flattenCandidate(context) {
  const {
    evaluationId,
    run,
    queryId,
    taskId,
    candidateCountTotal,
    candidate,
    candidateRank,
    metadata,
  } = context;
  const ui = objectValue(candidate.ui_sections);
  const insights = objectValue(ui.insights);
  const insightsData = objectValue(insights.data);
  const firstInsight = objectValue(arrayValue(insightsData.items)[0]);
  const photos = objectValue(ui.photos);
  const photosData = objectValue(photos.data);
  const profile = objectValue(ui.profile);
  const profileData = objectValue(profile.data);
  const social = objectValue(ui.social);
  const socialData = objectValue(social.data);
  const socialProfiles = arrayValue(socialData.profiles);
  const summary = objectValue(ui.summary);
  const summaryData = objectValue(summary.data);
  const primaryImage = objectValue(summaryData.primary_image);

  const row = {
    evaluation_id: evaluationId,
    run_label: run.spec.runLabel,
    system_version: run.spec.systemVersion,
    query_id: queryId,
    person_id: metadata?.person_id ?? "",
    query_type: metadata?.query_type ?? "",
    person_group: metadata?.person_group ?? "",
    difficulty: metadata?.difficulty ?? "",
    tags: (metadata?.tags ?? []).join("\n"),
    task_id: stringValue(taskId),
    candidate_count_total:
      typeof candidateCountTotal === "number" && Number.isFinite(candidateCountTotal)
        ? candidateCountTotal
        : "",
    candidate_rank: candidateRank,
    rank_score:
      typeof candidate.rank_score === "number" && Number.isFinite(candidate.rank_score)
        ? candidate.rank_score
        : "",
    candidate_id: stringValue(candidate.candidate_id),
    insights_status: stringValue(insights.status),
    insights_description: stringValue(firstInsight.description),
    insights_links: titleUrlLines(firstInsight.links),
    insights_data: compactJson(insightsData),
    photos_status: stringValue(photos.status),
    photos_baseline_photo_url: stringValue(photosData.baseline_photo_url),
    photos_identity_match_rate:
      typeof photosData.identity_match_rate === "number" ? photosData.identity_match_rate : "",
    photos_authenticity_photos:
      photosData.authenticity_photos === undefined ? "" : compactJson(photosData.authenticity_photos),
    photos_match_photos:
      photosData.match_photos === undefined ? "" : compactJson(photosData.match_photos),
    photos_data: compactJson(photosData),
    profile_status: stringValue(profile.status),
    profile_data: compactJson(profileData),
    social_status: stringValue(social.status),
    social_display_handles: socialProfiles.map((item) => stringValue(item?.display_handle)).join("\n"),
    social_platforms: socialProfiles.map((item) => stringValue(item?.platform)).join("\n"),
    social_urls: socialProfiles.map((item) => stringValue(item?.url)).join("\n"),
    social_profiles: compactJson(socialProfiles),
    summary_avatar_url: stringValue(summaryData.avatar_url),
    summary_confidence_level: stringValue(summaryData.confidence_level),
    summary_primary_image_url: stringValue(primaryImage.url),
    summary_social_links: titleUrlLines(summaryData.social_links),
    summary_web_links: titleUrlLines(summaryData.web_links),
    summary_display_name: stringValue(summaryData.display_name),
    summary_location: stringValue(summaryData.location),
    summary_match_score:
      typeof summaryData.match_score === "number" ? summaryData.match_score : "",
    summary_is_top_result:
      typeof summaryData.is_top_result === "boolean" ? summaryData.is_top_result : "",
    summary_is_best_match:
      typeof summaryData.is_best_match === "boolean" ? summaryData.is_best_match : "",
    identity_judgement: "",
    identity_evidence: "",
    field_review_status: "",
    failure_type: "",
    reviewer: "",
    review_comment: "",
  };

  const dynamicValues = new Map();
  for (const section of arrayValue(profileData.sections)) {
    const title = stringValue(section?.title);
    for (const item of arrayValue(section?.items)) {
      const label = stringValue(item?.label);
      if (!title || !label) continue;
      const column = `profile.${title}.${label}`;
      const values = dynamicValues.get(column) ?? [];
      if (item?.value !== null && item?.value !== undefined && stringValue(item.value) !== "") {
        values.push(stringValue(item.value));
      }
      dynamicValues.set(column, values);
    }
  }
  for (const [column, values] of dynamicValues) row[column] = values.join("\n");
  return row;
}

function metadataFields(metadata) {
  return {
    person_id: metadata?.person_id ?? "",
    query_type: metadata?.query_type ?? "",
    person_group: metadata?.person_group ?? "",
    difficulty: metadata?.difficulty ?? "",
    tags: (metadata?.tags ?? []).join("\n"),
  };
}

function runStatus(run, queryId) {
  const result = run.resultsByQuery.get(queryId);
  const failures = run.failuresByQuery.get(queryId) ?? [];
  if (run.conflicts.has(queryId) || (result && failures.length)) {
    return { status: "DATA_CONFLICT", count: result?.results?.length ?? 0, stage: failureStages(failures) };
  }
  if (result) {
    return { status: result.results.length ? "SUCCESS" : "NO_CANDIDATE", count: result.results.length, stage: "" };
  }
  if (failures.length) return { status: "FAILED", count: 0, stage: failureStages(failures) };
  return { status: "MISSING", count: 0, stage: "" };
}

function failureStages(failures) {
  return [...new Set(failures.map((item) => stringValue(item.stage)).filter(Boolean))].join("\n");
}

/** Build one Query summary row for single or paired runs. */
function buildQueryRow(mode, evaluationId, runs, queryId, metadata) {
  const row = { evaluation_id: evaluationId, query_id: queryId, ...metadataFields(metadata) };
  if (mode === "single") {
    const current = runStatus(runs[0], queryId);
    Object.assign(row, {
      current_status: current.status,
      current_candidate_count: current.count,
      current_failure_stage: current.stage,
      current_target_rank: "",
      current_hit1: "",
      current_hit3: "",
      current_hit5: "",
      current_mrr5: "",
      primary_failure_type: "",
      review_comment: "",
    });
  } else {
    const baseline = runStatus(runs[0], queryId);
    const candidateRun = runStatus(runs[1], queryId);
    Object.assign(row, {
      baseline_status: baseline.status,
      baseline_candidate_count: baseline.count,
      baseline_failure_stage: baseline.stage,
      candidate_status: candidateRun.status,
      candidate_candidate_count: candidateRun.count,
      candidate_failure_stage: candidateRun.stage,
      baseline_target_rank: "",
      candidate_target_rank: "",
      baseline_hit1: "",
      baseline_hit3: "",
      baseline_hit5: "",
      baseline_mrr5: "",
      candidate_hit1: "",
      candidate_hit3: "",
      candidate_hit5: "",
      candidate_mrr5: "",
      rank_change: "",
      change_type: "",
      regression_flag: "",
      primary_failure_type: "",
      review_comment: "",
    });
  }
  return row;
}

/** Convert failures and parsing errors into the workbook's failure rows. */
function collectFailureRows(evaluationId, runs) {
  const rows = [];
  for (const run of runs) {
    for (const [queryId, failures] of run.failuresByQuery.entries()) {
      for (const failure of failures) {
        rows.push({
          evaluation_id: evaluationId,
          run_label: run.spec.runLabel,
          system_version: run.spec.systemVersion,
          query_id: queryId,
          task_id: stringValue(failure.task_id),
          stage: stringValue(failure.stage),
          error: stringValue(failure.error),
          failure_type: "PIPELINE_FAILURE",
          source_file: "",
          source_line: "",
        });
      }
    }
    for (const error of run.inputErrors) {
      rows.push({
        evaluation_id: evaluationId,
        run_label: run.spec.runLabel,
        system_version: run.spec.systemVersion,
        query_id: stringValue(error.query_id),
        task_id: "",
        stage: "EXPORT_INPUT",
        error: stringValue(error.error),
        failure_type: "EXPORT_INPUT",
        source_file: stringValue(error.source_file),
        source_line: error.source_line ?? "",
      });
    }
  }
  return rows;
}

const TRACE_HEADERS = [
  "evaluation_id",
  "run_label",
  "system_version",
  "query_id",
  "person_id",
  "query_type",
  "person_group",
  "difficulty",
  "tags",
  "task_id",
  "candidate_id",
  "candidate_count_total",
  "candidate_rank",
  "rank_score",
];
const INSIGHTS_HEADERS = ["insights_status", "insights_description", "insights_links", "insights_data"];
const PHOTOS_HEADERS = [
  "photos_status",
  "photos_baseline_photo_url",
  "photos_identity_match_rate",
  "photos_authenticity_photos",
  "photos_match_photos",
  "photos_data",
];
const PROFILE_HEADERS = ["profile_status", "profile_data"];
const SOCIAL_HEADERS = [
  "social_status",
  "social_display_handles",
  "social_platforms",
  "social_urls",
  "social_profiles",
];
const SUMMARY_HEADERS = [
  "summary_avatar_url",
  "summary_confidence_level",
  "summary_primary_image_url",
  "summary_social_links",
  "summary_web_links",
  "summary_display_name",
  "summary_location",
  "summary_match_score",
  "summary_is_top_result",
  "summary_is_best_match",
];
const REVIEW_HEADERS = [
  "identity_judgement",
  "identity_evidence",
  "field_review_status",
  "failure_type",
  "reviewer",
  "review_comment",
];
const FAILURE_HEADERS = [
  "evaluation_id",
  "run_label",
  "system_version",
  "query_id",
  "task_id",
  "stage",
  "error",
  "failure_type",
  "source_file",
  "source_line",
];

const OMITTED_CANDIDATE_HEADERS = new Set([
  "system_version",
  "person_group",
  "difficulty",
  "tags",
  "insights_data",
  "photos_data",
  "profile_data",
  "social_profiles",
  "summary_display_name",
  "summary_location",
  "summary_match_score",
  "summary_is_top_result",
  "summary_is_best_match",
  "identity_judgement",
  "identity_evidence",
  "field_review_status",
  "failure_type",
  "reviewer",
  "review_comment",
]);

const FIELD_PROCESSING_NOTES = {
  run_label:
    "基准 Run 使用 baseline；接口检索返回结果使用 candidate（单 Run 传 --run-label candidate）",
  candidate_id: "该列移到 task_id 右侧",
  insights_links: "处理成 title：url；多条链接逐条换行；缺少 title 时只保留 url",
  summary_social_links: "处理成 title：url；多条链接逐条换行；缺少 title 时只保留 url",
  summary_web_links: "处理成 title：url；多条链接逐条换行；缺少 title 时只保留 url",
};

function allCandidateHeaders(profileColumns) {
  return [
    ...TRACE_HEADERS,
    ...INSIGHTS_HEADERS,
    ...PHOTOS_HEADERS,
    ...PROFILE_HEADERS,
    ...profileColumns,
    ...SOCIAL_HEADERS,
    ...SUMMARY_HEADERS,
    ...REVIEW_HEADERS,
  ];
}

function candidateHeaders(profileColumns) {
  return allCandidateHeaders(profileColumns).filter(
    (header) => !OMITTED_CANDIDATE_HEADERS.has(header),
  );
}

function queryHeaders(mode) {
  const metadata = ["evaluation_id", "query_id", "person_id", "query_type", "person_group", "difficulty", "tags"];
  if (mode === "single") {
    return [
      ...metadata,
      "current_status",
      "current_candidate_count",
      "current_failure_stage",
      "current_target_rank",
      "current_hit1",
      "current_hit3",
      "current_hit5",
      "current_mrr5",
      "primary_failure_type",
      "review_comment",
    ];
  }
  return [
    ...metadata,
    "baseline_status",
    "baseline_candidate_count",
    "baseline_failure_stage",
    "candidate_status",
    "candidate_candidate_count",
    "candidate_failure_stage",
    "baseline_target_rank",
    "candidate_target_rank",
    "baseline_hit1",
    "baseline_hit3",
    "baseline_hit5",
    "baseline_mrr5",
    "candidate_hit1",
    "candidate_hit3",
    "candidate_hit5",
    "candidate_mrr5",
    "rank_change",
    "change_type",
    "regression_flag",
    "primary_failure_type",
    "review_comment",
  ];
}

/** Build the editable dictionary shown beside the workbook notes. */
function buildFieldCatalog(headers) {
  const definitions = {
    evaluation_id: ["本次评测批次标识", "导出参数 --evaluation-id", "文本", "eval-20260722"],
    run_label: ["本行所属运行标签", "导出参数 --run-label", "文本", "current / baseline / candidate"],
    system_version: ["被测系统版本", "导出参数 --system-version", "文本", "v1.2"],
    query_id: ["查询唯一标识", "results.jsonl.input_id", "文本", "query-001"],
    person_id: ["被检索人物标识", "Query 元数据.person_id", "文本或空值", "person-001"],
    query_type: ["查询类型", "Query 元数据.query_type", "文本或空值", "Q1"],
    person_group: ["人物分组", "Query 元数据.person_group", "文本或空值", "C"],
    difficulty: ["查询难度", "Query 元数据.difficulty", "文本或空值", "medium"],
    tags: ["查询标签", "Query 元数据.tags", "多行文本；每个标签一行", "common_name\\nfew_clues"],
    task_id: ["搜索任务标识", "results.jsonl.task_id", "文本", "task-001"],
    candidate_count_total: [
      "本次查询返回的候选人总数",
      "results.jsonl.candidate_count_total（GetTask.data.candidate_count）",
      "整数或空值",
      "8",
    ],
    candidate_rank: [
      "候选人在本次查询中的名次",
      "results[].candidate_rank；旧数据缺失时按数组顺序生成",
      "正整数，当前通常为 1–5",
      "1",
    ],
    rank_score: [
      "候选人的接口排序分数",
      "results[].rank_score（ListTaskCandidates item）",
      "数值或空值",
      "0.91",
    ],
    candidate_id: ["候选人唯一标识", "results[].candidate_id", "文本", "candidate-001"],
    insights_status: ["洞察模块状态", "results[].ui_sections.insights.status", "枚举文本或空值", "data"],
    insights_description: ["第一条洞察描述", "results[].ui_sections.insights.data.items[0].description", "文本或空值", "Known public profile"],
    insights_links: ["第一条洞察的证据链接", "results[].ui_sections.insights.data.items[0].links", "多行文本；每条 title：url", "Public source：https://..."],
    insights_data: ["洞察模块完整 data", "results[].ui_sections.insights.data", "JSON 文本；超长转 Raw数据", "{\"count\":1,...}"],
    photos_status: ["照片模块状态", "results[].ui_sections.photos.status", "枚举文本或空值", "data"],
    photos_baseline_photo_url: ["基准照片地址", "results[].ui_sections.photos.data.baseline_photo_url", "URL 文本或空值", "https://.../base.jpg"],
    photos_identity_match_rate: ["照片身份匹配率", "results[].ui_sections.photos.data.identity_match_rate", "数值或空值", "0.75"],
    photos_authenticity_photos: ["真实性照片集合", "results[].ui_sections.photos.data.authenticity_photos", "JSON 文本或空值", "[{\"url\":\"https://...\"}]"],
    photos_match_photos: ["匹配照片集合", "results[].ui_sections.photos.data.match_photos", "JSON 文本或空值", "[]"],
    photos_data: ["照片模块完整 data", "results[].ui_sections.photos.data", "JSON 文本；超长转 Raw数据", "{\"baseline_photo_url\":...}"],
    profile_status: ["档案模块状态", "results[].ui_sections.profile.status", "枚举文本或空值", "data"],
    profile_data: ["档案模块完整 data", "results[].ui_sections.profile.data", "JSON 文本；超长转 Raw数据", "{\"sections\":[...]}"],
    social_status: ["社交模块状态", "results[].ui_sections.social.status", "枚举文本或空值", "data"],
    social_display_handles: ["社交账号展示名", "results[].ui_sections.social.data.profiles[].display_handle", "多行文本；每个账号一行", "first\\nsecond"],
    social_platforms: ["社交平台", "results[].ui_sections.social.data.profiles[].platform", "多行文本；与账号逐行对应", "linkedin\\nx"],
    social_urls: ["社交主页地址", "results[].ui_sections.social.data.profiles[].url", "多行 URL；与账号逐行对应", "https://linkedin.com/..."],
    social_profiles: ["社交账号完整集合", "results[].ui_sections.social.data.profiles", "JSON 文本；超长转 Raw数据", "[{\"platform\":\"linkedin\",...}]"],
    summary_avatar_url: ["摘要头像地址", "results[].ui_sections.summary.data.avatar_url", "URL 文本或空值", "https://.../avatar.jpg"],
    summary_confidence_level: ["系统置信等级", "results[].ui_sections.summary.data.confidence_level", "枚举文本或空值", "HIGH"],
    summary_primary_image_url: ["摘要主图地址", "results[].ui_sections.summary.data.primary_image.url", "URL 文本或空值", "https://.../primary.jpg"],
    summary_social_links: ["摘要社交链接", "results[].ui_sections.summary.data.social_links", "多行文本；每条 title：url", "LinkedIn：https://..."],
    summary_web_links: ["摘要网页链接", "results[].ui_sections.summary.data.web_links", "多行文本；每条 title：url", "Wikipedia：https://..."],
    summary_display_name: ["摘要展示姓名", "results[].ui_sections.summary.data.display_name", "文本或空值", "Example Person"],
    summary_location: ["摘要地点", "results[].ui_sections.summary.data.location", "文本或空值", "Shanghai"],
    summary_match_score: ["摘要匹配分数", "results[].ui_sections.summary.data.match_score", "数值或空值", "95"],
    summary_is_top_result: ["是否标记为首位结果", "results[].ui_sections.summary.data.is_top_result", "布尔值或空值", "TRUE"],
    summary_is_best_match: ["是否标记为最佳匹配", "results[].ui_sections.summary.data.is_best_match", "布尔值或空值", "TRUE"],
    identity_judgement: ["人工身份判断", "人工直接填写 Excel", "枚举：correct / wrong / unverifiable", "correct"],
    identity_evidence: ["人工身份判断依据", "人工直接填写 Excel", "文本", "姓名与任职经历一致"],
    field_review_status: ["人工字段质量判断", "人工直接填写 Excel", "枚举：correct / partial / wrong / unverifiable / not_returned / not_applicable", "partial"],
    failure_type: ["人工归类的失败类型", "人工直接填写 Excel", "文本", "wrong_person"],
    reviewer: ["复核人", "人工直接填写 Excel", "文本", "张三"],
    review_comment: ["复核备注", "人工直接填写 Excel", "文本", "需补充证据"],
  };
  return headers.map((header, index) => {
    const dynamicMatch = /^profile\.([^.]+)\.(.+)$/.exec(header);
    const definition = definitions[header] ?? [
      dynamicMatch
        ? `Profile「${dynamicMatch[1]}」中的「${dynamicMatch[2]}」`
        : "未定义字段",
      dynamicMatch
        ? `results[].ui_sections.profile.data.sections[title=${dynamicMatch[1]}].items[label=${dynamicMatch[2]}].value`
        : "待补充",
      dynamicMatch ? "文本；重复值换行" : "待补充",
      dynamicMatch ? "文本" : "",
    ];
    return {
      序号: index + 1,
      当前表头: header,
      中文含义: definition[0],
      "来源路径/生成规则": definition[1],
      内容格式: definition[2],
      示例格式: definition[3],
      是否保留: OMITTED_CANDIDATE_HEADERS.has(header) ? "否" : "是",
      新表头: "",
      "处理规则/备注": FIELD_PROCESSING_NOTES[header] ?? "",
    };
  });
}

/** Move over-limit strings to reversible Raw rows and replace the main value with a reference. */
function extractRawRows(candidateRows, visibleHeaders) {
  const rawRows = [];
  for (const row of candidateRows) {
    for (const fieldName of visibleHeaders) {
      const value = row[fieldName];
      if (typeof value !== "string" || value.length <= RAW_TRIGGER_LENGTH) continue;
      const rawRef = `RAW:${row.run_label}:${row.query_id}:${row.candidate_id}:${fieldName}`;
      const chunks = [];
      for (let offset = 0; offset < value.length; offset += RAW_CHUNK_LENGTH) {
        chunks.push(value.slice(offset, offset + RAW_CHUNK_LENGTH));
      }
      chunks.forEach((content, index) => {
        rawRows.push({
          raw_ref: rawRef,
          run_label: row.run_label,
          query_id: row.query_id,
          candidate_id: row.candidate_id,
          field_name: fieldName,
          chunk_index: index + 1,
          chunk_total: chunks.length,
          content,
        });
      });
      row[fieldName] = `[超长内容见 Raw数据] ${rawRef}`;
    }
  }
  return rawRows;
}

/** Build the complete workbook-neutral model shared by tests and authoring. */
function buildModel(mode, evaluationId, runs, metadata) {
  const profileColumns = collectProfileColumns(runs);
  const candidateRows = [];
  const runOrder = new Map(runs.map((run, index) => [run.spec.runLabel, index]));
  for (const run of runs) {
    for (const [queryId, record] of run.resultsByQuery.entries()) {
      record.results.forEach((candidate, index) => {
        if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
          run.inputErrors.push({
            source_file: run.spec.resultsFile,
            query_id: queryId,
            error: `results[${index}] 不是对象，已跳过`,
          });
          return;
        }
        candidateRows.push(
          flattenCandidate({
            evaluationId,
            run,
            queryId,
            taskId: record.task_id,
            candidateCountTotal: record.candidate_count_total,
            candidate,
            candidateRank:
              Number.isInteger(candidate.candidate_rank) && candidate.candidate_rank > 0
                ? candidate.candidate_rank
                : index + 1,
            metadata: metadata.get(queryId),
          }),
        );
      });
    }
  }
  candidateRows.sort(
    (left, right) =>
      left.query_id.localeCompare(right.query_id) ||
      runOrder.get(left.run_label) - runOrder.get(right.run_label) ||
      left.candidate_rank - right.candidate_rank,
  );

  const queryIds = new Set(metadata.keys());
  for (const run of runs) {
    for (const queryId of run.resultsByQuery.keys()) queryIds.add(queryId);
    for (const queryId of run.failuresByQuery.keys()) queryIds.add(queryId);
  }
  const queryRows = [...queryIds]
    .sort((left, right) => left.localeCompare(right))
    .map((queryId) => buildQueryRow(mode, evaluationId, runs, queryId, metadata.get(queryId)));
  const failureRows = collectFailureRows(evaluationId, runs);
  const headers = candidateHeaders(profileColumns);
  const rawRows = extractRawRows(candidateRows, headers);
  return {
    mode,
    profileColumns,
    candidateHeaders: headers,
    fieldCatalogRows: buildFieldCatalog(allCandidateHeaders(profileColumns)),
    candidateRows,
    queryRows,
    failureRows,
    rawRows,
  };
}

function columnName(index) {
  let current = index + 1;
  let name = "";
  while (current > 0) {
    current -= 1;
    name = String.fromCharCode(65 + (current % 26)) + name;
    current = Math.floor(current / 26);
  }
  return name;
}

function safeExcelValue(value) {
  if (typeof value === "string" && /^[=+\-@]/.test(value)) return `'${value}`;
  return value === undefined ? null : value;
}

/** Write a rectangular data sheet with a consistent readable table style. */
function writeDataSheet(workbook, name, headers, rows, tableName, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [headers, ...rows.map((row) => headers.map((header) => safeExcelValue(row[header] ?? null)))];
  sheet.getRangeByIndexes(0, 0, matrix.length, headers.length).values = matrix;
  sheet.freezePanes.freezeRows(1);

  const headerRange = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  headerRange.format = {
    fill: "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#17365D" },
  };
  headerRange.format.rowHeight = 30;

  if (rows.length) {
    const dataRange = sheet.getRangeByIndexes(1, 0, rows.length, headers.length);
    dataRange.format = { verticalAlignment: "top", wrapText: true };
    dataRange.format.rowHeight = options.rowHeight ?? 42;
    const endCell = `${columnName(headers.length - 1)}${rows.length + 1}`;
    const table = sheet.tables.add(`A1:${endCell}`, true, tableName);
    table.style = "TableStyleMedium2";
  }

  headers.forEach((header, index) => {
    const width = options.widths?.[header] ?? defaultWidth(header);
    sheet.getRangeByIndexes(0, index, Math.max(matrix.length, 1), 1).format.columnWidth = width;
  });
  applySemanticNumberFormats(sheet, headers, rows.length);
  return sheet;
}

function defaultWidth(header) {
  if (["candidate_rank", "source_line"].includes(header)) return 15;
  if (/candidate_count|target_rank/.test(header)) return 22;
  if (/status|difficulty|query_type|person_group|confidence|match_rate|match_score/.test(header)) return 16;
  if (/url|links|data|profiles|evidence|comment|error|description/.test(header)) return 34;
  if (/id|version|label|stage|type/.test(header)) return 20;
  return 18;
}

/** 按列语义设置数字格式，避免比率、成本和耗时被写成文本。 */
function applySemanticNumberFormats(sheet, headers, rowCount) {
  if (!rowCount) return;
  headers.forEach((header, index) => {
    let format = null;
    if (
      /(?:rate|accuracy|completeness)(?:_delta)?$/.test(header)
      || ["value", "preview_value", "threshold"].includes(header)
    ) {
      format = "0.0%";
    } else if (/cost/.test(header)) {
      format = "#,##0.0000";
    } else if (/duration_ms/.test(header)) {
      format = "#,##0";
    } else if (
      /(?:^|_)(?:count|numerator|denominator|rank|chunk_index|chunk_total)$/.test(header)
    ) {
      format = "#,##0";
    } else if (/score/.test(header)) {
      format = "0.0000";
    }
    if (format) {
      sheet.getRangeByIndexes(1, index, rowCount, 1).format.numberFormat = format;
    }
  });
}

function applyManualValidations(sheet, headers, rowCount) {
  if (!rowCount) return;
  const rules = {
    identity_judgement: ["correct", "wrong", "unverifiable"],
    field_review_status: [
      "correct",
      "partial",
      "wrong",
      "unverifiable",
      "not_returned",
      "not_applicable",
    ],
  };
  for (const [header, values] of Object.entries(rules)) {
    const index = headers.indexOf(header);
    if (index < 0) continue;
    const range = sheet.getRangeByIndexes(1, index, rowCount, 1);
    range.dataValidation = { rule: { type: "list", values } };
    range.format.fill = "#FFF2CC";
  }
}

/** Add the user-maintained candidate-field dictionary to the right of the notes. */
function writeFieldCatalog(sheet, rows) {
  const headers = [
    "序号",
    "当前表头",
    "中文含义",
    "来源路径/生成规则",
    "内容格式",
    "示例格式",
    "是否保留",
    "新表头",
    "处理规则/备注",
  ];
  const startColumn = 3;
  const matrix = [headers, ...rows.map((row) => headers.map((header) => safeExcelValue(row[header] ?? null)))];
  sheet.getRangeByIndexes(0, startColumn, matrix.length, headers.length).values = matrix;

  const headerRange = sheet.getRangeByIndexes(0, startColumn, 1, headers.length);
  headerRange.format = {
    fill: "#548235",
    font: { bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#375623" },
  };
  headerRange.format.rowHeight = 30;

  if (rows.length) {
    const dataRange = sheet.getRangeByIndexes(1, startColumn, rows.length, headers.length);
    dataRange.format = { verticalAlignment: "top", wrapText: true };
    dataRange.format.rowHeight = 36;
    const endCell = `${columnName(startColumn + headers.length - 1)}${rows.length + 1}`;
    const table = sheet.tables.add(`D1:${endCell}`, true, "CandidateFieldCatalogTable");
    table.style = "TableStyleMedium4";

    const editableRange = sheet.getRangeByIndexes(1, startColumn + 6, rows.length, 3);
    editableRange.format.fill = "#FFF2CC";
    sheet.getRangeByIndexes(1, startColumn + 6, rows.length, 1).dataValidation = {
      rule: { type: "list", values: ["是", "否", "待定"] },
    };
  }

  [8, 25, 30, 52, 28, 28, 14, 24, 40].forEach((width, index) => {
    sheet.getRangeByIndexes(0, startColumn + index, matrix.length, 1).format.columnWidth = width;
  });
}

function setFormula(sheet, rowIndex, columnIndex, formula) {
  sheet.getRangeByIndexes(rowIndex, columnIndex, 1, 1).formulas = [[formula]];
}

/** Add auditable Hit@K/MRR formulas driven by the editable target-rank cells. */
function applyQueryFormulas(sheet, headers, rowCount, mode) {
  const index = Object.fromEntries(headers.map((header, position) => [header, position]));
  for (let rowIndex = 1; rowIndex <= rowCount; rowIndex += 1) {
    const excelRow = rowIndex + 1;
    const addMetricFormulas = (prefix) => {
      const rankColumn = columnName(index[`${prefix}_target_rank`]);
      for (const k of [1, 3, 5]) {
        setFormula(
          sheet,
          rowIndex,
          index[`${prefix}_hit${k}`],
          `=IF(ISNUMBER(${rankColumn}${excelRow}),--(${rankColumn}${excelRow}<=${k}),\"\")`,
        );
      }
      setFormula(
        sheet,
        rowIndex,
        index[`${prefix}_mrr5`],
        `=IF(ISNUMBER(${rankColumn}${excelRow}),IF(AND(${rankColumn}${excelRow}>=1,${rankColumn}${excelRow}<=5),1/${rankColumn}${excelRow},0),\"\")`,
      );
    };

    if (mode === "single") {
      addMetricFormulas("current");
    } else {
      addMetricFormulas("baseline");
      addMetricFormulas("candidate");
      const baselineRank = columnName(index.baseline_target_rank);
      const candidateRank = columnName(index.candidate_target_rank);
      setFormula(
        sheet,
        rowIndex,
        index.rank_change,
        `=IF(AND(ISNUMBER(${baselineRank}${excelRow}),ISNUMBER(${candidateRank}${excelRow})),${baselineRank}${excelRow}-${candidateRank}${excelRow},\"\")`,
      );
    }
  }

  for (const header of headers.filter((item) => /target_rank|change_type|regression_flag|failure_type|review_comment/.test(item))) {
    const column = index[header];
    if (column >= 0 && rowCount) {
      sheet.getRangeByIndexes(1, column, rowCount, 1).format.fill = "#FFF2CC";
    }
  }
}

/** Author, inspect, optionally render, and export the final workbook. */
async function writeWorkbook(artifactTool, outputPath, model, context) {
  const { Workbook, SpreadsheetFile } = artifactTool;
  const workbook = Workbook.create();
  const candidateHeaders = model.candidateHeaders;
  const qHeaders = queryHeaders(model.mode);
  const candidateSheet = writeDataSheet(
    workbook,
    "候选结果",
    candidateHeaders,
    model.candidateRows,
    "CandidateResultsTable",
  );
  applyManualValidations(candidateSheet, candidateHeaders, model.candidateRows.length);

  const querySheet = writeDataSheet(
    workbook,
    "Query对比",
    qHeaders,
    model.queryRows,
    "QueryComparisonTable",
  );
  applyQueryFormulas(querySheet, qHeaders, model.queryRows.length, model.mode);

  writeDataSheet(workbook, "失败记录", FAILURE_HEADERS, model.failureRows, "FailureRecordsTable");

  const notes = [
    { item: "evaluation_id", value: context.evaluationId },
    { item: "运行模式", value: model.mode },
    { item: "生成时间", value: `UTC ${new Date().toISOString()}` },
    {
      item: "Run",
      value: context.runs
        .map((run) => `${run.spec.runLabel} | ${run.spec.systemVersion} | ${run.spec.resultsFile}`)
        .join("\n"),
    },
    { item: "Query 元数据", value: context.metadataPath || "未提供" },
    { item: "候选人数", value: model.candidateRows.length },
    { item: "Query 数", value: model.queryRows.length },
    { item: "失败/输入异常数", value: model.failureRows.length },
    { item: "Raw 引用数据块数", value: model.rawRows.length },
    { item: "评测口径", value: "当前只处理 Top 5；系统 confidence 不等于人工身份结论" },
    { item: "Profile 规则", value: "baseline/candidate 字段并集；列名为 profile.<section>.<label>" },
    { item: "人工复核", value: "黄色单元格为人工填写区域；先确认身份，再评价字段" },
  ];
  const notesSheet = writeDataSheet(workbook, "说明", ["item", "value"], notes, "WorkbookNotesTable", {
    widths: { item: 24, value: 70 },
    rowHeight: 36,
  });
  writeFieldCatalog(notesSheet, model.fieldCatalogRows);

  if (model.rawRows.length) {
    writeDataSheet(
      workbook,
      "Raw数据",
      ["raw_ref", "run_label", "query_id", "candidate_id", "field_name", "chunk_index", "chunk_total", "content"],
      model.rawRows,
      "RawDataTable",
      { widths: { raw_ref: 45, content: 80 }, rowHeight: 50 },
    );
  }

  const overview = await workbook.inspect({
    kind: "sheet",
    include: "id,name",
    maxChars: 3000,
  });
  if (!overview.ndjson.includes("候选结果") || !overview.ndjson.includes("Query对比")) {
    throw new Error("工作簿校验失败：缺少必要 Sheet");
  }
  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "formula error scan",
  });
  if (/#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/.test(formulaErrors.ndjson)) {
    throw new Error(`工作簿公式校验失败: ${formulaErrors.ndjson}`);
  }

  const candidateCheck = await workbook.inspect({
    kind: "table",
    range: `候选结果!A1:N${Math.min(model.candidateRows.length + 1, 6)}`,
    include: "values,formulas",
    tableMaxRows: 6,
    tableMaxCols: 12,
    maxChars: 5000,
  });
  const fieldCatalogCheck = await workbook.inspect({
    kind: "table",
    range: `说明!D1:L${Math.min(model.fieldCatalogRows.length + 1, 16)}`,
    include: "values,formulas",
    tableMaxRows: 16,
    tableMaxCols: 9,
    maxChars: 8000,
  });
  if (!fieldCatalogCheck.ndjson.includes("rank_score")) {
    throw new Error("工作簿校验失败：字段整理表缺少 rank_score");
  }
  const queryCheck = await workbook.inspect({
    kind: "table",
    range: `Query对比!A1:${columnName(qHeaders.length - 1)}${Math.min(model.queryRows.length + 1, 6)}`,
    include: "values,formulas",
    tableMaxRows: 6,
    tableMaxCols: qHeaders.length,
    maxChars: 8000,
  });
  const queryFormulaCheck = await workbook.inspect({
    kind: "formula",
    sheetId: "Query对比",
    range: `A1:${columnName(qHeaders.length - 1)}${Math.min(model.queryRows.length + 1, 6)}`,
    maxChars: 8000,
    options: { maxResults: 100 },
  });
  if (model.queryRows.length && !queryFormulaCheck.ndjson.includes("ISNUMBER")) {
    throw new Error("工作簿校验失败：Query对比 Sheet 缺少 Hit/MRR 公式");
  }

  const verifyDir = process.env.SEARCHTOOL_VERIFY_DIR;
  if (verifyDir) {
    await fs.mkdir(verifyDir, { recursive: true });
    const sheets = ["候选结果", "Query对比", "失败记录", "说明"];
    if (model.rawRows.length) sheets.push("Raw数据");
    for (const sheetName of sheets) {
      const sheet = workbook.worksheets.getItem(sheetName);
      const used = sheet.getUsedRange(true);
      const rowCount = Math.min((used?.rowCount ?? 1), 6);
      const usedColumnCount = used?.columnCount ?? 1;
      for (let startColumn = 0; startColumn < usedColumnCount; startColumn += 12) {
        const endColumn = Math.min(startColumn + 11, usedColumnCount - 1);
        const range = `${columnName(startColumn)}1:${columnName(endColumn)}${Math.max(rowCount, 1)}`;
        const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
        await fs.writeFile(
          path.join(verifyDir, `${sheetName}_${columnName(startColumn)}-${columnName(endColumn)}.png`),
          new Uint8Array(await preview.arrayBuffer()),
        );
      }
    }
    await fs.writeFile(path.join(verifyDir, "inspect.ndjson"), overview.ndjson, "utf8");
    await fs.writeFile(path.join(verifyDir, "candidate_check.ndjson"), candidateCheck.ndjson, "utf8");
    await fs.writeFile(path.join(verifyDir, "field_catalog_check.ndjson"), fieldCatalogCheck.ndjson, "utf8");
    await fs.writeFile(path.join(verifyDir, "query_check.ndjson"), queryCheck.ndjson, "utf8");
    await fs.writeFile(
      path.join(verifyDir, "query_formula_check.ndjson"),
      queryFormulaCheck.ndjson,
      "utf8",
    );
  }

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const tempPath = `${outputPath}.tmp-${process.pid}.xlsx`;
  try {
    const blob = await SpreadsheetFile.exportXlsx(workbook);
    await blob.save(tempPath);
    await fs.rename(tempPath, outputPath);
  } catch (error) {
    await fs.rm(tempPath, { force: true });
    throw error;
  } finally {
    await fs.rm(`${tempPath}.inspect.ndjson`, { force: true });
  }
}

/** 生成并校验 ReportModel processed Excel，不重新计算任何报告指标。 */
async function writeProcessedWorkbook(artifactTool, outputPath, model) {
  const { Workbook, SpreadsheetFile } = artifactTool;
  const workbook = Workbook.create();
  const reportMetadata = model.reportModel.metadata ?? {};
  const reportSummary = model.reportModel.summary ?? {};
  const notes = [
    { item: "report_id", value: reportMetadata.report_id ?? "" },
    { item: "evaluation_id", value: reportMetadata.evaluation_id ?? "" },
    { item: "报告类型", value: reportMetadata.report_type ?? "" },
    { item: "ReportModel", value: reportMetadata.report_model_version ?? "report-model-v1" },
    { item: "评估阶段", value: reportMetadata.evaluation_phase ?? "" },
    { item: "候选系统版本", value: reportMetadata.candidate_system_version ?? "" },
    { item: "基线系统版本", value: reportMetadata.baseline_system_version ?? "" },
    { item: "数据标识", value: reportMetadata.data_marker ?? "" },
    { item: "生成时间", value: reportMetadata.generated_at ?? "" },
    { item: "字段配置", value: reportMetadata.schema_version ?? "" },
    { item: "基准版本", value: reportMetadata.baseline_version ?? "" },
    {
      item: "指标规则",
      value: reportMetadata.metrics_rule_version ?? reportMetadata.rule_version ?? "",
    },
    { item: "处理规则", value: reportMetadata.rule_version ?? "" },
    { item: "正式状态", value: reportSummary.formal_ready ? "READY" : "PENDING_REVIEW" },
    {
      item: "参考线建议",
      value: model.reportModel.threshold_assessment?.recommendation ?? "未配置或未就绪",
    },
    { item: "候选人数", value: model.candidateRows.length },
    { item: "Query 数", value: model.queryRows.length },
    { item: "失败记录数", value: model.failureRows.length },
    { item: "空值规则", value: "未接入、无数据和未就绪均保持空单元格，不补0。" },
    { item: "成本单位", value: "正式接口单位尚未确认，按接口原始数字导出。" },
    {
      item: "风险说明",
      value: (model.reportModel.warnings ?? []).join("\n"),
    },
  ];

  writeDataSheet(
    workbook,
    "说明",
    ["item", "value"],
    notes,
    "ProcessedNotesTable",
    { widths: { item: 24, value: 80 }, rowHeight: 42 },
  );
  writeDataSheet(
    workbook,
    "核心指标",
    CORE_METRIC_HEADERS,
    model.coreMetricRows,
    "ProcessedCoreMetricsTable",
  );
  writeDataSheet(
    workbook,
    "Query明细",
    PROCESSED_QUERY_HEADERS,
    model.queryRows,
    "ProcessedQueryTable",
  );
  writeDataSheet(
    workbook,
    "候选结果",
    model.candidateHeaders,
    model.candidateRows,
    "ProcessedCandidateTable",
  );
  writeDataSheet(
    workbook,
    "同条件对比",
    SAME_CONDITION_HEADERS,
    model.sameConditionRows,
    "ProcessedSameConditionTable",
  );
  writeDataSheet(
    workbook,
    "新增线索",
    NEW_CLUE_HEADERS,
    model.newClueRows,
    "ProcessedNewClueTable",
  );
  writeDataSheet(
    workbook,
    "模块字段统计",
    MODULE_FIELD_HEADERS,
    model.moduleFieldRows,
    "ProcessedModuleFieldTable",
  );
  writeDataSheet(
    workbook,
    "失败记录",
    PROCESSED_FAILURE_HEADERS,
    model.failureRows,
    "ProcessedFailureTable",
  );
  writeDataSheet(
    workbook,
    "人工复核",
    PROCESSED_REVIEW_HEADERS,
    model.reviewRows,
    "ProcessedReviewTable",
  );
  if (model.rawRows.length) {
    writeDataSheet(
      workbook,
      "Raw数据",
      [
        "raw_ref",
        "run_label",
        "query_id",
        "candidate_id",
        "field_name",
        "chunk_index",
        "chunk_total",
        "content",
      ],
      model.rawRows,
      "ProcessedRawTable",
      { widths: { raw_ref: 45, content: 80 }, rowHeight: 50 },
    );
  }

  const overview = await workbook.inspect({
    kind: "sheet",
    include: "id,name",
    maxChars: 5000,
  });
  const requiredSheets = [
    "说明",
    "核心指标",
    "Query明细",
    "候选结果",
    "同条件对比",
    "新增线索",
    "模块字段统计",
    "失败记录",
    "人工复核",
  ];
  for (const required of requiredSheets) {
    if (!overview.ndjson.includes(required)) {
      throw new Error(`工作簿校验失败：缺少 ${required} Sheet`);
    }
  }
  const formulaErrors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 },
    summary: "processed formula error scan",
  });
  if (/#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/.test(formulaErrors.ndjson)) {
    throw new Error(`工作簿公式校验失败: ${formulaErrors.ndjson}`);
  }
  const coreMetricCheck = await workbook.inspect({
    kind: "table",
    range: `核心指标!A1:${columnName(CORE_METRIC_HEADERS.length - 1)}${Math.min(model.coreMetricRows.length + 1, 20)}`,
    include: "values,formulas",
    tableMaxRows: 20,
    tableMaxCols: CORE_METRIC_HEADERS.length,
    maxChars: 12000,
  });
  const queryCheck = await workbook.inspect({
    kind: "table",
    range: `Query明细!A1:${columnName(PROCESSED_QUERY_HEADERS.length - 1)}${Math.min(model.queryRows.length + 1, 6)}`,
    include: "values,formulas",
    tableMaxRows: 6,
    tableMaxCols: PROCESSED_QUERY_HEADERS.length,
    maxChars: 10000,
  });

  const verifyDir = process.env.SEARCHTOOL_VERIFY_DIR;
  if (verifyDir) {
    await fs.mkdir(verifyDir, { recursive: true });
    const sheets = [...requiredSheets];
    if (model.rawRows.length) sheets.push("Raw数据");
    for (const sheetName of sheets) {
      const sheet = workbook.worksheets.getItem(sheetName);
      const used = sheet.getUsedRange(true);
      const rowCount = Math.min(used?.rowCount ?? 1, 8);
      const columnCount = Math.min(used?.columnCount ?? 1, 12);
      const range = `A1:${columnName(columnCount - 1)}${Math.max(rowCount, 1)}`;
      const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
      await fs.writeFile(
        path.join(verifyDir, `processed_${sheetName}.png`),
        new Uint8Array(await preview.arrayBuffer()),
      );
    }
    await fs.writeFile(
      path.join(verifyDir, "processed_inspect.ndjson"),
      overview.ndjson,
      "utf8",
    );
    await fs.writeFile(
      path.join(verifyDir, "processed_core_metrics.ndjson"),
      coreMetricCheck.ndjson,
      "utf8",
    );
    await fs.writeFile(
      path.join(verifyDir, "processed_query_details.ndjson"),
      queryCheck.ndjson,
      "utf8",
    );
  }

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const tempPath = `${outputPath}.tmp-${process.pid}.xlsx`;
  try {
    const blob = await SpreadsheetFile.exportXlsx(workbook);
    await blob.save(tempPath);
    await fs.rename(tempPath, outputPath);
  } catch (error) {
    await fs.rm(tempPath, { force: true });
    throw error;
  }
}

async function main() {
  if (process.argv.slice(2).some((argument) => ["-h", "--help"].includes(argument))) {
    printHelp();
    return;
  }
  const { mode, values } = parseArgs(process.argv.slice(2));
  if (mode === "processed") {
    const model = await buildProcessedModel(
      path.resolve(values["input-file"]),
      path.resolve(values["report-model"]),
    );
    if (process.env.SEARCHTOOL_MODEL_OUTPUT) {
      await fs.writeFile(
        process.env.SEARCHTOOL_MODEL_OUTPUT,
        JSON.stringify(model, null, 2),
        "utf8",
      );
    }
    if (process.env.SEARCHTOOL_SKIP_WORKBOOK === "1") {
      console.log(
        `模型生成完成（processed）：Query ${model.queryRows.length}，候选人 ${model.candidateRows.length}`,
      );
      return;
    }
    const artifactTool = await loadArtifactTool();
    const outputPath = path.resolve(values.output);
    await writeProcessedWorkbook(artifactTool, outputPath, model);
    console.log(
      `导出完成：${outputPath}（Query ${model.queryRows.length}，候选人 ${model.candidateRows.length}）`,
    );
    return;
  }
  const runs =
    mode === "single"
      ? [
          await loadRun({
            runDir: values["run-dir"] ? path.resolve(values["run-dir"]) : "",
            resultsFile: values["results-file"] || "",
            failuresFile: values["failures-file"] || "",
            runLabel: values["run-label"],
            systemVersion: values["system-version"],
          }),
        ]
      : [
          await loadRun({
            runDir: values["baseline-dir"] ? path.resolve(values["baseline-dir"]) : "",
            resultsFile: values["baseline-results-file"] || "",
            failuresFile: values["baseline-failures-file"] || "",
            runLabel: "baseline",
            systemVersion: values["baseline-version"],
          }),
          await loadRun({
            runDir: values["candidate-dir"] ? path.resolve(values["candidate-dir"]) : "",
            resultsFile: values["candidate-results-file"] || "",
            failuresFile: values["candidate-failures-file"] || "",
            runLabel: "candidate",
            systemVersion: values["candidate-version"],
          }),
        ];
  const metadataPath = values.metadata ? path.resolve(values.metadata) : "";
  const metadata = await loadMetadata(metadataPath);
  const model = buildModel(mode, values["evaluation-id"], runs, metadata);

  if (process.env.SEARCHTOOL_MODEL_OUTPUT) {
    await fs.writeFile(
      process.env.SEARCHTOOL_MODEL_OUTPUT,
      JSON.stringify(model, null, 2),
      "utf8",
    );
  }

  // Unit tests can validate the shared data model without paying the workbook
  // startup cost. Normal CLI runs never set this internal environment flag.
  if (process.env.SEARCHTOOL_SKIP_WORKBOOK === "1") {
    console.log(
      `模型生成完成（测试模式）：Query ${model.queryRows.length}，候选人 ${model.candidateRows.length}`,
    );
    return;
  }

  const artifactTool = await loadArtifactTool();
  const outputPath = path.resolve(values.output);
  await writeWorkbook(artifactTool, outputPath, model, {
    evaluationId: values["evaluation-id"],
    runs,
    metadataPath,
  });
  console.log(
    `导出完成：${outputPath}（Query ${model.queryRows.length}，候选人 ${model.candidateRows.length}，失败/异常 ${model.failureRows.length}）`,
  );
}

main().catch((error) => {
  console.error(`导出失败: ${error.message}`);
  process.exitCode = 1;
});
