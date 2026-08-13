"""非结构化 HTTP API 文档的切片、LLM 映射和 Grounding 门禁。"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from agents.api_test.contracts.quality_gate import apply_quality_gate
from services.api_agent.models import (
    ApiContract, ContractParameter, FieldEvidence, ResponseDefinition,
    ReviewIssue, SourceTrace,
)
from services.common.errors import ServiceError, classify_runner_exception


ParserCallable = Callable[[str], Any]
_HEADING = re.compile(r"(?m)^(#{1,6})\s+(.+)$")


def split_sections(text: str) -> list[dict[str, str]]:
    """按 Markdown 标题切片；无标题文档作为单个稳定 Section。"""

    matches = list(_HEADING.finditer(text))
    if not matches:
        return [{"section_id": "section-001", "title": "API 文档", "content": text}]
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append({
            "section_id": f"section-{index + 1:03d}",
            "title": match.group(2).strip(),
            "content": text[start:end].strip(),
        })
    return sections


def parse_unstructured_document(
    text: str,
    *,
    parser: ParserCallable | None = None,
    source_id: str = "document",
    minimum_score: float = 0.90,
) -> tuple[list[ApiContract], list[dict[str, str]]]:
    """调用现有 LLM 解析器并把结果映射到带 Evidence 的契约。

    测试可注入纯函数 Parser；生产默认延迟导入现有 AIAPIDocumentParser。
    模型返回的关键值必须能在关联 Section 原文中找到，否则进入 unresolved。
    """

    sections = split_sections(text)
    if parser is None:
        from agents.api_test.parsers.ai_parser_api_document import AIAPIDocumentParser

        parser = AIAPIDocumentParser().parser
    raw = _parse_with_limited_retry(parser, text)
    items = raw if isinstance(raw, list) else [raw]
    contracts = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        section = _best_section(item, sections)
        quote = section["content"]
        method = str(item.get("method", "")).upper()
        path = str(item.get("path", ""))
        unresolved: list[ReviewIssue] = []
        evidences: list[FieldEvidence] = []
        _ground("method", method, quote, section, evidences, unresolved)
        _ground("path", path, quote, section, evidences, unresolved)
        parameters = []
        raw_groups = item.get("parameters") or {}
        for location in ("header", "path", "query", "cookie"):
            for raw_parameter in raw_groups.get(location, []) if isinstance(raw_groups, dict) else []:
                if not isinstance(raw_parameter, dict):
                    continue
                parameter_index = len(parameters)
                parameter = ContractParameter(
                    name=str(raw_parameter.get("name", "")), location=location,
                    required=bool(raw_parameter.get("required")),
                    description=str(raw_parameter.get("description", "")),
                    schema=raw_parameter.get("type") if isinstance(raw_parameter.get("type"), dict) else {},
                    example=raw_parameter.get("example"),
                )
                parameters.append(parameter)
                for field, value in (
                    ("name", parameter.name), ("location", location), ("required", parameter.required),
                ):
                    _ground(
                        f"parameters[{parameter_index}].{field}", value, quote,
                        section, evidences, unresolved,
                    )
        responses = []
        raw_responses = item.get("responses")
        if isinstance(raw_responses, dict):
            raw_responses = [raw_responses]
        for response_index, response in enumerate(raw_responses or []):
            if not isinstance(response, dict):
                continue
            status = str(response.get("http_code") or response.get("status_code") or "")
            responses.append(ResponseDefinition(
                status_code=status or "default", description=str(response.get("description", "")),
                content=response.get("content") if isinstance(response.get("content"), dict) else {},
            ))
            _ground(
                f"responses[{response_index}].status_code", status or "default", quote,
                section, evidences, unresolved,
            )
        # method/path 缺失时使用可校验占位值，但保持硬阻断 draft。
        safe_method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "GET"
        safe_path = path if path.startswith("/") and "://" not in path else "/unresolved"
        llm_unresolved = _review_issues(item.get("unresolved"), default_code="LLM_UNRESOLVED")
        conflicts = _review_issues(item.get("conflict_items"), default_code="LLM_CONFLICT", default_severity="blocker")
        ambiguities = _review_issues(item.get("ambiguity_notes"), default_code="LLM_AMBIGUITY")
        contract = ApiContract(
            contract_id="contract_" + hashlib.sha256(f"{safe_method} {safe_path} {index}".encode()).hexdigest()[:20],
            name=str(item.get("name") or item.get("summary") or f"{safe_method} {safe_path}"),
            summary=str(item.get("summary", "")), method=safe_method, path=safe_path,
            parameters=parameters, responses=responses,
            source_trace=SourceTrace(source_id=source_id, section_id=section["section_id"], quote=quote[:2000]),
            field_evidence=evidences, unresolved=[*unresolved, *llm_unresolved],
            conflict_items=conflicts, ambiguity_notes=ambiguities,
            test_design_suggestions=item.get("test_design_suggestions", []) if isinstance(item.get("test_design_suggestions"), list) else [],
        )
        contracts.append(apply_quality_gate(contract, minimum_score=minimum_score))
    return contracts, sections


def _review_issues(value: Any, *, default_code: str, default_severity: str = "warning") -> list[ReviewIssue]:
    """把模型的冲突、歧义和未解决项限制在显式 Review Schema 内。"""

    values = value if isinstance(value, list) else []
    result = []
    for item in values:
        if isinstance(item, str):
            result.append(ReviewIssue(code=default_code, field_path="", message=item, severity=default_severity))
        elif isinstance(item, dict) and item.get("message"):
            severity = item.get("severity") if item.get("severity") in {"info", "warning", "blocker"} else default_severity
            result.append(ReviewIssue(
                code=str(item.get("code") or default_code), field_path=str(item.get("field_path", "")),
                message=str(item["message"]), severity=severity,
                source_pointer=str(item.get("source_pointer", "")),
            ))
    return result


def _parse_with_limited_retry(parser: ParserCallable, text: str) -> Any:
    """对模型限流、超时和格式错误最多补充重试两次。

    鉴权错误不会重试；所有模型异常最终映射为稳定错误码，调用方可保留
    已完成的预检和切片产物并给出下一步建议。
    """

    retryable = {"LLM_RATE_LIMITED", "LLM_TIMEOUT", "LLM_RESPONSE_INVALID"}
    for attempt in range(3):
        try:
            return parser(text)
        except Exception as exc:
            code, message = classify_runner_exception(
                exc, default_code="CONTRACT_PARSE_FAILED", default_message="非结构化接口文档解析失败",
            )
            if code not in retryable or attempt == 2:
                raise ServiceError(503 if code != "LLM_RESPONSE_INVALID" else 422, code, message) from None
    raise ServiceError(422, "CONTRACT_PARSE_FAILED", "非结构化接口文档解析失败")


def _best_section(item: dict[str, Any], sections: list[dict[str, str]]) -> dict[str, str]:
    """选择同时包含 method/path 最多的原文 Section。"""

    needles = [str(item.get("method", "")), str(item.get("path", ""))]
    return max(sections, key=lambda section: sum(bool(value and value.lower() in section["content"].lower()) for value in needles))


def _ground(
    field_path: str,
    value: Any,
    quote: str,
    section: dict[str, str],
    evidence: list[FieldEvidence],
    unresolved: list[ReviewIssue],
) -> None:
    """将能从原文直接找到的值绑定 Evidence，其余移动到未解决项。"""

    text = str(value)
    explicit = bool(text) and text.lower() in quote.lower()
    evidence.append(FieldEvidence(
        field_path=field_path, value=value, source_type="source_quote",
        source_pointer=section["section_id"], quote=quote[:1000],
        evidence_type="explicit" if explicit else "inferred",
        confidence=1.0 if explicit else 0.0,
    ))
    if not explicit:
        unresolved.append(ReviewIssue(
            code="UNGROUNDED_FIELD", field_path=field_path,
            message="该字段缺少直接原文依据，未作为可确认事实", severity="blocker",
            source_pointer=section["section_id"],
        ))
