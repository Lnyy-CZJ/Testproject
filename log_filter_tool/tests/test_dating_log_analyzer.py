"""Dating 日志聚合器的任务生命周期与上传资源回归测试。"""

import ast
import builtins
from collections import Counter
import http.client
import json
import os
from pathlib import Path
import re
import socket
from statistics import median
from time import perf_counter
import unittest
from unittest.mock import patch
import urllib.request

from dating_log_analyzer import (
    analyze_dating_log,
    build_field_index,
    build_task_snapshot,
    build_upload_assets,
    classify_presence,
)
from gateway_log_parser import parse_interface_log


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dating"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLY_TASK_ID = "dating_task_147b21ac92063a1b24bbb8f8865e3bde"
ANALYSIS_TASK_ID = "dating_task_0e872c9510861f0b21fa76a91076f733"
MAX_DATING_LOG_BYTES = 10 * 1024 * 1024

DATING_RUNTIME_MODULES = (
    "gateway_log_parser.py",
    "dating_log_analyzer.py",
    "dating_log_rules.py",
)
FORBIDDEN_EXTERNAL_IMPORTS = (
    "socket",
    "http.client",
    "urllib.request",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "openai",
    "anthropic",
    "cohere",
    "google.generativeai",
    "google.genai",
)
BUSINESS_ID_KEYS = {
    "task_id",
    "task_ids",
    "asset_id",
    "asset_ids",
    "result_id",
    "reply_id",
    "signal_id",
    "event_id",
    "message_id",
    "evidence_message_ids",
    "role_id",
    "person_id",
}


def _dotted_name(node: ast.AST) -> str:
    """将 AST Name/Attribute 转为点分调用名，供离线能力静态验收。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _collect_business_ids(value: object) -> set[str]:
    """收集响应中的业务 ID；解析器内部 call_id 不属于业务 ID。"""
    found: set[str] = set()

    def visit(current: object, key: str | None = None) -> None:
        if isinstance(current, dict):
            for child_key, child_value in current.items():
                visit(child_value, child_key)
            return
        if isinstance(current, list):
            for item in current:
                visit(item, key)
            return
        if key in BUSINESS_ID_KEYS and isinstance(current, str) and current:
            found.add(current)

    visit(value)
    return found


def _build_large_dating_log(base_log: str) -> str:
    """在有效 golden 后追加纯诊断文本，构造略低于 10 MiB 的确定性日志。"""
    target_bytes = MAX_DATING_LOG_BYTES - 1024
    marker = "\nPERFORMANCE_PADDING="
    padding_bytes = (
        target_bytes
        - len(base_log.encode("utf-8"))
        - len(marker.encode("utf-8"))
    )
    if padding_bytes < 0:
        raise ValueError("golden 日志已超过性能验收目标大小")
    large_log = base_log + marker + ("x" * padding_bytes)
    if len(large_log.encode("utf-8")) != target_bytes:
        raise AssertionError("性能日志必须按字节精确构造")
    return large_log


def _read_fixture(name: str) -> str:
    """读取固定 Dating 样例，避免各测试重复处理路径和编码。"""
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _truncate_before_method(log_text: str, method_name: str) -> str:
    """按 parser 行号裁剪指定调用之前的日志，避免依赖易碎的文本标记。"""
    parsed = parse_interface_log(log_text)
    call = next(call for call in parsed["calls"] if call["method_name"] == method_name)
    line_start = call["request"]["line_start"]
    return "\n".join(log_text.splitlines()[: line_start - 1]) + "\n"


def _truncate_after_last_processing_poll(log_text: str) -> str:
    """保留最后一次 processing Poll 响应，移除 succeeded Poll 和 Result。"""
    parsed = parse_interface_log(log_text)
    processing_polls = [
        call
        for call in parsed["calls"]
        if call["method_name"] in {"GetTask", "GetAnalysisTask"}
        and (call.get("response") or {}).get("data", {}).get("status")
        == "processing"
    ]
    line_end = processing_polls[-1]["response"]["line_end"]
    return "\n".join(log_text.splitlines()[:line_end]) + "\n"


def _gateway_call(
    call_id: str,
    method_name: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
) -> dict:
    """构造与 parser 完整字段边界一致的成功 Gateway 调用。"""
    return {
        "call_id": call_id,
        "gateway_exchange_id": call_id.replace("call", "gateway"),
        "sequence": int(call_id.rsplit("_", 1)[-1]),
        "transport": "gateway",
        "service_name": "tool.dating.DatingAssistantService",
        "method_name": method_name,
        "request": {
            "timestamp": "2026-08-29 18:00:00.000",
            "line_start": 1,
            "line_end": 1,
            "client_request_id": None,
            "url": "https://gateway.example/dating/gateway/invoke",
            "headers": {},
            "params": params or {},
        },
        "response": {
            "timestamp": "2026-08-29 18:00:00.100",
            "line_start": 2,
            "line_end": 2,
            "http_status": 200,
            "elapsed_ms": 100.0,
            "headers": {},
            "gateway": {"code": 0},
            "sub_response": {"success": True, "code": 0},
            "data": data or {},
        },
        "result_class": "success",
        "parse_status": "PARSED",
        "warnings": [],
    }


def _put_call(call_id: str, url: str) -> dict:
    """构造成功 PUT；URL 是上传关联测试的唯一对象路径证据。"""
    call = _gateway_call(call_id, "PUT")
    call.update(
        {
            "gateway_exchange_id": None,
            "transport": "object_storage_put",
            "service_name": "object_storage",
        }
    )
    call["request"]["url"] = url
    call["response"]["gateway"] = None
    call["response"]["sub_response"] = None
    call["response"]["data"] = None
    return call


def _fixture_source() -> dict:
    """提供字段索引测试使用的固定 Result 响应块证据。"""
    return {
        "method": "GetTaskResult",
        "call_id": "call_result",
        "line_start": 20,
        "line_end": 40,
    }


def _analyze_reply_fixture() -> dict:
    """通过公共入口分析 Reply 黄金日志。"""
    return analyze_dating_log(_read_fixture("reply_generation_multi_image_success.log"))


def _analyze_analysis_fixture() -> dict:
    """通过公共入口分析 Analysis 黄金日志。"""
    return analyze_dating_log(
        _read_fixture("relationship_analysis_multi_image_success.log")
    )


def _snapshot_for_schema_result(
    result_payload: object,
    schema_version: str | None,
    *,
    include_outer_schema: bool = True,
    include_result: bool = True,
) -> dict:
    """构造包含一次成功 Result 的最小真实调用链，供 Schema 边界测试复用。"""
    task_id = "task_schema_projection"
    is_analysis = isinstance(schema_version, str) and "relationship_analysis" in schema_version
    task_type = "relationship_analysis" if is_analysis else "reply_generation"
    create_method = "CreateAnalysisTask" if is_analysis else "CreateReplyTask"
    result_method = "GetAnalysisResult" if is_analysis else "GetTaskResult"
    result_data = {
        "task_id": task_id,
        "task_type": task_type,
    }
    if include_result:
        result_data["result"] = result_payload
    if include_outer_schema:
        result_data["schema_version"] = schema_version
    calls = [
        _gateway_call(
            "call_0001",
            create_method,
            params={"asset_ids": []},
            data={
                "task_id": task_id,
                "task_type": task_type,
                "status": "queued",
                "phase": "queued",
            },
        ),
        _gateway_call(
            "call_0002",
            result_method,
            params={"task_id": task_id},
            data=result_data,
        ),
    ]
    snapshot, _ = build_task_snapshot(calls, [], task_id)
    return snapshot


class PresenceClassificationTests(unittest.TestCase):
    """锁定字段存在、显式空值和 Schema 缺失之间的事实分类。"""

    def test_presence_states_are_distinct(self):
        """非空、null、各类空容器和缺失不能被合并成同一状态。"""
        self.assertEqual(classify_presence("value"), "PRESENT")
        self.assertEqual(classify_presence(None), "NULL")
        self.assertEqual(classify_presence(""), "EMPTY_STRING")
        self.assertEqual(classify_presence([]), "EMPTY_ARRAY")
        self.assertEqual(classify_presence({}), "EMPTY_OBJECT")
        self.assertEqual(classify_presence(None, missing=True), "MISSING")


class FieldIndexTests(unittest.TestCase):
    """验证通用字段树索引的值、Schema 和资源上限契约。"""

    def test_long_text_is_truncated_exactly_with_block_evidence(self):
        """自由文本仅保留前 20000 字符，并保留完整 Result 块证据。"""
        fields, warnings = build_field_index(
            {"note": "x" * 20001},
            root_path="result",
            source=_fixture_source(),
        )
        note = next(field for field in fields if field["path"] == "result.note")

        self.assertEqual(note["value"], "x" * 20000)
        self.assertEqual(len(note["value"]), 20000)
        self.assertTrue(note["value_truncated"])
        self.assertEqual(
            note["source"],
            {
                "method": "GetTaskResult",
                "call_id": "call_result",
                "line_start": 20,
                "line_end": 40,
                "location_precision": "block",
            },
        )
        self.assertIn("VALUE_TRUNCATED", {item["code"] for item in warnings})

    def test_array_paths_use_schema_templates_and_unknown_fields_are_preserved(self):
        """输出保留实际索引，但 Schema 匹配必须把数组索引归一化为 []。"""
        fields, warnings = build_field_index(
            {"items": [{"known": "yes", "extra": "keep"}]},
            root_path="result",
            source=_fixture_source(),
            known_paths={
                "result",
                "result.items",
                "result.items[]",
                "result.items[].known",
                "result.required",
            },
            required_paths=("result.required",),
        )
        by_path = {field["path"]: field for field in fields}

        self.assertEqual(warnings, [])
        self.assertTrue(by_path["result.items[0].known"]["schema_known"])
        self.assertFalse(by_path["result.items[0].extra"]["schema_known"])
        self.assertEqual(by_path["result.items[0]"]["array_index"], 0)
        self.assertIsNone(by_path["result.items[0]"]["key"])
        self.assertEqual(by_path["result.items[0].known"]["key"], "known")
        self.assertEqual(by_path["result.required"]["presence"], "MISSING")
        self.assertEqual(by_path["result.required"]["value_type"], "missing")
        self.assertTrue(by_path["result.required"]["schema_known"])

    def test_max_depth_fifty_stops_deeper_nodes(self):
        """根节点深度为 0；深度 50 可见，深度 51 必须停止展开。"""
        payload: object = "leaf"
        for index in reversed(range(51)):
            payload = {f"level_{index}": payload}

        fields, warnings = build_field_index(
            payload,
            root_path="result",
            source=_fixture_source(),
        )

        self.assertEqual(len(fields), 51)
        self.assertIn(
            "MAX_FIELD_DEPTH_REACHED", {item["code"] for item in warnings}
        )
        self.assertTrue(fields[-1]["path"].endswith(".level_49"))

    def test_max_field_count_twenty_thousand_stops_expansion(self):
        """容器节点计入 20000 上限，超出的数组项不得进入索引。"""
        fields, warnings = build_field_index(
            list(range(20000)),
            root_path="result",
            source=_fixture_source(),
        )

        self.assertEqual(len(fields), 20000)
        self.assertEqual(fields[-1]["path"], "result[19998]")
        self.assertIn(
            "MAX_FIELD_COUNT_REACHED", {item["code"] for item in warnings}
        )

    def test_full_field_capacity_warns_for_omitted_required_nodes(self):
        """现有节点恰好占满上限时，required 截断必须有确定性证据。"""
        fields, warnings = build_field_index(
            {"existing": 1},
            root_path="result",
            source=_fixture_source(),
            known_paths={
                "result",
                "result.existing",
                "result.required_a",
                "result.required_b",
            },
            required_paths=("result.required_a", "result.required_b"),
            max_fields=2,
        )
        count_warnings = [
            warning
            for warning in warnings
            if warning["code"] == "MAX_FIELD_COUNT_REACHED"
        ]

        self.assertEqual(len(fields), 2)
        self.assertEqual(
            [field["path"] for field in fields],
            ["result", "result.existing"],
        )
        self.assertEqual(len(count_warnings), 1)
        self.assertEqual(count_warnings[0]["json_path"], "result.required_a")
        self.assertEqual(
            count_warnings[0]["omitted_required_paths"],
            ["result.required_a", "result.required_b"],
        )


class DatingResultProjectionTests(unittest.TestCase):
    """锁定两个 v1 Schema 的业务摘要、分组、字段与空值健康。"""

    def test_reply_v1_summary_sections_and_empty_field_health(self):
        """Reply 黄金结果必须逐项匹配 PRD §14，并保留空字符串和 null。"""
        task = _analyze_reply_fixture()["task_snapshot"]
        fields = {field["path"]: field for field in task["result_fields"]}

        self.assertEqual(task["schema_status"], "KNOWN_SCHEMA")
        self.assertEqual(
            task["result_summary"],
            {
                "conversation_stage": "boundary",
                "moment_type": "rejection",
                "reply_state": "user_waiting",
                "requested_intent": "",
                "effective_goal": "respect_boundary",
                "signal_count": 1,
                "role_count": 1,
                "reply_count": 4,
                "top_pick_reply_id": "reply_1",
                "person_history_used": False,
                "is_degraded": False,
                "warning_count": 1,
            },
        )
        self.assertEqual(
            [(section["label"], section["path"]) for section in task["result_sections"]],
            [
                ("上下文", "result.context"),
                ("综合分析", "result.comprehensive_analysis"),
                ("当前情况", "result.whats_happening"),
                ("推荐角色", "result.roles"),
                ("人物关联", "result.association"),
                ("降级", "result.degradation"),
                ("警告", "result.warnings"),
            ],
        )
        self.assertEqual(task["result_sections"][0]["value"], task["result_payload"]["context"])
        self.assertEqual(
            fields["result.context.requested_intent"]["presence"], "EMPTY_STRING"
        )
        self.assertEqual(fields["result.association.person_id"]["presence"], "NULL")
        self.assertTrue(fields["result.roles[0].replies[3].text"]["schema_known"])
        self.assertEqual(
            task["field_health"],
            {
                "total_field_count": 66,
                "present_count": 63,
                "null_count": 2,
                "empty_string_count": 1,
                "empty_array_count": 0,
                "empty_object_count": 0,
                "missing_count": 0,
                "unknown_schema_field_count": 0,
            },
        )

    def test_analysis_v1_summary_sections_and_empty_field_health(self):
        """Analysis 黄金结果必须逐项匹配 PRD §15，并保留 null 与空数组。"""
        task = _analyze_analysis_fixture()["task_snapshot"]
        fields = {field["path"]: field for field in task["result_fields"]}

        self.assertEqual(task["schema_status"], "KNOWN_SCHEMA")
        self.assertEqual(
            task["result_summary"],
            {
                "relationship_stage": "ENDED",
                "current_state": "SETTING_BOUNDARIES",
                "reliability_level": "VERY_HIGH",
                "uploaded_asset_count": 3,
                "valid_asset_count": 3,
                "ignored_asset_count": 0,
                "analyzed_message_count": 38,
                "positive_signal_count": 3,
                "watch_signal_count": 1,
                "risk_signal_count": 0,
                "turning_point_count": 3,
                "warning_count": 0,
            },
        )
        self.assertEqual(
            [(section["label"], section["path"]) for section in task["result_sections"]],
            [
                ("分析范围", "result.analysis_scope"),
                ("总览", "result.overview"),
                ("Dashboard", "result.overview.dashboard"),
                ("聊天信号", "result.chat_signals"),
                ("关键事件", "result.key_events"),
                ("警告", "result.warnings"),
            ],
        )
        self.assertEqual(
            fields["result.overview.dashboard.effort.you_score"]["presence"],
            "NULL",
        )
        self.assertEqual(
            fields["result.overview.dashboard.effort.you_score"]["label"],
            "你的投入度",
        )
        self.assertEqual(
            fields["result.chat_signals.risk_signals"]["presence"], "EMPTY_ARRAY"
        )
        self.assertEqual(
            task["field_health"],
            {
                "total_field_count": 101,
                "present_count": 94,
                "null_count": 3,
                "empty_string_count": 0,
                "empty_array_count": 4,
                "empty_object_count": 0,
                "missing_count": 0,
                "unknown_schema_field_count": 0,
            },
        )

    def test_known_schema_keeps_unknown_fields_and_adds_required_missing_nodes(self):
        """扩展字段不能丢弃；未返回的已知必填分组必须显式标为 MISSING。"""
        payload = {
            "schema_version": "dating.reply_generation.v1",
            "context": {},
            "roles": [],
            "future_extension": {"enabled": True},
        }
        task = _snapshot_for_schema_result(
            payload, "dating.reply_generation.v1"
        )
        fields = {field["path"]: field for field in task["result_fields"]}

        self.assertIs(task["result_payload"], payload)
        self.assertFalse(fields["result.future_extension"]["schema_known"])
        self.assertFalse(fields["result.future_extension.enabled"]["schema_known"])
        self.assertEqual(fields["result.association"]["presence"], "MISSING")
        self.assertEqual(fields["result.degradation"]["presence"], "MISSING")
        self.assertEqual(fields["result.warnings"]["presence"], "MISSING")
        self.assertEqual(task["field_health"]["missing_count"], 3)
        self.assertEqual(task["field_health"]["unknown_schema_field_count"], 2)

    def test_known_outer_schema_without_result_emits_required_missing_fields(self):
        """data.result 缺失时保留 Task 4 presence，并输出全部必填 MISSING 证据。"""
        task = _snapshot_for_schema_result(
            None,
            "dating.reply_generation.v1",
            include_result=False,
        )

        self.assertIs(task["result_payload_present"], False)
        self.assertIsNone(task["result_payload"])
        self.assertEqual(task["schema_status"], "KNOWN_SCHEMA")
        self.assertEqual(
            [field["path"] for field in task["result_fields"]],
            [
                "result.schema_version",
                "result.context",
                "result.roles",
                "result.association",
                "result.degradation",
                "result.warnings",
            ],
        )
        self.assertTrue(
            all(
                field["presence"] == "MISSING"
                for field in task["result_fields"]
            )
        )
        self.assertTrue(
            all(
                field["source"]
                == {
                    "method": "GetTaskResult",
                    "call_id": "call_0002",
                    "line_start": 2,
                    "line_end": 2,
                    "location_precision": "block",
                }
                for field in task["result_fields"]
            )
        )
        self.assertEqual(
            task["field_health"],
            {
                "total_field_count": 6,
                "present_count": 0,
                "null_count": 0,
                "empty_string_count": 0,
                "empty_array_count": 0,
                "empty_object_count": 0,
                "missing_count": 6,
                "unknown_schema_field_count": 0,
            },
        )
        self.assertEqual(task["result_summary"], {})
        self.assertEqual(task["result_sections"], [])

    def test_analysis_summary_distinguishes_missing_arrays_from_empty_arrays(self):
        """Schema path 缺失返回 None；字段存在且为空数组才返回计数 0。"""
        payload = {
            "schema_version": "dating.relationship_analysis.v1",
            "analysis_scope": {
                "uploaded_asset_count": 0,
                "valid_asset_count": 0,
                "ignored_asset_count": 0,
            },
            "overview": {},
            "chat_signals": {
                "positive_signals": [],
                "risk_signals": [],
            },
            "key_events": {"turning_points": []},
            "warnings": [],
        }
        task = _snapshot_for_schema_result(
            payload, "dating.relationship_analysis.v1"
        )

        self.assertEqual(task["result_summary"]["positive_signal_count"], 0)
        self.assertIsNone(task["result_summary"]["watch_signal_count"])
        self.assertEqual(task["result_summary"]["risk_signal_count"], 0)
        self.assertEqual(task["result_summary"]["turning_point_count"], 0)
        self.assertIsNone(task["result_summary"]["analyzed_message_count"])


class UnknownSchemaCompatibilityTests(unittest.TestCase):
    """验证未知版本不丢数据，也不会误套用 v1 业务投影。"""

    def test_unknown_schema_keeps_generic_tree_without_business_summary(self):
        """未知版本输出通用字段树、空业务摘要和稳定 UNKNOWN_SCHEMA warning。"""
        payload = {
            "schema_version": "dating.relationship_analysis.v2",
            "future": {"score": 9},
        }
        task = _snapshot_for_schema_result(
            payload, "dating.relationship_analysis.v2"
        )
        warning_codes = {warning["code"] for warning in task["warnings"]}

        self.assertIs(task["result_payload"], payload)
        self.assertEqual(task["schema_status"], "UNKNOWN_SCHEMA")
        self.assertEqual(task["result_summary"], {})
        self.assertEqual(task["result_sections"], [])
        self.assertEqual(
            [field["path"] for field in task["result_fields"]],
            [
                "result",
                "result.schema_version",
                "result.future",
                "result.future.score",
            ],
        )
        self.assertTrue(
            all(field["schema_known"] is False for field in task["result_fields"])
        )
        self.assertEqual(task["field_health"]["unknown_schema_field_count"], 4)
        self.assertIn("UNKNOWN_SCHEMA_VERSION", warning_codes)

    def test_missing_outer_schema_uses_inner_version_and_warns(self):
        """data.schema_version 缺失时使用 result.schema_version，但保留证据 warning。"""
        payload = {
            "schema_version": "dating.reply_generation.v1",
            "context": {},
            "roles": [],
            "association": {},
            "degradation": {},
            "warnings": [],
        }
        task = _snapshot_for_schema_result(
            payload,
            "dating.reply_generation.v1",
            include_outer_schema=False,
        )

        self.assertEqual(task["schema_version"], "dating.reply_generation.v1")
        self.assertEqual(task["schema_status"], "KNOWN_SCHEMA")
        self.assertIn(
            "OUTER_SCHEMA_VERSION_MISSING",
            {warning["code"] for warning in task["warnings"]},
        )


class DatingTaskAggregationTests(unittest.TestCase):
    """锁定 Reply/Analysis 的上传链路和异步任务黄金指标。"""

    def test_reply_task_lifecycle_and_assets(self):
        """Reply 必须保留全部 Poll，并关联两个完整且实际使用的资源。"""
        log_text = _read_fixture("reply_generation_multi_image_success.log")
        result = analyze_dating_log(log_text)
        parsed = parse_interface_log(log_text)

        # Task 4 的公共入口只能返回设计文档约定的基础结构；Schema、规则和报告
        # 属于后续任务，不能在这里提前扩展顶层协议。
        self.assertEqual(
            list(result),
            [
                "analyzer_version",
                "parser_version",
                "supported",
                "detected_domain",
                "selection_error",
                "task_ids",
                "summary",
                "interface_statistics",
                "flow_steps",
                "calls",
                "task_snapshot",
                "parse_warnings",
            ],
        )
        self.assertTrue(result["supported"])
        self.assertEqual(result["detected_domain"], "dating")
        self.assertIsNone(result["selection_error"])
        self.assertEqual(result["task_ids"], [REPLY_TASK_ID])
        self.assertEqual(result["calls"], parsed["calls"])
        self.assertEqual(result["flow_steps"], parsed["flow_steps"])
        self.assertEqual(result["parse_warnings"], parsed["parse_warnings"])

        task = result["task_snapshot"]
        self.assertEqual(task["task_id"], REPLY_TASK_ID)
        self.assertEqual(task["task_type"], "reply_generation")
        self.assertEqual(task["schema_version"], "dating.reply_generation.v1")
        self.assertEqual(task["create_call_id"], "call_0009")
        self.assertEqual(
            task["poll_call_ids"],
            [f"call_{sequence:04d}" for sequence in range(10, 21)],
        )
        self.assertEqual(task["result_call_id"], "call_0021")

        lifecycle = task["lifecycle"]
        self.assertEqual(lifecycle["initial_status"], "queued")
        self.assertEqual(lifecycle["final_status"], "succeeded")
        self.assertEqual(lifecycle["final_phase"], "finalizing")
        self.assertEqual(lifecycle["final_progress_percent"], 100)
        self.assertEqual(lifecycle["poll_count"], 11)
        self.assertEqual(lifecycle["duration_ms"], 11781)
        self.assertFalse(lifecycle["retryable"])
        self.assertEqual(lifecycle["error_code"], "")
        self.assertTrue(lifecycle["terminal"])

        samples = task["status_samples"]
        self.assertEqual(len(samples), 11)
        self.assertEqual(
            Counter(sample["status"] for sample in samples),
            {"queued": 1, "processing": 9, "succeeded": 1},
        )
        self.assertEqual(
            [sample["call_id"] for sample in samples], task["poll_call_ids"]
        )
        self.assertEqual(
            task["progress_diagnostics"],
            {
                "distinct_progress_values": [5, 30, 100],
                "unchanged_poll_count": 8,
                "longest_unchanged_progress": 30,
            },
        )

        self.assertEqual(len(task["input_assets"]), 2)
        self.assertTrue(
            all(asset["upload_state"] == "complete" for asset in task["input_assets"])
        )
        self.assertTrue(all(asset["used_by_task"] for asset in task["input_assets"]))
        self.assertEqual(
            task["result_payload"]["schema_version"],
            "dating.reply_generation.v1",
        )
        self.assertEqual(
            result["summary"],
            {
                "gateway_call_count": 19,
                "logical_interface_call_count": 19,
                "upload_call_count": 2,
                "http_error_count": 0,
                "gateway_error_count": 0,
                "business_error_count": 0,
                "unmatched_request_count": 0,
                "unmatched_response_count": 0,
                "parse_warning_count": 0,
                "task_count": 1,
                "result_count": 1,
                "check_fail_count": 0,
                "check_warn_count": 0,
                "check_unknown_count": 0,
            },
        )

    def test_analysis_task_lifecycle_and_assets(self):
        """Analysis 必须保留 21 次 Poll，并关联三个完整且实际使用的资源。"""
        result = analyze_dating_log(
            _read_fixture("relationship_analysis_multi_image_success.log")
        )
        task = result["task_snapshot"]

        self.assertEqual(result["task_ids"], [ANALYSIS_TASK_ID])
        self.assertEqual(task["task_id"], ANALYSIS_TASK_ID)
        self.assertEqual(task["task_type"], "relationship_analysis")
        self.assertEqual(
            task["schema_version"], "dating.relationship_analysis.v1"
        )
        self.assertEqual(task["lifecycle"]["poll_count"], 21)
        self.assertEqual(task["lifecycle"]["final_status"], "succeeded")
        self.assertEqual(task["lifecycle"]["final_phase"], "finalizing")
        self.assertEqual(task["lifecycle"]["final_progress_percent"], 100)
        self.assertEqual(task["lifecycle"]["duration_ms"], 23337)
        self.assertTrue(task["lifecycle"]["terminal"])

        samples = task["status_samples"]
        self.assertEqual(len(samples), 21)
        self.assertEqual(
            Counter(sample["status"] for sample in samples),
            {"queued": 1, "processing": 19, "succeeded": 1},
        )
        self.assertEqual(
            task["progress_diagnostics"],
            {
                "distinct_progress_values": [5, 30, 100],
                "unchanged_poll_count": 18,
                "longest_unchanged_progress": 30,
            },
        )

        self.assertEqual(len(task["input_assets"]), 3)
        self.assertTrue(
            all(asset["upload_state"] == "complete" for asset in task["input_assets"])
        )
        self.assertTrue(all(asset["used_by_task"] for asset in task["input_assets"]))
        self.assertEqual(
            task["result_payload"]["schema_version"],
            "dating.relationship_analysis.v1",
        )
        self.assertEqual(result["summary"]["gateway_call_count"], 30)
        self.assertEqual(result["summary"]["logical_interface_call_count"], 30)
        self.assertEqual(result["summary"]["upload_call_count"], 3)
        self.assertEqual(result["summary"]["result_count"], 1)


class DatingTaskSelectionTests(unittest.TestCase):
    """验证 0/1/多任务和显式 task_id 的稳定选择契约。"""

    @classmethod
    def setUpClass(cls):
        """一次读取两份较大的固定日志，测试中仅做确定性拼接或裁剪。"""
        cls.reply_log = _read_fixture("reply_generation_multi_image_success.log")
        cls.analysis_log = _read_fixture(
            "relationship_analysis_multi_image_success.log"
        )

    def test_upload_only_log_has_no_selected_task(self):
        """只有上传调用时仍识别 Dating，但不能从普通全文捏造 task_id。"""
        upload_only = _truncate_before_method(self.reply_log, "CreateReplyTask")
        log_text = upload_only + "plain note: dating_task_not_a_structured_value\n"

        result = analyze_dating_log(log_text)

        self.assertTrue(result["supported"])
        self.assertEqual(result["task_ids"], [])
        self.assertIsNone(result["selection_error"])
        self.assertIsNone(result["task_snapshot"])
        self.assertEqual(result["summary"]["task_count"], 0)
        self.assertEqual(result["summary"]["result_count"], 0)

    def test_multiple_tasks_require_explicit_selection(self):
        """两个已知任务且未指定 ID 时必须稳定返回 MULTIPLE_TASKS_FOUND。"""
        result = analyze_dating_log(self.reply_log + "\n" + self.analysis_log)

        self.assertEqual(result["task_ids"], [REPLY_TASK_ID, ANALYSIS_TASK_ID])
        self.assertEqual(result["selection_error"], "MULTIPLE_TASKS_FOUND")
        self.assertIsNone(result["task_snapshot"])
        self.assertEqual(result["summary"]["task_count"], 0)

    def test_explicit_reply_id_selects_reply_even_when_analysis_appears_first(self):
        """显式选择不得退化为“取日志中的第一个任务”。"""
        combined = self.analysis_log + "\n" + self.reply_log

        result = analyze_dating_log(combined, requested_task_id=REPLY_TASK_ID)

        self.assertEqual(result["task_ids"], [ANALYSIS_TASK_ID, REPLY_TASK_ID])
        self.assertIsNone(result["selection_error"])
        self.assertEqual(result["task_snapshot"]["task_id"], REPLY_TASK_ID)
        self.assertEqual(result["task_snapshot"]["task_type"], "reply_generation")
        self.assertEqual(len(result["task_snapshot"]["input_assets"]), 2)
        self.assertTrue(
            all(
                asset["used_by_task"]
                for asset in result["task_snapshot"]["input_assets"]
            )
        )

    def test_unknown_explicit_task_id_returns_task_not_found(self):
        """显式 ID 不存在时不能回退到唯一或第一个已识别任务。"""
        result = analyze_dating_log(
            self.reply_log, requested_task_id="dating_task_missing"
        )

        self.assertEqual(result["task_ids"], [REPLY_TASK_ID])
        self.assertEqual(result["selection_error"], "TASK_NOT_FOUND")
        self.assertIsNone(result["task_snapshot"])


class DatingUnfinishedTaskTests(unittest.TestCase):
    """验证日志截断时只保留已知状态，不伪造终态、时长或 Result。"""

    def test_processing_log_remains_non_terminal_without_result(self):
        """最后一次 processing Poll 必须成为 final sample，但 terminal 为假。"""
        truncated_log = _truncate_after_last_processing_poll(
            _read_fixture("reply_generation_multi_image_success.log")
        )

        result = analyze_dating_log(truncated_log)
        task = result["task_snapshot"]
        lifecycle = task["lifecycle"]

        self.assertEqual(lifecycle["final_status"], "processing")
        self.assertEqual(lifecycle["final_phase"], "analyzing")
        self.assertEqual(lifecycle["final_progress_percent"], 30)
        self.assertFalse(lifecycle["terminal"])
        self.assertIsNone(lifecycle["duration_ms"])
        self.assertEqual(lifecycle["poll_count"], 10)
        self.assertEqual(task["status_samples"][-1]["status"], "processing")
        self.assertIsNone(task["result_call_id"])
        self.assertIsNone(task["result_payload"])
        self.assertIsNone(task["schema_version"])
        self.assertEqual(result["summary"]["result_count"], 0)


class DatingRawResultTests(unittest.TestCase):
    """锁定 Task 4 对 Result 原值的无损保留和字段存在性语义。"""

    def _snapshot_for_result(self, *, present: bool, value=None) -> dict:
        """构造成功 Result 调用；present=False 表示 data 中没有 result 键。"""
        task_id = "task_raw_result"
        result_data = {
            "task_id": task_id,
            "task_type": "reply_generation",
            "schema_version": "dating.reply_generation.v1",
        }
        if present:
            result_data["result"] = value
        calls = [
            _gateway_call(
                "call_0001",
                "CreateReplyTask",
                params={"asset_ids": []},
                data={
                    "task_id": task_id,
                    "task_type": "reply_generation",
                    "status": "queued",
                    "phase": "queued",
                },
            ),
            _gateway_call(
                "call_0002",
                "GetTaskResult",
                params={"task_id": task_id},
                data=result_data,
            ),
        ]
        snapshot, _ = build_task_snapshot(calls, [], task_id)
        return snapshot

    def test_result_payload_preserves_list_scalar_and_null_values(self):
        """合法的非 dict Result 也必须按原类型和值原样保留。"""
        raw_values = ([{"item": 1}], "raw-text", 17, False, None)

        for raw_value in raw_values:
            with self.subTest(raw_value=raw_value):
                snapshot = self._snapshot_for_result(present=True, value=raw_value)
                self.assertEqual(snapshot["result_payload"], raw_value)
                self.assertIs(type(snapshot["result_payload"]), type(raw_value))
                self.assertIs(snapshot.get("result_payload_present"), True)

    def test_missing_result_is_distinct_from_explicit_null(self):
        """缺失 result 键与显式 JSON null 都返回 None，但 presence 必须不同。"""
        missing = self._snapshot_for_result(present=False)
        explicit_null = self._snapshot_for_result(present=True, value=None)

        self.assertIsNone(missing["result_payload"])
        self.assertIsNone(explicit_null["result_payload"])
        self.assertIs(missing.get("result_payload_present"), False)
        self.assertIs(explicit_null.get("result_payload_present"), True)


class DatingUploadAssociationTests(unittest.TestCase):
    """验证上传证据歧义时保留 orphan，绝不猜测 asset_id。"""

    def test_ambiguous_put_stays_orphan_and_warns(self):
        """两个未关闭 Prepare 且 PUT 路径均不匹配时不得选择最近资源。"""
        calls = [
            _gateway_call(
                "call_0001",
                "PrepareMediaUpload",
                params={"content_type": "image/png", "size_bytes": 100},
                data={
                    "asset_id": "asset_a",
                    "content_type": "image/png",
                    "size_bytes": 100,
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/a.png?signature=a",
                },
            ),
            _gateway_call(
                "call_0002",
                "PrepareMediaUpload",
                params={"content_type": "image/png", "size_bytes": 200},
                data={
                    "asset_id": "asset_b",
                    "content_type": "image/png",
                    "size_bytes": 200,
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/b.png?signature=b",
                },
            ),
            _put_call(
                "call_0003",
                "https://storage.example/uploads/unknown.png?signature=unknown",
            ),
            _gateway_call(
                "call_0004",
                "CompleteMediaUpload",
                params={"asset_id": "asset_a"},
                data={"asset_id": "asset_a", "status": "uploaded"},
            ),
            _gateway_call(
                "call_0005",
                "CompleteMediaUpload",
                params={"asset_id": "asset_b"},
                data={"asset_id": "asset_b", "status": "uploaded"},
            ),
            _gateway_call(
                "call_0006",
                "CreateReplyTask",
                params={"asset_ids": ["asset_a", "asset_b"]},
                data={"task_id": "task_ambiguous", "task_type": "reply_generation"},
            ),
        ]

        assets, warnings = build_upload_assets(calls, "task_ambiguous")
        by_id = {asset["asset_id"]: asset for asset in assets}
        orphan = next(asset for asset in assets if asset["asset_id"] is None)

        self.assertEqual(len(assets), 3)
        self.assertIn(
            "AMBIGUOUS_UPLOAD_ASSOCIATION",
            {warning["code"] for warning in warnings},
        )
        self.assertIsNone(by_id["asset_a"]["put_call_id"])
        self.assertIsNone(by_id["asset_b"]["put_call_id"])
        self.assertEqual(by_id["asset_a"]["upload_state"], "prepare_only")
        self.assertEqual(by_id["asset_b"]["upload_state"], "prepare_only")
        self.assertTrue(by_id["asset_a"]["used_by_task"])
        self.assertTrue(by_id["asset_b"]["used_by_task"])
        self.assertEqual(orphan["put_call_id"], "call_0003")
        self.assertEqual(orphan["upload_state"], "orphan_put")
        self.assertFalse(orphan["used_by_task"])

    def test_complete_before_put_stays_incomplete_and_warns(self):
        """Complete 早于 PUT 时不能提前闭合 Prepare→PUT→Complete 链路。"""
        calls = [
            _gateway_call(
                "call_0001",
                "PrepareMediaUpload",
                data={
                    "asset_id": "asset_a",
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/a.png?prepare=1",
                },
            ),
            _gateway_call(
                "call_0002",
                "CompleteMediaUpload",
                params={"asset_id": "asset_a"},
                data={"asset_id": "asset_a", "status": "uploaded"},
            ),
            _put_call(
                "call_0003", "https://storage.example/uploads/a.png?put=after-complete"
            ),
            _gateway_call(
                "call_0004",
                "CreateReplyTask",
                params={"asset_ids": ["asset_a"]},
                data={"task_id": "task_out_of_order", "task_type": "reply_generation"},
            ),
        ]

        assets, warnings = build_upload_assets(calls, "task_out_of_order")
        asset = next(asset for asset in assets if asset["asset_id"] == "asset_a")

        self.assertEqual(asset["put_call_id"], "call_0003")
        self.assertIsNone(asset["complete_call_id"])
        self.assertIsNone(asset["complete_status"])
        self.assertEqual(asset["upload_state"], "unknown")
        self.assertIn(
            "COMPLETE_WITHOUT_ASSOCIATED_PUT",
            {warning["code"] for warning in warnings},
        )

    def test_complete_with_duplicate_asset_id_candidates_stays_ambiguous(self):
        """同 asset_id 的多个 Prepare+PUT 候选不能按“最新记录”猜测 Complete。"""
        calls = [
            _gateway_call(
                "call_0001",
                "PrepareMediaUpload",
                data={
                    "asset_id": "shared_asset",
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/first.png?prepare=1",
                },
            ),
            _gateway_call(
                "call_0002",
                "PrepareMediaUpload",
                data={
                    "asset_id": "shared_asset",
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/second.png?prepare=2",
                },
            ),
            _put_call(
                "call_0003", "https://storage.example/uploads/first.png?put=1"
            ),
            _put_call(
                "call_0004", "https://storage.example/uploads/second.png?put=2"
            ),
            _gateway_call(
                "call_0005",
                "CompleteMediaUpload",
                params={"asset_id": "shared_asset"},
                data={"asset_id": "shared_asset", "status": "uploaded"},
            ),
            _gateway_call(
                "call_0006",
                "CreateReplyTask",
                params={"asset_ids": ["shared_asset"]},
                data={"task_id": "task_duplicate", "task_type": "reply_generation"},
            ),
        ]

        assets, warnings = build_upload_assets(calls, "task_duplicate")
        shared_assets = [
            asset for asset in assets if asset["asset_id"] == "shared_asset"
        ]

        self.assertEqual(len(shared_assets), 2)
        self.assertTrue(
            all(asset["complete_call_id"] is None for asset in shared_assets)
        )
        self.assertTrue(
            all(asset["upload_state"] == "unknown" for asset in shared_assets)
        )
        self.assertIn(
            "AMBIGUOUS_COMPLETE_ASSOCIATION",
            {warning["code"] for warning in warnings},
        )

    def test_object_path_uniquely_disambiguates_pending_prepares(self):
        """多个待关联 Prepare 中，去查询参数后的唯一同路径允许安全关联。"""
        calls = [
            _gateway_call(
                "call_0001",
                "PrepareMediaUpload",
                data={
                    "asset_id": "asset_a",
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/a.png?prepare=1",
                },
            ),
            _gateway_call(
                "call_0002",
                "PrepareMediaUpload",
                data={
                    "asset_id": "asset_b",
                    "status": "pending",
                    "upload_url": "https://storage.example/uploads/b.png?prepare=2",
                },
            ),
            _put_call(
                "call_0003", "https://storage.example/uploads/a.png?put=different"
            ),
            _gateway_call(
                "call_0004",
                "CompleteMediaUpload",
                params={"asset_id": "asset_a"},
                data={"asset_id": "asset_a", "status": "uploaded"},
            ),
            _gateway_call(
                "call_0005",
                "CreateReplyTask",
                params={"asset_ids": ["asset_a"]},
                data={"task_id": "task_unique", "task_type": "reply_generation"},
            ),
        ]

        assets, warnings = build_upload_assets(calls, "task_unique")
        by_id = {asset["asset_id"]: asset for asset in assets}

        self.assertNotIn(
            "AMBIGUOUS_UPLOAD_ASSOCIATION",
            {warning["code"] for warning in warnings},
        )
        self.assertEqual(by_id["asset_a"]["put_call_id"], "call_0003")
        self.assertEqual(by_id["asset_a"]["upload_state"], "complete")
        self.assertIsNone(by_id["asset_b"]["put_call_id"])
        self.assertEqual(by_id["asset_b"]["upload_state"], "prepare_only")


class DatingPackagingAcceptanceTest(unittest.TestCase):
    """锁定容器运行时文件和 Dating 环境变量，防止发布物漏装模块。"""

    def test_dockerfile_copies_all_dating_runtime_modules(self):
        """删除任一直接 COPY 都会让容器启动时无法导入完整分析链。"""
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        copied_sources = set()
        for line in dockerfile.splitlines():
            match = re.fullmatch(r"\s*COPY\s+(\S+)\s+\.\s*", line)
            if match:
                copied_sources.add(match.group(1))

        for module_name in DATING_RUNTIME_MODULES:
            with self.subTest(module=module_name):
                self.assertIn(module_name, copied_sources)

    def test_compose_sets_explicit_dating_runtime_environment(self):
        """Compose 必须固定开启开关并传入 canonical 10 MiB 上限。"""
        compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        expected = {
            "DATING_STRUCTURED_ANALYZER_ENABLED": "true",
            "DATING_STRUCTURED_MAX_LOG_BYTES": "10485760",
        }

        for key, expected_value in expected.items():
            with self.subTest(environment=key):
                match = re.search(
                    rf"(?m)^\s+{re.escape(key)}:\s*[\"']?([^\"'\s#]+)[\"']?\s*$",
                    compose,
                )
                self.assertIsNotNone(match, f"Compose 缺少 {key}")
                self.assertEqual(match.group(1), expected_value)


class DatingOfflineAcceptanceTest(unittest.TestCase):
    """验证 Dating 分析路径只执行本地确定性代码，不触发外部能力。"""

    def test_runtime_modules_have_no_network_or_llm_imports_and_calls(self):
        """引入网络 SDK、HTTP 客户端或已知 AI 调用时必须静态失败。"""
        violations = []
        forbidden_call_suffixes = (
            "socket",
            "create_connection",
            "getaddrinfo",
            "urlopen",
            "HTTPConnection.request",
            "HTTPSConnection.request",
            "OpenAI",
            "Anthropic",
            "GenerativeModel",
            "generate_content",
            "chat.completions.create",
        )

        for module_name in DATING_RUNTIME_MODULES:
            source = (PROJECT_ROOT / module_name).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=module_name)
            for node in ast.walk(tree):
                imported_names = []
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_names = [node.module]
                for imported_name in imported_names:
                    if any(
                        imported_name == prefix
                        or imported_name.startswith(prefix + ".")
                        for prefix in FORBIDDEN_EXTERNAL_IMPORTS
                    ):
                        violations.append(
                            f"{module_name}:{node.lineno} import {imported_name}"
                        )

                if isinstance(node, ast.Call):
                    call_name = _dotted_name(node.func)
                    if any(
                        call_name == suffix or call_name.endswith("." + suffix)
                        for suffix in forbidden_call_suffixes
                    ):
                        violations.append(
                            f"{module_name}:{node.lineno} call {call_name}"
                        )

        self.assertEqual(violations, [])

    def test_golden_analysis_succeeds_with_network_and_ai_guards(self):
        """真实分析若触发 socket、HTTP 或运行时加载 AI SDK，应立即失败。"""
        fixtures = (
            ("reply_generation_multi_image_success.log", REPLY_TASK_ID),
            ("relationship_analysis_multi_image_success.log", ANALYSIS_TASK_ID),
        )
        fixture_texts = [
            (name, _read_fixture(name), expected_task_id)
            for name, expected_task_id in fixtures
        ]
        real_import = builtins.__import__
        blocked_roots = {
            "openai",
            "anthropic",
            "cohere",
            "requests",
            "httpx",
            "aiohttp",
        }

        def reject_external(*_args, **_kwargs):
            raise AssertionError("Dating 分析尝试访问网络或 HTTP")

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.split(".", 1)[0]
            google_ai = name.startswith(("google.generativeai", "google.genai")) or (
                name == "google"
                and any(item in {"generativeai", "genai"} for item in fromlist)
            )
            if root in blocked_roots or google_ai:
                raise AssertionError(f"Dating 分析尝试加载外部 SDK: {name}")
            return real_import(name, globals, locals, fromlist, level)

        with (
            patch.object(builtins, "__import__", side_effect=guarded_import),
            patch.object(socket, "socket", side_effect=reject_external),
            patch.object(socket, "create_connection", side_effect=reject_external),
            patch.object(socket, "getaddrinfo", side_effect=reject_external),
            patch.object(urllib.request, "urlopen", side_effect=reject_external),
            patch.object(
                http.client.HTTPConnection, "request", side_effect=reject_external
            ),
            patch.object(
                http.client.HTTPSConnection, "request", side_effect=reject_external
            ),
        ):
            for name, log_text, expected_task_id in fixture_texts:
                with self.subTest(fixture=name):
                    result = analyze_dating_log(log_text)
                    self.assertTrue(result["supported"])
                    self.assertEqual(result["task_ids"], [expected_task_id])


class DatingDeterminismTest(unittest.TestCase):
    """持续执行轻量确定性验收，避免性能测试默认跳过时失去回归保护。"""

    def test_repeated_golden_analysis_is_identical_and_uses_sequential_call_ids(self):
        """同一日志不得生成随机业务 ID，解析调用 ID 必须按出现顺序稳定编号。"""
        fixtures = (
            ("reply_generation_multi_image_success.log", REPLY_TASK_ID),
            ("relationship_analysis_multi_image_success.log", ANALYSIS_TASK_ID),
        )

        for fixture_name, expected_task_id in fixtures:
            log_text = _read_fixture(fixture_name)
            first = analyze_dating_log(log_text)
            second = analyze_dating_log(log_text)
            with self.subTest(fixture=fixture_name):
                self.assertEqual(first, second)
                self.assertEqual(first["task_ids"], [expected_task_id])
                self.assertEqual(
                    [call["call_id"] for call in first["calls"]],
                    [
                        f"call_{sequence:04d}"
                        for sequence in range(1, len(first["calls"]) + 1)
                    ],
                )
                unexpected_ids = sorted(
                    business_id
                    for business_id in _collect_business_ids(first)
                    if business_id not in log_text
                )
                self.assertEqual(
                    unexpected_ids,
                    [],
                    f"输出包含日志中不存在的业务 ID: {unexpected_ids}",
                )


@unittest.skipUnless(
    os.environ.get("RUN_DATING_PERF") == "1",
    "设置 RUN_DATING_PERF=1 才运行 Dating 重压验收",
)
class DatingPerformanceAcceptanceTest(unittest.TestCase):
    """可直接运行的 Dating 确定性和性能完成标准。"""

    @classmethod
    def setUpClass(cls):
        """在计时前读取 fixture、构造大日志并预热全部分析路径。"""
        cls.golden_cases = (
            (
                "reply_generation_multi_image_success.log",
                _read_fixture("reply_generation_multi_image_success.log"),
                REPLY_TASK_ID,
            ),
            (
                "relationship_analysis_multi_image_success.log",
                _read_fixture("relationship_analysis_multi_image_success.log"),
                ANALYSIS_TASK_ID,
            ),
        )
        cls.large_log = _build_large_dating_log(cls.golden_cases[0][1])
        for _name, log_text, _expected_task_id in cls.golden_cases:
            analyze_dating_log(log_text)
        analyze_dating_log(cls.large_log)

    def test_golden_results_are_deterministic_and_median_is_within_500ms(self):
        """两份 golden 重复输出必须逐字节稳定，且各自中位数不超过 500ms。"""
        for name, log_text, expected_task_id in self.golden_cases:
            serialized_results = []
            elapsed_samples = []
            latest_result = None
            for _ in range(5):
                started = perf_counter()
                latest_result = analyze_dating_log(log_text)
                elapsed_samples.append(perf_counter() - started)
                serialized_results.append(
                    json.dumps(
                        latest_result,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )

            with self.subTest(fixture=name):
                self.assertTrue(all(
                    result == serialized_results[0]
                    for result in serialized_results[1:]
                ))
                self.assertEqual(latest_result["task_ids"], [expected_task_id])
                self.assertEqual(
                    latest_result["task_snapshot"]["task_id"], expected_task_id
                )
                unexpected_ids = sorted(
                    business_id
                    for business_id in _collect_business_ids(latest_result)
                    if business_id not in log_text
                )
                self.assertEqual(
                    unexpected_ids,
                    [],
                    f"输出包含日志中不存在的业务 ID: {unexpected_ids}",
                )
                self.assertLessEqual(
                    median(elapsed_samples),
                    0.5,
                    f"{name} 分析中位数超过 500ms",
                )

    def test_near_10mib_log_is_stable_and_finishes_within_two_seconds(self):
        """略低于 10 MiB 的有效 Dating 日志必须稳定且单次分析不超过 2 秒。"""
        self.assertLessEqual(
            len(self.large_log.encode("utf-8")), MAX_DATING_LOG_BYTES
        )
        serialized_results = []
        elapsed_samples = []
        for _ in range(2):
            started = perf_counter()
            result = analyze_dating_log(self.large_log)
            elapsed_samples.append(perf_counter() - started)
            serialized_results.append(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )

        self.assertTrue(result["supported"])
        self.assertEqual(result["task_ids"], [REPLY_TASK_ID])
        self.assertEqual(serialized_results[0], serialized_results[1])
        self.assertLessEqual(
            max(elapsed_samples), 2.0, "近 10 MiB 日志分析超过 2 秒"
        )


if __name__ == "__main__":
    unittest.main()
