#!/usr/bin/env node
/**
 * 正向关系阶段 E2E 截图数据集生成入口。
 *
 * 所有写入都必须先通过非覆盖预检。批量编排会在对应行为测试转绿后加入，本文件当前
 * 先冻结用户要求的安全边界，避免任何后续渲染逻辑绕过它。
 */
const fs = require("node:fs");
const path = require("node:path");

const { STAGE_SCENARIOS } = require("./scenario_catalog.cjs");
const {
  STAGES,
  buildDataset,
  stageDirectoryName,
  validateDataset,
} = require("./dataset.cjs");
const {
  buildRenderTasks,
  validateRenderManifest,
  validateRenderedOutput,
  validateSourceArtifacts,
  writeRenderManifest,
  writeSourceArtifacts,
} = require("./artifacts.cjs");
const { renderScreenshots } = require("./render.cjs");
const {
  buildContactSheetPlans,
  validateContactSheets,
  writeContactSheets,
} = require("./qa.cjs");

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const DEFAULT_SOURCE_ROOT = path.join(
  PROJECT_ROOT,
  "datasets/relationship-stage-positive-v1",
);
const DEFAULT_OUTPUT_ROOT =
  "/Users/admin/人际关系项目/dating assitsatant/测试数据/聊天截图测试数据";
const STAGE_DIRECTORIES = Object.freeze(STAGES.map(stageDirectoryName));

/**
 * 确认最终数据集路径尚未存在。
 *
 * 允许图片根目录保存历史散装 PNG，但任何计划中的阶段目录或数据集源目录一旦存在就
 * 立即停止，防止重新运行时覆盖用户资产。
 *
 * @param {string} outputRoot 最终聊天截图根目录。
 * @param {string} sourceRoot Transcript、Case 与清单根目录。
 * @throws {Error} 任一目标已经存在时抛出。
 */
function assertFreshDestinations(outputRoot, sourceRoot) {
  // 迁移期间旧枚举目录和新双语目录都视为占用，防止生成器在两套目录并存时发布。
  for (const directoryName of new Set([...STAGES, ...STAGE_DIRECTORIES])) {
    const stagePath = path.join(outputRoot, directoryName);
    if (fs.existsSync(stagePath)) {
      throw new Error(`Refusing to overwrite stage directory: ${stagePath}`);
    }
  }
  if (fs.existsSync(sourceRoot)) {
    throw new Error(`Refusing to overwrite dataset source: ${sourceRoot}`);
  }
}

/**
 * 把已通过全部验收的临时数据移动到最终路径。
 *
 * 由于用户要求 16 个阶段直接位于既有图片根目录，无法通过一次目录 rename 完成原子
 * 发布。本函数记录每个已移动目录；任何一步失败都会把源文件和阶段目录移回临时位置，
 * 既不删除历史根级图片，也不留下半套数据。
 *
 * @param {{stagedOutputRoot: string, outputRoot: string, stagedSourceRoot: string,
 *   sourceRoot: string, stageDirectories: string[]}} options 临时与最终路径及有序目录列表。
 * @throws {Error} 路径缺失、目标已存在或移动失败时抛出，并尽力恢复到提交前状态。
 */
function commitStagedDataset(options) {
  const {
    stagedOutputRoot,
    outputRoot,
    stagedSourceRoot,
    sourceRoot,
    stageDirectories,
  } = options;
  if (!fs.existsSync(stagedOutputRoot) || !fs.existsSync(stagedSourceRoot)) {
    throw new Error("Staged output and source directories must both exist");
  }
  for (const directoryName of stageDirectories) {
    const destination = path.join(outputRoot, directoryName);
    if (fs.existsSync(destination)) throw new Error(`Destination already exists: ${destination}`);
    if (!fs.existsSync(path.join(stagedOutputRoot, directoryName))) {
      throw new Error(`Staged stage is missing: ${directoryName}`);
    }
  }
  if (fs.existsSync(sourceRoot)) throw new Error(`Destination already exists: ${sourceRoot}`);

  const movedStages = [];
  let sourceMoved = false;
  try {
    for (const directoryName of stageDirectories) {
      fs.renameSync(
        path.join(stagedOutputRoot, directoryName),
        path.join(outputRoot, directoryName),
      );
      movedStages.push(directoryName);
    }
    // Source 根目录最后移动，等价于一枚“发布完成”标志；阶段移动中途失败时不会留下
    // 看似完整、实际缺图的数据集入口。
    fs.renameSync(stagedSourceRoot, sourceRoot);
    sourceMoved = true;
    fs.rmdirSync(stagedOutputRoot);
  } catch (error) {
    fs.mkdirSync(stagedOutputRoot, { recursive: true });
    for (const directoryName of movedStages.reverse()) {
      const destination = path.join(outputRoot, directoryName);
      if (fs.existsSync(destination)) {
        fs.renameSync(destination, path.join(stagedOutputRoot, directoryName));
      }
    }
    if (sourceMoved && fs.existsSync(sourceRoot) && !fs.existsSync(stagedSourceRoot)) {
      fs.renameSync(sourceRoot, stagedSourceRoot);
    }
    throw error;
  }
}

/**
 * 验证已经发布的数据集和源文件清单。
 *
 * @param {{outputRoot?: string, sourceRoot?: string}} [options] 可覆盖默认绝对路径。
 * @returns {object} 图片、消息和源文件数量摘要。
 * @throws {Error} 目录结构、PNG 哈希或源文件数量与冻结计划不一致时抛出。
 */
function validateExistingDataset(options = {}) {
  const outputRoot = options.outputRoot || DEFAULT_OUTPUT_ROOT;
  const sourceRoot = options.sourceRoot || DEFAULT_SOURCE_ROOT;
  const cases = buildDataset(STAGE_SCENARIOS);
  const dataSummary = validateDataset(cases);
  const renderSummary = validateRenderedOutput(cases, outputRoot);
  const sourceSummary = validateSourceArtifacts(cases, sourceRoot);
  validateRenderManifest(renderSummary, sourceRoot);
  const qaPlans = buildContactSheetPlans(
    cases,
    outputRoot,
    path.join(sourceRoot, "qa"),
  );
  const qaSummary = validateContactSheets(qaPlans);
  return {
    ...dataSummary,
    png_count: renderSummary.png_count,
    total_png_bytes: renderSummary.total_bytes,
    ...sourceSummary,
    qa_sheet_count: qaSummary.sheet_count,
    qa_sample_count: qaSummary.sample_count,
  };
}

/**
 * 生成并发布完整的 80 案例/448 PNG 数据集。
 *
 * 所有耗时写入先发生在最终目录旁边的唯一临时目录。只有内存数据、浏览器布局、PNG
 * 文件和 SHA-256 清单全部通过验收后，才调用 `commitStagedDataset` 发布。失败时只清理
 * 本次创建且名称已解析的临时目录。
 *
 * @param {{outputRoot?: string, sourceRoot?: string}} [options] 可覆盖默认绝对路径。
 * @returns {Promise<object>} 发布后的全量验证摘要。
 */
async function generateDataset(options = {}) {
  const outputRoot = options.outputRoot || DEFAULT_OUTPUT_ROOT;
  const sourceRoot = options.sourceRoot || DEFAULT_SOURCE_ROOT;
  assertFreshDestinations(outputRoot, sourceRoot);

  fs.mkdirSync(outputRoot, { recursive: true });
  fs.mkdirSync(path.dirname(sourceRoot), { recursive: true });
  const stagedOutputRoot = fs.mkdtempSync(path.join(outputRoot, ".positive-stage-build-"));
  const stagedSourceRoot = fs.mkdtempSync(
    path.join(path.dirname(sourceRoot), ".relationship-stage-positive-v1-build-"),
  );

  try {
    const cases = buildDataset(STAGE_SCENARIOS);
    validateDataset(cases);
    writeSourceArtifacts(cases, stagedSourceRoot);
    const tasks = buildRenderTasks(cases, stagedOutputRoot);
    await renderScreenshots(tasks);
    const rendered = validateRenderedOutput(cases, stagedOutputRoot);
    const qaRoot = path.join(stagedSourceRoot, "qa");
    const qaPlans = buildContactSheetPlans(cases, stagedOutputRoot, qaRoot);
    await writeContactSheets(qaPlans, qaRoot);
    validateContactSheets(qaPlans);
    writeRenderManifest(rendered, stagedSourceRoot);
    // 所有深校验必须在发布前针对 staging 数据执行。rename 不改变文件内容，因此这一步
    // 通过后，最终提交只承担同一文件系统内的目录移动，不会先发布再发现坏 Case/清单。
    validateSourceArtifacts(cases, stagedSourceRoot);
    validateRenderManifest(rendered, stagedSourceRoot);
    commitStagedDataset({
      stagedOutputRoot,
      outputRoot,
      stagedSourceRoot,
      sourceRoot,
      stageDirectories: STAGE_DIRECTORIES,
    });
    return validateExistingDataset({ outputRoot, sourceRoot });
  } catch (error) {
    for (const temporaryPath of [stagedOutputRoot, stagedSourceRoot]) {
      if (fs.existsSync(temporaryPath)) {
        fs.rmSync(temporaryPath, { recursive: true, force: true });
      }
    }
    throw error;
  }
}

/**
 * 命令行只接受无参数生成或 `--validate-only`，避免隐藏的覆盖/筛选选项改变冻结数据集。
 */
async function main() {
  const args = process.argv.slice(2);
  if (args.some((argument) => argument !== "--validate-only") || args.length > 1) {
    throw new Error("Usage: node generate.cjs [--validate-only]");
  }
  const summary = args[0] === "--validate-only"
    ? validateExistingDataset()
    : await generateDataset();
  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  DEFAULT_OUTPUT_ROOT,
  DEFAULT_SOURCE_ROOT,
  assertFreshDestinations,
  commitStagedDataset,
  generateDataset,
  validateExistingDataset,
};
