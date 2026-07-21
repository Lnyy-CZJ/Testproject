"""BillingService 底层订单请求形状单元测试。"""

from typing import Any

import pytest

from services.billing_service import BillingService


pytestmark = pytest.mark.payment_sandbox


class _RecordingClient:
    """保存 Billing Service 形成的 Gateway 调用。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def invoke(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        return object()


def test_create_order_matches_document_and_forwards_idempotency_key() -> None:
    client = _RecordingClient()
    service = BillingService(client)

    service.create_order(
        access_token="access-latest",
        client_request_id="crid-billing-stable",
        product_code="people_insight",
        plan_code="monthly",
        amount=999,
        currency="USD",
    )

    assert client.calls == [
        (
            (
                "tool.billing.BillingService",
                "CreateOrder",
                {
                    "client_request_id": "crid-billing-stable",
                    "product_code": "people_insight",
                    "plan_code": "monthly",
                    "amount": 999,
                    "currency": "USD",
                },
            ),
            {
                "auth_token": "access-latest",
                "client_request_id": "crid-billing-stable",
            },
        )
    ]


def test_get_order_passes_only_order_id_and_auth() -> None:
    client = _RecordingClient()
    service = BillingService(client)

    service.get_order(access_token="access-latest", order_id="order-1")

    assert client.calls == [
        (
            (
                "tool.billing.BillingService",
                "GetOrder",
                {"order_id": "order-1"},
            ),
            {"auth_token": "access-latest"},
        )
    ]


def test_verify_order_matches_documented_apple_shape() -> None:
    client = _RecordingClient()
    service = BillingService(client)

    service.verify_order(
        access_token="access-latest",
        order_id="order-1",
        store_provider="apple",
        transaction_id="tx-1",
        original_transaction_id="otx-1",
    )

    assert client.calls == [
        (
            (
                "tool.billing.BillingService",
                "VerifyOrder",
                {
                    "order_id": "order-1",
                    "store_provider": "apple",
                    "transaction_id": "tx-1",
                    "original_transaction_id": "otx-1",
                },
            ),
            {"auth_token": "access-latest"},
        )
    ]
