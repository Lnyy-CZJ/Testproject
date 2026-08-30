import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import (
    build_interface_statistics,
    create_app,
    detect_log_kind,
    extract_methods,
    extract_request_id,
    extract_status_code,
    extract_trace_id,
    filter_log_text,
    format_result_text,
    parse_log_block,
    parse_log_blocks,
    normalize_base_path,
    split_log_blocks,
)


SAMPLE_LOG = """默认\t10:00:00\tRunner\tflutter: ┌────
默认\t10:00:00\tRunner\tflutter: │ [HTTP] --> POST http://example.com service=svc method=GetMe
默认\t10:00:00\tRunner\tflutter: └────
默认\t10:00:01\tRunner\tflutter: ┌────
默认\t10:00:01\tRunner\tflutter: │ [HTTP] request:
默认\t10:00:01\tRunner\tflutter: │ {"method_name": "GetMe", "params": {"id": 1}}
默认\t10:00:01\tRunner\tflutter: └────
默认\t10:00:02\tRunner\tflutter: ┌────
默认\t10:00:02\tRunner\tflutter: │ [HTTP] <-- 200 POST http://example.com service=svc method=GetMe
默认\t10:00:02\tRunner\tflutter: └────
默认\t10:00:03\tRunner\tflutter: ┌────
默认\t10:00:03\tRunner\tflutter: │ [HTTP] response:
默认\t10:00:03\tRunner\tflutter: │ {"code": 0, "data": {"name": "alice"}}
默认\t10:00:03\tRunner\tflutter: └────
默认\t10:00:04\tRunner\tflutter: ┌────
默认\t10:00:04\tRunner\tflutter: │ [HTTP] --> POST http://example.com service=svc method=TrackEvents
默认\t10:00:04\tRunner\tflutter: └────"""


class LogFilterTests(unittest.TestCase):
    def test_export_log_saves_content_as_log_file(self):
        """导出接口应将指定内容保存为带来源前缀的 .log 文件。"""
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config["LOG_EXPORT_DIR"] = export_dir
            app.config["LOG_EXPORT_DISPLAY_DIR"] = export_dir
            response = app.test_client().post(
                "/export",
                json={"export_type": "filtered_result", "content": "filtered log"},
            )
            payload = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["filename"].startswith("filtered_result_"))
            self.assertTrue(payload["filename"].endswith(".log"))
            self.assertEqual(
                (Path(export_dir) / payload["filename"]).read_text(encoding="utf-8"),
                "filtered log",
            )

    def test_export_refuses_foreign_resource_context_without_creating_enumerable_file(self):
        """平台拒绝时，导出文件不得落入可猜测或可枚举的公共目录。"""
        app = create_app()
        app.testing = True

        class DeniedPlatformResponse:
            """提供 urlopen 上下文管理器协议的最小平台拒绝响应。"""

            def read(self):
                return b'{"allowed": false, "code": "RESOURCE_NOT_FOUND"}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with TemporaryDirectory() as export_dir, TemporaryDirectory() as token_dir:
            token_file = Path(token_dir) / "platform-token"
            token_file.write_text("test-tool-token", encoding="utf-8")
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
                PLATFORM_API_URL="http://platform.invalid/api/v1",
                PLATFORM_CLIENT_TOKEN_FILE=str(token_file),
            )
            with patch("app.urlrequest.urlopen", return_value=DeniedPlatformResponse()):
                client = app.test_client()
                client.set_cookie("tp_csrf", "test-csrf")
                response = client.post(
                    "/export",
                    json={"export_type": "filtered_result", "content": "secret log"},
                    headers={
                        "X-Platform-Resource-Context": "opaque-tester-b",
                        "X-CSRF-Token": "test-csrf",
                    },
                )

            self.assertEqual(404, response.status_code)
            self.assertEqual([], list(Path(export_dir).rglob("*")))

    def test_platform_export_registers_snapshot_before_writing_owner_directory(self):
        """平台导出必须先登记同一随机根 ID，再写入 owner 私有目录。"""

        app = create_app()
        app.testing = True
        calls = []

        class PlatformResponse:
            def __init__(self, payload, status=200):
                self.payload = payload
                self.status = status

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def platform_call(outgoing, timeout):
            calls.append(outgoing.full_url)
            if outgoing.full_url.endswith("/internal/resources"):
                request_payload = json.loads(outgoing.data.decode("utf-8"))
                return PlatformResponse({
                    "resource_id": request_payload["resource_id"],
                    "owner_user_id": "tester-a",
                    "environment_id": "dev",
                }, 201)
            return PlatformResponse({"allowed": True, "user_id": "tester-a"})

        with TemporaryDirectory() as export_dir, TemporaryDirectory() as token_dir:
            token_file = Path(token_dir) / "platform-token"
            token_file.write_text("test-tool-token", encoding="utf-8")
            app.config.update(LOG_EXPORT_DIR=export_dir, PLATFORM_API_URL="http://platform.invalid/api/v1", PLATFORM_CLIENT_TOKEN_FILE=str(token_file))
            with patch("app.urlrequest.urlopen", side_effect=platform_call):
                client = app.test_client()
                client.set_cookie("tp_csrf", "test-csrf")
                response = client.post("/export", json={"export_type": "filtered_result", "content": "private log"}, headers={"X-Platform-Resource-Context": "opaque", "X-CSRF-Token": "test-csrf"})

            self.assertEqual(200, response.status_code)
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue(calls[1].endswith("/internal/resources"))
            download_id = response.get_json()["download_id"]
            self.assertEqual(1, len(list((Path(export_dir) / "tester-a" / download_id).glob("*.log"))))

    def test_export_log_rejects_empty_content(self):
        """空内容不应创建导出文件。"""
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config["LOG_EXPORT_DIR"] = export_dir
            response = app.test_client().post(
                "/export",
                json={"export_type": "log_content", "content": ""},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(list(Path(export_dir).iterdir()), [])

    def test_export_dating_report_redacts_and_saves_markdown(self):
        """Dating Markdown 使用固定后缀，并在写盘前兜底删除签名查询。"""
        app = create_app()
        app.testing = True
        signed_url = (
            "https://signed.example/object.png?"
            "q-signature=markdown-export-secret&x=1"
        )

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            response = app.test_client().post(
                "/export",
                json={
                    "export_type": "dating_analysis_report",
                    "content": signed_url,
                },
            )
            payload = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                payload["filename"].startswith(
                    "dating_structured_analysis_"
                )
            )
            self.assertTrue(payload["filename"].endswith(".md"))
            self.assertEqual(
                (Path(export_dir) / payload["filename"]).read_text(
                    encoding="utf-8"
                ),
                "https://signed.example/object.png?[REDACTED]",
            )

    def test_export_dating_report_redacts_formatted_credential_values(self):
        """Markdown 导出落盘内容必须覆盖格式化凭证并保留安全邻接语法。"""
        cases = (
            (
                "bold",
                "**Authorization**: Bearer bold-secret",
                "**Authorization**: [REDACTED]",
            ),
            (
                "table",
                "| Cookie | table-secret |",
                "| Cookie | [REDACTED] |",
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
        )
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            for name, source, expected in cases:
                with self.subTest(name=name):
                    response = client.post(
                        "/export",
                        json={
                            "export_type": "dating_analysis_report",
                            "content": source,
                        },
                    )
                    payload = response.get_json()
                    persisted = (
                        Path(export_dir) / payload["filename"]
                    ).read_text(encoding="utf-8")

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(persisted, expected)

    def test_export_dating_report_preserves_sanitized_structure_boundaries(self):
        """Markdown 导出须按逻辑边界脱敏，不能泄漏或吞掉安全后缀。"""
        cases = (
            (
                "escaped-table-pipe",
                r"| Cookie | left\|TABLE_SUFFIX_SECRET | note | keep |",
                "| Cookie | [REDACTED] | note | keep |",
                "TABLE_SUFFIX_SECRET",
            ),
            (
                "whole-code-span",
                "`Authorization=Bearer CODE_PAIR_SECRET`",
                "`Authorization=[REDACTED]`",
                "CODE_PAIR_SECRET",
            ),
            (
                "code-span-safe-suffix",
                "`Authorization=CODE_SUFFIX_SECRET; status=ok`",
                "`Authorization=[REDACTED]; status=ok`",
                "CODE_SUFFIX_SECRET",
            ),
            (
                "json-array",
                '{"apiSecret":["JSON_ARRAY_SECRET"],"status":"ok"}',
                '{"apiSecret":"[REDACTED]","status":"ok"}',
                "JSON_ARRAY_SECRET",
            ),
            (
                "json-object",
                '{"apiSecret":{"value":"JSON_OBJECT_SECRET"},"status":"ok"}',
                '{"apiSecret":"[REDACTED]","status":"ok"}',
                "JSON_OBJECT_SECRET",
            ),
            (
                "json-null",
                '{"apiSecret":null,"status":"ok"}',
                '{"apiSecret":"[REDACTED]","status":"ok"}',
                None,
            ),
            (
                "json-number",
                '{"apiSecret":731,"status":"ok"}',
                '{"apiSecret":"[REDACTED]","status":"ok"}',
                "731",
            ),
            (
                "assignment-safe-suffix",
                "Authorization=HEADER_SECRET; status=ok; count=2",
                "Authorization=[REDACTED]; status=ok; count=2",
                "HEADER_SECRET",
            ),
        )
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            for name, source, expected, leaked_value in cases:
                with self.subTest(name=name):
                    response = client.post(
                        "/export",
                        json={
                            "export_type": "dating_analysis_report",
                            "content": source,
                        },
                    )
                    payload = response.get_json()
                    persisted = (
                        Path(export_dir) / payload["filename"]
                    ).read_text(encoding="utf-8")

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(persisted, expected)
                    if leaked_value is not None:
                        self.assertNotIn(leaked_value, persisted)

    def test_export_dating_report_redacts_rows_without_outer_pipes(self):
        """Markdown 导出须识别 one-delimiter 两列表格并保留安全列。"""
        cases = (
            (
                "two-columns",
                "Cookie | NO_OUTER_TABLE_SECRET",
                "Cookie | [REDACTED]",
                "NO_OUTER_TABLE_SECRET",
            ),
            (
                "safe-later-cells",
                "Cookie | OUTER_ROW_SECRET | note | keep",
                "Cookie | [REDACTED] | note | keep",
                "OUTER_ROW_SECRET",
            ),
        )
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            for name, source, expected, leaked_value in cases:
                with self.subTest(name=name):
                    response = client.post(
                        "/export",
                        json={
                            "export_type": "dating_analysis_report",
                            "content": source,
                        },
                    )
                    payload = response.get_json()
                    persisted = (
                        Path(export_dir) / payload["filename"]
                    ).read_text(encoding="utf-8")

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(persisted, expected)
                    self.assertNotIn(leaked_value, persisted)

    def test_export_dating_report_respects_quoted_assignment_values(self):
        """Markdown 导出须完整脱敏 quoted value 并保留外部安全赋值。"""
        cases = (
            (
                "double-quoted",
                'Authorization="LEFT_SECRET;RIGHT_SECRET"; status=ok',
                'Authorization="[REDACTED]"; status=ok',
                ("LEFT_SECRET", "RIGHT_SECRET"),
            ),
            (
                "single-quoted",
                "Authorization='SINGLE_LEFT_SECRET;SINGLE_RIGHT_SECRET'; status=ok",
                "Authorization='[REDACTED]'; status=ok",
                ("SINGLE_LEFT_SECRET", "SINGLE_RIGHT_SECRET"),
            ),
            (
                "escaped-double-quote",
                'Authorization="LEFT_SECRET\\\"INNER_SECRET;RIGHT_SECRET"; status=ok',
                'Authorization="[REDACTED]"; status=ok',
                ("LEFT_SECRET", "INNER_SECRET", "RIGHT_SECRET"),
            ),
            (
                "escaped-single-quote",
                "Authorization='LEFT_SECRET\\'INNER_SECRET;RIGHT_SECRET'; status=ok",
                "Authorization='[REDACTED]'; status=ok",
                ("LEFT_SECRET", "INNER_SECRET", "RIGHT_SECRET"),
            ),
            (
                "escaped-semicolon",
                r'Authorization="LEFT_SECRET\;RIGHT_SECRET"; status=ok',
                'Authorization="[REDACTED]"; status=ok',
                ("LEFT_SECRET", "RIGHT_SECRET"),
            ),
        )
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            for name, source, expected, leaked_values in cases:
                with self.subTest(name=name):
                    response = client.post(
                        "/export",
                        json={
                            "export_type": "dating_analysis_report",
                            "content": source,
                        },
                    )
                    payload = response.get_json()
                    persisted = (
                        Path(export_dir) / payload["filename"]
                    ).read_text(encoding="utf-8")

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(persisted, expected)
                    for leaked_value in leaked_values:
                        self.assertNotIn(leaked_value, persisted)

    def test_export_dating_report_apostrophe_does_not_hide_assignment(self):
        """Markdown 落盘前不得让普通 apostrophe 隐藏后续凭证赋值。"""
        source = (
            "note=it's-safe; "
            "Authorization=APOSTROPHE_BYPASS_SECRET; count=2"
        )
        expected = "note=it's-safe; Authorization=[REDACTED]; count=2"
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            response = app.test_client().post(
                "/export",
                json={
                    "export_type": "dating_analysis_report",
                    "content": source,
                },
            )
            payload = response.get_json()
            persisted = (
                Path(export_dir) / payload["filename"]
            ).read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(persisted, expected)
        self.assertNotIn("APOSTROPHE_BYPASS_SECRET", persisted)

    def test_export_dating_report_redacts_near_json_credentials(self):
        """Markdown 导出须保留 malformed JSON 诊断结构并遮住凭证值。"""
        cases = (
            (
                "trailing-comma",
                '{"apiSecret":"TRAILING_COMMA_SECRET",}',
                '{"apiSecret":"[REDACTED]",}',
                "TRAILING_COMMA_SECRET",
            ),
            (
                "surrounding-text-and-spacing",
                'before {"apiSecret" : "CONTEXT_SECRET", "status" : "ok",} after',
                'before {"apiSecret" : "[REDACTED]", "status" : "ok",} after',
                "CONTEXT_SECRET",
            ),
            (
                "nested-malformed-object",
                'prefix {"outer":{"apiSecret":"NESTED_NEAR_SECRET",},"status":"ok"} suffix',
                'prefix {"outer":{"apiSecret":"[REDACTED]",},"status":"ok"} suffix',
                "NESTED_NEAR_SECRET",
            ),
            (
                "safe-business-key",
                'prefix {"apiKeyRotationDate":"2026-01-01",} suffix',
                'prefix {"apiKeyRotationDate":"2026-01-01",} suffix',
                None,
            ),
        )
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            for name, source, expected, leaked_value in cases:
                with self.subTest(name=name):
                    response = client.post(
                        "/export",
                        json={
                            "export_type": "dating_analysis_report",
                            "content": source,
                        },
                    )
                    payload = response.get_json()
                    persisted = (
                        Path(export_dir) / payload["filename"]
                    ).read_text(encoding="utf-8")

                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(persisted, expected)
                    if leaked_value is not None:
                        self.assertNotIn(leaked_value, persisted)

    def test_export_dating_json_redacts_and_dumps_deterministically(self):
        """JSON 导出解析真实结构、递归脱敏，并保持稳定 UTF-8 格式。"""
        app = create_app()
        app.testing = True
        content = (
            '{"verdict":"NO_ISSUES",'
            '"Authorization":"Bearer json-export-secret",'
            '"signed_url":"https://signed.example/a?'
            'q-signature=json-signature",'
            '"token_count":3}'
        )

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            response = app.test_client().post(
                "/export",
                json={"export_type": "dating_analysis_json", "content": content},
            )
            payload = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                payload["filename"].startswith(
                    "dating_structured_analysis_"
                )
            )
            self.assertTrue(payload["filename"].endswith(".json"))
            saved = (Path(export_dir) / payload["filename"]).read_text(
                encoding="utf-8"
            )
            self.assertEqual(
                saved,
                "{\n"
                '  "verdict": "NO_ISSUES",\n'
                '  "Authorization": "[REDACTED]",\n'
                '  "signed_url": '
                '"https://signed.example/a?[REDACTED]",\n'
                '  "token_count": 3\n'
                "}",
            )
            self.assertNotIn("json-export-secret", saved)
            self.assertNotIn("json-signature", saved)

    def test_export_dating_json_accepts_all_valid_json_value_types(self):
        """list、scalar 和 null 都是有效 JSON，不能被错误限制为对象。"""
        app = create_app()
        app.testing = True
        cases = (
            (
                '[{"secret":"list-secret"}]',
                '[\n  {\n    "secret": "[REDACTED]"\n  }\n]',
            ),
            ('"scalar"', '"scalar"'),
            ("null", "null"),
            ("0", "0"),
        )

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            for content, expected in cases:
                with self.subTest(content=content):
                    response = client.post(
                        "/export",
                        json={
                            "export_type": "dating_analysis_json",
                            "content": content,
                        },
                    )
                    payload = response.get_json()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        (Path(export_dir) / payload["filename"]).read_text(
                            encoding="utf-8"
                        ),
                        expected,
                    )

    def test_dating_exports_preserve_full_golden_report_and_response(self):
        """超过 20k 的 golden 报告及完整 API 对象必须无损通过两种导出。"""
        app = create_app()
        app.testing = True
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "dating"
            / "reply_generation_multi_image_success.log"
        ).read_text(encoding="utf-8")

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            api_response = client.post(
                "/dating/analyze", json={"log_text": fixture}
            )
            api_payload = api_response.get_json()

            self.assertEqual(api_response.status_code, 200)
            self.assertGreater(len(api_payload["report_markdown"]), 20_000)

            markdown_response = client.post(
                "/export",
                json={
                    "export_type": "dating_analysis_report",
                    "content": api_payload["report_markdown"],
                },
            )
            json_response = client.post(
                "/export",
                json={
                    "export_type": "dating_analysis_json",
                    "content": json.dumps(
                        api_payload, ensure_ascii=False
                    ),
                },
            )

            self.assertEqual(markdown_response.status_code, 200)
            self.assertEqual(json_response.status_code, 200)
            markdown_path = (
                Path(export_dir) / markdown_response.get_json()["filename"]
            )
            json_path = Path(export_dir) / json_response.get_json()["filename"]
            self.assertEqual(
                markdown_path.read_text(encoding="utf-8"),
                api_payload["report_markdown"],
            )
            self.assertEqual(
                json.loads(json_path.read_text(encoding="utf-8")),
                api_payload,
            )

    def test_export_dating_json_rejects_invalid_json_without_file(self):
        """JSON 语法错误返回 400，且参数校验阶段不留下文件。"""
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            response = app.test_client().post(
                "/export",
                json={"export_type": "dating_analysis_json", "content": "{"},
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("JSON", response.get_json()["message"])
            self.assertEqual(list(Path(export_dir).iterdir()), [])

    def test_existing_analysis_report_and_unknown_export_contracts_remain(self):
        """新增 allow-list 不改变既有 Markdown 与未知类型的响应。"""
        app = create_app()
        app.testing = True

        with TemporaryDirectory() as export_dir:
            app.config.update(
                LOG_EXPORT_DIR=export_dir,
                LOG_EXPORT_DISPLAY_DIR=export_dir,
            )
            client = app.test_client()
            existing = client.post(
                "/export",
                json={"export_type": "analysis_report", "content": "# People"},
            )
            unknown = client.post(
                "/export",
                json={"export_type": "future_type", "content": "content"},
            )

            self.assertEqual(existing.status_code, 200)
            self.assertTrue(existing.get_json()["filename"].endswith(".md"))
            self.assertEqual(unknown.status_code, 400)
            self.assertEqual(unknown.get_json()["message"], "不支持的导出类型")

    def test_home_receives_disabled_dating_flag_and_still_renders(self):
        """首页只接收开关上下文；关闭 Dating 时现有页面仍正常渲染。"""
        app = create_app()
        app.testing = True
        app.config["DATING_STRUCTURED_ANALYZER_ENABLED"] = False

        with patch("app.render_template", return_value="rendered") as render:
            response = app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "rendered")
        self.assertFalse(
            render.call_args.kwargs["dating_analyzer_enabled"]
        )
        self.assertIn("platform_home_url", render.call_args.kwargs)

    def test_page_contains_export_search_and_auto_filter_controls(self):
        """页面应提供 Task 3 的 textarea 日志窗格和通用过滤控件。"""
        app = create_app()
        app.testing = True

        response = app.test_client().get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('<textarea id="log_text"', html)
        self.assertIn('<textarea id="result-text"', html)
        self.assertRegex(html, r'<textarea[^>]*id="result-text"[^>]*readonly')
        self.assertEqual(html.count('id="analyze-log-btn"'), 1)
        self.assertIn('id="log-filter-form"', html)
        self.assertIn('data-is-all="1"', html)
        self.assertIn('name="method"', html)
        self.assertIn('workbench-filter.js', html)
        self.assertIn('id="export-log-content-btn"', html)
        self.assertIn('id="export-filtered-result-btn"', html)
        self.assertIn('id="result-search"', html)
        self.assertIn('id="search-prev-btn"', html)
        self.assertIn('id="search-next-btn"', html)
        self.assertIn('id="action-message" role="status"', html)
        self.assertNotIn("<mark", html)

    def test_extracts_request_and_trace_ids_from_common_formats(self):
        text = 'request_id: abc123 trace_id=trace456 "request_id": "json789"'

        self.assertEqual(extract_request_id(text), "abc123")
        self.assertEqual(extract_trace_id(text), "trace456")

    def test_request_id_does_not_match_client_request_id(self):
        self.assertIsNone(extract_request_id('"client_request_id": "client123"'))

    def test_extracts_http_status_code(self):
        self.assertEqual(extract_status_code("[HTTP] <-- 200 POST /api"), 200)
        self.assertEqual(extract_status_code('"status_code": 500'), 500)
        self.assertIsNone(extract_status_code("[HTTP] request:"))

    def test_detects_request_and_response_log_kinds(self):
        self.assertEqual(detect_log_kind("[HTTP] --> POST /api"), "request")
        self.assertEqual(detect_log_kind("[HTTP] response:"), "response")
        self.assertEqual(detect_log_kind("ordinary log"), "other")

    def test_parses_log_block_into_structured_fields(self):
        block = "\n".join(
            [
                "[HTTP] <-- 200 POST /api service=svc method=TrackEvents",
                'request_id: abc123 trace_id: trace456',
            ]
        )

        parsed = parse_log_block(block, 3)

        self.assertEqual(parsed["index"], 3)
        self.assertEqual(parsed["method"], "TrackEvents")
        self.assertEqual(parsed["request_id"], "abc123")
        self.assertEqual(parsed["trace_id"], "trace456")
        self.assertEqual(parsed["kind"], "response")
        self.assertEqual(parsed["status_code"], 200)

    def test_builds_interface_statistics(self):
        blocks = parse_log_blocks(SAMPLE_LOG)

        statistics = build_interface_statistics(blocks)

        self.assertEqual(statistics["GetMe"]["request_count"], 1)
        self.assertEqual(statistics["GetMe"]["response_count"], 1)
        self.assertEqual(statistics["GetMe"]["success_count"], 1)
        self.assertEqual(statistics["GetMe"]["failure_count"], 0)
        self.assertEqual(statistics["GetMe"]["unresponded_count"], 0)
        self.assertEqual(statistics["GetMe"]["success_rate"], 100.0)
        self.assertEqual(statistics["GetMe"]["status_codes"], {200: 1})

    def test_page_displays_interface_statistics(self):
        app = create_app()
        app.testing = True

        response = app.test_client().post(
            "/",
            data={"log_text": SAMPLE_LOG, "method": "__ALL__"},
        )
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("接口分析", html)
        self.assertIn("GetMe", html)
        self.assertIn("成功率", html)
        self.assertIn("200", html)

    def test_extract_methods_from_method_and_method_name(self):
        methods = extract_methods(SAMPLE_LOG)

        self.assertEqual(methods, ["GetMe", "TrackEvents"])

    def test_split_log_blocks_uses_box_boundaries(self):
        blocks = split_log_blocks(SAMPLE_LOG)

        self.assertEqual(len(blocks), 5)
        self.assertIn("method=GetMe", blocks[0])
        self.assertIn("[HTTP] request:", blocks[1])

    def test_filter_method_includes_adjacent_request_and_response_blocks(self):
        result_text, count = filter_log_text(SAMPLE_LOG, "GetMe")

        self.assertEqual(count, 4)
        self.assertIn("method=GetMe", result_text)
        self.assertIn("[HTTP] request:", result_text)
        self.assertIn('"method_name": "GetMe"', result_text)
        self.assertIn("[HTTP] response:", result_text)
        self.assertNotIn("TrackEvents", result_text)

    def test_filter_method_uses_exact_method_name(self):
        log = "\n".join(
            [
                "默认\t10:00:00\tRunner\tflutter: ┌────",
                "默认\t10:00:00\tRunner\tflutter: │ [HTTP] --> POST http://example.com method=GetTask",
                "默认\t10:00:00\tRunner\tflutter: └────",
                "默认\t10:00:01\tRunner\tflutter: ┌────",
                "默认\t10:00:01\tRunner\tflutter: │ [HTTP] --> POST http://example.com method=GetTaskCandidateDetail",
                "默认\t10:00:01\tRunner\tflutter: └────",
            ]
        )

        result_text, count = filter_log_text(log, "GetTask")

        self.assertEqual(count, 1)
        self.assertIn("method=GetTask", result_text)
        self.assertNotIn("GetTaskCandidateDetail", result_text)

    def test_format_result_text_removes_console_prefix(self):
        blocks = split_log_blocks(SAMPLE_LOG)

        result_text = format_result_text(blocks[:1])

        self.assertNotIn("┌────", result_text)
        self.assertNotIn("└────", result_text)
        self.assertIn("[HTTP] --> POST", result_text)
        self.assertNotIn("│ [HTTP] --> POST", result_text)
        self.assertNotIn("默认\t10:00:00\tRunner\tflutter:", result_text)

    def test_filter_all_returns_original_log(self):
        result_text, count = filter_log_text(SAMPLE_LOG, "__ALL__")

        self.assertEqual(count, 5)
        self.assertIn("method=GetMe", result_text)
        self.assertNotIn("默认\t10:00:00\tRunner\tflutter:", result_text)

    def test_line_fallback_when_no_box_boundaries(self):
        log = "\n".join(
            [
                "[HTTP] --> POST http://example.com method=GetSubscriptionStatus",
                "[HTTP] --> POST http://example.com method=GetSubscriptionList",
            ]
        )

        result_text, count = filter_log_text(log, "GetSubscriptionStatus")

        self.assertEqual(count, 1)
        self.assertIn("GetSubscriptionStatus", result_text)
        self.assertNotIn("GetSubscriptionList", result_text)

    def test_large_log_form_submission_is_accepted(self):
        app = create_app()
        app.testing = True
        large_log = SAMPLE_LOG + "\n" + ("x" * 600_000)

        response = app.test_client().post(
            "/",
            data={"log_text": large_log, "method": "GetMe"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("GetMe", response.get_data(as_text=True))

    def test_base_path_is_normalized_and_rejects_unsafe_values(self):
        """基础路径应格式统一，并拒绝可能改变路由语义的配置。"""
        self.assertEqual(normalize_base_path(""), "")
        self.assertEqual(normalize_base_path("log-filter/"), "/log-filter")

        for invalid_path in ("/../log-filter", "/log-filter?debug=1", "//log-filter"):
            with self.subTest(invalid_path=invalid_path):
                with self.assertRaises(ValueError):
                    normalize_base_path(invalid_path)

    def test_prefixed_routes_keep_forms_and_export_on_platform_path(self):
        """平台模式下页面、导出与示例接口必须使用相同工具前缀。"""
        app = create_app(base_path="/log-filter")
        app.testing = True
        client = app.test_client()

        response = client.get("/log-filter/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/log-filter/"', html)
        self.assertIn('data-export-url="/log-filter/export"', html)
        self.assertEqual(client.get("/log-filter/sample").status_code, 200)
        self.assertEqual(client.get("/").status_code, 404)

    def test_prefixed_health_route_returns_service_status(self):
        """健康检查应轻量返回服务标识，且遵循基础路径。"""
        app = create_app(base_path="/log-filter")
        app.testing = True
        client = app.test_client()

        response = client.get("/log-filter/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "service": "log-filter", "status": "ok", "version": "unknown",
                "revision": "unknown", "dirty": True, "runtime_environment": "unknown",
                "content_sha256": "unknown",
            },
        )


if __name__ == "__main__":
    unittest.main()
