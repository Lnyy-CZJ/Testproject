"""递归脱敏与可选 Allure 安全附件测试。"""

import copy
import json
from pathlib import Path
from typing import Any

from framework.reporting import allure_helper
from framework.security.redactor import REDACTED, Redactor


class _FakeAllure:
    """记录附件内容的最小 Allure 替身。"""

    class attachment_type:
        JSON = "json"

    def __init__(self) -> None:
        self.attachments: list[tuple[str, str, str]] = []

    def attach(self, body: str, name: str, attachment_type: str) -> None:
        self.attachments.append((body, name, attachment_type))


def test_recursive_redaction_does_not_modify_input() -> None:
    payload: dict[str, Any] = {
        "auth_token": "access-secret",
        "nested": [
            {
                "refresh_token": "refresh-secret",
                "upload_url": "https://cos.example/a.jpg?X-Amz-Signature=secret&safe=1",
                "user_id": "u-100",
                "full_name": "Example Person",
                "social_link": "https://social.example/profile",
                "image_path": "/private/faces/person.jpg",
                "purchase_token": "purchase-secret",
                "google_purchase_token": "google-purchase-secret",
            }
        ],
        "callback": "https://api.example/path?safe=1&signature=secret",
    }
    original = copy.deepcopy(payload)

    result = Redactor().redact(payload)

    assert payload == original
    nested = result["nested"][0]
    assert result["auth_token"] == REDACTED
    assert all(nested[key] == REDACTED for key in ("refresh_token", "upload_url", "user_id", "full_name", "social_link", "image_path"))
    assert nested["purchase_token"] == REDACTED
    assert nested["google_purchase_token"] == REDACTED
    assert "secret" not in result["callback"]
    assert "safe=1" in result["callback"]


def test_feedback_diagnostics_mask_message_and_contact() -> None:
    """真实写反馈的自由文本和联系方式不能进入诊断或报告。"""
    result = Redactor().redact(
        {
            "feedback_message": "private feedback details",
            "contact": "private-user@example.test",
            "client_request_id": "autotest-build-TC-001-safe",
        }
    )

    assert result == {
        "feedback_message": REDACTED,
        "contact": REDACTED,
        "client_request_id": "autotest-build-TC-001-safe",
    }


def test_media_identifiers_are_redacted_as_whole_values() -> None:
    """截图 ID 和媒体 ID 数组整体遮盖，不逐项保留数量或内容。"""
    result = Redactor.from_config().redact(
        {
            "screenshot_media_asset_id": "media-screen-secret",
            "media_asset_ids": ["media-one-secret", "media-two-secret"],
        }
    )

    assert result == {
        "screenshot_media_asset_id": REDACTED,
        "media_asset_ids": REDACTED,
    }


def test_allure_attachment_is_optional_redacted_and_bounded(monkeypatch: Any) -> None:
    fake = _FakeAllure()
    monkeypatch.setattr(allure_helper, "_allure", fake)

    attached = allure_helper.attach_safe_json(
        "gateway-response",
        {"auth_token": "secret", "large": "x" * 5000},
        max_bytes=300,
    )

    assert attached is True
    body = fake.attachments[0][0]
    assert len(body.encode("utf-8")) <= 300
    assert "secret" not in body
    assert json.loads(body)["truncated"] is True


def test_missing_allure_is_a_safe_noop(monkeypatch: Any) -> None:
    monkeypatch.setattr(allure_helper, "_allure", None)

    assert allure_helper.attach_safe_json("response", {"code": 0}) is False


def test_allure_attachment_never_exceeds_one_mib(monkeypatch: Any) -> None:
    fake = _FakeAllure()
    monkeypatch.setattr(allure_helper, "_allure", fake)

    allure_helper.attach_safe_json(
        "oversized-response",
        {"payload": "x" * (1024 * 1024 + 1000)},
        max_bytes=2 * 1024 * 1024,
    )

    assert len(fake.attachments[0][0].encode("utf-8")) <= 1024 * 1024


def test_redactor_config_merges_custom_keys_with_secure_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "redaction.yaml"
    config_path.write_text(
        "sensitive_keys: [custom_secret]\nsignature_query_keys: [custom_signature]\n",
        encoding="utf-8",
    )

    result = Redactor.from_config(config_path).redact(
        {"auth_token": "auth-secret", "custom_secret": "custom-value"}
    )

    assert result["auth_token"] == REDACTED
    assert result["custom_secret"] == REDACTED


def test_redactor_masks_cos_and_common_signature_parameters_in_any_url_field() -> None:
    """任意字段中的 COS/通用预签名 URL 都必须隐藏签名与临时凭据参数。"""
    secret_values = [
        "cos-signature-secret",
        "cos-ak-secret",
        "key-time-secret",
        "sign-time-secret",
        "url-list-secret",
        "header-list-secret",
        "generic-sig-secret",
        "generic-token-secret",
        "google-signature-secret",
        "aws-key-secret",
    ]
    query = "&".join(
        [
            "q-signature=cos-signature-secret",
            "q-ak=cos-ak-secret",
            "q-key-time=key-time-secret",
            "q-sign-time=sign-time-secret",
            "q-url-param-list=url-list-secret",
            "q-header-list=header-list-secret",
            "sig=generic-sig-secret",
            "token=generic-token-secret",
            "X-Goog-Signature=google-signature-secret",
            "AWSAccessKeyId=aws-key-secret",
            "safe=visible",
        ]
    )

    result = Redactor().redact(
        {"ordinary_field": f"https://cos.example.test/object?{query}"}
    )

    assert all(secret not in result["ordinary_field"] for secret in secret_values)
    assert "safe=visible" in result["ordinary_field"]
