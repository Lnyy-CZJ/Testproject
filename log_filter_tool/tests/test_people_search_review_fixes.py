"""阶段 2~4 审查修复回归测试（2026-08-13）。

覆盖审查发现并修复的问题：
1. ROUTE-002 在 start_time 缺失（None）时不再抛异常导致 ROUTE-001~004 丢失。
2. Evidence Packet（AI 路径）checks 证据值按 json_path 提示脱敏。
3. Base64 脱敏不再误报普通长文本（需混合大小写+数字）。
4. 报告「已确认异常/需要后端确认/无法判断」章节包含证据引用。
5. 签名 URL 去除 query/fragment，普通 canonical social URL 保留。
6. LLM-001 按 timeline（start_time 升序）判断最后一次 LLM 调用。
7. CAND-004 检查 person_id/wikidata_id/canonical_url 全部稳定标识。
8. Evidence Packet §9.3：source_truncated、2000 字符文本上限、
   优先保留已选/高分候选与失败调用、social_url_decisions 字段。
9. limit_evidence_packet 同时标记 truncated 与 source_truncated。
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from people_search_ai import (  # noqa: E402
    AIConfig,
    limit_evidence_packet,
    summarize_with_ai,
)
from people_search_rules import (  # noqa: E402
    build_evidence_packet,
    redact_for_ai,
    redact_for_response,
    render_rule_report,
    run_all_checks,
)


def _base_snapshot(**overrides):
    snapshot = {
        "task": {"task_id": "t1", "full_name": "Test Person", "clue_types": ["FULL_NAME"],
                 "final_status": "SUCCEEDED", "candidate_count": 0,
                 "top_confidence_score": None, "query_id": "q1"},
        "coverage": {"debug": True, "get_task": True},
        "timeline": [],
        "candidates": [],
        "candidate_details": [],
        "diagnosis": {"final_status": "SUCCEEDED", "stop_reason": "MATCHED"},
        "cost": {},
        "create_request": {},
        "debug": {"agent_tool_calls": [], "diagnosis": {}},
        "get_task_data": {"status": "SUCCEEDED", "stop_reason": "MATCHED"},
        "source_records": [],
    }
    snapshot.update(overrides)
    return snapshot


def _analysis_result(snapshot):
    return {
        "supported": True,
        "selection_error": None,
        "task_ids": ["t1"],
        "parse_warnings": [],
        "snapshot": snapshot,
    }


class RouteOrderNoneStartTimeTests(unittest.TestCase):
    """修复 #1：start_time 缺失时 ROUTE-002 不再崩溃。"""

    def test_none_start_time_does_not_drop_route_rules(self):
        snapshot = _base_snapshot(
            diagnosis={
                "final_status": "SUCCEEDED",
                "stop_reason": "MATCHED",
                "public_figure_local_hit": False,
                "public_figure_remote_usable_count": 2,
                "public_figure_remote_ambiguous": False,
                "llm_search_call_count": 1,
                "pdl_identify_call_count": 1,
                "pdl_person_search_call_count": 0,
            },
            timeline=[
                {"provider": "wiki_remote", "status": "success", "start_time": None},
                {"provider": "people_data_labs", "status": "success",
                 "start_time": "2026-08-11T10:00:01+08:00"},
            ],
        )
        checks, _verdict, warnings = run_all_checks(snapshot)
        rule_ids = {c["rule_id"] for c in checks}
        # 四条路由规则均存在，没有因异常丢失
        for rid in ("ROUTE-001", "ROUTE-002", "ROUTE-003", "ROUTE-004"):
            self.assertIn(rid, rule_ids)
        self.assertFalse(
            any(w.get("code") == "RULE_ERROR" and "check_public_figure_route" in w.get("message", "")
                for w in warnings),
            f"路由规则仍抛异常: {warnings}",
        )

    def test_timeline_position_determines_route_order(self):
        # PDL 在 timeline 中位于 Wiki 之前 → FAIL
        snapshot = _base_snapshot(
            diagnosis={
                "final_status": "SUCCEEDED",
                "stop_reason": "MATCHED",
                "public_figure_local_hit": False,
                "public_figure_remote_usable_count": 2,
                "public_figure_remote_ambiguous": False,
                "llm_search_call_count": 0,
                "pdl_identify_call_count": 1,
                "pdl_person_search_call_count": 0,
            },
            timeline=[
                {"provider": "people_data_labs", "status": "success", "operation": "person_identify"},
                {"provider": "wiki_remote", "status": "success"},
            ],
        )
        checks, _verdict, _warnings = run_all_checks(snapshot)
        route2 = next(c for c in checks if c["rule_id"] == "ROUTE-002")
        self.assertEqual(route2["outcome"], "FAIL")


class EvidencePacketRedactionTests(unittest.TestCase):
    """修复 #2：AI 路径 checks 证据值按 json_path 脱敏。"""

    def test_packet_redacts_sensitive_evidence_value(self):
        snapshot = _base_snapshot(
            get_task_data={"status": "FAILED", "stop_reason": "MATCHED"},
        )
        result = _analysis_result(snapshot)
        packet = build_evidence_packet(result)
        self.assertIsNotNone(packet)
        # STATE-001 FAIL，注入一条敏感证据再验证脱敏路径
        from people_search_rules import _redact_dict_keys_custom, _redact_value_by_hint
        sensitive_check = {
            "rule_id": "X-001", "category": "test", "outcome": "FAIL",
            "severity": "P0", "title": "t", "actual": "a", "expected": "e",
            "evidence": [{"method": "GetTask", "json_path": "data.headers.authorization",
                          "value": "Bearer secret-token-123", "line_start": 1, "line_end": 2}],
        }
        packet_copy = dict(packet)
        packet_copy["checks"] = packet["checks"] + [sensitive_check]
        redacted = _redact_dict_keys_custom(packet_copy, _redact_value_by_hint)
        target = next(c for c in redacted["checks"] if c["rule_id"] == "X-001")
        self.assertEqual(target["evidence"][0]["value"], "***")

    def test_response_and_packet_redaction_same_level(self):
        sensitive = {"json_path": "$.request.auth_token", "value": "tk-secret",
                     "method": "GetTask", "line_start": 1, "line_end": 2}
        self.assertEqual(redact_for_response(sensitive)["value"], "***")


class Base64FalsePositiveTests(unittest.TestCase):
    """修复 #3：Base64 判定需要混合大小写+数字，避免误伤普通文本。"""

    def test_plain_long_alpha_text_not_redacted(self):
        text = "A" * 3000
        self.assertEqual(redact_for_ai(text), text)

    def test_real_base64_blob_redacted(self):
        blob = "iVBORw0KGgoAAAANSUhEUg" + "Ab1" * 300  # 混合大小写+数字
        self.assertEqual(redact_for_ai(blob), "[binary omitted]")

    def test_data_url_still_redacted(self):
        value = "data:image/jpeg;base64,/9j/4AAQ" + "A" * 600
        self.assertEqual(redact_for_response({"photo": value})["photo"], "[binary omitted]")

    def test_packet_keeps_long_name_text(self):
        snapshot = _base_snapshot()
        snapshot["task"]["full_name"] = "A" * 3000
        packet = build_evidence_packet(_analysis_result(snapshot))
        # 长文本保留（受 2000 字符上限裁剪，但不会被误判为二进制）
        self.assertNotEqual(packet["task_summary"]["full_name"], "[binary omitted]")


class ReportEvidenceTests(unittest.TestCase):
    """修复 #4：报告异常/疑问章节包含证据引用。"""

    def test_fail_section_contains_evidence_line(self):
        snapshot = _base_snapshot(
            get_task_data={"status": "FAILED", "stop_reason": "MATCHED"},
            source_records=[
                {"method": "GetTask", "direction": "response", "parse_status": "PARSED",
                 "start_line": 5, "end_line": 20},
                {"method": "GetSearchTaskDebug", "direction": "response", "parse_status": "PARSED",
                 "start_line": 21, "end_line": 40},
            ],
        )
        report = render_rule_report(_analysis_result(snapshot))
        self.assertIn("## 已确认异常", report)
        self.assertIn("STATE-001", report)
        self.assertIn("证据: GetTask", report)
        self.assertIn("日志行 5-20", report)


class SignedUrlRedactionTests(unittest.TestCase):
    """修复 #5：签名 URL 去 query，普通 social URL 保留。"""

    def test_signed_url_query_stripped(self):
        url = "https://cdn.example.com/photos/a.jpg?X-Amz-Signature=abc&X-Amz-Expires=3600"
        self.assertEqual(redact_for_ai(url), "https://cdn.example.com/photos/a.jpg")

    def test_canonical_social_url_kept(self):
        url = "https://www.instagram.com/someuser/"
        self.assertEqual(redact_for_ai(url), url)

    def test_unsigned_query_kept(self):
        url = "https://example.com/page?page=2"
        self.assertEqual(redact_for_ai(url), url)


class LlmOrderTests(unittest.TestCase):
    """修复 #6：LLM-001 使用 timeline（时间升序）判断最后一次调用。"""

    def test_last_llm_call_uses_timeline_order(self):
        snapshot = _base_snapshot(
            diagnosis={
                "final_status": "SUCCEEDED",
                "stop_reason": "MATCHED",
                "llm_search_call_count": 2,
                "llm_result_status": "complete",
            },
            timeline=[
                {"provider": "llm_search", "status": "success", "result_class": "truncated"},
                {"provider": "llm_search", "status": "success", "result_class": "complete"},
            ],
        )
        checks, _verdict, _warnings = run_all_checks(snapshot)
        llm = next(c for c in checks if c["rule_id"] == "LLM-001")
        self.assertEqual(llm["outcome"], "PASS")


class CandStableIdentifierTests(unittest.TestCase):
    """修复 #7：CAND-004 覆盖 canonical_url / wikidata_id 重复。"""

    def test_duplicate_canonical_url_detected(self):
        snapshot = _base_snapshot(
            candidates=[
                {"candidate_id": "c1", "person_id": "p1", "canonical_url": "https://instagram.com/u"},
                {"candidate_id": "c2", "person_id": "p2", "canonical_url": "https://instagram.com/u"},
            ],
        )
        checks, _verdict, _warnings = run_all_checks(snapshot)
        cand4 = next(c for c in checks if c["rule_id"] == "CAND-004")
        self.assertEqual(cand4["outcome"], "FAIL")
        self.assertIn("canonical_url", cand4["actual"])


class EvidencePacketLimitsTests(unittest.TestCase):
    """修复 #8：§9.3 source_truncated、文本上限、优先保留。"""

    def test_over_20_candidates_sets_source_truncated_and_keeps_selected(self):
        snapshot = _base_snapshot(
            candidates=[
                {"candidate_id": f"c{i}", "display_name": f"n{i}", "match_score": i,
                 "confidence_level": "LOW", "source_provider": "p",
                 "selected": i == 25}
                for i in range(1, 30)
            ],
        )
        packet = build_evidence_packet(_analysis_result(snapshot))
        self.assertTrue(packet.get("source_truncated"))
        self.assertEqual(len(packet["candidate_summary"]), 20)
        kept_ids = {c["candidate_id"] for c in packet["candidate_summary"]}
        self.assertIn("c25", kept_ids)  # selected 候选优先保留
        self.assertIn("c29", kept_ids)  # 最高分候选优先保留

    def test_free_text_capped_at_2000(self):
        snapshot = _base_snapshot()
        snapshot["task"]["full_name"] = "B" * 3000
        packet = build_evidence_packet(_analysis_result(snapshot))
        self.assertTrue(packet.get("source_truncated"))
        serialized = json.dumps(packet, ensure_ascii=False)
        self.assertNotIn("B" * 2001, serialized)
        self.assertIn("…(已截断)", packet["task_summary"]["full_name"])

    def test_small_packet_has_no_source_truncated(self):
        packet = build_evidence_packet(_analysis_result(_base_snapshot()))
        self.assertNotIn("source_truncated", packet)

    def test_packet_contains_social_url_decisions(self):
        snapshot = _base_snapshot()
        snapshot["debug"]["social_url_queue"] = [
            {"url": "https://instagram.com/u", "canonical_url": "https://instagram.com/u",
             "origin": "user_input", "decision": "CALLED", "skip_reason": ""},
        ]
        packet = build_evidence_packet(_analysis_result(snapshot))
        self.assertIn("social_url_decisions", packet)
        self.assertEqual(packet["social_url_decisions"][0]["decision"], "CALLED")

    def test_timeline_over_100_keeps_failed_calls(self):
        snapshot = _base_snapshot(
            timeline=(
                [{"provider": "p", "status": "success", "start_time": f"t{i}"} for i in range(120)]
                + [{"provider": "p", "status": "error", "start_time": "t999", "error_code": "E1"}]
            ),
        )
        packet = build_evidence_packet(_analysis_result(snapshot))
        self.assertTrue(packet.get("source_truncated"))
        self.assertEqual(len(packet["timeline"]), 100)
        self.assertTrue(any(c.get("status") == "error" for c in packet["timeline"]))


class LimitPacketMarkerTests(unittest.TestCase):
    """修复 #9：limit_evidence_packet 同时设置 truncated 与 source_truncated。"""

    def test_byte_limit_sets_both_markers(self):
        packet = {
            "analyzer_version": "v1",
            "verdict": "NORMAL",
            "checks": [
                {"rule_id": f"R-{i}", "actual": "x" * 200, "evidence": [{"value": "y" * 200}]}
                for i in range(50)
            ],
        }
        limited, truncated = limit_evidence_packet(packet, max_bytes=2048)
        size = len(json.dumps(limited, ensure_ascii=False).encode("utf-8"))
        self.assertLessEqual(size, 2048)
        self.assertTrue(truncated)
        self.assertTrue(limited.get("truncated"))
        self.assertTrue(limited.get("source_truncated"))


class SummarizeReturnPacketTests(unittest.TestCase):
    """修复 #12：summarize_with_ai 发起调用后返回实际发送的 packet。"""

    def test_success_returns_sent_packet(self):
        class FakeResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        body = json.dumps({"choices": [{"message": {"content": "总结"}}]}).encode("utf-8")
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append(req)
            return FakeResponse(body)

        cfg = AIConfig(ai_enabled=True, endpoint="http://llm.local/v1/chat/completions",
                       model="m", api_key="k")
        result = _analysis_result(_base_snapshot())
        text, status, packet = summarize_with_ai(result, cfg, skill_instruction="INST",
                                                 _urlopen=fake_urlopen)
        self.assertEqual(status["status"], "SUCCESS")
        self.assertIsNotNone(packet)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
