/**
 * 单日志分析工作台的无依赖共享核心。
 *
 * 职责：
 * 1. 暴露稳定的 ``window.LogWorkbench`` 命名空间和模式注册接口；
 * 2. 将通用模式路由到 Flask 原生表单，将 People/Dating 路由到已注册适配器；
 * 3. 维护日志 textarea、搜索、原始/过滤视图、stale 和真实行号定位状态；
 * 4. 初始化可访问标签页与支持键盘的双栏 resizer。
 *
 * 核心只写固定 DOM 节点的纯文本和值，不把日志内容拆成逐行节点。这样即使日志
 * 很大，编辑、搜索和定位也都保持在 textarea 的原生字符串模型中。
 */
(function bootstrapLogWorkbench(global, document) {
  "use strict";

  var namespace = global.LogWorkbench || {};
  var modes = namespace.modes || Object.create(null);
  var state = namespace.state || {};
  var modeAliases = {
    filter: "general",
    "people-search": "people"
  };
  var analysisInFlight = null;
  // requestSubmit 会同步触发表单 submit 事件；用短生命周期标记区分统一入口
  // 自己发起的那一次提交与用户在 submitting 状态下的重复提交。
  var nativeSubmitInProgress = false;
  var actionMessageTimer = null;
  var searchTimer = null;
  var searchMatches = [];
  var currentSearchIndex = -1;
  var searchQuery = "";
  var searchSource = null;
  var searchSourceText = "";

  state.activeMode = state.activeMode || "general";
  state.activeTab = state.activeTab || "overview";
  state.activeLogView = state.activeLogView || "raw";
  state.phase = state.phase || "idle";
  state.dirty = Boolean(state.dirty);
  state.inputRevision = Number(state.inputRevision) || 0;
  state.lastFocusedElement = state.lastFocusedElement || null;

  function getElement(id) {
    return document.getElementById(id);
  }

  function canonicalModeName(name) {
    var normalizedName = String(name || "").trim();
    return modeAliases[normalizedName] || normalizedName;
  }

  /**
   * 注册一个分析模式。
   *
   * @param {string} name select option 使用的稳定模式名。
   * @param {{nativeSubmit?: boolean, run?: Function, analyze?: Function}} definition
   *   原生表单模式声明 ``nativeSubmit``；异步业务模式提供 ``run`` 或 ``analyze``。
   * @returns {object} 已保存的模式定义。
   * @throws {TypeError} 模式名为空或定义没有可执行行为时抛出。
   *
   * ``people-search`` 是旧页面的注册名，而新壳层使用 ``people``。两者在这里
   * 指向同一对象，避免为 People/Dating 适配器改变既有接口契约。
   */
  function registerMode(name, definition) {
    var normalizedName = String(name || "").trim();
    if (!normalizedName) {
      throw new TypeError("分析模式名称不能为空");
    }
    if (!definition || (
      !definition.nativeSubmit &&
      typeof definition.run !== "function" &&
      typeof definition.analyze !== "function"
    )) {
      throw new TypeError("分析模式必须声明原生提交、run 或 analyze 函数");
    }
    modes[normalizedName] = definition;
    modes[canonicalModeName(normalizedName)] = definition;
    return definition;
  }

  /** 以新旧名称兼容地读取模式；未知名称交由调用方给出用户反馈。 */
  function getMode(name) {
    return modes[String(name || "").trim()] ||
      modes[canonicalModeName(name)] || null;
  }

  /** 注册一个由核心分发的异步适配器，接口与旧 ``registerMode`` 并存。 */
  function registerAnalysisMode(name, adapter) {
    var definition = typeof adapter === "function" ? {analyze: adapter} : adapter;
    return registerMode(name, definition);
  }

  /**
   * 在全局 Toast 中写入纯文本提示。
   * 使用 ``textContent`` 避免异常或服务端文案被解释为 HTML。
   *
   * @param {string} message 用户可见的提示内容。
   */
  function showToast(message) {
    var toast = getElement("workbench-toast");
    if (!toast) return;
    toast.textContent = String(message || "");
    toast.hidden = false;
  }

  function clearTimer(timer) {
    if (timer !== null && timer !== undefined && typeof clearTimeout === "function") {
      clearTimeout(timer);
    }
  }

  function schedule(callback, delay) {
    if (typeof setTimeout !== "function") return null;
    var timer = setTimeout(callback, delay);
    // Node 沙箱中的 Timeout 若不解除引用会让行为测试无意义地等待 3 秒；浏览器
    // 的数字 timer 没有该方法，因此这里仅在可用时调用，不改变浏览器语义。
    if (timer && typeof timer.unref === "function") timer.unref();
    return timer;
  }

  /**
   * 展示统一操作消息。
   *
   * @param {string} message 纯文本消息。
   * @param {boolean} isError 是否使用错误样式。
   * @param {boolean} persistent 是否保持显示，适用于需要用户处理的错误。
   */
  function showActionMessage(message, isError, persistent) {
    var messageElement = getElement("action-message");
    if (!messageElement) return;
    clearTimer(actionMessageTimer);
    actionMessageTimer = null;
    messageElement.textContent = String(message || "");
    if (messageElement.classList) {
      messageElement.classList.toggle("error", Boolean(isError));
      messageElement.classList.toggle("success", !isError);
    }
    messageElement.hidden = false;
    if (!persistent) {
      actionMessageTimer = schedule(function hideActionMessage() {
        messageElement.hidden = true;
      }, 3000);
    }
  }

  /** 将异常转为可操作的持久错误提示，并保持当前日志与结果不变。 */
  function showPersistentError(error) {
    var message = error && error.message ? error.message : "分析失败，请稍后重试。";
    showActionMessage(message, true, true);
    showToast(message);
  }

  /** 读取同源 CSRF Cookie，仅用于写请求 Header；不保存任何 UI 状态。 */
  function readCookie(name) {
    var prefix = String(name || "") + "=";
    var cookieText = document["cookie"] || "";
    var item = cookieText.split(";").map(function trimCookie(value) {
      return value.trim();
    }).find(function findCookie(value) {
      return value.indexOf(prefix) === 0;
    });
    if (!item) return "";
    try {
      return decodeURIComponent(item.slice(prefix.length));
    } catch (error) {
      return item.slice(prefix.length);
    }
  }

  /**
   * 发起 JSON 请求并统一解析服务端错误。
   *
   * @param {string} url 由模板 data 属性生成的同源 URL。
   * @param {object} options fetch 选项；object body 会自动 JSON 编码。
   * @returns {Promise<object>} 服务端 JSON payload。
   * @throws {Error} URL 缺失、响应不是 2xx 或 payload 无法解析时抛出。
   */
  function requestJson(url, options) {
    if (!url || typeof global.fetch !== "function") {
      return Promise.reject(new Error("请求地址不可用。"));
    }
    var requestOptions = options || {};
    var headers = Object.assign({}, requestOptions.headers || {});
    if (!headers["X-CSRF-Token"]) headers["X-CSRF-Token"] = readCookie("tp_csrf");
    var body = requestOptions.body;
    if (body !== undefined && body !== null && typeof body !== "string") {
      body = JSON.stringify(body);
      if (!headers["Content-Type"]) headers["Content-Type"] = "application/json";
    }
    var fetchOptions = {
      method: requestOptions.method || "GET",
      headers: headers
    };
    if (body !== undefined) fetchOptions.body = body;
    if (requestOptions.signal) fetchOptions.signal = requestOptions.signal;

    return global.fetch(url, fetchOptions).then(function parseResponse(response) {
      return response.text().then(function parsePayload(rawText) {
        var payload = {};
        if (rawText) {
          try {
            payload = JSON.parse(rawText);
          } catch (error) {
            payload = {message: rawText};
          }
        }
        if (!response.ok) {
          throw new Error(payload.message || "请求失败，请稍后重试。");
        }
        return payload;
      });
    });
  }

  /** 返回按真实换行符计算的每一行起始 UTF-16 偏移。 */
  function lineStartsFor(text) {
    var starts = [0];
    var index = 0;
    while (index < text.length) {
      if (text.charAt(index) === "\r") {
        if (text.charAt(index + 1) === "\n") index += 1;
        starts.push(index + 1);
      } else if (text.charAt(index) === "\n") {
        starts.push(index + 1);
      }
      index += 1;
    }
    return starts;
  }

  function lineCountFor(text, starts) {
    return text ? (starts || lineStartsFor(text)).length : 0;
  }

  /** 计算 UTF-8 字节数，避免依赖 TextEncoder，兼容旧桌面浏览器和测试沙箱。 */
  function utf8ByteLength(text) {
    var bytes = 0;
    var index = 0;
    while (index < text.length) {
      var codePoint = text.codePointAt(index);
      if (codePoint <= 0x7f) bytes += 1;
      else if (codePoint <= 0x7ff) bytes += 2;
      else if (codePoint <= 0xffff) bytes += 3;
      else {
        bytes += 4;
        index += 1;
      }
      index += 1;
    }
    return bytes;
  }

  /** 更新固定元数据节点；不会触碰结果 textarea，确保编辑时旧结果仍可核对。 */
  function updateLogMetadata(value) {
    var textarea = getElement("log_text");
    var text = value === undefined ? (textarea ? String(textarea.value || "") : "") : String(value);
    var starts = lineStartsFor(text);
    var lineCount = lineCountFor(text, starts);
    var lineElement = getElement("log-line-count");
    var byteElement = getElement("log-byte-count");
    if (lineElement) lineElement.textContent = lineCount + " 行";
    if (byteElement) byteElement.textContent = utf8ByteLength(text) + " B";
    return {text: text, lineCount: lineCount, byteCount: utf8ByteLength(text)};
  }

  /** 标记分析结果可能过期；旧结果保留用于核对，但禁止继续导出。 */
  function markAnalysisStale(message) {
    var stale = getElement("analysis-stale");
    var exportButton = getElement("export-filtered-result-btn");
    var text = message || "日志已修改，过滤结果可能已过期，请重新分析。";
    state.dirty = true;
    if (stale) {
      stale.textContent = text;
      stale.hidden = false;
    }
    if (exportButton) exportButton.disabled = true;
  }

  /** 分析完成后清除 stale，并按结果是否为空恢复过滤结果导出。 */
  function markAnalysisFresh() {
    var stale = getElement("analysis-stale");
    var result = getElement("result-text");
    var exportButton = getElement("export-filtered-result-btn");
    var filteredButton = getElement("filtered-log-view-btn");
    state.dirty = false;
    if (stale) {
      stale.textContent = "";
      stale.hidden = true;
    }
    var hasResult = Boolean(result && String(result.value || ""));
    if (exportButton) exportButton.disabled = !hasResult;
    if (filteredButton) {
      filteredButton.disabled = !hasResult;
      filteredButton.setAttribute("aria-disabled", String(!hasResult));
    }
  }

  /**
   * 只有适配器明确返回可用结果时才允许清理 stale。
   * ``undefined`` 也视为失败：旧的 People/Dating 适配器因此在模板中返回
   * ``{ok: true/false}``，而第三方适配器仍可返回任意非空成功 payload。
   */
  function isSuccessfulAnalysisResult(result) {
    if (result === undefined || result === null || result === false) return false;
    if (typeof result !== "object") return true;
    if (result.ok === false || result.success === false || result.valid === false) return false;
    if (result.ok === true || result.success === true || result.valid === true) return true;
    return !result.error;
  }

  function invalidateSearch() {
    searchSource = null;
    searchSourceText = "";
    searchMatches = [];
    currentSearchIndex = -1;
  }

  /** 当前搜索目标随视图切换，始终是完整 textarea 字符串而非逐行 DOM。 */
  function activeSearchElement() {
    var filtered = getElement("result-text");
    if (state.activeLogView === "filtered" && filtered) return filtered;
    return getElement("log_text");
  }

  function setSearchCount(value) {
    var countElement = getElement("search-count");
    if (countElement) countElement.textContent = value;
  }

  /** 按关键词生成 UTF-16 偏移区间；匹配采用旧行为的大小写不敏感、非重叠搜索。 */
  function refreshSearch() {
    var queryElement = getElement("result-search");
    var sourceElement = activeSearchElement();
    var query = queryElement ? String(queryElement.value || "") : "";
    var sourceText = sourceElement ? String(sourceElement.value || "") : "";
    searchQuery = query;
    searchSource = sourceElement;
    searchSourceText = sourceText;
    searchMatches = [];
    currentSearchIndex = -1;

    if (!query) {
      setSearchCount(lineCountFor(sourceText) + " 行");
      return [];
    }

    var sourceLower = sourceText.toLowerCase();
    var queryLower = query.toLowerCase();
    var cursor = 0;
    var matchIndex = sourceLower.indexOf(queryLower, cursor);
    while (matchIndex !== -1) {
      searchMatches.push({
        start: matchIndex,
        end: matchIndex + query.length
      });
      cursor = matchIndex + query.length;
      matchIndex = sourceLower.indexOf(queryLower, cursor);
    }
    setSearchCount(searchMatches.length ? "0/" + searchMatches.length : "0/0");
    return searchMatches;
  }

  function focusSearchMatch(index) {
    if (!searchMatches.length || !searchSource) {
      setSearchCount("0/0");
      return false;
    }
    currentSearchIndex = (index + searchMatches.length) % searchMatches.length;
    var match = searchMatches[currentSearchIndex];
    if (typeof searchSource.focus === "function") searchSource.focus();
    if (typeof searchSource.setSelectionRange === "function") {
      searchSource.setSelectionRange(match.start, match.end);
    }
    var sourceText = String(searchSource.value || "");
    var lineNumber = 1;
    for (var cursor = 0; cursor < match.start; cursor += 1) {
      if (sourceText.charAt(cursor) === "\n" || sourceText.charAt(cursor) === "\r") {
        if (sourceText.charAt(cursor) !== "\r" || sourceText.charAt(cursor + 1) !== "\n") {
          lineNumber += 1;
        }
      }
    }
    var styles = typeof global.getComputedStyle === "function"
      ? global.getComputedStyle(searchSource) : {};
    var lineHeight = parseFloat(styles.lineHeight) || 20;
    searchSource.scrollTop = Math.max(0, (lineNumber - 2) * lineHeight);
    if (typeof searchSource.scrollIntoView === "function") {
      searchSource.scrollIntoView({block: "center"});
    }
    setSearchCount((currentSearchIndex + 1) + "/" + searchMatches.length);
    return true;
  }

  /**
   * 搜索当前原始/过滤 textarea。
   *
   * @param {number} direction 1 表示下一个，-1 表示上一个；默认向前。
   * @returns {boolean} 是否定位到了匹配项。
   */
  function searchActiveLog(direction) {
    var queryElement = getElement("result-search");
    var sourceElement = activeSearchElement();
    var query = queryElement ? String(queryElement.value || "") : "";
    var sourceText = sourceElement ? String(sourceElement.value || "") : "";
    if (query !== searchQuery || sourceElement !== searchSource || sourceText !== searchSourceText) {
      refreshSearch();
    }
    if (!query) {
      setSearchCount(lineCountFor(sourceText) + " 行");
      return false;
    }
    if (!searchMatches.length) {
      setSearchCount("0/0");
      return false;
    }
    var step = Number(direction) < 0 ? -1 : 1;
    var nextIndex = currentSearchIndex < 0
      ? (step < 0 ? searchMatches.length - 1 : 0)
      : currentSearchIndex + step;
    return focusSearchMatch(nextIndex);
  }

  /** 绑定 150ms debounce 搜索和 Enter/Shift+Enter 前后切换。 */
  function initializeSearch() {
    var queryElement = getElement("result-search");
    if (!queryElement || typeof queryElement.addEventListener !== "function") return;
    queryElement.addEventListener("input", function handleSearchInput() {
      clearTimer(searchTimer);
      searchTimer = schedule(function debounceSearch() {
        refreshSearch();
        if (searchMatches.length) focusSearchMatch(0);
      }, 150);
    });
    queryElement.addEventListener("keydown", function handleSearchKeydown(event) {
      if (event.key !== "Enter") return;
      event.preventDefault();
      clearTimer(searchTimer);
      searchTimer = null;
      searchActiveLog(event.shiftKey ? -1 : 1);
    });
    var previousButton = getElement("search-prev-btn");
    var nextButton = getElement("search-next-btn");
    if (previousButton) previousButton.addEventListener("click", function searchPrevious() {
      searchActiveLog(-1);
    });
    if (nextButton) nextButton.addEventListener("click", function searchNext() {
      searchActiveLog(1);
    });
    refreshSearch();
  }

  function setActiveLogView(view, focusButton) {
    var normalizedView = view === "filtered" ? "filtered" : "raw";
    var rawView = getElement("raw-log-view");
    var filteredView = getElement("filtered-log-view");
    var rawButton = getElement("raw-log-view-btn");
    var filteredButton = getElement("filtered-log-view-btn");
    var result = getElement("result-text");
    if (normalizedView === "filtered" && filteredButton && filteredButton.disabled) return false;

    if (rawView) rawView.hidden = normalizedView !== "raw";
    if (filteredView) filteredView.hidden = normalizedView !== "filtered";
    if (rawButton) {
      rawButton.setAttribute("aria-selected", String(normalizedView === "raw"));
      rawButton.tabIndex = normalizedView === "raw" ? 0 : -1;
    }
    if (filteredButton) {
      filteredButton.setAttribute("aria-selected", String(normalizedView === "filtered"));
      filteredButton.tabIndex = normalizedView === "filtered" ? 0 : -1;
    }
    state.activeLogView = normalizedView;
    invalidateSearch();
    refreshSearch();
    if (focusButton) {
      var button = normalizedView === "filtered" ? filteredButton : rawButton;
      if (button && typeof button.focus === "function") button.focus();
    }
    return Boolean(result || rawView || filteredView);
  }

  /** 初始化原始/过滤视图；过滤结果为空时只读视图和导出保持禁用。 */
  function initializeLogViews() {
    var rawButton = getElement("raw-log-view-btn");
    var filteredButton = getElement("filtered-log-view-btn");
    var exportButton = getElement("export-filtered-result-btn");
    var result = getElement("result-text");
    var hasResult = Boolean(result && String(result.value || ""));
    if (exportButton) exportButton.disabled = !hasResult;
    if (filteredButton) {
      filteredButton.disabled = !hasResult;
      filteredButton.setAttribute("aria-disabled", String(filteredButton.disabled));
      filteredButton.addEventListener("click", function showFilteredLog() {
        setActiveLogView("filtered", false);
      });
    }
    if (rawButton) {
      rawButton.addEventListener("click", function showRawLog() {
        setActiveLogView("raw", false);
      });
    }
    setActiveLogView("raw", false);
  }

  /**
   * 在原始 textarea 中选择真实行范围，并反馈同一范围到 status/toast。
   *
   * @param {number} startLine 1-based 起始行，越界值会夹取到日志范围。
   * @param {number} endLine 1-based 结束行，缺省时等于起始行。
   * @returns {{startLine:number,endLine:number,selectionStart:number,selectionEnd:number}|false}
   *   成功返回定位信息；缺少原始 textarea 时返回 false。
   *
   * 行偏移来自原始字符串中的 CR/LF 实际位置，而不是服务端过滤结果中的行号。
   * method 筛选不是“全部”时只警告可能隐藏目标，不静默改变用户的筛选条件。
   */
  function focusLogLines(startLine, endLine) {
    var textarea = getElement("log_text");
    if (!textarea) return false;
    var text = String(textarea.value || "");
    var starts = lineStartsFor(text);
    var totalLines = Math.max(1, starts.length);
    var requestedStart = Number(startLine);
    var requestedEnd = Number(endLine);
    var safeStart = Number.isFinite(requestedStart) ? Math.floor(requestedStart) : 1;
    var safeEnd = Number.isFinite(requestedEnd) ? Math.floor(requestedEnd) : safeStart;
    safeStart = Math.max(1, Math.min(safeStart, totalLines));
    safeEnd = Math.max(safeStart, Math.min(safeEnd, totalLines));
    var selectionStart = starts[safeStart - 1];
    var selectionEnd = text.length;
    if (safeEnd < starts.length) {
      selectionEnd = starts[safeEnd];
      if (text.charAt(selectionEnd - 1) === "\n") selectionEnd -= 1;
      if (text.charAt(selectionEnd - 1) === "\r") selectionEnd -= 1;
    }

    setActiveLogView("raw", false);
    if (typeof textarea.focus === "function") textarea.focus();
    if (typeof textarea.setSelectionRange === "function") {
      textarea.setSelectionRange(selectionStart, selectionEnd);
    }
    var styles = typeof global.getComputedStyle === "function"
      ? global.getComputedStyle(textarea) : {};
    var lineHeight = parseFloat(styles.lineHeight) || 20;
    textarea.scrollTop = Math.max(0, (safeStart - 2) * lineHeight);
    if (typeof textarea.scrollIntoView === "function") {
      textarea.scrollIntoView({block: "center"});
    }

    var rangeLabel = "L" + safeStart + (safeEnd === safeStart ? "" : "–" + safeEnd);
    var allMethod = typeof document.querySelector === "function"
      ? document.querySelector('#method-dropdown input[data-is-all="1"]') : null;
    var filteredWarning = Boolean(allMethod && !allMethod.checked);
    var message = "已定位到原日志 " + rangeLabel;
    if (filteredWarning) {
      message += "；当前 method 筛选可能隐藏目标，请切换“全部”接口后核对过滤结果。";
    }
    var focusStatus = getElement("log-focus-status");
    if (focusStatus) focusStatus.textContent = message;
    showActionMessage(message, filteredWarning);
    showToast(message);
    state.lastFocusedElement = textarea;
    state.lastFocusedRange = {
      startLine: safeStart,
      endLine: safeEnd,
      selectionStart: selectionStart,
      selectionEnd: selectionEnd
    };
    return state.lastFocusedRange;
  }

  function initializeLogInput() {
    var textarea = getElement("log_text");
    if (!textarea || typeof textarea.addEventListener !== "function") return;
    updateLogMetadata();
    textarea.addEventListener("input", function handleLogInput() {
      state.inputRevision += 1;
      updateLogMetadata();
      invalidateSearch();
      markAnalysisStale();
    });
  }

  /** People/Dating 完成后统一激活结果标签，错误也必须可立即看到。 */
  function activateResultPanel() {
    var resultTab = getElement("resultTab");
    if (resultTab) activateTab("resultPanel", false);
  }

  /** 统一控制异步分析期间的入口、模式选择器与 loading 遮罩。 */
  function setAnalysisBusy(root, modeSelect, submitButton, loadingMask, isBusy, idleText) {
    root.setAttribute("aria-busy", isBusy ? "true" : "false");
    if (modeSelect) modeSelect.disabled = isBusy;
    if (submitButton) {
      submitButton.disabled = isBusy;
      submitButton.textContent = isBusy ? "分析中..." : idleText;
      submitButton.setAttribute("aria-busy", isBusy ? "true" : "false");
    }
    if (loadingMask) {
      loadingMask.hidden = !isBusy;
      loadingMask.setAttribute("aria-busy", isBusy ? "true" : "false");
    }
  }

  function currentForm() {
    return getElement("log-filter-form") || getElement("log-analysis-form");
  }

  function currentLogText() {
    var textarea = getElement("log_text");
    return textarea ? String(textarea.value || "") : "";
  }

  function submitGeneralForm(form) {
    if (!form) {
      showPersistentError(new Error("日志过滤表单不可用。"));
      return false;
    }
    try {
      if (typeof form.requestSubmit === "function") {
        state.phase = "submitting";
        nativeSubmitInProgress = true;
        form.requestSubmit();
        return true;
      }
      if (typeof form.submit === "function") {
        state.phase = "submitting";
        nativeSubmitInProgress = false;
        form.submit();
        return true;
      }
    } catch (error) {
      nativeSubmitInProgress = false;
      state.phase = "idle";
      showPersistentError(error);
      return false;
    }
    showPersistentError(new Error("浏览器不支持表单提交。"));
    return false;
  }

  function runAsyncAnalysis(root, form, modeSelect, submitButton, loadingMask, mode) {
    if (analysisInFlight) return analysisInFlight;
    var idleText = submitButton ? submitButton.textContent : "分析日志";
    var revisionAtStart = state.inputRevision;
    var controller = typeof global.AbortController === "function"
      ? new global.AbortController() : null;
    var context = {
      root: root,
      form: form,
      endpoints: namespace.endpoints,
      logText: currentLogText(),
      signal: controller ? controller.signal : null
    };
    var runner = typeof mode.analyze === "function" ? mode.analyze : mode.run;
    state.phase = "loading";
    setAnalysisBusy(root, modeSelect, submitButton, loadingMask, true, idleText);

    var runResult;
    try {
      runResult = runner(context);
    } catch (error) {
      runResult = Promise.reject(error);
    }
    analysisInFlight = Promise.resolve(runResult)
      .then(function completeAnalysis(result) {
        if (!isSuccessfulAnalysisResult(result)) {
          var invalidMessage = result && result.message
            ? result.message : "分析未生成有效结果，请检查日志后重试。";
          markAnalysisStale(invalidMessage);
          showPersistentError(new Error(invalidMessage));
          activateResultPanel();
          return {ok: false, message: invalidMessage};
        }
        if (revisionAtStart !== state.inputRevision) {
          markAnalysisStale("分析期间日志已修改，结果可能已过期，请重新分析。");
        }
        // People/Dating 只更新各自的结果面板，不会写入 result-text；它们成功时
        // 不能替通用 Filter 清 stale。通用 Filter 成功走原生 POST，由新页面结果
        // 建立 freshness，避免这里把两个生命周期混在一起。
        activateResultPanel();
        return result;
      })
      .catch(function handleAnalysisFailure(error) {
        // Promise reject 同样代表没有生成可用结果；即使日志本身没有再次 input，
        // 也要保留 stale 并禁用旧结果导出，避免失败请求误用历史结果。
        var failureMessage = error && error.message
          ? error.message : "分析失败，请稍后重试。";
        markAnalysisStale(failureMessage);
        showPersistentError(error);
        activateResultPanel();
        return null;
      })
      .finally(function restoreAnalysisControls() {
        state.phase = "idle";
        setAnalysisBusy(root, modeSelect, submitButton, loadingMask, false, idleText);
        analysisInFlight = null;
      });
    return analysisInFlight;
  }

  /**
   * 执行当前选择的模式。
   *
   * 通用模式只调用原有 form POST，不改变后端接口；异步模式由已注册适配器承接。
   * ``analysisInFlight`` 在调用适配器前就建立，因此统一按钮和表单重复事件只能产生
   * 一次分析请求。
   *
   * @returns {boolean|Promise<*>} 原生提交是否发起，或异步适配器的生命周期 Promise。
   */
  function analyzeSelectedMode() {
    var root = getElement("log-workbench");
    var modeSelect = getElement("analysis-mode");
    var submitButton = getElement("analyze-log-btn");
    var loadingMask = getElement("workbench-loading-mask");
    var form = currentForm();
    if (state.phase === "loading" || state.phase === "submitting") {
      return analysisInFlight || false;
    }
    if (!root || !modeSelect) {
      showPersistentError(new Error("分析工作台不可用。"));
      return false;
    }
    var selectedName = String(modeSelect.value || "");
    var mode = getMode(selectedName);
    if (!mode) {
      showActionMessage("请选择可用的分析模式。", true, true);
      showToast("请选择可用的分析模式。");
      return false;
    }
    state.activeMode = canonicalModeName(selectedName);
    if (mode.nativeSubmit) return submitGeneralForm(form);
    if (analysisInFlight) return analysisInFlight;
    return runAsyncAnalysis(root, form, modeSelect, submitButton, loadingMask, mode);
  }

  /** 初始化表单 submit 与唯一统一分析按钮。 */
  function initializeModeSubmission(root) {
    var form = currentForm();
    var modeSelect = getElement("analysis-mode");
    var submitButton = getElement("analyze-log-btn");
    if (!form || !modeSelect) return;

    form.addEventListener("submit", function handleWorkbenchSubmit(event) {
      var mode = getMode(modeSelect.value);
      if (!mode) {
        event.preventDefault();
        showActionMessage("请选择可用的分析模式。", true, true);
        showToast("请选择可用的分析模式。");
        return;
      }
      if (mode.nativeSubmit) {
        if (state.phase === "loading" ||
            (state.phase === "submitting" && !nativeSubmitInProgress)) {
          event.preventDefault();
          return;
        }
        nativeSubmitInProgress = false;
        state.phase = "submitting";
        return;
      }
      event.preventDefault();
      analyzeSelectedMode();
    });
    if (submitButton) {
      submitButton.addEventListener("click", function handleAnalyzeClick() {
        analyzeSelectedMode();
      });
    }
  }

  /** 从服务端渲染的数据属性读取真实 endpoint，自动继承 Blueprint base path。 */
  function readEndpoints(root) {
    var dataset = root.dataset || {};
    return {
      index: dataset.indexUrl,
      exportLog: dataset.exportUrl,
      peopleSearch: dataset.peopleSearchUrl,
      dating: dataset.datingUrl
    };
  }

  /** 为默认通用模式注册原生表单行为；旧 ``filter`` 名称由别名兼容。 */
  function registerDefaultModes() {
    if (!modes.general && !modes.filter) registerMode("general", {nativeSubmit: true});
    if (!modes.general && modes.filter) modes.general = modes.filter;
    if (!modes.filter && modes.general) modes.filter = modes.general;
  }

  /** 返回工作台中按 DOM 顺序排列的全部结果标签。 */
  function tabButtons(root) {
    return root && typeof root.querySelectorAll === "function"
      ? Array.from(root.querySelectorAll('[role="tab"][aria-controls]')) : [];
  }

  function visibleTabButtons(root) {
    return tabButtons(root).filter(function isVisible(button) {
      return !button.hidden;
    });
  }

  /** 激活一个可见结果 panel，并同步标签、panel 与键盘焦点状态。 */
  function activateTab(panelId, focusTab) {
    var root = getElement("log-workbench");
    if (!root) return false;
    var normalizedPanelId = String(panelId || "");
    var visibleTabs = visibleTabButtons(root);
    var selectedTab = visibleTabs.find(function findTarget(button) {
      return button.getAttribute("aria-controls") === normalizedPanelId;
    });
    if (!selectedTab) return false;

    tabButtons(root).forEach(function updateTab(button) {
      var selected = !button.hidden && button === selectedTab;
      var panel = getElement(button.getAttribute("aria-controls"));
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (panel) panel.hidden = !selected;
    });
    state.activeTab = normalizedPanelId.replace(/Panel$/, "");
    if (focusTab && typeof selectedTab.focus === "function") selectedTab.focus();
    return true;
  }

  /** 根据模式声明可见 panel，并在当前 panel 被移除时回退到首个可见标签。 */
  function setAvailableTabs(panelIds) {
    var root = getElement("log-workbench");
    if (!root) return false;
    var availableIds = new Set(Array.isArray(panelIds) ? panelIds.map(String) : []);
    tabButtons(root).forEach(function updateAvailability(button) {
      var panel = getElement(button.getAttribute("aria-controls"));
      var available = availableIds.has(button.getAttribute("aria-controls"));
      button.hidden = !available;
      if (!available) {
        button.setAttribute("aria-selected", "false");
        button.tabIndex = -1;
        if (panel) panel.hidden = true;
      }
    });
    var visibleTabs = visibleTabButtons(root);
    var selectedTab = visibleTabs.find(function findSelected(button) {
      return button.getAttribute("aria-selected") === "true";
    }) || visibleTabs[0];
    if (!selectedTab) {
      state.activeTab = "";
      return false;
    }
    return activateTab(selectedTab.getAttribute("aria-controls"), false);
  }

  /** 为结果标签绑定鼠标与仅包含可见标签的键盘导航。 */
  function initializeTabs(root) {
    var tabs = tabButtons(root);
    if (!tabs.length) return;
    tabs.forEach(function bindTab(tab) {
      tab.addEventListener("click", function handleTabClick() {
        activateTab(tab.getAttribute("aria-controls"), false);
      });
      tab.addEventListener("keydown", function handleTabKeydown(event) {
        var visibleTabs = visibleTabButtons(root);
        var currentIndex = visibleTabs.indexOf(tab);
        if (currentIndex < 0) return;
        var targetIndex = null;
        if (event.key === "ArrowLeft") targetIndex = (currentIndex - 1 + visibleTabs.length) % visibleTabs.length;
        if (event.key === "ArrowRight") targetIndex = (currentIndex + 1) % visibleTabs.length;
        if (event.key === "Home") targetIndex = 0;
        if (event.key === "End") targetIndex = visibleTabs.length - 1;
        if (targetIndex === null) return;
        event.preventDefault();
        activateTab(visibleTabs[targetIndex].getAttribute("aria-controls"), true);
      });
    });
    var visibleTabs = visibleTabButtons(root);
    var selected = visibleTabs.find(function findSelected(tab) {
      return tab.getAttribute("aria-selected") === "true";
    }) || visibleTabs[0];
    if (selected) activateTab(selected.getAttribute("aria-controls"), false);
  }

  /** 将 workspace padding/border 从轨道尺寸中扣除，保持键盘每次真实移动 16px。 */
  function workspaceTrackMetrics(root) {
    var bounds = root.getBoundingClientRect();
    var styles = typeof global.getComputedStyle === "function" ? global.getComputedStyle(root) : {};
    var borderLeft = Number.parseFloat(styles.borderLeftWidth) || 0;
    var borderRight = Number.parseFloat(styles.borderRightWidth) || 0;
    var paddingLeft = Number.parseFloat(styles.paddingLeft) || 0;
    var paddingRight = Number.parseFloat(styles.paddingRight) || 0;
    return {
      left: bounds.left + borderLeft + paddingLeft,
      width: Math.max(0, bounds.width - borderLeft - borderRight - paddingLeft - paddingRight)
    };
  }

  function setLogPaneWidth(root, resizer, requestedValue) {
    var minimum = Number(resizer.getAttribute("aria-valuemin")) || 32;
    var maximum = Number(resizer.getAttribute("aria-valuemax")) || 55;
    var numericValue = Number(requestedValue);
    if (!Number.isFinite(numericValue)) return null;
    var clampedValue = Math.min(maximum, Math.max(minimum, numericValue));
    var value = Math.round(clampedValue * 10000) / 10000;
    root.style.setProperty("--left-pane", String(value) + "%");
    resizer.setAttribute("aria-valuenow", String(value));
    return value;
  }

  /** 初始化键盘和指针均可操作的栏宽调整器。 */
  function initializeResizer(root) {
    var resizer = getElement("workbench-resizer");
    if (!resizer) return;
    resizer.addEventListener("keydown", function handleResizeKeydown(event) {
      var current = Number(resizer.getAttribute("aria-valuenow")) || 39;
      var metrics = workspaceTrackMetrics(root);
      var keyboardStep = metrics.width > 0 ? (16 / metrics.width) * 100 : 0;
      var next = null;
      if (event.key === "ArrowLeft") next = current - keyboardStep;
      if (event.key === "ArrowRight") next = current + keyboardStep;
      if (event.key === "Home") next = Number(resizer.getAttribute("aria-valuemin"));
      if (event.key === "End") next = Number(resizer.getAttribute("aria-valuemax"));
      if (next === null) return;
      event.preventDefault();
      setLogPaneWidth(root, resizer, next);
    });
    resizer.addEventListener("pointerdown", function handlePointerDown(event) {
      if (event.button !== 0) return;
      resizer.setPointerCapture(event.pointerId);
      function handlePointerMove(moveEvent) {
        var metrics = workspaceTrackMetrics(root);
        if (metrics.width <= 0) return;
        setLogPaneWidth(root, resizer, ((moveEvent.clientX - metrics.left) / metrics.width) * 100);
      }
      function stopPointerResize(endEvent) {
        document.removeEventListener("pointermove", handlePointerMove);
        document.removeEventListener("pointerup", stopPointerResize);
        document.removeEventListener("pointercancel", stopPointerResize);
        if (resizer.hasPointerCapture(endEvent.pointerId)) resizer.releasePointerCapture(endEvent.pointerId);
      }
      document.addEventListener("pointermove", handlePointerMove);
      document.addEventListener("pointerup", stopPointerResize);
      document.addEventListener("pointercancel", stopPointerResize);
    });
  }

  /** 幂等初始化当前页面；重复调用不会再次绑定事件。 */
  function initialize() {
    var root = getElement("log-workbench");
    if (!root || root.dataset.workbenchInitialized === "true") return;
    root.dataset.workbenchInitialized = "true";
    namespace.endpoints = readEndpoints(root);
    initializeTabs(root);
    initializeResizer(root);
    initializeLogViews();
    initializeLogInput();
    initializeSearch();
    initializeModeSubmission(root);
  }

  registerDefaultModes();
  namespace.state = state;
  namespace.modes = modes;
  namespace.registerMode = registerMode;
  namespace.registerAnalysisMode = registerAnalysisMode;
  namespace.getMode = getMode;
  namespace.analyzeSelectedMode = analyzeSelectedMode;
  namespace.searchActiveLog = searchActiveLog;
  namespace.refreshSearch = refreshSearch;
  namespace.focusLogLines = focusLogLines;
  namespace.setActiveLogView = setActiveLogView;
  namespace.activateLogView = setActiveLogView;
  namespace.updateLogMetadata = updateLogMetadata;
  namespace.markAnalysisStale = markAnalysisStale;
  namespace.markAnalysisFresh = markAnalysisFresh;
  namespace.setAvailableTabs = setAvailableTabs;
  namespace.activateTab = activateTab;
  namespace.activateResultPanel = activateResultPanel;
  namespace.showToast = showToast;
  namespace.showActionMessage = showActionMessage;
  namespace.showPersistentError = showPersistentError;
  namespace.readCookie = readCookie;
  namespace.requestJson = requestJson;
  namespace.init = initialize;
  global.LogWorkbench = namespace;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})(window, document);
