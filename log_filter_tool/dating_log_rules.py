"""Dating 结构化日志的确定性检查规则。

模块只消费 :func:`dating_log_analyzer.analyze_dating_log` 返回的字典，不重新
解析原始日志，也不访问 LLM、网络、数据库或对象存储。规则按固定注册顺序
执行，调用方可再用 :func:`compute_dating_verdict` 计算总体结论。
"""

from __future__ import annotations

import json
import math
import re
from urllib.parse import parse_qsl, urlsplit


CHECK_OUTCOMES = {"PASS", "FAIL", "WARN", "UNKNOWN", "NA"}

_REDACTED = "[REDACTED]"
_MAX_TEXT_VALUE_CHARS = 20_000
_SENSITIVE_KEYS = {
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "token",
    "authtoken",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "sessiontoken",
    "apikey",
    "xapikey",
    "secret",
    "clientsecret",
}
_BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/]*={0,2}\Z")
_URLSAFE_BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_-]*={0,2}\Z")
_TRUNCATION_WARNING_MESSAGE = "字段文本超过 20000 字符，结果仅保留前 20000 字符"

RULE_SPECS = (
    ("PARSE-001", "P0", "已识别请求或响应 JSON 可解析"),
    ("PAIR-001", "P0", "Gateway 子请求与子响应唯一配对"),
    ("HTTP-001", "P0", "外层 HTTP 状态为 2xx"),
    ("GATEWAY-001", "P0", "Gateway 外层 code 为 0"),
    ("SUBRESP-001", "P0", "子响应 success=true 且 code=0"),
    ("TRACE-001", "P2", "Gateway 响应包含 request_id 和 trace_id"),
    ("UPLOAD-001", "P0", "任务使用的资源完成上传链路"),
    ("UPLOAD-002", "P1", "Prepare 与 Complete 上传元数据一致"),
    ("TASK-001", "P0", "Create、Poll、Result task_id 一致"),
    ("TASK-002", "P0", "接口组合和 task_type 一致"),
    ("TASK-003", "P0", "轮询状态转换合法"),
    ("TASK-004", "P1", "任务进度不下降"),
    ("TASK-005", "P0", "成功任务进度为 100"),
    ("TASK-006", "P0", "失败任务包含可定位错误"),
    ("TASK-007", "P1", "任务与结果时间顺序合法"),
    ("TASK-008", "P1", "成功任务存在结果接口"),
    ("TASK-009", "P2", "成功任务不应停留 finalizing"),
    ("TASK-010", "P2", "处理进度没有长时间停滞"),
    ("RESULT-001", "P0", "结果 task_id 与任务一致"),
    ("RESULT-002", "P0", "外层和内层 schema_version 一致"),
    ("RESULT-003", "P1", "结果 result_id 非空"),
    ("RESULT-004", "P1", "已知 Schema 必填字段存在"),
    ("RESULT-005", "P2", "汇总 Result 空值健康度"),
    ("RESULT-006", "P2", "未知字段被保留并标记"),
    ("REPLY-001", "P0", "Reply ID 唯一"),
    ("REPLY-002", "P0", "每个 Role 最多一个 Top Pick"),
    ("REPLY-003", "P0", "Top Pick 引用已有 Reply"),
    ("REPLY-004", "P1", "Top Pick 文案与 Reply 一致"),
    ("REPLY-005", "P1", "Alternatives 与非 Top Pick Replies 一致"),
    ("REPLY-006", "P1", "Role rank 唯一且可排序"),
    ("REPLY-007", "P1", "降级 warning 与 is_degraded 一致"),
    ("REPLY-008", "P2", "Person history 使用状态与 person_id 一致"),
    ("ANALYSIS-001", "P0", "上传资源计数守恒"),
    ("ANALYSIS-002", "P0", "分析消息数不超过有效消息数"),
    ("ANALYSIS-003", "P0", "双方消息数等于分析消息总数"),
    ("ANALYSIS-004", "P1", "同类型 Signal ID 唯一"),
    ("ANALYSIS-005", "P1", "Key Event ID 唯一"),
    ("ANALYSIS-006", "P1", "Signal 与 Event 证据消息非空"),
    ("ANALYSIS-007", "P2", "汇总 Analysis 空值"),
    ("ANALYSIS-008", "P2", "汇总 Analysis warnings"),
)
RULE_IDS = tuple(spec[0] for spec in RULE_SPECS)
_RULE_SPEC_BY_ID = {spec[0]: spec for spec in RULE_SPECS}

_PARSE_FAILURE_CODES = {
    "MALFORMED_JSON_BLOCK",
    "UNPAIRED_GATEWAY_BLOCK",
    "GATEWAY_REQUEST_JSON_ERROR",
    "GATEWAY_REQUEST_TYPE_ERROR",
    "GATEWAY_RESPONSE_BODY_JSON_ERROR",
    "GATEWAY_RESPONSE_HEADERS_JSON_ERROR",
    "GATEWAY_RESPONSE_HEADERS_TYPE_ERROR",
    "PUT_REQUEST_JSON_ERROR",
    "PUT_REQUEST_TYPE_ERROR",
    "PUT_RESPONSE_HEADERS_JSON_ERROR",
    "PUT_RESPONSE_HEADERS_TYPE_ERROR",
    "GATEWAY_PAYLOAD_TYPE_ERROR",
    "GATEWAY_REQUESTS_TYPE_ERROR",
    "GATEWAY_RESPONSES_TYPE_ERROR",
    "GATEWAY_SUBREQUEST_TYPE_ERROR",
    "GATEWAY_SUBRESPONSE_TYPE_ERROR",
}
_PARSER_WARNING_CODES = _PARSE_FAILURE_CODES | {
    "AMBIGUOUS_PAIRING",
    "POSITIONAL_PAIRING_FALLBACK",
    "RESPONSE_ELAPSED_MS_INVALID",
    "UNMATCHED_REQUEST",
    "UNMATCHED_RESPONSE",
}
_PAIRING_WARNING_CODES = {
    "AMBIGUOUS_PAIRING",
    "POSITIONAL_PAIRING_FALLBACK",
    "UNMATCHED_REQUEST",
    "UNMATCHED_RESPONSE",
    "UNPAIRED_GATEWAY_BLOCK",
}

ALLOWED_TRANSITIONS = {
    "QUEUED": {"QUEUED", "PROCESSING", "SUCCEEDED", "FAILED"},
    "PROCESSING": {"PROCESSING", "SUCCEEDED", "FAILED"},
    "SUCCEEDED": set(),
    "FAILED": set(),
}
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED"}

_CREATE_METHOD_TYPES = {
    "CreateReplyTask": "reply_generation",
    "CreateAnalysisTask": "relationship_analysis",
}
_POLL_METHOD_TYPES = {
    "GetTask": "reply_generation",
    "GetAnalysisTask": "relationship_analysis",
}
_RESULT_METHOD_TYPES = {
    "GetTaskResult": "reply_generation",
    "GetAnalysisResult": "relationship_analysis",
}
_TASK_METHOD_TYPES = {
    **_CREATE_METHOD_TYPES,
    **_POLL_METHOD_TYPES,
    **_RESULT_METHOD_TYPES,
}
_EXPECTED_TASK_METHODS = {
    "reply_generation": {"CreateReplyTask", "GetTask", "GetTaskResult"},
    "relationship_analysis": {
        "CreateAnalysisTask",
        "GetAnalysisTask",
        "GetAnalysisResult",
    },
}


def _is_meaningful_text(value: object) -> bool:
    """判断证据标识符是否为非空文本，避免空白字符串冒充定位信息。"""
    return isinstance(value, str) and bool(value.strip())


def _is_exact_numeric_zero(value: object) -> bool:
    """只接受 JSON 数值语义的有限零，显式排除 bool 和其他类型。

    ``bool`` 是 ``int`` 子类，不能用 ``isinstance(value, (int, float))``
    直接判断；浮点数还需拒绝 NaN/Infinity，避免损坏的 analyzer 输入绕过规则。
    """
    if type(value) is int:
        return value == 0
    if type(value) is float:
        return math.isfinite(value) and value == 0.0
    return False


def _is_structured_evidence(item: object) -> bool:
    """校验证据是否能稳定定位到真实调用块或调用字段。

    字段级证据需要来源标识、JSON 路径和值键；调用级证据可没有路径和值，
    但必须同时提供 method 与 call_id。两类证据都必须使用有效的一基 block
    行范围，且显式排除 Python 中会伪装成整数的 bool。
    """
    if not isinstance(item, dict) or item.get("location_precision") != "block":
        return False
    line_start = item.get("line_start")
    line_end = item.get("line_end")
    if (
        type(line_start) is not int
        or type(line_end) is not int
        or line_start < 1
        or line_end < line_start
    ):
        return False

    has_method = _is_meaningful_text(item.get("method"))
    has_call_id = _is_meaningful_text(item.get("call_id"))
    has_path_value = _is_meaningful_text(item.get("json_path")) and "value" in item
    return (has_method or has_call_id) and (has_path_value or (has_method and has_call_id))


def _check(
    rule_id: str,
    priority: str,
    title: str,
    outcome: str,
    actual: object,
    expected: object,
    evidence: list[dict] | None = None,
) -> dict:
    """构造唯一的规则结果形状，并禁止没有真实证据的 FAIL/WARN。

    参数:
        rule_id/priority/title: 稳定规则元数据。
        outcome: 只能是 ``CHECK_OUTCOMES`` 中的值。
        actual/expected: 实际事实与可读预期。
        evidence: 来自 analyzer 调用块的证据列表。

    返回:
        包含七个固定字段的普通字典。

    异常:
        ValueError: outcome 非法，或 FAIL/WARN 未提供符合定位契约的证据时抛出。
    """
    resolved_evidence = evidence if isinstance(evidence, list) else []
    if outcome not in CHECK_OUTCOMES:
        raise ValueError(f"unsupported check outcome: {outcome}")
    if outcome in {"FAIL", "WARN"} and (
        not resolved_evidence
        or any(not _is_structured_evidence(item) for item in resolved_evidence)
    ):
        raise ValueError(
            f"{rule_id} cannot return {outcome} without evidence "
            "that satisfies the structural contract"
        )
    return {
        "rule_id": rule_id,
        "priority": priority,
        "title": title,
        "outcome": outcome,
        "actual": actual,
        "expected": expected,
        "evidence": resolved_evidence,
    }


def _evidence(call: dict, json_path: str, value: object) -> dict:
    """从 InterfaceCall 统一提取 block 级定位证据。

    响应字段优先定位响应块；调用方传入 request 路径时定位请求块。缺少
    行号不会被补造，仍明确标记为 ``block`` 精度。
    """
    source_name = "request" if json_path.startswith("request.") else "response"
    source = call.get(source_name)
    # Parser warning 本身也带真实 block 行号。允许统一构造器消费这种记录，
    # 避免 PARSE/PAIR 规则各自拼装不同 evidence 形状。
    block = source if isinstance(source, dict) else call
    evidence = {
        "method": (
            call.get("method_name")
            or call.get("method")
            # Parser warning 没有业务 method，但 code 与真实日志块行号共同标识
            # 解析器来源；使用固定来源名而不是伪造某个业务接口。
            or ("parse_interface_log" if _is_meaningful_text(call.get("code")) else None)
        ),
        "json_path": json_path,
        "value": value,
        "line_start": block.get("line_start"),
        "line_end": block.get("line_end"),
        "location_precision": "block",
    }
    # response-only parser call 没有 method_name，但 parser 已分配稳定 call_id；
    # 保留该真实身份即可满足证据契约，无需放宽校验或伪造业务方法名。
    if _is_meaningful_text(call.get("call_id")):
        evidence["call_id"] = call["call_id"]
    return evidence


def _result(
    rule_id: str,
    outcome: str,
    actual: object,
    expected: object,
    evidence: list[dict] | None = None,
) -> dict:
    """按注册元数据构造结果，规则函数不重复填写优先级和标题。"""
    _, priority, title = _RULE_SPEC_BY_ID[rule_id]
    return _check(rule_id, priority, title, outcome, actual, expected, evidence)


def _analysis_calls(analysis: dict) -> list[dict] | None:
    """读取 analyzer 调用列表；类型损坏视为证据不可用。"""
    calls = analysis.get("calls")
    return calls if isinstance(calls, list) else None


def _gateway_calls(analysis: dict) -> list[dict] | None:
    """保持日志顺序筛选 Gateway 调用。"""
    calls = _analysis_calls(analysis)
    if calls is None:
        return None
    return [call for call in calls if call.get("transport") == "gateway"]


def _warning_codes(call: dict) -> set[str]:
    """提取单个 InterfaceCall 引用的 parser warning code。"""
    warnings = call.get("warnings")
    if not isinstance(warnings, list):
        return set()
    return {
        warning.get("code")
        for warning in warnings
        if isinstance(warning, dict) and isinstance(warning.get("code"), str)
    }


def _call_by_id(analysis: dict, call_id: object) -> dict | None:
    """按 call_id 查找证据调用；缺失时返回 None，不制造占位调用。"""
    calls = _analysis_calls(analysis)
    if calls is None:
        return None
    return next((call for call in calls if call.get("call_id") == call_id), None)


def check_parse_complete(analysis: dict) -> dict:
    """PARSE-001：区分不可恢复解析失败、可恢复噪声和完整解析。"""
    calls = _analysis_calls(analysis)
    warnings = analysis.get("parse_warnings")
    if calls is None or not isinstance(warnings, list):
        return _result("PARSE-001", "UNKNOWN", None, "解析事实可用")

    severe = [
        warning
        for warning in warnings
        if isinstance(warning, dict)
        and warning.get("code") in _PARSE_FAILURE_CODES
    ]
    parse_error_calls = [
        call
        for call in calls
        if call.get("parse_status") == "PARSE_ERROR"
    ]
    if severe or parse_error_calls:
        evidence = [
            _evidence(warning, "parse_warnings[].code", warning.get("code"))
            for warning in severe
        ]
        evidence.extend(
            _evidence(
                call,
                "request.parse_status"
                if isinstance(call.get("request"), dict)
                else "response.parse_status",
                call.get("parse_status"),
            )
            for call in parse_error_calls
        )
        return _result(
            "PARSE-001",
            "FAIL",
            [warning.get("code") for warning in severe] or "PARSE_ERROR",
            "已识别请求或响应 JSON 均可解析",
            evidence,
        )

    recoverable = [
        warning
        for warning in warnings
        if isinstance(warning, dict)
        and warning.get("code") in _PARSER_WARNING_CODES
    ]
    if recoverable:
        return _result(
            "PARSE-001",
            "WARN",
            [warning.get("code") for warning in recoverable],
            "没有可恢复解析噪声",
            [
                _evidence(warning, "parse_warnings[].code", warning.get("code"))
                for warning in recoverable
            ],
        )
    return _result("PARSE-001", "PASS", [], "已识别 JSON 均可解析")


def check_gateway_pairing(analysis: dict) -> dict:
    """PAIR-001：每条 Gateway 逻辑请求必须有唯一子响应。"""
    calls = _gateway_calls(analysis)
    if calls is None:
        return _result("PAIR-001", "UNKNOWN", None, "Gateway 配对事实可用")
    if not calls:
        return _result("PAIR-001", "NA", 0, "存在 Gateway 调用时检查配对")

    defects: list[tuple[dict, str, object]] = []
    for call in calls:
        request = call.get("request")
        response = call.get("response")
        warning_codes = _warning_codes(call) & _PAIRING_WARNING_CODES
        if not isinstance(request, dict):
            defects.append((call, "response.sub_response.id", "missing request"))
        elif not isinstance(response, dict):
            defects.append((call, "request.params", "missing response"))
        elif not isinstance(response.get("sub_response"), dict):
            defects.append((call, "request.params", "missing sub_response"))
        elif warning_codes:
            defects.append((call, "response.sub_response.id", sorted(warning_codes)))
    if defects:
        evidence = [_evidence(call, path, value) for call, path, value in defects]
        return _result(
            "PAIR-001",
            "FAIL",
            [value for _, _, value in defects],
            "每个 Gateway 子请求存在唯一同 ID 子响应",
            evidence,
        )
    return _result("PAIR-001", "PASS", len(calls), "全部 Gateway 调用唯一配对")


def check_outer_http_status(analysis: dict) -> dict:
    """HTTP-001：Gateway 与 PUT 的真实外层 HTTP 必须为 2xx。"""
    calls = _analysis_calls(analysis)
    if calls is None:
        return _result("HTTP-001", "UNKNOWN", None, "HTTP 状态事实可用")
    if not calls:
        return _result("HTTP-001", "NA", 0, "存在接口调用时检查 HTTP")

    failures: list[tuple[dict, object]] = []
    unknown = False
    for call in calls:
        response = call.get("response")
        status = response.get("http_status") if isinstance(response, dict) else None
        if not isinstance(status, int):
            unknown = True
        elif not 200 <= status <= 299:
            failures.append((call, status))
    if failures:
        return _result(
            "HTTP-001",
            "FAIL",
            [status for _, status in failures],
            "全部外层 HTTP 状态为 2xx",
            [_evidence(call, "response.http_status", status) for call, status in failures],
        )
    if unknown:
        return _result("HTTP-001", "UNKNOWN", None, "全部 HTTP 状态可定位")
    return _result("HTTP-001", "PASS", "all 2xx", "全部外层 HTTP 状态为 2xx")


def check_gateway_status(analysis: dict) -> dict:
    """GATEWAY-001：只检查 Gateway envelope，不读取 HTTP 或业务层。"""
    calls = _gateway_calls(analysis)
    if calls is None:
        return _result("GATEWAY-001", "UNKNOWN", None, "Gateway code 可用")
    if not calls:
        return _result("GATEWAY-001", "NA", 0, "存在 Gateway 调用时检查 code")

    failures: list[tuple[dict, object]] = []
    unknown = False
    for call in calls:
        response = call.get("response")
        gateway = response.get("gateway") if isinstance(response, dict) else None
        if not isinstance(gateway, dict) or "code" not in gateway:
            unknown = True
            continue
        code = gateway["code"]
        if not _is_exact_numeric_zero(code):
            failures.append((call, code))
    if failures:
        return _result(
            "GATEWAY-001",
            "FAIL",
            [code for _, code in failures],
            "Gateway envelope code=0",
            [_evidence(call, "response.gateway.code", code) for call, code in failures],
        )
    if unknown:
        return _result("GATEWAY-001", "UNKNOWN", None, "全部 Gateway code 可定位")
    return _result("GATEWAY-001", "PASS", 0, "Gateway envelope code=0")


def check_subresponse_status(analysis: dict) -> dict:
    """SUBRESP-001：只检查逻辑子响应 success/code。"""
    calls = _gateway_calls(analysis)
    if calls is None:
        return _result("SUBRESP-001", "UNKNOWN", None, "子响应事实可用")
    if not calls:
        return _result("SUBRESP-001", "NA", 0, "存在 Gateway 调用时检查子响应")

    failures: list[tuple[dict, dict]] = []
    unknown = False
    for call in calls:
        response = call.get("response")
        sub = response.get("sub_response") if isinstance(response, dict) else None
        if not isinstance(sub, dict) or "success" not in sub or "code" not in sub:
            unknown = True
        elif (
            sub.get("success") is not True
            or not _is_exact_numeric_zero(sub.get("code"))
        ):
            failures.append((call, sub))
    if failures:
        return _result(
            "SUBRESP-001",
            "FAIL",
            [
                {"success": sub.get("success"), "code": sub.get("code")}
                for _, sub in failures
            ],
            "responses[].success=true 且 code=0",
            [
                _evidence(
                    call,
                    "response.sub_response",
                    {"success": sub.get("success"), "code": sub.get("code")},
                )
                for call, sub in failures
            ],
        )
    if unknown:
        return _result("SUBRESP-001", "UNKNOWN", None, "全部子响应可定位")
    return _result("SUBRESP-001", "PASS", "all success", "success=true 且 code=0")


def check_trace_ids_present(analysis: dict) -> dict:
    """TRACE-001：缺字段时 WARN，整段证据不可用时 UNKNOWN。"""
    summary = analysis.get("summary")
    if isinstance(summary, dict) and "trace_chain" in summary and summary["trace_chain"] is None:
        return _result("TRACE-001", "UNKNOWN", None, "Gateway trace 证据可用")
    calls = _gateway_calls(analysis)
    if calls is None:
        return _result("TRACE-001", "UNKNOWN", None, "Gateway trace 证据可用")
    if not calls:
        return _result("TRACE-001", "NA", 0, "存在 Gateway 调用时检查 trace")

    missing: list[tuple[dict, dict]] = []
    for call in calls:
        response = call.get("response")
        gateway = response.get("gateway") if isinstance(response, dict) else None
        if not isinstance(gateway, dict):
            return _result("TRACE-001", "UNKNOWN", None, "Gateway 响应块可用")
        absent = {
            key: gateway.get(key)
            for key in ("request_id", "trace_id")
            if not isinstance(gateway.get(key), str) or not gateway.get(key)
        }
        if absent:
            missing.append((call, absent))
    if missing:
        return _result(
            "TRACE-001",
            "WARN",
            [absent for _, absent in missing],
            "Gateway request_id 和 trace_id 均非空",
            [_evidence(call, "response.gateway", absent) for call, absent in missing],
        )
    return _result("TRACE-001", "PASS", "complete", "request_id/trace_id 均非空")


def _used_assets(analysis: dict) -> list[dict] | None:
    """读取所选任务资源；选择错误时必须返回 UNKNOWN 而非误判未使用。"""
    if analysis.get("selection_error") is not None:
        return None
    snapshot = analysis.get("task_snapshot")
    if snapshot is None:
        return []
    if not isinstance(snapshot, dict):
        return None
    assets = snapshot.get("input_assets")
    return assets if isinstance(assets, list) else None


def _asset_evidence_call(analysis: dict, asset: dict) -> dict | None:
    """按 Complete→PUT→Prepare 顺序寻找资源链中最后一个真实证据块。"""
    for key in ("complete_call_id", "put_call_id", "prepare_call_id"):
        call = _call_by_id(analysis, asset.get(key))
        if call is not None:
            return call
    return None


def check_used_asset_upload_chain(analysis: dict) -> dict:
    """UPLOAD-001：任务未引用资源时 NA，引用链不完整时 FAIL。"""
    assets = _used_assets(analysis)
    if assets is None:
        return _result("UPLOAD-001", "UNKNOWN", None, "所选任务资源事实可用")
    if not assets:
        return _result("UPLOAD-001", "NA", 0, "任务引用 asset 时检查上传链")

    incomplete = [
        asset
        for asset in assets
        if asset.get("upload_state") != "complete"
        or not all(
            asset.get(key)
            for key in ("prepare_call_id", "put_call_id", "complete_call_id")
        )
    ]
    if incomplete:
        located = [
            (asset, _asset_evidence_call(analysis, asset)) for asset in incomplete
        ]
        evidence = [
            _evidence(call, "response.data.asset_id", asset.get("asset_id"))
            for asset, call in located
            if call is not None
        ]
        if not evidence:
            return _result("UPLOAD-001", "UNKNOWN", incomplete, "上传链证据可定位")
        return _result(
            "UPLOAD-001",
            "FAIL",
            [
                {
                    "asset_id": asset.get("asset_id"),
                    "upload_state": asset.get("upload_state"),
                }
                for asset in incomplete
            ],
            "每个任务资源均完成 Prepare、PUT、Complete",
            evidence,
        )
    return _result("UPLOAD-001", "PASS", len(assets), "全部任务资源完成上传链")


def check_upload_metadata_consistency(analysis: dict) -> dict:
    """UPLOAD-002：比较 Prepare/Complete 的 size_bytes 与 content_type。"""
    assets = _used_assets(analysis)
    if assets is None:
        return _result("UPLOAD-002", "UNKNOWN", None, "所选任务资源事实可用")
    if not assets:
        return _result("UPLOAD-002", "NA", 0, "任务引用 asset 时比较元数据")

    mismatches: list[tuple[dict, dict, dict, dict]] = []
    unavailable = False
    for asset in assets:
        prepare = _call_by_id(analysis, asset.get("prepare_call_id"))
        complete = _call_by_id(analysis, asset.get("complete_call_id"))
        prepare_data = (
            prepare.get("response", {}).get("data")
            if isinstance(prepare, dict) and isinstance(prepare.get("response"), dict)
            else None
        )
        complete_data = (
            complete.get("response", {}).get("data")
            if isinstance(complete, dict) and isinstance(complete.get("response"), dict)
            else None
        )
        if not isinstance(prepare_data, dict) or not isinstance(complete_data, dict):
            unavailable = True
            continue
        before = {
            "size_bytes": prepare_data.get("size_bytes"),
            "content_type": prepare_data.get("content_type"),
        }
        after = {
            "size_bytes": complete_data.get("size_bytes"),
            "content_type": complete_data.get("content_type"),
        }
        if any(value is None for value in (*before.values(), *after.values())):
            unavailable = True
        elif before != after:
            mismatches.append((asset, prepare, complete, {"prepare": before, "complete": after}))
    if mismatches:
        return _result(
            "UPLOAD-002",
            "WARN",
            [values for _, _, _, values in mismatches],
            "Prepare 与 Complete 的 size_bytes/content_type 一致",
            [
                _evidence(complete, "response.data", values["complete"])
                for _, _, complete, values in mismatches
            ],
        )
    if unavailable:
        return _result("UPLOAD-002", "UNKNOWN", None, "Prepare/Complete 元数据完整")
    return _result("UPLOAD-002", "PASS", len(assets), "上传元数据一致")


def _task_snapshot(analysis: dict) -> dict | None:
    """返回所选任务快照；选择错误或结构缺失都保留为证据不足。"""
    if analysis.get("selection_error") is not None:
        return None
    snapshot = analysis.get("task_snapshot")
    return snapshot if isinstance(snapshot, dict) else None


def _response_data(call: dict | None) -> dict:
    """读取调用 response.data，类型异常时返回空字典。"""
    if not isinstance(call, dict):
        return {}
    response = call.get("response")
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else {}


def _request_params(call: dict | None) -> dict:
    """读取调用 request.params，类型异常时返回空字典。"""
    if not isinstance(call, dict):
        return {}
    request = call.get("request")
    params = request.get("params") if isinstance(request, dict) else None
    return params if isinstance(params, dict) else {}


def _snapshot_calls(analysis: dict, snapshot: dict) -> tuple[list[dict], bool]:
    """按快照引用顺序取 Create/Poll/Result，并返回是否存在悬空 call_id。"""
    ids: list[object] = [snapshot.get("create_call_id")]
    poll_ids = snapshot.get("poll_call_ids")
    if isinstance(poll_ids, list):
        ids.extend(poll_ids)
    elif poll_ids is not None:
        return [], True
    if snapshot.get("result_call_id") is not None:
        ids.append(snapshot.get("result_call_id"))

    resolved: list[dict] = []
    missing = False
    for call_id in ids:
        if call_id is None:
            missing = True
            continue
        call = _call_by_id(analysis, call_id)
        if call is None:
            missing = True
        else:
            resolved.append(call)
    return resolved, missing


def _status_text(value: object) -> str | None:
    """状态机统一比较大写枚举，同时保留输入事实供 evidence 输出。"""
    return value.upper() if isinstance(value, str) and value else None


def _sample_call(analysis: dict, sample: dict | None) -> dict | None:
    """把状态样本安全映射回 parser 的真实 Poll 调用。"""
    return _call_by_id(analysis, sample.get("call_id")) if isinstance(sample, dict) else None


def _final_sample(snapshot: dict) -> dict | None:
    """返回最后一个状态样本，不用 lifecycle 字段伪造 Poll 证据。"""
    samples = snapshot.get("status_samples")
    if isinstance(samples, list) and samples and isinstance(samples[-1], dict):
        return samples[-1]
    return None


def check_task_ids_consistent(analysis: dict) -> dict:
    """TASK-001：比较 Create 响应、全部 Poll 和 Result 的文档化 ID 路径。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return _result("TASK-001", "UNKNOWN", None, "所选任务及调用证据可用")
    task_id = snapshot.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return _result("TASK-001", "UNKNOWN", task_id, "task_id 非空")

    calls, dangling = _snapshot_calls(analysis, snapshot)
    result_call_id = snapshot.get("result_call_id")
    if not calls:
        return _result("TASK-001", "UNKNOWN", None, "Create/Poll/Result 调用可定位")

    observed: list[tuple[dict, str, object]] = []
    missing_path = dangling or result_call_id is None
    for call in calls:
        method = call.get("method_name")
        if method in _CREATE_METHOD_TYPES:
            value = _response_data(call).get("task_id")
            observed.append((call, "response.data.task_id", value))
            missing_path = missing_path or value is None
        elif method in _POLL_METHOD_TYPES or method in _RESULT_METHOD_TYPES:
            request_value = _request_params(call).get("task_id")
            response_value = _response_data(call).get("task_id")
            observed.extend(
                (
                    (call, "request.params.task_id", request_value),
                    (call, "response.data.task_id", response_value),
                )
            )
            missing_path = missing_path or request_value is None or response_value is None

    mismatches = [item for item in observed if item[2] not in (None, task_id)]
    if mismatches:
        return _result(
            "TASK-001",
            "FAIL",
            [value for _, _, value in mismatches],
            task_id,
            [_evidence(call, path, value) for call, path, value in mismatches],
        )
    if missing_path:
        return _result("TASK-001", "UNKNOWN", task_id, "全部文档化 task_id 路径可用")
    return _result("TASK-001", "PASS", task_id, "Create/Poll/Result task_id 一致")


def check_task_method_type_consistency(analysis: dict) -> dict:
    """TASK-002：所有已观察任务方法与快照 task_type 必须属于同一组合。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return _result("TASK-002", "UNKNOWN", None, "所选任务证据可用")
    task_type = snapshot.get("task_type")
    allowed = _EXPECTED_TASK_METHODS.get(task_type)
    if allowed is None:
        return _result("TASK-002", "UNKNOWN", task_type, "已知 task_type")
    calls, dangling = _snapshot_calls(analysis, snapshot)
    if dangling or not calls:
        return _result("TASK-002", "UNKNOWN", None, "任务调用可定位")

    mismatches: list[tuple[dict, object]] = []
    for call in calls:
        method = call.get("method_name")
        response_type = _response_data(call).get("task_type")
        if method not in allowed or (
            response_type is not None and response_type != task_type
        ):
            mismatches.append(
                (call, {"method_name": method, "task_type": response_type or task_type})
            )
    if mismatches:
        return _result(
            "TASK-002",
            "FAIL",
            [value for _, value in mismatches],
            {"task_type": task_type, "methods": sorted(allowed)},
            [_evidence(call, "response.data.task_type", value) for call, value in mismatches],
        )
    return _result(
        "TASK-002",
        "PASS",
        {"task_type": task_type, "methods": [call.get("method_name") for call in calls]},
        "接口组合与 task_type 一致",
    )


def check_task_status_transitions(analysis: dict) -> dict:
    """TASK-003：按显式状态机检查 Poll 顺序，不对样本去重。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return _result("TASK-003", "UNKNOWN", None, "任务状态样本可用")
    samples = snapshot.get("status_samples")
    lifecycle = snapshot.get("lifecycle")
    if not isinstance(samples, list) or not samples or not isinstance(lifecycle, dict):
        return _result("TASK-003", "UNKNOWN", None, "至少一个 Poll 状态样本")

    states = [_status_text(lifecycle.get("initial_status"))]
    states.extend(
        _status_text(sample.get("status")) if isinstance(sample, dict) else None
        for sample in samples
    )
    has_unknown_transition = False
    for index, (previous, current) in enumerate(zip(states, states[1:])):
        # 未知枚举只影响与其相邻的转换，不能掩盖序列其他位置已经能够
        # 证明的非法转换；因此先遍历全部已知相邻对，最后才返回 UNKNOWN。
        if previous not in ALLOWED_TRANSITIONS or current not in ALLOWED_TRANSITIONS:
            has_unknown_transition = True
            continue
        if current not in ALLOWED_TRANSITIONS[previous]:
            # ``states`` 在首位插入了 initial_status，因此第 index 个转换的
            # current 恰好对应 samples[index]；证据必须指向发生回退的 Poll。
            sample_index = index
            sample = samples[sample_index] if sample_index < len(samples) else samples[-1]
            call = _sample_call(analysis, sample)
            if call is None:
                return _result("TASK-003", "UNKNOWN", None, "非法转换证据可定位")
            actual = f"{previous.lower()} -> {current.lower()}"
            return _result(
                "TASK-003",
                "FAIL",
                actual,
                "只允许配置表中的合法状态转换",
                [_evidence(call, "response.data.status", sample.get("status"))],
            )
    if has_unknown_transition:
        return _result("TASK-003", "UNKNOWN", states, "状态枚举均可识别")
    return _result(
        "TASK-003",
        "PASS",
        " -> ".join(state.lower() for state in states),
        "只允许配置表中的合法状态转换",
    )


def check_task_progress_monotonic(analysis: dict) -> dict:
    """TASK-004：缺进度时 UNKNOWN，存在下降时指向下降 Poll。"""
    snapshot = _task_snapshot(analysis)
    samples = snapshot.get("status_samples") if isinstance(snapshot, dict) else None
    if not isinstance(samples, list) or not samples:
        return _result("TASK-004", "UNKNOWN", None, "Poll 进度样本可用")
    values = [
        sample.get("progress_percent") if isinstance(sample, dict) else None
        for sample in samples
    ]
    for index, (previous, current) in enumerate(zip(values, values[1:]), start=1):
        if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
            if current < previous:
                sample = samples[index]
                call = _sample_call(analysis, sample)
                if call is None:
                    return _result("TASK-004", "UNKNOWN", None, "下降 Poll 可定位")
                return _result(
                    "TASK-004",
                    "FAIL",
                    {"previous": previous, "current": current},
                    "progress_percent 不下降",
                    [_evidence(call, "response.data.progress_percent", current)],
                )
    if any(not isinstance(value, (int, float)) for value in values):
        return _result("TASK-004", "UNKNOWN", values, "每个 Poll 均含数字进度")
    return _result("TASK-004", "PASS", values, "progress_percent 不下降")


def check_succeeded_progress_complete(analysis: dict) -> dict:
    """TASK-005：仅成功终态适用，非成功任务返回 NA。"""
    snapshot = _task_snapshot(analysis)
    lifecycle = snapshot.get("lifecycle") if isinstance(snapshot, dict) else None
    if not isinstance(lifecycle, dict):
        return _result("TASK-005", "UNKNOWN", None, "任务终态可用")
    status = _status_text(lifecycle.get("final_status"))
    if status is None:
        return _result("TASK-005", "UNKNOWN", None, "final_status 可用")
    if status != "SUCCEEDED":
        return _result("TASK-005", "NA", status.lower(), "succeeded 时检查进度")
    progress = lifecycle.get("final_progress_percent")
    if progress is None:
        return _result("TASK-005", "UNKNOWN", None, "成功终态进度可用")
    if progress != 100:
        sample = _final_sample(snapshot)
        call = _sample_call(analysis, sample)
        if call is None:
            return _result("TASK-005", "UNKNOWN", progress, "终态 Poll 可定位")
        return _result(
            "TASK-005",
            "FAIL",
            progress,
            100,
            [_evidence(call, "response.data.progress_percent", progress)],
        )
    return _result("TASK-005", "PASS", progress, 100)


def check_failed_error_present(analysis: dict) -> dict:
    """TASK-006：failed 必须有非空 error_code 或响应中的可定位错误文本。"""
    snapshot = _task_snapshot(analysis)
    lifecycle = snapshot.get("lifecycle") if isinstance(snapshot, dict) else None
    if not isinstance(lifecycle, dict):
        return _result("TASK-006", "UNKNOWN", None, "任务终态可用")
    status = _status_text(lifecycle.get("final_status"))
    if status is None:
        return _result("TASK-006", "UNKNOWN", None, "final_status 可用")
    if status != "FAILED":
        return _result("TASK-006", "NA", status.lower(), "failed 时检查错误信息")

    error_code = lifecycle.get("error_code")
    sample = _final_sample(snapshot)
    call = _sample_call(analysis, sample)
    data = _response_data(call)
    error_text = next(
        (
            data.get(key)
            for key in ("error_message", "error", "message")
            if isinstance(data.get(key), str) and data.get(key).strip()
        ),
        None,
    )
    if (isinstance(error_code, str) and error_code.strip()) or error_text:
        return _result(
            "TASK-006",
            "PASS",
            {"error_code": error_code, "error_message": error_text},
            "failed 时存在可定位错误",
        )
    if call is None:
        return _result("TASK-006", "UNKNOWN", None, "failed Poll 可定位")
    return _result(
        "TASK-006",
        "FAIL",
        {"status": "failed", "error_code": error_code},
        "error_code 或可定位错误信息非空",
        [_evidence(call, "response.data.status", data.get("status"))],
    )


def check_task_time_order(analysis: dict) -> dict:
    """TASK-007：比较 Create、Result、完成和过期四个业务毫秒时间。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return _result("TASK-007", "UNKNOWN", None, "任务时间证据可用")
    create_call = _call_by_id(analysis, snapshot.get("create_call_id"))
    result_call = _call_by_id(analysis, snapshot.get("result_call_id"))
    sample = _final_sample(snapshot)
    poll_call = _sample_call(analysis, sample)
    if create_call is None or result_call is None or poll_call is None or sample is None:
        return _result("TASK-007", "UNKNOWN", None, "Create/Result/终态 Poll 均可定位")

    create_data = _response_data(create_call)
    result_data = _response_data(result_call)
    values = {
        "create_time": create_data.get("create_time"),
        "result_create_time": result_data.get("create_time"),
        "completed_time": sample.get("completed_time"),
        "expire_time": sample.get("expire_time")
        if sample.get("expire_time") is not None
        else result_data.get("expire_time", create_data.get("expire_time")),
    }
    if any(not isinstance(value, (int, float)) for value in values.values()):
        return _result("TASK-007", "UNKNOWN", values, "四个关键时间均为数字")
    ordered = (
        values["create_time"]
        <= values["result_create_time"]
        <= values["completed_time"]
        <= values["expire_time"]
    )
    if not ordered:
        return _result(
            "TASK-007",
            "FAIL",
            values,
            "create_time ≤ result create_time ≤ completed_time ≤ expire_time",
            [
                _evidence(create_call, "response.data.create_time", values["create_time"]),
                _evidence(
                    result_call,
                    "response.data.create_time",
                    values["result_create_time"],
                ),
                _evidence(
                    poll_call,
                    "response.data.completed_time",
                    values["completed_time"],
                ),
            ],
        )
    return _result(
        "TASK-007",
        "PASS",
        values,
        "create_time ≤ result create_time ≤ completed_time ≤ expire_time",
    )


def check_succeeded_has_result(analysis: dict) -> dict:
    """TASK-008：成功任务缺 Result 时 FAIL，未完成任务保持 UNKNOWN。"""
    snapshot = _task_snapshot(analysis)
    lifecycle = snapshot.get("lifecycle") if isinstance(snapshot, dict) else None
    if not isinstance(lifecycle, dict):
        return _result("TASK-008", "UNKNOWN", None, "任务状态证据可用")
    status = _status_text(lifecycle.get("final_status"))
    if status is None:
        return _result("TASK-008", "UNKNOWN", None, "final_status 可用")
    if status == "SUCCEEDED":
        result_call = _call_by_id(analysis, snapshot.get("result_call_id"))
        if result_call is not None:
            return _result("TASK-008", "PASS", result_call.get("call_id"), "成功任务存在 Result")
        sample = _final_sample(snapshot)
        poll_call = _sample_call(analysis, sample)
        if poll_call is None:
            return _result("TASK-008", "UNKNOWN", None, "终态 Poll 可定位")
        return _result(
            "TASK-008",
            "FAIL",
            None,
            "成功任务存在对应结果接口",
            [_evidence(poll_call, "response.data.status", lifecycle.get("final_status"))],
        )
    if status == "FAILED":
        return _result("TASK-008", "NA", "failed", "仅成功任务要求 Result")
    return _result("TASK-008", "UNKNOWN", status.lower(), "等待任务终态后判断 Result")


def check_succeeded_final_phase(analysis: dict) -> dict:
    """TASK-009：成功但仍为 finalizing 只告警，不升级为失败。"""
    snapshot = _task_snapshot(analysis)
    lifecycle = snapshot.get("lifecycle") if isinstance(snapshot, dict) else None
    if not isinstance(lifecycle, dict):
        return _result("TASK-009", "UNKNOWN", None, "任务状态证据可用")
    status = _status_text(lifecycle.get("final_status"))
    phase = lifecycle.get("final_phase")
    if status is None:
        return _result("TASK-009", "UNKNOWN", None, "final_status 可用")
    if status == "SUCCEEDED" and phase == "finalizing":
        sample = _final_sample(snapshot)
        call = _sample_call(analysis, sample)
        if call is None:
            return _result("TASK-009", "UNKNOWN", phase, "终态 Poll 可定位")
        return _result(
            "TASK-009",
            "WARN",
            {"status": "succeeded", "phase": phase},
            "succeeded 后 phase 不停留 finalizing",
            [_evidence(call, "response.data.phase", phase)],
        )
    if status == "SUCCEEDED":
        if phase is None:
            return _result("TASK-009", "UNKNOWN", None, "成功终态 phase 可用")
        return _result("TASK-009", "PASS", phase, "成功终态不为 finalizing")
    if status == "FAILED":
        return _result("TASK-009", "NA", "failed", "仅 succeeded 适用")
    return _result("TASK-009", "UNKNOWN", status.lower(), "等待 succeeded 后判断 phase")


def check_processing_progress_stall(analysis: dict) -> dict:
    """TASK-010：保留 Poll 顺序，计算 processing 同进度的最长连续次数。"""
    snapshot = _task_snapshot(analysis)
    samples = snapshot.get("status_samples") if isinstance(snapshot, dict) else None
    if not isinstance(samples, list) or not samples:
        return _result("TASK-010", "UNKNOWN", None, "Poll 状态样本可用")

    best: tuple[int, object, int, int] = (0, None, -1, -1)
    current_value: object = None
    current_start = -1
    current_count = 0
    missing_progress = False
    processing_seen = False
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict) or _status_text(sample.get("status")) != "PROCESSING":
            current_value = None
            current_start = -1
            current_count = 0
            continue
        processing_seen = True
        value = sample.get("progress_percent")
        if not isinstance(value, (int, float)):
            missing_progress = True
            current_value = None
            current_start = -1
            current_count = 0
            continue
        if value == current_value and current_count:
            current_count += 1
        else:
            current_value = value
            current_start = index
            current_count = 1
        if current_count > best[0]:
            best = (current_count, value, current_start, index)

    count, value, start, end = best
    actual = {"progress_percent": value, "stalled_poll_count": count}
    if count >= 5:
        run_samples = samples[start : end + 1]
        evidence = [
            _evidence(call, "response.data.progress_percent", value)
            for sample in (run_samples[0], run_samples[-1])
            if (call := _sample_call(analysis, sample)) is not None
        ]
        if not evidence:
            return _result("TASK-010", "UNKNOWN", actual, "停滞 Poll 可定位")
        return _result(
            "TASK-010",
            "WARN",
            actual,
            "processing 同进度连续次数少于 5",
            evidence,
        )
    if missing_progress:
        return _result("TASK-010", "UNKNOWN", actual, "processing 进度均可用")
    if not processing_seen:
        return _result("TASK-010", "NA", 0, "存在 processing 时检查停滞")
    return _result(
        "TASK-010",
        "PASS",
        actual,
        "processing 同进度连续次数少于 5",
    )


def _result_call(analysis: dict, snapshot: dict | None = None) -> dict | None:
    """只按 Task 4 选中的成功 Result call_id 读取结果调用。"""
    resolved_snapshot = snapshot if snapshot is not None else _task_snapshot(analysis)
    if not isinstance(resolved_snapshot, dict):
        return None
    return _call_by_id(analysis, resolved_snapshot.get("result_call_id"))


def check_result_task_id(analysis: dict) -> dict:
    """RESULT-001：Result 请求和响应 ID 均必须等于所选任务 ID。"""
    snapshot = _task_snapshot(analysis)
    call = _result_call(analysis, snapshot)
    if snapshot is None or call is None:
        return _result("RESULT-001", "UNKNOWN", None, "Result 调用可定位")
    task_id = snapshot.get("task_id")
    request_id = _request_params(call).get("task_id")
    response_id = _response_data(call).get("task_id")
    if not all(isinstance(value, str) and value for value in (task_id, request_id, response_id)):
        return _result(
            "RESULT-001",
            "UNKNOWN",
            {"task_id": task_id, "request_task_id": request_id, "response_task_id": response_id},
            "Result task_id 路径均非空",
        )
    mismatches = []
    if request_id != task_id:
        mismatches.append(("request.params.task_id", request_id))
    if response_id != task_id:
        mismatches.append(("response.data.task_id", response_id))
    if mismatches:
        return _result(
            "RESULT-001",
            "FAIL",
            {path: value for path, value in mismatches},
            task_id,
            [_evidence(call, path, value) for path, value in mismatches],
        )
    return _result("RESULT-001", "PASS", task_id, "结果接口 task_id 与任务一致")


def check_result_schema_versions(analysis: dict) -> dict:
    """RESULT-002：比较 Result data 外层版本与原始 result 内层版本。"""
    snapshot = _task_snapshot(analysis)
    call = _result_call(analysis, snapshot)
    if call is None:
        return _result("RESULT-002", "UNKNOWN", None, "Result 调用可定位")
    data = _response_data(call)
    outer = data.get("schema_version")
    payload = data.get("result")
    inner = payload.get("schema_version") if isinstance(payload, dict) else None
    actual = {"outer": outer, "inner": inner}
    if not all(isinstance(value, str) and value for value in (outer, inner)):
        return _result("RESULT-002", "UNKNOWN", actual, "外层和内层版本均非空")
    if outer != inner:
        return _result(
            "RESULT-002",
            "FAIL",
            actual,
            "外层和内层 schema_version 一致",
            [_evidence(call, "response.data.result.schema_version", inner)],
        )
    return _result("RESULT-002", "PASS", outer, "外层和内层 schema_version 一致")


def check_result_id_present(analysis: dict) -> dict:
    """RESULT-003：成功 Result 响应必须提供非空字符串 result_id。"""
    call = _result_call(analysis)
    if call is None:
        return _result("RESULT-003", "UNKNOWN", None, "Result 调用可定位")
    result_id = _response_data(call).get("result_id")
    if not isinstance(result_id, str) or not result_id:
        return _result(
            "RESULT-003",
            "FAIL",
            result_id,
            "result_id 为非空字符串",
            [_evidence(call, "response.data.result_id", result_id)],
        )
    return _result("RESULT-003", "PASS", result_id, "result_id 非空")


def check_required_result_fields(analysis: dict) -> dict:
    """RESULT-004：仅已知 Schema 检查 Task 5 生成的必填 MISSING 节点。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return _result("RESULT-004", "UNKNOWN", None, "Result Schema 事实可用")
    schema_status = snapshot.get("schema_status")
    if schema_status == "UNKNOWN_SCHEMA":
        return _result("RESULT-004", "NA", snapshot.get("schema_version"), "仅已知 Schema 适用")
    if schema_status != "KNOWN_SCHEMA" or _result_call(analysis, snapshot) is None:
        return _result("RESULT-004", "UNKNOWN", schema_status, "已知 Result Schema 可用")
    fields = snapshot.get("result_fields")
    if not isinstance(fields, list) or not fields:
        return _result("RESULT-004", "UNKNOWN", None, "Result 字段索引可用")

    missing_fields = [
        field
        for field in fields
        if isinstance(field, dict) and field.get("presence") == "MISSING"
    ]
    if missing_fields:
        evidence: list[dict] = []
        for field in missing_fields:
            source = field.get("source")
            call = _call_by_id(
                analysis,
                source.get("call_id") if isinstance(source, dict) else None,
            )
            if call is not None:
                evidence.append(_evidence(call, field.get("path", "response.data.result"), None))
        if not evidence:
            return _result(
                "RESULT-004",
                "UNKNOWN",
                [field.get("path") for field in missing_fields],
                "缺失字段证据可定位",
            )
        return _result(
            "RESULT-004",
            "FAIL",
            [field.get("path") for field in missing_fields],
            "已知 Schema 必填字段存在",
            evidence,
        )

    warnings = snapshot.get("warnings")
    if isinstance(warnings, list) and any(
        isinstance(warning, dict)
        and warning.get("code") == "MAX_FIELD_COUNT_REACHED"
        and warning.get("omitted_required_paths")
        for warning in warnings
    ):
        return _result(
            "RESULT-004",
            "UNKNOWN",
            "required paths truncated",
            "必填节点完整进入字段索引",
        )
    return _result("RESULT-004", "PASS", [], "已知 Schema 必填字段存在")


def check_result_empty_health(analysis: dict) -> dict:
    """RESULT-005：空值仅汇总为诊断事实，本规则不因计数非零告警。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None or _result_call(analysis, snapshot) is None:
        return _result("RESULT-005", "UNKNOWN", None, "Result 字段健康度可用")
    health = snapshot.get("field_health")
    keys = (
        "null_count",
        "empty_string_count",
        "empty_array_count",
        "empty_object_count",
    )
    if not isinstance(health, dict) or any(
        not isinstance(health.get(key), int) for key in keys
    ):
        return _result("RESULT-005", "UNKNOWN", health, "四类空值计数完整")
    actual = {key: health[key] for key in keys}
    return _result("RESULT-005", "PASS", actual, "仅汇总，不把空值统计本身判为异常")


def check_unknown_result_fields_preserved(analysis: dict) -> dict:
    """RESULT-006：已知 Schema 扩展字段保留且 schema_known=false。"""
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return _result("RESULT-006", "UNKNOWN", None, "Result Schema 事实可用")
    schema_status = snapshot.get("schema_status")
    if schema_status == "UNKNOWN_SCHEMA":
        # 整份 Schema 未知时无法把字段区分为“旧 Schema 扩展”，专属检查 NA。
        return _result("RESULT-006", "NA", snapshot.get("schema_version"), "仅已知 Schema 扩展字段适用")
    if schema_status != "KNOWN_SCHEMA" or _result_call(analysis, snapshot) is None:
        return _result("RESULT-006", "UNKNOWN", schema_status, "已知 Result Schema 可用")
    fields = snapshot.get("result_fields")
    if not isinstance(fields, list) or not fields:
        return _result("RESULT-006", "UNKNOWN", None, "Result 字段索引可用")
    unknown_paths = [
        field.get("path")
        for field in fields
        if isinstance(field, dict) and field.get("schema_known") is False
    ]
    return _result(
        "RESULT-006",
        "PASS",
        {
            "unknown_field_count": len(unknown_paths),
            "unknown_field_paths": unknown_paths,
        },
        "未知字段保留并标记 schema_known=false",
    )


_REPLY_SCHEMA_VERSION = "dating.reply_generation.v1"
_ANALYSIS_SCHEMA_VERSION = "dating.relationship_analysis.v1"
_SIGNAL_GROUPS = ("positive_signals", "watch_signals", "risk_signals")
_EVENT_GROUPS = ("turning_points", "hidden_meanings", "did_well", "could_improve")


def _schema_rule_inputs(
    analysis: dict,
    rule_id: str,
    expected_schema: str,
) -> tuple[dict | None, dict | None, dict | None]:
    """统一判定 Schema 专属规则是否适用，并解析固定业务分组。

    返回 ``(snapshot, sections, early_result)``。未知 Schema 和另一种已知
    Schema 明确返回 NA；日志不足或投影结构损坏返回 UNKNOWN。业务规则只从
    Task 5 的 summary/sections/fields 读取事实，不回读原始 Result payload。
    """
    snapshot = _task_snapshot(analysis)
    if snapshot is None:
        return None, None, _result(
            rule_id, "UNKNOWN", None, f"{expected_schema} 结构化 Result 可用"
        )
    schema_version = snapshot.get("schema_version")
    schema_status = snapshot.get("schema_status")
    if schema_status == "UNKNOWN_SCHEMA":
        return None, None, _result(
            rule_id, "NA", schema_version, f"仅适用于 {expected_schema}"
        )
    if schema_status == "KNOWN_SCHEMA" and schema_version != expected_schema:
        return None, None, _result(
            rule_id, "NA", schema_version, f"仅适用于 {expected_schema}"
        )
    if schema_status != "KNOWN_SCHEMA" or schema_version != expected_schema:
        return None, None, _result(
            rule_id, "UNKNOWN", schema_version, f"{expected_schema} Schema 可定位"
        )
    if _result_call(analysis, snapshot) is None:
        return None, None, _result(
            rule_id, "UNKNOWN", None, "Result 调用及业务分组可定位"
        )

    summary = snapshot.get("result_summary")
    raw_sections = snapshot.get("result_sections")
    fields = snapshot.get("result_fields")
    if (
        not isinstance(summary, dict)
        or not isinstance(raw_sections, list)
        or not isinstance(fields, list)
    ):
        return None, None, _result(
            rule_id, "UNKNOWN", None, "Result summary/sections/fields 结构完整"
        )

    sections: dict[str, object] = {}
    for section in raw_sections:
        if (
            not isinstance(section, dict)
            or not _is_meaningful_text(section.get("path"))
            or "value" not in section
            or section["path"] in sections
        ):
            return None, None, _result(
                rule_id, "UNKNOWN", None, "Result section path 唯一且可读取"
            )
        sections[section["path"]] = section["value"]
    return snapshot, sections, None


def _schema_evidence(analysis: dict, json_path: str, value: object) -> list[dict]:
    """把业务规则事实定位到真实 Result 响应块，保持 FAIL/WARN 证据不变量。"""
    call = _result_call(analysis)
    return [_evidence(call, json_path, value)] if call is not None else []


def _reply_roles(
    analysis: dict, rule_id: str
) -> tuple[list[dict] | None, dict | None]:
    """读取 Reply roles；不适用或结构不足时直接返回稳定规则结果。"""
    _, sections, early = _schema_rule_inputs(
        analysis, rule_id, _REPLY_SCHEMA_VERSION
    )
    if early is not None:
        return None, early
    roles = sections.get("result.roles") if sections is not None else None
    if not isinstance(roles, list) or any(not isinstance(role, dict) for role in roles):
        return None, _result(rule_id, "UNKNOWN", roles, "result.roles 为对象数组")
    return roles, None


def check_reply_ids_unique(analysis: dict) -> dict:
    """REPLY-001：全部 Role 下的 reply_id 必须为非空且全局唯一。"""
    roles, early = _reply_roles(analysis, "REPLY-001")
    if early is not None:
        return early
    reply_ids: list[str] = []
    for role in roles or []:
        replies = role.get("replies")
        if not isinstance(replies, list) or any(
            not isinstance(reply, dict) for reply in replies
        ):
            return _result("REPLY-001", "UNKNOWN", replies, "replies 为对象数组")
        for reply in replies:
            reply_id = reply.get("reply_id")
            if not _is_meaningful_text(reply_id):
                return _result("REPLY-001", "UNKNOWN", reply_id, "reply_id 可定位")
            reply_ids.append(reply_id)
    duplicates = sorted({item for item in reply_ids if reply_ids.count(item) > 1})
    if duplicates:
        return _result(
            "REPLY-001",
            "FAIL",
            {"duplicate_reply_ids": duplicates},
            "每个 reply_id 唯一",
            _schema_evidence(
                analysis, "result.roles[].replies[].reply_id", duplicates
            ),
        )
    return _result(
        "REPLY-001",
        "PASS",
        {"reply_count": len(reply_ids), "unique_reply_id_count": len(reply_ids)},
        "每个 reply_id 唯一",
    )


def check_reply_one_top_pick_per_role(analysis: dict) -> dict:
    """REPLY-002：每个 Role 最多一个 reply 显式标记为 Top Pick。"""
    roles, early = _reply_roles(analysis, "REPLY-002")
    if early is not None:
        return early
    counts: list[int] = []
    for index, role in enumerate(roles or []):
        replies = role.get("replies")
        if not isinstance(replies, list) or any(
            not isinstance(reply, dict) for reply in replies
        ):
            return _result("REPLY-002", "UNKNOWN", replies, "replies 为对象数组")
        count = sum(reply.get("is_top_pick") is True for reply in replies)
        counts.append(count)
        if count > 1:
            return _result(
                "REPLY-002",
                "FAIL",
                {"role_index": index, "top_pick_count": count},
                "每个 Role 最多一个 is_top_pick=true",
                _schema_evidence(
                    analysis, f"result.roles[{index}].replies", replies
                ),
            )
    return _result("REPLY-002", "PASS", counts, "每个 Role 最多一个 Top Pick")


def check_reply_top_pick_reference(analysis: dict) -> dict:
    """REPLY-003：每个 top_pick.reply_id 必须引用同 Role 的 replies。"""
    roles, early = _reply_roles(analysis, "REPLY-003")
    if early is not None:
        return early
    for index, role in enumerate(roles or []):
        replies = role.get("replies")
        top_pick = role.get("top_pick")
        if not isinstance(replies, list) or not isinstance(top_pick, dict):
            return _result("REPLY-003", "UNKNOWN", top_pick, "top_pick 与 replies 可用")
        reply_ids = {
            reply.get("reply_id")
            for reply in replies
            if isinstance(reply, dict) and _is_meaningful_text(reply.get("reply_id"))
        }
        top_pick_id = top_pick.get("reply_id")
        if not _is_meaningful_text(top_pick_id):
            return _result("REPLY-003", "UNKNOWN", top_pick_id, "top_pick.reply_id 可定位")
        if top_pick_id not in reply_ids:
            return _result(
                "REPLY-003",
                "FAIL",
                top_pick_id,
                sorted(reply_ids),
                _schema_evidence(
                    analysis, f"result.roles[{index}].top_pick.reply_id", top_pick_id
                ),
            )
    return _result("REPLY-003", "PASS", "all referenced", "Top Pick 引用已有 Reply")


def check_reply_top_pick_text(analysis: dict) -> dict:
    """REPLY-004：Top Pick 的冗余文案必须与被引用 Reply 完全一致。"""
    roles, early = _reply_roles(analysis, "REPLY-004")
    if early is not None:
        return early
    for index, role in enumerate(roles or []):
        replies = role.get("replies")
        top_pick = role.get("top_pick")
        if not isinstance(replies, list) or not isinstance(top_pick, dict):
            return _result("REPLY-004", "UNKNOWN", top_pick, "top_pick 与 replies 可用")
        top_pick_id = top_pick.get("reply_id")
        referenced = next(
            (
                reply
                for reply in replies
                if isinstance(reply, dict) and reply.get("reply_id") == top_pick_id
            ),
            None,
        )
        if referenced is None:
            return _result("REPLY-004", "UNKNOWN", top_pick_id, "Top Pick 引用可解析")
        expected_text = referenced.get("text")
        actual_text = top_pick.get("text")
        if not isinstance(expected_text, str) or not isinstance(actual_text, str):
            return _result("REPLY-004", "UNKNOWN", actual_text, "两处文案可定位")
        if actual_text != expected_text:
            return _result(
                "REPLY-004",
                "FAIL",
                actual_text,
                expected_text,
                _schema_evidence(
                    analysis, f"result.roles[{index}].top_pick.text", actual_text
                ),
            )
    return _result("REPLY-004", "PASS", "all matched", "Top Pick 文案与 Reply 一致")


def check_reply_alternatives(analysis: dict) -> dict:
    """REPLY-005：alternatives ID 多重集合等于非 Top Pick Reply ID。"""
    roles, early = _reply_roles(analysis, "REPLY-005")
    if early is not None:
        return early
    for index, role in enumerate(roles or []):
        replies = role.get("replies")
        alternatives = role.get("alternatives")
        if (
            not isinstance(replies, list)
            or not isinstance(alternatives, list)
            or any(not isinstance(item, dict) for item in replies + alternatives)
        ):
            return _result("REPLY-005", "UNKNOWN", alternatives, "Reply/alternative 数组可用")
        expected_ids = [
            item.get("reply_id")
            for item in replies
            if item.get("is_top_pick") is not True
        ]
        actual_ids = [item.get("reply_id") for item in alternatives]
        if any(not _is_meaningful_text(item) for item in expected_ids + actual_ids):
            return _result("REPLY-005", "UNKNOWN", actual_ids, "alternative reply_id 可定位")
        if sorted(actual_ids) != sorted(expected_ids):
            return _result(
                "REPLY-005",
                "FAIL",
                actual_ids,
                expected_ids,
                _schema_evidence(
                    analysis, f"result.roles[{index}].alternatives", actual_ids
                ),
            )
    return _result("REPLY-005", "PASS", "all matched", "Alternatives 与非 Top Pick 一致")


def check_reply_role_ranks(analysis: dict) -> dict:
    """REPLY-006：Role rank 必须是可排序的唯一整数。"""
    roles, early = _reply_roles(analysis, "REPLY-006")
    if early is not None:
        return early
    ranks = [role.get("rank") for role in roles or []]
    if any(type(rank) is not int for rank in ranks):
        return _result("REPLY-006", "UNKNOWN", ranks, "Role rank 为整数")
    duplicates = sorted({rank for rank in ranks if ranks.count(rank) > 1})
    if duplicates:
        return _result(
            "REPLY-006",
            "FAIL",
            {"duplicate_ranks": duplicates},
            "Role rank 不重复且可从小到大排序",
            _schema_evidence(analysis, "result.roles[].rank", duplicates),
        )
    return _result("REPLY-006", "PASS", sorted(ranks), "Role rank 唯一且可排序")


def check_reply_degradation_consistency(analysis: dict) -> dict:
    """REPLY-007：降级 warning 存在而标志为 false 时输出可定位 WARN。"""
    _, sections, early = _schema_rule_inputs(
        analysis, "REPLY-007", _REPLY_SCHEMA_VERSION
    )
    if early is not None:
        return early
    degradation = sections.get("result.degradation") if sections else None
    warnings = sections.get("result.warnings") if sections else None
    if not isinstance(degradation, dict) or not isinstance(warnings, list):
        return _result("REPLY-007", "UNKNOWN", None, "degradation/warnings 可用")
    is_degraded = degradation.get("is_degraded")
    if type(is_degraded) is not bool:
        return _result("REPLY-007", "UNKNOWN", is_degraded, "is_degraded 为布尔值")
    degradation_warnings = []
    for warning in warnings:
        warning_text = (
            warning
            if isinstance(warning, str)
            else warning.get("code") if isinstance(warning, dict) else None
        )
        if isinstance(warning_text, str) and "DEGRAD" in warning_text.upper():
            degradation_warnings.append(warning)
    actual = {"is_degraded": is_degraded, "warnings": warnings}
    if degradation_warnings and not is_degraded:
        return _result(
            "REPLY-007",
            "WARN",
            actual,
            "含降级 warning 时 is_degraded=true",
            _schema_evidence(
                analysis, "result.degradation.is_degraded", is_degraded
            ),
        )
    return _result("REPLY-007", "PASS", actual, "降级 warning 与标志一致")


def check_reply_person_history_nullability(analysis: dict) -> dict:
    """REPLY-008：仅确认未使用人物历史时 ``person_id=null`` 合法。

    PRD 没有定义 ``person_history_used=true`` 与 ``person_id`` 的反向约束，
    因此不能据此构造语义 FAIL；字段缺失则保留为日志事实不足的 UNKNOWN。
    """
    _, sections, early = _schema_rule_inputs(
        analysis, "REPLY-008", _REPLY_SCHEMA_VERSION
    )
    if early is not None:
        return early
    association = sections.get("result.association") if sections else None
    if not isinstance(association, dict):
        return _result("REPLY-008", "UNKNOWN", association, "association 可用")
    if "person_history_used" not in association or "person_id" not in association:
        missing = [
            key
            for key in ("person_history_used", "person_id")
            if key not in association
        ]
        return _result(
            "REPLY-008",
            "UNKNOWN",
            {"missing_fields": missing},
            "association 两个字段均可定位",
        )
    used = association["person_history_used"]
    person_id = association["person_id"]
    if type(used) is not bool:
        return _result("REPLY-008", "UNKNOWN", used, "person_history_used 为布尔值")
    return _result(
        "REPLY-008",
        "PASS",
        {"person_history_used": used, "person_id": person_id},
        "person_history_used=false 时允许 person_id=null；不推断反向约束",
    )


def _analysis_sections(
    analysis: dict, rule_id: str
) -> tuple[dict[str, object] | None, dict | None]:
    """读取 Analysis 业务分组，并复用统一 Schema 适用性语义。"""
    _, sections, early = _schema_rule_inputs(
        analysis, rule_id, _ANALYSIS_SCHEMA_VERSION
    )
    return sections, early


def _integer_values(mapping: dict, keys: tuple[str, ...]) -> list[int] | None:
    """仅接受 JSON 整数计数，排除 bool 和缺失字段。"""
    values = [mapping.get(key) for key in keys]
    return values if all(type(value) is int for value in values) else None


def check_analysis_asset_counts(analysis: dict) -> dict:
    """ANALYSIS-001：有效与忽略资源计数之和等于上传资源数。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-001")
    if early is not None:
        return early
    scope = sections.get("result.analysis_scope") if sections else None
    if not isinstance(scope, dict):
        return _result("ANALYSIS-001", "UNKNOWN", scope, "analysis_scope 可用")
    keys = ("uploaded_asset_count", "valid_asset_count", "ignored_asset_count")
    values = _integer_values(scope, keys)
    if values is None:
        return _result("ANALYSIS-001", "UNKNOWN", scope, "三项资源计数为整数")
    uploaded, valid, ignored = values
    actual = dict(zip(keys, values))
    if valid + ignored != uploaded:
        return _result(
            "ANALYSIS-001",
            "FAIL",
            actual,
            "valid_asset_count + ignored_asset_count = uploaded_asset_count",
            _schema_evidence(analysis, "result.analysis_scope", actual),
        )
    return _result("ANALYSIS-001", "PASS", actual, "资源计数守恒")


def check_analysis_valid_message_count(analysis: dict) -> dict:
    """ANALYSIS-002：分析消息数不得超过有效消息数。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-002")
    if early is not None:
        return early
    scope = sections.get("result.analysis_scope") if sections else None
    if not isinstance(scope, dict):
        return _result("ANALYSIS-002", "UNKNOWN", scope, "analysis_scope 可用")
    keys = ("valid_message_count", "analyzed_message_count")
    values = _integer_values(scope, keys)
    if values is None:
        return _result("ANALYSIS-002", "UNKNOWN", scope, "两项消息计数为整数")
    valid, analyzed = values
    actual = dict(zip(keys, values))
    if analyzed > valid:
        return _result(
            "ANALYSIS-002",
            "FAIL",
            actual,
            "analyzed_message_count <= valid_message_count",
            _schema_evidence(
                analysis, "result.analysis_scope.analyzed_message_count", analyzed
            ),
        )
    return _result("ANALYSIS-002", "PASS", actual, "分析消息数不超过有效消息数")


def check_analysis_participant_counts(analysis: dict) -> dict:
    """ANALYSIS-003：双方消息计数必须等于 analyzed_message_count。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-003")
    if early is not None:
        return early
    scope = sections.get("result.analysis_scope") if sections else None
    dashboard = sections.get("result.overview.dashboard") if sections else None
    message_counts = dashboard.get("message_counts") if isinstance(dashboard, dict) else None
    if not isinstance(scope, dict) or not isinstance(message_counts, dict):
        return _result("ANALYSIS-003", "UNKNOWN", None, "消息计数分组可用")
    participant_values = _integer_values(message_counts, ("user", "other"))
    analyzed_values = _integer_values(scope, ("analyzed_message_count",))
    if participant_values is None or analyzed_values is None:
        return _result("ANALYSIS-003", "UNKNOWN", None, "三项消息计数为整数")
    user_count, other_count = participant_values
    analyzed = analyzed_values[0]
    actual = {"user": user_count, "other": other_count, "analyzed": analyzed}
    if user_count + other_count != analyzed:
        return _result(
            "ANALYSIS-003",
            "FAIL",
            actual,
            "user + other = analyzed_message_count",
            _schema_evidence(
                analysis, "result.overview.dashboard.message_counts", actual
            ),
        )
    return _result("ANALYSIS-003", "PASS", actual, "双方消息数等于分析消息总数")


def check_analysis_signal_ids(analysis: dict) -> dict:
    """ANALYSIS-004：signal_id 只要求在各自类型数组内唯一。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-004")
    if early is not None:
        return early
    signals = sections.get("result.chat_signals") if sections else None
    if not isinstance(signals, dict):
        return _result("ANALYSIS-004", "UNKNOWN", signals, "chat_signals 可用")
    counts: dict[str, int] = {}
    for group in _SIGNAL_GROUPS:
        items = signals.get(group)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return _result("ANALYSIS-004", "UNKNOWN", items, f"{group} 为对象数组")
        ids = [item.get("signal_id") for item in items]
        if any(not _is_meaningful_text(item) for item in ids):
            return _result("ANALYSIS-004", "UNKNOWN", ids, "signal_id 可定位")
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            return _result(
                "ANALYSIS-004",
                "FAIL",
                {"signal_type": group, "duplicate_signal_ids": duplicates},
                "signal_id 在同一类型数组中唯一",
                _schema_evidence(
                    analysis, f"result.chat_signals.{group}[].signal_id", duplicates
                ),
            )
        counts[group] = len(ids)
    return _result("ANALYSIS-004", "PASS", counts, "同类型 Signal ID 唯一")


def check_analysis_event_ids(analysis: dict) -> dict:
    """ANALYSIS-005：event_id 在整个 key_events 分组中全局唯一。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-005")
    if early is not None:
        return early
    events = sections.get("result.key_events") if sections else None
    if not isinstance(events, dict):
        return _result("ANALYSIS-005", "UNKNOWN", events, "key_events 可用")
    event_ids: list[str] = []
    for group in _EVENT_GROUPS:
        items = events.get(group)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            return _result("ANALYSIS-005", "UNKNOWN", items, f"{group} 为对象数组")
        ids = [item.get("event_id") for item in items]
        if any(not _is_meaningful_text(item) for item in ids):
            return _result("ANALYSIS-005", "UNKNOWN", ids, "event_id 可定位")
        event_ids.extend(ids)
    duplicates = sorted({item for item in event_ids if event_ids.count(item) > 1})
    if duplicates:
        return _result(
            "ANALYSIS-005",
            "FAIL",
            {"duplicate_event_ids": duplicates},
            "event_id 在 key_events 中唯一",
            _schema_evidence(analysis, "result.key_events", duplicates),
        )
    return _result("ANALYSIS-005", "PASS", len(event_ids), "Key Event ID 唯一")


def check_analysis_evidence_message_ids(analysis: dict) -> dict:
    """ANALYSIS-006：每个 Signal/Event 的 evidence_message_ids 数组非空。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-006")
    if early is not None:
        return early
    signals = sections.get("result.chat_signals") if sections else None
    events = sections.get("result.key_events") if sections else None
    if not isinstance(signals, dict) or not isinstance(events, dict):
        return _result("ANALYSIS-006", "UNKNOWN", None, "Signal/Event 分组可用")
    violations: list[dict] = []
    for root, groups, container in (
        ("result.chat_signals", _SIGNAL_GROUPS, signals),
        ("result.key_events", _EVENT_GROUPS, events),
    ):
        for group in groups:
            items = container.get(group)
            if not isinstance(items, list) or any(
                not isinstance(item, dict) for item in items
            ):
                return _result("ANALYSIS-006", "UNKNOWN", items, f"{group} 为对象数组")
            for index, item in enumerate(items):
                evidence_ids = (
                    item["evidence_message_ids"]
                    if "evidence_message_ids" in item
                    else "MISSING"
                )
                if not isinstance(evidence_ids, list) or not evidence_ids:
                    violations.append(
                        {
                            "path": (
                                f"{root}.{group}[{index}].evidence_message_ids"
                            ),
                            "value": evidence_ids,
                        }
                    )
    if violations:
        evidence = []
        for violation in violations:
            evidence.extend(
                _schema_evidence(
                    analysis,
                    violation["path"],
                    violation["value"],
                )
            )
        return _result(
            "ANALYSIS-006",
            "FAIL",
            violations,
            "Signal/Event 的 evidence_message_ids 非空",
            evidence,
        )
    return _result("ANALYSIS-006", "PASS", "all non-empty", "证据消息数组非空")


def check_analysis_empty_value_summary(analysis: dict) -> dict:
    """ANALYSIS-007：只统计 Dashboard 指定 null/空数组，不生成告警。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-007")
    if early is not None:
        return early
    dashboard = sections.get("result.overview.dashboard") if sections else None
    if not isinstance(dashboard, dict):
        return _result("ANALYSIS-007", "UNKNOWN", dashboard, "Dashboard 可用")
    effort = dashboard.get("effort")
    match_degree = dashboard.get("match_degree")
    keywords = dashboard.get("keywords")
    if (
        not isinstance(effort, dict)
        or not isinstance(match_degree, dict)
        or not isinstance(keywords, dict)
        or any(key not in effort for key in ("you_score", "them_score"))
        or "score" not in match_degree
        or any(key not in keywords for key in ("user_focus", "other_focus"))
    ):
        return _result("ANALYSIS-007", "UNKNOWN", None, "指定 Dashboard 字段可定位")
    actual = {
        "effort_null_count": sum(
            effort[key] is None for key in ("you_score", "them_score")
        ),
        "match_degree_null_count": int(match_degree["score"] is None),
        "keywords_empty_array_count": sum(
            keywords[key] == [] for key in ("user_focus", "other_focus")
        ),
    }
    return _result("ANALYSIS-007", "PASS", actual, "仅汇总，不把空值统计判为异常")


def check_analysis_warning_summary(analysis: dict) -> dict:
    """ANALYSIS-008：原样汇总 warnings 数组，不依据内容推断质量。"""
    sections, early = _analysis_sections(analysis, "ANALYSIS-008")
    if early is not None:
        return early
    warnings = sections.get("result.warnings") if sections else None
    if not isinstance(warnings, list):
        return _result("ANALYSIS-008", "UNKNOWN", warnings, "warnings 数组可用")
    return _result(
        "ANALYSIS-008",
        "PASS",
        {"warning_count": len(warnings), "warnings": warnings},
        "仅汇总 Analysis warnings",
    )


GENERIC_RULES = (
    check_parse_complete,
    check_gateway_pairing,
    check_outer_http_status,
    check_gateway_status,
    check_subresponse_status,
    check_trace_ids_present,
    check_used_asset_upload_chain,
    check_upload_metadata_consistency,
)
TASK_RULES = (
    check_task_ids_consistent,
    check_task_method_type_consistency,
    check_task_status_transitions,
    check_task_progress_monotonic,
    check_succeeded_progress_complete,
    check_failed_error_present,
    check_task_time_order,
    check_succeeded_has_result,
    check_succeeded_final_phase,
    check_processing_progress_stall,
)
RESULT_RULES = (
    check_result_task_id,
    check_result_schema_versions,
    check_result_id_present,
    check_required_result_fields,
    check_result_empty_health,
    check_unknown_result_fields_preserved,
)
REPLY_RULES = (
    check_reply_ids_unique,
    check_reply_one_top_pick_per_role,
    check_reply_top_pick_reference,
    check_reply_top_pick_text,
    check_reply_alternatives,
    check_reply_role_ranks,
    check_reply_degradation_consistency,
    check_reply_person_history_nullability,
)
ANALYSIS_RULES = (
    check_analysis_asset_counts,
    check_analysis_valid_message_count,
    check_analysis_participant_counts,
    check_analysis_signal_ids,
    check_analysis_event_ids,
    check_analysis_evidence_message_ids,
    check_analysis_empty_value_summary,
    check_analysis_warning_summary,
)


def _normalized_secret_key(key: object) -> str:
    """把大小写、连字符、下划线和 camel 变体归一为精确类别键。

    仅移除约定的格式分隔符，不做前缀或模糊命中；例如 ``token_count``
    会归一为 ``tokencount``，不会误命中精确的 ``token``。
    """
    return str(key).lower().replace("-", "").replace("_", "")


def _redacted_signed_url(value: str) -> str | None:
    """识别签名 URL，并在保留对象路径的同时移除整个查询串。"""
    try:
        parsed = urlsplit(value)
    except ValueError:
        # urllib 会拒绝未闭合 IPv6 host；这类坏文本没有可安全确认的 URL
        # 结构，因此按普通字符串继续后续 Base64/长度规则，而不是中断响应。
        return None
    if not parsed.scheme or not parsed.netloc or not parsed.query:
        return None
    query_keys = {
        _normalized_secret_key(query_key)
        for query_key, _query_value in parse_qsl(
            parsed.query, keep_blank_values=True
        )
    }
    has_signature = any(
        "signature" in query_key
        or query_key == "qsignalgorithm"
        # Azure SAS 使用短键 sig；必须精确匹配，避免把普通 signal 等参数
        # 当成签名并删除整个查询串。
        or query_key == "sig"
        for query_key in query_keys
    )
    if not has_signature:
        return None
    # 不使用 urlunsplit，避免固定占位符中的方括号被百分号编码。
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{_REDACTED}"


def _is_long_base64_candidate(value: str) -> bool:
    """判断连续 256 字符以上的标准或 URL-safe Base64 候选值。

    URL-safe 候选只要出现 ``-`` 或 ``_`` 专用字符即按二进制处理；普通
    自由文本由空格、标点等非 Base64 字符与该分支区分。
    """
    if len(value) < 256:
        return False
    if _BASE64_CANDIDATE_RE.fullmatch(value) is not None:
        return True
    urlsafe_marker_count = value.count("-") + value.count("_")
    return (
        urlsafe_marker_count >= 1
        and _URLSAFE_BASE64_CANDIDATE_RE.fullmatch(value) is not None
    )


def _append_truncation_warnings(snapshot: dict, paths: list[str]) -> None:
    """在新建的 task snapshot 上补充去重后的字段截断告警。"""
    if not paths:
        return
    warnings = snapshot.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
        snapshot["warnings"] = warnings
    existing = {
        (warning.get("code"), warning.get("json_path"))
        for warning in warnings
        if isinstance(warning, dict)
    }
    for path in paths:
        identity = ("VALUE_TRUNCATED", path)
        if identity in existing:
            continue
        warnings.append(
            {
                "code": "VALUE_TRUNCATED",
                "message": _TRUNCATION_WARNING_MESSAGE,
                "json_path": path,
            }
        )
        existing.add(identity)


def _redact_dating_value(
    value: object,
    *,
    key: object = None,
    field_path: str | None = None,
    truncated_field_paths: list[str],
) -> object:
    """递归构造脱敏副本，并记录发生自由文本截断的 Result Field。"""
    if key is not None and _normalized_secret_key(key) in _SENSITIVE_KEYS:
        return _REDACTED

    if isinstance(value, dict):
        node_path = value.get("path")
        is_field_node = isinstance(node_path, str) and "value" in value
        redacted = {}
        for child_key, child_value in value.items():
            child_field_path = (
                node_path if is_field_node and child_key == "value" else field_path
            )
            redacted[child_key] = _redact_dating_value(
                child_value,
                key=child_key,
                field_path=child_field_path,
                truncated_field_paths=truncated_field_paths,
            )
        if is_field_node and node_path in truncated_field_paths:
            redacted["value_truncated"] = True

        # 仅修改刚构造的副本；父级 analysis 和 snapshot 入口都执行去重，
        # 从而兼容直接脱敏 snapshot 与脱敏完整分析响应两种调用方式。
        if "result_fields" in redacted:
            _append_truncation_warnings(redacted, truncated_field_paths)
        snapshot = redacted.get("task_snapshot")
        if isinstance(snapshot, dict):
            _append_truncation_warnings(snapshot, truncated_field_paths)
        return redacted

    if isinstance(value, list):
        return [
            _redact_dating_value(
                item,
                field_path=field_path,
                truncated_field_paths=truncated_field_paths,
            )
            for item in value
        ]

    if not isinstance(value, str):
        return value

    signed_url = _redacted_signed_url(value)
    if signed_url is not None:
        return signed_url
    if value.lower().startswith("data:") and ";base64," in value.lower():
        return f"[REDACTED_BASE64 length={len(value)}]"
    if _is_long_base64_candidate(value):
        return f"[REDACTED_BASE64 length={len(value)}]"
    if len(value) > _MAX_TEXT_VALUE_CHARS:
        if field_path is not None and field_path not in truncated_field_paths:
            truncated_field_paths.append(field_path)
        return value[:_MAX_TEXT_VALUE_CHARS]
    return value


def redact_dating_response(value: object, key: str | None = None) -> object:
    """返回 Dating 响应的递归脱敏副本，不修改调用方传入对象。

    敏感键、签名 URL 和 Base64 候选值使用固定占位符；其他超过
    20,000 字符的自由文本被截断。若超限值来自 Result Field，还会设置
    ``value_truncated`` 并在 task snapshot 中生成带字段路径的稳定告警。
    """
    return _redact_dating_value(
        value,
        key=key,
        truncated_field_paths=[],
    )


def _report_value(value: object) -> str:
    """把结构化值稳定序列化为单个 Markdown 单元格。"""
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return rendered.replace("|", "\\|").replace("\r\n", "<br>").replace(
        "\n", "<br>"
    )


def _report_table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> list[str]:
    """渲染列数固定的 Markdown 表格；空表也保留表头以稳定模板。"""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_report_value(cell) for cell in row) + " |"
        for row in rows
    )
    return lines


def _warning_location(warning: dict) -> object:
    """提取 warning 已有的块级或 JSON 路径证据，不制造具体行定位。"""
    location = {
        key: warning[key]
        for key in (
            "call_id",
            "method",
            "line",
            "line_start",
            "line_end",
            "json_path",
        )
        if warning.get(key) is not None
    }
    evidence = warning.get("evidence")
    if evidence:
        location["evidence"] = evidence
    return location or None


def _report_overview(analysis: dict, checks: list[dict]) -> list[str]:
    """生成总体结论，只汇总已有事实和确定性计数。"""
    snapshot = analysis.get("task_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    summary = analysis.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    abnormal_calls = sum(
        value
        for value in (
            summary.get("http_error_count"),
            summary.get("gateway_error_count"),
            summary.get("business_error_count"),
        )
        if isinstance(value, int) and not isinstance(value, bool)
    )
    outcome_counts = {
        outcome: sum(check.get("outcome") == outcome for check in checks)
        for outcome in ("FAIL", "WARN", "UNKNOWN")
    }
    return [
        f"- verdict: `{compute_dating_verdict(checks)}`",
        f"- 任务类型: `{_report_value(snapshot.get('task_type'))}`",
        f"- Schema: `{_report_value(snapshot.get('schema_version'))}`",
        "- 接口调用数: "
        f"{_report_value(summary.get('logical_interface_call_count', len(analysis.get('calls', []))))}",
        f"- 异常调用数: {abnormal_calls}",
        "- 规则计数: "
        f"FAIL={outcome_counts['FAIL']}, WARN={outcome_counts['WARN']}, "
        f"UNKNOWN={outcome_counts['UNKNOWN']}",
    ]


def _report_calls(analysis: dict) -> list[str]:
    """按 parser 调用顺序输出接口、状态、追踪 ID 与耗时。"""
    rows = []
    calls = analysis.get("calls")
    calls = calls if isinstance(calls, list) else []
    for index, call in enumerate(calls, start=1):
        if not isinstance(call, dict):
            continue
        response = call.get("response")
        response = response if isinstance(response, dict) else {}
        gateway = response.get("gateway")
        gateway = gateway if isinstance(gateway, dict) else {}
        rows.append(
            (
                call.get("sequence", index),
                call.get("service_name"),
                call.get("method_name"),
                call.get("result_class"),
                gateway.get("request_id"),
                response.get("elapsed_ms"),
            )
        )
    return _report_table(
        ("序号", "接口名", "method", "状态", "request_id", "耗时(ms)"), rows
    )


def _report_uploads(snapshot: dict) -> list[str]:
    """输出 analyzer 已确定关联的上传资产，不重新猜测关联关系。"""
    rows = []
    assets = snapshot.get("input_assets")
    assets = assets if isinstance(assets, list) else []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        rows.append(
            (
                asset.get("asset_id"),
                asset.get("purpose"),
                asset.get("upload_state"),
                asset.get("prepare_status"),
                asset.get("put_http_status"),
                asset.get("complete_status"),
                asset.get("used_by_task"),
                asset.get("object_path"),
            )
        )
    return _report_table(
        (
            "asset_id",
            "purpose",
            "upload_state",
            "Prepare",
            "PUT",
            "Complete",
            "used_by_task",
            "object_path",
        ),
        rows,
    )


def _report_lifecycle(snapshot: dict) -> list[str]:
    """输出完整轮询状态序列及 analyzer 聚合的终态事实。"""
    lifecycle = snapshot.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    samples = snapshot.get("status_samples")
    samples = samples if isinstance(samples, list) else []
    statuses = [
        sample.get("status")
        for sample in samples
        if isinstance(sample, dict)
    ]
    lines = [
        f"- task_id: `{_report_value(snapshot.get('task_id'))}`",
        f"- Create call: `{_report_value(snapshot.get('create_call_id'))}`",
        f"- Poll count: {_report_value(lifecycle.get('poll_count'))}",
        f"- Poll statuses: `{_report_value(statuses)}`",
        f"- Final status: `{_report_value(lifecycle.get('final_status'))}`",
        f"- Final phase: `{_report_value(lifecycle.get('final_phase'))}`",
        f"- Final progress: {_report_value(lifecycle.get('final_progress_percent'))}",
        f"- Terminal: {_report_value(lifecycle.get('terminal'))}",
        f"- Duration(ms): {_report_value(lifecycle.get('duration_ms'))}",
        f"- Result call: `{_report_value(snapshot.get('result_call_id'))}`",
    ]
    sample_rows = [
        (
            sample.get("call_id"),
            sample.get("timestamp"),
            sample.get("status"),
            sample.get("phase"),
            sample.get("progress_percent"),
            sample.get("retryable"),
            sample.get("error_code"),
            {
                "line_start": sample.get("line_start"),
                "line_end": sample.get("line_end"),
            },
        )
        for sample in samples
        if isinstance(sample, dict)
    ]
    lines.extend(["", "### Poll 状态样本", ""])
    lines.extend(
        _report_table(
            (
                "call_id",
                "timestamp",
                "status",
                "phase",
                "progress_percent",
                "retryable",
                "error_code",
                "日志行",
            ),
            sample_rows,
        )
    )
    return lines


def _report_result_summary(snapshot: dict) -> list[str]:
    """按稳定 key 顺序输出摘要，并按 analyzer 的 section 顺序输出块值。"""
    lines = [
        f"- task_id: `{_report_value(snapshot.get('task_id'))}`",
        f"- 任务类型: `{_report_value(snapshot.get('task_type'))}`",
        f"- Schema: `{_report_value(snapshot.get('schema_version'))}`",
        f"- Schema status: `{_report_value(snapshot.get('schema_status'))}`",
        "- Result payload present: "
        f"{_report_value(snapshot.get('result_payload_present'))}",
    ]
    summary = snapshot.get("result_summary")
    summary = summary if isinstance(summary, dict) else {}
    lines.extend(
        _report_table(
            ("摘要字段", "值"),
            [(key, summary[key]) for key in sorted(summary)],
        )
    )
    sections = snapshot.get("result_sections")
    sections = sections if isinstance(sections, list) else []
    section_rows = [
        (section.get("label"), section.get("path"), section.get("value"))
        for section in sections
        if isinstance(section, dict)
    ]
    lines.extend(["", "### Result Sections", ""])
    lines.extend(_report_table(("label", "path", "value"), section_rows))
    return lines


def _report_field_health(snapshot: dict) -> list[str]:
    """输出 Task 5 已计算的 Null/空值健康度，不重新解释业务语义。"""
    health = snapshot.get("field_health")
    health = health if isinstance(health, dict) else {}
    ordered_keys = (
        "total_field_count",
        "present_count",
        "null_count",
        "empty_string_count",
        "empty_array_count",
        "empty_object_count",
        "missing_count",
        "unknown_schema_field_count",
    )
    rows = [(key, health.get(key)) for key in ordered_keys if key in health]
    rows.extend(
        (key, health[key])
        for key in sorted(set(health) - set(ordered_keys))
    )
    return _report_table(("指标", "值"), rows)


def _report_result_fields(snapshot: dict) -> list[str]:
    """输出 Task 5 字段索引的固定七列，不执行 Schema 二次投影。"""
    fields = snapshot.get("result_fields")
    fields = fields if isinstance(fields, list) else []
    rows = [
        (
            field.get("path"),
            field.get("value_type"),
            field.get("presence"),
            field.get("value"),
            field.get("schema_known"),
            field.get("source"),
            field.get("value_truncated"),
        )
        for field in fields
        if isinstance(field, dict)
    ]
    return _report_table(
        (
            "path",
            "value_type",
            "presence",
            "value",
            "schema_known",
            "source",
            "value_truncated",
        ),
        rows,
    )


def _report_checks(checks: list[dict], outcome: str) -> list[str]:
    """只渲染指定 outcome，固定报告用章节本身表达结果类别。"""
    selected_checks = [
        check
        for check in checks
        if isinstance(check, dict) and check.get("outcome") == outcome
    ]
    if not selected_checks:
        return ["- 无"]
    lines = []
    for check in selected_checks:
        lines.extend(
            [
                f"### [{check.get('outcome')}] {check.get('rule_id')} — {check.get('title')}",
                "",
                f"- priority: `{_report_value(check.get('priority'))}`",
                f"- actual: `{_report_value(check.get('actual'))}`",
                f"- expected: `{_report_value(check.get('expected'))}`",
                f"- evidence: `{_report_value(check.get('evidence'))}`",
                "",
            ]
        )
    return lines


def _report_warnings(analysis: dict, snapshot: dict) -> list[str]:
    """汇总 parser 与 task warning，并按首次出现顺序去重。"""
    candidates = []
    for warning_group in (
        analysis.get("parse_warnings"),
        snapshot.get("warnings"),
    ):
        if isinstance(warning_group, list):
            candidates.extend(warning_group)
    rows = []
    seen = set()
    for warning in candidates:
        if not isinstance(warning, dict):
            continue
        identity = _report_value(warning)
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(
            (
                warning.get("code"),
                warning.get("message"),
                _warning_location(warning),
            )
        )
    return _report_table(("code", "message", "证据位置"), rows)


def render_dating_report(analysis_result: dict, checks: list[dict]) -> str:
    """由已脱敏结构化数据渲染固定 Markdown，不调用模型或推测原因。

    入口仍执行一次递归脱敏，保证调用方即使误传内部原值，报告也不会泄漏
    凭证、签名 URL、Base64 或超过长度上限的自由文本。
    """
    safe = redact_dating_response(
        {"analysis_result": analysis_result, "checks": checks}
    )
    analysis = safe.get("analysis_result")
    analysis = analysis if isinstance(analysis, dict) else {}
    safe_checks = safe.get("checks")
    safe_checks = safe_checks if isinstance(safe_checks, list) else []
    snapshot = analysis.get("task_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    sections = (
        ("## 总体结论", _report_overview(analysis, safe_checks)),
        ("## 任务与结果摘要", _report_result_summary(snapshot)),
        ("## 接口执行链路", _report_calls(analysis)),
        ("## 上传资源", _report_uploads(snapshot)),
        ("## 任务状态时间线", _report_lifecycle(snapshot)),
        ("## 最终结果字段", _report_result_fields(snapshot)),
        ("## Null 与空值", _report_field_health(snapshot)),
        ("## 已确认正常", _report_checks(safe_checks, "PASS")),
        ("## 已确认异常", _report_checks(safe_checks, "FAIL")),
        ("## 需要确认", _report_checks(safe_checks, "WARN")),
        (
            "## 日志不足",
            _report_checks(safe_checks, "UNKNOWN")
            + ["", "### 解析警告", ""]
            + _report_warnings(analysis, snapshot),
        ),
    )
    lines = ["# Dating 结构化接口日志分析", ""]
    for heading, content in sections:
        lines.extend([heading, ""])
        lines.extend(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_dating_checks(analysis: dict) -> list[dict]:
    """按固定顺序运行 24 条通用规则和 16 条 Schema 专属规则。"""
    checks = [rule(analysis) for rule in GENERIC_RULES]
    checks.extend(rule(analysis) for rule in TASK_RULES)
    checks.extend(rule(analysis) for rule in RESULT_RULES)
    checks.extend(rule(analysis) for rule in REPLY_RULES)
    checks.extend(rule(analysis) for rule in ANALYSIS_RULES)
    return checks


def compute_dating_verdict(checks: list[dict]) -> str:
    """按 FAIL、WARN、关键 UNKNOWN 的固定优先级计算总体结论。"""
    outcomes = {item["outcome"] for item in checks}
    if "FAIL" in outcomes:
        return "ISSUES_FOUND"
    if "WARN" in outcomes:
        return "WARNINGS_FOUND"
    if any(
        item["outcome"] == "UNKNOWN" and item["priority"] in {"P0", "P1"}
        for item in checks
    ):
        return "INCOMPLETE_LOG"
    return "NO_ISSUES"
