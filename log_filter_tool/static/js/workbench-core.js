/**
 * 单日志分析工作台的无依赖核心。
 *
 * 职责：
 * 1. 暴露稳定的 ``window.LogWorkbench`` 命名空间和模式注册接口；
 * 2. 将显式选择的分析模式路由到 Flask 表单或已注册的业务适配器；
 * 3. 初始化可访问标签页与支持键盘的双栏 resizer。
 *
 * 本文件不解析日志内容，也不根据日志内容推断模式。具体业务渲染继续由
 * 既有页面函数负责，后续任务可通过 ``registerMode`` 扩展而无需改动壳层。
 */
(function bootstrapLogWorkbench(global, document) {
  "use strict";

  var namespace = global.LogWorkbench || {};
  var modes = namespace.modes || Object.create(null);
  var state = namespace.state || {activeTab: "overview"};

  /**
   * 注册一个显式分析模式。
   *
   * @param {string} name select option 使用的稳定模式名。
   * @param {{nativeSubmit?: boolean, run?: Function}} definition 模式行为。
   * @returns {object} 已保存的模式定义。
   * @throws {TypeError} 模式名为空或定义不包含可执行行为时抛出。
   */
  function registerMode(name, definition) {
    var normalizedName = String(name || "").trim();
    if (!normalizedName) {
      throw new TypeError("分析模式名称不能为空");
    }
    if (!definition || (!definition.nativeSubmit && typeof definition.run !== "function")) {
      throw new TypeError("分析模式必须声明原生提交或 run 函数");
    }
    modes[normalizedName] = definition;
    return definition;
  }

  /** 根据名称返回已注册模式；未知名称返回 null，交由调用方给出用户反馈。 */
  function getMode(name) {
    return modes[name] || null;
  }

  /**
   * 在全局 Toast 中写入纯文本提示。
   * 使用 ``textContent`` 避免将异常或服务端文案解释为 HTML。
   */
  function showToast(message) {
    var toast = document.getElementById("workbench-toast");
    if (!toast) return;
    toast.textContent = String(message || "");
    toast.hidden = false;
  }

  /**
   * 注册壳层原生处理的过滤模式。People/Dating 在核心脚本加载后由业务脚本适配，
   * 这样核心不会依赖尚未声明的页面全局函数。
   */
  function registerDefaultModes() {
    if (!getMode("filter")) {
      registerMode("filter", {nativeSubmit: true});
    }
  }

  /** 返回工作台中按 DOM 顺序排列的全部结果标签。 */
  function tabButtons(root) {
    return Array.from(root.querySelectorAll('[role="tab"][aria-controls]'));
  }

  /**
   * 返回当前模式允许展示的标签。
   * ``hidden`` 标签不会进入方向键/Home/End 序列，避免焦点落到不可见能力上。
   */
  function visibleTabButtons(root) {
    return tabButtons(root).filter(function isVisible(button) {
      return !button.hidden;
    });
  }

  /**
   * 激活一个可见 panel，并原子同步标签与 panel 的可访问状态。
   *
   * @param {string} panelId ``aria-controls`` 指向的 panel ID。
   * @param {boolean} focusTab 是否把键盘焦点移动到对应标签。
   * @returns {boolean} 目标存在且当前可见时返回 true，否则保持原选择并返回 false。
   */
  function activateTab(panelId, focusTab) {
    var root = document.getElementById("log-workbench");
    if (!root) return false;

    var normalizedPanelId = String(panelId || "");
    var visibleTabs = visibleTabButtons(root);
    var selectedTab = visibleTabs.find(function findTarget(button) {
      return button.getAttribute("aria-controls") === normalizedPanelId;
    });
    if (!selectedTab) return false;

    tabButtons(root).forEach(function updateTab(button) {
      var selected = !button.hidden && button === selectedTab;
      var panel = document.getElementById(button.getAttribute("aria-controls"));
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      if (panel) panel.hidden = !selected;
    });

    state.activeTab = normalizedPanelId.replace(/Panel$/, "");
    if (focusTab) selectedTab.focus();
    return true;
  }

  /**
   * 按当前分析模式声明可用 panel；未知 ID 被忽略。
   * 若当前标签被移除，则回退到 DOM 中第一个可见标签，确保始终只有一个
   * ``aria-selected=true`` 和一个 ``tabindex=0``。
   *
   * @param {string[]} panelIds 当前模式可展示的 panel ID。
   * @returns {boolean} 至少存在一个可见标签时返回 true。
   */
  function setAvailableTabs(panelIds) {
    var root = document.getElementById("log-workbench");
    if (!root) return false;

    var availableIds = new Set(
      Array.isArray(panelIds) ? panelIds.map(String) : []
    );
    tabButtons(root).forEach(function updateAvailability(button) {
      var panel = document.getElementById(button.getAttribute("aria-controls"));
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

  /** 为五个标准结果标签绑定鼠标与仅包含可见标签的键盘导航。 */
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
        if (event.key === "ArrowLeft") {
          targetIndex = (currentIndex - 1 + visibleTabs.length) % visibleTabs.length;
        }
        if (event.key === "ArrowRight") {
          targetIndex = (currentIndex + 1) % visibleTabs.length;
        }
        if (event.key === "Home") targetIndex = 0;
        if (event.key === "End") targetIndex = visibleTabs.length - 1;
        if (targetIndex === null) return;
        event.preventDefault();
        activateTab(
          visibleTabs[targetIndex].getAttribute("aria-controls"),
          true
        );
      });
    });

    var visibleTabs = visibleTabButtons(root);
    var selected = visibleTabs.find(function findSelected(tab) {
      return tab.getAttribute("aria-selected") === "true";
    }) || visibleTabs[0];
    if (selected) activateTab(selected.getAttribute("aria-controls"), false);
  }

  /**
   * 返回 CSS Grid 实际分配轨道的内容区域。
   * ``getBoundingClientRect`` 包含工作台的 padding/border，百分比轨道却基于内容盒；
   * 换算时扣除这些尺寸，才能保证键盘每次真实移动 16px 且拖动不会发生跳变。
   */
  function workspaceTrackMetrics(root) {
    var bounds = root.getBoundingClientRect();
    var styles = typeof global.getComputedStyle === "function"
      ? global.getComputedStyle(root) : {};
    var borderLeft = Number.parseFloat(styles.borderLeftWidth) || 0;
    var borderRight = Number.parseFloat(styles.borderRightWidth) || 0;
    var paddingLeft = Number.parseFloat(styles.paddingLeft) || 0;
    var paddingRight = Number.parseFloat(styles.paddingRight) || 0;
    return {
      left: bounds.left + borderLeft + paddingLeft,
      width: Math.max(
        0,
        bounds.width - borderLeft - borderRight - paddingLeft - paddingRight
      )
    };
  }

  /**
   * 将日志栏宽度限制在 ARIA 声明的 32%–55%，确保两栏都保留可用空间。
   * 保留四位小数可将百分比回写误差控制在远小于一个 CSS 像素的范围内。
   */
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
    var resizer = document.getElementById("workbench-resizer");
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
        var requested = ((moveEvent.clientX - metrics.left) / metrics.width) * 100;
        setLogPaneWidth(root, resizer, requested);
      }

      function stopPointerResize(endEvent) {
        document.removeEventListener("pointermove", handlePointerMove);
        document.removeEventListener("pointerup", stopPointerResize);
        document.removeEventListener("pointercancel", stopPointerResize);
        if (resizer.hasPointerCapture(endEvent.pointerId)) {
          resizer.releasePointerCapture(endEvent.pointerId);
        }
      }

      /*
       * move/up 监听放在 document：即使浏览器或自动化环境没有持续派发
       * pointer capture，指针离开 8px 分隔条后仍能连续调整并可靠清理监听器。
       */
      document.addEventListener("pointermove", handlePointerMove);
      document.addEventListener("pointerup", stopPointerResize);
      document.addEventListener("pointercancel", stopPointerResize);
    });
  }

  /**
   * 统一控制异步分析期间的主按钮、模式选择器与全局 loading 遮罩。
   * 状态在调用业务适配器之前同步写入，连续 submit 因而无法穿透 busy 锁。
   */
  function setAnalysisBusy(root, modeSelect, submitButton, loadingMask, isBusy, idleText) {
    root.setAttribute("aria-busy", isBusy ? "true" : "false");
    modeSelect.disabled = isBusy;
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

  /** People/Dating 完成后统一激活结果标签，保证错误或成功信息都可立即看到。 */
  function activateResultPanel() {
    var resultTab = document.getElementById("resultTab");
    if (resultTab) activateTab("resultPanel", false);
  }

  /**
   * 根据用户选择执行模式。filter 保留浏览器原生表单提交，其余模式阻止提交后
   * 调用异步业务适配器。壳层持有完整 Promise 生命周期，防止重复 POST，并在
   * 成功或失败结束后恢复入口状态和展示 resultPanel。
   */
  function initializeModeSubmission(root) {
    var form = document.getElementById("log-analysis-form");
    var modeSelect = document.getElementById("analysis-mode");
    var submitButton = document.getElementById("analyze-log-btn");
    var loadingMask = document.getElementById("workbench-loading-mask");
    var analysisInFlight = false;
    if (!form || !modeSelect) return;

    form.addEventListener("submit", function handleWorkbenchSubmit(event) {
      var mode = getMode(modeSelect.value);
      if (!mode) {
        event.preventDefault();
        showToast("请选择可用的分析模式。");
        return;
      }
      if (mode.nativeSubmit) return;
      event.preventDefault();
      if (analysisInFlight) return;

      analysisInFlight = true;
      var idleButtonText = submitButton ? submitButton.textContent : "分析日志";
      setAnalysisBusy(root, modeSelect, submitButton, loadingMask, true, idleButtonText);

      var runResult;
      try {
        runResult = mode.run({root: root, form: form, endpoints: namespace.endpoints});
      } catch (error) {
        runResult = Promise.reject(error);
      }

      Promise.resolve(runResult)
        .catch(function handleAnalysisFailure(error) {
          showToast(error && error.message ? error.message : "分析失败，请稍后重试。");
        })
        .then(function showAnalysisResult() {
          activateResultPanel();
        })
        .finally(function restoreAnalysisControls() {
          analysisInFlight = false;
          setAnalysisBusy(
            root, modeSelect, submitButton, loadingMask, false, idleButtonText
          );
        });
    });
  }

  /**
   * 从服务端渲染的数据属性读取真实 endpoint。所有值自动继承 Blueprint base path。
   */
  function readEndpoints(root) {
    return {
      index: root.dataset.indexUrl,
      exportLog: root.dataset.exportUrl,
      peopleSearch: root.dataset.peopleSearchUrl,
      dating: root.dataset.datingUrl
    };
  }

  /** 幂等初始化当前页面；重复调用不会再次绑定事件。 */
  function initialize() {
    var root = document.getElementById("log-workbench");
    if (!root || root.dataset.workbenchInitialized === "true") return;
    root.dataset.workbenchInitialized = "true";
    namespace.endpoints = readEndpoints(root);
    initializeTabs(root);
    initializeResizer(root);
    initializeModeSubmission(root);
  }

  registerDefaultModes();
  namespace.state = state;
  namespace.modes = modes;
  namespace.registerMode = registerMode;
  namespace.getMode = getMode;
  namespace.setAvailableTabs = setAvailableTabs;
  namespace.activateTab = activateTab;
  namespace.activateResultPanel = activateResultPanel;
  namespace.showToast = showToast;
  namespace.init = initialize;
  global.LogWorkbench = namespace;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})(window, document);
