/**
 * People Insight 工作台适配器。
 *
 * 职责：
 * 1. 复用现有 /people-search/analyze JSON 接口，不在浏览器重做分析规则；
 * 2. 把同一份响应拆到概览、Provider 接口链路、最终结果和检查结果四个 panel；
 * 3. 只使用固定 DOM 节点的 textContent、属性和值渲染服务端数据，保留完整 Markdown；
 * 4. 仅在 evidence 同时给出有效日志起止行时调用核心的真实行号定位。
 *
 * People 的 Provider timeline 是接口调用链，不是任务 Poll 时间线，因此只放在
 * interfacesPanel，并通过 setAvailableTabs 隐藏通用 timelinePanel。
 */
(function bootstrapPeopleWorkbench(global, document) {
  "use strict";

  var api = global.LogWorkbench || {};

  var verdictLabels = {
    NORMAL: "未发现异常",
    ISSUES_FOUND: "发现已确认异常",
    NEEDS_CONFIRMATION: "需要后端确认",
    INCOMPLETE_EVIDENCE: "日志证据不足"
  };

  var coverageLabels = {
    create_task: "创建任务",
    get_task: "任务终态",
    candidate_list: "候选列表",
    candidate_detail: "候选详情",
    debug: "调试链路",
    cost_summary: "成本汇总"
  };

  var diagnosisLabels = {
    final_status: "诊断终态",
    stop_reason: "业务停止原因",
    status_consistent: "状态自检",
    llm_output_status: "LLM 输出",
    llm_result_status: "LLM 结果",
    llm_truncation_detected: "LLM 截断",
    pdl_identify_call_count: "PDL Identify 次数",
    pdl_person_search_call_count: "PDL Search 次数",
    pdl_person_search_returned_profile_count: "PDL 返回 Profile",
    pdl_usable_candidate_count: "PDL 可用候选",
    reverse_image_status: "图片反查",
    reverse_image_stop_reason: "图片停止原因",
    reverse_image_primary_provider: "图片主工具",
    reverse_image_final_provider: "图片最终工具",
    social_profile_status: "Social Profile",
    face_comparison_status: "Face Comparison",
    pre_pdl_estimated_cost_microunit: "PDL 前阶段成本"
  };

  var outcomeOrder = {
    FAIL: 0,
    WARN: 1,
    UNKNOWN: 2,
    PASS: 3,
    NOT_APPLICABLE: 4,
    NA: 4
  };

  var outcomeLabels = {
    FAIL: "FAIL",
    WARN: "WARN",
    UNKNOWN: "UNKNOWN",
    PASS: "PASS",
    NOT_APPLICABLE: "NA",
    NA: "NA"
  };

  var latestPeopleChecks = [];
  var latestPeopleLineCount = 0;
  var peopleCheckFilterInitialized = false;

  function getElement(id) {
    return document.getElementById(id);
  }

  /** 将结构化值变为可读纯文本；0、false 和空数组都不能被误当成缺失。 */
  function displayValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") {
      try {
        return JSON.stringify(value);
      } catch (error) {
        return "[值无法展示]";
      }
    }
    return String(value);
  }

  /** 清空一个由本适配器拥有的固定容器，不触碰日志或其他模式的状态。 */
  function clearNode(node) {
    if (!node) return node;
    node.textContent = "";
    // 行为测试的轻量 DOM 用数组保存 children；真实浏览器由 textContent 负责移除子节点。
    if (Array.isArray(node.children)) node.children.length = 0;
    return node;
  }

  function createElement(tagName, className, text) {
    var element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  }

  function appendField(container, label, value) {
    var group = createElement("div", "people-field");
    var term = createElement("dt", "people-field__label", label);
    var description = createElement("dd", "people-field__value", displayValue(value));
    group.appendChild(term);
    group.appendChild(description);
    container.appendChild(group);
  }

  /** 用固定顺序展示已知诊断字段，并追加响应中新增但前端尚未命名的字段。 */
  function renderObjectFields(container, object, labels) {
    var source = object && typeof object === "object" ? object : {};
    var rendered = Object.create(null);
    var knownKeys = Object.keys(labels || {});
    knownKeys.forEach(function renderKnownField(key) {
      if (!Object.prototype.hasOwnProperty.call(source, key)) return;
      appendField(container, labels[key], source[key]);
      rendered[key] = true;
    });
    Object.keys(source).forEach(function renderAdditionalField(key) {
      if (rendered[key]) return;
      appendField(container, key, source[key]);
    });
    return Object.keys(source).length > 0;
  }

  /** 统一 header 先尝试使用核心 setter，同时保留当前版本核心的 DOM 兼容回退。 */
  function setPeopleResultHeader(title, subtitle) {
    if (typeof api.setResultHeader === "function") {
      api.setResultHeader(title, subtitle);
    }
    var heading = getElement("workbench-result-heading");
    var subheading = getElement("workbench-result-subheading");
    if (heading) heading.textContent = String(title || "");
    if (subheading) subheading.textContent = String(subtitle || "");
  }

  function taskSubtitle(task) {
    task = task && typeof task === "object" ? task : {};
    var clues = Array.isArray(task.clue_types) ? task.clue_types.join("、") : displayValue(task.clue_types);
    return "姓名=" + displayValue(task.full_name) +
      " · task_id=" + displayValue(task.task_id) +
      " · 终态=" + displayValue(task.final_status) +
      " · candidate_count=" + displayValue(task.candidate_count) +
      " · result_type=" + displayValue(task.result_type) +
      " · no_result_reason=" + displayValue(task.no_result_reason) +
      " · clues=" + clues;
  }

  /** 任务摘要必须来自本轮响应的 task，不能继续显示模板的初始占位文案。 */
  function renderTaskSummary(data) {
    var summary = getElement("people-task-summary");
    if (summary) summary.textContent = taskSubtitle(data.task);
  }

  function renderVerdict(data) {
    var verdict = data.verdict || "INCOMPLETE_EVIDENCE";
    var label = verdictLabels[verdict] || String(verdict);
    var panel = getElement("people-verdict-panel");
    var title = getElement("people-verdict-title") || getElement("people-overview-heading");
    if (panel) panel.setAttribute("data-verdict", verdictLabels[verdict] ? verdict : "INCOMPLETE_EVIDENCE");
    if (title) title.textContent = label;
    setPeopleResultHeader(label, taskSubtitle(data.task));
    var status = getElement("people-search-status");
    if (status) status.textContent = String(verdict);
  }

  /** AI 只作为辅助说明展示，永远不参与 verdict 标题和确定性结论计算。 */
  function renderAiStatus(data) {
    var ai = data.ai && typeof data.ai === "object" ? data.ai : {};
    var status = ai.status || "DISABLED";
    var labels = {
      SUCCESS: "AI 分析状态：已生成独立解释",
      DISABLED: "AI 分析状态：未启用，当前内容来自确定性规则",
      FAILED: "AI 分析状态：调用失败，已降级为确定性规则"
    };
    var element = getElement("people-ai-status");
    if (!element) return;
    element.className = "ai-status " + (status === "SUCCESS" ? "success" : status === "FAILED" ? "failed" : "");
    element.textContent = labels[status] || "AI 分析状态：" + String(status);
  }

  function renderCoverage(data) {
    var container = clearNode(getElement("people-coverage-list"));
    if (!container) return;
    var coverage = data.coverage && typeof data.coverage === "object" ? data.coverage : {};
    Object.keys(coverageLabels).forEach(function renderCoverageItem(key) {
      var item = createElement("div", "coverage-item");
      var label = createElement("span", "coverage-item__label", coverageLabels[key]);
      var state = createElement("span", coverage[key] ? "present" : "missing", coverage[key] ? "已包含" : "缺失");
      item.appendChild(label);
      item.appendChild(state);
      container.appendChild(item);
    });
    if (coverage.source_truncated) {
      var warning = createElement("p", "coverage-warning", "部分日志解析失败，证据可能不完整。");
      container.appendChild(warning);
    }
  }

  function renderIssueSummary(data) {
    var container = clearNode(getElement("people-issue-list"));
    if (!container) return;
    var checks = Array.isArray(data.checks) ? data.checks : [];
    var issues = checks.filter(function isIssue(check) {
      return check && ["FAIL", "WARN", "UNKNOWN"].indexOf(String(check.outcome || "")) !== -1;
    });
    if (!issues.length) {
      container.appendChild(createElement("li", "issue-item", "当前规则范围内没有异常或待确认项。"));
      return;
    }
    issues.forEach(function renderIssue(check) {
      var outcome = normalizeOutcome(check.outcome);
      var text = outcome + " · " + displayValue(check.rule_id) + " · " + displayValue(check.title) +
        " — " + displayValue(check.actual);
      container.appendChild(createElement("li", "issue-item " + outcome.toLowerCase(), text));
    });
  }

  function formatCallDetails(details) {
    if (!details || typeof details !== "object") return "—";
    return Object.keys(details).map(function formatDetail(key) {
      return key + "=" + displayValue(details[key]);
    }).join(" · ") || "—";
  }

  /** Provider 行使用后端已经抽取的字段；不存在的日志上下文明确标记为不足。 */
  function buildPeopleDrawerPayload(call) {
    call = call && typeof call === "object" ? call : {};
    var operation = call.operation || call.provider_operation;
    var source = call.source && typeof call.source === "object" ? call.source : null;
    return {
      title: "Provider 调用详情",
      provider: call.provider,
      operation: operation,
      status: call.status,
      http_status: call.http_status,
      cache_hit: call.cache_hit,
      cost_status: call.cost_status,
      estimated_cost_microunit: call.estimated_cost_microunit,
      result_class: call.result_class,
      result_details: call.result_details,
      request: call.request || null,
      response: call.response || null,
      evidence: source || "日志证据不足"
    };
  }

  function openPeopleCallDrawer(call, trigger) {
    var payload = buildPeopleDrawerPayload(call);
    if (typeof api.openInterfaceDrawer === "function") {
      api.openInterfaceDrawer(payload, trigger);
    } else if (typeof api.showActionMessage === "function") {
      api.showActionMessage("接口详情抽屉不可用。", true);
    }
    return payload;
  }

  /** Provider 链路只渲染到 interfacesPanel，保留业务结果和技术诊断两组字段。 */
  function renderTimeline(data) {
    var container = clearNode(getElement("people-timeline"));
    if (!container) return;
    var timeline = Array.isArray(data.timeline) ? data.timeline : [];
    if (!timeline.length) {
      container.textContent = "缺少 agent_tool_calls，Provider 顺序无法判断。";
      return;
    }
    var table = createElement("table", "analysis-table");
    var headRow = createElement("tr");
    ["#", "Provider", "Operation", "状态", "业务结果", "诊断", "HTTP", "缓存", "成本"].forEach(function renderHeader(label) {
      headRow.appendChild(createElement("th", "", label));
    });
    var thead = createElement("thead");
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = createElement("tbody");
    timeline.forEach(function renderCall(call, index) {
      call = call && typeof call === "object" ? call : {};
      var business = [call.no_result_reason, call.decision_reason,
        call.found === null || call.found === undefined ? "" : "found=" + String(call.found),
        call.candidate_count === null || call.candidate_count === undefined ? "" : "candidates=" + String(call.candidate_count)]
        .filter(Boolean).join(" · ") || "—";
      var cost = [call.cost_status,
        call.estimated_cost_microunit === null || call.estimated_cost_microunit === undefined
          ? "" : call.estimated_cost_microunit]
        .filter(function keepCost(value) { return value !== "" && value !== null && value !== undefined; })
        .join(" · ") || "—";
      var row = createElement("tr");
      var sequenceCell = createElement("td");
      var trigger = createElement("button", "people-row-toggle", index + 1);
      trigger.type = "button";
      trigger.setAttribute("aria-label", "打开 Provider 接口详情");
      trigger.setAttribute("aria-expanded", "false");
      trigger.addEventListener("click", function openCallDetails() {
        openPeopleCallDrawer(call, trigger);
      });
      sequenceCell.appendChild(trigger);
      row.appendChild(sequenceCell);
      [call.provider, call.operation, call.status, business,
        formatCallDetails(call.result_details), call.http_status,
        call.cache_hit ? "是" : "否", cost].forEach(function renderCell(value, cellIndex) {
          var cell = createElement("td", cellIndex === 4 ? "diagnostic-cell" : "", displayValue(value));
          row.appendChild(cell);
        });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  function renderDiagnosis(data) {
    var container = clearNode(getElement("people-diagnosis-list"));
    if (!container) return;
    if (!renderObjectFields(container, data.diagnosis, diagnosisLabels)) {
      container.textContent = "暂无可核对的诊断数据。";
    }
  }

  function renderCost(data) {
    var container = clearNode(getElement("people-cost-summary"));
    if (!container) return;
    var cost = data.cost && typeof data.cost === "object" ? data.cost : {};
    if (!renderObjectFields(container, cost, {
      total_estimated_cost_microunit: "任务总成本（microunit）",
      totals: "按币种总计",
      by_provider: "按 Provider 分项",
      items: "成本明细",
      calls: "调用成本明细"
    })) {
      container.textContent = "缺少可核对的成本总计。";
    }
  }

  /** 按当前原始日志的换行符计算 1-based 可定位行数。 */
  function countLogLines(text) {
    var value = String(text || "");
    return value ? value.split(/\r\n|\r|\n/).length : 0;
  }

  function normalizeOutcome(outcome) {
    var value = String(outcome || "UNKNOWN").toUpperCase();
    return Object.prototype.hasOwnProperty.call(outcomeLabels, value) ? value : "UNKNOWN";
  }

  /** 只接受当前日志内的真实整数范围，拒绝越界、反向和数字字符串。 */
  function validEvidenceRange(evidence, lineCount) {
    if (!evidence || typeof evidence !== "object") return null;
    var start = evidence.line_start;
    var end = evidence.line_end;
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 ||
        end < start || end > lineCount) return null;
    return {start: start, end: end};
  }

  /** Evidence 没有同时给出真实行号时，明确降级，不从 json_path 或 method 猜测位置。 */
  function renderEvidence(container, evidenceList, lineCount) {
    var evidence = Array.isArray(evidenceList) ? evidenceList : [];
    if (!evidence.length) {
      container.appendChild(createElement("span", "evidence-unavailable", "日志证据不足"));
      return;
    }
    evidence.forEach(function renderEvidenceItem(item) {
      var wrapper = createElement("div", "evidence-item");
      var reference = item && typeof item === "object"
        ? displayValue(item.method) + " " + displayValue(item.json_path)
        : "未知证据";
      wrapper.appendChild(createElement("span", "evidence-reference", "证据：" + reference));
      var range = validEvidenceRange(item, lineCount);
      if (!range) {
        wrapper.appendChild(createElement("span", "evidence-unavailable", "日志证据不足"));
      } else {
        var button = createElement("button", "evidence-button", "定位日志 L" + range.start + "–" + range.end);
        button.type = "button";
        button.addEventListener("click", function focusEvidence() {
          if (typeof api.focusLogLines === "function") api.focusLogLines(range.start, range.end);
        });
        wrapper.appendChild(button);
      }
      container.appendChild(wrapper);
    });
  }

  function getPeopleCheckFilterValue() {
    var filter = getElement("people-check-filter");
    var value = filter && filter.value ? String(filter.value).toUpperCase() : "ALL";
    return value || "ALL";
  }

  function peopleOutcomeMatches(outcome, filter) {
    if (filter === "ALL") return true;
    if (filter === "NA") return outcome === "NA" || outcome === "NOT_APPLICABLE";
    return outcome === filter;
  }

  /** 按 outcome 更新文字 badge；筛选控件不依赖颜色来表达状态。 */
  function renderPeopleCheckFilter() {
    var filter = getElement("people-check-filter");
    if (!filter || typeof filter.querySelectorAll !== "function") return;
    var counts = {ALL: latestPeopleChecks.length, FAIL: 0, WARN: 0, UNKNOWN: 0, PASS: 0, NA: 0};
    latestPeopleChecks.forEach(function countCheck(check) {
      var outcome = normalizeOutcome(check && check.outcome);
      if (outcome === "NOT_APPLICABLE") outcome = "NA";
      if (Object.prototype.hasOwnProperty.call(counts, outcome)) counts[outcome] += 1;
    });
    Array.from(filter.querySelectorAll("button")).forEach(function updateFilterButton(button) {
      var outcome = String(button.dataset && button.dataset.outcome || "ALL").toUpperCase();
      var label = outcome === "ALL" ? "全部" : (outcomeLabels[outcome] || outcome);
      button.textContent = label + " " + (counts[outcome] || 0);
      button.setAttribute("aria-pressed", String(getPeopleCheckFilterValue() === outcome));
    });
  }

  function initializePeopleCheckFilter() {
    var filter = getElement("people-check-filter");
    if (!filter || peopleCheckFilterInitialized) return;
    peopleCheckFilterInitialized = true;
    if (!filter.value) filter.value = "ALL";
    if (typeof filter.querySelectorAll === "function") {
      Array.from(filter.querySelectorAll("button")).forEach(function bindFilterButton(button) {
        button.addEventListener("click", function selectOutcome() {
          filter.value = String(button.dataset && button.dataset.outcome || "ALL").toUpperCase();
          renderPeopleChecks();
        });
      });
    }
    filter.addEventListener("change", renderPeopleChecks);
  }

  function renderPeopleChecks() {
    var container = clearNode(getElement("people-check-list"));
    if (!container) return;
    var filter = getPeopleCheckFilterValue();
    var ordered = latestPeopleChecks.map(function preserveOrder(check, index) {
      return {check: check || {}, index: index};
    }).sort(function sortChecks(left, right) {
      var leftOutcome = normalizeOutcome(left.check.outcome);
      var rightOutcome = normalizeOutcome(right.check.outcome);
      return (outcomeOrder[leftOutcome] - outcomeOrder[rightOutcome]) || (left.index - right.index);
    }).filter(function filterCheck(entry) {
      return peopleOutcomeMatches(normalizeOutcome(entry.check.outcome), filter);
    });
    // 即使当前筛选没有命中，也要先同步按钮计数和 aria-pressed，再展示空态。
    renderPeopleCheckFilter();
    if (!ordered.length) {
      container.appendChild(createElement("li", "issue-item", "暂无规则检查结果。"));
      return;
    }
    ordered.forEach(function renderCheck(entry) {
      var check = entry.check;
      var outcome = normalizeOutcome(check.outcome);
      var item = createElement("li", "people-check-item outcome-" + outcome.toLowerCase());
      item.appendChild(createElement("span", "check-outcome", outcomeLabels[outcome]));
      item.appendChild(createElement("h4", "check-title", displayValue(check.rule_id) + " · " + displayValue(check.title)));
      item.appendChild(createElement("p", "check-actual", "实际：" + displayValue(check.actual)));
      item.appendChild(createElement("p", "check-expected", "期望：" + displayValue(check.expected)));
      var evidenceContainer = createElement("div", "check-evidence");
      renderEvidence(evidenceContainer, check.evidence, latestPeopleLineCount);
      item.appendChild(evidenceContainer);
      container.appendChild(item);
    });
  }

  function renderChecks(data, lineCount) {
    latestPeopleChecks = Array.isArray(data.checks) ? data.checks.slice() : [];
    latestPeopleLineCount = lineCount;
    initializePeopleCheckFilter();
    renderPeopleChecks();
  }

  function setPeopleTabs() {
    var panels = ["overviewPanel", "interfacesPanel", "resultPanel", "checksPanel"];
    if (typeof api.setAvailableTabs === "function") api.setAvailableTabs(panels);
    var timelinePanel = getElement("timelinePanel");
    var timelineTab = getElement("timelineTab");
    if (timelinePanel) timelinePanel.hidden = true;
    if (timelineTab) timelineTab.hidden = true;
    if (typeof api.activateTab === "function") api.activateTab("overviewPanel", false);
  }

  function showPeopleSurfaces() {
    ["people-overview", "people-interfaces", "people-result", "people-checks"].forEach(function showSurface(id) {
      var surface = getElement(id);
      if (surface) surface.hidden = false;
    });
    ["people-overview-empty", "people-interfaces-empty", "people-checks-empty"].forEach(function hideEmpty(id) {
      var empty = getElement(id);
      if (empty) empty.hidden = true;
    });
  }

  function renderPeopleAnalysis(data) {
    data = data && typeof data === "object" ? data : {};
    showPeopleSurfaces();
    renderTaskSummary(data);
    renderVerdict(data);
    renderAiStatus(data);
    renderCoverage(data);
    renderIssueSummary(data);
    renderTimeline(data);
    renderDiagnosis(data);
    renderCost(data);
    var report = getElement("people-search-report");
    var reportText = typeof data.report_markdown === "string" ? data.report_markdown : "";
    if (report) report.textContent = reportText;
    var copyButton = getElement("copy-report-btn");
    var exportButton = getElement("export-report-btn");
    if (copyButton) copyButton.disabled = !reportText;
    if (exportButton) exportButton.disabled = !reportText;
    renderChecks(data, countLogLines(arguments.length > 1 ? arguments[1] : ""));
  }

  /** 日志变化后保留旧结果供核对，但禁止 People 报告复制和导出。 */
  function markPeopleStale() {
    var copyButton = getElement("copy-report-btn");
    var exportButton = getElement("export-report-btn");
    if (copyButton) copyButton.disabled = true;
    if (exportButton) exportButton.disabled = true;
    var status = getElement("people-search-status");
    if (status && latestPeopleChecks.length >= 0) status.textContent = "结果已过期，仅供查看";
  }

  function formatPeopleError(error) {
    var message = typeof error === "string"
      ? error
      : error && error.message ? error.message : "People 分析失败，请稍后重试。";
    var ids = error && Array.isArray(error.detected_task_ids) ? error.detected_task_ids : [];
    if (ids.length) {
      message += "（检测到 task_id：" + ids.map(function formatTaskId(value) {
        return displayValue(value);
      }).join("、") + "）";
    }
    return message;
  }

  /** 清理本适配器拥有的叶节点并隐藏 People surface，保留固定 DOM 结构供下一轮复用。 */
  function clearPeopleSurfaces() {
    ["people-overview", "people-interfaces", "people-result", "people-checks"].forEach(function hideSurface(id) {
      var surface = getElement(id);
      if (surface) surface.hidden = true;
    });
    ["people-verdict-title", "people-task-summary", "people-ai-status", "people-search-status",
      "people-coverage-list", "people-issue-list", "people-timeline", "people-diagnosis-list",
      "people-cost-summary", "people-search-report", "people-check-list"].forEach(function clearLeaf(id) {
      clearNode(getElement(id));
    });
    var verdictPanel = getElement("people-verdict-panel");
    if (verdictPanel) verdictPanel.setAttribute("data-verdict", "INCOMPLETE_EVIDENCE");
    var copyButton = getElement("copy-report-btn");
    var exportButton = getElement("export-report-btn");
    if (copyButton) copyButton.disabled = true;
    if (exportButton) exportButton.disabled = true;
  }

  function renderPeopleError(error) {
    var message = formatPeopleError(error);
    clearPeopleSurfaces();
    var status = getElement("people-search-status");
    if (status) status.textContent = "失败：" + message;
    setPeopleResultHeader("People 分析失败", message);
    if (typeof api.showActionMessage === "function") api.showActionMessage(message, true, true);
  }

  /** 空日志是可解释的业务空态，不应伪装成后端故障或覆盖其他模式结果。 */
  function renderPeopleEmpty(message) {
    clearPeopleSurfaces();
    var empty = getElement("people-overview-empty");
    if (empty) {
      empty.textContent = String(message || "日志内容为空，请先粘贴日志再分析");
      empty.hidden = false;
    }
    var status = getElement("people-search-status");
    if (status) status.textContent = "空日志";
    setPeopleResultHeader("People 等待日志", message);
  }

  /**
   * 通过统一核心请求 People API。
   *
   * 参数说明：context 由 workbench-core 提供，必须含当前 root 和 logText；signal
   * 用于复用核心的取消能力。返回值用 {ok,data} 交给核心判断异步分析是否成功。
   * 错误说明：网络、HTTP 或空 data 都转为纯文本错误，不清空原始日志/过滤结果。
   */
  function analyzePeopleSearch(context) {
    context = context || {};
    var root = context.root || getElement("log-workbench");
    var logText = context.logText === undefined
      ? (getElement("log_text") ? getElement("log_text").value : "")
      : String(context.logText || "");
    clearPeopleSurfaces();
    if (!String(logText).trim()) {
      var emptyMessage = "日志内容为空，请先粘贴日志再分析";
      var emptyError = new Error(emptyMessage);
      emptyError.error_code = "EMPTY_LOG";
      renderPeopleEmpty(emptyMessage);
      return Promise.resolve({ok: false, empty: true, message: emptyMessage, error: emptyError});
    }
    if (!root || !root.dataset || !root.dataset.peopleUrl || typeof api.requestJson !== "function") {
      var endpointMessage = "People 分析地址不可用。";
      renderPeopleError(endpointMessage);
      return Promise.resolve({ok: false, message: endpointMessage});
    }

    setPeopleTabs();
    var status = getElement("people-search-status");
    if (status) status.textContent = "分析中";
    return api.requestJson(root.dataset.peopleUrl, {
      method: "POST",
      body: {log_text: logText},
      signal: context.signal || undefined
    }).then(function handlePeopleResponse(payload) {
      if (typeof context.isCurrent === "function" && !context.isCurrent()) {
        return {ok: false, stale: true};
      }
      var data = payload && payload.data;
      if (!data || typeof data !== "object") throw new Error("People 分析未返回有效结果。");
      renderPeopleAnalysis(data, logText);
      if (typeof api.showActionMessage === "function") api.showActionMessage("分析完成：" + String(data.verdict || ""), false);
      return {ok: true, data: data};
    }).catch(function handlePeopleError(error) {
      if (typeof context.isCurrent === "function" && !context.isCurrent()) {
        return {ok: false, stale: true};
      }
      var message = formatPeopleError(error);
      renderPeopleError(error);
      return {ok: false, message: message, error: error};
    });
  }

  /** 复制和导出只读取已渲染的完整 Markdown 纯文本，不复制页面装饰。 */
  function copyReport() {
    var report = getElement("people-search-report");
    var content = report ? String(report.textContent || "") : "";
    var clipboard = global.navigator && global.navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== "function") {
      if (typeof api.showActionMessage === "function") api.showActionMessage("复制失败，请检查浏览器剪贴板权限。", true);
      return Promise.resolve(false);
    }
    return clipboard.writeText(content).then(function copySucceeded() {
      if (typeof api.showActionMessage === "function") api.showActionMessage("People 报告已复制。", false);
      return true;
    }).catch(function copyFailed() {
      if (typeof api.showActionMessage === "function") api.showActionMessage("复制失败，请检查浏览器剪贴板权限。", true);
      return false;
    });
  }

  function exportReport() {
    var report = getElement("people-search-report");
    var content = report ? String(report.textContent || "") : "";
    if (typeof api.exportLog !== "function") {
      if (typeof api.showActionMessage === "function") api.showActionMessage("导出地址不可用。", true, true);
      return Promise.resolve(null);
    }
    return api.exportLog("analysis_report", content);
  }

  function resetPeopleSearch() {
    clearPeopleSurfaces();
    latestPeopleChecks = [];
    latestPeopleLineCount = 0;
  }

  function initialize() {
    var copyButton = getElement("copy-report-btn");
    var exportButton = getElement("export-report-btn");
    if (copyButton) copyButton.addEventListener("click", copyReport);
    if (exportButton) exportButton.addEventListener("click", exportReport);
  }

  var definition = {
    analyze: analyzePeopleSearch,
    run: analyzePeopleSearch,
    reset: resetPeopleSearch,
    onInputRevision: markPeopleStale
  };

  /* 兼容 Task 1/3 的新旧注册入口；核心会把 people-search 别名解析到 people。 */
  if (typeof api.registerAnalysisMode === "function") {
    api.registerAnalysisMode('people', definition);
  } else if (typeof api.registerMode === "function") {
    api.registerMode('people', definition);
  }
  if (typeof api.getMode !== "function" || !api.getMode("people-search")) {
    if (typeof api.registerMode === "function") api.registerMode("people-search", definition);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})(window, document);
