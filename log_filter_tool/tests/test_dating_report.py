"""Dating 固定 Markdown 报告与后端递归脱敏的回归测试。"""

from copy import deepcopy
from pathlib import Path
import unittest

import dating_log_rules
from dating_log_analyzer import analyze_dating_log
from dating_log_rules import run_dating_checks


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"
REPORT_HEADINGS = [
    "## 总体结论",
    "## 接口调用链",
    "## 上传资源",
    "## 任务生命周期",
    "## Result 摘要",
    "## Result 字段",
    "## 规则检查",
    "## 解析警告",
]


def _load_reply_analysis() -> dict:
    """使用真实 Reply golden，报告测试不复制 analyzer 聚合结果。"""
    return analyze_dating_log(
        (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
    )


class DatingRedactionTest(unittest.TestCase):
    """覆盖敏感键、签名 URL、Base64 与长文本递归脱敏。"""

    def test_sensitive_keys_signed_urls_and_base64_are_redacted(self):
        data_url = "data:image/png;base64," + "A" * 32
        base64_blob = "B" * 256
        source = {
            "Authorization": "Bearer secret-token-value",
            "headers": {
                "Cookie": "session=secret-cookie",
                "set-cookie": "session=secret-set-cookie",
            },
            "auth-token": "secret-auth-token",
            "api-key": "secret-api-key",
            "nested": {"secret": "secret-value"},
            "signed_url": (
                "https://host.example/path/file.png?"
                "q-sign-algorithm=sha256&q-signature=q-signature"
            ),
            "aws_url": (
                "https://bucket.example/object.jpg?"
                "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=aws-secret"
            ),
            "normal_url": "https://host.example/path?a=1",
            "data_url": data_url,
            "blob": base64_blob,
            "task_id": "task_reply_fixture_001",
        }

        redacted = dating_log_rules.redact_dating_response(source)

        self.assertEqual(redacted["Authorization"], "[REDACTED]")
        self.assertEqual(redacted["headers"]["Cookie"], "[REDACTED]")
        self.assertEqual(redacted["headers"]["set-cookie"], "[REDACTED]")
        self.assertEqual(redacted["auth-token"], "[REDACTED]")
        self.assertEqual(redacted["api-key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["secret"], "[REDACTED]")
        self.assertEqual(
            redacted["signed_url"],
            "https://host.example/path/file.png?[REDACTED]",
        )
        self.assertEqual(
            redacted["aws_url"],
            "https://bucket.example/object.jpg?[REDACTED]",
        )
        self.assertEqual(redacted["normal_url"], source["normal_url"])
        self.assertEqual(
            redacted["data_url"], f"[REDACTED_BASE64 length={len(data_url)}]"
        )
        self.assertEqual(
            redacted["blob"], f"[REDACTED_BASE64 length={len(base64_blob)}]"
        )
        self.assertEqual(redacted["task_id"], source["task_id"])
        self.assertEqual(source["Authorization"], "Bearer secret-token-value")

    def test_long_text_is_truncated_everywhere_and_field_warning_is_added(self):
        long_text = "x" * 20000 + "SECRET_TAIL"
        source = {
            "task_snapshot": {
                "result_fields": [
                    {
                        "path": "result.note",
                        "value": long_text,
                        "value_truncated": False,
                    }
                ],
                "result_payload": {"note": long_text},
                "warnings": [],
            },
            "calls": [
                {"response": {"data": {"result": {"note": long_text}}}}
            ],
            "checks": [{"actual": long_text, "evidence": [{"value": long_text}]}],
        }

        redacted = dating_log_rules.redact_dating_response(source)

        field = redacted["task_snapshot"]["result_fields"][0]
        self.assertEqual(len(field["value"]), 20000)
        self.assertTrue(field["value_truncated"])
        self.assertEqual(
            redacted["task_snapshot"]["result_payload"]["note"], "x" * 20000
        )
        self.assertEqual(
            redacted["calls"][0]["response"]["data"]["result"]["note"],
            "x" * 20000,
        )
        self.assertEqual(redacted["checks"][0]["actual"], "x" * 20000)
        self.assertEqual(
            redacted["checks"][0]["evidence"][0]["value"], "x" * 20000
        )
        warnings = redacted["task_snapshot"]["warnings"]
        self.assertEqual(
            [(warning["code"], warning["json_path"]) for warning in warnings],
            [("VALUE_TRUNCATED", "result.note")],
        )
        self.assertIn("SECRET_TAIL", source["task_snapshot"]["result_payload"]["note"])


class DatingReportTest(unittest.TestCase):
    """覆盖固定章节、排序、确定性以及报告入口防御性脱敏。"""

    def test_report_sections_are_fixed_ordered_and_llm_free(self):
        analysis = _load_reply_analysis()
        report = dating_log_rules.render_dating_report(
            analysis, run_dating_checks(analysis)
        )
        headings = [line for line in report.splitlines() if line.startswith("## ")]

        self.assertEqual(report.splitlines()[0], "# Dating 结构化接口日志分析")
        self.assertEqual(headings, REPORT_HEADINGS)
        self.assertNotIn("AI 说明", report)
        self.assertNotIn("模型名称", report)
        self.assertNotIn("可能原因", report)
        self.assertNotIn("推测", report)
        self.assertIn("dating.reply_generation.v1", report)
        self.assertIn("GetTaskResult", report)

    def test_report_is_deterministic_and_sorts_checks_by_outcome(self):
        analysis = _load_reply_analysis()
        checks = [
            {
                "rule_id": rule_id,
                "priority": "P2",
                "title": title,
                "outcome": outcome,
                "actual": actual,
                "expected": expected,
                "evidence": [],
            }
            for rule_id, title, outcome, actual, expected in (
                ("T-PASS", "pass", "PASS", 1, 1),
                ("T-NA", "na", "NA", None, "applicable"),
                ("T-WARN", "warn", "WARN", "w", "clean"),
                ("T-UNKNOWN", "unknown", "UNKNOWN", None, "known"),
                ("T-FAIL", "fail", "FAIL", "bad", "good"),
            )
        ]

        first = dating_log_rules.render_dating_report(analysis, checks)
        second = dating_log_rules.render_dating_report(
            deepcopy(analysis), deepcopy(checks)
        )

        self.assertEqual(first, second)
        ordered_markers = [
            "[FAIL] T-FAIL",
            "[WARN] T-WARN",
            "[UNKNOWN] T-UNKNOWN",
            "[PASS] T-PASS",
            "[NA] T-NA",
        ]
        positions = [first.index(marker) for marker in ordered_markers]
        self.assertEqual(positions, sorted(positions))

    def test_report_redacts_analysis_and_check_values_without_mutating_inputs(self):
        analysis = _load_reply_analysis()
        analysis["calls"][0].setdefault("request", {})[
            "Authorization"
        ] = "Bearer secret-token-value"
        analysis["task_snapshot"]["input_assets"][0]["signed_url"] = (
            "https://host.example/object.png?q-signature=q-signature"
        )
        analysis["task_snapshot"]["result_summary"]["preview"] = (
            "data:image/png;base64," + "C" * 32
        )
        checks = run_dating_checks(analysis)
        checks[0]["actual"] = {
            "access_token": "secret-check-token",
            "url": "https://host.example/path?Signature=check-signature",
        }

        report = dating_log_rules.render_dating_report(analysis, checks)

        for secret in (
            "secret-token-value",
            "q-signature",
            "secret-check-token",
            "check-signature",
            "data:image/png;base64",
        ):
            self.assertNotIn(secret, report)
        self.assertIn("[REDACTED]", report)
        self.assertIn("[REDACTED_BASE64", report)
        self.assertEqual(
            analysis["calls"][0]["request"]["Authorization"],
            "Bearer secret-token-value",
        )


if __name__ == "__main__":
    unittest.main()
