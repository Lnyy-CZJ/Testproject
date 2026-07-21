"""BillingService 底层订单协议参数封装。"""

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class BillingService:
    """封装底层 Billing 能力，不参与正常 Subscription 购买编排。

    功能说明:
        封装底层 Billing 订单能力，不参与正常 Subscription 购买编排。
    参数说明:
        client: 统一 Gateway 客户端或实现相同 ``invoke`` 协议的测试替身。
    返回值:
        公共方法均返回 Gateway 标准响应。
    异常说明:
        Gateway 网络、HTTP、参数和响应解析异常原样向调用方传播。
    """

    SERVICE_NAME = "tool.billing.BillingService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def create_order(
        self,
        *,
        access_token: str,
        client_request_id: str,
        product_code: str,
        plan_code: str,
        amount: int,
        currency: str,
    ) -> GatewayResponse:
        """以调用方稳定幂等 ID 创建底层订单。

        功能说明:
            以调用方稳定幂等 ID 创建底层订单。
        参数说明:
            access_token/client_request_id: 最新 token 与稳定幂等 ID；其余字段为
            产品、套餐、最小货币单位金额与币种。
        返回值:
            Billing 订单 Gateway 标准响应。
        异常说明:
            Gateway 调用异常原样抛出，不自动生成或替换幂等 ID。
        """
        params = {
            "client_request_id": client_request_id,
            "product_code": product_code,
            "plan_code": plan_code,
            "amount": amount,
            "currency": currency,
        }
        return self._client.invoke(
            self.SERVICE_NAME,
            "CreateOrder",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def get_order(self, *, access_token: str, order_id: str) -> GatewayResponse:
        """按订单 ID 查询底层订单。

        功能说明:
            按订单 ID 查询底层订单状态。
        参数说明:
            access_token: 最新会话 token；order_id: 待查询订单 ID。
        返回值:
            Billing 订单 Gateway 标准响应。
        异常说明:
            Gateway 调用异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetOrder",
            {"order_id": order_id},
            auth_token=access_token,
        )

    def verify_order(
        self,
        *,
        access_token: str,
        order_id: str,
        store_provider: str,
        transaction_id: str,
        original_transaction_id: str,
    ) -> GatewayResponse:
        """使用平台交易标识验证底层订单。

        功能说明:
            使用平台交易标识验证底层订单。
        参数说明:
            access_token/order_id/store_provider: 会话、订单和商店提供方；
            transaction_id/original_transaction_id: 平台交易标识。
        返回值:
            Billing 验单 Gateway 标准响应。
        异常说明:
            Gateway 调用异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "VerifyOrder",
            {
                "order_id": order_id,
                "store_provider": store_provider,
                "transaction_id": transaction_id,
                "original_transaction_id": original_transaction_id,
            },
            auth_token=access_token,
        )
