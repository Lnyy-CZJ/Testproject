/**
 * 单日志分析工作台的无依赖核心。
 *
 * 职责：
 * 1. 暴露稳定的 ``window.LogWorkbench`` 命名空间和模式注册接口；
 * 2. 将显式选择的分析模式路由到既有 Flask 表单或分析函数；
 * 3. 初始化可访问标签页与支持键盘的双栏 resizer。
 *
 * 本文件不解析日志内容，也不根据日志内容推断模式。具体业务渲染继续由
 * 既有页面函数负责，后续任务可通过 ``registerMode`` 扩展而无需改动壳层。
 */
(function bootstrapLogWorkbench(global, document) {
  "use strict";

  var namespace = global.LogWorkbench || {};
  var modes = namespace.modes || Object.create(null);

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

  /** 调用模板中保留的既有分析入口，并在入口不可用时提供可见错误。 */
  function invokeExistingAnalyzer(functionName) {
    var analyzer = global[functionName];
    if (typeof analyzer !== "function") {
      showToast("当前分析模式暂不可用，请刷新页面后重试。");
      return false;
    }
    analyzer();
    return true;
  }

  /**
   * 注册 Task 1 提供的三个固定模式。模式只响应用户选择，不读取日志内容做推断。
   * Dating option 由模板功能开关决定是否出现，保留注册项便于后续模块复用。
   */
  function registerDefaultModes() {
    if (!getMode("filter")) {
      registerMode("filter", {nativeSubmit: true});
    }
    if (!getMode("people-search")) {
      registerMode("people-search", {
        run: function runPeopleSearch() {
          return invokeExistingAnalyzer("analyzePeopleSearch");
        }
      });
    }
    if (!getMode("dating")) {
      registerMode("dating", {
        run: function runDatingAnalysis() {
          return invokeExistingAnalyzer("analyzeDatingLog");
        }
      });
    }
  }

  /**
   * 切换到目标 tab，并同步 aria-selected、tabindex 与 panel.hidden。
   *
   * @param {HTMLElement} selectedTab 要激活的 role=tab 元素。
   * @param {HTMLElement} root 当前工作台根节点。
   */
  function activateTab(selectedTab, root) {
    var tabs = Array.from(root.querySelectorAll('[role="tab"][aria-controls]'));
    tabs.forEach(function updateTab(tab) {
      var selected = tab === selectedTab;
      var panel = document.getElementById(tab.getAttribute("aria-controls"));
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
      if (panel) panel.hidden = !selected;
    });
  }

  /** 为五个标准结果标签绑定鼠标与方向键操作。 */
  function initializeTabs(root) {
    var tabs = Array.from(root.querySelectorAll('[role="tab"][aria-controls]'));
    if (!tabs.length) return;

    tabs.forEach(function bindTab(tab, index) {
      tab.addEventListener("click", function handleTabClick() {
        activateTab(tab, root);
      });
      tab.addEventListener("keydown", function handleTabKeydown(event) {
        var targetIndex = null;
        if (event.key === "ArrowLeft") targetIndex = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "ArrowRight") targetIndex = (index + 1) % tabs.length;
        if (event.key === "Home") targetIndex = 0;
        if (event.key === "End") targetIndex = tabs.length - 1;
        if (targetIndex === null) return;
        event.preventDefault();
        activateTab(tabs[targetIndex], root);
        tabs[targetIndex].focus();
      });
    });

    var selected = tabs.find(function findSelected(tab) {
      return tab.getAttribute("aria-selected") === "true";
    }) || tabs[0];
    activateTab(selected, root);
  }

  /**
   * 将日志栏宽度限制在 ARIA 声明的 30%-70%，确保两栏都保留可用空间。
   */
  function setLogPaneWidth(root, resizer, requestedValue) {
    var minimum = Number(resizer.getAttribute("aria-valuemin")) || 30;
    var maximum = Number(resizer.getAttribute("aria-valuemax")) || 70;
    var value = Math.min(maximum, Math.max(minimum, Math.round(requestedValue)));
    root.style.setProperty("--wb-log-pane-width", value + "%");
    resizer.setAttribute("aria-valuenow", String(value));
  }

  /** 初始化键盘和指针均可操作的栏宽调整器。 */
  function initializeResizer(root) {
    var resizer = document.getElementById("workbench-resizer");
    if (!resizer) return;

    resizer.addEventListener("keydown", function handleResizeKeydown(event) {
      var current = Number(resizer.getAttribute("aria-valuenow")) || 44;
      var next = null;
      if (event.key === "ArrowLeft") next = current - 2;
      if (event.key === "ArrowRight") next = current + 2;
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
        var bounds = root.getBoundingClientRect();
        var requested = ((moveEvent.clientX - bounds.left) / bounds.width) * 100;
        setLogPaneWidth(root, resizer, requested);
      }

      function stopPointerResize(endEvent) {
        resizer.removeEventListener("pointermove", handlePointerMove);
        resizer.removeEventListener("pointerup", stopPointerResize);
        resizer.removeEventListener("pointercancel", stopPointerResize);
        if (resizer.hasPointerCapture(endEvent.pointerId)) {
          resizer.releasePointerCapture(endEvent.pointerId);
        }
      }

      resizer.addEventListener("pointermove", handlePointerMove);
      resizer.addEventListener("pointerup", stopPointerResize);
      resizer.addEventListener("pointercancel", stopPointerResize);
    });
  }

  /**
   * 根据用户选择执行模式。filter 保留浏览器原生表单提交，其余模式阻止提交后
   * 调用既有异步分析入口，因此不会重复 POST 或改变已有 CSRF 合同。
   */
  function initializeModeSubmission(root) {
    var form = document.getElementById("log-analysis-form");
    var modeSelect = document.getElementById("analysis-mode");
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
      mode.run({root: root, form: form, endpoints: namespace.endpoints});
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
  namespace.modes = modes;
  namespace.registerMode = registerMode;
  namespace.getMode = getMode;
  namespace.activateTab = activateTab;
  namespace.showToast = showToast;
  namespace.init = initialize;
  global.LogWorkbench = namespace;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, {once: true});
  } else {
    initialize();
  }
})(window, document);
