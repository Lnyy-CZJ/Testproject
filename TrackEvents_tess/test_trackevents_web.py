import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from trackevents_web import (
    HTML,
    create_server,
    normalize_base_path,
    render_html,
    resolve_log_text,
)


class TrackEventsWebTest(unittest.TestCase):
    def test_resolve_log_text_reads_default_log_when_payload_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_log = Path(tmpdir) / "default.log"
            default_log.write_text("default log content", encoding="utf-8")

            self.assertEqual(resolve_log_text("", default_log), "default log content")

    def test_resolve_log_text_uses_uploaded_log_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            default_log = Path(tmpdir) / "default.log"
            default_log.write_text("default log content", encoding="utf-8")

            self.assertEqual(resolve_log_text("uploaded log content", default_log), "uploaded log content")

    def test_web_page_has_paste_input_and_paste_takes_priority(self):
        self.assertIn('id="logText"', HTML)
        self.assertIn("const pastedLog = logTextInput.value", HTML)
        self.assertIn("hasPastedLog ? pastedLog : (file ? await file.text() : '')", HTML)

    def test_event_details_has_action_filter(self):
        self.assertIn('id="moduleFilter"', HTML)
        self.assertIn('id="actionFilter"', HTML)
        self.assertIn("addEventListener('change', applyFilters)", HTML)
        self.assertNotIn('id="applyActionFilter"', HTML)

    def test_event_details_shows_extra_field_values(self):
        self.assertIn('item.extra_params', HTML)
        self.assertIn('疑似多传字段值：', HTML)

    def test_web_page_has_common_param_check_panel(self):
        self.assertIn('id="commonParamsPanel"', HTML)
        self.assertIn('data.common_param_summary', HTML)
        self.assertIn('公参实际值', HTML)
        self.assertIn('缺失必填公参', HTML)

    def test_expected_counts_support_line_format(self):
        self.assertIn('function parseExpectedCounts(text)', HTML)
        self.assertIn("const match = value.match(/^(.+?)(\\d+)?$/)", HTML)
        self.assertIn("counts[action] = match[2] ? Number(match[2]) : 1", HTML)

    def test_base_path_is_normalized_and_rejects_unsafe_values(self):
        """基础路径应使用统一格式，并拒绝可能改变路由语义的配置。"""
        self.assertEqual(normalize_base_path(""), "")
        self.assertEqual(normalize_base_path("trackevents/"), "/trackevents")

        for invalid_path in ("/../trackevents", "/trackevents?debug=1", "//trackevents"):
            with self.subTest(invalid_path=invalid_path):
                with self.assertRaises(ValueError):
                    normalize_base_path(invalid_path)

    def test_rendered_page_uses_platform_routes(self):
        """平台模式页面中的资源与 API 地址必须保留工具前缀。"""
        html = render_html("/trackevents", platform_home_url="/")

        self.assertIn('href="/trackevents/favicon.svg"', html)
        self.assertIn("fetch('/trackevents/api/analyze'", html)
        self.assertIn('href="/"', html)

    def test_server_exposes_prefixed_health_route_only(self):
        """平台模式应只在配置的基础路径下暴露健康检查。"""
        server = create_server("127.0.0.1", 0, base_path="/trackevents")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]

        try:
            with urlopen(f"http://127.0.0.1:{port}/trackevents/health") as response:
                self.assertEqual(response.status, 200)
                self.assertIn('"status": "ok"', response.read().decode("utf-8"))

            with self.assertRaises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{port}/health")
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
