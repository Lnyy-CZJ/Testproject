/**
 * 正向关系阶段截图数据集的领域定义与确定性内容生成。
 *
 * 本模块不直接访问文件系统或浏览器。它只把冻结的阶段、案例主题与轮转规则转换为
 * 可验证的内存对象，方便单元测试独立检查内容数量、分页连续性和黄金标注。
 */
const { beatBankForStage } = require("./dialogue_beats.cjs");

/**
 * 关系阶段必须保持产品枚举表中的顺序。
 * 阶段序号参与图片数量、locale 和视觉样式的轮转，改变顺序会同时改变全部案例分配。
 */
const STAGES = Object.freeze([
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

/**
 * 用户可见的截图交付目录名称。
 *
 * 内部数据、黄金标注和后端协议继续使用稳定的英文大写枚举；只有文件系统交付路径
 * 使用产品英文标签加中文释义。将映射集中在这里，可避免 E2E Case、manifest、QA 和
 * 实际 PNG 目录分别维护字符串后发生漂移。
 */
const STAGE_DIRECTORY_NAMES = Object.freeze({
  UNCLEAR: "Unclear阶段待确定",
  NEW_CONNECTION: "New connection初识接触",
  FRIENDS: "Friends朋友关系",
  TALKING: "Talking持续互动",
  FLIRTING: "Flirting暧昧探索",
  SITUATIONSHIP: "Situationship未定义关系",
  DATE_PLANNING: "Planning a date邀约阶段",
  DATING: "Dating约会验证",
  DEFINING_RELATIONSHIP: "Defining relationship关系确认",
  EXCLUSIVE: "Exclusive排他关系",
  RELATIONSHIP: "Relationship稳定关系",
  LONG_DISTANCE: "Long-distance异地关系",
  ON_A_BREAK: "On a break关系暂停",
  BREAKUP_DISCUSSION: "Breakup discussion分手讨论",
  RECONNECTING: "Reconnecting重新联系",
  ENDED: "Ended关系结束",
});

/**
 * 返回某个内部阶段对应的用户可见交付目录。
 *
 * @param {string} stage 产品关系阶段枚举。
 * @returns {string} 英文标签与中文释义连续拼接的目录名。
 * @throws {RangeError} 未知阶段不得静默退回枚举名，否则不同产物会产生两套路由。
 */
function stageDirectoryName(stage) {
  if (!Object.prototype.hasOwnProperty.call(STAGE_DIRECTORY_NAMES, stage)) {
    throw new RangeError(`Unknown relationship stage directory: ${String(stage)}`);
  }
  return STAGE_DIRECTORY_NAMES[stage];
}

const IMAGE_COUNTS = Object.freeze([3, 4, 5, 7, 9]);
const LOCALES = Object.freeze(["en-US", "en-GB", "en-CA", "en-IE", "en-NL"]);
const STYLE_IDS = Object.freeze([
  "azure-light",
  "sage-light",
  "midnight-dark",
  "plum-light",
  "mono-high-contrast",
]);
const PAIR_TYPES = Object.freeze([
  "woman-man",
  "woman-woman",
  "man-man",
  "nonbinary-inclusive",
]);

const CONTACT_NAMES = Object.freeze({
  woman: Object.freeze([
    "Ava", "Amelia", "Sofia", "Maya", "Chloe", "Lily", "Grace", "Nora", "Hannah",
    "Zoe", "Claire", "Lucy", "Alice", "Emma", "Ruby", "Isla", "Freya", "Elena",
    "Julia", "Naomi", "Leah", "Eva", "Clara", "Sadie", "Nina", "Mia", "Olivia",
    "Audrey", "Stella", "Vivian", "Lila", "Maeve", "Tessa", "Celeste", "Phoebe",
  ]),
  man: Object.freeze([
    "Liam", "Noah", "Ethan", "Lucas", "Owen", "Henry", "Leo", "Jack", "Theo",
    "Miles", "Adam", "Daniel", "Isaac", "Finn", "Oscar", "Felix", "Hugo", "Simon",
    "Colin", "Adrian", "Julian", "Marcus", "Elliot", "Louis", "Caleb", "Rowan",
    "Aaron", "Bennett", "Gabriel", "Nathan", "Victor", "Jonah", "Samuel", "Wesley",
    "Dylan",
  ]),
  nonbinary: Object.freeze([
    "Alex", "Taylor", "Jordan", "Casey", "Morgan", "Riley", "Avery", "Quinn", "Jamie",
    "Parker",
  ]),
});

const PRONOUNS = Object.freeze({
  woman: "she/her",
  man: "he/him",
  nonbinary: "they/them",
});

/**
 * 黄金标注中的排除项只描述“不能出现什么决定性证据”，不会展示在截图中。
 * 它用于人工评审相邻阶段边界，避免把诸如“正在讨论排他”和“已经排他”混为一类。
 */
const STAGE_EXCLUDED_CUES = Object.freeze({
  UNCLEAR: Object.freeze(["explicit friend label", "date confirmation", "romantic commitment"]),
  NEW_CONNECTION: Object.freeze(["established communication routine", "romantic history"]),
  FRIENDS: Object.freeze(["mutual flirting", "romantic date logistics"]),
  TALKING: Object.freeze(["explicit flirting", "confirmed date", "relationship label"]),
  FLIRTING: Object.freeze(["specific date confirmation", "exclusive agreement"]),
  SITUATIONSHIP: Object.freeze(["resolved relationship label", "active final definition decision"]),
  DATE_PLANNING: Object.freeze(["date already happened", "exclusive agreement"]),
  DATING: Object.freeze(["exclusive agreement", "confirmed partner label"]),
  DEFINING_RELATIONSHIP: Object.freeze(["final relationship decision", "completed exclusivity agreement"]),
  EXCLUSIVE: Object.freeze(["confirmed partner label", "long-distance dependency"]),
  RELATIONSHIP: Object.freeze(["long-term remote-only interaction", "active breakup decision"]),
  LONG_DISTANCE: Object.freeze(["same-city routine", "relationship pause"]),
  ON_A_BREAK: Object.freeze(["final breakup decision", "normal relationship routine"]),
  BREAKUP_DISCUSSION: Object.freeze(["completed breakup", "normal unresolved conflict only"]),
  RECONNECTING: Object.freeze(["restored commitment", "continuous uninterrupted contact"]),
  ENDED: Object.freeze(["romantic rebuilding", "unresolved breakup decision"]),
});

/**
 * 每个阶段额外保留一条自然的末段证据。五条场景锚点必须按作者编写顺序连续出现，不能
 * 为了把证据摊到不同截图而拆开问答；因此这里用独立句子满足“最后两张仍有强证据”的
 * 验收要求。句子只复述当前状态，并明确避开最容易混淆的相邻阶段。
 */
const LATE_STAGE_EVIDENCE = Object.freeze({
  UNCLEAR: "I am comfortable keeping this connection open without deciding what it means today.",
  NEW_CONNECTION: "I am glad we have started getting acquainted, and I am happy to keep it easy.",
  FRIENDS: "I value the friendship we have, and I am glad we can keep showing up as friends.",
  TALKING: "I like our regular conversations and want to keep learning about each other at this pace.",
  FLIRTING: "I am enjoying the way we flirt, and I do not need to turn it into a bigger promise today.",
  SITUATIONSHIP: "I care about this connection, and I also know we have not defined what we are.",
  DATE_PLANNING: "I am looking forward to the date we planned, and I appreciate keeping the details comfortable.",
  DATING: "I am enjoying dating you and want to keep learning about each other without rushing exclusivity.",
  DEFINING_RELATIONSHIP: "I am glad we can discuss what this relationship could be without forcing a decision tonight.",
  EXCLUSIVE: "I value our agreement to date only each other, even though we have not chosen a partner label.",
  RELATIONSHIP: "I feel secure in the relationship we have built as partners, including in ordinary moments.",
  LONG_DISTANCE: "I am committed to our relationship and to caring for it across the distance between us.",
  ON_A_BREAK: "I will respect the break we agreed on until our review, without treating the silence as a final answer.",
  BREAKUP_DISCUSSION: "I am still considering whether we should end the relationship, and I have not chosen an answer tonight.",
  RECONNECTING: "I am glad we are reconnecting slowly without assuming that our old relationship will return.",
  ENDED: "I accept that our relationship is over, and this respectful goodbye does not reopen it.",
});

/**
 * 把阶段枚举转换为稳定的案例 ID 片段。
 *
 * @param {string} stage 产品关系阶段枚举。
 * @returns {string} 仅包含小写字母和连字符的 ID 片段。
 */
function stageIdPart(stage) {
  return stage.toLowerCase().replaceAll("_", "-");
}

/**
 * 把混合来源的英文素材统一为目标 locale 的常见拼写。
 *
 * 场景锚点与通用填充模板由不同批次维护，不能假设它们天然采用同一套拼写。数据集
 * 将 en-US 视为美式英文，其余四个欧洲/加拿大语境采用英式英文；这里只转换容易在
 * 测试数据中出现的确定性词形，不改写句法或口语，避免无意改变阶段证据的含义。
 *
 * @param {string} text 原始英文正文。
 * @param {string} locale 案例 locale。
 * @returns {string} 拼写已统一、语义不变的正文。
 */
function localiseEnglish(text, locale) {
  const britishToAmerican = new Map([
    ["favourites", "favorites"],
    ["favourite", "favorite"],
    ["colours", "colors"],
    ["colour", "color"],
    ["organisations", "organizations"],
    ["organisation", "organization"],
    ["organising", "organizing"],
    ["organised", "organized"],
    ["organises", "organizes"],
    ["organise", "organize"],
    ["centres", "centers"],
    ["centre", "center"],
    ["travellers", "travelers"],
    ["traveller", "traveler"],
    ["travelling", "traveling"],
    ["travelled", "traveled"],
    ["cancelling", "canceling"],
    ["cancelled", "canceled"],
    ["flavours", "flavors"],
    ["flavour", "flavor"],
    ["practising", "practicing"],
    ["practised", "practiced"],
    ["practises", "practices"],
    ["honouring", "honoring"],
    ["honoured", "honored"],
    ["honours", "honors"],
    ["honour", "honor"],
    ["behavioural", "behavioral"],
    ["behaviour", "behavior"],
  ]);
  const americanToBritish = new Map(
    [...britishToAmerican].map(([british, american]) => [american, british]),
  );
  const spellings = locale === "en-US" ? britishToAmerican : americanToBritish;
  const pattern = new RegExp(`\\b(${[...spellings.keys()].join("|")})\\b`, "gi");
  return text.replace(pattern, (match) => {
    const replacement = spellings.get(match.toLowerCase());
    if (match === match.toUpperCase()) return replacement.toUpperCase();
    if (match[0] === match[0].toUpperCase()) {
      return replacement[0].toUpperCase() + replacement.slice(1);
    }
    return replacement;
  });
}

/**
 * 按四类关系组合分配人物代词和唯一联系人名。
 *
 * `CONTACT_NAMES` 的数量与 80 个案例中的实际联系人身份分布精确对应：女性 35、男性
 * 35、非二元 10。若后续调整组合分布而未同步扩展姓名库，本函数会立即报错，而不会
 * 静默复用姓名造成案例混淆。
 *
 * @param {Array<object>} definitions 全部案例元数据。
 * @returns {Array<object>} 与 definitions 一一对应的 participants 对象。
 */
function buildParticipants(definitions) {
  const counters = { woman: 0, man: 0, nonbinary: 0 };

  function nextContact(identity) {
    const name = CONTACT_NAMES[identity][counters[identity]];
    if (!name) {
      throw new RangeError(`No unused contact name for identity: ${identity}`);
    }
    counters[identity] += 1;
    return { identity, name, pronouns: PRONOUNS[identity] };
  }

  return definitions.map((definition, caseIndex) => {
    const cycleIndex = Math.floor(caseIndex / PAIR_TYPES.length);
    let selfIdentity;
    let otherIdentity;

    if (definition.pair_type === "woman-man") {
      otherIdentity = cycleIndex % 2 === 0 ? "man" : "woman";
      selfIdentity = otherIdentity === "man" ? "woman" : "man";
    } else if (definition.pair_type === "woman-woman") {
      selfIdentity = "woman";
      otherIdentity = "woman";
    } else if (definition.pair_type === "man-man") {
      selfIdentity = "man";
      otherIdentity = "man";
    } else if (cycleIndex % 2 === 0) {
      selfIdentity = cycleIndex % 4 === 0 ? "woman" : "man";
      otherIdentity = "nonbinary";
    } else {
      selfIdentity = "nonbinary";
      otherIdentity = cycleIndex % 4 === 1 ? "woman" : "man";
    }

    const contact = nextContact(otherIdentity);
    return Object.freeze({
      self: Object.freeze({
        id: "self",
        display_name: "You",
        pronouns: PRONOUNS[selfIdentity],
      }),
      other: Object.freeze({
        id: "other",
        display_name: contact.name,
        pronouns: contact.pronouns,
      }),
    });
  });
}

/**
 * 构建全部 80 个案例的不可变分配信息。
 *
 * 图片数量、locale 和样式使用不同步长轮转，确保每个阶段都覆盖五种取值，同时避免
 * 某种地区或视觉样式与固定对话长度绑定。人物组合按全局案例序号轮转，最终四类各
 * 20 例。该函数不生成消息正文，因此可以在浏览器和文件系统之外独立验证。
 *
 * @returns {Array<object>} 按阶段顺序、阶段内 example_01～example_05 排列的案例定义。
 */
function buildCaseDefinitions() {
  return STAGES.flatMap((stage, stageIndex) =>
    Array.from({ length: 5 }, (_, exampleIndex) => {
      const exampleNumber = exampleIndex + 1;
      return Object.freeze({
        schema_version: "aidating.chat-screenshot-source.v1",
        case_id: `analysis-stage-${stageIdPart(stage)}-positive-${String(exampleNumber).padStart(2, "0")}`,
        task_kind: "analysis",
        target_stage: stage,
        example_id: `example_${String(exampleNumber).padStart(2, "0")}`,
        image_count: IMAGE_COUNTS[(stageIndex + exampleIndex) % IMAGE_COUNTS.length],
        locale: LOCALES[(2 * stageIndex + exampleIndex) % LOCALES.length],
        style_id: STYLE_IDS[(3 * stageIndex + exampleIndex) % STYLE_IDS.length],
        pair_type: PAIR_TYPES[(stageIndex * 5 + exampleIndex) % PAIR_TYPES.length],
      });
    }),
  );
}

/**
 * 生成单个案例的完整消息序列和截图分页。
 *
 * 五条人工锚点保持原顺序连续出现，避免把问题与回答拆到几十条消息之外；随后使用一
 * 段不间断的阶段安全双人对话，倒数第三条再写入独立阶段证据。内部 `scenario.topic`
 * 只保留在源数据元信息中，绝不会作为可见聊天模板参数。
 *
 * @param {object} definition `buildCaseDefinitions` 产生的案例元数据。
 * @param {object} scenario 包含五条阶段锚点和两条结尾消息的场景定义。
 * @returns {{messages: Array<object>, pages: Array<object>, stage_evidence_message_ids: string[]}}
 *   `messages` 只包含去重后的原始顺序；`pages` 按 14 条一页、相邻两条重叠切片；
 *   `stage_evidence_message_ids` 指向五条场景锚点与一条末段阶段证据。
 * @throws {RangeError|TypeError} 图片数量或场景结构不符合冻结契约时抛出。
 */
function buildConversation(definition, scenario) {
  if (!IMAGE_COUNTS.includes(definition.image_count)) {
    throw new RangeError(`Unsupported image count: ${definition.image_count}`);
  }
  if (
    !scenario
    || !Array.isArray(scenario.anchors)
    || scenario.anchors.length !== 5
    || !Array.isArray(scenario.closing)
    || scenario.closing.length !== 2
  ) {
    throw new TypeError("Scenario must contain exactly 5 anchors and 2 closing messages");
  }

  const messageCount = 14 + (definition.image_count - 1) * 12;
  const beatBank = beatBankForStage(definition.target_stage);
  const fillerMessageCount = messageCount - scenario.anchors.length - scenario.closing.length - 1;
  const fillerBeatCount = fillerMessageCount / 2;
  if (!Number.isInteger(fillerBeatCount) || fillerBeatCount > beatBank.length) {
    throw new RangeError(
      `${definition.case_id}: dialogue beat bank is shorter than the requested conversation`,
    );
  }
  const usesNeutralDailyChat = beatBank === beatBankForStage("TALKING");
  const fillerMessages = beatBank.slice(0, fillerBeatCount).flatMap((beat, beatIndex) => {
    /*
     * 通用 bank 会从阶段讨论切到日常话题，因此首句明确提示换题；阶段专用 bank 则沿着
     * 当前关系语境继续，不强行宣称换题。最后一组固定回扣此前讨论，让末段证据成为
     * 对方提问后的自然回答，而不是从做饭、工作等闲聊中突然插入标签式总结。
     */
    if (beatIndex === fillerBeatCount - 1) {
      return [
        { speaker: "other", text: "Before we wrap up, can we return to what we said earlier?" },
        { speaker: "self", text: "Yes, I have one more thought about it." },
      ];
    }
    const firstOtherText = usesNeutralDailyChat
      ? `I understand. Can we shift topics for a moment? ${beat.other}`
      : `I understand. ${beat.other}`;
    return [
      { speaker: "other", text: beatIndex === 0 ? firstOtherText : beat.other },
      { speaker: "self", text: beat.self },
    ];
  });
  const lateEvidence = LATE_STAGE_EVIDENCE[definition.target_stage];
  if (!lateEvidence) throw new RangeError(`Missing late evidence for ${definition.target_stage}`);
  const rawMessages = [
    ...scenario.anchors.map((anchor) => ({ ...anchor, evidence: true })),
    ...fillerMessages,
    { speaker: "self", text: lateEvidence, evidence: true },
    ...scenario.closing.map((message) => ({ ...message })),
  ];

  const startedAt = Date.UTC(2026, 0, 8, 18, 0);
  const messages = rawMessages.map(({ evidence, ...message }, index) => ({
    id: `m_${String(index + 1).padStart(3, "0")}`,
    ...message,
    text: localiseEnglish(message.text, definition.locale),
    type: "text",
    timestamp: new Date(startedAt + index * 4 * 60_000).toISOString(),
  }));
  const stageEvidenceMessageIds = rawMessages
    .map((message, index) => message.evidence ? messages[index].id : null)
    .filter(Boolean);

  const pages = Array.from({ length: definition.image_count }, (_, pageIndex) => {
    const start = pageIndex * 12;
    return {
      page_number: pageIndex + 1,
      messages: messages.slice(start, start + 14),
    };
  });

  return {
    messages,
    pages,
    stage_evidence_message_ids: stageEvidenceMessageIds,
  };
}

/**
 * 把案例轮转、场景目录、人物与长对话组合成最终的 80 个内存案例。
 *
 * @param {Record<string, Array<object>>} stageScenarios 由 scenario_catalog.cjs 提供的目录。
 * @returns {Array<object>} 可直接序列化为 Transcript、黄金标注和渲染任务的案例集合。
 * @throws {TypeError} 当任一阶段缺少五个场景时抛出，防止生成半套数据。
 */
function buildDataset(stageScenarios) {
  const definitions = buildCaseDefinitions();
  const participants = buildParticipants(definitions);

  return definitions.map((definition, caseIndex) => {
    const scenarios = stageScenarios[definition.target_stage];
    if (!Array.isArray(scenarios) || scenarios.length !== 5) {
      throw new TypeError(`Expected 5 scenarios for ${definition.target_stage}`);
    }
    const scenario = scenarios[caseIndex % 5];
    const conversation = buildConversation(definition, scenario);
    return Object.freeze({
      ...definition,
      positive_track: scenario.track,
      scenario,
      participants: participants[caseIndex],
      messages: conversation.messages,
      pages: conversation.pages,
      stage_evidence_message_ids: conversation.stage_evidence_message_ids,
      excluded_stage_cues: STAGE_EXCLUDED_CUES[definition.target_stage],
      render: Object.freeze({
        width: 430,
        height: 932,
        bubbles_per_image: 14,
        overlap_messages: 2,
        page_message_ids: conversation.pages.map((page) =>
          page.messages.map(({ id }) => id)
        ),
      }),
    });
  });
}

/**
 * 校验内存数据集是否满足截图生成前的全部确定性约束。
 *
 * @param {Array<object>} cases `buildDataset` 生成的完整案例。
 * @returns {{stage_count: number, case_count: number, page_count: number,
 *   unique_message_count: number, contact_count: number}} 验收统计。
 * @throws {Error} 任一数量、分页、正文、隐私或证据约束失败时，一次列出全部错误。
 */
function validateDataset(cases) {
  const errors = [];
  const stageSet = new Set(cases.map(({ target_stage }) => target_stage));
  const caseIdSet = new Set(cases.map(({ case_id }) => case_id));
  const contactSet = new Set(cases.map(({ participants }) => participants.other.display_name));
  const pageCount = cases.reduce((total, item) => total + item.pages.length, 0);
  const uniqueMessageCount = cases.reduce((total, item) => total + item.messages.length, 0);
  const forbiddenVisibleData = /(?:\b(?:WhatsApp|iMessage|Telegram|Messenger|Instagram|Tinder|Bumble|Hinge)\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\+?\d[\d ()-]{7,}\d)/i;

  if (
    stageSet.size !== STAGES.length
    || STAGES.some((stage) => !stageSet.has(stage))
  ) {
    errors.push(`expected exact 16-stage set, got ${stageSet.size} stages`);
  }
  if (cases.length !== 80) errors.push(`expected 80 cases, got ${cases.length}`);
  if (caseIdSet.size !== cases.length) errors.push("case IDs are not unique");
  if (pageCount !== 448) errors.push(`expected 448 pages, got ${pageCount}`);
  if (uniqueMessageCount !== 5536) {
    errors.push(`expected 5536 unique messages, got ${uniqueMessageCount}`);
  }
  if (contactSet.size !== 80) errors.push(`expected 80 contacts, got ${contactSet.size}`);

  for (const stage of STAGES) {
    const stageCases = cases.filter(({ target_stage }) => target_stage === stage);
    const sizes = stageCases.map(({ image_count }) => image_count).sort((a, b) => a - b);
    const tracks = stageCases.map(({ positive_track }) => positive_track);
    if (stageCases.length !== 5) errors.push(`${stage}: expected 5 cases`);
    if (JSON.stringify(sizes) !== JSON.stringify(IMAGE_COUNTS)) {
      errors.push(`${stage}: must cover image counts 3/4/5/7/9 exactly once`);
    }
    if (
      tracks.filter((track) => track === "stage_accurate").length !== 3
      || tracks.filter((track) => track === "constructive").length !== 2
    ) {
      errors.push(`${stage}: expected 3 stage_accurate and 2 constructive cases`);
    }
  }

  for (const item of cases) {
    const expectedMessageCount = 14 + (item.image_count - 1) * 12;
    if (item.messages.length !== expectedMessageCount) {
      errors.push(`${item.case_id}: wrong message count`);
    }
    if (item.pages.length !== item.image_count) {
      errors.push(`${item.case_id}: wrong page count`);
    }
    if (item.stage_evidence_message_ids.length !== 6) {
      errors.push(`${item.case_id}: expected exactly 6 stage evidence messages`);
    }
    if (new Set(item.stage_evidence_message_ids).size !== item.stage_evidence_message_ids.length) {
      errors.push(`${item.case_id}: stage evidence message IDs must be unique`);
    }
    if (item.positive_track !== item.scenario.track) {
      errors.push(`${item.case_id}: track does not match scenario`);
    }

    const messageIds = new Set();
    let previousTimestamp = "";
    for (const message of item.messages) {
      if (messageIds.has(message.id)) errors.push(`${item.case_id}: duplicate ${message.id}`);
      messageIds.add(message.id);
      if (message.timestamp <= previousTimestamp) {
        errors.push(`${item.case_id}: timestamps are not increasing at ${message.id}`);
      }
      previousTimestamp = message.timestamp;
      if (
        message.text.length < 2
        || message.text.length > 110
        || !/^[\x20-\x7E]+$/.test(message.text)
      ) {
        errors.push(`${item.case_id}: invalid English text at ${message.id}`);
      }
      if (forbiddenVisibleData.test(message.text)) {
        errors.push(`${item.case_id}: brand or PII pattern at ${message.id}`);
      }
      if (localiseEnglish(message.text, item.locale) !== message.text) {
        errors.push(`${item.case_id}: locale spelling mismatch at ${message.id}`);
      }
    }
    for (const evidenceId of item.stage_evidence_message_ids) {
      if (!messageIds.has(evidenceId)) {
        errors.push(`${item.case_id}: unknown stage evidence message ${evidenceId}`);
      }
    }
    const authoredEvidence = [
      ...item.scenario.anchors,
      { speaker: "self", text: LATE_STAGE_EVIDENCE[item.target_stage] },
    ].map(({ speaker, text }) => ({
      speaker,
      text: localiseEnglish(text, item.locale),
    }));
    const actualEvidence = item.stage_evidence_message_ids.map((evidenceId) => {
      const message = item.messages.find(({ id }) => id === evidenceId);
      return message ? { speaker: message.speaker, text: message.text } : null;
    });
    if (JSON.stringify(actualEvidence) !== JSON.stringify(authoredEvidence)) {
      errors.push(`${item.case_id}: stage evidence does not match authored evidence`);
    }

    for (let pageIndex = 0; pageIndex < item.pages.length; pageIndex += 1) {
      const page = item.pages[pageIndex];
      if (page.messages.length !== 14) {
        errors.push(`${item.case_id}: page ${page.page_number} does not have 14 messages`);
      }
      const selfCount = page.messages.filter(({ speaker }) => speaker === "self").length;
      const otherCount = page.messages.filter(({ speaker }) => speaker === "other").length;
      if (selfCount < 5 || otherCount < 5) {
        errors.push(`${item.case_id}: page ${page.page_number} has unbalanced speakers`);
      }
      const expectedPageMessages = item.messages.slice(pageIndex * 12, pageIndex * 12 + 14);
      if (JSON.stringify(page.messages) !== JSON.stringify(expectedPageMessages)) {
        errors.push(
          `${item.case_id}: page ${page.page_number} does not match the transcript slice`,
        );
      }
      let run = 1;
      let longestRun = 1;
      for (let index = 1; index < page.messages.length; index += 1) {
        if (page.messages[index].speaker === page.messages[index - 1].speaker) {
          run += 1;
          longestRun = Math.max(longestRun, run);
        } else {
          run = 1;
        }
      }
      if (longestRun > 4) {
        errors.push(`${item.case_id}: page ${page.page_number} has a speaker run over 4`);
      }
      if (pageIndex > 0) {
        const previousPage = item.pages[pageIndex - 1];
        const overlapView = ({ id, text, timestamp }) => ({ id, text, timestamp });
        const previousOverlap = previousPage.messages.slice(-2).map(overlapView);
        const currentOverlap = page.messages.slice(0, 2).map(overlapView);
        const currentIds = new Set(page.messages.map(({ id }) => id));
        const sharedIds = previousPage.messages
          .map(({ id }) => id)
          .filter((id) => currentIds.has(id));
        if (
          sharedIds.length !== 2
          || JSON.stringify(previousOverlap) !== JSON.stringify(currentOverlap)
        ) {
          errors.push(
            `${item.case_id}: page ${page.page_number} overlap must preserve exactly 2 messages with identical ID, text, and timestamp`,
          );
        }
      }
    }

    const recentIds = new Set(
      item.pages.slice(-2).flatMap((page) => page.messages.map(({ id }) => id)),
    );
    if (!item.stage_evidence_message_ids.some((id) => recentIds.has(id))) {
      errors.push(`${item.case_id}: no stage evidence in the final two pages`);
    }
  }

  if (errors.length > 0) {
    throw new Error(`Dataset validation failed:\n- ${errors.join("\n- ")}`);
  }
  return {
    stage_count: stageSet.size,
    case_count: cases.length,
    page_count: pageCount,
    unique_message_count: uniqueMessageCount,
    contact_count: contactSet.size,
  };
}

module.exports = {
  CONTACT_NAMES,
  IMAGE_COUNTS,
  LATE_STAGE_EVIDENCE,
  LOCALES,
  PAIR_TYPES,
  STAGE_EXCLUDED_CUES,
  STAGE_DIRECTORY_NAMES,
  STAGES,
  STYLE_IDS,
  buildCaseDefinitions,
  buildConversation,
  buildDataset,
  localiseEnglish,
  stageDirectoryName,
  validateDataset,
};
