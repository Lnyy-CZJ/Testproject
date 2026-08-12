import json
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from search_tool import (
    Config,
    ConfigError,
    FlowError,
    GET_TASK_FAILURE_TERMINAL_STATUSES,
    SearchClient,
    extract_admin_tool_usage,
    extract_admin_task_fields,
    load_photo_input,
    normalize_result_status,
    process_one,
    run_batch,
    select_output_paths,
    validate_input,
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
        if isinstance(body, tuple):
            return FakeResponse(body[0], status_code=body[1])
        return FakeResponse(body)


class FakePutSession:
    """记录 COS PUT，并返回测试指定的 HTTP 状态。"""

    def __init__(self, status_code=200):
        self.status_code = status_code
        self.calls = []

    def put(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse({}, status_code=self.status_code)


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
        "photo_enabled": True,
        "photo_input_dir": "input/input_photos",
        "photo_upload_host_suffixes": (".myqcloud.com",),
    }
    values.update(overrides)
    return Config(**values)


def public_info_fixture(name):
    """读取任务公共信息阶段的脱敏固定响应。"""

    return json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "v1_3_public_info"
            / name
        ).read_text(encoding="utf-8")
    )


class SearchToolTests(unittest.TestCase):
    def test_read_only_request_retries_transient_timeout_and_records_attempts(self):
        """GetTask 临时超时应短重试，且每次尝试分别进入 Raw。"""

        gateway = FakeSession(
            [
                api_body({"task_id": "task-retry-read"}),
                requests.ReadTimeout("temporary read timeout"),
                api_body({"status": "NO_RESULT", "candidate_count": 0}),
            ]
        )
        waits = []
        raw_records = []

        result = process_one(
            {
                "input_id": "case-retry-read",
                "query_stage": "FULL_NAME",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME", "value": "Retry Read"}],
                "additional_details": [],
            },
            SearchClient(config(search_retry_initial_delay_seconds=2), gateway),
            sleep_fn=waits.append,
            raw_callback=raw_records.append,
        )

        self.assertEqual("NO_CANDIDATE", result["query_status"])
        get_task_records = [
            record for record in raw_records if record["stage"] == "GetTask"
        ]
        self.assertEqual([1, 2], [record["attempt"] for record in get_task_records])
        self.assertTrue(get_task_records[0]["error"])
        self.assertFalse(get_task_records[1]["error"])
        self.assertIn(2, waits)

    def test_create_retries_dns_only_but_does_not_replay_read_timeout(self):
        """Create 仅在明确 DNS 未送达时重试，读取超时不得自动重放。"""

        dns_gateway = FakeSession(
            [
                requests.ConnectionError(
                    "Failed to resolve gateway.test: No address associated with hostname"
                ),
                api_body({"task_id": "task-create-dns"}),
                api_body({"status": "NO_RESULT", "candidate_count": 0}),
            ]
        )
        dns_raw = []
        dns_waits = []
        process_one(
            {
                "input_id": "case-create-dns",
                "query_stage": "FULL_NAME",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME", "value": "DNS Retry"}],
                "additional_details": [],
            },
            SearchClient(config(search_retry_initial_delay_seconds=2), dns_gateway),
            sleep_fn=dns_waits.append,
            raw_callback=dns_raw.append,
        )
        create_records = [
            record for record in dns_raw if record["stage"] == "CreateIntentTask"
        ]
        self.assertEqual([1, 2], [record["attempt"] for record in create_records])
        self.assertIn(2, dns_waits)

        timeout_gateway = FakeSession([requests.ReadTimeout("response lost")])
        timeout_raw = []
        with self.assertRaises(FlowError):
            process_one(
                {
                    "input_id": "case-create-timeout",
                    "query_stage": "FULL_NAME",
                    "match_strategy": "UNION",
                    "clues": [{"type": "FULL_NAME", "value": "No Replay"}],
                    "additional_details": [],
                },
                SearchClient(config(), timeout_gateway),
                sleep_fn=lambda _seconds: None,
                raw_callback=timeout_raw.append,
            )
        self.assertEqual(1, len(timeout_gateway.calls))
        self.assertEqual(
            [1],
            [
                record["attempt"]
                for record in timeout_raw
                if record["stage"] == "CreateIntentTask"
            ],
        )

    def test_candidate_detail_retries_transient_read_timeout(self):
        """Candidate Detail 临时读取超时后应重试当前候选人，不影响结果。"""

        gateway = FakeSession(
            [
                api_body({"task_id": "task-detail-retry"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 1}),
                api_body(
                    {
                        "items": [
                            {
                                "candidate_id": "candidate-retry",
                                "rank_score": 0.9,
                            }
                        ]
                    }
                ),
                requests.ReadTimeout("temporary candidate detail timeout"),
                api_body({"ui_sections": {}}),
            ]
        )
        raw_records = []
        result = process_one(
            {
                "input_id": "case-detail-retry",
                "query_stage": "FULL_NAME",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME", "value": "Detail Retry"}],
                "additional_details": [],
            },
            SearchClient(config(search_retry_initial_delay_seconds=2), gateway),
            sleep_fn=lambda _seconds: None,
            raw_callback=raw_records.append,
        )

        self.assertEqual("SUCCESS", result["query_status"])
        detail_records = [
            record
            for record in raw_records
            if record["stage"] == "GetTaskCandidateDetail"
        ]
        self.assertEqual([1, 2], [record["attempt"] for record in detail_records])
        self.assertTrue(detail_records[0]["error"])
        self.assertFalse(detail_records[1]["error"])

    def test_social_photo_query_uploads_original_jpeg_and_preserves_social_clue(self):
        """组合 Query 原样上传 JPEG，并把 Social 与运行时 PHOTO 一起提交。"""

        jpeg_bytes = b"\xff\xd8\xff\xe1Exif\x00\x00source-metadata\xff\xd9"
        upload_url = (
            "https://bucket.cos.ap-shanghai.myqcloud.com/object.jpg"
            "?q-sign-algorithm=sha1&q-signature=must-not-persist"
        )
        gateway = FakeSession(
            [
                api_body(
                    {
                        "allowed_content_types": ["image/jpeg"],
                        "max_size_bytes": 10000000,
                        "config_version": "media_upload_v4_10mb",
                        "strip_exif": True,
                        "complete_retry": {
                            "initial_delay_ms": 500,
                            "max_attempts": 3,
                            "max_delay_ms": 5000,
                        },
                    }
                ),
                api_body(
                    {
                        "media_asset_id": "media-photo-001",
                        "upload_url": upload_url,
                        "upload_method": "PUT",
                        "upload_headers": {
                            "Content-Length": str(len(jpeg_bytes)),
                            "Content-Type": "image/jpeg",
                        },
                        "content_type": "image/jpeg",
                        "size_bytes": len(jpeg_bytes),
                        "max_size_bytes": 10000000,
                        "status": "pending",
                        "expires_time": 4102444800000,
                    }
                ),
                api_body(
                    {
                        "media_asset_id": "media-photo-001",
                        "content_type": "image/jpeg",
                        "size_bytes": len(jpeg_bytes),
                        "status": "ignored-on-503",
                    }
                ),
                api_body(
                    {
                        "media_asset_id": "media-photo-001",
                        "content_type": "image/jpeg",
                        "size_bytes": len(jpeg_bytes),
                        "status": "pending",
                    }
                ),
                api_body(
                    {
                        "media_asset_id": "media-photo-001",
                        "content_type": "image/jpeg",
                        "size_bytes": len(jpeg_bytes),
                        "status": "uploaded",
                    }
                ),
                api_body({"task_id": "task-photo-001"}),
                api_body({"status": "NO_RESULT", "candidate_count": 0}),
            ]
        )
        gateway.bodies[2] = (gateway.bodies[2], 503)
        cos = FakePutSession(status_code=204)
        waits = []

        with tempfile.TemporaryDirectory() as temp_dir:
            photo_root = Path(temp_dir) / "input_photos"
            photo_root.mkdir()
            (photo_root / "person.jpg").write_bytes(jpeg_bytes)
            client = SearchClient(
                config(photo_input_dir=str(photo_root)),
                gateway,
                media_session=cos,
            )
            result = process_one(
                {
                    "input_id": "case-photo-001",
                    "query_stage": "FULL_NAME_SOCIAL_PHOTO",
                    "photo_path": "person.jpg",
                    "match_strategy": "UNION",
                    "clues": [
                        {
                            "type": "FULL_NAME",
                            "full_name_query": {"full_name": "Photo Person"},
                        },
                        {
                            "type": "SOCIAL_LINK",
                            "social_link_query": {
                                "url": "https://linkedin.com/in/photo-person",
                                "platform_hint": "linkedin",
                            },
                        },
                    ],
                    "additional_details": [],
                },
                client,
                sleep_fn=waits.append,
                run_id="run-photo-001",
            )

        self.assertEqual("1.3.2", result["result_schema_version"])
        self.assertEqual("FULL_NAME_SOCIAL_PHOTO", result["query_stage"])
        self.assertEqual("media-photo-001", result["photo_input"]["media_asset_id"])
        self.assertEqual("uploaded", result["photo_input"]["upload_status"])
        self.assertEqual(jpeg_bytes, cos.calls[0][1]["data"])
        self.assertEqual(False, cos.calls[0][1]["allow_redirects"])
        self.assertEqual(
            {"Content-Length": str(len(jpeg_bytes)), "Content-Type": "image/jpeg"},
            cos.calls[0][1]["headers"],
        )
        self.assertIn(0.5, waits)
        self.assertIn(1.0, waits)
        methods = [
            call[1]["json"]["requests"][0]["method_name"]
            for call in gateway.calls
        ]
        self.assertEqual(
            [
                "GetMediaUploadConfig",
                "PrepareMediaUpload",
                "CompleteMediaUpload",
                "CompleteMediaUpload",
                "CompleteMediaUpload",
                "CreateIntentTask",
                "GetTask",
            ],
            methods,
        )
        create_clues = gateway.calls[5][1]["json"]["requests"][0]["params"]["clues"]
        self.assertEqual(["FULL_NAME", "SOCIAL_LINK", "PHOTO"], [item["type"] for item in create_clues])
        self.assertEqual("PHOTO", create_clues[-1]["type"])
        self.assertEqual("media-photo-001", create_clues[-1]["photo_query"]["media_asset_id"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("q-signature", serialized)
        self.assertNotIn("must-not-persist", serialized)
        self.assertNotIn("source-metadata", serialized)

    def test_photo_input_contract_rejects_missing_path_and_prebuilt_photo_clue(self):
        """照片输入必须提供相对路径，且不能预置运行时 PHOTO clue。"""

        with self.assertRaisesRegex(FlowError, "photo_path"):
            validate_input(
                {
                    "input_id": "missing-photo",
                    "query_stage": "FULL_NAME_PHOTO",
                    "clues": [{"type": "FULL_NAME"}],
                },
                1,
                set(),
            )
        with self.assertRaisesRegex(FlowError, "PHOTO"):
            validate_input(
                {
                    "input_id": "prebuilt-photo",
                    "query_stage": "FULL_NAME_PHOTO",
                    "photo_path": "input_photos/person.jpg",
                    "clues": [
                        {"type": "FULL_NAME"},
                        {"type": "PHOTO", "photo_query": {"media_asset_id": "old"}},
                    ],
                },
                1,
                set(),
            )
        with self.assertRaisesRegex(FlowError, "SOCIAL_LINK"):
            validate_input(
                {
                    "input_id": "missing-social",
                    "query_stage": "FULL_NAME_SOCIAL_PHOTO",
                    "photo_path": "input_photos/person.jpg",
                    "clues": [{"type": "FULL_NAME"}],
                },
                1,
                set(),
            )

    def test_photo_file_validation_blocks_traversal_symlink_and_fake_jpeg(self):
        """本地照片读取拒绝目录逃逸、符号链接和伪造扩展名内容。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "input_photos"
            root.mkdir()
            outside = Path(temp_dir) / "outside.jpg"
            outside.write_bytes(b"\xff\xd8outside\xff\xd9")
            (root / "fake.jpg").write_bytes(b"not-a-jpeg")
            (root / "linked.jpg").symlink_to(outside)
            configured = config(photo_input_dir=str(root))

            for photo_path in ("../outside.jpg", str(outside), "linked.jpg"):
                with self.subTest(photo_path=photo_path):
                    with self.assertRaises(FlowError):
                        load_photo_input(
                            {"photo_path": photo_path},
                            configured,
                        )
            with self.assertRaisesRegex(FlowError, "JPEG"):
                load_photo_input({"photo_path": "fake.jpg"}, configured)

    def test_extract_admin_task_fields_uses_confirmed_admin_contract(self):
        """按已确认路径换算 USD 成本、PDL 调用状态和任务运行时长。"""

        debug_body = api_body(
            {
                "debug": {
                    "task": {
                        "start_time": "2026-08-05T10:14:19.126Z",
                        "finish_time": "2026-08-05T10:14:30.721Z",
                    },
                    "diagnosis": {"pdl_called": True},
                    "agent_tool_calls": [
                        {"provider": "people_data_labs", "provider_operation": "person_identify", "status": "success"},
                        {"provider": "people_data_labs", "provider_operation": "person_search", "status": "success"},
                        {"provider": "llm_search:deepseek", "provider_operation": "search", "status": "success"},
                        {"provider": "public_figure", "provider_operation": "remote_lookup", "status": "success"},
                        {"provider": "google_lens", "provider_operation": "image_search", "status": "failed"},
                        {"provider": "google_vision", "provider_operation": "face_match", "status": "success"},
                        {"provider": "social_profile", "provider_operation": "extract", "status": "success"},
                    ],
                }
            }
        )
        cost_body = api_body(
            {
                "cost_summary": {
                    "by_provider": [
                        {
                            "provider": "llm_search:deepseek",
                            "currency": "USD",
                            "total_cost_microunit": "383",
                        },
                        {
                            "provider": "llm_search:other",
                            "currency": "USD",
                            "total_cost_microunit": "17",
                        },
                        {
                            "provider": "people_data_labs",
                            "currency": "USD",
                            "total_cost_microunit": "1390000",
                        },
                        {
                            "provider": "image_search",
                            "currency": "USD",
                            "total_cost_microunit": "1000",
                        },
                        {
                            "provider": "public_figure",
                            "currency": "UNSPECIFIED",
                            "total_cost_microunit": "0",
                        },
                        {
                            "provider": "google_lens",
                            "currency": "USD",
                            "total_cost_microunit": "2000",
                            "call_count": 1,
                        },
                        {
                            "provider": "google_vision",
                            "currency": "USD",
                            "total_cost_microunit": "3000",
                            "call_count": 1,
                        },
                        {
                            "provider": "social_profile",
                            "currency": "UNSPECIFIED",
                            "total_cost_microunit": "0",
                            "call_count": 1,
                            "unpriced_call_count": "1",
                        },
                    ],
                    "by_search": [
                        {
                            "task_id": "task-other",
                            "currency": "USD",
                            "total_cost_microunit": "9999999",
                        },
                        {
                            "task_id": "task-confirmed",
                            "currency": "USD",
                            "total_cost_microunit": "1396400",
                        },
                    ],
                    "totals": [
                        {
                            "currency": "USD",
                            "total_cost_microunit": "8888888",
                        }
                    ],
                }
            }
        )

        task_fields, metadata = extract_admin_task_fields(
            task_id="task-confirmed",
            debug_body=debug_body,
            cost_body=cost_body,
        )

        self.assertEqual(0.0004, task_fields["llm_cost"])
        self.assertEqual(1.396, task_fields["third_party_cost"])
        self.assertEqual(1.3964, task_fields["total_cost"])
        self.assertIs(task_fields["pdl_called"], True)
        self.assertEqual(11595, task_fields["search_duration_ms"])
        self.assertEqual("USD", metadata["cost_currency"])
        self.assertEqual(400, metadata["llm_cost_microunit"])
        self.assertEqual(1396000, metadata["third_party_cost_microunit"])
        self.assertEqual(1396400, metadata["total_cost_microunit"])
        self.assertEqual("COMPLETE", metadata["field_mapping_status"])
        tool_usage = {
            item["key"]: item for item in metadata["tool_usage_summary"]
        }
        self.assertEqual(1, tool_usage["pdl_person_identify"]["call_count"])
        self.assertEqual(1, tool_usage["pdl_person_search"]["call_count"])
        self.assertEqual(0.0004, tool_usage["llm_search"]["cost"])
        self.assertEqual(0.002, tool_usage["google_lens"]["cost"])
        self.assertEqual(0.003, tool_usage["google_vision"]["cost"])
        self.assertEqual("UNPRICED", tool_usage["social_profile_extraction"]["cost_status"])
        # PDL Provider 同一 Query 同时执行 Identify 与 Search，成本只能保留
        # Provider 级汇总，不允许在两个工具之间擅自分摊。
        self.assertIsNone(tool_usage["pdl_person_identify"]["cost"])
        self.assertEqual(1.39, metadata["pdl_provider_cost"])
        self.assertEqual(1, metadata["wiki_call_count"])

    def test_extract_admin_tool_usage_separates_no_result_and_cache_hit(self):
        """工具状态应区分成功、无结果和真实失败。

        功能说明:
            模拟成功、缓存命中、正常无结果与明确失败四种 Debug 状态，防止
            ``no_result`` 和 ``cache_hit`` 再被报告误标为失败。

        返回值:
            无；分类计数符合接口语义即通过。

        异常说明:
            状态映射回退为旧的二分法时测试失败。
        """

        usage, _ = extract_admin_tool_usage(
            api_body({
                "debug": {
                    "agent_tool_calls": [
                        {
                            "provider": "google_vision",
                            "provider_operation": "web_detection",
                            "status": "success",
                        },
                        {
                            "provider": "google_vision",
                            "provider_operation": "web_detection",
                            "status": "cache_hit",
                        },
                        {
                            "provider": "google_vision",
                            "provider_operation": "web_detection",
                            "status": "no_result",
                        },
                        {
                            "provider": "google_vision",
                            "provider_operation": "web_detection",
                            "status": "failed",
                            "error_code": "UPSTREAM_ERROR",
                        },
                    ]
                }
            }),
            None,
        )
        google_vision = {
            item["key"]: item for item in usage
        }["google_vision"]

        self.assertEqual(4, google_vision["call_count"])
        self.assertEqual(2, google_vision["success_count"])
        self.assertEqual(1, google_vision["no_result_count"])
        self.assertEqual(1, google_vision["failed_count"])
        self.assertEqual(0, google_vision["unknown_count"])

    def test_extract_admin_task_fields_keeps_all_provider_costs_for_single_pdl_mode(self):
        """单独调用 PDL Identify 时，Provider 总额和第三方成本都不得丢失。"""

        task_fields, metadata = extract_admin_task_fields(
            task_id="task-provider-costs",
            debug_body=api_body(
                {
                    "debug": {
                        "diagnosis": {"pdl_called": True},
                        "agent_tool_calls": [
                            {
                                "provider": "people_data_labs",
                                "provider_operation": "person_identify",
                                "status": "success",
                            }
                        ],
                    }
                }
            ),
            cost_body=api_body(
                {
                    "cost_summary": {
                        "by_provider": [
                            {
                                "provider": "people_data_labs",
                                "currency": "USD",
                                "total_cost_microunit": "550000",
                                "call_count": 1,
                                "priced_call_count": 1,
                            },
                            {
                                "provider": "google_vision",
                                "currency": "USD",
                                "total_cost_microunit": "3500",
                                "call_count": 1,
                                "priced_call_count": 1,
                            },
                            {
                                "provider": "searchapi_google_lens",
                                "currency": "USD",
                                "total_cost_microunit": "3000",
                                "call_count": 1,
                                "priced_call_count": 1,
                            },
                            {
                                "provider": "social_profile",
                                "currency": "USD",
                                "total_cost_microunit": "1880",
                                "call_count": 1,
                                "priced_call_count": 1,
                            },
                            {
                                "provider": "social_profile",
                                "currency": "UNSPECIFIED",
                                "total_cost_microunit": "0",
                                "call_count": 1,
                                "non_billable_call_count": 1,
                            },
                            {
                                "provider": "llm_search:deepseek",
                                "currency": "USD",
                                "total_cost_microunit": "286",
                                "call_count": 1,
                                "priced_call_count": 1,
                            },
                        ],
                        "by_search": [
                            {
                                "task_id": "task-provider-costs",
                                "currency": "USD",
                                "total_cost_microunit": "558666",
                            }
                        ],
                    }
                }
            ),
        )

        self.assertEqual(0.000286, task_fields["llm_cost"])
        self.assertEqual(0.55838, task_fields["third_party_cost"])
        self.assertEqual(0.558666, task_fields["total_cost"])
        self.assertEqual(0.55, metadata["pdl_provider_cost"])
        self.assertEqual("PRICED", metadata["pdl_provider_cost_status"])
        self.assertEqual(0.55, metadata["pdl_person_identify_cost"])
        self.assertEqual(0.003, metadata["google_lens_cost"])
        self.assertEqual(0.0035, metadata["google_vision_cost"])
        self.assertEqual(0.00188, metadata["social_profile_extraction_cost"])
        details = {
            item["provider"]: item
            for item in metadata["provider_cost_details"]
        }
        self.assertEqual(0.55, details["people_data_labs"]["cost"])
        self.assertEqual(0.00188, details["social_profile"]["cost"])
        self.assertEqual(2, details["social_profile"]["call_count"])
        self.assertEqual(1, details["social_profile"]["non_billable_call_count"])

    def test_extract_admin_task_fields_keeps_zero_distinct_from_missing(self):
        """真实零成本和 False 正常落库，未返回的字段继续保持空值。"""

        task_fields, metadata = extract_admin_task_fields(
            task_id="task-zero",
            debug_body=api_body(
                {
                    "debug": {
                        "task": {"start_time": "2026-08-05T10:00:00Z"},
                        "diagnosis": {"pdl_called": False},
                    }
                }
            ),
            cost_body=api_body(
                {
                    "cost_summary": {
                        "by_provider": [
                            {
                                "provider": "llm_search:deepseek",
                                "currency": "USD",
                                "total_cost_microunit": "0",
                            }
                        ],
                        "by_search": [
                            {
                                "task_id": "task-zero",
                                "currency": "USD",
                                "total_cost_microunit": "0",
                            }
                        ],
                        "totals": [],
                    }
                }
            ),
        )

        self.assertEqual(0.0, task_fields["llm_cost"])
        self.assertEqual(0.0, task_fields["third_party_cost"])
        self.assertEqual(0.0, task_fields["total_cost"])
        self.assertIs(task_fields["pdl_called"], False)
        self.assertIsNone(task_fields["search_duration_ms"])
        self.assertEqual("PARTIAL", metadata["field_mapping_status"])

        missing_fields, missing_metadata = extract_admin_task_fields(
            task_id="task-missing",
            debug_body=None,
            cost_body=None,
        )
        self.assertTrue(all(value is None for value in missing_fields.values()))
        self.assertEqual("NOT_MAPPED", missing_metadata["field_mapping_status"])

    def test_extract_admin_task_fields_maps_confirmed_no_charge_to_zero(self):
        """Admin 已确认成本完整且无计费记录时应映射为真实零成本。

        功能说明:
            覆盖缓存命中和全部非计费调用的共同接口语义：成本接口成功
            返回完整汇总，但没有 USD 计费行，此时三个成本字段应为 0。

        返回值:
            无；成本字段与微单位均为 0 且映射状态完整即通过。

        异常说明:
            空汇总仍被误判为字段未接入时测试失败。
        """

        task_fields, metadata = extract_admin_task_fields(
            task_id="task-confirmed-free",
            debug_body=api_body({
                "debug": {
                    "task": {
                        "start_time": "2026-08-11T03:18:43.215Z",
                        "finish_time": "2026-08-11T03:18:43.224Z",
                    },
                    "diagnosis": {
                        "cost_complete": True,
                        "pdl_called": False,
                    },
                    "agent_tool_calls": [],
                }
            }),
            cost_body=api_body({
                "cost_summary": {
                    "by_provider": [],
                    "by_search": [],
                    "by_worker": [],
                    "calls": [],
                    "totals": [],
                }
            }),
        )

        self.assertEqual(0.0, task_fields["llm_cost"])
        self.assertEqual(0.0, task_fields["third_party_cost"])
        self.assertEqual(0.0, task_fields["total_cost"])
        self.assertIs(task_fields["pdl_called"], False)
        self.assertEqual(9, task_fields["search_duration_ms"])
        self.assertEqual(0, metadata["llm_cost_microunit"])
        self.assertEqual(0, metadata["third_party_cost_microunit"])
        self.assertEqual(0, metadata["total_cost_microunit"])
        self.assertEqual("COMPLETE", metadata["field_mapping_status"])

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

        self.assertEqual("1.3.2", result["result_schema_version"])
        self.assertEqual("run-v13", result["run_id"])
        self.assertEqual("FULL_NAME_SOCIAL", result["query_stage"])
        self.assertEqual("PARTIAL_DETAIL_FAILED", result["query_status"])
        self.assertEqual("HAS_CANDIDATES", result["result_status"])
        self.assertEqual(
            {
                "llm_cost": None,
                "third_party_cost": None,
                "total_cost": None,
                "pdl_called": None,
                "search_duration_ms": None,
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
        self.assertEqual("1.3.2", failure["failure_schema_version"])
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

        self.assertEqual([5, 5, 1.0], sleeps)
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
        """验证 SEARCHING 后转为 SUCCEEDED 会继续获取候选列表和详情。"""

        session = FakeSession(
            [
                api_body({"task_id": "task-searching"}),
                api_body({"status": "SEARCHING"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 1}),
                api_body({"items": [{"candidate_id": "candidate-searching"}]}),
                api_body({"ui_sections": {}}),
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

        self.assertEqual([5, 5, 1.0], sleeps)
        self.assertEqual("SUCCESS", result["query_status"])
        self.assertEqual("HAS_CANDIDATES", result["result_status"])
        self.assertEqual(1, result["candidate_count_total"])
        self.assertEqual(1, result["candidate_count_listed"])
        methods = [call[1]["json"]["requests"][0]["method_name"] for call in session.calls]
        self.assertEqual(
            [
                "CreateIntentTask",
                "GetTask",
                "GetTask",
                "ListTaskCandidates",
                "GetTaskCandidateDetail",
            ],
            methods,
        )

    def test_process_one_no_result_skips_list_and_detail_requests(self):
        """验证 GetTask 的 NO_RESULT 是唯一跳过后续接口的无候选人终态。"""

        session = FakeSession(
            [
                api_body({"task_id": "task-no-result"}),
                api_body({"status": "NO_RESULT", "candidate_count": 9}),
            ]
        )
        result = process_one(
            {
                "input_id": "case-no-result",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            SearchClient(config(), session),
            sleep_fn=lambda _: None,
        )

        self.assertEqual("NO_CANDIDATE", result["query_status"])
        self.assertEqual("NO_CANDIDATES", result["result_status"])
        self.assertEqual(0, result["candidate_count_total"])
        self.assertEqual(0, result["candidate_count_listed"])
        methods = [call[1]["json"]["requests"][0]["method_name"] for call in session.calls]
        self.assertEqual(["CreateIntentTask", "GetTask"], methods)

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
            self.assertEqual("1.3.2", failures[0]["failure_schema_version"])
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

    def test_config_reads_photo_settings_without_changing_default_off_state(self):
        """照片配置使用严格开关和逗号分隔 Host，默认仍保持关闭。"""

        base = {
            "SEARCH_API_URL": "https://example.test",
            "AUTH_TOKEN": "token",
            "DEVICE_ID": "device",
            "USER_ID": "user",
            "SEARCH_HTTP_HEADERS_JSON": "{}",
        }
        with patch.dict("os.environ", base, clear=True):
            default_config = Config.from_env(Path("/does/not/exist"))
        with patch.dict(
            "os.environ",
            {
                **base,
                "SEARCH_PHOTO_ENABLED": "true",
                "SEARCH_PHOTO_INPUT_DIR": "/app/input/input_photos",
                "SEARCH_PHOTO_UPLOAD_HOST_SUFFIXES": ".myqcloud.com,.example-cos.test",
            },
            clear=True,
        ):
            photo_config = Config.from_env(Path("/does/not/exist"))

        self.assertFalse(default_config.photo_enabled)
        self.assertTrue(photo_config.photo_enabled)
        self.assertEqual("/app/input/input_photos", photo_config.photo_input_dir)
        self.assertEqual(
            (".myqcloud.com", ".example-cos.test"),
            photo_config.photo_upload_host_suffixes,
        )

    def test_cos_put_accepts_confirmed_statuses_and_rejects_host_boundary_bypass(self):
        """COS PUT 只接受确认的 2xx，并按域名边界阻止伪造 Host。"""

        for status_code in (200, 201, 204):
            with self.subTest(status_code=status_code):
                cos = FakePutSession(status_code=status_code)
                client = SearchClient(config(), FakeSession([]), media_session=cos)
                returned = client.put_media_binary(
                    "https://bucket.cos.myqcloud.com/object.jpg?signature=secret",
                    {"Content-Length": "4", "Content-Type": "image/jpeg"},
                    b"test",
                )
                self.assertEqual(status_code, returned)
        blocked = FakePutSession()
        client = SearchClient(config(), FakeSession([]), media_session=blocked)
        with self.assertRaisesRegex(FlowError, "允许的域名"):
            client.put_media_binary(
                "https://evilmyqcloud.com/object.jpg?signature=secret",
                {"Content-Length": "4", "Content-Type": "image/jpeg"},
                b"test",
            )
        self.assertEqual([], blocked.calls)

    def test_config_reloads_updated_secret_file_without_process_cache(self):
        """每次创建配置都读取最新 Secret，且不得把凭证写入全局环境。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "searchtool.env"

            def write_secret(token: str) -> None:
                """写入当前测试所需的最小 Secret 配置。"""

                env_file.write_text(
                    "\n".join(
                        [
                            "SEARCH_API_URL=https://secret-file.test/rpc",
                            "SEARCH_HTTP_HEADERS_JSON={}",
                            f"AUTH_TOKEN={token}",
                            "DEVICE_ID=file-device",
                            "USER_ID=file-user",
                        ]
                    ),
                    encoding="utf-8",
                )

            with patch.dict("os.environ", {}, clear=True):
                write_secret("old-file-token")
                first = Config.from_env(env_file)
                write_secret("new-file-token")
                second = Config.from_env(env_file)

                self.assertNotIn("AUTH_TOKEN", os.environ)

        self.assertEqual("old-file-token", first.auth_token)
        self.assertEqual("new-file-token", second.auth_token)

    def test_platform_environment_overrides_secret_file(self):
        """平台显式环境变量应覆盖 Secret 文件中的同名配置。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "searchtool.env"
            env_file.write_text(
                "\n".join(
                    [
                        "SEARCH_API_URL=https://secret-file.test/rpc",
                        "SEARCH_HTTP_HEADERS_JSON={}",
                        "AUTH_TOKEN=file-token",
                        "DEVICE_ID=file-device",
                        "USER_ID=file-user",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "AUTH_TOKEN": "platform-token",
                    "DEVICE_ID": "platform-device",
                },
                clear=True,
            ):
                configured = Config.from_env(env_file)

        self.assertEqual("platform-token", configured.auth_token)
        self.assertEqual("platform-device", configured.device_id)
        self.assertEqual("file-user", configured.user_id)

    def test_invalid_admin_config_does_not_block_search_config(self):
        """Admin 配置缺失只关闭公共采集，不能让原 Search 配置加载失败。"""

        env = {
            "SEARCH_API_URL": "https://example.test",
            "AUTH_TOKEN": "token",
            "DEVICE_ID": "device",
            "USER_ID": "user",
            "SEARCH_HTTP_HEADERS_JSON": "{}",
            "SEARCH_ADMIN_ENABLED": "true",
            "SEARCH_ADMIN_HTTP_HEADERS_JSON": "[]",
        }
        with patch.dict("os.environ", env, clear=True):
            configured = Config.from_env(Path("/does/not/exist"))

        self.assertTrue(configured.admin_enabled)
        self.assertIn("必须是合法 JSON", configured.admin_config_error)

    def test_admin_public_info_order_and_raw_contract(self):
        """终态后按 Login、Debug、Cost、List 顺序采集并保留脱敏 Raw。"""

        search_session = FakeSession(
            [
                api_body({"task_id": "task-admin"}),
                api_body({"status": "SUCCEEDED", "candidate_count": 0}),
                api_body({"items": []}),
            ]
        )
        admin_session = FakeSession(
            [
                public_info_fixture("admin_login_success.json"),
                public_info_fixture("get_search_task_debug_success.json"),
                public_info_fixture("get_provider_cost_summary_success.json"),
            ]
        )
        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            search_session,
            admin_session,
        )
        sleeps = []
        raw_events = []
        progress_events = []
        result = process_one(
            {
                "input_id": "case-admin",
                "query_stage": "FULL_NAME",
                "match_strategy": "UNION",
                "clues": [
                    {
                        "type": "FULL_NAME",
                        "full_name_query": {"full_name": "Example Person"},
                    }
                ],
                "additional_details": [],
            },
            client,
            sleep_fn=sleeps.append,
            progress_callback=progress_events.append,
            raw_callback=raw_events.append,
            run_id="run-admin",
        )

        self.assertEqual([5, 1.0], sleeps)
        self.assertEqual(
            [
                "CreateIntentTask",
                "GetTask",
                "AdminLogin",
                "GetSearchTaskDebug",
                "GetProviderCostSummary",
                "ListTaskCandidates",
            ],
            [record["stage"] for record in raw_events],
        )
        self.assertEqual("COMPLETE", result["public_fields"]["public_info_status"])
        self.assertIs(result["public_fields"]["cache_hit"], False)
        serialized = json.dumps(raw_events, ensure_ascii=False)
        self.assertNotIn("fixture-session-token", serialized)
        self.assertNotIn("fixture-password", serialized)
        progress_stages = [event.get("stage") for event in progress_events]
        self.assertIn("PublicInfoDelay", progress_stages)
        self.assertIn("AdminLogin", progress_stages)
        self.assertIn("GetSearchTaskDebug", progress_stages)
        self.assertIn("GetProviderCostSummary", progress_stages)

    def test_admin_session_is_reused_across_queries(self):
        """同一个 SearchClient 处理多个 Query 时只登录一次。"""

        search_session = FakeSession(
            [
                api_body({"task_id": "task-1"}),
                api_body({"status": "NO_RESULT"}),
                api_body({"task_id": "task-2"}),
                api_body({"status": "NO_RESULT"}),
            ]
        )
        admin_session = FakeSession(
            [
                public_info_fixture("admin_login_success.json"),
                public_info_fixture("get_search_task_debug_success.json"),
                public_info_fixture("get_provider_cost_summary_success.json"),
                public_info_fixture("get_search_task_debug_success.json"),
                public_info_fixture("get_provider_cost_summary_success.json"),
            ]
        )
        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            search_session,
            admin_session,
        )
        for input_id in ("case-1", "case-2"):
            process_one(
                {
                    "input_id": input_id,
                    "query_stage": "FULL_NAME",
                    "match_strategy": "UNION",
                    "clues": [{"type": "FULL_NAME"}],
                    "additional_details": [],
                },
                client,
                sleep_fn=lambda _: None,
                run_id="run-reuse",
            )

        login_calls = [call for call in admin_session.calls if call[0].endswith("/admin/invoke")]
        self.assertEqual(1, len(login_calls))

    def test_admin_refreshes_with_less_than_one_hour_remaining(self):
        """Token 剩余不足一小时会在下次公共请求前更新。"""

        admin_session = FakeSession([public_info_fixture("admin_login_success.json")])
        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            FakeSession([]),
            admin_session,
        )
        client.admin_client.session_token = "old-token"
        client.admin_client.expire_time = datetime.now(timezone.utc) + timedelta(minutes=59)
        client.admin_client.operator_id = "old-id"
        client.admin_client.operator_name = "old-name"

        client.admin_client.ensure_session()

        self.assertEqual(1, len(admin_session.calls))
        self.assertEqual("fixture-session-token", client.admin_client.session_token)

    def test_admin_reuses_token_with_more_than_one_hour_remaining(self):
        """Token 剩余 61 分钟时继续复用，不产生额外 Login 请求。"""

        admin_session = FakeSession([])
        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            FakeSession([]),
            admin_session,
        )
        client.admin_client.session_token = "fresh-token"
        client.admin_client.expire_time = datetime.now(timezone.utc) + timedelta(minutes=61)
        client.admin_client.operator_id = "operator-id"
        client.admin_client.operator_name = "operator-name"

        client.admin_client.ensure_session()

        self.assertEqual([], admin_session.calls)

    def test_debug_failure_does_not_block_cost_or_main_list(self):
        """Debug 独立失败时仍调用 Cost 与原 List，并将采集结果标记为 PARTIAL。"""

        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            FakeSession(
                [
                    api_body({"task_id": "task-partial"}),
                    api_body({"status": "SUCCEEDED"}),
                    api_body({"items": []}),
                ]
            ),
            FakeSession(
                [
                    public_info_fixture("admin_login_success.json"),
                    api_body({}, code=7, success=False),
                    public_info_fixture("get_provider_cost_summary_success.json"),
                ]
            ),
        )

        result = process_one(
            {
                "input_id": "case-partial",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=lambda _: None,
        )

        self.assertEqual("PARTIAL", result["public_fields"]["public_info_status"])
        self.assertEqual("FAILED", result["public_fields"]["debug_collection_status"])
        self.assertEqual("SUCCESS", result["public_fields"]["cost_collection_status"])
        self.assertEqual(
            "ListTaskCandidates",
            client.session.calls[-1][1]["json"]["requests"][0]["method_name"],
        )

    def test_empty_cost_response_retries_once_after_short_delay(self):
        """成本数据首次为空时仅短重试一次，并保留两次请求 Raw。"""

        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            FakeSession(
                [
                    api_body({"task_id": "task-cost-retry"}),
                    api_body({"status": "NO_RESULT"}),
                ]
            ),
            FakeSession(
                [
                    public_info_fixture("admin_login_success.json"),
                    public_info_fixture("get_search_task_debug_success.json"),
                    api_body({}),
                    public_info_fixture("get_provider_cost_summary_success.json"),
                ]
            ),
        )
        sleeps = []
        raw_events = []

        result = process_one(
            {
                "input_id": "case-cost-retry",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=sleeps.append,
            raw_callback=raw_events.append,
        )

        self.assertEqual([5, 1.0, 1.0], sleeps)
        self.assertEqual(
            [1, 2],
            [
                record["sequence_no"]
                for record in raw_events
                if record["stage"] == "GetProviderCostSummary"
            ],
        )

    def test_auth_failure_relogs_and_replays_only_once(self):
        """服务端认证失败触发一次重新登录，并记录失败与成功两次尝试。"""

        auth_failure = api_body({}, code=401, success=False)
        search_session = FakeSession(
            [
                api_body({"task_id": "task-auth"}),
                api_body({"status": "NO_RESULT"}),
            ]
        )
        admin_session = FakeSession(
            [
                public_info_fixture("admin_login_success.json"),
                auth_failure,
                public_info_fixture("admin_login_success.json"),
                public_info_fixture("get_search_task_debug_success.json"),
                public_info_fixture("get_provider_cost_summary_success.json"),
            ]
        )
        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            search_session,
            admin_session,
        )
        raw_events = []
        result = process_one(
            {
                "input_id": "case-auth",
                "query_stage": "FULL_NAME",
                "match_strategy": "UNION",
                "clues": [{"type": "FULL_NAME"}],
                "additional_details": [],
            },
            client,
            sleep_fn=lambda _: None,
            raw_callback=raw_events.append,
        )

        debug_events = [
            record for record in raw_events if record["stage"] == "GetSearchTaskDebug"
        ]
        self.assertEqual([1, 2], [record["attempt"] for record in debug_events])
        self.assertTrue(debug_events[0]["error"])
        self.assertFalse(debug_events[1]["error"])
        self.assertEqual(2, sum(record["stage"] == "AdminLogin" for record in raw_events))
        self.assertEqual(2, len(result["raw"]["get_search_task_debug_history"]))

    def test_failure_terminal_preserves_public_info(self):
        """GetTask 失败终态采集公共信息后仍抛出 Query 级失败。"""

        self.assertIn("FAILED", GET_TASK_FAILURE_TERMINAL_STATUSES)
        client = SearchClient(
            config(
                admin_enabled=True,
                admin_login_api_url="https://admin.test/admin/invoke",
                admin_api_url="https://admin.test/gateway/invoke",
                admin_headers={},
                admin_username="fixture-admin",
                admin_password="fixture-password",
            ),
            FakeSession(
                [
                    api_body({"task_id": "task-failed"}),
                    api_body({"status": "FAILED"}),
                ]
            ),
            FakeSession(
                [
                    public_info_fixture("admin_login_success.json"),
                    public_info_fixture("get_search_task_debug_success.json"),
                    public_info_fixture("get_provider_cost_summary_success.json"),
                ]
            ),
        )
        with self.assertRaises(FlowError) as context:
            process_one(
                {
                    "input_id": "case-failed",
                    "query_stage": "FULL_NAME",
                    "match_strategy": "UNION",
                    "clues": [{"type": "FULL_NAME"}],
                    "additional_details": [],
                },
                client,
                sleep_fn=lambda _: None,
            )

        self.assertEqual("COMPLETE", context.exception.public_fields["public_info_status"])
        self.assertEqual(
            ["AdminLogin", "GetSearchTaskDebug", "GetProviderCostSummary"],
            [
                record["stage"]
                for record in context.exception.raw_records
                if record["stage"].startswith("Admin")
                or record["stage"].startswith("GetSearch")
                or record["stage"].startswith("GetProvider")
            ],
        )

    def test_query_chain_log_is_complete_unique_and_sanitized(self):
        """人物日志逐事件写入、同名不覆盖且不包含认证秘密。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(2):
                client = SearchClient(
                    config(
                        admin_enabled=True,
                        admin_login_api_url="https://admin.test/admin/invoke",
                        admin_api_url="https://admin.test/gateway/invoke",
                        admin_headers={},
                        admin_username="fixture-admin",
                        admin_password="fixture-password",
                        query_log_enabled=True,
                        query_log_dir=str(root),
                    ),
                    FakeSession(
                        [
                            api_body({"task_id": f"task-log-{index}"}),
                            api_body({"status": "SUCCEEDED"}),
                            api_body(
                                {
                                    "items": [
                                        {
                                            "candidate_id": f"candidate-log-{index}",
                                            "rank_score": 0.9,
                                        }
                                    ]
                                }
                            ),
                            api_body({"ui_sections": {}}),
                        ]
                    ),
                    FakeSession(
                        [
                            public_info_fixture("admin_login_success.json"),
                            public_info_fixture("get_search_task_debug_success.json"),
                            public_info_fixture("get_provider_cost_summary_success.json"),
                        ]
                    ),
                )
                process_one(
                    {
                        "input_id": f"case-log-{index}",
                        "query_stage": "FULL_NAME",
                        "match_strategy": "UNION",
                        "clues": [
                            {
                                "type": "FULL_NAME",
                                "full_name_query": {
                                    "full_name": "../Example / 人物\n"
                                },
                            }
                        ],
                        "additional_details": [],
                    },
                    client,
                    sleep_fn=lambda _: None,
                    run_id="run-log",
                    run_name="Regression Run / v1",
                )

            log_paths = sorted(root.glob("*/*/*.log"))
            self.assertEqual(2, len(log_paths))
            self.assertNotEqual(log_paths[0].name, log_paths[1].name)
            self.assertTrue(all(".." not in path.name for path in log_paths))
            self.assertTrue(
                all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.parent.name)
                    for path in log_paths)
            )
            self.assertTrue(
                all(path.parent.name == "Regression_Run___v1" for path in log_paths)
            )
            self.assertTrue(
                all(
                    re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}_.+\.log$", path.name)
                    for path in log_paths
                )
            )
            content = log_paths[0].read_text(encoding="utf-8")
            for stage in (
                "QueryStart",
                "CreateIntentTask",
                "GetTask",
                "AdminLogin",
                "GetSearchTaskDebug",
                "GetProviderCostSummary",
                "ListTaskCandidates",
                "GetTaskCandidateDetail",
                "QueryEnd",
            ):
                self.assertIn(stage, content)
            self.assertIn("脱敏请求数据", content)
            self.assertIn("响应数据: HTTP 200", content)
            self.assertIn('\n{\n  "', content)
            self.assertNotIn("fixture-password", content)
            self.assertNotIn("fixture-session-token", content)

    def test_query_log_explains_admin_not_configured(self):
        """Admin 未配置时也要在人物日志明确记录三个阶段未执行的原因。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            process_one(
                {
                    "input_id": "case-admin-disabled",
                    "query_stage": "FULL_NAME",
                    "match_strategy": "UNION",
                    "clues": [{"type": "FULL_NAME"}],
                    "additional_details": [],
                },
                SearchClient(
                    config(
                        query_log_enabled=True,
                        query_log_dir=temp_dir,
                    ),
                    FakeSession(
                        [
                            api_body({"task_id": "task-admin-disabled"}),
                            api_body({"status": "NO_RESULT"}),
                        ]
                    ),
                ),
                sleep_fn=lambda _: None,
            )

            log_path = next(Path(temp_dir).glob("*/*/*.log"))
            content = log_path.read_text(encoding="utf-8")

        for stage in (
            "AdminLogin",
            "GetSearchTaskDebug",
            "GetProviderCostSummary",
        ):
            self.assertIn(stage, content)
        self.assertIn("NOT_CONFIGURED", content)
        self.assertIn("未执行", content)

    def test_query_log_explains_cost_skipped_after_admin_login_failure(self):
        """Login 失败时 Cost 未实际请求，也必须在日志标记 AUTH_FAILED。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            process_one(
                {
                    "input_id": "case-admin-auth-failed",
                    "query_stage": "FULL_NAME",
                    "match_strategy": "UNION",
                    "clues": [{"type": "FULL_NAME"}],
                    "additional_details": [],
                },
                SearchClient(
                    config(
                        admin_enabled=True,
                        admin_login_api_url="https://admin.test/admin/invoke",
                        admin_api_url="https://admin.test/gateway/invoke",
                        admin_headers={},
                        admin_username="fixture-admin",
                        admin_password="fixture-password",
                        query_log_enabled=True,
                        query_log_dir=temp_dir,
                    ),
                    FakeSession(
                        [
                            api_body({"task_id": "task-admin-auth-failed"}),
                            api_body({"status": "NO_RESULT"}),
                        ]
                    ),
                    FakeSession([api_body({}, code=401, success=False)]),
                ),
                sleep_fn=lambda _: None,
            )

            log_path = next(Path(temp_dir).glob("*/*/*.log"))
            content = log_path.read_text(encoding="utf-8")

        for stage in (
            "AdminLogin",
            "GetSearchTaskDebug",
            "GetProviderCostSummary",
        ):
            self.assertIn(stage, content)
        self.assertIn("AUTH_FAILED", content)
        self.assertIn("未执行", content)

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
