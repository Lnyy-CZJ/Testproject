"""ProfileFeedbackService 通用产品反馈请求参数封装。"""

from __future__ import annotations

from typing import Any

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class ProfileFeedbackService:
    """按 3.0 文档委托个人中心或通用入口反馈接口。

    功能说明:
        按 3.0 文档封装个人中心或通用入口反馈参数。
    参数说明:
        client: 统一 Gateway 客户端或实现相同 ``invoke`` 协议的离线替身。
    返回值:
        :meth:`submit_profile_feedback` 返回标准 Gateway 响应。
    异常说明:
        Gateway 调用及响应解析异常原样传播，不在本地替代服务端参数校验。
    """

    SERVICE_NAME = "tool.people_insight.ProfileFeedbackService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def submit_profile_feedback(
        self,
        *,
        access_token: str,
        client_request_id: str,
        feedback_message: str,
        feedback_type: str | None = None,
        contact: str | None = None,
        media_asset_ids: list[str] | None = None,
        client_context: dict[str, Any] | None = None,
    ) -> GatewayResponse:
        """以稳定幂等 ID 提交通用产品反馈和可选图片。

        功能说明:
            以稳定幂等 ID 提交通用产品反馈和可选图片。
        参数说明:
            feedback_message 为文档必填字段；feedback_type/contact/media_asset_ids/
            client_context 仅在调用方提供时发送，显式空值原样保留。
        返回值:
            包含反馈 ID、submitted 状态和创建时间的标准响应。
        异常说明:
            不生成反馈 ID、不上传媒体；Gateway 异常与业务失败原样传播。
        """
        params: dict[str, Any] = {
            "client_request_id": client_request_id,
            "feedback_message": feedback_message,
        }
        optional = {
            "feedback_type": feedback_type,
            "contact": contact,
            "media_asset_ids": media_asset_ids,
            "client_context": client_context,
        }
        params.update({key: value for key, value in optional.items() if value is not None})
        return self._client.invoke(
            self.SERVICE_NAME,
            "SubmitProfileFeedback",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )
