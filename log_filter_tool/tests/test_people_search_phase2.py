"""阶段 2 测试：规则审计、成本核对和确定性报告。

覆盖范围：
1. 10 份夹具的 verdict 和 expected_rules 回归（完成条件：正常样本无确定性误报，历史 Bug 样本命中对应规则）；
2. 确定性 Markdown 报告结构与内容验证；
3. Evidence Packet 构建与脱敏；
4. 真实日志规则审计。
"""
import json
import unittest
from pathlib import Path

from people_search_analyzer import analyze_log_file, analyze_people_search_log
from people_search_rules import (
    ANALYZER_VERSION,
    RULESET_VERSION,
    build_evidence_packet,
    redact_for_ai,
    render_rule_report,
    run_all_checks,
    _redact_dict_keys,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "people_search"
CONTRACTS_PATH = FIXTURE_DIR / "contracts.json"
REAL_LOG_DIR = Path(__file__).resolve().parents[1] / "peoplesearch_logs"

CONTRACTS = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))


def analyze_fixture(name):
    return analyze_log_file(FIXTURE_DIR / name)


class FixtureRuleRegressionTests(unittest.TestCase):
    """10 份夹具的 verdict 和 expected_rules 全部匹配。"""

    def test_all_fixtures_match_expected_verdict_and_rules(self):
        for fx in CONTRACTS["fixtures"]:
            with self.subTest(fixture=fx["name"]):
                result = analyze_fixture(fx["file"])
                self.assertTrue(result["supported"])
                self.assertIsNone(result["selection_error"])
                checks, verdict, warnings = run_all_checks(
                    result["snapshot"], list(result["parse_warnings"])
                )
                # verdict 匹配
                self.assertEqual(verdict, fx["expected_verdict"], fx["name"])
                # expected_rules 逐条匹配
                check_by_id = {c["rule_id"]: c for c in checks}
                for rule_id, expected_outcome in fx["expected_rules"].items():
                    self.assertIn(rule_id, check_by_id, f"{fx['name']}: {rule_id} 未生成")
                    self.assertEqual(
                        check_by_id[rule_id]["outcome"],
                        expected_outcome,
                        f"{fx['name']}: {rule_id} got {check_by_id[rule_id]['outcome']} expected {expected_outcome}",
                    )

    def test_normal_fixtures_have_no_false_positive_fail(self):
        """正常样本无确定性误报。"""
        normal_fixtures = [fx for fx in CONTRACTS["fixtures"] if fx["expected_verdict"] == "NORMAL"]
        for fx in normal_fixtures:
            with self.subTest(fixture=fx["name"]):
                result = analyze_fixture(fx["file"])
                checks, _verdict, _warnings = run_all_checks(
                    result["snapshot"], list(result["parse_warnings"])
                )
                fails = [c for c in checks if c["outcome"] == "FAIL"]
                self.assertEqual(fails, [], f"{fx['name']}: 不应有 FAIL，但发现 {[c['rule_id'] for c in fails]}")

    def test_bug_fixtures_hit_expected_rules(self):
        """历史 Bug 样本命中对应规则。"""
        bug_fixtures = [fx for fx in CONTRACTS["fixtures"] if fx["expected_verdict"] == "ISSUES_FOUND"]
        for fx in bug_fixtures:
            with self.subTest(fixture=fx["name"]):
                result = analyze_fixture(fx["file"])
                checks, verdict, _warnings = run_all_checks(
                    result["snapshot"], list(result["parse_warnings"])
                )
                self.assertEqual(verdict, "ISSUES_FOUND", fx["name"])
                expected_fails = {
                    rid: outcome
                    for rid, outcome in fx["expected_rules"].items()
                    if outcome == "FAIL"
                }
                actual_fails = {
                    c["rule_id"]: c["outcome"]
                    for c in checks
                    if c["outcome"] == "FAIL"
                }
                for rid in expected_fails:
                    self.assertIn(rid, actual_fails, f"{fx['name']}: 期望 {rid} FAIL")

    def test_f03_route_003_fail_with_evidence(self):
        result = analyze_fixture("f03_wiki_unique_but_pdl_called.log")
        checks, _v, _w = run_all_checks(result["snapshot"], [])
        route_003 = next(c for c in checks if c["rule_id"] == "ROUTE-003")
        self.assertEqual(route_003["outcome"], "FAIL")
        self.assertTrue(route_003["evidence"])
        ev = route_003["evidence"][0]
        self.assertEqual(ev["method"], "GetSearchTaskDebug")
        self.assertIn("usable_count", ev["json_path"])

    def test_f09_cost_001_fail_with_evidence(self):
        result = analyze_fixture("f09_cost_mismatch_unpriced.log")
        checks, _v, _w = run_all_checks(result["snapshot"], [])
        cost_001 = next(c for c in checks if c["rule_id"] == "COST-001")
        self.assertEqual(cost_001["outcome"], "FAIL")
        self.assertIn("≠", cost_001["actual"])

    def test_f10_state_002_and_stop_001_fail(self):
        result = analyze_fixture("f10_technical_failure_misclassified.log")
        checks, _v, _w = run_all_checks(result["snapshot"], [])
        state_002 = next(c for c in checks if c["rule_id"] == "STATE-002")
        stop_001 = next(c for c in checks if c["rule_id"] == "STOP-001")
        self.assertEqual(state_002["outcome"], "FAIL")
        self.assertEqual(stop_001["outcome"], "FAIL")

    def test_f08_face_001_pass_known_gap(self):
        result = analyze_fixture("f08_image_lens_vision_face_not_connected.log")
        checks, _v, _w = run_all_checks(result["snapshot"], [])
        face_001 = next(c for c in checks if c["rule_id"] == "FACE-001")
        self.assertEqual(face_001["outcome"], "PASS")

    def test_all_24_rules_have_results(self):
        """每份夹具生成的 checks 覆盖全部 24 条规则。"""
        result = analyze_fixture("f01_public_figure_local_hit.log")
        checks, _v, _w = run_all_checks(result["snapshot"], [])
        rule_ids = {c["rule_id"] for c in checks}
        expected_ids = {r["rule_id"] for r in CONTRACTS["rules"]}
        self.assertEqual(rule_ids, expected_ids)

    def test_rule_results_deterministic(self):
        """规则结果在多次运行中保持一致。"""
        for fx in CONTRACTS["fixtures"][:3]:
            with self.subTest(fixture=fx["name"]):
                text = (FIXTURE_DIR / fx["file"]).read_text(encoding="utf-8")
                first = json.dumps(
                    run_all_checks(analyze_people_search_log(text)["snapshot"], [])[0],
                    sort_keys=True, ensure_ascii=False,
                )
                second = json.dumps(
                    run_all_checks(analyze_people_search_log(text)["snapshot"], [])[0],
                    sort_keys=True, ensure_ascii=False,
                )
                self.assertEqual(first, second)


class ReportRenderingTests(unittest.TestCase):
    """确定性 Markdown 报告结构与内容验证。"""

    def test_report_has_all_required_sections(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        report = render_rule_report(result)
        required_sections = [
            "# People Insight 检索日志分析",
            "## 总体结论",
            "## 日志覆盖度",
            "## 实际执行链路",
            "## Provider与成本",
            "## 已确认正常",
            "## 已确认异常",
            "## 需要后端确认",
            "## 日志不足，无法判断",
        ]
        for section in required_sections:
            self.assertIn(section, report, f"缺少报告章节: {section}")

    def test_normal_report_has_no_fail_section_content(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        report = render_rule_report(result)
        # NORMAL 报告的"已确认异常"应为"（无）"
        self.assertIn("## 已确认异常\n\n（无）", report)

    def test_bug_report_contains_fail_details(self):
        result = analyze_fixture("f03_wiki_unique_but_pdl_called.log")
        report = render_rule_report(result)
        self.assertIn("ROUTE-003", report)
        self.assertIn("ISSUES_FOUND", report)

    def test_report_contains_coverage_table(self):
        result = analyze_fixture("f06_social_link_queue_dedupe.log")
        report = render_rule_report(result)
        self.assertIn("| 接口 | 覆盖 |", report)
        self.assertIn("CreateIntentTask", report)
        self.assertIn("GetSearchTaskDebug", report)

    def test_report_contains_timeline_table(self):
        result = analyze_fixture("f03_wiki_unique_but_pdl_called.log")
        report = render_rule_report(result)
        self.assertIn("| # | Provider | Operation |", report)
        self.assertIn("wiki_remote", report)
        self.assertIn("people_data_labs", report)

    def test_unsupported_log_report(self):
        result = analyze_people_search_log("some random log text\n")
        report = render_rule_report(result)
        self.assertIn("UNSUPPORTED_LOG", report)

    def test_multiple_tasks_report(self):
        combined = (FIXTURE_DIR / "f01_public_figure_local_hit.log").read_text(encoding="utf-8")
        combined += "\n" + (FIXTURE_DIR / "f06_social_link_queue_dedupe.log").read_text(encoding="utf-8")
        result = analyze_people_search_log(combined)
        report = render_rule_report(result)
        self.assertIn("MULTIPLE_TASKS_FOUND", report)

    def test_report_deterministic(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        first = render_rule_report(result)
        second = render_rule_report(result)
        self.assertEqual(first, second)


class EvidencePacketTests(unittest.TestCase):
    """Evidence Packet 构建与脱敏。"""

    def test_packet_top_level_fields(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        packet = build_evidence_packet(result)
        self.assertIsNotNone(packet)
        for field in ("analyzer_version", "task_summary", "coverage", "timeline",
                       "candidate_summary", "diagnosis_summary", "cost_summary",
                       "checks", "parse_warnings"):
            self.assertIn(field, packet)

    def test_packet_version(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        packet = build_evidence_packet(result)
        self.assertEqual(packet["analyzer_version"], ANALYZER_VERSION)
        self.assertEqual(packet["ruleset_version"], RULESET_VERSION)

    def test_packet_checks_contain_rule_results(self):
        result = analyze_fixture("f03_wiki_unique_but_pdl_called.log")
        packet = build_evidence_packet(result)
        rule_ids = {c["rule_id"] for c in packet["checks"]}
        self.assertIn("ROUTE-003", rule_ids)
        route_003 = next(c for c in packet["checks"] if c["rule_id"] == "ROUTE-003")
        self.assertEqual(route_003["outcome"], "FAIL")

    def test_packet_candidate_summary_max_20(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        packet = build_evidence_packet(result)
        self.assertLessEqual(len(packet["candidate_summary"]), 20)

    def test_packet_timeline_max_100(self):
        result = analyze_fixture("f01_public_figure_local_hit.log")
        packet = build_evidence_packet(result)
        self.assertLessEqual(len(packet["timeline"]), 100)

    def test_packet_unsupported_log_returns_none(self):
        result = analyze_people_search_log("random text\n")
        self.assertIsNone(build_evidence_packet(result))

    def test_redact_authorization_token(self):
        data = {"auth_token": "secret123", "comm": {"Authorization": "Bearer xxx"}}
        redacted = _redact_dict_keys(data)
        self.assertEqual(redacted["auth_token"], "***")
        self.assertEqual(redacted["comm"]["Authorization"], "***")

    def test_redact_preserves_email_and_phone(self):
        data = {"email": "user@example.com", "phone": "+8613800138000"}
        redacted = _redact_dict_keys(data)
        self.assertEqual(redacted["email"], "user@example.com")
        self.assertEqual(redacted["phone"], "+8613800138000")

    def test_redact_base64_data_url(self):
        data = {"photo": "data:image/jpeg;base64,/9j/4AAQ" + "A" * 600}
        redacted = _redact_dict_keys(data)
        self.assertEqual(redacted["photo"], "[binary omitted]")

    def test_packet_serializable_json(self):
        result = analyze_fixture("f06_social_link_queue_dedupe.log")
        packet = build_evidence_packet(result)
        serialized = json.dumps(packet, ensure_ascii=False)
        self.assertIsInstance(serialized, str)
        # 邮箱保留原值
        self.assertIn("carol@example.com", serialized)


class RealLogRuleTests(unittest.TestCase):
    """真实日志规则审计。"""

    @unittest.skipUnless(REAL_LOG_DIR.is_dir(), "peoplesearch_logs 目录不存在")
    def test_real_logs_produce_valid_checks(self):
        logs = sorted(REAL_LOG_DIR.glob("2026-08-11_*.log"))
        self.assertGreaterEqual(len(logs), 5)
        for path in logs:
            with self.subTest(log=path.name):
                result = analyze_log_file(path)
                self.assertTrue(result["supported"])
                self.assertIsNone(result["selection_error"])
                checks, verdict, warnings = run_all_checks(
                    result["snapshot"], list(result["parse_warnings"])
                )
                # 全部 24 条规则都有结果
                rule_ids = {c["rule_id"] for c in checks}
                expected_ids = {r["rule_id"] for r in CONTRACTS["rules"]}
                self.assertEqual(rule_ids, expected_ids, path.name)
                # 真实日志应正常或仅有 WARN
                self.assertIn(verdict, ("NORMAL", "NEEDS_CONFIRMATION", "ISSUES_FOUND"), path.name)
                # 无规则异常
                rule_errors = [w for w in warnings if w.get("code") == "RULE_ERROR"]
                self.assertEqual(rule_errors, [], path.name)

    @unittest.skipUnless(REAL_LOG_DIR.is_dir(), "peoplesearch_logs 目录不存在")
    def test_real_log_report_rendered(self):
        path = REAL_LOG_DIR / "2026-08-11_124606_Kervin_Lau.log"
        result = analyze_log_file(path)
        report = render_rule_report(result)
        self.assertIn("# People Insight 检索日志分析", report)
        self.assertIn("Kervin Lau", report)
        self.assertIn("## 实际执行链路", report)


if __name__ == "__main__":
    unittest.main()
