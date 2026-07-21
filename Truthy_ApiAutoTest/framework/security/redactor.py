"""请求、响应和诊断数据的递归脱敏。"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml


REDACTED = "***REDACTED***"

_DEFAULT_SENSITIVE_KEYS = {
    "auth_token",
    "refresh_token",
    "device_id",
    "upload_url",
    "user_id",
    "name",
    "full_name",
    "display_name",
    "social_link",
    "social_links",
    "social_url",
    "avatar_url",
    "image_path",
    "image_url",
    "photo_path",
    "photo_url",
    "purchase_token",
    "google_purchase_token",
    "apple_purchase_token",
    "app_store_receipt",
    "purchase_receipt",
    "receipt_data",
    "signed_transaction_info",
    "feedback_message",
    "contact",
    "screenshot_media_asset_id",
    "media_asset_ids",
}
_DEFAULT_SIGNATURE_QUERY_KEYS = {
    "signature",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-cos-security-token",
    "security-token",
    "q-signature",
    "q-ak",
    "q-key-time",
    "q-sign-time",
    "q-url-param-list",
    "q-header-list",
    "sig",
    "token",
    "access-key",
    "access_key",
    "credential",
    "policy",
    "key-pair-id",
    "expires",
    "awsaccesskeyid",
    "googleaccessid",
    "x-goog-signature",
    "x-goog-credential",
    "x-goog-security-token",
    "x-ms-signature",
}


class Redactor:
    """对嵌套字典、列表、元组及带签名 URL 生成安全副本。

    功能说明:
        对嵌套容器与任意字段中的预签名 URL 生成安全副本。
    参数说明:
        sensitive_keys: 整个值需要掩码的字段名；默认覆盖凭据、用户标识、姓名、社媒和图片字段。
        signature_query_keys: URL 中需要单独掩码的签名参数名。
    返回值:
        ``redact`` 返回结构独立的脱敏对象，不修改输入。
    异常说明:
        本类不主动吞掉输入对象自定义拷贝产生的异常。
    """

    def __init__(
        self,
        *,
        sensitive_keys: Iterable[str] | None = None,
        signature_query_keys: Iterable[str] | None = None,
    ) -> None:
        self.sensitive_keys = set(_DEFAULT_SENSITIVE_KEYS)
        self.sensitive_keys.update(key.lower() for key in (sensitive_keys or ()))
        self.signature_query_keys = set(_DEFAULT_SIGNATURE_QUERY_KEYS)
        self.signature_query_keys.update(
            key.lower() for key in (signature_query_keys or ())
        )

    @classmethod
    def from_config(cls, path: str | Path | None = None) -> "Redactor":
        """加载脱敏 YAML 并与内置安全字段合并。

        功能说明:
            读取可选 YAML，并与内置敏感字段和签名参数集合合并。
        参数说明:
            path: 配置文件路径；默认读取项目 ``config/log_redaction.yaml``。
        返回值:
            同时包含内置安全字段和配置扩展字段的脱敏器。
        异常说明:
            配置根结构或字段类型错误时抛出 ``ValueError``；文件读取和 YAML 解析异常原样抛出。
        """
        config_path = (
            Path(path)
            if path is not None
            else Path(__file__).resolve().parents[2] / "config/log_redaction.yaml"
        )
        if not config_path.exists():
            return cls()
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"脱敏配置必须是对象: {config_path}")
        sensitive_keys = loaded.get("sensitive_keys", [])
        signature_query_keys = loaded.get("signature_query_keys", [])
        if not isinstance(sensitive_keys, list) or not isinstance(signature_query_keys, list):
            raise ValueError(f"脱敏配置字段必须是列表: {config_path}")
        return cls(
            sensitive_keys=sensitive_keys,
            signature_query_keys=signature_query_keys,
        )

    def redact(self, value: Any) -> Any:
        """递归生成脱敏副本。

        功能说明:
            递归脱敏容器、敏感键及 URL 签名查询参数。
        参数说明:
            value: 任意由字典、列表、元组和基础标量组成的诊断数据。
        返回值:
            保持原容器形态的脱敏副本。
        异常说明:
            不支持的自定义对象会通过 ``deepcopy`` 复制，其复制异常原样抛出。
        """
        return self._redact_value(value)

    def _redact_value(self, value: Any) -> Any:
        """根据容器类型递归处理值，并对普通字符串清理签名查询参数。"""
        if isinstance(value, dict):
            return {
                copy.deepcopy(key): (
                    REDACTED
                    if str(key).lower() in self.sensitive_keys
                    else self._redact_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        if isinstance(value, str):
            return self._redact_signed_url(value)
        return copy.deepcopy(value)

    def _redact_signed_url(self, value: str) -> str:
        """仅掩码 URL 中的签名查询参数，同时保留非敏感参数用于排查。"""
        try:
            parsed = urlsplit(value)
        except ValueError:
            return value
        if not parsed.scheme or not parsed.netloc or not parsed.query:
            return value
        query = [
            (key, REDACTED if key.lower() in self.signature_query_keys else item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
