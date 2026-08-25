"""OpenAPI 3.x 与 Swagger 2.0 的确定性、无网络解析器。"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from agents.api_test.contracts.quality_gate import apply_quality_gate
from services.api_agent.models import (
    ApiContract,
    ContractParameter,
    FieldEvidence,
    RequestBodyDefinition,
    ResponseDefinition,
    ReviewIssue,
    SecurityRequirement,
    ServerDefinition,
    SourceTrace,
)


HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


def _pointer_escape(value: str) -> str:
    """按 RFC 6901 转义 JSON Pointer 节点。"""

    return value.replace("~", "~0").replace("/", "~1")


def _resolve_local_ref(root: dict[str, Any], value: Any, seen: set[str] | None = None) -> tuple[Any, str | None]:
    """只解析本地 `$ref`，远程、循环或失效引用返回错误说明且不联网。"""

    if not isinstance(value, dict) or "$ref" not in value:
        return deepcopy(value), None
    reference = str(value["$ref"])
    if not reference.startswith("#/"):
        return deepcopy(value), "远程 $ref 不受支持，解析器未发起网络请求"
    active = set(seen or set())
    if reference in active:
        return deepcopy(value), "检测到循环 $ref"
    active.add(reference)
    current: Any = root
    try:
        for part in reference[2:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            current = current[key]
    except (KeyError, TypeError):
        return deepcopy(value), "本地 $ref 指向不存在的节点"
    resolved, error = _resolve_local_ref(root, current, active)
    if isinstance(resolved, dict):
        resolved = {**resolved, **{key: deepcopy(item) for key, item in value.items() if key != "$ref"}}
    return resolved, error


def _evidence(field_path: str, value: Any, pointer: str) -> FieldEvidence:
    """为确定性结构节点生成显式 Evidence。"""

    return FieldEvidence(
        field_path=field_path, value=value, source_type="openapi_node",
        source_pointer=pointer, evidence_type="explicit", confidence=1.0,
    )


def _schema(value: Any, root: dict[str, Any], unresolved: list[ReviewIssue], field_path: str) -> dict[str, Any]:
    """展开单层/递归本地 Schema 引用，并记录未支持引用。"""

    resolved, error = _resolve_local_ref(root, value or {})
    if error:
        unresolved.append(ReviewIssue(
            code="REF_UNRESOLVED", field_path=field_path, message=error, severity="warning",
            source_pointer=str(value.get("$ref", "")) if isinstance(value, dict) else "",
        ))
    return resolved if isinstance(resolved, dict) else {}


def parse_openapi_document(document: dict[str, Any], *, source_id: str = "document", minimum_score: float = 0.90) -> list[ApiContract]:
    """把 OpenAPI/Swagger 文档规范化为 ApiContract 列表。

    参数说明:
        document: 已经安全加载且通过格式识别的根对象。
        source_id: 任务内文档来源 ID。
    返回值:
        通过字段 Evidence 和质量门禁处理后的契约列表。
    异常说明:
        本函数不访问网络；未支持的引用进入 unresolved。
    """

    swagger = str(document.get("swagger", "")) == "2.0"
    contracts: list[ApiContract] = []
    for raw_path, path_item in (document.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            pointer = f"/paths/{_pointer_escape(str(raw_path))}/{method}"
            unresolved: list[ReviewIssue] = []
            evidences = [
                _evidence("method", method.upper(), pointer),
                _evidence("path", str(raw_path), f"/paths/{_pointer_escape(str(raw_path))}"),
            ]
            raw_sla = operation.get("x-sla-ms", operation.get("x-response-time-ms"))
            sla_ms = int(raw_sla) if isinstance(raw_sla, (int, float)) and raw_sla > 0 else None
            if sla_ms:
                sla_key = "x-sla-ms" if "x-sla-ms" in operation else "x-response-time-ms"
                evidences.append(_evidence("sla_ms", sla_ms, f"{pointer}/{sla_key}"))
            raw_parameters = [
                *(path_item.get("parameters") or []), *(operation.get("parameters") or []),
            ]
            parameters: list[ContractParameter] = []
            request_body: RequestBodyDefinition | None = None
            for raw_index, raw_parameter in enumerate(raw_parameters):
                parameter, error = _resolve_local_ref(document, raw_parameter)
                if error:
                    unresolved.append(ReviewIssue(
                        code="REF_UNRESOLVED", field_path="parameters", message=error,
                        source_pointer=str(raw_parameter.get("$ref", "")) if isinstance(raw_parameter, dict) else "",
                    ))
                if not isinstance(parameter, dict):
                    continue
                if swagger and parameter.get("in") == "body":
                    request_body = RequestBodyDefinition(
                        required=bool(parameter.get("required")),
                        content={"application/json": {"schema": _schema(
                            parameter.get("schema"), document, unresolved, "request_body",
                        )}},
                    )
                    continue
                location = str(parameter.get("in", "query"))
                if location not in {"header", "path", "query", "cookie"}:
                    unresolved.append(ReviewIssue(
                        code="PARAMETER_LOCATION_UNSUPPORTED", field_path="parameters",
                        message=f"参数位置 {location} 暂不支持", severity="warning",
                    ))
                    continue
                index = len(parameters)
                schema_value = parameter.get("schema") or {
                    key: parameter[key] for key in ("type", "format", "enum", "minimum", "maximum", "minLength", "maxLength")
                    if key in parameter
                }
                parameters.append(ContractParameter(
                    name=str(parameter.get("name", f"parameter_{raw_index + 1}")),
                    location=location,
                    required=True if location == "path" else bool(parameter.get("required")),
                    description=str(parameter.get("description", "")),
                    schema=_schema(schema_value, document, unresolved, f"parameters[{index}].schema"),
                    example=parameter.get("example"),
                ))
                base_pointer = f"{pointer}/parameters/{raw_index}"
                evidences.extend([
                    _evidence(f"parameters[{index}].name", parameters[-1].name, f"{base_pointer}/name"),
                    _evidence(f"parameters[{index}].location", location, f"{base_pointer}/in"),
                    _evidence(f"parameters[{index}].required", parameters[-1].required, f"{base_pointer}/required"),
                ])
            if not swagger and isinstance(operation.get("requestBody"), dict):
                body, error = _resolve_local_ref(document, operation["requestBody"])
                if error:
                    unresolved.append(ReviewIssue(code="REF_UNRESOLVED", field_path="request_body", message=error))
                if isinstance(body, dict):
                    content = {}
                    for media, media_value in (body.get("content") or {}).items():
                        media_value = media_value if isinstance(media_value, dict) else {}
                        content[str(media)] = {
                            **media_value,
                            "schema": _schema(media_value.get("schema"), document, unresolved, "request_body"),
                        }
                    request_body = RequestBodyDefinition(required=bool(body.get("required")), content=content)
            responses: list[ResponseDefinition] = []
            for response_index, (status_code, raw_response) in enumerate((operation.get("responses") or {}).items()):
                response, error = _resolve_local_ref(document, raw_response)
                if error:
                    unresolved.append(ReviewIssue(code="REF_UNRESOLVED", field_path="responses", message=error))
                response = response if isinstance(response, dict) else {}
                content = response.get("content") or {}
                if swagger and response.get("schema") is not None:
                    content = {"application/json": {"schema": _schema(
                        response.get("schema"), document, unresolved, f"responses[{response_index}]",
                    )}}
                responses.append(ResponseDefinition(
                    status_code=str(status_code), description=str(response.get("description", "")), content=content,
                ))
                evidences.append(_evidence(
                    f"responses[{response_index}].status_code", str(status_code),
                    f"{pointer}/responses/{_pointer_escape(str(status_code))}",
                ))
            security = []
            for item in operation.get("security", document.get("security", [])) or []:
                if isinstance(item, dict):
                    security.extend(SecurityRequirement(scheme=str(name), scopes=list(scopes or [])) for name, scopes in item.items())
            servers = _servers(document, operation, swagger)
            contract_id = "contract_" + hashlib.sha256(
                f"{method.upper()} {raw_path}".encode("utf-8")
            ).hexdigest()[:20]
            tags = [str(item) for item in operation.get("tags", [])] if isinstance(operation.get("tags"), list) else []
            contract = ApiContract(
                contract_id=contract_id,
                name=str(operation.get("operationId") or operation.get("summary") or f"{method.upper()} {raw_path}"),
                summary=str(operation.get("description") or operation.get("summary") or ""),
                module=tags[0] if tags else "",
                tags=tags,
                method=method,
                path=str(raw_path),
                sla_ms=sla_ms,
                servers=servers,
                parameters=parameters,
                request_body=request_body,
                responses=responses,
                security=security,
                source_trace=SourceTrace(source_id=source_id, section_id=pointer, quote=""),
                field_evidence=evidences,
                unresolved=unresolved,
            )
            contracts.append(apply_quality_gate(contract, minimum_score=minimum_score))
    return contracts


def _servers(document: dict[str, Any], operation: dict[str, Any], swagger: bool) -> list[ServerDefinition]:
    """提取 Server 元数据，但不解析为真实执行目标。"""

    if not swagger:
        values = operation.get("servers") or document.get("servers") or []
        return [
            ServerDefinition(url=str(item.get("url", "")), description=str(item.get("description", "")))
            for item in values if isinstance(item, dict) and item.get("url")
        ]
    host = str(document.get("host", ""))
    base_path = str(document.get("basePath", ""))
    schemes = document.get("schemes") or ["https"]
    if not host:
        return []
    return [ServerDefinition(url=f"{scheme}://{host}{base_path}") for scheme in schemes]
