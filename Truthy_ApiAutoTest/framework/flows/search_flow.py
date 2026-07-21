"""二次精炼与报告补图刷新任务的安全生产协调器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from framework.models.envelope import GatewayResponse
from framework.waiters.task_waiter import TaskWaitResult, TaskWaiter
from services.report_service import ReportService
from services.search_service import SearchService


class SearchFlowError(RuntimeError):
    """搜索扩展流程安全异常。

    功能说明:
        表示阶段4流程、血缘或终态契约异常，消息不含 token、ID 值或业务载荷。
    参数说明:
        继承 ``RuntimeError`` 的安全错误消息参数。
    返回值:
        无；该类型仅用于异常传播。
    异常说明:
        本类型自身不额外抛出异常。
    """


@dataclass(frozen=True, slots=True)
class SearchFlowResult:
    """精炼或补图刷新流程的不可变结果摘要。

    功能说明:
        保存精炼或补图刷新流程的不可变结果摘要。
    参数说明:
        task_id/source_task_id/status: 新任务血缘和终态；candidates: 成功终态的
        候选快照，其他允许终态为空；feedback_id/media_asset_ids: 对应流程回显。
    返回值:
        实例作为扩展搜索流程的安全结果。
    异常说明:
        数据类构造不主动校验，字段正确性由流程协调器保证。
    """

    task_id: str
    source_task_id: str
    status: str
    candidates: tuple[dict[str, Any], ...]
    feedback_id: str | None = None
    media_asset_ids: tuple[str, ...] = ()


class SearchFlow:
    """严格执行 Refine/Add → wait → 条件读取候选的阶段4流程。

    功能说明:
        严格执行 Refine/Add → wait → 条件读取候选的扩展流程。
    参数说明:
        search_service/report_service: 已有 Service 封装；task_waiter: 可选注入的
        等待器，默认基于同一 SearchService 构造 20 秒等待器。
    返回值:
        两个公共流程均返回 :class:`SearchFlowResult`。
    异常说明:
        调用、业务响应、任务血缘、来源稳定字段或终态不符合契约时抛中文
        :class:`SearchFlowError`，不暴露 token、外部异常消息或业务数据。
    """

    _SOURCE_STABLE_FIELDS = (
        "task_id",
        "status",
        "user_id",
        "create_time",
        "update_time",
        "error_code",
        "no_result_reason",
    )

    def __init__(
        self,
        search_service: SearchService,
        report_service: ReportService,
        *,
        task_waiter: TaskWaiter | None = None,
    ) -> None:
        self._search = search_service
        self._report = report_service
        self._waiter = task_waiter or TaskWaiter(search_service)

    def refine_and_collect(
        self,
        *,
        access_token: str,
        client_request_id: str,
        source_task_id: str,
        additional_details: list[dict[str, Any]],
        feedback_type: str,
        feedback_message: str,
    ) -> SearchFlowResult:
        """精炼来源任务，复核来源稳定性并按新任务终态收集候选。

        功能说明:
            精炼来源任务，复核来源稳定性并按新任务终态收集候选。
        参数说明:
            参数与 ``SearchService.refine_task`` 一致；所有 ID 均由调用方提供并
            原样传递，协调器不接收或生成 report_id。
        返回值:
            SUCCEEDED 含候选；NO_RESULT/合法 FAILED 返回空候选。
        异常说明:
            Refine 失败立即短路；新任务血缘错误、来源稳定字段变化、FAILED 缺少
            error_code 或候选响应异常时抛 :class:`SearchFlowError`。
        """
        source_before = self._call_data(
            "来源 GetTask",
            lambda: self._search.get_task(
                access_token=access_token, task_id=source_task_id
            ),
        )
        if source_before.get("task_id") != source_task_id:
            raise SearchFlowError("来源任务快照 task_id 不匹配")
        refined = self._call_data(
            "RefineTask",
            lambda: self._search.refine_task(
                access_token=access_token,
                client_request_id=client_request_id,
                source_task_id=source_task_id,
                additional_details=additional_details,
                feedback_type=feedback_type,
                feedback_message=feedback_message,
            ),
        )
        task_id = self._validated_lineage(
            refined,
            new_task_field="task_id",
            source_task_id=source_task_id,
        )
        feedback_id = refined.get("feedback_id")
        if not isinstance(feedback_id, str) or not feedback_id:
            raise SearchFlowError("RefineTask 缺少非空 feedback_id")
        terminal = self._wait(access_token=access_token, task_id=task_id)
        source_after = self._call_data(
            "来源复核 GetTask",
            lambda: self._search.get_task(
                access_token=access_token, task_id=source_task_id
            ),
        )
        self._assert_source_stable(source_before, source_after)
        return self._collect_terminal(
            access_token=access_token,
            task_id=task_id,
            source_task_id=source_task_id,
            terminal=terminal,
            feedback_id=feedback_id,
        )

    def add_photos_and_collect(
        self,
        *,
        access_token: str,
        client_request_id: str,
        source_task_id: str,
        media_asset_ids: list[str],
        client_context: dict[str, Any] | None = None,
    ) -> SearchFlowResult:
        """补充已上传媒体，等待刷新任务并按终态收集候选。

        功能说明:
            补充已上传媒体，等待刷新任务并按终态收集候选。
        参数说明:
            参数映射到 ``ReportService.add_report_photos``；source_task_id 作为文档
            ``task_id`` 原样发送，协调器不处理上传和内部 report_id。
        返回值:
            SUCCEEDED 含刷新候选；NO_RESULT/合法 FAILED 返回空候选。
        异常说明:
            Add 业务失败、血缘异常或 FAILED 缺少 error_code 时立即安全短路。
        """
        added = self._call_data(
            "AddReportPhotos",
            lambda: self._report.add_report_photos(
                access_token=access_token,
                client_request_id=client_request_id,
                task_id=source_task_id,
                media_asset_ids=media_asset_ids,
                client_context=client_context,
            ),
        )
        task_id = self._validated_lineage(
            added,
            new_task_field="refresh_task_id",
            source_task_id=source_task_id,
        )
        echoed_media = added.get("media_asset_ids")
        if not isinstance(echoed_media, list) or not all(
            isinstance(item, str) and item for item in echoed_media
        ):
            raise SearchFlowError("AddReportPhotos 缺少有效 media_asset_ids")
        if echoed_media != media_asset_ids:
            raise SearchFlowError("AddReportPhotos media_asset_ids 与请求不一致")
        terminal = self._wait(access_token=access_token, task_id=task_id)
        return self._collect_terminal(
            access_token=access_token,
            task_id=task_id,
            source_task_id=source_task_id,
            terminal=terminal,
            media_asset_ids=tuple(echoed_media),
        )

    @staticmethod
    def _require_success_data(
        response: GatewayResponse, *, stage: str
    ) -> dict[str, Any]:
        """读取最小成功 data，业务 message 和载荷不进入异常。"""
        if response.http_status is None or not 200 <= response.http_status < 300:
            raise SearchFlowError(f"{stage} HTTP 异常")
        item = next((item for item in response.responses if item.id == "req_0"), None)
        if item is None:
            raise SearchFlowError(f"{stage} 缺少业务子响应")
        if item.success is not True or item.code != 0:
            raise SearchFlowError(f"{stage} 业务失败")
        if not isinstance(item.data, dict):
            raise SearchFlowError(f"{stage} data 必须是对象")
        return dict(item.data)

    def _call_data(
        self, stage: str, call: Callable[[], GatewayResponse]
    ) -> dict[str, Any]:
        """安全包装外部 Service 调用，再验证标准成功 data。"""
        try:
            response = call()
        except Exception as exc:  # noqa: BLE001 - 外部异常消息可能含 token
            raise SearchFlowError(
                f"{stage} 调用异常: {type(exc).__name__}"
            ) from None
        return self._require_success_data(response, stage=stage)

    @staticmethod
    def _validated_lineage(
        data: dict[str, Any], *, new_task_field: str, source_task_id: str
    ) -> str:
        """校验新任务与来源血缘，不把实际 ID 写入异常。"""
        task_id = data.get(new_task_field)
        if not isinstance(task_id, str) or not task_id or task_id == source_task_id:
            raise SearchFlowError("流程未返回不同于来源的新任务 ID")
        if data.get("source_task_id") != source_task_id:
            raise SearchFlowError("流程返回的 source_task_id 不匹配")
        return task_id

    def _wait(self, *, access_token: str, task_id: str) -> TaskWaitResult:
        """安全包装任务等待器，并校验终态快照仍属于目标新任务。"""
        try:
            terminal = self._waiter.wait(
                access_token=access_token, task_id=task_id
            )
        except Exception as exc:  # noqa: BLE001 - 注入等待器异常必须安全包装
            raise SearchFlowError(
                f"新任务等待异常: {type(exc).__name__}"
            ) from None
        if terminal.data.get("task_id") != task_id:
            raise SearchFlowError("新任务终态快照 task_id 不匹配")
        return terminal

    def _assert_source_stable(
        self, before: dict[str, Any], after: dict[str, Any]
    ) -> None:
        """比较来源任务文档稳定字段，字段增删也视为不一致。"""
        missing = object()
        for field in self._SOURCE_STABLE_FIELDS:
            if before.get(field, missing) != after.get(field, missing):
                raise SearchFlowError("来源任务稳定字段发生变化")

    def _collect_terminal(
        self,
        *,
        access_token: str,
        task_id: str,
        source_task_id: str,
        terminal: TaskWaitResult,
        feedback_id: str | None = None,
        media_asset_ids: tuple[str, ...] = (),
    ) -> SearchFlowResult:
        """只在 SUCCEEDED 查询候选，其他允许终态执行契约化短路。"""
        if terminal.status == "FAILED":
            error_code = terminal.data.get("error_code")
            if not isinstance(error_code, str) or not error_code:
                raise SearchFlowError("FAILED 终态缺少非空 error_code")
            candidates: tuple[dict[str, Any], ...] = ()
        elif terminal.status == "NO_RESULT":
            candidates = ()
        elif terminal.status == "SUCCEEDED":
            data = self._call_data(
                "ListTaskCandidates",
                lambda: self._search.list_task_candidates(
                    access_token=access_token, task_id=task_id
                ),
            )
            if data.get("task_id") != task_id:
                raise SearchFlowError("候选响应 task_id 不匹配")
            items = data.get("items")
            if not isinstance(items, list) or not all(
                isinstance(item, dict) for item in items
            ):
                raise SearchFlowError("候选响应 items 必须是对象数组")
            candidates = tuple(dict(item) for item in items)
        else:
            raise SearchFlowError("等待器返回非允许终态")
        return SearchFlowResult(
            task_id=task_id,
            source_task_id=source_task_id,
            status=terminal.status,
            candidates=candidates,
            feedback_id=feedback_id,
            media_asset_ids=media_asset_ids,
        )
