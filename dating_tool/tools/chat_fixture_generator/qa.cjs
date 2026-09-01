/**
 * 为人工阶段复核生成外部 QA 联系表。
 *
 * 每个阶段的联系表按五行展示五个案例，每行并排放置首张与末张截图。联系表只写入
 * 评测工程的数据集源目录，绝不进入只允许 PNG 聊天截图的交付目录。
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");

const { STAGES, stageDirectoryName } = require("./dataset.cjs");

const SHEET_WIDTH = 760;
const THUMB_WIDTH = 300;
const THUMB_HEIGHT = 650;
const HEADER_HEIGHT = 110;
const ROW_HEIGHT = 680;
const SHEET_HEIGHT = HEADER_HEIGHT + 5 * ROW_HEIGHT + 20;

/**
 * 加载 Sharp。优先使用项目依赖，Codex 桌面环境可回退到捆绑运行时，行为与截图
 * 渲染器加载 Playwright 的策略一致。
 *
 * @returns {import("sharp")} Sharp 工厂函数。
 * @throws {Error} 项目依赖与捆绑依赖均不可用时抛出可操作的安装提示。
 */
function loadSharp() {
  try {
    return require("sharp");
  } catch (projectError) {
    const configuredRoot = process.env.DATING_WORKSPACE_NODE_MODULES;
    const bundledRoot = path.join(
      os.homedir(),
      ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
    );
    for (const root of [configuredRoot, bundledRoot].filter(Boolean)) {
      const candidate = path.join(root, "sharp");
      if (fs.existsSync(candidate)) return require(candidate);
    }
    const error = new Error("Sharp is unavailable; run `npm install` in dating_tool first.");
    error.cause = projectError;
    throw error;
  }
}

/**
 * 把文本转义为 SVG 安全文本。字段全部来自合成元数据，但仍统一转义，防止后续新增
 * 场景名时破坏联系表结构。
 *
 * @param {string} value 待写入 SVG 的字符串。
 * @returns {string} 已转义字符串。
 */
function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

/**
 * 从 80 个案例构造 16 张联系表的确定性渲染计划。
 *
 * @param {Array<object>} cases 已通过 `validateDataset` 的完整案例。
 * @param {string} imageRoot 448 张正式截图所在根目录。
 * @param {string} qaRoot 联系表与索引的独立输出目录。
 * @returns {Array<object>} 按冻结阶段顺序排列的联系表计划。
 */
function buildContactSheetPlans(cases, imageRoot, qaRoot) {
  if (!Array.isArray(cases)) throw new TypeError("cases must be an array");
  return STAGES.map((stage) => {
    const deliveryDirectory = stageDirectoryName(stage);
    const stageCases = cases
      .filter(({ target_stage: targetStage }) => targetStage === stage)
      .sort((left, right) => left.example_id.localeCompare(right.example_id));
    if (stageCases.length !== 5) {
      throw new Error(`Expected 5 QA samples for ${stage}, received ${stageCases.length}`);
    }
    return {
      stage,
      output_path: path.join(qaRoot, "contact-sheets", `${stage}.png`),
      samples: stageCases.map((fixtureCase) => {
        const firstRelativePath = path.posix.join(
          deliveryDirectory,
          fixtureCase.example_id,
          "chat_01.png",
        );
        const lastRelativePath = path.posix.join(
          deliveryDirectory,
          fixtureCase.example_id,
          `chat_${String(fixtureCase.image_count).padStart(2, "0")}.png`,
        );
        return {
          case_id: fixtureCase.case_id,
          example_id: fixtureCase.example_id,
          positive_track: fixtureCase.positive_track,
          locale: fixtureCase.locale,
          style_id: fixtureCase.style_id,
          image_count: fixtureCase.image_count,
          first_relative_path: firstRelativePath,
          last_relative_path: lastRelativePath,
          first_image_path: path.join(imageRoot, ...firstRelativePath.split("/")),
          last_image_path: path.join(imageRoot, ...lastRelativePath.split("/")),
        };
      }),
    };
  });
}

/**
 * 构造联系表索引的唯一规范形态，写入与验收共用，避免校验器只看阶段名却漏掉首尾图
 * 映射的回归。
 *
 * @param {Array<object>} plans 联系表计划。
 * @returns {object} 可序列化索引。
 */
function buildContactSheetIndex(plans) {
  return {
    schema_version: "dating.qa.contact-sheet.v1",
    purpose: "Manual first-and-last screenshot review; not part of the E2E media input.",
    stages: plans.map((plan) => ({
      stage: plan.stage,
      sheet: path.posix.join("contact-sheets", `${plan.stage}.png`),
      samples: plan.samples.map((sample) => ({
        case_id: sample.case_id,
        example_id: sample.example_id,
        first_image: sample.first_relative_path,
        last_image: sample.last_relative_path,
      })),
    })),
  };
}

/**
 * 生成一张联系表的文字、边框和列标题 SVG 图层。
 *
 * @param {object} plan 单阶段联系表计划。
 * @returns {Buffer} 可直接交给 Sharp composite 的 SVG 缓冲区。
 */
function buildOverlay(plan) {
  const rows = plan.samples.map((sample, index) => {
    const rowTop = HEADER_HEIGHT + index * ROW_HEIGHT;
    const label = `${sample.example_id}  |  ${sample.positive_track}  |  ${sample.locale}  |  ${sample.image_count} pages`;
    return `
      <text x="70" y="${rowTop + 18}" class="row-label">${escapeXml(label)}</text>
      <rect x="69" y="${rowTop + 28}" width="302" height="652" rx="18" class="frame"/>
      <rect x="389" y="${rowTop + 28}" width="302" height="652" rx="18" class="frame"/>`;
  }).join("");
  return Buffer.from(`
    <svg width="${SHEET_WIDTH}" height="${SHEET_HEIGHT}" xmlns="http://www.w3.org/2000/svg">
      <style>
        .title { font: 700 26px -apple-system, BlinkMacSystemFont, sans-serif; fill: #111827; }
        .column { font: 600 15px -apple-system, BlinkMacSystemFont, sans-serif; fill: #4b5563; }
        .row-label { font: 600 13px -apple-system, BlinkMacSystemFont, sans-serif; fill: #374151; }
        .frame { fill: #ffffff; stroke: #cbd5e1; stroke-width: 2; }
      </style>
      <text x="32" y="38" class="title">${escapeXml(plan.stage)} — first / last QA</text>
      <text x="220" y="82" text-anchor="middle" class="column">First screenshot</text>
      <text x="540" y="82" text-anchor="middle" class="column">Last screenshot</text>
      ${rows}
    </svg>
  `);
}

/**
 * 写出联系表 PNG 与机器可读索引。
 *
 * @param {Array<object>} plans `buildContactSheetPlans` 的一个或多个结果。
 * @param {string} qaRoot QA 输出根目录。
 * @returns {Promise<{sheet_count: number, sample_count: number}>} 写出数量摘要。
 */
async function writeContactSheets(plans, qaRoot) {
  if (!Array.isArray(plans) || plans.length === 0) {
    throw new TypeError("At least one contact-sheet plan is required");
  }
  const sharp = loadSharp();
  fs.mkdirSync(path.join(qaRoot, "contact-sheets"), { recursive: true });

  for (const plan of plans) {
    const composites = [{ input: buildOverlay(plan), left: 0, top: 0 }];
    for (const [index, sample] of plan.samples.entries()) {
      const rowTop = HEADER_HEIGHT + index * ROW_HEIGHT + 29;
      for (const [column, sourcePath] of [
        [0, sample.first_image_path],
        [1, sample.last_image_path],
      ]) {
        if (!fs.existsSync(sourcePath)) throw new Error(`Missing QA source image: ${sourcePath}`);
        const thumbnail = await sharp(sourcePath)
          .resize(THUMB_WIDTH, THUMB_HEIGHT, { fit: "fill" })
          .png()
          .toBuffer();
        composites.push({ input: thumbnail, left: column === 0 ? 70 : 390, top: rowTop });
      }
    }
    fs.mkdirSync(path.dirname(plan.output_path), { recursive: true });
    await sharp({
      create: {
        width: SHEET_WIDTH,
        height: SHEET_HEIGHT,
        channels: 4,
        background: "#f3f4f6",
      },
    }).composite(composites).png().toFile(plan.output_path);
  }

  const index = buildContactSheetIndex(plans);
  fs.writeFileSync(
    path.join(qaRoot, "contact-sheet-index.json"),
    `${JSON.stringify(index, null, 2)}\n`,
  );
  return {
    sheet_count: plans.length,
    sample_count: plans.reduce((sum, plan) => sum + plan.samples.length, 0),
  };
}

/**
 * 校验联系表的数量、PNG 签名、尺寸和内容唯一性。
 *
 * @param {Array<object>} plans 联系表计划。
 * @returns {{sheet_count: number, sample_count: number}} 验收摘要。
 */
function validateContactSheets(plans) {
  const hashes = new Set();
  for (const plan of plans) {
    if (!fs.existsSync(plan.output_path)) throw new Error(`Missing QA sheet: ${plan.output_path}`);
    const png = fs.readFileSync(plan.output_path);
    if (!png.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
      throw new Error(`QA sheet is not a real PNG: ${plan.output_path}`);
    }
    if (png.readUInt32BE(16) !== SHEET_WIDTH || png.readUInt32BE(20) !== SHEET_HEIGHT) {
      throw new Error(`Unexpected QA sheet dimensions: ${plan.output_path}`);
    }
    const hash = crypto.createHash("sha256").update(png).digest("hex");
    if (hashes.has(hash)) throw new Error(`Duplicate QA sheet content: ${plan.output_path}`);
    hashes.add(hash);
  }
  const qaRoot = path.dirname(path.dirname(plans[0].output_path));
  const indexPath = path.join(qaRoot, "contact-sheet-index.json");
  if (!fs.existsSync(indexPath)) throw new Error(`Missing QA contact-sheet index: ${indexPath}`);
  const index = JSON.parse(fs.readFileSync(indexPath, "utf8"));
  if (!isDeepStrictEqual(index, buildContactSheetIndex(plans))) {
    throw new Error(`Invalid QA contact-sheet index: ${indexPath}`);
  }
  return {
    sheet_count: plans.length,
    sample_count: plans.reduce((sum, plan) => sum + plan.samples.length, 0),
  };
}

module.exports = {
  SHEET_HEIGHT,
  SHEET_WIDTH,
  buildContactSheetPlans,
  validateContactSheets,
  writeContactSheets,
};
