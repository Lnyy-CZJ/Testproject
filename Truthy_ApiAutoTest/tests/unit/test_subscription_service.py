"""SubscriptionService 文档 3.0 请求形状单元测试。"""

from typing import Any

import pytest

from services.subscription_service import SubscriptionService


class _RecordingClient:
    """保存 Service 对 GatewayClient.invoke 的调用参数。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def invoke(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        return object()


@pytest.fixture
def service_and_client() -> tuple[SubscriptionService, _RecordingClient]:
    client = _RecordingClient()
    return SubscriptionService(client), client


@pytest.mark.parametrize(
    ("call", "method_name", "params"),
    [
        (
            lambda service: service.list_subscription_products(
                access_token="access-latest", platform="ios", region_code="US"
            ),
            "ListSubscriptionProducts",
            {"platform": "ios", "region_code": "US"},
        ),
        (
            lambda service: service.get_subscription_status(
                access_token="access-latest",
                product_code="people_insight",
                scenario="search",
            ),
            "GetSubscriptionStatus",
            {"product_code": "people_insight", "scenario": "search"},
        ),
        (
            lambda service: service.get_entitlement(
                access_token="access-latest", product_code="people_insight"
            ),
            "GetEntitlement",
            {"product_code": "people_insight"},
        ),
        (
            lambda service: service.list_quota_ledger(
                access_token="access-latest",
                product_code="people_insight",
                page_size=20,
                page_token="next-page",
            ),
            "ListQuotaLedger",
            {
                "product_code": "people_insight",
                "page": {"page_size": 20, "page_token": "next-page"},
            },
        ),
    ],
)
def test_subscription_reads_match_documented_shape(
    service_and_client: tuple[SubscriptionService, _RecordingClient],
    call: Any,
    method_name: str,
    params: dict[str, Any],
) -> None:
    service, client = service_and_client

    call(service)

    assert client.calls == [
        (
            ("tool.subscription.SubscriptionService", method_name, params),
            {"auth_token": "access-latest"},
        )
    ]


def test_get_entitlement_forwards_optional_read_timeout(
    service_and_client: tuple[SubscriptionService, _RecordingClient],
) -> None:
    """等待器提供剩余预算时，订阅读取必须继续传到 GatewayClient。"""
    service, client = service_and_client

    service.get_entitlement(
        access_token="access-latest",
        product_code="people_insight",
        read_timeout=4.5,
    )

    assert client.calls == [
        (
            (
                "tool.subscription.SubscriptionService",
                "GetEntitlement",
                {"product_code": "people_insight"},
            ),
            {"auth_token": "access-latest", "read_timeout": 4.5},
        )
    ]


@pytest.mark.payment_sandbox
def test_create_subscription_order_forwards_stable_client_request_id(
    service_and_client: tuple[SubscriptionService, _RecordingClient],
) -> None:
    service, client = service_and_client

    service.create_subscription_order(
        access_token="access-latest",
        client_request_id="crid-order-stable",
        product_id="product-1",
        store_product_id="com.example.premium.monthly",
        platform="ios",
    )

    assert client.calls == [
        (
            (
                "tool.subscription.SubscriptionService",
                "CreateSubscriptionOrder",
                {
                    "client_request_id": "crid-order-stable",
                    "product_id": "product-1",
                    "store_product_id": "com.example.premium.monthly",
                    "platform": "ios",
                },
            ),
            {
                "auth_token": "access-latest",
                "client_request_id": "crid-order-stable",
            },
        )
    ]


@pytest.mark.payment_sandbox
def test_verify_subscription_purchase_supports_exact_apple_shape(
    service_and_client: tuple[SubscriptionService, _RecordingClient],
) -> None:
    service, client = service_and_client

    service.verify_subscription_purchase(
        access_token="access-latest",
        order_id="order-1",
        product_id="product-1",
        store_product_id="com.example.premium.monthly",
        platform="ios",
        store_provider="apple",
        transaction_id="tx-1",
        original_transaction_id="otx-1",
    )

    assert client.calls[0] == (
        (
            "tool.subscription.SubscriptionService",
            "VerifySubscriptionPurchase",
            {
                "order_id": "order-1",
                "product_id": "product-1",
                "store_product_id": "com.example.premium.monthly",
                "platform": "ios",
                "store_provider": "apple",
                "transaction_id": "tx-1",
                "original_transaction_id": "otx-1",
            },
        ),
        {"auth_token": "access-latest"},
    )


@pytest.mark.payment_sandbox
def test_verify_subscription_purchase_supports_exact_google_shape(
    service_and_client: tuple[SubscriptionService, _RecordingClient],
) -> None:
    service, client = service_and_client

    service.verify_subscription_purchase(
        access_token="access-latest",
        order_id="order-1",
        product_id="product-1",
        store_product_id="com.example.premium.monthly",
        platform="android",
        store_provider="google",
        purchase_token="purchase-placeholder",
        package_name="com.example.app",
    )

    params = client.calls[0][0][2]
    assert params == {
        "order_id": "order-1",
        "product_id": "product-1",
        "store_product_id": "com.example.premium.monthly",
        "platform": "android",
        "store_provider": "google",
        "purchase_token": "purchase-placeholder",
        "package_name": "com.example.app",
    }
    assert "transaction_id" not in params


@pytest.mark.payment_sandbox
def test_restore_subscription_does_not_add_order_id(
    service_and_client: tuple[SubscriptionService, _RecordingClient],
) -> None:
    service, client = service_and_client

    service.restore_subscription(
        access_token="access-latest",
        store_product_id="com.example.premium.monthly",
        platform="ios",
        store_provider="apple",
        transaction_id="tx-1",
        original_transaction_id="otx-1",
    )

    assert client.calls[0] == (
        (
            "tool.subscription.SubscriptionService",
            "RestoreSubscription",
            {
                "store_product_id": "com.example.premium.monthly",
                "platform": "ios",
                "store_provider": "apple",
                "transaction_id": "tx-1",
                "original_transaction_id": "otx-1",
            },
        ),
        {"auth_token": "access-latest"},
    )
