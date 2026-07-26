import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import requests

from search_tool import (
    Config,
    ConfigError,
    FlowError,
    SearchClient,
    normalize_result_status,
    process_one,
    run_batch,
    select_output_paths,
)


def api_body(data, *, code=0, success=True):
    return {
        "code": code,
        "message": "ok" if code == 0 else "failed",
        "responses": [
            {"id": "req_0", "success": success, "code": code, "message": "ok", "data": data}
        ],
    }


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.bodies:
            raise AssertionError("unexpected HTTP call")
        body = self.bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return FakeResponse(body)


def config(**overrides):
    values = {
        "api_url": "https://example.test/rpc",
        "headers": {"x-app-id": "test"},
        "auth_token": "secret",
        "device_id": "device",
        "user_id": "user",
        "poll_interval_seconds": 5,
        "max_poll_count": 3,
        "http_timeout_seconds": 10,
    }
    values.update(overrides)
    return Config(**values)


class SearchToolTests(unittest.TestCase):
    def test_normalize_result_status_uses_candidate_count_before_detail_status(self):
        """规范化状态区分有结果、无结果和执行失败。"""

        self.assertEqual(
            "HAS_CANDIDATES",
            normalize_result_status("PARTIAL_DETAIL_FAILED", 2),
        )
        self.assertEqual(
            "NO_CANDIDATES",
            normalize_result_status("NO_CANDIDATE", 0),
        )
        self.assertEqual(
            "EXECUTION_FAILED",
            normalize_result_status("FAILED", 0),
        )
        self.assertEqual(
            "HAS_CANDIDATES",
            normalize_result_status("FAILED", 1),
        )

    def test_phase0_optimization_contract_fixtures_are_frozen(self):
        """冻结新增公共字段与可选空路径的脱敏接口契约样例。

        功能说明:
            验证阶段0 Mock 保持标准响应信封、公共字段类型和可选空结构，
            防止后续开发在接口真实路径尚未确认时自行改写契约样例。

        返回值:
            无；断言失败表示阶段0契约夹具发生了非预期变化。

        异常说明:
            文件不存在或 JSON 非法时由测试直接失败，避免使用损坏夹具。
        """

        fixture_dir = (
            Path(__file__).parent
            / "fixtures"
            / "v1_3_optimization_phase0"
        )
        full = json.loads(
            (fixture_dir / "get_task_public_fields_full.json").read_text(
                encoding="utf-8"
            )
        )
        partial = json.loads(
            (fixture_dir / "get_task_public_fields_partial.json").read_text(
                encoding="utf-8"
            )
        )
        optional = json.loads(
            (
                fixture_dir
                / "candidate_detail_optional_fields_missing.json"
            ).read_text(encoding="utf-8")
        )

        full_data = full["responses"][0]["data"]
        self.assertEqual("SUCCEEDED", full_data["status"])
        self.assertEqual(2, full_data["candidate_count"])
        self.assertIsInstance(full_data["llm_cost"], float)
        self.assertIsInstance(full_data["third_party_cost"], float)
        self.assertIsInstance(full_data["total_cost"], float)
        self.assertIs(full_data["pdl_called"], True)
        self.assertIsInstance(full_data["search_duration_ms"], int)

        partial_data = partial["responses"][0]["data"]
        self.assertEqual(0.0, partial_data["llm_cost"])
        self.assertIs(partial_data["pdl_called"], False)
        self.assertNotIn("third_party_cost", partial_data)
        self.assertNotIn("total_cost", partial_data)
        self.assertNotIn("search_duration_ms", partial_data)

        sections = optional["responses"][0]["data"]["ui_sections"]
        self.assertEqual([], sections["insights"]["data"]["items"])
        self.assertIsNone(sections["summary"]["data"]["primary_image"])
        self.assertEqual(
            "MEDIUM",
            sections["summary"]["data"]["confidence_level"],
        )

    def test_candidate_detail_failure_isolated_and_raw_is_sanitized(self):
        """验证单候选人详情失败隔离、Raw 脱敏及进度事件。"""

        create_body = api_body({"task_id": "task-v13"})
        create_body["auth_token"] = "response-secret"
        create_body["device_id"] = "response-device"
        create_body["future_field"] = {"kept": True}
        session = FakeSession(
            [
                create_body,
                api_body(
                    {
                        "status": "SUCCEEDED",
                        "candidate_count": 3,
                        "llm_cost": 1.25,
                        "third_party_cost": 2.5,
                        "total_cost": 3.75,
                        "pdl_called": True,
                        "search_duration_ms": 4321,
                    }
                ),
                api_body(
                    {
                        "items": [
                            {"candidate_id": "c1", "rank_score": 0.9},
                            {"candidate_id": "c2", "rank_score": 0.8},
                            {"candidate_id": "c3", "rank_score": 0.7},
                        ]
                    }
                ),
                api_body({"ui_sections": {"summary": {"status": "data"}}}),
                api_body({}, code=7, success=False),
                api_body({"ui_sections": {"social": {"status": "data"}}}),
            ]
        )
        client = SearchClient(config(), session)
        progress_events = []
        raw_events = []
        candidate_failures = []

        result = process_one(
            {
                "input_id": "case-v13",
                "query_stage": "FULL_NAME_SOCIAL",
                "match_strategy": "UNION",
                "clues": [
                    {"type": "FULL_NAME"},
                    {"type": "SOCIAL_LINK", "auth_token": "input-secret"},
                ],
                "additional_details": [],
            },
            client,
            sleep_fn=lambda _: None,
            progress_callback=progress_events.append,
            raw_callback=raw_events.append,
            failure_callback=candidate_failures.append,
            run_id="run-v13",
        )

        self.assertEqual("1.3.1", result["result_schema_version"])
        self.assertEqual("run-v13", result["run_id"])
        self.assertEqual("FULL_NAME_SOCIAL", result["query_stage"])
        self.assertEqual("PARTIAL_DETAIL_FAILED", result["query_status"])
        self.assertEqual("HAS_CANDIDATES", result["result_status"])
        self.assertEqual(
            {
                "llm_cost": 1.25,
                "third_party_cost": 2.5,
                "total_cost": 3.75,
                "pdl_called": True,
                "search_duration_ms": 4321,
            },
            result["task_fields"],
        )
        self.assertEqual(2, result["detail_success_count"])
        self.assertEqual(1, result["detail_failure_count"])
        self.assertEqual(
            ["SUCCESS", "FAILED", "SUCCESS"],
            [candidate["detail_status"] for candidate in result["results"]],
        )
        self.assertIn("code=7", result["results"][1]["detail_error"])
        self.assertIsNone(result["results"][1]["detail_data_raw"])
        self.assertEqual("data", result["results"][2]["ui_sections"]["social"]["status"])

        self.assertEqual(1, len(candidate_failures))
        self.assertEqual("CANDIDATE", candidate_failures[0]["scope"])
        self.assertEqual("c2", candidate_failures[0]["candidate_id"])
        self.assertIn("code=7", candidate_failures[0]["error"])

        self.assertEqual(
            [
                "CreateIntentTask",
                "GetTask",
                "ListTaskCandidates",
                "GetTaskCandidateDetail",
                "GetTaskCandidateDetail",
                "GetTaskCandidateDetail",
            ],
            [event["stage"] for event in raw_events],
        )
        serialized_raw = json.dumps(
            {"result_raw": result["raw"], "events": raw_events},
            ensure_ascii=False,
        )
        self.assertNotIn("response-secret", serialized_raw)
        self.assertNotIn("response-device", serialized_raw)
        self.assertNotIn("input-secret", serialized_raw)
        self.assertTrue(
            result["raw"]["create_intent_task"]["response_body"]["future_field"]["kept"]
        )

        event_names = [event["event"] for event in progress_events]
        self.assertEqual("query_started", event_names[0])
        self.assertIn("candidate_failed", event_names)
        self.assertEqual("query_succeeded", event_names[-1])
        self.assertEqual(
            "PARTIAL_DETAIL_FAILED",
            progress_events[-1]["status"],
        )

    def test_run_batch_writes_failed_candidate_to_results_and_failures(self):
        """验证部分详情失败同时写入 v1.3 结果与失败文件。"""

        session = FakeSession(
            [
                api_body({"task_id": "task-partial"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 2}),
                api_body(
                    {
                        "items": [
                            {"candidate_id": "c1", "rank_score": 0.9},
                            {"candidate_id": "c2", "rank_score": 0.8},
                        ]
                    }
                ),
                api_body({}, code=8, success=False),
                api_body({"ui_sections": {"summary": {"status": "data"}}}),
            ]
        )
        client = SearchClient(config(), session)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "tasks.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "input_id": "partial",
                        "query_stage": "FULL_NAME",
                        "clues": [{"type": "FULL_NAME"}],
                    }
                ),
                encoding="utf-8",
            )

            succeeded, failed = run_batch(
                input_path,
                root / "output",
                client,
                lambda _: None,
                run_id="run-partial",
            )
            result = json.loads(
                (root / "output/results.jsonl").read_text(encoding="utf-8")
            )
            failure = json.loads(
                (root / "output/failures.jsonl").read_text(encoding="utf-8")
            )

        self.assertEqual((0, 1), (succeeded, failed))
        self.assertEqual("PARTIAL_DETAIL_FAILED", result["query_status"])
        self.assertEqual("FAILED", result["results"][0]["detail_status"])
        self.assertEqual("SUCCESS", result["results"][1]["detail_status"])
        self.assertEqual("1.3.1", failure["failure_schema_version"])
        self.assertEqual("run-partial", failure["run_id"])
        self.assertEqual("CANDIDATE", failure["scope"])
        self.assertEqual("c1", failure["candidate_id"])

    def test_invalid_list_items_are_candidate_failures_and_do_not_stop(self):
        """验证非法 List 单项按候选级失败保留，并继续合法候选人。"""

        session = FakeSession(
            [
                api_body({"task_id": "task-invalid-list"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 3}),
                api_body(
                    {
                        "items": [
                            "invalid-item",
                            {"rank_score": 0.5},
                            {"candidate_id": "c3", "rank_score": 0.4},
                        ]
                    }
                ),
                api_body({"ui_sections": {}}),
            ]
        )
        client = SearchClient(config(), session)
        candidate_failures = []

        result = process_one(
            {
                "input_id": "invalid-list",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=lambda _: None,
            failure_callback=candidate_failures.append,
        )

        self.assertEqual("PARTIAL_DETAIL_FAILED", result["query_status"])
        self.assertEqual(1, result["detail_success_count"])
        self.assertEqual(2, result["detail_failure_count"])
        self.assertEqual(3, len(result["results"]))
        self.assertEqual(
            ["FAILED", "FAILED", "SUCCESS"],
            [candidate["detail_status"] for candidate in result["results"]],
        )
        self.assertEqual(2, len(candidate_failures))
        detail_calls = [
            call
            for call in session.calls
            if call[1]["json"]["requests"][0]["method_name"]
            == "GetTaskCandidateDetail"
        ]
        self.assertEqual(1, len(detail_calls))

    def test_process_one_queued_then_succeeded_and_two_candidates(self):
        session = FakeSession(
            [
                api_body({"task_id": "task-1"}),
                api_body({"status": "QUEUED"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 2}),
                api_body(
                    {
                        "items": [
                            {"candidate_id": "c1", "rank_score": 0.91},
                            {"candidate_id": "c2"},
                        ]
                    }
                ),
                api_body({"ui_sections": {"summary": {"status": "data"}}}),
                api_body({"ui_sections": {"social": {"status": "empty"}}}),
            ]
        )
        client = SearchClient(config(), session)
        sleeps = []

        result = process_one(
            {
                "input_id": "case-1",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=sleeps.append,
        )

        self.assertEqual([5, 5], sleeps)
        self.assertEqual("task-1", result["task_id"])
        self.assertEqual(2, result["candidate_count_total"])
        self.assertEqual(2, result["candidate_count_listed"])
        self.assertEqual("SUCCESS", result["query_status"])
        self.assertEqual(2, result["detail_success_count"])
        self.assertEqual(0, result["detail_failure_count"])
        self.assertEqual(2, len(result["raw"]["get_task_history"]))
        self.assertEqual(["c1", "c2"], [item["candidate_id"] for item in result["results"]])
        self.assertEqual([1, 2], [item["candidate_rank"] for item in result["results"]])
        self.assertEqual([0.91, None], [item["rank_score"] for item in result["results"]])
        methods = [call[1]["json"]["requests"][0]["method_name"] for call in session.calls]
        self.assertEqual(
            [
                "CreateIntentTask",
                "GetTask",
                "GetTask",
                "ListTaskCandidates",
                "GetTaskCandidateDetail",
                "GetTaskCandidateDetail",
            ],
            methods,
        )
        list_params = session.calls[3][1]["json"]["requests"][0]["params"]
        self.assertEqual({"page_size": 100, "page_token": ""}, list_params["page"])

    def test_process_one_searching_continues_polling_until_succeeded(self):
        """验证 SEARCHING 状态继续轮询，成功后再请求候选人列表。"""

        session = FakeSession(
            [
                api_body({"task_id": "task-searching"}),
                api_body({"status": "SEARCHING"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 0}),
                api_body({"items": []}),
            ]
        )
        client = SearchClient(config(), session)
        sleeps = []

        result = process_one(
            {
                "input_id": "case-searching",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=sleeps.append,
        )

        self.assertEqual([5, 5], sleeps)
        self.assertEqual("NO_CANDIDATE", result["query_status"])
        self.assertEqual("NO_CANDIDATES", result["result_status"])
        self.assertEqual(0, result["candidate_count_total"])
        self.assertEqual(0, result["candidate_count_listed"])
        methods = [call[1]["json"]["requests"][0]["method_name"] for call in session.calls]
        self.assertEqual(
            ["CreateIntentTask", "GetTask", "GetTask", "ListTaskCandidates"],
            methods,
        )

    def test_requests_details_for_every_listed_candidate(self):
        """验证 List 返回多少名候选人，就请求多少次候选人详情。"""

        candidates = [
            {"candidate_id": f"c{index}", "rank_score": index / 10}
            for index in range(1, 7)
        ]
        session = FakeSession(
            [
                api_body({"task_id": "task-1"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 8}),
                api_body({"items": candidates}),
                *[api_body({"ui_sections": {}}) for _ in range(6)],
            ]
        )
        client = SearchClient(config(), session)

        result = process_one(
            {
                "input_id": "case-1",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=lambda _: None,
        )

        self.assertEqual(8, result["candidate_count_total"])
        self.assertEqual(6, result["candidate_count_listed"])
        self.assertEqual(6, len(result["results"]))
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            [item["candidate_rank"] for item in result["results"]],
        )
        detail_calls = [
            call
            for call in session.calls
            if call[1]["json"]["requests"][0]["method_name"] == "GetTaskCandidateDetail"
        ]
        self.assertEqual(6, len(detail_calls))

    def test_process_one_times_out(self):
        session = FakeSession(
            [api_body({"task_id": "task-1"}), api_body({"status": "QUEUED"}), api_body({"status": "QUEUED"})]
        )
        client = SearchClient(config(max_poll_count=2), session)

        with self.assertRaises(FlowError) as context:
            process_one(
                {
                    "input_id": "case-1",
                    "match_strategy": "UNION",
                    "clues": [{"type": "FULL_NAME"}],
                    "additional_details": [],
                },
                client,
                sleep_fn=lambda _: None,
            )

        self.assertEqual("GetTask", context.exception.stage)
        self.assertEqual("task-1", context.exception.task_id)
        self.assertIn("超时", str(context.exception))

    def test_batch_continues_after_failure(self):
        session = FakeSession(
            [
                api_body({"task_id": "task-fail"}),
                api_body({"status": "UNKNOWN"}),
                api_body({"task_id": "task-ok"}),
                api_body({"status": "SUCCEEDED"}),
                api_body({"items": []}),
            ]
        )
        client = SearchClient(config(), session)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "tasks.jsonl"
            input_path.write_text(
                "\n".join(
                    [
                        json.dumps({"input_id": "bad", "clues": [{"type": "FULL_NAME"}]}),
                        json.dumps({"input_id": "good", "clues": [{"type": "FULL_NAME"}]}),
                    ]
                ),
                encoding="utf-8",
            )

            success, failed = run_batch(input_path, root / "output", client, lambda _: None)

            self.assertEqual((1, 1), (success, failed))
            results = [json.loads(line) for line in (root / "output/results.jsonl").read_text().splitlines()]
            failures = [json.loads(line) for line in (root / "output/failures.jsonl").read_text().splitlines()]
            self.assertEqual("good", results[0]["input_id"])
            self.assertIsNone(results[0]["candidate_count_total"])
            self.assertEqual(0, results[0]["candidate_count_listed"])
            self.assertEqual([], results[0]["results"])
            self.assertEqual("bad", failures[0]["input_id"])
            self.assertEqual("GetTask", failures[0]["stage"])
            self.assertEqual("1.3.1", failures[0]["failure_schema_version"])
            self.assertEqual("QUERY", failures[0]["scope"])
            self.assertEqual(
                ["CreateIntentTask", "GetTask"],
                [record["stage"] for record in failures[0]["raw"]],
            )

    def test_rejects_business_error(self):
        session = FakeSession([api_body({}, code=7, success=False)])
        client = SearchClient(config(), session)
        with self.assertRaises(FlowError):
            client.call("CreateIntentTask", {})

    def test_config_rejects_invalid_headers(self):
        env = {
            "SEARCH_API_URL": "https://example.test",
            "AUTH_TOKEN": "token",
            "DEVICE_ID": "device",
            "USER_ID": "user",
            "SEARCH_HTTP_HEADERS_JSON": "[]",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ConfigError):
                Config.from_env(Path("/does/not/exist"))

    def test_config_reads_input_output_and_duplicate_settings(self):
        """Environment configuration controls the default input and output policy."""

        env = {
            "SEARCH_API_URL": "https://example.test",
            "AUTH_TOKEN": "token",
            "DEVICE_ID": "device",
            "USER_ID": "user",
            "SEARCH_HTTP_HEADERS_JSON": "{}",
            "SEARCH_INPUT_FILE": "input/tasks_v02.jsonl",
            "SEARCH_OUTPUT_DIR": "managed-output",
            "ALLOW_DUPLICATE_RUN": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            configured = Config.from_env(Path("/does/not/exist"))

        self.assertEqual("input/tasks_v02.jsonl", configured.input_file)
        self.assertEqual("managed-output", configured.output_dir)
        self.assertTrue(configured.allow_duplicate_run)

    def test_output_paths_use_date_and_input_stem(self):
        """The first run uses the requested YYYYMMDD_input naming convention."""

        with tempfile.TemporaryDirectory() as temp_dir:
            results_path, failures_path = select_output_paths(
                Path("input/tasks_v01.jsonl"),
                Path(temp_dir),
                allow_duplicate=False,
                run_date=date(2026, 7, 22),
            )

        self.assertEqual("20260722_tasks_v01_results.jsonl", results_path.name)
        self.assertEqual("20260722_tasks_v01_failures.jsonl", failures_path.name)

    def test_duplicate_run_is_blocked_or_gets_incrementing_run_number(self):
        """Existing results are protected unless duplicate runs are explicitly allowed."""

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            first_results = output_dir / "20260722_tasks_v01_results.jsonl"
            first_failures = output_dir / "20260722_tasks_v01_failures.jsonl"
            first_results.write_text("existing", encoding="utf-8")
            first_failures.write_text("existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                select_output_paths(
                    Path("input/tasks_v01.jsonl"),
                    output_dir,
                    allow_duplicate=False,
                    run_date=date(2026, 7, 22),
                )

            second_results, second_failures = select_output_paths(
                Path("input/tasks_v01.jsonl"),
                output_dir,
                allow_duplicate=True,
                run_date=date(2026, 7, 22),
            )
            self.assertEqual("20260722_tasks_v01_run02_results.jsonl", second_results.name)
            self.assertEqual("20260722_tasks_v01_run02_failures.jsonl", second_failures.name)

            second_results.write_text("existing", encoding="utf-8")
            second_failures.write_text("existing", encoding="utf-8")
            third_results, _ = select_output_paths(
                Path("input/tasks_v01.jsonl"),
                output_dir,
                allow_duplicate=True,
                run_date=date(2026, 7, 22),
            )
            self.assertEqual("20260722_tasks_v01_run03_results.jsonl", third_results.name)


if __name__ == "__main__":
    unittest.main()
