"""IdentityService 身份与会话参数封装。"""

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class IdentityService:
    """封装身份接口且只委托统一 Gateway 客户端。

    功能说明:
        形成客户端接口文档 3.0 规定的 Identity 请求形状；匿名创建与刷新显式
        禁用环境默认鉴权，登录态查询显式使用调用方提供的最新 access token。
    参数说明:
        client: 统一 :class:`GatewayClient` 或实现相同 ``invoke`` 协议的测试替身。
    返回值:
        公共方法返回标准 :class:`GatewayResponse`。
    异常说明:
        Gateway 网络、HTTP、参数和响应解析异常原样向调用方传播。
    """

    SERVICE_NAME = "tool.identity.IdentityService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def create_anonymous_session(
        self, *, consent_policy_version: str, client_request_id: str
    ) -> GatewayResponse:
        """创建匿名会话。

        功能说明:
            以稳定 Gateway 幂等 ID 创建匿名会话。
        参数说明:
            consent_policy_version: 客户端已同意的隐私政策版本；
            client_request_id: 调用方为本次创建流程生成的稳定幂等 ID，只写入
            Gateway ``comm``，不写入文档未声明该字段的业务 ``params``。
        返回值:
            包含用户与会话 token 数据的 Gateway 标准响应。
        异常说明:
            Gateway 调用和响应解析异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "CreateAnonymousSession",
            {"consent_policy_version": consent_policy_version},
            auth_token=None,
            client_request_id=client_request_id,
        )

    def refresh_session(self, *, refresh_token: str) -> GatewayResponse:
        """使用 refresh token 匿名刷新会话。

        功能说明:
            使用 refresh token 匿名刷新会话。
        参数说明:
            refresh_token: 当前会话的刷新 token。
        返回值:
            包含一组新 token 和过期时间的 Gateway 标准响应。
        异常说明:
            Gateway 调用和响应解析异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "RefreshSession",
            {"refresh_token": refresh_token},
            auth_token=None,
        )

    def get_me(self, *, access_token: str) -> GatewayResponse:
        """使用最新 access token 查询当前用户。

        功能说明:
            使用最新 access token 查询当前用户身份。
        参数说明:
            access_token: 调用方会话上下文中的最新 access token。
        返回值:
            包含 ``user_id``、``device_id`` 等身份字段的标准响应。
        异常说明:
            Gateway 调用和响应解析异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetMe",
            {},
            auth_token=access_token,
        )
