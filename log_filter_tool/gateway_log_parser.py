"""通用接口日志解析原语与 Gateway/PUT 传输解析。

本模块只负责日志行规范化、JSON 边界扫描和 Gateway 信封分层，不包含任何
People/Dating 领域规则，也不得导入 Flask、app.py 或领域分析模块。这样后续
分析器可以共享稳定的传输层能力，同时避免 Web 入口与业务解析器之间形成循环依赖。
"""

from __future__ import annotations

import json
import re


PARSER_VERSION = "gateway-log-v1"
MAX_SCAN_LINES = 100000

# Flutter 控制台会在真实日志内容前附加运行器信息，只移除首个匹配前缀。
CONSOLE_PREFIX_PATTERN = re.compile(r"^.*?\bflutter:\s?")
RE_LOGGER_PREFIX = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+)\s*\|\s*(\w+)\s*\|\s*([\w.]+)\s*\|\s*"
)
RE_FLUTTER_TIMESTAMP = re.compile(r"\t(\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{4})\t")

# Marker 必须与真实夹具逐字一致；PUT 使用“上传响应”，没有“数据”二字。
RE_GATEWAY_REQUEST = re.compile(r"^Gateway 请求数据:\s*$")
RE_GATEWAY_RESPONSE = re.compile(
    r"^Gateway 响应数据:\s*HTTP\s+(\d{3})\s+elapsed_ms=([\d.]+)\s*$"
)
RE_PUT_REQUEST = re.compile(r"^PUT 上传请求数据:\s*$")
RE_PUT_RESPONSE = re.compile(
    r"^PUT 上传响应:\s*HTTP\s+(\d{3})\s+elapsed_ms=([\d.]+)\s*$"
)
RE_FLOW_START = re.compile(r"^开始 Flow 步骤:.*?step=([^\s]+)\s+\((\d+)/(\d+)\)")
RE_FLOW_END = re.compile(r"^完成 Flow 步骤:\s*step=([^\s]+)")
RE_FLOW_SKIP = re.compile(r"^因条件跳过 Flow 步骤:\s*step=([^\s]+)")
_INTERFACE_MARKERS = (
    RE_GATEWAY_REQUEST,
    RE_GATEWAY_RESPONSE,
    RE_PUT_REQUEST,
    RE_PUT_RESPONSE,
    RE_FLOW_START,
    RE_FLOW_END,
    RE_FLOW_SKIP,
)


def clean_log_line(line: str) -> str:
    """清除 Flutter 控制台前缀和日志框线，并保持 app 的历史清洗行为。

    参数:
        line: 单行原始日志。调用方应传入字符串，与原 ``app.clean_log_line``
            的输入约束一致。

    返回:
        清洗后的日志内容。框线起止行返回空字符串；内容行仅移除框线字符，
        不额外裁剪尾部空白，避免改变既有过滤与导出结果。
    """
    line = CONSOLE_PREFIX_PATTERN.sub("", line, count=1)
    stripped_line = line.lstrip()
    if stripped_line.startswith(("┌", "└")):
        return ""
    if line.startswith("│ "):
        return line[2:]
    if line.startswith("│"):
        return line[1:]
    return line.replace("│", "")


def normalize_log_lines(log_text):
    """规范化日志行，同时保留原始行号、文本和可用时间戳。

    返回列表中的每个普通字典均包含 ``line_no``、``raw``、``content``、
    ``json_text`` 和 ``timestamp``。这里只清理已知控制台/Logger 前缀，
    不删除原始行，确保上层分析器继续报告准确的输入行号。
    """
    lines = []
    for index, raw in enumerate(log_text.splitlines()):
        cleaned = clean_log_line(raw)
        timestamp = None
        logger_match = RE_LOGGER_PREFIX.match(cleaned)
        if logger_match:
            timestamp = logger_match.group(1).replace(",", ".")
            content = cleaned[logger_match.end():]
        else:
            content = cleaned
            flutter_match = RE_FLUTTER_TIMESTAMP.search(raw)
            if flutter_match:
                timestamp = flutter_match.group(1)
        lines.append(
            {
                "line_no": index + 1,
                "raw": raw,
                "content": content,
                "json_text": content,
                "timestamp": timestamp,
            }
        )
    return lines


def scan_json_block(lines, start_idx):
    """从指定下标扫描首个完整 JSON 对象或数组。

    返回 ``(value, end_idx, start_line, end_line, error)``。扫描器区分字符串
    内外的括号并处理反斜杠转义；JSON 开始前若出现非空白内容则立即报错，
    防止把后续无关日志误识别为当前 marker 的 payload。
    """
    depth = 0
    in_string = False
    escaped = False
    started = False
    buffer = []
    start_line = None
    limit = min(len(lines), start_idx + MAX_SCAN_LINES)
    for idx in range(start_idx, limit):
        text = lines[idx]["json_text"]
        for ch in text:
            if not started:
                if ch in "{[":
                    started = True
                    start_line = lines[idx]["line_no"]
                    depth = 1
                    buffer.append(ch)
                elif not ch.isspace():
                    return None, idx, None, None, "marker 后未找到 JSON 起始"
                continue
            buffer.append(ch)
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
                    raw_text = "".join(buffer)
                    try:
                        return json.loads(raw_text), idx, start_line, lines[idx]["line_no"], None
                    except ValueError as exc:
                        return None, idx, start_line, lines[idx]["line_no"], str(exc)
        if started:
            buffer.append("\n")
    if started:
        return None, limit - 1, start_line, None, "JSON 未闭合（可能被截断）"
    return None, limit - 1, None, None, "未找到 JSON"


def scan_named_json_block(lines, start_idx, assignment_name):
    """查找精确 ``assignment_name=`` 行并扫描其后的 JSON。

    搜索从 ``start_idx`` 开始，只有行内容以完全一致的赋值前缀开头才会
    命中；例如查找 ``body`` 时不会误取 ``headers=``、``xbody=`` 或
    ``body =``。为保留输入行号且不修改调用方数据，只复制命中行后再复用
    通用括号扫描器。

    返回值与 :func:`scan_json_block` 相同，其中 ``end_idx`` 仍是原始
    ``lines`` 列表中的下标。
    """
    assignment_prefix = f"{assignment_name}="
    limit = min(len(lines), start_idx + MAX_SCAN_LINES)
    for idx in range(start_idx, limit):
        text = lines[idx]["json_text"]
        if not text.startswith(assignment_prefix):
            continue

        scoped_lines = lines[idx:limit]
        scoped_lines[0] = dict(scoped_lines[0])
        scoped_lines[0]["json_text"] = text[len(assignment_prefix):]
        value, relative_end_idx, start_line, end_line, error = scan_json_block(scoped_lines, 0)
        return value, idx + relative_end_idx, start_line, end_line, error

    return None, limit - 1, None, None, f"未找到 {assignment_prefix} JSON"


def unwrap_gateway_envelope(payload: object) -> dict:
    """将 Gateway payload 投影为网关、请求、响应和业务数据四层。

    参数:
        payload: JSON 解码后的任意对象。

    返回:
        新建的普通字典。函数不会修改 ``payload``；非字典值作为 ``data``
        原样返回，缺失或类型错误的 requests/responses 统一为空列表。
    """
    if not isinstance(payload, dict):
        return {"gateway": None, "requests": [], "responses": [], "data": payload}
    return {
        "gateway": {
            "code": payload.get("code"),
            "message": payload.get("message"),
            "request_id": payload.get("request_id"),
            "trace_id": payload.get("trace_id"),
        },
        "requests": payload.get("requests") if isinstance(payload.get("requests"), list) else [],
        "responses": payload.get("responses") if isinstance(payload.get("responses"), list) else [],
        "data": payload.get("data") if "data" in payload else payload,
    }


def classify_result(call: dict) -> str:
    """按 parse/response/HTTP/Gateway/业务的固定优先级分类调用结果。"""
    if call.get("parse_status") != "PARSED":
        return "parse_error"
    response = call.get("response")
    if response is None:
        return "no_response"
    http_status = response.get("http_status")
    if http_status is not None and not 200 <= http_status <= 299:
        return "http_error"
    gateway = response.get("gateway") or {}
    if gateway.get("code") not in (None, 0):
        return "gateway_error"
    sub_response = response.get("sub_response") or {}
    if sub_response.get("success") is False or sub_response.get("code") not in (None, 0):
        return "business_error"
    if http_status is not None and 200 <= http_status <= 299:
        return "success"
    return "unknown"


def _next_marker(lines: list[dict], start_idx: int) -> int:
    """返回下一传输/Flow marker 下标，用作损坏 JSON 的硬边界。"""
    for idx in range(start_idx, len(lines)):
        if any(pattern.match(lines[idx]["content"]) for pattern in _INTERFACE_MARKERS):
            return idx
    return len(lines)


def _scan_segment(
    lines: list[dict],
    start_idx: int,
    assignment_name: str | None = None,
) -> tuple[object, int, int | None, str | None]:
    """在下一 marker 前扫描 JSON，避免一处截断吞掉后续完整交换。"""
    boundary = _next_marker(lines, start_idx)
    scoped = lines[start_idx:boundary]
    if not scoped:
        label = f"{assignment_name}= " if assignment_name else ""
        return None, start_idx - 1, None, f"未找到 {label}JSON"
    if assignment_name is None:
        value, relative_end, _start_line, end_line, error = scan_json_block(scoped, 0)
    else:
        value, relative_end, _start_line, end_line, error = scan_named_json_block(
            scoped, 0, assignment_name
        )
    end_idx = start_idx + max(relative_end, 0)
    if end_line is None and 0 <= end_idx < len(lines):
        # 截断块没有自然结束行，记录扫描实际抵达的最后一行作为 block 证据。
        end_line = lines[end_idx]["line_no"]
    return value, end_idx, end_line, error


def _warning(
    warnings: list[dict],
    code: str,
    message: str,
    *,
    line_start: int | None = None,
    line_end: int | None = None,
    **context,
) -> dict:
    """追加稳定 warning，并返回同一对象供具体 InterfaceCall 引用。"""
    result = {"code": code, "message": message}
    if line_start is not None:
        result["line_start"] = line_start
    if line_end is not None:
        result["line_end"] = line_end
    result.update({key: value for key, value in context.items() if value is not None})
    warnings.append(result)
    return result


def _parse_request(
    lines: list[dict],
    marker_idx: int,
    transport: str,
    warnings: list[dict],
    exchange_id: str | None = None,
) -> tuple[dict, int]:
    """解析 Gateway 或 PUT 请求，并保留 marker 到 JSON 结束的原始范围。"""
    value, end_idx, end_line, error = _scan_segment(lines, marker_idx + 1)
    marker = lines[marker_idx]
    line_start = marker["line_no"]
    line_end = end_line or line_start
    local_warnings = []
    parse_error = error is not None or not isinstance(value, dict)
    prefix = "GATEWAY" if transport == "gateway" else "PUT"
    if error is not None:
        local_warnings.append(
            _warning(
                warnings,
                f"{prefix}_REQUEST_JSON_ERROR",
                f"请求 JSON 解析失败: {error}",
                line_start=line_start,
                line_end=line_end,
                gateway_exchange_id=exchange_id,
                transport=transport,
            )
        )
    elif not isinstance(value, dict):
        local_warnings.append(
            _warning(
                warnings,
                f"{prefix}_REQUEST_TYPE_ERROR",
                "请求 JSON 顶层必须是对象",
                line_start=line_start,
                line_end=line_end,
                gateway_exchange_id=exchange_id,
                transport=transport,
            )
        )

    request_object = value if isinstance(value, dict) else {}
    if transport == "gateway":
        payload_value = request_object.get("payload")
        payload = (
            payload_value
            if isinstance(payload_value, dict)
            else request_object if "requests" in request_object else {}
        )
        if payload_value is not None and not isinstance(payload_value, dict):
            parse_error = True
            local_warnings.append(
                _warning(
                    warnings,
                    "GATEWAY_PAYLOAD_TYPE_ERROR",
                    "Gateway payload 必须是对象",
                    line_start=line_start,
                    line_end=line_end,
                    gateway_exchange_id=exchange_id,
                )
            )
        items = payload.get("requests")
        if items is None:
            items = []
        elif not isinstance(items, list):
            parse_error = True
            items = []
            local_warnings.append(
                _warning(
                    warnings,
                    "GATEWAY_REQUESTS_TYPE_ERROR",
                    "Gateway payload.requests 必须是数组",
                    line_start=line_start,
                    line_end=line_end,
                    gateway_exchange_id=exchange_id,
                )
            )
        comm = payload.get("comm") if isinstance(payload.get("comm"), dict) else {}
        client_request_id = comm.get("client_request_id")
        params = None
    else:
        items = []
        client_request_id = None
        params = {
            key: item
            for key, item in request_object.items()
            if key not in {"url", "headers"}
        }

    return {
        "transport": transport,
        "gateway_exchange_id": exchange_id,
        "timestamp": marker["timestamp"],
        "line_start": line_start,
        "line_end": line_end,
        "url": request_object.get("url"),
        "headers": request_object.get("headers"),
        "client_request_id": client_request_id,
        "params": params,
        "items": items,
        "parse_error": parse_error,
        "warnings": local_warnings,
    }, max(marker_idx, end_idx)


def _parse_response(
    lines: list[dict],
    marker_idx: int,
    match: re.Match,
    transport: str,
    warnings: list[dict],
    exchange_id: str | None = None,
) -> tuple[dict, int]:
    """解析 HTTP 元数据和响应 JSON；Gateway 与 PUT 共享 headers 处理。"""
    headers, headers_end_idx, headers_end_line, headers_error = _scan_segment(
        lines, marker_idx + 1, "headers"
    )
    marker = lines[marker_idx]
    line_start = marker["line_no"]
    line_end = headers_end_line or line_start
    local_warnings = []
    parse_error = headers_error is not None or not isinstance(headers, dict)
    prefix = "GATEWAY" if transport == "gateway" else "PUT"
    if headers_error is not None:
        local_warnings.append(
            _warning(
                warnings,
                f"{prefix}_RESPONSE_HEADERS_JSON_ERROR",
                f"响应 headers 解析失败: {headers_error}",
                line_start=line_start,
                line_end=line_end,
                gateway_exchange_id=exchange_id,
                transport=transport,
            )
        )
    elif not isinstance(headers, dict):
        local_warnings.append(
            _warning(
                warnings,
                f"{prefix}_RESPONSE_HEADERS_TYPE_ERROR",
                "响应 headers 必须是对象",
                line_start=line_start,
                line_end=line_end,
                gateway_exchange_id=exchange_id,
                transport=transport,
            )
        )

    body_end_idx = marker_idx
    if transport == "gateway":
        body, body_end_idx, body_end_line, body_error = _scan_segment(
            lines, marker_idx + 1, "body"
        )
        line_end = max(line_end, body_end_line or line_start)
        if body_error is not None or not isinstance(body, dict):
            parse_error = True
            local_warnings.append(
                _warning(
                    warnings,
                    "GATEWAY_RESPONSE_BODY_JSON_ERROR",
                    (
                        f"Gateway body 解析失败: {body_error}"
                        if body_error is not None
                        else "Gateway body 必须是对象"
                    ),
                    line_start=line_start,
                    line_end=line_end,
                    gateway_exchange_id=exchange_id,
                )
            )
        envelope = unwrap_gateway_envelope(body)
        raw_responses = body.get("responses") if isinstance(body, dict) else None
        if raw_responses is not None and not isinstance(raw_responses, list):
            parse_error = True
            local_warnings.append(
                _warning(
                    warnings,
                    "GATEWAY_RESPONSES_TYPE_ERROR",
                    "Gateway body.responses 必须是数组",
                    line_start=line_start,
                    line_end=line_end,
                    gateway_exchange_id=exchange_id,
                )
            )
        gateway = envelope["gateway"]
        items = envelope["responses"]
    else:
        gateway = None
        items = []

    return {
        "transport": transport,
        "gateway_exchange_id": exchange_id,
        "timestamp": marker["timestamp"],
        "line_start": line_start,
        "line_end": line_end,
        "http_status": int(match.group(1)),
        "elapsed_ms": float(match.group(2)),
        "headers": headers if isinstance(headers, dict) else None,
        "gateway": gateway,
        "items": items,
        "parse_error": parse_error,
        "warnings": local_warnings,
    }, max(marker_idx, headers_end_idx, body_end_idx)


def _item_id(item: object) -> object | None:
    """返回可哈希的非空子项 ID；其他值只能参与位置兜底。"""
    if not isinstance(item, dict) or item.get("id") in (None, ""):
        return None
    item_id = item["id"]
    try:
        hash(item_id)
    except TypeError:
        return None
    return item_id


def _request_view(record: dict | None, item: object = None) -> dict | None:
    """将传输请求投影为统一 request 字段集合。"""
    if record is None:
        return None
    params = record["params"]
    if record["transport"] == "gateway":
        params = item.get("params") if isinstance(item, dict) else item
    return {
        "timestamp": record["timestamp"],
        "line_start": record["line_start"],
        "line_end": record["line_end"],
        "client_request_id": record["client_request_id"],
        "url": record["url"],
        "headers": record["headers"],
        "params": params,
    }


def _response_view(record: dict | None, item: object = None) -> dict | None:
    """保持 HTTP、Gateway、sub_response 三层独立，业务 data 单独输出。"""
    if record is None:
        return None
    if record["transport"] == "gateway" and isinstance(item, dict):
        sub_response = {
            "id": item.get("id"),
            "success": item.get("success"),
            "code": item.get("code"),
            "message": item.get("message"),
        }
        data = item.get("data")
    else:
        sub_response = None
        data = item if record["transport"] == "gateway" else None
    return {
        "timestamp": record["timestamp"],
        "line_start": record["line_start"],
        "line_end": record["line_end"],
        "http_status": record["http_status"],
        "elapsed_ms": record["elapsed_ms"],
        "headers": record["headers"],
        "gateway": record["gateway"],
        "sub_response": sub_response,
        "data": data,
    }


def _collect_call(
    calls: list[dict],
    *,
    exchange_id: str | None,
    transport: str,
    service_name: object,
    method_name: object,
    request: dict | None,
    response: dict | None,
    parse_error: bool,
    call_warnings: list[dict],
    order_line: int,
) -> None:
    """暂存无 ID 调用；扫描结束后按原始行顺序统一编号。"""
    calls.append(
        {
            "gateway_exchange_id": exchange_id,
            "transport": transport,
            "service_name": service_name,
            "method_name": method_name,
            "request": request,
            "response": response,
            "parse_status": "PARSE_ERROR" if parse_error else "PARSED",
            "warnings": call_warnings,
            "_order": (order_line, len(calls)),
        }
    )


def _emit_gateway_exchange(
    request_record: dict | None,
    response_record: dict | None,
    calls: list[dict],
    warnings: list[dict],
) -> None:
    """按 ID 优先展开 Gateway 子调用，重复 ID 按出现顺序稳定配对。

    使用 ID 到位置列表而非字典单值，避免重复 ID 覆盖证据。ID 配对完成后，
    仅对双方都无 ID 的剩余项做位置兜底；有明确但错误 ID 的项保持 unmatched。
    """
    requests = request_record["items"] if request_record else []
    responses = response_record["items"] if response_record else []
    exchange_id = (
        request_record["gateway_exchange_id"]
        if request_record
        else response_record["gateway_exchange_id"]
    )
    line_start = request_record["line_start"] if request_record else response_record["line_start"]
    line_end = response_record["line_end"] if response_record else request_record["line_end"]
    base_warnings = list(request_record["warnings"] if request_record else [])
    if response_record:
        base_warnings.extend(response_record["warnings"])

    request_groups = {}
    response_groups = {}
    id_order = []
    for index, item in enumerate(requests):
        item_id = _item_id(item)
        if item_id is not None:
            request_groups.setdefault(item_id, []).append(index)
            if item_id not in id_order:
                id_order.append(item_id)
    for index, item in enumerate(responses):
        item_id = _item_id(item)
        if item_id is not None:
            response_groups.setdefault(item_id, []).append(index)
            if item_id not in id_order:
                id_order.append(item_id)

    duplicate_warnings = {}
    for item_id in id_order:
        request_indexes = request_groups.get(item_id, [])
        response_indexes = response_groups.get(item_id, [])
        if len(request_indexes) > 1 or len(response_indexes) > 1:
            duplicate_warnings[item_id] = _warning(
                warnings,
                "AMBIGUOUS_PAIRING",
                "Gateway 子项存在重复 ID，按出现顺序稳定配对",
                line_start=line_start,
                line_end=line_end,
                gateway_exchange_id=exchange_id,
                item_id=item_id,
                request_indexes=request_indexes,
                response_indexes=response_indexes,
            )

    assignments = {}
    used_responses = set()
    for request_index, request_item in enumerate(requests):
        request_id = _item_id(request_item)
        if request_id is None:
            continue
        for response_index in response_groups.get(request_id, []):
            if response_index not in used_responses:
                assignments[request_index] = response_index
                used_responses.add(response_index)
                break

    positional_warnings = {}
    idless_requests = [
        index
        for index, item in enumerate(requests)
        if index not in assignments and _item_id(item) is None
    ]
    idless_responses = [
        index
        for index, item in enumerate(responses)
        if index not in used_responses and _item_id(item) is None
    ]
    for request_index, response_index in zip(idless_requests, idless_responses):
        assignments[request_index] = response_index
        used_responses.add(response_index)
        positional_warnings[request_index] = _warning(
            warnings,
            "POSITIONAL_PAIRING_FALLBACK",
            "Gateway 子项缺少 ID，按未配对项相对位置兜底",
            line_start=line_start,
            line_end=line_end,
            gateway_exchange_id=exchange_id,
            request_index=request_index,
            response_index=response_index,
        )

    for request_index, request_item in enumerate(requests):
        response_index = assignments.get(request_index)
        response_item = responses[response_index] if response_index is not None else None
        call_warnings = list(base_warnings)
        request_id = _item_id(request_item)
        response_id = _item_id(response_item)
        duplicate = duplicate_warnings.get(request_id) or duplicate_warnings.get(response_id)
        if duplicate:
            call_warnings.append(duplicate)
        if request_index in positional_warnings:
            call_warnings.append(positional_warnings[request_index])
        if not isinstance(request_item, dict):
            call_warnings.append(
                _warning(
                    warnings,
                    "GATEWAY_SUBREQUEST_TYPE_ERROR",
                    "Gateway 子请求必须是对象",
                    line_start=request_record["line_start"],
                    line_end=request_record["line_end"],
                    gateway_exchange_id=exchange_id,
                    request_index=request_index,
                )
            )
        if response_index is not None and not isinstance(response_item, dict):
            call_warnings.append(
                _warning(
                    warnings,
                    "GATEWAY_SUBRESPONSE_TYPE_ERROR",
                    "Gateway 子响应必须是对象",
                    line_start=response_record["line_start"],
                    line_end=response_record["line_end"],
                    gateway_exchange_id=exchange_id,
                    response_index=response_index,
                )
            )
        if response_index is None:
            call_warnings.append(
                _warning(
                    warnings,
                    "UNMATCHED_REQUEST",
                    "Gateway 逻辑子请求没有匹配的子响应",
                    line_start=request_record["line_start"],
                    line_end=request_record["line_end"],
                    gateway_exchange_id=exchange_id,
                    request_index=request_index,
                    item_id=request_id,
                )
            )

        request_dict = request_item if isinstance(request_item, dict) else {}
        _collect_call(
            calls,
            exchange_id=exchange_id,
            transport="gateway",
            service_name=request_dict.get("service_name"),
            method_name=request_dict.get("method_name"),
            request=_request_view(request_record, request_item),
            response=_response_view(response_record, response_item),
            parse_error=(
                request_record["parse_error"]
                or bool(response_record and response_record["parse_error"])
                or not isinstance(request_item, dict)
                or (response_index is not None and not isinstance(response_item, dict))
            ),
            call_warnings=call_warnings,
            order_line=request_record["line_start"],
        )

    for response_index, response_item in enumerate(responses):
        if response_index in used_responses:
            continue
        response_id = _item_id(response_item)
        call_warnings = list(base_warnings)
        duplicate = duplicate_warnings.get(response_id)
        if duplicate:
            call_warnings.append(duplicate)
        call_warnings.append(
            _warning(
                warnings,
                "UNMATCHED_RESPONSE",
                "Gateway 逻辑子响应没有匹配的子请求",
                line_start=response_record["line_start"],
                line_end=response_record["line_end"],
                gateway_exchange_id=exchange_id,
                response_index=response_index,
                item_id=response_id,
            )
        )
        _collect_call(
            calls,
            exchange_id=exchange_id,
            transport="gateway",
            service_name=None,
            method_name=None,
            request=None,
            response=_response_view(response_record, response_item),
            parse_error=response_record["parse_error"] or not isinstance(response_item, dict),
            call_warnings=call_warnings,
            order_line=response_record["line_start"],
        )

    # 损坏 JSON 可能无法恢复任何子项；保留一条 unknown 调用承载 HTTP/行范围。
    if not requests and not responses and (
        bool(request_record and request_record["parse_error"])
        or bool(response_record and response_record["parse_error"])
        or request_record is None
    ):
        call_warnings = list(base_warnings)
        if request_record is None and response_record is not None:
            call_warnings.append(
                _warning(
                    warnings,
                    "UNMATCHED_RESPONSE",
                    "Gateway 外层响应前没有可配对请求",
                    line_start=response_record["line_start"],
                    line_end=response_record["line_end"],
                    gateway_exchange_id=exchange_id,
                )
            )
        _collect_call(
            calls,
            exchange_id=exchange_id,
            transport="gateway",
            service_name=None,
            method_name=None,
            request=_request_view(request_record),
            response=_response_view(response_record),
            parse_error=True,
            call_warnings=call_warnings,
            order_line=line_start,
        )


def _emit_put_exchange(
    request_record: dict | None,
    response_record: dict | None,
    calls: list[dict],
    warnings: list[dict],
) -> None:
    """将 PUT 响应与最早未关闭请求配对；缺失一侧仍保留调用证据。"""
    call_warnings = list(request_record["warnings"] if request_record else [])
    if response_record:
        call_warnings.extend(response_record["warnings"])
    if request_record and not response_record:
        call_warnings.append(
            _warning(
                warnings,
                "UNMATCHED_REQUEST",
                "PUT 请求没有匹配响应",
                line_start=request_record["line_start"],
                line_end=request_record["line_end"],
                transport="object_storage_put",
            )
        )
    elif response_record and not request_record:
        call_warnings.append(
            _warning(
                warnings,
                "UNMATCHED_RESPONSE",
                "PUT 响应前没有可配对请求",
                line_start=response_record["line_start"],
                line_end=response_record["line_end"],
                transport="object_storage_put",
            )
        )
    order_line = request_record["line_start"] if request_record else response_record["line_start"]
    _collect_call(
        calls,
        exchange_id=None,
        transport="object_storage_put",
        service_name="object_storage",
        method_name="PUT",
        request=_request_view(request_record),
        response=_response_view(response_record),
        parse_error=(
            bool(request_record and request_record["parse_error"])
            or bool(response_record and response_record["parse_error"])
        ),
        call_warnings=call_warnings,
        order_line=order_line,
    )


def _finalize_calls(calls: list[dict]) -> list[dict]:
    """按证据行稳定排序，从 ``call_0001`` 生成确定性业务 ID。"""
    result = []
    for sequence, call in enumerate(sorted(calls, key=lambda item: item["_order"]), start=1):
        finalized = {
            "call_id": f"call_{sequence:04d}",
            "gateway_exchange_id": call["gateway_exchange_id"],
            "sequence": sequence,
            "transport": call["transport"],
            "service_name": call["service_name"],
            "method_name": call["method_name"],
            "request": call["request"],
            "response": call["response"],
            "result_class": None,
            "parse_status": call["parse_status"],
            "warnings": call["warnings"],
        }
        finalized["result_class"] = classify_result(finalized)
        result.append(finalized)
    return result


def parse_interface_log(log_text: str) -> dict:
    """解析 Gateway、PUT 和 Flow，返回 calls/flow_steps/parse_warnings。

    Gateway/PUT 外层按最早未关闭请求 FIFO 配对；每次受限 JSON 扫描后将
    ``idx`` 跳过已消费区间。EOF 中仍未关闭的请求转换为 no_response 调用。
    """
    lines = normalize_log_lines(log_text)
    pending_gateway = []
    pending_put = []
    calls = []
    flow_steps = []
    warnings = []
    gateway_sequence = 0
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        content = line["content"]
        flow_match = RE_FLOW_START.match(content)
        if flow_match:
            flow_steps.append(
                {
                    "step": flow_match.group(1),
                    "event": "start",
                    "current": int(flow_match.group(2)),
                    "total": int(flow_match.group(3)),
                    "timestamp": line["timestamp"],
                    "line": line["line_no"],
                }
            )
            idx += 1
            continue
        flow_match = RE_FLOW_END.match(content) or RE_FLOW_SKIP.match(content)
        if flow_match:
            flow_steps.append(
                {
                    "step": flow_match.group(1),
                    "event": "complete" if RE_FLOW_END.match(content) else "skip",
                    "current": None,
                    "total": None,
                    "timestamp": line["timestamp"],
                    "line": line["line_no"],
                }
            )
            idx += 1
            continue

        if RE_GATEWAY_REQUEST.match(content):
            gateway_sequence += 1
            exchange_id = f"gateway_{gateway_sequence:04d}"
            request, end_idx = _parse_request(
                lines, idx, "gateway", warnings, exchange_id
            )
            pending_gateway.append(request)
            idx = max(idx + 1, end_idx + 1)
            continue
        response_match = RE_GATEWAY_RESPONSE.match(content)
        if response_match:
            if pending_gateway:
                request = pending_gateway.pop(0)
                exchange_id = request["gateway_exchange_id"]
            else:
                gateway_sequence += 1
                exchange_id = f"gateway_{gateway_sequence:04d}"
                request = None
            response, end_idx = _parse_response(
                lines, idx, response_match, "gateway", warnings, exchange_id
            )
            _emit_gateway_exchange(request, response, calls, warnings)
            idx = max(idx + 1, end_idx + 1)
            continue

        if RE_PUT_REQUEST.match(content):
            request, end_idx = _parse_request(lines, idx, "object_storage_put", warnings)
            pending_put.append(request)
            idx = max(idx + 1, end_idx + 1)
            continue
        response_match = RE_PUT_RESPONSE.match(content)
        if response_match:
            request = pending_put.pop(0) if pending_put else None
            response, end_idx = _parse_response(
                lines, idx, response_match, "object_storage_put", warnings
            )
            _emit_put_exchange(request, response, calls, warnings)
            idx = max(idx + 1, end_idx + 1)
            continue
        idx += 1

    # 延迟到 EOF 创建的 no_response 调用会在 finalizer 中按请求原始行归位。
    for request in pending_gateway:
        _emit_gateway_exchange(request, None, calls, warnings)
    for request in pending_put:
        _emit_put_exchange(request, None, calls, warnings)
    return {
        "parser_version": PARSER_VERSION,
        "calls": _finalize_calls(calls),
        "flow_steps": flow_steps,
        "parse_warnings": warnings,
    }
