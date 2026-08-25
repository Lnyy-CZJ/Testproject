"""阶段一纯 Contract Analysis Workflow。

本模块将格式路由、既有解析器、V3 Adapter 和质量门禁组织为可观测的 LangGraph。
它只处理调用者传入的内存数据；版本保存、任务状态迁移和任何真实请求均由 Runner
或后续执行平面负责。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.api_test.contracts.format_detector import DocumentFormat, detect_document_format
from agents.api_test.contracts.openapi_parser import parse_openapi_document
from agents.api_test.contracts.unstructured_parser import split_sections
from agents.api_test.contracts.v2_adapter import V2ContractAdapter
from services.api_agent.models import (
    ApiContract,
    GenerationRejection,
    StageEvent,
    WorkflowProvenance,
    WorkflowResult,
    WorkflowRuntimeContext,
)


class ContractAnalysisState(TypedDict, total=False):
    """图内状态，仅容纳输入快照和中间内存对象。"""

    document_text: str
    filename: str
    runtime: WorkflowRuntimeContext
    document: dict[str, Any]
    document_format: DocumentFormat
    route: str
    sections: list[dict[str, Any]]
    raw_contracts: list[ApiContract]
    raw_candidates: Any
    contracts: list[ApiContract]


class ContractAnalysisWorkflow:
    """V2.4 阶段一主图，输出未持久化的 ``WorkflowResult``。"""

    _NODES = (
        "preflight", "route_format", "deterministic_parse", "split_sections",
        "legacy_ai_parse", "contract_v2_adapter", "request_body_completeness",
        "auth_completeness", "evidence_binding", "contract_quality_gate",
        "output_contract_candidates",
    )

    def __init__(
        self,
        *,
        legacy_parser: Callable[[str], Any] | None = None,
        adapter: V2ContractAdapter | None = None,
    ) -> None:
        self._legacy_parser = legacy_parser
        self._adapter = adapter or V2ContractAdapter()

    def create_workflow(self):
        """构建无副作用的 LangGraph；每个节点仅返回内存状态增量。"""

        graph = StateGraph(ContractAnalysisState)
        graph.add_node("preflight", self._preflight)
        graph.add_node("route_format", self._route_format)
        graph.add_node("deterministic_parse", self._deterministic_parse)
        graph.add_node("split_sections", self._split_sections)
        graph.add_node("legacy_ai_parse", self._legacy_ai_parse)
        graph.add_node("contract_v2_adapter", self._contract_v2_adapter)
        graph.add_node("request_body_completeness", self._request_body_completeness)
        graph.add_node("auth_completeness", self._auth_completeness)
        graph.add_node("evidence_binding", self._evidence_binding)
        graph.add_node("contract_quality_gate", self._contract_quality_gate)
        graph.add_node("output_contract_candidates", self._output_contract_candidates)
        graph.add_edge(START, "preflight")
        graph.add_edge("preflight", "route_format")
        graph.add_conditional_edges(
            "route_format", lambda state: state["route"],
            {"structured": "deterministic_parse", "unstructured": "split_sections"},
        )
        graph.add_edge("deterministic_parse", "contract_v2_adapter")
        graph.add_edge("split_sections", "legacy_ai_parse")
        graph.add_edge("legacy_ai_parse", "contract_v2_adapter")
        graph.add_edge("contract_v2_adapter", "request_body_completeness")
        graph.add_edge("request_body_completeness", "auth_completeness")
        graph.add_edge("auth_completeness", "evidence_binding")
        graph.add_edge("evidence_binding", "contract_quality_gate")
        graph.add_edge("contract_quality_gate", "output_contract_candidates")
        graph.add_edge("output_contract_candidates", END)
        return graph.compile()

    def run(
        self,
        *,
        document_text: str,
        filename: str,
        runtime: WorkflowRuntimeContext,
    ) -> WorkflowResult:
        """执行阶段一主图并返回纯内存候选；异常转换为可审计的 failed 结果。"""

        try:
            state = self.create_workflow().invoke({
                "document_text": document_text, "filename": filename, "runtime": runtime,
            })
            contracts = state.get("contracts", [])
            blockers = sum(len(contract.quality_report.blockers) for contract in contracts)
            ready = sum(contract.status == "confirmed_candidate" for contract in contracts)
            status = "ready" if ready and not blockers else "partial_ready" if ready else "failed"
            return WorkflowResult(
                status=status,
                items=[contract.model_dump(mode="json") for contract in contracts],
                rejections=[],
                quality_summary={"candidate_count": len(contracts), "ready_count": ready, "blocker_count": blockers},
                workflow_provenance=self._provenance(runtime),
            )
        except Exception as exc:
            self._emit(runtime, "contract_analysis", "failed", "failed", str(exc))
            return WorkflowResult(
                status="failed", items=[],
                rejections=[GenerationRejection(
                    contract_id="", item_index=-1, prompt_id="contract_analysis",
                    prompt_sha256="", error_code="CONTRACT_WORKFLOW_FAILED",
                    rejection_stage="response", suggestion="检查文档格式或解析器输出",
                )],
                quality_summary={"candidate_count": 0, "blocker_count": 1},
                workflow_provenance=self._provenance(runtime),
            )

    def _preflight(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "preflight", "started")
        document_format, document, _profile = detect_document_format(
            state["document_text"], state["filename"]
        )
        self._emit_state(state, "preflight", "completed")
        return {
            "document_format": document_format,
            "document": document if isinstance(document, dict) else {},
        }

    def _route_format(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "route_format", "started")
        route = "structured" if state["document_format"] in {
            DocumentFormat.OPENAPI_3, DocumentFormat.SWAGGER_2,
        } else "unstructured"
        self._emit_state(state, "route_format", "completed", route)
        return {"route": route}

    def _deterministic_parse(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "deterministic_parse", "started")
        document = state["document"]
        contracts = parse_openapi_document(document)
        self._emit_state(state, "deterministic_parse", "completed", f"解析 {len(contracts)} 个接口")
        return {"document": document, "raw_contracts": contracts}

    def _split_sections(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "split_sections", "started")
        sections = split_sections(state["document_text"])
        self._emit_state(state, "split_sections", "completed", f"切分 {len(sections)} 个片段")
        return {"sections": sections}

    def _legacy_ai_parse(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "legacy_ai_parse", "started")
        parser = self._legacy_parser
        if parser is None:
            from agents.api_test.parsers.ai_parser_api_document import AIAPIDocumentParser
            parser = AIAPIDocumentParser().parser
        candidates = parser(state["document_text"])
        # 旧 Parser 的输出 Schema 只描述单接口；把整份多接口 Markdown 一次性交给
        # 它时通常只返回第一条。这里以文档中明确的 METHOD/PATH 为确定性骨架，
        # 再把模型结果合并到同一接口，既不增加模型调用次数，也不丢失后续接口。
        candidates = _merge_endpoint_skeletons(candidates, state.get("sections", []))
        self._emit_state(state, "legacy_ai_parse", "completed", f"聚合 {len(candidates)} 个接口候选")
        return {"raw_candidates": candidates}

    def _contract_v2_adapter(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "contract_v2_adapter", "started")
        if state.get("route") == "structured":
            contracts = self._adapter.enrich_deterministic_contracts(
                state.get("raw_contracts", []), document_text=state["document_text"],
                document=state["document"], source_id=state["filename"],
            )
        else:
            contracts = self._adapter.adapt_legacy_candidates(
                state.get("raw_candidates"), document_text=state["document_text"], source_id=state["filename"],
            )
        self._emit_state(state, "contract_v2_adapter", "completed", f"适配 {len(contracts)} 个候选")
        return {"contracts": contracts}

    def _request_body_completeness(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "request_body_completeness", "completed")
        return {}

    def _auth_completeness(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "auth_completeness", "completed")
        return {}

    def _evidence_binding(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "evidence_binding", "completed")
        return {}

    def _contract_quality_gate(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "contract_quality_gate", "completed")
        return {}

    def _output_contract_candidates(self, state: ContractAnalysisState) -> dict[str, Any]:
        self._emit_state(state, "output_contract_candidates", "completed")
        return {}

    def _emit_state(self, state: ContractAnalysisState, node: str, event_type: str, message: str = "") -> None:
        self._emit(state["runtime"], node, event_type, "running" if event_type == "started" else "completed", message)

    @staticmethod
    def _emit(runtime: WorkflowRuntimeContext, node: str, event_type: str, status: str, message: str) -> None:
        runtime.event_sink(StageEvent(
            event_id=f"workflow_{hashlib.sha256(f'{runtime.attempt_id}|{node}|{event_type}'.encode()).hexdigest()[:20]}",
            task_id=runtime.task_id, attempt_id=runtime.attempt_id, stage="document_preflight",
            node=node, event_type=event_type, status=status, message=message,
            input_versions=runtime.input_versions, workflow_id=runtime.workflow_id,
            workflow_version=runtime.workflow_version,
            workflow_sha256=hashlib.sha256("|".join(ContractAnalysisWorkflow._NODES).encode()).hexdigest(),
        ))

    @classmethod
    def _provenance(cls, runtime: WorkflowRuntimeContext) -> WorkflowProvenance:
        return WorkflowProvenance(
            workflow_id=runtime.workflow_id, workflow_version=runtime.workflow_version,
            workflow_sha256=hashlib.sha256("|".join(cls._NODES).encode()).hexdigest(),
            input_versions=runtime.input_versions, node_ids=list(cls._NODES),
        )


_ENDPOINT_LINE = re.compile(r"(?im)^\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(`?[^\s`；;]+`?)")
_HEADER_LINE = re.compile(r"(?im)^\s*([A-Za-z][A-Za-z0-9-]{1,63})\s*:\s*([^\n]+)$")
_PUBLIC_NO_AUTH = frozenset({
    "/api/v1/health/live", "/api/v1/health/ready", "/api/v1/setup", "/api/v1/auth/login",
})


def _merge_endpoint_skeletons(candidates: Any, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """以明确 METHOD/PATH 补齐旧单接口 Parser 的缺口，并按接口去重合并。"""

    raw_items = candidates if isinstance(candidates, list) else [candidates]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        method = str(raw.get("method", "")).upper()
        path = str(raw.get("path", "")).split("?", 1)[0].strip("`；;")
        if method and path.startswith("/"):
            by_key[(method, path)] = dict(raw)

    common_auth = next((
        str(section.get("content", "")).split("所有平台错误使用", 1)[0]
        for section in sections if "通用约定" in str(section.get("title", ""))
    ), "")
    for section in sections:
        content = str(section.get("content", ""))
        matches = list(_ENDPOINT_LINE.finditer(content))
        for index, match in enumerate(matches):
            method = match.group(1).upper()
            raw_target = match.group(2).strip("`；;")
            path, _, query_text = raw_target.partition("?")
            if not path.startswith("/"):
                continue
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            snippet = content[match.start():end].strip()
            skeleton = _endpoint_skeleton(method, path, query_text, snippet, common_auth, section)
            existing = by_key.get((method, path))
            if existing:
                # 模型结构优先补充业务语义；确定性来源片段和显式无鉴权结论始终
                # 由文档骨架控制，模型不得替换或扩大来源范围。
                skeleton.update(existing)
                skeleton["method"], skeleton["path"] = method, path
                skeleton["_source_text"] = _endpoint_source_text(snippet, common_auth, path)
                skeleton["_source_section_id"] = str(section.get("section_id", ""))
            by_key[(method, path)] = skeleton
    return [by_key[key] for key in sorted(by_key)]


def _endpoint_source_text(snippet: str, common_auth: str, path: str) -> str:
    """只给接口绑定直接片段和必要的公共鉴权约定，避免整文档信号串扰。"""

    return snippet if path in _PUBLIC_NO_AUTH else f"{snippet}\n{common_auth}".strip()


def _endpoint_skeleton(
    method: str, path: str, query_text: str, snippet: str, common_auth: str,
    section: dict[str, Any],
) -> dict[str, Any]:
    """从文档明确文本构造最小旧 Parser 兼容结构，不推断响应或业务结果。"""

    parameters: dict[str, list[dict[str, Any]]] = {key: [] for key in ("header", "path", "query", "cookie")}
    for name in re.findall(r"\{([A-Za-z_][A-Za-z0-9_-]*)\}", path):
        parameters["path"].append(_parameter(name, True, "路径参数"))
    for pair in query_text.split("&") if query_text else []:
        name = pair.split("=", 1)[0].strip()
        if name:
            parameters["query"].append(_parameter(name, False, "文档示例查询参数"))
    for name, value in _HEADER_LINE.findall(snippet):
        if name.lower() in {"content-type", "accept"}:
            continue
        parameters["header"].append(_parameter(name, True, value.strip()))

    explicit_no_auth = path in _PUBLIC_NO_AUTH
    if path.startswith("/api/v1/internal/"):
        _append_unique(parameters["header"], _parameter("Authorization", True, "Bearer tool-client-token"))
    elif not explicit_no_auth and path.startswith("/api/v1/"):
        _append_unique(parameters["cookie"], _parameter("tp_session", True, "有效统一会话 Cookie"))
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            _append_unique(parameters["header"], _parameter("X-CSRF-Token", True, "写请求使用 tp_csrf"))

    request_body = _json_request_body(snippet)
    return {
        "name": f"{method} {path}", "summary": str(section.get("title", "")),
        "method": method, "path": path, "parameters": parameters,
        "requestBody": request_body,
        "_explicit_no_auth": explicit_no_auth,
        "_source_text": _endpoint_source_text(snippet, common_auth, path),
        "_source_section_id": str(section.get("section_id", "")),
    }


def _parameter(name: str, required: bool, description: str) -> dict[str, Any]:
    return {
        "name": name, "required": required, "description": description,
        "type": {"type": "string"}, "param_role": "required" if required else "optional",
    }


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if not any(str(existing.get("name", "")).lower() == str(item["name"]).lower() for existing in items):
        items.append(item)


def _json_request_body(snippet: str) -> dict[str, Any] | None:
    """读取紧邻接口的 JSON 示例字段；示例只证明字段存在，不臆断必填性。"""

    start = snippet.find("{")
    if start < 0:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(snippet[start:])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None

    def schema_type(item: Any) -> str:
        if isinstance(item, bool):
            return "boolean"
        if isinstance(item, int):
            return "integer"
        if isinstance(item, float):
            return "number"
        if isinstance(item, list):
            return "array"
        if isinstance(item, dict):
            return "object"
        return "string"

    return {
        "content_type": "application/json",
        "body": [{
            "name": str(name), "description": "文档 JSON 示例字段", "required": False,
            "type": {"type": schema_type(item)}, "param_role": "optional", "allow_omit": True,
            "baseline_value": item,
        } for name, item in value.items()],
    }
