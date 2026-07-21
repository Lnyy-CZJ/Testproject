"""ReportService 报告补图与反馈请求参数封装。"""

from __future__ import annotations

from typing import Any

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class ReportService:
    """只封装文档公开的 task 级报告扩展能力，不暴露内部 report_id。

    功能说明:
        封装公开的 task 级报告补图与反馈能力，不暴露内部 report_id。
    参数说明:
        client: 统一 Gateway 客户端或实现相同 ``invoke`` 协议的离线替身。
    返回值:
        公共方法返回未吞掉业务状态的 :class:`GatewayResponse`。
    异常说明:
        Gateway 网络、HTTP 和解析异常原样传播；业务参数不在 Service 层拦截。
    """

    SERVICE_NAME = "tool.people_insight.ReportService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def add_report_photos(
        self,
        *,
        access_token: str,
        client_request_id: str,
        task_id: str,
        media_asset_ids: list[str],
        client_context: dict[str, Any] | None = None,
    ) -> GatewayResponse:
        """为已完成任务补充上传完成的媒体并创建刷新任务。

        功能说明:
            为已完成任务补充上传完成的媒体并创建刷新任务。
        参数说明:
            client_request_id: 调用方稳定幂等 ID；task_id: 来源搜索任务；
            media_asset_ids: 当前用户媒体 ID；client_context: 可选客户端上下文。
        返回值:
            文档规定包含 refresh_task_id/source_task_id/media_asset_ids 的响应。
        异常说明:
            不同步等待刷新任务；Gateway 异常原样传播。
        """
        params: dict[str, Any] = {
            "client_request_id": client_request_id,
            "task_id": task_id,
            "media_asset_ids": media_asset_ids,
        }
        if client_context is not None:
            params["client_context"] = client_context
        return self._client.invoke(
            self.SERVICE_NAME,
            "AddReportPhotos",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def submit_feedback(
        self,
        *,
        access_token: str,
        client_request_id: str,
        task_id: str,
        feedback_type: str,
        feedback_message: str | None = None,
        selected_evidence_ids: list[str] | None = None,
        additional_details: list[dict[str, Any]] | None = None,
        screenshot_media_asset_id: str | None = None,
        client_context: dict[str, Any] | None = None,
    ) -> GatewayResponse:
        """以调用方幂等 ID 提交 task 级搜索结果反馈。

        功能说明:
            以稳定幂等 ID 提交 task 级搜索结果反馈。
        参数说明:
            task_id/feedback_type 为文档必填字段；其余字段仅在调用方提供时发送，
            显式空值原样保留；客户端不提交 report_id 或完整报告快照。
        返回值:
            包含 feedback_id、submitted 状态和创建时间的标准响应。
        异常说明:
            Service 不生成反馈 ID；Gateway 异常和业务失败原样传播。
        """
        params: dict[str, Any] = {
            "client_request_id": client_request_id,
            "task_id": task_id,
            "feedback_type": feedback_type,
        }
        optional = {
            "feedback_message": feedback_message,
            "selected_evidence_ids": selected_evidence_ids,
            "additional_details": additional_details,
            "screenshot_media_asset_id": screenshot_media_asset_id,
            "client_context": client_context,
        }
        params.update({key: value for key, value in optional.items() if value is not None})
        return self._client.invoke(
            self.SERVICE_NAME,
            "SubmitFeedback",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )
