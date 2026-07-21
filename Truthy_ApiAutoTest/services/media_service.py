"""MediaService 三段式上传协议及 COS PUT 编排。"""

from __future__ import annotations

from typing import Any

from framework.assertions.gateway_assert import assert_business_success
from framework.client.cos_client import CosClient
from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class MediaService:
    """封装媒体配置、上传准备、完成确认和可选的一站式编排。

    功能说明:
        封装媒体配置、上传准备、COS PUT、完成确认和一站式编排。
    参数说明:
        client: 统一 Gateway 客户端；cos_client: 仅执行预签名 PUT 的客户端，调用
        :meth:`upload_media` 时必须提供，单独调用三个 Gateway 方法时可省略。
    返回值:
        三个协议方法及 ``upload_media`` 均返回标准 Gateway 响应。
    异常说明:
        Gateway/COS 异常原样传播；配置或服务端回显与待上传内容不一致时抛出
        ``ValueError``，且不会继续错误阶段。
    """

    SERVICE_NAME = "tool.people_insight.MediaService"

    def __init__(self, client: GatewayClient, *, cos_client: CosClient | None = None) -> None:
        self._client = client
        self._cos_client = cos_client

    def get_media_upload_config(self, *, access_token: str) -> GatewayResponse:
        """获取允许的图片类型、大小和上传有效期配置。

        功能说明:
            获取允许的图片类型、大小和上传有效期配置。
        参数说明:
            access_token: 当前会话最新 access token。
        返回值:
            媒体上传配置的标准 Gateway 响应。
        异常说明:
            Gateway 网络、HTTP、预算和响应解析异常原样传播。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetMediaUploadConfig",
            {},
            auth_token=access_token,
        )

    def prepare_media_upload(
        self,
        *,
        access_token: str,
        client_request_id: str,
        content_type: str,
        size_bytes: int,
    ) -> GatewayResponse:
        """以稳定幂等 ID 准备上传并获取短期 COS URL 与服务端请求头。

        功能说明:
            以稳定幂等 ID 获取短期 COS URL 与服务端请求头。
        参数说明:
            access_token: 最新会话 token；client_request_id: 调用方稳定幂等 ID；
            content_type/size_bytes: 待上传内容的 MIME 类型与严格字节数。
        返回值:
            包含资产 ID、预签名 URL 和请求头的标准 Gateway 响应。
        异常说明:
            本方法不在本地改写参数，Gateway 异常原样传播。
        """
        params = {
            "client_request_id": client_request_id,
            "content_type": content_type,
            "size_bytes": size_bytes,
        }
        return self._client.invoke(
            self.SERVICE_NAME,
            "PrepareMediaUpload",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def complete_media_upload(
        self, *, access_token: str, media_asset_id: str
    ) -> GatewayResponse:
        """确认指定媒体资产已经完成二进制上传。

        功能说明:
            确认指定媒体资产已经完成二进制上传。
        参数说明:
            access_token: 最新会话 token；media_asset_id: Prepare 返回的资产 ID。
        返回值:
            服务端确认后的标准 Gateway 响应。
        异常说明:
            Gateway 网络、HTTP 和响应解析异常原样传播。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "CompleteMediaUpload",
            {"media_asset_id": media_asset_id},
            auth_token=access_token,
        )

    def upload_media(
        self,
        *,
        access_token: str,
        client_request_id: str,
        content_type: str,
        content: bytes,
    ) -> GatewayResponse:
        """严格按 Config → Prepare → COS PUT → Complete 上传图片。

        功能说明:
            严格执行 Config → Prepare → COS PUT → Complete 上传流程。
        参数说明:
            access_token: 最新会话 token；client_request_id: 调用方生成且保持稳定
            的上传幂等 ID；content_type/content: 待上传图片 MIME 类型与二进制体。
        返回值:
            已验证 ``status=uploaded``、资产 ID、类型和大小一致的 Complete 响应。
        异常说明:
            未配置 COS 客户端、类型/大小超限、Prepare 状态或回显不一致、Complete
            资产/状态不一致时抛出 ``ValueError``；图片内容从不进入诊断。
        """
        if self._cos_client is None:
            raise ValueError("upload_media 必须配置 cos_client")
        size_bytes = len(content)
        config_response = self.get_media_upload_config(access_token=access_token)
        config = self._require_data_object(config_response, stage="Config")
        self._validate_config(config)
        if not self._is_positive_int(size_bytes):
            raise ValueError("上传 size_bytes 必须是正整数")
        if content_type not in config["allowed_content_types"]:
            raise ValueError(f"content_type 不在服务端允许列表: {content_type}")
        if size_bytes > config["max_size_bytes"]:
            raise ValueError(
                f"size 超过服务端 max_size_bytes: {size_bytes}>{config['max_size_bytes']}"
            )

        prepare_response = self.prepare_media_upload(
            access_token=access_token,
            client_request_id=client_request_id,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        prepare = self._require_data_object(prepare_response, stage="Prepare")
        self._validate_prepare(prepare, content_type=content_type, size_bytes=size_bytes)
        media_asset_id = prepare["media_asset_id"]
        self._cos_client.put(
            prepare["upload_url"],
            upload_headers=prepare["upload_headers"],
            content=content,
        )

        complete_response = self.complete_media_upload(
            access_token=access_token, media_asset_id=media_asset_id
        )
        complete = self._require_data_object(complete_response, stage="Complete")
        self._validate_complete(complete, prepare=prepare)
        return complete_response

    @staticmethod
    def _require_data_object(
        response: GatewayResponse, *, stage: str
    ) -> dict[str, Any]:
        """断言 Gateway 业务成功，并要求阶段 data 为对象。

        参数说明:
            response: 当前阶段 Gateway 响应；stage: Config/Prepare/Complete 诊断名。
        返回值:
            严格为字典的业务 data。
        异常说明:
            Gateway 业务失败仍由统一断言报告；data 非对象时抛出 ``ValueError``。
        """
        data = assert_business_success(response)
        if not isinstance(data, dict):
            raise ValueError(f"{stage} data 必须是对象")
        return data

    @staticmethod
    def _require_fields(data: dict[str, Any], *, stage: str, fields: set[str]) -> None:
        """在读取字段前报告缺失键，避免泄露整个服务端 data。"""
        missing = fields.difference(data)
        if missing:
            raise ValueError(f"{stage} data 缺少字段: {sorted(missing)}")

    @staticmethod
    def _is_positive_int(value: Any) -> bool:
        """仅接受真正的正整数，明确排除 Python 的 bool 整数子类。"""
        return type(value) is int and value > 0

    @staticmethod
    def _is_non_empty_str(value: Any) -> bool:
        """仅接受含非空白内容的原生字符串。"""
        return type(value) is str and bool(value.strip())

    @classmethod
    def _validate_config(cls, config: dict[str, Any]) -> None:
        """严格验证上传类型列表和正整数最大字节数。"""
        cls._require_fields(
            config,
            stage="Config",
            fields={"allowed_content_types", "max_size_bytes"},
        )
        allowed = config["allowed_content_types"]
        if not isinstance(allowed, list) or not all(
            cls._is_non_empty_str(item) for item in allowed
        ):
            raise ValueError("Config allowed_content_types 必须是 list[str]")
        if not cls._is_positive_int(config["max_size_bytes"]):
            raise ValueError("Config max_size_bytes 必须是非 bool 正整数")

    @classmethod
    def _validate_prepare(
        cls, prepare: dict[str, Any], *, content_type: str, size_bytes: int
    ) -> None:
        """验证 Prepare 回显、方法、状态和大小上限后才允许发送图片。"""
        cls._require_fields(
            prepare,
            stage="Prepare",
            fields={
                "media_asset_id",
                "status",
                "content_type",
                "size_bytes",
                "upload_url",
                "upload_method",
                "upload_headers",
                "max_size_bytes",
            },
        )
        for field in (
            "media_asset_id",
            "status",
            "content_type",
            "upload_url",
            "upload_method",
        ):
            if not cls._is_non_empty_str(prepare[field]):
                raise ValueError(f"Prepare {field} 必须是非空字符串")
        for field in ("size_bytes", "max_size_bytes"):
            if not cls._is_positive_int(prepare[field]):
                raise ValueError(f"Prepare {field} 必须是非 bool 正整数")
        headers = prepare["upload_headers"]
        if not isinstance(headers, dict) or not all(
            type(key) is str and type(value) is str
            for key, value in headers.items()
        ):
            raise ValueError("Prepare upload_headers 必须是 dict[str,str]")
        if prepare["status"] != "pending":
            raise ValueError(f"Prepare status 非 pending: {prepare['status']}")
        if prepare["upload_method"] != "PUT":
            raise ValueError(f"Prepare upload_method 非 PUT: {prepare['upload_method']}")
        if prepare["content_type"] != content_type:
            raise ValueError("Prepare content_type 与请求不一致")
        if prepare["size_bytes"] != size_bytes:
            raise ValueError("Prepare size_bytes 与请求不一致")
        if size_bytes > prepare["max_size_bytes"]:
            raise ValueError("size 超过 Prepare max_size_bytes")
        if not prepare["media_asset_id"]:
            raise ValueError("Prepare media_asset_id 不能为空")

    @classmethod
    def _validate_complete(
        cls, complete: dict[str, Any], *, prepare: dict[str, Any]
    ) -> None:
        """严格验证 Complete 字段类型并与已上传的 Prepare 数据逐项一致。"""
        cls._require_fields(
            complete,
            stage="Complete",
            fields={"media_asset_id", "status", "content_type", "size_bytes"},
        )
        for field in ("media_asset_id", "status", "content_type"):
            if not cls._is_non_empty_str(complete[field]):
                raise ValueError(f"Complete {field} 必须是非空字符串")
        if not cls._is_positive_int(complete["size_bytes"]):
            raise ValueError("Complete size_bytes 必须是非 bool 正整数")
        if complete["media_asset_id"] != prepare["media_asset_id"]:
            raise ValueError("Complete media_asset_id 与 Prepare 不一致")
        if complete["status"] != "uploaded":
            raise ValueError(f"Complete status 非 uploaded: {complete['status']}")
        if complete["content_type"] != prepare["content_type"]:
            raise ValueError("Complete content_type 与 Prepare 不一致")
        if complete["size_bytes"] != prepare["size_bytes"]:
            raise ValueError("Complete size_bytes 与 Prepare 不一致")
