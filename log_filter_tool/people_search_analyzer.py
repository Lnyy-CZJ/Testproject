"""People Insight 检索日志结构化解析与任务快照（开发设计 §6~§7，阶段 1）。

职责：
- 识别 Gateway/Flutter 与 QueryChainLogger 两类日志 marker。
- 用括号平衡扫描器提取跨行 JSON。
- 解包 Gateway 信封（兼容裸 data 与真实 Gateway 信封两种响应体）。
- 对无 marker 的独立 JSON 做受限兜底识别（debug / cost_summary）。
- 单任务选择、终态选择和 agent_tool_calls 时间线排序。
- 输出统一任务快照和 coverage，不调用 AI。

输入允许由同一 task 的主流程日志、单独复制的 GetSearchTaskDebug 响应和
GetProviderCostSummary 响应拼接组成。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app import clean_log_line

ANALYZER_VERSION = "people-search-v1"
RULESET_VERSION = "2026-08-13"

# 只识别以下 People Insight 相关接口（设计 §6.2）。
SUPPORTED_METHODS = (
    "CreateIntentTask",
    "RefineTask",
    "StartTask",
    "GetTask",
    "ListTaskCandidates",
    "GetTaskCandidateDetail",
    "ListTaskPublicSources",
    "GetSearchTaskDebug",
    "GetProviderCostSummary",
)

TERMINAL_STATUSES = ("SUCCEEDED", "PARTIAL_SUCCEEDED", "NO_RESULT", "FAILED")

# 无终态时最后一条 GetTask 的兜底状态标记（设计 §7.2）。
TASK_NOT_TERMINAL = "TASK_NOT_TERMINAL"

MULTIPLE_TASKS_FOUND = "MULTIPLE_TASKS_FOUND"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
UNSUPPORTED_LOG = "UNSUPPORTED_LOG"

# Gateway/Flutter 格式 marker。
RE_GW_ARROW = re.compile(
    r"^\[HTTP\] (-->|<--)(?:\s+(\d{3}))?\s+POST\s+\S+\s+service=\S+\s+method=(\w+)"
)
RE_GW_REQUEST = re.compile(r"^\[HTTP\] request:\s*$")
RE_GW_RESPONSE = re.compile(r"^\[HTTP\] response:\s*$")

# QueryChainLogger 格式 marker。请求 marker 允许带 attempt=N 后缀；
# 响应 marker 允许 HTTP - / elapsed_ms=-（如 QueryEnd）。
RE_QCL_EVENT = re.compile(r"^(\w+) 事件:\s*$")
RE_QCL_REQUEST = re.compile(r"^(\w+) 脱敏请求数据:(?:\s*attempt=(\d+))?\s*$")
RE_QCL_RESPONSE = re.compile(r"^(\w+) 响应数据:\s*HTTP\s+(\d+|-)\s+elapsed_ms=(\d+|-)\s*$")

# QueryChainLogger 行前缀：`2026-08-11 12:46:07,429 | INFO | search_tool.QueryChainLogger | `。
RE_LOGGER_PREFIX = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+)\s*\|\s*(\w+)\s*\|\s*([\w.]+)\s*\|\s*"
)

# Flutter 行前缀中的时间戳：`默认\t10:01:00.012345+0800\tRunner\tflutter: ...`。
RE_FLUTTER_TIMESTAMP = re.compile(r"\t(\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{4})\t")

# 括号平衡扫描的安全上限，防止异常日志导致长时间扫描。
MAX_SCAN_LINES = 100000


def normalize_log_lines(log_text):
    """行规范化（设计 §6.1）：保留原始行号，只做格式清理。

    每行输出：
    - line_no: 原始行号（从 1 开始）
    - raw: 原始行
    - content: 去除 Flutter 前缀和 QueryChainLogger 行前缀后的行，用于 marker 识别
    - json_text: 用于 JSON 拼接的行文本
    - timestamp: 行前缀中提取的时间戳（无则 None）
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
    """从 start_idx 行开始查找第一个 `{`/`[` 并做括号平衡扫描（设计 §6.3）。

    返回 (value, end_idx, start_line, end_line, error)：
    - 成功：value 为解析结果，end_idx 为 JSON 结束行下标，error 为 None。
    - 失败：value 为 None，error 描述原因；end_idx 为已消费到的行下标。
    marker 之后只允许出现空白字符，直到 JSON 开始，避免把后续日志误当 payload。
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


def _new_record(method, direction, marker_format, marker_line_no, timestamp):
    return {
        "method": method,
        "direction": direction,
        "http_status": None,
        "timestamp": timestamp,
        "elapsed_ms": None,
        "request_id": None,
        "trace_id": None,
        "payload": None,
        "data": None,
        "gateway": None,
        "attempt": None,
        "start_line": marker_line_no,
        "end_line": marker_line_no,
        "parse_status": "PARSE_ERROR",
        "marker_format": marker_format,
        "task_ids": [],
    }


def unwrap_gateway_payload(record):
    """Gateway 解包（设计 §6.5）。

    - 保留外层 code/message/request_id/trace_id。
    - 遍历 responses[]，分别保存子请求 success/code/message/data。
    - HTTP 200 但子请求失败时，业务结果按子请求判断（子请求信息保存在 gateway 中）。
    - 兼容裸 data 响应体（无信封）与 Gateway 请求体（comm + requests）。
    """
    payload = record["payload"]
    if not isinstance(payload, dict):
        record["data"] = payload
        return

    if isinstance(payload.get("request_id"), str):
        record["request_id"] = payload["request_id"]
    if isinstance(payload.get("trace_id"), str):
        record["trace_id"] = payload["trace_id"]

    responses = payload.get("responses")
    if isinstance(responses, list):
        sub_requests = []
        datas = []
        for sub in responses:
            if not isinstance(sub, dict):
                continue
            sub_requests.append(
                {
                    "id": sub.get("id"),
                    "success": sub.get("success"),
                    "code": sub.get("code"),
                    "message": sub.get("message"),
                }
            )
            datas.append(sub.get("data"))
        record["gateway"] = {
            "code": payload.get("code"),
            "message": payload.get("message"),
            "sub_requests": sub_requests,
        }
        record["data"] = datas[0] if len(datas) == 1 else datas
        return

    requests = payload.get("requests")
    if isinstance(requests, list) and "comm" in payload:
        sub_requests = []
        params_list = []
        for sub in requests:
            if not isinstance(sub, dict):
                continue
            sub_requests.append(
                {
                    "id": sub.get("id"),
                    "service_name": sub.get("service_name"),
                    "method_name": sub.get("method_name"),
                }
            )
            params_list.append(sub.get("params"))
        record["gateway"] = {"sub_requests": sub_requests}
        record["data"] = params_list[0] if len(params_list) == 1 else params_list
        return

    record["data"] = payload


def _extract_task_ids(record):
    """只从已识别接口的请求/响应关键路径收集 task_id（设计 §6.6）。"""
    found = []

    def add(value):
        if isinstance(value, str) and value and value not in found:
            found.append(value)

    data = record.get("data")
    if isinstance(data, dict):
        add(data.get("task_id"))
        debug = data.get("debug")
        if isinstance(debug, dict):
            add(debug.get("task_id"))
            task = debug.get("task")
            if isinstance(task, dict):
                add(task.get("task_id"))
            query = debug.get("query")
            if isinstance(query, dict):
                add(query.get("task_id"))
        cost_summary = data.get("cost_summary")
        if isinstance(cost_summary, dict):
            add(cost_summary.get("task_id"))
            calls = cost_summary.get("calls")
            if isinstance(calls, list):
                for call in calls:
                    if isinstance(call, dict):
                        add(call.get("task_id"))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                add(item.get("task_id"))
    record["task_ids"] = found
    return found


def parse_log_records(log_text):
    """解析日志文本，返回 (records, stage_events, warnings)。

    records 按出现顺序排列，包含接口请求/响应记录和无 marker 兜底记录。
    stage_events 为 QueryChainLogger `<Method> 事件:` 的阶段元数据。
    """
    lines = normalize_log_lines(log_text)
    records = []
    stage_events = []
    warnings = []
    consumed_spans = set()

    def consume(marker_idx, end_idx):
        for idx in range(marker_idx, end_idx + 1):
            consumed_spans.add(idx)

    def advance_after_scan(marker_idx, end_idx, error):
        """消费 marker 及其 JSON 块，返回续扫下标。

        marker 后未找到 JSON 起始时，只消费 marker 行本身，让紧随其后的
        下一个 marker 行重新参与识别。
        """
        if error == "marker 后未找到 JSON 起始":
            consume(marker_idx, marker_idx)
            return marker_idx + 1
        consume(marker_idx, end_idx)
        return end_idx + 1

    def add_record(record, marker_idx, value, end_idx, start_line, end_line, error):
        if error is not None:
            record["parse_status"] = "PARSE_ERROR"
            warnings.append(
                {
                    "code": "PARSE_ERROR",
                    "message": f"{record['method']} {record['direction']} JSON 解析失败: {error}",
                    "line": record["start_line"],
                }
            )
        else:
            record["payload"] = value
            record["parse_status"] = "PARSED"
            unwrap_gateway_payload(record)
            _extract_task_ids(record)
        record["end_line"] = end_line if end_line is not None else record["start_line"]
        records.append(record)
        return advance_after_scan(marker_idx, end_idx, error)

    pending_gateway_method = None
    idx = 0
    total = len(lines)
    while idx < total:
        content = lines[idx]["content"]
        line_no = lines[idx]["line_no"]
        timestamp = lines[idx]["timestamp"]

        arrow_match = RE_GW_ARROW.match(content)
        if arrow_match:
            method = arrow_match.group(3)
            direction = "request" if arrow_match.group(1) == "-->" else "response"
            if method in SUPPORTED_METHODS:
                record = _new_record(method, direction, "gateway_arrow", line_no, timestamp)
                # 箭头行本身没有 JSON 体，仅作方法与方向标记。
                record["parse_status"] = "PARSED"
                if arrow_match.group(2):
                    record["http_status"] = int(arrow_match.group(2))
                records.append(record)
            pending_gateway_method = method
            consumed_spans.add(idx)
            idx += 1
            continue

        if RE_GW_REQUEST.match(content) or RE_GW_RESPONSE.match(content):
            direction = "request" if RE_GW_REQUEST.match(content) else "response"
            method = pending_gateway_method
            if method and method in SUPPORTED_METHODS:
                record = _new_record(method, direction, "gateway", line_no, timestamp)
                value, end_idx, start_line, end_line, error = scan_json_block(lines, idx + 1)
                idx = add_record(record, idx, value, end_idx, start_line, end_line, error)
            else:
                # 非受支持接口仍消费其 JSON 块，避免进入兜底扫描。
                _value, end_idx, _s, _e, error = scan_json_block(lines, idx + 1)
                idx = advance_after_scan(idx, end_idx, error)
            continue

        qcl_event = RE_QCL_EVENT.match(content)
        if qcl_event:
            method = qcl_event.group(1)
            value, end_idx, start_line, end_line, error = scan_json_block(lines, idx + 1)
            if error is None and isinstance(value, dict):
                stage_events.append(
                    {
                        "method": method,
                        "line_no": line_no,
                        "sequence_no": value.get("sequence_no"),
                        "api_sequence_no": value.get("api_sequence_no"),
                        "run_id": value.get("run_id"),
                        "input_id": value.get("input_id"),
                        "person_name": value.get("person_name"),
                        "task_id": value.get("task_id"),
                        "candidate_id": value.get("candidate_id"),
                        "stage": value.get("stage"),
                        "attempt": value.get("attempt"),
                        "business_success": value.get("business_success"),
                    }
                )
            elif error is not None:
                warnings.append(
                    {
                        "code": "PARSE_ERROR",
                        "message": f"{method} 事件 JSON 解析失败: {error}",
                        "line": line_no,
                    }
                )
            idx = advance_after_scan(idx, end_idx, error)
            continue

        qcl_request = RE_QCL_REQUEST.match(content)
        if qcl_request:
            method = qcl_request.group(1)
            attempt = int(qcl_request.group(2)) if qcl_request.group(2) else None
            value, end_idx, start_line, end_line, error = scan_json_block(lines, idx + 1)
            if method in SUPPORTED_METHODS:
                record = _new_record(method, "request", "qcl", line_no, timestamp)
                record["attempt"] = attempt
                idx = add_record(record, idx, value, end_idx, start_line, end_line, error)
            else:
                if error is not None:
                    warnings.append(
                        {
                            "code": "PARSE_ERROR",
                            "message": f"{method} request JSON 解析失败: {error}",
                            "line": line_no,
                        }
                    )
                idx = advance_after_scan(idx, end_idx, error)
            continue

        qcl_response = RE_QCL_RESPONSE.match(content)
        if qcl_response:
            method = qcl_response.group(1)
            http_status = qcl_response.group(2)
            elapsed_ms = qcl_response.group(3)
            value, end_idx, start_line, end_line, error = scan_json_block(lines, idx + 1)
            if method in SUPPORTED_METHODS:
                record = _new_record(method, "response", "qcl", line_no, timestamp)
                record["http_status"] = int(http_status) if http_status.isdigit() else None
                record["elapsed_ms"] = int(elapsed_ms) if elapsed_ms.isdigit() else None
                idx = add_record(record, idx, value, end_idx, start_line, end_line, error)
            else:
                if error is not None:
                    warnings.append(
                        {
                            "code": "PARSE_ERROR",
                            "message": f"{method} response JSON 解析失败: {error}",
                            "line": line_no,
                        }
                    )
                idx = advance_after_scan(idx, end_idx, error)
            continue

        idx += 1

    # 无 marker 独立 JSON 的受限兜底识别（设计 §6.2）：
    # 根结构或 Gateway 子请求中存在 debug/cost_summary 时才识别，其他不猜测。
    idx = 0
    while idx < total:
        if idx in consumed_spans:
            idx += 1
            continue
        text = lines[idx]["json_text"].lstrip()
        if not text.startswith("{"):
            idx += 1
            continue
        value, end_idx, start_line, end_line, error = scan_json_block(lines, idx)
        if error is not None:
            # 只对疑似 People Insight 块（含 debug/cost_summary）告警，避免无关日志噪音。
            span_text = "\n".join(
                lines[span_idx]["json_text"] for span_idx in range(idx, end_idx + 1)
            )
            if '"debug"' in span_text or '"cost_summary"' in span_text:
                warnings.append(
                    {
                        "code": "PARSE_ERROR",
                        "message": f"独立 JSON 解析失败: {error}",
                        "line": lines[idx]["line_no"],
                    }
                )
            for span_idx in range(idx, end_idx + 1):
                consumed_spans.add(span_idx)
            idx = end_idx + 1
            continue
        method = _classify_markerless(value)
        if method:
            record = _new_record(method, "response", "markerless", lines[idx]["line_no"], None)
            record["payload"] = value
            record["parse_status"] = "PARSED"
            record["end_line"] = end_line if end_line is not None else lines[idx]["line_no"]
            unwrap_gateway_payload(record)
            _extract_task_ids(record)
            records.append(record)
        for span_idx in range(idx, end_idx + 1):
            consumed_spans.add(span_idx)
        idx = end_idx + 1

    return records, stage_events, warnings


def _classify_markerless(payload):
    if not isinstance(payload, dict):
        return None
    if "debug" in payload:
        return "GetSearchTaskDebug"
    if "cost_summary" in payload:
        return "GetProviderCostSummary"
    responses = payload.get("responses")
    if isinstance(responses, list):
        for sub in responses:
            data = sub.get("data") if isinstance(sub, dict) else None
            if isinstance(data, dict):
                if "debug" in data:
                    return "GetSearchTaskDebug"
                if "cost_summary" in data:
                    return "GetProviderCostSummary"
    return None


def select_task_records(records, requested_task_id=None):
    """单任务选择（设计 §6.6）。

    返回 (selected_records, selected_task_id, task_ids, selection_error)。
    """
    task_ids = []
    for record in records:
        for task_id in record.get("task_ids", []):
            if task_id not in task_ids:
                task_ids.append(task_id)

    if requested_task_id:
        selected = [
            record
            for record in records
            if not record.get("task_ids") or requested_task_id in record["task_ids"]
        ]
        has_task_records = any(
            requested_task_id in record.get("task_ids", []) for record in records
        )
        if not has_task_records:
            return [], None, task_ids, TASK_NOT_FOUND
        return selected, requested_task_id, task_ids, None

    if len(task_ids) == 1:
        return list(records), task_ids[0], task_ids, None
    if len(task_ids) > 1:
        return [], None, task_ids, MULTIPLE_TASKS_FOUND

    # 没有 task_id 但只有一组接口时允许生成临时任务快照，任务 ID 标记为未知。
    if records:
        return list(records), None, task_ids, None
    return [], None, task_ids, None


def _parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _build_timeline(debug_records, warnings):
    """从 GetSearchTaskDebug 的 agent_tool_calls 构建工具时间线（设计 §7.3）。"""
    if not debug_records:
        return []
    debug_record = debug_records[-1]
    data = debug_record.get("data")
    debug = data.get("debug") if isinstance(data, dict) else None
    tool_calls = debug.get("agent_tool_calls") if isinstance(debug, dict) else None
    if not isinstance(tool_calls, list):
        return []

    entries = []
    for call_index, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            continue
        entries.append(
            {
                "provider": call.get("provider"),
                "operation": call.get("operation") or call.get("provider_operation"),
                "status": call.get("status"),
                "start_time": call.get("start_time"),
                "finish_time": call.get("finish_time"),
                "http_status": call.get("http_status"),
                "cache_hit": bool(call.get("cache_hit")),
                "candidate_count": call.get("candidate_count"),
                "error_code": call.get("error_code") or "",
                "cost_status": call.get("cost_status"),
                "estimated_cost_microunit": call.get("estimated_cost_microunit"),
                # LLM 调用分类信息，供 LLM-001/LLM-002 按时间顺序核对（审查修复）
                "result_class": call.get("result_class"),
                "finish_reason": call.get("finish_reason"),
                "source": {
                    "method": debug_record["method"],
                    "json_path": f"debug.agent_tool_calls[{call_index}]",
                    "line_start": debug_record["start_line"],
                    "line_end": debug_record["end_line"],
                },
            }
        )

    timed = []
    untimed = []
    for original_index, entry in enumerate(entries):
        parsed = _parse_timestamp(entry["start_time"])
        if parsed is None:
            untimed.append((original_index, entry))
        else:
            timed.append((parsed, original_index, entry))
    timed.sort(key=lambda item: (item[0], item[1]))
    ordered = [entry for _ts, _oi, entry in timed] + [entry for _oi, entry in untimed]
    if untimed:
        warnings.append(
            {
                "code": "MISSING_TOOL_CALL_TIME",
                "message": f"{len(untimed)} 条 agent_tool_calls 缺少可解析的 start_time，已保持原序置于时间线末尾",
                "line": debug_record["start_line"],
            }
        )
    return ordered


def _responses_by_method(records):
    grouped = {}
    for record in records:
        if record["direction"] != "response" or record["parse_status"] != "PARSED":
            continue
        grouped.setdefault(record["method"], []).append(record)
    return grouped


def _first_request_data(records, method):
    for record in records:
        if (
            record["method"] == method
            and record["direction"] == "request"
            and record["parse_status"] == "PARSED"
            and isinstance(record.get("data"), dict)
        ):
            return record["data"]
    return None


def _select_final_get_task(get_task_records, warnings):
    """终态选择（设计 §7.2）：优先最后一个终态，否则最后一条 GetTask。"""
    if not get_task_records:
        return None, None
    datas = [
        record.get("data")
        for record in get_task_records
        if isinstance(record.get("data"), dict)
    ]
    if not datas:
        return None, None
    for data in reversed(datas):
        status = data.get("status")
        if status in TERMINAL_STATUSES:
            return status, data
    last_data = datas[-1]
    warnings.append(
        {
            "code": TASK_NOT_TERMINAL,
            "message": f"未找到终态 GetTask，最后状态为 {last_data.get('status')}",
            "line": get_task_records[-1]["start_line"],
        }
    )
    return last_data.get("status"), last_data


def _normalize_social_links(links):
    normalized = []
    if not isinstance(links, list):
        return normalized
    for link in links:
        if isinstance(link, str):
            normalized.append(link)
        elif isinstance(link, dict) and link.get("url"):
            normalized.append(link["url"])
    return normalized


def build_snapshot(records, stage_events, selected_task_id, warnings):
    """构建统一任务快照（设计 §7.1）。"""
    responses = _responses_by_method(records)
    get_task_records = responses.get("GetTask", [])
    debug_records = responses.get("GetSearchTaskDebug", [])
    cost_records = responses.get("GetProviderCostSummary", [])
    candidate_list_records = responses.get("ListTaskCandidates", [])

    final_status, final_task_data = _select_final_get_task(get_task_records, warnings)

    trace_ids = []
    request_ids = []
    for record in records:
        if record.get("trace_id") and record["trace_id"] not in trace_ids:
            trace_ids.append(record["trace_id"])
        if record.get("request_id") and record["request_id"] not in request_ids:
            request_ids.append(record["request_id"])

    create_request = _first_request_data(records, "CreateIntentTask")
    full_name = None
    clue_types = []
    if isinstance(create_request, dict):
        clues = create_request.get("clues")
        if isinstance(clues, list):
            for clue in clues:
                if not isinstance(clue, dict):
                    continue
                clue_type = clue.get("type")
                if clue_type and clue_type not in clue_types:
                    clue_types.append(clue_type)
                name_query = clue.get("full_name_query")
                if full_name is None and isinstance(name_query, dict):
                    full_name = name_query.get("full_name")
    if full_name is None:
        for event in stage_events:
            if event.get("person_name"):
                full_name = event["person_name"]
                break

    create_responses = responses.get("CreateIntentTask", [])
    query_id = None
    if create_responses and isinstance(create_responses[-1].get("data"), dict):
        query_id = create_responses[-1]["data"].get("query_id")
        if not clue_types:
            response_clue_types = create_responses[-1]["data"].get("clue_types")
            if isinstance(response_clue_types, list):
                clue_types = response_clue_types
    if query_id is None:
        debug_data = debug_records[-1].get("data") if debug_records else None
        debug_body = debug_data.get("debug") if isinstance(debug_data, dict) else None
        query = debug_body.get("query") if isinstance(debug_body, dict) else None
        if isinstance(query, dict):
            query_id = query.get("query_id")

    candidate_count = None
    top_confidence_score = None
    if isinstance(final_task_data, dict):
        candidate_count = final_task_data.get("candidate_count")
        top_confidence_score = final_task_data.get("top_confidence_score")

    candidates = []
    if candidate_list_records:
        list_data = candidate_list_records[-1].get("data")
        items = list_data.get("items") if isinstance(list_data, dict) else None
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                candidates.append(
                    {
                        "candidate_id": item.get("candidate_id"),
                        "person_id": item.get("person_id"),
                        "display_name": item.get("display_name"),
                        "confidence_level": item.get("confidence_level"),
                        "match_score": item.get("match_score"),
                        "matched_clue_types": item.get("matched_clue_types") or [],
                        "is_top_result": bool(item.get("is_top_result")),
                        "is_best_match": bool(item.get("is_best_match")),
                        "source_provider": item.get("source_provider"),
                        "social_links": _normalize_social_links(item.get("social_links")),
                    }
                )

    debug_body = {}
    if debug_records:
        debug_data = debug_records[-1].get("data")
        debug_body = debug_data.get("debug") if isinstance(debug_data, dict) and isinstance(
            debug_data.get("debug"), dict
        ) else {}
    diagnosis = debug_body.get("diagnosis", {}) if isinstance(debug_body, dict) else {}

    cost = {}
    if cost_records:
        cost_data = cost_records[-1].get("data")
        if isinstance(cost_data, dict):
            cost = cost_data.get("cost_summary") or cost_data

    candidate_details = []
    for record in responses.get("GetTaskCandidateDetail", []):
        data = record.get("data")
        if isinstance(data, dict):
            candidate_details.append(data)

    coverage = {
        "create_task": bool(records and any(r["method"] == "CreateIntentTask" for r in records)),
        "get_task": bool(get_task_records),
        "candidate_list": bool(candidate_list_records),
        "candidate_detail": bool(responses.get("GetTaskCandidateDetail")),
        "debug": bool(debug_records),
        "cost_summary": bool(cost_records),
        "source_truncated": any(r["parse_status"] == "PARSE_ERROR" for r in records),
        "parse_warnings": list(warnings),
    }

    return {
        "analyzer_version": ANALYZER_VERSION,
        "ruleset_version": RULESET_VERSION,
        "task": {
            "task_id": selected_task_id,
            "query_id": query_id,
            "trace_ids": trace_ids,
            "request_ids": request_ids,
            "full_name": full_name,
            "clue_types": clue_types,
            "social_links": candidates[0]["social_links"] if candidates else [],
            "photo_count": 0,
            "final_status": final_status,
            "candidate_count": candidate_count,
            "top_confidence_score": top_confidence_score,
        },
        "coverage": coverage,
        "timeline": _build_timeline(debug_records, warnings),
        "candidates": candidates,
        "candidate_details": candidate_details,
        "diagnosis": diagnosis,
        "debug": debug_body,
        "get_task_data": final_task_data,
        "create_request": create_request,
        "cost": cost,
        "source_records": records,
    }


def analyze_people_search_log(log_text, requested_task_id=None):
    """分析入口：解析日志并生成统一任务快照（不调用 AI）。

    返回 dict：
    - supported: 是否识别到 People Insight 检索日志
    - unsupported_reason: 不支持时为 UNSUPPORTED_LOG
    - selection_error: MULTIPLE_TASKS_FOUND / TASK_NOT_FOUND / None
    - task_ids: 日志中收集到的主任务 ID 列表
    - snapshot: 统一任务快照（无法选择任务时为 None）
    - records: 全部接口记录（含未选中任务的记录）
    - stage_events: QueryChainLogger 阶段事件
    - parse_warnings: 解析告警
    """
    records, stage_events, warnings = parse_log_records(log_text)
    result = {
        "analyzer_version": ANALYZER_VERSION,
        "ruleset_version": RULESET_VERSION,
        "supported": bool(records),
        "unsupported_reason": None if records else UNSUPPORTED_LOG,
        "selection_error": None,
        "task_ids": [],
        "snapshot": None,
        "records": records,
        "stage_events": stage_events,
        "parse_warnings": warnings,
    }
    if not records:
        return result

    selected, selected_task_id, task_ids, selection_error = select_task_records(
        records, requested_task_id
    )
    result["task_ids"] = task_ids
    result["selection_error"] = selection_error
    if selection_error is not None:
        return result
    result["snapshot"] = build_snapshot(selected, stage_events, selected_task_id, warnings)
    return result


def analyze_log_file(path, requested_task_id=None):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        log_text = handle.read()
    return analyze_people_search_log(log_text, requested_task_id)


def summarize_result(result):
    """生成简洁文本摘要，便于命令行验证。"""
    if not result["supported"]:
        return f"UNSUPPORTED_LOG（未识别到 People Insight 检索接口，记录数=0）"
    if result["selection_error"]:
        return (
            f"{result['selection_error']}（task_ids={', '.join(result['task_ids']) or '无'}，"
            f"接口记录数={len(result['records'])}）"
        )
    snapshot = result["snapshot"]
    task = snapshot["task"]
    coverage = snapshot["coverage"]
    coverage_flags = "".join(
        "1" if coverage[key] else "0"
        for key in (
            "create_task",
            "get_task",
            "candidate_list",
            "candidate_detail",
            "debug",
            "cost_summary",
        )
    )
    return (
        f"task_id={task['task_id'] or '未知'} full_name={task['full_name']!r} "
        f"final_status={task['final_status']} coverage={coverage_flags} "
        f"timeline={len(snapshot['timeline'])} candidates={len(snapshot['candidates'])} "
        f"records={len(snapshot['source_records'])} warnings={len(result['parse_warnings'])}"
    )


if __name__ == "__main__":
    import sys

    for arg_path in sys.argv[1:]:
        analysis = analyze_log_file(arg_path)
        print(f"{arg_path}: {summarize_result(analysis)}")
