"""API V2.2 基础用例 Grounding 与历史执行定义兼容门禁。"""

from __future__ import annotations

import json
import re
from typing import Any

from services.api_agent.models import (
    ApiContract,
    BaseTestCase,
    CaseEvidenceRef,
    CaseQualityReport,
    ReviewIssue,
)


_BUSINESS_TERMS = frozenset({
    "登录", "注册", "鉴权", "账号", "密码", "会话", "令牌", "商品", "订单", "支付",
    "退款", "购物车", "库存", "物流", "优惠券", "发票", "用户", "文件", "上传",
})


def contract_evidence_refs(contract: ApiContract) -> list[CaseEvidenceRef]:
    """把契约字段证据转换为轻量引用，避免复制整份原文。"""

    refs = [CaseEvidenceRef(
        field_path=item.field_path,
        source_pointer=item.source_pointer,
        quote=item.quote[:240],
    ) for item in contract.field_evidence if item.source_type != "human_override" or item.quote]
    if not refs and contract.source_trace.section_id:
        refs.append(CaseEvidenceRef(
            field_path="contract",
            source_pointer=contract.source_trace.section_id,
            quote=contract.source_trace.quote[:240],
        ))
    return refs


def _issue(code: str, message: str, *, field_path: str = "") -> ReviewIssue:
    """生成稳定的基础用例阻断项。"""

    return ReviewIssue(code=code, field_path=field_path, message=message, severity="blocker")


def _contract_text(contract: ApiContract) -> str:
    """汇总允许用于业务语义校验的契约事实。"""

    values: list[Any] = [
        contract.name, contract.summary, contract.module, contract.tags, contract.method, contract.path,
        [item.name for item in contract.parameters],
        [item.description for item in contract.responses],
        [item.quote for item in contract.field_evidence],
        contract.test_design_suggestions,
    ]
    return json.dumps(values, ensure_ascii=False, default=str).lower()


def assess_case_grounding(case: BaseTestCase, contract: ApiContract) -> CaseQualityReport:
    """验证用例内容是否来自绑定契约并具备可 Review 的完整结构。"""

    blockers: list[ReviewIssue] = []
    if case.contract_id != contract.contract_id:
        blockers.append(_issue("CASE_GROUNDING_FAILED", "用例绑定的接口契约不一致", field_path="contract_id"))
    if not case.steps:
        blockers.append(_issue("CASE_REQUEST_INCOMPLETE", "基础用例缺少执行步骤", field_path="steps"))
    if not case.expected_results and case.scenario_type != "exploratory":
        blockers.append(_issue("CASE_EXPECTATION_UNGROUNDED", "基础用例缺少预期结果", field_path="expected_results"))

    case_text = json.dumps({
        "name": case.name,
        "objective": case.objective,
        "steps": case.steps,
        "expected_results": case.expected_results,
    }, ensure_ascii=False, default=str).lower()
    allowed_text = _contract_text(contract)
    unsupported = sorted(term for term in _BUSINESS_TERMS if term in case_text and term not in allowed_text)
    if unsupported:
        blockers.append(_issue(
            "CASE_BUSINESS_CONTEXT_UNSUPPORTED",
            f"用例包含契约未支持的业务语义：{', '.join(unsupported)}",
            field_path="objective",
        ))

    refs = case.evidence_refs or contract_evidence_refs(contract)
    if not refs:
        blockers.append(_issue("CASE_GROUNDING_FAILED", "用例没有可追溯的契约 Evidence", field_path="evidence_refs"))
    evidence_rate = 1.0 if refs else 0.0
    completeness = bool(case.steps and (case.expected_results or case.scenario_type == "exploratory"))
    return CaseQualityReport(
        hard_gate_passed=not blockers,
        grounding_passed=not any(item.code in {"CASE_GROUNDING_FAILED", "CASE_BUSINESS_CONTEXT_UNSUPPORTED"} for item in blockers),
        completeness_passed=completeness,
        evidence_rate=evidence_rate,
        blockers=blockers,
    )


def validate_legacy_executable(payload: dict[str, Any], contract: ApiContract) -> list[ReviewIssue]:
    """在创建新 Run 前校验历史执行定义；不修改历史文件和报告。"""

    issues: list[ReviewIssue] = []
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    normalized_path = re.sub(r"\$\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}", r"{\1}", str(request.get("path", "")))
    if request.get("method") != contract.method or normalized_path != contract.path:
        issues.append(_issue("LEGACY_VALIDATION_REQUIRED", "历史用例的 method/path 与当前契约不一致"))
    if contract.request_body and contract.request_body.required and request.get("body") is None:
        issues.append(_issue("CASE_REQUEST_INCOMPLETE", "契约要求请求体，但历史执行定义的 body 为空", field_path="request.body"))
    assertions = payload.get("assertions") if isinstance(payload.get("assertions"), list) else []
    observations = payload.get("observation_targets") if isinstance(payload.get("observation_targets"), list) else []
    if not assertions and not observations:
        issues.append(_issue("LEGACY_VALIDATION_REQUIRED", "历史执行定义没有断言或探索观察目标"))
    if any(item.code != "LEGACY_VALIDATION_REQUIRED" for item in issues) and not any(item.code == "LEGACY_VALIDATION_REQUIRED" for item in issues):
        issues.append(_issue("LEGACY_VALIDATION_REQUIRED", "历史用例需要使用融合内核重新生成"))
    return issues


def extract_template_variables(value: Any) -> set[str]:
    """提取 ${{name}} 变量，供执行定义完整性校验复用。"""

    return set(re.findall(r"\$\{\{([A-Za-z_][A-Za-z0-9_.-]*)\}\}", json.dumps(value, ensure_ascii=False, default=str)))
