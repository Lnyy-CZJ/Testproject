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
                window.LogWorkbench.activateTab(overviewTab, root);

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
