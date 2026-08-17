"""People Insight 检索日志规则审计、报告生成与 Evidence Packet（开发设计 §8~§10、§14，阶段 2）。

职责：
- 12 个纯函数检查规则，只读取任务快照，返回规则结果数组。
- 单条规则异常被捕获为 warning，不中断其他规则。
- 确定性 Markdown 报告（§14.1）。
- Evidence Packet 构建与脱敏（§9、§10）。
"""

from __future__ import annotations

import json
import re
import traceback
from urllib.parse import urlsplit

from people_search_analyzer import ANALYZER_VERSION, RULESET_VERSION

# ---------------------------------------------------------------------------
# 规则元数据
# ---------------------------------------------------------------------------

RULE_META = {
    "STATE-001": ("state", "P0", "GetTask 与 diagnosis 终态一致且符合业务结果"),
    "STATE-002": ("state", "P0", "全部 Provider 技术失败不能归类为普通 NO_MATCH"),
    "ROUTE-001": ("routing", "P0", "Local 可用命中后跳过 LLM、Wiki、PDL"),
    "ROUTE-002": ("routing", "P0", "Public Figure 条件成立且主结果不足时 Wiki 在 PDL 前"),
    "ROUTE-003": ("routing", "P0", "Wiki 唯一可靠结果后跳过 PDL"),
    "ROUTE-004": ("routing", "P0", "Wiki 歧义后允许 PDL，且歧义信息不应静默丢失"),
    "LLM-001": ("llm", "P0", "LLM 完整、截断、失败和无结果分类一致"),
    "LLM-002": ("llm", "P0", "截断时存在 finish_reason、token、可恢复候选和重试诊断"),
    "PDL-001": ("pdl", "P0", "显示实际调用 Identify 或 Search，不混用统计字段"),
    "PDL-002": ("pdl", "P1", "PDL 候选 decision/selected 与最终候选质量一致"),
    "SOCIAL-001": ("social", "P0", "输入 Social Link 有 CALLED 或明确 skip reason"),
    "SOCIAL-002": ("social", "P1", "Provider 新发现受支持 URL 有调用或明确跳过原因"),
    "SOCIAL-003": ("social", "P0", "同一 canonical URL 最多一次真实调用"),
    "SOCIAL-004": ("social", "P0", "Social 成功结果与候选合并统计和最终来源一致"),
    "IMAGE-001": ("image", "P1", "用户图片触发反查或存在明确未规划原因"),
    "IMAGE-002": ("image", "P0", "Reverse Image 主工具和 fallback 顺序一致"),
    "FACE-001": ("face", "P0", "未执行 Face Comparison 不解释为 0% 或不匹配；未接入期间展示为「已知能力缺失」，不计为任务异常"),
    "CAND-001": ("candidate", "P0", "candidate_count、top score 与候选列表一致"),
    "CAND-002": ("candidate", "P0", "score/confidence/decision/selected 不矛盾"),
    "CAND-003": ("candidate", "P1", "matched_clue_types 在 Debug、List、Detail 中一致"),
    "CAND-004": ("candidate", "P1", "相同稳定标识的跨 Provider 候选不重复"),
    "COST-001": ("cost", "P0", "分项、阶段与任务总成本一致"),
    "COST-002": ("cost", "P0", "UNPRICED 不作为免费，缓存调用不重复计费"),
    "STOP-001": ("stop", "P0", "人物链路停止原因与业务结果语义一致"),
}

TERMINAL_STATUSES = ("SUCCEEDED", "PARTIAL_SUCCEEDED", "NO_RESULT", "FAILED")

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _ev(method, json_path, value, line_start=None, line_end=None):
    """构建证据引用。"""
    return {
        "method": method,
        "json_path": json_path,
        "value": value,
        "line_start": line_start,
        "line_end": line_end,
    }


def _result(rule_id, outcome, actual="", expected="", evidence=None):
    """构建规则结果。"""
    category, severity, title = RULE_META[rule_id]
    return {
        "rule_id": rule_id,
        "category": category,
        "outcome": outcome,
        "severity": severity,
        "title": title,
        "actual": actual,
        "expected": expected,
        "evidence": evidence or [],
    }


def _pass(rule_id, actual="", evidence=None):
    return _result(rule_id, "PASS", actual, "", evidence)


def _fail(rule_id, actual, expected, evidence=None):
    return _result(rule_id, "FAIL", actual, expected, evidence)


def _warn(rule_id, actual, evidence=None):
    return _result(rule_id, "WARN", actual, "", evidence)


def _unknown(rule_id, actual, evidence=None):
    return _result(rule_id, "UNKNOWN", actual, "", evidence)


def _na(rule_id, actual="", evidence=None):
    return _result(rule_id, "NOT_APPLICABLE", actual, "", evidence)


def _get_debug(snapshot):
    return snapshot.get("debug") or {}


def _get_diagnosis(snapshot):
    return snapshot.get("diagnosis") or {}


def _get_timeline(snapshot):
    return snapshot.get("timeline") or []


def _get_get_task_data(snapshot):
    return snapshot.get("get_task_data") or {}


def _get_create_request(snapshot):
    return snapshot.get("create_request") or {}


def _extract_clue_values(create_request):
    """从 CreateIntentTask 请求中提取紧凑的线索值摘要（§10.2）。

    邮箱和电话保留原值（评审确认允许发送给模型）。
    """
    if not isinstance(create_request, dict):
        return []
    clues = create_request.get("clues")
    if not isinstance(clues, list):
        return []
    values = []
    for clue in clues:
        if not isinstance(clue, dict):
            continue
        ctype = clue.get("type", "")
        if ctype == "FULL_NAME":
            nq = clue.get("full_name_query")
            if isinstance(nq, dict) and nq.get("full_name"):
                values.append({"type": "FULL_NAME", "value": nq["full_name"]})
        elif ctype == "EMAIL":
            eq = clue.get("email_query")
            if isinstance(eq, dict) and eq.get("email"):
                values.append({"type": "EMAIL", "value": eq["email"]})
        elif ctype == "PHONE":
            pq = clue.get("phone_query")
            if isinstance(pq, dict) and pq.get("phone"):
                values.append({"type": "PHONE", "value": pq["phone"]})
        elif ctype == "SOCIAL_LINK":
            sq = clue.get("social_link_query")
            if isinstance(sq, dict) and sq.get("url"):
                values.append({"type": "SOCIAL_LINK", "value": sq["url"]})
    return values


def _get_cost(snapshot):
    return snapshot.get("cost") or {}


def _extract_cost_total(cost):
    """从 cost summary 提取总成本，兼容夹具和真实日志格式。

    - 夹具：total_estimated_cost_microunit（int，含 0）
    - 真实日志：totals 为 list，按 currency 汇总 total_cost_microunit
    - 旧格式：totals 为 dict，取 estimated_cost_microunit
    """
    total = cost.get("total_estimated_cost_microunit")
    if total is not None:
        return total
    totals = cost.get("totals")
    if isinstance(totals, list):
        return sum(
            int(t.get("total_cost_microunit", 0) or 0)
            for t in totals
            if isinstance(t, dict) and str(t.get("total_cost_microunit", "")).isdigit()
        ) or None
    if isinstance(totals, dict):
        return totals.get("estimated_cost_microunit")
    return None


def _cost_totals_by_currency(cost):
    """返回按币种分组的成本总额，避免跨币种直接相加。"""
    totals = cost.get("totals")
    if not isinstance(totals, list):
        return []
    result = []
    for item in totals:
        if not isinstance(item, dict):
            continue
        result.append({
            "currency": item.get("currency") or "UNSPECIFIED",
            "total_cost_microunit": item.get("total_cost_microunit", 0),
            "cost_complete": item.get("cost_complete"),
            "unpriced_call_count": item.get("unpriced_call_count", 0),
        })
    return result


def _get_candidates(snapshot):
    return snapshot.get("candidates") or []


def _get_candidate_details(snapshot):
    return snapshot.get("candidate_details") or []


def _get_debug_candidates(snapshot):
    debug = _get_debug(snapshot)
    cands = debug.get("candidates")
    return cands if isinstance(cands, list) else []


def _get_social_url_queue(snapshot):
    debug = _get_debug(snapshot)
    queue = debug.get("social_url_queue")
    if not isinstance(queue, list):
        queue = _get_diagnosis(snapshot).get("social_profile_queue_decisions")
    if not isinstance(queue, list):
        return []
    normalized = []
    for item in queue:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry.setdefault("url", item.get("raw_url") or item.get("canonical_url"))
        if not entry.get("origin") and item.get("discovered_by"):
            entry["origin"] = "provider_discovery"
        normalized.append(entry)
    return normalized


def _provider_is(call, provider_kind):
    """兼容夹具旧名称和 QueryChainLogger 真实 Provider/operation 名称。"""
    provider = str(call.get("provider") or "").lower()
    operation = str(call.get("operation") or "").lower()
    if provider_kind == "llm":
        return provider.startswith("llm_search")
    if provider_kind == "wiki":
        return provider == "wiki_remote" or (
            provider == "public_figure" and operation == "remote_lookup"
        )
    if provider_kind == "local":
        return provider == "public_figure_local" or (
            provider == "public_figure" and operation == "local_lookup"
        )
    if provider_kind == "pdl":
        return provider == "people_data_labs"
    if provider_kind == "social":
        return "social" in provider
    return False


def _pdl_operation_kind(call):
    """将 person_search_profile 等真实操作名归一为 identify/search。"""
    operation = str(call.get("operation") or "").lower()
    if operation.startswith("person_identify"):
        return "identify"
    if operation.startswith("person_search"):
        return "search"
    details = call.get("result_details") or {}
    if details.get("pdl_identify_call_count", 0) > 0:
        return "identify"
    if details.get("pdl_person_search_call_count", 0) > 0:
        return "search"
    return None


def _is_reverse_image_call(call):
    """识别真实 Lens/Vision Provider 与旧夹具的统一图片反查调用。"""
    provider = str(call.get("provider") or "").lower()
    operation = str(call.get("operation") or "").lower()
    return (
        operation in {"reverse_image_search", "google_lens_search", "web_detection"}
        or "google_lens" in provider
        or provider in {"google_vision", "bing_visual_search", "tineye"}
    )


def _canonical_social_url(value):
    """生成只用于队列比对的稳定社交 URL，不修改报告中的原始证据。"""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    if "://" not in text:
        text = "https://" + text
    parsed = urlsplit(text)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    return f"{host}{path}"


def _has_coverage(snapshot, *keys):
    cov = snapshot.get("coverage") or {}
    return all(cov.get(k) for k in keys)


def _debug_evidence(snapshot, json_path, value):
    """从 source_records 中找到 GetSearchTaskDebug 的行号范围。"""
    for record in snapshot.get("source_records") or []:
        if record.get("method") == "GetSearchTaskDebug" and record.get("direction") == "response":
            return _ev("GetSearchTaskDebug", json_path, value,
                       record.get("start_line"), record.get("end_line"))
    return _ev("GetSearchTaskDebug", json_path, value)


def _get_task_evidence(snapshot, json_path, value):
    for record in snapshot.get("source_records") or []:
        if record.get("method") == "GetTask" and record.get("direction") == "response":
            if record.get("parse_status") == "PARSED":
                return _ev("GetTask", json_path, value,
                           record.get("start_line"), record.get("end_line"))
    return _ev("GetTask", json_path, value)


# ---------------------------------------------------------------------------
# 检查函数（§8.2）
# ---------------------------------------------------------------------------


def check_terminal_status(snapshot):
    """STATE-001: 终态字段一致，且业务结果与终态语义一致。"""
    results = []
    if not _has_coverage(snapshot, "get_task", "debug"):
        return [_unknown("STATE-001", "缺少 GetTask 或 Debug 证据")]
    get_task_status = _get_get_task_data(snapshot).get("status")
    diag_status = _get_diagnosis(snapshot).get("final_status")
    if get_task_status is None or diag_status is None:
        return [_unknown("STATE-001", f"GetTask status={get_task_status}, diagnosis final_status={diag_status}")]
    get_task = _get_get_task_data(snapshot)
    diagnosis = _get_diagnosis(snapshot)
    candidate_count = get_task.get("candidate_count")
    result_type = str(get_task.get("result_type") or "").lower()
    no_result_reason = get_task.get("no_result_reason") or ""
    stop_reason = diagnosis.get("stop_reason") or ""
    exhausted_without_match = (
        candidate_count == 0
        and result_type in {"none", "no_result"}
        and stop_reason in {"PROVIDERS_EXHAUSTED_NO_MATCH", "NO_MATCH"}
    )
    if get_task_status == diag_status and get_task_status == "SUCCEEDED" and exhausted_without_match:
        return [_fail(
            "STATE-001",
            "0 个候选且所有 Provider 均无匹配，但 GetTask/diagnosis 仍为 SUCCEEDED，"
            f"no_result_reason={no_result_reason!r}, status_consistent={diagnosis.get('status_consistent')}",
            "业务终态应为 NO_RESULT，no_result_reason=NO_MATCH；Report Ready 不应改写检索结果终态",
            [
                _get_task_evidence(snapshot, "data.status", get_task_status),
                _get_task_evidence(snapshot, "data.candidate_count", candidate_count),
                _get_task_evidence(snapshot, "data.no_result_reason", no_result_reason),
                _debug_evidence(snapshot, "debug.diagnosis.stop_reason", stop_reason),
            ],
        )]
    if get_task_status == diag_status:
        return [_pass("STATE-001", f"GetTask status={get_task_status} = diagnosis final_status={diag_status}，业务结果未见冲突")]
    return [_fail(
        "STATE-001",
        f"GetTask status={get_task_status} ≠ diagnosis final_status={diag_status}",
        "两者一致",
        [_get_task_evidence(snapshot, "data.status", get_task_status),
         _debug_evidence(snapshot, "debug.diagnosis.final_status", diag_status)],
    )]


def check_state_002(snapshot):
    """STATE-002: 全部 Provider 技术失败不能归类为普通 NO_MATCH。"""
    results = []
    if not _has_coverage(snapshot, "get_task", "debug"):
        return [_unknown("STATE-002", "缺少 GetTask 或 Debug 证据")]
    timeline = _get_timeline(snapshot)
    if not timeline:
        return [_na("STATE-002", "无 agent_tool_calls")]
    provider_calls = [
        call for call in timeline
        if any(_provider_is(call, kind) for kind in ("llm", "wiki", "local", "pdl", "social"))
    ]
    if not provider_calls:
        return [_na("STATE-002", "无可识别 Provider 调用")]
    all_error = all(call.get("status") == "error" for call in provider_calls)
    if not all_error:
        return [_pass("STATE-002", f"非全部失败（{sum(1 for c in timeline if c.get('status') == 'error')}/{len(timeline)} error）")]
    get_task = _get_get_task_data(snapshot)
    stop_reason = get_task.get("stop_reason", "")
    if stop_reason == "NO_MATCH":
        return [_fail(
            "STATE-002",
            f"全部 Provider 技术失败但 stop_reason=NO_MATCH",
            "应归类为 PROVIDER_TECHNICAL_FAILURE 或类似",
            [_get_task_evidence(snapshot, "data.stop_reason", stop_reason),
             _debug_evidence(snapshot, "debug.agent_tool_calls", f"{len(timeline)} calls all error")],
        )]
    return [_pass("STATE-002", f"全部失败且 stop_reason={stop_reason}（非 NO_MATCH）")]


def check_public_figure_route(snapshot):
    """ROUTE-001~004: Public Figure 路由规则。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        results.append(_unknown("ROUTE-001", "缺少 Debug 证据"))
        results.append(_unknown("ROUTE-002", "缺少 Debug 证据"))
        results.append(_unknown("ROUTE-003", "缺少 Debug 证据"))
        results.append(_unknown("ROUTE-004", "缺少 Debug 证据"))
        return results
    diag = _get_diagnosis(snapshot)
    timeline = _get_timeline(snapshot)
    local_value = diag.get("public_figure_local_hit")
    if local_value is None:
        local_value = diag.get("public_figure_local")
    local_hit = local_value is True or str(local_value).lower() in {
        "hit", "success", "usable", "selected"
    }
    negative_cache_hit = (
        diag.get("local_negative_cache_hit") is True
        or diag.get("public_figure_local_negative_cache_hit") is True
        or str(local_value).lower() in {"negative_cache", "negative_cache_hit"}
    )
    policy_version = snapshot.get("policy_version") or _get_debug(snapshot).get("policy_version")
    usable_count = diag.get("public_figure_remote_usable_count", 0)
    ambiguous = diag.get("public_figure_remote_ambiguous", False)
    pdl_identify = diag.get("pdl_identify_call_count", 0)
    pdl_search = diag.get("pdl_person_search_call_count", 0)
    pdl_timeline = [c for c in timeline if _provider_is(c, "pdl")]
    pdl_called = pdl_identify > 0 or pdl_search > 0 or bool(pdl_timeline)
    llm_called = diag.get("llm_search_call_count", 0) > 0 or any(
        _provider_is(c, "llm") for c in timeline
    )
    wiki_calls = [c for c in timeline if _provider_is(c, "wiki")]

    # ROUTE-001: Local 可用命中后跳过 LLM、Wiki、PDL
    if negative_cache_hit and not policy_version:
        # negative cache 的跳过策略可能随规则版本变化；版本未知时不能硬判对错。
        results.append(_warn(
            "ROUTE-001",
            "命中 Local negative cache，但缺少 policy_version，跳过策略需要确认",
            [_debug_evidence(snapshot, "debug.policy_version", policy_version)],
        ))
    elif local_hit:
        skipped = not llm_called and not wiki_calls and not pdl_called
        if skipped:
            results.append(_pass("ROUTE-001", "Local 命中后 LLM/Wiki/PDL 均未调用"))
        else:
            called = []
            if llm_called:
                called.append("LLM")
            if wiki_calls:
                called.append("Wiki")
            if pdl_called:
                called.append("PDL")
            results.append(_fail(
                "ROUTE-001",
                f"Local 命中后仍调用了 {', '.join(called)}",
                "跳过 LLM、Wiki、PDL",
                [_debug_evidence(snapshot, "debug.diagnosis.public_figure_local_hit", True)],
            ))
    else:
        results.append(_na("ROUTE-001", "非 Local 命中场景"))

    # ROUTE-002: Public Figure 条件成立且主结果不足时 Wiki 在 PDL 前。
    # 是否需要 fallback 由实际 Wiki/PDL 调用或 public_figure_eligible 证明，不能
    # 用 Wiki 最终 usable_count>0 作为前置条件，否则 Wiki 无结果场景会被漏检。
    # timeline 已按解析后的 start_time 升序排序，直接用列表位置比较先后，
    # 避免原始时间戳缺失（None）或格式混杂导致比较异常（审查修复）。
    wiki_positions = [i for i, c in enumerate(timeline) if _provider_is(c, "wiki")]
    pdl_positions = [i for i, c in enumerate(timeline) if _provider_is(c, "pdl")]
    public_figure_eligible = diag.get("public_figure_eligible") is True
    route_applicable = not local_hit and (
        public_figure_eligible or bool(wiki_positions)
    )
    if route_applicable and not ambiguous:
        if wiki_positions and pdl_positions:
            if min(wiki_positions) < min(pdl_positions):
                results.append(_pass("ROUTE-002", "Wiki 在 PDL 之前调用"))
            else:
                results.append(_fail(
                    "ROUTE-002",
                    "PDL 在 Wiki 之前调用",
                    "Wiki 应在 PDL 前",
                    [_debug_evidence(snapshot, "debug.diagnosis.public_figure_remote_usable_count", usable_count)],
                ))
        elif wiki_positions and not pdl_positions:
            results.append(_pass("ROUTE-002", "Wiki 调用且 PDL 未调用"))
        elif not wiki_positions and pdl_positions:
            results.append(_warn("ROUTE-002", "有 PDL 但无 Wiki 调用记录"))
        else:
            results.append(_na("ROUTE-002", "无 Wiki 和 PDL 调用"))
    elif route_applicable and ambiguous:
        results.append(_na("ROUTE-002", "Wiki 歧义场景，由 ROUTE-004 覆盖"))
    else:
        results.append(_na("ROUTE-002", "非 Public Figure remote 场景"))

    # ROUTE-003: Wiki 唯一可靠结果后跳过 PDL
    if not local_hit and usable_count == 1 and not ambiguous:
        if pdl_called:
            results.append(_fail(
                "ROUTE-003",
                f"Wiki 唯一可靠命中(usable_count=1)后仍调用 PDL(identify={pdl_identify}, search={pdl_search})",
                "跳过 PDL",
                [_debug_evidence(snapshot, "debug.diagnosis.public_figure_remote_usable_count", 1),
                 _debug_evidence(snapshot, "debug.diagnosis.pdl_identify_call_count", pdl_identify)],
            ))
        else:
            results.append(_pass("ROUTE-003", "Wiki 唯一可靠命中后 PDL 未调用"))
    else:
        results.append(_na("ROUTE-003", "非 Wiki 唯一可靠命中场景"))

    # ROUTE-004: Wiki 歧义后允许 PDL，且歧义信息不应静默丢失
    if ambiguous:
        debug = _get_debug(snapshot)
        wiki_calls_raw = [
            c for c in debug.get("agent_tool_calls", [])
            if isinstance(c, dict) and _provider_is(c, "wiki")
        ]
        has_ambiguity_info = any(
            c.get("ambiguous") or c.get("ambiguous_entities")
            for c in wiki_calls_raw if isinstance(c, dict)
        )
        if has_ambiguity_info:
            if pdl_called:
                results.append(_pass("ROUTE-004", "Wiki 歧义后调用 PDL fallback，歧义信息已记录"))
            else:
                results.append(_pass("ROUTE-004", "Wiki 歧义但未调用 PDL，歧义信息已记录"))
        else:
            results.append(_fail(
                "ROUTE-004",
                "Wiki 歧义但歧义信息缺失",
                "歧义信息不应静默丢失",
                [_debug_evidence(snapshot, "debug.diagnosis.public_figure_remote_ambiguous", True)],
            ))
    else:
        results.append(_na("ROUTE-004", "非 Wiki 歧义场景"))

    return results


def check_llm_output(snapshot):
    """LLM-001: LLM 完整、截断、失败和无结果分类一致。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        return [_unknown("LLM-001", "缺少 Debug 证据")]
    diag = _get_diagnosis(snapshot)
    timeline = _get_timeline(snapshot)
    llm_calls = [c for c in timeline if _provider_is(c, "llm")]
    llm_call_count = diag.get("llm_search_call_count")
    if llm_call_count is None:
        llm_call_count = diag.get("llm_http_attempt_count")
    if llm_call_count is None:
        llm_call_count = len(llm_calls)
    raw_status = diag.get("llm_result_status") or diag.get("llm_output_status") or "not_called"
    status_aliases = {
        "LLM_OUTPUT_COMPLETE": "complete",
        "LLM_OUTPUT_TRUNCATED": "truncated",
        "LLM_OUTPUT_NO_RESULT": "no_result",
        "LLM_OUTPUT_ERROR": "error",
    }
    llm_result_status = status_aliases.get(raw_status, str(raw_status).lower())
    if raw_status == "LLM_OUTPUT_COMPLETE" and llm_calls:
        final_call_status = str(llm_calls[-1].get("status") or "").lower()
        if final_call_status in {"no_result", "error"}:
            llm_result_status = final_call_status
    if llm_call_count == 0:
        return [_na("LLM-001", "LLM 未调用")]
    if not llm_calls:
        return [_unknown("LLM-001", f"diagnosis 记录 llm_call_count={llm_call_count} 但 timeline 无 LLM 调用")]
    # 检查 result_class 与 diagnosis.llm_result_status 一致性。
    # timeline 已按 start_time 升序排序，用其顺序判断“最后一次调用”；
    # 原始 agent_tool_calls 数组顺序不可靠（真实日志常倒序返回）（审查修复）。
    result_classes = []
    for call in llm_calls:
        result_class = call.get("result_class")
        if not result_class:
            status = str(call.get("status") or "").lower()
            if status in {"success", "complete"}:
                result_class = "complete"
            elif status in {"no_result", "error", "truncated"}:
                result_class = status
        if result_class:
            result_classes.append(result_class)
    # diagnosis.llm_result_status 应反映最后一次 LLM 调用的状态
    last_class = result_classes[-1] if result_classes else None
    if last_class and last_class == llm_result_status:
        return [_pass("LLM-001", f"LLM result_class={last_class} 与 diagnosis.llm_result_status={llm_result_status} 一致")]
    elif last_class and last_class != llm_result_status:
        # truncated 后重试成功，diagnosis 记录最终状态为 complete
        if llm_result_status == "complete" and "truncated" in result_classes:
            return [_pass("LLM-001", f"截断后重试成功，最终 llm_result_status={llm_result_status}")]
        return [_fail(
            "LLM-001",
            f"LLM result_class={last_class} ≠ diagnosis.llm_result_status={llm_result_status}",
            "分类一致",
            [_debug_evidence(snapshot, "debug.diagnosis.llm_result_status", llm_result_status)],
        )]
    return [_warn("LLM-001", f"无法验证 LLM 分类一致性（result_classes={result_classes}）")]


def check_llm_truncation(snapshot):
    """LLM-002: 截断时存在 finish_reason、token、可恢复候选和重试诊断。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        return [_unknown("LLM-002", "缺少 Debug 证据")]
    debug = _get_debug(snapshot)
    raw_calls = [
        c for c in debug.get("agent_tool_calls", [])
        if isinstance(c, dict) and c.get("provider") == "llm_search"
    ]
    truncated_calls = [c for c in raw_calls if c.get("result_class") == "truncated" or c.get("finish_reason") == "length"]
    if not truncated_calls:
        return [_na("LLM-002", "无 LLM 截断调用")]
    missing = []
    for call in truncated_calls:
        if not call.get("finish_reason"):
            missing.append("finish_reason")
        if not call.get("token_usage"):
            missing.append("token_usage")
        if call.get("recoverable_candidate_count") is None:
            missing.append("recoverable_candidate_count")
    diag = _get_diagnosis(snapshot)
    recovery = diag.get("llm_truncation_recovery")
    if not recovery:
        missing.append("llm_truncation_recovery")
    if missing:
        return [_fail(
            "LLM-002",
            f"截断调用缺少: {', '.join(missing)}",
            "finish_reason、token_usage、recoverable_candidate_count、llm_truncation_recovery",
            [_debug_evidence(snapshot, "debug.agent_tool_calls", f"{len(truncated_calls)} truncated calls")],
        )]
    return [_pass("LLM-002", "截断调用包含 finish_reason、token、可恢复候选和重试诊断")]


def check_pdl_fallback(snapshot):
    """PDL-001: 显示实际调用 Identify 或 Search，不混用统计字段。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        return [_unknown("PDL-001", "缺少 Debug 证据")]
    diag = _get_diagnosis(snapshot)
    identify_count = diag.get("pdl_identify_call_count", 0)
    search_count = diag.get("pdl_person_search_call_count", 0)
    if identify_count == 0 and search_count == 0:
        return [_na("PDL-001", "PDL 未调用")]
    timeline = _get_timeline(snapshot)
    pdl_calls = [c for c in timeline if _provider_is(c, "pdl")]
    pdl_ops = set(c.get("operation") for c in pdl_calls if c.get("operation"))
    # 验证 diagnosis 计数与 timeline 调用一致
    timeline_identify = sum(1 for c in pdl_calls if _pdl_operation_kind(c) == "identify")
    timeline_search = sum(1 for c in pdl_calls if _pdl_operation_kind(c) == "search")
    if timeline_identify == identify_count and timeline_search == search_count:
        return [_pass("PDL-001", f"Identify={identify_count}, Search={search_count}，diagnosis 与 timeline 一致")]
    return [_warn(
        "PDL-001",
        f"diagnosis identify={identify_count} search={search_count} vs timeline identify={timeline_identify} search={timeline_search}",
        evidence=[_debug_evidence(snapshot, "debug.diagnosis.pdl_identify_call_count", identify_count)],
    )]


def check_pdl_candidate_quality(snapshot):
    """PDL-002: PDL 候选 decision/selected 与最终候选质量一致。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        return [_unknown("PDL-002", "缺少 Debug 证据")]
    debug_candidates = _get_debug_candidates(snapshot)
    pdl_candidates = [c for c in debug_candidates if isinstance(c, dict) and c.get("provider") == "people_data_labs"]
    if not pdl_candidates:
        return [_na("PDL-002", "无 PDL 候选")]
    list_candidates = _get_candidates(snapshot)
    pdl_list_ids = {c.get("candidate_id") for c in list_candidates if c.get("source_provider") == "people_data_labs"}
    issues = []
    for dc in pdl_candidates:
        decision = dc.get("decision")
        selected = dc.get("selected")
        cid = dc.get("candidate_id")
        # decision=SELECTED 应 selected=true；UNRESOLVED/REJECTED 应 selected=false
        if decision == "SELECTED" and not selected:
            issues.append(f"{cid}: decision=SELECTED 但 selected=false")
        if decision in ("UNRESOLVED", "REJECTED") and selected:
            issues.append(f"{cid}: decision={decision} 但 selected=true")
        # SELECTED 候选应在 List 中出现
        if decision == "SELECTED" and cid and cid not in pdl_list_ids:
            issues.append(f"{cid}: decision=SELECTED 但未出现在候选列表")
    if issues:
        return [_fail(
            "PDL-002",
            "; ".join(issues),
            "decision/selected 与候选列表一致",
            [_debug_evidence(snapshot, "debug.candidates", f"{len(pdl_candidates)} PDL candidates")],
        )]
    return [_pass("PDL-002", f"{len(pdl_candidates)} 个 PDL 候选 decision/selected 一致")]


def check_social_profile_queue(snapshot):
    """SOCIAL-001~004: Social Profile 队列与合并规则。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        for rid in ("SOCIAL-001", "SOCIAL-002", "SOCIAL-003", "SOCIAL-004"):
            results.append(_unknown(rid, "缺少 Debug 证据"))
        return results
    create_req = _get_create_request(snapshot)
    queue = _get_social_url_queue(snapshot)
    timeline = _get_timeline(snapshot)
    diag = _get_diagnosis(snapshot)
    debug_candidates = _get_debug_candidates(snapshot)
    list_candidates = _get_candidates(snapshot)

    # 提取输入 Social Link
    input_urls = set()
    clues = create_req.get("clues") if isinstance(create_req, dict) else None
    if isinstance(clues, list):
        for clue in clues:
            if isinstance(clue, dict) and clue.get("type") == "SOCIAL_LINK":
                sq = clue.get("social_link_query")
                if isinstance(sq, dict) and sq.get("url"):
                    input_urls.add(sq["url"])

    # SOCIAL-001: 输入 Social Link 有 CALLED 或明确 skip reason
    if not input_urls:
        results.append(_na("SOCIAL-001", "无输入 Social Link"))
    else:
        issues = []
        for url in input_urls:
            canonical_input = _canonical_social_url(url)
            matched = [
                q for q in queue
                if isinstance(q, dict)
                and canonical_input in {
                    _canonical_social_url(q.get("url")),
                    _canonical_social_url(q.get("canonical_url")),
                }
            ]
            if not matched:
                issues.append(f"输入 URL {url} 不在队列中")
            else:
                for q in matched:
                    decision = q.get("decision")
                    skip_reason = q.get("skip_reason", "")
                    if decision not in ("CALLED", "DEDUPED", "SKIPPED") or (decision in ("DEDUPED", "SKIPPED") and not skip_reason):
                        issues.append(f"URL {url}: decision={decision}, skip_reason={skip_reason!r}")
        if issues:
            results.append(_fail(
                "SOCIAL-001",
                "; ".join(issues),
                "输入 Social Link 有 CALLED 或明确 skip reason",
                [_debug_evidence(snapshot, "debug.social_url_queue", f"{len(queue)} entries")],
            ))
        else:
            results.append(_pass("SOCIAL-001", f"{len(input_urls)} 个输入 Social Link 均有明确决策"))

    # SOCIAL-002: Provider 新发现受支持 URL 有调用或明确跳过原因
    discovered = [
        q for q in queue
        if isinstance(q, dict) and q.get("origin") == "provider_discovery"
    ]
    if not discovered:
        results.append(_na("SOCIAL-002", "无 Provider 新发现 URL"))
    else:
        issues = []
        for q in discovered:
            decision = q.get("decision")
            skip_reason = q.get("skip_reason", "")
            if decision not in ("CALLED", "DEDUPED", "SKIPPED") or (decision in ("DEDUPED", "SKIPPED") and not skip_reason):
                issues.append(f"URL {q.get('url')}: decision={decision}, skip_reason={skip_reason!r}")
        if issues:
            results.append(_fail(
                "SOCIAL-002",
                "; ".join(issues),
                "新发现 URL 有调用或明确跳过原因",
                [_debug_evidence(snapshot, "debug.social_url_queue", f"{len(discovered)} discovered")],
            ))
        else:
            results.append(_pass("SOCIAL-002", f"{len(discovered)} 个新发现 URL 均有明确决策"))

    # SOCIAL-003: 同一 canonical URL 最多一次真实调用
    called_urls = {}
    for q in queue:
        if isinstance(q, dict) and q.get("decision") == "CALLED":
            canonical = q.get("canonical_url", q.get("url"))
            called_urls[canonical] = called_urls.get(canonical, 0) + 1
    duplicates = {url: count for url, count in called_urls.items() if count > 1}
    if duplicates:
        results.append(_fail(
            "SOCIAL-003",
            f"重复调用: {duplicates}",
            "同一 canonical URL 最多一次真实调用",
            [_debug_evidence(snapshot, "debug.social_url_queue", f"{len(queue)} entries")],
        ))
    else:
        social_calls = [c for c in timeline if _provider_is(c, "social")]
        call_count_ok = len(social_calls) == sum(called_urls.values())
        if call_count_ok or not social_calls:
            results.append(_pass("SOCIAL-003", f"{len(called_urls)} 个 canonical URL 调用 {sum(called_urls.values())} 次，无重复"))
        else:
            results.append(_warn("SOCIAL-003", f"队列调用 {sum(called_urls.values())} 次 vs timeline social 调用 {len(social_calls)} 次"))

    # SOCIAL-004: Social 成功结果与候选合并统计和最终来源一致
    social_success_count = sum(
        1 for c in timeline
        if _provider_is(c, "social") and c.get("status") == "success"
    )
    merged_count = diag.get("social_profile_merged_candidate_count", 0)
    if social_success_count == 0:
        results.append(_na("SOCIAL-004", "无 Social 成功调用"))
    elif merged_count > 0 and any(
        isinstance(c, dict) and any(
            marker in str(provider).lower()
            for provider in ([c.get("source_provider")] + list(c.get("source_providers") or []))
            for marker in ("social", "scrapecreators")
        )
        for c in list_candidates
    ):
        results.append(_pass("SOCIAL-004", f"Social 成功 {social_success_count}，合并 {merged_count} 候选，候选列表含 social 来源"))
    else:
        results.append(_fail(
            "SOCIAL-004",
            f"Social 成功调用 {social_success_count} 但 merged_candidate_count={merged_count}，候选列表无 social 来源",
            "成功结果应与合并统计和最终来源一致",
            [_debug_evidence(snapshot, "debug.diagnosis.social_profile_merged_candidate_count", merged_count)],
        ))

    return results


def check_reverse_image_route(snapshot):
    """IMAGE-001~002: 图片反查路由规则。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        results.append(_unknown("IMAGE-001", "缺少 Debug 证据"))
        results.append(_unknown("IMAGE-002", "缺少 Debug 证据"))
        return results
    create_req = _get_create_request(snapshot)
    diag = _get_diagnosis(snapshot)
    timeline = _get_timeline(snapshot)

    # 检测是否有图片输入
    has_photo = False
    clues = create_req.get("clues") if isinstance(create_req, dict) else None
    if isinstance(clues, list):
        for clue in clues:
            if isinstance(clue, dict) and clue.get("type") == "PHOTO":
                has_photo = True
                break
            pq = clue.get("photo_query") if isinstance(clue, dict) else None
            if isinstance(pq, dict) and pq.get("photo_url"):
                has_photo = True
                break

    # IMAGE-001: 用户图片触发反查或存在明确未规划原因
    if not has_photo:
        results.append(_na("IMAGE-001", "无用户图片输入"))
    else:
        reverse_calls = [c for c in timeline if _is_reverse_image_call(c)]
        reverse_diag = diag.get("reverse_image")
        if reverse_calls:
            results.append(_pass("IMAGE-001", f"图片输入触发 {len(reverse_calls)} 次反查"))
        elif (
            isinstance(reverse_diag, dict)
            and reverse_diag.get("planned") is False
            and bool(reverse_diag.get("reason") or reverse_diag.get("skip_reason"))
        ):
            results.append(_pass("IMAGE-001", "图片输入但反查未规划（有明确原因）"))
        else:
            results.append(_fail(
                "IMAGE-001",
                "图片输入但无反查调用且无明确未规划原因",
                "触发反查或存在明确未规划原因",
                [_debug_evidence(snapshot, "debug.diagnosis", "reverse_image missing")],
            ))

    # IMAGE-002: Reverse Image 主工具和 fallback 顺序一致
    reverse_calls = [c for c in timeline if _is_reverse_image_call(c)]
    if len(reverse_calls) < 2:
        results.append(_na("IMAGE-002", f"仅 {len(reverse_calls)} 次反查调用，无 fallback"))
    else:
        reverse_diag = diag.get("reverse_image")
        primary = (
            reverse_diag.get("primary_tool")
            if isinstance(reverse_diag, dict)
            else diag.get("reverse_image_primary_provider")
        )
        fallback = (
            reverse_diag.get("fallback_tool")
            if isinstance(reverse_diag, dict)
            else diag.get("reverse_image_final_provider")
        )
        if primary or fallback or diag.get("reverse_image_fallback_used") is not None:
            timeline_providers = [c.get("provider") for c in reverse_calls]
            if primary and fallback and timeline_providers[0] == primary and timeline_providers[1] == fallback:
                results.append(_pass("IMAGE-002", f"主工具 {primary} → fallback {fallback} 顺序一致"))
            else:
                results.append(_fail(
                    "IMAGE-002",
                    f"timeline 顺序 {timeline_providers} vs diagnosis primary={primary} fallback={fallback}",
                    "主工具和 fallback 顺序一致",
                    [_debug_evidence(snapshot, "debug.diagnosis.reverse_image", str(reverse_diag or {
                        "primary": primary, "fallback": fallback,
                    }))],
                ))
        else:
            results.append(_warn("IMAGE-002", "有多次反查但 diagnosis 无 reverse_image 诊断"))

    return results


def check_face_comparison_semantics(snapshot):
    """FACE-001: 未执行 Face Comparison 不解释为 0% 或不匹配；未接入期间展示为"已知能力缺失"。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        return [_unknown("FACE-001", "缺少 Debug 证据")]
    diag = _get_diagnosis(snapshot)
    face_status = diag.get("face_comparison_status", "")
    candidate_details = _get_candidate_details(snapshot)

    if face_status != "not_performed":
        return [_na("FACE-001", f"face_comparison_status={face_status}，非未执行场景")]

    # 检查候选详情中是否将 not_performed 误解释为 0% 或不匹配
    for detail in candidate_details:
        fc = detail.get("face_comparison") if isinstance(detail, dict) else None
        if isinstance(fc, dict):
            fc_status = fc.get("status", "")
            fc_reason = fc.get("reason", "")
            if fc_status != "not_performed":
                return [_fail(
                    "FACE-001",
                    f"diagnosis=not_performed 但候选详情 status={fc_status or '缺失'}",
                    "未执行时所有候选详情均应为 not_performed",
                    [_debug_evidence(snapshot, "debug.diagnosis.face_comparison_status", face_status)],
                )]
            if fc_status == "not_performed":
                if "not_connected" in fc_reason or "provider_not_connected" in fc_reason:
                    # 未接入期间展示为"已知能力缺失"，不计为任务异常
                    return [_pass("FACE-001", f"face_comparison not_performed (reason={fc_reason})，展示为已知能力缺失")]
                elif fc.get("score") == 0 or "mismatch" in str(fc.get("status", "")).lower():
                    return [_fail(
                        "FACE-001",
                        f"not_performed 被解释为 score=0 或不匹配",
                        "不解释为 0% 或不匹配；展示为已知能力缺失",
                        [_debug_evidence(snapshot, "debug.diagnosis.face_comparison_status", face_status)],
                    )]

    # 无候选详情时检查 diagnosis
    if face_status == "not_performed":
        return [_pass("FACE-001", "face_comparison not_performed，未解释为 0% 或不匹配")]
    return [_na("FACE-001", "无法判断")]


def check_candidate_consistency(snapshot):
    """CAND-001~004: 候选一致性规则。"""
    results = []
    if not _has_coverage(snapshot, "debug"):
        for rid in ("CAND-001", "CAND-002", "CAND-003", "CAND-004"):
            results.append(_unknown(rid, "缺少 Debug 证据"))
        return results

    get_task = _get_get_task_data(snapshot)
    list_candidates = _get_candidates(snapshot)
    debug_candidates = _get_debug_candidates(snapshot)
    candidate_details = _get_candidate_details(snapshot)

    # CAND-001: candidate_count、top score 与候选列表一致
    if not _has_coverage(snapshot, "get_task", "candidate_list"):
        results.append(_unknown("CAND-001", "缺少 GetTask 或 ListTaskCandidates"))
    else:
        gt_count = get_task.get("candidate_count")
        gt_top = get_task.get("top_confidence_score")
        list_count = len(list_candidates)
        list_scores = [c.get("match_score") for c in list_candidates if c.get("match_score") is not None]
        list_top = max(list_scores) if list_scores else None
        if gt_count == list_count and (gt_top is None or list_top is None or gt_top == list_top):
            results.append(_pass("CAND-001", f"GetTask count={gt_count} top={gt_top} = List count={list_count} top={list_top}"))
        else:
            results.append(_fail(
                "CAND-001",
                f"GetTask count={gt_count} top={gt_top} ≠ List count={list_count} top={list_top}",
                "candidate_count 和 top_confidence_score 一致",
                [_get_task_evidence(snapshot, "data.candidate_count", gt_count)],
            ))

    # CAND-002: score/confidence/decision/selected 不矛盾
    if list_candidates and not _has_coverage(snapshot, "candidate_detail"):
        results.append(_unknown("CAND-002", "存在候选但缺少 GetTaskCandidateDetail，无法完成 decision/selected 全链路核对"))
    elif not debug_candidates and not list_candidates:
        results.append(_na("CAND-002", "无候选数据"))
    else:
        issues = []
        # 检查 debug candidates decision/selected 矛盾
        for dc in debug_candidates:
            if not isinstance(dc, dict):
                continue
            decision = dc.get("decision")
            selected = dc.get("selected")
            if decision == "SELECTED" and selected is False:
                issues.append(f"{dc.get('candidate_id')}: decision=SELECTED 但 selected=false")
            if decision in ("REJECTED", "UNRESOLVED") and selected is True:
                issues.append(f"{dc.get('candidate_id')}: decision={decision} 但 selected=true")
        # 检查 list candidates confidence=HIGH 但 is_best_match=false 且无 SELECTED 候选
        any_selected = any(dc.get("decision") == "SELECTED" for dc in debug_candidates if isinstance(dc, dict))
        for lc in list_candidates:
            if not isinstance(lc, dict):
                continue
            if lc.get("confidence_level") == "HIGH" and not lc.get("is_best_match") and any_selected:
                issues.append(f"{lc.get('candidate_id')}: confidence=HIGH 但 is_best_match=false 且存在 SELECTED 候选")
        if issues:
            results.append(_fail(
                "CAND-002",
                "; ".join(issues),
                "score/confidence/decision/selected 不矛盾",
                [_debug_evidence(snapshot, "debug.candidates", f"{len(debug_candidates)} candidates")],
            ))
        else:
            results.append(_pass("CAND-002", "候选 score/confidence/decision/selected 无矛盾"))

    # CAND-003: matched_clue_types 在 Debug、List、Detail 中一致
    if list_candidates and not _has_coverage(snapshot, "candidate_detail"):
        results.append(_unknown("CAND-003", "存在候选但缺少 GetTaskCandidateDetail，无法完成跨接口核对"))
    elif not debug_candidates or not list_candidates:
        results.append(_na("CAND-003", "缺少 Debug 或 List 候选数据"))
    else:
        issues = []
        # 按 candidate_id 对比 Debug 和 List 的 matched_clue_types
        debug_by_id = {dc.get("candidate_id"): dc for dc in debug_candidates if isinstance(dc, dict) and dc.get("candidate_id")}
        list_by_id = {lc.get("candidate_id"): lc for lc in list_candidates if isinstance(lc, dict) and lc.get("candidate_id")}
        for cid, dc in debug_by_id.items():
            lc = list_by_id.get(cid)
            if lc:
                dc_types = set(dc.get("matched_clue_types") or [])
                lc_types = set(lc.get("matched_clue_types") or [])
                if dc_types != lc_types:
                    issues.append(f"{cid}: Debug={dc_types} ≠ List={lc_types}")
        # 对比 Detail
        for detail in candidate_details:
            if not isinstance(detail, dict):
                continue
            cid = detail.get("candidate_id")
            cand = detail.get("candidate") if isinstance(detail.get("candidate"), dict) else {}
            detail_types = set(cand.get("matched_clue_types") or [])
            dc = debug_by_id.get(cid)
            if dc and detail_types:
                dc_types = set(dc.get("matched_clue_types") or [])
                if dc_types != detail_types:
                    issues.append(f"{cid}: Debug={dc_types} ≠ Detail={detail_types}")
        if issues:
            results.append(_fail(
                "CAND-003",
                "; ".join(issues),
                "matched_clue_types 在 Debug、List、Detail 中一致",
                [_debug_evidence(snapshot, "debug.candidates", f"{len(debug_candidates)} candidates")],
            ))
        else:
            results.append(_pass("CAND-003", "matched_clue_types 跨接口一致"))

    # CAND-004: 相同稳定标识的跨 Provider 候选不重复。
    # 稳定标识包括 person_id、wikidata_id、canonical_url（§8.4 审查修复：
    # 原实现只查 person_id，遗漏其他稳定标识）。
    stable_key_fields = (("person_id", "person_id"), ("wikidata_id", "wikidata_id"), ("canonical_url", "canonical_url"))
    dup_issues = []
    checked_counts = []
    for label, field in stable_key_fields:
        ids = {}
        for lc in list_candidates:
            if not isinstance(lc, dict):
                continue
            value = lc.get(field)
            if value:
                ids.setdefault(value, []).append(lc.get("candidate_id"))
        checked_counts.append(f"{label}={len(ids)}")
        duplicates = {value: cids for value, cids in ids.items() if len(cids) > 1}
        for value, cids in duplicates.items():
            dup_issues.append(f"相同 {label}={value} 候选重复: {cids}")
    if dup_issues:
        results.append(_fail(
            "CAND-004",
            "; ".join(dup_issues),
            "相同稳定标识的跨 Provider 候选不重复",
            [_debug_evidence(snapshot, "debug.candidates", f"{len(debug_candidates)} candidates")],
        ))
    else:
        results.append(_pass("CAND-004", f"稳定标识无重复（{', '.join(checked_counts)}）"))

    return results


def check_cost_consistency(snapshot):
    """COST-001~002: 成本一致性规则。"""
    results = []
    if not _has_coverage(snapshot, "debug", "cost_summary"):
        results.append(_unknown("COST-001", "缺少 Debug 或 Cost 证据"))
        results.append(_unknown("COST-002", "缺少 Debug 或 Cost 证据"))
        return results

    cost = _get_cost(snapshot)
    timeline = _get_timeline(snapshot)

    # COST-001: 分项成本与任务总成本一致。多币种不能直接相加或换算（PRD §6.9）。
    totals = cost.get("totals")
    currencies = {
        str(item.get("currency"))
        for item in totals or []
        if isinstance(item, dict)
        and int(item.get("total_cost_microunit", 0) or 0) > 0
        and item.get("currency")
    } if isinstance(totals, list) else set()
    if len(currencies) > 1:
        results.append(_unknown(
            "COST-001",
            f"存在多币种成本 {sorted(currencies)}，未做汇率换算",
            [_debug_evidence(snapshot, "cost_summary.totals", sorted(currencies))],
        ))
    else:
        total = _extract_cost_total(cost)
        items = cost.get("items") or cost.get("calls") or []
        if total is None or not items:
            results.append(_unknown("COST-001", f"total={total}, items={len(items)}"))
        elif isinstance(items, list):
            # 汇总分项成本：夹具用 items[].estimated_cost_microunit，
            # 真实日志 calls 用 cost_breakdown_json[].estimated_cost_microunit。
            item_sum = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("estimated_cost_microunit") is not None:
                    item_sum += item.get("estimated_cost_microunit", 0)
                else:
                    breakdown = item.get("cost_breakdown_json") or []
                    for bd in breakdown:
                        if isinstance(bd, dict):
                            item_sum += bd.get("estimated_cost_microunit", 0)
            if item_sum == total:
                results.append(_pass("COST-001", f"分项和 {item_sum} = 总成本 {total}"))
            else:
                results.append(_fail(
                    "COST-001",
                    f"分项和 {item_sum} ≠ 总成本 {total}",
                    "分项成本与任务总成本一致",
                    [_debug_evidence(snapshot, "cost_summary", f"total={total}, sum={item_sum}")],
                ))
        else:
            results.append(_unknown("COST-001", "items 格式异常"))

    # PDL 前阶段成本应等于 timeline 中首次 PDL 之前已产生的真实调用成本。
    # 这能识别总成本正确、但 pre_pdl 诊断字段漏记 LLM 成本的情况。
    diagnosis = _get_diagnosis(snapshot)
    pre_pdl_actual = diagnosis.get("pre_pdl_estimated_cost_microunit")
    pdl_positions = [index for index, call in enumerate(timeline) if _provider_is(call, "pdl")]
    if pre_pdl_actual is not None and pdl_positions and results and results[0]["outcome"] == "PASS":
        pre_pdl_expected = sum(
            int(call.get("estimated_cost_microunit") or 0)
            for call in timeline[:min(pdl_positions)]
        )
        if int(pre_pdl_actual or 0) != pre_pdl_expected:
            results[0] = _fail(
                "COST-001",
                f"总成本一致，但 pre_pdl_estimated_cost_microunit={pre_pdl_actual}，"
                f"PDL 前 timeline 成本={pre_pdl_expected}",
                f"pre_pdl_estimated_cost_microunit 应为 {pre_pdl_expected}",
                [_debug_evidence(
                    snapshot,
                    "debug.diagnosis.pre_pdl_estimated_cost_microunit",
                    pre_pdl_actual,
                )],
            )

    # COST-002: UNPRICED 不作为免费，缓存调用不重复计费
    debug = _get_debug(snapshot)
    raw_calls = debug.get("agent_tool_calls", [])
    unpriced_calls = [
        c for c in raw_calls
        if isinstance(c, dict) and c.get("cost_status") == "UNPRICED"
    ]
    cache_calls = [
        c for c in raw_calls
        if isinstance(c, dict) and (c.get("cache_hit") or c.get("cost_status") == "CACHE")
    ]
    if not unpriced_calls and not cache_calls:
        results.append(_na("COST-002", "无 UNPRICED 或缓存调用"))
    else:
        issues = []
        # UNPRICED 不应出现在 cost items 中计费
        cost_items = cost.get("items") or cost.get("calls") or []
        for item in cost_items:
            if isinstance(item, dict) and item.get("cost_status") == "UNPRICED":
                if item.get("estimated_cost_microunit", 0) > 0:
                    issues.append(f"UNPRICED 调用 {item.get('provider')} 有非零成本")
        # 缓存调用成本应为 0
        for item in cost_items:
            if isinstance(item, dict) and (
                item.get("cost_status") == "CACHE" or bool(item.get("cache_hit"))
            ):
                if item.get("estimated_cost_microunit", 0) > 0:
                    issues.append(f"缓存调用 {item.get('provider')} 有非零成本")
        if issues:
            results.append(_fail(
                "COST-002",
                "; ".join(issues),
                "UNPRICED 不作为免费，缓存调用不重复计费",
                [_debug_evidence(snapshot, "cost_summary", str(cost))],
            ))
        elif unpriced_calls:
            results.append(_unknown(
                "COST-002",
                f"存在 {len(unpriced_calls)} 条 UNPRICED 调用，0 不代表免费，无法完成价格核对",
                [_debug_evidence(snapshot, "debug.agent_tool_calls", "UNPRICED")],
            ))
        else:
            results.append(_pass("COST-002", f"UNPRICED={len(unpriced_calls)}, CACHE={len(cache_calls)}，无计费异常"))

    return results


def check_stop_reason_consistency(snapshot):
    """STOP-001: 核对人物链路停止原因，不混淆 Report 工作流完成状态。"""
    results = []
    if not _has_coverage(snapshot, "get_task", "debug"):
        return [_unknown("STOP-001", "缺少 GetTask 或 Debug 证据")]
    get_task = _get_get_task_data(snapshot)
    diag = _get_diagnosis(snapshot)
    diag_stop = diag.get("stop_reason")
    debug = _get_debug(snapshot)
    agent_stops = [
        (call.get("result_details") or {}).get("stop_reason")
        for call in _get_timeline(snapshot)
        if str(call.get("provider") or "").lower() == "agent_people"
    ]
    agent_stop = next((value for value in reversed(agent_stops) if value), None)

    reports = debug.get("reports") if isinstance(debug, dict) else None
    report_summary = reports[-1].get("subject_summary") if isinstance(reports, list) and reports else None
    report_stop = report_summary.get("stop_reason") if isinstance(report_summary, dict) else None

    if diag_stop is None:
        return [_unknown("STOP-001", "diagnosis.stop_reason 缺失")]
    if agent_stop and agent_stop != diag_stop:
        return [_fail(
            "STOP-001",
            f"agent_people stop_reason={agent_stop} ≠ diagnosis stop_reason={diag_stop}",
            "人物聚合调用与 diagnosis 的停止原因一致",
            [_debug_evidence(snapshot, "debug.diagnosis.stop_reason", diag_stop)],
        )]
    if agent_stop == diag_stop:
        report_note = f"；Report stop_reason={report_stop} 表示报告工作流完成" if report_stop else ""
        return [_pass(
            "STOP-001",
            f"人物链路 stop_reason={diag_stop} 与 agent_people 一致{report_note}",
        )]

    # 兼容旧日志：若 GetTask 直接提供 stop_reason，仍按原字段核对。
    gt_stop = get_task.get("stop_reason")
    if gt_stop is not None:
        if gt_stop == diag_stop:
            return [_pass("STOP-001", f"GetTask/diagnosis stop_reason 均为 {gt_stop}")]
        return [_fail(
            "STOP-001",
            f"GetTask stop_reason={gt_stop} ≠ diagnosis stop_reason={diag_stop}",
            "GetTask 与 diagnosis 的人物链路停止原因一致",
            [_get_task_evidence(snapshot, "data.stop_reason", gt_stop),
             _debug_evidence(snapshot, "debug.diagnosis.stop_reason", diag_stop)],
        )]
    return [_unknown(
        "STOP-001",
        f"diagnosis stop_reason={diag_stop}，缺少 agent_people/GetTask 停止原因证据",
    )]


# ---------------------------------------------------------------------------
# CHECKS 注册表（§8.2）
# ---------------------------------------------------------------------------

CHECKS = (
    check_terminal_status,
    check_state_002,
    check_public_figure_route,
    check_llm_output,
    check_llm_truncation,
    check_pdl_fallback,
    check_pdl_candidate_quality,
    check_social_profile_queue,
    check_reverse_image_route,
    check_face_comparison_semantics,
    check_candidate_consistency,
    check_cost_consistency,
    check_stop_reason_consistency,
)


def run_all_checks(snapshot, warnings=None):
    """运行全部检查规则，返回 (checks, verdict, warnings)。

    单条规则异常被捕获为 warning，不中断其他规则。
    """
    if warnings is None:
        warnings = []
    checks = []
    for check_fn in CHECKS:
        try:
            results = check_fn(snapshot)
            if isinstance(results, list):
                checks.extend(results)
            elif isinstance(results, dict):
                checks.append(results)
        except Exception:
            warnings.append({
                "code": "RULE_ERROR",
                "message": f"{check_fn.__name__} 异常: {traceback.format_exc().splitlines()[-1]}",
            })
    verdict = _compute_verdict(checks, snapshot)
    return checks, verdict, warnings


def _compute_verdict(checks, snapshot):
    """根据规则结果计算总体 verdict。"""
    if not checks:
        return "INCOMPLETE_EVIDENCE"
    has_fail = any(c["outcome"] == "FAIL" for c in checks)
    has_warn = any(c["outcome"] == "WARN" for c in checks)
    has_unknown = any(c["outcome"] == "UNKNOWN" for c in checks)
    if has_fail:
        return "ISSUES_FOUND"
    if (snapshot.get("coverage") or {}).get("source_truncated"):
        return "INCOMPLETE_EVIDENCE"
    if has_warn:
        return "NEEDS_CONFIRMATION"
    if has_unknown:
        return "INCOMPLETE_EVIDENCE"
    return "NORMAL"


# ---------------------------------------------------------------------------
# 确定性 Markdown 报告（§14.1）
# ---------------------------------------------------------------------------


def _markdown_cell(value):
    """把结构化值压缩为安全、可扫描的 Markdown 表格文本。"""
    if value is None or value == "":
        return "—"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _call_business_result(call):
    """生成人可读的 Provider 业务结果，不把 HTTP 200 当成业务成功。"""
    parts = []
    if call.get("no_result_reason"):
        parts.append(f"reason={call['no_result_reason']}")
    if call.get("decision_reason"):
        parts.append(f"decision={call['decision_reason']}")
    if call.get("found") is not None:
        parts.append(f"found={str(bool(call['found'])).lower()}")
    if call.get("candidate_count") is not None:
        parts.append(f"candidates={call['candidate_count']}")
    if call.get("evidence_count") is not None:
        parts.append(f"evidence={call['evidence_count']}")
    return "; ".join(parts) or "—"


def _call_diagnostic_details(call):
    """展示解析器允许对外输出的调用级关键诊断字段。"""
    details = call.get("result_details") or {}
    return "; ".join(
        f"{key}={_markdown_cell(value)}"
        for key, value in details.items()
    ) or "—"


def render_rule_report(analysis_result):
    """生成确定性 Markdown 报告。

    analysis_result 为 analyze_people_search_log 的返回值。
    """
    if not analysis_result["supported"]:
        return "# People Insight 检索日志分析\n\n## 总体结论\n\nUNSUPPORTED_LOG：未识别到 People Insight 检索接口。\n"

    if analysis_result["selection_error"]:
        task_ids = ", ".join(analysis_result["task_ids"]) or "无"
        return (
            f"# People Insight 检索日志分析\n\n"
            f"## 总体结论\n\n{analysis_result['selection_error']}："
            f"检测到多个任务（{task_ids}），请指定 requested_task_id 后重试。\n"
        )

    snapshot = analysis_result["snapshot"]
    warnings = list(analysis_result["parse_warnings"])
    checks, verdict, warnings = run_all_checks(snapshot, warnings)

    task = snapshot["task"]
    coverage = snapshot["coverage"]
    timeline = snapshot["timeline"]
    candidates = snapshot["candidates"]
    diagnosis = snapshot["diagnosis"]
    cost = snapshot["cost"]

    lines = ["# People Insight 检索日志分析", ""]

    # 总体结论
    lines.append("## 总体结论")
    verdict_label = {
        "NORMAL": "正常",
        "ISSUES_FOUND": "发现异常",
        "NEEDS_CONFIRMATION": "需要后端确认",
        "INCOMPLETE_EVIDENCE": "证据不足",
        "UNSUPPORTED_LOG": "不支持",
    }.get(verdict, verdict)
    lines.append(f"**{verdict_label}**（{verdict}）")
    lines.append("")
    if task.get("full_name"):
        lines.append(f"- 任务: {task['full_name']}（task_id={task.get('task_id') or '未知'}）")
        lines.append("")

    # 任务结果与停止原因：明确区分工作流完成和业务检索结果。
    get_task = snapshot.get("get_task_data") or {}
    lines.append("## 任务结果与停止原因")
    lines.append(f"- GetTask: status={get_task.get('status')}, result_type={get_task.get('result_type')}, "
                 f"candidate_count={get_task.get('candidate_count')}, "
                 f"no_result_reason={get_task.get('no_result_reason')!r}")
    lines.append(f"- Diagnosis: final_status={diagnosis.get('final_status')}, "
                 f"stop_reason={diagnosis.get('stop_reason')}, "
                 f"status_consistent={diagnosis.get('status_consistent')}")
    progress = get_task.get("progress")
    if isinstance(progress, dict):
        lines.append(
            f"- Progress: stage={progress.get('stage')}, "
            f"display_message={progress.get('display_message')}, "
            f"display_percent={progress.get('display_percent')}"
        )
    lines.append("")

    # 日志覆盖度
    lines.append("## 日志覆盖度")
    lines.append("| 接口 | 覆盖 |")
    lines.append("| --- | --- |")
    cov_labels = [
        ("CreateIntentTask", "create_task"),
        ("GetTask", "get_task"),
        ("ListTaskCandidates", "candidate_list"),
        ("GetTaskCandidateDetail", "candidate_detail"),
        ("GetSearchTaskDebug", "debug"),
        ("GetProviderCostSummary", "cost_summary"),
    ]
    for label, key in cov_labels:
        lines.append(f"| {label} | {'✓' if coverage.get(key) else '✗'} |")
    if coverage.get("source_truncated"):
        lines.append("")
        lines.append("> ⚠ 部分日志解析失败，证据可能不完整。")
    lines.append("")

    # 实际执行链路
    lines.append("## 实际执行链路")
    if timeline:
        lines.append("| # | Provider / Operation | 技术/业务状态 | 业务结果 | 关键诊断 | 成本 | Start |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, call in enumerate(timeline, 1):
            cost_text = (
                f"{call.get('estimated_cost_microunit')} microunit "
                f"({call.get('billing_currency') or 'UNSPECIFIED'}, {call.get('cost_status') or 'UNKNOWN'})"
                if call.get("estimated_cost_microunit") is not None
                else (call.get("cost_status") or "—")
            )
            lines.append(
                f"| {i} | {_markdown_cell(call.get('provider'))} / {_markdown_cell(call.get('operation'))} | "
                f"status={_markdown_cell(call.get('status'))}; HTTP={_markdown_cell(call.get('http_status'))}; "
                f"cache={'是' if call.get('cache_hit') else '否'} | "
                f"{_markdown_cell(_call_business_result(call))} | "
                f"{_markdown_cell(_call_diagnostic_details(call))} | "
                f"{_markdown_cell(cost_text)} | {_markdown_cell(call.get('start_time'))} |"
            )
    else:
        lines.append("无 agent_tool_calls 数据。")
    lines.append("")

    # 关键诊断摘要：固定报告即使 AI 关闭也能解释每条工作线的结果。
    lines.append("## 关键诊断摘要")
    lines.append(
        "- LLM: "
        f"output_status={diagnosis.get('llm_output_status') or diagnosis.get('llm_result_status')}, "
        f"reasoning_bytes={diagnosis.get('llm_reasoning_bytes')}, "
        f"truncation_detected={diagnosis.get('llm_truncation_detected')}, "
        f"repair_retry_used={diagnosis.get('llm_repair_retry_used')}"
    )
    lines.append(
        "- PDL: "
        f"identify={diagnosis.get('pdl_identify_call_count')}, "
        f"search={diagnosis.get('pdl_person_search_call_count')}, "
        f"external_requests={diagnosis.get('pdl_external_request_count')}, "
        f"returned_profiles={diagnosis.get('pdl_person_search_returned_profile_count')}, "
        f"usable_candidates={diagnosis.get('pdl_usable_candidate_count')}"
    )
    lines.append(
        "- Reverse Image: "
        f"status={diagnosis.get('reverse_image_status')}, "
        f"stop_reason={diagnosis.get('reverse_image_stop_reason')}, "
        f"primary={diagnosis.get('reverse_image_primary_provider')}, "
        f"final={diagnosis.get('reverse_image_final_provider')}, "
        f"fallback_used={diagnosis.get('reverse_image_fallback_used')}"
    )
    lines.append(
        "- Social / Face: "
        f"social_status={diagnosis.get('social_profile_status')}, "
        f"social_planned={diagnosis.get('social_profile_planned_count')}, "
        f"face_status={diagnosis.get('face_comparison_status')}"
    )
    lines.append("")

    # Provider与成本
    lines.append("## Provider与成本")
    currency_totals = _cost_totals_by_currency(cost)
    total = _extract_cost_total(cost)
    if currency_totals:
        lines.append("- 按币种总计:")
        for item in currency_totals:
            lines.append(
                f"  - {item['currency']}: {item['total_cost_microunit']} microunit "
                f"(complete={item['cost_complete']}, unpriced={item['unpriced_call_count']})"
            )
    elif total is not None:
        lines.append(f"- 任务总成本: {total} microunit")
    if diagnosis.get("pre_pdl_estimated_cost_microunit") is not None:
        lines.append(
            f"- PDL 前阶段成本: {diagnosis.get('pre_pdl_estimated_cost_microunit')} microunit"
        )
    by_provider = cost.get("by_provider")
    items = cost.get("items") or cost.get("calls") or []
    if isinstance(by_provider, list) and by_provider:
        lines.append("- 分项:")
        for item in by_provider[:20]:
            if isinstance(item, dict):
                lines.append(
                    f"  - {item.get('provider', '')}: {item.get('total_cost_microunit', 0)} "
                    f"(calls={item.get('call_count', 0)}, currency={item.get('currency', '')})"
                )
    elif items:
        lines.append("- 分项:")
        for item in items[:20]:
            if isinstance(item, dict):
                lines.append(
                    f"  - {item.get('provider', '')} / {item.get('operation', item.get('provider_operation', ''))}: "
                    f"{item.get('estimated_cost_microunit', 0)} ({item.get('cost_status', '')})"
                )
    lines.append("")

    # 候选信息
    if candidates:
        lines.append("## 候选列表")
        lines.append("| Candidate ID | Display Name | Score | Confidence | Source |")
        lines.append("| --- | --- | --- | --- | --- |")
        for cand in candidates[:20]:
            lines.append(
                f"| {cand.get('candidate_id', '')} | {cand.get('display_name', '')} | "
                f"{cand.get('match_score', '')} | {cand.get('confidence_level', '')} | "
                f"{cand.get('source_provider', '')} |"
            )
        lines.append("")

    # 规则结果分组
    passed = [c for c in checks if c["outcome"] == "PASS"]
    failed = [c for c in checks if c["outcome"] == "FAIL"]
    warned = [c for c in checks if c["outcome"] == "WARN"]
    unknown = [c for c in checks if c["outcome"] == "UNKNOWN"]
    na = [c for c in checks if c["outcome"] == "NOT_APPLICABLE"]

    def _evidence_lines(check):
        """输出证据引用行（PRD §12.1-13：每条异常和疑问都包含证据）。

        证据值先经 json_path 提示脱敏，避免报告泄露敏感信息（§10.1）。
        """
        out = []
        for ev in check.get("evidence") or []:
            ev = _redact_value_by_hint(ev) if isinstance(ev, dict) else ev
            if not isinstance(ev, dict):
                continue
            location = f"{ev.get('method') or '未知接口'} {ev.get('json_path') or ''}".strip()
            if ev.get("line_start"):
                location += f"（日志行 {ev.get('line_start')}-{ev.get('line_end') or ev.get('line_start')}）"
            value = ev.get("value")
            if isinstance(value, (str, int, float, bool)):
                value_text = str(value)
                if len(value_text) > 80:
                    value_text = value_text[:80] + "…"
                location += f"，值={value_text}"
            out.append(f"  - 证据: {location}")
        return out

    lines.append("## 已确认正常")
    lines.append("")
    if passed:
        for c in passed:
            lines.append(f"- **{c['rule_id']}** ({c['severity']}): {c['title']} — {c['actual']}")
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("## 已确认异常")
    lines.append("")
    if failed:
        for c in failed:
            lines.append(f"- **{c['rule_id']}** ({c['severity']}): {c['title']}")
            lines.append(f"  - 实际: {c['actual']}")
            lines.append(f"  - 期望: {c['expected']}")
            lines.extend(_evidence_lines(c))
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("## 需要后端确认")
    lines.append("")
    if warned:
        for c in warned:
            lines.append(f"- **{c['rule_id']}** ({c['severity']}): {c['title']} — {c['actual']}")
            lines.extend(_evidence_lines(c))
    else:
        lines.append("（无）")
    lines.append("")

    lines.append("## 日志不足，无法判断")
    lines.append("")
    if unknown:
        for c in unknown:
            lines.append(f"- **{c['rule_id']}** ({c['severity']}): {c['title']} — {c['actual']}")
            lines.extend(_evidence_lines(c))
    else:
        lines.append("（无）")
    if na:
        lines.append("")
        lines.append("### 不适用")
        for c in na:
            lines.append(f"- **{c['rule_id']}** ({c['severity']}): {c['title']} — {c['actual']}")

    # 解析告警
    if warnings:
        lines.append("")
        lines.append("## 解析告警")
        for w in warnings:
            lines.append(f"- [{w.get('code', '')}] {w.get('message', '')}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Evidence Packet 与脱敏（§9、§10）
# ---------------------------------------------------------------------------

_REDACT_KEYS = re.compile(
    r"(authorization|auth_token|token|cookie|password|secret|api_key|access_token)",
    re.IGNORECASE,
)
_REDACT_B64 = re.compile(r"^[A-Za-z0-9+/]{200,}={0,2}$")
_REDACT_DATA_URL = re.compile(r"^data:[^;]+;base64,")
# 签名 URL 的 query 特征参数（§10.2：签名图片 URL 去除 query 和 fragment）
_SIGNED_URL_PARAM_RE = re.compile(
    r"(signature|x-amz-|sig=|token=|expires|access_key|se=|sp=|sr=)",
    re.IGNORECASE,
)


def _looks_like_base64_blob(value):
    """判断字符串是否为 Base64 二进制内容。

    仅凭字符集匹配会把普通长文本（如连续字母）误判为二进制（审查修复），
    因此额外要求同时包含大写字母、小写字母和数字——真实 Base64
    图片/二进制编码几乎总是混合三类字符。
    """
    if len(value) <= 500 or not _REDACT_B64.match(value):
        return False
    has_upper = any(c.isupper() for c in value)
    has_lower = any(c.islower() for c in value)
    has_digit = any(c.isdigit() for c in value)
    return has_upper and has_lower and has_digit


def _strip_signed_url_query(value):
    """对带签名参数的 http(s) URL 去除 query 和 fragment（§10.2）。

    保留 scheme、host、path，用于身份与去重分析；普通 canonical
    social URL（无签名参数）保持原样。
    """
    if not value.startswith(("http://", "https://")):
        return value
    query_pos = value.find("?")
    if query_pos == -1:
        return value
    query = value[query_pos + 1:].split("#", 1)[0]
    if _SIGNED_URL_PARAM_RE.search(query):
        return value[:query_pos]
    return value


def _redact_string_value(value):
    """字符串值统一脱敏入口：data URL / Base64 → [binary omitted]，签名 URL 去 query。"""
    if _REDACT_DATA_URL.match(value):
        return "[binary omitted]"
    if _looks_like_base64_blob(value):
        return "[binary omitted]"
    return _strip_signed_url_query(value)


def redact_for_ai(value):
    """递归脱敏（§10.2）：authorization/token 等替换为 ***，Base64/data URL 替换为 [binary omitted]。

    邮箱和电话保留原值（评审确认）。
    """
    if isinstance(value, dict):
        return {k: redact_for_ai(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_ai(item) for item in value]
    if isinstance(value, str):
        return _redact_string_value(value)
    return value


_VALUE_PATH_SENSITIVE = re.compile(
    r"(authorization|auth_token|token|cookie|password|secret|api_key|access_token)",
    re.IGNORECASE,
)


def _redact_value_by_hint(value_obj):
    """对 evidence 对象按 json_path 中的敏感关键字补充脱敏。

    checks[].evidence[] 结构通常是 {"method":..., "json_path":..., "value":..., ...}
    其中 json_path 引用了实际字段名，value 则用通用 key "value" 包装。
    """
    if not isinstance(value_obj, dict):
        return value_obj
    json_path = value_obj.get("json_path")
    if (
        isinstance(json_path, str)
        and _VALUE_PATH_SENSITIVE.search(json_path)
        and "value" in value_obj
        and isinstance(value_obj.get("value"), str)
    ):
        value_obj = dict(value_obj)
        value_obj["value"] = "***"
    return value_obj


def redact_for_response(value):
    """对外响应脱敏（§10.1）：checks、接口响应等递归脱敏敏感字段。

    与 redact_for_ai 的差异：本函数额外按 key 名脱敏（auth_token 等），
    且对 checks.evidence 中以 json_path 引用敏感字段的 value 进行补充脱敏，
    确保结构化 checks 中的证据值不会泄露 Token、密钥等敏感信息。
    """
    return _redact_dict_keys_custom(value, _redact_value_by_hint)


def _redact_dict_keys_custom(data, entry_hint_fn):
    """递归处理 dict 敏感 key，同时对每个 dict 应用 entry_hint_fn。"""
    if isinstance(data, dict):
        data = entry_hint_fn(data)
        if not isinstance(data, dict):
            return data
        result = {}
        for k, v in data.items():
            if isinstance(k, str) and _REDACT_KEYS.search(k):
                result[k] = "***"
            else:
                result[k] = _redact_dict_keys_custom(v, entry_hint_fn)
        return result
    if isinstance(data, list):
        return [_redact_dict_keys_custom(item, entry_hint_fn) for item in data]
    if isinstance(data, str):
        return _redact_string_value(data)
    return data


def _redact_dict_keys(data):
    """递归处理 dict 的 key：敏感 key 的值替换为 ***（保留给 Evidence Packet 内部使用）。"""
    return _redact_dict_keys_custom(data, lambda x: x)


# Evidence Packet 上限常量（§9.3）
MAX_PACKET_CANDIDATES = 20
MAX_PACKET_TOOL_CALLS = 100
MAX_PACKET_SOCIAL_DECISIONS = 100
MAX_PACKET_COST_CALLS = 100
MAX_PACKET_TEXT_CHARS = 2000


def _cap_free_text(value, truncated_flag):
    """递归限制单个自由文本字段最多 2000 字符（§9.3 审查修复）。"""
    if isinstance(value, dict):
        return {k: _cap_free_text(v, truncated_flag) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap_free_text(item, truncated_flag) for item in value]
    if isinstance(value, str) and len(value) > MAX_PACKET_TEXT_CHARS:
        truncated_flag.append(True)
        return value[:MAX_PACKET_TEXT_CHARS] + "…(已截断)"
    return value


def _limit_candidate_summary(raw_candidates, truncated_flag):
    """候选摘要最多 20 个；超限时优先保留已选、最高分候选（§9.3 审查修复）。"""
    def _summary(cand):
        return {
            "candidate_id": cand.get("candidate_id"),
            "display_name": cand.get("display_name"),
            "match_score": cand.get("match_score"),
            "confidence_level": cand.get("confidence_level"),
            "source_provider": cand.get("source_provider"),
            "selected": cand.get("selected"),
        }

    if len(raw_candidates) <= MAX_PACKET_CANDIDATES:
        return [_summary(c) for c in raw_candidates if isinstance(c, dict)]
    truncated_flag.append(True)

    def _priority(cand):
        score = cand.get("match_score")
        return (0 if cand.get("selected") else 1, -(score if isinstance(score, (int, float)) else 0))

    kept = sorted((c for c in raw_candidates if isinstance(c, dict)), key=_priority)
    return [_summary(c) for c in kept[:MAX_PACKET_CANDIDATES]]


def _limit_timeline(raw_timeline, truncated_flag):
    """工具调用最多 100 条；超限时优先保留失败调用，其余按时间顺序取前部（§9.3 审查修复）。"""
    if len(raw_timeline) <= MAX_PACKET_TOOL_CALLS:
        return list(raw_timeline)
    truncated_flag.append(True)
    failed_count = sum(1 for c in raw_timeline if c.get("status") == "error")
    if failed_count >= MAX_PACKET_TOOL_CALLS:
        return [c for c in raw_timeline if c.get("status") == "error"][:MAX_PACKET_TOOL_CALLS]
    normal_budget = MAX_PACKET_TOOL_CALLS - failed_count
    limited = []
    for call in raw_timeline:
        if call.get("status") == "error":
            limited.append(call)
        elif normal_budget > 0:
            limited.append(call)
            normal_budget -= 1
    return limited


def _pick_report_subject_summary(subject):
    """保留 Report 中可解释业务结果且不含原始媒体内容的摘要字段。"""
    if not isinstance(subject, dict):
        return {}
    fields = (
        "headline", "identity_found", "people_found", "photo_evidence_found",
        "confidence_cap", "stop_reason", "submitted_photo_count",
        "submitted_photo_error_count", "submitted_photo_match_count",
        "submitted_photo_no_match_count", "reverse_image_status",
        "reverse_image_stop_reason", "reverse_image_fallback_used",
        "reverse_image_primary_provider", "reverse_image_final_provider",
        "social_profile_status", "social_profile_planned_count",
        "estimated_cost_microunit", "task_total_estimated_cost_microunit",
    )
    return {
        field: subject.get(field)
        for field in fields
        if subject.get(field) is not None
    }


def build_evidence_packet(analysis_result):
    """构建 Evidence Packet（§9.2），用于发送给 AI。

    先运行规则检查，再脱敏证据值。超限时按 §9.3 优先保留已选/高分候选、
    失败调用，设置 source_truncated=true，并限制单文本 2000 字符。
    """
    if not analysis_result["supported"] or analysis_result["selection_error"]:
        return None

    snapshot = analysis_result["snapshot"]
    warnings = list(analysis_result["parse_warnings"])
    checks, verdict, warnings = run_all_checks(snapshot, warnings)

    task = snapshot["task"]
    coverage = snapshot["coverage"]
    truncated_flag = []

    # 线索值摘要（邮箱、电话保留原值，供 AI 分析；§10.2）
    clue_values = _extract_clue_values(snapshot.get("create_request"))

    # 候选摘要（最多 20 个，超限优先保留已选/高分候选）
    candidate_summary = _limit_candidate_summary(snapshot.get("candidates") or [], truncated_flag)

    # 工具时间线（最多 100 条，超限优先保留失败调用）
    timeline = _limit_timeline(snapshot.get("timeline") or [], truncated_flag)

    # Social URL 决策（最多 100 条，§9.3）
    queue = _get_social_url_queue(snapshot)
    social_url_decisions = [
        {
            "url": q.get("url"),
            "canonical_url": q.get("canonical_url"),
            "origin": q.get("origin"),
            "decision": q.get("decision"),
            "skip_reason": q.get("skip_reason"),
        }
        for q in queue if isinstance(q, dict)
    ]
    if len(social_url_decisions) > MAX_PACKET_SOCIAL_DECISIONS:
        truncated_flag.append(True)
        social_url_decisions = social_url_decisions[:MAX_PACKET_SOCIAL_DECISIONS]

    # 诊断摘要
    diagnosis = snapshot.get("diagnosis") or {}
    diagnosis_fields = (
        "final_status", "final_reason", "stop_reason", "status_consistent",
        "successful_call_count", "failed_call_count", "no_result_call_count",
        "llm_result_status", "llm_output_status", "llm_http_attempt_count",
        "llm_reasoning_bytes", "llm_truncation_detected", "llm_repair_retry_used",
        "llm_recoverable_candidates", "llm_partial_result_usable",
        "public_figure_local", "public_figure_local_hit", "public_figure_skip_reason",
        "public_figure_remote_called", "public_figure_remote_total",
        "public_figure_remote_usable_count", "public_figure_remote_ambiguous",
        "pdl_identify_call_count", "pdl_person_search_call_count",
        "pdl_external_request_count", "pdl_person_search_returned_profile_count",
        "pdl_usable_candidate_count", "pdl_billing_unit_count", "pdl_pipeline_stages",
        "social_profile_status", "social_profile_planned_count",
        "social_profile_attempted_count", "social_profile_merged_candidate_count",
        "reverse_image_status", "reverse_image_stop_reason",
        "reverse_image_primary_provider", "reverse_image_final_provider",
        "reverse_image_fallback_used", "reverse_image_fallback_reasons",
        "reverse_image_provider_attempt_count", "submitted_photo_error_count",
        "submitted_photo_no_match_count", "face_comparison_status",
        "estimated_cost_microunit", "pre_pdl_estimated_cost_microunit",
        "pdl_estimated_cost_microunit", "reverse_image_estimated_cost_microunit",
        "task_total_estimated_cost_microunit",
        "report_estimated_cost_microunit", "cost_consistent", "unpriced_call_count",
    )
    diagnosis_summary = {
        field: diagnosis.get(field)
        for field in diagnosis_fields
        if diagnosis.get(field) is not None
    }

    reports = (snapshot.get("debug") or {}).get("reports") or []
    latest_report = reports[-1] if isinstance(reports, list) and reports else {}
    report_subject = latest_report.get("subject_summary") if isinstance(latest_report, dict) else {}
    report_summary = {
        "status": latest_report.get("status") if isinstance(latest_report, dict) else None,
        "confidence_level": latest_report.get("confidence_level") if isinstance(latest_report, dict) else None,
        "subject_summary": _pick_report_subject_summary(report_subject),
        "evidence": latest_report.get("evidence") if isinstance(latest_report, dict) else [],
        "disclaimers": latest_report.get("disclaimers") if isinstance(latest_report, dict) else [],
    }

    # 成本摘要（调用最多 100 条）
    cost = snapshot.get("cost") or {}
    cost_calls = cost.get("calls") or cost.get("items") or []
    if len(cost_calls) > MAX_PACKET_COST_CALLS:
        truncated_flag.append(True)
        cost_calls = cost_calls[:MAX_PACKET_COST_CALLS]
    cost_summary = {
        "total_estimated_cost_microunit": cost.get("total_estimated_cost_microunit"),
        "totals_by_currency": _cost_totals_by_currency(cost),
        "by_provider": cost.get("by_provider") or [],
        "call_count": len(cost_calls),
        "calls": cost_calls,
    }

    packet = {
        "analyzer_version": ANALYZER_VERSION,
        "ruleset_version": RULESET_VERSION,
        "policy_version": snapshot.get("policy_version"),
        "verdict": verdict,
        "task_summary": {
            "task_id": task.get("task_id"),
            "query_id": task.get("query_id"),
            "client_request_id": task.get("client_request_id"),
            "full_name": task.get("full_name"),
            "clue_types": task.get("clue_types"),
            "clues": clue_values,
            "social_links": task.get("social_links") or [],
            "photo_count": task.get("photo_count", 0),
            "final_status": task.get("final_status"),
            "candidate_count": task.get("candidate_count"),
            "top_confidence_score": task.get("top_confidence_score"),
            "result_type": task.get("result_type"),
            "no_result_reason": task.get("no_result_reason"),
            "progress": task.get("progress"),
        },
        "coverage": coverage,
        "timeline": timeline,
        "candidate_summary": candidate_summary,
        "social_url_decisions": social_url_decisions,
        "diagnosis_summary": diagnosis_summary,
        "report_summary": report_summary,
        "cost_summary": cost_summary,
        "checks": checks,
        "parse_warnings": warnings,
    }

    # 单个自由文本字段最多 2000 字符（§9.3）
    packet = _cap_free_text(packet, truncated_flag)
    # 超限时设置 source_truncated=true，最终结论不能标记为完全正常（§9.3）
    if truncated_flag:
        packet["source_truncated"] = True

    # 脱敏后返回：与对外响应同级脱敏，checks.evidence 按 json_path 提示
    # 补充脱敏，避免敏感证据值发送给 LLM（审查修复）
    return _redact_dict_keys_custom(packet, _redact_value_by_hint)
