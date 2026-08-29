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
    "## 任务与结果摘要",
    "## 接口执行链路",
    "## 上传资源",
    "## 任务状态时间线",
    "## 最终结果字段",
    "## Null 与空值",
    "## 已确认正常",
    "## 已确认异常",
    "## 需要确认",
    "## 日志不足",
]


def _load_reply_analysis() -> dict:
    """使用真实 Reply golden，报告测试不复制 analyzer 聚合结果。"""
    return analyze_dating_log(
        (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
    )


def _report_section(report: str, heading: str) -> str:
    """提取一个固定二级章节，避免测试依赖生产报告辅助函数。"""
    start = report.index(heading) + len(heading)
    next_heading = report.find("\n## ", start)
    return report[start:] if next_heading < 0 else report[start:next_heading]


class DatingRedactionTest(unittest.TestCase):
    """覆盖敏感键、签名 URL、Base64 与长文本递归脱敏。"""

    def test_document_redactor_sanitizes_embedded_markdown_secrets(self):
        """整篇 Markdown 中的凭证行、签名 URL 和二进制片段均须脱敏。"""
        standard_blob = "A" * 256
        padded_blob = "D" * 254 + "=="
        urlsafe_blob = "B" * 255 + "_"
        data_url = "data:image/png;base64," + "C" * 300
        document = (
            "# Diagnostic report\n\n"
            "Authorization: Bearer markdown-auth-secret\n"
            "- Cookie: session=markdown-cookie-secret\n"
            "> X-Auth-Token: markdown-token-secret\n"
            "Asset: [image](https://cdn.example/a.png?"
            "X-Amz-Signature=markdown-signature&x=1)\n"
            f"Inline data: {data_url}\n"
            f"Standard blob: {standard_blob}\n"
            f"Padded blob: {padded_blob}\n"
            f"URL-safe blob: {urlsafe_blob}\n"
        )
        redactor = getattr(dating_log_rules, "redact_dating_document", None)

        self.assertIsNotNone(redactor)
        redacted = redactor(document)

        for secret in (
            "markdown-auth-secret",
            "markdown-cookie-secret",
            "markdown-token-secret",
            "markdown-signature",
            data_url,
            standard_blob,
            padded_blob,
            urlsafe_blob,
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("Authorization: [REDACTED]", redacted)
        self.assertIn("- Cookie: [REDACTED]", redacted)
        self.assertIn("> X-Auth-Token: [REDACTED]", redacted)
        self.assertIn(
            "https://cdn.example/a.png?[REDACTED]",
            redacted,
        )
        self.assertIn(
            f"[REDACTED_BASE64 length={len(data_url)}]", redacted
        )
        self.assertIn(
            f"[REDACTED_BASE64 length={len(standard_blob)}]", redacted
        )
        self.assertIn(
            f"[REDACTED_BASE64 length={len(padded_blob)}]", redacted
        )
        self.assertIn(
            f"[REDACTED_BASE64 length={len(urlsafe_blob)}]", redacted
        )

    def test_document_redactor_is_idempotent_and_does_not_cap_document(self):
        """文档可超过 20,000 字符，重复脱敏不得丢失正文或继续变化。"""
        document = (
            "# Long report\n"
            + "ordinary markdown paragraph with spaces and punctuation.\n" * 500
            + "END-OF-FULL-REPORT\n"
        )
        redactor = getattr(dating_log_rules, "redact_dating_document", None)

        self.assertGreater(len(document), 20_000)
        self.assertIsNotNone(redactor)
        first = redactor(document)
        second = redactor(first)

        self.assertEqual(first, document)
        self.assertEqual(second, first)
        self.assertTrue(first.endswith("END-OF-FULL-REPORT\n"))

    def test_document_credential_formats_replace_only_sensitive_values(self):
        """常见 Markdown/JSON 包装不能绕过显式敏感键判定。"""
        cases = (
            (
                "bold",
                "**Authorization**: Bearer bold-secret",
                "**Authorization**: [REDACTED]",
            ),
            (
                "backtick",
                "`X-Auth-Token`: backtick-secret",
                "`X-Auth-Token`: [REDACTED]",
            ),
            (
                "quoted-header",
                '"Authorization": Bearer quoted-header-secret',
                '"Authorization": [REDACTED]',
            ),
            (
                "underscore",
                "_Cookie_: underscore-secret",
                "_Cookie_: [REDACTED]",
            ),
            (
                "table",
                "| Cookie | table-secret |",
                "| Cookie | [REDACTED] |",
            ),
            (
                "table-safe-neighbors",
                "| Cookie | table-secret | note | keep |",
                "| Cookie | [REDACTED] | note | keep |",
            ),
            (
                "inline-json",
                '{"apiSecret":"json-secret","status":"ok"}',
                '{"apiSecret":"[REDACTED]","status":"ok"}',
            ),
            (
                "inline-json-spaces",
                '{"apiSecret" : "space-secret", "status": "ok"}',
                '{"apiSecret" : "[REDACTED]", "status": "ok"}',
            ),
            (
                "plain-colon",
                "Authorization: plain-secret",
                "Authorization: [REDACTED]",
            ),
            (
                "plain-equals",
                "api_key=equal-secret",
                "api_key=[REDACTED]",
            ),
            (
                "safe-bold",
                "**authorizationMode**: delegated",
                "**authorizationMode**: delegated",
            ),
            (
                "safe-table",
                "| cookieConsent | accepted |",
                "| cookieConsent | accepted |",
            ),
            (
                "safe-json",
                '{"apiKeyRotationDate":"2026-01-01","status":"ok"}',
                '{"apiKeyRotationDate":"2026-01-01","status":"ok"}',
            ),
            (
                "safe-equals",
                "secretSantaName=Alice",
                "secretSantaName=Alice",
            ),
        )

        for name, source, expected in cases:
            with self.subTest(name=name):
                redacted = dating_log_rules.redact_dating_document(source)
                self.assertEqual(redacted, expected)
                self.assertEqual(
                    dating_log_rules.redact_dating_document(redacted),
                    expected,
                )

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

    def test_signed_url_variants_and_urlsafe_base64_are_redacted(self):
        """覆盖四类签名查询键和连续 URL-safe Base64 候选值。"""
        urlsafe_blob = "A" * 255 + "_"
        source = {
            "cos": "https://cos.example/a.png?q-signature=cos-secret&x=1",
            "cos_underscore": (
                "https://cos.example/a2.png?q_signature=cos-secret&x=1"
            ),
            "aws": "https://s3.example/b.png?X-Amz-Signature=aws-secret&x=1",
            "aws_underscore": (
                "https://s3.example/b2.png?x_amz_signature=aws-secret&x=1"
            ),
            "google": (
                "https://storage.example/c.png?"
                "X-Goog-Signature=google-secret&x=1"
            ),
            "google_underscore": (
                "https://storage.example/c2.png?"
                "x_goog_signature=google-secret&x=1"
            ),
            "azure": "https://blob.example/d.png?sv=2025-01-01&SIG=azure-secret",
            "algorithm": (
                "https://cos.example/e.png?q_sign_algorithm=sha256&x=1"
            ),
            "urlsafe_blob": urlsafe_blob,
        }

        redacted = dating_log_rules.redact_dating_response(source)

        self.assertEqual(redacted["cos"], "https://cos.example/a.png?[REDACTED]")
        self.assertEqual(
            redacted["cos_underscore"],
            "https://cos.example/a2.png?[REDACTED]",
        )
        self.assertEqual(redacted["aws"], "https://s3.example/b.png?[REDACTED]")
        self.assertEqual(
            redacted["aws_underscore"],
            "https://s3.example/b2.png?[REDACTED]",
        )
        self.assertEqual(
            redacted["google"], "https://storage.example/c.png?[REDACTED]"
        )
        self.assertEqual(
            redacted["google_underscore"],
            "https://storage.example/c2.png?[REDACTED]",
        )
        self.assertEqual(redacted["azure"], "https://blob.example/d.png?[REDACTED]")
        self.assertEqual(
            redacted["algorithm"], "https://cos.example/e.png?[REDACTED]"
        )
        self.assertEqual(
            redacted["urlsafe_blob"],
            f"[REDACTED_BASE64 length={len(urlsafe_blob)}]",
        )

    def test_signature_like_business_query_keys_are_not_over_redacted(self):
        """仅有 signature/sig 前缀的业务参数不是签名凭证。"""
        source = {
            "snake": "https://host.example/a?signature_color=blue&x=1",
            "camel": "https://host.example/b?signatureColor=green&x=1",
            "short": "https://host.example/c?sig_color=red&x=1",
            "metadata": "https://host.example/d?signature_count=3&x=1",
        }

        redacted = dating_log_rules.redact_dating_response(source)
        analysis = _load_reply_analysis()
        checks = run_dating_checks(analysis)
        checks[0]["actual"] = source
        report = dating_log_rules.render_dating_report(analysis, checks)

        self.assertEqual(redacted, source)
        for url in source.values():
            self.assertIn(url, report)

    def test_malformed_url_like_text_does_not_crash_redaction_or_report(self):
        """坏 URL 只作为普通文本保留，不能让递归响应或报告渲染中断。"""
        malformed = "https://[broken"

        redacted = dating_log_rules.redact_dating_response(
            {"ordinary_text": malformed}
        )
        analysis = _load_reply_analysis()
        checks = run_dating_checks(analysis)
        checks[0]["actual"] = malformed
        report = dating_log_rules.render_dating_report(analysis, checks)

        self.assertEqual(redacted["ordinary_text"], malformed)
        self.assertIn(malformed, report)

    def test_sensitive_key_format_variants_redact_without_business_overmatch(self):
        """敏感类别按完整词元匹配，camel/连字符变化不影响结果。"""
        sensitive = {
            "authorization": "secret-authorization",
            "Proxy-Authorization": "secret-proxy-authorization",
            "X-Auth-Token": "secret-x-auth-token",
            "cookie": "secret-cookie",
            "setCookie": "secret-set-cookie",
            "auth_token": "secret-auth-token",
            "accessToken": "secret-access-token",
            "refreshToken": "secret-refresh-token",
            "ID-TOKEN": "secret-id-token",
            "sessionToken": "secret-session-token",
            "api_key": "secret-api-key",
            "X-API-Key": "secret-x-api-key",
            "secret": "secret-value",
            "apiSecret": "secret-api-secret",
            "clientSecret": "secret-client-value",
            "AWS-Secret-Access-Key": "secret-aws-access-key",
        }
        ordinary = {
            "authorization_status": "approved",
            "cookie_preferences": "essential-only",
            "token_count": 3,
            "token_status": "active",
            "sessionTokenCount": 2,
            "accessTokenStatus": "expired",
            "auth_token_count": 4,
            "api_key_count": 1,
            "client_secret_hint": "last-four",
            "secretary": "business-value",
        }

        redacted = dating_log_rules.redact_dating_response(
            {**sensitive, **ordinary}
        )

        self.assertEqual(
            {key: redacted[key] for key in sensitive},
            {key: "[REDACTED]" for key in sensitive},
        )
        self.assertEqual(
            {key: redacted[key] for key in ordinary},
            ordinary,
        )

    def test_credential_key_table_matches_raw_and_report_without_overreach(self):
        """显式凭证键及紧凑别名脱敏，业务复合键在两种输出中均保留。"""
        cases = (
            ("Authorization", "credential-authorization", True),
            ("Proxy-Authorization", "credential-proxy-authorization", True),
            ("Cookie", "credential-cookie", True),
            ("Set-Cookie", "credential-set-cookie", True),
            ("auth_token", "credential-auth-token", True),
            ("X-Auth-Token", "credential-x-auth-token", True),
            ("accessToken", "credential-access-token", True),
            ("refreshToken", "credential-refresh-token", True),
            ("id_token", "credential-id-token", True),
            ("sessionToken", "credential-session-token", True),
            ("api_key", "credential-api-key", True),
            ("X-API-Key", "credential-x-api-key", True),
            ("secret", "credential-secret", True),
            ("client_secret", "credential-client-secret", True),
            ("apiSecret", "credential-api-secret", True),
            ("AWS-Secret-Access-Key", "credential-aws-secret", True),
            ("xauthtoken", "compact-x-auth-token", True),
            ("XAUTHTOKEN", "compact-upper-x-auth-token", True),
            ("apisecret", "compact-api-secret", True),
            ("APISECRET", "compact-upper-api-secret", True),
            ("awssecretaccesskey", "compact-aws-secret", True),
            ("AWSSECRETACCESSKEY", "compact-upper-aws-secret", True),
            ("cookieConsent", "business-cookie-consent", False),
            ("tokenBucketSize", "business-token-bucket-size", False),
            ("secretSantaName", "business-secret-santa-name", False),
            ("apiKeyRotationDate", "business-api-key-rotation-date", False),
            ("authorizationMode", "business-authorization-mode", False),
            ("authorization_status", "business-authorization-status", False),
            ("token_count", "business-token-count", False),
            ("accessTokenStatus", "business-access-token-status", False),
            ("api_key_count", "business-api-key-count", False),
            ("client_secret_hint", "business-secret-hint", False),
        )
        source = {key: value for key, value, _sensitive in cases}

        redacted = dating_log_rules.redact_dating_response(source)
        analysis = _load_reply_analysis()
        checks = run_dating_checks(analysis)
        checks[0]["actual"] = source
        report = dating_log_rules.render_dating_report(analysis, checks)

        for key, value, sensitive in cases:
            with self.subTest(surface="raw", key=key):
                expected = "[REDACTED]" if sensitive else value
                self.assertEqual(redacted[key], expected)
            with self.subTest(surface="report", key=key):
                if sensitive:
                    self.assertNotIn(value, report)
                else:
                    self.assertIn(f'"{key}":"{value}"', report)

    def test_long_text_is_truncated_everywhere_and_field_warning_is_added(self):
        # 空格使该值明确属于自由文本，而不是 Base64/URL-safe Base64 候选。
        long_text = "x" * 20000 + " SECRET_TAIL"
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
        self.assertIn("null_count", _report_section(report, "## Null 与空值"))

    def test_report_is_deterministic_and_partitions_checks_by_outcome(self):
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
        partitions = {
            "## 已确认正常": "[PASS] T-PASS",
            "## 已确认异常": "[FAIL] T-FAIL",
            "## 需要确认": "[WARN] T-WARN",
            "## 日志不足": "[UNKNOWN] T-UNKNOWN",
        }
        for heading, expected_marker in partitions.items():
            with self.subTest(heading=heading):
                section = _report_section(first, heading)
                self.assertIn(expected_marker, section)
                for other_marker in set(partitions.values()) - {expected_marker}:
                    self.assertNotIn(other_marker, section)
        log_section = _report_section(first, "## 日志不足")
        self.assertIn("### 不适用", log_section)
        self.assertIn("[NA] T-NA", log_section)
        self.assertLess(
            log_section.index("[UNKNOWN] T-UNKNOWN"),
            log_section.index("### 不适用"),
        )
        self.assertLess(
            log_section.index("### 不适用"),
            log_section.index("[NA] T-NA"),
        )
        for heading in ("## 已确认正常", "## 已确认异常", "## 需要确认"):
            self.assertNotIn("[NA] T-NA", _report_section(first, heading))
        self.assertEqual(
            [line for line in first.splitlines() if line.startswith("## ")],
            REPORT_HEADINGS,
        )

    def test_every_stable_rule_appears_exactly_once_in_report(self):
        """40 条规则无论 outcome 都必须在固定报告中可追溯且不重复。"""
        analysis = _load_reply_analysis()
        checks = run_dating_checks(analysis)

        report = dating_log_rules.render_dating_report(analysis, checks)

        self.assertEqual(len(checks), 40)
        for check in checks:
            marker = f"[{check['outcome']}] {check['rule_id']}"
            with self.subTest(rule_id=check["rule_id"]):
                self.assertEqual(report.count(marker), 1)

    def test_parse_warnings_are_in_fixed_log_insufficient_section(self):
        """解析 warning 进入既有“日志不足”章节，不能新增顶级章节。"""
        analysis = _load_reply_analysis()
        analysis["parse_warnings"].append(
            {
                "code": "TEST_PARSE_WARNING",
                "message": "fixture parse warning",
                "line_start": 3,
                "line_end": 4,
            }
        )

        report = dating_log_rules.render_dating_report(
            analysis, run_dating_checks(analysis)
        )

        section = _report_section(report, "## 日志不足")
        self.assertIn("TEST_PARSE_WARNING", section)
        self.assertIn("fixture parse warning", section)
        self.assertEqual(
            [line for line in report.splitlines() if line.startswith("## ")],
            REPORT_HEADINGS,
        )

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

    def test_report_redacts_composite_credential_keys_without_hiding_metadata(self):
        """报告入口沿用凭证键分类，同时保留 token 计数和状态字段。"""
        analysis = _load_reply_analysis()
        checks = run_dating_checks(analysis)
        checks[0]["actual"] = {
            "X-Auth-Token": "report-x-auth-secret",
            "apiSecret": "report-api-secret",
            "AWS-Secret-Access-Key": "report-aws-access-secret",
            "accessTokenStatus": "expired",
            "auth_token_count": 4,
        }

        report = dating_log_rules.render_dating_report(analysis, checks)

        for secret in (
            "report-x-auth-secret",
            "report-api-secret",
            "report-aws-access-secret",
        ):
            self.assertNotIn(secret, report)
        self.assertIn('"accessTokenStatus":"expired"', report)
        self.assertIn('"auth_token_count":4', report)

    def test_report_does_not_leak_azure_sas_or_urlsafe_base64_from_checks(self):
        """报告入口必须递归脱敏 checks 中的 Azure SAS 与二进制候选值。"""
        analysis = _load_reply_analysis()
        checks = run_dating_checks(analysis)
        urlsafe_blob = "A" * 255 + "_"
        checks[0]["actual"] = {
            "azure_url": (
                "https://blob.example/object.png?"
                "sv=2025-01-01&sig=azure-check-secret"
            ),
            "binary": urlsafe_blob,
        }

        report = dating_log_rules.render_dating_report(analysis, checks)

        self.assertNotIn("azure-check-secret", report)
        self.assertNotIn("?sv=", report)
        self.assertNotIn(urlsafe_blob, report)
        self.assertIn("https://blob.example/object.png?[REDACTED]", report)
        self.assertIn(
            f"[REDACTED_BASE64 length={len(urlsafe_blob)}]", report
        )


if __name__ == "__main__":
    unittest.main()
