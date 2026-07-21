"""Pytest 层危险 marker 默认保护测试。"""

from typing import Any
from types import SimpleNamespace

import conftest as project_conftest
import pytest

from framework.adapters.entitlement_fixture import (
    DisabledEntitlementFixtureAdapter,
    EntitlementFixtureUnavailable,
)
from framework.config import Settings
from framework.models.envelope import GatewayResponse


class _FakeConfig:
    """按参数名返回布尔开关的最小 Pytest 配置替身。"""

    def __init__(self, *, run_dangerous: bool, run_live_safe: bool = False) -> None:
        self.options = {
            "--run-dangerous": run_dangerous,
            "--run-live-safe": run_live_safe,
            "--env": "test",
        }

    def getoption(self, name: str) -> Any:
        return self.options[name]


class _FakeItem:
    """记录 collection 钩子追加 marker 的最小测试项替身。"""

    def __init__(self, *keywords: str) -> None:
        self.keywords = {keyword: True for keyword in keywords}
        self.added_markers: list[Any] = []
        self.user_properties: list[tuple[str, str]] = [
            ("markers", "stale duplicate"),
            ("safe_property", "retained"),
        ]

    def add_marker(self, marker: Any) -> None:
        self.added_markers.append(marker)

    def iter_markers(self) -> list[Any]:
        return [SimpleNamespace(name=name) for name in self.keywords]


class _FakeRequest:
    """模拟 fixture request，仅暴露测试 marker 查询。"""

    class _Node:
        def __init__(self, is_live_safe: bool) -> None:
            self.is_live_safe = is_live_safe

        def get_closest_marker(self, name: str) -> object | None:
            if name == "live_safe" and self.is_live_safe:
                return object()
            return None

    def __init__(self, *, is_live_safe: bool) -> None:
        self.node = self._Node(is_live_safe)


def test_direct_pytest_skips_payment_and_destructive_by_default() -> None:
    payment = _FakeItem("payment_real")
    destructive = _FakeItem("destructive")
    safe = _FakeItem("contract")

    project_conftest.pytest_collection_modifyitems(
        _FakeConfig(run_dangerous=False),
        [payment, destructive, safe],
    )

    assert len(payment.added_markers) == 1
    assert len(destructive.added_markers) == 1
    assert safe.added_markers == []


def test_collection_records_unique_marker_property_for_junit_and_xdist() -> None:
    item = _FakeItem("p0", "smoke", "p0")

    project_conftest.pytest_collection_modifyitems(
        _FakeConfig(run_dangerous=False), [item]
    )
    project_conftest.pytest_collection_modifyitems(
        _FakeConfig(run_dangerous=False), [item]
    )

    marker_properties = [value for name, value in item.user_properties if name == "markers"]
    assert marker_properties == ["p0 smoke"]
    assert ("safe_property", "retained") in item.user_properties


def test_live_safe_does_not_unlock_dangerous_markers() -> None:
    dangerous = _FakeItem("live_safe", "destructive")

    project_conftest.pytest_collection_modifyitems(
        _FakeConfig(run_dangerous=False, run_live_safe=True),
        [dangerous],
    )

    assert len(dangerous.added_markers) == 1


def test_run_dangerous_explicitly_unlocks_dangerous_markers() -> None:
    dangerous = _FakeItem("payment_real")

    project_conftest.pytest_collection_modifyitems(
        _FakeConfig(run_dangerous=True),
        [dangerous],
    )

    assert dangerous.added_markers == []


def test_live_write_without_destructive_marker_is_rejected() -> None:
    unsafe_write = _FakeItem("live_write")

    with pytest.raises(pytest.UsageError, match="destructive"):
        project_conftest.pytest_collection_modifyitems(
            _FakeConfig(run_dangerous=False), [unsafe_write]
        )


def test_live_safe_settings_use_distinct_case_devices(monkeypatch: Any) -> None:
    """两个 live_safe 用例应派生不同设备，且保留配置设备 ID 作为前缀。"""
    monkeypatch.setattr(
        project_conftest,
        "load_config",
        lambda _env: Settings(device_id="autotest-device-test"),
    )
    config = _FakeConfig(run_dangerous=False, run_live_safe=True)

    first = project_conftest.settings.__wrapped__(
        config, _FakeRequest(is_live_safe=True)
    )
    second = project_conftest.settings.__wrapped__(
        config, _FakeRequest(is_live_safe=True)
    )

    assert first.device_id.startswith("autotest-device-test-")
    assert second.device_id.startswith("autotest-device-test-")
    assert first.device_id != second.device_id


class _AnonymousIdentityService:
    """为匿名会话 fixture 返回不含真实凭据的离线成功响应。"""

    def __init__(self) -> None:
        self.client_request_ids: list[str] = []

    def create_anonymous_session(
        self, *, consent_policy_version: str, client_request_id: str
    ) -> GatewayResponse:
        assert consent_policy_version == "2026-06-01"
        self.client_request_ids.append(client_request_id)
        response = GatewayResponse.model_validate(
            {
                "code": 0,
                "message": "OK",
                "request_id": "gw-fixture",
                "trace_id": "trace-fixture",
                "responses": [
                    {
                        "id": "req_0",
                        "code": 0,
                        "success": True,
                        "data": {
                            "user_id": "user-placeholder",
                            "access_token": "access-placeholder",
                            "expires_time": 1000,
                            "refresh_token": "refresh-placeholder",
                            "refresh_expires_time": 2000,
                            "is_new_user": True,
                        },
                    }
                ],
            }
        )
        response.http_status = 200
        return response


def test_anonymous_session_fixture_skips_without_live_safe_flag() -> None:
    with pytest.raises(pytest.skip.Exception, match="--run-live-safe"):
        project_conftest.anonymous_session.__wrapped__(
            _FakeRequest(is_live_safe=True),
            _FakeConfig(run_dangerous=False, run_live_safe=False),
            Settings(device_id="device-placeholder"),
            _AnonymousIdentityService(),
        )


def test_anonymous_session_fixture_builds_context_only_when_explicitly_enabled() -> None:
    identity_service = _AnonymousIdentityService()
    context = project_conftest.anonymous_session.__wrapped__(
        _FakeRequest(is_live_safe=True),
        _FakeConfig(run_dangerous=False, run_live_safe=True),
        Settings(device_id="device-placeholder"),
        identity_service,
    )

    assert context.device_id == "device-placeholder"
    assert context.user_id == "user-placeholder"
    assert context.access_token == "access-placeholder"
    assert identity_service.client_request_ids[0].startswith("autotest-anonymous-")


def test_anonymous_session_fixture_rejects_non_live_safe_consumer() -> None:
    with pytest.raises(pytest.UsageError, match="live_safe"):
        project_conftest.anonymous_session.__wrapped__(
            _FakeRequest(is_live_safe=False),
            _FakeConfig(run_dangerous=False, run_live_safe=True),
            Settings(device_id="device-placeholder"),
            _AnonymousIdentityService(),
        )


def test_entitlement_adapter_fixture_defaults_to_disabled_offline_implementation() -> None:
    """普通测试拿到禁用适配器，不能因环境变量而意外启用真实夹具。"""
    adapter = project_conftest.entitlement_adapter.__wrapped__()

    assert isinstance(adapter, DisabledEntitlementFixtureAdapter)
    with pytest.raises(EntitlementFixtureUnavailable):
        adapter.grant(object(), "people_insight", 60)


def test_live_entitlement_fixture_explicitly_skips_without_confirmed_protocol() -> None:
    """即使危险开关开启，缺少真实协议和凭据也必须给出明确 skip。"""
    with pytest.raises(pytest.skip.Exception, match="协议/凭据"):
        project_conftest.live_entitlement_adapter.__wrapped__()
