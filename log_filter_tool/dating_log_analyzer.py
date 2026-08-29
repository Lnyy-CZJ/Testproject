"""Dating Gateway 日志的确定性任务、上传和 Result Schema 聚合器。

本模块只消费 :func:`gateway_log_parser.parse_interface_log` 的结构化结果，
不访问网络、数据库、对象存储或 LLM。当前仅实现 Task 5 的 Result 字段与
业务摘要投影；规则判定、报告、API 和脱敏由后续任务实现。
"""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlsplit

from gateway_log_parser import PARSER_VERSION, parse_interface_log


ANALYZER_VERSION = "dating-structured-v1"
REPLY_SCHEMA_VERSION = "dating.reply_generation.v1"
ANALYSIS_SCHEMA_VERSION = "dating.relationship_analysis.v1"
MAX_TEXT_VALUE_CHARS = 20000
MAX_FIELD_DEPTH = 50
MAX_FIELD_COUNT = 20000

REPLY_REQUIRED_PATHS = (
    "result.schema_version",
    "result.context",
    "result.roles",
    "result.association",
    "result.degradation",
    "result.warnings",
)
ANALYSIS_REQUIRED_PATHS = (
    "result.schema_version",
    "result.analysis_scope",
    "result.overview",
    "result.chat_signals",
    "result.key_events",
    "result.warnings",
)

# Schema path 使用 ``[]`` 表示任意数组项。集合完整覆盖两份 PRD 黄金样本；
# 后续响应出现的新字段仍会进入字段索引，但会明确标记 schema_known=false。
REPLY_SCHEMA_PATHS = frozenset(
    (
        "result",
        "result.schema_version",
        "result.context",
        "result.context.conversation_stage",
        "result.context.moment_type",
        "result.context.reply_state",
        "result.context.requested_intent",
        "result.context.effective_goal",
        "result.context.signals",
        "result.context.signals[]",
        "result.context.signals[].signal_id",
        "result.context.signals[].value",
        "result.context.signals[].message_id",
        "result.comprehensive_analysis",
        "result.comprehensive_analysis.whats_happening",
        "result.whats_happening",
        "result.whats_happening.title",
        "result.whats_happening.summary",
        "result.roles",
        "result.roles[]",
        "result.roles[].role_id",
        "result.roles[].role_name",
        "result.roles[].rank",
        "result.roles[].is_best_fit",
        "result.roles[].selection_rule_id",
        "result.roles[].selection_reasons",
        "result.roles[].selection_reasons[]",
        "result.roles[].coach_note",
        "result.roles[].replies",
        "result.roles[].replies[]",
        "result.roles[].replies[].reply_id",
        "result.roles[].replies[].text",
        "result.roles[].replies[].is_top_pick",
        "result.roles[].top_pick",
        "result.roles[].top_pick.reply_id",
        "result.roles[].top_pick.text",
        "result.roles[].alternatives",
        "result.roles[].alternatives[]",
        "result.roles[].alternatives[].reply_id",
        "result.roles[].alternatives[].text",
        "result.association",
        "result.association.person_id",
        "result.association.person_history_used",
        "result.degradation",
        "result.degradation.is_degraded",
        "result.degradation.reason",
        "result.warnings",
        "result.warnings[]",
    )
)

ANALYSIS_SCHEMA_PATHS = frozenset(
    (
        "result",
        "result.schema_version",
        "result.analysis_scope",
        "result.analysis_scope.uploaded_asset_count",
        "result.analysis_scope.valid_asset_count",
        "result.analysis_scope.ignored_asset_count",
        "result.analysis_scope.valid_message_count",
        "result.analysis_scope.analyzed_message_count",
        "result.analysis_scope.truncated_to_recent_300",
        "result.overview",
        "result.overview.insight_title",
        "result.overview.insight_summary",
        "result.overview.relationship_stage",
        "result.overview.current_state",
        "result.overview.reliability_level",
        "result.overview.next_steps",
        "result.overview.next_steps.action",
        "result.overview.next_steps.communication",
        "result.overview.next_steps.observation",
        "result.overview.dashboard",
        "result.overview.dashboard.message_counts",
        "result.overview.dashboard.message_counts.user",
        "result.overview.dashboard.message_counts.other",
        "result.overview.dashboard.effort",
        "result.overview.dashboard.effort.you_score",
        "result.overview.dashboard.effort.them_score",
        "result.overview.dashboard.match_degree",
        "result.overview.dashboard.match_degree.score",
        "result.overview.dashboard.match_degree.level",
        "result.overview.dashboard.keywords",
        "result.overview.dashboard.keywords.user_focus",
        "result.overview.dashboard.keywords.other_focus",
        "result.chat_signals",
        "result.chat_signals.signal_summary",
        "result.chat_signals.positive_signals",
        "result.chat_signals.positive_signals[]",
        "result.chat_signals.positive_signals[].signal_id",
        "result.chat_signals.positive_signals[].text",
        "result.chat_signals.positive_signals[].evidence_message_ids",
        "result.chat_signals.positive_signals[].evidence_message_ids[]",
        "result.chat_signals.watch_signals",
        "result.chat_signals.watch_signals[]",
        "result.chat_signals.watch_signals[].signal_id",
        "result.chat_signals.watch_signals[].text",
        "result.chat_signals.watch_signals[].evidence_message_ids",
        "result.chat_signals.watch_signals[].evidence_message_ids[]",
        "result.chat_signals.risk_signals",
        "result.chat_signals.risk_signals[]",
        "result.chat_signals.risk_signals[].signal_id",
        "result.chat_signals.risk_signals[].text",
        "result.chat_signals.risk_signals[].evidence_message_ids",
        "result.chat_signals.risk_signals[].evidence_message_ids[]",
        "result.key_events",
        "result.key_events.turning_points",
        "result.key_events.turning_points[]",
        "result.key_events.turning_points[].event_id",
        "result.key_events.turning_points[].event",
        "result.key_events.turning_points[].takeaway",
        "result.key_events.turning_points[].evidence_message_ids",
        "result.key_events.turning_points[].evidence_message_ids[]",
        "result.key_events.hidden_meanings",
        "result.key_events.hidden_meanings[]",
        "result.key_events.hidden_meanings[].event_id",
        "result.key_events.hidden_meanings[].event",
        "result.key_events.hidden_meanings[].takeaway",
        "result.key_events.hidden_meanings[].evidence_message_ids",
        "result.key_events.hidden_meanings[].evidence_message_ids[]",
        "result.key_events.did_well",
        "result.key_events.did_well[]",
        "result.key_events.did_well[].event_id",
        "result.key_events.did_well[].event",
        "result.key_events.did_well[].takeaway",
        "result.key_events.did_well[].evidence_message_ids",
        "result.key_events.did_well[].evidence_message_ids[]",
        "result.key_events.could_improve",
        "result.key_events.could_improve[]",
        "result.key_events.could_improve[].event_id",
        "result.key_events.could_improve[].event",
        "result.key_events.could_improve[].takeaway",
        "result.key_events.could_improve[].evidence_message_ids",
        "result.key_events.could_improve[].evidence_message_ids[]",
        "result.warnings",
        "result.warnings[]",
    )
)

_FIELD_LABELS = {
    "result.overview.dashboard.effort.you_score": "你的投入度",
}

MULTIPLE_TASKS_FOUND = "MULTIPLE_TASKS_FOUND"
TASK_NOT_FOUND = "TASK_NOT_FOUND"

SUPPORTED_METHODS = (
    "GetUserPreferences",
    "GetMediaUploadConfig",
    "PrepareMediaUpload",
    "CompleteMediaUpload",
    "CreateReplyTask",
    "GetTask",
    "GetTaskResult",
    "CreateAnalysisTask",
    "GetAnalysisTask",
    "GetAnalysisResult",
)

# 任务类型只能由已知的 Create/Poll/Result 接口组合推导，不能依赖日志全文
# 中形似 task_id 的普通字符串。Schema 版本仍以真实 Result 响应为准。
_CREATE_METHODS = {
    "CreateReplyTask": "reply_generation",
    "CreateAnalysisTask": "relationship_analysis",
}
_POLL_METHODS = {
    "GetTask": "reply_generation",
    "GetAnalysisTask": "relationship_analysis",
}
_RESULT_METHODS = {
    "GetTaskResult": "reply_generation",
    "GetAnalysisResult": "relationship_analysis",
}
_TASK_METHODS = frozenset((*_CREATE_METHODS, *_POLL_METHODS, *_RESULT_METHODS))
_TERMINAL_STATUSES = frozenset(("succeeded", "failed", "cancelled", "canceled"))


def classify_presence(value: object, *, missing: bool = False) -> str:
    """区分字段缺失、显式 null 与不同类型的空值。

    参数:
        value: 已解析的 JSON 值；当 ``missing=True`` 时仅作为占位值。
        missing: 已知 Schema 是否预期该字段、但响应中没有该字段。

    返回:
        PRD §6 定义的稳定 presence 字符串。布尔值 ``False`` 和数字 ``0``
        都是有效值，因此统一归类为 ``PRESENT``。
    """
    if missing:
        return "MISSING"
    if value is None:
        return "NULL"
    if value == "":
        return "EMPTY_STRING"
    if isinstance(value, list) and not value:
        return "EMPTY_ARRAY"
    if isinstance(value, dict) and not value:
        return "EMPTY_OBJECT"
    return "PRESENT"


def _request_params(call: dict) -> dict:
    """返回调用参数字典；解析缺失或类型异常时使用空字典。"""
    request = call.get("request")
    params = request.get("params") if isinstance(request, dict) else None
    return params if isinstance(params, dict) else {}


def _response_data(call: dict) -> dict:
    """返回业务响应 data；HTTP/Gateway 层缺失时不臆造业务字段。"""
    response = call.get("response")
    data = response.get("data") if isinstance(response, dict) else None
    return data if isinstance(data, dict) else {}


def _gateway_calls(calls: list[dict], method: str | None = None) -> list[dict]:
    """筛选 Gateway 调用，并可按 method_name 做精确匹配。

    参数:
        calls: parser 生成的 InterfaceCall 列表。
        method: 可选的完整方法名；不执行模糊或正则匹配。

    返回:
        保持原日志顺序的 Gateway 调用列表。
    """
    gateway_calls = [call for call in calls if call.get("transport") == "gateway"]
    if method is None:
        return gateway_calls
    return [call for call in gateway_calls if call.get("method_name") == method]


def _append_unique(values: list[str], value: object) -> None:
    """仅追加非空字符串，并保持首次出现顺序。"""
    if isinstance(value, str) and value and value not in values:
        values.append(value)


def _call_task_ids(call: dict) -> list[str]:
    """从已知 Create/Poll/Result 参数与响应路径提取 task_id。

    Create 的 ID 来自 ``response.data.task_id``；Poll/Result 依次读取
    ``request.params.task_id`` 和 ``response.data.task_id``。函数不会扫描
    其他字段，更不会对原始全文执行 task_id 正则搜索。
    """
    if call.get("transport") != "gateway":
        return []
    method = call.get("method_name")
    if method not in _TASK_METHODS:
        return []

    task_ids: list[str] = []
    if method in _POLL_METHODS or method in _RESULT_METHODS:
        _append_unique(task_ids, _request_params(call).get("task_id"))
    _append_unique(task_ids, _response_data(call).get("task_id"))
    return task_ids


def select_dating_task(
    calls: list[dict], requested_task_id: str | None = None
) -> tuple[str | None, list[str], str | None]:
    """按 0/1/多任务及显式 ID 契约选择任务，并返回稳定错误码。"""
    task_ids: list[str] = []
    for call in _gateway_calls(calls):
        for task_id in _call_task_ids(call):
            _append_unique(task_ids, task_id)

    if requested_task_id in task_ids:
        return requested_task_id, task_ids, None
    if requested_task_id is not None:
        return None, task_ids, TASK_NOT_FOUND
    if requested_task_id is None and len(task_ids) > 1:
        return None, task_ids, MULTIPLE_TASKS_FOUND
    if task_ids:
        return task_ids[0], task_ids, None
    return None, task_ids, None


def _call_succeeded(call: dict) -> bool:
    """判断 parser 已分类调用是否成功，并兼容最小字典输入。"""
    result_class = call.get("result_class")
    if result_class is not None:
        return result_class == "success"
    response = call.get("response")
    if not isinstance(response, dict):
        return False
    status = response.get("http_status")
    return isinstance(status, int) and 200 <= status <= 299


def _object_path(url: object) -> str | None:
    """去除签名查询参数，只保留可用于确定性关联的对象路径。"""
    if not isinstance(url, str) or not url:
        return None
    return urlsplit(url).path or None


def _warning(code: str, message: str, **context: object) -> dict:
    """创建与 parser warning 兼容的稳定字典结构。"""
    warning = {"code": code, "message": message}
    warning.update({key: value for key, value in context.items() if value is not None})
    return warning


def _normalized_schema_path(path: str) -> str:
    """把实际数组索引归一化为 Schema 使用的 ``[]`` 模板。"""
    return re.sub(r"\[\d+\]", "[]", path)


def _field_identity(path: str, parent_path: str | None) -> tuple[str | None, int | None]:
    """从字段 path 提取对象 key 或数组索引，两者不会同时存在。"""
    if parent_path is not None and path.startswith(f"{parent_path}["):
        suffix = path[len(parent_path) + 1 : -1]
        if suffix.isdigit():
            return None, int(suffix)
    return path.rsplit(".", 1)[-1], None


def _json_value_type(value: object, *, missing: bool = False) -> str:
    """返回与 JSON 类型一致的稳定字段类型名称。"""
    if missing:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _make_field_node(
    value: object,
    path: str,
    parent_path: str | None,
    source: dict,
    known_paths: set[str],
    *,
    missing: bool = False,
) -> tuple[dict, dict | None]:
    """构造单个字段节点，并仅在自由文本超限时返回 warning。"""
    key, array_index = _field_identity(path, parent_path)
    normalized_path = _normalized_schema_path(path)
    truncated = isinstance(value, str) and len(value) > MAX_TEXT_VALUE_CHARS
    field_value = value[:MAX_TEXT_VALUE_CHARS] if truncated else value
    field_source = {
        "method": source.get("method"),
        "call_id": source.get("call_id"),
        "line_start": source.get("line_start"),
        "line_end": source.get("line_end"),
        # Task 5 只承诺 Result 响应块级证据，不能伪造具体 JSON key 行号。
        "location_precision": "block",
    }
    field = {
        "path": path,
        "parent_path": parent_path,
        "key": key,
        "array_index": array_index,
        "label": _FIELD_LABELS.get(
            normalized_path, key if key is not None else f"[{array_index}]"
        ),
        "value": field_value,
        "value_type": _json_value_type(value, missing=missing),
        "presence": classify_presence(value, missing=missing),
        "schema_known": missing or normalized_path in known_paths,
        "value_truncated": truncated,
        "source": field_source,
    }
    warning = None
    if truncated:
        warning = _warning(
            "VALUE_TRUNCATED",
            "字段文本超过 20000 字符，结果仅保留前 20000 字符",
            json_path=path,
        )
    return field, warning


def build_field_index(
    result_payload: object,
    *,
    root_path: str,
    source: dict,
    known_paths: set[str] | frozenset[str] | None = None,
    required_paths: tuple[str, ...] = (),
    max_depth: int = MAX_FIELD_DEPTH,
    max_fields: int = MAX_FIELD_COUNT,
) -> tuple[list[dict], list[dict]]:
    """递归生成 Result 字段索引和遍历 warning。

    实际字段 path 保留数组索引；Schema 匹配使用 ``[]`` 模板。未知字段仍
    完整输出但 ``schema_known=false``。遍历后为已知 Schema 的缺失必填项
    追加 ``MISSING`` 节点，且所有节点只使用调用方提供的响应块级证据。
    """
    fields: list[dict] = []
    warnings: list[dict] = []
    known_path_set = set(known_paths or ())
    field_limit_reached = False

    def visit(
        current: object, path: str, parent_path: str | None, depth: int
    ) -> None:
        nonlocal field_limit_reached
        if field_limit_reached:
            return
        if depth > max_depth:
            warnings.append(
                _warning(
                    "MAX_FIELD_DEPTH_REACHED",
                    "Result 字段递归深度超过上限",
                    json_path=path,
                )
            )
            return
        if len(fields) >= max_fields:
            warnings.append(
                _warning(
                    "MAX_FIELD_COUNT_REACHED",
                    "Result 字段节点数量达到上限",
                    json_path=path,
                )
            )
            field_limit_reached = True
            return

        field, field_warning = _make_field_node(
            current, path, parent_path, source, known_path_set
        )
        fields.append(field)
        if field_warning is not None:
            warnings.append(field_warning)

        if isinstance(current, dict):
            for key, child in current.items():
                visit(child, f"{path}.{key}", path, depth + 1)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                visit(child, f"{path}[{index}]", path, depth + 1)

    visit(result_payload, root_path, None, 0)

    present_schema_paths = {
        _normalized_schema_path(field["path"])
        for field in fields
        if field["presence"] != "MISSING"
    }
    for required_path in required_paths:
        if required_path in present_schema_paths or len(fields) >= max_fields:
            continue
        parent_path = required_path.rsplit(".", 1)[0] if "." in required_path else None
        field, _ = _make_field_node(
            None,
            required_path,
            parent_path,
            source,
            known_path_set,
            missing=True,
        )
        fields.append(field)

    return fields, warnings


def _field_health(fields: list[dict]) -> dict:
    """按 presence 和 Schema 归属计算纯事实型字段健康摘要。"""
    presence_counts = {
        presence: sum(field.get("presence") == presence for field in fields)
        for presence in (
            "PRESENT",
            "NULL",
            "EMPTY_STRING",
            "EMPTY_ARRAY",
            "EMPTY_OBJECT",
            "MISSING",
        )
    }
    return {
        "total_field_count": len(fields),
        "present_count": presence_counts["PRESENT"],
        "null_count": presence_counts["NULL"],
        "empty_string_count": presence_counts["EMPTY_STRING"],
        "empty_array_count": presence_counts["EMPTY_ARRAY"],
        "empty_object_count": presence_counts["EMPTY_OBJECT"],
        "missing_count": presence_counts["MISSING"],
        "unknown_schema_field_count": sum(
            field.get("schema_known") is False for field in fields
        ),
    }


def build_reply_sections(result_payload: dict) -> list[dict]:
    """按 PRD §14.2 的固定顺序构造 Reply 业务分组。"""
    section_specs = (
        ("上下文", "result.context", result_payload.get("context")),
        (
            "综合分析",
            "result.comprehensive_analysis",
            result_payload.get("comprehensive_analysis"),
        ),
        ("当前情况", "result.whats_happening", result_payload.get("whats_happening")),
        ("推荐角色", "result.roles", result_payload.get("roles")),
        ("人物关联", "result.association", result_payload.get("association")),
        ("降级", "result.degradation", result_payload.get("degradation")),
        ("警告", "result.warnings", result_payload.get("warnings")),
    )
    return [
        {"label": label, "path": path, "value": value}
        for label, path, value in section_specs
    ]


def _project_reply_result(result_payload: dict) -> tuple[dict, list[dict]]:
    """生成 Reply v1 的 PRD §14.3 摘要和业务分组。"""
    raw_roles = result_payload.get("roles")
    roles = [role for role in raw_roles if isinstance(role, dict)] if isinstance(
        raw_roles, list
    ) else []
    replies: list[dict] = []
    for role in roles:
        role_replies = role.get("replies")
        if isinstance(role_replies, list):
            replies.extend(
                reply for reply in role_replies if isinstance(reply, dict)
            )
    top_pick = next(
        (reply for reply in replies if reply.get("is_top_pick") is True), None
    )
    context_value = result_payload.get("context")
    association_value = result_payload.get("association")
    degradation_value = result_payload.get("degradation")
    context = context_value if isinstance(context_value, dict) else {}
    association = association_value if isinstance(association_value, dict) else {}
    degradation = degradation_value if isinstance(degradation_value, dict) else {}
    signals = context.get("signals")
    warnings = result_payload.get("warnings")
    summary = {
        "conversation_stage": context.get("conversation_stage"),
        "moment_type": context.get("moment_type"),
        "reply_state": context.get("reply_state"),
        "requested_intent": context.get("requested_intent"),
        "effective_goal": context.get("effective_goal"),
        "signal_count": len(signals) if isinstance(signals, list) else 0,
        "role_count": len(roles),
        "reply_count": len(replies),
        "top_pick_reply_id": top_pick.get("reply_id") if top_pick else None,
        "person_history_used": association.get("person_history_used"),
        "is_degraded": degradation.get("is_degraded"),
        "warning_count": len(warnings) if isinstance(warnings, list) else 0,
    }
    return summary, build_reply_sections(result_payload)


def build_analysis_sections(result_payload: dict) -> list[dict]:
    """按 PRD §15.2 的固定顺序构造 Analysis 业务分组。"""
    overview_value = result_payload.get("overview")
    overview = overview_value if isinstance(overview_value, dict) else {}
    section_specs = (
        ("分析范围", "result.analysis_scope", result_payload.get("analysis_scope")),
        ("总览", "result.overview", overview_value),
        ("Dashboard", "result.overview.dashboard", overview.get("dashboard")),
        ("聊天信号", "result.chat_signals", result_payload.get("chat_signals")),
        ("关键事件", "result.key_events", result_payload.get("key_events")),
        ("警告", "result.warnings", result_payload.get("warnings")),
    )
    return [
        {"label": label, "path": path, "value": value}
        for label, path, value in section_specs
    ]


def _array_count(container: dict, key: str) -> int | None:
    """数组存在时返回长度；缺失或类型异常时返回 None，避免伪造空数组。"""
    if key not in container:
        return None
    value = container.get(key)
    return len(value) if isinstance(value, list) else None


def _project_analysis_result(result_payload: dict) -> tuple[dict, list[dict]]:
    """生成 Analysis v1 的 PRD §15.3 摘要和业务分组。"""
    scope_value = result_payload.get("analysis_scope")
    overview_value = result_payload.get("overview")
    signals_value = result_payload.get("chat_signals")
    events_value = result_payload.get("key_events")
    scope = scope_value if isinstance(scope_value, dict) else {}
    overview = overview_value if isinstance(overview_value, dict) else {}
    signals = signals_value if isinstance(signals_value, dict) else {}
    events = events_value if isinstance(events_value, dict) else {}
    summary = {
        "relationship_stage": overview.get("relationship_stage"),
        "current_state": overview.get("current_state"),
        "reliability_level": overview.get("reliability_level"),
        "uploaded_asset_count": scope.get("uploaded_asset_count"),
        "valid_asset_count": scope.get("valid_asset_count"),
        "ignored_asset_count": scope.get("ignored_asset_count"),
        "analyzed_message_count": scope.get("analyzed_message_count"),
        "positive_signal_count": _array_count(signals, "positive_signals"),
        "watch_signal_count": _array_count(signals, "watch_signals"),
        "risk_signal_count": _array_count(signals, "risk_signals"),
        "turning_point_count": _array_count(events, "turning_points"),
        "warning_count": _array_count(result_payload, "warnings"),
    }
    return summary, build_analysis_sections(result_payload)


def _result_block_source(result_call: dict) -> dict:
    """从最后一次成功 Result 响应提取字段树共享的 block 级证据。"""
    response = (
        result_call.get("response")
        if isinstance(result_call.get("response"), dict)
        else {}
    )
    return {
        "method": result_call.get("method_name"),
        "call_id": result_call.get("call_id"),
        "line_start": response.get("line_start"),
        "line_end": response.get("line_end"),
    }


def _selected_asset_ids(calls: list[dict], selected_task_id: str | None) -> list[str]:
    """只从所选任务 Create 请求的 asset_ids 读取资源使用关系。"""
    if selected_task_id is None:
        return []
    for call in _gateway_calls(calls):
        if call.get("method_name") not in _CREATE_METHODS:
            continue
        if selected_task_id not in _call_task_ids(call):
            continue
        asset_ids = _request_params(call).get("asset_ids")
        if not isinstance(asset_ids, list):
            return []
        result: list[str] = []
        for asset_id in asset_ids:
            _append_unique(result, asset_id)
        return result
    return []


def _new_prepare_asset(call: dict) -> dict:
    """将 PrepareMediaUpload 投影为上传资源基础记录。"""
    params = _request_params(call)
    data = _response_data(call)
    upload_url = data.get("upload_url")
    return {
        "asset_id": data.get("asset_id"),
        "content_type": data.get("content_type", params.get("content_type")),
        "size_bytes": data.get("size_bytes", params.get("size_bytes")),
        "purpose": data.get("purpose"),
        "prepare_status": data.get("status"),
        "put_http_status": None,
        "complete_status": None,
        "prepare_call_id": call.get("call_id"),
        "put_call_id": None,
        "complete_call_id": None,
        "object_path": _object_path(upload_url),
        "used_by_task": False,
        "upload_state": "unknown",
        "warnings": [],
        # 以下键只服务于本函数内的状态计算，返回前统一移除。
        "_prepare_seen": True,
        "_prepare_ok": _call_succeeded(call) and bool(data.get("asset_id")),
        "_put_seen": False,
        "_put_ok": False,
        "_complete_seen": False,
        "_complete_ok": False,
    }


def _new_orphan_put_asset(call: dict, warning: dict | None = None) -> dict:
    """保留无法关联到 Prepare 的 PUT，防止静默丢失上传证据。"""
    response = call.get("response") if isinstance(call.get("response"), dict) else {}
    request = call.get("request") if isinstance(call.get("request"), dict) else {}
    return {
        "asset_id": None,
        "content_type": None,
        "size_bytes": None,
        "purpose": None,
        "prepare_status": None,
        "put_http_status": response.get("http_status"),
        "complete_status": None,
        "prepare_call_id": None,
        "put_call_id": call.get("call_id"),
        "complete_call_id": None,
        "object_path": _object_path(request.get("url")),
        "used_by_task": False,
        "upload_state": "orphan_put",
        "warnings": [warning] if warning else [],
        "_prepare_seen": False,
        "_prepare_ok": False,
        "_put_seen": True,
        "_put_ok": _call_succeeded(call),
        "_complete_seen": False,
        "_complete_ok": False,
    }


def _finalize_upload_asset(asset: dict, used_asset_ids: list[str]) -> dict:
    """按 Task 4 固定优先级计算 upload_state，并移除内部状态键。"""
    prepare_ok = asset["_prepare_ok"]
    put_ok = asset["_put_ok"]
    complete_ok = asset["_complete_ok"]
    put_seen = asset["_put_seen"]
    complete_seen = asset["_complete_seen"]
    put_status = asset.get("put_http_status")
    asset_id = asset.get("asset_id")

    if prepare_ok and put_ok and complete_ok:
        upload_state = "complete"
    elif isinstance(put_status, int) and not 200 <= put_status <= 299:
        upload_state = "put_failed"
    elif complete_seen and not complete_ok:
        upload_state = "complete_failed"
    elif put_seen and asset_id is None:
        upload_state = "orphan_put"
    elif asset["_prepare_seen"] and not put_seen:
        upload_state = "prepare_only"
    else:
        upload_state = "unknown"

    asset["upload_state"] = upload_state
    asset["used_by_task"] = isinstance(asset_id, str) and asset_id in used_asset_ids
    for key in (
        "_prepare_seen",
        "_prepare_ok",
        "_put_seen",
        "_put_ok",
        "_complete_seen",
        "_complete_ok",
    ):
        asset.pop(key, None)
    return asset


def build_upload_assets(
    calls: list[dict], selected_task_id: str | None
) -> tuple[list[dict], list[dict]]:
    """聚合 Prepare、PUT、Complete，并标记所选任务使用的资源。

    关联只接受去查询参数后的唯一对象路径，或日志中唯一尚未关联的 Prepare。
    多个候选且无唯一证据时保留 orphan PUT 并输出 warning，绝不猜测最近资源。
    """
    assets: list[dict] = []
    warnings: list[dict] = []

    for call in calls:
        method = call.get("method_name")
        transport = call.get("transport")

        if transport == "gateway" and method == "PrepareMediaUpload":
            assets.append(_new_prepare_asset(call))
            continue

        if transport == "object_storage_put":
            request = call.get("request") if isinstance(call.get("request"), dict) else {}
            put_path = _object_path(request.get("url"))
            candidates = [
                asset
                for asset in assets
                if asset["_prepare_seen"] and not asset["_put_seen"]
            ]
            path_matches = [
                asset
                for asset in candidates
                if put_path is not None and asset.get("object_path") == put_path
            ]
            if len(path_matches) == 1:
                target = path_matches[0]
            elif len(candidates) == 1:
                target = candidates[0]
            elif candidates:
                warning = _warning(
                    "AMBIGUOUS_UPLOAD_ASSOCIATION",
                    "PUT 对应多个未关联 PrepareMediaUpload，缺少唯一对象路径证据。",
                    put_call_id=call.get("call_id"),
                    object_path=put_path,
                    candidate_prepare_call_ids=[
                        asset.get("prepare_call_id") for asset in candidates
                    ],
                )
                warnings.append(warning)
                assets.append(_new_orphan_put_asset(call, warning))
                continue
            else:
                target = None
            if target is None:
                warning = _warning(
                    "ORPHAN_UPLOAD_PUT",
                    "PUT 前没有可关联的 PrepareMediaUpload。",
                    put_call_id=call.get("call_id"),
                )
                warnings.append(warning)
                assets.append(_new_orphan_put_asset(call, warning))
                continue
            response = call.get("response") if isinstance(call.get("response"), dict) else {}
            target["put_call_id"] = call.get("call_id")
            target["put_http_status"] = response.get("http_status")
            target["object_path"] = put_path or target.get("object_path")
            target["_put_seen"] = True
            target["_put_ok"] = _call_succeeded(call)
            continue

        if transport == "gateway" and method == "CompleteMediaUpload":
            params = _request_params(call)
            data = _response_data(call)
            asset_id = params.get("asset_id", data.get("asset_id"))
            matching_prepares = [
                asset
                for asset in assets
                if asset.get("asset_id") == asset_id and asset["_prepare_seen"]
            ]
            candidates = [
                asset
                for asset in matching_prepares
                if asset["_put_seen"] and asset.get("complete_call_id") is None
            ]
            if len(candidates) > 1:
                warning = _warning(
                    "AMBIGUOUS_COMPLETE_ASSOCIATION",
                    "CompleteMediaUpload 对应多个已关联 PUT 的 Prepare，不能唯一选择。",
                    asset_id=asset_id,
                    complete_call_id=call.get("call_id"),
                    candidate_prepare_call_ids=[
                        asset.get("prepare_call_id") for asset in candidates
                    ],
                    candidate_put_call_ids=[
                        asset.get("put_call_id") for asset in candidates
                    ],
                )
                warnings.append(warning)
                continue
            if not candidates:
                has_associated_put = any(asset["_put_seen"] for asset in matching_prepares)
                warning_code = (
                    "ORPHAN_UPLOAD_COMPLETE"
                    if has_associated_put or not matching_prepares
                    else "COMPLETE_WITHOUT_ASSOCIATED_PUT"
                )
                warning = _warning(
                    warning_code,
                    (
                        "CompleteMediaUpload 发生时，对应 Prepare 尚未关联 PUT。"
                        if warning_code == "COMPLETE_WITHOUT_ASSOCIATED_PUT"
                        else "CompleteMediaUpload 无唯一且尚未关闭的 Prepare+PUT 链路。"
                    ),
                    asset_id=asset_id,
                    complete_call_id=call.get("call_id"),
                )
                warnings.append(warning)
                continue
            target = candidates[0]
            target["complete_call_id"] = call.get("call_id")
            target["complete_status"] = data.get("status")
            target["_complete_seen"] = True
            target["_complete_ok"] = _call_succeeded(call)

    used_asset_ids = _selected_asset_ids(calls, selected_task_id)
    return [
        _finalize_upload_asset(asset, used_asset_ids) for asset in assets
    ], warnings


def _normalized_text(value: object) -> str | None:
    """状态比较统一使用小写；原值由 status sample 的 raw_* 字段保留。"""
    return value.lower() if isinstance(value, str) else None


def _status_sample(call: dict) -> dict:
    """将一次 Poll 调用转换为不可去重的状态样本。"""
    data = _response_data(call)
    response = call.get("response") if isinstance(call.get("response"), dict) else None
    request = call.get("request") if isinstance(call.get("request"), dict) else None
    source = response or request or {}
    raw_status = data.get("status")
    raw_phase = data.get("phase")
    return {
        "call_id": call.get("call_id"),
        "timestamp": source.get("timestamp"),
        "status": _normalized_text(raw_status),
        "raw_status": raw_status,
        "phase": _normalized_text(raw_phase),
        "raw_phase": raw_phase,
        "progress_percent": data.get("progress_percent"),
        "retryable": data.get("retryable"),
        "error_code": data.get("error_code"),
        "create_time": data.get("create_time"),
        "completed_time": data.get("completed_time"),
        "expire_time": data.get("expire_time"),
        "line_start": source.get("line_start"),
        "line_end": source.get("line_end"),
    }


def _progress_diagnostics(samples: list[dict]) -> dict:
    """计算进度去重视图和相邻 Poll 停滞诊断，不删除原始样本。"""
    values = [sample.get("progress_percent") for sample in samples]
    distinct: list[object] = []
    for value in values:
        if value is not None and value not in distinct:
            distinct.append(value)

    unchanged_poll_count = sum(
        1
        for previous, current in zip(values, values[1:])
        if current is not None and current == previous
    )

    longest_value = None
    longest_run = 1
    current_value = None
    current_run = 0
    for value in values:
        if value is not None and value == current_value:
            current_run += 1
        else:
            current_value = value
            current_run = 1
        if value is not None and current_run > longest_run:
            longest_run = current_run
            longest_value = value

    return {
        "distinct_progress_values": distinct,
        "unchanged_poll_count": unchanged_poll_count,
        "longest_unchanged_progress": longest_value,
    }


def _timestamp_ms(value: object) -> datetime | None:
    """解析 parser 的本地 ISO 时间，仅用于同一日志内的毫秒差。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _duration_ms(create_call: dict | None, samples: list[dict]) -> int | None:
    """优先使用业务毫秒时间，缺失时回退到 Create→最后 Poll 日志时间。"""
    create_data = _response_data(create_call) if create_call is not None else {}
    create_time = create_data.get("create_time")
    if create_time is None and samples:
        create_time = samples[0].get("create_time")
    completed_time = samples[-1].get("completed_time") if samples else None
    if isinstance(create_time, (int, float)) and isinstance(
        completed_time, (int, float)
    ):
        return int(completed_time - create_time)

    if create_call is None or not samples:
        return None
    create_response = (
        create_call.get("response")
        if isinstance(create_call.get("response"), dict)
        else None
    )
    start = _timestamp_ms((create_response or {}).get("timestamp"))
    end = _timestamp_ms(samples[-1].get("timestamp"))
    if start is None or end is None:
        return None
    return int(round((end - start).total_seconds() * 1000))


def _task_type_from_calls(task_calls: list[dict]) -> str | None:
    """按 Create→Poll→Result 的证据优先级识别任务类型。"""
    for methods in (_CREATE_METHODS, _POLL_METHODS, _RESULT_METHODS):
        for call in task_calls:
            method = call.get("method_name")
            if method in methods:
                return methods[method]
    for call in task_calls:
        task_type = _response_data(call).get("task_type")
        if isinstance(task_type, str):
            return task_type
    return None


def build_task_snapshot(
    calls: list[dict], assets: list[dict], task_id: str
) -> tuple[dict, list[dict]]:
    """聚合一个任务的 Create、全部 Poll、Result 与上传资源。

    参数:
        calls: parser 输出的全部调用。
        assets: :func:`build_upload_assets` 生成的资源记录。
        task_id: 已由 :func:`select_dating_task` 选中的任务 ID。

    返回:
        ``(snapshot, warnings)``。Result 按原类型保留服务端 ``data.result``，
        并单独记录字段是否存在；只有 dict 类型的已知 v1 Result 才生成
        Schema 专属摘要，原始值本身不会被投影结果替换。
    """
    task_calls = [
        call
        for call in _gateway_calls(calls)
        if task_id in _call_task_ids(call)
    ]
    create_calls = [
        call for call in task_calls if call.get("method_name") in _CREATE_METHODS
    ]
    poll_calls = [
        call for call in task_calls if call.get("method_name") in _POLL_METHODS
    ]
    result_calls = [
        call for call in task_calls if call.get("method_name") in _RESULT_METHODS
    ]

    create_call = create_calls[0] if create_calls else None
    successful_results = [call for call in result_calls if _call_succeeded(call)]
    result_call = successful_results[-1] if successful_results else None
    task_type = _task_type_from_calls(task_calls)
    samples = [_status_sample(call) for call in poll_calls]

    create_data = _response_data(create_call) if create_call is not None else {}
    initial_status = _normalized_text(create_data.get("status"))
    if initial_status is None and samples:
        initial_status = samples[0].get("status")
    final_source = samples[-1] if samples else {
        "status": initial_status,
        "phase": _normalized_text(create_data.get("phase")),
        "progress_percent": create_data.get("progress_percent"),
        "retryable": create_data.get("retryable"),
        "error_code": create_data.get("error_code"),
    }
    final_status = final_source.get("status")
    terminal = final_status in _TERMINAL_STATUSES

    result_data = _response_data(result_call) if result_call is not None else {}
    result_payload_present = "result" in result_data
    result_payload = result_data["result"] if result_payload_present else None
    task_warnings: list[dict] = []
    schema_version = result_data.get("schema_version")
    if not isinstance(schema_version, str) and isinstance(result_payload, dict):
        nested_schema = result_payload.get("schema_version")
        if isinstance(nested_schema, str):
            schema_version = nested_schema
            task_warnings.append(
                _warning(
                    "OUTER_SCHEMA_VERSION_MISSING",
                    "Result 外层 data.schema_version 缺失，已使用内层版本",
                    call_id=result_call.get("call_id") if result_call else None,
                )
            )
        else:
            schema_version = None

    schema_status = None
    result_summary: dict = {}
    result_sections: list[dict] = []
    result_fields: list[dict] = []
    field_health: dict = {}
    known_paths: frozenset[str] | None = None
    required_paths: tuple[str, ...] = ()
    if schema_version == REPLY_SCHEMA_VERSION:
        schema_status = "KNOWN_SCHEMA"
        known_paths = REPLY_SCHEMA_PATHS
        required_paths = REPLY_REQUIRED_PATHS
        if isinstance(result_payload, dict):
            result_summary, result_sections = _project_reply_result(result_payload)
    elif schema_version == ANALYSIS_SCHEMA_VERSION:
        schema_status = "KNOWN_SCHEMA"
        known_paths = ANALYSIS_SCHEMA_PATHS
        required_paths = ANALYSIS_REQUIRED_PATHS
        if isinstance(result_payload, dict):
            result_summary, result_sections = _project_analysis_result(
                result_payload
            )
    elif result_call is not None:
        # 未知版本仍遍历原始 Result，但不给任何字段套用旧 Schema，也不生成
        # Reply/Analysis 专属摘要，避免版本升级后产生看似可信的错误投影。
        schema_status = "UNKNOWN_SCHEMA"
        known_paths = frozenset()
        task_warnings.append(
            _warning(
                "UNKNOWN_SCHEMA_VERSION",
                "Result schema_version 不在当前支持列表中",
                schema_version=schema_version,
                call_id=result_call.get("call_id"),
            )
        )

    if (
        result_call is not None
        and result_payload_present
        and known_paths is not None
    ):
        result_fields, field_warnings = build_field_index(
            result_payload,
            root_path="result",
            source=_result_block_source(result_call),
            known_paths=known_paths,
            required_paths=required_paths,
        )
        task_warnings.extend(field_warnings)
        field_health = _field_health(result_fields)

    snapshot = {
        "task_id": task_id,
        "task_type": task_type,
        "schema_version": schema_version,
        "schema_status": schema_status,
        "create_call_id": create_call.get("call_id") if create_call else None,
        "poll_call_ids": [call.get("call_id") for call in poll_calls],
        "result_call_id": result_call.get("call_id") if result_call else None,
        "input_assets": [asset for asset in assets if asset.get("used_by_task")],
        "lifecycle": {
            "initial_status": initial_status,
            "final_status": final_status,
            "final_phase": final_source.get("phase"),
            "final_progress_percent": final_source.get("progress_percent"),
            "poll_count": len(poll_calls),
            # 非终态日志只能报告最后已知状态，不能把“当前已耗时”伪装成
            # 服务端任务完成时长；终态时才允许业务时间或日志时间回退。
            "duration_ms": _duration_ms(create_call, samples) if terminal else None,
            "retryable": final_source.get("retryable"),
            "error_code": final_source.get("error_code"),
            "terminal": terminal,
        },
        "progress_diagnostics": _progress_diagnostics(samples),
        "status_samples": samples,
        "result_payload": result_payload,
        "result_payload_present": result_payload_present,
        "result_summary": result_summary,
        "result_sections": result_sections,
        "result_fields": result_fields,
        "field_health": field_health,
        "checks": [],
        "warnings": task_warnings,
    }
    return snapshot, task_warnings


def build_analysis_summary(
    calls: list[dict], task_snapshot: dict | None, warnings: list[dict]
) -> dict:
    """计算 PRD §19.3 的基础调用、错误、配对、任务和 warning 计数。"""
    result_classes = [call.get("result_class") for call in calls]
    checks = task_snapshot.get("checks", []) if task_snapshot else []
    return {
        "gateway_call_count": sum(
            call.get("transport") == "gateway" for call in calls
        ),
        "logical_interface_call_count": sum(
            call.get("transport") == "gateway" for call in calls
        ),
        "upload_call_count": sum(
            call.get("transport") == "object_storage_put" for call in calls
        ),
        "http_error_count": result_classes.count("http_error"),
        "gateway_error_count": result_classes.count("gateway_error"),
        "business_error_count": result_classes.count("business_error"),
        "unmatched_request_count": sum(call.get("request") is None for call in calls),
        "unmatched_response_count": sum(
            call.get("response") is None for call in calls
        ),
        "parse_warning_count": len(warnings),
        "task_count": 1 if task_snapshot is not None else 0,
        "result_count": int(
            bool(task_snapshot and task_snapshot.get("result_call_id"))
        ),
        "check_fail_count": sum(check.get("severity") == "FAIL" for check in checks),
        "check_warn_count": sum(check.get("severity") == "WARN" for check in checks),
        "check_unknown_count": sum(
            check.get("severity") == "UNKNOWN" for check in checks
        ),
    }


def build_interface_statistics(calls: list[dict]) -> list[dict]:
    """按 service_name + method_name 聚合调用数量、结果和耗时。"""
    groups: dict[tuple[object, object], list[dict]] = {}
    for call in calls:
        key = (call.get("service_name"), call.get("method_name"))
        groups.setdefault(key, []).append(call)

    statistics: list[dict] = []
    failure_classes = {
        "parse_error",
        "http_error",
        "gateway_error",
        "business_error",
    }
    for (service_name, method_name), grouped_calls in groups.items():
        http_status_counts: dict[str, int] = {}
        result_class_counts: dict[str, int] = {}
        elapsed_values: list[float] = []
        for call in grouped_calls:
            response = call.get("response")
            if isinstance(response, dict):
                status = response.get("http_status")
                if status is not None:
                    status_key = str(status)
                    http_status_counts[status_key] = http_status_counts.get(status_key, 0) + 1
                elapsed_ms = response.get("elapsed_ms")
                if isinstance(elapsed_ms, (int, float)):
                    elapsed_values.append(float(elapsed_ms))
            result_class = call.get("result_class")
            if isinstance(result_class, str):
                result_class_counts[result_class] = (
                    result_class_counts.get(result_class, 0) + 1
                )

        statistics.append(
            {
                "service_name": service_name,
                "method_name": method_name,
                "request_count": sum(
                    call.get("request") is not None for call in grouped_calls
                ),
                "response_count": sum(
                    call.get("response") is not None for call in grouped_calls
                ),
                "success_count": sum(
                    call.get("result_class") == "success" for call in grouped_calls
                ),
                "failure_count": sum(
                    call.get("result_class") in failure_classes
                    for call in grouped_calls
                ),
                "unresponded_count": sum(
                    call.get("request") is not None and call.get("response") is None
                    for call in grouped_calls
                ),
                "http_status_counts": http_status_counts,
                "result_class_counts": result_class_counts,
                "average_elapsed_ms": (
                    round(sum(elapsed_values) / len(elapsed_values), 2)
                    if elapsed_values
                    else None
                ),
                "max_elapsed_ms": round(max(elapsed_values), 2)
                if elapsed_values
                else None,
            }
        )
    return statistics


def analyze_dating_log(
    log_text: str, requested_task_id: str | None = None
) -> dict:
    """解析 Dating 日志并返回 Task 4 约定的基础确定性结构。

    参数:
        log_text: 原始接口日志文本。
        requested_task_id: 可选的显式任务 ID。

    返回:
        包含 parser 原始 calls/flow_steps/warnings、任务选择、上传资源、
        生命周期和基础统计的字典。函数不产生外部副作用。
    """
    parsed = parse_interface_log(log_text)
    calls = parsed["calls"]
    supported = any(
        call.get("method_name") in SUPPORTED_METHODS
        or call.get("transport") == "object_storage_put"
        for call in calls
    )
    selected_task_id, task_ids, selection_error = select_dating_task(
        calls, requested_task_id
    )
    warnings = list(parsed["parse_warnings"])
    assets, asset_warnings = build_upload_assets(calls, selected_task_id)
    warnings.extend(asset_warnings)

    task_snapshot = None
    if selected_task_id is not None:
        task_snapshot, task_warnings = build_task_snapshot(
            calls, assets, selected_task_id
        )
        warnings.extend(task_warnings)

    summary = build_analysis_summary(calls, task_snapshot, warnings)
    return {
        "analyzer_version": ANALYZER_VERSION,
        "parser_version": PARSER_VERSION,
        "supported": supported,
        "detected_domain": "dating" if supported else None,
        "selection_error": selection_error,
        "task_ids": task_ids,
        "summary": summary,
        "interface_statistics": build_interface_statistics(calls),
        "flow_steps": parsed["flow_steps"],
        "calls": calls,
        "task_snapshot": task_snapshot,
        "parse_warnings": warnings,
    }
