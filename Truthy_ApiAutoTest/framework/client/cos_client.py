"""仅用于 COS 预签名 URL 的二进制 PUT 客户端。"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from ipaddress import ip_address
import re
from typing import Any
from urllib.parse import SplitResult, urlsplit

import requests


class CosUploadError(RuntimeError):
    """COS 上传安全异常，消息和异常链均不包含原始预签名 URL。

    功能说明:
        使用安全字段描述 COS 上传失败，不保留原始预签名 URL 或异常链。
    参数说明:
        redacted_url: 已移除全部查询参数值的 URL；error_type: 底层失败类别；
        http_status: 可选 HTTP 状态。
    返回值:
        异常字符串只包含安全诊断字段。
    异常说明:
        本异常由 :meth:`CosClient.put` 在底层 ``except`` 块之外抛出，因此
        ``__context__`` 和 ``__cause__`` 不会保留可能含完整 URL 的 requests 异常。
    """

    def __init__(
        self,
        *,
        redacted_url: str,
        error_type: str,
        http_status: int | None,
    ) -> None:
        status_text = str(http_status) if http_status is not None else "unknown"
        super().__init__(
            f"COS PUT 失败: error_type={error_type}, "
            f"http_status={status_text}, url={redacted_url}"
        )


_SAFE_HOST_PATTERN = re.compile(r"^[A-Za-z0-9.:-]{1,253}$")


def _parse_url(url: str) -> SplitResult:
    """在单一安全边界解析 URL，解析失败时不链接底层异常或回显输入。"""
    parse_failed = False
    parsed: SplitResult | None = None
    try:
        if not isinstance(url, str):
            raise TypeError("url is not str")
        parsed = urlsplit(url)
        # hostname 属性本身也可能对畸形 IPv6/转义输入抛出 ValueError。
        _ = parsed.hostname
    except (TypeError, ValueError):
        parse_failed = True
    if parse_failed or parsed is None:
        raise ValueError("COS URL 无效: url=<redacted>") from None
    return parsed


def _is_local_http_url(parsed: SplitResult) -> bool:
    """判断已安全解析的 URL 是否为 localhost 或回环 HTTP 地址。"""
    if parsed.scheme.lower() != "http":
        return False
    hostname = parsed.hostname or ""
    if hostname.lower() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _safe_url_summary(parsed: SplitResult) -> str:
    """仅保留协议与安全主机摘要，不包含 userinfo、路径、查询或 fragment。"""
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    safe_host = hostname if _SAFE_HOST_PATTERN.fullmatch(hostname) else "<redacted>"
    return f"{scheme or '<unknown>'}://{safe_host or '<redacted>'}/<redacted>"


class CosClient:
    """使用服务端预签名 URL 和请求头上传二进制内容。

    功能说明:
        仅使用服务端预签名 URL 和指定请求头执行二进制 PUT。
    参数说明:
        session: 可注入且由调用方持有的 requests 会话，客户端不会关闭；未注入时
        客户端创建并持有会话，可通过 ``close`` 或上下文管理关闭。其余参数为独立
        连接/读取超时和只接收安全摘要的诊断钩子。
    返回值:
        :meth:`put` 成功时无返回值。
    异常说明:
        远程非 HTTPS URL 抛出 ``ValueError``；连接/读取异常和 HTTP 非 2xx
        响应统一转换为不保留原始异常链的 :class:`CosUploadError`。
    """

    def __init__(
        self,
        *,
        session: Any | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        diagnostic_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._owns_session = session is None
        self._session = session if session is not None else requests.Session()
        self._closed = False
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._diagnostic_hook = diagnostic_hook

    def _emit(
        self,
        *,
        url_summary: str,
        started_at: float,
        http_status: int | None = None,
        error_type: str | None = None,
    ) -> None:
        """发送最小安全诊断，不记录上传请求头或图片内容。"""
        if self._diagnostic_hook is None:
            return
        diagnostic: dict[str, Any] = {
            "method": "PUT",
            "url": url_summary,
            "http_status": http_status,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
        if error_type is not None:
            diagnostic["error_type"] = error_type
        self._diagnostic_hook(diagnostic)

    def put(
        self,
        url: str,
        *,
        upload_headers: Mapping[str, str],
        content: bytes,
    ) -> None:
        """向一次性预签名 URL PUT 二进制体。

        功能说明:
            校验 URL 后执行禁重定向 PUT，并仅输出安全诊断。
        参数说明:
            url: 服务端 ``PrepareMediaUpload`` 返回的短期 URL；upload_headers:
            服务端原样返回的上传请求头；content: 图片二进制体。
        返回值:
            HTTP 2xx 时返回 ``None``。
        异常说明:
            非 localhost 的 URL 必须为 HTTPS；超时、连接失败或 HTTP 非 2xx
            转换为 :class:`CosUploadError`。诊断和对外异常均不会包含图片内容、
            请求头或 URL 签名，也不会链接可能泄密的底层异常。
        """
        parsed = _parse_url(url)
        url_summary = _safe_url_summary(parsed)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError(f"COS URL 无效: url={url_summary}")
        if not parsed.hostname:
            raise ValueError("COS URL 无效: url=<redacted>")
        if parsed.scheme.lower() != "https" and not _is_local_http_url(parsed):
            raise ValueError("非 localhost 的 COS 预签名 URL 必须使用 HTTPS")
        started_at = time.perf_counter()
        safe_error: CosUploadError | None = None
        try:
            response = self._session.put(
                url,
                headers=upload_headers,
                data=content,
                timeout=(self._connect_timeout, self._read_timeout),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is None:
                status = getattr(locals().get("response"), "status_code", None)
            self._emit(
                url_summary=url_summary,
                started_at=started_at,
                http_status=status,
                error_type=type(exc).__name__,
            )
            safe_error = CosUploadError(
                redacted_url=url_summary,
                error_type=type(exc).__name__,
                http_status=status,
            )
        if safe_error is None:
            status = getattr(response, "status_code", None)
            if isinstance(status, bool) or not isinstance(status, int):
                safe_error = CosUploadError(
                    redacted_url=url_summary,
                    error_type="InvalidHTTPStatus",
                    http_status=None,
                )
            elif not 200 <= status < 300:
                self._emit(
                    url_summary=url_summary,
                    started_at=started_at,
                    http_status=status,
                    error_type="HTTPError",
                )
                safe_error = CosUploadError(
                    redacted_url=url_summary,
                    error_type="HTTPError",
                    http_status=status,
                )
        if safe_error is not None:
            # 必须在 except 块外抛出，确保 __context__ 不指向可能包含签名 URL 的异常。
            raise safe_error from None
        self._emit(
            url_summary=url_summary,
            started_at=started_at,
            http_status=response.status_code,
        )

    def close(self) -> None:
        """关闭客户端自建会话。

        功能说明:
            幂等关闭内部创建的 Session；注入的外部 Session 始终由调用方管理。
        参数说明:
            无。
        返回值:
            无。
        异常说明:
            自建 Session 的 ``close`` 异常原样传播。
        """
        if self._owns_session and not self._closed:
            self._session.close()
            self._closed = True

    def __enter__(self) -> "CosClient":
        """返回客户端自身，供真实上传使用确定性资源生命周期。"""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """退出上下文时仅关闭客户端自建会话，不吞掉业务异常。"""
        self.close()
