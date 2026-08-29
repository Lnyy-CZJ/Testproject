"""Dating 日志确定性规则框架与边界回归测试。"""

from copy import deepcopy
from pathlib import Path
import unittest

from dating_log_analyzer import analyze_dating_log, build_task_snapshot
from dating_log_rules import (
    CHECK_OUTCOMES,
    RULE_IDS,
    _check,
    compute_dating_verdict,
    run_dating_checks,
)
from gateway_log_parser import parse_interface_log


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"
EXPECTED_RULE_IDS = (
    "PARSE-001",
    "PAIR-001",
    "HTTP-001",
    "GATEWAY-001",
    "SUBRESP-001",
    "TRACE-001",
    "UPLOAD-001",
    "UPLOAD-002",
    "TASK-001",
    "TASK-002",
    "TASK-003",
    "TASK-004",
    "TASK-005",
    "TASK-006",
    "TASK-007",
    "TASK-008",
    "TASK-009",
    "TASK-010",
    "RESULT-001",
    "RESULT-002",
    "RESULT-003",
    "RESULT-004",
    "RESULT-005",
    "RESULT-006",
)


def _load_analysis(name: str = "reply_generation_multi_image_success.log") -> dict:
    """通过公共 analyzer 入口生成规则输入，不复制生产聚合逻辑。"""
    log_text = (FIXTURE_DIR / name).read_text(encoding="utf-8")
    return analyze_dating_log(log_text)


def _load_unfinished_reply_analysis() -> dict:
    """保留首个 processing Poll，构造真实非终态且无 Result 的日志。"""
    log_text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
        encoding="utf-8"
    )
    parsed = parse_interface_log(log_text)
    first_processing = next(
        call
        for call in parsed["calls"]
        if call.get("method_name") == "GetTask"
        and (call.get("response") or {}).get("data", {}).get("status")
        == "processing"
    )
    line_end = first_processing["response"]["line_end"]
    truncated = "\n".join(log_text.splitlines()[:line_end]) + "\n"
    return analyze_dating_log(truncated)


def _rebuild_task_snapshot(analysis: dict) -> dict:
    """在变异 calls 后复用生产聚合器，确保 Result 原始语义仍由 Task 5 提供。"""
    old_snapshot = analysis["task_snapshot"]
    snapshot, warnings = build_task_snapshot(
        analysis["calls"],
        old_snapshot["input_assets"],
        old_snapshot["task_id"],
    )
    analysis["task_snapshot"] = snapshot
    analysis["parse_warnings"].extend(warnings)
    return analysis


def _check_by_id(checks: list[dict], rule_id: str) -> dict:
    """按稳定规则 ID 取检查项，使断言不依赖列表下标。"""
    return next(check for check in checks if check["rule_id"] == rule_id)


def _call_by_id(analysis: dict, call_id: str) -> dict:
    """从 analyzer 保留的调用链中按 ID 获取真实证据块。"""
    return next(call for call in analysis["calls"] if call["call_id"] == call_id)


def _assert_evidence_shape(testcase: unittest.TestCase, check: dict) -> None:
    """FAIL/WARN 必须指向统一的 block 级证据形状。"""
    testcase.assertTrue(check["evidence"])
    required = {
        "method",
        "json_path",
        "value",
        "line_start",
        "line_end",
        "location_precision",
    }
    for evidence in check["evidence"]:
        testcase.assertEqual(set(evidence), required)
        testcase.assertEqual(evidence["location_precision"], "block")


class DatingRuleFrameworkTest(unittest.TestCase):
    """锁定规则顺序、结果形状以及证据构造器的不变量。"""

    def test_every_check_has_stable_contract(self):
        checks = run_dating_checks(_load_analysis())
        required = {
            "rule_id",
            "priority",
            "title",
            "outcome",
            "actual",
            "expected",
            "evidence",
        }
        self.assertTrue(checks)
        for check in checks:
            self.assertEqual(set(check), required)
            self.assertIn(check["outcome"], CHECK_OUTCOMES)
            if check["outcome"] in {"FAIL", "WARN"}:
                self.assertTrue(check["evidence"])

    def test_rule_order_is_exact_and_stable(self):
        checks = run_dating_checks(_load_analysis())
        self.assertEqual(RULE_IDS, EXPECTED_RULE_IDS)
        self.assertEqual(tuple(item["rule_id"] for item in checks), EXPECTED_RULE_IDS)

    def test_unavailable_trace_evidence_returns_unknown(self):
        analysis = _load_analysis()
        analysis["summary"]["trace_chain"] = None
        trace_check = _check_by_id(run_dating_checks(analysis), "TRACE-001")
        self.assertEqual(trace_check["outcome"], "UNKNOWN")
        self.assertEqual(trace_check["evidence"], [])

    def test_check_rejects_invalid_outcome_and_unsubstantiated_findings(self):
        with self.assertRaisesRegex(ValueError, "unsupported check outcome"):
            _check("TEST-001", "P0", "测试", "BROKEN", None, None)
        for outcome in ("FAIL", "WARN"):
            with self.subTest(outcome=outcome):
                with self.assertRaisesRegex(ValueError, "without evidence"):
                    _check("TEST-001", "P0", "测试", outcome, None, None)

    def test_check_rejects_structurally_invalid_finding_evidence(self):
        base = {
            "method": "GetTask",
            "json_path": "response.data.status",
            "value": "failed",
            "line_start": 10,
            "line_end": 12,
            "location_precision": "block",
        }
        invalid_entries = [
            {},
            {**base, "method": ""},
            {key: value for key, value in base.items() if key != "json_path"},
            {key: value for key, value in base.items() if key != "value"},
            {**base, "line_start": 0},
            {**base, "line_start": 13},
            {**base, "line_end": True},
            {**base, "location_precision": "field"},
        ]

        for outcome in ("FAIL", "WARN"):
            for entry in invalid_entries:
                with self.subTest(outcome=outcome, evidence=entry):
                    with self.assertRaisesRegex(ValueError, "without evidence"):
                        _check(
                            "TEST-001",
                            "P0",
                            "测试",
                            outcome,
                            None,
                            None,
                            [entry],
                        )

    def test_check_accepts_path_and_call_level_evidence_contracts(self):
        path_evidence = {
            "method": "GetTask",
            "json_path": "response.data.error",
            # null 仍是已定位的真实值，必须与缺少 value 键区分。
            "value": None,
            "line_start": 10,
            "line_end": 12,
            "location_precision": "block",
        }
        call_evidence = {
            "method": "GetTask",
            "call_id": "call_7",
            "line_start": 10,
            "line_end": 12,
            "location_precision": "block",
        }

        for entry in (path_evidence, call_evidence):
            with self.subTest(evidence=entry):
                check = _check(
                    "TEST-001", "P0", "测试", "FAIL", None, None, [entry]
                )
                self.assertEqual(check["evidence"], [entry])

    def test_verdict_priority_is_deterministic(self):
        def item(priority: str, outcome: str) -> dict:
            evidence = None
            if outcome in {"FAIL", "WARN"}:
                evidence = [
                    {
                        "method": "TestMethod",
                        "json_path": "response.data.value",
                        "value": outcome,
                        "line_start": 1,
                        "line_end": 1,
                        "location_precision": "block",
                    }
                ]
            return _check(
                "TEST-001", priority, "测试", outcome, None, None, evidence
            )

        self.assertEqual(CHECK_OUTCOMES, {"PASS", "FAIL", "WARN", "UNKNOWN", "NA"})
        self.assertEqual(compute_dating_verdict([item("P0", "PASS")]), "NO_ISSUES")
        self.assertEqual(
            compute_dating_verdict([item("P0", "UNKNOWN")]),
            "INCOMPLETE_LOG",
        )
        self.assertEqual(
            compute_dating_verdict([item("P2", "UNKNOWN")]),
            "NO_ISSUES",
        )
        self.assertEqual(
            compute_dating_verdict([item("P0", "UNKNOWN"), item("P2", "WARN")]),
            "WARNINGS_FOUND",
        )
        self.assertEqual(
            compute_dating_verdict([item("P2", "WARN"), item("P0", "FAIL")]),
            "ISSUES_FOUND",
        )


class GenericAndUploadRuleTest(unittest.TestCase):
    """覆盖解析、三层传输、追踪与任务使用资源的确定性边界。"""

    def test_reply_and_analysis_golden_common_rules_pass(self):
        for fixture_name in (
            "reply_generation_multi_image_success.log",
            "relationship_analysis_multi_image_success.log",
        ):
            with self.subTest(fixture=fixture_name):
                checks = run_dating_checks(_load_analysis(fixture_name))
                for rule_id in (
                    "PARSE-001",
                    "PAIR-001",
                    "HTTP-001",
                    "GATEWAY-001",
                    "SUBRESP-001",
                    "TRACE-001",
                    "UPLOAD-001",
                    "UPLOAD-002",
                ):
                    self.assertEqual(_check_by_id(checks, rule_id)["outcome"], "PASS")

    def test_malformed_json_warning_fails_parse_rule_with_real_lines(self):
        analysis = _load_analysis()
        warning = {
            "code": "MALFORMED_JSON_BLOCK",
            "message": "JSON block truncated",
            "line_start": 34,
            "line_end": 40,
        }
        analysis["parse_warnings"].append(warning)
        analysis["calls"][0]["warnings"].append(warning)

        check = _check_by_id(run_dating_checks(analysis), "PARSE-001")

        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)
        self.assertEqual(check["evidence"][0]["line_start"], 34)

    def test_recoverable_parser_noise_warns_when_call_remains_parsed(self):
        analysis = _load_analysis()
        warning = {
            "code": "RESPONSE_ELAPSED_MS_INVALID",
            "message": "elapsed_ms is malformed but body is available",
            "line_start": 34,
            "line_end": 61,
        }
        analysis["parse_warnings"].append(warning)
        analysis["calls"][0]["warnings"].append(warning)

        check = _check_by_id(run_dating_checks(analysis), "PARSE-001")

        self.assertEqual(check["outcome"], "WARN")
        _assert_evidence_shape(self, check)

    def test_fatal_headers_parse_error_wins_over_invalid_elapsed_warning(self):
        log_text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
        log_text = log_text.replace("elapsed_ms=1489.23", "elapsed_ms=1..2", 1)
        headers_start = log_text.index("headers={")
        body_start = log_text.index("\nbody=", headers_start)
        log_text = log_text[:headers_start] + "headers=[]" + log_text[body_start:]
        analysis = analyze_dating_log(log_text)
        first_call = analysis["calls"][0]
        warning_codes = {warning["code"] for warning in first_call["warnings"]}

        check = _check_by_id(run_dating_checks(analysis), "PARSE-001")

        self.assertEqual(first_call["parse_status"], "PARSE_ERROR")
        self.assertIn("GATEWAY_RESPONSE_HEADERS_TYPE_ERROR", warning_codes)
        self.assertIn("RESPONSE_ELAPSED_MS_INVALID", warning_codes)
        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)

    def test_missing_gateway_response_fails_pairing(self):
        analysis = _load_analysis()
        analysis["calls"][0]["response"] = None

        check = _check_by_id(run_dating_checks(analysis), "PAIR-001")

        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)

    def test_put_http_failure_is_not_confused_with_gateway_status(self):
        analysis = _load_analysis()
        put_call = next(
            call
            for call in analysis["calls"]
            if call["transport"] == "object_storage_put"
        )
        put_call["response"]["http_status"] = 500

        checks = run_dating_checks(analysis)
        http_check = _check_by_id(checks, "HTTP-001")
        gateway_check = _check_by_id(checks, "GATEWAY-001")

        self.assertEqual(http_check["outcome"], "FAIL")
        _assert_evidence_shape(self, http_check)
        self.assertEqual(gateway_check["outcome"], "PASS")

    def test_gateway_and_subresponse_layers_fail_independently(self):
        for key, value, rule_id in (
            ("gateway", {"code": 500, "request_id": "req", "trace_id": "trace"}, "GATEWAY-001"),
            ("sub_response", {"success": False, "code": 9}, "SUBRESP-001"),
        ):
            with self.subTest(rule_id=rule_id):
                analysis = _load_analysis()
                analysis["calls"][0]["response"][key] = value
                check = _check_by_id(run_dating_checks(analysis), rule_id)
                self.assertEqual(check["outcome"], "FAIL")
                _assert_evidence_shape(self, check)

    def test_gateway_and_subresponse_codes_require_exact_integer_zero(self):
        original_log = (
            FIXTURE_DIR / "reply_generation_multi_image_success.log"
        ).read_text(encoding="utf-8")
        for layer, rule_id in (
            ("gateway", "GATEWAY-001"),
            ("sub_response", "SUBRESP-001"),
        ):
            for invalid_code, json_literal in (
                (False, "false"),
                (None, "null"),
                (0.0, "0.0"),
            ):
                with self.subTest(layer=layer, invalid_code=invalid_code):
                    if layer == "gateway":
                        mutated_log = original_log.replace(
                            'body={\n  "code": 0,',
                            f'body={{\n  "code": {json_literal},',
                            1,
                        )
                    else:
                        mutated_log = original_log.replace(
                            '      "success": true,\n      "code": 0,',
                            f'      "success": true,\n      "code": {json_literal},',
                            1,
                        )
                    analysis = analyze_dating_log(mutated_log)

                    check = _check_by_id(run_dating_checks(analysis), rule_id)

                    self.assertEqual(check["outcome"], "FAIL")
                    _assert_evidence_shape(self, check)

        valid_checks = run_dating_checks(_load_analysis())
        self.assertEqual(
            _check_by_id(valid_checks, "GATEWAY-001")["outcome"], "PASS"
        )
        self.assertEqual(
            _check_by_id(valid_checks, "SUBRESP-001")["outcome"], "PASS"
        )

    def test_missing_trace_id_warns_but_missing_trace_source_is_unknown(self):
        analysis = _load_analysis()
        analysis["calls"][0]["response"]["gateway"]["request_id"] = None
        check = _check_by_id(run_dating_checks(analysis), "TRACE-001")
        self.assertEqual(check["outcome"], "WARN")
        _assert_evidence_shape(self, check)

        unavailable = _load_analysis()
        unavailable["summary"]["trace_chain"] = None
        unknown = _check_by_id(run_dating_checks(unavailable), "TRACE-001")
        self.assertEqual(unknown["outcome"], "UNKNOWN")

    def test_used_asset_without_complete_fails_upload_chain(self):
        analysis = _load_analysis()
        asset = analysis["task_snapshot"]["input_assets"][0]
        complete_call_id = asset["complete_call_id"]
        analysis["calls"] = [
            call for call in analysis["calls"] if call["call_id"] != complete_call_id
        ]
        asset["complete_call_id"] = None
        asset["complete_status"] = None
        asset["upload_state"] = "prepare_only"

        check = _check_by_id(run_dating_checks(analysis), "UPLOAD-001")

        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)

    def test_prepare_complete_size_mismatch_warns(self):
        analysis = _load_analysis()
        asset = analysis["task_snapshot"]["input_assets"][0]
        complete_call = _call_by_id(analysis, asset["complete_call_id"])
        complete_call["response"]["data"]["size_bytes"] += 1

        check = _check_by_id(run_dating_checks(analysis), "UPLOAD-002")

        self.assertEqual(check["outcome"], "WARN")
        _assert_evidence_shape(self, check)

    def test_upload_rules_are_na_when_task_references_no_assets(self):
        analysis = _load_analysis()
        analysis["task_snapshot"]["input_assets"] = []
        checks = run_dating_checks(analysis)

        self.assertEqual(_check_by_id(checks, "UPLOAD-001")["outcome"], "NA")
        self.assertEqual(_check_by_id(checks, "UPLOAD-002")["outcome"], "NA")


class TaskLifecycleRuleTest(unittest.TestCase):
    """覆盖 TASK-001..010 的一致性、状态机、时间和停滞诊断。"""

    def test_golden_task_rules_have_exact_outcomes_and_warning_evidence(self):
        expected = {
            "TASK-001": "PASS",
            "TASK-002": "PASS",
            "TASK-003": "PASS",
            "TASK-004": "PASS",
            "TASK-005": "PASS",
            "TASK-006": "NA",
            "TASK-007": "PASS",
            "TASK-008": "PASS",
            "TASK-009": "WARN",
            "TASK-010": "WARN",
        }
        for fixture_name in (
            "reply_generation_multi_image_success.log",
            "relationship_analysis_multi_image_success.log",
        ):
            with self.subTest(fixture=fixture_name):
                checks = run_dating_checks(_load_analysis(fixture_name))
                self.assertEqual(
                    {
                        rule_id: _check_by_id(checks, rule_id)["outcome"]
                        for rule_id in expected
                    },
                    expected,
                )
                _assert_evidence_shape(self, _check_by_id(checks, "TASK-009"))
                stall = _check_by_id(checks, "TASK-010")
                _assert_evidence_shape(self, stall)
                self.assertGreaterEqual(stall["actual"]["stalled_poll_count"], 5)
                self.assertEqual(compute_dating_verdict(checks), "WARNINGS_FOUND")

    def test_task_id_and_method_type_mutations_fail_independently(self):
        analysis = _load_analysis()
        result_call = _call_by_id(
            analysis, analysis["task_snapshot"]["result_call_id"]
        )
        result_call["response"]["data"]["task_id"] = "task_other"
        task_id_check = _check_by_id(run_dating_checks(analysis), "TASK-001")
        self.assertEqual(task_id_check["outcome"], "FAIL")
        _assert_evidence_shape(self, task_id_check)

        analysis = _load_analysis()
        create_call = _call_by_id(
            analysis, analysis["task_snapshot"]["create_call_id"]
        )
        create_call["method_name"] = "CreateAnalysisTask"
        type_check = _check_by_id(run_dating_checks(analysis), "TASK-002")
        self.assertEqual(type_check["outcome"], "FAIL")
        _assert_evidence_shape(self, type_check)

    def test_terminal_status_rollback_fails(self):
        analysis = _load_analysis()
        samples = analysis["task_snapshot"]["status_samples"]
        samples[2]["status"] = "succeeded"
        call = _call_by_id(analysis, samples[2]["call_id"])
        call["response"]["data"]["status"] = "succeeded"

        check = _check_by_id(run_dating_checks(analysis), "TASK-003")

        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)
        self.assertIn("succeeded -> processing", check["actual"])
        self.assertEqual(check["evidence"][0]["value"], "processing")

    def test_proven_illegal_transition_wins_when_another_status_is_unknown(self):
        analysis = _load_analysis()
        samples = analysis["task_snapshot"]["status_samples"]

        # 一个未知枚举只能让相邻两段无法证明；后续独立存在的
        # succeeded -> processing 仍是已证实的非法转换，必须优先 FAIL。
        samples[1]["status"] = "waiting_external"
        _call_by_id(analysis, samples[1]["call_id"])["response"]["data"][
            "status"
        ] = "waiting_external"
        samples[2]["status"] = "succeeded"
        _call_by_id(analysis, samples[2]["call_id"])["response"]["data"][
            "status"
        ] = "succeeded"

        check = _check_by_id(run_dating_checks(analysis), "TASK-003")

        self.assertEqual(check["outcome"], "FAIL")
        self.assertEqual(check["actual"], "succeeded -> processing")
        _assert_evidence_shape(self, check)
        self.assertEqual(check["evidence"][0]["value"], "processing")

    def test_progress_regression_and_incomplete_success_fail(self):
        analysis = _load_analysis()
        sample = analysis["task_snapshot"]["status_samples"][2]
        sample["progress_percent"] = 20
        _call_by_id(analysis, sample["call_id"])["response"]["data"][
            "progress_percent"
        ] = 20
        progress_check = _check_by_id(run_dating_checks(analysis), "TASK-004")
        self.assertEqual(progress_check["outcome"], "FAIL")
        _assert_evidence_shape(self, progress_check)

        analysis = _load_analysis()
        snapshot = analysis["task_snapshot"]
        snapshot["lifecycle"]["final_progress_percent"] = 95
        final_sample = snapshot["status_samples"][-1]
        final_sample["progress_percent"] = 95
        _call_by_id(analysis, final_sample["call_id"])["response"]["data"][
            "progress_percent"
        ] = 95
        success_check = _check_by_id(run_dating_checks(analysis), "TASK-005")
        self.assertEqual(success_check["outcome"], "FAIL")
        _assert_evidence_shape(self, success_check)

    def test_failed_task_without_locatable_error_fails(self):
        analysis = _load_analysis()
        snapshot = analysis["task_snapshot"]
        lifecycle = snapshot["lifecycle"]
        lifecycle.update(
            {
                "final_status": "failed",
                "final_phase": "failed",
                "error_code": "",
                "terminal": True,
            }
        )
        final_sample = snapshot["status_samples"][-1]
        final_sample.update({"status": "failed", "phase": "failed", "error_code": ""})
        final_call = _call_by_id(analysis, final_sample["call_id"])
        final_call["response"]["data"].update(
            {"status": "failed", "phase": "failed", "error_code": ""}
        )

        check = _check_by_id(run_dating_checks(analysis), "TASK-006")

        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)

    def test_invalid_time_order_and_missing_success_result_fail(self):
        analysis = _load_analysis()
        snapshot = analysis["task_snapshot"]
        result_call = _call_by_id(analysis, snapshot["result_call_id"])
        result_create_time = result_call["response"]["data"]["create_time"]
        final_sample = snapshot["status_samples"][-1]
        final_sample["completed_time"] = result_create_time - 1
        _call_by_id(analysis, final_sample["call_id"])["response"]["data"][
            "completed_time"
        ] = result_create_time - 1
        time_check = _check_by_id(run_dating_checks(analysis), "TASK-007")
        self.assertEqual(time_check["outcome"], "FAIL")
        _assert_evidence_shape(self, time_check)

        analysis = _load_analysis()
        snapshot = analysis["task_snapshot"]
        result_call_id = snapshot["result_call_id"]
        snapshot["result_call_id"] = None
        analysis["calls"] = [
            call for call in analysis["calls"] if call["call_id"] != result_call_id
        ]
        result_check = _check_by_id(run_dating_checks(analysis), "TASK-008")
        self.assertEqual(result_check["outcome"], "FAIL")
        _assert_evidence_shape(self, result_check)

    def test_unfinished_log_keeps_terminal_and_result_rules_unknown(self):
        analysis = _load_unfinished_reply_analysis()
        snapshot = analysis["task_snapshot"]
        self.assertFalse(snapshot["lifecycle"]["terminal"])
        self.assertIsNone(snapshot["result_call_id"])
        self.assertFalse(snapshot["result_payload_present"])

        checks = run_dating_checks(analysis)
        self.assertEqual(_check_by_id(checks, "TASK-007")["outcome"], "UNKNOWN")
        self.assertEqual(_check_by_id(checks, "TASK-008")["outcome"], "UNKNOWN")
        self.assertEqual(_check_by_id(checks, "TASK-009")["outcome"], "UNKNOWN")
        self.assertEqual(_check_by_id(checks, "TASK-010")["outcome"], "PASS")
        self.assertEqual(compute_dating_verdict(checks), "INCOMPLETE_LOG")

    def test_task_selection_errors_remain_incomplete_without_fallback(self):
        for selection_error in ("MULTIPLE_TASKS_FOUND", "TASK_NOT_FOUND"):
            with self.subTest(selection_error=selection_error):
                analysis = _load_analysis()
                analysis["selection_error"] = selection_error
                analysis["task_snapshot"] = None
                checks = run_dating_checks(analysis)
                for rule_id in ("TASK-001", "TASK-002", "TASK-007", "TASK-008"):
                    self.assertEqual(
                        _check_by_id(checks, rule_id)["outcome"], "UNKNOWN"
                    )
                self.assertEqual(compute_dating_verdict(checks), "INCOMPLETE_LOG")


class ResultRuleTest(unittest.TestCase):
    """覆盖 RESULT-001..006 的一致性、必填、空值和未知 Schema 语义。"""

    def test_golden_result_rules_all_pass_and_empty_health_is_diagnostic(self):
        expected_health = {
            "reply_generation_multi_image_success.log": {
                "null_count": 2,
                "empty_string_count": 1,
                "empty_array_count": 0,
                "empty_object_count": 0,
            },
            "relationship_analysis_multi_image_success.log": {
                "null_count": 3,
                "empty_string_count": 0,
                "empty_array_count": 4,
                "empty_object_count": 0,
            },
        }
        for fixture_name, health in expected_health.items():
            with self.subTest(fixture=fixture_name):
                checks = run_dating_checks(_load_analysis(fixture_name))
                for rule_id in (
                    "RESULT-001",
                    "RESULT-002",
                    "RESULT-003",
                    "RESULT-004",
                    "RESULT-005",
                    "RESULT-006",
                ):
                    self.assertEqual(_check_by_id(checks, rule_id)["outcome"], "PASS")
                self.assertEqual(_check_by_id(checks, "RESULT-005")["actual"], health)

    def test_result_task_schema_and_id_mutations_fail_with_evidence(self):
        mutations = (
            (
                "RESULT-001",
                lambda call: call["response"]["data"].__setitem__(
                    "task_id", "task_other"
                ),
            ),
            (
                "RESULT-002",
                lambda call: call["response"]["data"]["result"].__setitem__(
                    "schema_version", "dating.reply_generation.v2"
                ),
            ),
            (
                "RESULT-003",
                lambda call: call["response"]["data"].__setitem__("result_id", ""),
            ),
        )
        for rule_id, mutate in mutations:
            with self.subTest(rule_id=rule_id):
                analysis = _load_analysis()
                result_call = _call_by_id(
                    analysis, analysis["task_snapshot"]["result_call_id"]
                )
                mutate(result_call)
                check = _check_by_id(run_dating_checks(analysis), rule_id)
                self.assertEqual(check["outcome"], "FAIL")
                _assert_evidence_shape(self, check)

    def test_known_schema_missing_required_path_fails(self):
        analysis = _load_analysis()
        field = next(
            field
            for field in analysis["task_snapshot"]["result_fields"]
            if field["path"] == "result.context"
        )
        field["presence"] = "MISSING"
        field["value"] = None

        check = _check_by_id(run_dating_checks(analysis), "RESULT-004")

        self.assertEqual(check["outcome"], "FAIL")
        _assert_evidence_shape(self, check)
        self.assertIn("result.context", check["actual"])

    def test_required_field_truncated_by_absolute_cap_is_unknown_not_pass(self):
        analysis = _load_analysis()
        snapshot = analysis["task_snapshot"]
        snapshot["result_fields"] = [
            field
            for field in snapshot["result_fields"]
            if field["path"] != "result.context"
        ]
        snapshot["warnings"].append(
            {
                "code": "MAX_FIELD_COUNT_REACHED",
                "message": "required node omitted at absolute cap",
                "omitted_required_paths": ["result.context"],
            }
        )

        check = _check_by_id(run_dating_checks(analysis), "RESULT-004")

        self.assertEqual(check["outcome"], "UNKNOWN")

    def test_unknown_field_is_preserved_and_does_not_fail(self):
        analysis = _load_analysis()
        result_fields = analysis["task_snapshot"]["result_fields"]
        source = deepcopy(result_fields[0]["source"])
        result_fields.append(
            {
                "path": "result.future_extension",
                "parent_path": "result",
                "key": "future_extension",
                "array_index": None,
                "label": "future_extension",
                "value": {"enabled": True},
                "value_type": "object",
                "presence": "PRESENT",
                "schema_known": False,
                "value_truncated": False,
                "source": source,
            }
        )
        analysis["task_snapshot"]["field_health"]["unknown_schema_field_count"] = 1

        check = _check_by_id(run_dating_checks(analysis), "RESULT-006")

        self.assertEqual(check["outcome"], "PASS")
        self.assertEqual(check["actual"]["unknown_field_paths"], ["result.future_extension"])

    def test_unknown_schema_keeps_generic_health_and_schema_rules_na(self):
        analysis = _load_analysis()
        result_call = _call_by_id(
            analysis, analysis["task_snapshot"]["result_call_id"]
        )
        unknown_version = "dating.reply_generation.v99"
        result_call["response"]["data"]["schema_version"] = unknown_version
        result_call["response"]["data"]["result"]["schema_version"] = unknown_version
        _rebuild_task_snapshot(analysis)

        checks = run_dating_checks(analysis)

        self.assertEqual(analysis["task_snapshot"]["schema_status"], "UNKNOWN_SCHEMA")
        self.assertTrue(analysis["task_snapshot"]["result_fields"])
        self.assertEqual(_check_by_id(checks, "RESULT-002")["outcome"], "PASS")
        self.assertEqual(_check_by_id(checks, "RESULT-004")["outcome"], "NA")
        self.assertEqual(_check_by_id(checks, "RESULT-005")["outcome"], "PASS")
        self.assertEqual(_check_by_id(checks, "RESULT-006")["outcome"], "NA")
        self.assertIn(
            "UNKNOWN_SCHEMA_VERSION",
            [warning["code"] for warning in analysis["parse_warnings"]],
        )

    def test_success_result_missing_payload_emits_required_missing_failure(self):
        analysis = _load_analysis()
        result_call = _call_by_id(
            analysis, analysis["task_snapshot"]["result_call_id"]
        )
        result_call["response"]["data"].pop("result")
        _rebuild_task_snapshot(analysis)
        snapshot = analysis["task_snapshot"]

        self.assertFalse(snapshot["result_payload_present"])
        self.assertTrue(
            any(field["presence"] == "MISSING" for field in snapshot["result_fields"])
        )
        checks = run_dating_checks(analysis)
        required_check = _check_by_id(checks, "RESULT-004")
        self.assertEqual(required_check["outcome"], "FAIL")
        _assert_evidence_shape(self, required_check)
        self.assertEqual(_check_by_id(checks, "RESULT-005")["outcome"], "PASS")

    def test_raw_list_scalar_and_null_results_are_not_projected_or_crashed(self):
        for payload in (["raw"], 7, None):
            with self.subTest(payload=payload):
                analysis = _load_analysis()
                result_call = _call_by_id(
                    analysis, analysis["task_snapshot"]["result_call_id"]
                )
                result_call["response"]["data"]["result"] = payload
                _rebuild_task_snapshot(analysis)
                snapshot = analysis["task_snapshot"]
                self.assertIs(snapshot["result_payload"], payload)

                checks = run_dating_checks(analysis)
                self.assertEqual(
                    _check_by_id(checks, "RESULT-002")["outcome"], "UNKNOWN"
                )
                self.assertEqual(
                    _check_by_id(checks, "RESULT-004")["outcome"], "FAIL"
                )
                self.assertEqual(_check_by_id(checks, "RESULT-005")["outcome"], "PASS")

    def test_unfinished_log_leaves_all_result_rules_unknown(self):
        checks = run_dating_checks(_load_unfinished_reply_analysis())
        for rule_id in (
            "RESULT-001",
            "RESULT-002",
            "RESULT-003",
            "RESULT-004",
            "RESULT-005",
            "RESULT-006",
        ):
            self.assertEqual(_check_by_id(checks, rule_id)["outcome"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
