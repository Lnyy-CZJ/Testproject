"""阶段 0 契约测试：People Insight 检索日志分析。

验证三样阶段 0 交付物：
1. 规则清单确认版（24 条规则，含 P0/P1 级别）；
2. Evidence Packet 字段确认版（结构与设计文档第 9 节一致）；
3. 10 份脱敏最小夹具（f01~f10）及其人工期望结论。

阶段 0 完成条件：每条 P0 规则至少有一个正例（PASS）或反例（FAIL）。
"""
import json
import re
import unittest
from pathlib import Path

from app import clean_log_line

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "people_search"
CONTRACTS_PATH = FIXTURE_DIR / "contracts.json"

EXPECTED_SUPPORTED_METHODS = [
    "CreateIntentTask",
    "RefineTask",
    "StartTask",
    "GetTask",
    "ListTaskCandidates",
    "GetTaskCandidateDetail",
    "ListTaskPublicSources",
    "GetSearchTaskDebug",
    "GetProviderCostSummary",
]

EXPECTED_P1_RULES = {"PDL-002", "SOCIAL-002", "IMAGE-001", "CAND-003", "CAND-004"}

RE_GW_ARROW = re.compile(
    r"^\[HTTP\] (?:-->|<--)(?:\s+\d+)? POST \S+ service=\S+ method=(\w+)"
)
RE_GW_REQUEST = re.compile(r"^\[HTTP\] request:\s*$")
RE_GW_RESPONSE = re.compile(r"^\[HTTP\] response:\s*$")
RE_QCL_REQUEST = re.compile(r"^(\w+) 脱敏请求数据:\s*$")
RE_QCL_RESPONSE = re.compile(r"^(\w+) 响应数据: HTTP (\d+) elapsed_ms=(\d+)\s*$")

FALLBACK_ROOT_KEY_BY_METHOD = {
    "GetSearchTaskDebug": "debug",
    "GetProviderCostSummary": "cost_summary",
}


def scan_balanced(text, start):
    """从 text[start]（必须是 '{' 或 '['）扫描括号平衡的 JSON 片段，返回结束下标。"""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def top_level_spans(text):
    spans = []
    i = 0
    while i < len(text):
        if text[i] in "{[":
            end = scan_balanced(text, i)
            if end is not None:
                spans.append((i, end))
                i = end
                continue
        i += 1
    return spans


class FixtureParseResult:
    def __init__(self, name):
        self.name = name
        self.blocks = []          # {"kind", "method", "payload", "line_start", "line_end"}
        self.parse_errors = []
        self.marker_methods = set()
        self.root_keys = set()


def parse_fixture(path):
    """解析一份夹具：识别 marker、抽取全部顶层 JSON 块并校验可解析。"""
    result = FixtureParseResult(path.name)
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    cleaned = [clean_log_line(line) for line in raw_lines]
    text = "\n".join(cleaned)
    line_offsets = []
    offset = 0
    for line in cleaned:
        line_offsets.append(offset)
        offset += len(line) + 1

    def line_of(pos):
        lo, hi = 0, len(line_offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_offsets[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    # marker → (kind, method)，method 对 Gateway 块来自最近的 -->/<-- 行
    markers = []
    current_method = None
    for idx, line in enumerate(cleaned):
        arrow = RE_GW_ARROW.match(line)
        if arrow:
            current_method = arrow.group(1)
            continue
        if RE_GW_REQUEST.match(line):
            markers.append(("request", current_method, idx))
            continue
        if RE_GW_RESPONSE.match(line):
            markers.append(("response", current_method, idx))
            continue
        qcl_req = RE_QCL_REQUEST.match(line)
        if qcl_req:
            markers.append(("request", qcl_req.group(1), idx))
            continue
        qcl_resp = RE_QCL_RESPONSE.match(line)
        if qcl_resp:
            markers.append(("response", qcl_resp.group(1), idx))
            continue

    spans = top_level_spans(text)
    span_by_start = {start: end for start, end in spans}
    used_spans = set()

    for kind, method, marker_line in markers:
        if method:
            result.marker_methods.add(method)
        search_from = line_offsets[marker_line] + len(cleaned[marker_line]) + 1
        json_start = None
        for start, end in spans:
            if start >= search_from:
                json_start = start
                break
        if json_start is None:
            result.parse_errors.append(f"{kind} marker '{method}' 后未找到 JSON 块（第 {marker_line + 1} 行）")
            continue
        used_spans.add(json_start)
        payload_text = text[json_start:span_by_start[json_start]]
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            result.parse_errors.append(f"{method} {kind} JSON 解析失败: {exc}")
            continue
        result.blocks.append(
            {
                "kind": kind,
                "method": method,
                "payload": payload,
                "line_start": line_of(json_start),
                "line_end": line_of(span_by_start[json_start] - 1),
            }
        )

    # 兜底识别：无 marker 的独立 JSON（根字段 debug / cost_summary）。
    # 夹具的独立 payload 均为对象；顶层 "[" 只可能来自 "[HTTP]" 等日志文本，跳过。
    for start, end in spans:
        if start in used_spans or text[start] != "{":
            continue
        payload_text = text[start:end]
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            result.parse_errors.append(f"独立 JSON 块解析失败（第 {line_of(start)} 行）: {exc}")
            continue
        if isinstance(payload, dict):
            result.root_keys.update(payload.keys())
            if "debug" in payload:
                result.marker_methods.add("GetSearchTaskDebug")
            if "cost_summary" in payload:
                result.marker_methods.add("GetProviderCostSummary")
        result.blocks.append(
            {
                "kind": "standalone",
                "method": None,
                "payload": payload,
                "line_start": line_of(start),
                "line_end": line_of(end - 1),
            }
        )
    return result


def load_contracts():
    return json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))


class TestPeopleSearchContracts(unittest.TestCase):
    """规则清单确认版与 Evidence Packet 字段确认版。"""

    @classmethod
    def setUpClass(cls):
        cls.contracts = load_contracts()
        cls.rules = cls.contracts["rules"]
        cls.rule_ids = [rule["rule_id"] for rule in cls.rules]

    def test_version_and_baseline(self):
        self.assertEqual(self.contracts["analyzer_version"], "people-search-v1")
        self.assertEqual(self.contracts["ruleset_version"], "2026-08-13")
        baseline = self.contracts["policy_baseline"]
        self.assertIn("feishu.cn", baseline["url"])
        self.assertEqual(baseline["policy_version_sample"], "people_image_v1")

    def test_supported_methods(self):
        self.assertEqual(self.contracts["supported_methods"], EXPECTED_SUPPORTED_METHODS)

    def test_outcome_and_verdict_enums(self):
        self.assertEqual(
            self.contracts["outcome_values"],
            ["PASS", "FAIL", "WARN", "UNKNOWN", "NOT_APPLICABLE"],
        )
        self.assertEqual(
            self.contracts["verdict_values"],
            ["NORMAL", "ISSUES_FOUND", "NEEDS_CONFIRMATION",
             "INCOMPLETE_EVIDENCE", "UNSUPPORTED_LOG"],
        )

    def test_ruleset_unique_and_complete(self):
        self.assertEqual(len(self.rules), 24, "规则清单应为 24 条")
        self.assertEqual(len(set(self.rule_ids)), 24, "rule_id 不允许重复")

    def test_rule_severity_levels(self):
        severities = {rule["rule_id"]: rule["severity"] for rule in self.rules}
        p1_rules = {rule_id for rule_id, sev in severities.items() if sev == "P1"}
        p0_rules = {rule_id for rule_id, sev in severities.items() if sev == "P0"}
        self.assertTrue(set(severities.values()) <= {"P0", "P1"})
        self.assertEqual(p1_rules, EXPECTED_P1_RULES)
        self.assertEqual(len(p0_rules), 19, "P0 规则应为 19 条")

    def test_rule_required_evidence_are_supported_methods(self):
        supported = set(EXPECTED_SUPPORTED_METHODS)
        for rule in self.rules:
            self.assertTrue(rule["required_evidence"], f"{rule['rule_id']} 缺少必需证据")
            self.assertTrue(
                set(rule["required_evidence"]) <= supported,
                f"{rule['rule_id']} 的必需证据不在受支持接口列表内",
            )

    def test_face_rule_reflects_known_gap(self):
        face = next(rule for rule in self.rules if rule["rule_id"] == "FACE-001")
        self.assertIn("已知能力缺失", face["title"])

    def test_evidence_packet_top_level_fields(self):
        packet = self.contracts["evidence_packet"]
        self.assertEqual(
            packet["top_level_fields"],
            ["analyzer_version", "task_summary", "coverage", "timeline",
             "candidate_summary", "diagnosis_summary", "cost_summary",
             "checks", "parse_warnings"],
        )

    def test_evidence_packet_struct_fields(self):
        packet = self.contracts["evidence_packet"]
        for field in ("task_id", "final_status", "candidate_count", "top_confidence_score"):
            self.assertIn(field, packet["task_summary_fields"])
        for field in ("create_task", "get_task", "candidate_list", "candidate_detail",
                      "debug", "cost_summary", "source_truncated", "parse_warnings"):
            self.assertIn(field, packet["coverage_fields"])
        for field in ("provider", "operation", "status", "start_time", "finish_time",
                      "http_status", "cache_hit", "candidate_count", "error_code",
                      "cost_status", "estimated_cost_microunit", "source"):
            self.assertIn(field, packet["timeline_fields"])
        self.assertEqual(
            packet["timeline_source_fields"],
            ["method", "json_path", "line_start", "line_end"],
        )
        for field in ("rule_id", "category", "outcome", "severity", "title",
                      "actual", "expected", "evidence"):
            self.assertIn(field, packet["check_fields"])
        self.assertEqual(
            packet["evidence_fields"],
            ["method", "json_path", "value", "line_start", "line_end"],
        )

    def test_evidence_packet_limits(self):
        limits = self.contracts["evidence_packet"]["limits"]
        self.assertEqual(limits["max_candidate_summary"], 20)
        self.assertEqual(limits["max_timeline_calls"], 100)
        self.assertEqual(limits["max_social_url_decisions"], 100)
        self.assertEqual(limits["max_cost_calls"], 100)
        self.assertEqual(limits["max_free_text_chars"], 2000)
        self.assertEqual(limits["max_packet_bytes"], 524288)


class TestPeopleSearchFixtures(unittest.TestCase):
    """夹具注册表、文件完整性与人工期望结论。"""

    @classmethod
    def setUpClass(cls):
        cls.contracts = load_contracts()
        cls.fixtures = cls.contracts["fixtures"]
        cls.rule_ids = {rule["rule_id"] for rule in cls.contracts["rules"]}
        cls.parsed = {}
        for fixture in cls.fixtures:
            path = FIXTURE_DIR / fixture["file"]
            if path.exists():
                cls.parsed[fixture["name"]] = parse_fixture(path)

    def test_registry_has_ten_unique_fixtures(self):
        names = [fixture["name"] for fixture in self.fixtures]
        self.assertEqual(len(self.fixtures), 10)
        self.assertEqual(len(set(names)), 10)

    def test_fixture_files_exist_and_not_empty(self):
        for fixture in self.fixtures:
            path = FIXTURE_DIR / fixture["file"]
            self.assertTrue(path.exists(), f"缺少夹具文件 {fixture['file']}")
            self.assertGreater(path.stat().st_size, 0, f"夹具文件为空 {fixture['file']}")

    def test_fixture_metadata_valid(self):
        verdict_values = set(self.contracts["verdict_values"])
        outcome_values = set(self.contracts["outcome_values"])
        for fixture in self.fixtures:
            self.assertIn(fixture["format"], ("gateway", "query_chain_logger"))
            self.assertIn(fixture["expected_verdict"], verdict_values)
            self.assertTrue(fixture["expected_methods"])
            for method in fixture["expected_methods"]:
                self.assertIn(method, EXPECTED_SUPPORTED_METHODS)
            for rule_id, outcome in fixture["expected_rules"].items():
                self.assertIn(rule_id, self.rule_ids, f"{fixture['name']} 引用未知规则 {rule_id}")
                self.assertIn(outcome, outcome_values)

    def test_all_json_blocks_parse(self):
        for fixture in self.fixtures:
            result = self.parsed[fixture["name"]]
            self.assertEqual(result.parse_errors, [], f"{fixture['file']} 存在 JSON 解析问题")
            self.assertTrue(result.blocks, f"{fixture['file']} 未抽取出任何 JSON 块")

    def test_expected_methods_present(self):
        for fixture in self.fixtures:
            result = self.parsed[fixture["name"]]
            for method in fixture["expected_methods"]:
                self.assertIn(
                    method, result.marker_methods,
                    f"{fixture['file']} 缺少接口 {method} 的 marker 或兜底识别根字段",
                )

    def test_gateway_fixtures_use_http_markers(self):
        for fixture in self.fixtures:
            if fixture["format"] != "gateway":
                continue
            text = (FIXTURE_DIR / fixture["file"]).read_text(encoding="utf-8")
            self.assertIn("[HTTP] --> POST", text, fixture["file"])
            self.assertIn("[HTTP] response:", text, fixture["file"])

    def test_query_chain_logger_fixture_uses_markers(self):
        text = (FIXTURE_DIR / "f06_social_link_queue_dedupe.log").read_text(encoding="utf-8")
        self.assertIn("脱敏请求数据:", text)
        self.assertRegex(text, r"响应数据: HTTP 200 elapsed_ms=\d+")

    def test_verdict_consistent_with_expected_rules(self):
        for fixture in self.fixtures:
            has_fail = "FAIL" in fixture["expected_rules"].values()
            has_unknown = "UNKNOWN" in fixture["expected_rules"].values()
            if has_fail:
                self.assertEqual(
                    fixture["expected_verdict"], "ISSUES_FOUND",
                    f"{fixture['name']} 存在 FAIL 规则但结论不是 ISSUES_FOUND",
                )
            elif has_unknown:
                self.assertEqual(
                    fixture["expected_verdict"], "INCOMPLETE_EVIDENCE",
                    f"{fixture['name']} 存在 UNKNOWN 规则但结论不是 INCOMPLETE_EVIDENCE",
                )
            else:
                self.assertEqual(
                    fixture["expected_verdict"], "NORMAL",
                    f"{fixture['name']} 无 FAIL 规则但结论不是 NORMAL",
                )

    def test_p0_rule_coverage(self):
        """阶段 0 完成条件：每条 P0 规则至少有一个正例或反例。"""
        p0_rules = {
            rule["rule_id"] for rule in self.contracts["rules"] if rule["severity"] == "P0"
        }
        covered = {}
        for fixture in self.fixtures:
            for rule_id, outcome in fixture["expected_rules"].items():
                if outcome in ("PASS", "FAIL"):
                    covered.setdefault(rule_id, set()).add(outcome)
        missing = sorted(rule_id for rule_id in p0_rules if rule_id not in covered)
        self.assertEqual(missing, [], f"以下 P0 规则缺少正例/反例夹具: {missing}")

    def test_p1_rule_coverage(self):
        covered = set()
        for fixture in self.fixtures:
            for rule_id, outcome in fixture["expected_rules"].items():
                if outcome in ("PASS", "FAIL"):
                    covered.add(rule_id)
        missing = sorted(EXPECTED_P1_RULES - covered)
        self.assertEqual(missing, [], f"以下 P1 规则缺少正例/反例夹具: {missing}")

    def test_f03_tool_calls_in_reverse_start_time(self):
        result = self.parsed["f03_wiki_unique_but_pdl_called"]
        debug_blocks = [
            block for block in result.blocks
            if isinstance(block["payload"], dict) and "debug" in block["payload"]
        ]
        self.assertTrue(debug_blocks, "f03 缺少 debug JSON 块")
        calls = debug_blocks[0]["payload"]["debug"]["agent_tool_calls"]
        start_times = [call["start_time"] for call in calls]
        self.assertEqual(
            start_times, sorted(start_times, reverse=True),
            "f03 的 agent_tool_calls 应按 start_time 倒序提供，验证解析侧排序契约",
        )

    def test_f06_email_kept_as_is(self):
        text = (FIXTURE_DIR / "f06_social_link_queue_dedupe.log").read_text(encoding="utf-8")
        self.assertIn("carol@example.com", text, "评审确认邮箱允许发送给模型，夹具应保留原值")

    def test_f08_face_comparison_shown_as_known_gap(self):
        text = (FIXTURE_DIR / "f08_image_lens_vision_face_not_connected.log").read_text(encoding="utf-8")
        self.assertIn("not_performed", text)
        self.assertIn("已知能力缺失", text)
        self.assertNotIn("similarity", text, "未接入 Face Comparison 时不应出现相似度数值")

    def test_f10_contains_two_gettask_polls(self):
        result = self.parsed["f10_technical_failure_misclassified"]
        gettask_responses = [
            block for block in result.blocks
            if block["method"] == "GetTask" and block["kind"] == "response"
        ]
        self.assertEqual(len(gettask_responses), 2, "f10 应包含一次 RUNNING 轮询和一次终态")
        statuses = [block["payload"]["responses"][0]["data"]["status"] for block in gettask_responses]
        self.assertEqual(statuses, ["RUNNING", "FAILED"])


if __name__ == "__main__":
    unittest.main()
