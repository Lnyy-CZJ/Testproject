"""Gateway/PUT 通用解析器的原语、黄金样本与异常配对合同测试。"""

import json
from pathlib import Path
import unittest

from gateway_log_parser import (
    clean_log_line,
    normalize_log_lines,
    parse_interface_log,
    classify_result,
    scan_json_block,
    scan_named_json_block,
    unwrap_gateway_envelope,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"


def make_gateway_request(requests, *, timestamp="2026-08-29 18:51:08,000"):
    """生成与真实夹具同形的 Gateway 请求 marker 和完整 JSON。

    测试通过 ``json.dumps`` 生成 payload，避免手写 JSON 时遗漏外层 ``payload``、
    ``comm`` 或数组结构，导致测试只覆盖一个并不存在的日志格式。
    """
    payload = {
        "url": "https://gateway.example.test/dating/gateway/invoke",
        "headers": {"Content-Type": "application/json"},
        "payload": {
            "comm": {"client_request_id": "crid_inline_fixture"},
            "requests": requests,
        },
    }
    return "\n".join(
        [
            (
                f"{timestamp} | INFO | tests.gateway | "
                "Gateway 请求数据:"
            ),
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def make_gateway_response(
    responses,
    *,
    http_status=200,
    elapsed_ms="1.25",
    gateway_code=0,
    gateway_message="ok",
    timestamp="2026-08-29 18:51:08,125",
    truncate_body=False,
):
    """生成真实 ``headers=``/``body=`` 响应，可注入坏元数据或截断 body。"""
    envelope = {
        "code": gateway_code,
        "message": gateway_message,
        "request_id": "gw_req_inline_fixture",
        "trace_id": "trace_inline_fixture",
        "responses": responses,
    }
    body = json.dumps(envelope, ensure_ascii=False, indent=2)
    if truncate_body:
        # 仅移除由 json.dumps 生成的最后一个闭合括号，确保错误来自日志截断，
        # 而不是测试夹具本身拼错字段或字符串转义。
        body = body[:-1]
    return "\n".join(
        [
            (
                f"{timestamp} | INFO | tests.gateway | Gateway 响应数据: "
                f"HTTP {http_status} elapsed_ms={elapsed_ms}"
            ),
            'headers=' + json.dumps(
                {"Content-Type": "application/json"},
                ensure_ascii=False,
                indent=2,
            ),
            "body=" + body,
        ]
    )


def make_gateway_exchange(requests, responses, **response_options):
    """组合一组请求/响应，供配对测试直接表达逻辑子调用。"""
    return "\n".join(
        [
            make_gateway_request(requests),
            make_gateway_response(responses, **response_options),
        ]
    )


class SharedParserPrimitiveTests(unittest.TestCase):
    def test_scan_json_block_ignores_braces_inside_strings(self):
        lines = normalize_log_lines('marker\n{"text":"a } b", "ok":true}\nafter')
        value, end_idx, start_line, end_line, error = scan_json_block(lines, 1)
        self.assertIsNone(error)
        self.assertEqual(value, {"text": "a } b", "ok": True})
        self.assertEqual((start_line, end_line), (2, 2))

    def test_scan_named_body_skips_headers(self):
        lines = normalize_log_lines(
            'Gateway 响应数据: HTTP 200 elapsed_ms=1.25\n'
            'headers={"Content-Type":"application/json"}\n'
            'body={"code":0,"responses":[]}'
        )
        value, _, start_line, end_line, error = scan_named_json_block(lines, 1, "body")
        self.assertIsNone(error)
        self.assertEqual(value["code"], 0)
        self.assertEqual((start_line, end_line), (3, 3))

    def test_unwrap_gateway_envelope_preserves_three_layers(self):
        result = unwrap_gateway_envelope({
            "code": 0,
            "message": "ok",
            "request_id": "gw_req_1",
            "trace_id": "trace_1",
            "responses": [{
                "id": "req_0", "success": True, "code": 0,
                "message": "ok", "data": {"status": "queued"},
            }],
        })
        self.assertEqual(result["gateway"]["code"], 0)
        self.assertEqual(result["responses"][0]["data"]["status"], "queued")


class DatingTransportParsingTests(unittest.TestCase):
    """以不可变黄金夹具固定统一 InterfaceCall 的主要公共合同。"""

    def test_reply_fixture_produces_gateway_and_put_calls(self):
        text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
        parsed = parse_interface_log(text)
        gateway = [c for c in parsed["calls"] if c["transport"] == "gateway"]
        puts = [
            c for c in parsed["calls"]
            if c["transport"] == "object_storage_put"
        ]

        self.assertEqual(
            {"parser_version", "calls", "flow_steps", "parse_warnings"},
            set(parsed),
        )
        self.assertEqual(len({c["gateway_exchange_id"] for c in gateway}), 19)
        self.assertEqual(len(gateway), 19)
        self.assertEqual(len(puts), 2)
        self.assertEqual([], parsed["parse_warnings"])
        self.assertEqual(
            [f"call_{index:04d}" for index in range(1, 22)],
            [call["call_id"] for call in parsed["calls"]],
        )
        self.assertEqual(
            list(range(1, 22)),
            [call["sequence"] for call in parsed["calls"]],
        )

        create = next(c for c in gateway if c["method_name"] == "CreateReplyTask")
        self.assertEqual(
            {
                "call_id",
                "gateway_exchange_id",
                "sequence",
                "transport",
                "service_name",
                "method_name",
                "request",
                "response",
                "result_class",
                "parse_status",
                "warnings",
            },
            set(create),
        )
        self.assertEqual("tool.dating.DatingAssistantService", create["service_name"])
        self.assertEqual("2026-08-29 18:51:12.634", create["request"]["timestamp"])
        self.assertEqual((477, 515), (
            create["request"]["line_start"],
            create["request"]["line_end"],
        ))
        self.assertEqual(
            "crid_1788000672634723888",
            create["request"]["client_request_id"],
        )
        self.assertEqual(
            [
                "dating_media_c93f2385b50067579d9b14a28ec7ba32",
                "dating_media_6ae2a0b08fce432f9461936399ffaceb",
            ],
            create["request"]["params"]["asset_ids"],
        )
        self.assertEqual("2026-08-29 18:51:12.857", create["response"]["timestamp"])
        self.assertEqual((516, 544), (
            create["response"]["line_start"],
            create["response"]["line_end"],
        ))
        self.assertEqual(create["response"]["http_status"], 200)
        self.assertEqual(create["response"]["gateway"]["code"], 0)
        self.assertTrue(create["response"]["sub_response"]["success"])
        self.assertEqual("queued", create["response"]["data"]["status"])
        self.assertEqual("success", create["result_class"])
        self.assertEqual("PARSED", create["parse_status"])

    def test_analysis_fixture_produces_thirty_gateway_calls(self):
        text = (
            FIXTURE_DIR / "relationship_analysis_multi_image_success.log"
        ).read_text(encoding="utf-8")
        parsed = parse_interface_log(text)
        gateway = [c for c in parsed["calls"] if c["transport"] == "gateway"]
        puts = [
            c for c in parsed["calls"]
            if c["transport"] == "object_storage_put"
        ]

        self.assertEqual(len({c["gateway_exchange_id"] for c in gateway}), 30)
        self.assertEqual(len(gateway), 30)
        self.assertEqual(len(puts), 3)
        self.assertEqual(33, len(parsed["calls"]))
        self.assertEqual(
            [f"call_{index:04d}" for index in range(1, 34)],
            [call["call_id"] for call in parsed["calls"]],
        )

    def test_real_put_and_flow_markers_preserve_evidence(self):
        text = (FIXTURE_DIR / "reply_generation_multi_image_success.log").read_text(
            encoding="utf-8"
        )
        parsed = parse_interface_log(text)
        first_put = next(
            call for call in parsed["calls"]
            if call["transport"] == "object_storage_put"
        )

        # 真实日志使用“PUT 上传响应”而不是 Gateway 的“响应数据”拼法；这里
        # 同时固定无 body 的 2xx 响应仍为成功，并保留 headers 的结束行。
        self.assertEqual("object_storage", first_put["service_name"])
        self.assertEqual("PUT", first_put["method_name"])
        self.assertIsNone(first_put["gateway_exchange_id"])
        self.assertEqual("2026-08-29 18:51:10.066", first_put["request"]["timestamp"])
        self.assertEqual((226, 235), (
            first_put["request"]["line_start"],
            first_put["request"]["line_end"],
        ))
        self.assertEqual("2026-08-29 18:51:11.610", first_put["response"]["timestamp"])
        self.assertEqual((236, 246), (
            first_put["response"]["line_start"],
            first_put["response"]["line_end"],
        ))
        self.assertEqual(200, first_put["response"]["http_status"])
        self.assertIsNone(first_put["response"]["gateway"])
        self.assertIsNone(first_put["response"]["sub_response"])
        self.assertIsNone(first_put["response"]["data"])
        self.assertEqual("success", first_put["result_class"])

        self.assertEqual(15, len(parsed["flow_steps"]))
        self.assertEqual(
            {
                "step": "get_preferences",
                "event": "start",
                "current": 1,
                "total": 8,
                "timestamp": "2026-08-29 18:51:08.132",
                "line": 1,
            },
            parsed["flow_steps"][0],
        )
        skipped = next(step for step in parsed["flow_steps"] if step["event"] == "skip")
        self.assertEqual("update_preferences", skipped["step"])
        self.assertEqual(63, skipped["line"])


class GatewayPairingEdgeTests(unittest.TestCase):
    """固定 ID 优先、确定性兜底和损坏输入隔离等边界行为。"""

    def test_subresponses_are_paired_by_id_not_array_position(self):
        log = make_gateway_exchange(
            requests=[
                {
                    "id": "a",
                    "service_name": "svc",
                    "method_name": "First",
                    "params": {},
                },
                {
                    "id": "b",
                    "service_name": "svc",
                    "method_name": "Second",
                    "params": {},
                },
            ],
            responses=[
                {
                    "id": "b",
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "data": {"v": 2},
                },
                {
                    "id": "a",
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "data": {"v": 1},
                },
            ],
        )
        calls = parse_interface_log(log)["calls"]
        by_method = {call["method_name"]: call for call in calls}

        self.assertEqual(by_method["First"]["response"]["data"]["v"], 1)
        self.assertEqual(by_method["Second"]["response"]["data"]["v"], 2)
        self.assertEqual(2, len(calls))
        self.assertEqual({"gateway_0001"}, {
            call["gateway_exchange_id"] for call in calls
        })
        self.assertEqual(["call_0001", "call_0002"], [
            call["call_id"] for call in calls
        ])

    def test_duplicate_positional_and_unmatched_items_keep_all_evidence(self):
        log = make_gateway_exchange(
            requests=[
                {"id": "dup", "service_name": "svc", "method_name": "First", "params": {}},
                {"id": "dup", "service_name": "svc", "method_name": "Second", "params": {}},
                {"service_name": "svc", "method_name": "Positional", "params": {}},
                {"id": "missing", "service_name": "svc", "method_name": "Missing", "params": {}},
            ],
            responses=[
                {"id": "dup", "success": True, "code": 0, "message": "ok", "data": {"v": 1}},
                {"id": "dup", "success": True, "code": 0, "message": "ok", "data": {"v": 2}},
                {"success": True, "code": 0, "message": "ok", "data": {"v": 3}},
                {"id": "orphan", "success": True, "code": 0, "message": "ok", "data": {"v": 4}},
            ],
        )
        parsed = parse_interface_log(log)
        calls = parsed["calls"]
        by_method = {
            call["method_name"]: call
            for call in calls
            if call["method_name"] is not None
        }
        orphan = next(call for call in calls if call["request"] is None)
        warning_codes = {warning["code"] for warning in parsed["parse_warnings"]}

        self.assertEqual(5, len(calls))
        self.assertEqual(1, by_method["First"]["response"]["data"]["v"])
        self.assertEqual(2, by_method["Second"]["response"]["data"]["v"])
        self.assertEqual(3, by_method["Positional"]["response"]["data"]["v"])
        # 外层 HTTP/Gateway 响应确实存在，因此保留两层状态；只有对应的
        # sub_response 为空，并通过 UNMATCHED_REQUEST 明示逻辑配对缺口。
        self.assertEqual(200, by_method["Missing"]["response"]["http_status"])
        self.assertIsNone(by_method["Missing"]["response"]["sub_response"])
        self.assertEqual(4, orphan["response"]["data"]["v"])
        self.assertEqual(
            {
                "AMBIGUOUS_PAIRING",
                "POSITIONAL_PAIRING_FALLBACK",
                "UNMATCHED_REQUEST",
                "UNMATCHED_RESPONSE",
            },
            warning_codes,
        )
        self.assertTrue(by_method["First"]["warnings"])
        self.assertTrue(by_method["Second"]["warnings"])
        self.assertIn(
            "POSITIONAL_PAIRING_FALLBACK",
            {warning["code"] for warning in by_method["Positional"]["warnings"]},
        )
        self.assertIn(
            "UNMATCHED_RESPONSE",
            {warning["code"] for warning in orphan["warnings"]},
        )

    def test_request_without_outer_response_is_no_response(self):
        log = make_gateway_request([
            {
                "id": "pending",
                "service_name": "svc",
                "method_name": "Pending",
                "params": {"v": 1},
            }
        ])
        parsed = parse_interface_log(log)
        call = parsed["calls"][0]

        self.assertIsNone(call["response"])
        self.assertEqual("PARSED", call["parse_status"])
        self.assertEqual("no_response", call["result_class"])
        self.assertIn(
            "UNMATCHED_REQUEST",
            {warning["code"] for warning in call["warnings"]},
        )

    def test_truncated_response_does_not_consume_next_exchange(self):
        broken = "\n".join(
            [
                make_gateway_request([
                    {"id": "broken", "service_name": "svc", "method_name": "Broken", "params": {}}
                ]),
                make_gateway_response(
                    [{"id": "broken", "success": True, "code": 0, "message": "ok"}],
                    truncate_body=True,
                ),
            ]
        )
        valid = make_gateway_exchange(
            [{"id": "valid", "service_name": "svc", "method_name": "Valid", "params": {}}],
            [{"id": "valid", "success": True, "code": 0, "message": "ok", "data": {"ok": True}}],
        )
        parsed = parse_interface_log("\n".join([broken, valid]))
        by_method = {
            call["method_name"]: call
            for call in parsed["calls"]
            if call["method_name"] is not None
        }

        self.assertEqual("parse_error", by_method["Broken"]["result_class"])
        self.assertNotEqual("PARSED", by_method["Broken"]["parse_status"])
        self.assertTrue(by_method["Broken"]["warnings"])
        self.assertEqual("success", by_method["Valid"]["result_class"])
        self.assertTrue(by_method["Valid"]["response"]["data"]["ok"])

    def test_gateway_malformed_elapsed_preserves_exchange_as_parse_error(self):
        """Gateway marker 已识别时，坏耗时不能让整份日志丢失。"""
        log = make_gateway_exchange(
            [{"id": "bad", "service_name": "svc", "method_name": "BadElapsed", "params": {}}],
            [{
                "id": "bad",
                "success": True,
                "code": 0,
                "message": "ok",
                "data": {"kept": True},
            }],
            elapsed_ms=".",
        )

        parsed = parse_interface_log(log)
        self.assertEqual(1, len(parsed["calls"]))
        call = parsed["calls"][0]
        warning = {
            "code": "RESPONSE_ELAPSED_MS_INVALID",
            "message": "响应 elapsed_ms 不是有效数字: '.'",
            "line_start": 21,
            "line_end": 41,
            "gateway_exchange_id": "gateway_0001",
            "transport": "gateway",
            "raw_value": ".",
        }

        self.assertEqual("call_0001", call["call_id"])
        self.assertEqual("gateway_0001", call["gateway_exchange_id"])
        self.assertEqual("2026-08-29 18:51:08.000", call["request"]["timestamp"])
        self.assertEqual((1, 20), (
            call["request"]["line_start"],
            call["request"]["line_end"],
        ))
        self.assertEqual("2026-08-29 18:51:08.125", call["response"]["timestamp"])
        self.assertEqual((21, 41), (
            call["response"]["line_start"],
            call["response"]["line_end"],
        ))
        self.assertEqual(200, call["response"]["http_status"])
        self.assertIsNone(call["response"]["elapsed_ms"])
        self.assertTrue(call["response"]["data"]["kept"])
        self.assertEqual("PARSE_ERROR", call["parse_status"])
        self.assertEqual("parse_error", call["result_class"])
        self.assertEqual([warning], call["warnings"])
        self.assertEqual([warning], parsed["parse_warnings"])

    def test_put_malformed_elapsed_preserves_lines_as_parse_error(self):
        """PUT 的坏耗时同样保留请求、响应和原始 marker 行证据。"""
        log = "\n".join([
            "2026-08-29 20:00:01,000 | INFO | tests.gateway | PUT 上传请求数据:",
            json.dumps({
                "url": "https://storage.example.test/object",
                "headers": {"Content-Type": "image/jpeg"},
                "content_length": 4,
            }, ensure_ascii=False),
            (
                "2026-08-29 20:00:01,010 | INFO | tests.gateway | "
                "PUT 上传响应: HTTP 200 elapsed_ms=1.2.3"
            ),
            'headers={"ETag":"kept"}',
        ])

        parsed = parse_interface_log(log)
        self.assertEqual(1, len(parsed["calls"]))
        call = parsed["calls"][0]
        warning = {
            "code": "RESPONSE_ELAPSED_MS_INVALID",
            "message": "响应 elapsed_ms 不是有效数字: '1.2.3'",
            "line_start": 3,
            "line_end": 4,
            "transport": "object_storage_put",
            "raw_value": "1.2.3",
        }

        self.assertEqual("call_0001", call["call_id"])
        self.assertIsNone(call["gateway_exchange_id"])
        self.assertEqual("2026-08-29 20:00:01.000", call["request"]["timestamp"])
        self.assertEqual((1, 2), (
            call["request"]["line_start"],
            call["request"]["line_end"],
        ))
        self.assertEqual("2026-08-29 20:00:01.010", call["response"]["timestamp"])
        self.assertEqual((3, 4), (
            call["response"]["line_start"],
            call["response"]["line_end"],
        ))
        self.assertEqual(200, call["response"]["http_status"])
        self.assertIsNone(call["response"]["elapsed_ms"])
        self.assertEqual({"ETag": "kept"}, call["response"]["headers"])
        self.assertEqual("PARSE_ERROR", call["parse_status"])
        self.assertEqual("parse_error", call["result_class"])
        self.assertEqual([warning], call["warnings"])
        self.assertEqual([warning], parsed["parse_warnings"])

    def test_result_class_priority_keeps_transport_layers_separate(self):
        cases = [
            ({"parse_status": "ERROR", "response": None}, "parse_error"),
            ({"parse_status": "PARSED", "response": None}, "no_response"),
            ({
                "parse_status": "PARSED",
                "response": {
                    "http_status": 500,
                    "gateway": {"code": 9},
                    "sub_response": {"success": False, "code": 8},
                },
            }, "http_error"),
            ({
                "parse_status": "PARSED",
                "response": {
                    "http_status": 200,
                    "gateway": {"code": 9},
                    "sub_response": {"success": False, "code": 8},
                },
            }, "gateway_error"),
            ({
                "parse_status": "PARSED",
                "response": {
                    "http_status": 200,
                    "gateway": {"code": 0},
                    "sub_response": {"success": False, "code": 8},
                },
            }, "business_error"),
            ({
                "parse_status": "PARSED",
                "response": {
                    "http_status": 200,
                    "gateway": {"code": 0},
                    "sub_response": {"success": True, "code": 0},
                },
            }, "success"),
            ({
                "parse_status": "PARSED",
                "response": {
                    "http_status": None,
                    "gateway": None,
                    "sub_response": None,
                },
            }, "unknown"),
        ]

        for call, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, classify_result(call))
