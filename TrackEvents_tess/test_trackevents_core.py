import json
import unittest

from trackevents_core import analyze_log_text


class TrackEventsCoreTest(unittest.TestCase):
    def test_sample_log_extracts_trackevents_only_and_counts_batch_events(self):
        with open("请求与响应log格式.log", "r", encoding="utf-8") as fh:
            result = analyze_log_text(fh.read())

        self.assertEqual(result["summary"]["request_count"], 6)
        self.assertEqual(result["summary"]["response_count"], 6)
        self.assertEqual(result["summary"]["event_count"], 7)
        self.assertEqual(result["event_counts"]["app_foreground"], 1)
        self.assertEqual(result["event_counts"]["app_page_stay"], 3)
        self.assertEqual(result["event_counts"]["lead_page_exit"], 1)
        self.assertNotIn("RefreshSession", result["event_counts"])
        self.assertEqual(
            [item["accepted_count"] for item in result["response_checks"]],
            [1, 1, 1, 1, 1, 2],
        )

    def test_expected_counts_are_checked_when_provided(self):
        with open("请求与响应log格式.log", "r", encoding="utf-8") as fh:
            result = analyze_log_text(
                fh.read(),
                expected_counts={"app_page_stay": 2, "app_foreground": 1},
            )

        count_checks = {item["event_name"]: item for item in result["count_checks"]}
        self.assertEqual(count_checks["app_foreground"]["status"], "pass")
        self.assertEqual(count_checks["app_page_stay"]["status"], "fail")
        self.assertEqual(count_checks["app_page_stay"]["actual"], 3)
        self.assertEqual(count_checks["app_page_stay"]["expected"], 2)

    def test_field_validation_reports_missing_business_field(self):
        log = "\n".join(
            [
                "flutter: │ [HTTP] --> POST http://x service=tool.event_tracking.EventTrackingService method=TrackEvents",
                "flutter: │ [HTTP] request:",
                "flutter: │ " + json.dumps(
                    {
                        "requests": [
                            {
                                "method_name": "TrackEvents",
                                "params": {
                                    "events": [
                                        {
                                            "event_id": "evt-1",
                                            "event_name": "app_page_stay",
                                            "event_time_ms": 1000,
                                            "properties": {
                                                "logtime": 1000,
                                                "log_id": "evt-1",
                                                "page_from": "candidate",
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                "flutter: │ [HTTP] <-- 200 POST http://x service=tool.event_tracking.EventTrackingService method=TrackEvents",
                "flutter: │ [HTTP] response:",
                'flutter: │ {"code":0,"responses":[{"success":true,"code":0,"data":{"accepted_count":1}}]}',
            ]
        )

        result = analyze_log_text(log)

        self.assertEqual(result["events"][0]["status"], "fail")
        self.assertIn("缺少业务子参: duration_s", result["events"][0]["errors"])

    def test_event_detail_contains_business_param_keys(self):
        with open("请求与响应log格式.log", "r", encoding="utf-8") as fh:
            result = analyze_log_text(fh.read())

        page_stay = next(item for item in result["events"] if item["event_name"] == "app_page_stay")
        foreground = next(item for item in result["events"] if item["event_name"] == "app_foreground")

        self.assertEqual(page_stay["required_params"], ["duration_s", "page_from"])
        self.assertEqual(foreground["required_params"], [])

    def test_event_detail_contains_business_param_values(self):
        log = "\n".join(
            [
                "flutter: │ [HTTP] --> POST http://x service=tool.event_tracking.EventTrackingService method=TrackEvents",
                "flutter: │ [HTTP] request:",
                "flutter: │ " + json.dumps(
                    {
                        "requests": [
                            {
                                "method_name": "TrackEvents",
                                "params": {
                                    "events": [
                                        {
                                            "event_id": "evt-1",
                                            "event_name": "app_start",
                                            "event_time_ms": 1000,
                                            "properties": {
                                                "logtime": 1000,
                                                "log_id": "evt-1",
                                                "is_first": 0,
                                                "search_count": 11,
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            ]
        )

        result = analyze_log_text(log)

        self.assertEqual(
            result["events"][0]["business_params"],
            {"is_first": 0, "search_count": 11},
        )

    def test_event_detail_contains_extra_param_values(self):
        log = json.dumps(
            {
                "requests": [
                    {
                        "method_name": "TrackEvents",
                        "params": {
                            "events": [
                                {
                                    "event_id": "evt-extra",
                                    "event_name": "app_start",
                                    "event_time_ms": 1000,
                                    "properties": {
                                        "logtime": 1000,
                                        "log_id": "evt-extra",
                                        "is_first": 0,
                                        "search_count": 11,
                                        "unexpected_value": "shown",
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        )

        result = analyze_log_text(log)

        self.assertEqual(result["events"][0]["extra_params"], {"unexpected_value": "shown"})

    def test_latest_paywall_rules_allow_documented_optional_fields(self):
        log = json.dumps(
            {
                "requests": [
                    {
                        "method_name": "TrackEvents",
                        "params": {
                            "events": [
                                {
                                    "event_id": "paywall-start",
                                    "event_name": "paywall_purchase_start",
                                    "event_time_ms": 1000,
                                    "properties": {
                                        "logtime": 1000,
                                        "log_id": "paywall-start",
                                        "page_from": "home",
                                        "product_id": "product-1",
                                        "store_product_id": "store-1",
                                        "billing_period": "week",
                                        "purchase_stage": "create_order",
                                    },
                                },
                                {
                                    "event_id": "paywall-restore",
                                    "event_name": "paywall_restore_success",
                                    "event_time_ms": 1001,
                                    "properties": {
                                        "logtime": 1001,
                                        "log_id": "paywall-restore",
                                        "page_from": "home",
                                    },
                                },
                            ]
                        },
                    }
                ]
            }
        )

        result = analyze_log_text(log)

        self.assertEqual(result["event_counts"]["paywall_purchase_start"], 1)
        self.assertEqual(result["event_counts"]["paywall_restore_success"], 1)
        self.assertEqual([item["status"] for item in result["events"]], ["pass", "pass"])
        action_summary = next(item for item in result["common_param_summary"] if item["key"] == "action")
        self.assertEqual(action_summary["missing_count"], 0)
        self.assertEqual(result["common_param_events"][0]["values"]["action"], "paywall_purchase_start")

    def test_event_statistics_include_module(self):
        with open("请求与响应log格式.log", "r", encoding="utf-8") as fh:
            result = analyze_log_text(fh.read())

        stats = {item["event_name"]: item for item in result["event_stats"]}

        self.assertEqual(stats["app_page_stay"]["module"], "app")
        self.assertEqual(stats["lead_page_exit"]["module"], "lead")
        self.assertEqual(stats["app_page_stay"]["count"], 3)

    def test_recovers_trackevent_when_request_json_is_interleaved(self):
        log = "\n".join(
            [
                'flutter: │ [EventTracking] name=app_start id=evt-1 time=1000 props={"is_first":0,"search_count":11}',
                "flutter: │ [HTTP] --> POST http://x service=tool.event_tracking.EventTrackingService method=TrackEvents",
                "flutter: │ [HTTP] request:",
                "flutter: │ {",
                'flutter: │   "requests": [',
                "flutter: │     {",
                'flutter: │       "method_name": "TrackEvents",',
                'flutter: │       "params": {',
                'flutter: │         "events": [',
                "flutter: │           {",
                'flutter: │             "event_id": "evt-1",',
                'flutter: │             "event_name": "app_start",',
                'flutter: │             "event_time_ms": 1000,',
                'flutter: │             "properties": {',
                'flutter: │               "logtime": 1000,',
                'flutter: │               "log_id": "evt-1",',
                "flutter: │ [HTTP] --> POST http://x service=tool.identity.IdentityService method=GetMe",
                "flutter: │ [HTTP] request:",
                'flutter: │ {"requests":[{"method_name":"GetMe","params":{}}]}',
            ]
        )

        result = analyze_log_text(log)

        self.assertEqual(result["event_counts"]["app_start"], 1)
        self.assertEqual(result["events"][0]["business_params"], {"is_first": 0, "search_count": 11})

    def test_recovers_trackevents_request_when_http_start_line_is_missing(self):
        log = "\n".join(
            [
                'flutter: │ [EventTracking] name=app_start id=evt-1 time=1000 props={"is_first":0,"search_count":11}',
                "flutter: │ {",
                'flutter: │   "requests": [',
                "flutter: │     {",
                'flutter: │       "method_name": "TrackEvents",',
                'flutter: │       "params": {',
                'flutter: │         "events": [',
                "flutter: │           {",
                'flutter: │             "event_id": "evt-1",',
                'flutter: │             "event_name": "app_start",',
                'flutter: │             "event_time_ms": 1000,',
                'flutter: │             "properties": {"logtime": 1000, "log_id": "evt-1", "is_first": 0, "search_count": 11}',
                "flutter: │           }",
                "flutter: │         ]",
                "flutter: │       }",
                "flutter: │     }",
                "flutter: │   ]",
                "flutter: │ }",
            ]
        )

        result = analyze_log_text(log)

        self.assertEqual(result["event_counts"]["app_start"], 1)
        self.assertEqual(result["events"][0]["event_id"], "evt-1")

    def test_infers_trackevents_from_request_events_when_method_is_missing(self):
        log = json.dumps(
            {
                "requests": [
                    {
                        "id": "req_0",
                        "params": {
                            "events": [
                                {
                                    "event_id": "evt-inferred-request",
                                    "event_name": "app_start",
                                    "event_time_ms": 1000,
                                    "properties": {
                                        "logtime": 1000,
                                        "log_id": "evt-inferred-request",
                                        "is_first": 0,
                                        "search_count": 11,
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        )

        result = analyze_log_text(log)

        self.assertEqual(result["summary"]["request_count"], 1)
        self.assertEqual(result["event_counts"]["app_start"], 1)

    def test_infers_trackevents_request_from_response_events_when_request_is_missing(self):
        log = json.dumps(
            {
                "code": 0,
                "responses": [
                    {
                        "success": True,
                        "code": 0,
                        "data": {
                            "accepted_count": 1,
                            "events": [
                                {
                                    "event_id": "evt-inferred-response",
                                    "event_name": "app_start",
                                    "status": "accepted",
                                }
                            ],
                        },
                    }
                ],
            }
        )

        result = analyze_log_text(log)

        self.assertEqual(result["summary"]["request_count"], 1)
        self.assertEqual(result["summary"]["response_count"], 1)
        self.assertEqual(result["event_counts"]["app_start"], 1)

    def test_response_fallback_only_adds_missing_events_from_a_batch(self):
        request = {
            "requests": [
                {
                    "method_name": "TrackEvents",
                    "params": {
                        "events": [
                            {
                                "event_id": "evt-known",
                                "event_name": "app_start",
                                "event_time_ms": 1000,
                                "properties": {
                                    "logtime": 1000,
                                    "log_id": "evt-known",
                                    "is_first": 0,
                                    "search_count": 11,
                                },
                            }
                        ]
                    },
                }
            ]
        }
        response = {
            "responses": [
                {
                    "data": {
                        "accepted_count": 2,
                        "events": [
                            {"event_id": "evt-known", "event_name": "app_start"},
                            {"event_id": "evt-missing", "event_name": "app_terminate"},
                        ],
                    }
                }
            ]
        }

        result = analyze_log_text("\n".join([json.dumps(request), json.dumps(response)]))

        self.assertEqual(result["event_counts"]["app_start"], 1)
        self.assertEqual(result["event_counts"]["app_terminate"], 1)
        self.assertEqual(result["summary"]["event_count"], 2)

    def test_default_log_counts_two_app_start_events(self):
        with open("default.log", "r", encoding="utf-8") as fh:
            result = analyze_log_text(fh.read())

        self.assertEqual(result["event_counts"]["app_start"], 2)


if __name__ == "__main__":
    unittest.main()
