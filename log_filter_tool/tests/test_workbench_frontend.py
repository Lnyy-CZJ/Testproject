"""单日志分析工作台壳层、事件绑定与异步生命周期的行为测试。"""

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest

from app import create_app


class _WorkbenchMarkupParser(HTMLParser):
    """提取脚本顺序与字符串事件属性，避免用脆弱的正则匹配 HTML。"""

    def __init__(self):
        super().__init__()
        self.inline_event_attributes = []
        self.scripts = []
        self._current_script = None

    def handle_starttag(self, tag, attrs):
        """记录所有 ``on*`` 属性，并按文档顺序保存 script 内容。"""
        normalized_attrs = {name.lower(): value for name, value in attrs}
        for name, value in attrs:
            if name.lower().startswith("on"):
                self.inline_event_attributes.append((tag, name, value))

        if tag.lower() == "script":
            self._current_script = {
                "src": normalized_attrs.get("src"),
                "content": [],
            }
            self.scripts.append(self._current_script)

    def handle_data(self, data):
        """保留内联脚本文本，以识别承载既有业务函数的适配脚本。"""
        if self._current_script is not None:
            self._current_script["content"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self._current_script = None


class WorkbenchShellTest(unittest.TestCase):
    """锁定后续前端任务依赖的 DOM 标识与 Blueprint 静态资源合同。"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _run_task_two_core_harness(self, scenario):
        """在无第三方 DOM 依赖的 Node 沙箱中执行 Task 2 交互场景。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行前端交互合同测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeElement {
              constructor(id, attributes = {}) {
                this.id = id;
                this.attributes = {...attributes};
                this.dataset = {};
                this.listeners = Object.create(null);
                this.hidden = Boolean(attributes.hidden);
                this.tabIndex = Number(attributes.tabIndex ?? 0);
                this.focusCount = 0;
                this.capturedPointers = new Set();
                this.bounds = {left: 0, width: 1000};
                this.style = {
                  updates: [],
                  values: Object.create(null),
                  setProperty(name, value) {
                    this.updates.push([name, String(value)]);
                    this.values[name] = String(value);
                  }
                };
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              removeEventListener(type, listener) {
                this.listeners[type] = (this.listeners[type] || []).filter(
                  registered => registered !== listener
                );
              }

              dispatch(type, event = {}) {
                (this.listeners[type] || []).slice().forEach(listener => listener(event));
              }

              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? String(this.attributes[name]) : null;
              }

              setAttribute(name, value) {
                this.attributes[name] = String(value);
              }

              getBoundingClientRect() {
                return this.bounds;
              }

              setPointerCapture(pointerId) {
                this.capturedPointers.add(pointerId);
              }

              hasPointerCapture(pointerId) {
                return this.capturedPointers.has(pointerId);
              }

              releasePointerCapture(pointerId) {
                this.capturedPointers.delete(pointerId);
              }

              focus() {
                this.focusCount += 1;
              }
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            const root = new FakeElement("log-workbench");
            root.dataset = {
              indexUrl: "/",
              exportUrl: "/export",
              peopleSearchUrl: "/people",
              datingUrl: "/dating"
            };
            const tabDefinitions = [
              ["overviewTab", "overviewPanel", true],
              ["interfacesTab", "interfacesPanel", false],
              ["timelineTab", "timelinePanel", false],
              ["resultTab", "resultPanel", false],
              ["checksTab", "checksPanel", false]
            ];
            const tabs = tabDefinitions.map(([id, panelId, selected]) =>
              new FakeElement(id, {
                "aria-controls": panelId,
                "aria-selected": String(selected),
                tabIndex: selected ? 0 : -1
              })
            );
            const panels = tabDefinitions.map(([, panelId, selected]) =>
              new FakeElement(panelId, {hidden: !selected})
            );
            const resizer = new FakeElement("workbench-resizer", {
              "aria-valuemin": "32",
              "aria-valuemax": "55",
              "aria-valuenow": "39"
            });
            root.querySelectorAll = selector =>
              selector === '[role="tab"][aria-controls]' ? tabs : [];

            const elements = {"log-workbench": root, "workbench-resizer": resizer};
            [...tabs, ...panels].forEach(element => { elements[element.id] = element; });

            let persistenceWrites = 0;
            const localStorage = {
              setItem() { persistenceWrites += 1; },
              removeItem() { persistenceWrites += 1; }
            };
            const documentListeners = Object.create(null);
            const document = {
              readyState: "complete",
              getElementById(id) { return elements[id] || null; },
              addEventListener(type, listener) {
                (documentListeners[type] ||= []).push(listener);
              },
              removeEventListener(type, listener) {
                documentListeners[type] = (documentListeners[type] || []).filter(
                  registered => registered !== listener
                );
              },
              dispatch(type, event = {}) {
                (documentListeners[type] || []).slice().forEach(
                  listener => listener(event)
                );
              }
            };
            Object.defineProperty(document, "cookie", {
              get() { return ""; },
              set() { persistenceWrites += 1; }
            });
            const window = {
              localStorage,
              // 与真实 .workspace 一致的水平内边距，用于验证 16px 换算基于网格内容宽度。
              getComputedStyle() {
                return {paddingLeft: "24px", paddingRight: "24px"};
              }
            };

            vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
              window,
              document,
              localStorage,
              Promise,
              Array,
              Object,
              String,
              Number,
              Math,
              Set,
              TypeError
            });

            const api = window.LogWorkbench;
            const byId = id => elements[id];

            if (process.argv[2] === "tabs") {
              assert(typeof api.setAvailableTabs === "function",
                "核心未暴露 setAvailableTabs(ids)");
              assert(typeof api.activateTab === "function",
                "核心未暴露 activateTab(panelId, focusTab)");

              api.setAvailableTabs(["overviewPanel", "resultPanel", "checksPanel"]);
              assert(byId("interfacesTab").hidden, "不可用的接口标签未隐藏");
              assert(byId("timelineTab").hidden, "不可用的时间线标签未隐藏");
              assert(byId("interfacesPanel").hidden, "不可用接口 panel 未隐藏");
              assert(byId("overviewTab").tabIndex === 0,
                "当前可见标签没有保留唯一 tabindex=0");

              assert(api.activateTab("resultPanel", true) === true,
                "可见 resultPanel 应能激活");
              assert(byId("resultTab").getAttribute("aria-selected") === "true",
                "激活标签未同步 aria-selected");
              assert(byId("resultTab").tabIndex === 0,
                "激活标签未同步 tabindex");
              assert(byId("resultPanel").hidden === false,
                "激活 panel 仍被隐藏");
              assert(byId("overviewPanel").hidden,
                "非激活 panel 未隐藏");
              assert(byId("resultTab").focusCount === 1,
                "focusTab=true 时未聚焦标签");

              api.setAvailableTabs(["overviewPanel", "interfacesPanel", "checksPanel"]);
              assert(byId("resultTab").hidden, "移除后的当前标签未隐藏");
              assert(byId("overviewTab").getAttribute("aria-selected") === "true",
                "当前标签被移除后没有回退到首个可见标签");
              assert(api.state.activeTab === "overview",
                "回退激活后 state.activeTab 未同步");

              let prevented = 0;
              byId("overviewTab").dispatch("keydown", {
                key: "End",
                preventDefault() { prevented += 1; }
              });
              assert(byId("checksTab").getAttribute("aria-selected") === "true",
                "End 未移动到最后一个可见标签");
              assert(byId("checksTab").focusCount === 1,
                "键盘切换未把焦点移到目标标签");

              byId("checksTab").dispatch("keydown", {
                key: "ArrowLeft",
                preventDefault() { prevented += 1; }
              });
              assert(byId("interfacesTab").getAttribute("aria-selected") === "true",
                "ArrowLeft 没有跳过隐藏标签");

              byId("interfacesTab").dispatch("keydown", {
                key: "ArrowRight",
                preventDefault() { prevented += 1; }
              });
              assert(byId("checksTab").getAttribute("aria-selected") === "true",
                "ArrowRight 没有跳过隐藏标签");

              byId("checksTab").dispatch("keydown", {
                key: "Home",
                preventDefault() { prevented += 1; }
              });
              assert(byId("overviewTab").getAttribute("aria-selected") === "true",
                "Home 未移动到第一个可见标签");
              assert(api.activateTab("timelinePanel", true) === false,
                "隐藏标签不应被 activateTab 激活");
              assert(byId("overviewTab").getAttribute("aria-selected") === "true",
                "无效激活破坏了当前选择");
              assert(prevented === 4, "标签导航键未全部阻止默认滚动行为");
            }

            if (process.argv[2] === "resizer") {
              const press = key => {
                let prevented = 0;
                resizer.dispatch("keydown", {
                  key,
                  preventDefault() { prevented += 1; }
                });
                assert(prevented === 1, key + " 未阻止默认滚动行为");
              };

              press("ArrowRight");
              const increasedPercent = Number(
                root.style.values["--left-pane"].replace("%", "")
              );
              const increasedPixels = (increasedPercent - 39) * 952 / 100;
              assert(Math.abs(increasedPixels - 16) < 0.01,
                "ArrowRight 必须按网格可用宽度精确增加 16px");
              assert(resizer.getAttribute("aria-valuenow") === String(increasedPercent),
                "键盘调整后 aria-valuenow 未同步");
              press("ArrowLeft");
              const restoredPercent = Number(
                root.style.values["--left-pane"].replace("%", "")
              );
              assert(Math.abs(restoredPercent - 39) < 0.001,
                "ArrowLeft 必须按 16px 恢复左栏");
              press("Home");
              assert(root.style.values["--left-pane"] === "32%",
                "Home 未夹取到最小值 32%");
              press("End");
              assert(root.style.values["--left-pane"] === "55%",
                "End 未夹取到最大值 55%");

              resizer.dispatch("pointerdown", {button: 0, pointerId: 7});
              assert(resizer.hasPointerCapture(7), "pointerdown 未捕获指针");
              document.dispatch("pointermove", {
                clientX: 24 + (952 * 0.44), pointerId: 7
              });
              assert(root.style.values["--left-pane"] === "44%",
                "指针百分比未扣除工作台左侧内边距");
              document.dispatch("pointermove", {clientX: 100, pointerId: 7});
              assert(root.style.values["--left-pane"] === "32%",
                "指针拖到左边界时未夹取到 32%");
              document.dispatch("pointermove", {clientX: 900, pointerId: 7});
              assert(root.style.values["--left-pane"] === "55%",
                "指针拖到右边界时未夹取到 55%");
              document.dispatch("pointerup", {pointerId: 7});
              assert(!resizer.hasPointerCapture(7), "pointerup 后未释放指针");
              assert(root.style.updates.every(([name]) => name === "--left-pane"),
                "resizer 修改了 --left-pane 之外的样式属性");
              assert(persistenceWrites === 0,
                "栏宽不得写入 localStorage 或 Cookie");
            }
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path), scenario],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr or completed.stdout,
        )

    def _run_task_three_core_harness(self, scenario):
        """在最小 DOM 沙箱中验证 Task 3 的共享日志行为。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 Task 3 前端行为合同测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeClassList {
              constructor() { this.values = new Set(); }
              toggle(name, force) {
                const shouldHave = force === undefined ? !this.values.has(name) : force;
                if (shouldHave) this.values.add(name); else this.values.delete(name);
                return shouldHave;
              }
              contains(name) { return this.values.has(name); }
            }

            class FakeElement {
              constructor(id, attributes = {}) {
                this.id = id;
                this.attributes = {...attributes};
                this.dataset = {};
                this.listeners = Object.create(null);
                this.classList = new FakeClassList();
                this.hidden = Boolean(attributes.hidden);
                this.disabled = false;
                this.value = attributes.value || "";
                this.textContent = attributes.textContent || "";
                this.tabIndex = 0;
                this.scrollTop = 0;
                this.selectionStart = 0;
                this.selectionEnd = 0;
                this.selectionCalls = [];
                this.focusCount = 0;
                this.style = {setProperty() {}};
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              dispatch(type, event = {}) {
                (this.listeners[type] || []).slice().forEach(listener => listener(event));
              }

              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? String(this.attributes[name]) : null;
              }

              setAttribute(name, value) { this.attributes[name] = String(value); }
              removeAttribute(name) { delete this.attributes[name]; }
              focus() { this.focusCount += 1; }
              setSelectionRange(start, end) {
                this.selectionStart = start;
                this.selectionEnd = end;
                this.selectionCalls.push([start, end]);
              }
              scrollIntoView() {}
              getBoundingClientRect() { return {left: 0, width: 1000}; }
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            const root = new FakeElement("log-workbench");
            root.dataset = {
              indexUrl: "/",
              exportUrl: "/export",
              peopleSearchUrl: "/people",
              datingUrl: "/dating"
            };
            root.querySelectorAll = () => [];

            const form = new FakeElement("log-filter-form");
            let requestSubmitCount = 0;
            form.requestSubmit = () => { requestSubmitCount += 1; };
            const modeSelect = new FakeElement("analysis-mode", {value: "general"});
            const analyzeButton = new FakeElement("analyze-log-btn", {
              textContent: "分析日志"
            });
            const logText = new FakeElement("log_text");
            logText.value = "zero\nneedle\nline needle\nend";
            const resultText = new FakeElement("result-text");
            resultText.value = "filtered needle";
            const rawView = new FakeElement("raw-log-view");
            const filteredView = new FakeElement("filtered-log-view", {hidden: true});
            const rawViewButton = new FakeElement("raw-log-view-btn", {
              "aria-selected": "true"
            });
            const filteredViewButton = new FakeElement("filtered-log-view-btn", {
              "aria-selected": "false"
            });
            const searchInput = new FakeElement("result-search");
            const searchCount = new FakeElement("search-count");
            const actionMessage = new FakeElement("action-message", {hidden: true});
            const toast = new FakeElement("workbench-toast", {hidden: true});
            const focusStatus = new FakeElement("log-focus-status");
            const staleStatus = new FakeElement("analysis-stale");
            const lineCount = new FakeElement("log-line-count");
            const byteCount = new FakeElement("log-byte-count");
            const allMethod = new FakeElement("all-method", {checked: true});
            allMethod.checked = true;

            const elements = {
              "log-workbench": root,
              "log-filter-form": form,
              "log-analysis-form": form,
              "analysis-mode": modeSelect,
              "analyze-log-btn": analyzeButton,
              "log_text": logText,
              "result-text": resultText,
              "raw-log-view": rawView,
              "filtered-log-view": filteredView,
              "raw-log-view-btn": rawViewButton,
              "filtered-log-view-btn": filteredViewButton,
              "result-search": searchInput,
              "search-count": searchCount,
              "action-message": actionMessage,
              "workbench-toast": toast,
              "log-focus-status": focusStatus,
              "analysis-stale": staleStatus,
              "log-line-count": lineCount,
              "log-byte-count": byteCount,
              "workbench-loading-mask": new FakeElement("workbench-loading-mask", {hidden: true})
            };
            const document = {
              readyState: "complete",
              getElementById(id) { return elements[id] || null; },
              querySelector(selector) {
                return selector === '#method-dropdown input[data-is-all="1"]'
                  ? allMethod : null;
              },
              addEventListener() {}
            };
            const window = {
              getComputedStyle() { return {lineHeight: "20px"}; }
            };

            vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
              window,
              document,
              Promise,
              Array,
              Object,
              String,
              Number,
              Math,
              Set,
              TypeError,
              setTimeout,
              clearTimeout
            });

            (async function runScenario() {
              const api = window.LogWorkbench;
              if (process.argv[2] === "dispatch") {
              assert(typeof api.analyzeSelectedMode === "function",
                "核心未暴露 analyzeSelectedMode() ");
              api.analyzeSelectedMode();
              assert(requestSubmitCount === 1,
                "general 模式未通过现有表单 requestSubmit");
              // 该沙箱只记录 requestSubmit，不执行浏览器导航；真实页面会在 POST
              // 后离开当前文档，因此这里只恢复生命周期状态以继续测试异步模式。
              api.state.phase = "idle";

              let analyzeCount = 0;
              let resolveAnalysis;
              const pending = new Promise(resolve => { resolveAnalysis = resolve; });
              api.registerAnalysisMode("people", {
                analyze(context) {
                  analyzeCount += 1;
                  assert(context.logText === logText.value, "异步模式未读取当前日志");
                  return pending;
                }
              });
              modeSelect.value = "people";
              const run = api.analyzeSelectedMode();
              api.analyzeSelectedMode();
              assert(analyzeCount === 1, "loading 期间异步模式被重复调用");
              assert(api.state.phase === "loading", "异步分析未进入 loading 状态");
              resolveAnalysis();
              await run;
              await Promise.resolve();
              assert(api.state.phase === "idle", "异步分析完成后状态未恢复 idle");
            }

              if (process.argv[2] === "search-focus-stale") {
              assert(typeof api.searchActiveLog === "function",
                "核心未暴露 searchActiveLog(direction)");
              searchInput.value = "needle";
              api.searchActiveLog(1);
              assert(logText.selectionStart === 5 && logText.selectionEnd === 11,
                "搜索未选择第一处真实字符串偏移");
              assert(searchCount.textContent === "1/2",
                "搜索计数未反映当前匹配");
              api.searchActiveLog(1);
              assert(logText.selectionStart === 17 && logText.selectionEnd === 23,
                "搜索下一项未选择第二处真实字符串偏移");
              api.searchActiveLog(-1);
              assert(logText.selectionStart === 5 && logText.selectionEnd === 11,
                "搜索上一项未回到第一处匹配");
              searchInput.value = "";
              api.searchActiveLog(1);
              assert(searchCount.textContent === "4 行",
                "空查询未显示当前日志总行数");

              api.focusLogLines(2, 3);
              assert(!rawView.hidden && filteredView.hidden,
                "行号定位前未切回原始日志视图");
              assert(logText.selectionStart === 5 && logText.selectionEnd === 23,
                "行号定位未使用真实换行偏移");
              assert(focusStatus.textContent.includes("L2–3"),
                "状态区未反馈真实定位范围");
              assert(actionMessage.textContent.includes("L2–3"),
                "操作反馈未反馈真实定位范围");
              assert(toast.textContent.includes("L2–3"),
                "toast 未反馈真实定位范围");

              const beforeResult = resultText.value;
              logText.value = "changed\nlog";
              logText.dispatch("input");
              assert(api.state.dirty === true, "日志修改未标记 stale 状态");
              assert(resultText.value === beforeResult,
                "日志修改立即清空了既有过滤结果");
              assert(staleStatus.textContent.includes("重新分析"),
                "stale 状态未给出重新分析提示");
              assert(lineCount.textContent === "2 行", "修改后行数元数据未更新");
              }
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path), scenario],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr or completed.stdout,
        )

    def _run_task_three_review_harness(self, scenario):
        """加载 core 与真实 filter 脚本，验证复审指出的跨脚本行为合同。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 Task 3 复审行为合同测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        filter_path = Path(__file__).resolve().parents[1] / "static/js/workbench-filter.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeClassList {
              constructor() { this.values = new Set(); }
              add(name) { this.values.add(name); }
              remove(name) { this.values.delete(name); }
              toggle(name, force) {
                const shouldHave = force === undefined ? !this.values.has(name) : force;
                if (shouldHave) this.values.add(name); else this.values.delete(name);
                return shouldHave;
              }
              contains(name) { return this.values.has(name); }
            }

            class FakeElement {
              constructor(id, attributes = {}) {
                this.id = id;
                this.attributes = {...attributes};
                this.dataset = {};
                this.listeners = Object.create(null);
                this.hidden = Boolean(attributes.hidden);
                this.disabled = Boolean(attributes.disabled);
                this.checked = Boolean(attributes.checked);
                this.value = attributes.value || "";
                this.textContent = attributes.textContent || "";
                this.classList = new FakeClassList();
                this.style = {setProperty() {}};
                this.selectionStart = 0;
                this.selectionEnd = 0;
                this.selectionCalls = [];
                this.scrollTop = 0;
                this.focusCount = 0;
              }
              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }
              dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                (this.listeners[type] || []).slice().forEach(listener => listener(event));
              }
              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? String(this.attributes[name]) : null;
              }
              setAttribute(name, value) { this.attributes[name] = String(value); }
              removeAttribute(name) { delete this.attributes[name]; }
              contains(target) { return target === this || (target && target.parent === this); }
              closest() { return null; }
              focus() { this.focusCount += 1; }
              click() { this.dispatch("click", {stopPropagation() {}}); }
              setSelectionRange(start, end) {
                this.selectionStart = start;
                this.selectionEnd = end;
                this.selectionCalls.push([start, end]);
              }
              scrollIntoView() {}
              getBoundingClientRect() { return {left: 0, width: 1000}; }
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            function createFixture(readyState, initialResult) {
              const root = new FakeElement("log-workbench");
              root.dataset = {
                indexUrl: "/",
                exportUrl: "/export",
                peopleSearchUrl: "/people",
                datingUrl: "/dating"
              };
              const form = new FakeElement("log-filter-form");
              const modeSelect = new FakeElement("analysis-mode", {value: "general"});
              const analyzeButton = new FakeElement("analyze-log-btn", {
                textContent: "分析日志"
              });
              const logText = new FakeElement("log_text");
              logText.value = "zero\nneedle\nline needle\nend";
              const resultText = new FakeElement("result-text");
              resultText.value = initialResult;
              const rawView = new FakeElement("raw-log-view");
              const filteredView = new FakeElement("filtered-log-view", {hidden: true});
              const rawViewButton = new FakeElement("raw-log-view-btn", {
                "aria-selected": "true"
              });
              const filteredViewButton = new FakeElement("filtered-log-view-btn", {
                "aria-selected": "false"
              });
              const searchInput = new FakeElement("result-search");
              const searchCount = new FakeElement("search-count");
              const actionMessage = new FakeElement("action-message", {hidden: true});
              const toast = new FakeElement("workbench-toast", {hidden: true});
              const focusStatus = new FakeElement("log-focus-status");
              const staleStatus = new FakeElement("analysis-stale", {hidden: true});
              const lineCount = new FakeElement("log-line-count");
              const byteCount = new FakeElement("log-byte-count");
              const exportLogButton = new FakeElement("export-log-content-btn", {
                textContent: "导出日志"
              });
              const exportFilteredButton = new FakeElement("export-filtered-result-btn", {
                textContent: "导出过滤结果"
              });
              const copyButton = new FakeElement("copy-btn", {textContent: "复制过滤结果"});
              const toggle = new FakeElement("method-toggle");
              const dropdown = new FakeElement("method-dropdown");
              const container = new FakeElement("multi-select");
              const toggleText = new FakeElement("method-toggle-text");
              const allMethod = new FakeElement("all-method", {checked: true});
              const methodOne = new FakeElement("method-one", {value: "GetMe"});
              const methodTwo = new FakeElement("method-two", {value: "GetTask"});
              const methods = [allMethod, methodOne, methodTwo];
              const selectAll = new FakeElement("btn-select-all");
              const deselectAll = new FakeElement("btn-deselect-all");
              const previousButton = new FakeElement("search-prev-btn");
              const nextButton = new FakeElement("search-next-btn");
              const loadingMask = new FakeElement("workbench-loading-mask", {hidden: true});
              const elements = {
                "log-workbench": root,
                "log-filter-form": form,
                "log-analysis-form": form,
                "analysis-mode": modeSelect,
                "analyze-log-btn": analyzeButton,
                "log_text": logText,
                "result-text": resultText,
                "raw-log-view": rawView,
                "filtered-log-view": filteredView,
                "raw-log-view-btn": rawViewButton,
                "filtered-log-view-btn": filteredViewButton,
                "result-search": searchInput,
                "search-count": searchCount,
                "action-message": actionMessage,
                "workbench-toast": toast,
                "log-focus-status": focusStatus,
                "analysis-stale": staleStatus,
                "log-line-count": lineCount,
                "log-byte-count": byteCount,
                "export-log-content-btn": exportLogButton,
                "export-filtered-result-btn": exportFilteredButton,
                "copy-btn": copyButton,
                "method-toggle": toggle,
                "method-dropdown": dropdown,
                "multi-select": container,
                "method-toggle-text": toggleText,
                "btn-select-all": selectAll,
                "btn-deselect-all": deselectAll,
                "search-prev-btn": previousButton,
                "search-next-btn": nextButton,
                "workbench-loading-mask": loadingMask
              };
              dropdown.querySelectorAll = selector => {
                if (selector === 'input[name="method"]') return methods;
                if (selector === 'input[name="method"]:checked') return methods.filter(item => item.checked);
                if (selector === 'input[name="method"]:not([data-is-all="1"])') return methods.slice(1);
                return [];
              };
              dropdown.querySelector = selector =>
                selector === 'input[data-is-all="1"]' ? allMethod : null;
              root.querySelectorAll = () => [];
              form.requestSubmitCount = 0;
              form.submitCount = 0;
              form.requestSubmit = () => { form.requestSubmitCount += 1; };
              form.submit = () => { form.submitCount += 1; };

              const documentListeners = Object.create(null);
              const document = {
                readyState,
                getElementById(id) { return elements[id] || null; },
                querySelector(selector) {
                  return selector === '#method-dropdown input[data-is-all="1"]' ? allMethod : null;
                },
                addEventListener(type, listener) {
                  (documentListeners[type] ||= []).push(listener);
                },
                removeEventListener(type, listener) {
                  documentListeners[type] = (documentListeners[type] || []).filter(
                    registered => registered !== listener
                  );
                },
                dispatch(type, event = {}) {
                  (documentListeners[type] || []).slice().forEach(listener => listener(event));
                }
              };
              Object.defineProperty(document, "cookie", {
                get() { return "tp_csrf=csrf%20token"; }
              });

              const fetchCalls = [];
              let pendingFetchResolve = null;
              let copiedText = null;
              const window = {
                getComputedStyle() { return {lineHeight: "20px"}; },
                navigator: {
                  clipboard: {
                    writeText(value) { copiedText = value; return Promise.resolve(); }
                  }
                },
                fetch(url, options) {
                  fetchCalls.push({url, options});
                  if (readyState === "race") {
                    return new Promise(resolve => { pendingFetchResolve = resolve; });
                  }
                  return Promise.resolve({
                    ok: true,
                    text: () => Promise.resolve(JSON.stringify({path: "/tmp/export.log"}))
                  });
                }
              };
              const context = {
                window,
                document,
                Promise,
                Array,
                Object,
                String,
                Number,
                Math,
                Set,
                TypeError,
                JSON,
                setTimeout,
                clearTimeout,
                console
              };
              return {
                root, form, modeSelect, analyzeButton, logText, resultText,
                rawView, filteredView, rawViewButton, filteredViewButton,
                searchInput, searchCount, actionMessage, toast, focusStatus,
                staleStatus, exportLogButton, exportFilteredButton, copyButton,
                toggle, dropdown, container, toggleText, allMethod, methodOne,
                methodTwo, selectAll, deselectAll, previousButton, nextButton,
                loadingMask, document, window, context, fetchCalls,
                get pendingFetchResolve() { return pendingFetchResolve; },
                setPendingFetchResolve(value) { pendingFetchResolve = value; },
                get copiedText() { return copiedText; }
              };
            }

            function loadScript(path, fixture) {
              vm.runInNewContext(fs.readFileSync(path, "utf8"), fixture.context);
            }

            function wait(milliseconds) {
              return new Promise(resolve => setTimeout(resolve, milliseconds));
            }

            (async () => {
              const scenario = process.argv[3];
              const fixture = createFixture(
                scenario === "filter-init" ? "loading" :
                  scenario === "export-race" ? "race" : "complete",
                scenario === "filter-empty" ? "" : "filtered result"
              );
              const corePath = process.argv[1];
              const filterPath = process.argv[2];
              loadScript(corePath, fixture);

              if (scenario === "async-failure") {
                const api = fixture.window.LogWorkbench;
                fixture.logText.value = "changed";
                fixture.logText.dispatch("input");
                api.registerAnalysisMode("people", {
                  analyze() { return Promise.resolve({ok: false, message: "业务失败"}); }
                });
                fixture.modeSelect.value = "people";
                await api.analyzeSelectedMode();
                await Promise.resolve();
                assert(api.state.dirty, "业务失败错误地清除了 stale 状态");
                assert(!fixture.staleStatus.hidden, "业务失败未保留 stale 提示");
                assert(fixture.exportFilteredButton.disabled, "业务失败重新启用了旧结果导出");
                assert(fixture.actionMessage.textContent.includes("业务失败"),
                  "业务失败未显示错误消息");
              } else if (scenario === "async-success-keeps-filter-stale") {
                const api = fixture.window.LogWorkbench;
                api.markAnalysisFresh();
                fixture.logText.value = "changed after filter";
                fixture.logText.dispatch("input");
                assert(api.state.dirty && fixture.exportFilteredButton.disabled,
                  "People/Dating 回归的前置 stale 状态未建立");
                for (const modeName of ["people", "dating"]) {
                  api.registerAnalysisMode(modeName, {
                    analyze() {
                      return Promise.resolve({ok: true, mode: modeName});
                    }
                  });
                  fixture.modeSelect.value = modeName;
                  await api.analyzeSelectedMode();
                  assert(api.state.dirty,
                    modeName + " 成功时错误清除了 Filter stale");
                  assert(fixture.exportFilteredButton.disabled,
                    modeName + " 成功时错误重新启用了旧 Filter 导出");
                  assert(fixture.resultText.value === "filtered result",
                    modeName + " 成功时不应改写 Filter result-text");
                }
              } else if (scenario === "async-failure-success-keeps-filter-fresh") {
                const api = fixture.window.LogWorkbench;
                api.markAnalysisFresh();
                assert(!api.state.dirty && !fixture.exportFilteredButton.disabled,
                  "异步失败回归的 Filter fresh 前置状态未建立");
                for (const modeName of ["people", "dating"]) {
                  let attempt = 0;
                  api.registerAnalysisMode(modeName, {
                    analyze() {
                      attempt += 1;
                      if (attempt === 1) {
                        if (modeName === "people") {
                          return Promise.reject(new Error("people 请求失败"));
                        }
                        return Promise.resolve({ok: false, message: "dating 业务失败"});
                      }
                      return Promise.resolve({ok: true, mode: modeName});
                    }
                  });
                  fixture.modeSelect.value = modeName;
                  await api.analyzeSelectedMode();
                  assert(!api.state.dirty && !fixture.exportFilteredButton.disabled,
                    modeName + " 失败时错误污染了 Filter freshness");
                  assert(fixture.resultText.value === "filtered result",
                    modeName + " 失败时不应改写 Filter result-text");
                  await api.analyzeSelectedMode();
                  assert(!api.state.dirty && !fixture.exportFilteredButton.disabled,
                    modeName + " 成功重试后未恢复/保持 Filter fresh");
                  assert(fixture.resultText.value === "filtered result",
                    modeName + " 成功重试时不应改写 Filter result-text");
                }
              } else if (scenario === "phase-lock") {
                const api = fixture.window.LogWorkbench;
                let analyzeCount = 0;
                let resolveAnalysis;
                const pending = new Promise(resolve => { resolveAnalysis = resolve; });
                api.registerAnalysisMode("people", {
                  analyze() {
                    analyzeCount += 1;
                    return pending.then(() => ({ok: true}));
                  }
                });
                fixture.modeSelect.value = "people";
                const running = api.analyzeSelectedMode();
                fixture.modeSelect.value = "general";
                api.analyzeSelectedMode();
                assert(fixture.form.requestSubmitCount === 0,
                  "异步 loading 期间通用模式仍发起 POST");
                resolveAnalysis();
                await running;
                fixture.modeSelect.value = "general";
                api.analyzeSelectedMode();
                assert(api.state.phase === "submitting",
                  "通用 POST 未进入 submitting 锁定状态");
                fixture.modeSelect.value = "people";
                api.analyzeSelectedMode();
                assert(analyzeCount === 1, "通用 POST 期间异步模式仍被启动");
              } else {
                loadScript(filterPath, fixture);
                const api = fixture.window.LogWorkbench;
                if (scenario === "filter-init") {
                  const cachedExport = api.exportLog;
                  assert(typeof cachedExport === "function",
                    "DOMContentLoaded 前 api.exportLog 尚未可供内联脚本缓存");
                  fixture.document.dispatch("DOMContentLoaded");
                  await cachedExport("analysis_report", "report body");
                  assert(fixture.fetchCalls.length === 1, "缓存的导出引用未发起请求");
                  assert(fixture.fetchCalls[0].options.headers["X-CSRF-Token"] === "csrf token",
                    "缓存导出未携带 CSRF");
                }
                if (scenario === "filter-empty") {
                  assert(fixture.exportFilteredButton.disabled,
                    "初始无过滤结果时导出按钮未禁用");
                  assert(fixture.filteredViewButton.disabled,
                    "初始无过滤结果时过滤视图未禁用");
                }
                if (scenario === "filter-controls") {
                  fixture.toggle.dispatch("keydown", {
                    key: "Enter", preventDefault() {}
                  });
                  assert(fixture.dropdown.classList.contains("open"),
                    "method 下拉 Enter 未打开");
                  fixture.methodOne.checked = true;
                  fixture.methodOne.dispatch("change");
                  assert(!fixture.allMethod.checked && fixture.toggleText.textContent === "GetMe",
                    "method 单选未同步全部状态与文案");
                  fixture.document.dispatch("click", {target: new FakeElement("outside")});
                  assert(fixture.form.requestSubmitCount === 1,
                    "method 选择变化后外部点击未自动提交");
                  fixture.toggle.dispatch("keydown", {
                    key: "Space", preventDefault() {}
                  });
                  fixture.toggle.dispatch("keydown", {
                    key: "Escape", preventDefault() {}
                  });
                  fixture.selectAll.dispatch("click", {preventDefault() {}});
                  assert(fixture.methodOne.checked && fixture.methodTwo.checked && !fixture.allMethod.checked,
                    "全选未保留 method 多选行为");
                  fixture.deselectAll.dispatch("click", {preventDefault() {}});
                  assert(fixture.allMethod.checked && !fixture.methodOne.checked && !fixture.methodTwo.checked,
                    "取消全选未恢复全部 method");

                  fixture.searchInput.value = "needle";
                  fixture.searchInput.dispatch("input");
                  assert(fixture.searchCount.textContent === "4 行",
                    "debounce 前不应提前刷新搜索结果");
                  await wait(180);
                  assert(fixture.logText.selectionStart === 5 && fixture.logText.selectionEnd === 11,
                    "debounce 后未选择第一处字符串偏移");
                  fixture.searchInput.dispatch("keydown", {
                    key: "Enter", shiftKey: false, preventDefault() {}
                  });
                  assert(fixture.logText.selectionStart === 17 && fixture.logText.selectionEnd === 23,
                    "Enter 未前进到下一处匹配");
                  fixture.searchInput.dispatch("keydown", {
                    key: "Enter", shiftKey: true, preventDefault() {}
                  });
                  assert(fixture.logText.selectionStart === 5 && fixture.logText.selectionEnd === 11,
                    "Shift+Enter 未回到上一处匹配");

                  fixture.logText.value = "one\r\ntwo\r\nthree";
                  api.focusLogLines(2, 3);
                  assert(fixture.logText.selectionStart === 5 && fixture.logText.selectionEnd === 15,
                    "CRLF 行号定位未使用真实偏移");
                  fixture.logText.dispatch("input");
                  assert(api.state.dirty && fixture.exportFilteredButton.disabled,
                    "日志修改未标 stale 或禁用旧结果导出");
                  assert(fixture.resultText.value === "filtered result",
                    "日志修改不应清空旧过滤结果");
                  await api.copyResult();
                  assert(fixture.copiedText === "filtered result", "复制未读取只读 textarea 值");
                  await api.exportLog("log_content");
                  const call = fixture.fetchCalls[fixture.fetchCalls.length - 1];
                  assert(call.url === "/export" && call.options.method === "POST",
                    "导出未使用 data endpoint 和 POST");
                  assert(call.options.headers["X-CSRF-Token"] === "csrf token",
                    "导出请求未携带 CSRF");
                  assert(JSON.parse(call.options.body).content === fixture.logText.value,
                    "日志导出未读取当前 textarea 字符串");
                }
                if (scenario === "export-race") {
                  api.markAnalysisFresh();
                  const exporting = api.exportLog("filtered_result");
                  fixture.logText.value = "changed\nlog";
                  fixture.logText.dispatch("input");
                  assert(fixture.exportFilteredButton.disabled,
                    "竞态测试中日志修改未立即禁用导出");
                  fixture.pendingFetchResolve({
                    ok: true,
                    text: () => Promise.resolve(JSON.stringify({path: "/tmp/export.log"}))
                  });
                  await exporting;
                  assert(fixture.exportFilteredButton.disabled,
                    "导出 finally 无条件重新启用了 stale 结果");
                }
              }
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path), str(filter_path), scenario],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr or completed.stdout,
        )

    def test_page_uses_single_log_workbench_shell(self):
        """根页面必须交付单日志壳层，且不得残留双日志比较入口。"""
        html = self.client.get("/").get_data(as_text=True)
        for marker in (
            'id="log-workbench"',
            'id="analysis-mode"',
            'id="analyze-log-btn"',
            'id="workbench-log-pane"',
            'id="workbench-result-pane"',
            'id="overviewPanel"',
            'id="interfacesPanel"',
            'id="timelinePanel"',
            'id="resultPanel"',
            'id="checksPanel"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn("双日志对比", html)
        self.assertNotIn('id="compareView"', html)

    def test_blueprint_static_assets_follow_base_path(self):
        """静态资源必须由 tool Blueprint 管理，并随部署前缀一同生成。"""
        app = create_app("/log-tool")
        app.config["TESTING"] = True
        client = app.test_client()
        html = client.get("/log-tool/").get_data(as_text=True)
        self.assertIn("/log-tool/static/css/log-workbench.css", html)
        # Flask 的静态响应持有文件句柄；上下文管理器确保测试结束前主动关闭。
        with client.get("/log-tool/static/js/workbench-core.js") as response:
            self.assertEqual(response.status_code, 200)

    def test_styles_use_prototype_visual_tokens(self):
        """工作台必须使用原型固定色值、圆角、字体与 39% 默认左栏。"""
        css = Path("static/css/log-workbench.css").read_text(encoding="utf-8")

        for token in (
            "--page: #f5f5f7;",
            "--surface: #ffffff;",
            "--surface-subtle: #fafafa;",
            "--surface-selected: #f0f7ff;",
            "--text: #1d1d1f;",
            "--text-secondary: #6e6e73;",
            "--line: rgba(0, 0, 0, 0.11);",
            "--accent: #0071e3;",
            "--success: #147a3d;",
            "--warning: #8a5a00;",
            "--danger: #c6292e;",
            "--radius-control: 9px;",
            "--radius-panel: 14px;",
            "--left-pane: 39%;",
        ):
            self.assertIn(token, css)
        # Task 1 已具备 reduced-motion 基础，此处只锁定不可回退的无动效合同。
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("transition-duration: 0.01ms !important;", css)

    def test_layout_keeps_scrolling_inside_1280px_desktop_panes(self):
        """桌面壳层不得让页面纵向滚动，两侧内容应在各自 pane 内滚动。"""
        css = Path("static/css/log-workbench.css").read_text(encoding="utf-8")
        compact_css = " ".join(css.split())

        self.assertIn(
            "grid-template-columns: minmax(360px, var(--left-pane)) "
            "8px minmax(540px, 1fr);",
            compact_css,
        )
        self.assertIn("height: calc(100vh - 72px);", compact_css)
        self.assertIn("min-width: 1280px;", compact_css)
        self.assertRegex(compact_css, r"body \{[^}]*overflow: hidden;")
        self.assertRegex(
            compact_css,
            r"\.workspace > \.workbench-pane \{[^}]*overflow: auto;",
        )

    def test_resizer_markup_exposes_task_two_percentage_range(self):
        """separator 的 ARIA 范围必须与 32%–55% 夹取和 39% 默认值一致。"""
        html = self.client.get("/").get_data(as_text=True)

        self.assertIn('role="separator"', html)
        self.assertIn('aria-valuemin="32"', html)
        self.assertIn('aria-valuemax="55"', html)
        self.assertIn('aria-valuenow="39"', html)

    def test_tab_api_syncs_visibility_selection_and_keyboard_focus(self):
        """动态标签 API 只能在可见标签中同步选择、panel 与键盘焦点。"""
        self._run_task_two_core_harness("tabs")

    def test_resizer_clamps_pointer_and_moves_keyboard_by_16px(self):
        """拖动与键盘调整必须夹在 32%–55%，且键盘步长为真实 16px。"""
        self._run_task_two_core_harness("resizer")

    def test_core_keeps_safe_rendering_and_ephemeral_resizer_state(self):
        """核心不得恢复 HTML 字符串写入，也不得持久化栏宽。"""
        javascript = Path("static/js/workbench-core.js").read_text(encoding="utf-8")

        for forbidden in (
            "innerHTML",
            "insertAdjacentHTML",
            "localStorage",
            "document.cookie",
        ):
            self.assertNotIn(forbidden, javascript)

    def test_page_has_no_inline_event_handler_attributes(self):
        """页面事件必须通过脚本绑定，禁止 CSP 不友好的字符串事件处理器。"""
        parser = _WorkbenchMarkupParser()
        parser.feed(self.client.get("/").get_data(as_text=True))

        self.assertEqual([], parser.inline_event_attributes)

    def test_core_script_loads_before_business_adapter(self):
        """核心命名空间必须先建立，People 适配器才能注册工作台模式。"""
        parser = _WorkbenchMarkupParser()
        parser.feed(self.client.get("/").get_data(as_text=True))

        core_index = next(
            index
            for index, script in enumerate(parser.scripts)
            if (script["src"] or "").endswith("/static/js/workbench-core.js")
        )
        business_index = next(
            index
            for index, script in enumerate(parser.scripts)
            if (script["src"] or "").endswith("/static/js/workbench-people.js")
        )

        self.assertLess(core_index, business_index)

        filter_index = next(
            index
            for index, script in enumerate(parser.scripts)
            if (script["src"] or "").endswith("/static/js/workbench-filter.js")
        )
        self.assertLess(filter_index, business_index)
        self.assertFalse(
            any("function analyzePeopleSearch" in "".join(script["content"])
                for script in parser.scripts),
            "People 分析函数不应继续内联在模板中",
        )

    def test_async_modes_share_busy_lock_loading_and_result_panel_lifecycle(self):
        """People/Dating 连续提交只运行一次，并在完成后恢复统一入口和结果页。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行无第三方依赖的前端行为回归测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeElement {
              constructor(id, attributes = {}) {
                this.id = id;
                this.attributes = {...attributes};
                this.dataset = {};
                this.listeners = Object.create(null);
                this.hidden = Boolean(attributes.hidden);
                this.disabled = false;
                this.textContent = attributes.textContent || "";
                this.tabIndex = attributes.tabIndex || 0;
                this.style = {setProperty() {}};
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? String(this.attributes[name]) : null;
              }

              setAttribute(name, value) {
                this.attributes[name] = String(value);
              }

              removeAttribute(name) {
                delete this.attributes[name];
              }

              focus() {}
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            (async () => {
              const root = new FakeElement("log-workbench");
              root.dataset = {
                indexUrl: "/",
                exportUrl: "/export",
                peopleSearchUrl: "/people",
                datingUrl: "/dating"
              };
              const overviewTab = new FakeElement("overviewTab", {
                "aria-controls": "overviewPanel",
                "aria-selected": "true"
              });
              const resultTab = new FakeElement("resultTab", {
                "aria-controls": "resultPanel",
                "aria-selected": "false"
              });
              const overviewPanel = new FakeElement("overviewPanel");
              const resultPanel = new FakeElement("resultPanel", {hidden: true});
              const form = new FakeElement("log-analysis-form");
              const modeSelect = new FakeElement("analysis-mode");
              const submitButton = new FakeElement("analyze-log-btn", {
                textContent: "分析日志"
              });
              const loadingMask = new FakeElement("workbench-loading-mask", {hidden: true});
              const toast = new FakeElement("workbench-toast", {hidden: true});
              const tabs = [overviewTab, resultTab];
              root.querySelectorAll = selector =>
                selector === '[role="tab"][aria-controls]' ? tabs : [];

              const elements = {
                "log-workbench": root,
                "overviewTab": overviewTab,
                "resultTab": resultTab,
                "overviewPanel": overviewPanel,
                "resultPanel": resultPanel,
                "log-analysis-form": form,
                "analysis-mode": modeSelect,
                "analyze-log-btn": submitButton,
                "workbench-loading-mask": loadingMask,
                "workbench-toast": toast
              };
              const document = {
                readyState: "complete",
                getElementById(id) { return elements[id] || null; },
                addEventListener() {}
              };
              const window = {};
              vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
                window,
                document,
                Promise,
                Array,
                Object,
                String,
                Number,
                Math,
                TypeError
              });

              const submit = form.listeners.submit[0];
              assert(typeof submit === "function", "统一表单未绑定 submit 处理器");

              async function verifyMode(modeName) {
                let runCount = 0;
                let finishRun;
                const pending = new Promise(resolve => { finishRun = resolve; });
                window.LogWorkbench.registerMode(modeName, {
                  run() {
                    runCount += 1;
                    return pending;
                  }
                });
                modeSelect.value = modeName;
                window.LogWorkbench.activateTab("overviewPanel", false);

                let prevented = 0;
                const event = {preventDefault() { prevented += 1; }};
                submit(event);
                submit(event);

                assert(prevented === 2, modeName + " 两次异步提交都应阻止原生 POST");
                assert(runCount === 1, modeName + " busy 期间发生了重复请求");
                assert(submitButton.disabled, modeName + " 请求期间统一按钮未禁用");
                assert(submitButton.textContent === "分析中...", modeName + " 未显示分析中文案");
                assert(loadingMask.hidden === false, modeName + " 请求期间未显示 loading");

                finishRun();
                await pending;
                await Promise.resolve();
                await Promise.resolve();

                assert(!submitButton.disabled, modeName + " 完成后统一按钮未恢复");
                assert(submitButton.textContent === "分析日志", modeName + " 完成后按钮文案未恢复");
                assert(loadingMask.hidden, modeName + " 完成后 loading 未隐藏");
                assert(resultPanel.hidden === false, modeName + " 完成后未切到 resultPanel");
                assert(resultTab.getAttribute("aria-selected") === "true",
                  modeName + " 完成后 resultTab 未激活");
              }

              await verifyMode("people-search");
              await verifyMode("dating");
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            0,
            completed.returncode,
            completed.stderr or completed.stdout,
        )

    def _run_task_five_core_lifecycle_harness(self, scenario):
        """在最小 DOM 沙箱中验证 Task 5 的错误 panel 与模式 owner 生命周期。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 Task 5 核心生命周期测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeElement {
              constructor(id, attributes = {}) {
                this.id = id;
                this.attributes = {...attributes};
                this.dataset = {};
                this.listeners = Object.create(null);
                this.children = [];
                this.hidden = Boolean(attributes.hidden);
                this.disabled = Boolean(attributes.disabled);
                this.textContent = attributes.textContent || "";
                this.value = attributes.value || "";
                this.tabIndex = Number(attributes.tabIndex || 0);
                this.style = {setProperty() {}};
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                return Promise.all((this.listeners[type] || []).map(listener => listener(event)));
              }

              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? String(this.attributes[name]) : null;
              }

              setAttribute(name, value) {
                this.attributes[name] = String(value);
              }

              removeAttribute(name) {
                delete this.attributes[name];
              }

              focus() {}
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            const root = new FakeElement("log-workbench");
            root.dataset = {indexUrl: "/", exportUrl: "/export"};
            const overviewTab = new FakeElement("overviewTab", {
              "aria-controls": "overviewPanel", "aria-selected": "true"
            });
            const resultTab = new FakeElement("resultTab", {
              "aria-controls": "resultPanel", "aria-selected": "false"
            });
            const overviewPanel = new FakeElement("overviewPanel");
            const resultPanel = new FakeElement("resultPanel", {hidden: true});
            const form = new FakeElement("log-analysis-form");
            const modeSelect = new FakeElement("analysis-mode", {value: "dating"});
            const submitButton = new FakeElement("analyze-log-btn", {
              textContent: "分析日志"
            });
            const loadingMask = new FakeElement("workbench-loading-mask", {hidden: true});
            const toast = new FakeElement("workbench-toast", {hidden: true});
            const logText = new FakeElement("log_text", {value: "raw log"});
            const filteredResult = new FakeElement("result-text", {
              value: "existing filter result"
            });
            const filterExport = new FakeElement("export-filtered-result-btn");
            const staleMessage = new FakeElement("analysis-stale", {hidden: true});
            const datingSurface = new FakeElement("dating-result");
            const datingMarkdown = new FakeElement("export-dating-report-btn");
            const datingJson = new FakeElement("export-dating-json-btn");
            const tabs = [overviewTab, resultTab];
            root.querySelectorAll = selector =>
              selector === '[role="tab"][aria-controls]' ? tabs : [];
            const elements = {
              "log-workbench": root,
              overviewTab, resultTab, overviewPanel, resultPanel,
              "log-analysis-form": form,
              "analysis-mode": modeSelect,
              "analyze-log-btn": submitButton,
              "workbench-loading-mask": loadingMask,
              "workbench-toast": toast,
              "log_text": logText,
              "result-text": filteredResult,
              "export-filtered-result-btn": filterExport,
              "analysis-stale": staleMessage,
              "dating-result": datingSurface,
              "export-dating-report-btn": datingMarkdown,
              "export-dating-json-btn": datingJson
            };
            const document = {
              readyState: "complete",
              getElementById(id) { return elements[id] || null; },
              addEventListener() {}
            };
            const window = {};
            vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
              window, document, Promise, Array, Object, String, Number, Math, TypeError
            });

            (async () => {
              const api = window.LogWorkbench;
              const scenario = process.argv[2];
              if (scenario === "dating-error") {
                api.registerAnalysisMode("dating", {
                  errorPanel: "overviewPanel",
                  analyze() {
                    return Promise.resolve({ok: false, message: "TASK_NOT_FOUND"});
                  }
                });
                modeSelect.value = "dating";
                await api.analyzeSelectedMode();
                assert(overviewTab.getAttribute("aria-selected") === "true",
                  "Dating 失败后应停留在 Overview");
                assert(resultTab.getAttribute("aria-selected") === "false",
                  "Dating 失败后不能被核心强制切到 Result");

                api.registerAnalysisMode("people", {
                  analyze() {
                    return Promise.resolve({ok: false, message: "PEOPLE_FAILED"});
                  }
                });
                modeSelect.value = "people";
                await api.analyzeSelectedMode();
                assert(resultTab.getAttribute("aria-selected") === "true",
                  "People 失败仍应保留既有 Result panel 行为");
              } else if (scenario === "dating-stale") {
                let datingStaleCalls = 0;
                api.registerAnalysisMode("dating", {
                  onInputRevision() {
                    datingStaleCalls += 1;
                    datingSurface.textContent = "";
                    datingMarkdown.disabled = true;
                    datingJson.disabled = true;
                  },
                  analyze() {
                    datingSurface.textContent = "dating result";
                    datingMarkdown.disabled = false;
                    datingJson.disabled = false;
                    return Promise.resolve({ok: true});
                  }
                });
                modeSelect.value = "dating";
                await api.analyzeSelectedMode();
                assert(datingSurface.textContent === "dating result",
                  "测试前置：Dating 应已有自己的结果");
                assert(!datingMarkdown.disabled && !datingJson.disabled,
                  "测试前置：Dating 导出应已启用");

                logText.value = "edited log";
                await logText.dispatch("input");
                assert(datingStaleCalls === 1,
                  "日志修订必须只通知当前 Dating owner 一次");
                assert(datingSurface.textContent === "",
                  "日志修订后不能保留 Dating 旧结果");
                assert(datingMarkdown.disabled && datingJson.disabled,
                  "日志修订后必须禁用 Dating Markdown/JSON 导出");
                assert(filteredResult.value === "existing filter result",
                  "Dating stale 不能污染 Filter 结果");
                assert(filterExport.disabled,
                  "日志修订后 Filter 导出仍应保持 stale 禁用");
                assert(api.state.dirty === true,
                  "日志修订必须保留核心 dirty 状态");
              } else {
                throw new Error("未知 Task 5 生命周期场景: " + scenario);
              }
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path), scenario],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_dating_async_failure_stays_overview_without_changing_people_behavior(self):
        """Dating 失败应展示 Overview 错误；People 失败仍沿用 Result panel。"""
        self._run_task_five_core_lifecycle_harness("dating-error")

    def test_dating_input_revision_clears_only_dating_results_and_exports(self):
        """日志修订必须调用 Dating stale owner，且不污染 Filter 既有结果。"""
        self._run_task_five_core_lifecycle_harness("dating-stale")

    def test_task_three_log_pane_keeps_textareas_and_single_dispatch_button(self):
        """日志窗格只能保留两个 textarea 与一个统一分析按钮。"""
        html = self.client.get("/").get_data(as_text=True)

        self.assertIn('<textarea id="log_text"', html)
        self.assertIn('<textarea id="result-text"', html)
        self.assertRegex(html, r'<textarea[^>]*id="result-text"[^>]*readonly')
        self.assertEqual(html.count('id="analyze-log-btn"'), 1)
        self.assertIn('id="log-filter-form"', html)
        self.assertIn('id="raw-log-view-btn"', html)
        self.assertIn('id="filtered-log-view-btn"', html)
        self.assertNotIn('class="log-line"', html)
        self.assertNotIn("<mark", html)

    def test_task_three_scripts_never_write_untrusted_html(self):
        """所有工作台静态脚本都不得批量写入 HTML 或插入标记节点。"""
        scripts = sorted(Path("static/js").glob("workbench-*.js"))
        self.assertIn(Path("static/js/workbench-filter.js"), scripts)
        for path in scripts:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("innerHTML", source)
            self.assertNotIn("insertAdjacentHTML", source)

    def test_task_three_core_dispatches_modes_and_prevents_duplicate_async_runs(self):
        """通用模式走既有 POST，异步适配器由核心分发且 loading 时去重。"""
        self._run_task_three_core_harness("dispatch")

    def test_task_three_core_searches_text_and_focuses_real_log_lines(self):
        """搜索、行号定位和日志编辑 stale 都基于 textarea 的真实文本。"""
        self._run_task_three_core_harness("search-focus-stale")

    def test_task_three_filter_exports_are_available_before_dom_ready(self):
        """外部过滤脚本必须先暴露 API，避免既有内联适配器缓存 undefined。"""
        self._run_task_three_review_harness("filter-init")

    def test_task_three_filter_controls_use_real_dom_behavior(self):
        """真实加载过滤脚本并覆盖 method、搜索、复制、导出和 CRLF 定位。"""
        self._run_task_three_review_harness("filter-controls")

    def test_task_three_empty_result_and_export_race_keep_export_disabled(self):
        """空结果立即禁用导出，日志竞态结束后也不能重新启用 stale 导出。"""
        self._run_task_three_review_harness("filter-empty")
        self._run_task_three_review_harness("export-race")

    def test_task_three_async_errors_keep_stale_and_phase_lock_modes(self):
        """业务失败保持 stale；通用 POST 与异步分析共享入口锁。"""
        self._run_task_three_review_harness("async-failure")
        self._run_task_three_review_harness("phase-lock")

    def test_task_three_async_modes_do_not_freshen_filter_result(self):
        """People/Dating 成功也不能清除未更新 result-text 的 Filter stale。"""
        self._run_task_three_review_harness("async-success-keeps-filter-stale")

    def test_task_three_async_failures_do_not_pollute_filter_freshness(self):
        """Filter fresh 时异步失败及重试不得改写 Filter dirty/stale 或结果。"""
        self._run_task_three_review_harness("async-failure-success-keeps-filter-fresh")

    def test_task_three_disabled_dating_flag_hides_dating_endpoint_capability(self):
        """Dating 关闭时页面不得输出可被核心误读的 Dating endpoint。"""
        app = create_app()
        app.config["TESTING"] = True
        app.config["DATING_STRUCTURED_ANALYZER_ENABLED"] = False
        html = app.test_client().get("/").get_data(as_text=True)

        self.assertNotIn('data-dating-url="', html)
        self.assertNotIn('value="dating"', html)

    def test_dating_adapter_keeps_reply_and_relationship_poll_samples(self):
        """Dating 适配器必须保留 Reply 11 条与 Relationship 21 条重复 Poll。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 Dating 适配器行为测试")
        adapter_path = Path(__file__).resolve().parents[1] / "static/js/workbench-dating.js"
        self.assertTrue(adapter_path.exists(), "Task 5 必须创建 Dating 静态适配器")
        if not adapter_path.exists():
            return

        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeElement {
              constructor(tagName, id = "", attributes = {}) {
                this.tagName = String(tagName).toUpperCase();
                this.id = id;
                this.attributes = {...attributes};
                this.children = [];
                this.listeners = Object.create(null);
                this.hidden = Boolean(attributes.hidden);
                this.disabled = Boolean(attributes.disabled);
                this.value = attributes.value ?? "";
                this.open = Boolean(attributes.open);
                this._textContent = attributes.textContent || "";
              }

              get textContent() {
                return this._textContent + this.children.map(child => child.textContent || "").join("");
              }

              set textContent(value) {
                this._textContent = String(value ?? "");
                this.children = [];
              }

              appendChild(child) {
                this.children.push(child);
                child.parentNode = this;
                return child;
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              async dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                const results = (this.listeners[type] || []).map(listener => listener(event));
                return Promise.all(results);
              }

              setAttribute(name, value) { this.attributes[name] = String(value); }
              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? this.attributes[name] : null;
              }
              focus() {}
              scrollIntoView() {}

              querySelectorAll(selector) {
                const found = [];
                const visit = node => {
                  (node.children || []).forEach(child => {
                    if (selector === "button" && child.tagName === "BUTTON") found.push(child);
                    visit(child);
                  });
                };
                visit(this);
                return found;
              }
            }

            function textOf(node) { return String(node && node.textContent || ""); }
            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            const ids = [
              "log-workbench", "analysis-mode", "log_text", "dating-analysis", "dating-status",
              "dating-state", "dating-content", "dating-overview", "dating-interfaces",
              "dating-timeline", "dating-result", "dating-checks", "dating-verdict",
              "dating-summary-heading", "dating-verdict-detail", "dating-next-action",
              "dating-summary", "dating-lifecycle-metrics", "dating-upload-list",
              "dating-progress-diagnostics", "dating-task-timeline", "dating-result-heading",
              "dating-schema-status", "dating-result-summary", "dating-result-sections",
              "dating-field-tree-details", "dating-field-tree", "dating-field-filter",
              "dating-field-search", "dating-field-more", "dating-field-table-body",
              "dating-interface-table-body", "dating-call-count", "dating-check-list",
              "dating-check-filter", "dating-parse-warnings", "dating-warning-count",
              "dating-report", "copy-dating-report-btn", "export-dating-report-btn",
              "export-dating-json-btn", "dating-report-details"
            ];
            const elements = Object.create(null);
            for (const id of ids) {
              elements[id] = new FakeElement(id === "log-workbench" ? "main" : "div", id);
            }
            elements["analysis-mode"].value = "dating";
            elements["log_text"].value = "raw\nlog";
            elements["dating-field-filter"].value = "ALL";
            elements["dating-field-search"].value = "";
            elements["dating-field-tree-details"].open = false;
            elements["dating-analysis"].hidden = true;
            elements["dating-content"].hidden = true;
            elements["dating-overview"].hidden = true;
            elements["dating-interfaces"].hidden = true;
            elements["dating-timeline"].hidden = true;
            elements["dating-result"].hidden = true;
            elements["dating-checks"].hidden = true;

            const root = elements["log-workbench"];
            root.dataset = {datingUrl: "/prefix/dating/analyze"};
            const requests = [];
            let requestCount = 0;
            const tabs = [];
            let drawerModel = null;
            const registered = Object.create(null);
            const api = {
              registerAnalysisMode(name, definition) { registered[name] = definition; },
              setAvailableTabs(ids) { tabs.push(ids.slice()); },
              setResultHeader() {},
              focusLogLines() {},
              showActionMessage() {},
              requestJson(url, options) {
                requestCount += 1;
                requests.push({url, options});
                if (requestCount === 3) {
                  const error = new Error("TASK_NOT_FOUND");
                  error.error_code = "TASK_NOT_FOUND";
                  return Promise.reject(error);
                }
                return Promise.resolve({
                  verdict: "WARNINGS_FOUND",
                  summary: {
                    gateway_call_count: 1, upload_call_count: 0,
                    http_error_count: 0, business_error_count: 0,
                    check_fail_count: 0, check_warn_count: 1
                  },
                  calls: [{
                    call_id: "call-1", sequence: 1, transport: "gateway",
                    service_name: "DatingService", method_name: "GetTask",
                    result_class: "success", parse_status: "PARSED",
                    request: {
                      timestamp: "2026-08-30T00:00:00Z", line_start: 1, line_end: 2,
                      params: {task_id: "task-1", marker: "<unsafe>"},
                      headers: {"X-Test": "safe"}
                    },
                    response: {
                      line_start: 3, line_end: 4, http_status: 200, elapsed_ms: 4,
                      gateway: {code: 0},
                      sub_response: {success: true, code: 0},
                      data: {task_id: "task-1", result_id: "result-1", marker: "<unsafe>"},
                      headers: {"Content-Type": "application/json"}
                    },
                    warnings: []
                  }],
                  task_snapshot: {
                    task_type: requestCount === 1 ? "reply_generation" : "relationship_analysis",
                    task_id: "task-1",
                    schema_version: requestCount === 1
                      ? "dating.reply_generation.v1" : "dating.relationship_analysis.v1",
                    schema_status: "KNOWN",
                    lifecycle: {
                      terminal: true, final_status: "succeeded",
                      poll_count: requestCount === 1 ? 11 : 21,
                      duration_ms: requestCount === 1 ? 11781 : 21821
                    },
                    input_assets: [],
                    status_samples: Array.from({length: requestCount === 1 ? 11 : 21}, (_, index) => ({
                      timestamp: "2026-08-30T00:00:0" + index + "Z",
                      status: "processing", phase: "analyzing", progress_percent: 50,
                      line_start: index + 10, line_end: index + 10
                    })),
                    progress_diagnostics: {
                      distinct_progress_values: [50], unchanged_poll_count: 10,
                      stall_detected: true
                    },
                    result_payload: {
                      schema_version: requestCount === 1
                        ? "dating.reply_generation.v1" : "dating.relationship_analysis.v1",
                      roles: []
                    },
                    result_summary: {},
                    result_fields: [{
                      path: "result", parent_path: null, value: {}, value_type: "object",
                      presence: "PRESENT", schema_known: true,
                      source: {method: "GetTaskResult", line_start: 5, line_end: 6}
                    }]
                  },
                  checks: [], parse_warnings: [], report_markdown: "# Dating report"
                });
              },
              openInterfaceDrawer(model) { drawerModel = model; }
            };

            const document = {
              readyState: "complete",
              getElementById(id) { return elements[id] || null; },
              createElement(tag) { return new FakeElement(tag); },
              createTextNode(value) { return new FakeElement("text", "", {textContent: String(value)}); },
              addEventListener() {}
            };
            const window = {LogWorkbench: api, navigator: {clipboard: {writeText: () => Promise.resolve()}}};
            const context = {
              window, document, Promise, Array, Object, String, Number, Math, JSON, Set,
              TypeError, console
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

            (async () => {
              const adapter = registered.dating;
              assert(adapter && typeof adapter.analyze === "function", "Dating 模式未注册");
              const result = await adapter.analyze({root, logText: "raw\nlog"});
              assert(result && result.ok === true, "Dating 分析未返回成功结果");
              assert(requests.length === 1 && requests[0].url === "/prefix/dating/analyze",
                "Dating 未使用 root.dataset.datingUrl");
              const requestBody = typeof requests[0].options.body === "string"
                ? JSON.parse(requests[0].options.body) : requests[0].options.body;
              assert(requestBody.log_text === "raw\nlog",
                "Dating 请求未携带当前日志");
              assert(tabs[tabs.length - 1].join(",") ===
                "overviewPanel,interfacesPanel,timelinePanel,resultPanel,checksPanel",
                "Dating 未启用五个标准 panel");
              assert(elements["dating-task-timeline"].children.length === 11,
                "Reply 必须保留全部 11 条重复 Poll 状态样本");
              assert(textOf(elements["dating-progress-diagnostics"]).includes("10"),
                "Dating 未展示 progress diagnostics");

              const relationshipResult = await adapter.analyze({root, logText: "relationship\nlog"});
              assert(relationshipResult && relationshipResult.ok === true,
                "Relationship Analysis 分析未返回成功结果");
              assert(elements["dating-task-timeline"].children.length === 21,
                "Relationship Analysis 必须保留全部 21 条 status_samples");

              const rowButton = elements["dating-interface-table-body"].querySelectorAll("button")[0];
              assert(rowButton, "Dating 接口行未提供详情触发器");
              await rowButton.dispatch("click");
              assert(drawerModel && drawerModel.method === "GetTask" &&
                drawerModel.service === "DatingService" && drawerModel.transport === "gateway" &&
                drawerModel.result_class === "success" && drawerModel.parse_status === "PARSED",
                "Dating drawer payload 缺少调用元数据");
              assert(drawerModel.request.params.marker === "<unsafe>" &&
                drawerModel.response.data.marker === "<unsafe>" &&
                drawerModel.http.status === 200 && drawerModel.gateway.code === 0 &&
                drawerModel.sub_response.success === true && drawerModel.elapsed_ms === 4 &&
                drawerModel.request.headers["X-Test"] === "safe",
                "Dating drawer payload 缺少脱敏调用详情");

              const failedResult = await adapter.analyze({root, logText: "failed\nlog"});
              assert(failedResult && failedResult.ok === false,
                "Dating 失败请求必须显式返回业务失败");
              assert(elements["export-dating-report-btn"].disabled &&
                elements["export-dating-json-btn"].disabled &&
                elements["copy-dating-report-btn"].disabled,
                "Dating 失败后不能继续导出旧 Markdown/JSON");
              assert(textOf(elements["dating-report"]) === "" &&
                elements["dating-task-timeline"].children.length === 0,
                "Dating 失败后不能保留旧结果内容");

              elements["dating-overview"].hidden = false;
              elements["dating-overview"].textContent = "old dating result";
              elements["analysis-mode"].value = "people";
              await elements["analysis-mode"].dispatch("change");
              assert(elements["dating-overview"].hidden && textOf(elements["dating-overview"]) === "",
                "切换 People 后仍残留 Dating 内容");
              assert(tabs[tabs.length - 1].join(",") ===
                "overviewPanel,interfacesPanel,resultPanel,checksPanel",
                "切换 People 后仍残留 Dating 时间线标签");
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(adapter_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_people_adapter_requests_and_renders_only_people_workbench_surfaces(self):
        """People 适配器应保留确定性结论、真实证据和报告的面板边界。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 People 适配器行为测试")
        adapter_path = Path(__file__).resolve().parents[1] / "static/js/workbench-people.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeClassList {
              constructor() { this.values = new Set(); }
              add(name) { this.values.add(name); }
              remove(name) { this.values.delete(name); }
              toggle(name, force) {
                const shouldHave = force === undefined ? !this.values.has(name) : force;
                if (shouldHave) this.values.add(name); else this.values.delete(name);
                return shouldHave;
              }
            }

            class FakeElement {
              constructor(tagName, id = "") {
                this.tagName = tagName.toUpperCase();
                this.id = id;
                this.attributes = Object.create(null);
                this.children = [];
                this.listeners = Object.create(null);
                this.classList = new FakeClassList();
                this.dataset = Object.create(null);
                this.textContent = "";
                this.value = "";
                this.hidden = false;
                this.disabled = false;
              }
              appendChild(child) { this.children.push(child); return child; }
              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }
              dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                return Promise.all((this.listeners[type] || []).map(listener => listener(event)));
              }
              setAttribute(name, value) { this.attributes[name] = String(value); }
              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? this.attributes[name] : null;
              }
              querySelectorAll(selector) {
                const found = [];
                const visit = node => {
                  (node.children || []).forEach(child => {
                    if (selector === "button" && child.tagName === "BUTTON") found.push(child);
                    visit(child);
                  });
                };
                visit(this);
                return found;
              }
              focus() {}
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            function textOf(node) {
              return String(node.textContent || "") + (node.children || []).map(textOf).join(" ");
            }

            const elements = Object.create(null);
            const add = (tag, id) => {
              const element = new FakeElement(tag, id);
              elements[id] = element;
              return element;
            };

            const root = add("main", "log-workbench");
            root.dataset.peopleUrl = "/people-search/analyze";
            const logText = add("textarea", "log_text");
            logText.value = "first\nsecond\nthird";
            add("h2", "workbench-result-heading");
            add("p", "workbench-result-subheading");
            ["overviewPanel", "interfacesPanel", "timelinePanel", "resultPanel", "checksPanel"].forEach(id => add("section", id));
            ["overviewTab", "interfacesTab", "timelineTab", "resultTab", "checksTab"].forEach(id => add("button", id));
            const overview = add("div", "people-overview");
            const verdictPanel = add("section", "people-verdict-panel");
            const verdictTitle = add("h3", "people-verdict-title");
            const taskSummary = add("p", "people-task-summary");
            const aiStatus = add("p", "people-ai-status");
            const coverage = add("div", "people-coverage-list");
            const issueList = add("ul", "people-issue-list");
            const timeline = add("div", "people-timeline");
            const diagnosis = add("dl", "people-diagnosis-list");
            const cost = add("div", "people-cost-summary");
            const report = add("pre", "people-search-report");
            const checks = add("ol", "people-check-list");
            const copyButton = add("button", "copy-report-btn");
            const exportButton = add("button", "export-report-btn");

            const data = {
              verdict: "ISSUES_FOUND",
              task: {
                full_name: "<Alice>", task_id: "task-1", final_status: "FAILED",
                candidate_count: 0, result_type: "NO_RESULT", no_result_reason: "NO_MATCH",
                clue_types: ["FULL_NAME"]
              },
              coverage: {create_task: true, get_task: true, candidate_list: false,
                candidate_detail: false, debug: true, cost_summary: true},
              ai: {status: "SUCCESS"},
              timeline: [{provider: "provider-1", operation: "lookup", status: "no_result",
                no_result_reason: "NO_MATCH", result_details: {safe: "<detail>"},
                http_status: 200, cache_hit: false, cost_status: "CALCULATED",
                estimated_cost_microunit: 12}],
              diagnosis: {stop_reason: "PROVIDERS_EXHAUSTED", final_status: "FAILED"},
              cost: {total_estimated_cost_microunit: 12},
              checks: [
                {outcome: "PASS", rule_id: "R-PASS", title: "ok", actual: "a", expected: "e", evidence: []},
                {outcome: "NOT_APPLICABLE", rule_id: "R-NA", title: "na", actual: "a", expected: "", evidence: []},
                {outcome: "UNKNOWN", rule_id: "R-UNKNOWN", title: "unknown", actual: "a", expected: "", evidence: [{method: "GetTask", json_path: "missing"}]},
                {outcome: "WARN", rule_id: "R-WARN", title: "warn", actual: "a", expected: "", evidence: [{method: "GetTask", json_path: "path"}]},
                {outcome: "FAIL", rule_id: "R-FAIL", title: "<unsafe>", actual: "<actual>", expected: "expected", evidence: [{method: "GetTask", json_path: "status", line_start: 2, line_end: 3}]}
              ],
              report_markdown: "# report <not-html>"
            };

            const registered = Object.create(null);
            const requestCalls = [];
            const availableTabs = [];
            const focusCalls = [];
            const exports = [];
            let copied = "";
            const api = {
              state: {},
              registerAnalysisMode(name, definition) { registered[name] = definition; },
              getMode(name) { return registered[name] || null; },
              requestJson(url, options) {
                requestCalls.push({url, options});
                return Promise.resolve({data});
              },
              setAvailableTabs(ids) {
                availableTabs.push(ids.slice());
                ["overviewPanel", "interfacesPanel", "resultPanel", "checksPanel"].forEach(id => {
                  elements[id].hidden = !ids.includes(id);
                });
                elements.timelinePanel.hidden = !ids.includes("timelinePanel");
              },
              activateTab() {},
              focusLogLines(start, end) { focusCalls.push([start, end]); },
              showActionMessage() {},
              showToast() {},
              exportLog(type, content) { exports.push([type, content]); return Promise.resolve({}); }
            };
            const document = {
              readyState: "complete",
              getElementById(id) { return elements[id] || null; },
              createElement(tag) { return new FakeElement(tag); },
              createTextNode(value) { return {tagName: "#text", textContent: String(value), children: []}; },
              addEventListener() {}
            };
            const window = {
              LogWorkbench: api,
              navigator: {clipboard: {writeText(value) { copied = value; return Promise.resolve(); }}}
            };
            vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
              window, document, Promise, Array, Object, String, Number, Math, JSON, Set,
              console, setTimeout, clearTimeout
            });

            (async () => {
              const adapter = registered.people || registered["people-search"];
              assert(adapter && typeof adapter.analyze === "function", "People 模式未注册");
              await adapter.analyze({root, logText: "first\nsecond\nthird", signal: null});
              assert(requestCalls.length === 1, "People 未发起一次 JSON 请求");
              assert(requestCalls[0].url === "/people-search/analyze", "People 未使用 root.dataset.peopleUrl");
              assert(requestCalls[0].options.method === "POST", "People 请求未使用 POST");
              assert(requestCalls[0].options.body.log_text === "first\nsecond\nthird", "People 请求未携带当前日志");
              assert(availableTabs.length === 1 && availableTabs[0].join(",") === "overviewPanel,interfacesPanel,resultPanel,checksPanel",
                "People 未声明四个工作台 panel");
              assert(elements.timelinePanel.hidden, "People 不应显示任务时间线 panel");
              assert(verdictTitle.textContent === "发现已确认异常", "header 未使用确定性 verdict label");
              assert(elements["workbench-result-heading"].textContent === "发现已确认异常", "统一 header 标题错误");
              assert(textOf(elements["workbench-result-subheading"]).includes("<Alice>") &&
                textOf(elements["workbench-result-subheading"]).includes("task-1") &&
                textOf(elements["workbench-result-subheading"]).includes("candidate_count=0") &&
                textOf(elements["workbench-result-subheading"]).includes("no_result_reason=NO_MATCH"),
                "统一 header 副标题缺少真实任务字段");
              assert(textOf(timeline).includes("provider-1") && textOf(timeline).includes("lookup"),
                "Provider timeline 未写入 interfacesPanel");
              assert(textOf(diagnosis).includes("PROVIDERS_EXHAUSTED") && textOf(cost).includes("12"),
                "diagnosis/cost 未写入 resultPanel");
              assert(report.textContent === "# report <not-html>", "完整 Markdown 未以纯文本保留");
              const order = checks.children.map(textOf);
              assert(order[0].includes("FAIL") && order[1].includes("WARN") && order[2].includes("UNKNOWN") &&
                order[3].includes("PASS") && order[4].includes("NA"), "checks 未按 outcome 排序或映射 NA");
              const validButton = checks.querySelectorAll("button")[0];
              await validButton.dispatch("click");
              assert(focusCalls.length === 1 && focusCalls[0][0] === 2 && focusCalls[0][1] === 3,
                "有效 evidence 未定位真实行号");
              const unknownItem = checks.children.find(item => textOf(item).includes("R-UNKNOWN"));
              assert(unknownItem.querySelectorAll("button").length === 0 && textOf(unknownItem).includes("日志证据不足"),
                "缺失 evidence 未降级为不可点击提示");
              await copyButton.dispatch("click");
              assert(copied === "# report <not-html>", "复制未读取完整 Markdown 文本");
              await exportButton.dispatch("click");
              assert(exports.length === 1 && exports[0][0] === "analysis_report" && exports[0][1] === "# report <not-html>",
                "导出未复用 analysis_report 文本契约");
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(adapter_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)

    def test_people_adapter_and_core_use_real_request_lifecycle_and_clear_failures(self):
        """真实加载 core/People 后覆盖初始化、请求安全、证据边界和失败清理。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 People/core 集成行为测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        adapter_path = Path(__file__).resolve().parents[1] / "static/js/workbench-people.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeClassList {
              constructor() { this.values = new Set(); }
              toggle(name, force) {
                const shouldHave = force === undefined ? !this.values.has(name) : force;
                if (shouldHave) this.values.add(name); else this.values.delete(name);
                return shouldHave;
              }
            }

            class FakeElement {
              constructor(tagName, id = "", attributes = {}) {
                this.tagName = tagName.toUpperCase();
                this.id = id;
                this.attributes = {...attributes};
                this.children = [];
                this.listeners = Object.create(null);
                this.classList = new FakeClassList();
                this.dataset = Object.create(null);
                this.hidden = Boolean(attributes.hidden);
                this.disabled = Boolean(attributes.disabled);
                this.value = attributes.value || "";
                this.checked = Boolean(attributes.checked);
                this._textContent = attributes.textContent || "";
                this.selectionStart = 0;
                this.selectionEnd = 0;
                this.scrollTop = 0;
                this.style = {setProperty() {}};
              }

              get textContent() {
                return this._textContent + this.children.map(child => child.textContent || "").join("");
              }

              set textContent(value) {
                this._textContent = String(value ?? "");
                this.children = [];
              }

              appendChild(child) {
                this.children.push(child);
                child.parentNode = this;
                return child;
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                return Promise.all((this.listeners[type] || []).map(listener => listener(event)));
              }

              setAttribute(name, value) { this.attributes[name] = String(value); }

              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? this.attributes[name] : null;
              }

              setSelectionRange(start, end) {
                this.selectionStart = start;
                this.selectionEnd = end;
              }

              focus() {}
              scrollIntoView() {}
              getBoundingClientRect() { return {left: 0, width: 1000}; }

              querySelectorAll(selector) {
                const found = [];
                const visit = node => {
                  (node.children || []).forEach(child => {
                    if (selector === "button" && child.tagName === "BUTTON") found.push(child);
                    visit(child);
                  });
                };
                visit(this);
                return found;
              }
            }

            function textOf(node) { return String(node && node.textContent || ""); }

            const elements = Object.create(null);
            const add = (tag, id, attributes = {}) => {
              const element = new FakeElement(tag, id, attributes);
              elements[id] = element;
              return element;
            };

            const root = add("main", "log-workbench");
            root.dataset = {
              indexUrl: "/",
              exportUrl: "/export",
              peopleUrl: "/people-search/analyze",
              datingUrl: "/dating"
            };
            const tabDefinitions = [
              ["overviewTab", "overviewPanel", false],
              ["interfacesTab", "interfacesPanel", false],
              ["timelineTab", "timelinePanel", false],
              ["resultTab", "resultPanel", true],
              ["checksTab", "checksPanel", false]
            ];
            const tabs = tabDefinitions.map(([id, panelId, selected]) =>
              add("button", id, {
                "aria-controls": panelId,
                "aria-selected": String(selected),
                tabIndex: selected ? 0 : -1
              })
            );
            const panels = tabDefinitions.map(([, panelId, selected]) =>
              add("section", panelId, {hidden: !selected})
            );
            root.querySelectorAll = selector =>
              selector === '[role="tab"][aria-controls]' ? tabs : [];

            const form = add("form", "log-filter-form");
            form.requestSubmit = () => {};
            const modeSelect = add("select", "analysis-mode", {value: "general"});
            const analyzeButton = add("button", "analyze-log-btn", {textContent: "分析日志"});
            const loadingMask = add("div", "workbench-loading-mask", {hidden: true});
            const logText = add("textarea", "log_text");
            logText.value = "first\nsecond\nthird";
            const resultText = add("textarea", "result-text");
            resultText.value = "FILTER_RESULT";
            add("div", "raw-log-view");
            add("div", "filtered-log-view", {hidden: true});
            add("button", "raw-log-view-btn", {"aria-selected": "true"});
            add("button", "filtered-log-view-btn", {"aria-selected": "false"});
            const actionMessage = add("div", "action-message", {hidden: true});
            add("div", "workbench-toast", {hidden: true});
            add("div", "analysis-stale", {hidden: true});
            add("div", "log-line-count");
            add("div", "log-byte-count");
            const filteredExport = add("button", "export-filtered-result-btn");
            const heading = add("h2", "workbench-result-heading", {textContent: "分析结果"});
            const subheading = add("p", "workbench-result-subheading", {
              textContent: "等待分析"
            });
            const peopleOverview = add("div", "people-overview", {hidden: true});
            const peopleInterfaces = add("div", "people-interfaces", {hidden: true});
            const peopleResult = add("div", "people-result", {hidden: true});
            const peopleChecks = add("div", "people-checks", {hidden: true});
            const verdictPanel = add("section", "people-verdict-panel");
            const verdictTitle = add("h3", "people-verdict-title");
            const taskSummary = add("p", "people-task-summary");
            const aiStatus = add("p", "people-ai-status");
            const peopleStatus = add("span", "people-search-status");
            const coverage = add("div", "people-coverage-list");
            const issueList = add("ul", "people-issue-list");
            const timeline = add("div", "people-timeline");
            const diagnosis = add("dl", "people-diagnosis-list");
            const cost = add("div", "people-cost-summary");
            const report = add("pre", "people-search-report");
            const checks = add("ol", "people-check-list");
            const copyButton = add("button", "copy-report-btn", {disabled: true});
            const exportButton = add("button", "export-report-btn", {disabled: true});
            const datingSurface = add("div", "dating-analysis");

            const successData = {
              verdict: "ISSUES_FOUND",
              task: {
                full_name: "<Alice>", task_id: "task-success", final_status: "FAILED",
                candidate_count: 0, result_type: "NO_RESULT", no_result_reason: "NO_MATCH",
                clue_types: ["FULL_NAME"]
              },
              coverage: {create_task: true, get_task: true, candidate_list: false,
                candidate_detail: false, debug: true, cost_summary: true},
              ai: {status: "DISABLED"},
              timeline: [{provider: "provider-old", operation: "lookup", status: "failed",
                result_details: {safe: "detail"}, http_status: 500, cache_hit: false}],
              diagnosis: {final_status: "FAILED", stop_reason: "PROVIDERS_EXHAUSTED"},
              cost: {total_estimated_cost_microunit: 12},
              checks: [
                {outcome: "FAIL", rule_id: "R-VALID", title: "valid", actual: "a", expected: "e",
                  evidence: [{method: "GetTask", json_path: "status", line_start: 2, line_end: 3}]},
                {outcome: "WARN", rule_id: "R-OUT", title: "out", actual: "a", expected: "e",
                  evidence: [{method: "GetTask", json_path: "status", line_start: 4, line_end: 4}]},
                {outcome: "UNKNOWN", rule_id: "R-REVERSE", title: "reverse", actual: "a", expected: "e",
                  evidence: [{method: "GetTask", json_path: "status", line_start: 3, line_end: 2}]},
                {outcome: "PASS", rule_id: "R-MISSING", title: "missing", actual: "a", expected: "e",
                  evidence: [{method: "GetTask", json_path: "missing"}]}
              ],
              report_markdown: "# People success"
            };
            const responses = [
              {ok: true, status: 200, text: () => Promise.resolve(JSON.stringify({data: successData}))},
              {ok: false, status: 422, text: () => Promise.resolve(JSON.stringify({
                code: 1,
                message: "日志包含多个 People 任务",
                error_code: "MULTIPLE_TASKS_FOUND",
                detected_task_ids: ["task-a", "task-b"]
              }))}
            ];
            const fetchCalls = [];
            function fetch(url, options) {
              fetchCalls.push({url, options});
              return Promise.resolve(responses.shift());
            }

            const documentListeners = Object.create(null);
            const document = {
              readyState: "loading",
              getElementById(id) { return elements[id] || null; },
              createElement(tag) { return new FakeElement(tag); },
              createTextNode(value) { return {textContent: String(value), children: []}; },
              querySelector() { return null; },
              addEventListener(type, listener) {
                (documentListeners[type] ||= []).push(listener);
              },
              removeEventListener(type, listener) {
                documentListeners[type] = (documentListeners[type] || []).filter(
                  registered => registered !== listener
                );
              },
              dispatch(type, event = {}) {
                (documentListeners[type] || []).slice().forEach(listener => listener(event));
              }
            };
            Object.defineProperty(document, "cookie", {
              get() { return "tp_csrf=csrf-token"; }
            });

            const window = {
              fetch,
              navigator: {clipboard: {writeText: () => Promise.resolve()}},
              getComputedStyle() { return {lineHeight: "20px"}; }
            };
            const context = {
              window, document, Promise, Array, Object, String, Number, Math, JSON, Set,
              TypeError, console, setTimeout, clearTimeout
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
            vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);

            const api = window.LogWorkbench;
            const failures = [];
            function check(condition, message) {
              if (!condition) failures.push(message);
            }

            let headerCalls = 0;
            if (typeof api.setResultHeader === "function") {
              const coreSetResultHeader = api.setResultHeader;
              api.setResultHeader = function wrappedSetResultHeader(title, subtitle) {
                headerCalls += 1;
                return coreSetResultHeader(title, subtitle);
              };
            } else {
              failures.push("core 未暴露 setResultHeader");
            }

            (async () => {
            document.dispatch("DOMContentLoaded");
            check(root.dataset.workbenchInitialized === "true", "真实 DOMContentLoaded 未初始化 core");
            check((form.listeners.submit || []).length === 1, "真实初始化未绑定统一 submit");

            modeSelect.value = "people";
            api.markAnalysisFresh();
            const successRun = api.analyzeSelectedMode();
            await successRun;
            check(fetchCalls.length === 1, "People 未通过真实 core 发起一次 fetch");
            check(fetchCalls[0] && fetchCalls[0].url === "/people-search/analyze",
              "真实 requestJson 未使用 People endpoint");
            check(fetchCalls[0] && fetchCalls[0].options.method === "POST",
              "真实 requestJson 未使用 POST");
            check(fetchCalls[0] && fetchCalls[0].options.headers["X-CSRF-Token"] === "csrf-token",
              "真实 requestJson 未从 Cookie 读取 CSRF");
            check(fetchCalls[0] && fetchCalls[0].options.headers["Content-Type"] === "application/json",
              "真实 requestJson 未设置 JSON Content-Type");
            check(fetchCalls[0] && JSON.parse(fetchCalls[0].options.body).log_text === logText.value,
              "真实 requestJson 未发送当前原始日志");
            check(headerCalls === 1, "People 未调用 core 的 setResultHeader");
            check(taskSummary.textContent.includes("<Alice>") &&
              taskSummary.textContent.includes("task-success") &&
              taskSummary.textContent.includes("candidate_count=0") &&
              !taskSummary.textContent.includes("尚无 People Insight 任务结果"),
              "People task summary 未使用真实 task 字段");
            check(heading.textContent === "发现已确认异常" &&
              subheading.textContent.includes("task-success"),
              "统一 header 未使用真实 People 结论");

            const findCheck = marker => checks.children.find(item => textOf(item).includes(marker));
            const validItem = findCheck("R-VALID");
            const outOfRangeItem = findCheck("R-OUT");
            const reverseItem = findCheck("R-REVERSE");
            const missingItem = findCheck("R-MISSING");
            check(validItem && validItem.querySelectorAll("button").length === 1,
              "有效 evidence 未生成定位按钮");
            check(outOfRangeItem && outOfRangeItem.querySelectorAll("button").length === 0 &&
              textOf(outOfRangeItem).includes("日志证据不足"),
              "越界 evidence 不应生成定位按钮");
            check(reverseItem && reverseItem.querySelectorAll("button").length === 0 &&
              textOf(reverseItem).includes("日志证据不足"),
              "反向 evidence 不应生成定位按钮");
            check(missingItem && missingItem.querySelectorAll("button").length === 0 &&
              textOf(missingItem).includes("日志证据不足"),
              "缺失 evidence 不应生成定位按钮");
            if (validItem && validItem.querySelectorAll("button")[0]) {
              await validItem.querySelectorAll("button")[0].dispatch("click");
            }
            check(logText.selectionStart === 6 && logText.selectionEnd === 18,
              "有效 evidence 未通过真实 core 定位日志");
            const selectionBeforeInvalid = [logText.selectionStart, logText.selectionEnd];
            check(api.focusLogLines(4, 4) === false, "core 未拒绝越界行号");
            check(api.focusLogLines(3, 2) === false, "core 未拒绝反向行号");
            check(logText.selectionStart === selectionBeforeInvalid[0] &&
              logText.selectionEnd === selectionBeforeInvalid[1],
              "非法行号仍改变了原日志选择");

            datingSurface.textContent = "dating result";
            api.markAnalysisFresh();
            const failureRun = api.analyzeSelectedMode();
            await failureRun;
            check(fetchCalls.length === 2, "People 失败重试未通过真实 requestJson");
            check((peopleStatus.textContent + actionMessage.textContent).includes("task-a") &&
              (peopleStatus.textContent + actionMessage.textContent).includes("task-b"),
              "422 错误未显示真实 detected_task_ids");
            check(peopleOverview.hidden && peopleInterfaces.hidden &&
              peopleResult.hidden && peopleChecks.hidden,
              "People 失败后旧 surface 仍可见");
            check(!textOf(taskSummary).includes("task-success") &&
              !textOf(timeline).includes("provider-old") &&
              !textOf(checks).includes("R-VALID"),
              "People 失败后旧 verdict/timeline/checks 仍残留");
            check(heading.textContent !== "发现已确认异常" &&
              !subheading.textContent.includes("task-success"),
              "People 失败后统一 header 仍残留旧结论");
            check(resultText.value === "FILTER_RESULT", "People 失败清理了 Filter result-text");
            check(datingSurface.textContent === "dating result", "People 失败清理了 Dating surface");
            check(api.state.dirty === false && filteredExport.disabled === false,
              "People 失败污染了 Filter freshness");
            check(copyButton.disabled && exportButton.disabled,
              "People 失败后报告操作仍保持可用");

            if (failures.length) throw new Error(failures.join("\n"));
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path), str(adapter_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)


    def test_task_six_drawer_and_status_contracts_are_accessible(self):
        """Task 6 壳层必须包含可访问 drawer、互斥状态区和键盘关闭入口。"""
        html = self.client.get("/").get_data(as_text=True)
        core = Path("static/js/workbench-core.js").read_text(encoding="utf-8")
        css = Path("static/css/log-workbench.css").read_text(encoding="utf-8")

        for marker in (
            'id="workbench-drawer"',
            'role="dialog"',
            'aria-modal="true"',
            'id="workbench-drawer-backdrop"',
            'id="workbench-drawer-close"',
            'id="workbench-analysis-state"',
            'role="status" aria-live="polite"',
            'id="workbench-retry-btn"',
            'data-outcome="WARN"',
        ):
            self.assertIn(marker, html)

        for marker in (
            "function openInterfaceDrawer",
            "function closeInterfaceDrawer",
            "event.key === 'Escape'",
            "lastFocusedElement",
            "inert",
        ):
            self.assertIn(marker, core)

        self.assertIn(":focus-visible", css)
        self.assertNotIn("outline: none", css)


    def test_task_six_review_layout_and_success_focus_contracts(self):
        """复审回归：loading 只覆盖结果区，成功后结果标题可被聚焦。"""
        html = self.client.get("/").get_data(as_text=True)
        core = Path("static/js/workbench-core.js").read_text(encoding="utf-8")
        css = Path("static/css/log-workbench.css").read_text(encoding="utf-8")

        self.assertIn('id="workbench-result-heading" tabindex="-1"', html)
        self.assertEqual(html.count('id="workbench-loading-mask"'), 1)
        result_pane_index = html.index('id="workbench-result-pane"')
        loading_mask_index = html.index('id="workbench-loading-mask"')
        tabs_index = html.index('class="workbench-tabs"')
        self.assertGreater(loading_mask_index, result_pane_index)
        self.assertLess(loading_mask_index, tabs_index)
        self.assertRegex(css, r"\.workbench-result-pane\s*\{[^}]*position:\s*relative;")
        self.assertRegex(css, r"\.workbench-loading-mask\s*\{[^}]*position:\s*absolute;")
        self.assertIn("activateResultPanel(true)", core)
        self.assertIn("heading.focus", core)


    def _run_task_six_core_harness(self, scenario):
        """在最小但可交互 DOM 中验证 drawer 与异步状态机的真实副作用。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 Task 6 core 行为合同测试")
        core_path = Path(__file__).resolve().parents[1] / "static/js/workbench-core.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeClassList {
              constructor() { this.values = new Set(); }
              add(name) { this.values.add(name); }
              remove(name) { this.values.delete(name); }
              toggle(name, force) {
                const shouldHave = force === undefined ? !this.values.has(name) : force;
                if (shouldHave) this.values.add(name); else this.values.delete(name);
                return shouldHave;
              }
              contains(name) { return this.values.has(name); }
            }

            class FakeElement {
              constructor(tagName, id = "", attributes = {}) {
                this.tagName = String(tagName).toUpperCase();
                this.id = id;
                this.attributes = {...attributes};
                this.children = [];
                this.parentNode = null;
                this.listeners = Object.create(null);
                this.classList = new FakeClassList();
                this.dataset = Object.create(null);
                this.hidden = Boolean(attributes.hidden);
                this.disabled = Boolean(attributes.disabled);
                this.inert = Boolean(attributes.inert);
                this.value = attributes.value || "";
                this._textContent = attributes.textContent || "";
                this.tabIndex = Number(attributes.tabIndex || 0);
                this.focusCount = 0;
                this.style = {setProperty() {}};
              }

              appendChild(child) {
                this.children.push(child);
                child.parentNode = this;
                return child;
              }

              get textContent() {
                return this._textContent + this.children.map(child => child.textContent || "").join("");
              }

              set textContent(value) {
                this._textContent = String(value ?? "");
                this.children = [];
              }

              removeChild(child) {
                this.children = this.children.filter(item => item !== child);
              }

              addEventListener(type, listener) {
                (this.listeners[type] ||= []).push(listener);
              }

              removeEventListener(type, listener) {
                this.listeners[type] = (this.listeners[type] || []).filter(
                  registered => registered !== listener
                );
              }

              dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                return Promise.all((this.listeners[type] || []).map(listener => listener(event)));
              }

              setAttribute(name, value) { this.attributes[name] = String(value); }
              getAttribute(name) {
                return Object.prototype.hasOwnProperty.call(this.attributes, name)
                  ? String(this.attributes[name]) : null;
              }
              removeAttribute(name) { delete this.attributes[name]; }
              focus() { this.focusCount += 1; document.activeElement = this; }
              setSelectionRange() {}
              scrollIntoView() {}
              getBoundingClientRect() { return {left: 0, width: 1000}; }

              contains(target) {
                if (target === this) return true;
                return this.children.some(child => child.contains && child.contains(target));
              }

              querySelectorAll(selector) {
                const found = [];
                const matches = node => {
                  if (selector === "button" && node.tagName === "BUTTON") return true;
                  if (selector === "pre" && node.tagName === "PRE") return true;
                  return false;
                };
                const visit = node => {
                  (node.children || []).forEach(child => {
                    if (matches(child)) found.push(child);
                    visit(child);
                  });
                };
                visit(this);
                return found;
              }
            }

            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            const elements = Object.create(null);
            const add = (tag, id, attributes = {}) => {
              const element = new FakeElement(tag, id, attributes);
              elements[id] = element;
              return element;
            };

            const root = add("main", "log-workbench");
            root.dataset = {indexUrl: "/", exportUrl: "/export"};
            root.querySelectorAll = () => [];
            add("form", "log-filter-form");
            const modeSelect = add("select", "analysis-mode", {value: "people"});
            const analyzeButton = add("button", "analyze-log-btn", {textContent: "分析日志"});
            const loadingMask = add("div", "workbench-loading-mask", {hidden: true});
            const logText = add("textarea", "log_text");
            logText.value = "old log";
            add("textarea", "result-text", {value: "existing result"});
            const filterExport = add("button", "export-filtered-result-btn");
            add("div", "raw-log-view");
            add("div", "filtered-log-view", {hidden: true});
            add("button", "raw-log-view-btn");
            add("button", "filtered-log-view-btn", {disabled: true});
            add("input", "result-search");
            add("span", "search-count");
            add("div", "action-message", {hidden: true});
            add("div", "workbench-toast", {hidden: true});
            add("div", "log-focus-status");
            add("div", "analysis-stale", {hidden: true});
            add("span", "log-line-count");
            add("span", "log-byte-count");
            add("div", "workbench-result-heading", {textContent: "分析结果"});
            add("div", "workbench-result-subheading");
            const resultStale = add("span", "workbench-result-stale", {hidden: true});
            const state = add("div", "workbench-analysis-state", {hidden: false});
            const stateMessage = add("span", "workbench-analysis-state-message");
            state.appendChild(stateMessage);
            const stateSkeleton = add("div", "workbench-result-loading", {hidden: true});
            const emptyState = add("p", "workbench-result-empty", {hidden: true});
            const errorPanel = add("section", "workbench-result-error", {hidden: true});
            const errorCode = add("strong", "workbench-result-error-code");
            const errorMessage = add("p", "workbench-result-error-message");
            const retryButton = add("button", "workbench-retry-btn");
            errorPanel.appendChild(errorCode);
            errorPanel.appendChild(errorMessage);
            errorPanel.appendChild(retryButton);
            const drawer = add("aside", "workbench-drawer", {hidden: true});
            const drawerTitle = add("h2", "workbench-drawer-title");
            const drawerClose = add("button", "workbench-drawer-close");
            drawer.appendChild(drawerTitle);
            drawer.appendChild(drawerClose);
            const backdrop = add("div", "workbench-drawer-backdrop", {hidden: true});
            const trigger = add("button", "trigger");

            const documentListeners = Object.create(null);
            const document = {
              readyState: "complete",
              activeElement: trigger,
              getElementById(id) { return elements[id] || null; },
              createElement(tag) { return new FakeElement(tag); },
              createTextNode(value) { return new FakeElement("text", "", {textContent: String(value)}); },
              querySelector() { return null; },
              addEventListener(type, listener) { (documentListeners[type] ||= []).push(listener); },
              removeEventListener(type, listener) {
                documentListeners[type] = (documentListeners[type] || []).filter(
                  registered => registered !== listener
                );
              },
              dispatch(type, event = {}) {
                if (!event.target) event.target = document;
                return Promise.all((documentListeners[type] || []).map(listener => listener(event)));
              }
            };
            Object.defineProperty(document, "cookie", {get() { return ""; }});

            const window = {
              getComputedStyle() { return {lineHeight: "20px"}; },
              navigator: {clipboard: {writeText: () => Promise.resolve()}},
              AbortController
            };
            const context = {
              window, document, Promise, Array, Object, String, Number, Math, JSON, Set,
              TypeError, AbortController, console, setTimeout, clearTimeout
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
            const api = window.LogWorkbench;

            (async () => {
              if (process.argv[2] === "drawer") {
                api.openInterfaceDrawer({
                  title: "<unsafe title>", method: "GET",
                  response: {marker: "<script>alert(1)</script>", status: 200}
                }, trigger);
                assert(!drawer.hidden, "drawer 未打开");
                assert(drawer.getAttribute("aria-modal") === "true", "drawer 未声明 aria-modal=true");
                assert(root.inert === true && root.getAttribute("aria-hidden") === "true",
                  "打开 drawer 后主工作区未隔离");
                assert(backdrop.hidden === false, "drawer backdrop 未显示");
                assert(document.activeElement === drawerClose, "打开 drawer 后焦点未进入关闭按钮");
                assert(drawer.textContent.includes("<script>alert(1)</script>"),
                  "drawer 未保留服务端值文本");
                assert(drawer.querySelectorAll("pre").some(pre =>
                  pre.textContent.includes("<script>alert(1)</script>")),
                  "对象值未通过 JSON 文本写入 pre");
                assert(drawer.querySelectorAll("script").length === 0,
                  "不可信 drawer 值创建了 script 节点");

                await drawerClose.dispatch("click");
                assert(drawer.hidden && backdrop.hidden, "关闭按钮未统一关闭 drawer");
                assert(root.inert === false && root.getAttribute("aria-hidden") === null,
                  "关闭 drawer 后背景隔离未恢复");
                assert(document.activeElement === trigger, "关闭 drawer 后未恢复触发焦点");

                api.openInterfaceDrawer({method: "POST"}, trigger);
                await document.dispatch("keydown", {
                  key: "Escape", preventDefault() {}
                });
                assert(drawer.hidden, "Escape 未统一关闭 drawer");

                api.openInterfaceDrawer({method: "PUT"}, trigger);
                await backdrop.dispatch("click", {target: backdrop});
                assert(drawer.hidden, "backdrop 未统一关闭 drawer");
              } else if (process.argv[2] === "async") {
                let resolveOld;
                let calls = 0;
                const oldMarker = add("p", "old-result-marker");
                api.registerAnalysisMode("people", {
                  analyze(context) {
                    calls += 1;
                    if (calls === 1) {
                      return new Promise(resolve => {
                        resolveOld = () => resolve({ok: true});
                      }).then(result => {
                        if (context.isCurrent && context.isCurrent()) oldMarker.textContent = "old";
                        return result;
                      });
                    }
                    return Promise.resolve({ok: false, message: "后端错误", error: {
                      error_code: "BACKEND_TIMEOUT", message: "后端错误"
                    }});
                  }
                });
                api.analyzeSelectedMode();
                assert(api.state.phase === "loading" && !loadingMask.hidden && analyzeButton.disabled,
                  "异步分析未进入 loading 且锁定主按钮");
                logText.value = "new log";
                await logText.dispatch("input");
                assert(api.state.dirty === true && api.state.phase === "idle",
                  "编辑日志未取消/标记旧异步请求");
                assert(!resultStale.hidden && resultStale.textContent.includes("过期"),
                  "日志 stale 后右侧结果 header 未同步显示过期标记");
                api.markAnalysisFresh();
                assert(resultStale.hidden && resultStale.textContent === "",
                  "fresh 后右侧结果 header 未清理过期标记");
                resolveOld();
                await Promise.resolve();
                await Promise.resolve();
                assert(oldMarker.textContent === "", "旧请求结果回写到当前页面");

                await api.analyzeSelectedMode();
                assert(state.getAttribute("data-state") === "error" && !errorPanel.hidden,
                  "后端失败未进入 error 状态");
                assert(errorCode.textContent.includes("BACKEND_TIMEOUT") &&
                  errorMessage.textContent.includes("后端错误") && !retryButton.disabled,
                  "error 状态未显示后端 code/message 与重试入口");
                await retryButton.dispatch("click");
                assert(state.getAttribute("data-state") === "error",
                  "失败后重试不应伪造成功状态");
              } else if (process.argv[2] === "empty") {
                api.registerAnalysisMode("people", {
                  analyze() {
                    return Promise.resolve({ok: false, empty: true,
                      message: "日志内容为空，请先粘贴日志再分析", error: {
                        error_code: "EMPTY_LOG", message: "日志内容为空，请先粘贴日志再分析"
                      }});
                  }
                });
                await api.analyzeSelectedMode();
                assert(state.getAttribute("data-state") === "empty",
                  "空日志未进入统一 empty 状态");
                assert(errorPanel.hidden, "empty 状态错误面板不应显示");
                assert(!emptyState.hidden && stateMessage.textContent.includes("日志内容为空"),
                  "empty 状态未保留真实空态文案");
              } else if (process.argv[2] === "owner-freshness") {
                let calls = 0;
                for (const owner of ["people", "dating"]) {
                  api.registerAnalysisMode(owner, {
                    analyze() {
                      calls += 1;
                      return Promise.resolve({ok: true, owner, calls});
                    }
                  });
                  // 先建立一个可用的 Filter 结果，再验证异步 owner 成功不会把它误恢复。
                  api.markAnalysisFresh("general");
                  api.markAnalysisFresh(owner);
                  modeSelect.value = owner;
                  await api.analyzeSelectedMode();
                  assert(resultStale.hidden, owner + " 首次成功不应显示 stale");

                  logText.value = "new log " + owner;
                  await logText.dispatch("input");
                  assert(!resultStale.hidden, owner + " 结果失效后未显示 stale");
                  assert(filterExport.disabled, owner + " 日志修改后旧 Filter 导出未禁用");

                  await api.analyzeSelectedMode();
                  assert(resultStale.hidden,
                    owner + " 在当前日志上重新成功后仍显示全局 stale");
                  assert(api.state.dirty === true && filterExport.disabled,
                    owner + " 成功错误清除了旧 Filter 的 stale 状态");
                }
              } else {
                throw new Error("未知 Task 6 core 场景: " + process.argv[2]);
              }
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(core_path), scenario],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)


    def test_task_six_core_drawer_and_async_states(self):
        """共享 drawer 与旧请求隔离必须由 core 的真实 DOM 副作用保证。"""
        self._run_task_six_core_harness("drawer")
        self._run_task_six_core_harness("async")
        self._run_task_six_core_harness("empty")


    def test_task_six_mode_owner_freshness_isolated(self):
        """People/Dating 成功只能恢复自己的结果，不能清除 Filter stale。"""
        self._run_task_six_core_harness("owner-freshness")


    def test_task_six_people_drawer_and_outcome_filter(self):
        """People Provider 行使用真实字段打开 drawer，检查筛选显示空态而非成功。"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行 Task 6 People 行为合同测试")
        adapter_path = Path(__file__).resolve().parents[1] / "static/js/workbench-people.js"
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class FakeElement {
              constructor(tagName, id = "") {
                this.tagName = String(tagName).toUpperCase();
                this.id = id;
                this.children = [];
                this.listeners = Object.create(null);
                this.attributes = Object.create(null);
                this.hidden = false;
                this.disabled = false;
                this.value = "";
                this.textContent = "";
              }
              appendChild(child) { this.children.push(child); return child; }
              addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
              dispatch(type, event = {}) {
                if (!event.target) event.target = this;
                return Promise.all((this.listeners[type] || []).map(listener => listener(event)));
              }
              setAttribute(name, value) { this.attributes[name] = String(value); }
              getAttribute(name) { return this.attributes[name] || null; }
              querySelectorAll(selector) {
                const found = [];
                const visit = node => {
                  (node.children || []).forEach(child => {
                    if (selector === "button" && child.tagName === "BUTTON") found.push(child);
                    visit(child);
                  });
                };
                visit(this);
                return found;
              }
              focus() {}
            }

            function textOf(node) {
              return String(node && node.textContent || "") +
                (node && node.children || []).map(textOf).join(" ");
            }
            function assert(condition, message) {
              if (!condition) throw new Error(message);
            }

            const elements = Object.create(null);
            const add = (tag, id) => {
              const element = new FakeElement(tag, id);
              elements[id] = element;
              return element;
            };
            const root = add("main", "log-workbench");
            root.dataset = {peopleUrl: "/people-search/analyze"};
            const logText = add("textarea", "log_text");
            logText.value = "one\ntwo\nthree";
            add("h2", "workbench-result-heading");
            add("p", "workbench-result-subheading");
            ["overviewPanel", "interfacesPanel", "timelinePanel", "resultPanel", "checksPanel"].forEach(
              id => add("section", id)
            );
            ["overviewTab", "interfacesTab", "timelineTab", "resultTab", "checksTab"].forEach(
              id => add("button", id)
            );
            add("div", "people-overview");
            const peopleOverviewEmpty = add("p", "people-overview-empty");
            peopleOverviewEmpty.hidden = true;
            add("section", "people-verdict-panel");
            add("h3", "people-verdict-title");
            add("p", "people-task-summary");
            add("p", "people-ai-status");
            const peopleStatus = add("p", "people-search-status");
            add("div", "people-coverage-list");
            add("ul", "people-issue-list");
            add("div", "people-timeline");
            add("dl", "people-diagnosis-list");
            add("div", "people-cost-summary");
            add("pre", "people-search-report");
            const checkList = add("ol", "people-check-list");
            const checkFilter = add("div", "people-check-filter");
            checkFilter.value = "WARN";
            const warnFilterButton = add("button", "people-filter-warn");
            warnFilterButton.dataset = {outcome: "WARN"};
            checkFilter.appendChild(warnFilterButton);
            add("button", "copy-report-btn");
            add("button", "export-report-btn");

            const drawerModels = [];
            const api = {
              state: {},
              registerAnalysisMode(name, definition) { this.definition = definition; },
              setAvailableTabs() {},
              activateTab() {},
              setResultHeader() {},
              focusLogLines() {},
              showActionMessage() {},
              requestJson() {
                return Promise.resolve({data: {
                  verdict: "INCOMPLETE_EVIDENCE",
                  task: {task_id: "task-1", full_name: "Alice"},
                  coverage: {},
                  timeline: [{provider: "Provider-A", operation: "lookup", status: "FAILED",
                    result_details: {marker: "<unsafe>"}, http_status: 502,
                    cache_hit: false, cost_status: "UNPRICED",
                    estimated_cost_microunit: null}],
                  diagnosis: {}, cost: {}, checks: [
                    {outcome: "WARN", rule_id: "R-WARN", title: "warning", actual: "a",
                      expected: "e", evidence: []},
                    {outcome: "PASS", rule_id: "R-PASS", title: "pass", actual: "a",
                      expected: "e", evidence: []}
                  ], report_markdown: ""
                }});
              },
              openInterfaceDrawer(model) { drawerModels.push(model); },
              exportLog() { return Promise.resolve({}); }
            };
            const document = {
              readyState: "complete",
              getElementById(id) { return elements[id] || null; },
              createElement(tag) { return new FakeElement(tag); },
              createTextNode(value) { return new FakeElement("text", "", {textContent: String(value)}); },
              addEventListener() {}
            };
            const window = {LogWorkbench: api, navigator: {clipboard: {writeText: () => Promise.resolve()}}};
            const context = {window, document, Promise, Array, Object, String, Number, Math, JSON,
              Set, TypeError, console};
            vm.createContext(context);
            vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);

            (async () => {
              const result = await api.definition.analyze({root, logText: logText.value});
              assert(result && result.ok === true, "People 分析未完成");
              const rowButton = elements["people-timeline"].querySelectorAll("button")[0];
              assert(rowButton, "People Provider timeline 行未提供 drawer 触发器");
              await rowButton.dispatch("click");
              assert(drawerModels.length === 1 && drawerModels[0].provider === "Provider-A" &&
                drawerModels[0].operation === "lookup" && drawerModels[0].http_status === 502 &&
                drawerModels[0].result_details.marker === "<unsafe>",
                "People drawer 未使用真实 Provider 字段");
              await checkFilter.dispatch("change");
              assert(checkList.children.length === 1 && textOf(checkList).includes("R-WARN") &&
                !textOf(checkList).includes("R-PASS"), "People outcome 筛选未生效");
              checkFilter.value = "FAIL";
              await checkFilter.dispatch("change");
              assert(textOf(checkList).includes("暂无规则检查结果") ||
                textOf(checkList).includes("当前筛选条件下没有规则检查"),
                "无匹配检查项未显示 empty 状态");
              assert(warnFilterButton.getAttribute("aria-pressed") === "false",
                "无匹配检查项时未同步 outcome 筛选按钮 aria-pressed");
              const emptyResult = await api.definition.analyze({root, logText: "   "});
              assert(emptyResult && emptyResult.ok === false && emptyResult.empty === true &&
                emptyResult.error && emptyResult.error.error_code === "EMPTY_LOG",
                "People 空日志未返回 empty/EMPTY_LOG 状态");
              assert(!peopleOverviewEmpty.hidden && textOf(peopleOverviewEmpty).includes("日志内容为空"),
                "People 空日志未保留真实空态文案");
            })().catch(error => {
              console.error(error.stack || error.message);
              process.exitCode = 1;
            });
            """
        )
        completed = subprocess.run(
            [node, "-e", harness, str(adapter_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
