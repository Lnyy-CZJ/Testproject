"""API 契约 Evidence、Grounding 和 confirmed_candidate 硬门禁。"""

from __future__ import annotations

from services.api_agent.models import ApiContract, ContractQualityReport, ReviewIssue


def apply_quality_gate(contract: ApiContract, *, minimum_score: float = 0.90) -> ApiContract:
    """计算可解释质量结果并设置候选状态。

    质量分只用于展示；任何硬阻断项都会使契约保持 draft。
    """

    evidence_paths = {
        item.field_path for item in contract.field_evidence if item.evidence_type == "explicit"
    }
    critical = {"method", "path"}
    critical.update(f"parameters[{index}].name" for index, _ in enumerate(contract.parameters))
    critical.update(f"parameters[{index}].location" for index, _ in enumerate(contract.parameters))
    critical.update(f"parameters[{index}].required" for index, _ in enumerate(contract.parameters))
    critical.update(f"responses[{index}].status_code" for index, _ in enumerate(contract.responses))
    missing = sorted(critical - evidence_paths)
    blockers: list[ReviewIssue] = []
    if missing:
        blockers.append(ReviewIssue(
            code="MISSING_CRITICAL_EVIDENCE", field_path="field_evidence",
            message=f"关键字段缺少证据: {', '.join(missing)}", severity="blocker",
        ))
    active = {"open", "reopened"}
    blockers.extend(item for item in contract.conflict_items if item.severity == "blocker" and item.status in active)
    blockers.extend(item for item in contract.unresolved if item.severity == "blocker" and item.status in active)
    blockers.extend(item for item in contract.ambiguity_notes if item.severity == "blocker" and item.status in active)
    unsupported = sum(
        1 for item in contract.field_evidence
        if item.evidence_type == "inferred" and item.field_path not in evidence_paths
    )
    if unsupported:
        blockers.append(ReviewIssue(
            code="UNSUPPORTED_FACTS", field_path="field_evidence",
            message="存在无充分依据的契约事实", severity="blocker",
        ))
    evidence_rate = 1.0 if not critical else round(len(critical & evidence_paths) / len(critical), 4)
    completeness = sum(bool(value) for value in (contract.method, contract.path, contract.name)) / 3
    conflict_rate = 1.0 if not any(item.status in active for item in contract.conflict_items) else 0.0
    schema_rate = 1.0
    score = round(
        completeness * 0.25 + evidence_rate * 0.25 + schema_rate * 0.20
        + (1.0 if unsupported == 0 else 0.0) * 0.15 + conflict_rate * 0.10 + 0.05,
        4,
    )
    passed = not blockers and score >= minimum_score
    contract.quality_report = ContractQualityReport(
        quality_score=score,
        hard_gate_passed=passed,
        evidence_rate=evidence_rate,
        grounding_passed=unsupported == 0,
        unsupported_facts=unsupported,
        blockers=blockers,
    )
    contract.status = "confirmed_candidate" if passed else "draft"
    return contract
