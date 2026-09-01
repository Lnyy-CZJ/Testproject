"""历史 ``redact_text`` 兼容入口的原文与截断行为测试。"""

from __future__ import annotations

from pathlib import PosixPath

import pytest

from web.redaction import redact_text, truncate_tail


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bearer abc123.def456-xyz",
        "headers={'Authorization': 'raw-secret-value'}",
        "Cookie: session=secret-session-id; theme=dark",
        "AUTH_TOKEN=super-secret-auth",
        '{"refresh_token": "json-secret-value", "name": "case"}',
        "url=https://cdn.example.com/a.jpg?Signature=s3cr3t&width=100",
    ],
)
def test_sensitive_text_is_preserved_verbatim(text: str) -> None:
    """日志兼容入口不得修改 Header、Token、Cookie 或签名 URL。"""
    assert redact_text(text) == text


def test_container_path_is_preserved() -> None:
    """原始日志需要保留完整文件路径，便于在本机直接定位代码。"""
    root = PosixPath("/app")
    text = 'File "/app/test_cases/test_single_api.py", line 10'

    assert redact_text(text, project_root=root) == text


def test_truncation_applied() -> None:
    """超长文本仍按显示上限截断，但不得修改截断范围内的内容。"""
    result = redact_text("y" * 5000, max_length=100)

    assert len(result) <= 100 + len("...(truncated)")
    assert result.endswith("...(truncated)")


def test_plain_text_unchanged() -> None:
    """普通文本原样返回。"""
    text = "3 passed, 1 failed in 2.34s"

    assert redact_text(text) == text


def test_tail_truncation_preserves_latest_original_text() -> None:
    """日志尾部限长必须保留最终异常，而不是保留文件开头。"""
    result = truncate_tail("BEGIN-" + "x" * 5000 + "-FINAL-ERROR", max_length=100)

    assert len(result) <= 100
    assert result.startswith("...(truncated)")
    assert result.endswith("-FINAL-ERROR")
    assert "BEGIN-" not in result
