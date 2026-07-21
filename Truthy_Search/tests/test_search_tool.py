import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from search_tool import Config, ConfigError, FlowError, SearchClient, process_one, run_batch


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
    def test_process_one_queued_then_succeeded_and_two_candidates(self):
        session = FakeSession(
            [
                api_body({"task_id": "task-1"}),
                api_body({"status": "QUEUED"}),
                api_body({"status": "SUCCEEDED"}),
                api_body({"items": [{"candidate_id": "c1"}, {"candidate_id": "c2"}]}),
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
        self.assertEqual(["c1", "c2"], [item["candidate_id"] for item in result["results"]])
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
        self.assertEqual({"page_size": 5, "page_token": ""}, list_params["page"])

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
            self.assertEqual([], results[0]["results"])
            self.assertEqual("bad", failures[0]["input_id"])
            self.assertEqual("GetTask", failures[0]["stage"])

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


if __name__ == "__main__":
    unittest.main()
