/**
 * 正向关系阶段截图数据集的行为测试。
 *
 * 测试只断言用户已经冻结的公开数据契约，不复制生成器内部算法。首个测试故意在
 * 生产模块尚不存在时以清晰的断言失败，作为 TDD 的 RED 证据。
 */
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const modulePath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/dataset.cjs",
);
const dataset = fs.existsSync(modulePath) ? require(modulePath) : null;
const catalogPath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/scenario_catalog.cjs",
);
const catalog = fs.existsSync(catalogPath) ? require(catalogPath) : null;
const dialogueBeatsPath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/dialogue_beats.cjs",
);
const dialogueBeats = fs.existsSync(dialogueBeatsPath) ? require(dialogueBeatsPath) : null;
const rendererModulePath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/render.cjs",
);
const renderer = fs.existsSync(rendererModulePath) ? require(rendererModulePath) : null;
const artifactsModulePath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/artifacts.cjs",
);
const artifacts = fs.existsSync(artifactsModulePath) ? require(artifactsModulePath) : null;
const generatorModulePath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/generate.cjs",
);
const generator = fs.existsSync(generatorModulePath) ? require(generatorModulePath) : null;
const qaModulePath = path.resolve(
  __dirname,
  "../tools/chat_fixture_generator/qa.cjs",
);
const qa = fs.existsSync(qaModulePath) ? require(qaModulePath) : null;

/** 用户可见的 16 个交付目录字面量；内部阶段枚举仍保持英文大写常量。 */
const EXPECTED_DELIVERY_DIRECTORIES = Object.freeze([
  "Unclear阶段待确定",
  "New connection初识接触",
  "Friends朋友关系",
  "Talking持续互动",
  "Flirting暧昧探索",
  "Situationship未定义关系",
  "Planning a date邀约阶段",
  "Dating约会验证",
  "Defining relationship关系确认",
  "Exclusive排他关系",
  "Relationship稳定关系",
  "Long-distance异地关系",
  "On a break关系暂停",
  "Breakup discussion分手讨论",
  "Reconnecting重新联系",
  "Ended关系结束",
]);

test("定义附图中的 16 个关系阶段且保持冻结顺序", () => {
  assert.ok(dataset, "dataset.cjs 尚未实现");
  assert.deepEqual(dataset.STAGES, [
    "UNCLEAR",
    "NEW_CONNECTION",
    "FRIENDS",
    "TALKING",
    "FLIRTING",
    "SITUATIONSHIP",
    "DATE_PLANNING",
    "DATING",
    "DEFINING_RELATIONSHIP",
    "EXCLUSIVE",
    "RELATIONSHIP",
    "LONG_DISTANCE",
    "ON_A_BREAK",
    "BREAKUP_DISCUSSION",
    "RECONNECTING",
    "ENDED",
  ]);
});

test("交付截图使用英文标签加中文释义的 16 个阶段目录", () => {
  assert.equal(typeof dataset.stageDirectoryName, "function");
  const outputRoot = path.join(path.sep, "fixture-root");
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  const tasks = artifacts.buildRenderTasks(cases, outputRoot);
  const actualDirectories = [...new Set(tasks.map(({ output_path }) =>
    path.relative(outputRoot, output_path).split(path.sep)[0]
  ))];

  assert.deepEqual(actualDirectories, EXPECTED_DELIVERY_DIRECTORIES);
  assert.throws(() => dataset.stageDirectoryName("NOT_A_STAGE"), /unknown/i);
});

test("为每个阶段定义 3 个阶段准确案例和 2 个建设性案例", () => {
  assert.ok(catalog, "scenario_catalog.cjs 尚未实现");
  assert.deepEqual(Object.keys(catalog.STAGE_SCENARIOS), dataset.STAGES);

  for (const stage of dataset.STAGES) {
    const scenarios = catalog.STAGE_SCENARIOS[stage];
    assert.equal(scenarios.length, 5, `${stage} 应有 5 个案例`);
    assert.deepEqual(
      scenarios.map((scenario) => scenario.track),
      [
        "stage_accurate",
        "stage_accurate",
        "stage_accurate",
        "constructive",
        "constructive",
      ],
      `${stage} 的正向版本分配不正确`,
    );
    for (const scenario of scenarios) {
      assert.match(scenario.slug, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
      assert.equal(scenario.anchors.length, 5);
      assert.ok(scenario.anchors.every(({ speaker, text }) =>
        ["self", "other"].includes(speaker) && /^[\x20-\x7E]+$/.test(text)
      ));
    }
  }
});

test("场景文案使用自然英语且不依赖测试守卫式短语", () => {
  const visibleScenarioText = Object.values(catalog.STAGE_SCENARIOS)
    .flat()
    .flatMap((scenario) => [...scenario.anchors, ...scenario.closing])
    .map(({ text }) => text)
    .join("\n");
  assert.doesNotMatch(
    visibleScenarioText,
    /has not happened|still-upcoming|cautious coffee|final breakup logistics|completely ended|relationship is ended|more breakup discussions|this is a breakup discussion/i,
  );
});

test("人工场景中的直接问题得到明确回答且旧话题有局部指代", () => {
  assert.equal(
    catalog.STAGE_SCENARIOS.NEW_CONNECTION[2].anchors[4].text,
    "Yes, I am planning to sign up, and I would be glad to say hello again.",
  );
  assert.equal(
    catalog.STAGE_SCENARIOS.TALKING[1].anchors[4].text,
    "Steadiness guides me most, and talking about values helps me understand you beyond casual conversation.",
  );
  assert.equal(
    catalog.STAGE_SCENARIOS.FLIRTING[3].anchors[4].text,
    "I like \"bright eyes,\" but please ask each time at first.",
  );
  assert.equal(
    catalog.STAGE_SCENARIOS.FLIRTING[3].closing[0].text,
    "Then I will ask before calling you bright eyes.",
  );
  assert.equal(
    catalog.STAGE_SCENARIOS.UNCLEAR[1].closing[0].text,
    "I feel the same, and I will still put together that short film list.",
  );
  assert.equal(
    catalog.STAGE_SCENARIOS.SITUATIONSHIP[3].closing[0].text,
    "I hear you, and I will take time to think without forcing an answer tonight.",
  );
});

test("六类共享对话片段均提供至少 56 组自然双人往返", () => {
  assert.ok(dialogueBeats, "dialogue_beats.cjs 尚未实现");
  assert.equal(typeof dialogueBeats.beatBankForStage, "function");
  assert.deepEqual(Object.keys(dialogueBeats.BEAT_BANKS).sort(), [
    "breakup",
    "ended",
    "general",
    "long_distance",
    "pause",
    "relationship",
  ]);
  for (const [bankName, beats] of Object.entries(dialogueBeats.BEAT_BANKS)) {
    assert.ok(beats.length >= 56, `${bankName} 对话片段不足 56 组`);
    assert.equal(
      new Set(beats.map(({ other, self }) => `${other}\n${self}`)).size,
      beats.length,
      `${bankName} 包含重复片段`,
    );
    assert.ok(beats.every(({ other, self }) => [other, self].every((text) =>
      typeof text === "string"
      && text.length >= 2
      && text.length <= 110
      && /^[\x20-\x7E]+$/.test(text)
    )));
  }
  for (const stage of dataset.STAGES) {
    assert.ok(dialogueBeats.beatBankForStage(stage).length >= 56);
  }
  assert.throws(() => dialogueBeats.beatBankForStage("NOT_A_STAGE"), /unknown/i);
});

test("分手讨论共享对话不得实质进入关系暂停", () => {
  const breakupText = dialogueBeats.beatBankForStage("BREAKUP_DISCUSSION")
    .flatMap(({ other, self }) => [other, self])
    .join("\n");
  assert.doesNotMatch(
    breakupText,
    /few days apart|three days|no casual contact|protected reflection time|step back until/i,
  );
  assert.match(breakupText, /normal contact|not taking a relationship break/i);
});

test("构建 80 个案例并在每个阶段轮转 3/4/5/7/9 张图片", () => {
  assert.equal(typeof dataset.buildCaseDefinitions, "function");
  const cases = dataset.buildCaseDefinitions();

  assert.equal(cases.length, 80);
  assert.equal(new Set(cases.map(({ case_id }) => case_id)).size, 80);

  for (const stage of dataset.STAGES) {
    const stageCases = cases.filter((item) => item.target_stage === stage);
    assert.equal(stageCases.length, 5);
    assert.deepEqual(
      stageCases.map(({ image_count }) => image_count).sort((a, b) => a - b),
      [3, 4, 5, 7, 9],
    );
    assert.equal(
      stageCases.reduce((total, item) => total + item.image_count, 0),
      28,
    );
  }
});

test("轮转五种英语语境和界面并均衡四类人物组合", () => {
  const cases = dataset.buildCaseDefinitions();
  const expectedLocales = ["en-US", "en-GB", "en-CA", "en-IE", "en-NL"];
  const expectedStyles = [
    "azure-light",
    "sage-light",
    "midnight-dark",
    "plum-light",
    "mono-high-contrast",
  ];
  const expectedPairCounts = {
    "woman-man": 20,
    "woman-woman": 20,
    "man-man": 20,
    "nonbinary-inclusive": 20,
  };

  for (const stage of dataset.STAGES) {
    const stageCases = cases.filter((item) => item.target_stage === stage);
    assert.deepEqual(
      stageCases.map(({ locale }) => locale).sort(),
      [...expectedLocales].sort(),
    );
    assert.deepEqual(
      stageCases.map(({ style_id }) => style_id).sort(),
      [...expectedStyles].sort(),
    );
  }

  const actualPairCounts = Object.fromEntries(
    Object.keys(expectedPairCounts).map((pairType) => [
      pairType,
      cases.filter(({ pair_type }) => pair_type === pairType).length,
    ]),
  );
  assert.deepEqual(actualPairCounts, expectedPairCounts);
});

test("按每页 14 条和相邻 2 条重叠生成连续对话分页", () => {
  assert.equal(typeof dataset.buildConversation, "function");
  const scenario = {
    slug: "test-scenario",
    title: "Test scenario",
    premise: "Two synthetic people have a clear and respectful conversation.",
    topic: "the plan they discussed",
    track: "stage_accurate",
    anchors: [
      { speaker: "other", text: "This is anchor one." },
      { speaker: "self", text: "This is anchor two." },
      { speaker: "other", text: "This is anchor three." },
      { speaker: "self", text: "This is anchor four." },
      { speaker: "other", text: "This is anchor five." },
    ],
    closing: [
      { speaker: "self", text: "This is the first closing message." },
      { speaker: "other", text: "This is the final closing message." },
    ],
  };
  const definition = {
    case_id: "analysis-stage-test-positive-01",
    target_stage: "TALKING",
    image_count: 3,
    locale: "en-US",
    style_id: "azure-light",
    pair_type: "woman-man",
  };

  const conversation = dataset.buildConversation(definition, scenario);
  assert.equal(conversation.messages.length, 38);
  assert.equal(conversation.pages.length, 3);
  assert.ok(conversation.pages.every((page) => page.messages.length === 14));
  assert.deepEqual(
    conversation.pages[0].messages.slice(-2).map(({ id }) => id),
    conversation.pages[1].messages.slice(0, 2).map(({ id }) => id),
  );
  assert.deepEqual(
    conversation.pages[1].messages.slice(-2).map(({ id }) => id),
    conversation.pages[2].messages.slice(0, 2).map(({ id }) => id),
  );
  assert.deepEqual(
    conversation.messages.slice(-2).map(({ text }) => text),
    scenario.closing.map(({ text }) => text),
  );
  assert.deepEqual(
    conversation.messages.slice(0, 5).map(({ text }) => text),
    scenario.anchors.map(({ text }) => text),
    "五条人工阶段证据应保持原始连续对话，避免拆开问答",
  );
  assert.equal(conversation.stage_evidence_message_ids.length, 6);
  const finalEvidenceIndex = conversation.messages.findIndex(
    ({ id }) => id === conversation.stage_evidence_message_ids.at(-1),
  );
  assert.equal(finalEvidenceIndex, conversation.messages.length - 3);
  assert.ok(
    conversation.pages.slice(-2).some((page) =>
      page.messages.some(({ id }) =>
        conversation.stage_evidence_message_ids.includes(id)
      )
    ),
  );
});

test("场景证据保持连续、问题得到邻接回应且内部 topic 不进入可见聊天", () => {
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  for (const item of cases) {
    const evidenceIndexes = item.stage_evidence_message_ids.map((id) =>
      item.messages.findIndex((message) => message.id === id)
    );
    assert.deepEqual(evidenceIndexes.slice(0, 5), [0, 1, 2, 3, 4]);
    assert.equal(evidenceIndexes[5], item.messages.length - 3);
    const visibleText = item.messages.map(({ text }) => text.toLowerCase()).join("\n");
    assert.doesNotMatch(visibleText, /you mentioned the (?:song|film) you mentioned/);
    if (!["RELATIONSHIP", "LONG_DISTANCE", "ON_A_BREAK", "BREAKUP_DISCUSSION", "ENDED"]
      .includes(item.target_stage)) {
      assert.match(
        item.messages[5].text,
        /^I understand\. Can we shift topics for a moment\?/,
        `${item.case_id} 从场景锚点切入中性日常对话时缺少显式过渡`,
      );
    }
    assert.deepEqual(
      item.messages.slice(-5, -3).map(({ speaker }) => speaker),
      ["other", "self"],
      `${item.case_id} 的末段阶段证据前缺少双人回扣`,
    );
    assert.match(
      item.messages.at(-5).text,
      /return to what we said earlier/i,
      `${item.case_id} 的末段阶段证据前没有回扣旧话题`,
    );
    assert.match(
      item.messages.at(-4).text,
      /one more thought/i,
      `${item.case_id} 的末段阶段证据前没有自然承接`,
    );

    for (let index = 0; index < item.messages.length - 1; index += 1) {
      const current = item.messages[index];
      const next = item.messages[index + 1];
      assert.ok(
        !(current.text.endsWith("?") && current.speaker === next.speaker),
        `${item.case_id} ${current.id} 的直接问题被同一说话者切断`,
      );
    }

    let run = 1;
    let longestRun = 1;
    for (let index = 1; index < item.messages.length; index += 1) {
      run = item.messages[index].speaker === item.messages[index - 1].speaker
        ? run + 1
        : 1;
      longestRun = Math.max(longestRun, run);
    }
    assert.ok(longestRun <= 2, `${item.case_id} 出现超过两条连续同发送者消息`);
  }

  // 使用不可能自然出现的哨兵值证明生成器没有把内部 topic 当作可见模板参数；自然的
  // “first coffee date”等主题词仍可由人工编写的阶段证据正常表达。
  const sentinelScenario = {
    ...catalog.STAGE_SCENARIOS.TALKING[0],
    topic: "INTERNAL_TOPIC_SENTINEL_SHOULD_NOT_RENDER",
  };
  const sentinel = dataset.buildConversation(
    {
      case_id: "analysis-stage-sentinel-positive-01",
      target_stage: "TALKING",
      image_count: 3,
      locale: "en-US",
      style_id: "azure-light",
      pair_type: "woman-man",
    },
    sentinelScenario,
  );
  assert.ok(sentinel.messages.every(({ text }) => !text.includes(sentinelScenario.topic)));
});

test("按 locale 统一美式与英式英文拼写", () => {
  const scenario = {
    slug: "locale-spelling",
    title: "Locale spelling",
    premise: "Two synthetic people discuss a favourite colour and a favorite place.",
    topic: "your favourite local place",
    track: "stage_accurate",
    anchors: [
      { speaker: "other", text: "What is your favourite colour?" },
      { speaker: "self", text: "My favorite color is blue." },
      { speaker: "other", text: "We can organise a walk near the town centre." },
      { speaker: "self", text: "I can organize that while I am traveling." },
      { speaker: "other", text: "The last plan was cancelled, but this one works." },
    ],
    closing: [
      { speaker: "self", text: "My favorite route starts downtown." },
      { speaker: "other", text: "Great, I will bring my favourite scarf." },
    ],
  };
  const baseDefinition = {
    case_id: "analysis-stage-locale-positive-01",
    target_stage: "TALKING",
    image_count: 3,
    style_id: "azure-light",
    pair_type: "woman-man",
  };

  const usText = dataset.buildConversation(
    { ...baseDefinition, locale: "en-US" },
    scenario,
  ).messages.map(({ text }) => text).join(" ");
  assert.doesNotMatch(usText, /\b(favourite|colour|organise|centre|travelling|cancelled)\b/i);
  assert.match(usText, /\bfavorite\b/i);
  assert.match(usText, /\bcolor\b/i);

  const gbText = dataset.buildConversation(
    { ...baseDefinition, locale: "en-GB" },
    scenario,
  ).messages.map(({ text }) => text).join(" ");
  assert.doesNotMatch(gbText, /\b(favorite|color|organize|center|traveling|canceled)\b/i);
  assert.match(gbText, /\bfavourite\b/i);
  assert.match(gbText, /\bcolour\b/i);
  assert.equal(
    dataset.localiseEnglish(
      "My favorite flavor came from practicing, honoring feedback, and behavioral study.",
      "en-GB",
    ),
    "My favourite flavour came from practising, honouring feedback, and behavioural study.",
  );
});

test("生成可读英文消息并保证每页双方都有足够内容", () => {
  const scenario = {
    slug: "readable-chat",
    title: "Readable chat",
    premise: "A respectful conversation with enough context for analysis.",
    topic: "the book they were discussing",
    track: "stage_accurate",
    anchors: [
      { speaker: "other", text: "We have been talking regularly this week." },
      { speaker: "self", text: "I like learning how you see things." },
      { speaker: "other", text: "I enjoy these conversations too." },
      { speaker: "self", text: "There is no rush to label anything." },
      { speaker: "other", text: "Let us keep getting to know each other." },
    ],
    closing: [
      { speaker: "self", text: "I will send you the title tomorrow." },
      { speaker: "other", text: "Sounds good. Have a calm evening." },
    ],
  };
  const definition = {
    case_id: "analysis-stage-talking-positive-01",
    target_stage: "TALKING",
    image_count: 9,
    locale: "en-GB",
    style_id: "midnight-dark",
    pair_type: "woman-woman",
  };
  const conversation = dataset.buildConversation(definition, scenario);

  assert.ok(
    conversation.messages.every(({ text }) =>
      text.length >= 2
      && text.length <= 110
      && /^[\x20-\x7E]+$/.test(text)
      && !text.startsWith("Synthetic conversation detail")
    ),
  );
  for (const page of conversation.pages) {
    const selfCount = page.messages.filter(({ speaker }) => speaker === "self").length;
    const otherCount = page.messages.filter(({ speaker }) => speaker === "other").length;
    assert.ok(selfCount >= 5, `第 ${page.page_number} 页 self 消息不足`);
    assert.ok(otherCount >= 5, `第 ${page.page_number} 页 other 消息不足`);
    let longestRun = 1;
    let currentRun = 1;
    for (let index = 1; index < page.messages.length; index += 1) {
      if (page.messages[index].speaker === page.messages[index - 1].speaker) {
        currentRun += 1;
        longestRun = Math.max(longestRun, currentRun);
      } else {
        currentRun = 1;
      }
    }
    assert.ok(longestRun <= 4, `第 ${page.page_number} 页连续同一发送者过多`);
  }
});

test("汇总 80 个完整案例、448 个页面和可追溯黄金标注", () => {
  assert.equal(typeof dataset.buildDataset, "function");
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);

  assert.equal(cases.length, 80);
  assert.equal(
    cases.reduce((total, item) => total + item.pages.length, 0),
    448,
  );
  assert.equal(
    new Set(cases.map(({ participants }) => participants.other.display_name)).size,
    80,
  );
  for (const item of cases) {
    assert.equal(item.task_kind, "analysis");
    assert.equal(item.messages.length, 14 + (item.image_count - 1) * 12);
    assert.equal(item.pages.length, item.image_count);
    assert.equal(item.stage_evidence_message_ids.length, 6);
    assert.ok(item.excluded_stage_cues.length >= 1);
    assert.equal(item.positive_track, item.scenario.track);
    assert.match(item.participants.other.display_name, /^[A-Za-z]+$/);
    assert.ok(["she/her", "he/him", "they/them"].includes(item.participants.other.pronouns));
    assert.deepEqual(
      item.render.page_message_ids,
      item.pages.map((page) => page.messages.map(({ id }) => id)),
    );
  }
});

test("全量校验消息密度、发送方、英文正文和阶段证据", () => {
  assert.equal(typeof dataset.validateDataset, "function");
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  const summary = dataset.validateDataset(cases);

  assert.deepEqual(summary, {
    stage_count: 16,
    case_count: 80,
    page_count: 448,
    unique_message_count: 5536,
    contact_count: 80,
  });
});

test("校验相邻截图重叠消息的 ID、正文和时间完全一致", () => {
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  const firstCase = cases[0];
  const changedPages = firstCase.pages.map((page) => ({
    ...page,
    messages: page.messages.map((message) => ({ ...message })),
  }));
  changedPages[1].messages[0].text = "This overlap was changed after pagination.";
  const changedCases = [{ ...firstCase, pages: changedPages }, ...cases.slice(1)];
  assert.throws(
    () => dataset.validateDataset(changedCases),
    /overlap.*ID, text, and timestamp/i,
  );
});

test("校验分页必须来自主消息序列且六条阶段证据唯一、真实、可追溯", () => {
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  const firstCase = cases[0];

  const pageDrift = firstCase.pages.map((page) => ({
    ...page,
    messages: page.messages.map((message) => ({ ...message })),
  }));
  pageDrift[0].messages[3].text = "This page drifted away from the transcript.";
  assert.throws(
    () => dataset.validateDataset([{ ...firstCase, pages: pageDrift }, ...cases.slice(1)]),
    /page 1 does not match the transcript slice/i,
  );

  assert.throws(
    () => dataset.validateDataset([
      {
        ...firstCase,
        stage_evidence_message_ids: [
          ...firstCase.stage_evidence_message_ids.slice(0, 5),
          "m_missing",
        ],
      },
      ...cases.slice(1),
    ]),
    /unknown stage evidence message m_missing/i,
  );

  assert.throws(
    () => dataset.validateDataset([
      {
        ...firstCase,
        stage_evidence_message_ids: Array(6).fill(firstCase.stage_evidence_message_ids[0]),
      },
      ...cases.slice(1),
    ]),
    /stage evidence message IDs must be unique/i,
  );

  assert.throws(
    () => dataset.validateDataset([
      {
        ...firstCase,
        stage_evidence_message_ids: firstCase.messages.slice(5, 11).map(({ id }) => id),
      },
      ...cases.slice(1),
    ]),
    /stage evidence does not match authored evidence/i,
  );
});

test("五种界面均生成 430x932 的真实 PNG 且内容没有溢出", async (context) => {
  assert.ok(renderer, "render.cjs 尚未实现");
  assert.equal(typeof renderer.renderScreenshots, "function");
  const outputDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "dating-render-test-"));
  context.after(() => fs.rmSync(outputDirectory, { recursive: true, force: true }));
  const styles = [
    "azure-light",
    "sage-light",
    "midnight-dark",
    "plum-light",
    "mono-high-contrast",
  ];
  const messages = Array.from({ length: 14 }, (_, index) => ({
    id: `m_${String(index + 1).padStart(3, "0")}`,
    speaker: index % 2 === 0 ? "other" : "self",
    type: "text",
    text: index % 3 === 0
      ? "I appreciated the calm and thoughtful way you explained that today."
      : "That makes sense to me. Thank you for being clear.",
    timestamp: new Date(Date.UTC(2026, 0, 8, 18, index * 4)).toISOString(),
  }));
  const tasks = styles.map((styleId, index) => ({
    output_path: path.join(outputDirectory, `${styleId}.png`),
    payload: {
      style_id: styleId,
      locale: "en-US",
      contact_name: ["Alex", "Taylor", "Jordan", "Casey", "Morgan"][index],
      page_number: 1,
      page_count: 1,
      messages,
    },
  }));

  const result = await renderer.renderScreenshots(tasks);
  assert.deepEqual(result, { rendered: 5, width: 430, height: 932 });
  for (const task of tasks) {
    const png = fs.readFileSync(task.output_path);
    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(png.readUInt32BE(16), 430);
    assert.equal(png.readUInt32BE(20), 932);
    assert.ok(png.length > 20_000);
  }
});

test("渲染时间使用数据集固定时区而不受生成机器时区影响", async () => {
  assert.ok(renderer, "render.cjs 尚未实现");
  assert.equal(typeof renderer.inspectFixture, "function");
  const messages = Array.from({ length: 14 }, (_, index) => ({
    id: `m_${String(index + 1).padStart(3, "0")}`,
    speaker: index % 2 === 0 ? "other" : "self",
    type: "text",
    text: "A clear and respectful synthetic message.",
    timestamp: new Date(Date.UTC(2026, 0, 8, 18, index * 4)).toISOString(),
  }));
  const basePayload = {
    style_id: "azure-light",
    contact_name: "Alex",
    page_number: 1,
    page_count: 1,
    messages,
  };

  const us = await renderer.inspectFixture({ ...basePayload, locale: "en-US" });
  assert.equal(us.avatar_count, 0, "合成截图不得显示头像或头像占位符");
  assert.equal(us.clock, "06:52 PM");
  assert.match(us.date_label, /Thursday, Jan 8 .* 06:00 PM/);
  assert.equal(us.message_times[0], "06:00 PM");

  const gb = await renderer.inspectFixture({ ...basePayload, locale: "en-GB" });
  assert.equal(gb.clock, "18:52");
  assert.match(gb.date_label, /Thursday 8 Jan .* 18:00/);
  assert.equal(gb.message_times[0], "18:00");
});

test("逐阶段生成包含五个案例首尾图的外部 QA 联系表", async (context) => {
  assert.ok(qa, "qa.cjs 尚未实现");
  assert.equal(typeof qa.buildContactSheetPlans, "function");
  assert.equal(typeof qa.writeContactSheets, "function");
  assert.equal(typeof qa.validateContactSheets, "function");
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dating-qa-test-"));
  context.after(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));
  const imageRoot = path.join(temporaryRoot, "delivery-images");
  const qaRoot = path.join(temporaryRoot, "dataset-source", "qa");
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  const plans = qa.buildContactSheetPlans(cases, imageRoot, qaRoot);

  assert.equal(plans.length, 16);
  assert.ok(plans.every(({ samples }) => samples.length === 5));
  assert.ok(plans.every(({ output_path }) => !output_path.startsWith(imageRoot)));
  assert.deepEqual(
    plans[0].samples.map(({ first_relative_path, last_relative_path }) => [
      first_relative_path,
      last_relative_path,
    ]),
    [
      ["Unclear阶段待确定/example_01/chat_01.png", "Unclear阶段待确定/example_01/chat_03.png"],
      ["Unclear阶段待确定/example_02/chat_01.png", "Unclear阶段待确定/example_02/chat_04.png"],
      ["Unclear阶段待确定/example_03/chat_01.png", "Unclear阶段待确定/example_03/chat_05.png"],
      ["Unclear阶段待确定/example_04/chat_01.png", "Unclear阶段待确定/example_04/chat_07.png"],
      ["Unclear阶段待确定/example_05/chat_01.png", "Unclear阶段待确定/example_05/chat_09.png"],
    ],
  );

  // 极小 PNG 只用于隔离测试联系表布局；正式运行会读取真实的 430×932 截图。
  const onePixelPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  );
  for (const sample of plans[0].samples) {
    for (const sourcePath of [sample.first_image_path, sample.last_image_path]) {
      fs.mkdirSync(path.dirname(sourcePath), { recursive: true });
      fs.writeFileSync(sourcePath, onePixelPng);
    }
  }
  const writeSummary = await qa.writeContactSheets([plans[0]], qaRoot);
  assert.deepEqual(writeSummary, { sheet_count: 1, sample_count: 5 });
  assert.deepEqual(qa.validateContactSheets([plans[0]]), {
    sheet_count: 1,
    sample_count: 5,
  });
  const sheet = fs.readFileSync(plans[0].output_path);
  assert.deepEqual([...sheet.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.equal(sheet.readUInt32BE(16), qa.SHEET_WIDTH);
  assert.equal(sheet.readUInt32BE(20), qa.SHEET_HEIGHT);
  const index = JSON.parse(fs.readFileSync(path.join(qaRoot, "contact-sheet-index.json")));
  assert.equal(index.schema_version, "dating.qa.contact-sheet.v1");
  assert.equal(index.stages.length, 1);
  index.stages[0].samples = [];
  fs.writeFileSync(
    path.join(qaRoot, "contact-sheet-index.json"),
    `${JSON.stringify(index, null, 2)}\n`,
  );
  assert.throws(() => qa.validateContactSheets([plans[0]]), /contact-sheet index/i);
});

test("为 80 个案例构建 448 个不泄露阶段答案的有序渲染任务", () => {
  assert.ok(artifacts, "artifacts.cjs 尚未实现");
  assert.equal(typeof artifacts.buildRenderTasks, "function");
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);
  const outputRoot = "/fixture-root";
  const tasks = artifacts.buildRenderTasks(cases, outputRoot);

  assert.equal(tasks.length, 448);
  assert.equal(new Set(tasks.map(({ output_path }) => output_path)).size, 448);
  assert.equal(
    tasks[0].output_path,
    path.join(outputRoot, "Unclear阶段待确定/example_01/chat_01.png"),
  );
  assert.ok(tasks.every(({ payload }) =>
    payload.messages.length === 14
    && payload.contact_name
    && payload.locale
    && payload.style_id
    && !("target_stage" in payload)
  ));
});

test("写出 80 份 Transcript、80 份 E2E Case 和 80 条黄金标注", (context) => {
  assert.equal(typeof artifacts.writeSourceArtifacts, "function");
  assert.equal(typeof artifacts.validateSourceArtifacts, "function");
  const sourceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dating-source-test-"));
  const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dating-fixture-test-"));
  context.after(() => fs.rmSync(sourceRoot, { recursive: true, force: true }));
  context.after(() => fs.rmSync(fixtureRoot, { recursive: true, force: true }));
  const cases = dataset.buildDataset(catalog.STAGE_SCENARIOS);

  const result = artifacts.writeSourceArtifacts(cases, sourceRoot);
  assert.deepEqual(result, {
    conversation_files: 80,
    e2e_case_files: 80,
    gold_annotations: 80,
  });

  const conversation = JSON.parse(fs.readFileSync(
    path.join(sourceRoot, "conversations/UNCLEAR/example_01.json"),
    "utf8",
  ));
  assert.equal(conversation.schema_version, "aidating.chat-screenshot-source.v1");
  assert.equal(conversation.messages.length, 38);
  assert.equal(conversation.target_stage, "UNCLEAR");
  assert.equal(conversation.render.page_message_ids.length, 3);

  const e2eCase = JSON.parse(fs.readFileSync(
    path.join(sourceRoot, "cases/analysis-stage-unclear-positive-01.json"),
    "utf8",
  ));
  assert.deepEqual(e2eCase, {
    schema_version: "aidating.e2e.case.v1",
    case_id: "analysis-stage-unclear-positive-01",
    task_kind: "analysis",
    locale: "en-US",
    media: [
      { path: "Unclear阶段待确定/example_01/chat_01.png" },
      { path: "Unclear阶段待确定/example_01/chat_02.png" },
      { path: "Unclear阶段待确定/example_01/chat_03.png" },
    ],
    analysis: {
      other_person_name: "Liam",
    },
    expect: {
      task_status: "succeeded",
      result_schema: "dating.relationship_analysis.v1",
    },
  });
  const goldLines = fs.readFileSync(
    path.join(sourceRoot, "gold_annotations.jsonl"),
    "utf8",
  ).trim().split("\n");
  assert.equal(goldLines.length, 80);
  assert.equal(JSON.parse(goldLines[0]).target_stage, "UNCLEAR");

  assert.deepEqual(artifacts.validateSourceArtifacts(cases, sourceRoot), {
    conversation_files: 80,
    e2e_case_files: 80,
    gold_annotations: 80,
  });

  // 正式 Python 加载器只接收一级 JSON 目录；空媒体文件足以验证路径、schema 和 80 例批量加载。
  for (const task of artifacts.buildRenderTasks(cases, fixtureRoot)) {
    fs.mkdirSync(path.dirname(task.output_path), { recursive: true });
    fs.writeFileSync(task.output_path, "fixture", "utf8");
  }
  const python = spawnSync(
    "python3",
    [
      "-c",
      [
        "from pathlib import Path",
        "import sys",
        "from aidating_eval.cases import load_cases",
        "items = load_cases(Path(sys.argv[1]), 'e2e', Path(sys.argv[2]))",
        "print(len(items))",
        "print(sum(len(item.media_paths) for item in items))",
      ].join("; "),
      path.join(sourceRoot, "cases"),
      fixtureRoot,
    ],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        PYTHONPATH: path.resolve(__dirname, "../src"),
      },
    },
  );
  assert.equal(python.status, 0, python.stderr);
  assert.equal(python.stdout.trim(), "80\n448");

  const conversationPath = path.join(
    sourceRoot,
    "conversations/UNCLEAR/example_01.json",
  );
  const changedConversation = JSON.parse(fs.readFileSync(conversationPath, "utf8"));
  changedConversation.messages[0].text = "Tampered source text.";
  fs.writeFileSync(conversationPath, `${JSON.stringify(changedConversation, null, 2)}\n`);
  assert.throws(
    () => artifacts.validateSourceArtifacts(cases, sourceRoot),
    /source artifact mismatch/i,
  );
});

test("校验真实 PNG 并写出带 SHA-256 的渲染清单", async (context) => {
  assert.equal(typeof artifacts.validateRenderedOutput, "function");
  assert.equal(typeof artifacts.validateRenderManifest, "function");
  assert.equal(typeof artifacts.writeRenderManifest, "function");
  const outputRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dating-output-test-"));
  const sourceRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dating-manifest-test-"));
  context.after(() => {
    fs.rmSync(outputRoot, { recursive: true, force: true });
    fs.rmSync(sourceRoot, { recursive: true, force: true });
  });
  const firstCase = dataset.buildDataset(catalog.STAGE_SCENARIOS)[0];
  const tasks = artifacts.buildRenderTasks([firstCase], outputRoot);
  await renderer.renderScreenshots(tasks);

  const validation = artifacts.validateRenderedOutput([firstCase], outputRoot);
  assert.equal(validation.png_count, 3);
  assert.equal(validation.stage_count, 1);
  assert.equal(validation.case_count, 1);
  assert.equal(validation.unique_message_count, 38);
  assert.equal(validation.entries.length, 3);
  assert.equal(new Set(validation.entries.map(({ sha256 }) => sha256)).size, 3);
  assert.ok(validation.entries.every(({ width, height, bytes }) =>
    width === 430 && height === 932 && bytes > 20_000 && bytes < 10_000_000
  ));

  const manifestPath = artifacts.writeRenderManifest(validation, sourceRoot);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  assert.equal(manifest.schema_version, "aidating.chat-screenshot-manifest.v1");
  assert.equal(manifest.summary.png_count, 3);
  assert.equal(manifest.summary.unique_message_count, 38);
  assert.equal(manifest.images[0].relative_path, "Unclear阶段待确定/example_01/chat_01.png");
  assert.equal(manifest.images[0].message_count, 14);
  assert.equal(manifest.images[0].case_image_count, 3);
  assert.equal(manifest.images[0].case_unique_message_count, 38);
  assert.deepEqual(artifacts.validateRenderManifest(validation, sourceRoot), {
    image_count: 3,
  });

  manifest.images = Array.from({ length: 3 }, () => manifest.images[0]);
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  assert.throws(
    () => artifacts.validateRenderManifest(validation, sourceRoot),
    /render manifest mismatch/i,
  );
});

test("生成前拒绝覆盖既有阶段目录或数据集源目录", (context) => {
  assert.ok(generator, "generate.cjs 尚未实现");
  assert.equal(typeof generator.assertFreshDestinations, "function");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "dating-preflight-test-"));
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const outputRoot = path.join(root, "images");
  const sourceRoot = path.join(root, "source");
  fs.mkdirSync(path.join(outputRoot, "UNCLEAR"), { recursive: true });
  assert.throws(
    () => generator.assertFreshDestinations(outputRoot, sourceRoot),
    /Refusing to overwrite stage directory/,
  );
  fs.rmSync(path.join(outputRoot, "UNCLEAR"), { recursive: true });
  fs.mkdirSync(path.join(outputRoot, "Unclear阶段待确定"), { recursive: true });
  assert.throws(
    () => generator.assertFreshDestinations(outputRoot, sourceRoot),
    /Refusing to overwrite stage directory/,
  );
  fs.rmSync(path.join(outputRoot, "Unclear阶段待确定"), { recursive: true });
  fs.mkdirSync(sourceRoot, { recursive: true });
  assert.throws(
    () => generator.assertFreshDestinations(outputRoot, sourceRoot),
    /Refusing to overwrite dataset source/,
  );
});

test("验收后移动阶段目录并保留图片根目录中的历史文件", (context) => {
  assert.equal(typeof generator.commitStagedDataset, "function");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "dating-commit-test-"));
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const outputRoot = path.join(root, "images");
  const stagedOutputRoot = path.join(outputRoot, ".build");
  const sourceRoot = path.join(root, "source-final");
  const stagedSourceRoot = path.join(root, ".source-build");
  fs.mkdirSync(path.join(stagedOutputRoot, "Unclear阶段待确定/example_01"), { recursive: true });
  fs.mkdirSync(path.join(stagedOutputRoot, "New connection初识接触/example_01"), { recursive: true });
  fs.mkdirSync(stagedSourceRoot, { recursive: true });
  fs.writeFileSync(path.join(outputRoot, "legacy.png"), "keep", "utf8");
  fs.writeFileSync(path.join(stagedSourceRoot, "manifest.json"), "{}", "utf8");

  generator.commitStagedDataset({
    stagedOutputRoot,
    outputRoot,
    stagedSourceRoot,
    sourceRoot,
    stageDirectories: ["Unclear阶段待确定", "New connection初识接触"],
  });

  assert.ok(fs.existsSync(path.join(outputRoot, "legacy.png")));
  assert.ok(fs.existsSync(path.join(outputRoot, "Unclear阶段待确定/example_01")));
  assert.ok(fs.existsSync(path.join(outputRoot, "New connection初识接触/example_01")));
  assert.ok(fs.existsSync(path.join(sourceRoot, "manifest.json")));
  assert.ok(!fs.existsSync(stagedOutputRoot));
  assert.ok(!fs.existsSync(stagedSourceRoot));
});
