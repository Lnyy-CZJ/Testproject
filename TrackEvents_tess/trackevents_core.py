from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any


COMMON_PROPERTY_KEYS = {
    "logtime",
    "log_id",
    "net",
    "pkg",
    "bucket",
    "abslot",
    "ram",
    "cpu",
    "sh",
    "sw",
    "city",
    "ste",
    "lat",
    "lng",
    "sty",
    "isp",
    "mod",
    "brd",
    "os",
    "pf",
    "slan",
    "reg",
    "cou",
    "sub",
    "cha",
    "verc",
    "ver",
    "sid",
    "uuid",
    "idfa",
    "idfv",
    "aid",
    "gaid",
    "did",
    "uid",
    "anm",
    "push_id",
    "push_type",
    "is_pro",
}

# Synced from 产品埋点需求文档/需求埋点list(维护最新版).xlsx, sheet 公参定义.
COMMON_PARAM_RULES = [
    {"key": "ip", "required": True, "allow_empty": True},
    {"key": "slogtime", "required": True, "allow_empty": False},
    {"key": "logtime", "required": True, "allow_empty": False},
    {"key": "action", "required": True, "allow_empty": False},
    {"key": "log_id", "required": True, "allow_empty": False},
    {"key": "net", "required": True, "allow_empty": False},
    {"key": "pkg", "required": True, "allow_empty": False},
    {"key": "bucket", "required": True, "allow_empty": False},
    {"key": "abslot", "required": True, "allow_empty": False},
    {"key": "ram", "required": True, "allow_empty": True},
    {"key": "cpu", "required": True, "allow_empty": True},
    {"key": "sh", "required": True, "allow_empty": True},
    {"key": "sw", "required": True, "allow_empty": True},
    {"key": "city", "required": True, "allow_empty": True},
    {"key": "ste", "required": True, "allow_empty": True},
    {"key": "lat", "required": True, "allow_empty": True},
    {"key": "lng", "required": True, "allow_empty": True},
    {"key": "sty", "required": True, "allow_empty": True},
    {"key": "isp", "required": True, "allow_empty": False},
    {"key": "mod", "required": True, "allow_empty": False},
    {"key": "brd", "required": True, "allow_empty": False},
    {"key": "os", "required": True, "allow_empty": False},
    {"key": "pf", "required": True, "allow_empty": False},
    {"key": "slan", "required": True, "allow_empty": True},
    {"key": "reg", "required": True, "allow_empty": True},
    {"key": "cou", "required": True, "allow_empty": False},
    {"key": "sub", "required": True, "allow_empty": False},
    {"key": "cha", "required": True, "allow_empty": False},
    {"key": "verc", "required": True, "allow_empty": False},
    {"key": "ver", "required": True, "allow_empty": False},
    {"key": "sid", "required": True, "allow_empty": False},
    {"key": "idfa", "required": True, "allow_empty": True},
    {"key": "idfv", "required": True, "allow_empty": True},
    {"key": "aid", "required": True, "allow_empty": True},
    {"key": "gaid", "required": True, "allow_empty": True},
    {"key": "did", "required": True, "allow_empty": False},
    {"key": "uid", "required": True, "allow_empty": True},
    {"key": "anm", "required": True, "allow_empty": False},
    {"key": "push_id", "required": True, "allow_empty": True},
    {"key": "push_type", "required": True, "allow_empty": True},
    {"key": "is_pro", "required": True, "allow_empty": False},
    {"key": "uuid", "required": True, "allow_empty": False},
]
COMMON_PROPERTY_KEYS.update(rule["key"] for rule in COMMON_PARAM_RULES)


EVENT_RULES: dict[str, dict[str, Any]] = {
    "app_start": {"module": "app", "params": ["is_first", "search_count"]},
    "app_push_start": {"module": "app", "params": []},
    "app_foreground": {"module": "app", "params": []},
    "app_terminate": {"module": "app", "params": ["page_from"]},
    "app_time": {"module": "app", "params": ["duration_s"]},
    "install": {"module": "app", "params": ["content"]},
    "app_page_show": {"module": "app", "params": ["page_from", "duration_s"]},
    "app_page_stay": {"module": "app", "params": ["page_from", "duration_s"]},
    "app_heartbeat": {"module": "app", "params": ["type", "duration_s"]},
    "app_pro": {"module": "app", "params": ["is_pro", "product_id"]},
    "home_pageview": {"module": "home", "params": []},
    "home_searchbox_click": {"module": "home", "params": []},
    "home_popular_click": {"module": "home", "params": ["item_id"]},
    "home_history_click": {"module": "home", "params": []},
    "home_pro_click": {"module": "home", "params": []},
    "home_myaccount_click": {"module": "home", "params": []},
    "lead_pageview": {"module": "lead", "params": ["page_from", "has_name"]},
    "lead_enrich_click": {"module": "lead", "params": ["status"]},
    "lead_name_input_start": {"module": "lead", "params": []},
    "lead_photo_add_click": {"module": "lead", "params": ["from"]},
    "lead_photo_upload_success": {"module": "lead", "params": []},
    "lead_photo_upload_fail": {"module": "lead", "params": ["fail_reason"]},
    "lead_social_input_start": {"module": "lead", "params": []},
    "lead_social_add_click": {"module": "lead", "params": []},
    "lead_social_input_suc": {"module": "lead", "params": ["platform"]},
    "lead_social_input_fail": {"module": "lead", "params": ["fail_reason"]},
    "lead_location_input_start": {"module": "lead", "params": []},
    "lead_details_add_start": {"module": "lead", "params": []},
    "lead_details_add_click": {"module": "lead", "params": ["add_type"]},
    "lead_search_submit_click": {"module": "lead", "params": ["is_pro", "clue"]},
    "lead_leave_dialogview": {"module": "lead", "params": []},
    "lead_leave_stay_click": {"module": "lead", "params": []},
    "lead_leave_leave_click": {"module": "lead", "params": []},
    "lead_page_exit": {"module": "lead", "params": ["has_search", "has_name", "add_type"]},
    "search_fake_pageview": {"module": "search_fake", "params": []},
    "search_fake_page_exit": {"module": "search_fake", "params": []},
    "paywall_pageview": {"module": "paywall", "params": ["page_from"]},
    "paywall_product_load_start": {"module": "paywall", "params": ["page_from"]},
    "paywall_product_load_success": {"module": "paywall", "params": ["page_from", "products_count"]},
    "paywall_product_load_fail": {
        "module": "paywall",
        "params": ["page_from", "fail_reason", "error_code"],
        "optional_params": ["error_code"],
    },
    "paywall_plan_expose": {
        "module": "paywall",
        "params": [
            "page_from", "product_id", "store_product_id", "billing_period", "selected",
            "price_server", "price_apple", "price_actual", "amount_minor", "amount_minor_currency",
            "apple_amount_minor", "apple_amount_minor_currency", "actual_amount_minor",
            "actual_amount_minor_currency", "intro_eligible", "intro_price",
        ],
    },
    "paywall_plan_select_click": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "billing_period", "price_actual", "actual_amount_minor", "intro_eligible"],
    },
    "paywall_purchase_click": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "billing_period", "price_actual", "actual_amount_minor", "intro_eligible"],
    },
    "paywall_purchase_start": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "billing_period", "purchase_stage", "client_request_id"],
        "optional_params": ["client_request_id"],
    },
    "paywall_storekit_launch_success": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "purchase_stage"],
    },
    "paywall_storekit_launch_fail": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "purchase_stage", "fail_reason", "error_code", "platform_error_code"],
    },
    "paywall_purchase_cancel": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "purchase_stage"],
    },
    "paywall_verify_start": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "purchase_stage", "order_id", "transaction_id"],
        "optional_params": ["order_id", "transaction_id"],
    },
    "paywall_verify_success": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "purchase_stage", "order_id", "transaction_id", "original_transaction_id"],
        "optional_params": ["order_id", "transaction_id", "original_transaction_id"],
    },
    "paywall_verify_fail": {
        "module": "paywall",
        "params": ["page_from", "product_id", "store_product_id", "purchase_stage", "order_id", "transaction_id", "fail_reason", "error_code", "server_error_code"],
    },
    "paywall_status_refresh_success": {
        "module": "paywall",
        "params": ["page_from", "product_id", "purchase_stage", "pro_status"],
        "optional_params": ["product_id"],
    },
    "paywall_status_refresh_fail": {
        "module": "paywall",
        "params": ["page_from", "product_id", "purchase_stage", "fail_reason", "error_code"],
        "optional_params": ["product_id"],
    },
    "paywall_purchase_success": {
        "module": "paywall",
        "params": [
            "page_from", "product_id", "store_product_id", "billing_period", "purchase_stage",
            "price_server", "price_apple", "price_actual", "amount_minor", "apple_amount_minor",
            "actual_amount_minor", "intro_eligible", "intro_price", "order_id", "transaction_id",
            "original_transaction_id",
        ],
        "optional_params": ["order_id", "transaction_id", "original_transaction_id"],
    },
    "paywall_purchase_fail": {
        "module": "paywall",
        "params": [
            "page_from", "product_id", "store_product_id", "billing_period", "purchase_stage",
            "fail_reason", "error_code", "platform_error_code", "server_error_code",
        ],
    },
    "paywall_restore_click": {"module": "paywall", "params": ["page_from"]},
    "paywall_restore_success": {
        "module": "paywall",
        "params": ["page_from", "transaction_id", "original_transaction_id"],
        "optional_params": ["transaction_id", "original_transaction_id"],
    },
    "paywall_restore_fail": {
        "module": "paywall",
        "params": ["page_from", "fail_reason", "error_code"],
        "optional_params": ["error_code"],
    },
    "paywall_success_dialogview": {"module": "paywall", "params": ["page_from", "product_id", "store_product_id"]},
    "search_true_pageview": {"module": "search_true", "params": ["task_id", "page_from"]},
    "search_true_create_task_start": {"module": "search_true", "params": []},
    "search_true_start": {
        "module": "search_true",
        "params": ["task_id", "is_first", "page_from", "is_add", "add_type", "clue"],
    },
    "search_true_result": {
        "module": "search_true",
        "params": [
            "task_id",
            "is_first",
            "is_add",
            "result_type",
            "num",
            "confidence_array",
            "confidence_top",
            "fail_reason",
        ],
    },
    "search_true_retry": {"module": "search_true", "params": []},
    "search_true_page_exit": {"module": "search_true", "params": []},
    "candidate_pageview": {"module": "candidate", "params": ["task_id", "num", "confidence_top"]},
    "candidate_card_click": {
        "module": "candidate",
        "params": ["task_id", "candidate_id", "confidence", "rank"],
    },
    "candidate_continue_click": {
        "module": "candidate",
        "params": ["task_id", "candidate_id", "confidence", "rank"],
    },
    "candidate_addmore_click": {"module": "candidate", "params": []},
    "candidate_empty_view": {"module": "candidate", "params": ["task_id"]},
    "candidate_empty_add_click": {"module": "candidate", "params": []},
    "report_pageview": {"module": "report", "params": ["page_from", "task_id", "candidate_id"]},
    "report_load_success": {"module": "report", "params": ["report"]},
    "report_load_fail": {"module": "report", "params": []},
    "report_refresh_success": {"module": "report", "params": ["report"]},
    "report_refresh_fail": {"module": "report", "params": []},
    "report_tab_click": {"module": "report", "params": ["type"]},
    "report_tab_view": {"module": "report", "params": ["type", "stay_time"]},
    "report_issue_click": {"module": "report", "params": []},
    "report_social_copy_click": {"module": "report", "params": ["platform"]},
    "report_datasource_click": {"module": "report", "params": ["type"]},
    "report_photo_add_click": {"module": "report", "params": ["candidate_id"]},
    "profile_retry_click": {"module": "profile", "params": ["candidate_id", "type"]},
    "profile_pro_unlock_view": {"module": "profile", "params": []},
    "profile_pro_unlock_click": {"module": "profile", "params": []},
    "profile_issue_dialogview": {"module": "profile", "params": []},
    "profile_issue_submit_click": {"module": "profile", "params": []},
    "profile_issue_submit_success": {"module": "profile", "params": ["issue", "candidate_id"]},
    "profile_issue_submit_fail": {"module": "profile", "params": ["fail_reason"]},
    "history_pageview": {"module": "history", "params": []},
    "history_person_click": {"module": "history", "params": ["candidate_id"]},
    "account_pageview": {"module": "account", "params": []},
    "account_pro_banner_view": {"module": "account", "params": ["pro_status"]},
    "account_pro_banner_click": {"module": "account", "params": ["pro_status"]},
    "account_restore_click": {"module": "account", "params": []},
    "account_faq_click": {"module": "account", "params": []},
    "account_feedback_click": {"module": "account", "params": []},
    "account_rateus_click": {"module": "account", "params": []},
    "account_about_click": {"module": "account", "params": []},
    "faq_pageview": {"module": "faq", "params": []},
    "about_pageview": {"module": "about", "params": []},
}


ENUMS: dict[str, set[str]] = {
    "is_first": {"0", "1"},
    "is_pro": {"0", "1"},
    "has_name": {"0", "1"},
    "has_search": {"0", "1"},
    "is_add": {"0", "1"},
    "selected": {"0", "1"},
    "status": {"expand", "collapse"},
    "from": {"recommend_card", "enrich"},
    "platform": {"linkedin", "instagram", "x", "facebook", "tiktok", "unknown"},
    "result_type": {"none", "single", "multiple", "timeout", "fail"},
    "pro_status": {"unsub", "active", "expired"},
    "purchase_stage": {
        "create_order", "launch_storekit", "storekit_result", "verify",
        "refresh_status", "completed", "unknown",
    },
}

TYPE_ENUM_ACTIONS = {
    "app_heartbeat": {"0", "1"},
    "report_tab_click": {"social", "photo", "profile", "insight"},
    "report_tab_view": {"social", "photo", "profile", "insight"},
    "report_datasource_click": {"social", "photo", "profile", "insight"},
    "profile_retry_click": {"social", "photo", "profile", "insight"},
}

PAGE_FROM_VALUES = {
    "home",
    "lead",
    "search_fake",
    "paywall",
    "paywall_success",
    "search_true",
    "search",
    "candidate",
    "report",
    "account",
    "faq",
    "about",
    "history",
    "popular",
    "myaccount",
}

ADD_TYPE_VALUES = {"photo", "social", "location", "profession", "employer", "school", "other"}


def analyze_log_text(log_text: str, expected_counts: dict[str, int] | None = None) -> dict[str, Any]:
    expected_counts = expected_counts or {}
    parser = LogParser(log_text)
    requests = parser.parse_requests()
    responses = parser.parse_responses()
    events = _extract_events(requests)
    event_counts = Counter(item["event_name"] for item in events)
    event_stats = _build_event_stats(event_counts)

    response_checks = _check_responses(requests, responses)
    validated_events = [_validate_event(item) for item in events]
    common_param_summary, common_param_events = _build_common_param_checks(validated_events)
    count_checks = _check_counts(event_counts, expected_counts)

    failed_events = sum(1 for item in validated_events if item["status"] == "fail")
    failed_responses = sum(1 for item in response_checks if item["status"] == "fail")
    failed_counts = sum(1 for item in count_checks if item["status"] == "fail")
    passed_events = len(validated_events) - failed_events

    result = {
        "summary": {
            "request_count": len(requests),
            "response_count": len(responses),
            "event_count": len(events),
            "passed_event_count": passed_events,
            "failed_event_count": failed_events,
            "failed_response_count": failed_responses,
            "failed_count_check_count": failed_counts,
        },
        "event_counts": dict(sorted(event_counts.items())),
        "event_stats": event_stats,
        "count_checks": count_checks,
        "events": validated_events,
        "response_checks": response_checks,
        "common_param_summary": common_param_summary,
        "common_param_events": common_param_events,
    }
    result["markdown_report"] = build_markdown_report(result)
    return result


def _build_event_stats(event_counts: Counter[str]) -> list[dict[str, Any]]:
    stats = []
    for event_name, count in sorted(event_counts.items()):
        rule = EVENT_RULES.get(event_name, {})
        stats.append(
            {
                "module": rule.get("module", ""),
                "event_name": event_name,
                "count": count,
            }
        )
    return stats


class LogParser:
    def __init__(self, log_text: str) -> None:
        self.lines = [_clean_line(line) for line in log_text.splitlines()]
        self.event_tracking_by_id = _parse_event_tracking_lines(self.lines)

    def parse_requests(self) -> list[dict[str, Any]]:
        requests = self._parse_blocks(direction="-->", marker="[HTTP] request:")
        known_event_ids = _request_event_ids(requests)
        for request in self._parse_standalone_trackevents_requests():
            event_ids = _request_event_ids([request])
            if event_ids and event_ids.issubset(known_event_ids):
                continue
            requests.append(request)
            known_event_ids.update(event_ids)
        for request in self._parse_response_derived_requests():
            request = _remove_known_request_events(request, known_event_ids)
            event_ids = _request_event_ids([request])
            if not event_ids:
                continue
            requests.append(request)
            known_event_ids.update(event_ids)
        return requests

    def parse_responses(self) -> list[dict[str, Any]]:
        responses = self._parse_blocks(direction="<--", marker="[HTTP] response:")
        known_event_ids = _response_event_ids(responses)
        for response in self._parse_standalone_trackevents_responses():
            event_ids = _response_event_ids([response])
            if event_ids and event_ids.issubset(known_event_ids):
                continue
            responses.append(response)
            known_event_ids.update(event_ids)
        return responses

    def _parse_blocks(self, direction: str, marker: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for index, line in enumerate(self.lines):
            if "[HTTP]" not in line or direction not in line or "method=TrackEvents" not in line:
                continue
            marker_index = _find_next_marker(self.lines, index + 1, marker)
            if marker_index is None:
                continue
            parsed = _read_json_after_marker(self.lines, marker_index + 1)
            if parsed is not None:
                blocks.append(parsed)
            elif direction == "-->":
                recovered = self._recover_interleaved_trackevents_request(marker_index + 1)
                if recovered is not None:
                    blocks.append(recovered)
        return blocks

    def _recover_interleaved_trackevents_request(self, start: int) -> dict[str, Any] | None:
        partial_lines: list[str] = []
        for line in self.lines[start:]:
            if "[HTTP]" in line and ("-->" in line or "<--" in line):
                break
            partial_lines.append(line)
        partial_text = "\n".join(partial_lines)
        event_id = _regex_value(partial_text, r'"event_id"\s*:\s*"([^"]+)"')
        event_name = _regex_value(partial_text, r'"event_name"\s*:\s*"([^"]+)"')
        event_time = _regex_int(partial_text, r'"event_time_ms"\s*:\s*(\d+)')
        if not event_id or not event_name or event_time is None:
            return None

        fallback = self.event_tracking_by_id.get(event_id, {})
        properties = dict(fallback.get("properties") or {})
        properties.setdefault("logtime", event_time)
        properties.setdefault("log_id", event_id)

        return {
            "_recovered_from_event_tracking": True,
            "requests": [
                {
                    "id": "req_0",
                    "method_name": "TrackEvents",
                    "params": {
                        "events": [
                            {
                                "event_id": event_id,
                                "event_name": event_name,
                                "event_time_ms": event_time,
                                "properties": properties,
                            }
                        ]
                    },
                }
            ],
        }

    def _parse_standalone_trackevents_requests(self) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        for parsed in self._parse_standalone_json_blocks():
            normalized = _normalize_trackevents_request(parsed)
            if normalized is not None:
                requests.append(normalized)
        return requests

    def _parse_response_derived_requests(self) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        for response in self._parse_standalone_trackevents_responses():
            events = []
            for response_item in response.get("responses", []):
                data = response_item.get("data", {})
                for response_event in data.get("events", []):
                    event_id = response_event.get("event_id")
                    event_name = response_event.get("event_name")
                    if not event_id or not event_name:
                        continue
                    fallback = self.event_tracking_by_id.get(str(event_id), {})
                    events.append(
                        {
                            "event_id": event_id,
                            "event_name": event_name,
                            "event_time_ms": fallback.get("event_time_ms"),
                            "properties": dict(fallback.get("properties") or {}),
                        }
                    )
            if events:
                requests.append(
                    {
                        "_recovered_from_response": True,
                        "requests": [
                            {
                                "id": "req_0",
                                "method_name": "TrackEvents",
                                "params": {"events": events},
                            }
                        ],
                    }
                )
        return requests

    def _parse_standalone_trackevents_responses(self) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        for parsed in self._parse_standalone_json_blocks():
            if _response_event_ids([parsed]):
                responses.append(parsed)
        return responses

    def _parse_standalone_json_blocks(self) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for index, line in enumerate(self.lines):
            if not line.startswith("{"):
                continue
            parsed = _read_json_after_marker(self.lines, index)
            if parsed is not None:
                blocks.append(parsed)
        return blocks


def _clean_line(line: str) -> str:
    if "flutter:" in line:
        line = line.split("flutter:", 1)[1]
    line = line.strip()
    line = re.sub(r"^[│┌└─\s]+", "", line)
    return line.strip()


def _parse_event_tracking_lines(lines: list[str]) -> dict[str, dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    pattern = re.compile(
        r"\[EventTracking\]\s+name=(?P<name>\S+)\s+id=(?P<id>\S+)\s+time=(?P<time>\d+)\s+props=(?P<props>\{.*\})"
    )
    for line in lines:
        match = pattern.search(line)
        if not match:
            continue
        try:
            props = json.loads(match.group("props"))
        except json.JSONDecodeError:
            props = {}
        event_id = match.group("id")
        events[event_id] = {
            "event_id": event_id,
            "event_name": match.group("name"),
            "event_time_ms": int(match.group("time")),
            "properties": props if isinstance(props, dict) else {},
        }
    return events


def _regex_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _regex_int(text: str, pattern: str) -> int | None:
    value = _regex_value(text, pattern)
    return int(value) if value is not None else None


def _find_next_marker(lines: list[str], start: int, marker: str) -> int | None:
    for index in range(start, len(lines)):
        if marker in lines[index]:
            return index
        if "[HTTP]" in lines[index] and ("-->" in lines[index] or "<--" in lines[index]):
            return None
    return None


def _read_json_after_marker(lines: list[str], start: int) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    for line in lines[start:]:
        if not started:
            brace_index = line.find("{")
            if brace_index < 0:
                if "[HTTP]" in line:
                    return None
                continue
            buffer = line[brace_index:]
            started = True
        else:
            buffer += "\n" + line

        try:
            obj, end = decoder.raw_decode(buffer)
        except json.JSONDecodeError:
            continue
        if buffer[end:].strip():
            continue
        return obj if isinstance(obj, dict) else None
    return None


def _extract_events(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for request_index, request_body in enumerate(requests, start=1):
        for request_item in request_body.get("requests", []):
            if request_item.get("method_name") != "TrackEvents":
                continue
            for event_index, event in enumerate(
                request_item.get("params", {}).get("events", []), start=1
            ):
                events.append(
                    {
                        "request_index": request_index,
                        "event_index": event_index,
                        "event_id": event.get("event_id"),
                        "event_name": event.get("event_name"),
                        "event_time_ms": event.get("event_time_ms"),
                        "properties": event.get("properties") or {},
                    }
                )
    return events


def _request_event_ids(requests: list[dict[str, Any]]) -> set[str]:
    event_ids: set[str] = set()
    for request_body in requests:
        for request_item in request_body.get("requests", []):
            if request_item.get("method_name") != "TrackEvents":
                continue
            for event in request_item.get("params", {}).get("events", []):
                event_id = event.get("event_id")
                if event_id:
                    event_ids.add(str(event_id))
    return event_ids


def _response_event_ids(responses: list[dict[str, Any]]) -> set[str]:
    event_ids: set[str] = set()
    for response_body in responses:
        for response_item in response_body.get("responses", []):
            data = response_item.get("data", {})
            for event in data.get("events", []):
                event_id = event.get("event_id")
                if event_id:
                    event_ids.add(str(event_id))
    return event_ids


def _normalize_trackevents_request(body: dict[str, Any]) -> dict[str, Any] | None:
    trackevent_items: list[dict[str, Any]] = []
    for request_item in body.get("requests", []):
        events = request_item.get("params", {}).get("events", [])
        if request_item.get("method_name") != "TrackEvents" and not _looks_like_trackevents(events):
            continue
        normalized_item = dict(request_item)
        normalized_item["method_name"] = "TrackEvents"
        trackevent_items.append(normalized_item)
    if not trackevent_items:
        return None
    return {**body, "requests": trackevent_items}


def _looks_like_trackevents(events: Any) -> bool:
    return bool(
        isinstance(events, list)
        and events
        and all(
            isinstance(event, dict) and event.get("event_id") and event.get("event_name")
            for event in events
        )
    )


def _remove_known_request_events(
    request_body: dict[str, Any], known_event_ids: set[str]
) -> dict[str, Any]:
    request_items: list[dict[str, Any]] = []
    for request_item in request_body.get("requests", []):
        events = request_item.get("params", {}).get("events", [])
        new_events = [
            event
            for event in events
            if str(event.get("event_id")) not in known_event_ids
        ]
        if not new_events:
            continue
        normalized_item = dict(request_item)
        normalized_item["params"] = {
            **request_item.get("params", {}),
            "events": new_events,
        }
        request_items.append(normalized_item)
    return {**request_body, "requests": request_items}


def _check_responses(
    requests: list[dict[str, Any]], responses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    max_len = max(len(requests), len(responses))
    for index in range(max_len):
        request_body = requests[index] if index < len(requests) else None
        response_body = responses[index] if index < len(responses) else None
        request_event_count = _request_event_count(request_body) if request_body else 0
        response_item = (response_body or {}).get("responses", [{}])[0]
        accepted_count = response_item.get("data", {}).get("accepted_count")
        errors: list[str] = []

        if request_body is None:
            errors.append("存在响应但没有对应请求")
        if response_body is None:
            errors.append("存在请求但没有对应响应")
        if response_body is not None and response_body.get("code") != 0:
            errors.append(f"响应顶层 code 非 0: {response_body.get('code')}")
        if response_body is not None and response_item.get("success") is not True:
            errors.append(f"响应 success 不是 true: {response_item.get('success')}")
        if response_body is not None and response_item.get("code") != 0:
            errors.append(f"响应子 code 非 0: {response_item.get('code')}")
        if response_body is not None and accepted_count != request_event_count:
            errors.append(f"accepted_count={accepted_count} 与请求事件数 {request_event_count} 不一致")

        checks.append(
            {
                "request_index": index + 1,
                "request_event_count": request_event_count,
                "accepted_count": accepted_count,
                "success": response_item.get("success"),
                "status": "fail" if errors else "pass",
                "errors": errors,
            }
        )
    return checks


def _request_event_count(request_body: dict[str, Any] | None) -> int:
    if not request_body:
        return 0
    count = 0
    for request_item in request_body.get("requests", []):
        if request_item.get("method_name") == "TrackEvents":
            count += len(request_item.get("params", {}).get("events", []))
    return count


def _validate_event(event: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    event_name = event.get("event_name")
    properties = event.get("properties")
    properties = properties if isinstance(properties, dict) else {}

    if not event.get("event_id"):
        errors.append("缺少基础字段: event_id")
    if not event_name:
        errors.append("缺少基础字段: event_name")
    if event.get("event_time_ms") in (None, ""):
        errors.append("缺少基础字段: event_time_ms")
    elif not isinstance(event.get("event_time_ms"), int):
        errors.append("event_time_ms 不是数字毫秒时间戳")

    if "logtime" in properties and properties.get("logtime") != event.get("event_time_ms"):
        errors.append("properties.logtime 与 event_time_ms 不一致")
    if "log_id" in properties and properties.get("log_id") != event.get("event_id"):
        errors.append("properties.log_id 与 event_id 不一致")

    rule = EVENT_RULES.get(str(event_name))
    expected_params: set[str] = set()
    if rule is None:
        errors.append(f"未定义事件: {event_name}")
    else:
        expected_params = set(rule["params"])
        optional_params = set(rule.get("optional_params", []))
        for key in rule["params"]:
            if key in optional_params:
                if key in properties and properties.get(key) not in (None, ""):
                    _validate_param_value(str(event_name), key, properties.get(key), errors)
                continue
            if key not in properties:
                errors.append(f"缺少业务子参: {key}")
            elif properties.get(key) in (None, ""):
                errors.append(f"业务子参为空: {key}")
            else:
                _validate_param_value(str(event_name), key, properties.get(key), errors)

    allowed_keys = COMMON_PROPERTY_KEYS | expected_params
    extra_keys = sorted(set(properties) - allowed_keys)
    if extra_keys:
        warnings.append("疑似多传字段: " + ", ".join(extra_keys))
    extra_params = {key: properties.get(key) for key in extra_keys}

    missing_common = sorted({"logtime", "log_id"} - set(properties))
    if missing_common:
        warnings.append("缺少推荐公参: " + ", ".join(missing_common))

    business_params = {key: properties.get(key) for key in sorted(expected_params)}

    return {
        **event,
        "properties": properties,
        "module": (rule or {}).get("module", ""),
        "required_params": sorted(expected_params),
        "business_params": business_params,
        "extra_params": extra_params,
        "status": "fail" if errors else "pass",
        "errors": errors,
        "warnings": warnings,
    }


def _validate_param_value(event_name: str, key: str, value: Any, errors: list[str]) -> None:
    value_text = str(value)
    if key == "page_from":
        if value_text not in PAGE_FROM_VALUES:
            errors.append(f"page_from 枚举值错误: {value_text}")
        return
    if key == "add_type":
        bad_values = [item for item in value_text.split("|") if item and item not in ADD_TYPE_VALUES]
        if bad_values:
            errors.append(f"add_type 枚举值错误: {', '.join(bad_values)}")
        return
    if key == "type" and event_name in TYPE_ENUM_ACTIONS:
        if value_text not in TYPE_ENUM_ACTIONS[event_name]:
            errors.append(f"type 枚举值错误: {value_text}")
        return
    enum_values = ENUMS.get(key)
    if enum_values and value_text not in enum_values:
        errors.append(f"{key} 枚举值错误: {value_text}")


def _build_common_param_checks(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    summary: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for rule in COMMON_PARAM_RULES:
        key = rule["key"]
        present_count = 0
        empty_count = 0
        for event in events:
            properties = dict(event.get("properties") or {})
            if key == "action":
                properties.setdefault("action", event.get("event_name"))
            if key not in properties:
                continue
            present_count += 1
            if properties[key] in (None, ""):
                empty_count += 1
        missing_count = len(events) - present_count
        failed = missing_count > 0 or (not rule["allow_empty"] and empty_count > 0)
        summary.append(
            {
                **rule,
                "event_count": len(events),
                "present_count": present_count,
                "missing_count": missing_count,
                "empty_count": empty_count,
                "status": "fail" if failed else "pass",
            }
        )

    for event in events:
        properties = dict(event.get("properties") or {})
        properties.setdefault("action", event.get("event_name"))
        missing_required = [
            rule["key"]
            for rule in COMMON_PARAM_RULES
            if rule["required"] and rule["key"] not in properties
        ]
        empty_not_allowed = [
            rule["key"]
            for rule in COMMON_PARAM_RULES
            if rule["key"] in properties
            and not rule["allow_empty"]
            and properties[rule["key"]] in (None, "")
        ]
        details.append(
            {
                "request_index": event.get("request_index"),
                "event_index": event.get("event_index"),
                "module": event.get("module", ""),
                "event_name": event.get("event_name", ""),
                "event_id": event.get("event_id", ""),
                "values": {
                    rule["key"]: properties.get(rule["key"])
                    if rule["key"] in properties
                    else None
                    for rule in COMMON_PARAM_RULES
                },
                "missing_required": missing_required,
                "empty_not_allowed": empty_not_allowed,
                "status": "fail" if missing_required or empty_not_allowed else "pass",
            }
        )
    return summary, details


def _check_counts(event_counts: Counter[str], expected_counts: dict[str, int]) -> list[dict[str, Any]]:
    checks = []
    for event_name, expected in sorted(expected_counts.items()):
        actual = event_counts.get(event_name, 0)
        checks.append(
            {
                "event_name": event_name,
                "expected": expected,
                "actual": actual,
                "status": "pass" if actual == expected else "fail",
            }
        )
    return checks


def build_markdown_report(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# 埋点测试报告",
        "",
        "## 总览",
        f"- TrackEvents 请求数：{summary['request_count']}",
        f"- TrackEvents 响应数：{summary['response_count']}",
        f"- 事件总数：{summary['event_count']}",
        f"- 字段校验通过事件数：{summary['passed_event_count']}",
        f"- 字段校验失败事件数：{summary['failed_event_count']}",
        "",
        "## 事件统计",
    ]
    if result["event_counts"]:
        for event_name, count in result["event_counts"].items():
            lines.append(f"- `{event_name}`：{count} 次")
    else:
        lines.append("- 未识别到 TrackEvents 事件")

    if result["count_checks"]:
        lines.extend(["", "## 预期次数校验"])
        for item in result["count_checks"]:
            label = "通过" if item["status"] == "pass" else "失败"
            lines.append(
                f"- `{item['event_name']}`：实际 {item['actual']} 次，预期 {item['expected']} 次，{label}"
            )

    failed_events = [item for item in result["events"] if item["status"] == "fail"]
    if failed_events:
        lines.extend(["", "## 字段问题"])
        for item in failed_events:
            lines.append(f"- 请求 #{item['request_index']} `{item['event_name']}`：")
            for error in item["errors"]:
                lines.append(f"  - {error}")

    failed_responses = [item for item in result["response_checks"] if item["status"] == "fail"]
    if failed_responses:
        lines.extend(["", "## 响应问题"])
        for item in failed_responses:
            lines.append(f"- 请求 #{item['request_index']}：")
            for error in item["errors"]:
                lines.append(f"  - {error}")

    return "\n".join(lines)
