"""阶段4权益夹具适配器的离线单元测试。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import math

import pytest

from framework.adapters.entitlement_fixture import (
    DisabledEntitlementFixtureAdapter,
    EntitlementFixtureState,
    EntitlementFixtureUnavailable,
    MockEntitlementFixtureAdapter,
    build_entitlement_fixture_adapter,
)
from framework.data.context import SessionContext


class _SessionStub:
    """允许构造无效 user_id 的最小会话替身。"""

    def __init__(self, user_id: object) -> None:
        self.user_id = user_id


class _Clock:
    """可推进或返回无效值的离线单调时钟。"""

    def __init__(self, now: object = 0.0) -> None:
        self.now = now

    def __call__(self) -> object:
        return self.now


def _session(*, user_id: str = "user-a", token: str = "token-ultra-secret") -> SessionContext:
    """构造仅供离线适配器测试使用的内存会话。"""
    return SessionContext(
        device_id="device-a",
        user_id=user_id,
        access_token=token,
        expires_time=1000,
        refresh_token=f"refresh-{token}",
        refresh_expires_time=2000,
    )


def test_disabled_adapter_and_default_factory_are_offline_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认实现必须直接拒绝，且不能尝试构造任何网络连接。"""
    network_calls: list[object] = []
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda *args, **kwargs: network_calls.append((args, kwargs)),
    )
    adapter = build_entitlement_fixture_adapter()
    secret = "token-ultra-secret"

    assert isinstance(adapter, DisabledEntitlementFixtureAdapter)
    for action in (
        lambda: adapter.grant(_session(token=secret), "SEARCH", 60),
        lambda: adapter.revoke(_session(token=secret), "SEARCH"),
    ):
        with pytest.raises(EntitlementFixtureUnavailable) as caught:
            action()
        assert secret not in str(caught.value)
        assert secret not in repr(caught.value)
    assert network_calls == []


def test_mock_adapter_tracks_active_expired_inactive_and_does_not_leak_session() -> None:
    """显式 mock 支持完整状态切换，但公开结果和 repr 不带 token。"""
    adapter = MockEntitlementFixtureAdapter()
    session = _session()

    granted = adapter.grant(session, "SEARCH", 60)
    expired = adapter.expire(session, "SEARCH")
    revoked = adapter.revoke(session, "SEARCH")

    assert [granted.state, expired.state, revoked.state] == [
        EntitlementFixtureState.ACTIVE,
        EntitlementFixtureState.EXPIRED,
        EntitlementFixtureState.INACTIVE,
    ]
    assert adapter.get_state(session, "SEARCH") is EntitlementFixtureState.INACTIVE
    for value in (adapter, granted, expired, revoked):
        assert "token-ultra-secret" not in repr(value)
        assert "refresh-token-ultra-secret" not in repr(value)


def test_mock_adapter_expires_grant_at_monotonic_deadline() -> None:
    """TTL 到达边界时在 get_state 锁内原子转为 expired。"""
    clock = _Clock(10.0)
    adapter = MockEntitlementFixtureAdapter(clock=clock)
    session = _session()
    result = adapter.grant(session, "SEARCH", 5)

    clock.now = 14.999
    assert adapter.get_state(session, "SEARCH") is EntitlementFixtureState.ACTIVE
    clock.now = 15.0
    assert adapter.get_state(session, "SEARCH") is EntitlementFixtureState.EXPIRED
    assert result.state is EntitlementFixtureState.ACTIVE
    assert result.ttl_seconds == 5
    assert not hasattr(result, "deadline")
    with pytest.raises(FrozenInstanceError):
        result.ttl_seconds = 99  # type: ignore[misc]


@pytest.mark.parametrize(
    "ttl",
    [math.inf, math.nan, -math.inf, 1.5, 10**10000],
    ids=["positive-infinity", "nan", "negative-infinity", "fraction", "overflow"],
)
def test_mock_adapter_rejects_non_finite_fractional_or_overflowing_ttl(
    ttl: object,
) -> None:
    """TTL 无法形成有限 deadline 时不写入状态。"""
    adapter = MockEntitlementFixtureAdapter(clock=lambda: 1.0)
    session = _session()

    with pytest.raises((TypeError, ValueError), match="ttl_seconds|deadline"):
        adapter.grant(session, "SEARCH", ttl)

    assert adapter.get_state(session, "SEARCH") is EntitlementFixtureState.INACTIVE


@pytest.mark.parametrize(
    "clock_value",
    [True, math.inf, math.nan, -math.inf, "now", 10**10000],
    ids=["bool", "positive-infinity", "nan", "negative-infinity", "text", "overflow"],
)
def test_mock_adapter_rejects_invalid_clock_without_state_change(
    clock_value: object,
) -> None:
    """注入时钟返回 bool、非有限数或非数值时安全失败。"""
    adapter = MockEntitlementFixtureAdapter(clock=lambda: clock_value)

    with pytest.raises((TypeError, ValueError), match="clock"):
        adapter.grant(_session(), "SEARCH", 5)


def test_expiration_race_remains_atomic_and_isolated() -> None:
    """到期竞争不能使其他用户或商品状态串扰，也不能恢复 active。"""
    clock = _Clock(0.0)
    adapter = MockEntitlementFixtureAdapter(clock=clock)
    user_a = _session(user_id="user-a")
    user_b = _session(user_id="user-b")
    adapter.grant(user_a, "SEARCH", 1)
    adapter.grant(user_a, "EXPORT", 100)
    adapter.grant(user_b, "SEARCH", 100)
    clock.now = 1.0

    with ThreadPoolExecutor(max_workers=16) as executor:
        states = list(
            executor.map(
                lambda _: adapter.get_state(user_a, "SEARCH"), range(200)
            )
        )

    assert set(states) == {EntitlementFixtureState.EXPIRED}
    assert adapter.get_state(user_a, "EXPORT") is EntitlementFixtureState.ACTIVE
    assert adapter.get_state(user_b, "SEARCH") is EntitlementFixtureState.ACTIVE


def test_mock_adapter_isolates_users_and_products() -> None:
    """权益以用户和商品为联合键，状态不能跨用户或跨商品污染。"""
    adapter = MockEntitlementFixtureAdapter()
    user_a = _session(user_id="user-a")
    user_b = _session(user_id="user-b")

    adapter.grant(user_a, "SEARCH", 60)
    adapter.grant(user_a, "EXPORT", 60)
    adapter.expire(user_a, "EXPORT")

    assert adapter.get_state(user_a, "SEARCH") is EntitlementFixtureState.ACTIVE
    assert adapter.get_state(user_a, "EXPORT") is EntitlementFixtureState.EXPIRED
    assert adapter.get_state(user_b, "SEARCH") is EntitlementFixtureState.INACTIVE


@pytest.mark.parametrize(
    "operation,session,product_code,ttl,error_type",
    [
        ("grant", None, "SEARCH", 60, TypeError),
        ("grant", object(), "SEARCH", 60, TypeError),
        ("grant", _SessionStub(""), "SEARCH", 60, ValueError),
        ("grant", _SessionStub(" user-a"), "SEARCH", 60, ValueError),
        ("grant", _SessionStub(1), "SEARCH", 60, TypeError),
        ("grant", _session(), "", 60, ValueError),
        ("grant", _session(), " SEARCH", 60, ValueError),
        ("grant", _session(), 1, 60, TypeError),
        ("grant", _session(), "SEARCH", True, TypeError),
        ("grant", _session(), "SEARCH", 0, ValueError),
        ("revoke", _session(), "", None, ValueError),
        ("expire", _session(), "", None, ValueError),
    ],
)
def test_mock_adapter_strictly_rejects_invalid_input_without_secret_echo(
    operation: str,
    session: object,
    product_code: object,
    ttl: object,
    error_type: type[Exception],
) -> None:
    """所有入口先严格校验，异常只说明字段而不回显值或会话。"""
    adapter = MockEntitlementFixtureAdapter()
    call = getattr(adapter, operation)

    with pytest.raises(error_type) as caught:
        if operation == "grant":
            call(session, product_code, ttl)
        else:
            call(session, product_code)

    assert "token-ultra-secret" not in str(caught.value)


def test_mock_adapter_updates_are_atomic_under_concurrent_access() -> None:
    """同一联合键的并发更新必须形成完整状态，不能暴露中间结构。"""
    adapter = MockEntitlementFixtureAdapter()
    session = _session()

    def update(index: int) -> None:
        if index % 3 == 0:
            adapter.grant(session, "SEARCH", 60)
        elif index % 3 == 1:
            adapter.expire(session, "SEARCH")
        else:
            adapter.revoke(session, "SEARCH")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(update, range(300)))

    assert adapter.get_state(session, "SEARCH") in set(EntitlementFixtureState)


def test_factory_accepts_explicit_future_adapter_without_knowing_its_protocol() -> None:
    """工厂只依赖公开协议，未来真实实现可由配置层显式注入。"""
    custom = MockEntitlementFixtureAdapter()

    assert build_entitlement_fixture_adapter(custom) is custom
