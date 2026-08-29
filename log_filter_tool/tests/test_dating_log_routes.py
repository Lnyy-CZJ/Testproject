"""Dating 结构化分析 Flask 路由的请求、编排与安全回归测试。"""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app import create_app
from dating_log_analyzer import analyze_dating_log


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"
SUCCESS_KEYS = [
    "analyzer_version",
    "parser_version",
    "ruleset_version",
    "supported",
    "detected_domain",
    "verdict",
    "selection_error",
    "task_ids",
    "summary",
    "interface_statistics",
    "flow_steps",
    "calls",
    "task_snapshot",
    "checks",
    "parse_warnings",
    "report_markdown",
]


class DatingRouteTest(unittest.TestCase):
    """覆盖 Dating API 的严格输入合同、错误映射与成功响应。"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    @staticmethod
    def _fixture(name):
        """按 UTF-8 读取真实 golden，避免在路由测试复制分析结构。"""
        return (FIXTURE_DIR / name).read_text(encoding="utf-8")

    def assert_error(self, response, status_code, error_code):
        """断言稳定 HTTP/error_code，错误正文不得返回成功包络。"""
        self.assertEqual(response.status_code, status_code)
        payload = response.get_json()
        self.assertEqual(payload["error_code"], error_code)
        self.assertIn("message", payload)
        self.assertNotIn("data", payload)

    def test_dating_config_defaults_and_invalid_size_fallback(self):
        """默认开启且限制 10 MiB，非法环境值不能阻止应用启动。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DATING_STRUCTURED_ANALYZER_ENABLED", None)
            os.environ.pop("DATING_STRUCTURED_MAX_BYTES", None)
            default_app = create_app()

        self.assertTrue(default_app.config["DATING_STRUCTURED_ANALYZER_ENABLED"])
        self.assertEqual(
            default_app.config["DATING_STRUCTURED_MAX_BYTES"],
            10 * 1024 * 1024,
        )

        with patch.dict(
            os.environ,
            {"DATING_STRUCTURED_MAX_BYTES": "not-an-integer"},
            clear=False,
        ):
            fallback_app = create_app()
        self.assertEqual(
            fallback_app.config["DATING_STRUCTURED_MAX_BYTES"],
            10 * 1024 * 1024,
        )

    def test_disabled_analyzer_returns_503(self):
        self.app.config["DATING_STRUCTURED_ANALYZER_ENABLED"] = False

        response = self.client.post(
            "/dating/analyze", json={"log_text": "safe sample"}
        )

        self.assert_error(response, 503, "ANALYZER_DISABLED")

    def test_base_path_route_is_registered(self):
        app = create_app("/log-tool")
        app.config["TESTING"] = True

        response = app.test_client().post(
            "/log-tool/dating/analyze",
            json={"log_text": "safe sample"},
        )

        self.assert_error(response, 422, "UNSUPPORTED_LOG")

    def test_request_must_be_exact_json_object(self):
        """非 application/json、非对象、缺字段、未知字段和错误类型均拒绝。"""
        cases = (
            (
                "non-json",
                {"data": "plain text", "content_type": "text/plain"},
            ),
            (
                "malformed-json",
                {"data": "{", "content_type": "application/json"},
            ),
            ("array", {"json": ["log"]}),
            ("null", {"json": None}),
            ("missing-log-text", {"json": {"task_id": None}}),
            (
                "unknown-field",
                {"json": {"log_text": "safe sample", "rules": []}},
            ),
            ("wrong-log-type", {"json": {"log_text": 1}}),
            (
                "wrong-task-type",
                {"json": {"log_text": "safe sample", "task_id": 1}},
            ),
        )

        for name, request_kwargs in cases:
            with self.subTest(name=name):
                response = self.client.post(
                    "/dating/analyze", **request_kwargs
                )
                self.assert_error(response, 400, "INVALID_REQUEST")

    def test_blank_log_returns_empty_log(self):
        response = self.client.post(
            "/dating/analyze", json={"log_text": " \n\t", "task_id": None}
        )

        self.assert_error(response, 400, "EMPTY_LOG")

    def test_log_size_uses_utf8_bytes(self):
        self.app.config["DATING_STRUCTURED_MAX_BYTES"] = 5

        response = self.client.post(
            "/dating/analyze", json={"log_text": "测测"}
        )

        self.assert_error(response, 413, "LOG_TOO_LARGE")

    def test_unsupported_log_returns_422(self):
        response = self.client.post(
            "/dating/analyze", json={"log_text": "ordinary local text"}
        )

        self.assert_error(response, 422, "UNSUPPORTED_LOG")

    def test_task_selection_errors_map_to_422(self):
        reply_log = self._fixture("reply_generation_multi_image_success.log")
        analysis_log = self._fixture(
            "relationship_analysis_multi_image_success.log"
        )

        multiple = self.client.post(
            "/dating/analyze", json={"log_text": reply_log + "\n" + analysis_log}
        )
        missing = self.client.post(
            "/dating/analyze",
            json={"log_text": reply_log, "task_id": "dating_task_missing"},
        )

        self.assert_error(multiple, 422, "MULTIPLE_TASKS_FOUND")
        self.assertEqual(len(multiple.get_json()["task_ids"]), 2)
        self.assert_error(missing, 422, "TASK_NOT_FOUND")
        self.assertEqual(len(missing.get_json()["task_ids"]), 1)

    def test_golden_logs_return_direct_ordered_prd_response(self):
        """成功响应无 code/data 包络，并由真实 analyzer/rules/report 贯通生成。"""
        fixtures = (
            (
                "reply_generation_multi_image_success.log",
                "reply_generation",
            ),
            (
                "relationship_analysis_multi_image_success.log",
                "relationship_analysis",
            ),
        )

        for fixture_name, task_type in fixtures:
            with self.subTest(fixture=fixture_name):
                response = self.client.post(
                    "/dating/analyze",
                    json={"log_text": self._fixture(fixture_name)},
                )
                payload = response.get_json()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(payload), SUCCESS_KEYS)
                self.assertEqual(
                    payload["analyzer_version"], "dating-structured-v1"
                )
                self.assertEqual(payload["parser_version"], "gateway-log-v1")
                self.assertEqual(payload["ruleset_version"], "2026-08-29")
                self.assertTrue(payload["supported"])
                self.assertEqual(payload["detected_domain"], "dating")
                self.assertEqual(payload["verdict"], "WARNINGS_FOUND")
                self.assertIsNone(payload["selection_error"])
                self.assertEqual(payload["task_snapshot"]["task_type"], task_type)
                self.assertEqual(len(payload["checks"]), 40)
                self.assertTrue(
                    payload["report_markdown"].startswith(
                        "# Dating 结构化接口日志分析"
                    )
                )
                for outcome, summary_key in (
                    ("FAIL", "check_fail_count"),
                    ("WARN", "check_warn_count"),
                    ("UNKNOWN", "check_unknown_count"),
                ):
                    self.assertEqual(
                        payload["summary"][summary_key],
                        sum(
                            check["outcome"] == outcome
                            for check in payload["checks"]
                        ),
                    )

    def test_success_response_and_report_are_redacted_without_input_mutation(self):
        """API 与 report 只读取脱敏副本，不能泄漏 analyzer 内部原值。"""
        source = analyze_dating_log(
            self._fixture("reply_generation_multi_image_success.log")
        )
        source["calls"][0]["request"]["Authorization"] = "Bearer route-secret"
        source["calls"][0]["request"]["signed_url"] = (
            "https://signed.example/object.png?q-signature=route-signature"
        )

        with patch(
            "dating_log_analyzer.analyze_dating_log", return_value=source
        ):
            response = self.client.post(
                "/dating/analyze", json={"log_text": "recognized by stub"}
            )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("route-secret", body)
        self.assertNotIn("route-signature", body)
        self.assertIn("[REDACTED]", body)
        self.assertEqual(
            source["calls"][0]["request"]["Authorization"],
            "Bearer route-secret",
        )

    def test_internal_exception_returns_sanitized_500(self):
        with patch(
            "dating_log_analyzer.analyze_dating_log",
            side_effect=RuntimeError("private stack detail"),
        ):
            response = self.client.post(
                "/dating/analyze", json={"log_text": "recognized by stub"}
            )

        self.assert_error(response, 500, "ANALYSIS_INTERNAL_ERROR")
        self.assertNotIn("private stack detail", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
