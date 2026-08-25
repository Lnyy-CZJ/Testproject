"""稳定错误码与 Flask 错误响应。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any

from services.common.redaction import redact_structure


@dataclass(slots=True)
class ServiceError(Exception):
    """表示可安全返回给浏览器的业务错误。

    参数说明:
        status_code: HTTP 状态码。
        code: 稳定错误码。
        message: 已脱敏的中文错误摘要。
    """

    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False
    suggested_action: str = ""


def error_payload(error: ServiceError, request_id: str) -> dict:
    """构造不包含内部异常信息的统一错误响应。"""

    payload: dict[str, Any] = {
        "code": error.code, "message": error.message, "request_id": request_id,
        "retryable": error.retryable or error.status_code >= 500,
        "suggested_action": error.suggested_action or (
            "请稍后重试或携带请求 ID 联系管理员" if error.status_code >= 500 else "请检查输入或刷新后重试"
        ),
    }
    if error.details:
        payload["details"] = error.details
    return {"error": payload}


def structured_log(logger: logging.Logger, level: str = "info", **fields: Any) -> None:
    """使用标准库输出单行脱敏 JSON，供 request_id 和任务 ID 关联排障。"""

    payload = redact_structure({
        "timestamp": datetime.now(UTC).isoformat(), "level": level, **fields,
    })
    getattr(logger, level if level in {"debug", "info", "warning", "error"} else "info")(
        json.dumps(payload, ensure_ascii=False, default=str)
    )


INVALID_INPUT = "INVALID_INPUT"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TASK_QUEUE_FULL = "TASK_QUEUE_FULL"
INVALID_TASK_STATE = "INVALID_TASK_STATE"
REVIEW_FILE_INVALID = "REVIEW_FILE_INVALID"
REVIEW_REVISION_CONFLICT = "REVIEW_REVISION_CONFLICT"
REVIEW_DRAFT_REQUIRED = "REVIEW_DRAFT_REQUIRED"
REVIEW_WARNING_CONFIRMATION_REQUIRED = "REVIEW_WARNING_CONFIRMATION_REQUIRED"
REVIEW_VALIDATION_FAILED = "REVIEW_VALIDATION_FAILED"
REVIEW_AI_ALREADY_RUNNING = "REVIEW_AI_ALREADY_RUNNING"
REVIEW_AI_BASE_CHANGED = "REVIEW_AI_BASE_CHANGED"
REVIEW_AI_SCOPE_REQUIRED = "REVIEW_AI_SCOPE_REQUIRED"
REVIEW_AI_RESPONSE_INVALID = "REVIEW_AI_RESPONSE_INVALID"
STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
QUEUE_FULL = "QUEUE_FULL"
FEATURE_DISABLED = "FEATURE_DISABLED"
CONFIG_NOT_READY = "CONFIG_NOT_READY"
PLATFORM_CONFIG_UNAVAILABLE = "PLATFORM_CONFIG_UNAVAILABLE"
WORKER_INTERRUPTED = "WORKER_INTERRUPTED"
TASK_TIMEOUT = "TASK_TIMEOUT"
ARTIFACT_PUBLISH_FAILED = "ARTIFACT_PUBLISH_FAILED"
LLM_AUTH_FAILED = "LLM_AUTH_FAILED"
LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
LLM_TIMEOUT = "LLM_TIMEOUT"
LLM_RESPONSE_INVALID = "LLM_RESPONSE_INVALID"
QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"


def classify_runner_exception(
    error: Exception,
    *,
    default_code: str,
    default_message: str,
) -> tuple[str, str]:
    """把第三方模型异常归一为稳定且不泄露原文的任务错误。

    参数说明:
        error: Runner 捕获的原始异常，仅用于类型、状态码和特征词判断。
        default_code: 无法识别时使用的工作流错误码。
        default_message: 无法识别时使用的中文安全摘要。

    返回值:
        tuple[str, str]: 稳定错误码与可展示摘要。

    异常策略:
        本函数自身不抛异常；未知 SDK 仍落到调用方给定的通用失败，原始
        异常只保留在经过二次脱敏的任务日志中。
    """

    if isinstance(error, ServiceError):
        return error.code, error.message
    type_name = type(error).__name__.lower()
    message = str(error).lower()
    status_code = getattr(error, "status_code", None)
    if str(error) == CONFIG_NOT_READY:
        return CONFIG_NOT_READY, "必需配置尚未就绪"
    if status_code == 429 or "ratelimit" in type_name or "rate limit" in message or "insufficient_quota" in message:
        return LLM_RATE_LIMITED, "模型服务当前限流或额度不足，请稍后重试"
    if status_code in {401, 403} or "authentication" in type_name or "invalid api key" in message:
        return LLM_AUTH_FAILED, "模型服务鉴权失败，请联系管理员检查 Secret"
    if isinstance(error, TimeoutError) or "timeout" in type_name or "timed out" in message:
        return LLM_TIMEOUT, "模型服务响应超时，请稍后重试"
    if any(name in type_name for name in ("outputparser", "jsondecode", "validationerror")):
        return LLM_RESPONSE_INVALID, "模型输出格式不合法且无法修复"
    if "qualitygate" in type_name or "quality gate" in message or "质量门禁" in message:
        return QUALITY_GATE_FAILED, "生成结果未通过质量门禁"
    return default_code, default_message
