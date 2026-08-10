"""requests HTTP 调用与敏感信息脱敏封装。"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from utils.custom.logger import get_logger
from utils.third_party.allure_reporter import attach_json

LOGGER = get_logger(__name__)
SENSITIVE_KEYS = {
    "access_token",
    "auth_token",
    "authorization",
    "refresh_token",
    "token",
}


def mask_sensitive(data: Any) -> Any:
    """递归复制并脱敏字典或列表中的敏感字段。

    参数说明:
        data: 准备写入日志的数据，可为任意 JSON 兼容结构。

    返回值:
        脱敏后的副本；原对象不会被修改。
    """
    if isinstance(data, dict):
        masked: dict[Any, Any] = {}
        for key, value in data.items():
            normalized_key = str(key).lower()
            if normalized_key in SENSITIVE_KEYS:
                masked[key] = "***"
            elif (
                isinstance(value, str)
                and (normalized_key == "url" or normalized_key.endswith("_url"))
            ):
                # PrepareMediaUpload 的响应也可能携带预签名 URL，响应日志同样要脱敏。
                masked[key] = _mask_signed_url(value)
            else:
                masked[key] = mask_sensitive(value)
        return masked
    if isinstance(data, list):
        return [mask_sensitive(item) for item in data]
    return deepcopy(data)


def _format_log_data(data: Any) -> str:
    """将请求或响应数据格式化为便于终端阅读的文本。

    参数说明:
        data: JSON 兼容对象或普通文本。

    返回值:
        JSON 对象使用中文友好的缩进格式；其他类型转换为字符串。

    异常说明:
        不向调用方抛出序列化异常，遇到非 JSON 类型时回退为字符串。
    """
    try:
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(data)


def _mask_signed_url(url: str) -> str:
    """移除签名 URL 查询参数，避免对象存储临时凭证进入日志。"""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "***" if parts.query else "", ""))


class HttpClient:
    """提供框架统一使用的最小 HTTP POST JSON 能力。"""

    def __init__(self, session: Any | None = None) -> None:
        """创建客户端；允许测试注入兼容 requests.Session 的替身。"""
        self.session = session or requests.Session()

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> requests.Response:
        """发送 JSON POST 请求。

        参数说明:
            url: 完整请求地址。
            headers: HTTP 请求头。
            payload: Gateway JSON 请求体。
            timeout: 请求超时秒数。

        返回值:
            requests 返回的 Response 对象。

        异常说明:
            requests.RequestException: 网络错误或超时时记录脱敏请求后原样抛出。
        """
        safe_request = {
            "url": url,
            "headers": mask_sensitive(headers),
            "payload": mask_sensitive(payload),
        }
        LOGGER.info("Gateway 请求数据:\n%s", _format_log_data(safe_request))
        attach_json("Gateway 请求", safe_request)
        started_at = time.perf_counter()
        try:
            response = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            # 异常日志复用脱敏后的请求副本，避免网络失败时泄露凭证。
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            attach_json(
                "Gateway 请求异常",
                {
                    "request": safe_request,
                    "elapsed_ms": elapsed_ms,
                    "exception_type": type(exc).__name__,
                },
            )
            LOGGER.error(
                "Gateway 请求异常: elapsed_ms=%.2f\n%s",
                elapsed_ms,
                _format_log_data(safe_request),
            )
            raise

        try:
            response_body = response.json()
            response_attachment = {
                "status_code": response.status_code,
                "elapsed_ms": (time.perf_counter() - started_at) * 1000,
                "body_type": "json",
                "body": mask_sensitive(response_body),
            }
        except (TypeError, ValueError):
            # 非 JSON 响应仍需输出原始文本，方便定位网关或代理异常。
            response_body = getattr(response, "text", "")
            # 报告不保存非 JSON 正文，只保留足以判断代理错误的类型和长度。
            response_attachment = {
                "status_code": response.status_code,
                "elapsed_ms": (time.perf_counter() - started_at) * 1000,
                "body_type": "text",
                "body_length": len(response_body),
            }
        attach_json("Gateway 响应", response_attachment)
        LOGGER.info(
            "Gateway 响应数据: HTTP %s elapsed_ms=%.2f\n%s",
            response.status_code,
            (time.perf_counter() - started_at) * 1000,
            _format_log_data(mask_sensitive(response_body)),
        )
        return response

    def put_bytes(
        self,
        url: str,
        headers: dict[str, str],
        content: bytes,
        timeout: float,
    ) -> requests.Response:
        """向预签名地址上传二进制内容。

        参数说明:
            url: PrepareMediaUpload 返回的预签名上传地址。
            headers: PrepareMediaUpload 返回的 upload_headers，原样用于 PUT。
            content: 待上传文件的原始字节。
            timeout: 请求超时秒数。

        返回值:
            requests 返回的 Response；由流程层判断是否为 HTTP 2xx。

        异常说明:
            requests.RequestException: 网络错误或超时时记录脱敏信息后原样抛出。
        """
        safe_request = {
            "url": _mask_signed_url(url),
            "headers": mask_sensitive(headers),
            "content_length": len(content),
        }
        LOGGER.info("PUT 上传请求数据:\n%s", _format_log_data(safe_request))
        attach_json("COS PUT 请求", safe_request)
        started_at = time.perf_counter()
        try:
            response = self.session.put(
                url=url,
                headers=headers,
                data=content,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            attach_json(
                "COS PUT 请求异常",
                {
                    "request": safe_request,
                    "elapsed_ms": elapsed_ms,
                    "exception_type": type(exc).__name__,
                },
            )
            LOGGER.error(
                "PUT 上传请求异常: elapsed_ms=%.2f\n%s",
                elapsed_ms,
                _format_log_data(safe_request),
            )
            raise
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        attach_json(
            "COS PUT 响应",
            {
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        LOGGER.info(
            "PUT 上传响应: HTTP %s elapsed_ms=%.2f",
            response.status_code,
            elapsed_ms,
        )
        return response
