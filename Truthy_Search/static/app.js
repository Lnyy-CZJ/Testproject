/* 阶段3页面交互：Run 定时刷新、Raw 按需加载、折叠搜索与复制。 */

(() => {
  "use strict";

  const terminalStatuses = new Set([
    "COMPLETED",
    "PARTIAL_FAILED",
    "FAILED",
    "INTERRUPTED",
  ]);

  function updateText(selector, value) {
    const element = document.querySelector(selector);
    if (element) element.textContent = value ?? "—";
  }

  function startRunPolling() {
    const host = document.querySelector("[data-run-status-url]");
    if (!host) return;
    const statusUrl = host.dataset.runStatusUrl;
    let timer = null;

    const refresh = async () => {
      try {
        const response = await fetch(statusUrl, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) return;
        const state = await response.json();
        updateText("[data-run-status]", state.status);
        updateText("[data-total]", state.total_queries);
        updateText("[data-completed]", state.completed_queries);
        updateText("[data-success]", state.success_queries);
        updateText("[data-failed]", state.failed_queries);
        updateText("[data-current-query]", state.current_query_id || "—");
        updateText("[data-current-stage]", state.current_stage || "—");
        updateText("[data-progress-message]", state.message || "—");
        if (terminalStatuses.has(state.status)) {
          window.clearInterval(timer);
          window.location.reload();
        }
      } catch (_) {
        // 暂时网络错误不改变数据库状态；下一次定时刷新会继续尝试。
      }
    };

    refresh();
    timer = window.setInterval(refresh, 2000);
  }

  const rawDialog = document.querySelector("#raw-dialog");
  const rawTree = document.querySelector("#raw-tree");
  const rawCode = document.querySelector("#raw-code");
  const rawLoading = document.querySelector("#raw-loading");
  const rawSearch = document.querySelector("#raw-search");
  const rawSearchResult = document.querySelector("#raw-search-result");
  let loadedRaw = null;
  let rawView = "json";

  function stringifyValue(value) {
    if (typeof value === "string") return value;
    return JSON.stringify(value);
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = value;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
  }

  function actionButton(label, value) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => copyText(value));
    return button;
  }

  function renderLeaf(key, value, path) {
    const row = document.createElement("div");
    row.className = "json-leaf";
    row.dataset.searchText = `${path} ${stringifyValue(value)}`.toLowerCase();

    const pathNode = document.createElement("span");
    pathNode.className = "json-path";
    pathNode.textContent = key;

    const valueNode = document.createElement("span");
    valueNode.className = "json-value";
    valueNode.textContent = stringifyValue(value);

    const actions = document.createElement("span");
    actions.className = "json-actions";
    actions.append(
      actionButton("路径", path),
      actionButton("值", stringifyValue(value)),
    );
    row.append(pathNode, valueNode, actions);
    return row;
  }

  function renderJsonNode(value, path = "root", label = "root", depth = 0) {
    if (value === null || typeof value !== "object") {
      return renderLeaf(label, value, path);
    }
    const details = document.createElement("details");
    details.open = depth < 2;
    details.dataset.searchText = path.toLowerCase();
    const summary = document.createElement("summary");
    const size = Array.isArray(value)
      ? `${value.length} items`
      : `${Object.keys(value).length} fields`;
    summary.textContent = `${label} · ${size}`;
    details.appendChild(summary);
    Object.entries(value).forEach(([key, child]) => {
      const childPath = Array.isArray(value)
        ? `${path}[${key}]`
        : `${path}.${key}`;
      details.appendChild(renderJsonNode(child, childPath, key, depth + 1));
    });
    return details;
  }

  /**
   * 以真实 JSON 缩进格式渲染 Raw，并仅用文本节点插入搜索高亮，避免响应内容被当作 HTML。
   *
   * 参数说明:
   *   term: 用户输入的字段名或值关键词；空值时显示完整格式化 JSON。
   */
  function renderRawCode(term = "") {
    if (!rawCode || loadedRaw === null) return;
    const text = JSON.stringify(loadedRaw, null, 2);
    const normalizedTerm = term.trim().toLowerCase();
    const normalizedText = text.toLowerCase();
    rawCode.replaceChildren();
    let cursor = 0;
    let matchCount = 0;
    let index = normalizedTerm ? normalizedText.indexOf(normalizedTerm) : -1;
    while (index !== -1) {
      rawCode.append(document.createTextNode(text.slice(cursor, index)));
      const mark = document.createElement("mark");
      mark.textContent = text.slice(index, index + normalizedTerm.length);
      rawCode.append(mark);
      cursor = index + normalizedTerm.length;
      matchCount += 1;
      index = normalizedText.indexOf(normalizedTerm, cursor);
    }
    rawCode.append(document.createTextNode(text.slice(cursor)));
    if (rawSearchResult) {
      rawSearchResult.hidden = !normalizedTerm;
      rawSearchResult.textContent = normalizedTerm
        ? `格式化 JSON 中找到 ${matchCount} 处匹配`
        : "";
    }
  }

  /** 切换 Raw 的 JSON 代码视图与结构树视图，默认优先展示可复制的标准 JSON。 */
  function setRawView(view) {
    rawView = view === "tree" ? "tree" : "json";
    if (rawCode) rawCode.hidden = rawView !== "json";
    if (rawTree) rawTree.hidden = rawView !== "tree";
    document.querySelectorAll("[data-raw-view]").forEach((button) => {
      button.classList.toggle("active", button.dataset.rawView === rawView);
    });
    if (loadedRaw !== null) {
      if (rawView === "json") renderRawCode(rawSearch?.value || "");
      else filterRawTree(rawSearch?.value || "");
    }
  }

  function filterRawTree(term) {
    if (!rawTree) return;
    const normalized = term.trim().toLowerCase();
    rawTree.querySelectorAll(".json-leaf").forEach((leaf) => {
      leaf.hidden = Boolean(
        normalized && !leaf.dataset.searchText.includes(normalized),
      );
    });
    if (normalized) {
      rawTree.querySelectorAll("details").forEach((details) => {
        const hasVisibleLeaf = [...details.querySelectorAll(".json-leaf")].some(
          (leaf) => !leaf.hidden,
        );
        details.hidden = !hasVisibleLeaf;
        if (hasVisibleLeaf) details.open = true;
      });
    } else {
      rawTree.querySelectorAll("details").forEach((details) => {
        details.hidden = false;
      });
    }
  }

  async function openRaw(rawId, label) {
    if (!rawDialog || !rawTree || !rawLoading) return;
    rawTree.replaceChildren();
    rawLoading.hidden = false;
    loadedRaw = null;
    rawSearch.value = "";
    if (rawSearchResult) rawSearchResult.hidden = true;
    updateText("#raw-dialog-title", label || "Raw JSON");
    rawDialog.showModal();
    try {
      const response = await fetch(`/api/raw/${encodeURIComponent(rawId)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      loadedRaw = await response.json();
      rawTree.appendChild(renderJsonNode(loadedRaw));
      setRawView("json");
    } catch (error) {
      const message = document.createElement("p");
      message.className = "error-list";
      message.textContent = `Raw 加载失败：${error.message}`;
      rawTree.appendChild(message);
    } finally {
      rawLoading.hidden = true;
    }
  }

  document.querySelectorAll("[data-raw-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openRaw(button.dataset.rawId, button.dataset.rawLabel);
    });
  });

  document.querySelector("[data-close-dialog]")?.addEventListener("click", () => {
    rawDialog?.close();
  });

  rawSearch?.addEventListener("input", () => {
    if (rawView === "json") renderRawCode(rawSearch.value);
    else filterRawTree(rawSearch.value);
  });

  document.querySelectorAll("[data-raw-view]").forEach((button) => {
    button.addEventListener("click", () => setRawView(button.dataset.rawView));
  });

  document.querySelector("[data-copy-json]")?.addEventListener("click", () => {
    if (loadedRaw !== null) {
      copyText(JSON.stringify(loadedRaw, null, 2));
    }
  });

  /**
   * 初始化单人基准工作台。
   *
   * 功能说明:
   *   支持字段搜索、批量勾选和未保存状态提示；只修改字段可用性，
   *   不改变导入的基准值。每个人物卡片独立维护，避免跨人物误操作。
   *
   * 参数说明:
   *   workbench: 当前人物的工作台根节点。
   *
   * 返回值:
   *   无；交互状态直接反映到当前表单。
   */
  function initializeBaselineWorkbench(workbench) {
    const form = workbench.querySelector("form");
    const search = workbench.querySelector("[data-baseline-field-search]");
    const fields = [...workbench.querySelectorAll("[data-baseline-field]")];
    const groups = [...workbench.querySelectorAll(".baseline-field-group")];
    const checkboxes = fields
      .map((field) => field.querySelector('input[name="available_fields"]'))
      .filter(Boolean);
    const selectedCount = workbench.querySelector(
      "[data-baseline-selected-count]",
    );
    const saveState = workbench.querySelector("[data-baseline-save-state]");
    const noMatch = workbench.querySelector("[data-baseline-no-match]");

    const refreshSelectedCount = () => {
      const count = checkboxes.filter((checkbox) => checkbox.checked).length;
      if (selectedCount) selectedCount.textContent = String(count);
    };

    const markChanged = () => {
      refreshSelectedCount();
      if (saveState) {
        saveState.textContent = "有未保存修改";
        saveState.classList.add("changed");
      }
    };

    const setChecked = (predicate) => {
      checkboxes.forEach((checkbox, index) => {
        checkbox.checked = predicate(fields[index], checkbox);
      });
      markChanged();
    };

    search?.addEventListener("input", () => {
      const term = search.value.trim().toLowerCase();
      let visibleCount = 0;
      fields.forEach((field) => {
        const visible = !term || field.dataset.fieldSearch.includes(term);
        field.hidden = !visible;
        if (visible) visibleCount += 1;
      });
      groups.forEach((group) => {
        group.hidden = ![...group.querySelectorAll("[data-baseline-field]")].some(
          (field) => !field.hidden,
        );
      });
      if (noMatch) noMatch.hidden = visibleCount !== 0;
    });

    workbench
      .querySelector("[data-baseline-select-valued]")
      ?.addEventListener("click", () => {
        setChecked((field) => field.dataset.hasValue === "true");
      });
    workbench
      .querySelector("[data-baseline-select-all]")
      ?.addEventListener("click", () => setChecked(() => true));
    workbench
      .querySelector("[data-baseline-clear]")
      ?.addEventListener("click", () => setChecked(() => false));
    checkboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", markChanged);
    });
    form?.addEventListener("submit", () => {
      if (saveState) saveState.textContent = "正在保存…";
    });
    refreshSelectedCount();
  }

  document
    .querySelectorAll("[data-baseline-workbench]")
    .forEach(initializeBaselineWorkbench);

  /**
   * 初始化历史 Query 人物关联工作区。
   *
   * 功能说明:
   *   “采用唯一建议”只修改当前页面下拉框，仍需测试人员点击保存；
   *   同名多匹配和无匹配行保持原值，避免把姓名建议当成自动确认。
   *
   * 参数说明:
   *   workbench: 人物关联表单根节点。
   *
   * 返回值:
   *   无；只更新浏览器表单状态，不直接请求后端。
   */
  function initializePersonLinkWorkbench(workbench) {
    workbench
      .querySelector("[data-adopt-unique]")
      ?.addEventListener("click", () => {
        workbench.querySelectorAll("[data-person-link-row]").forEach((row) => {
          const personId = row.dataset.uniquePersonId;
          const select = row.querySelector('select[name^="person_id__"]');
          if (personId && select && !select.disabled) {
            select.value = personId;
          }
        });
      });
  }

  document
    .querySelectorAll("[data-person-link-workbench]")
    .forEach(initializePersonLinkWorkbench);

  /**
   * 字段配置矩阵的模块级提取开关。
   *
   * 仅修改当前页面中同一模块的「提取」复选框，提交后仍由服务端发布
   * 新的不可变 Schema；不会修改历史配置或触发任何检索请求。
   */
  document.querySelectorAll("[data-toggle-module]").forEach((button) => {
    button.addEventListener("click", () => {
      const module = button.dataset.toggleModule;
      const fields = [...document.querySelectorAll(
        `input[name="enabled_fields"][data-module="${module}"]`,
      )];
      const shouldEnable = fields.some((field) => !field.checked);
      fields.forEach((field) => {
        field.checked = shouldEnable;
      });
    });
  });

  /**
   * 初始化核心指标计算详情抽屉。
   *
   * 功能说明：指标结果和贡献明细只读取不可变报告快照；历史 v5 快照没有
   * breakdown 时仍展示用途、公式、分子和分母，不在浏览器重新计算指标。
   *
   * 返回值：无；页面不含 v5 指标卡或浏览器不支持 dialog 时静默跳过。
   */
  function initializeReportMetricDialog() {
    const dialog = document.querySelector("[data-report-metric-dialog]");
    const snapshotNode = document.querySelector("#report-v5-metric-snapshot");
    const cards = document.querySelectorAll("[data-report-metric]");
    if (!dialog || !snapshotNode || !cards.length || !dialog.showModal) return;

    let metrics = {};
    try {
      metrics = JSON.parse(snapshotNode.textContent || "{}");
    } catch (_) {
      metrics = {};
    }
    const title = dialog.querySelector("[data-metric-dialog-title]");
    const purpose = dialog.querySelector("[data-metric-dialog-purpose]");
    const formula = dialog.querySelector("[data-metric-dialog-formula]");
    const result = dialog.querySelector("[data-metric-dialog-result]");
    const expression = dialog.querySelector("[data-metric-dialog-expression]");
    const auxiliary = dialog.querySelector("[data-metric-dialog-auxiliary]");
    const status = dialog.querySelector("[data-metric-dialog-status]");
    const populationGroups = dialog.querySelector("[data-metric-dialog-populations]");
    const breakdownBody = dialog.querySelector("[data-metric-dialog-breakdown]");
    const close = dialog.querySelector("[data-metric-dialog-close]");
    const percent = (value, digits = 4) => (
      value === null || value === undefined
        ? "—"
        : `${(Number(value) * 100).toFixed(digits)}%`
    );
    const scalar = (value) => {
      const number = Number(value);
      return Number.isFinite(number)
        ? number.toFixed(6).replace(/\.?0+$/, "")
        : "0";
    };
    cards.forEach((card) => card.addEventListener("click", () => {
      const metric = metrics[card.dataset.reportMetric] || {};
      const groups = Array.isArray(metric.population_groups)
        ? metric.population_groups
        : [];
      const formalGroup = groups.find((group) => group.formal);
      title.textContent = metric.label || card.dataset.metricLabel || "指标计算详情";
      purpose.textContent = metric.purpose || card.dataset.metricPurpose || "";
      formula.textContent = metric.formula || card.dataset.metricFormula || "历史快照未保存公式";
      result.textContent = formalGroup
        ? `${formalGroup.label} ${formalGroup.candidate_count} 人 · ${scalar(formalGroup.numerator)} ÷ ${formalGroup.denominator ?? 0} = ${percent(formalGroup.value)}`
        : `${scalar(metric.numerator)} ÷ ${metric.denominator ?? 0} = ${percent(metric.value)}`;
      expression.textContent = metric.calculation_expression
        ? `展开：${metric.calculation_expression}`
        : "";
      const auxiliaryMetric = metric.auxiliary_calculation;
      auxiliary.textContent = !groups.length && auxiliaryMetric?.denominator
        ? `${auxiliaryMetric.label}：${scalar(auxiliaryMetric.numerator)} ÷ ${auxiliaryMetric.denominator} = ${percent(auxiliaryMetric.value)}`
        : "";
      status.textContent = [
        `状态：${metric.status || "UNKNOWN"}`,
        ...(metric.reasons || []),
      ].join(" · ");
      if (populationGroups) {
        populationGroups.replaceChildren();
        populationGroups.hidden = !groups.length;
        groups.forEach((group) => {
          const item = document.createElement("article");
          const heading = document.createElement("strong");
          heading.textContent = `${group.label || "未命名分组"}${group.formal ? " · 正式整体指标" : " · 辅助分析"}`;
          const description = document.createElement("small");
          description.textContent = group.description || "";
          const calculation = document.createElement("span");
          calculation.textContent = `${group.candidate_count ?? 0} 人 · ${group.numerator_label || "分子"} ${scalar(group.numerator)} ÷ ${group.denominator_label || "分母"} ${group.denominator ?? 0} = ${percent(group.value)}`;
          item.append(heading, description, calculation);
          const groupAuxiliary = group.auxiliary_calculation;
          if (groupAuxiliary?.denominator) {
            const auxiliaryLine = document.createElement("span");
            auxiliaryLine.className = "report-v5-population-auxiliary";
            auxiliaryLine.textContent = `${groupAuxiliary.label}：${groupAuxiliary.numerator_label || "字段最终得分之和"} ${scalar(groupAuxiliary.numerator)} ÷ ${groupAuxiliary.denominator_label || "字段数"} ${groupAuxiliary.denominator} = ${percent(groupAuxiliary.value)}`;
            item.append(auxiliaryLine);
          }
          populationGroups.append(item);
        });
      }
      breakdownBody.replaceChildren();
      const breakdown = Array.isArray(metric.breakdown) ? metric.breakdown : [];
      if (!breakdown.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "历史快照仅保留汇总结果，暂无参与计算明细。";
        row.append(cell);
        breakdownBody.append(row);
      } else {
        breakdown.forEach((item) => {
          const row = document.createElement("tr");
          const itemNumerator = item.numerator ?? item.value ?? 0;
          const itemDenominator = item.denominator ?? 1;
          const fieldDetails = (item.field_components || [])
            .map((field) => `${field.field_key}=${scalar(field.score)}`)
            .join("；");
          [
            item.query_id || "—",
            item.candidate_id || `返回 ${item.candidate_count ?? 0} 位候选人`,
            item.result || "—",
            `${scalar(itemNumerator)} ÷ ${itemDenominator}`,
            [percent(item.value), fieldDetails].filter(Boolean).join("\n"),
          ].forEach((value) => {
            const cell = document.createElement("td");
            cell.textContent = value;
            if (String(value).includes("\n")) cell.className = "report-v5-calculation-cell";
            row.append(cell);
          });
          breakdownBody.append(row);
        });
      }
      dialog.showModal();
    }));
    close?.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  }

  /**
   * 初始化 ReportModel v5 的 Query 工作台。
   *
   * 功能说明：完整 Query/Candidate 快照只在浏览器内存保留一份；首次和每次
   * “加载更多”只创建一段 DOM。搜索、阶段和身份筛选始终作用于完整快照，
   * 不请求新的报告 API，也不会重新计算任何指标。
   *
   * 返回值：无；无法解析历史或损坏快照时显示可读错误提示。
   */
  function initializeReportExplorer() {
    const host = document.querySelector("[data-report-explorer]");
    const snapshotNode = document.querySelector("#report-v5-snapshot");
    if (!host || !snapshotNode) return;

    let snapshot;
    try {
      snapshot = JSON.parse(snapshotNode.textContent || "{}");
    } catch (_) {
      host.querySelector("[data-report-load-state]").textContent =
        "报告快照无法解析，无法加载 Query 明细。";
      return;
    }
    const allItems = Array.isArray(snapshot.items) ? snapshot.items : [];
    const initialQueryCount = Number(snapshot.initial_query_count) || 5;
    const loadMoreQueryCount = Number(snapshot.load_more_query_count) || 10;
    const search = host.querySelector("[data-report-search]");
    const stage = host.querySelector("[data-report-stage]");
    const identity = host.querySelector("[data-report-identity]");
    const state = host.querySelector("[data-report-load-state]");
    const list = host.querySelector("[data-report-query-list]");
    const loadMore = host.querySelector("[data-report-load-more]");
    let renderedCount = 0;

    const stringify = (value) => {
      if (value === null || value === undefined || value === "") return "—";
      return typeof value === "string" ? value : JSON.stringify(value, null, 2);
    };
    const metricText = (metric) => {
      if (!metric || metric.value === null || metric.value === undefined) {
        return metric?.status === "NOT_APPLICABLE" ? "不适用" : "—";
      }
      return `${(Number(metric.value) * 100).toFixed(2)}%`;
    };
    const make = (tag, className, text) => {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    };
    const searchable = (item) => {
      const candidates = item.candidate_run?.candidates || [];
      return [
        item.person_id,
        item.display_name,
        item.candidate_run?.query?.query_id,
        ...candidates.flatMap((candidate) => [
          candidate.candidate_id,
          candidate.display_name,
          candidate.identity?.judgement,
        ]),
      ].join(" ").toLowerCase();
    };
    const matchingCandidates = (item, identityValue) => {
      const candidates = item.candidate_run?.candidates || [];
      return identityValue
        ? candidates.filter((candidate) => candidate.identity?.judgement === identityValue)
        : candidates;
    };
    const filteredItems = () => {
      const term = (search?.value || "").trim().toLowerCase();
      const stageValue = stage?.value || "";
      const identityValue = identity?.value || "";
      return allItems.filter((item) => {
        if (stageValue && item.query_stage !== stageValue) return false;
        if (identityValue && matchingCandidates(item, identityValue).length === 0) return false;
        return !term || searchable(item).includes(term);
      });
    };
    const renderCandidate = (candidate) => {
      const details = make("details", "report-v5-candidate");
      const summary = make("summary");
      const heading = make("span", "report-v5-candidate-title");
      heading.textContent = `#${candidate.candidate_rank ?? "—"} · ${candidate.display_name || candidate.candidate_id || "未命名候选人"}`;
      const badges = make("span", "report-v5-badges");
      badges.append(
        make("span", `report-v5-badge is-${String(candidate.identity?.judgement || "UNKNOWN").toLowerCase()}`, candidate.identity?.judgement || "UNCLASSIFIED"),
        make("span", "report-v5-rank", `score ${candidate.rank_score ?? "—"}`),
      );
      summary.append(heading, badges);
      details.append(summary);

      const body = make("div", "report-v5-candidate-body");
      const metrics = make("div", "report-v5-candidate-metrics");
      [
        ["命中信息准确度", candidate.metrics?.matched_accuracy],
        ["命中资料完整度", candidate.metrics?.matched_completeness],
        ["非命中资料完整度", candidate.metrics?.nonmatched_data_completeness],
        ["非命中候选人资料相似度", candidate.metrics?.nonmatched_baseline_overlap],
      ].forEach(([label, metric]) => {
        const item = make("div");
        item.append(make("span", "", label), make("strong", "", metricText(metric)));
        if (metric?.reason_codes?.length) item.append(make("small", "", metric.reason_codes.join(", ")));
        metrics.append(item);
      });
      body.append(metrics);
      const identityText = [
        candidate.identity?.reason,
        candidate.detail_error,
        candidate.confidence && `Confidence: ${candidate.confidence}`,
      ].filter(Boolean).join(" · ");
      if (identityText) body.append(make("p", "inline-note", identityText));

      const modules = candidate.modules || {};
      const moduleDetails = make("details", "report-v5-drilldown");
      moduleDetails.append(make("summary", "", "模块摘要"));
      const moduleGrid = make("div", "report-v5-module-grid");
      Object.values(modules).forEach((module) => {
        const card = make("div", "report-v5-module-card");
        card.append(
          make("strong", "", module.module),
          make("span", "", module.status || (module.has_real_data ? "有数据" : "无数据")),
          make("small", "", `有值 ${module.returned_field_count}/${module.display_field_count} · 完整度 ${metricText(module.completeness)} · 准确度 ${metricText(module.accuracy)}`),
        );
        moduleGrid.append(card);
      });
      moduleDetails.append(moduleGrid);
      body.append(moduleDetails);

      const fields = candidate.field_comparisons || [];
      if (fields.length) {
        const fieldDetails = make("details", "report-v5-drilldown");
        fieldDetails.append(make("summary", "", `字段比较 · ${fields.length}`));
        const wrap = make("div", "table-wrap");
        const table = make("table");
        const head = make("thead");
        const headerRow = make("tr");
        ["字段", "基准人物值", "检索候选值", "结果", "资料完整 / 基准覆盖 / 准确"].forEach((label) => headerRow.append(make("th", "", label)));
        head.append(headerRow);
        const tableBody = make("tbody");
        fields.forEach((field) => {
          const row = make("tr");
          const name = make("td");
          name.append(make("strong", "", field.display_name || field.field_key), make("small", "mono", field.field_key));
          const baseline = make("td", "report-v5-value", stringify(field.baseline_value));
          const candidateValue = make("td", "report-v5-value", stringify(field.candidate_value));
          const result = make("td", "", field.comparison_status || (field.baseline_available ? "未比较" : "基准无值"));
          const score = make("td", "", [field.data_completeness_score, field.baseline_coverage_score, field.accuracy_score].filter((value) => value !== null && value !== undefined).join(" / ") || "—");
          row.append(name, baseline, candidateValue, result, score);
          tableBody.append(row);
        });
        table.append(head, tableBody);
        wrap.append(table);
        fieldDetails.append(wrap);
        body.append(fieldDetails);
      }

      const links = make("p", "report-v5-links");
      if (candidate.candidate_pk) {
        const link = make("a", "", "查看候选人详情与 Raw");
        link.href = `/candidates/${encodeURIComponent(candidate.candidate_pk)}?process_id=${encodeURIComponent(host.dataset.processId || "")}`;
        links.append(link);
      }
      if (candidate.references?.raw_ids?.length) links.append(make("span", "", ` · Raw 引用 ${candidate.references.raw_ids.length} 条`));
      body.append(links);
      details.append(body);
      return details;
    };
    const renderQuery = (item) => {
      const query = item.candidate_run?.query || item.baseline_run?.query || {};
      const card = make("details", "report-v5-query-card");
      const summary = make("summary", "report-v5-query-summary");
      const title = make("div", "report-v5-query-title");
      title.append(make("h3", "", item.display_name || item.person_id || query.query_id || "未命名 Query"));
      const tags = make("div", "report-v5-badges");
      tags.append(make("span", "report-v5-badge", item.query_stage || "UNSPECIFIED"));
      if (item.change_category) tags.append(make("span", "report-v5-badge", item.change_category));
      title.append(tags);
      const meta = make("p", "report-v5-query-meta", `${query.query_id || "—"} · ${query.candidate_count ?? 0} 位候选人 · ${query.result_status || query.query_status || "—"}`);
      summary.append(title, meta);
      card.append(summary);
      let candidatesRendered = false;
      card.addEventListener("toggle", () => {
        if (!card.open || candidatesRendered) return;
        const body = make("div", "report-v5-query-body");
        const candidates = matchingCandidates(item, identity?.value || "");
        if (candidates.length) {
          candidates.forEach((candidate) => body.append(renderCandidate(candidate)));
        } else {
          body.append(make("p", "inline-note", "当前筛选条件下没有候选人。"));
        }
        card.append(body);
        candidatesRendered = true;
      });
      return card;
    };
    const render = (reset = false) => {
      const items = filteredItems();
      if (reset) {
        renderedCount = 0;
        list.replaceChildren();
      }
      const chunkSize = reset ? initialQueryCount : loadMoreQueryCount;
      const nextItems = items.slice(renderedCount, renderedCount + chunkSize);
      nextItems.forEach((item) => list.append(renderQuery(item)));
      renderedCount += nextItems.length;
      state.textContent = `已展示 ${renderedCount} / ${items.length} 个 Query（快照共 ${allItems.length} 个）`;
      loadMore.hidden = renderedCount >= items.length;
    };
    [search, stage, identity].forEach((input) => input?.addEventListener("input", () => render(true)));
    stage?.addEventListener("change", () => render(true));
    identity?.addEventListener("change", () => render(true));
    loadMore?.addEventListener("click", () => render(false));
    render(true);
  }

  startRunPolling();
  initializeReportMetricDialog();
  initializeReportExplorer();
})();
