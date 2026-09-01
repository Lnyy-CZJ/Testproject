"""不包含业务重试、可选记录完整原始交换的 HTTP Transport。"""

import base64
from collections.abc import Callable
import json
import time
from typing import Any, Protocol
from urllib.parse import urlsplit
import threading

import requests

from aidating_eval.errors import TransportError
from aidating_eval.wire_logging import RawWireLogger


class _SessionLike(Protocol):
    def request(self, method: str, url: str, **kwargs: Any): ...
    def get(self, url: str, **kwargs: Any): ...
    def put(self, url: str, **kwargs: Any): ...


class RequestsTransport:
    """每个线程持有独立 Session；Adapter 决定幂等和业务重试策略。"""

    def __init__(
        self,
        timeout_seconds: float = 15,
        *,
        session_factory: Callable[[], _SessionLike] = requests.Session,
        wire_logger: RawWireLogger | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._session_factory = session_factory
        self._wire_logger = wire_logger
        self._local = threading.local()

    def _session(self) -> _SessionLike:
        if not hasattr(self._local, "session"):
            self._local.session = self._session_factory()
        return self._local.session

    def get_status(self, url: str) -> int:
        """执行禁止重定向的健康检查，并记录完整响应正文。"""

        exchange_id = self._begin_exchange("GET", url, headers={}, body_kind="none")
        started = time.monotonic()
        try:
            response = self._session().get(
                url,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            self._log_prepared_request(exchange_id, getattr(exc, "request", None))
            self._log_error(exchange_id, started, exc)
            raise TransportError(type(exc).__name__) from exc
        self._log_prepared_request(exchange_id, getattr(response, "request", None))
        self._log_response(exchange_id, started, response)
        return int(response.status_code)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """发送 JSON 请求；调用方异常保持稳定，Wire Log 保留原始上下文。"""

        exchange_id = self._begin_exchange(
            method,
            url,
            headers=headers,
            body_kind="json",
            json_body=json_body,
        )
        started = time.monotonic()
        try:
            response = self._session().request(
                method,
                url,
                headers=dict(headers),
                json=json_body,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            self._log_prepared_request(exchange_id, getattr(exc, "request", None))
            self._log_error(exchange_id, started, exc)
            raise TransportError(type(exc).__name__) from exc

        self._log_prepared_request(exchange_id, getattr(response, "request", None))
        if not 200 <= response.status_code < 300:
            self._log_response(exchange_id, started, response)
            error = TransportError(f"HTTP_{response.status_code}")
            self._log_error(exchange_id, started, error)
            raise error
        try:
            body = response.json()
        except ValueError as exc:
            self._log_response(exchange_id, started, response)
            self._log_error(exchange_id, started, exc)
            raise TransportError("INVALID_JSON") from exc
        self._log_response(exchange_id, started, response, json_body=body)
        if not isinstance(body, dict):
            error = TransportError("INVALID_JSON_OBJECT")
            self._log_error(exchange_id, started, error)
            raise error
        return body

    def put_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
    ) -> int:
        """将图片原始字节 PUT 到 HTTPS 预签名地址，并以 Base64 写入 Wire Log。"""

        exchange_id = self._begin_exchange(
            "PUT",
            url,
            headers=headers,
            body_kind="binary",
            body_base64=base64.b64encode(content).decode("ascii"),
            content_length=len(content),
        )
        started = time.monotonic()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            self._log_error(exchange_id, started, exc)
            raise TransportError("INVALID_UPLOAD_URL") from exc
        if parsed.scheme != "https" or not parsed.netloc:
            error = TransportError("INSECURE_UPLOAD_URL")
            self._log_error(exchange_id, started, error)
            raise error
        try:
            response = self._session().put(
                url,
                headers=dict(headers),
                data=content,
                timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            self._log_prepared_request(exchange_id, getattr(exc, "request", None))
            self._log_error(exchange_id, started, exc)
            raise TransportError(type(exc).__name__) from exc
        self._log_prepared_request(exchange_id, getattr(response, "request", None))
        self._log_response(
            exchange_id,
            started,
            response,
            include_body_base64=True,
        )
        if not 200 <= response.status_code < 300:
            error = TransportError(f"HTTP_{response.status_code}")
            self._log_error(exchange_id, started, error)
            raise error
        return int(response.status_code)

    def _begin_exchange(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body_kind: str,
        json_body: dict[str, Any] | None = None,
        body_base64: str | None = None,
        content_length: int | None = None,
    ) -> str:
        """记录请求并返回并发安全的关联 ID；未启用日志时保持零开销路径。"""

        if self._wire_logger is None:
            return ""
        try:
            exchange_id = self._wire_logger.new_exchange_id()
        except Exception:
            # 日志对象异常不能阻止真实请求，更不能让 Create 成功结果丢失 task_id。
            return ""
        fields: dict[str, Any] = {
            "exchange_id": exchange_id,
            "method": method,
            "url": url,
            "headers": dict(headers),
            "body_kind": body_kind,
            "timeout_seconds": self.timeout_seconds,
            "allow_redirects": False,
        }
        if body_kind == "json":
            fields["json_body"] = json_body
        elif body_kind == "binary":
            fields["body_base64"] = body_base64
            fields["content_length"] = content_length
        self._write_wire("http_request", **fields)
        return exchange_id

    def _log_prepared_request(self, exchange_id: str, prepared: Any) -> None:
        """记录 Requests 最终发送的 URL、运行时 Header 和序列化正文。

        ``http_request`` 保留业务调用参数，便于网络尚未 prepare 就失败时排查；本事件则来自
        ``Response.request`` 或 ``RequestException.request``，包含 Session 默认 Header、Cookie、
        URL 编码和 Content-Length 等实际 Wire 视图。
        """

        if self._wire_logger is None or prepared is None:
            return
        try:
            headers = dict(getattr(prepared, "headers", {}) or {})
            body = getattr(prepared, "body", None)
            fields: dict[str, Any] = {
                "exchange_id": exchange_id,
                "method": getattr(prepared, "method", None),
                "url": getattr(prepared, "url", None),
                "headers": headers,
            }
            if body is None:
                fields["body_kind"] = "none"
            elif isinstance(body, str):
                fields["body_kind"] = "text"
                fields["body_text"] = body
                fields["content_length"] = len(body.encode("utf-8"))
                self._add_json_body_if_possible(fields, headers, body)
            elif isinstance(body, bytes):
                fields["body_kind"] = "binary"
                fields["body_base64"] = base64.b64encode(body).decode("ascii")
                fields["content_length"] = len(body)
                try:
                    text_body = body.decode("utf-8")
                except UnicodeDecodeError:
                    text_body = None
                if text_body is not None:
                    fields["body_text"] = text_body
                    self._add_json_body_if_possible(fields, headers, text_body)
            else:
                # 当前产品只发送 JSON 与图片 bytes；保留未知 body 的具体类型和 repr 供排障。
                fields["body_kind"] = type(body).__name__
                fields["body_repr"] = repr(body)
            self._write_wire("http_prepared_request", **fields)
        except Exception:
            # 检查或序列化 PreparedRequest 也不能覆盖已经发生的网络结果。
            return

    @staticmethod
    def _add_json_body_if_possible(
        fields: dict[str, Any], headers: dict[str, Any], body: str
    ) -> None:
        """在 Content-Type 为 JSON 时提供可检索结构，同时保留原始 body_text。"""

        content_type = str(headers.get("Content-Type", "")).lower()
        if "json" not in content_type:
            return
        try:
            fields["json_body"] = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return

    def _log_response(
        self,
        exchange_id: str,
        started: float,
        response: Any,
        *,
        json_body: Any | None = None,
        include_body_base64: bool = False,
    ) -> None:
        """记录服务端原始 Header/正文以及解析后的 JSON，便于对照协议结构。"""

        if self._wire_logger is None:
            return
        raw_content = getattr(response, "content", b"")
        if not isinstance(raw_content, bytes):
            raw_content = bytes(raw_content)
        fields: dict[str, Any] = {
            "exchange_id": exchange_id,
            "status_code": int(response.status_code),
            "headers": dict(getattr(response, "headers", {}) or {}),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "body_text": getattr(response, "text", None),
        }
        if json_body is not None:
            fields["json_body"] = json_body
        if include_body_base64:
            fields["body_base64"] = base64.b64encode(raw_content).decode("ascii")
        self._write_wire("http_response", **fields)

    def _log_error(
        self,
        exchange_id: str,
        started: float,
        exc: BaseException,
    ) -> None:
        """把原始异常消息写入本地日志，同时不改变对 CLI 暴露的稳定错误。"""

        if self._wire_logger is None:
            return
        self._write_wire(
            "http_error",
            exchange_id=exchange_id,
            error_type=type(exc).__name__,
            message=str(exc),
            elapsed_ms=round((time.monotonic() - started) * 1000, 3),
        )

    def _write_wire(self, event: str, **fields: Any) -> None:
        """隔离任意 logger 实现的异常，保证日志永远不改变网络与清理语义。"""

        if self._wire_logger is None:
            return
        try:
            self._wire_logger.write(event, **fields)
        except Exception:
            # RawWireLogger 自身已经 fail-open；这里同时保护测试替身及未来 logger。
            return
