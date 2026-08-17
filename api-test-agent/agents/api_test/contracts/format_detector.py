"""HTTP API 文档格式识别和资源限制预检。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from services.common.errors import ServiceError
from services.common.redaction import redact_text


class DocumentFormat(StrEnum):
    """当前产品允许路由的文档格式。"""

    OPENAPI_3 = "openapi_3"
    SWAGGER_2 = "swagger_2"
    UNSTRUCTURED_TEXT = "unstructured_text"
    UNSTRUCTURED_DATA = "unstructured_data"


@dataclass(frozen=True, slots=True)
class DocumentProfile:
    """预检阶段可安全返回和持久化的文档摘要。"""

    format: str
    specification_version: str
    size_bytes: int
    character_count: int
    sha256: str
    estimated_interface_count: int
    secret_risk_detected: bool
    redacted_preview: str

    def as_dict(self) -> dict[str, Any]:
        """转换为 JSON 产物结构。"""

        return {
            "format": self.format,
            "specification_version": self.specification_version,
            "size_bytes": self.size_bytes,
            "character_count": self.character_count,
            "sha256": self.sha256,
            "estimated_interface_count": self.estimated_interface_count,
            "secret_risk_detected": self.secret_risk_detected,
            "redacted_preview": self.redacted_preview,
        }


_PROTO = re.compile(r"(?m)^\s*syntax\s*=\s*[\"']proto[23][\"']|\brpc\s+\w+\s*\(")
_GRAPHQL = re.compile(r"(?m)^\s*(type\s+Query|schema\s*\{|query\s+\w+\s*\(|mutation\s+\w+)")
_WEBSOCKET = re.compile(r"(?i)(?:\b(?:wss?|websocket)://|\bwebsocket\b|\bupgrade\s*:\s*websocket\b)")
_SECRET = re.compile(r"(?i)(authorization|api[_-]?key|token|cookie|password|secret)\s*[:=]\s*\S+")


def _load_structured(text: str, extension: str) -> Any:
    """安全加载 JSON/YAML；语法错误转换为稳定业务错误。"""

    try:
        if extension == ".json":
            return json.loads(text)
        alias_count = sum(1 for token in yaml.scan(text) if isinstance(token, yaml.tokens.AliasToken))
        if alias_count > 100:
            raise ServiceError(422, "DOCUMENT_SYNTAX_INVALID", "YAML alias 数量超过安全限制")
        return yaml.safe_load(text)
    except ServiceError:
        raise
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        mark = getattr(exc, "problem_mark", None)
        position = f"（行 {mark.line + 1}，列 {mark.column + 1}）" if mark else ""
        raise ServiceError(422, "DOCUMENT_SYNTAX_INVALID", f"文档语法不正确{position}") from None


def _validate_shape(value: Any, *, max_depth: int = 64, max_nodes: int = 100_000) -> None:
    """限制解析树深度和节点数，避免结构化文档耗尽内存或递归栈。"""

    nodes = 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > max_depth or nodes > max_nodes:
            raise ServiceError(422, "DOCUMENT_SYNTAX_INVALID", "文档结构过深或节点数量超过限制")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _reject_unsupported(value: Any, text: str) -> None:
    """识别明确不在产品范围内的协议和集合格式。"""

    if isinstance(value, dict):
        info = value.get("info")
        schema_url = info.get("schema", "") if isinstance(info, dict) else ""
        if "schema.getpostman.com" in str(schema_url).lower() or (
            isinstance(info, dict) and isinstance(value.get("item"), list) and "_postman_id" in info
        ):
            raise ServiceError(422, "DOCUMENT_FORMAT_UNSUPPORTED", "当前不支持 Postman Collection 导入")
        if "asyncapi" in value:
            raise ServiceError(422, "DOCUMENT_FORMAT_UNSUPPORTED", "当前不支持 AsyncAPI 或 WebSocket 文档")
        if "__schema" in value or (isinstance(value.get("data"), dict) and "__schema" in value["data"]):
            raise ServiceError(422, "DOCUMENT_FORMAT_UNSUPPORTED", "当前不支持 GraphQL 文档")
    if _PROTO.search(text):
        raise ServiceError(422, "DOCUMENT_FORMAT_UNSUPPORTED", "当前不支持 gRPC/proto 文档")
    if _GRAPHQL.search(text):
        raise ServiceError(422, "DOCUMENT_FORMAT_UNSUPPORTED", "当前不支持 GraphQL 文档")
    if _WEBSOCKET.search(text):
        raise ServiceError(422, "DOCUMENT_FORMAT_UNSUPPORTED", "当前不支持 WebSocket 文档")


def detect_document_format(text: str, filename: str) -> tuple[DocumentFormat, Any | None, DocumentProfile]:
    """识别文档格式并生成不含 Secret 的预检摘要。

    参数说明:
        text: 已完成 UTF-8 和长度校验的文档正文。
        filename: 仅用于选择 JSON/YAML 解析器的原始文件名。
    返回值:
        文档格式、结构化对象（文本为 None）和预检摘要。
    异常说明:
        空文档、语法错误和明确不支持格式抛出带稳定错误码的 ServiceError。
    """

    if not text.strip():
        raise ServiceError(422, "DOCUMENT_EMPTY", "接口文档不能为空")
    extension = Path(filename).suffix.lower()
    value = _load_structured(text, extension) if extension in {".json", ".yaml", ".yml"} else None
    if value is not None:
        _validate_shape(value)
    _reject_unsupported(value, text)
    specification_version = ""
    estimated = 0
    if isinstance(value, dict) and str(value.get("openapi", "")).startswith("3.") and isinstance(value.get("paths"), dict):
        document_format = DocumentFormat.OPENAPI_3
        specification_version = str(value["openapi"])
        estimated = _operation_count(value["paths"])
    elif isinstance(value, dict) and str(value.get("swagger", "")) == "2.0" and isinstance(value.get("paths"), dict):
        document_format = DocumentFormat.SWAGGER_2
        specification_version = "2.0"
        estimated = _operation_count(value["paths"])
    elif extension in {".json", ".yaml", ".yml"}:
        document_format = DocumentFormat.UNSTRUCTURED_DATA
    else:
        document_format = DocumentFormat.UNSTRUCTURED_TEXT
    encoded = text.encode("utf-8")
    profile = DocumentProfile(
        format=document_format.value,
        specification_version=specification_version,
        size_bytes=len(encoded),
        character_count=len(text),
        sha256=hashlib.sha256(encoded).hexdigest(),
        estimated_interface_count=estimated,
        secret_risk_detected=bool(_SECRET.search(text)),
        redacted_preview=redact_text(text[:500]),
    )
    return document_format, value, profile


def _operation_count(paths: dict[str, Any]) -> int:
    """统计 OpenAPI paths 中标准 HTTP operation 数量。"""

    methods = {"get", "post", "put", "patch", "delete", "head", "options"}
    return sum(
        1 for path_item in paths.values() if isinstance(path_item, dict)
        for method in methods if isinstance(path_item.get(method), dict)
    )
