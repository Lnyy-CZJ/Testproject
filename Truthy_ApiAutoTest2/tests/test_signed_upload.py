"""通用签名二进制上传动作的边界与原始日志测试。"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from utils.custom.flow_runner import (
    FlowEnvironmentError,
    FlowExecutionError,
    FlowRunner,
)
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


def test_signed_binary_upload_reads_current_project_fixture_and_logs_full_url(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """上传只读当前项目 fixture，日志完整保留签名 URL 查询参数。"""
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
    assert "top-secret" in caplog.text
    assert "token=abc" in caplog.text
    assert (
        "https://cos.example.com/object?signature=top-secret&token=abc"
        in caplog.text
    )


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


def test_signed_binary_upload_reads_current_task_input(tmp_path: Path) -> None:
    """input_file 只从当前任务 inputs 读取，不依赖项目 fixture。"""

    input_root = tmp_path / "runtime/dating/task/inputs"
    input_root.mkdir(parents=True)
    (input_root / "001-chat.png").write_bytes(b"task-image")
    client = _RecordingClient()
    context = RuntimeContext(
        {
            "media_file": {"relative_path": "001-chat.png"},
            "signed_url": "https://cos.example/upload",
            "signed_headers": {"Content-Type": "image/png"},
        }
    )
    action = {
        "type": "signed_binary_upload",
        "url": "{{signed_url}}",
        "headers": "{{signed_headers}}",
        "input_file": "{{media_file.relative_path}}",
        "method": "PUT",
    }

    FlowRunner(
        tmp_path,
        gateway_factory=lambda _: None,
        task_input_root=input_root,
    )._execute_action(action, _Gateway(client), context)

    assert client.calls[0]["content"] == b"task-image"


@pytest.mark.parametrize("input_file", ["../outside.png", "/tmp/outside.png"])
def test_signed_binary_upload_rejects_task_input_escape(
    tmp_path: Path,
    input_file: str,
) -> None:
    """input_file 的绝对路径和父目录穿越必须在读取前拒绝。"""

    input_root = tmp_path / "inputs"
    input_root.mkdir()
    (tmp_path / "outside.png").write_bytes(b"outside")
    action = {
        "type": "signed_binary_upload",
        "url": "https://cos.example/upload",
        "headers": {},
        "input_file": input_file,
    }

    with pytest.raises(FlowEnvironmentError, match="input_file.*越界"):
        FlowRunner(
            tmp_path,
            gateway_factory=lambda _: None,
            task_input_root=input_root,
        )._execute_action(action, _Gateway(_RecordingClient()), RuntimeContext())


def test_validate_binary_inputs_uses_live_constraints() -> None:
    """上传前必须用 GetMediaUploadConfig 提取的实时限制校验完整输入列表。"""

    context = RuntimeContext(
        {
            "media_files": [
                {"content_type": "image/png", "size_bytes": 100},
                {"content_type": "image/jpeg", "size_bytes": 200},
            ],
            "allowed_types": ["image/png", "image/jpeg"],
            "min_assets": 1,
            "max_assets": 9,
            "max_bytes": 1024,
        }
    )
    action = {
        "type": "validate_binary_inputs",
        "files": "{{media_files}}",
        "allowed_content_types": "{{allowed_types}}",
        "min_items": "{{min_assets}}",
        "max_items": "{{max_assets}}",
        "max_size_bytes": "{{max_bytes}}",
    }
    runner = FlowRunner(Path("."), gateway_factory=lambda _: None)

    runner._execute_action(action, None, context)
    context.set("max_bytes", 150)
    with pytest.raises(FlowExecutionError, match="FLOW_INPUT_CONSTRAINT_FAILED.*200"):
        runner._execute_action(action, None, context)


def test_signed_upload_headers_and_nested_url_are_preserved() -> None:
    """对象存储自定义签名 Header 与嵌套 URL 必须完整进入日志和附件。"""
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
        "x-cos-security-token": "header-secret",
        "x-signature": "signed-value",
        "Content-Type": "image/jpeg",
    }
    assert masked["upload_url"] == (
        "https://cos.example/object?signature=query-secret"
    )
