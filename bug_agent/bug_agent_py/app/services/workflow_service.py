"""
缺陷状态机服务

功能说明:
    集中管理缺陷状态流转规则，避免各 API 分散判断。

设计约束:
    - 状态矩阵与 PRD 保持一致。
    - 每次状态变更必须写入 status_changes。
    - 非法流转返回 409，便于前端明确提示。
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.workflow import StatusChange


class DefectStatus(StrEnum):
    """缺陷状态枚举"""

    NEW = "new"
    PENDING_ASSIGN = "pending_assign"
    PENDING_ANALYSIS = "pending_analysis"
    ANALYZING = "analyzing"
    PENDING_FIX = "pending_fix"
    FIXING = "fixing"
    MANUAL_FIXING = "manual_fixing"
    PENDING_VERIFY = "pending_verify"
    FIXED = "fixed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    REOPENED = "reopened"


class WorkflowService:
    """缺陷状态机服务"""

    _TRANSITIONS: ClassVar[dict[DefectStatus, set[DefectStatus]]] = {
        DefectStatus.NEW: {DefectStatus.PENDING_ASSIGN},
        DefectStatus.PENDING_ASSIGN: {DefectStatus.PENDING_ANALYSIS},
        DefectStatus.PENDING_ANALYSIS: {DefectStatus.ANALYZING, DefectStatus.REJECTED},
        DefectStatus.ANALYZING: {DefectStatus.PENDING_FIX, DefectStatus.PENDING_ANALYSIS},
        DefectStatus.PENDING_FIX: {
            DefectStatus.FIXING,
            DefectStatus.MANUAL_FIXING,
            DefectStatus.PENDING_ANALYSIS,
            DefectStatus.REJECTED,
            DefectStatus.SUSPENDED,
        },
        DefectStatus.FIXING: {DefectStatus.PENDING_VERIFY},
        DefectStatus.MANUAL_FIXING: {DefectStatus.PENDING_VERIFY, DefectStatus.PENDING_FIX},
        DefectStatus.PENDING_VERIFY: {DefectStatus.FIXED, DefectStatus.PENDING_FIX},
        DefectStatus.FIXED: {DefectStatus.COMPLETED},
        DefectStatus.REJECTED: {DefectStatus.REOPENED, DefectStatus.PENDING_ANALYSIS},
        DefectStatus.REOPENED: {
            DefectStatus.PENDING_ANALYSIS,
            DefectStatus.ANALYZING,
            DefectStatus.PENDING_FIX,
            DefectStatus.REJECTED,
        },
        DefectStatus.SUSPENDED: {DefectStatus.PENDING_FIX},
    }

    _TERMINAL: ClassVar[set[DefectStatus]] = {DefectStatus.COMPLETED}

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _parse_status(value: str) -> DefectStatus | None:
        """
        安全解析状态字符串。

        返回值:
            DefectStatus | None: 合法状态返回枚举；未知状态返回 None，
            由调用方按非法流转处理，避免 API 暴露 500。
        """
        try:
            return DefectStatus(value)
        except ValueError:
            return None

    @classmethod
    def valid_transitions(cls, current: str) -> list[str]:
        """
        获取当前状态可流转目标。

        参数说明:
            current: 当前状态字符串。

        返回值:
            list[str]: 可流转目标状态列表。
        """
        status_value = cls._parse_status(current)
        if status_value is None:
            return []
        return sorted(item.value for item in cls._TRANSITIONS.get(status_value, set()))

    @classmethod
    def is_valid_transition(cls, from_status: str, to_status: str) -> bool:
        """判断状态流转是否合法"""
        from_value = cls._parse_status(from_status)
        to_value = cls._parse_status(to_status)
        if from_value is None or to_value is None:
            return False
        return to_value in cls._TRANSITIONS.get(from_value, set())

    async def transition(
        self,
        defect: Defect,
        to_status: str,
        operator_id: int,
        comment: str | None = None,
        allow_same: bool = False,
    ) -> Defect:
        """
        执行缺陷状态流转。

        参数说明:
            defect: 缺陷 ORM 对象。
            to_status: 目标状态。
            operator_id: 操作人 ID。
            comment: 流转备注。
            allow_same: 是否允许同状态刷新，默认不允许。

        返回值:
            Defect: 更新后的缺陷对象。

        异常说明:
            HTTPException(409): 状态流转不合法。
        """
        from_status = defect.status
        if from_status == to_status and allow_same:
            return defect
        if not self.is_valid_transition(from_status, to_status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"状态不能从 {from_status} 流转到 {to_status}",
            )

        defect.status = to_status
        self.db.add(
            StatusChange(
                defect_id=defect.id,
                from_status=from_status,
                to_status=to_status,
                operator_id=operator_id,
                comment=comment,
            )
        )
        await self.db.flush()
        await self.db.refresh(defect)
        return defect
