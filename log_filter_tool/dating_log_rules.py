"""Dating 结构化日志的确定性检查规则。

模块只消费 :func:`dating_log_analyzer.analyze_dating_log` 返回的字典，不重新
解析原始日志，也不访问 LLM、网络、数据库或对象存储。规则按固定注册顺序
执行，调用方可再用 :func:`compute_dating_verdict` 计算总体结论。
"""

from __future__ import annotations

import math


CHECK_OUTCOMES = {"PASS", "FAIL", "WARN", "UNKNOWN", "NA"}

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


def run_dating_checks(analysis: dict) -> list[dict]:
    """按固定顺序运行当前 24 条规则并返回结构化检查列表。"""
    checks = [rule(analysis) for rule in GENERIC_RULES]
    checks.extend(rule(analysis) for rule in TASK_RULES)
    checks.extend(rule(analysis) for rule in RESULT_RULES)
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
