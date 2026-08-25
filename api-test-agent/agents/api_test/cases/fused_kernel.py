"""无数据库、无执行副作用的 API V2.2 融合生成内核。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from agents.api_test.cases.coverage import build_coverage
from agents.api_test.cases.grounding import assess_case_grounding, contract_evidence_refs
from services.api_agent.models import (
    ApiContract,
    BaseTestCase,
    CaseParameterMutation,
    GenerationProvenance,
    GenerationRejection,
    ReviewIssue,
)


ModelCallable = Callable[[str], Any]


@dataclass(frozen=True)
class GenerationContext:
    """单接口最小生成上下文；禁止混入其他接口或真实执行目标。"""

    contract: ApiContract
    contract_version: int
    document_excerpt: str = ""
    analysis_scope: dict[str, Any] = field(default_factory=dict)
    accepted_suggestions: tuple[str, ...] = ()
    historical_case_summaries: tuple[str, ...] = ()

    @classmethod
    def from_contract(cls, contract: ApiContract, *, contract_version: int) -> "GenerationContext":
        """从契约 Evidence 构造受限上下文。"""

        excerpt = "\n".join(item.quote for item in contract.field_evidence if item.quote)[:4000]
        suggestions = tuple(
            json.dumps(item, ensure_ascii=False, default=str)
            for item in contract.test_design_suggestions
        )
        return cls(contract=contract, contract_version=contract_version, document_excerpt=excerpt, accepted_suggestions=suggestions)

    def prompt_payload(self) -> dict[str, Any]:
        """返回可序列化且不含 Server、Credential 的模型输入。"""

        contract = self.contract
        return {
            "contract": {
                "contract_id": contract.contract_id,
                "name": contract.name,
                "summary": contract.summary,
                "method": contract.method,
                "path": contract.path,
                "parameters": [item.model_dump(mode="json", by_alias=True) for item in contract.parameters],
                "request_body": contract.request_body.model_dump(mode="json") if contract.request_body else None,
                "responses": [item.model_dump(mode="json") for item in contract.responses],
                "security": [item.model_dump(mode="json") for item in contract.security],
                "dependencies": [item.model_dump(mode="json") for item in contract.dependencies],
            },
            "document_excerpt": self.document_excerpt,
            "analysis_scope": self.analysis_scope,
            "accepted_suggestions": list(self.accepted_suggestions),
            "historical_case_summaries": list(self.historical_case_summaries),
        }


def _prompt_sha() -> str:
    """计算融合基础用例 Prompt 的稳定摘要。"""

    from agents.api_test.prompts.base_case_generator import v2_prompt

    template = getattr(v2_prompt, "template", str(v2_prompt))
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def _enrich_case(case: BaseTestCase, contract: ApiContract) -> BaseTestCase:
    """把确定性覆盖骨架补成可 Review 的步骤、数据变化和 Evidence。"""

    updated = case.model_copy(deep=True)
    updated.generation_kernel = "v2_fused"
    updated.generation_sources = ["deterministic_rule", f"contract:{contract.contract_id}"]
    updated.prompt_sha256 = ""
    updated.evidence_refs = contract_evidence_refs(contract)
    updated.scenario_type = "negative" if any(key in updated.dimension for key in ("missing", "invalid", "boundary", "auth", "response:")) else "normal"
    if updated.dimension == "positive":
        updated.steps = [{"order": 1, "action": "按契约构造完整有效请求", "method": contract.method, "path": contract.path}]
        updated.expected_results = [response.description or f"返回状态 {response.status_code}" for response in contract.responses if response.status_code.startswith("2")]
        if not updated.expected_results:
            updated.scenario_type = "exploratory"
            updated.expected_results = ["记录实际状态码和响应结构，等待人工确认"]
    elif updated.dimension.startswith("required_missing:"):
        name = updated.dimension.rsplit(":", 1)[-1]
        updated.parameter_mutations = [CaseParameterMutation(field_path=name, strategy="missing", description=f"移除必填参数 {name}")]
        updated.steps = [{"order": 1, "action": f"移除必填参数 {name} 后发送请求", "method": contract.method, "path": contract.path}]
    elif updated.dimension == "auth_missing":
        updated.parameter_mutations = [CaseParameterMutation(field_path="security", strategy="missing", description="不注入鉴权信息")]
        updated.steps = [{"order": 1, "action": "不携带鉴权信息发送请求", "method": contract.method, "path": contract.path}]
    elif updated.dimension.startswith("type_invalid:"):
        name = updated.dimension.rsplit(":", 1)[-1]
        updated.parameter_mutations = [CaseParameterMutation(field_path=name, strategy="invalid_type", description=f"把 {name} 替换为契约不允许的类型")]
        updated.steps = [{"order": 1, "action": f"使用错误类型的 {name} 发送请求", "method": contract.method, "path": contract.path}]
    elif updated.dimension.startswith("enum_boundary:"):
        name = updated.dimension.rsplit(":", 1)[-1]
        updated.parameter_mutations = [CaseParameterMutation(field_path=name, strategy="invalid_enum", description=f"使用 {name} 枚举之外的值")]
        updated.steps = [{"order": 1, "action": f"使用非法枚举值的 {name} 发送请求", "method": contract.method, "path": contract.path}]
    elif updated.dimension.startswith("boundary:"):
        name = updated.dimension.rsplit(":", 1)[-1]
        updated.parameter_mutations = [CaseParameterMutation(field_path=name, strategy="boundary", description=f"验证 {name} 的边界内外取值")]
        updated.steps = [{"order": 1, "action": f"使用 {name} 边界值发送请求", "method": contract.method, "path": contract.path}]
    else:
        updated.steps = [{"order": 1, "action": updated.objective, "method": contract.method, "path": contract.path}]
    updated.quality_report = assess_case_grounding(updated, contract)
    if not updated.quality_report.hard_gate_passed:
        updated.status = "draft"
    return updated


_SCENARIO_TYPES = {
    "normal": "normal", "positive": "normal", "success": "normal",
    "valid": "normal", "happy_path": "normal",
    "negative": "negative", "abnormal": "negative", "invalid": "negative",
    "error": "negative", "failure": "negative",
    "exploratory": "exploratory", "exploration": "exploratory",
    "observe": "exploratory", "unknown_expectation": "exploratory",
}


def _normalize_scenario_type(value: Any) -> tuple[str, bool]:
    """在 Schema 前归一化模型常见枚举；未知值必须显式降为探索场景。"""

    normalized = str(value or "normal").strip().lower()
    return _SCENARIO_TYPES.get(normalized, "exploratory"), normalized not in _SCENARIO_TYPES


def _rejection(
    contract: ApiContract, *, index: int, prompt_sha: str, error_code: str,
    stage: str, suggestion: str, field_path: str = "", model_call_id: str | None = None,
) -> GenerationRejection:
    """构造不含模型原文的拒绝摘要。"""

    return GenerationRejection(
        contract_id=contract.contract_id, item_index=index, model_call_id=model_call_id,
        prompt_id="base_case_generator.v2_prompt", prompt_sha256=prompt_sha,
        error_code=error_code, field_path=field_path, rejection_stage=stage,
        suggestion=suggestion,
    )


def generate_fused_cases(
    context: GenerationContext,
    *,
    model: ModelCallable | None = None,
    attempt_id: str = "",
) -> tuple[list[BaseTestCase], GenerationProvenance]:
    """生成单接口基础用例；模型只能追加通过 Grounding 的候选。"""

    contract = context.contract
    deterministic, _matrix = build_coverage([contract], contract_version=context.contract_version)
    cases = [_enrich_case(case, contract) for case in deterministic]
    prompt_sha = _prompt_sha()
    rejections: list[GenerationRejection] = []
    llm_count = 0
    supplement_status = "not_called"
    if model is not None:
        from agents.api_test.prompts.base_case_generator import v2_prompt

        prompt = v2_prompt.format(generation_context=json.dumps(context.prompt_payload(), ensure_ascii=False))
        model_call_id = None
        try:
            raw = model(prompt)
            metadata = getattr(raw, "response_metadata", {})
            if isinstance(metadata, dict):
                model_call_id = metadata.get("api_model_call_id")
            raw = getattr(raw, "content", raw)
            if isinstance(raw, str):
                raw = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            if not isinstance(raw, list):
                raise ValueError("模型输出必须为 JSON 数组")
        except Exception as exc:
            model_call_id = getattr(exc, "model_call_id", model_call_id)
            raw = []
            rejections.append(_rejection(
                contract, index=-1, prompt_sha=prompt_sha,
                error_code="LLM_RESPONSE_INVALID", stage="response",
                suggestion="重试 AI 补充或检查模型输出格式", model_call_id=model_call_id,
            ))
        for index, item in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(item, dict):
                rejections.append(_rejection(
                    contract, index=index, prompt_sha=prompt_sha,
                    error_code="CASE_PROMPT_ITEM_INVALID", stage="schema",
                    suggestion="模型候选必须是 JSON 对象", model_call_id=model_call_id,
                ))
                continue
            scenario_type, unknown_scenario = _normalize_scenario_type(item.get("scenario_type"))
            try:
                if not isinstance(item.get("steps", []), list):
                    raise ValueError("steps 必须为数组")
                if not isinstance(item.get("expected_results", []), list):
                    raise ValueError("expected_results 必须为数组")
                digest_input = f"{contract.contract_id}|llm|{index}|{item.get('name', '')}"
                case = BaseTestCase(
                    case_id=f"case_{hashlib.sha256(digest_input.encode()).hexdigest()[:20]}",
                    contract_id=contract.contract_id,
                    name=str(item.get("name", "")).strip(),
                    objective=str(item.get("objective", "")).strip(),
                    dimension=str(item.get("dimension", "business_scenario")),
                    preconditions=[str(value) for value in item.get("preconditions", []) if str(value).strip()],
                    steps=[value for value in item.get("steps", []) if isinstance(value, dict)],
                    expected_results=[str(value) for value in item.get("expected_results", []) if str(value).strip()],
                    source="llm", scenario_type=scenario_type,
                    generation_kernel="v2_fused",
                    generation_sources=["llm_business_case", f"contract:{contract.contract_id}"],
                    prompt_sha256=prompt_sha, evidence_refs=contract_evidence_refs(contract),
                )
            except (TypeError, ValueError) as exc:
                field_path = ""
                errors = getattr(exc, "errors", lambda: [])()
                if errors:
                    field_path = ".".join(str(value) for value in errors[0].get("loc", ()))
                rejections.append(_rejection(
                    contract, index=index, prompt_sha=prompt_sha,
                    error_code="CASE_PROMPT_ITEM_INVALID", field_path=field_path,
                    stage="schema", suggestion=str(exc).splitlines()[0][:200],
                    model_call_id=model_call_id,
                ))
                continue
            case.quality_report = assess_case_grounding(case, contract)
            if unknown_scenario:
                case.quality_report.warnings.append(ReviewIssue(
                    code="CASE_ENUM_NORMALIZED", field_path="scenario_type",
                    message="未知场景类型已转为探索场景，请人工确认", severity="warning",
                ))
            if not case.name or not case.objective or not case.steps or (
                case.scenario_type == "exploratory" and not case.expected_results
            ):
                rejections.append(_rejection(
                    contract, index=index, prompt_sha=prompt_sha,
                    error_code="CASE_PROMPT_ITEM_INVALID", stage="completeness",
                    suggestion="补充用例名称、目标、步骤和预期或观察目标",
                    model_call_id=model_call_id,
                ))
                continue
            if not case.quality_report.hard_gate_passed:
                rejections.append(_rejection(
                    contract, index=index, prompt_sha=prompt_sha,
                    error_code="CASE_GROUNDING_FAILED", stage="grounding",
                    suggestion="删除契约外业务内容并关联当前接口依据",
                    field_path=case.quality_report.blockers[0].field_path if case.quality_report.blockers else "",
                    model_call_id=model_call_id,
                ))
                continue
            signature = json.dumps({
                "contract": case.contract_id, "dimension": case.dimension,
                "steps": case.steps, "expected": case.expected_results,
            }, ensure_ascii=False, sort_keys=True, default=str)
            if any(json.dumps({
                "contract": existing.contract_id, "dimension": existing.dimension,
                "steps": existing.steps, "expected": existing.expected_results,
            }, ensure_ascii=False, sort_keys=True, default=str) == signature for existing in cases):
                rejections.append(_rejection(
                    contract, index=index, prompt_sha=prompt_sha,
                    error_code="CASE_PROMPT_ITEM_INVALID", stage="deduplication",
                    suggestion="删除与已有覆盖语义重复的候选", model_call_id=model_call_id,
                ))
                continue
            case.status = "confirmed_candidate"
            cases.append(case)
            llm_count += 1

        supplement_status = "succeeded" if not rejections else ("partial" if llm_count else "failed")

    provenance = GenerationProvenance(
        attempt_id=attempt_id,
        generation_kernel="v2_fused",
        contract_ids=[contract.contract_id],
        input_versions={"contracts": context.contract_version},
        prompt_ids=["base_case_generator.v2_prompt"] if model is not None else [],
        prompt_sha256={"base_case_generator.v2_prompt": prompt_sha} if model is not None else {},
        deterministic_case_count=sum(item.source == "deterministic" for item in cases),
        llm_case_count=llm_count, rejected_case_count=len(rejections),
        ai_supplement_status=supplement_status, rejections=rejections,
    )
    return cases, provenance
