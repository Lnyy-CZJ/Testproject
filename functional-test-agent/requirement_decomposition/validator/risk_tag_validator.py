"""风险标签枚举校验。"""

from __future__ import annotations

from requirement_decomposition.models.schema import Requirement
from requirement_decomposition.validator.schema_validator import ValidationResult

ALLOWED_RISK_TAGS = {
    "输入校验",
    "权限",
    "状态流转",
    "金额",
    "数据一致性",
    "并发",
    "幂等",
    "异常流程",
    "接口",
    "兼容性",
    "性能",
    "安全",
}


def validate_risk_tags(requirement: Requirement) -> ValidationResult:
    """清理枚举外 risk_tags，并返回对应 issue。"""

    valid_tags: list[str] = []
    issues: list[dict] = []
    for tag in requirement.test_design_suggestions.risk_tags:
        if tag in ALLOWED_RISK_TAGS:
            valid_tags.append(tag)
            continue
        issues.append(
            {
                "issue_type": "risk_tag_invalid",
                "requirement_id": requirement.requirement_id,
                "field": "test_design_suggestions.risk_tags",
                "value": tag,
                "reason": "risk_tags 必须使用 PRD 固定枚举",
            }
        )
    requirement.test_design_suggestions.risk_tags = valid_tags
    return ValidationResult(passed=not issues, issues=issues)
