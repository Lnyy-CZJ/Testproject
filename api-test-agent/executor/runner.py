"""无凭证、无平台权限的固定 API Executor 入口。"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "api-key", "apikey", "api_key", "token", "access_token", "refresh_token", "password", "passwd", "secret"}


def redact(value: Any, key: str = "") -> Any:
    """在 Executor 输出前递归脱敏，避免原始容器日志和中间结果保存 Secret。"""

    if key.lower().replace("_", "-") in {item.replace("_", "-") for item in SENSITIVE_KEYS}:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value


def redact_response_body(body: str) -> Any:
    """JSON 响应按字段递归脱敏；非 JSON 仅保留受限文本。"""

    try:
        return redact(json.loads(body))
    except (TypeError, json.JSONDecodeError):
        return body[:65536]


def now() -> str:
    """返回 UTC 时间字符串，供 CaseResult 审计使用。"""

    return datetime.now(UTC).isoformat()


def classify(status_code: int | None, error: str) -> str:
    """使用确定性规则区分目标响应失败与运行环境失败。"""

    if error:
        return "environment_blocked"
    if status_code is not None and status_code >= 500:
        return "product_defect_candidate"
    if status_code is not None and status_code >= 400:
        return "test_data_issue"
    return "none"


def run_case(case: dict[str, Any], target_base_url: str, timeout_seconds: int) -> dict[str, Any]:
    """执行单条已静态校验用例；脚本能力在本机首轮试点中保持拒绝。"""

    case_id = str(case.get("executable_case_id", ""))
    started_at = now()
    started = time.monotonic()
    request_data = case.get("request") or {}
    if case.get("setup_script") or case.get("teardown_script"):
        finished = now()
        return {
            "case_id": case_id, "status": "error", "started_at": started_at, "finished_at": finished,
            "duration_ms": 0, "failure_classification": "test_case_issue",
            "error_signature": "EXECUTOR_SCRIPT_NOT_SUPPORTED", "step_results": [],
            "request_summary": {}, "response_summary": {}, "assertion_results": [],
        }
    query = urllib.parse.urlencode(request_data.get("query") or {}, doseq=True)
    path = str(request_data.get("path", "/"))
    url = target_base_url.rstrip("/") + path + (f"?{query}" if query else "")
    body = request_data.get("body")
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {str(key): str(value) for key, value in (request_data.get("headers") or {}).items()}
    if encoded is not None:
        headers.setdefault("Content-Type", "application/json")
    response_body, response_headers, error_text = "", {}, ""
    status_code: int | None = None
    try:
        request = urllib.request.Request(url, data=encoded, headers=headers, method=str(request_data.get("method", "GET")))
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            response_headers = dict(response.headers.items())
            response_body = response.read(1024 * 1024).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        response_headers = dict(exc.headers.items())
        response_body = exc.read(1024 * 1024).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        error_text = type(exc).__name__
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    assertions = []
    for assertion in case.get("assertions") or []:
        operator = assertion.get("operator")
        if operator == "status_code":
            passed = status_code == assertion.get("expected")
        elif operator == "contains":
            passed = str(assertion.get("expected", "")) in response_body
        else:
            passed = True
        assertions.append({"operator": operator, "passed": passed, "expected": assertion.get("expected")})
    assertion_failed = any(not item["passed"] for item in assertions)
    status = "error" if error_text else ("failed" if assertion_failed else "passed")
    return {
        "case_id": case_id, "status": status, "started_at": started_at, "finished_at": now(),
        "duration_ms": duration_ms, "step_results": [],
        "request_summary": redact({"method": request_data.get("method"), "path": path, "headers": headers, "body": body}),
        "response_summary": redact({"status_code": status_code, "headers": response_headers, "body": redact_response_body(response_body)}),
        "assertion_results": assertions, "failure_classification": classify(status_code, error_text),
        "error_signature": error_text or ("ASSERTION_FAILED" if assertion_failed else ""),
    }


def main() -> int:
    """读取只读输入并将标准 JSON 写到 stdout，由 Controller 捕获保存。"""

    payload = json.loads(Path("/run/input/input.json").read_text(encoding="utf-8"))
    base_url = str(payload["resolved_target_url"])
    timeout = int(payload.get("request_timeout_seconds", 10))
    result = {"run_id": payload["run_id"], "case_results": [run_case(case, base_url, timeout) for case in payload["cases"]]}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
