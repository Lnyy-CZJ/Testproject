"""无凭证、无平台权限的受限 API 依赖执行器入口。

本模块只消费当前 Run 挂载的不可变输入。它不导入平台服务、模型、数据库或旧
执行器，所有依赖变量、Cookie 与节点状态均局限在单个容器进程的内存中。
"""

from __future__ import annotations

import json
import copy
import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {
    "authorization", "proxy-authorization", "cookie", "set-cookie", "api-key", "apikey",
    "api_key", "token", "access_token", "refresh_token", "password", "passwd", "secret",
    # Session/CSRF 值也可能同时出现在 Cookie 和 JSON 响应中，均不得进入结果文件。
    "session", "sessionid", "session_id", "csrf", "csrf_token", "x-csrf-token",
}
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 测试可替换此单一受控出口；生产环境始终调用 urllib，网络边界仍由 Egress Proxy 约束。
send_request = urllib.request.urlopen


class VariableValueMissing(ValueError):
    """请求模板引用了当前 Run 尚未产生的变量。"""


class ExtractionFailed(ValueError):
    """受控提取规则无法安全地产生变量值。"""


class RunContext:
    """单 Run 内存态：变量、Cookie、节点终态和脱敏所需的最小执行上下文。"""

    def __init__(self) -> None:
        self.variables: dict[str, Any] = {}
        # 使用标准 CookieJar 执行 Domain/Path/Secure/Expires 语义；原值只存在于
        # 当前短生命周期容器内存，结果文件只输出名称和数量。
        self.cookie_jar = http.cookiejar.CookieJar()
        self.node_states: dict[str, str] = {}
        self.block_reasons: dict[str, str] = {}

    def resolve(self, value: Any) -> Any:
        """递归替换 ``{{variable}}``，完整占位符返回原生类型而非字符串。"""

        if isinstance(value, str):
            full = PLACEHOLDER.fullmatch(value)
            if full:
                return self._variable(full.group(1))

            def replace(match: re.Match[str]) -> str:
                return str(self._variable(match.group(1)))

            return PLACEHOLDER.sub(replace, value)
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self.resolve(item) for key, item in value.items()}
        return value

    def _variable(self, name: str) -> Any:
        if name not in self.variables:
            raise VariableValueMissing(name)
        return self.variables[name]

    def add_response_cookies(
        self, response: Any, request: urllib.request.Request, headers: dict[str, str],
    ) -> None:
        """将响应 Cookie 纳入标准 CookieJar；测试替身不完整时使用受限回退。"""

        try:
            self.cookie_jar.extract_cookies(response, request)
            return
        except (AttributeError, TypeError, ValueError):
            # 单元测试响应不一定实现 ``info()``。回退仅用于无法提取时，并仍把
            # Cookie 绑定到当前请求主机，避免退化为跨目标的全局字典。
            pass

        raw = _header_value(headers, "set-cookie")
        if not raw:
            return
        parsed = SimpleCookie()
        try:
            parsed.load(raw)
        except (TypeError, ValueError):
            return
        domain = (urllib.parse.urlparse(request.full_url).hostname or "").lower()
        for name, morsel in parsed.items():
            self.cookie_jar.set_cookie(http.cookiejar.Cookie(
                version=0, name=name, value=morsel.value, port=None, port_specified=False,
                domain=domain, domain_specified=False, domain_initial_dot=False,
                path=morsel["path"] or "/", path_specified=bool(morsel["path"]),
                secure=bool(morsel["secure"]), expires=None, discard=True,
                comment=None, comment_url=None, rest={}, rfc2109=False,
            ))

    def cookie_value(self, name: str) -> str:
        """按名称读取当前 Run Cookie；仅供已确认的提取规则写入变量上下文。"""

        for cookie in self.cookie_jar:
            if cookie.name == name:
                return cookie.value
        raise ExtractionFailed("COOKIE_VALUE_MISSING")


def redact(value: Any, key: str = "") -> Any:
    """在 stdout 前递归脱敏，避免请求、响应与 Cookie 原值进入结果文件。"""

    if key.lower().replace("_", "-") in {item.replace("_", "-") for item in SENSITIVE_KEYS}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value


def redact_response_body(body: str) -> Any:
    """JSON 响应按字段递归脱敏；非 JSON 响应只保留受限长度文本。"""

    try:
        return redact(json.loads(body))
    except (TypeError, json.JSONDecodeError):
        return body[:65536]


def now() -> str:
    """返回 UTC 时间字符串，供节点和用例结果审计使用。"""

    return datetime.now(UTC).isoformat()


def classify(status_code: int | None, error: str) -> str:
    """使用确定性规则区分目标响应失败、用例错误和运行环境失败。"""

    if error:
        return "test_case_issue" if error.startswith(("ASSERTION_", "VARIABLE_", "WRITE_RETRY_", "EXTRACTION_")) else "environment_blocked"
    if status_code is not None and status_code >= 500:
        return "product_defect_candidate"
    if status_code is not None and status_code >= 400:
        return "test_data_issue"
    return "none"


def _header_value(headers: dict[str, str], name: str) -> str:
    """按 HTTP Header 的大小写不敏感语义读取字段。"""

    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def _json_pointer(document: Any, pointer: str) -> Any:
    """实现受限 JSON Pointer，拒绝无效路径与无效数组下标。"""

    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ExtractionFailed("JSON_POINTER_INVALID")
    current = document
    for part in pointer[1:].split("/"):
        token = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ExtractionFailed("JSON_POINTER_VALUE_MISSING")
    return current


def _controlled_regex(pattern: str, text: str) -> str:
    """限制正则长度、输入长度和高风险语法，避免文本提取放大容器 CPU 风险。"""

    if not pattern or len(pattern) > 256 or "(?" in pattern or re.search(r"\\[1-9]", pattern):
        raise ExtractionFailed("REGEX_NOT_ALLOWED")
    try:
        match = re.search(pattern, text[:65536])
    except re.error as exc:
        raise ExtractionFailed("REGEX_INVALID") from exc
    if not match:
        raise ExtractionFailed("REGEX_VALUE_MISSING")
    return match.group(1) if match.lastindex else match.group(0)


def _extract_value(rule: dict[str, Any], *, body: str, headers: dict[str, str], status_code: int | None, context: RunContext) -> Any:
    """从允许的响应位置提取值；不支持 JMESPath 或任意脚本。"""

    # 执行计划使用 V3 ``VariableProducer``（extractor_type/source_path），
    # 旧夹具仍可能使用 source/pointer/header。这里只做确定性字段别名适配。
    source = str(rule.get("source") or rule.get("kind") or rule.get("extractor_type") or "")
    source_path = str(rule.get("source_path") or "")
    if source in {"json_pointer", "json"}:
        try:
            document = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ExtractionFailed("JSON_RESPONSE_INVALID") from exc
        return _json_pointer(document, str(rule.get("pointer") or rule.get("path") or source_path))
    if source == "header":
        value = _header_value(headers, str(rule.get("header") or rule.get("key") or source_path))
        if not value:
            raise ExtractionFailed("HEADER_VALUE_MISSING")
        return value
    if source in {"cookie", "cookie_jar"}:
        name = str(rule.get("cookie") or rule.get("key") or source_path)
        return context.cookie_value(name)
    if source in {"status", "status_code"}:
        if status_code is None:
            raise ExtractionFailed("STATUS_CODE_MISSING")
        return status_code
    if source == "regex":
        return _controlled_regex(str(rule.get("pattern") or source_path), body)
    raise ExtractionFailed("EXTRACTION_SOURCE_UNSUPPORTED")


def _assertions(assertions: list[dict[str, Any]], *, status_code: int | None, body: str, context: RunContext) -> tuple[list[dict[str, Any]], str]:
    """执行已确认断言；未知操作符失败关闭，不能被默认放行。"""

    results: list[dict[str, Any]] = []
    error = ""
    for assertion in assertions:
        operator = str(assertion.get("operator") or "")
        try:
            expected = context.resolve(assertion.get("expected"))
        except VariableValueMissing:
            results.append({"operator": operator, "passed": False, "expected": "[MISSING_VARIABLE]"})
            error = "VARIABLE_VALUE_MISSING"
            continue
        if operator == "status_code":
            passed = status_code == expected
        elif operator == "contains":
            passed = str(expected) in body
        elif operator == "json_pointer_equals":
            try:
                passed = _json_pointer(json.loads(body), str(assertion.get("pointer") or "")) == expected
            except (json.JSONDecodeError, ExtractionFailed):
                passed = False
        else:
            passed = False
            error = "ASSERTION_UNKNOWN_OPERATOR"
        results.append({"operator": operator, "passed": passed, "expected": redact(expected, "expected")})
    return results, error


def _request_headers(request_data: dict[str, Any], context: RunContext, encoded: bytes | None) -> dict[str, str]:
    """组合已确认 Header 和显式 Cookie；CookieJar 随后按 URL 安全补充会话。"""

    headers = {str(key): str(value) for key, value in (request_data.get("headers") or {}).items()}
    cookies = {str(key): str(value) for key, value in (request_data.get("cookies") or {}).items()}
    if cookies and not _header_value(headers, "cookie"):
        headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in sorted(cookies.items()))
    if encoded is not None:
        headers.setdefault("Content-Type", "application/json")
    return headers


def _node_id(node: dict[str, Any], index: int) -> str:
    """兼容计划节点与旧 executable case，避免由外部输入生成空节点 ID。"""

    return str(node.get("node_id") or node.get("id") or node.get("executable_case_id") or f"node_{index}")


def _dependency_ids(node: dict[str, Any]) -> set[str]:
    """读取计划编译器已确认的显式依赖，不在运行时猜测变量或业务依赖。"""

    raw = node.get("depends_on") or node.get("precondition_case_ids") or node.get("dependencies") or []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    result = set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            item = item.get("node_id") or item.get("case_id") or item.get("id")
        if item:
            result.add(str(item))
    return result


def _plan_nodes(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], dict[str, set[str]]]:
    """只读取 V2.4 计划节点和拓扑；无计划输入必须失败关闭。"""

    plan = payload.get("execution_plan") or payload.get("plan") or {}
    if not isinstance(plan, dict) or not isinstance(plan.get("nodes"), list):
        raise ValueError("EXECUTION_PLAN_INVALID")
    planned_nodes = plan.get("nodes") if isinstance(plan, dict) else None
    nodes = planned_nodes
    normalized = [item for item in nodes if isinstance(item, dict)]
    ids = [_node_id(node, index) for index, node in enumerate(normalized)]
    by_id = dict(zip(ids, normalized, strict=True))
    requested_order = plan.get("topological_order") if isinstance(plan, dict) else []
    ordered_ids = [str(item.get("node_id") if isinstance(item, dict) else item) for item in requested_order or []]
    ordered_ids = [item for item in ordered_ids if item in by_id]
    ordered_ids.extend(item for item in ids if item not in ordered_ids)
    dependencies = {node_id: _dependency_ids(by_id[node_id]) for node_id in ordered_ids}
    edges = plan.get("edges", []) if isinstance(plan, dict) else []
    for edge in edges if isinstance(edges, list) else []:
        if not isinstance(edge, dict):
            continue
        source = edge.get("from_node") or edge.get("from_node_id") or edge.get("from") or edge.get("source")
        target = edge.get("to_node") or edge.get("to_node_id") or edge.get("to") or edge.get("target")
        if source and target and str(source) in by_id and str(target) in dependencies:
            dependencies[str(target)].add(str(source))
    return [by_id[node_id] for node_id in ordered_ids], ordered_ids, dependencies


def _set_nested_value(container: dict[str, Any], field_path: str, value: Any) -> None:
    """按受控 JSON Pointer/点路径写入请求体，不执行任意表达式。"""

    parts = field_path[1:].split("/") if field_path.startswith("/") else field_path.split(".")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in parts if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise VariableValueMissing(field_path)
    current = container
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise VariableValueMissing(field_path)
        current = child
    current[parts[-1]] = value


def _apply_variable_consumers(
    node: dict[str, Any], request_data: dict[str, Any], context: RunContext,
) -> dict[str, Any]:
    """按 Review 后的 destination/field_path 注入变量，缺失值默认失败关闭。"""

    request_data = copy.deepcopy(request_data)
    for consumer in node.get("consumers") or node.get("variable_consumers") or []:
        if not isinstance(consumer, dict):
            raise VariableValueMissing("consumer")
        name = str(consumer.get("name") or "")
        try:
            value = context._variable(name)
        except VariableValueMissing:
            if consumer.get("default_policy") == "use_default":
                value = consumer.get("default_value")
            elif consumer.get("required", True):
                raise
            else:
                continue
        destination = str(consumer.get("destination") or "")
        field_path = str(consumer.get("field_path") or "")
        if destination in {"query", "header", "cookie"}:
            key = {"query": "query", "header": "headers", "cookie": "cookies"}[destination]
            bucket = request_data.setdefault(key, {})
            if not isinstance(bucket, dict) or not field_path:
                raise VariableValueMissing(name)
            bucket[field_path] = value
        elif destination == "body":
            body = request_data.setdefault("body", {})
            if not isinstance(body, dict):
                raise VariableValueMissing(name)
            _set_nested_value(body, field_path, value)
        elif destination == "path":
            path = str(request_data.get("path") or "")
            marker = "{" + field_path + "}"
            if not field_path or marker not in path:
                raise VariableValueMissing(name)
            request_data["path"] = path.replace(marker, urllib.parse.quote(str(value), safe=""))
        else:
            raise VariableValueMissing(name)
    return request_data


def _terminal_result(node_id: str, node: dict[str, Any], status: str, error: str, dependencies: set[str]) -> dict[str, Any]:
    """构造未发请求的节点终态，保证取消、超时和阻断也有可审计结果。"""

    timestamp = now()
    return {
        "node_id": node_id, "case_id": str(node.get("executable_case_id") or node_id), "status": status,
        "started_at": timestamp, "finished_at": timestamp, "duration_ms": 0,
        "precondition_node_ids": sorted(dependencies), "request_summary": {}, "response_summary": {},
        "assertion_results": [], "extracted_variables": [], "cookie_jar_size": 0,
        "failure_classification": classify(None, error), "error_signature": error, "retry_count": 0,
    }


def _execute_node(node_id: str, node: dict[str, Any], context: RunContext, target_base_url: str, timeout_seconds: int, dependencies: set[str]) -> dict[str, Any]:
    """执行单节点 HTTP 请求、断言和提取；脚本与未确认写重试均在容器内拒绝。"""

    started_at = now()
    started = time.monotonic()
    request_data = node.get("request") or {}
    if not isinstance(request_data, dict):
        return _terminal_result(node_id, node, "error", "EXECUTION_PLAN_INVALID", dependencies)
    if node.get("setup_script") or node.get("teardown_script") or request_data.get("script"):
        return _terminal_result(node_id, node, "error", "EXECUTOR_SCRIPT_NOT_SUPPORTED", dependencies)
    try:
        request_data = _apply_variable_consumers(node, request_data, context)
        request_data = context.resolve(request_data)
    except VariableValueMissing:
        return _terminal_result(node_id, node, "blocked", "VARIABLE_VALUE_MISSING", dependencies)
    method = str(request_data.get("method", "GET")).upper()
    retry_policy = node.get("retry_policy") if isinstance(node.get("retry_policy"), dict) else {}
    # V3 模型以总尝试次数表达，旧输入以重试次数表达；两者不得累加。
    if "max_attempts" in retry_policy:
        max_retries = max(0, int(retry_policy.get("max_attempts", 1) or 1) - 1)
    else:
        max_retries = max(0, int(retry_policy.get("max_retries", 0) or 0))
    query = urllib.parse.urlencode(request_data.get("query") or {}, doseq=True)
    path = str(request_data.get("path", "/"))
    url = target_base_url.rstrip("/") + path + (f"?{query}" if query else "")
    body = request_data.get("body")
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = _request_headers(request_data, context, encoded)
    retry_confirmed = bool(retry_policy.get("confirmed") or retry_policy.get("retry_confirmed"))
    idempotent = bool(retry_policy.get("idempotent"))
    idempotency_header = str(retry_policy.get("idempotency_key_header") or "")
    has_idempotency_key = bool(idempotency_header and _header_value(headers, idempotency_header).strip())
    if max_retries and method not in READ_METHODS and not (idempotent and retry_confirmed and has_idempotency_key):
        return _terminal_result(node_id, node, "error", "WRITE_RETRY_NOT_ALLOWED", dependencies)
    response_body, response_headers, error_text, status_code = "", {}, "", None
    effective_headers = dict(headers)
    retry_count = 0
    for attempt in range(max_retries + 1):
        try:
            request = urllib.request.Request(url, data=encoded, headers=headers, method=method)
            context.cookie_jar.add_cookie_header(request)
            effective_headers = {str(key): str(value) for key, value in request.header_items()}
            # ``urllib.request.urlopen`` 的第二个位置参数是请求体 data，而不是
            # timeout。GET 等无 Body 请求若把整数超时作为位置参数传入，会在
            # http.client 中被误当作消息体并导致容器崩溃，因此必须显式传关键字。
            response = send_request(request, timeout=timeout_seconds)
            try:
                status_code = response.status
                response_headers = {str(key): str(value) for key, value in response.headers.items()}
                context.add_response_cookies(response, request, response_headers)
                response_body = response.read(1024 * 1024).decode("utf-8", errors="replace")
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            break
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            response_headers = {str(key): str(value) for key, value in exc.headers.items()}
            context.add_response_cookies(exc, request, response_headers)
            response_body = exc.read(1024 * 1024).decode("utf-8", errors="replace")
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error_text = type(exc).__name__
            if attempt >= max_retries:
                break
            retry_count += 1
    assertions, assertion_error = _assertions(
        [item for item in node.get("assertions") or [] if isinstance(item, dict)],
        status_code=status_code, body=response_body, context=context,
    )
    if assertion_error:
        error_text = assertion_error
    elif any(not item["passed"] for item in assertions):
        error_text = "ASSERTION_FAILED"
    extracted: list[dict[str, Any]] = []
    if not error_text:
        try:
            rules = node.get("extractors") or node.get("extract") or node.get("producers") or []
            for rule in rules:
                if not isinstance(rule, dict) or not str(rule.get("name") or ""):
                    raise ExtractionFailed("EXTRACTION_RULE_INVALID")
                name = str(rule["name"])
                context.variables[name] = _extract_value(rule, body=response_body, headers=response_headers, status_code=status_code, context=context)
                extracted.append({"name": name, "redacted": name.lower() in SENSITIVE_KEYS})
        except ExtractionFailed as exc:
            error_text = str(exc)
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    status = "error" if error_text and status_code is None else ("failed" if error_text.startswith("ASSERTION_") else ("error" if error_text else "passed"))
    return {
        "node_id": node_id, "case_id": str(node.get("executable_case_id") or node_id), "status": status,
        "started_at": started_at, "finished_at": now(), "duration_ms": duration_ms,
        "precondition_node_ids": sorted(dependencies),
        "request_summary": redact({"method": method, "path": path, "headers": effective_headers, "body": body}),
        "response_summary": redact({"status_code": status_code, "headers": response_headers, "body": redact_response_body(response_body)}),
        "assertion_results": assertions, "extracted_variables": extracted, "cookie_jar_size": len(list(context.cookie_jar)),
        "failure_classification": classify(status_code, error_text), "error_signature": error_text,
        "retry_count": retry_count,
    }


def execute_run(payload: dict[str, Any]) -> dict[str, Any]:
    """按计划拓扑串行执行，失败只阻断后继，旧 cases 输入仅作为兼容回退。"""

    target_base_url = str(payload["resolved_target_url"])
    timeout_seconds = max(1, int(payload.get("request_timeout_seconds", 10) or 10))
    run_timeout = payload.get("run_timeout_seconds")
    deadline = time.monotonic() + max(0, int(run_timeout)) if run_timeout is not None else None
    nodes, node_ids, dependencies = _plan_nodes(payload)
    context = RunContext()
    step_results: list[dict[str, Any]] = []
    cancelled = bool(payload.get("cancelled"))
    for node_id, node in zip(node_ids, nodes, strict=True):
        check = payload.get("cancel_check")
        cancellation_requested = cancelled or (bool(check()) if callable(check) else False)
        if cancellation_requested:
            result = _terminal_result(node_id, node, "cancelled", "RUN_CANCELLED", dependencies[node_id])
        elif deadline is not None and time.monotonic() >= deadline:
            result = _terminal_result(node_id, node, "timed_out", "RUN_TIMEOUT", dependencies[node_id])
        else:
            # 依赖状态缺失说明拓扑或计划损坏，也必须阻断，不能被当成“尚未失败”。
            failed_dependencies = [item for item in dependencies[node_id] if context.node_states.get(item) != "passed"]
            if failed_dependencies:
                result = _terminal_result(node_id, node, "blocked", "DEPENDENCY_NODE_BLOCKED", dependencies[node_id])
                result["blocked_by"] = sorted(failed_dependencies)
            else:
                result = _execute_node(node_id, node, context, target_base_url, timeout_seconds, dependencies[node_id])
        context.node_states[node_id] = str(result["status"])
        if result["status"] == "blocked":
            context.block_reasons[node_id] = str(result["error_signature"])
        step_results.append(result)
    case_results = [{key: value for key, value in result.items() if key != "node_id"} for result in step_results]
    return {
        "run_id": payload["run_id"], "case_results": case_results, "step_results": step_results,
        "dependency_propagation": {"node_states": context.node_states, "blocked_reasons": context.block_reasons},
    }


def run_case(case: dict[str, Any], target_base_url: str, timeout_seconds: int) -> dict[str, Any]:
    """保留旧单 case 调用入口，内部复用受限节点执行语义。"""

    node_id = _node_id(case, 0)
    return _execute_node(node_id, case, RunContext(), target_base_url, timeout_seconds, _dependency_ids(case))


def main() -> int:
    """读取当前 Run 的只读输入并将脱敏 JSON 写到 stdout，由 Controller 保存。"""

    payload = json.loads(Path("/run/input/input.json").read_text(encoding="utf-8"))
    print(json.dumps(execute_run(payload), ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
