"""身份会话与订阅读取的显式 live_safe 合同。"""

import pytest

from framework.assertions.gateway_assert import assert_business_success
from framework.data.context import SessionContext
from services.identity_service import IdentityService
from services.subscription_service import SubscriptionService


@pytest.mark.contract
@pytest.mark.live_safe
@pytest.mark.p0
@pytest.mark.auth
def test_identity_session_refresh_live_safe(
    anonymous_session: SessionContext,
    identity_service: IdentityService,
) -> None:
    """执行 CreateAnonymousSession 后的读取、刷新和最新 token 身份读取。"""
    first_me = assert_business_success(
        identity_service.get_me(access_token=anonymous_session.access_token),
        required_data_fields={"user_id", "device_id"},
    )
    refreshed = assert_business_success(
        identity_service.refresh_session(
            refresh_token=anonymous_session.refresh_token
        ),
        required_data_fields={
            "access_token",
            "expires_time",
            "refresh_token",
            "refresh_expires_time",
        },
    )
    anonymous_session.replace_tokens(refreshed)
    second_me = assert_business_success(
        identity_service.get_me(access_token=anonymous_session.access_token),
        required_data_fields={"user_id", "device_id"},
    )

    assert first_me["user_id"] == second_me["user_id"] == anonymous_session.user_id
    assert first_me["device_id"] == second_me["device_id"] == anonymous_session.device_id


@pytest.mark.contract
@pytest.mark.live_safe
@pytest.mark.p0
@pytest.mark.subscription
def test_subscription_reads_live_safe(
    anonymous_session: SessionContext,
    subscription_service: SubscriptionService,
) -> None:
    """只读验证商品、订阅状态与权益的最小文档字段。"""
    assert_business_success(
        subscription_service.list_subscription_products(
            access_token=anonymous_session.access_token,
            platform="ios",
            region_code="US",
        ),
        required_data_fields={"items"},
    )
    assert_business_success(
        subscription_service.get_subscription_status(
            access_token=anonymous_session.access_token,
            product_code="people_insight",
            scenario="search",
        ),
        required_data_fields={
            "has_active_subscription",
            "subscription_status",
            "product_code",
            "entitlement",
        },
    )
    assert_business_success(
        subscription_service.get_entitlement(
            access_token=anonymous_session.access_token,
            product_code="people_insight",
        ),
        required_data_fields={
            "subscription_status",
            "can_start_search",
            "quota_remaining",
            "concurrency_remaining",
            "decision",
            "vip_level",
        },
    )
