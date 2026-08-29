import unittest

from gateway_log_parser import (
    clean_log_line,
    normalize_log_lines,
    scan_json_block,
    scan_named_json_block,
    unwrap_gateway_envelope,
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
