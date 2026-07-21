"""TC-001/002/007～015 身份与订阅离线可执行契约。"""

from collections.abc import Iterable
from typing import Any

import pytest

from framework.assertions.gateway_assert import (
    assert_business_error,
    assert_business_success,
    assert_gateway_received,
)
from framework.data.context import SessionContext
from framework.models.envelope import GatewayResponse, GatewaySubResponse
from services.identity_service import IdentityService
from services.subscription_service import SubscriptionService


def _gateway_response(
    *,
    data: dict[str, Any] | None = None,
    error_code: str = "",
    numeric_code: int = 0,
) -> GatewayResponse:
    """构造顶层已接收、子响应可成功或失败的离线响应。"""
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "gw-offline",
            "trace_id": "trace-offline",
            "responses": [
                {
                    "id": "req_0",
                    "code": numeric_code,
                    "message": "offline",
                    "success": not error_code,
                    "business_error_code": error_code,
                    "data": data,
                }
            ],
        }
    )
    response.http_status = 200
    return response


def _assert_unconfirmed_business_failure(
    response: GatewayResponse,
) -> GatewaySubResponse:
    """断言尚无正式错误码的通用业务失败契约。

    功能说明:
        仅验证 Gateway 顶层成功接收且 ``req_0`` 子响应明确失败，不把离线 mock
        的错误码哨兵误写为服务端正式协议。
    参数说明:
        response: 无效商品、未支付验单或不存在恢复交易的离线响应。
    返回值:
        已确认失败的 ``req_0`` 子响应。
    异常说明:
        顶层状态、目标子响应或通用失败字段不符合预期时抛出 ``AssertionError``。
        具体数字码和 ``business_error_code`` 待后端及接口文档确认后再精确断言。
    """
    assert_gateway_received(response)
    assert response.code == 0
    matches = [item for item in response.responses if item.id == "req_0"]
    assert len(matches) == 1
    item = matches[0]
    assert item.success is False
    assert item.code != 0
    assert item.business_error_code
    return item


class _QueuedGatewayClient:
    """按顺序返回离线响应并保留所有 Service 调用。"""

    def __init__(self, responses: Iterable[GatewayResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self,
        service_name: str,
        method_name: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> GatewayResponse:
        self.calls.append(
            {
                "service_name": service_name,
                "method_name": method_name,
                "params": params,
                **kwargs,
            }
        )
        return next(self._responses)


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.auth
@pytest.mark.subscription
@pytest.mark.payment_sandbox
def test_tc001_subscription_flow_uses_identity_then_subscription_only() -> None:
    session_data = {
        "user_id": "user-offline",
        "access_token": "access-offline",
        "expires_time": 1000,
        "refresh_token": "refresh-offline",
        "refresh_expires_time": 2000,
        "is_new_user": True,
    }
    products = {
        "items": [
            {
                "product_id": "product-1",
                "product_code": "people_insight",
                "store_product_id": "com.example.premium.monthly",
                "is_purchasable": True,
            }
        ]
    }
    client = _QueuedGatewayClient(
        [
            _gateway_response(data=session_data),
            _gateway_response(data={"user_id": "user-offline", "device_id": "device-1"}),
            _gateway_response(data=products),
            _gateway_response(data={"order_id": "order-1", "order_status": "pending"}),
            _gateway_response(
                data={"verification_result": "verified", "subscription_status": "active"}
            ),
            _gateway_response(
                data={
                    "has_active_subscription": True,
                    "subscription_status": "active",
                    "product_code": "people_insight",
                }
            ),
            _gateway_response(
                data={
                    "subscription_status": "active",
                    "can_start_search": True,
                    "decision": "ALLOW",
                }
            ),
        ]
    )
    identity = IdentityService(client)
    subscription = SubscriptionService(client)

    created = assert_business_success(
        identity.create_anonymous_session(
            consent_policy_version="2026-06-01",
            client_request_id="crid-tc001-anonymous-stable",
        ),
        required_data_fields={
            "user_id",
            "access_token",
            "expires_time",
            "refresh_token",
            "refresh_expires_time",
            "is_new_user",
        },
    )
    context = SessionContext.from_anonymous_session(device_id="device-1", data=created)
    me = assert_business_success(
        identity.get_me(access_token=context.access_token),
        required_data_fields={"user_id", "device_id"},
    )
    product_data = assert_business_success(
        subscription.list_subscription_products(
            access_token=context.access_token, platform="ios", region_code="US"
        ),
        required_data_fields={"items"},
    )
    product = product_data["items"][0]
    order = assert_business_success(
        subscription.create_subscription_order(
            access_token=context.access_token,
            client_request_id="crid-tc001-stable",
            product_id=product["product_id"],
            store_product_id=product["store_product_id"],
            platform="ios",
        ),
        required_data_fields={"order_id", "order_status"},
    )
    verified = assert_business_success(
        subscription.verify_subscription_purchase(
            access_token=context.access_token,
            order_id=order["order_id"],
            product_id=product["product_id"],
            store_product_id=product["store_product_id"],
            platform="ios",
            store_provider="apple",
            transaction_id="transaction-placeholder",
            original_transaction_id="original-placeholder",
        ),
        required_data_fields={"verification_result", "subscription_status"},
    )
    status = assert_business_success(
        subscription.get_subscription_status(
            access_token=context.access_token,
            product_code="people_insight",
            scenario="search",
        ),
        required_data_fields={"has_active_subscription", "subscription_status"},
    )
    entitlement = assert_business_success(
        subscription.get_entitlement(
            access_token=context.access_token, product_code="people_insight"
        ),
        required_data_fields={"subscription_status", "can_start_search", "decision"},
    )

    assert me == {"user_id": context.user_id, "device_id": context.device_id}
    assert verified["subscription_status"] == status["subscription_status"]
    assert status["subscription_status"] == entitlement["subscription_status"]
    assert all("BillingService" not in call["service_name"] for call in client.calls)


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.auth
def test_tc002_refresh_uses_new_token_without_changing_local_owner() -> None:
    client = _QueuedGatewayClient(
        [
            _gateway_response(
                data={
                    "access_token": "access-new",
                    "expires_time": 3000,
                    "refresh_token": "refresh-new",
                    "refresh_expires_time": 4000,
                }
            ),
            _gateway_response(data={"user_id": "user-1", "device_id": "device-1"}),
        ]
    )
    service = IdentityService(client)
    context = SessionContext(
        device_id="device-1",
        user_id="user-1",
        access_token="access-old",
        expires_time=1000,
        refresh_token="refresh-old",
        refresh_expires_time=2000,
    )

    refreshed = assert_business_success(
        service.refresh_session(refresh_token=context.refresh_token),
        required_data_fields={
            "access_token",
            "expires_time",
            "refresh_token",
            "refresh_expires_time",
        },
    )
    context.replace_tokens(refreshed)
    me = assert_business_success(
        service.get_me(access_token=context.access_token),
        required_data_fields={"user_id", "device_id"},
    )

    assert client.calls[0]["auth_token"] is None
    assert client.calls[1]["auth_token"] == "access-new"
    assert me["user_id"] == context.user_id == "user-1"
    assert "user_id" not in client.calls[1]
    assert "user_id" not in client.calls[1]["params"]


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.auth
@pytest.mark.subscription
@pytest.mark.payment_sandbox
@pytest.mark.parametrize(
    ("case_id", "token", "operation"),
    [
        ("TC-007", None, "create"),
        ("TC-008", "invalid-token-placeholder", "entitlement"),
    ],
)
def test_subscription_access_errors_are_double_asserted(
    case_id: str,
    token: str | None,
    operation: str,
) -> None:
    client = _QueuedGatewayClient(
        [_gateway_response(error_code="UNAUTHENTICATED", numeric_code=300001)]
    )
    service = SubscriptionService(client)

    if operation == "entitlement":
        response = service.get_entitlement(
            access_token=token, product_code="people_insight"
        )
    else:
        response = service.create_subscription_order(
            access_token=token,
            client_request_id=f"crid-{case_id.lower()}",
            product_id="product-1",
            store_product_id="missing.store.product",
            platform="ios",
        )

    sub_response = assert_business_error(
        response, "UNAUTHENTICATED", expected_code=300001
    )

    assert response.code == 0
    assert sub_response.success is False


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.payment_sandbox
def test_tc009_invalid_product_returns_unconfirmed_business_failure() -> None:
    """无效商品必须失败；正式错误码待后端及接口文档确认。"""
    client = _QueuedGatewayClient(
        [
            _gateway_response(
                error_code="UNCONFIRMED_TEST_ERROR", numeric_code=399999
            )
        ]
    )
    service = SubscriptionService(client)

    response = service.create_subscription_order(
        access_token="access-offline",
        client_request_id="crid-tc009",
        product_id="missing-product",
        store_product_id="missing.store.product",
        platform="ios",
    )

    _assert_unconfirmed_business_failure(response)


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.idempotency
@pytest.mark.payment_sandbox
def test_tc010_duplicate_create_reuses_client_request_id_and_order() -> None:
    client = _QueuedGatewayClient(
        [
            _gateway_response(data={"order_id": "order-same", "order_status": "pending"}),
            _gateway_response(data={"order_id": "order-same", "order_status": "pending"}),
        ]
    )
    service = SubscriptionService(client)

    results = []
    for _ in range(2):
        response = service.create_subscription_order(
            access_token="access-offline",
            client_request_id="crid-tc010-stable",
            product_id="product-1",
            store_product_id="com.example.premium.monthly",
            platform="ios",
        )
        results.append(
            assert_business_success(
                response, required_data_fields={"order_id", "order_status"}
            )
        )

    assert results[0] == results[1]
    assert {call["client_request_id"] for call in client.calls} == {
        "crid-tc010-stable"
    }
    assert {call["params"]["client_request_id"] for call in client.calls} == {
        "crid-tc010-stable"
    }


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.payment_sandbox
def test_tc011_unpaid_purchase_verification_is_business_failure() -> None:
    """未支付验单必须失败；正式错误码待后端及接口文档确认。"""
    client = _QueuedGatewayClient(
        [
            _gateway_response(
                error_code="UNCONFIRMED_TEST_ERROR", numeric_code=399999
            )
        ]
    )
    service = SubscriptionService(client)

    response = service.verify_subscription_purchase(
        access_token="access-offline",
        order_id="order-unpaid",
        product_id="product-1",
        store_product_id="com.example.premium.monthly",
        platform="ios",
        store_provider="apple",
        transaction_id="unpaid-placeholder",
        original_transaction_id="unpaid-original-placeholder",
    )

    _assert_unconfirmed_business_failure(response)


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.idempotency
@pytest.mark.payment_sandbox
def test_tc012_duplicate_verification_returns_same_subscription_result() -> None:
    result = {
        "verification_result": "verified",
        "subscription_status": "active",
        "product_code": "people_insight",
    }
    client = _QueuedGatewayClient(
        [_gateway_response(data=result), _gateway_response(data=result)]
    )
    service = SubscriptionService(client)

    verified = []
    for _ in range(2):
        response = service.verify_subscription_purchase(
            access_token="access-offline",
            order_id="order-paid",
            product_id="product-1",
            store_product_id="com.example.premium.monthly",
            platform="ios",
            store_provider="apple",
            transaction_id="paid-placeholder",
            original_transaction_id="paid-original-placeholder",
        )
        verified.append(
            assert_business_success(
                response,
                required_data_fields={"verification_result", "subscription_status"},
            )
        )

    assert verified[0] == verified[1]
    assert client.calls[0]["params"] == client.calls[1]["params"]


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.payment_sandbox
def test_tc013_restore_unknown_transaction_is_business_failure() -> None:
    """不存在交易的恢复必须失败；正式错误码待后端及接口文档确认。"""
    client = _QueuedGatewayClient(
        [
            _gateway_response(
                error_code="UNCONFIRMED_TEST_ERROR", numeric_code=399999
            )
        ]
    )
    service = SubscriptionService(client)

    response = service.restore_subscription(
        access_token="access-offline",
        store_product_id="com.example.premium.monthly",
        platform="ios",
        store_provider="apple",
        transaction_id="unknown-placeholder",
        original_transaction_id="unknown-original-placeholder",
    )

    _assert_unconfirmed_business_failure(response)


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.idempotency
@pytest.mark.payment_sandbox
def test_tc014_restore_same_transaction_is_idempotent() -> None:
    restored = {
        "subscription_status": "active",
        "product_code": "people_insight",
        "expires_time": 5000,
    }
    client = _QueuedGatewayClient(
        [_gateway_response(data=restored), _gateway_response(data=restored)]
    )
    service = SubscriptionService(client)

    results = []
    for _ in range(2):
        response = service.restore_subscription(
            access_token="access-offline",
            store_product_id="com.example.premium.monthly",
            platform="ios",
            store_provider="apple",
            transaction_id="restored-placeholder",
            original_transaction_id="restored-original-placeholder",
        )
        results.append(
            assert_business_success(
                response,
                required_data_fields={"subscription_status", "product_code"},
            )
        )

    assert results[0] == results[1]
    assert client.calls[0]["params"] == client.calls[1]["params"]


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.subscription
@pytest.mark.parametrize(
    ("status", "has_active", "can_start", "decision"),
    [
        ("active", True, True, "ALLOW"),
        ("expired", False, False, "SUBSCRIPTION_EXPIRED"),
        ("inactive", False, False, "SUBSCRIPTION_REQUIRED"),
    ],
)
def test_tc015_subscription_status_and_entitlement_are_consistent(
    status: str, has_active: bool, can_start: bool, decision: str
) -> None:
    client = _QueuedGatewayClient(
        [
            _gateway_response(
                data={
                    "has_active_subscription": has_active,
                    "subscription_status": status,
                    "product_code": "people_insight",
                }
            ),
            _gateway_response(
                data={
                    "subscription_status": status,
                    "can_start_search": can_start,
                    "decision": decision,
                    "vip_level": 1 if has_active else 0,
                }
            ),
        ]
    )
    service = SubscriptionService(client)

    status_data = assert_business_success(
        service.get_subscription_status(
            access_token="access-offline",
            product_code="people_insight",
            scenario="search",
        ),
        required_data_fields={"has_active_subscription", "subscription_status"},
    )
    entitlement = assert_business_success(
        service.get_entitlement(
            access_token="access-offline", product_code="people_insight"
        ),
        required_data_fields={"subscription_status", "can_start_search", "decision"},
    )

    assert status_data["subscription_status"] == entitlement["subscription_status"]
    assert status_data["has_active_subscription"] is entitlement["can_start_search"]
