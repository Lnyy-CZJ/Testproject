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
    if (node) node.textContent = "";
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
      [index + 1, call.provider, call.operation, call.status, business,
        formatCallDetails(call.result_details), call.http_status,
        call.cache_hit ? "是" : "否", cost].forEach(function renderCell(value, cellIndex) {
          var cell = createElement("td", cellIndex === 5 ? "diagnostic-cell" : "", displayValue(value));
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

  function normalizeOutcome(outcome) {
    var value = String(outcome || "UNKNOWN").toUpperCase();
    return Object.prototype.hasOwnProperty.call(outcomeLabels, value) ? value : "UNKNOWN";
  }

  function validEvidenceRange(evidence) {
    if (!evidence || typeof evidence !== "object") return null;
    var start = Number(evidence.line_start);
    var end = Number(evidence.line_end);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start) return null;
    return {start: start, end: end};
  }

  /** Evidence 没有同时给出真实行号时，明确降级，不从 json_path 或 method 猜测位置。 */
  function renderEvidence(container, evidenceList) {
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
      var range = validEvidenceRange(item);
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

  function renderChecks(data) {
    var container = clearNode(getElement("people-check-list"));
    if (!container) return;
    var checks = Array.isArray(data.checks) ? data.checks : [];
    var ordered = checks.map(function preserveOrder(check, index) {
      return {check: check || {}, index: index};
    }).sort(function sortChecks(left, right) {
      var leftOutcome = normalizeOutcome(left.check.outcome);
      var rightOutcome = normalizeOutcome(right.check.outcome);
      return (outcomeOrder[leftOutcome] - outcomeOrder[rightOutcome]) || (left.index - right.index);
    });
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
      renderEvidence(evidenceContainer, check.evidence);
      item.appendChild(evidenceContainer);
      container.appendChild(item);
    });
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
    renderChecks(data);
  }

  function renderPeopleError(message) {
    var status = getElement("people-search-status");
    if (status) status.textContent = "失败";
    if (typeof api.showActionMessage === "function") api.showActionMessage(message, true, true);
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
    if (!String(logText).trim()) {
      var emptyMessage = "日志内容为空，请先粘贴日志再分析";
      renderPeopleError(emptyMessage);
      return Promise.resolve({ok: false, message: emptyMessage});
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
      body: {log_text: context.logText},
      signal: context.signal || undefined
    }).then(function handlePeopleResponse(payload) {
      var data = payload && payload.data;
      if (!data || typeof data !== "object") throw new Error("People 分析未返回有效结果。");
      renderPeopleAnalysis(data);
      if (typeof api.showActionMessage === "function") api.showActionMessage("分析完成：" + String(data.verdict || ""), false);
      return {ok: true, data: data};
    }).catch(function handlePeopleError(error) {
      var message = error && error.message ? error.message : "People 分析失败，请稍后重试。";
      renderPeopleError(message);
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
    ["people-overview", "people-interfaces", "people-result", "people-checks"].forEach(function hideSurface(id) {
      var surface = getElement(id);
      if (surface) surface.hidden = true;
    });
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
    reset: resetPeopleSearch
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
