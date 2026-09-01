/**
 * 正向关系阶段数据集的文件模型与渲染任务构建。
 *
 * 本模块把已经验证的内存案例转换为截图任务和可追溯文件。它不生成聊天正文，也不
 * 判断关系阶段，避免持久化逻辑与语义规则互相污染。
 */
const fs = require("node:fs");
const crypto = require("node:crypto");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");
const { stageDirectoryName } = require("./dataset.cjs");

/**
 * 为全部案例构建按阅读顺序排列的截图任务。
 *
 * payload 刻意不携带 `target_stage`、黄金证据或排除项，保证答案不会出现在浏览器页面
 * 或像素中。输出路径严格遵循 `英文标签中文释义/example_XX/chat_XX.png`。
 *
 * @param {Array<object>} cases 已通过 `validateDataset` 的完整案例。
 * @param {string} outputRoot PNG 输出根目录。
 * @returns {Array<{output_path: string, payload: object}>} 供 Playwright 顺序渲染的任务。
 */
function buildRenderTasks(cases, outputRoot) {
  return cases.flatMap((item) =>
    item.pages.map((page) => ({
      output_path: path.join(
        outputRoot,
        stageDirectoryName(item.target_stage),
        item.example_id,
        `chat_${String(page.page_number).padStart(2, "0")}.png`,
      ),
      payload: {
        style_id: item.style_id,
        locale: item.locale,
        contact_name: item.participants.other.display_name,
        page_number: page.page_number,
        page_count: item.pages.length,
        messages: page.messages,
      },
    })),
  );
}

/**
 * 以稳定缩进和结尾换行写入 JSON，便于版本控制和人工审阅。
 *
 * @param {string} filePath 目标文件路径。
 * @param {object} value 可 JSON 序列化的数据。
 */
function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

/**
 * 把案例中的场景说明裁剪为可复用的稳定元数据。聊天像素不会接收这些字段；它们只供
 * Transcript 与黄金标注人工追溯。
 *
 * @param {object} item 内存案例。
 * @returns {object} 稳定场景元数据。
 */
function buildScenarioMetadata(item) {
  return {
    slug: item.scenario.slug,
    title: item.scenario.title,
    premise: item.scenario.premise,
    topic: item.scenario.topic,
  };
}

/** @param {object} item 内存案例。 @returns {object} Transcript JSON 对象。 */
function buildConversationArtifact(item) {
  return {
    schema_version: item.schema_version,
    case_id: item.case_id,
    task_kind: item.task_kind,
    target_stage: item.target_stage,
    positive_track: item.positive_track,
    locale: item.locale,
    participants: item.participants,
    style_id: item.style_id,
    image_count: item.image_count,
    pair_type: item.pair_type,
    scenario: buildScenarioMetadata(item),
    messages: item.messages,
    stage_evidence_message_ids: item.stage_evidence_message_ids,
    excluded_stage_cues: item.excluded_stage_cues,
    render: item.render,
  };
}

/**
 * 构造正式 Runner 可直接读取的 Analysis E2E Case。
 *
 * `analysis` 是仓库 `aidating.e2e.case.v1` 的必填分支；这里只传合成联系人名，不传目标
 * 阶段或黄金证据，既满足加载契约，也避免答案进入被测请求。
 *
 * @param {object} item 内存案例。
 * @returns {object} E2E Case JSON 对象。
 */
function buildE2ECaseArtifact(item) {
  return {
    schema_version: "aidating.e2e.case.v1",
    case_id: item.case_id,
    task_kind: "analysis",
    locale: item.locale,
    media: item.pages.map((page) => ({
      path: path.posix.join(
        stageDirectoryName(item.target_stage),
        item.example_id,
        `chat_${String(page.page_number).padStart(2, "0")}.png`,
      ),
    })),
    analysis: {
      other_person_name: item.participants.other.display_name,
    },
    expect: {
      task_status: "succeeded",
      result_schema: "dating.relationship_analysis.v1",
    },
  };
}

/** @param {object} item 内存案例。 @returns {object} 独立黄金标注对象。 */
function buildGoldAnnotation(item) {
  return {
    case_id: item.case_id,
    target_stage: item.target_stage,
    positive_track: item.positive_track,
    scenario: buildScenarioMetadata(item),
    stage_evidence_message_ids: item.stage_evidence_message_ids,
    excluded_stage_cues: item.excluded_stage_cues,
  };
}

/**
 * 递归列出根目录内的文件相对路径，供严格集合比较使用。
 *
 * @param {string} root 目录根。
 * @returns {string[]} POSIX 分隔、已排序的文件路径。
 */
function listRelativeFiles(root) {
  if (!fs.existsSync(root)) return [];
  const files = [];
  const visit = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (entry.isFile()) {
        files.push(path.relative(root, target).split(path.sep).join("/"));
      }
    }
  };
  visit(root);
  return files.sort();
}

/**
 * 写出 Transcript、公开 E2E Case 与独立黄金标注。
 *
 * 目标阶段只存在于 Transcript/黄金标注，不写入 `aidating.e2e.case.v1.expect`，避免擅自
 * 扩展当前协议。媒体路径以截图 Fixture 根目录为基准并使用 POSIX 分隔符，保证 Case
 * 在不同操作系统上读取顺序一致。
 *
 * @param {Array<object>} cases 完整内存案例。
 * @param {string} sourceRoot 数据集源文件根目录，必须是新建或空目录。
 * @returns {{conversation_files: number, e2e_case_files: number, gold_annotations: number}}
 *   写入数量统计。
 * @throws {Error} 当固定输出文件已经存在时抛出，禁止静默覆盖。
 */
function writeSourceArtifacts(cases, sourceRoot) {
  const conversationsRoot = path.join(sourceRoot, "conversations");
  const e2eCasesRoot = path.join(sourceRoot, "cases");
  const goldPath = path.join(sourceRoot, "gold_annotations.jsonl");
  for (const target of [conversationsRoot, e2eCasesRoot, goldPath]) {
    if (fs.existsSync(target)) throw new Error(`Refusing to overwrite: ${target}`);
  }

  for (const item of cases) {
    const sourcePath = path.join(
      conversationsRoot,
      item.target_stage,
      `${item.example_id}.json`,
    );
    const e2ePath = path.join(
      e2eCasesRoot,
      `${item.case_id}.json`,
    );
    writeJson(sourcePath, buildConversationArtifact(item));
    writeJson(e2ePath, buildE2ECaseArtifact(item));
  }

  const goldAnnotations = cases.map(buildGoldAnnotation);
  fs.mkdirSync(sourceRoot, { recursive: true });
  fs.writeFileSync(
    goldPath,
    `${goldAnnotations.map((entry) => JSON.stringify(entry)).join("\n")}\n`,
    "utf8",
  );
  return {
    conversation_files: cases.length,
    e2e_case_files: cases.length,
    gold_annotations: goldAnnotations.length,
  };
}

/**
 * 逐文件验证 Transcript、扁平 E2E Case 与 JSONL 黄金标注的结构和完整内容。
 *
 * 与仅统计文件数不同，本函数把磁盘内容和当前确定性构建结果做深比较，因此缺字段、
 * 非法 JSON、目录嵌套错误、额外文件或单条消息被篡改都会让 `--validate-only` 失败。
 *
 * @param {Array<object>} cases 当前内存案例。
 * @param {string} sourceRoot 数据集源目录。
 * @returns {{conversation_files: number, e2e_case_files: number, gold_annotations: number}}
 * @throws {Error} 任一源数据不一致时抛出。
 */
function validateSourceArtifacts(cases, sourceRoot) {
  const conversationsRoot = path.join(sourceRoot, "conversations");
  const e2eCasesRoot = path.join(sourceRoot, "cases");
  const goldPath = path.join(sourceRoot, "gold_annotations.jsonl");
  const expectedConversationFiles = cases.map((item) =>
    path.posix.join(item.target_stage, `${item.example_id}.json`)
  ).sort();
  const expectedE2EFiles = cases.map((item) => `${item.case_id}.json`).sort();
  const errors = [];

  if (!isDeepStrictEqual(listRelativeFiles(conversationsRoot), expectedConversationFiles)) {
    errors.push("conversation file set differs");
  }
  if (!isDeepStrictEqual(listRelativeFiles(e2eCasesRoot), expectedE2EFiles)) {
    errors.push("E2E case file set differs or is not flat");
  }

  for (const item of cases) {
    const checks = [
      [
        path.join(conversationsRoot, item.target_stage, `${item.example_id}.json`),
        buildConversationArtifact(item),
      ],
      [path.join(e2eCasesRoot, `${item.case_id}.json`), buildE2ECaseArtifact(item)],
    ];
    for (const [filePath, expected] of checks) {
      try {
        const actual = JSON.parse(fs.readFileSync(filePath, "utf8"));
        if (!isDeepStrictEqual(actual, expected)) errors.push(`${filePath}: content differs`);
      } catch (error) {
        errors.push(`${filePath}: unreadable JSON (${error.message})`);
      }
    }
  }

  const expectedGold = cases.map(buildGoldAnnotation);
  try {
    const rawLines = fs.readFileSync(goldPath, "utf8").split("\n");
    if (rawLines.at(-1) === "") rawLines.pop();
    if (rawLines.some((line) => !line.trim())) throw new Error("blank JSONL line");
    const actualGold = rawLines.map((line) => JSON.parse(line));
    if (!isDeepStrictEqual(actualGold, expectedGold)) errors.push(`${goldPath}: content differs`);
  } catch (error) {
    errors.push(`${goldPath}: unreadable JSONL (${error.message})`);
  }

  if (errors.length > 0) {
    throw new Error(`Source artifact mismatch:\n- ${errors.join("\n- ")}`);
  }
  return {
    conversation_files: expectedConversationFiles.length,
    e2e_case_files: expectedE2EFiles.length,
    gold_annotations: expectedGold.length,
  };
}

/**
 * 读取 PNG 固定头和 IHDR 尺寸，不引入额外图片依赖。
 *
 * @param {Buffer} buffer PNG 文件二进制。
 * @returns {{width: number, height: number}} 图片像素尺寸。
 * @throws {TypeError} 文件签名或最小长度不合法时抛出。
 */
function readPngDimensions(buffer) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (buffer.length < 24 || !buffer.subarray(0, 8).equals(signature)) {
    throw new TypeError("File is not a valid PNG");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

/**
 * 验证截图目录结构、格式、尺寸、大小和内容哈希。
 *
 * 输出根目录允许保留用户已有的根级图片，但阶段目录必须与传入案例精确对应；每个案例
 * 目录中只允许出现计划生成的 PNG。这样既不删除历史样例，也能保证新增 16×5 树纯净。
 *
 * @param {Array<object>} cases 需要验证的案例集合。
 * @param {string} outputRoot 截图 Fixture 根目录。
 * @returns {{png_count: number, stage_count: number, case_count: number,
 *   total_bytes: number, entries: Array<object>}} 渲染清单原始数据。
 * @throws {Error} 任一文件或目录约束失败时一次列出全部问题。
 */
function validateRenderedOutput(cases, outputRoot) {
  const errors = [];
  const tasks = buildRenderTasks(cases, outputRoot);
  const expectedStages = [...new Set(cases.map(({ target_stage }) => target_stage))];
  const expectedStageDirectories = expectedStages.map(stageDirectoryName);
  const actualStageDirectories = fs.existsSync(outputRoot)
    ? fs.readdirSync(outputRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort()
    : [];
  if (actualStageDirectories.join("|") !== [...expectedStageDirectories].sort().join("|")) {
    errors.push("stage directories do not match the expected set");
  }

  for (const stage of expectedStages) {
    const expectedExamples = cases
      .filter(({ target_stage }) => target_stage === stage)
      .map(({ example_id }) => example_id)
      .sort();
    const stagePath = path.join(outputRoot, stageDirectoryName(stage));
    const actualExamples = fs.existsSync(stagePath)
      ? fs.readdirSync(stagePath, { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name)
        .sort()
      : [];
    if (actualExamples.join("|") !== expectedExamples.join("|")) {
      errors.push(`${stage}: example directories do not match`);
    }
  }

  const taskByPath = new Map(tasks.map((task) => [task.output_path, task]));
  const caseByKey = new Map(cases.map((item) => [
    `${stageDirectoryName(item.target_stage)}/${item.example_id}`,
    item,
  ]));
  const entries = [];
  const hashes = new Set();

  for (const item of cases) {
    const examplePath = path.join(
      outputRoot,
      stageDirectoryName(item.target_stage),
      item.example_id,
    );
    const expectedNames = item.pages.map((page) =>
      `chat_${String(page.page_number).padStart(2, "0")}.png`
    ).sort();
    const actualNames = fs.existsSync(examplePath)
      ? fs.readdirSync(examplePath, { withFileTypes: true }).map((entry) =>
        entry.isFile() ? entry.name : `${entry.name}/`
      ).sort()
      : [];
    if (actualNames.join("|") !== expectedNames.join("|")) {
      errors.push(`${item.case_id}: example directory must contain only expected PNG files`);
    }
  }

  for (const task of tasks) {
    if (!fs.existsSync(task.output_path)) {
      errors.push(`missing PNG: ${task.output_path}`);
      continue;
    }
    const buffer = fs.readFileSync(task.output_path);
    let dimensions;
    try {
      dimensions = readPngDimensions(buffer);
    } catch (error) {
      errors.push(`${task.output_path}: ${error.message}`);
      continue;
    }
    if (dimensions.width !== 430 || dimensions.height !== 932) {
      errors.push(`${task.output_path}: expected 430x932`);
    }
    if (buffer.length <= 20_000 || buffer.length >= 10_000_000) {
      errors.push(`${task.output_path}: PNG byte size outside accepted range`);
    }
    const sha256 = crypto.createHash("sha256").update(buffer).digest("hex");
    if (hashes.has(sha256)) errors.push(`${task.output_path}: duplicate PNG content`);
    hashes.add(sha256);
    const relativePath = path.relative(outputRoot, task.output_path).split(path.sep).join("/");
    const [stage, exampleId] = relativePath.split("/");
    const item = caseByKey.get(`${stage}/${exampleId}`);
    entries.push({
      relative_path: relativePath,
      case_id: item.case_id,
      target_stage: item.target_stage,
      example_id: item.example_id,
      locale: item.locale,
      style_id: item.style_id,
      page_number: task.payload.page_number,
      message_count: task.payload.messages.length,
      case_image_count: item.image_count,
      case_unique_message_count: item.messages.length,
      width: dimensions.width,
      height: dimensions.height,
      bytes: buffer.length,
      sha256,
    });
    taskByPath.delete(task.output_path);
  }
  if (taskByPath.size > 0) errors.push("not all render tasks were validated");

  if (errors.length > 0) {
    throw new Error(`Rendered output validation failed:\n- ${errors.join("\n- ")}`);
  }
  return {
    png_count: entries.length,
    stage_count: expectedStages.length,
    case_count: cases.length,
    unique_message_count: cases.reduce((total, item) => total + item.messages.length, 0),
    total_bytes: entries.reduce((total, entry) => total + entry.bytes, 0),
    entries,
  };
}

/**
 * 把验证后的 PNG 元数据与 SHA-256 写入数据集源目录。
 *
 * @param {object} validation `validateRenderedOutput` 的成功结果。
 * @param {string} sourceRoot 数据集源文件根目录。
 * @returns {string} 写入的 manifest 绝对路径。
 * @throws {Error} manifest 已存在时拒绝覆盖。
 */
function buildRenderManifest(validation) {
  return {
    schema_version: "aidating.chat-screenshot-manifest.v1",
    dataset_version: "1.0.0",
    summary: {
      stage_count: validation.stage_count,
      case_count: validation.case_count,
      png_count: validation.png_count,
      unique_message_count: validation.unique_message_count,
      total_bytes: validation.total_bytes,
    },
    images: validation.entries,
  };
}

function writeRenderManifest(validation, sourceRoot) {
  const manifestPath = path.join(sourceRoot, "render_manifest.json");
  if (fs.existsSync(manifestPath)) throw new Error(`Refusing to overwrite: ${manifestPath}`);
  writeJson(manifestPath, buildRenderManifest(validation));
  return manifestPath;
}

/**
 * 把磁盘 manifest 与当前 448 张图片的完整验证结果逐字段比较。完整数组深比较同时保证
 * 路径唯一、顺序、哈希、locale、样式、阶段和消息数量一一对应。
 *
 * @param {object} validation `validateRenderedOutput` 的结果。
 * @param {string} sourceRoot 数据集源目录。
 * @returns {{image_count: number}} 清单图片数量。
 * @throws {Error} 缺失、非法 JSON 或任一字段不一致时抛出。
 */
function validateRenderManifest(validation, sourceRoot) {
  const manifestPath = path.join(sourceRoot, "render_manifest.json");
  let actual;
  try {
    actual = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`Render manifest mismatch: unreadable JSON (${error.message})`);
  }
  if (!isDeepStrictEqual(actual, buildRenderManifest(validation))) {
    throw new Error(`Render manifest mismatch: ${manifestPath}`);
  }
  return { image_count: validation.entries.length };
}

module.exports = {
  buildRenderTasks,
  validateRenderManifest,
  validateRenderedOutput,
  validateSourceArtifacts,
  writeSourceArtifacts,
  writeRenderManifest,
};
