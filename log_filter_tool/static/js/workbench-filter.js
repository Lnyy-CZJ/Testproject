/**
 * 通用日志过滤模式的页面交互。
 *
 * 本文件只负责 method 多选、导出、复制和视图控件；分析模式分发、textarea 搜索、
 * stale 与行号定位由 workbench-core.js 统一维护。服务端过滤仍使用原有表单 POST，
 * 因而不会在前端复制后端的日志分块规则或改变接口契约。
 */
(function bootstrapLogWorkbenchFilter(global, document) {
  "use strict";

  var api = global.LogWorkbench || {};
  var selectionSnapshot = "";

  function getElement(id) {
    return document.getElementById(id);
  }

  function getForm() {
    return getElement("log-filter-form") || getElement("log-analysis-form");
  }

  function getCheckboxes(dropdown) {
    if (!dropdown || typeof dropdown.querySelectorAll !== "function") return [];
    return Array.from(dropdown.querySelectorAll('input[name="method"]'));
  }

  function getAllCheckbox(dropdown) {
    if (!dropdown || typeof dropdown.querySelector === "undefined") return null;
    return dropdown.querySelector('input[data-is-all="1"]');
  }

  function getMethodCheckboxes(dropdown) {
    if (!dropdown || typeof dropdown.querySelectorAll !== "function") return [];
    return Array.from(dropdown.querySelectorAll('input[name="method"]:not([data-is-all="1"])'));
  }

  /** 返回稳定选择签名，外部点击时据此决定是否自动提交。 */
  function getSelectionSignature(checkboxes) {
    return checkboxes.filter(function isChecked(checkbox) {
      return checkbox.checked;
    }).map(function checkboxValue(checkbox) {
      return checkbox.value;
    }).sort().join("|");
  }

  function updateToggleText(dropdown, allCheckbox, toggleText) {
    if (!dropdown || !toggleText) return;
    var checked = typeof dropdown.querySelectorAll === "function"
      ? Array.from(dropdown.querySelectorAll('input[name="method"]:checked')) : [];
    if (!checked.length || (allCheckbox && allCheckbox.checked)) {
      toggleText.textContent = "全部";
    } else if (checked.length === 1) {
      toggleText.textContent = checked[0].value;
    } else {
      toggleText.textContent = "已选 " + checked.length + " 项";
    }
  }

  function closeDropdown(toggle, dropdown) {
    if (!dropdown || !dropdown.classList || !dropdown.classList.contains("open")) return;
    dropdown.classList.remove("open");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  }

  function isInteractiveTarget(target) {
    return Boolean(target && typeof target.closest === "function" &&
      target.closest("button, input, textarea, a"));
  }

  /**
   * 复用原通用过滤 form 的原生提交路径。
   * People/Dating 选择期间不自动触发过滤 POST，避免它们的已注册适配器被绕过。
   */
  function submitGeneralFilter() {
    var modeSelect = getElement("analysis-mode");
    if (modeSelect && modeSelect.value !== "general" && modeSelect.value !== "filter") {
      if (typeof api.showToast === "function") api.showToast("method 筛选仅用于通用接口分析。");
      return;
    }
    var form = getForm();
    if (!form) return;
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else if (typeof form.submit === "function") form.submit();
  }

  /** 安全地读取当前日志/过滤结果 textarea 的值，保留原始换行。 */
  function exportContent(exportType, overrideContent) {
    if (overrideContent !== undefined && overrideContent !== null) return String(overrideContent);
    if (exportType === "log_content") {
      var logText = getElement("log_text");
      return logText ? String(logText.value || "") : "";
    }
    var resultText = getElement("result-text");
    return resultText ? String(resultText.value || "") : "";
  }

  /**
   * 导出固定文本来源。
   *
   * @param {'log_content'|'filtered_result'|'analysis_report'} exportType 后端导出类型。
   * @param {string} [overrideContent] People 报告等显式文本来源。
   * @returns {Promise<object>|undefined} 请求 Promise；无控件或 stale 时返回已完成 Promise。
   */
  function exportLog(exportType, overrideContent) {
    if (exportType === "filtered_result" && api.state && api.state.dirty) {
      if (typeof api.showActionMessage === "function") {
        api.showActionMessage("日志已修改，过滤结果可能已过期，请重新分析后再导出。", true, true);
      }
      return Promise.resolve(null);
    }
    var revisionAtStart = api.state ? Number(api.state.inputRevision) || 0 : 0;
    var content = exportContent(exportType, overrideContent);
    var buttonId = exportType === "log_content"
      ? "export-log-content-btn"
      : exportType === "analysis_report" ? "export-report-btn" : "export-filtered-result-btn";
    var button = getElement(buttonId);
    var originalText = button ? button.textContent : "";
    var endpoint = api.endpoints && api.endpoints.exportLog;
    if (!endpoint || typeof api.requestJson !== "function") {
      if (typeof api.showActionMessage === "function") {
        api.showActionMessage("导出地址不可用。", true, true);
      }
      return Promise.resolve(null);
    }

    if (button) {
      button.disabled = true;
      button.textContent = "导出中...";
    }
    return api.requestJson(endpoint, {
      method: "POST",
      body: {export_type: exportType, content: content}
    }).then(function handleExportSuccess(payload) {
      if (typeof api.showActionMessage === "function") {
        api.showActionMessage("已保存：" + (payload.path || ""), false);
      }
      return payload;
    }).catch(function handleExportFailure(error) {
      if (typeof api.showActionMessage === "function") {
        api.showActionMessage(error.message || "导出失败", true);
      }
      return null;
    }).finally(function restoreExportButton() {
      if (button) {
        // 导出请求期间日志可能发生 input；finally 重新计算状态，不能把 stale
        // 结果错误恢复成可导出。结果为空时也必须维持初始禁用语义。
        var result = getElement("result-text");
        var hasResult = Boolean(result && String(result.value || ""));
        var stale = exportType === "filtered_result" && api.state &&
          (api.state.dirty || Number(api.state.inputRevision) !== revisionAtStart);
        button.disabled = Boolean(stale || (exportType === "filtered_result" && !hasResult));
        button.textContent = originalText;
      }
    });
  }

  /** 复制只读过滤结果 textarea 的纯文本值，不复制搜索状态或页面装饰。 */
  function copyResult() {
    var result = getElement("result-text");
    var content = result ? String(result.value || "") : "";
    var navigatorObject = global.navigator;
    if (!navigatorObject || !navigatorObject.clipboard ||
        typeof navigatorObject.clipboard.writeText !== "function") {
      if (typeof api.showActionMessage === "function") {
        api.showActionMessage("复制失败，请检查浏览器剪贴板权限。", true);
      }
      return Promise.resolve(false);
    }
    return navigatorObject.clipboard.writeText(content).then(function copySucceeded() {
      var button = getElement("copy-btn");
      if (!button) return true;
      var originalText = button.textContent;
      button.textContent = "已复制";
      var timer = setTimeout(function restoreCopyButton() {
        button.textContent = originalText;
      }, 1500);
      if (timer && typeof timer.unref === "function") timer.unref();
      return true;
    }).catch(function copyFailed() {
      if (typeof api.showActionMessage === "function") {
        api.showActionMessage("复制失败，请检查浏览器剪贴板权限。", true);
      }
      return false;
    });
  }

  function bindMethodSelector() {
    var toggle = getElement("method-toggle");
    var dropdown = getElement("method-dropdown");
    var toggleText = getElement("method-toggle-text");
    var container = getElement("multi-select");
    if (!toggle || !dropdown || !container) return;

    var form = getForm();
    var checkboxes = getCheckboxes(dropdown);
    var allCheckbox = getAllCheckbox(dropdown);
    var methodCheckboxes = getMethodCheckboxes(dropdown);

    toggle.addEventListener("click", function handleToggleClick(event) {
      event.stopPropagation();
      if (!dropdown.classList.contains("open")) {
        selectionSnapshot = getSelectionSignature(checkboxes);
      }
      dropdown.classList.toggle("open");
      toggle.setAttribute("aria-expanded", dropdown.classList.contains("open") ? "true" : "false");
      toggle.focus();
    });

    /** 自定义 method 选择器的键盘行为与原生按钮一致。 */
    toggle.addEventListener("keydown", function handleToggleKeydown(event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle.click();
      } else if (event.key === "Escape" && dropdown.classList.contains("open")) {
        closeDropdown(toggle, dropdown);
      }
    });

    document.addEventListener("click", function handleOutsideClick(event) {
      var inside = typeof container.contains === "function" && container.contains(event.target);
      if (inside || !dropdown.classList.contains("open")) return;
      var changed = selectionSnapshot !== getSelectionSignature(checkboxes);
      closeDropdown(toggle, dropdown);
      if (changed && !isInteractiveTarget(event.target) && form) submitGeneralFilter();
    });

    if (allCheckbox) {
      allCheckbox.addEventListener("change", function handleAllChange() {
        if (allCheckbox.checked) {
          methodCheckboxes.forEach(function uncheckMethod(checkbox) {
            checkbox.checked = false;
          });
        }
        updateToggleText(dropdown, allCheckbox, toggleText);
      });
    }
    methodCheckboxes.forEach(function bindMethodChange(checkbox) {
      checkbox.addEventListener("change", function handleMethodChange() {
        if (checkbox.checked && allCheckbox) allCheckbox.checked = false;
        updateToggleText(dropdown, allCheckbox, toggleText);
      });
    });

    var selectAllButton = getElement("btn-select-all");
    var deselectAllButton = getElement("btn-deselect-all");
    if (selectAllButton) selectAllButton.addEventListener("click", function selectAll(event) {
      event.preventDefault();
      if (allCheckbox) allCheckbox.checked = false;
      methodCheckboxes.forEach(function checkMethod(checkbox) { checkbox.checked = true; });
      updateToggleText(dropdown, allCheckbox, toggleText);
    });
    if (deselectAllButton) deselectAllButton.addEventListener("click", function deselectAll(event) {
      event.preventDefault();
      if (allCheckbox) allCheckbox.checked = true;
      methodCheckboxes.forEach(function uncheckMethod(checkbox) { checkbox.checked = false; });
      updateToggleText(dropdown, allCheckbox, toggleText);
    });
    updateToggleText(dropdown, allCheckbox, toggleText);
  }

  function bindGenericControls() {
    var logExportButton = getElement("export-log-content-btn");
    var filteredExportButton = getElement("export-filtered-result-btn");
    var copyButton = getElement("copy-btn");
    if (logExportButton) logExportButton.addEventListener("click", function exportLogContent() {
      exportLog("log_content");
    });
    if (filteredExportButton) filteredExportButton.addEventListener("click", function exportFilteredResult() {
      exportLog("filtered_result");
    });
    if (copyButton) copyButton.addEventListener("click", copyResult);
  }

  function initialize() {
    if (typeof api.init === "function") api.init();
    bindMethodSelector();
    bindGenericControls();
  }

  // 模板中的既有业务脚本紧随本文件执行，并会缓存 exportLog。API 必须在
  // DOMContentLoaded 之前暴露；事件绑定仍延后到 DOM 就绪，避免初始化时序竞态。
  api.exportLog = exportLog;
  api.copyResult = copyResult;
  api.submitGeneralFilter = submitGeneralFilter;
  api.initFilter = initialize;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})(window, document);
