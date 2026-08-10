"""壳服务展示内容的二次脱敏。

功能说明:
    框架日志已由 http_client 完成一次脱敏，可直接展示；但 ``console.log``、
    pytest 错误摘要、traceback 等壳服务自产内容可能携带凭证或容器内部
    路径，必须经过本模块统一脱敏与截断后才允许进入接口响应或页面。
"""

from __future__ import annotations

import re
from pathlib import Path

# 展示内容最大长度，超出部分截断，防止大段 traceback 进入响应。
DEFAULT_MAX_LENGTH = 2000

# 失败摘要中单条消息的最大长度。
FAILED_MESSAGE_LIMIT = 500

# Authorization 头 / Bearer token；兼容 dict/JSON repr 中键值被引号包裹的形式。
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)\b(authorization\s*[\"']?\s*[:=]\s*[\"']?(?:bearer\s+)?)"
    r"[A-Za-z0-9._\-+/=%]+"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-+/=%]+")

# Cookie / Set-Cookie 头：逐个掩盖键值对中的值。
_COOKIE_VALUE_PATTERN = re.compile(
    r"(?i)((?:set-)?cookie\s*[:=]\s*)([^\r\n]+)"
)
_COOKIE_PAIR_PATTERN = re.compile(r"([^=;\s]+)=([^;]*)")

# 敏感键值：键名含 TOKEN/SECRET/PASSWORD/PASSWD/APIKEY 等，
# 同时覆盖 JSON 形式（"key": "value"）与 .env 形式（KEY=value）；
# 分隔符两侧的引号（dict/JSON repr）并入分隔组，使值本身无需匹配引号。
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:token|secret|password|passwd|api_?key)[A-Za-z0-9_]*)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s\"',;}\]]+)"
)

# 预签名 URL 等带敏感查询参数的地址：按参数名判断并掩盖参数值。
_URL_QUERY_PATTERN = re.compile(r"(?i)(https?://[^\s'\"<>]*?)\?([^\s'\"<>]+)")
_SENSITIVE_QUERY_KEYS = re.compile(
    r"(?i)^(signature|x-amz-signature|x-goog-signature|sig|token|access_?token"
    r"|api_?key|key|secret|password|x-amz-security-token|se|sp|spr|expires)$"
)

_MASK = "[REDACTED]"

# 截断标注后缀；计入总长度，保证输出不超过 max_length。
_TRUNCATION_SUFFIX = "...(truncated)"


def _redact_cookie_header(match: re.Match[str]) -> str:
    """掩盖 Cookie 头中每个键值对的值，保留键名便于排查。"""
    pairs = _COOKIE_PAIR_PATTERN.sub(
        lambda pair: f"{pair.group(1)}={_MASK}", match.group(2)
    )
    return f"{match.group(1)}{pairs}"


def _redact_url_query(match: re.Match[str]) -> str:
    """掩盖 URL 查询中敏感参数的值，非敏感参数原样保留。"""
    query = match.group(2)
    kept: list[str] = []
    for part in query.split("&"):
        key, sep, _value = part.partition("=")
        if sep and _SENSITIVE_QUERY_KEYS.match(key):
            kept.append(f"{key}={_MASK}")
        else:
            kept.append(part)
    return f"{match.group(1)}?{'&'.join(kept)}"


def redact_text(
    text: str,
    project_root: Path | None = None,
    max_length: int | None = DEFAULT_MAX_LENGTH,
) -> str:
    """对展示文本执行统一的二次脱敏与截断。

    功能说明:
        依次掩盖 Authorization/Bearer、Cookie、敏感键值对、预签名 URL
        敏感查询参数；如提供项目根路径，同时把容器内绝对路径替换为占位符，
        避免泄漏容器内部目录结构。最后按最大长度截断。

    参数说明:
        text: 待脱敏文本；None 或空串原样返回空串。
        project_root: 项目根目录；出现其绝对路径时替换为 ``<project_root>``。
        max_length: 截断上限；None 表示不截断。

    返回值:
        脱敏后的文本，长度不超过 max_length（超出追加 ``...(truncated)``）。
    """
    if not text:
        return ""

    result = _AUTHORIZATION_PATTERN.sub(rf"\1{_MASK}", text)
    result = _BEARER_PATTERN.sub(rf"\1{_MASK}", result)
    result = _COOKIE_VALUE_PATTERN.sub(_redact_cookie_header, result)
    result = _SENSITIVE_KEY_PATTERN.sub(rf"\1\2{_MASK}", result)
    result = _URL_QUERY_PATTERN.sub(_redact_url_query, result)

    if project_root is not None:
        root_text = str(Path(project_root).resolve())
        if root_text and root_text != "/":
            result = result.replace(root_text, "<project_root>")

    if max_length is not None and len(result) > max_length:
        keep = max(max_length - len(_TRUNCATION_SUFFIX), 0)
        result = result[:keep] + _TRUNCATION_SUFFIX
    return result
