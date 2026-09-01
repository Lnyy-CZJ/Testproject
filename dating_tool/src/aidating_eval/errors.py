"""工具级异常。

异常类型只表达稳定类别；上层逻辑不得根据后端自由文本错误消息分支。
"""

from collections.abc import Iterable
from typing import Any, Self


class DatingEvalError(Exception):
    """工具能够识别和安全呈现的错误基类。

    Adapter 在解析 Create 响应时可能已经观察到 ``task_id``，但随后才发现状态或
    Schema 违反契约。异常会携带这些 ID，让 Runner 即使拿不到完整 ``TaskSnapshot``
    也能在 ``finally`` 中逐个删除，避免校验失败反而造成远端私密数据残留。
    """

    def add_cleanup_task_ids(self, *task_ids: str) -> Self:
        """追加需要清理的 Task ID，并保持首次观察顺序和向后兼容字段。"""

        existing = list(getattr(self, "task_ids_to_cleanup", ()))
        for task_id in task_ids:
            if isinstance(task_id, str) and task_id and task_id not in existing:
                existing.append(task_id)
        self.task_ids_to_cleanup = tuple(existing)
        self.task_id_to_cleanup = existing[0] if existing else None
        return self

    def prepend_cleanup_task_ids(self, *task_ids: str) -> Self:
        """把较早观察到的 ID 放到现有列表前，便于按创建顺序清理。"""

        existing = list(getattr(self, "task_ids_to_cleanup", ()))
        ordered: list[str] = []
        for task_id in (*task_ids, *existing):
            if isinstance(task_id, str) and task_id and task_id not in ordered:
                ordered.append(task_id)
        self.task_ids_to_cleanup = tuple(ordered)
        self.task_id_to_cleanup = ordered[0] if ordered else None
        return self


class ConfigurationError(DatingEvalError):
    """运行配置缺失、格式错误或违反安全约束。"""


class CaseValidationError(DatingEvalError):
    """Case 在任何外部请求之前未通过本地校验。"""


class TransportError(DatingEvalError):
    """HTTP、连接、超时或 JSON 解码失败。"""


class RunInterrupted(DatingEvalError):
    """运行收到停止信号，业务步骤应停止但清理仍须执行。"""


class ContractError(DatingEvalError):
    """服务响应信封、状态或结果 Schema 不符合冻结契约。"""


class BusinessError(DatingEvalError):
    """后端通过稳定 business_error_code 返回的业务错误。"""

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        data: dict[str, Any] | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
        task_id_to_cleanup: str | None = None,
        task_ids_to_cleanup: Iterable[str] = (),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.safe_message = message
        self.data = dict(data or {})
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.task_ids_to_cleanup: tuple[str, ...] = ()
        self.task_id_to_cleanup: str | None = None
        self.add_cleanup_task_ids(*task_ids_to_cleanup)
        if task_id_to_cleanup is not None:
            self.add_cleanup_task_ids(task_id_to_cleanup)
