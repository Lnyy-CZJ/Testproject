"""将阶段一解析结果收敛为带 Evidence 的 V3 契约。

Adapter 是纯转换层：它只接收内存中的解析结果和原始文档文本，不读取任务目录、
不访问数据库，也不调用网络。这样 Runner 可以在人工 Review 前统一保存候选版本。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from agents.api_test.contracts.quality_gate import apply_quality_gate
from services.api_agent.models import (
    ApiContract,
    AuthRequirement,
    ContractParameter,
    FieldEvidence,
    RequestBodyDefinition,
    ResponseDefinition,
    ReviewIssue,
    SourceTrace,
)


_BODY_SIGNAL = re.compile(r"(?i)(?:request\s*body|\bjson\b|\bform\b|--data|-d\b|请求体|字段表)")
_AUTH_SIGNAL = re.compile(
    r"(?i)(?:authorization|bearer|token|cookie|session|csrf|api[_ -]?key|鉴权|认证|会话)"
)
_EXPLICIT_NO_AUTH = re.compile(r"(?i)(?:无需(?:鉴权|认证|会话)|no\s+(?:auth|authentication))")


class V2ContractAdapter:
    """把旧 AI 候选和确定性 Contract 合并为 V3 语义的 ``ApiContract``。

    确定性 Contract 只会补充 V3 元数据，绝不会让模型候选覆盖 method、path 或
    OpenAPI 解析得到的请求/响应事实。非结构化文档则由旧候选提供结构，所有关键值
    都绑定到同一文档片段的 Evidence，随后才进入统一质量门禁。
    """

    def adapt_legacy_candidates(
        self,
        candidates: Any,
        *,
        document_text: str,
        source_id: str = "document",
    ) -> list[ApiContract]:
        """将旧 ``AIAPIDocumentParser`` 风格候选映射为候选契约。"""

        raw_items = candidates if isinstance(candidates, list) else [candidates]
        contracts: list[ApiContract] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                continue
            contracts.append(self._legacy_contract(raw, index, document_text, source_id))
        return contracts

    def enrich_deterministic_contracts(
        self,
        contracts: Iterable[ApiContract],
        *,
        document_text: str,
        document: dict[str, Any],
        source_id: str = "document",
    ) -> list[ApiContract]:
        """补足确定性解析结果的 V3 鉴权结论与门禁信息，保留解析事实不变。"""

        result: list[ApiContract] = []
        for contract in contracts:
            contract.artifact_schema_version = 3
            contract.body_signal_detected = bool(contract.request_body) or bool(_BODY_SIGNAL.search(document_text))
            operation = self._operation(document, contract)
            explicit_no_auth = operation.get("security") == [] or document.get("security") == []
            if explicit_no_auth:
                contract.auth_conclusion = "none"
                contract.auth_signal_detected = False
            elif contract.security:
                contract.auth_conclusion = "required"
                contract.auth_signal_detected = True
                contract.auth_requirements = self._requirements_from_security(contract)
            else:
                contract.auth_signal_detected = bool(_AUTH_SIGNAL.search(document_text))
                contract.auth_conclusion = "unresolved"

            self._ensure_core_evidence(contract, document_text, source_id, source_type="openapi_node")
            self._apply_completeness_blockers(contract)
            result.append(apply_quality_gate(contract))
        return result

    def _legacy_contract(
        self,
        raw: dict[str, Any],
        index: int,
        document_text: str,
        source_id: str,
    ) -> ApiContract:
        source_text = str(raw.get("_source_text") or document_text)
        method = str(raw.get("method", "GET")).upper()
        method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "GET"
        path = str(raw.get("path", "/unresolved"))
        if not path.startswith("/") or "://" in path:
            path = "/unresolved"
        parameters = self._parameters(raw.get("parameters"))
        request_body = self._request_body(raw.get("requestBody"))
        responses = self._responses(raw.get("responses"))
        digest = hashlib.sha256(f"{method}|{path}|{index}".encode()).hexdigest()[:20]
        contract = ApiContract(
            contract_id=f"contract_{digest}",
            artifact_schema_version=3,
            name=str(raw.get("name") or raw.get("summary") or f"{method} {path}"),
            summary=str(raw.get("summary", "")),
            method=method,
            path=path,
            parameters=parameters,
            request_body=request_body,
            responses=responses,
            source_trace=SourceTrace(
                source_id=source_id,
                section_id=str(raw.get("_source_section_id") or f"candidate-{index}"),
                quote=source_text[:2000],
            ),
            body_signal_detected=bool(_BODY_SIGNAL.search(source_text)),
            auth_signal_detected=bool(_AUTH_SIGNAL.search(source_text)),
        )
        contract.auth_requirements = self._requirements_from_parameters(parameters)
        if bool(raw.get("_explicit_no_auth")) or _EXPLICIT_NO_AUTH.search(source_text):
            contract.auth_conclusion = "none"
        elif contract.auth_requirements:
            contract.auth_conclusion = "required"
        elif contract.auth_signal_detected:
            contract.auth_conclusion = "unresolved"
        else:
            contract.auth_conclusion = "unresolved"

        self._ensure_core_evidence(contract, source_text, source_id, source_type="source_quote")
        self._apply_completeness_blockers(contract)
        return apply_quality_gate(contract)

    @staticmethod
    def _parameters(raw_groups: Any) -> list[ContractParameter]:
        groups = raw_groups if isinstance(raw_groups, dict) else {}
        parameters: list[ContractParameter] = []
        for location in ("header", "path", "query", "cookie"):
            for item in groups.get(location, []) if isinstance(groups.get(location), list) else []:
                if not isinstance(item, dict):
                    continue
                parameters.append(ContractParameter(
                    name=str(item.get("name", "")),
                    location=location,
                    required=bool(item.get("required", False)),
                    description=str(item.get("description", "")),
                    schema=item.get("type") if isinstance(item.get("type"), dict) else {},
                    example=item.get("example"),
                    param_role=str(item.get("param_role") or "required"),
                    fixed_value=item.get("fixed_value"),
                    default_value=item.get("default_value"),
                    allow_omit=bool(item.get("allow_omit", False)),
                    baseline_value=item.get("baseline_value"),
                    data_category=str(item.get("data_category") or "baseline"),
                    dependencies=[str(value) for value in item.get("dependencies", [])]
                    if isinstance(item.get("dependencies"), list) else [],
                    mutex_group=str(item["mutex_group"]) if item.get("mutex_group") else None,
                    test_strategy=[str(value) for value in item.get("test_strategy", [])]
                    if isinstance(item.get("test_strategy"), list) else [],
                ))
        return parameters

    @staticmethod
    def _request_body(raw: Any) -> RequestBodyDefinition | None:
        if not isinstance(raw, dict):
            return None
        fields = raw.get("body") if isinstance(raw.get("body"), list) else raw.get("fields")
        if not isinstance(fields, list):
            return None
        def property_schema(item: dict[str, Any]) -> dict[str, Any]:
            """递归保留旧解析器的对象/数组字段和参数角色，供控制变量法生成请求。"""

            type_value = item.get("type")
            schema = dict(type_value) if isinstance(type_value, dict) else {"type": str(type_value or "string")}
            role = str(item.get("param_role") or "required")
            schema["x-param-role"] = role
            if item.get("fixed_value") is not None:
                schema["const"] = item["fixed_value"]
            if item.get("default_value") is not None:
                schema["default"] = item["default_value"]
            if item.get("baseline_value") is not None:
                schema["x-baseline-value"] = item["baseline_value"]
            schema["x-allow-omit"] = bool(item.get("allow_omit", role == "optional"))
            nested = item.get("nested_fields")
            array_items = item.get("array_item_fields")
            if isinstance(nested, list) and nested:
                children = [child for child in nested if isinstance(child, dict) and child.get("name")]
                schema.update({
                    "type": "object",
                    "properties": {str(child["name"]): property_schema(child) for child in children},
                })
                child_required = [str(child["name"]) for child in children if bool(child.get("required"))]
                if child_required:
                    schema["required"] = child_required
            elif isinstance(array_items, list):
                children = [child for child in array_items if isinstance(child, dict) and child.get("name")]
                item_schema: dict[str, Any] = {
                    "type": "object",
                    "properties": {str(child["name"]): property_schema(child) for child in children},
                }
                item_required = [str(child["name"]) for child in children if bool(child.get("required"))]
                if item_required:
                    item_schema["required"] = item_required
                schema.update({"type": "array", "items": item_schema})
            return schema

        properties: dict[str, Any] = {}
        required: list[str] = []
        for item in fields:
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                continue
            name = str(item["name"]).strip()
            properties[name] = property_schema(item)
            if bool(item.get("required")):
                required.append(name)
        return RequestBodyDefinition(
            required=bool(required),
            content={
                "media_types": [str(raw.get("content_type") or raw.get("media_type") or "application/json")],
                "schema": {"type": "object", "properties": properties, "required": required},
            },
        )

    @staticmethod
    def _responses(raw: Any) -> list[ResponseDefinition]:
        items = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        return [
            ResponseDefinition(
                status_code=str(item.get("http_code") or item.get("status_code") or "default"),
                description=str(item.get("description", "")),
                content=item.get("content") if isinstance(item.get("content"), dict) else {},
            )
            for item in items
            if isinstance(item, dict)
        ]

    @staticmethod
    def _requirements_from_parameters(parameters: Iterable[ContractParameter]) -> list[AuthRequirement]:
        requirements: list[AuthRequirement] = []
        for parameter in parameters:
            name = parameter.name.lower()
            if parameter.location == "cookie":
                scheme_type, location = "session", "cookie"
            elif "csrf" in name:
                scheme_type, location = "csrf", "header"
            elif "authorization" in name or "bearer" in parameter.description.lower():
                scheme_type, location = "bearer", parameter.location
            elif "token" in name or "api" in name and "key" in name:
                scheme_type, location = "api_key", parameter.location
            else:
                continue
            requirements.append(AuthRequirement(
                scheme_type=scheme_type, credential_location=location,
                field_name=parameter.name, evidence_refs=[f"parameters.{parameter.name}"],
            ))
        return requirements

    @staticmethod
    def _requirements_from_security(contract: ApiContract) -> list[AuthRequirement]:
        return [
            AuthRequirement(
                scheme_type="custom", credential_location="runtime_profile", field_name=item.scheme,
                scopes=item.scopes, evidence_refs=["security"],
            )
            for item in contract.security
        ]

    @staticmethod
    def _operation(document: dict[str, Any], contract: ApiContract) -> dict[str, Any]:
        paths = document.get("paths") if isinstance(document.get("paths"), dict) else {}
        path_item = paths.get(contract.path) if isinstance(paths.get(contract.path), dict) else {}
        operation = path_item.get(contract.method.lower()) if isinstance(path_item, dict) else {}
        return operation if isinstance(operation, dict) else {}

    @staticmethod
    def _ensure_core_evidence(
        contract: ApiContract,
        document_text: str,
        source_id: str,
        *,
        source_type: str,
    ) -> None:
        """为质量门禁生成字段级 Evidence，非结构化候选必须逐值匹配原文。"""

        paths = {item.field_path for item in contract.field_evidence}
        lines = document_text.splitlines()

        def add(field_path: str, value: Any, *, parameter_name: str = "") -> None:
            if field_path not in paths:
                explicit = source_type == "openapi_node"
                matching_line = 1
                if not explicit:
                    text = str(value).strip()
                    for line_index, line in enumerate(lines, 1):
                        lower = line.lower()
                        name_present = not parameter_name or parameter_name.lower() in lower
                        if not name_present:
                            continue
                        if field_path.endswith(".location"):
                            markers = {
                                "header": ("header", "请求头", "-h", "authorization", "csrf"),
                                "cookie": ("cookie", "会话"),
                                "query": ("query", "查询参数"),
                                "path": ("path", "路径参数"),
                            }.get(text.lower(), (text.lower(),))
                            matched = any(marker in lower for marker in markers)
                        elif field_path.endswith(".required"):
                            required_markers = ("必填", "required=true", "required: true")
                            optional_markers = ("可选", "optional", "required=false", "required: false")
                            matched = any(marker in lower for marker in (required_markers if bool(value) else optional_markers))
                        else:
                            matched = bool(text) and text.lower() in lower
                        if matched:
                            explicit, matching_line = True, line_index
                            break
                evidence_quote = lines[matching_line - 1] if lines else document_text[:1000]
                contract.field_evidence.append(FieldEvidence(
                    field_path=field_path, value=value, source_type=source_type,
                    source_pointer=f"{source_id}:L{matching_line}", quote=evidence_quote[:1000],
                    evidence_type="explicit" if explicit else "inferred",
                    confidence=1.0 if explicit else 0.0,
                    start_line=matching_line, end_line=matching_line,
                ))
                if not explicit and not any(
                    issue.code == "UNGROUNDED_FIELD" and issue.field_path == field_path
                    for issue in contract.unresolved
                ):
                    contract.unresolved.append(ReviewIssue(
                        code="UNGROUNDED_FIELD", field_path=field_path,
                        message="该字段缺少直接原文依据，未作为可确认事实",
                        severity="blocker", source_pointer=source_id,
                    ))
                paths.add(field_path)

        add("method", contract.method)
        add("path", contract.path)
        for index, parameter in enumerate(contract.parameters):
            add(f"parameters[{index}].name", parameter.name, parameter_name=parameter.name)
            add(f"parameters[{index}].location", parameter.location, parameter_name=parameter.name)
            add(f"parameters[{index}].required", parameter.required, parameter_name=parameter.name)
        for index, response in enumerate(contract.responses):
            add(f"responses[{index}].status_code", response.status_code)

    @staticmethod
    def _apply_completeness_blockers(contract: ApiContract) -> None:
        existing = {issue.code for issue in contract.unresolved}
        def block(code: str, field_path: str, message: str) -> None:
            if code not in existing:
                contract.unresolved.append(ReviewIssue(
                    code=code, field_path=field_path, message=message, severity="blocker",
                ))
                existing.add(code)

        if contract.body_signal_detected and contract.request_body is None:
            block("CONTRACT_REQUEST_BODY_MISSING", "request_body", "原文存在请求体信号，但未得到结构化请求体")
        if contract.auth_signal_detected and contract.auth_conclusion == "unresolved":
            block("CONTRACT_AUTH_CONCLUSION_MISSING", "auth_conclusion", "原文存在鉴权信号，但鉴权结论未确定")
        if contract.auth_conclusion == "required" and not contract.auth_requirements:
            block("CONTRACT_AUTH_REQUIREMENT_INCOMPLETE", "auth_requirements", "鉴权必需但方案、位置或字段不完整")
