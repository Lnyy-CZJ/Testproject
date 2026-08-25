"""文档识别、OpenAPI 确定性解析和非结构化 Grounding 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agents.api_test.contracts.format_detector import DocumentFormat, detect_document_format
from agents.api_test.contracts.openapi_parser import parse_openapi_document
from agents.api_test.contracts.unstructured_parser import parse_unstructured_document
from agents.api_test.parsers.ai_parser_api_document import ParametersModel
from services.common.errors import ServiceError


FIXTURES = Path(__file__).parent / "fixtures"


def test_legacy_parser_schema_accepts_cookie_parameters() -> None:
    """会话 Cookie 必须能从旧 AI 解析器进入核心契约，而不是被 Parser Schema 丢弃。"""

    parsed = ParametersModel.model_validate({
        "header": [], "path": [], "query": [],
        "cookie": [{
            "name": "SESSION", "description": "登录会话", "required": True,
            "type": {"type": "string"},
        }],
    })
    assert parsed.cookie[0].name == "SESSION"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("openapi3.yaml", DocumentFormat.OPENAPI_3), ("swagger2.json", DocumentFormat.SWAGGER_2)],
)
def test_detect_and_parse_structured_documents(name: str, expected: DocumentFormat) -> None:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    detected, document, profile = detect_document_format(text, name)
    assert detected == expected
    assert profile.estimated_interface_count == 1
    contracts = parse_openapi_document(document)
    assert len(contracts) == 1
    assert contracts[0].method in {"GET", "POST"}
    assert contracts[0].path in {"/users", "/login/{tenant_id}"}
    assert contracts[0].status == "confirmed_candidate"
    if name == "openapi3.yaml":
        assert contracts[0].sla_ms == 1200
    assert all(item.source_type == "openapi_node" for item in contracts[0].field_evidence)
    assert all("example.test" not in contracts[0].path for _ in [0])


@pytest.mark.parametrize(
    ("payload", "filename"),
    [
        ({"info": {"_postman_id": "x", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"}, "item": []}, "postman.json"),
        ({"asyncapi": "2.6.0", "channels": {}}, "asyncapi.yaml"),
        ({"data": {"__schema": {}}}, "graphql.json"),
    ],
)
def test_unsupported_structured_formats_are_rejected(payload: dict, filename: str) -> None:
    text = json.dumps(payload) if filename.endswith("json") else yaml.safe_dump(payload)
    with pytest.raises(ServiceError) as error:
        detect_document_format(text, filename)
    assert error.value.code == "DOCUMENT_FORMAT_UNSUPPORTED"


@pytest.mark.parametrize("text", ['syntax = "proto3"; service X { rpc Get (A) returns (B); }', "type Query { user: User }"])
def test_unsupported_text_protocols_are_rejected(text: str) -> None:
    with pytest.raises(ServiceError) as error:
        detect_document_format(text, "api.txt")
    assert error.value.code == "DOCUMENT_FORMAT_UNSUPPORTED"


def test_unstructured_ungrounded_fact_is_blocked() -> None:
    text = "# 登录\nPOST /login\n返回 200。"
    contracts, sections = parse_unstructured_document(
        text,
        parser=lambda _text: {
            "method": "POST", "path": "/login", "summary": "登录", "parameters": {
                "query": [{"name": "invented", "required": True, "type": {"type": "string"}}]
            }, "responses": {"http_code": "200", "description": "ok"},
        },
    )
    assert sections
    assert contracts[0].status == "draft"
    assert any(item.field_path == "parameters[0].name" for item in contracts[0].unresolved)


def test_logout_csrf_golden_sample_locates_header_but_keeps_required_for_review() -> None:
    """Curl 可证明 Header 位置，但未声明必填性时仍需人工决定。"""

    text = (FIXTURES / "logout-csrf.md").read_text(encoding="utf-8")
    contracts, _sections = parse_unstructured_document(text, parser=lambda _text: [{
        "name": "退出登录", "method": "POST", "path": "/api/logout",
        "parameters": {"header": [{"name": "X-CSRF-Token", "required": False}]},
        "responses": [{"http_code": 204}],
    }])
    contract = contracts[0]
    location = next(item for item in contract.field_evidence if item.field_path == "parameters[0].location")
    assert location.evidence_type == "explicit"
    assert "curl" in location.quote
    assert any(item.field_path == "parameters[0].required" for item in contract.unresolved)


def test_unstructured_model_retry_is_finite_and_auth_fails_fast() -> None:
    attempts = []

    def limited(_text):
        attempts.append(1)
        error = RuntimeError("rate limit")
        error.status_code = 429
        raise error

    with pytest.raises(ServiceError) as error:
        parse_unstructured_document("GET /health", parser=limited)
    assert error.value.code == "LLM_RATE_LIMITED"
    assert len(attempts) == 3

    auth_attempts = []

    def unauthorized(_text):
        auth_attempts.append(1)
        error = RuntimeError("invalid api key")
        error.status_code = 401
        raise error

    with pytest.raises(ServiceError) as auth_error:
        parse_unstructured_document("GET /health", parser=unauthorized)
    assert auth_error.value.code == "LLM_AUTH_FAILED"
    assert len(auth_attempts) == 1


def test_yaml_alias_limit_is_enforced_before_loading() -> None:
    text = "root: &root {value: 1}\nitems:\n" + "".join(f"  - *root # {index}\n" for index in range(101))
    with pytest.raises(ServiceError) as error:
        detect_document_format(text, "api.yaml")
    assert error.value.code == "DOCUMENT_SYNTAX_INVALID"
