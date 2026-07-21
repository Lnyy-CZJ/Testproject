"""异步业务等待器。"""

from framework.waiters.entitlement_waiter import (
    EntitlementWaitError,
    EntitlementWaitResult,
    wait_entitlement_allow,
)
from framework.waiters.task_waiter import TaskWaitError, TaskWaitResult, TaskWaiter

__all__ = [
    "EntitlementWaitError",
    "EntitlementWaitResult",
    "TaskWaitError",
    "TaskWaitResult",
    "TaskWaiter",
    "wait_entitlement_allow",
]
