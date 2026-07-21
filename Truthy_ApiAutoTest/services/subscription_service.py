"""SubscriptionService 订阅协议参数封装。"""

from typing import Any

from framework.client.gateway_client import GatewayClient
from framework.models.envelope import GatewayResponse


class SubscriptionService:
    """封装客户端订阅主流程，不混入底层 Billing 调用。

    功能说明:
        按客户端接口文档 3.0 形成订阅商品、订单、验单、恢复、状态、权益和
        额度流水请求；所有网络行为只委托 :class:`GatewayClient`。
    参数说明:
        client: 统一 Gateway 客户端或实现相同 ``invoke`` 协议的测试替身。
    返回值:
        公共方法均返回未吞掉业务状态的 Gateway 标准响应。
    异常说明:
        Gateway 网络、HTTP、参数和响应解析异常原样向调用方传播。
    """

    SERVICE_NAME = "tool.subscription.SubscriptionService"

    def __init__(self, client: GatewayClient) -> None:
        self._client = client

    def list_subscription_products(
        self, *, access_token: str, platform: str, region_code: str
    ) -> GatewayResponse:
        """查询指定平台和地区可展示的订阅商品。

        功能说明:
            查询指定平台和地区可展示的订阅商品。
        参数说明:
            access_token: 最新会话 token；platform/region_code: 商店平台与地区。
        返回值:
            商品列表 Gateway 标准响应。
        异常说明:
            Gateway 调用异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "ListSubscriptionProducts",
            {"platform": platform, "region_code": region_code},
            auth_token=access_token,
        )

    def create_subscription_order(
        self,
        *,
        access_token: str,
        client_request_id: str,
        product_id: str,
        store_product_id: str,
        platform: str,
    ) -> GatewayResponse:
        """以调用方稳定幂等 ID 创建订阅购买意图。

        功能说明:
            以调用方稳定幂等 ID 创建订阅购买意图。
        参数说明:
            access_token: 最新会话 token；client_request_id: 调用方生成且重试时
            保持不变的幂等 ID；其余参数定位服务端商品和商店商品。
        返回值:
            包含订单 ID 与订单状态的 Gateway 标准响应。
        异常说明:
            Gateway 调用异常原样抛出，不自动生成或替换幂等 ID。
        """
        params = {
            "client_request_id": client_request_id,
            "product_id": product_id,
            "store_product_id": store_product_id,
            "platform": platform,
        }
        return self._client.invoke(
            self.SERVICE_NAME,
            "CreateSubscriptionOrder",
            params,
            auth_token=access_token,
            client_request_id=client_request_id,
        )

    def verify_subscription_purchase(
        self,
        *,
        access_token: str,
        order_id: str,
        product_id: str,
        store_product_id: str,
        platform: str,
        store_provider: str,
        transaction_id: str | None = None,
        original_transaction_id: str | None = None,
        purchase_token: str | None = None,
        package_name: str | None = None,
    ) -> GatewayResponse:
        """使用 Apple 或 Google 平台凭证验证订阅购买。

        功能说明:
            使用 Apple 或 Google 平台凭证验证订阅购买。
        参数说明:
            access_token/order_id/product_id/store_product_id/platform/store_provider:
            订单与平台定位信息；Apple 使用 transaction 两字段，Google 使用
            purchase_token 与 package_name。
        返回值:
            验单结果和订阅状态的 Gateway 标准响应。
        异常说明:
            Service 不猜测平台必填组合；服务端参数或业务错误原样返回/抛出。
        """
        params: dict[str, Any] = {
            "order_id": order_id,
            "product_id": product_id,
            "store_product_id": store_product_id,
            "platform": platform,
            "store_provider": store_provider,
            "transaction_id": transaction_id,
            "original_transaction_id": original_transaction_id,
            "purchase_token": purchase_token,
            "package_name": package_name,
        }
        return self._client.invoke(
            self.SERVICE_NAME,
            "VerifySubscriptionPurchase",
            {key: value for key, value in params.items() if value is not None},
            auth_token=access_token,
        )

    def restore_subscription(
        self,
        *,
        access_token: str,
        store_product_id: str,
        platform: str,
        store_provider: str,
        transaction_id: str | None = None,
        original_transaction_id: str | None = None,
    ) -> GatewayResponse:
        """使用平台交易凭证恢复订阅，不传订单 ID。

        功能说明:
            使用平台交易凭证恢复订阅，不传订单 ID。
        参数说明:
            access_token: 最新会话 token；商店、平台及 Apple transaction 字段按
            客户端接口文档 3.0 的 RestoreSubscription 示例原样传递。
        返回值:
            恢复结果 Gateway 标准响应。
        异常说明:
            Gateway 调用和业务响应异常原样传播。
        """
        params: dict[str, Any] = {
            "store_product_id": store_product_id,
            "platform": platform,
            "store_provider": store_provider,
            "transaction_id": transaction_id,
            "original_transaction_id": original_transaction_id,
        }
        return self._client.invoke(
            self.SERVICE_NAME,
            "RestoreSubscription",
            {key: value for key, value in params.items() if value is not None},
            auth_token=access_token,
        )

    def get_subscription_status(
        self,
        *,
        access_token: str,
        product_code: str,
        scenario: str,
    ) -> GatewayResponse:
        """查询指定产品和场景的三态订阅状态。

        功能说明:
            查询指定产品和场景的三态订阅状态。
        参数说明:
            access_token: 最新会话 token；product_code/scenario: 产品与业务场景。
        返回值:
            包含 active/inactive/expired 状态的标准响应。
        异常说明:
            Gateway 调用异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetSubscriptionStatus",
            {"product_code": product_code, "scenario": scenario},
            auth_token=access_token,
        )

    def get_entitlement(
        self,
        *,
        access_token: str,
        product_code: str,
        read_timeout: float | None = None,
    ) -> GatewayResponse:
        """查询当前用户指定产品的搜索权益。

        功能说明:
            查询当前用户指定产品的搜索权益，并支持等待器缩短 HTTP 超时。
        参数说明:
            access_token: 最新会话 token；product_code: 产品代码；read_timeout:
            最终一致性等待器提供的可选剩余秒数，用于缩短 Gateway HTTP 超时。
        返回值:
            包含订阅状态、额度、并发和决策的标准响应。
        异常说明:
            Gateway 调用异常原样抛出。
        """
        invoke_kwargs: dict[str, Any] = {"auth_token": access_token}
        if read_timeout is not None:
            invoke_kwargs["read_timeout"] = read_timeout
        return self._client.invoke(
            self.SERVICE_NAME,
            "GetEntitlement",
            {"product_code": product_code},
            **invoke_kwargs,
        )

    def list_quota_ledger(
        self,
        *,
        access_token: str,
        product_code: str,
        page_size: int = 20,
        page_token: str = "",
    ) -> GatewayResponse:
        """分页查询指定产品的额度流水。

        功能说明:
            分页查询指定产品的额度流水。
        参数说明:
            access_token/product_code: 会话 token 与产品代码；page_size/page_token:
            文档 3.0 的嵌套分页参数。
        返回值:
            额度流水 Gateway 标准响应。
        异常说明:
            Gateway 调用异常原样抛出。
        """
        return self._client.invoke(
            self.SERVICE_NAME,
            "ListQuotaLedger",
            {
                "product_code": product_code,
                "page": {"page_size": page_size, "page_token": page_token},
            },
            auth_token=access_token,
        )
