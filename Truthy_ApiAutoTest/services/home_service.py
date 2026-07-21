"""HomeService 业务参数封装。"""

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class HomeService:
    """封装首页读取接口，不直接处理 HTTP。

    功能说明:
        仅封装首页读取业务参数，所有 HTTP 行为委托 GatewayClient。
    参数说明:
        client: 统一 :class:`GatewayClient` 或实现相同 ``invoke`` 协议的测试替身。
    返回值:
        公共方法返回标准 :class:`GatewayResponse`。
    异常说明:
        Gateway 网络、HTTP 和解析异常原样向测试层传播。
    """

    SERVICE_NAME = "tool.people_insight.HomeService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def get_home_content(
        self,
        *,
        locale: str = "en-US",
        auth_token: str | None = None,
    ) -> GatewayResponse:
        """获取首页检索案例和用户故事。

        功能说明:
            获取匿名或登录态首页检索案例和用户故事。
        参数说明:
            locale: 后端内容区域标识。
            auth_token: 可选登录态；匿名首页读取可不传。
        返回值:
            未吞掉业务状态的 Gateway 标准响应。
        异常说明:
            参数校验、网络、HTTP 或响应解析异常原样抛出。
        """
        # Home 内容是匿名可读接口，显式传 None，避免环境默认 token 被隐式继承。
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetHomeContent",
            {"locale": locale},
            auth_token=auth_token,
        )
