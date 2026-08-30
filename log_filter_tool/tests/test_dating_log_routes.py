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


class DatingPageTest(unittest.TestCase):
    """锁定 Dating 工作台的 DOM、交互、安全写入和部署路径合同。"""

    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def assert_contains_contracts(self, source, contracts):
        """集中报告缺失的静态合同，避免失败时打印整段内联 JavaScript。"""
        missing = [contract for contract in contracts if contract not in source]
        self.assertEqual(missing, [], f"缺失前端合同：{missing}")

    @staticmethod
    def dating_source():
        """读取独立 Dating 适配器，确保页面测试不再依赖模板内联脚本。"""
        path = Path(__file__).resolve().parents[1] / "static/js/workbench-dating.js"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_enabled_page_contains_complete_dating_workbench(self):
        """缺失任一业务区块时，工程师都无法完成 PRD 的排查流程。"""
        html = self.client.get("/").get_data(as_text=True)

        for marker in (
            'id="analyze-dating-btn"',
            'id="dating-analysis"',
            'id="dating-summary"',
            'id="dating-interface-table"',
            'id="dating-upload-list"',
            'id="dating-task-timeline"',
            'id="dating-result-sections"',
            'id="dating-field-tree"',
            'id="dating-field-filter"',
            'id="dating-field-search"',
            'id="dating-field-table"',
            'id="dating-check-list"',
            'id="dating-parse-warnings"',
            'id="dating-report"',
            'id="copy-dating-report-btn"',
            'id="export-dating-report-btn"',
            'id="export-dating-json-btn"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

        people_position = html.find('id="analyze-people-search-btn"')
        dating_position = html.find('id="analyze-dating-btn"')
        self.assertGreater(dating_position, people_position)
        self.assertIn("/dating/analyze", html)

    def test_disabled_page_omits_dating_ui_but_preserves_people(self):
        """功能开关关闭时不能留下不可用入口，也不能影响 People 面板。"""
        self.app.config["DATING_STRUCTURED_ANALYZER_ENABLED"] = False

        html = self.client.get("/").get_data(as_text=True)

        self.assertNotIn('id="analyze-dating-btn"', html)
        self.assertNotIn('id="dating-analysis"', html)
        self.assertNotIn("function analyzeDatingLog()", html)
        self.assertIn('id="analyze-log-btn"', html)
        self.assertIn('id="people-search-analysis"', html)

    def test_dating_urls_follow_base_path_and_exports_use_exact_types(self):
        """硬编码根路径会让带 SCRIPT_NAME 的部署请求落到错误 endpoint。"""
        app = create_app("/log-tool")
        app.config["TESTING"] = True

        html = app.test_client().get("/log-tool/").get_data(as_text=True)

        self.assertIn('data-dating-url="/log-tool/dating/analyze"', html)
        self.assertIn('/log-tool/static/js/workbench-dating.js', html)
        source = self.dating_source()
        self.assertIn("root.dataset.datingUrl", source)
        self.assertIn('"dating_analysis_report"', source)
        self.assertIn('"dating_analysis_json"', source)
        self.assertNotIn("fetch('/dating/analyze'", html)
        self.assertNotIn('fetch("/dating/analyze"', html)

    def test_dating_javascript_is_independent_and_uses_safe_dom_writes(self):
        """Dating 数据不得覆盖 Filter/People，也不得作为 HTML 执行。"""
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('/static/js/workbench-dating.js', html)
        dating_script = self.dating_source()

        for contract in (
            "var latestDatingAnalysis = null",
            "var latestDatingReport = ''",
            "function analyzeDatingLog()",
            "function setDatingLoading(isLoading)",
            "function renderDatingAnalysis(data)",
            "function renderDatingSummary(summary)",
            "function renderDatingLifecycle(taskSnapshot)",
            "function renderDatingResult(taskSnapshot)",
            "function renderDatingCalls(calls)",
            "function renderDatingFields(fields)",
            "function renderDatingChecks(checks)",
            "function appendDatingText(parent, value)",
            "document.createTextNode",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, dating_script)

        self.assertNotIn("innerHTML", dating_script)
        self.assertNotIn("people-search-report", dating_script)
        self.assertNotIn("resultRawText =", dating_script)

    def test_dating_mode_maps_all_workbench_tabs(self):
        """Dating 适配器必须注册五个标准 panel，并直接消费完整任务快照。"""
        source = self.dating_source()
        self.assertIn("registerAnalysisMode('dating'", source)
        for contract in (
            "renderDatingSummary", "renderDatingCalls", "renderDatingLifecycle",
            "renderDatingResult", "renderDatingFields", "renderDatingChecks",
            "taskSnapshot.status_samples", "taskSnapshot.result_payload",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, source)
        self.assertNotIn("aggregatePoll", source)

        html = self.client.get("/").get_data(as_text=True)
        for marker in (
            'id="dating-overview"',
            'id="dating-interfaces"',
            'id="dating-timeline"',
            'id="dating-result"',
            'id="dating-checks"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_dating_states_filters_and_line_locator_are_accessible(self):
        """状态不能只靠颜色，字段与证据必须可筛选并回到原日志。"""
        html = self.client.get("/").get_data(as_text=True)
        dating_script = self.dating_source()

        for presence in (
            "ALL",
            "PRESENT",
            "NULL",
            "EMPTY_STRING",
            "EMPTY_ARRAY",
            "EMPTY_OBJECT",
            "MISSING",
            "UNKNOWN_SCHEMA_FIELD",
        ):
            self.assertIn(f'value="{presence}"', html)
        for contract in (
            'id="dating-state" role="status" aria-live="polite"',
            "正在解析接口和结果字段…",
            "EMPTY_LOG",
            "LOG_TOO_LARGE",
            "UNSUPPORTED_LOG",
            "MULTIPLE_TASKS_FOUND",
            "TASK_NOT_FOUND",
            "ANALYZER_DISABLED",
            "ANALYSIS_INTERNAL_ERROR",
            "api.focusLogLines",
            "function renderDatingFieldTree(fields)",
            "parent_path",
            ":focus-visible",
            "prefers-reduced-motion: reduce",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, html if contract.startswith('id="dating-state"') or contract.endswith(":focus-visible") or contract == "prefers-reduced-motion: reduce" else dating_script)

        self.assertIn('id="copy-dating-report-btn"', html)
        self.assertIn('id="copy-dating-report-btn" type="button" disabled', html)
        self.assertIn('id="export-dating-report-btn" type="button" disabled', html)
        self.assertIn('id="export-dating-json-btn" type="button" disabled', html)

    def test_success_renderer_replaces_loading_state(self):
        """成功响应必须结束 loading 文案，避免同时显示“完成”和“分析中”。"""
        dating_script = self.dating_source()

        self.assertIn("state.className = 'dating-state success'", dating_script)
        self.assertIn("state.textContent = '分析完成：'", dating_script)

    def test_schema_specific_result_views_preserve_documented_facts(self):
        """已知 Schema 必须使用事实视图，未知 Schema 才只展示通用字段。"""
        dating_script = self.dating_source()

        self.assert_contains_contracts(dating_script, (
            "function sortDatingRolesByRank(roles)",
            "function renderDatingReplyResult(resultPayload)",
            "function renderDatingReplyRole(role)",
            "role.role_id",
            "role.role_name",
            "role.selection_rule_id",
            "role.selection_reasons",
            "role.coach_note",
            "role.replies",
            "role.top_pick",
            "role.alternatives",
            "reply.reply_id",
            "reply.text",
            "reply.is_top_pick",
            "function renderDatingAnalysisResult(resultPayload)",
            "overview.insight_title",
            "overview.insight_summary",
            "overview.next_steps",
            "overview.dashboard",
            "signals.positive_signals",
            "signals.watch_signals",
            "signals.risk_signals",
            "events.turning_points",
            "events.hidden_meanings",
            "events.did_well",
            "events.could_improve",
            "item.evidence_message_ids",
            "UNKNOWN_SCHEMA：仅提供通用字段树和字段索引。",
        ))

        self.assertNotIn("appendDatingText(pre, section.value)", dating_script)

    def test_collapsed_dating_details_materialize_once_on_first_open(self):
        """首屏不得创建折叠字段树、调用行或每个调用的 JSON 详情。"""
        dating_script = self.dating_source()

        self.assert_contains_contracts(dating_script, (
            "var datingFieldTreeMaterialized = false",
            "var datingCallsMaterialized = false",
            "function setupDatingLazySections(taskSnapshot, calls)",
            "function materializeDatingFieldTreeOnce()",
            "function materializeDatingCallsOnce()",
            "fieldTreeDetails.addEventListener('toggle'",
            "fieldTreeDetails.addEventListener('toggle'",
            "var detailMaterialized = false",
            "function openDatingCallDrawer(call, putAssetMap, trigger)",
            "api.openInterfaceDrawer",
        ))

        render_start = dating_script.index("function renderDatingAnalysis(data)")
        render_end = dating_script.index("function renderDatingSummary(summary)")
        initial_renderer = dating_script[render_start:render_end]
        self.assertIn(
            "setupDatingLazySections(taskSnapshot, data.calls || [])",
            initial_renderer,
        )
        self.assertNotIn("renderDatingFieldTree(", initial_renderer)
        self.assertIn("renderDatingCalls(", initial_renderer)

        result_start = dating_script.index("function renderDatingResult(taskSnapshot)")
        result_end = dating_script.index("function createDatingPresence(field)")
        self.assertNotIn(
            "renderDatingFieldTree(", dating_script[result_start:result_end]
        )

    def test_put_assets_are_mapped_to_interface_calls_and_terminal_is_explicit(self):
        """PUT 行必须可追溯 asset，未完成任务必须与 verdict 分开提示。"""
        dating_script = self.dating_source()

        self.assert_contains_contracts(dating_script, (
            "function buildDatingPutAssetMap(taskSnapshot)",
            "asset.put_call_id",
            "putAssetMap[call.call_id]",
            "function datingCallReference(call, putAssetMap)",
            "lifecycle.terminal === false",
            "任务未到终态或日志截断",
        ))

    def test_empty_string_is_distinct_from_null_and_unavailable(self):
        """业务空字符串必须显示其 presence，不能与 undefined/null 混淆。"""
        dating_script = self.dating_source()

        self.assertIn("value === '' ? '空字符串'", dating_script)
        self.assertIn("if (value === null) return 'null'", dating_script)
        self.assertIn("if (value === undefined) return '—'", dating_script)
        self.assertNotIn("value === undefined || value === '' ? '—'", dating_script)


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
            os.environ.pop("DATING_STRUCTURED_MAX_LOG_BYTES", None)
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

    def test_canonical_max_log_env_precedes_supported_alias(self):
        """PRD canonical 优先；未设置 canonical 时旧 alias 仍兼容。"""
        with patch.dict(
            os.environ,
            {
                "DATING_STRUCTURED_MAX_LOG_BYTES": "2048",
                "DATING_STRUCTURED_MAX_BYTES": "1024",
            },
            clear=True,
        ):
            canonical_app = create_app()
        with patch.dict(
            os.environ,
            {"DATING_STRUCTURED_MAX_BYTES": "3072"},
            clear=True,
        ):
            alias_app = create_app()

        self.assertEqual(
            canonical_app.config["DATING_STRUCTURED_MAX_BYTES"], 2048
        )
        self.assertEqual(
            alias_app.config["DATING_STRUCTURED_MAX_BYTES"], 3072
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

    def test_request_over_flask_body_limit_returns_dating_json_error(self):
        """>25 MiB 请求也必须由 Dating 合同返回 JSON，不能落到 Flask HTML。"""
        response = self.client.post(
            "/dating/analyze",
            json={"log_text": "x" * (26 * 1024 * 1024)},
        )

        self.assertEqual(response.status_code, 413)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json()["error_code"], "LOG_TOO_LARGE")

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
                self.assertEqual(len(SUCCESS_KEYS), 16)
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

    def test_dating_ordering_does_not_change_people_response_bytes(self):
        """Dating 固定顺序必须局部生效，People 继续使用 Flask 原有键排序。"""
        people_fixture = (
            Path(__file__).parent
            / "fixtures"
            / "people_search"
            / "f01_public_figure_local_hit.log"
        ).read_text(encoding="utf-8")

        response = self.client.post(
            "/people-search/analyze", json={"log_text": people_fixture}
        )
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(body.startswith('{"code":0,"data":'))
        self.assertGreater(
            body.rfind('"message":"ok"'), body.find('"data":')
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
        with self.assertLogs(self.app.logger, level="ERROR") as logs:
            with patch(
                "dating_log_analyzer.analyze_dating_log",
                side_effect=RuntimeError("private stack detail"),
            ):
                response = self.client.post(
                    "/dating/analyze",
                    json={"log_text": "recognized by stub"},
                )

        self.assert_error(response, 500, "ANALYSIS_INTERNAL_ERROR")
        self.assertNotIn("private stack detail", response.get_data(as_text=True))
        self.assertTrue(
            any("Dating 结构化分析发生未预期异常" in line for line in logs.output)
        )


if __name__ == "__main__":
    unittest.main()
