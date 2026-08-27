"""通用签名二进制上传动作的边界与日志脱敏测试。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from utils.custom.flow_runner import FlowEnvironmentError, FlowRunner
from utils.custom.http_client import mask_sensitive
from utils.custom.runtime_context import RuntimeContext


class _Response:
    """模拟 requests 响应，仅暴露通用动作需要的状态码。"""

    status_code = 200


class _RecordingClient:
    """记录二进制 PUT 参数，避免真实外部上传。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def put_bytes(self, **kwargs: object) -> _Response:
        """保存调用并返回成功响应。"""
        self.calls.append(kwargs)
        return _Response()


class _Gateway:
    """向 FlowRunner 提供 HTTP 客户端与超时配置。"""

    def __init__(self, client: _RecordingClient) -> None:
        self.http_client = client
        self.settings = {"timeout": 5}


def test_signed_binary_upload_reads_current_project_fixture_and_redacts_query(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """上传只读当前项目 fixture，日志不得包含签名 URL 查询参数。"""
    fixture = tmp_path / "fixtures/chat.jpg"
    fixture.parent.mkdir()
    fixture.write_bytes(b"private-image")
    client = _RecordingClient()
    context = RuntimeContext(
        {
            "signed_url": "https://cos.example.com/object?signature=top-secret&token=abc",
            "signed_headers": {"Content-Type": "image/jpeg"},
        }
    )
    action = {
        "type": "signed_binary_upload",
        "url": "{{signed_url}}",
        "headers": "{{signed_headers}}",
        "fixture": "chat.jpg",
        "method": "PUT",
        "success_statuses": [200, 204],
    }

    with caplog.at_level(logging.INFO):
        FlowRunner(tmp_path, gateway_factory=lambda _: None)._execute_action(
            action, _Gateway(client), context
        )

    assert client.calls[0]["url"].endswith("signature=top-secret&token=abc")
    assert client.calls[0]["content"] == b"private-image"
    assert "top-secret" not in caplog.text
    assert "token=abc" not in caplog.text
    assert "https://cos.example.com/object?<redacted>" in caplog.text


def test_signed_binary_upload_rejects_fixture_escape(tmp_path: Path) -> None:
    """通用动作不能使用 ../ 读取项目外或其他项目 fixture。"""
    (tmp_path / "fixtures").mkdir()
    (tmp_path.parent / "secret.jpg").write_bytes(b"secret")
    context = RuntimeContext(
        {"signed_url": "https://cos.example/upload?signature=x", "signed_headers": {}}
    )
    action = {
        "type": "signed_binary_upload",
        "url": "{{signed_url}}",
        "headers": "{{signed_headers}}",
        "fixture": "../secret.jpg",
        "method": "PUT",
        "success_statuses": [200],
    }

    with pytest.raises(FlowEnvironmentError, match="fixture.*越界"):
        FlowRunner(tmp_path, gateway_factory=lambda _: None)._execute_action(
            action, _Gateway(_RecordingClient()), context
        )


def test_signed_upload_headers_and_nested_url_are_redacted() -> None:
    """对象存储自定义签名 Header 与嵌套 URL 都不能进入日志或附件。"""
    masked = mask_sensitive(
        {
            "required_headers": {
                "x-cos-security-token": "header-secret",
                "x-signature": "signed-value",
                "Content-Type": "image/jpeg",
            },
            "upload_url": "https://cos.example/object?signature=query-secret",
        }
    )

    assert masked["required_headers"] == {
        "x-cos-security-token": "***",
        "x-signature": "***",
        "Content-Type": "image/jpeg",
    }
    assert "query-secret" not in masked["upload_url"]
