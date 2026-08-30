/**
 * Dating 结构化分析工作台适配器。
 *
 * 职责：
 * 1. 通过 workbench-core 提供的 requestJson 调用当前根节点上的 Dating endpoint；
 * 2. 将后端已脱敏的单任务响应拆到五个标准 panel，不改变 analyzer/rules/report 契约；
 * 3. 保留每一条 Poll、每一条 calls 和字段 presence，并把接口详情交给共享 drawer；
 * 4. 所有响应值都以 textContent、createTextNode 或 pre.textContent 写入固定 DOM。
 *
 * 本文件不拥有 Filter 的 result-text，也不拥有 People 的节点。每轮请求开始时只
 * 清理 Dating 自己的状态；失败时不把上一次任务的报告、JSON 或导出按钮带到新任务。
 */
(function bootstrapDatingWorkbench(global, document) {
  "use strict";

  var api = global.LogWorkbench || {};

  var latestDatingAnalysis = null;
  var latestDatingReport = '';
  var latestDatingFields = [];
  var latestDatingChecks = [];
  var latestDatingParseWarnings = [];
  var datingExpandedPaths = Object.create(null);
  var datingTreeLimits = Object.create(null);
  var datingVisibleFieldCount = 200;
  var pendingDatingFieldTreeFields = [];
  var pendingDatingCalls = [];
  var pendingDatingPutAssetMap = Object.create(null);
  var datingFieldTreeMaterialized = false;
  var datingCallsMaterialized = false;
  var datingLazyListenersAttached = false;
  var datingModeListenerAttached = false;
  var datingInitialized = false;

  var DATING_ERROR_MESSAGES = {
    EMPTY_LOG: '日志内容为空',
    LOG_TOO_LARGE: '日志内容超过允许的字节上限',
    UNSUPPORTED_LOG: '未识别到 Dating Gateway/PUT 日志',
    MULTIPLE_TASKS_FOUND: '日志包含多个 Dating 任务，请指定 task_id',
    TASK_NOT_FOUND: '指定的 task_id 不存在',
    ANALYZER_DISABLED: 'Dating 结构化分析功能未启用',
    ANALYSIS_INTERNAL_ERROR: 'Dating 分析失败'
  };

  var DATING_ERROR_STATUS = {
    EMPTY_LOG: 400,
    LOG_TOO_LARGE: 413,
    UNSUPPORTED_LOG: 422,
    MULTIPLE_TASKS_FOUND: 422,
    TASK_NOT_FOUND: 422,
    ANALYZER_DISABLED: 503,
    ANALYSIS_INTERNAL_ERROR: 500
  };

  var DATING_ERROR_ACTIONS = {
    EMPTY_LOG: '请先粘贴日志后重试。',
    LOG_TOO_LARGE: '请缩小日志到 10 MiB 以内后重试。',
    UNSUPPORTED_LOG: '请确认日志包含 Dating Gateway/PUT 调用。',
    MULTIPLE_TASKS_FOUND: '请在请求中指定唯一 task_id 后重试。',
    TASK_NOT_FOUND: '请确认指定的 task_id 出现在当前日志中。',
    ANALYZER_DISABLED: '请联系管理员启用 Dating 结构化分析功能。',
    ANALYSIS_INTERNAL_ERROR: '请保留原日志并稍后重试；服务端已记录内部异常。'
  };

  function getElement(id) {
    return document.getElementById(id);
  }

  /**
   * 将后端值转换成纯文本节点。
   *
   * 参数说明：parent 是适配器拥有的固定父节点，value 是后端已经脱敏的值。
   * 返回值：返回 parent，便于调用方继续追加节点。
   * 异常说明：循环对象无法 JSON.stringify 时降级为 String，不让单个字段中断整页。
   */
  function appendDatingText(parent, value) {
    if (!parent) return parent;
    var text;
    if (value === null) {
      text = 'null';
    } else if (value === undefined) {
      text = '—';
    } else if (typeof value === 'string') {
      text = value === '' ? '空字符串' : value;
    } else if (typeof value === 'object') {
      try {
        text = JSON.stringify(value, null, 2);
      } catch (error) {
        text = String(value);
      }
      if (text === undefined) text = '—';
    } else {
      text = String(value);
    }
    parent.appendChild(document.createTextNode(text));
    return parent;
  }

  /** 只清空当前适配器拥有的叶子节点，避免误删其他分析模式的 DOM。 */
  function clearDatingNode(id) {
    var node = getElement(id);
    if (node) node.textContent = '';
    return node;
  }

  /** 创建只含固定 class 与纯文本的节点。className 不来自服务端。 */
  function createDatingTextElement(tagName, className, value) {
    var node = document.createElement(tagName);
    if (className) node.className = className;
    appendDatingText(node, value);
    return node;
  }

  /** 向 dl 追加 label/value 对；value 的缺失、null、空字符串由 appendDatingText 区分。 */
  function appendDatingDefinition(parent, label, value) {
    if (!parent) return;
    var group = document.createElement('div');
    group.className = 'dating-summary-item';
    group.appendChild(createDatingTextElement('dt', '', label));
    group.appendChild(createDatingTextElement('dd', '', value));
    parent.appendChild(group);
  }

  /** 返回适合表格单元格的单行文本；对象仍使用 JSON 文本，不生成标记。 */
  function datingCompactValue(value) {
    if (value === null) return 'null';
    if (value === undefined) return '—';
    if (typeof value === 'string') return value === '' ? '空字符串' : value;
    if (typeof value === 'object') {
      try {
        return JSON.stringify(value);
      } catch (error) {
        return String(value);
      }
    }
    return String(value);
  }

  /** 业务 Schema 的空值语义；字段缺失不能伪装成 null 或空字符串。 */
  function datingSchemaValue(value) {
    if (value === null) return 'null';
    if (value === undefined) return '字段缺失';
    if (value === '') return '空字符串';
    if (Array.isArray(value) && !value.length) return '空数组 []';
    if (value && typeof value === 'object' && !Object.keys(value).length) {
      return '空对象 {}';
    }
    return datingCompactValue(value);
  }

  function setText(id, value) {
    var node = getElement(id);
    if (node) node.textContent = value === undefined || value === null ? '' : String(value);
    return node;
  }

  function setHidden(id, hidden) {
    var node = getElement(id);
    if (node) node.hidden = Boolean(hidden);
    return node;
  }

  function setDatingResultHeader(title, subtitle) {
    if (typeof api.setResultHeader === 'function') {
      api.setResultHeader(title, subtitle);
    }
    // 兼容尚未加载新版 core 的测试沙箱；仍只写固定文本节点。
    setText('workbench-result-heading', title);
    setText('workbench-result-subheading', subtitle);
  }

  function datingErrorInfo(error) {
    var code = error && (error.error_code || error.errorCode);
    code = DATING_ERROR_MESSAGES[code] ? code : 'ANALYSIS_INTERNAL_ERROR';
    var status = DATING_ERROR_STATUS[code];
    var message = error && error.message ? String(error.message) : DATING_ERROR_MESSAGES[code];
    // requestJson 已将后端 message 放入 Error；稳定 code 的默认文案仍以 API 合同为准。
    if (!error || !error.message || code !== 'ANALYSIS_INTERNAL_ERROR') {
      message = error && error.message ? String(error.message) : DATING_ERROR_MESSAGES[code];
    }
    return {
      code: code,
      status: status,
      message: message || DATING_ERROR_MESSAGES[code],
      action: DATING_ERROR_ACTIONS[code]
    };
  }

  function updateDatingExportButtons(isLoading) {
    var copyButton = getElement('copy-dating-report-btn');
    var reportButton = getElement('export-dating-report-btn');
    var jsonButton = getElement('export-dating-json-btn');
    if (copyButton) copyButton.disabled = Boolean(isLoading) || !latestDatingReport;
    if (reportButton) reportButton.disabled = Boolean(isLoading) || !latestDatingReport;
    if (jsonButton) jsonButton.disabled = Boolean(isLoading) || !latestDatingAnalysis;
  }

  /** 日志修订后结果仍可核对，但所有 Dating 结果导出必须失效。 */
  function markDatingStale() {
    var copyButton = getElement('copy-dating-report-btn');
    var reportButton = getElement('export-dating-report-btn');
    var jsonButton = getElement('export-dating-json-btn');
    if (copyButton) copyButton.disabled = true;
    if (reportButton) reportButton.disabled = true;
    if (jsonButton) jsonButton.disabled = true;
    setText('dating-status', latestDatingAnalysis ? '结果已过期，仅供查看' : '等待分析');
  }

  /** 请求期间显示可感知状态；结束时只按当前任务结果恢复导出按钮。 */
  function setDatingLoading(isLoading) {
    var status = getElement('dating-status');
    var state = getElement('dating-state');
    if (isLoading) {
      setText('dating-status', '分析中');
      if (state) {
        state.className = 'dating-state loading';
        state.textContent = '正在解析接口和结果字段…';
      }
    }
    updateDatingExportButtons(isLoading);
    if (!isLoading && status && !latestDatingAnalysis && state && state.className === 'dating-state loading') {
      status.textContent = '未分析';
    }
  }

  function setDatingTabs() {
    var panels = ['overviewPanel', 'interfacesPanel', 'timelinePanel', 'resultPanel', 'checksPanel'];
    if (typeof api.setAvailableTabs === 'function') api.setAvailableTabs(panels);
  }

  function setNonDatingTabs(modeName) {
    var panels = modeName === 'people'
      ? ['overviewPanel', 'interfacesPanel', 'resultPanel', 'checksPanel']
      : ['overviewPanel', 'interfacesPanel'];
    if (typeof api.setAvailableTabs === 'function') api.setAvailableTabs(panels);
  }

  function showDatingSuccessSurfaces() {
    setHidden('dating-analysis', false);
    setHidden('dating-content', false);
    ['dating-overview', 'dating-interfaces', 'dating-timeline', 'dating-result', 'dating-checks']
      .forEach(function showSurface(id) { setHidden(id, false); });
  }

  function hideDatingSurfaces() {
    ['dating-analysis', 'dating-content', 'dating-overview', 'dating-interfaces',
      'dating-timeline', 'dating-result', 'dating-checks']
      .forEach(function hideSurface(id) { setHidden(id, true); });
  }

  /**
   * 清空当前任务。
   * 重要状态迁移：分析开始、错误和模式切换都经过这里，确保错误请求不能继续导出旧任务。
   */
  function resetDatingResult() {
    latestDatingAnalysis = null;
    latestDatingReport = '';
    latestDatingFields = [];
    latestDatingChecks = [];
    latestDatingParseWarnings = [];
    pendingDatingFieldTreeFields = [];
    pendingDatingCalls = [];
    pendingDatingPutAssetMap = Object.create(null);
    datingExpandedPaths = Object.create(null);
    datingTreeLimits = Object.create(null);
    datingVisibleFieldCount = 200;
    datingFieldTreeMaterialized = false;
    datingCallsMaterialized = false;
    hideDatingSurfaces();
    setText('dating-status', '未分析');
    var state = getElement('dating-state');
    if (state) {
      state.className = 'dating-state';
      state.textContent = '等待分析。请选择 Dating 模式并点击“分析日志”。';
    }
    ['dating-summary', 'dating-lifecycle-metrics', 'dating-upload-list',
      'dating-timeline-upload-list', 'dating-progress-diagnostics', 'dating-task-timeline',
      'dating-result-summary', 'dating-result-sections', 'dating-field-tree',
      'dating-field-table-body', 'dating-interface-table-body', 'dating-check-list',
      'dating-parse-warnings', 'dating-report'].forEach(function clearSurface(id) {
      clearDatingNode(id);
    });
    // 行为测试可能用无子节点的替身直接写入 panel 文本；真实模板有固定子节点，
    // 因此只在空容器时清理自身文本，避免为清旧结果而删掉模板结构。
    ['dating-overview', 'dating-interfaces', 'dating-timeline', 'dating-result', 'dating-checks']
      .forEach(function clearEmptySurfaceText(id) {
        var surface = getElement(id);
        if (surface && surface.children && !surface.children.length) surface.textContent = '';
      });
    var rawJson = getElement('dating-raw-result-json');
    if (rawJson) rawJson.textContent = '';
    setText('dating-call-count', '');
    setText('dating-field-count', '0 个字段');
    setText('dating-warning-count', '');
    updateDatingExportButtons(false);
  }

  /** 展示稳定 HTTP/error_code、后端原文和可执行下一步。 */
  function renderDatingError(error) {
    var info = datingErrorInfo(error);
    var section = getElement('dating-analysis');
    var state = getElement('dating-state');
    if (section) section.hidden = false;
    if (state) {
      state.className = 'dating-state error';
      state.textContent = '';
      state.appendChild(createDatingTextElement('strong', '', String(info.status) + ' · ' + info.code));
      state.appendChild(createDatingTextElement('p', '', info.message));
      state.appendChild(createDatingTextElement('p', '', info.action));
    }
    setText('dating-status', '失败 · ' + String(info.status) + ' · ' + info.code);
    setDatingResultHeader('Dating 分析失败', info.message);
    if (typeof api.showActionMessage === 'function') {
      api.showActionMessage(info.message, true, true);
    }
    if (typeof api.activateTab === 'function') api.activateTab('overviewPanel', false);
    if (section && typeof section.focus === 'function') section.focus({preventScroll: true});
    updateDatingExportButtons(false);
    return info;
  }

  /** 依据 result_call_id 从完整 calls 中读取 result_id，避免从全文猜测业务字段。 */
  function findDatingResultId(calls, resultCallId) {
    var resultCall = (Array.isArray(calls) ? calls : []).find(function findCall(call) {
      return call && call.call_id === resultCallId;
    });
    var data = resultCall && resultCall.response && resultCall.response.data;
    return data && data.result_id !== undefined ? data.result_id : null;
  }

  /** 从服务端已关联的 input_assets 构造 PUT call_id 到 asset_id 的映射。 */
  function buildDatingPutAssetMap(taskSnapshot) {
    var putAssetMap = Object.create(null);
    var assets = taskSnapshot && Array.isArray(taskSnapshot.input_assets)
      ? taskSnapshot.input_assets : [];
    assets.forEach(function mapAsset(asset) {
      if (!asset || !asset.put_call_id || asset.asset_id === null ||
          asset.asset_id === undefined || asset.asset_id === '') return;
      var putCallId = String(asset.put_call_id);
      if (!Object.prototype.hasOwnProperty.call(putAssetMap, putCallId)) {
        putAssetMap[putCallId] = String(asset.asset_id);
      }
    });
    return putAssetMap;
  }

  /** 根据 documented params/data 和后端 PUT 关联展示 task/resource 事实。 */
  function datingCallReference(call, putAssetMap) {
    var requestParams = call && call.request && call.request.params || {};
    var responseData = call && call.response && call.response.data || {};
    putAssetMap = putAssetMap || Object.create(null);
    if (requestParams.task_id !== undefined) return requestParams.task_id;
    if (responseData.task_id !== undefined) return responseData.task_id;
    if (requestParams.asset_id !== undefined) return requestParams.asset_id;
    if (responseData.asset_id !== undefined) return responseData.asset_id;
    if (call && call.call_id && putAssetMap[call.call_id]) return putAssetMap[call.call_id];
    return '—';
  }

  /** 原始字段树仅在 details 首次展开时创建，避免大响应阻塞首屏。 */
  function materializeDatingFieldTreeOnce() {
    if (datingFieldTreeMaterialized) return;
    datingFieldTreeMaterialized = true;
    renderDatingFieldTree(pendingDatingFieldTreeFields);
  }

  /** 接口表不是折叠面板；此函数供共享生命周期/测试重放时幂等物化。 */
  function materializeDatingCallsOnce() {
    if (datingCallsMaterialized) return;
    datingCallsMaterialized = true;
    renderDatingCalls(pendingDatingCalls, pendingDatingPutAssetMap);
  }

  /** 保存重型分区，并只为字段树绑定一次 toggle；Interfaces 始终显示完整 calls 表。 */
  function setupDatingLazySections(taskSnapshot, calls) {
    pendingDatingFieldTreeFields = Array.isArray(taskSnapshot.result_fields)
      ? taskSnapshot.result_fields.slice() : [];
    pendingDatingCalls = Array.isArray(calls) ? calls.slice() : [];
    pendingDatingPutAssetMap = buildDatingPutAssetMap(taskSnapshot);
    datingFieldTreeMaterialized = false;
    datingCallsMaterialized = false;
    datingExpandedPaths = Object.create(null);
    datingTreeLimits = Object.create(null);

    var fieldTreeDetails = getElement('dating-field-tree-details');
    if (fieldTreeDetails) fieldTreeDetails.open = false;
    clearDatingNode('dating-field-tree');
    if (!datingLazyListenersAttached && fieldTreeDetails &&
        typeof fieldTreeDetails.addEventListener === 'function') {
      fieldTreeDetails.addEventListener('toggle', function handleFieldTreeToggle() {
        if (fieldTreeDetails.open) materializeDatingFieldTreeOnce();
      });
      datingLazyListenersAttached = true;
    }
    setText('dating-call-count', '共 ' + pendingDatingCalls.length + ' 条');
  }

  /**
   * 通过统一核心请求 Dating API。
   *
   * context 由 core 提供，必须包含 root/logText，可选 signal 用于取消请求。请求体
   * 保持后端严格合同 {log_text, task_id:null}；成功返回 {ok,data}，失败返回 {ok:false}
   * 交给 core 维持统一 loading/stale 生命周期。
   */
  function analyzeDatingLog() {
    var context = arguments[0] || {};
    var root = context.root || getElement('log-workbench');
    var logText = context.logText === undefined
      ? (getElement('log_text') ? getElement('log_text').value : '')
      : String(context.logText || '');

    setDatingTabs();
    resetDatingResult();
    setHidden('dating-analysis', false);

    if (!String(logText).trim()) {
      var emptyError = new Error(DATING_ERROR_MESSAGES.EMPTY_LOG);
      emptyError.error_code = 'EMPTY_LOG';
      renderDatingError(emptyError);
      return Promise.resolve({ok: false, message: DATING_ERROR_MESSAGES.EMPTY_LOG, error: emptyError});
    }
    if (!root || !root.dataset || !root.dataset.datingUrl ||
        typeof api.requestJson !== 'function') {
      var endpointError = new Error(DATING_ERROR_MESSAGES.ANALYSIS_INTERNAL_ERROR);
      endpointError.error_code = 'ANALYSIS_INTERNAL_ERROR';
      renderDatingError(endpointError);
      return Promise.resolve({ok: false, message: endpointError.message, error: endpointError});
    }

    setDatingLoading(true);
    return api.requestJson(root.dataset.datingUrl, {
      method: 'POST',
      body: {log_text: logText, task_id: null},
      signal: context.signal || undefined
    }).then(function handleDatingResponse(payload) {
      if (typeof context.isCurrent === 'function' && !context.isCurrent()) {
        return {ok: false, stale: true};
      }
      if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        throw new Error(DATING_ERROR_MESSAGES.ANALYSIS_INTERNAL_ERROR);
      }
      latestDatingAnalysis = payload;
      latestDatingReport = typeof payload.report_markdown === 'string'
        ? payload.report_markdown : '';
      renderDatingAnalysis(payload);
      if (typeof api.showActionMessage === 'function') {
        api.showActionMessage('分析完成：' + String(payload.verdict || ''), false);
      }
      return {ok: true, data: payload};
    }).catch(function handleDatingError(error) {
      if (typeof context.isCurrent === 'function' && !context.isCurrent()) {
        return {ok: false, stale: true};
      }
      resetDatingResult();
      var info = renderDatingError(error);
      return {ok: false, message: info.message, error: error};
    }).finally(function restoreDatingState() {
      if (typeof context.isCurrent !== 'function' || context.isCurrent()) {
        setDatingLoading(false);
      }
    });
  }

  /** 创建合法且可键盘操作的真实日志行号按钮。 */
  function createDatingLineButton(startLine, endLine, label) {
    var safeStart = Number(startLine);
    var safeEnd = Number(endLine);
    if (!Number.isInteger(safeStart) || safeStart < 1) {
      return createDatingTextElement('span', 'dating-muted', '日志证据不足');
    }
    if (!Number.isInteger(safeEnd) || safeEnd < safeStart) safeEnd = safeStart;
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'dating-line-button';
    button.textContent = (label ? String(label) + ' ' : '') + 'L' + safeStart +
      (safeEnd === safeStart ? '' : '–' + safeEnd);
    button.addEventListener('click', function focusDatingEvidence() {
      if (typeof api.focusLogLines === 'function') api.focusLogLines(safeStart, safeEnd);
    });
    return button;
  }

  function findDatingCall(callId) {
    if (!callId || !latestDatingAnalysis || !Array.isArray(latestDatingAnalysis.calls)) {
      return null;
    }
    return latestDatingAnalysis.calls.find(function findCall(call) {
      return call && call.call_id === callId;
    }) || null;
  }

  function appendDatingCallLines(parent, callId, label) {
    var call = findDatingCall(callId);
    if (!call || !parent) return;
    var request = call.request || {};
    var response = call.response || {};
    if (request.line_start !== undefined && request.line_start !== null) {
      parent.appendChild(createDatingLineButton(request.line_start, request.line_end, label + ' 请求'));
    }
    if (response.line_start !== undefined && response.line_start !== null) {
      parent.appendChild(createDatingLineButton(response.line_start, response.line_end, label + ' 响应'));
    }
  }

  function renderDatingUploadList(targetId, assets) {
    var uploadList = clearDatingNode(targetId);
    if (!uploadList) return;
    if (!assets.length) {
      uploadList.appendChild(createDatingTextElement('p', 'dating-muted', '没有可关联的上传资源。'));
      return;
    }
    assets.forEach(function renderAsset(asset, assetIndex) {
      asset = asset || {};
      var item = document.createElement('article');
      item.className = 'dating-upload-item';
      item.appendChild(createDatingTextElement(
        'h4', '', String(assetIndex + 1) + '. ' + (asset.asset_id || 'orphan PUT')
      ));
      item.appendChild(createDatingTextElement(
        'p', 'dating-upload-chain',
        'Prepare ' + (asset.prepare_status || '未知') +
        ' → PUT ' + (asset.put_http_status === null || asset.put_http_status === undefined
          ? '未知' : asset.put_http_status) +
        ' → Complete ' + (asset.complete_status || '未知') +
        ' → Used by Task ' + (asset.used_by_task ? '是' : '否')
      ));
      item.appendChild(createDatingTextElement(
        'p', 'dating-upload-meta',
        '关联状态=' + (asset.upload_state || 'unknown') +
        ' · content_type=' + (asset.content_type || '—') +
        ' · size=' + (asset.size_bytes === null || asset.size_bytes === undefined
          ? '—' : asset.size_bytes + ' bytes')
      ));
      var lines = document.createElement('div');
      lines.className = 'result-tools';
      appendDatingCallLines(lines, asset.prepare_call_id, 'Prepare');
      appendDatingCallLines(lines, asset.put_call_id, 'PUT');
      appendDatingCallLines(lines, asset.complete_call_id, 'Complete');
      if (lines.childNodes && lines.childNodes.length) item.appendChild(lines);
      if (Array.isArray(asset.warnings) && asset.warnings.length) {
        item.appendChild(createDatingTextElement(
          'p', 'dating-muted', 'Warnings: ' + datingCompactValue(asset.warnings)
        ));
      }
      uploadList.appendChild(item);
    });
  }

  /** 展示诊断原文；停滞只改变此摘要，不改变 status_samples。 */
  function renderProgressDiagnostics(diagnostics) {
    var container = clearDatingNode('dating-progress-diagnostics');
    if (!container) return;
    var safeDiagnostics = diagnostics && typeof diagnostics === 'object' ? diagnostics : {};
    var keys = Object.keys(safeDiagnostics);
    if (!keys.length) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', '没有 progress diagnostics。'));
      return;
    }
    var facts = document.createElement('dl');
    facts.className = 'dating-result-summary';
    keys.forEach(function renderDiagnostic(key) {
      appendDatingDefinition(facts, key, datingSchemaValue(safeDiagnostics[key]));
    });
    container.appendChild(facts);
    if (safeDiagnostics.stall_detected) {
      container.appendChild(createDatingTextElement(
        'p', 'dating-muted', '检测到进度停滞；仅展示 diagnostics，所有 Poll 样本仍保留。'
      ));
    }
  }

  /**
   * 渲染上传链路、progress diagnostics 和完整 Poll。
   * 关键约束：直接遍历 taskSnapshot.status_samples，禁止聚合、去重或按停滞省略样本。
   */
  function renderDatingLifecycle(taskSnapshot) {
    var lifecycle = taskSnapshot.lifecycle || {};
    var diagnostics = taskSnapshot.progress_diagnostics || {};
    var metrics = clearDatingNode('dating-lifecycle-metrics');
    var terminalText = lifecycle.terminal === false
      ? '任务未到终态或日志截断'
      : lifecycle.terminal === true ? '任务已到终态' : '终态未知';
    if (metrics) {
      [
        ['生命周期', terminalText],
        ['Poll 次数', lifecycle.poll_count],
        ['不同进度', Array.isArray(diagnostics.distinct_progress_values)
          ? diagnostics.distinct_progress_values.join('、') : '—'],
        ['未变化 Poll', diagnostics.unchanged_poll_count],
        ['任务耗时', lifecycle.duration_ms === null || lifecycle.duration_ms === undefined
          ? '—' : lifecycle.duration_ms + ' ms']
      ].forEach(function renderMetric(entry) {
        appendDatingDefinition(metrics, entry[0], entry[1]);
      });
    }

    var assets = Array.isArray(taskSnapshot.input_assets) ? taskSnapshot.input_assets : [];
    renderDatingUploadList('dating-upload-list', assets);
    renderDatingUploadList('dating-timeline-upload-list', assets);
    renderProgressDiagnostics(diagnostics);

    var timeline = clearDatingNode('dating-task-timeline');
    var samples = Array.isArray(taskSnapshot.status_samples)
      ? taskSnapshot.status_samples : [];
    if (!timeline) return;
    if (!samples.length) {
      timeline.appendChild(createDatingTextElement('li', 'dating-muted', '日志中没有 Poll 状态样本。'));
    }
    samples.forEach(function renderPollSample(sample, sampleIndex) {
      sample = sample || {};
      var item = document.createElement('li');
      item.appendChild(createDatingTextElement(
        'span', 'dating-timeline-sequence', '#' + String(sampleIndex + 1)
      ));
      item.appendChild(createDatingTextElement(
        'span', 'dating-mono', sample.timestamp || '时间未知'
      ));
      item.appendChild(createDatingTextElement(
        'span', '', datingSchemaValue(sample.status) + ' / ' + datingSchemaValue(sample.phase)
      ));
      item.appendChild(createDatingTextElement(
        'span', '', sample.progress_percent === null || sample.progress_percent === undefined
          ? '进度未知' : String(sample.progress_percent) + '%'
      ));
      item.appendChild(createDatingLineButton(sample.line_start, sample.line_end, 'Poll'));
      timeline.appendChild(item);
    });
  }

  /** 将当前响应拆入五个 panel；字段树保持懒加载，calls 在 Interfaces 中完整可见。 */
  function renderDatingAnalysis(data) {
    var taskSnapshot = data.task_snapshot || {};
    var lifecycle = taskSnapshot.lifecycle || {};
    var baseSummary = data.summary || {};
    var inputAssets = Array.isArray(taskSnapshot.input_assets) ? taskSnapshot.input_assets : [];
    var summary = {
      verdict: data.verdict,
      task_type: taskSnapshot.task_type,
      task_id: taskSnapshot.task_id,
      result_id: findDatingResultId(data.calls, taskSnapshot.result_call_id),
      schema_version: taskSnapshot.schema_version,
      final_status: lifecycle.final_status,
      duration_ms: lifecycle.duration_ms,
      gateway_call_count: baseSummary.gateway_call_count,
      upload_call_count: baseSummary.upload_call_count,
      asset_count: inputAssets.length,
      poll_count: lifecycle.poll_count,
      http_error_count: baseSummary.http_error_count,
      business_error_count: baseSummary.business_error_count,
      check_fail_count: baseSummary.check_fail_count,
      check_warn_count: baseSummary.check_warn_count
    };

    showDatingSuccessSurfaces();
    var state = getElement('dating-state');
    if (state) {
      state.className = 'dating-state success';
      state.textContent = '分析完成：' + (data.verdict || '完成') + '。';
    }
    renderDatingSummary(summary);
    renderDatingLifecycle(taskSnapshot);
    renderDatingResult(taskSnapshot);
    renderDatingFields(taskSnapshot.result_fields || []);
    setupDatingLazySections(taskSnapshot, data.calls || []);
    datingCallsMaterialized = true;
    renderDatingCalls(data.calls || [], pendingDatingPutAssetMap);
    renderDatingChecks(data.checks || []);
    renderDatingParseWarnings(data.parse_warnings || []);
    var report = getElement('dating-report');
    if (report) report.textContent = latestDatingReport;
    setText('dating-status', (data.verdict || '完成') + ' · task_id=' + (taskSnapshot.task_id || '—'));
    updateDatingExportButtons(false);
  }


  /** 渲染总体 verdict、下一步和生命周期/接口计数摘要。 */
  function renderDatingSummary(summary) {
    var verdictLabels = {
      NO_ISSUES: '未发现问题',
      WARNINGS_FOUND: '存在需要确认项',
      ISSUES_FOUND: '发现已确认异常',
      INCOMPLETE_LOG: '日志证据不足'
    };
    var verdictClasses = {
      NO_ISSUES: 'no-issues',
      WARNINGS_FOUND: 'warnings',
      ISSUES_FOUND: 'issues',
      INCOMPLETE_LOG: 'incomplete'
    };
    var nextActions = {
      NO_ISSUES: '下一步：可继续核对生命周期和最终字段。',
      WARNINGS_FOUND: '下一步：先核对 WARN 检查项及其原日志证据。',
      ISSUES_FOUND: '下一步：先处理 FAIL 检查项，再核对关联调用。',
      INCOMPLETE_LOG: '下一步：补齐缺失的请求、响应或任务终态日志。'
    };
    var verdict = summary.verdict || 'INCOMPLETE_LOG';
    var verdictPanel = getElement('dating-verdict');
    if (verdictPanel) verdictPanel.className = 'dating-verdict ' + (verdictClasses[verdict] || 'incomplete');
    setText('dating-summary-heading', verdictLabels[verdict] || verdict);
    setText('dating-verdict-detail',
      '最终状态 ' + datingSchemaValue(summary.final_status) +
      ' · FAIL ' + String(summary.check_fail_count || 0) +
      ' · WARN ' + String(summary.check_warn_count || 0));
    setText('dating-next-action', nextActions[verdict] || nextActions.INCOMPLETE_LOG);

    var container = clearDatingNode('dating-summary');
    if (container) {
      [
        ['任务类型', summary.task_type],
        ['task_id', summary.task_id],
        ['result_id', summary.result_id],
        ['schema_version', summary.schema_version],
        ['最终状态', summary.final_status],
        ['任务耗时', summary.duration_ms === null || summary.duration_ms === undefined
          ? '—' : summary.duration_ms + ' ms'],
        ['Gateway', summary.gateway_call_count],
        ['PUT', summary.upload_call_count],
        ['Asset', summary.asset_count],
        ['Poll', summary.poll_count],
        ['HTTP / Business Error', String(summary.http_error_count || 0) +
          ' / ' + String(summary.business_error_count || 0)],
        ['FAIL / WARN', String(summary.check_fail_count || 0) +
          ' / ' + String(summary.check_warn_count || 0)]
      ].forEach(function renderSummaryItem(entry) {
        appendDatingDefinition(container, entry[0], datingSchemaValue(entry[1]));
      });
    }
    setDatingResultHeader('Dating · ' + (verdictLabels[verdict] || verdict),
      'task_id=' + datingSchemaValue(summary.task_id) +
      ' · schema=' + datingSchemaValue(summary.schema_version));
  }

  /** details 首次展开才生成长数组，业务字段仍只来自已知 Schema 响应。 */
  function appendDatingLazyDetails(parent, summaryText, renderer) {
    var details = document.createElement('details');
    details.className = 'dating-result-section';
    var summary = document.createElement('summary');
    appendDatingText(summary, summaryText);
    var body = document.createElement('div');
    var materialized = false;
    details.addEventListener('toggle', function materializeOnOpen() {
      if (!details.open || materialized) return;
      materialized = true;
      body.appendChild(renderer());
    });
    details.appendChild(summary);
    details.appendChild(body);
    parent.appendChild(details);
  }

  /** 返回按 rank 升序、同 rank 保持服务端顺序的角色副本。 */
  function sortDatingRolesByRank(roles) {
    return (Array.isArray(roles) ? roles : []).map(function mapRole(role, index) {
      return {role: role || {}, index: index};
    }).sort(function sortRoles(left, right) {
      var leftRank = Number(left.role.rank);
      var rightRank = Number(right.role.rank);
      leftRank = Number.isFinite(leftRank) ? leftRank : Number.POSITIVE_INFINITY;
      rightRank = Number.isFinite(rightRank) ? rightRank : Number.POSITIVE_INFINITY;
      return leftRank === rightRank ? left.index - right.index : leftRank - rightRank;
    }).map(function unwrapRole(entry) {
      return entry.role;
    });
  }

  /** Reply role/top pick/replies/alternatives 的事实视图。 */
  function renderDatingReplyRole(role) {
    var body = document.createElement('div');
    var facts = document.createElement('dl');
    facts.className = 'dating-result-summary';
    [
      ['role_id', role.role_id],
      ['name', role.role_name],
      ['rank', role.rank],
      ['selection_rule_id', role.selection_rule_id],
      ['reasons', role.selection_reasons],
      ['coach note', role.coach_note]
    ].forEach(function renderRoleFact(entry) {
      appendDatingDefinition(facts, entry[0], datingSchemaValue(entry[1]));
    });
    body.appendChild(facts);

    body.appendChild(createDatingTextElement('h4', '', 'Replies'));
    var replies = role.replies;
    if (!Array.isArray(replies)) {
      body.appendChild(createDatingTextElement('p', 'dating-muted', datingSchemaValue(replies)));
    } else if (!replies.length) {
      body.appendChild(createDatingTextElement('p', 'dating-muted', '空数组 []'));
    } else {
      var tableWrap = document.createElement('div');
      tableWrap.className = 'table-scroll';
      var table = document.createElement('table');
      table.className = 'dating-field-table';
      var head = document.createElement('thead');
      var headRow = document.createElement('tr');
      ['reply_id', 'text', 'is_top_pick'].forEach(function renderReplyHeading(label) {
        headRow.appendChild(createDatingTextElement('th', '', label));
      });
      head.appendChild(headRow);
      table.appendChild(head);
      var tableBody = document.createElement('tbody');
      replies.forEach(function renderReply(reply) {
        reply = reply || {};
        var row = document.createElement('tr');
        row.appendChild(createDatingTextElement('td', 'dating-mono', datingSchemaValue(reply.reply_id)));
        row.appendChild(createDatingTextElement('td', 'dating-value-cell', datingSchemaValue(reply.text)));
        row.appendChild(createDatingTextElement('td', '', datingSchemaValue(reply.is_top_pick)));
        tableBody.appendChild(row);
      });
      table.appendChild(tableBody);
      tableWrap.appendChild(table);
      body.appendChild(tableWrap);
    }

    body.appendChild(createDatingTextElement('h4', '', 'top_pick 引用'));
    var topPick = role.top_pick;
    if (!topPick || typeof topPick !== 'object' || Array.isArray(topPick)) {
      body.appendChild(createDatingTextElement('p', 'dating-muted', datingSchemaValue(topPick)));
    } else {
      var topPickFacts = document.createElement('dl');
      topPickFacts.className = 'dating-result-summary';
      appendDatingDefinition(topPickFacts, 'reply_id', datingSchemaValue(topPick.reply_id));
      appendDatingDefinition(topPickFacts, 'text', datingSchemaValue(topPick.text));
      body.appendChild(topPickFacts);
    }

    body.appendChild(createDatingTextElement('h4', '', 'alternatives 引用'));
    var alternatives = role.alternatives;
    var alternativeList = document.createElement('ul');
    if (!Array.isArray(alternatives)) {
      alternativeList.appendChild(createDatingTextElement('li', 'dating-muted', datingSchemaValue(alternatives)));
    } else if (!alternatives.length) {
      alternativeList.appendChild(createDatingTextElement('li', 'dating-muted', '空数组 []'));
    }
    (Array.isArray(alternatives) ? alternatives : []).forEach(function renderAlternative(alternative) {
      alternative = alternative || {};
      alternativeList.appendChild(createDatingTextElement(
        'li', '', datingSchemaValue(alternative.reply_id) + ' · ' + datingSchemaValue(alternative.text)
      ));
    });
    body.appendChild(alternativeList);
    return body;
  }

  function renderDatingReplyResult(resultPayload) {
    var container = document.createElement('div');
    if (!resultPayload || typeof resultPayload !== 'object' || Array.isArray(resultPayload)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', 'Reply Result 不是对象，专属视图不可用。'));
      return container;
    }
    var rolesValue = resultPayload.roles;
    var roles = sortDatingRolesByRank(rolesValue);
    if (!Array.isArray(rolesValue)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', 'roles：' + datingSchemaValue(rolesValue)));
    } else if (!roles.length) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', 'roles：空数组 []'));
    }
    roles.forEach(function renderRole(role) {
      appendDatingLazyDetails(
        container,
        'rank=' + datingSchemaValue(role.rank) + ' · ' +
          datingSchemaValue(role.role_id) + ' · ' + datingSchemaValue(role.role_name),
        function renderRoleDetails() { return renderDatingReplyRole(role); }
      );
    });
    return container;
  }

  /** Relationship Analysis Overview 的 documented 字段。 */
  function renderDatingAnalysisOverview(overview) {
    var container = document.createElement('section');
    container.appendChild(createDatingTextElement('h4', '', 'Overview 原文'));
    var facts = document.createElement('dl');
    facts.className = 'dating-result-summary';
    [
      ['insight_title', overview.insight_title],
      ['insight_summary', overview.insight_summary],
      ['relationship_stage', overview.relationship_stage],
      ['current_state', overview.current_state],
      ['reliability_level', overview.reliability_level]
    ].forEach(function renderOverviewFact(entry) {
      appendDatingDefinition(facts, entry[0], datingSchemaValue(entry[1]));
    });
    container.appendChild(facts);

    container.appendChild(createDatingTextElement('h4', '', 'next_steps'));
    var nextSteps = overview.next_steps;
    if (!nextSteps || typeof nextSteps !== 'object' || Array.isArray(nextSteps)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', datingSchemaValue(nextSteps)));
    } else {
      var nextStepFacts = document.createElement('dl');
      nextStepFacts.className = 'dating-result-summary';
      ['action', 'communication', 'observation'].forEach(function renderNextStep(key) {
        appendDatingDefinition(nextStepFacts, key, datingSchemaValue(nextSteps[key]));
      });
      container.appendChild(nextStepFacts);
    }

    container.appendChild(createDatingTextElement('h4', '', 'Dashboard'));
    var dashboard = overview.dashboard;
    if (!dashboard || typeof dashboard !== 'object' || Array.isArray(dashboard) ||
        !Object.keys(dashboard).length) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', datingSchemaValue(dashboard)));
      return container;
    }
    [
      ['message_counts', ['user', 'other']],
      ['effort', ['you_score', 'them_score']],
      ['match_degree', ['score', 'level']],
      ['keywords', ['user_focus', 'other_focus']]
    ].forEach(function renderDashboardGroup(group) {
      container.appendChild(createDatingTextElement('h5', '', group[0]));
      var groupValue = dashboard[group[0]];
      var groupFacts = document.createElement('dl');
      groupFacts.className = 'dating-result-summary';
      if (!groupValue || typeof groupValue !== 'object' || Array.isArray(groupValue) ||
          !Object.keys(groupValue).length) {
        appendDatingDefinition(groupFacts, '状态', datingSchemaValue(groupValue));
      } else {
        group[1].forEach(function renderDashboardFact(key) {
          appendDatingDefinition(groupFacts, key, datingSchemaValue(groupValue[key]));
        });
      }
      container.appendChild(groupFacts);
    });
    return container;
  }

  function renderDatingSignalItems(items) {
    var container = document.createElement('div');
    if (!Array.isArray(items)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', datingSchemaValue(items)));
      return container;
    }
    if (!items.length) container.appendChild(createDatingTextElement('p', 'dating-muted', '空数组 []'));
    items.forEach(function renderSignal(item) {
      item = item || {};
      var facts = document.createElement('dl');
      facts.className = 'dating-result-summary';
      appendDatingDefinition(facts, 'signal_id', datingSchemaValue(item.signal_id));
      appendDatingDefinition(facts, 'text', datingSchemaValue(item.text));
      appendDatingDefinition(facts, 'evidence_message_ids', datingSchemaValue(item.evidence_message_ids));
      container.appendChild(facts);
    });
    return container;
  }

  function renderDatingEventItems(items) {
    var container = document.createElement('div');
    if (!Array.isArray(items)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', datingSchemaValue(items)));
      return container;
    }
    if (!items.length) container.appendChild(createDatingTextElement('p', 'dating-muted', '空数组 []'));
    items.forEach(function renderEvent(item) {
      item = item || {};
      var facts = document.createElement('dl');
      facts.className = 'dating-result-summary';
      appendDatingDefinition(facts, 'event_id', datingSchemaValue(item.event_id));
      appendDatingDefinition(facts, 'event', datingSchemaValue(item.event));
      appendDatingDefinition(facts, 'takeaway', datingSchemaValue(item.takeaway));
      appendDatingDefinition(facts, 'evidence_message_ids', datingSchemaValue(item.evidence_message_ids));
      container.appendChild(facts);
    });
    return container;
  }

  /** Relationship Analysis 的 overview/signals/events 事实视图。 */
  function renderDatingAnalysisResult(resultPayload) {
    var container = document.createElement('div');
    if (!resultPayload || typeof resultPayload !== 'object' || Array.isArray(resultPayload)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', 'Analysis Result 不是对象，专属视图不可用。'));
      return container;
    }
    var overview = resultPayload.overview;
    if (!overview || typeof overview !== 'object' || Array.isArray(overview)) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', 'Overview：' + datingSchemaValue(overview)));
    } else {
      container.appendChild(renderDatingAnalysisOverview(overview));
    }

    var signals = resultPayload.chat_signals;
    signals = signals && typeof signals === 'object' && !Array.isArray(signals) ? signals : {};
    container.appendChild(createDatingTextElement(
      'p', 'dating-muted', 'signal_summary：' + datingSchemaValue(signals.signal_summary)
    ));
    [
      ['positive_signals', signals.positive_signals],
      ['watch_signals', signals.watch_signals],
      ['risk_signals', signals.risk_signals]
    ].forEach(function renderSignalGroup(group) {
      appendDatingLazyDetails(
        container,
        group[0] + ' · ' + (Array.isArray(group[1]) ? group[1].length : datingSchemaValue(group[1])),
        function renderSignals() { return renderDatingSignalItems(group[1]); }
      );
    });

    var events = resultPayload.key_events;
    events = events && typeof events === 'object' && !Array.isArray(events) ? events : {};
    [
      ['turning_points', events.turning_points],
      ['hidden_meanings', events.hidden_meanings],
      ['did_well', events.did_well],
      ['could_improve', events.could_improve]
    ].forEach(function renderEventGroup(group) {
      appendDatingLazyDetails(
        container,
        group[0] + ' · ' + (Array.isArray(group[1]) ? group[1].length : datingSchemaValue(group[1])),
        function renderEvents() { return renderDatingEventItems(group[1]); }
      );
    });
    return container;
  }

  /** 根据 Schema badge 选择业务视图，并始终写入已脱敏 result_payload 的原始 JSON。 */
  function renderDatingResult(taskSnapshot) {
    var schemaVersion = taskSnapshot.schema_version || 'UNKNOWN_SCHEMA';
    var schemaStatus = taskSnapshot.schema_status || 'UNKNOWN_SCHEMA';
    var knownReply = schemaVersion === 'dating.reply_generation.v1' && schemaStatus !== 'UNKNOWN_SCHEMA';
    var knownAnalysis = schemaVersion === 'dating.relationship_analysis.v1' && schemaStatus !== 'UNKNOWN_SCHEMA';
    setText('dating-result-heading', knownReply
      ? 'Reply v1 业务摘要' : knownAnalysis
        ? 'Analysis v1 业务摘要' : '未知 Schema · 通用字段树');
    setText('dating-schema-status', schemaVersion + ' · ' + schemaStatus);

    var resultSummary = clearDatingNode('dating-result-summary');
    var sectionsContainer = clearDatingNode('dating-result-sections');
    if (!knownReply && !knownAnalysis && sectionsContainer) {
      sectionsContainer.appendChild(createDatingTextElement(
        'p', 'dating-muted', 'UNKNOWN_SCHEMA：仅提供通用字段树和字段索引。'
      ));
    }

    var summary = taskSnapshot.result_summary || {};
    var summaryKeys = Object.keys(summary);
    if (resultSummary && !summaryKeys.length) {
      resultSummary.appendChild(createDatingTextElement('div', 'dating-muted', '没有可展示的 Schema 专属摘要。'));
    }
    if (resultSummary) {
      summaryKeys.forEach(function renderResultSummary(key) {
        appendDatingDefinition(resultSummary, key, datingSchemaValue(summary[key]));
      });
    }

    var resultPayload = taskSnapshot.result_payload;
    if (sectionsContainer && (knownReply || knownAnalysis)) {
      sectionsContainer.appendChild(knownReply
        ? renderDatingReplyResult(resultPayload)
        : renderDatingAnalysisResult(resultPayload));
    }

    var rawJson = getElement('dating-raw-result-json');
    if (rawJson) {
      var safeRawPayload = resultPayload === undefined ? null : resultPayload;
      try {
        rawJson.textContent = JSON.stringify(safeRawPayload, null, 2);
      } catch (error) {
        rawJson.textContent = String(safeRawPayload);
      }
    }
  }

  /** 将 presence 映射为稳定文本和固定样式类。 */
  function createDatingPresence(field) {
    var node = document.createElement('span');
    var presence = field && field.presence ? field.presence : 'UNKNOWN';
    var className = 'dating-presence';
    if (presence === 'MISSING') className += ' missing';
    if (presence === 'NULL') className += ' null';
    if (field && field.schema_known === false) className += ' unknown';
    node.className = className;
    node.textContent = presence + (field && field.schema_known === false ? ' · 未知字段' : '');
    return node;
  }

  /** 对字段值显示 PRD 约定的 MISSING/null/empty 语义。 */
  function datingFieldValue(field) {
    if (!field) return '—';
    if (field.presence === 'MISSING') return '字段缺失';
    if (field.presence === 'NULL') return 'null';
    if (field.presence === 'EMPTY_STRING') return '空字符串';
    if (field.presence === 'EMPTY_ARRAY') return '空数组 []';
    if (field.presence === 'EMPTY_OBJECT') return '空对象 {}';
    if (field.value_type === 'array' && Array.isArray(field.value)) {
      return '数组，共 ' + field.value.length + ' 项';
    }
    if (field.value_type === 'object' && field.value && typeof field.value === 'object') {
      return '对象，共 ' + Object.keys(field.value).length + ' 个键';
    }
    return datingCompactValue(field.value);
  }

  /**
   * 生成可展开的字段树；每个 parent_path 首次最多渲染 20 个子节点，避免大结果一次建树。
   */
  function renderDatingFieldTree(fields) {
    var safeFields = Array.isArray(fields) ? fields : [];
    var container = clearDatingNode('dating-field-tree');
    if (!container) return;
    var childrenByParent = Object.create(null);

    safeFields.forEach(function groupField(field) {
      field = field || {};
      var parentKey = field.parent_path === null || field.parent_path === undefined
        ? '__ROOT__' : String(field.parent_path);
      if (!childrenByParent[parentKey]) childrenByParent[parentKey] = [];
      childrenByParent[parentKey].push(field);
    });

    if (!safeFields.length) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', 'Result 字段树为空。'));
      return;
    }

    function renderChildren(parentPath, list) {
      var key = parentPath === null ? '__ROOT__' : String(parentPath);
      var children = childrenByParent[key] || [];
      var limit = datingTreeLimits[key] || 20;
      children.slice(0, limit).forEach(function renderField(field) {
        var item = document.createElement('li');
        item.className = 'dating-field-node';
        var line = document.createElement('div');
        line.className = 'dating-field-node-line';
        var fieldChildren = childrenByParent[String(field.path)] || [];
        var pathButton = document.createElement('button');
        pathButton.type = 'button';
        pathButton.className = 'dating-path-button';
        pathButton.textContent = field.path || field.key || '未命名字段';
        pathButton.setAttribute('aria-expanded', fieldChildren.length && datingExpandedPaths[field.path]
          ? 'true' : 'false');
        pathButton.addEventListener('click', function toggleFieldChildren() {
          if (!fieldChildren.length) return;
          datingExpandedPaths[field.path] = !datingExpandedPaths[field.path];
          renderDatingFieldTree(safeFields);
        });
        line.appendChild(pathButton);
        line.appendChild(createDatingPresence(field));
        line.appendChild(createDatingTextElement('span', 'dating-muted', datingFieldValue(field)));
        var source = field.source || {};
        line.appendChild(createDatingLineButton(
          source.line_start, source.line_end, source.location_precision || 'Source'
        ));
        item.appendChild(line);
        if (fieldChildren.length && datingExpandedPaths[field.path]) {
          var nested = document.createElement('ul');
          renderChildren(field.path, nested);
          item.appendChild(nested);
        }
        list.appendChild(item);
      });

      if (children.length > limit) {
        var moreItem = document.createElement('li');
        var moreButton = document.createElement('button');
        moreButton.type = 'button';
        moreButton.className = 'dating-more-button';
        moreButton.textContent = '加载后续 ' + Math.min(20, children.length - limit) +
          ' 个节点（剩余 ' + (children.length - limit) + '）';
        moreButton.addEventListener('click', function showMoreTreeChildren() {
          datingTreeLimits[key] = limit + 20;
          renderDatingFieldTree(safeFields);
        });
        moreItem.appendChild(moreButton);
        list.appendChild(moreItem);
      }
    }

    var rootList = document.createElement('ul');
    rootList.className = 'dating-field-tree';
    renderChildren(null, rootList);
    container.appendChild(rootList);
  }

  /** 展开字段 parent_path 祖先，并把字段树带入视区。 */
  function expandDatingParentPath(parentPath) {
    var currentPath = parentPath;
    var guard = 0;
    while (currentPath && guard < 50) {
      datingExpandedPaths[currentPath] = true;
      var parentField = latestDatingFields.find(function findParent(field) {
        return field.path === currentPath;
      });
      currentPath = parentField ? parentField.parent_path : null;
      guard += 1;
    }
    var details = getElement('dating-field-tree-details');
    if (details) details.open = true;
    if (datingFieldTreeMaterialized) renderDatingFieldTree(latestDatingFields);
    else materializeDatingFieldTreeOnce();
    if (details && typeof details.scrollIntoView === 'function') details.scrollIntoView({block: 'start'});
  }

  function resetAndRenderDatingFields() {
    datingVisibleFieldCount = 200;
    renderDatingFields();
  }

  function showMoreDatingFields() {
    datingVisibleFieldCount += 200;
    renderDatingFields();
  }

  /** 字段索引支持 presence 筛选、path/value 搜索和固定批量数量。 */
  function renderDatingFields(fields) {
    if (Array.isArray(fields)) {
      latestDatingFields = fields.slice();
      datingVisibleFieldCount = 200;
    }
    var filterElement = getElement('dating-field-filter');
    var searchElement = getElement('dating-field-search');
    var filter = filterElement ? String(filterElement.value || 'ALL') : 'ALL';
    var query = searchElement ? String(searchElement.value || '').trim().toLowerCase() : '';
    var filtered = latestDatingFields.filter(function filterField(field) {
      field = field || {};
      var presenceMatches = filter === 'ALL' || (filter === 'UNKNOWN_SCHEMA_FIELD'
        ? field.schema_known === false : field.presence === filter);
      if (!presenceMatches) return false;
      if (!query) return true;
      return String(field.path || '').toLowerCase().indexOf(query) !== -1 ||
        datingCompactValue(field.value).toLowerCase().indexOf(query) !== -1;
    });
    var visible = filtered.slice(0, datingVisibleFieldCount);
    var body = clearDatingNode('dating-field-table-body');
    if (!body) return;

    if (!visible.length) {
      var emptyRow = document.createElement('tr');
      var emptyCell = createDatingTextElement('td', 'dating-muted', '当前筛选条件下没有字段。');
      emptyCell.colSpan = 5;
      emptyRow.appendChild(emptyCell);
      body.appendChild(emptyRow);
    }

    visible.forEach(function renderFieldRow(field) {
      field = field || {};
      var row = document.createElement('tr');
      var pathCell = document.createElement('td');
      var pathButton = document.createElement('button');
      pathButton.type = 'button';
      pathButton.className = 'dating-path-button';
      pathButton.textContent = field.path || '未命名字段';
      pathButton.addEventListener('click', function focusFieldPath() {
        expandDatingParentPath(field.parent_path || field.path);
      });
      pathCell.appendChild(pathButton);
      if (field.label && field.label !== field.key) {
        pathCell.appendChild(createDatingTextElement('div', 'dating-muted', field.label));
      }
      row.appendChild(pathCell);
      row.appendChild(createDatingTextElement('td', 'dating-mono', field.value_type || 'unknown'));
      var presenceCell = document.createElement('td');
      presenceCell.appendChild(createDatingPresence(field));
      row.appendChild(presenceCell);
      row.appendChild(createDatingTextElement('td', 'dating-value-cell', datingFieldValue(field)));
      var sourceCell = document.createElement('td');
      var source = field.source || {};
      sourceCell.appendChild(createDatingTextElement(
        'div', 'dating-mono', (source.method || 'method 未知') +
          (source.call_id ? ' · ' + source.call_id : '')
      ));
      sourceCell.appendChild(createDatingLineButton(
        source.line_start, source.line_end, source.location_precision || 'Source'
      ));
      row.appendChild(sourceCell);
      body.appendChild(row);
    });

    setText('dating-field-count', '匹配 ' + filtered.length + ' / ' + latestDatingFields.length +
      '，当前显示 ' + visible.length);
    var moreButton = getElement('dating-field-more');
    if (moreButton) {
      moreButton.hidden = visible.length >= filtered.length;
      moreButton.textContent = moreButton.hidden ? '显示更多字段'
        : '显示更多（剩余 ' + (filtered.length - visible.length) + '）';
    }
  }

  /** 为共享 drawer 组织完整、可追溯且仅含 API 脱敏值的调用模型。 */
  function buildDatingDrawerPayload(call, putAssetMap) {
    call = call || {};
    var request = call.request || {};
    var response = call.response || {};
    var requestLine = {start: request.line_start, end: request.line_end};
    var responseLine = {start: response.line_start, end: response.line_end};
    var requestHeaders = request.headers || {};
    var responseHeaders = response.headers || {};
    return {
      method: call.method_name,
      service: call.service_name,
      transport: call.transport,
      result_class: call.result_class,
      parse_status: call.parse_status,
      request_line: requestLine,
      response_line: responseLine,
      http: {status: response.http_status},
      gateway: response.gateway || null,
      sub_response: response.sub_response || null,
      elapsed_ms: response.elapsed_ms,
      request: {
        timestamp: request.timestamp,
        line: requestLine,
        params: request.params || {},
        headers: requestHeaders
      },
      response: {
        timestamp: response.timestamp,
        line: responseLine,
        data: response.data === undefined ? null : response.data,
        headers: responseHeaders
      },
      headers: {request: requestHeaders, response: responseHeaders},
      task_or_asset: datingCallReference(call, putAssetMap),
      call_id: call.call_id,
      sequence: call.sequence,
      warnings: Array.isArray(response.warnings) ? response.warnings : (call.warnings || [])
    };
  }

  /** 点击接口行时才构造详情并交给共享 drawer；不在表格内复制 JSON 详情。 */
  function openDatingCallDrawer(call, putAssetMap, trigger) {
    var detailMaterialized = false;
    var payload = null;
    if (!detailMaterialized) {
      payload = buildDatingDrawerPayload(call, putAssetMap);
      detailMaterialized = true;
    }
    if (typeof api.openInterfaceDrawer === 'function') {
      api.openInterfaceDrawer(payload, trigger);
    } else if (typeof api.showActionMessage === 'function') {
      api.showActionMessage('接口详情抽屉不可用。', true);
    }
    return payload;
  }

  /** 完整 calls 表：HTTP、Gateway、SubResponse 三层状态都独立展示。 */
  function renderDatingCalls(calls) {
    var safeCalls = Array.isArray(calls) ? calls : [];
    var putAssetMap = arguments.length > 1 && arguments[1]
      ? arguments[1] : Object.create(null);
    var body = clearDatingNode('dating-interface-table-body');
    var columnCount = 13;
    setText('dating-call-count', '共 ' + safeCalls.length + ' 条');
    if (!body) return;

    if (!safeCalls.length) {
      var emptyRow = document.createElement('tr');
      var emptyCell = createDatingTextElement('td', 'dating-muted', '没有可展示的接口调用。');
      emptyCell.colSpan = columnCount;
      emptyRow.appendChild(emptyCell);
      body.appendChild(emptyRow);
      return;
    }

    safeCalls.forEach(function renderCall(call, callIndex) {
      call = call || {};
      var request = call.request || {};
      var response = call.response || {};
      var gateway = response.gateway || {};
      var subResponse = response.sub_response || {};
      var row = document.createElement('tr');
      var sequenceCell = document.createElement('td');
      var trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'dating-row-toggle';
      trigger.textContent = String(call.sequence === undefined ? callIndex + 1 : call.sequence);
      trigger.setAttribute('aria-expanded', 'false');
      trigger.setAttribute('aria-label', '打开接口详情');
      sequenceCell.appendChild(trigger);
      row.appendChild(sequenceCell);
      [
        request.timestamp || '—',
        call.service_name || '—',
        call.method_name || '—',
        call.transport || '—',
        response.http_status === null || response.http_status === undefined
          ? 'HTTP 未知' : 'HTTP ' + response.http_status,
        gateway.code === null || gateway.code === undefined
          ? 'Gateway 未知' : 'code=' + gateway.code,
        subResponse.success === null || subResponse.success === undefined
          ? 'SubResponse 未知'
          : 'success=' + String(subResponse.success) + ' / code=' + datingCompactValue(subResponse.code),
        call.result_class || 'unknown',
        call.parse_status || 'unknown',
        response.elapsed_ms === null || response.elapsed_ms === undefined
          ? '—' : response.elapsed_ms + ' ms',
        datingCallReference(call, putAssetMap)
      ].forEach(function renderCallCell(value, cellIndex) {
        row.appendChild(createDatingTextElement(
          'td', cellIndex === 1 || cellIndex === 2 || cellIndex === 10 ? 'dating-mono' : '', value
        ));
      });
      var lineCell = document.createElement('td');
      if (request.line_start !== undefined && request.line_start !== null) {
        lineCell.appendChild(createDatingLineButton(request.line_start, request.line_end, '请求'));
      }
      if (response.line_start !== undefined && response.line_start !== null) {
        lineCell.appendChild(createDatingLineButton(response.line_start, response.line_end, '响应'));
      }
      if (!lineCell.childNodes || !lineCell.childNodes.length) appendDatingText(lineCell, '日志证据不足');
      row.appendChild(lineCell);
      body.appendChild(row);
      trigger.addEventListener('click', function openCallDetails() {
        openDatingCallDrawer(call, putAssetMap, trigger);
      });
    });
  }

  function datingCheckOrder(outcome) {
    var order = {FAIL: 0, WARN: 1, UNKNOWN: 2, PASS: 3, NA: 4, NOT_APPLICABLE: 4};
    return Object.prototype.hasOwnProperty.call(order, outcome) ? order[outcome] : 5;
  }

  function normalizeDatingOutcome(outcome) {
    var value = String(outcome || 'UNKNOWN').toUpperCase();
    return ['FAIL', 'WARN', 'UNKNOWN', 'PASS', 'NA', 'NOT_APPLICABLE'].indexOf(value) !== -1
      ? value : 'UNKNOWN';
  }

  function renderDatingCheckItems(checks) {
    var container = clearDatingNode('dating-check-list');
    if (!container) return;
    var filterElement = getElement('dating-check-filter');
    var filter = filterElement ? String(filterElement.value || 'ALL').toUpperCase() : 'ALL';
    var safeChecks = (Array.isArray(checks) ? checks : []).map(function preserveCheck(check, index) {
      return {check: check || {}, index: index};
    }).sort(function sortChecks(left, right) {
      return datingCheckOrder(normalizeDatingOutcome(left.check.outcome)) -
        datingCheckOrder(normalizeDatingOutcome(right.check.outcome)) || left.index - right.index;
    }).filter(function filterCheck(entry) {
      var outcome = normalizeDatingOutcome(entry.check.outcome);
      return filter === 'ALL' || outcome === filter ||
        (filter === 'NA' && outcome === 'NOT_APPLICABLE');
    });
    if (!safeChecks.length) {
      container.appendChild(createDatingTextElement('p', 'dating-muted', '当前筛选条件下没有规则检查。'));
      return;
    }

    safeChecks.forEach(function renderCheck(entry) {
      var check = entry.check;
      var outcome = normalizeDatingOutcome(check.outcome);
      var details = document.createElement('details');
      details.className = 'dating-check ' + outcome.toLowerCase();
      details.open = outcome === 'FAIL' || outcome === 'WARN';
      var summary = document.createElement('summary');
      summary.appendChild(createDatingTextElement('span', 'check-outcome', outcome === 'NOT_APPLICABLE' ? 'NA' : outcome));
      appendDatingText(summary, ' · ' + (check.rule_id || 'UNKNOWN-RULE') +
        ' · ' + (check.title || '未命名检查'));
      details.appendChild(summary);
      var body = document.createElement('div');
      body.className = 'dating-check-body';
      var actualGroup = document.createElement('div');
      actualGroup.appendChild(createDatingTextElement('strong', '', 'Actual'));
      actualGroup.appendChild(createDatingTextElement('pre', '', check.actual));
      body.appendChild(actualGroup);
      var expectedGroup = document.createElement('div');
      expectedGroup.appendChild(createDatingTextElement('strong', '', 'Expected'));
      expectedGroup.appendChild(createDatingTextElement('pre', '', check.expected));
      body.appendChild(expectedGroup);
      body.appendChild(createDatingTextElement('strong', '', 'Evidence'));
      var evidenceList = document.createElement('ul');
      evidenceList.className = 'dating-evidence-list';
      var evidence = Array.isArray(check.evidence) ? check.evidence : [];
      if (!evidence.length) evidenceList.appendChild(createDatingTextElement('li', 'dating-evidence-item', '日志证据不足'));
      evidence.forEach(function renderEvidence(item) {
        item = item || {};
        var evidenceItem = document.createElement('li');
        evidenceItem.className = 'dating-evidence-item';
        evidenceItem.appendChild(createDatingTextElement(
          'div', 'dating-mono', (item.method || item.call_id || '调用未知') +
            ' · ' + (item.json_path || '路径未知')
        ));
        evidenceItem.appendChild(createDatingTextElement('div', 'dating-value-cell', datingCompactValue(item.value)));
        evidenceItem.appendChild(createDatingLineButton(item.line_start, item.line_end, '证据'));
        evidenceList.appendChild(evidenceItem);
      });
      body.appendChild(evidenceList);
      details.appendChild(body);
      container.appendChild(details);
    });
  }

  /** checks 筛选由固定选择器驱动，排序只使用服务端 outcome，不重新计算规则。 */
  function renderDatingChecks(checks) {
    latestDatingChecks = Array.isArray(checks) ? checks.slice() : [];
    renderDatingCheckItems(latestDatingChecks);
  }

  function renderDatingParseWarnings(warnings) {
    latestDatingParseWarnings = Array.isArray(warnings) ? warnings.slice() : [];
    var list = clearDatingNode('dating-parse-warnings');
    setText('dating-warning-count', '共 ' + latestDatingParseWarnings.length + ' 条');
    if (!list) return;
    if (!latestDatingParseWarnings.length) {
      list.appendChild(createDatingTextElement('li', 'dating-muted', '没有解析警告。'));
      return;
    }
    latestDatingParseWarnings.forEach(function renderWarning(warning) {
      var item = document.createElement('li');
      item.className = 'dating-evidence-item';
      appendDatingText(item, datingCompactValue(warning));
      if (warning && typeof warning === 'object' && warning.line_start) {
        item.appendChild(createDatingLineButton(warning.line_start, warning.line_end, '警告'));
      }
      list.appendChild(item);
    });
  }


  function copyDatingReport() {
    if (!latestDatingReport) return Promise.resolve(false);
    var clipboard = global.navigator && global.navigator.clipboard;
    if (!clipboard || typeof clipboard.writeText !== 'function') {
      if (typeof api.showActionMessage === 'function') api.showActionMessage('复制失败，请检查浏览器剪贴板权限。', true);
      return Promise.resolve(false);
    }
    return clipboard.writeText(latestDatingReport).then(function copySucceeded() {
      if (typeof api.showActionMessage === 'function') api.showActionMessage('Dating Markdown 报告已复制。', false);
      return true;
    }).catch(function copyFailed() {
      if (typeof api.showActionMessage === 'function') api.showActionMessage('复制失败，请检查浏览器剪贴板权限。', true);
      return false;
    });
  }

  /** 复用 core/filter 的 exportLog，避免 Dating 自己复制 CSRF、base path 或下载逻辑。 */
  function exportDatingContent(exportType, content, button) {
    if (!content || typeof api.exportLog !== 'function') {
      if (typeof api.showActionMessage === 'function') {
        api.showActionMessage(!content ? '当前没有可导出的 Dating 结果。' : '导出地址不可用。', true, true);
      }
      return Promise.resolve(null);
    }
    var originalText = button ? button.textContent : '';
    if (button) {
      button.disabled = true;
      button.textContent = '导出中...';
    }
    return Promise.resolve(api.exportLog(exportType, content)).finally(function restoreDatingExport() {
      if (!button) return;
      button.textContent = originalText;
      button.disabled = exportType === "dating_analysis_report"
        ? !latestDatingReport : !latestDatingAnalysis;
    });
  }

  function exportDatingReport() {
    return exportDatingContent(
      "dating_analysis_report", latestDatingReport, getElement('export-dating-report-btn')
    );
  }

  function exportDatingJson() {
    var content = latestDatingAnalysis ? JSON.stringify(latestDatingAnalysis, null, 2) : '';
    return exportDatingContent("dating_analysis_json", content, getElement('export-dating-json-btn'));
  }

  /** People/通用模式切换时收回 Dating 自己的面板和数据，避免残留标签或内容。 */
  function handleDatingModeChange(event) {
    var modeName = event && event.target ? String(event.target.value || '') : '';
    if (modeName === 'dating') {
      setDatingTabs();
      return;
    }
    resetDatingResult();
    setNonDatingTabs(modeName);
  }

  function initialize() {
    if (datingInitialized) return;
    datingInitialized = true;
    var copyButton = getElement('copy-dating-report-btn');
    var reportButton = getElement('export-dating-report-btn');
    var jsonButton = getElement('export-dating-json-btn');
    var fieldFilter = getElement('dating-field-filter');
    var fieldSearch = getElement('dating-field-search');
    var fieldMore = getElement('dating-field-more');
    var checkFilter = getElement('dating-check-filter');
    var modeSelect = getElement('analysis-mode');
    if (copyButton) copyButton.addEventListener('click', copyDatingReport);
    if (reportButton) reportButton.addEventListener('click', exportDatingReport);
    if (jsonButton) jsonButton.addEventListener('click', exportDatingJson);
    if (fieldFilter) fieldFilter.addEventListener('change', resetAndRenderDatingFields);
    if (fieldSearch) fieldSearch.addEventListener('input', resetAndRenderDatingFields);
    if (fieldMore) fieldMore.addEventListener('click', showMoreDatingFields);
    if (checkFilter) checkFilter.addEventListener('change', function filterDatingChecks() {
      renderDatingCheckItems(latestDatingChecks);
    });
    if (!datingModeListenerAttached && modeSelect && typeof modeSelect.addEventListener === 'function') {
      modeSelect.addEventListener('change', handleDatingModeChange);
      datingModeListenerAttached = true;
    }
    updateDatingExportButtons(false);
  }

  var definition = {
    analyze: analyzeDatingLog,
    run: analyzeDatingLog,
    reset: resetDatingResult,
    // Dating 的错误码、后端原文和处理建议都在 Overview；输入修订只清理
    // Dating 自己的结果与导出状态，不触碰 Filter/People 的 owner。历史接口
    // onInputRevision: resetDatingResult 仍保留为显式重置语义；日志修订走 stale
    // hook，让旧结果保持可查看但不可导出。
    errorPanel: 'overviewPanel',
    onInputRevision: markDatingStale
  };

  if (typeof api.registerAnalysisMode === 'function') {
    api.registerAnalysisMode('dating', definition);
  } else if (typeof api.registerMode === 'function') {
    api.registerMode('dating', definition);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, {once: true});
  } else {
    initialize();
  }
})(window, document);
