"""阶段 3：Flask 页面与导出接入集成测试（设计 §13、§14.3、§15、§17.1）。

验证：
- 分析接口成功、400、422（UNSUPPORTED_LOG / MULTIPLE_TASKS_FOUND）和 AI 降级。
- 平台 base path 下接口 URL 正确。
- POST 继续受 CSRF 保护。
- 分析报告 .md 导出。
- 页面包含按钮、加载状态、复制和导出逻辑。
- 对外 checks 脱敏。
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app import create_app

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "people_search"


def _read_fixture(name):
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class AnalyzeEndpointTests(unittest.TestCase):
    """POST /people-search/analyze 的成功与错误分支。"""

    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()

    def test_analyze_success_returns_report_and_disabled_ai(self):
        """成功分析应返回规则报告，AI 默认 DISABLED，且包含全部结构化字段。"""
        log_text = _read_fixture("f01_public_figure_local_hit.log")

        response = self.client.post(
            "/people-search/analyze",
            json={"log_text": log_text},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["code"], 0)
        data = payload["data"]
        self.assertEqual(data["analyzer_version"], "people-search-v1")
        self.assertIn(data["verdict"], {"NORMAL", "ISSUES_FOUND", "NEEDS_CONFIRMATION", "INCOMPLETE_EVIDENCE"})
        self.assertTrue(data["report_markdown"].startswith("# People Insight 检索日志分析"))
        # AI 默认关闭，不发网络请求，状态为 DISABLED
        self.assertEqual(data["ai"], {"status": "DISABLED"})
        self.assertNotIn("model", data["ai"])
        # 结构化字段齐全
        for field in ("task", "coverage", "timeline", "diagnosis", "checks", "cost"):
            self.assertIn(field, data)
        self.assertIsInstance(data["checks"], list)
        self.assertEqual(len(data["checks"]), 24)

    def test_analyze_empty_log_returns_400(self):
        """空日志应返回 400 和 EMPTY_LOG。"""
        response = self.client.post(
            "/people-search/analyze",
            json={"log_text": "   "},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error_code"], "EMPTY_LOG")

    def test_analyze_unsupported_log_returns_422(self):
        """未识别到 People Insight 接口应返回 422 和 UNSUPPORTED_LOG。"""
        response = self.client.post(
            "/people-search/analyze",
            json={"log_text": "this is just random text without any method"},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["error_code"], "UNSUPPORTED_LOG")

    def test_analyze_multiple_tasks_returns_422_with_task_ids(self):
        """检测到多个 task_id 应返回 422 并附带 detected_task_ids。"""
        log_text = _read_fixture("f01_public_figure_local_hit.log") + "\n" + _read_fixture(
            "f02_wiki_unique_hit_skip_pdl.log"
        )

        response = self.client.post(
            "/people-search/analyze",
            json={"log_text": log_text},
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["error_code"], "MULTIPLE_TASKS_FOUND")
        self.assertGreaterEqual(len(payload["detected_task_ids"]), 2)

    def test_analyze_with_task_id_filter_succeeds(self):
        """多 task 日志传入 task_id 后应正常分析单个任务。"""
        log_text = _read_fixture("f01_public_figure_local_hit.log") + "\n" + _read_fixture(
            "f02_wiki_unique_hit_skip_pdl.log"
        )

        response = self.client.post(
            "/people-search/analyze",
            json={"log_text": log_text, "task_id": "task_f010000000000000000000aa"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["report_markdown"].startswith("# People Insight 检索日志分析"))

    def test_analyze_checks_redact_sensitive_keys(self):
        """对外 checks 中的敏感 key 应被脱敏，不泄露 Token。"""
        log_text = _read_fixture("f01_public_figure_local_hit.log")

        response = self.client.post(
            "/people-search/analyze",
            json={"log_text": log_text},
        )
        data = response.get_json()["data"]

        def _has_sensitive(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(k, str) and any(s in k.lower() for s in ("auth_token", "authorization", "access_token")):
                        if v not in ("***", "", None):
                            return True
                    if _has_sensitive(v):
                        return True
            elif isinstance(value, list):
                return any(_has_sensitive(item) for item in value)
            return False

        self.assertFalse(_has_sensitive(data["checks"]), "checks 中存在未脱敏的敏感字段")


class AnalyzePlatformPathTests(unittest.TestCase):
    """平台 base path 下分析接口的 URL 与 CSRF 行为。"""

    def test_analyze_route_available_under_platform_base_path(self):
        """平台模式下分析接口应使用工具前缀，根路径不可达。"""
        app = create_app(base_path="/log-filter")
        app.testing = True
        client = app.test_client()
        log_text = _read_fixture("f01_public_figure_local_hit.log")

        response = client.post(
            "/log-filter/people-search/analyze",
            json={"log_text": log_text},
        )
        self.assertEqual(response.status_code, 200)

        # 根路径下不应存在分析接口
        root_response = client.post(
            "/people-search/analyze",
            json={"log_text": log_text},
        )
        self.assertEqual(root_response.status_code, 404)

    def test_analyze_post_requires_csrf_on_platform(self):
        """平台模式下分析接口应受双提交 CSRF 保护。"""
        app = create_app(base_path="/log-filter")
        app.testing = True
        app.config["PLATFORM_API_URL"] = "https://platform.example.com"
        client = app.test_client()
        log_text = _read_fixture("f01_public_figure_local_hit.log")

        # 缺少 CSRF Token 应被拒绝
        no_token_response = client.post(
            "/log-filter/people-search/analyze",
            json={"log_text": log_text},
        )
        self.assertEqual(no_token_response.status_code, 403)

        # 提供匹配的 Cookie 与 Header 应通过
        client.set_cookie("tp_csrf", "csrf-secret")
        ok_response = client.post(
            "/log-filter/people-search/analyze",
            json={"log_text": log_text},
            headers={"X-CSRF-Token": "csrf-secret"},
        )
        self.assertEqual(ok_response.status_code, 200)


class AnalysisReportExportTests(unittest.TestCase):
    """分析报告 .md 导出。"""

    def test_export_analysis_report_as_markdown_file(self):
        """analysis_report 导出类型应保存为 .md 文件。"""
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config["LOG_EXPORT_DIR"] = export_dir
            app.config["LOG_EXPORT_DISPLAY_DIR"] = export_dir
            response = app.test_client().post(
                "/export",
                json={"export_type": "analysis_report", "content": "# People Insight 检索日志分析\n\n结论"},
            )
            payload = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["filename"].startswith("people_search_analysis_"))
            self.assertTrue(payload["filename"].endswith(".md"))
            self.assertEqual(
                (Path(export_dir) / payload["filename"]).read_text(encoding="utf-8"),
                "# People Insight 检索日志分析\n\n结论",
            )

    def test_export_rejects_unknown_type(self):
        """未知导出类型应返回 400。"""
        app = create_app()
        app.testing = True

        response = app.test_client().post(
            "/export",
            json={"export_type": "unknown_type", "content": "x"},
        )
        self.assertEqual(response.status_code, 400)


class PageRenderingTests(unittest.TestCase):
    """页面应把 People 结果映射到统一工作台，而不是继续依赖模板内联脚本。"""

    def test_people_mode_is_registered_without_inline_script(self):
        """People 模式由独立静态适配器注册，并占用四个真实工作台 surface。"""
        app = create_app()
        app.testing = True

        html = app.test_client().get("/").get_data(as_text=True)
        source = Path("static/js/workbench-people.js").read_text(encoding="utf-8")

        self.assertIn('<option value="people">People Insight</option>', html)
        self.assertIn('data-people-url="/people-search/analyze"', html)
        self.assertIn("workbench-people.js", html)
        self.assertIn("registerAnalysisMode('people'", source)
        for key in ("data.coverage", "data.timeline", "data.diagnosis", "data.checks", "data.cost"):
            self.assertIn(key, source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)

        for marker in (
            'id="people-verdict-panel"',
            'id="people-task-summary"',
            'id="people-ai-status"',
            'id="people-coverage-list"',
            'id="people-issue-list"',
            'id="people-timeline"',
            'id="people-diagnosis-list"',
            'id="people-cost-summary"',
            'id="people-search-report"',
            'id="people-check-list"',
            'id="copy-report-btn"',
            'id="export-report-btn"',
        ):
            self.assertIn(marker, html)

        # People 不再在模板中声明旧分析函数或隐藏的第二个分析入口。
        for inline_marker in (
            "function renderPeopleSearchAnalysis(data)",
            "function analyzePeopleSearch()",
            "function copyReport()",
            "function exportReport()",
            'id="analyze-people-search-btn"',
        ):
            self.assertNotIn(inline_marker, html)

        # 统一入口仍是唯一可见分析按钮，People 的复制/导出按钮只服务结果面板。
        self.assertEqual(html.count('id="analyze-log-btn"'), 1)
        self.assertIn('id="copy-report-btn"', html)
        self.assertIn('id="export-report-btn"', html)
        self.assertIn("analysis_report", source)


class RedactForResponseTests(unittest.TestCase):
    """对外响应脱敏单元测试（§10.1）。"""

    def test_redact_for_response_redacts_sensitive_keys_and_keeps_email(self):
        from people_search_rules import redact_for_response

        data = {
            "evidence": [
                {"auth_token": "Bearer secret-token", "email": "carol@example.com"},
                {"cost_breakdown_json": [{"access_token": "abc"}]},
            ],
            "plain": "normal text",
        }
        redacted = redact_for_response(data)

        self.assertEqual(redacted["evidence"][0]["auth_token"], "***")
        self.assertEqual(redacted["evidence"][0]["email"], "carol@example.com")
        self.assertEqual(redacted["evidence"][1]["cost_breakdown_json"][0]["access_token"], "***")
        self.assertEqual(redacted["plain"], "normal text")

    def test_redact_for_response_redacts_data_url_strings(self):
        from people_search_rules import redact_for_response

        redacted = redact_for_response({"image": "data:image/png;base64,iVBORw0KGgoAAAANS" + "A" * 600})
        self.assertEqual(redacted["image"], "[binary omitted]")


if __name__ == "__main__":
    unittest.main()
