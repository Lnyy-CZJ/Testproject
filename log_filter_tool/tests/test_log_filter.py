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

    def test_page_contains_export_search_and_auto_filter_controls(self):
        """页面应提供两个导出入口、结果搜索和 method 自动提交逻辑。"""
        app = create_app()
        app.testing = True

        response = app.test_client().get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="export-log-content-btn"', html)
        self.assertIn('id="export-filtered-result-btn"', html)
        self.assertIn('id="result-search"', html)
        self.assertIn('id="search-prev-btn"', html)
        self.assertIn('id="search-next-btn"', html)
        self.assertIn("form.requestSubmit()", html)
        self.assertIn('id="action-message" role="status"', html)
        self.assertIn("}, 3000);", html)

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
        self.assertIn('var exportUrl = "/log-filter/export"', html)
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
