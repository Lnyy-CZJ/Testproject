"""日志和本地产物共用的递归脱敏函数。"""

from urllib.parse import urlsplit


SECRET_KEYS = frozenset(
    {
        "authorization",
        "auth_token",
        "access_token",
        "refresh_token",
        "api_key",
        "upload_url",
        "required_headers",
        "x-cos-security-token",
        "signature",
        "credential",
        "user_id",
        "device_id",
    }
)

# 这些字段可能包含用户对话或模型生成正文。协议验证在内存中完成，写入排障产物时仅保留
# 结构和非正文元数据，避免本地文件成为第二份隐私数据源。
CONTENT_KEYS = frozenset(
    {
        "text",
        "background",
        "transcript",
        "messages",
        "whats_happening",
        "top_pick",
        "alternatives",
        "candidate_reply",
        "reply_text",
        "content",
        "result",
        "message",
        "error_message",
        "detail",
        "details",
    }
)


def _looks_like_signed_url(value: str) -> bool:
    """任何带查询参数的 HTTP(S) URL 都按预签名 URL 处理。"""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.query)


def redact_mapping(value: object) -> object:
    """返回深拷贝的安全视图，不修改调用方对象。

    Key 规则负责已知凭据和正文，URL 规则作为第二道防线，避免签名参数藏在普通 ``url``
    字段中。tuple 转为 list，确保结果能够稳定 JSON 序列化。
    """

    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in SECRET_KEYS or normalized in CONTENT_KEYS:
                redacted[key] = "***"
            else:
                redacted[key] = redact_mapping(child)
        return redacted
    if isinstance(value, list):
        return [redact_mapping(child) for child in value]
    if isinstance(value, tuple):
        return [redact_mapping(child) for child in value]
    if isinstance(value, str) and _looks_like_signed_url(value):
        return "***"
    return value
