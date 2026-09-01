"""共用 Runner 依赖的最小 Adapter 端口。"""

from collections.abc import Mapping
from typing import Any, Protocol

from aidating_eval.domain import (
    CaseDefinition,
    CleanupResult,
    DoctorCheck,
    PollPolicy,
    PreparedCase,
    RunContext,
    TaskSnapshot,
)


class TaskFlowAdapter(Protocol):
    """隐藏公开与内部 Wire Schema 差异的任务生命周期接口。"""

    @property
    def poll_policy(self) -> PollPolicy: ...

    def doctor(self) -> list[DoctorCheck]: ...

    def prepare_run(self, context: RunContext) -> None: ...

    def prepare_case(
        self, case: CaseDefinition, context: RunContext
    ) -> PreparedCase: ...

    def create_task(
        self,
        case: CaseDefinition,
        prepared: PreparedCase,
        context: RunContext,
    ) -> TaskSnapshot: ...

    def get_task(self, task_id: str, context: RunContext) -> TaskSnapshot: ...

    def get_result(
        self,
        task_id: str,
        case: CaseDefinition,
        context: RunContext,
    ) -> Mapping[str, Any]: ...

    def get_diagnostics(
        self,
        task_id: str,
        case: CaseDefinition,
        context: RunContext,
    ) -> Mapping[str, Any] | None: ...

    def delete_task(self, task_id: str, context: RunContext) -> CleanupResult: ...
