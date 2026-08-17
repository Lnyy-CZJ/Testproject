"""Schema 校验。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from requirement_decomposition.models.schema import Requirement


class ValidationResult(BaseModel):
    """通用校验结果。"""

    passed: bool
    issues: list[dict] = []


def validate_requirement_schema(requirement: Requirement | dict[str, Any]) -> ValidationResult:
    """使用 Pydantic 校验 Requirement Schema。"""

    try:
        if isinstance(requirement, Requirement):
            Requirement.model_validate(requirement.model_dump(mode="json", by_alias=True))
        else:
            Requirement.model_validate(requirement)
    except ValidationError as exc:
        return ValidationResult(
            passed=False,
            issues=[
                {
                    "issue_type": "schema_invalid",
                    "field": ".".join(str(part) for part in error["loc"]),
                    "reason": error["msg"],
                }
                for error in exc.errors()
            ],
        )
    return ValidationResult(passed=True, issues=[])
