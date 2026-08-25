"""阶段四 ExecutionPlan 的纯编译器。

本模块故意只接受轻量字典（也兼容提供 ``model_dump`` 的对象），不读取文件、不调用
网络、也不写入存储。控制平面负责选择版本、保存不可变计划和最终确认；本模块只把
已经审核的执行定义确定性地转换为可审查的 DAG，或返回创建 Run 前必须处理的 blocker。
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SUPPORTED_ASSERTION_OPERATORS = frozenset({"status_code", "contains", "json_pointer_equals"})
_SENSITIVE_FIELD = re.compile(
    r"(?i)(?:authorization|proxy[-_]?authorization|api[-_]?key|token|password|passwd|secret|cookie|session|csrf)"
)
_RUNTIME_PLACEHOLDER = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.-]*\s*\}\}")


@dataclass(frozen=True, slots=True)
class PlanBlocker:
    """计划无法进入确认态时返回的稳定错误。

    ``field_path`` 供 API 和页面精确定位问题；``detail`` 只表达脱敏的结构性上下文，
    不得放入 Host、Credential、Cookie 或响应正文。
    """

    code: str
    field_path: str
    detail: str


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """纯编译结果；有 blocker 时不生成可确认的计划。"""

    plan: dict[str, Any] | None
    blockers: tuple[PlanBlocker, ...]

    @property
    def ready(self) -> bool:
        """计划是否已通过静态编译门禁。"""

        return self.plan is not None and not self.blockers


def canonical_sha256(payload: Any) -> str:
    """对计划正文做稳定序列化，避免字典或输入数组顺序影响确认结果。"""

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_PLAN_HASH_FIELDS = (
    "artifact_schema_version", "task_id", "source_executable_version",
    "source_executable_sha256", "target_id", "environment",
    "target_policy_sha256", "resource_policy_id", "egress_policy_id",
    "policy_version", "nodes", "edges", "topological_order", "node_count",
    "edge_count", "write_operation_count", "high_risk_count", "teardown_count",
    "confirmation_summary", "status",
)


def target_policy_sha256(target: Mapping[str, Any] | Any) -> str:
    """计算登记目标的不可逆安全快照，避免在计划中持久化内部 URL。"""

    item = _mapping(target)
    if not item:
        item = {
            key: getattr(target, key, "")
            for key in ("target_id", "environment", "internal_base_url", "allow_write_methods")
        }
    return canonical_sha256({
        "target_id": str(item.get("target_id", "")),
        "environment": str(item.get("environment", "")),
        "internal_base_url": str(item.get("internal_base_url", "")).rstrip("/"),
        "allow_write_methods": bool(item.get("allow_write_methods", False)),
    })


def validate_execution_plan_hashes(plan: Mapping[str, Any] | Any) -> bool:
    """重算编译期计划 SHA 和确认 SHA，拒绝存储后被修改的计划正文。

    人工确认只会增加确认人、时间和原因，并把状态从 ``ready`` 改为
    ``confirmed``；这些审计字段不属于编译期正文。校验时恢复 ``ready``，从而
    既保留不可变业务内容校验，也不要求确认动作重新生成计划标识。
    """

    item = _mapping(plan)
    if not item.get("target_policy_sha256"):
        return False
    compiled = {field: item.get(field) for field in _PLAN_HASH_FIELDS}
    compiled["status"] = "ready"
    confirmation_sha = canonical_sha256(compiled)
    if confirmation_sha != str(item.get("confirmation_sha256", "")):
        return False
    return canonical_sha256({**compiled, "confirmation_sha256": confirmation_sha}) == str(item.get("sha256", ""))


def rehash_execution_plan(plan: Mapping[str, Any] | Any) -> dict[str, Any]:
    """在 Pydantic 规范化后重建计划摘要，并保留 Review 审计字段。"""

    item = _mapping(plan)
    compiled = {field: item.get(field) for field in _PLAN_HASH_FIELDS}
    compiled["status"] = "ready"
    confirmation_sha = canonical_sha256(compiled)
    item["confirmation_sha256"] = confirmation_sha
    item["sha256"] = canonical_sha256({**compiled, "confirmation_sha256": confirmation_sha})
    return item


def compile_execution_plan(
    executable_cases: Sequence[Mapping[str, Any] | Any],
    *,
    task_id: str,
    source_executable_version: int,
    source_executable_sha256: str,
    target_id: str,
    environment: str,
    registered_targets: Mapping[str, Mapping[str, Any] | Any],
    resource_policy_id: str,
    egress_policy_id: str,
    policy_version: str,
    manual_edges: Iterable[Mapping[str, Any] | Any] = (),
) -> CompilationResult:
    """编译已确认执行定义为稳定的 ExecutionPlanV1 字典。

    参数说明：
        executable_cases: 已从版本存储选出的执行定义；当前阶段用字典协议，后续可由
            Pydantic V3 模型直接通过 ``model_dump`` 适配。
        registered_targets: 受部署配置控制的目标登记表，而不是来自浏览器的 Host。
        manual_edges: Review 已确认的顺序关系，每项使用 ``from_node``、``to_node`` 和
            可审计 ``reason``。

    返回值：
        无 blocker 时返回带 nodes、edges、稳定拓扑顺序和两个 SHA 的计划；出现任何
        blocker 时 ``plan`` 为 ``None``，调用方不得据此创建 Run。
    """

    blockers: list[PlanBlocker] = []
    target = _mapping(registered_targets.get(target_id))
    if not target:
        _block(blockers, "EXECUTION_PLAN_INVALID", "target_id", "目标未登记")
    elif str(target.get("environment", "")) != environment:
        _block(blockers, "EXECUTION_PLAN_INVALID", "environment", "目标环境与计划环境不一致")
    elif str(target.get("internal_base_url", "")).startswith("https://"):
        _block(blockers, "EGRESS_HTTPS_NOT_READY", "target_id", "当前受控出口尚未启用 HTTPS 目标")

    by_id: dict[str, dict[str, Any]] = {}
    for index, raw_case in enumerate(executable_cases):
        case = _mapping(raw_case)
        case_id = str(case.get("executable_case_id", ""))
        path = f"executable_cases[{index}]"
        if not case_id:
            _block(blockers, "EXECUTION_PLAN_INVALID", f"{path}.executable_case_id", "执行定义缺少 ID")
            continue
        # Review 明确禁用或静态校验禁用的定义属于历史/诊断产物，应保留展示但不
        # 进入计划。只有看似可执行却未确认、已过期或状态矛盾的定义才阻断编译。
        if case.get("review_status") == "disabled" or (
            case.get("validation_status") == "disabled" and case.get("enabled") is False
        ):
            continue
        if case_id in by_id:
            _block(blockers, "EXECUTION_PLAN_INVALID", f"{path}.executable_case_id", "执行定义 ID 重复")
            continue
        by_id[case_id] = case
        if (
            case.get("validation_status") != "ready"
            or case.get("enabled") is not True
            or case.get("review_status", "confirmed") != "confirmed"
            or case.get("lifecycle_status", "current") != "current"
        ):
            _block(blockers, "EXECUTION_PLAN_INVALID", case_id, "执行定义不是 current、confirmed、ready 状态")

    producers, conflicted_producer_names = _collect_producers(by_id, blockers)
    edges: list[dict[str, str]] = []
    for case_id in sorted(by_id):
        case = by_id[case_id]
        _add_explicit_edges(case_id, case, by_id, edges, blockers)
        _add_variable_edges(case_id, case, producers, conflicted_producer_names, edges, blockers)
    _add_session_edges(by_id, edges, blockers)
    _add_manual_edges(manual_edges, by_id, edges, blockers)

    edge_rows = _stable_edges(edges)
    topological_order = _stable_kahn(by_id, edge_rows)
    if len(topological_order) != len(by_id):
        _block(blockers, "EXECUTION_DEPENDENCY_CYCLE", "edges", "执行依赖图存在循环")

    write_count = 0
    high_risk_count = 0
    teardown_count = 0
    for case_id in sorted(by_id):
        case = by_id[case_id]
        request = _mapping(case.get("request"))
        method = str(request.get("method", "GET")).upper()
        if _contains_plaintext_credential(request, case.get("variable_consumers")):
            _block(
                blockers, "PLAINTEXT_CREDENTIAL_FORBIDDEN", f"{case_id}.request",
                "请求或变量默认值包含明文凭证；请改用运行时变量占位符",
            )
        for assertion_index, assertion in enumerate(case.get("assertions", []) or []):
            operator = str(_mapping(assertion).get("operator", ""))
            if operator not in SUPPORTED_ASSERTION_OPERATORS:
                _block(
                    blockers, "ASSERTION_OPERATOR_UNSUPPORTED",
                    f"{case_id}.assertions[{assertion_index}]", f"Executor 不支持断言操作符: {operator}",
                )
        if method in WRITE_METHODS:
            write_count += 1
            if target and not bool(target.get("allow_write_methods", False)):
                _block(
                    blockers, "EXECUTION_TARGET_WRITE_DENIED", f"{case_id}.request.method",
                    "目标未授权写操作",
                )
            if _retry_count(case) > 0 and not _write_retry_confirmed(case):
                _block(blockers, "WRITE_RETRY_NOT_ALLOWED", f"{case_id}.retry_policy", "写操作未确认幂等性，禁止自动重试")
        if case.get("risk_level") == "high":
            high_risk_count += 1
        if case.get("teardown_capabilities") or case.get("teardown_script"):
            teardown_count += 1

    if blockers:
        return CompilationResult(plan=None, blockers=tuple(blockers))

    nodes = [_plan_node(by_id[case_id]) for case_id in sorted(by_id)]
    confirmation_summary = {
        "node_count": len(nodes),
        "edge_count": len(edge_rows),
        "write_operation_count": write_count,
        "high_risk_count": high_risk_count,
        "teardown_count": teardown_count,
    }
    plan_without_hashes = {
        "artifact_schema_version": 1,
        "task_id": task_id,
        "source_executable_version": source_executable_version,
        "source_executable_sha256": source_executable_sha256,
        "target_id": target_id,
        "environment": environment,
        "target_policy_sha256": target_policy_sha256({"target_id": target_id, **target}),
        "resource_policy_id": resource_policy_id,
        "egress_policy_id": egress_policy_id,
        "policy_version": policy_version,
        "nodes": nodes,
        "edges": edge_rows,
        "topological_order": topological_order,
        **confirmation_summary,
        "confirmation_summary": confirmation_summary,
        "status": "ready",
    }
    confirmation_sha256 = canonical_sha256(plan_without_hashes)
    plan = {
        **plan_without_hashes,
        "confirmation_sha256": confirmation_sha256,
    }
    plan["sha256"] = canonical_sha256(plan)
    return CompilationResult(plan=plan, blockers=())


def _mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    """将字典或 Pydantic 风格对象转换为独立字典，避免编译时修改调用方数据。"""

    if isinstance(value, Mapping):
        return dict(value)
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper(mode="json")
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _block(blockers: list[PlanBlocker], code: str, field_path: str, detail: str) -> None:
    """按发现顺序记录 blocker；同一结构错误保留一次，便于页面稳定展示。"""

    blocker = PlanBlocker(code=code, field_path=field_path, detail=detail)
    if blocker not in blockers:
        blockers.append(blocker)


def _collect_producers(
    by_id: Mapping[str, Mapping[str, Any]], blockers: list[PlanBlocker],
) -> tuple[dict[str, tuple[str, dict[str, Any]]], set[str]]:
    """建立变量唯一生产者索引，重复名称在编译期失败关闭。"""

    raw_index: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for case_id in sorted(by_id):
        for producer in _mapping_list(by_id[case_id].get("variable_producers")):
            name = str(producer.get("name", ""))
            if name:
                raw_index[name].append((case_id, producer))
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    conflicted_names: set[str] = set()
    for name in sorted(raw_index):
        candidates = raw_index[name]
        if len(candidates) != 1:
            _block(blockers, "VARIABLE_NAME_CONFLICT", f"variable_producers.{name}", "同名变量存在多个生产节点")
            conflicted_names.add(name)
            continue
        index[name] = candidates[0]
    return index, conflicted_names


def _add_explicit_edges(
    case_id: str,
    case: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    edges: list[dict[str, str]],
    blockers: list[PlanBlocker],
) -> None:
    """把已声明的前置关系转换为可追溯边，并拒绝不存在节点。"""

    for dependency_id in sorted(str(value) for value in case.get("precondition_case_ids", []) or []):
        if dependency_id not in by_id:
            _block(blockers, "EXECUTION_DEPENDENCY_MISSING", f"{case_id}.precondition_case_ids", f"前置节点不存在: {dependency_id}")
            continue
        _edge(edges, dependency_id, case_id, "explicit_precondition", dependency_id, "显式前置条件")


def _add_variable_edges(
    case_id: str,
    case: Mapping[str, Any],
    producers: Mapping[str, tuple[str, dict[str, Any]]],
    conflicted_producer_names: set[str],
    edges: list[dict[str, str]],
    blockers: list[PlanBlocker],
) -> None:
    """验证 required 消费者有唯一来源，并建立生产者到消费者的边。"""

    for consumer in _mapping_list(case.get("variable_consumers")):
        name = str(consumer.get("name", ""))
        if not name:
            _block(blockers, "VARIABLE_SOURCE_MISSING", f"{case_id}.variable_consumers", "变量消费者缺少名称")
            continue
        producer = producers.get(name)
        if producer is None:
            # 重复生产者已经产生更准确的 VARIABLE_NAME_CONFLICT，不能再误报无来源。
            if name in conflicted_producer_names:
                continue
            if consumer.get("required", True) and not _controlled_input(consumer):
                _block(blockers, "VARIABLE_SOURCE_MISSING", f"{case_id}.variable_consumers.{name}", "required 变量没有生产者或受控输入")
            continue
        producer_id, _producer = producer
        _edge(edges, producer_id, case_id, "variable", name, "响应变量传递")


def _add_session_edges(
    by_id: Mapping[str, Mapping[str, Any]], edges: list[dict[str, str]], blockers: list[PlanBlocker],
) -> None:
    """把 Cookie/Session/CSRF 声明编译为边，避免依赖链仅靠偶然数组顺序。"""

    producers: dict[str, list[str]] = defaultdict(list)
    for case_id in sorted(by_id):
        for token in sorted(str(value) for value in by_id[case_id].get("session_produces", []) or []):
            producers[token].append(case_id)
    for case_id in sorted(by_id):
        for token in sorted(str(value) for value in by_id[case_id].get("session_consumes", []) or []):
            sources = producers.get(token, [])
            if len(sources) != 1:
                code = "VARIABLE_NAME_CONFLICT" if len(sources) > 1 else "EXECUTION_DEPENDENCY_MISSING"
                _block(blockers, code, f"{case_id}.session_consumes.{token}", "会话或 CSRF 来源必须唯一且存在")
                continue
            source_type = "csrf" if token.startswith("csrf:") else "cookie_session"
            _edge(edges, sources[0], case_id, source_type, token, "受控会话传递")


def _add_manual_edges(
    manual_edges: Iterable[Mapping[str, Any] | Any],
    by_id: Mapping[str, Mapping[str, Any]],
    edges: list[dict[str, str]],
    blockers: list[PlanBlocker],
) -> None:
    """接收 Review 已确认的顺序边；人工确认仍不能引用不存在节点。"""

    for index, raw_edge in enumerate(manual_edges):
        edge = _mapping(raw_edge)
        source = str(edge.get("from_node", ""))
        destination = str(edge.get("to_node", ""))
        if source not in by_id or destination not in by_id:
            _block(blockers, "EXECUTION_DEPENDENCY_MISSING", f"manual_edges[{index}]", "人工顺序关系引用了不存在节点")
            continue
        reason = str(edge.get("reason", "人工确认顺序"))
        _edge(edges, source, destination, "manual_order", reason, reason)


def _edge(
    edges: list[dict[str, str]], source: str, destination: str, source_type: str, source_ref: str, reason: str,
) -> None:
    """保存结构化边；相同节点对的不同来源要保留，供计划审查解释。"""

    edges.append({
        "from_node": source,
        "to_node": destination,
        "source_type": source_type,
        "source_ref": source_ref,
        "reason": reason,
    })


def _stable_edges(edges: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """去除完全重复边，并按所有可见字段排序，保障 SHA 和页面顺序稳定。"""

    unique = {
        (edge["from_node"], edge["to_node"], edge["source_type"], edge["source_ref"], edge["reason"])
        for edge in edges
    }
    return [
        {"from_node": source, "to_node": destination, "source_type": source_type, "source_ref": source_ref, "reason": reason}
        for source, destination, source_type, source_ref, reason in sorted(unique)
    ]


def _stable_kahn(nodes: Mapping[str, Mapping[str, Any]], edges: Iterable[Mapping[str, str]]) -> list[str]:
    """使用节点 ID 最小堆实现确定性 Kahn 拓扑排序。"""

    outgoing: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    for edge in edges:
        source, destination = edge["from_node"], edge["to_node"]
        if destination not in outgoing[source]:
            outgoing[source].add(destination)
            indegree[destination] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(queue)
    ordered: list[str] = []
    while queue:
        node_id = heapq.heappop(queue)
        ordered.append(node_id)
        for destination in sorted(outgoing[node_id]):
            indegree[destination] -= 1
            if indegree[destination] == 0:
                heapq.heappush(queue, destination)
    return ordered


def _plan_node(case: Mapping[str, Any]) -> dict[str, Any]:
    """复制计划执行所需的结构化字段，避免计划持有生成期无关内容。"""

    raw_retry = _mapping(case.get("retry_policy"))
    retry_policy = {
        "max_attempts": max(1, int(raw_retry.get("max_attempts", int(raw_retry.get("max_retries", 0) or 0) + 1))),
        "idempotent": bool(raw_retry.get("idempotent") or raw_retry.get("idempotent_confirmed")),
        "idempotency_key_header": str(
            raw_retry.get("idempotency_key_header") or raw_retry.get("idempotency_key_field") or ""
        ),
        "confirmed": bool(raw_retry.get("confirmed") or raw_retry.get("retry_confirmed")),
    }
    request = _mapping(case.get("request"))
    return {
        "node_id": str(case["executable_case_id"]),
        "executable_case_id": str(case["executable_case_id"]),
        "request": request,
        # 运行前必须能在不重新解释请求正文的情况下复核目标写权限；该字段由
        # 确定性 method 计算，不接受模型或浏览器直接声明。
        "write_operation": str(request.get("method", "GET")).upper() in WRITE_METHODS,
        "producers": _mapping_list(case.get("variable_producers")),
        "consumers": _mapping_list(case.get("variable_consumers")),
        "session_produces": sorted(str(value) for value in case.get("session_produces", []) or []),
        "session_consumes": sorted(str(value) for value in case.get("session_consumes", []) or []),
        "assertions": list(case.get("assertions", []) or []),
        "observation_targets": list(case.get("observation_targets", []) or []),
        "retry_policy": retry_policy,
        "failure_policy": _mapping(case.get("failure_policy")) or {"on_failure": "block_descendants"},
        "setup_capabilities": list(case.get("setup_capabilities", []) or []),
        "teardown_capabilities": list(case.get("teardown_capabilities", []) or []),
    }


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    """将列表中的协议对象安全转换为字典，忽略不合法条目。"""

    return [_mapping(item) for item in value if _mapping(item)] if isinstance(value, list) else []


def _controlled_input(consumer: Mapping[str, Any]) -> bool:
    """只允许明确标记的环境/测试数据输入绕过前置节点生产者。"""

    return bool(consumer.get("controlled_input")) or consumer.get("source") in {"environment", "test_data"}


def _retry_count(case: Mapping[str, Any]) -> int:
    """兼容最小 retry_policy 字典；畸形值按 0 处理并避免编译器抛异常。"""

    try:
        policy = _mapping(case.get("retry_policy"))
        if "max_attempts" in policy:
            return max(0, int(policy.get("max_attempts", 1)) - 1)
        return max(0, int(policy.get("max_retries", 0)))
    except (TypeError, ValueError):
        return 0


def _write_retry_confirmed(case: Mapping[str, Any]) -> bool:
    """写重试必须同时有人工确认的幂等语义及幂等键字段。"""

    policy = _mapping(case.get("retry_policy"))
    confirmed = bool(policy.get("confirmed") or policy.get("retry_confirmed"))
    idempotent = bool(policy.get("idempotent_confirmed") or policy.get("idempotent"))
    key = str(
        policy.get("idempotency_key_field") or policy.get("idempotency_key")
        or policy.get("idempotency_key_header")
        or ""
    )
    request = _mapping(case.get("request"))
    headers = _mapping(request.get("headers"))
    actual = next((value for name, value in headers.items() if str(name).lower() == key.lower()), "")
    return confirmed and idempotent and bool(key) and bool(str(actual).strip())


def _contains_plaintext_credential(request: Mapping[str, Any], consumers: Any) -> bool:
    """递归识别请求和变量默认值中的明文凭证；运行时占位符允许进入计划。"""

    def unsafe(value: Any, key: str = "") -> bool:
        if isinstance(value, Mapping):
            return any(unsafe(child, str(child_key)) for child_key, child in value.items())
        if isinstance(value, list):
            return any(unsafe(child, key) for child in value)
        if not _SENSITIVE_FIELD.search(key) or value in {None, ""}:
            return False
        text = str(value).strip()
        # 允许 ``Bearer {{access_token}}`` 等纯运行时引用，但拒绝混入任何固定值。
        without_placeholders = _RUNTIME_PLACEHOLDER.sub("", text)
        return not _RUNTIME_PLACEHOLDER.search(text) or bool(
            without_placeholders.strip().lower() not in {"", "bearer", "basic"}
        )

    if unsafe(request):
        return True
    for consumer in _mapping_list(consumers):
        if consumer.get("default_policy") != "use_default":
            continue
        key = f"{consumer.get('name', '')}.{consumer.get('field_path', '')}"
        if unsafe(consumer.get("default_value"), key):
            return True
    return False
