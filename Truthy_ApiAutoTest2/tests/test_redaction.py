"""redaction 二次脱敏单元测试：伪造凭证零明文泄漏验证。"""

from __future__ import annotations

from pathlib import Path, PosixPath

from web.redaction import redact_text


def test_bearer_token_redacted() -> None:
    """Bearer token 不得明文出现。"""
    text = "Authorization: Bearer abc123.def456-xyz"
    assert "abc123" not in redact_text(text)


def test_authorization_header_value_redacted() -> None:
    """Authorization 头值（非 Bearer 形式）同样掩盖。"""
    text = "headers={'Authorization': 'raw-secret-value'}"
    assert "raw-secret-value" not in redact_text(text)


def test_cookie_values_redacted() -> None:
    """Cookie 键值对的值被掩盖，键名保留。"""
    text = "Cookie: session=secret-session-id; theme=dark"
    result = redact_text(text)
    assert "secret-session-id" not in result
    assert "session=" in result


def test_sensitive_env_keys_redacted() -> None:
    """_TOKEN/_SECRET/_PASSWORD 等键值对的值被掩盖。"""
    text = (
        "AUTH_TOKEN=super-secret-auth\n"
        "ADMIN_SESSION_TOKEN=super-secret-admin\n"
        "API_SECRET=super-secret-api\n"
        "DB_PASSWORD=super-secret-db\n"
    )
    result = redact_text(text)
    for secret in (
        "super-secret-auth",
        "super-secret-admin",
        "super-secret-api",
        "super-secret-db",
    ):
        assert secret not in result


def test_json_style_sensitive_values_redacted() -> None:
    """JSON 形式的敏感键值同样掩盖。"""
    text = '{"refresh_token": "json-secret-value", "name": "case"}'
    result = redact_text(text)
    assert "json-secret-value" not in result
    assert "case" in result


def test_presigned_url_signature_redacted() -> None:
    """预签名 URL 的敏感查询参数值被掩盖，普通参数保留。"""
    text = "url=https://cdn.example.com/a.jpg?Signature=s3cr3t&width=100"
    result = redact_text(text)
    assert "s3cr3t" not in result
    assert "width=100" in result


def test_container_path_redacted() -> None:
    """traceback 中的容器内项目绝对路径被替换。"""
    root = PosixPath("/app")
    text = 'File "/app/test_cases/test_single_api.py", line 10'
    result = redact_text(text, project_root=root)
    assert "/app/test_cases" not in result
    assert "<project_root>" in result


def test_truncation_applied() -> None:
    """超长文本按上限截断并标注。"""
    result = redact_text("y" * 5000, max_length=100)
    assert len(result) <= 100 + len("...(truncated)")
    assert result.endswith("...(truncated)")


def test_plain_text_unchanged() -> None:
    """普通文本不被误伤。"""
    text = "3 passed, 1 failed in 2.34s"
    assert redact_text(text) == text
