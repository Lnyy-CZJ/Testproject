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


if __name__ == "__main__":
    unittest.main()
