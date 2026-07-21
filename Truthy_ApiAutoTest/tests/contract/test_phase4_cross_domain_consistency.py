"""TC-024～030 当前可执行子集的纯离线跨域一致性测试。"""

from typing import Any

import pytest

from framework.adapters.entitlement_fixture import (
    EntitlementFixtureState,
    MockEntitlementFixtureAdapter,
)
from framework.assertions.gateway_assert import (
    assert_business_error,
    assert_business_success,
)
from framework.data.context import SessionContext
from framework.data.factories import build_client_request_id
from framework.models.envelope import GatewayResponse
from framework.waiters.entitlement_waiter import wait_entitlement_allow
from services.identity_service import IdentityService
from services.search_service import SearchService
from services.subscription_service import SubscriptionService


def _response(
    data: Any = None, *, error_code: str = "", numeric_code: int = 0
) -> GatewayResponse:
    """构造阶段4内存后端使用的 Gateway 信封。"""
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "offline-request",
            "trace_id": "offline-trace",
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


def _session() -> SessionContext:
    """返回无真实凭据的阶段4用户会话。"""
    return SessionContext(
        device_id="device-phase4",
        user_id="user-phase4",
        access_token="access-phase4-old",
        expires_time=1000,
        refresh_token="refresh-phase4-old",
        refresh_expires_time=2000,
    )


class _EntitlementAwareGateway:
    """把会话、权益、订单、任务和历史保存在内存中的离线后端。

    功能说明:
        只模拟 TC-025～030 已被文档定义的行为；搜索无权益固定返回
        ``301101/ENTITLEMENT_REQUIRED``，搜索 token 失效固定返回文档中的
        ``301002/UNAUTHENTICATED``。不猜跨用户错误码或真实夹具 HTTP 协议。
    """

    PRODUCT = "people_insight"

    def __init__(
        self,
        session: SessionContext,
        adapter: MockEntitlementFixtureAdapter,
        *,
        delayed_grant_poll: int | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.valid_tokens = {session.access_token}
        self.history: list[str] = []
        self.owners: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []
        self.delayed_grant_poll = delayed_grant_poll
        self.entitlement_polls = 0

    def invalidate(self, access_token: str) -> None:
        """测试专用地使 token 失效，不模拟未定义的删除会话接口。"""
        self.valid_tokens.discard(access_token)

    def invoke(
        self, service_name: str, method_name: str, params: dict[str, Any], **kwargs: Any
    ) -> GatewayResponse:
        """根据公开 Service 方法返回最小离线契约响应。"""
        self.calls.append(
            {
                "service_name": service_name,
                "method_name": method_name,
                "params": params,
                **kwargs,
            }
        )
        if method_name == "RefreshSession":
            if params.get("refresh_token") != self.session.refresh_token:
                return _response(error_code="UNAUTHENTICATED", numeric_code=300001)
            new_access = "access-phase4-new"
            self.valid_tokens.add(new_access)
            return _response(
                {
                    "access_token": new_access,
                    "expires_time": 3000,
                    "refresh_token": "refresh-phase4-new",
                    "refresh_expires_time": 4000,
                }
            )

        access_token = kwargs.get("auth_token")
        if access_token not in self.valid_tokens:
            code = 301002 if "people_insight" in service_name else 300001
            return _response(error_code="UNAUTHENTICATED", numeric_code=code)

        if method_name == "GetMe":
            return _response(
                {"user_id": self.session.user_id, "device_id": self.session.device_id}
            )
        if method_name == "CreateSubscriptionOrder":
            order_id = "order-phase4"
            self.owners[order_id] = self.session.user_id
            return _response({"order_id": order_id, "order_status": "pending"})
        if method_name == "GetEntitlement":
            self.entitlement_polls += 1
            if self.entitlement_polls == self.delayed_grant_poll:
                self.adapter.grant(self.session, self.PRODUCT, 60)
            state = self.adapter.get_state(self.session, self.PRODUCT)
            return _response(
                {
                    "subscription_status": state.value,
                    "can_start_search": state is EntitlementFixtureState.ACTIVE,
                    "decision": (
                        "ALLOW" if state is EntitlementFixtureState.ACTIVE else "DENY"
                    ),
                }
            )
        if method_name == "CreateIntentTask":
            if (
                self.adapter.get_state(self.session, self.PRODUCT)
                is not EntitlementFixtureState.ACTIVE
            ):
                return _response(
                    error_code="ENTITLEMENT_REQUIRED", numeric_code=301101
                )
            task_id = f"task-phase4-{len(self.history) + 1}"
            self.history.append(task_id)
            self.owners[task_id] = self.session.user_id
            self.owners[f"candidate:{task_id}"] = self.session.user_id
            return _response({"task_id": task_id, "status": "SUCCEEDED"})
        if method_name == "ListTaskCandidates":
            task_id = params["task_id"]
            return _response(
                {
                    "task_id": task_id,
                    "items": [{"candidate_id": f"candidate-{task_id}"}],
                    "next_page_token": "",
                    "empty_reason": "",
                }
            )
        if method_name == "ListSearchHistory":
            return _response(
                {
                    "items": [{"task_id": task_id} for task_id in self.history],
                    "next_page_token": "",
                }
            )
        raise AssertionError(f"离线后端未声明方法: {method_name}")


@pytest.mark.skip(reason="越权错误码契约未确认")
@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.auth
@pytest.mark.search
def test_tc024_cross_user_access_contract_pending() -> None:
    """待跨用户 task/candidate 精确错误码确认后再启用。"""


@pytest.mark.contract
@pytest.mark.p0
@pytest.mark.auth
@pytest.mark.subscription
@pytest.mark.search
@pytest.mark.requires_entitlement
def test_tc025_anonymous_identity_is_preserved_across_order_task_and_candidate() -> None:
    """同一 token 解析出的用户必须贯穿订单、任务和候选归属。"""
    session = _session()
    adapter = MockEntitlementFixtureAdapter()
    adapter.grant(session, "people_insight", 60)
    gateway = _EntitlementAwareGateway(session, adapter)
    me = assert_business_success(
        IdentityService(gateway).get_me(access_token=session.access_token)
    )
    order = assert_business_success(
        SubscriptionService(gateway).create_subscription_order(
            access_token=session.access_token,
            client_request_id=build_client_request_id("build4", "TC-025"),
            product_id="product-phase4",
            store_product_id="store-product-phase4",
            platform="ios",
        )
    )
    search = SearchService(gateway)
    task = assert_business_success(
        search.create_intent_task(
            access_token=session.access_token,
            client_request_id=build_client_request_id("build4", "TC-025-search"),
            match_strategy="UNION",
            clues=[{"type": "FULL_NAME", "full_name_query": {"full_name": "Ada Lovelace"}}],
        )
    )
    assert_business_success(
        search.list_task_candidates(
            access_token=session.access_token, task_id=task["task_id"]
        )
    )

    assert me["user_id"] == session.user_id
    assert gateway.owners[order["order_id"]] == session.user_id
    assert gateway.owners[task["task_id"]] == session.user_id
    assert gateway.owners[f"candidate:{task['task_id']}"] == session.user_id


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.auth
@pytest.mark.search
def test_tc026_refresh_keeps_user_and_existing_history() -> None:
    """原子替换 token 后用户身份不变，新 token 仍读取原历史。"""
    session = _session()
    adapter = MockEntitlementFixtureAdapter()
    adapter.grant(session, "people_insight", 60)
    gateway = _EntitlementAwareGateway(session, adapter)
    search = SearchService(gateway)
    task = assert_business_success(
        search.create_intent_task(
            access_token=session.access_token,
            client_request_id=build_client_request_id("build4", "TC-026"),
            match_strategy="UNION",
            clues=[],
        )
    )
    refreshed = assert_business_success(
        IdentityService(gateway).refresh_session(refresh_token=session.refresh_token)
    )
    session.replace_tokens(refreshed)
    me = assert_business_success(
        IdentityService(gateway).get_me(access_token=session.access_token)
    )
    history = assert_business_success(
        search.list_search_history(access_token=session.access_token)
    )

    assert me["user_id"] == "user-phase4"
    assert [item["task_id"] for item in history["items"]] == [task["task_id"]]


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.subscription
@pytest.mark.entitlement_fixture
@pytest.mark.fixture_required
def test_tc027_delayed_entitlement_becomes_active_with_bounded_polling() -> None:
    """离线夹具模拟异步延迟，有限次数轮询后权益最终生效。"""
    session = _session()
    adapter = MockEntitlementFixtureAdapter()
    gateway = _EntitlementAwareGateway(session, adapter, delayed_grant_poll=3)
    subscription = SubscriptionService(gateway)
    now = [0.0]

    result = wait_entitlement_allow(
        subscription,
        access_token=session.access_token,
        product_code="people_insight",
        clock=lambda: now[0],
        sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )

    assert [item["decision"] for item in result.trajectory] == [
        "DENY",
        "DENY",
        "ALLOW",
    ]
    assert result.data["subscription_status"] == "active"
    assert result.data["can_start_search"] is True


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
@pytest.mark.entitlement_fixture
@pytest.mark.requires_entitlement
@pytest.mark.parametrize("transition", ["revoke", "expire"])
def test_tc028_inactive_or_expired_entitlement_blocks_search(transition: str) -> None:
    """撤销和过期后搜索均返回文档精确无权益错误。"""
    session = _session()
    adapter = MockEntitlementFixtureAdapter()
    adapter.grant(session, "people_insight", 60)
    getattr(adapter, transition)(session, "people_insight")
    gateway = _EntitlementAwareGateway(session, adapter)

    response = SearchService(gateway).create_intent_task(
        access_token=session.access_token,
        client_request_id=build_client_request_id("build4", f"TC-028-{transition}"),
        match_strategy="UNION",
        clues=[],
    )

    assert_business_error(
        response, "ENTITLEMENT_REQUIRED", expected_code=301101
    )


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.search
@pytest.mark.entitlement_fixture
@pytest.mark.requires_entitlement
def test_tc029_grant_changes_search_from_denied_to_success() -> None:
    """同一用户获得权益后，后续新幂等请求可成功创建搜索。"""
    session = _session()
    adapter = MockEntitlementFixtureAdapter()
    gateway = _EntitlementAwareGateway(session, adapter)
    search = SearchService(gateway)
    denied = search.create_intent_task(
        access_token=session.access_token,
        client_request_id=build_client_request_id("build4", "TC-029-before"),
        match_strategy="UNION",
        clues=[],
    )
    assert_business_error(denied, "ENTITLEMENT_REQUIRED", expected_code=301101)

    adapter.grant(session, "people_insight", 60)
    created = assert_business_success(
        search.create_intent_task(
            access_token=session.access_token,
            client_request_id=build_client_request_id("build4", "TC-029-after"),
            match_strategy="UNION",
            clues=[],
        )
    )

    assert created["status"] == "SUCCEEDED"


@pytest.mark.contract
@pytest.mark.p1
@pytest.mark.auth
@pytest.mark.search
def test_tc030_invalidated_token_cannot_read_business_history() -> None:
    """测试专用失效旧 token 后，业务接口返回文档鉴权失败。"""
    session = _session()
    adapter = MockEntitlementFixtureAdapter()
    adapter.grant(session, "people_insight", 60)
    gateway = _EntitlementAwareGateway(session, adapter)
    search = SearchService(gateway)
    assert_business_success(
        search.create_intent_task(
            access_token=session.access_token,
            client_request_id=build_client_request_id("build4", "TC-030"),
            match_strategy="UNION",
            clues=[],
        )
    )
    gateway.invalidate(session.access_token)

    response = search.list_search_history(access_token=session.access_token)

    assert_business_error(response, "UNAUTHENTICATED", expected_code=301002)


@pytest.mark.contract
@pytest.mark.live_write
@pytest.mark.destructive
@pytest.mark.entitlement_fixture
@pytest.mark.fixture_required
def test_live_entitlement_fixture_requires_confirmed_protocol(
    live_entitlement_adapter: object,
) -> None:
    """危险开关开启后仍由 fixture 因真实协议/凭据缺失明确跳过。"""
    raise AssertionError("缺少真实协议时不应执行到测试体")
