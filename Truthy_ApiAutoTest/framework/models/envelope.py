"""Gateway 统一请求信封与响应模型。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class CommContext(BaseModel):
    """Gateway 客户端公共上下文。

    功能说明:
        保存 Gateway 每次请求共用的设备、平台、区域与可选鉴权上下文。
    参数说明:
        device_id: 客户端持久设备 ID。
        其余字段为协议规定的平台、版本、区域与可选鉴权信息。
    返回值:
        模型实例可序列化到请求信封的 ``comm`` 字段。
    异常说明:
        必填字段缺失或类型错误时由 Pydantic 抛出校验异常。
    """

    model_config = ConfigDict(extra="allow")

    device_id: str
    auth_token: str | None = None
    client_request_id: str | None = None
    trace_id: str
    platform: str
    app_version: str
    locale: str
    timezone: str


class GatewayExecution(BaseModel):
    """Gateway 执行策略。

    功能说明:
        保存 Gateway 子请求执行模式和失败中止策略。
    参数说明:
        mode: 执行模式，阶段 1 默认顺序执行。
        stop_on_error: 子请求失败时是否中止，默认否。
    返回值:
        模型实例可作为请求信封的 ``execution``。
    异常说明:
        字段类型错误时由 Pydantic 抛出校验异常。
    """

    mode: str = "sequential"
    stop_on_error: bool = False


class GatewaySubRequest(BaseModel):
    """Gateway 信封中的单个业务请求。

    功能说明:
        表示 Gateway 信封中的一个业务方法调用。
    参数说明:
        id: 子请求 ID；service_name/method_name/params: 业务路由与参数。
    返回值:
        模型实例可序列化到 ``requests[]``。
    异常说明:
        必填字段缺失或类型错误时由 Pydantic 抛出校验异常。
    """

    id: str = "req_0"
    service_name: str
    method_name: str
    params: dict[str, Any]


class GatewayEnvelope(BaseModel):
    """可直接序列化发送的 Gateway 请求信封。

    功能说明:
        组合公共上下文、执行策略和业务子请求。
    参数说明:
        comm: 公共上下文；execution: 执行策略；requests: 业务子请求列表。
    返回值:
        模型实例可通过 ``model_dump`` 生成 HTTP JSON 请求体。
    异常说明:
        嵌套模型校验失败时由 Pydantic 抛出校验异常。
    """

    comm: CommContext
    execution: GatewayExecution = Field(default_factory=GatewayExecution)
    requests: list[GatewaySubRequest]


class GatewaySubResponse(BaseModel):
    """单个业务请求的响应。

    功能说明:
        保留双层断言所需字段，并允许服务端向前兼容地增加字段。
    参数说明:
        id/code/success/business_error_code/data: Gateway 子响应协议字段。
    返回值:
        供业务成功或错误断言使用的模型实例。
    异常说明:
        必需字段缺失或类型错误时由 Pydantic 抛出校验异常。
    """

    model_config = ConfigDict(extra="allow")

    id: str
    code: StrictInt
    message: str = ""
    success: StrictBool
    business_error_code: str = ""
    http_status: StrictInt | None = None
    data: Any = None


class GatewayResponse(BaseModel):
    """Gateway 顶层响应及客户端记录的 HTTP 状态。

    功能说明:
        保存 Gateway 顶层协议响应及客户端记录的 HTTP 状态。
    参数说明:
        code/message/request_id/trace_id/responses: Gateway 协议字段。
        http_status: 客户端记录的 HTTP 状态，不参与模型序列化。
    返回值:
        供统一双层断言使用的响应模型。
    异常说明:
        必需协议字段缺失或类型错误时由 Pydantic 抛出校验异常。
    """

    model_config = ConfigDict(extra="allow")

    code: StrictInt
    message: str = ""
    request_id: str
    trace_id: str
    responses: list[GatewaySubResponse]
    http_status: StrictInt | None = Field(default=None, exclude=True)


def build_gateway_envelope(
    *,
    service_name: str,
    method_name: str,
    params: dict[str, Any],
    device_id: str,
    platform: str,
    app_version: str,
    locale: str,
    timezone: str,
    auth_token: str | None = None,
    client_request_id: str | None = None,
    trace_id: str | None = None,
) -> GatewayEnvelope:
    """构造单业务请求 Gateway 信封。

    功能说明:
        为单个业务方法创建不含 ``user_id`` 的标准 Gateway 信封。
    参数说明:
        service_name/method_name/params: 业务服务、方法和参数。
        device_id/platform/app_version/locale/timezone: 公共客户端信息。
        auth_token/client_request_id/trace_id: 可选鉴权、幂等和追踪标识。
    返回值:
        不包含 ``user_id`` 的 :class:`GatewayEnvelope`。
    异常说明:
        参数类型或必填值不合法时由 Pydantic 抛出校验异常。
    """
    comm = CommContext(
        device_id=device_id,
        auth_token=auth_token,
        client_request_id=client_request_id,
        trace_id=trace_id or f"auto-{uuid4().hex[:8]}",
        platform=platform,
        app_version=app_version,
        locale=locale,
        timezone=timezone,
    )
    request = GatewaySubRequest(
        service_name=service_name,
        method_name=method_name,
        params=params,
    )
    return GatewayEnvelope(comm=comm, requests=[request])
