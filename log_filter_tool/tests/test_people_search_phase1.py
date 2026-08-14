"""阶段 1 解析层测试：People Insight 检索日志结构化解析和任务快照。

覆盖范围：
1. 10 份阶段 0 夹具（Gateway 格式与裸 QueryChainLogger 格式）；
2. peoplesearch_logs/ 下的真实检索日志（带 logger 前缀、attempt 后缀、
   Gateway 信封响应的 QueryChainLogger 格式，以及多任务拼接日志）；
3. 单任务选择、终态选择、时间线排序、Gateway 解包和兜底识别。

阶段 1 完成条件：不调用 AI 即可从完整夹具生成稳定任务快照。
"""
import json
import unittest
from pathlib import Path

from people_search_analyzer import (
    ANALYZER_VERSION,
    MULTIPLE_TASKS_FOUND,
    TASK_NOT_FOUND,
    TERMINAL_STATUSES,
    UNSUPPORTED_LOG,
    _parse_timestamp,
    analyze_log_file,
    analyze_people_search_log,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "people_search"
REAL_LOG_DIR = Path(__file__).resolve().parents[1] / "peoplesearch_logs"
REAL_QCL_LOGS = sorted(REAL_LOG_DIR.glob("2026-08-11_*.log"))
MULTI_TASK_LOG = REAL_LOG_DIR / "20260810_204204_097281_test_26120.log"

ALL_FIXTURES = sorted(FIXTURE_DIR.glob("f*.log"))


def load_fixture(name):
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class FixtureParsingTests(unittest.TestCase):
    """10 份夹具均可不调用 AI 生成稳定任务快照。"""

    def test_all_fixtures_generate_snapshot_without_ai(self):
        self.assertEqual(len(ALL_FIXTURES), 10)
        for path in ALL_FIXTURES:
            with self.subTest(fixture=path.name):
                result = analyze_log_file(path)
                self.assertTrue(result["supported"], path.name)
                self.assertIsNone(result["selection_error"], path.name)
                self.assertIsNone(result["unsupported_reason"], path.name)
                snapshot = result["snapshot"]
                self.assertIsNotNone(snapshot, path.name)
                self.assertEqual(snapshot["analyzer_version"], ANALYZER_VERSION)
                for key in (
                    "create_task",
                    "get_task",
                    "candidate_list",
                    "candidate_detail",
                    "debug",
                    "cost_summary",
                    "source_truncated",
                    "parse_warnings",
                ):
                    self.assertIn(key, snapshot["coverage"], path.name)
                for record in result["records"]:
                    self.assertEqual(record["parse_status"], "PARSED", path.name)
                self.assertEqual(result["parse_warnings"], [], path.name)

    def test_f01_snapshot_content(self):
        result = analyze_log_file(FIXTURE_DIR / "f01_public_figure_local_hit.log")
        snapshot = result["snapshot"]
        task = snapshot["task"]
        self.assertEqual(task["task_id"], "task_f010000000000000000000aa")
        self.assertEqual(task["full_name"], "Alice Example")
        self.assertEqual(task["final_status"], "SUCCEEDED")
        self.assertEqual(task["candidate_count"], 1)
        self.assertEqual(task["top_confidence_score"], 95)
        self.assertEqual(task["clue_types"], ["FULL_NAME"])
        self.assertTrue(task["trace_ids"])
        coverage = snapshot["coverage"]
        self.assertTrue(coverage["create_task"])
        self.assertTrue(coverage["get_task"])
        self.assertTrue(coverage["candidate_list"])
        self.assertFalse(coverage["candidate_detail"])
        self.assertTrue(coverage["debug"])
        self.assertTrue(coverage["cost_summary"])
        self.assertEqual(len(snapshot["timeline"]), 1)
        self.assertEqual(snapshot["timeline"][0]["provider"], "public_figure_local")
        self.assertEqual(snapshot["diagnosis"].get("stop_reason"), "LOCAL_HIT")

    def test_f03_timeline_sorted_ascending_despite_reversed_input(self):
        result = analyze_log_file(FIXTURE_DIR / "f03_wiki_unique_but_pdl_called.log")
        timeline = result["snapshot"]["timeline"]
        self.assertEqual(len(timeline), 4)
        parsed_times = [_parse_timestamp(entry["start_time"]) for entry in timeline]
        self.assertTrue(all(t is not None for t in parsed_times))
        self.assertEqual(parsed_times, sorted(parsed_times))
        # 夹具中 agent_tool_calls 为倒序，排序后第一条应为最早的 llm_search。
        self.assertEqual(timeline[0]["provider"], "llm_search")
        self.assertEqual(timeline[-1]["provider"], "people_data_labs")
        self.assertEqual(timeline[-1]["operation"], "person_search")

    def test_f06_qcl_format_with_email_preserved(self):
        result = analyze_log_file(FIXTURE_DIR / "f06_social_link_queue_dedupe.log")
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["task"]["task_id"], "task_f0600000000000000000000aa")
        self.assertEqual(snapshot["task"]["full_name"], "Carol Fixture")
        qcl_requests = [
            record
            for record in result["records"]
            if record["marker_format"] == "qcl" and record["direction"] == "request"
        ]
        self.assertTrue(qcl_requests)
        # 邮箱按评审结论保留原值，不在解析层脱敏。
        serialized = json.dumps(snapshot["source_records"], ensure_ascii=False)
        self.assertIn("carol@example.com", serialized)
        self.assertEqual(len(snapshot["timeline"]), 3)
        self.assertEqual(len(snapshot["candidates"]), 2)

    def test_f10_terminal_selection_picks_failed(self):
        result = analyze_log_file(FIXTURE_DIR / "f10_technical_failure_misclassified.log")
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["task"]["final_status"], "FAILED")
        self.assertTrue(snapshot["coverage"]["get_task"])
        self.assertFalse(snapshot["coverage"]["candidate_list"])


class TaskSelectionTests(unittest.TestCase):
    def test_multiple_tasks_found_without_requested_task_id(self):
        combined = load_fixture("f01_public_figure_local_hit.log") + "\n" + load_fixture(
            "f06_social_link_queue_dedupe.log"
        )
        result = analyze_people_search_log(combined)
        self.assertEqual(result["selection_error"], MULTIPLE_TASKS_FOUND)
        self.assertIsNone(result["snapshot"])
        self.assertEqual(
            set(result["task_ids"]),
            {"task_f010000000000000000000aa", "task_f0600000000000000000000aa"},
        )

    def test_requested_task_id_selects_single_task(self):
        combined = load_fixture("f01_public_figure_local_hit.log") + "\n" + load_fixture(
            "f06_social_link_queue_dedupe.log"
        )
        result = analyze_people_search_log(
            combined, requested_task_id="task_f0600000000000000000000aa"
        )
        self.assertIsNone(result["selection_error"])
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["task"]["task_id"], "task_f0600000000000000000000aa")
        for record in snapshot["source_records"]:
            if record["task_ids"]:
                self.assertIn("task_f0600000000000000000000aa", record["task_ids"])

    def test_task_not_found(self):
        result = analyze_people_search_log(
            load_fixture("f01_public_figure_local_hit.log"),
            requested_task_id="task_does_not_exist",
        )
        self.assertEqual(result["selection_error"], TASK_NOT_FOUND)
        self.assertIsNone(result["snapshot"])

    def test_markerless_debug_and_cost_only(self):
        text = (
            '{\n'
            '  "debug": {\n'
            '    "task_id": "task_markerless_01",\n'
            '    "agent_tool_calls": [],\n'
            '    "diagnosis": {"final_status": "SUCCEEDED", "stop_reason": "COMPLETED"}\n'
            '  }\n'
            '}\n'
            '{\n'
            '  "cost_summary": {\n'
            '    "task_id": "task_markerless_01",\n'
            '    "total_estimated_cost_microunit": 0,\n'
            '    "items": []\n'
            '  }\n'
            '}\n'
        )
        result = analyze_people_search_log(text)
        self.assertTrue(result["supported"])
        self.assertIsNone(result["selection_error"])
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["task"]["task_id"], "task_markerless_01")
        self.assertTrue(snapshot["coverage"]["debug"])
        self.assertTrue(snapshot["coverage"]["cost_summary"])
        self.assertFalse(snapshot["coverage"]["create_task"])
        self.assertEqual(snapshot["diagnosis"].get("stop_reason"), "COMPLETED")

    def test_unsupported_log(self):
        result = analyze_people_search_log(
            "2026-08-10 20:42:04,423 | INFO | utils.custom.flow_runner | 开始步骤\n"
            '{"url": "https://gateway.example/api", "payload": {"token": "***"}}\n'
        )
        self.assertFalse(result["supported"])
        self.assertEqual(result["unsupported_reason"], UNSUPPORTED_LOG)
        self.assertIsNone(result["snapshot"])


class TerminalAndTimelineTests(unittest.TestCase):
    def test_task_not_terminal_warning(self):
        text = (
            'GetTask 脱敏请求数据:\n'
            '{"task_id": "task_synth_01"}\n'
            'GetTask 响应数据: HTTP 200 elapsed_ms=100\n'
            '{"task_id": "task_synth_01", "status": "RUNNING"}\n'
        )
        result = analyze_people_search_log(text)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["task"]["final_status"], "RUNNING")
        codes = [w["code"] for w in result["parse_warnings"]]
        self.assertIn("TASK_NOT_TERMINAL", codes)

    def test_gateway_envelope_subrequest_failure_preserved(self):
        text = (
            'GetTask 响应数据: HTTP 200 elapsed_ms=50\n'
            '{"code": 0, "message": "ok", "request_id": "gw_req_sub", "trace_id": "trace_sub",'
            ' "responses": [{"id": "req_0", "success": false, "code": 500, "message": "boom",'
            ' "data": {"task_id": "task_sub_01", "status": "FAILED"}}]}\n'
        )
        result = analyze_people_search_log(text)
        record = result["records"][0]
        self.assertEqual(record["request_id"], "gw_req_sub")
        self.assertEqual(record["trace_id"], "trace_sub")
        self.assertEqual(record["gateway"]["sub_requests"][0]["success"], False)
        self.assertEqual(record["gateway"]["sub_requests"][0]["code"], 500)
        self.assertEqual(result["snapshot"]["task"]["final_status"], "FAILED")

    def test_missing_tool_call_time_warning_and_order(self):
        text = (
            'GetSearchTaskDebug 响应数据: HTTP 200 elapsed_ms=10\n'
            '{"debug": {"task_id": "task_time_01", "agent_tool_calls": ['
            '{"provider": "a", "operation": "op1"},'
            '{"provider": "b", "operation": "op2", "start_time": "2026-08-13T10:00:05+08:00"},'
            '{"provider": "c", "operation": "op3", "start_time": "2026-08-13T10:00:01+08:00"}'
            "]}}\n"
        )
        result = analyze_people_search_log(text)
        timeline = result["snapshot"]["timeline"]
        self.assertEqual([entry["provider"] for entry in timeline], ["c", "b", "a"])
        codes = [w["code"] for w in result["parse_warnings"]]
        self.assertIn("MISSING_TOOL_CALL_TIME", codes)

    def test_query_end_http_dash_tolerated(self):
        text = (
            'QueryEnd 事件:\n'
            '{"stage": "QueryEnd", "task_id": "task_qe_01"}\n'
            'QueryEnd 响应数据: HTTP - elapsed_ms=-\n'
            '{"task_id": "task_qe_01"}\n'
            'GetTask 响应数据: HTTP 200 elapsed_ms=10\n'
            '{"task_id": "task_qe_01", "status": "SUCCEEDED"}\n'
        )
        result = analyze_people_search_log(text)
        self.assertTrue(result["supported"])
        # QueryEnd 非受支持接口，不产生接口记录。
        self.assertEqual([record["method"] for record in result["records"]], ["GetTask"])
        self.assertEqual(result["parse_warnings"], [])


@unittest.skipUnless(
    REAL_LOG_DIR.is_dir() and REAL_QCL_LOGS, "peoplesearch_logs 真实日志目录不存在"
)
class RealLogTests(unittest.TestCase):
    def test_all_real_qcl_logs_parse_to_single_terminal_task(self):
        self.assertGreaterEqual(len(REAL_QCL_LOGS), 5)
        for path in REAL_QCL_LOGS:
            with self.subTest(log=path.name):
                result = analyze_log_file(path)
                self.assertTrue(result["supported"], path.name)
                self.assertIsNone(result["selection_error"], path.name)
                self.assertEqual(len(result["task_ids"]), 1, path.name)
                snapshot = result["snapshot"]
                task = snapshot["task"]
                self.assertTrue(task["task_id"].startswith("task_"), path.name)
                self.assertIn(task["final_status"], TERMINAL_STATUSES, path.name)
                self.assertTrue(task["full_name"], path.name)
                coverage = snapshot["coverage"]
                for key in ("create_task", "get_task", "debug", "cost_summary"):
                    self.assertTrue(coverage[key], f"{path.name} coverage.{key}")
                self.assertEqual(result["parse_warnings"], [], path.name)
                # 时间线非空且按 start_time 升序。
                timeline = snapshot["timeline"]
                self.assertTrue(timeline, path.name)
                parsed_times = [_parse_timestamp(entry["start_time"]) for entry in timeline]
                self.assertTrue(all(t is not None for t in parsed_times), path.name)
                self.assertEqual(parsed_times, sorted(parsed_times), path.name)
                for record in result["records"]:
                    self.assertEqual(record["parse_status"], "PARSED", path.name)

    def test_kervin_lau_log_structure(self):
        path = REAL_LOG_DIR / "2026-08-11_124606_Kervin_Lau.log"
        result = analyze_log_file(path)
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["task"]["task_id"], "task_86c9f1e3898ab4e336cb4ca6")
        self.assertEqual(snapshot["task"]["full_name"], "Kervin Lau")
        self.assertEqual(snapshot["task"]["final_status"], "SUCCEEDED")
        # 真实 QCL 请求 marker 带 attempt 后缀，响应为 Gateway 信封。
        create_requests = [
            record
            for record in result["records"]
            if record["method"] == "CreateIntentTask" and record["direction"] == "request"
        ]
        self.assertEqual(len(create_requests), 1)
        self.assertEqual(create_requests[0]["attempt"], 1)
        self.assertEqual(create_requests[0]["marker_format"], "qcl")
        get_task_records = [
            record
            for record in result["records"]
            if record["method"] == "GetTask" and record["direction"] == "response"
        ]
        self.assertTrue(get_task_records)
        for record in get_task_records:
            self.assertTrue(record["request_id"].startswith("gw_req_"))
            self.assertIsNotNone(record["gateway"])
        # 真实 agent_tool_calls 使用 provider_operation 字段，时间线 operation 不应为空。
        self.assertTrue(all(entry["operation"] for entry in snapshot["timeline"]))
        # stage 事件提供了 run_id/person_name 等元数据。
        self.assertTrue(any(e["run_id"] for e in result["stage_events"]))

    @unittest.skipUnless(MULTI_TASK_LOG.is_file(), "多任务真实日志不存在")
    def test_multi_task_real_log_requires_explicit_selection(self):
        result = analyze_log_file(MULTI_TASK_LOG)
        self.assertTrue(result["supported"])
        self.assertEqual(result["selection_error"], MULTIPLE_TASKS_FOUND)
        self.assertEqual(len(result["task_ids"]), 3)
        self.assertIsNone(result["snapshot"])

        target_task_id = result["task_ids"][1]
        selected = analyze_log_file(MULTI_TASK_LOG, requested_task_id=target_task_id)
        self.assertIsNone(selected["selection_error"])
        snapshot = selected["snapshot"]
        self.assertEqual(snapshot["task"]["task_id"], target_task_id)
        self.assertTrue(snapshot["coverage"]["debug"])
        self.assertTrue(snapshot["coverage"]["cost_summary"])
        self.assertTrue(snapshot["timeline"])
        for record in snapshot["source_records"]:
            if record["task_ids"]:
                self.assertIn(target_task_id, record["task_ids"])

    def test_real_snapshot_deterministic(self):
        path = REAL_LOG_DIR / "2026-08-11_124606_Kervin_Lau.log"
        first = json.dumps(analyze_log_file(path)["snapshot"], sort_keys=True, ensure_ascii=False)
        second = json.dumps(analyze_log_file(path)["snapshot"], sort_keys=True, ensure_ascii=False)
        self.assertEqual(first, second)

    def test_fixture_snapshot_deterministic(self):
        text = load_fixture("f01_public_figure_local_hit.log")
        first = json.dumps(
            analyze_people_search_log(text)["snapshot"], sort_keys=True, ensure_ascii=False
        )
        second = json.dumps(
            analyze_people_search_log(text)["snapshot"], sort_keys=True, ensure_ascii=False
        )
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
