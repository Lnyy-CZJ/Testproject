"""可替换的外部测试能力适配器。"""

from framework.adapters.entitlement_fixture import (
    DisabledEntitlementFixtureAdapter,
    EntitlementFixtureAdapter,
    EntitlementFixtureResult,
    EntitlementFixtureState,
    EntitlementFixtureUnavailable,
    MockEntitlementFixtureAdapter,
    build_entitlement_fixture_adapter,
)

__all__ = [
    "DisabledEntitlementFixtureAdapter",
    "EntitlementFixtureAdapter",
    "EntitlementFixtureResult",
    "EntitlementFixtureState",
    "EntitlementFixtureUnavailable",
    "MockEntitlementFixtureAdapter",
    "build_entitlement_fixture_adapter",
]
