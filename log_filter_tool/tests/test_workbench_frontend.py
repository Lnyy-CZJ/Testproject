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
        """核心命名空间必须先建立，业务脚本才能注册 People/Dating 模式。"""
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
            if "function analyzePeopleSearch" in "".join(script["content"])
        )

        self.assertLess(core_index, business_index)

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


if __name__ == "__main__":
    unittest.main()
