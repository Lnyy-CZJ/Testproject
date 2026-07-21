"""COS 预签名 PUT 客户端的安全与失败语义测试。"""

from typing import Any

import pytest
import requests

from framework.client.cos_client import CosClient, CosUploadError


class _Response:
    """模拟 requests PUT 响应。"""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    """记录 PUT 参数并返回或抛出预设结果。"""

    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.close_calls = 0

    def put(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        self.close_calls += 1


def test_cos_put_uses_server_headers_binary_body_and_split_timeout() -> None:
    session = _Session(_Response(200))
    client = CosClient(session=session, connect_timeout=1.5, read_timeout=4.5)
    content = b"binary-image-content"
    headers = {"Content-Type": "image/jpeg", "x-cos-meta-owner": "test"}

    client.put(
        "https://bucket.example.test/media.jpg?X-Cos-Signature=secret",
        upload_headers=headers,
        content=content,
    )

    assert session.calls == [
        {
            "url": "https://bucket.example.test/media.jpg?X-Cos-Signature=secret",
            "headers": headers,
            "data": content,
            "timeout": (1.5, 4.5),
            "allow_redirects": False,
        }
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://cos.example.test/file?signature=secret",
        "ftp://cos.example.test/file",
    ],
)
def test_cos_put_rejects_non_https_remote_url_before_network(url: str) -> None:
    session = _Session(_Response(200))

    with pytest.raises(ValueError, match="HTTPS"):
        CosClient(session=session).put(url, upload_headers={}, content=b"x")

    assert session.calls == []


@pytest.mark.parametrize(
    "url",
    ["http://localhost:9000/file", "http://127.0.0.1:9000/file", "http://[::1]:9000/file"],
)
def test_cos_put_allows_local_http_for_offline_contract(url: str) -> None:
    session = _Session(_Response(204))

    CosClient(session=session).put(url, upload_headers={}, content=b"x")

    assert len(session.calls) == 1


def test_cos_put_wraps_read_timeout_without_logging_content() -> None:
    diagnostics: list[dict[str, Any]] = []
    content = b"unique-private-image-bytes"
    client = CosClient(
        session=_Session(requests.ReadTimeout("slow")),
        diagnostic_hook=diagnostics.append,
    )

    with pytest.raises(CosUploadError, match="ReadTimeout"):
        client.put(
            "https://bucket.example.test/file?X-Amz-Signature=signature-secret",
            upload_headers={"Content-Type": "image/png"},
            content=content,
        )

    serialized = str(diagnostics)
    assert "signature-secret" not in serialized
    assert content.decode() not in serialized
    assert diagnostics[0]["error_type"] == "ReadTimeout"


def test_cos_put_non_2xx_emits_signature_redacted_diagnostic() -> None:
    diagnostics: list[dict[str, Any]] = []
    client = CosClient(
        session=_Session(_Response(403)), diagnostic_hook=diagnostics.append
    )

    with pytest.raises(CosUploadError, match="HTTPError"):
        client.put(
            "https://bucket.example.test/file?signature=signature-secret&part=1",
            upload_headers={"Authorization": "server-signed-header"},
            content=b"private-image",
        )

    serialized = str(diagnostics)
    assert "signature-secret" not in serialized
    assert "private-image" not in serialized
    assert diagnostics[0]["http_status"] == 403


@pytest.mark.parametrize(
    "outcome",
    [
        requests.ConnectionError(
            "connect https://bucket.example.test/file?signature=TOPSECRET"
        ),
        requests.ReadTimeout(
            "read https://bucket.example.test/file?signature=TOPSECRET"
        ),
    ],
)
def test_cos_network_error_text_and_exception_chain_hide_presigned_url(
    outcome: requests.RequestException,
) -> None:
    client = CosClient(session=_Session(outcome))

    with pytest.raises(CosUploadError) as captured:
        client.put(
            "https://bucket.example.test/file?signature=TOPSECRET",
            upload_headers={},
            content=b"private",
        )

    assert "TOPSECRET" not in str(captured.value)
    assert "redacted" in str(captured.value).lower()
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_cos_http_error_text_and_exception_chain_hide_presigned_url() -> None:
    class _LeakyHttpResponse(_Response):
        """模拟 requests 将完整请求 URL 写入 HTTP 异常消息。"""

        def raise_for_status(self) -> None:
            raise requests.HTTPError(
                "403 https://bucket.example.test/file?signature=TOPSECRET"
            )

    client = CosClient(session=_Session(_LeakyHttpResponse(403)))

    with pytest.raises(CosUploadError) as captured:
        client.put(
            "https://bucket.example.test/file?signature=TOPSECRET",
            upload_headers={},
            content=b"private",
        )

    assert "TOPSECRET" not in str(captured.value)
    assert "HTTPError" in str(captured.value)
    assert "403" in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


@pytest.mark.parametrize("status_code", [301, 302, 307, 308])
def test_cos_redirect_is_failure_and_redirect_following_is_disabled(
    status_code: int,
) -> None:
    session = _Session(_Response(status_code))
    client = CosClient(session=session)

    with pytest.raises(CosUploadError, match=str(status_code)):
        client.put(
            "https://bucket.example.test/file?signature=TOPSECRET",
            upload_headers={"Authorization": "server-header"},
            content=b"private-body",
        )

    assert len(session.calls) == 1
    assert session.calls[0]["allow_redirects"] is False


def test_cos_error_and_diagnostic_hide_userinfo_query_fragment_and_raw_url() -> None:
    diagnostics: list[dict[str, Any]] = []
    raw_url = (
        "https://TOPSECRET-user:TOPSECRET-pass@bucket.example.test/secret-path"
        "?signature=TOPSECRET-query#TOPSECRET-fragment"
    )
    client = CosClient(
        session=_Session(_Response(403)), diagnostic_hook=diagnostics.append
    )

    with pytest.raises((CosUploadError, ValueError)) as captured:
        client.put(raw_url, upload_headers={}, content=b"private")

    serialized = f"{captured.value!s} {diagnostics!s}"
    assert raw_url not in serialized
    assert "TOPSECRET" not in serialized
    assert "secret-path" not in serialized
    assert "bucket.example.test" in serialized
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_malformed_url_has_fixed_safe_error_without_parse_exception_chain() -> None:
    raw_url = "https://[TOPSECRET?signature=TOPSECRET"
    client = CosClient(session=_Session(_Response(200)))

    with pytest.raises(ValueError, match="COS URL 无效") as captured:
        client.put(raw_url, upload_headers={}, content=b"private")

    assert "TOPSECRET" not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_injected_session_is_external_and_not_closed_by_client_context() -> None:
    session = _Session(_Response(204))

    with CosClient(session=session) as client:
        assert client is not None

    assert session.close_calls == 0


def test_self_created_session_is_closed_by_close_and_context(monkeypatch) -> None:
    created_sessions: list[_Session] = []

    def _create_session() -> _Session:
        session = _Session(_Response(204))
        created_sessions.append(session)
        return session

    monkeypatch.setattr(requests, "Session", _create_session)
    client = CosClient()

    with client as entered:
        assert entered is client
    client.close()

    assert created_sessions[0].close_calls == 1
