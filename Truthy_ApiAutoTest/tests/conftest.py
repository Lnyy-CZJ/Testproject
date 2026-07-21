"""项目通用 Pytest 参数、安全 marker 策略与业务 fixture。"""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from framework.client.gateway_client import GatewayClient
from framework.adapters.entitlement_fixture import (
    DisabledEntitlementFixtureAdapter,
    EntitlementFixtureAdapter,
)
from framework.assertions.gateway_assert import assert_business_success
from framework.config import Settings, load_config
from framework.data.context import SessionContext
from services.billing_service import BillingService
from services.home_service import HomeService
from services.identity_service import IdentityService
from services.subscription_service import SubscriptionService


def pytest_addoption(parser: pytest.Parser) -> None:
    """注册环境与安全联调开关。

    参数说明:
        parser: Pytest 命令行解析器。
    返回值:
        无。
    异常说明:
        重复注册同名参数时由 Pytest 抛出配置异常。
    """
    parser.addoption("--env", action="store", default="test", help="运行环境配置名")
    parser.addoption(
        "--run-live-safe",
        action="store_true",
        default=False,
        help="显式运行已授权的只读安全联调用例",
    )
    parser.addoption(
        "--run-dangerous",
        action="store_true",
        default=False,
        help="显式授权 payment_real 和 destructive 危险用例",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """默认跳过真实联调与危险用例，防止意外联网或产生副作用。

    参数说明:
        config: 当前 Pytest 配置；items: 已收集测试项。
    返回值:
        无；直接为未显式授权的真实联调或危险用例追加 skip marker。
    异常说明:
        本钩子不主动抛出异常。
    """
    allow_live_safe = config.getoption("--run-live-safe")
    allow_dangerous = config.getoption("--run-dangerous")
    live_marker = pytest.mark.skip(reason="需显式传入 --run-live-safe 才运行真实安全联调")
    dangerous_marker = pytest.mark.skip(
        reason="需显式传入 --run-dangerous 才运行 payment_real/destructive 用例"
    )
    for item in items:
        # JUnit 的 user_properties 可被 xdist 序列化；先移除旧值再写入排序后的唯一值，
        # 防止插件或重复调用 collection hook 产生多个 markers 属性。
        marker_names = sorted({marker.name for marker in item.iter_markers()})
        item.user_properties[:] = [
            (name, value)
            for name, value in item.user_properties
            if name != "markers"
        ]
        item.user_properties.append(("markers", " ".join(marker_names)))
        if "live_write" in item.keywords and "destructive" not in item.keywords:
            raise pytest.UsageError(
                f"真实写测试必须同时标记 live_write 和 destructive: {item}"
            )
        if "live_safe" in item.keywords and not allow_live_safe:
            item.add_marker(live_marker)
        if (
            "payment_real" in item.keywords or "destructive" in item.keywords
        ) and not allow_dangerous:
            item.add_marker(dangerous_marker)


@pytest.fixture
def settings(pytestconfig: pytest.Config, request: pytest.FixtureRequest) -> Settings:
    """加载环境配置，并为每个 live_safe 用例派生独立设备 ID。

    参数说明:
        pytestconfig: 当前 Pytest 配置；request: 用于读取当前用例 marker。
    返回值:
        当前用例的 :class:`Settings`；普通离线用例保留配置设备 ID，live_safe
        用例使用 ``配置前缀 + UUID``，同一用例内所有 Service 共享该实例。
    异常说明:
        配置文件或值无效时抛出加载/校验异常。
    """
    configured = load_config(pytestconfig.getoption("--env"))
    if request.node.get_closest_marker("live_safe") is None:
        return configured
    prefix = configured.device_id.rstrip("-") or "autotest-device"
    return configured.model_copy(update={"device_id": f"{prefix}-{uuid4().hex}"})


@pytest.fixture
def gateway_client(settings: Settings) -> Iterator[GatewayClient]:
    """创建 function-scope Gateway 客户端。

    参数说明:
        settings: 当前会话环境配置。
    返回值:
        通过 yield 提供客户端，并在用例结束后关闭 HTTP 会话。
    异常说明:
        客户端构造或会话关闭异常原样抛出。
    """
    client = GatewayClient(settings)
    yield client
    session = getattr(client, "_session", None)
    close = getattr(session, "close", None)
    if callable(close):
        close()


@pytest.fixture
def home_service(gateway_client: GatewayClient) -> HomeService:
    """构造 Home 业务 Service。

    参数说明:
        gateway_client: function-scope Gateway 客户端。
    返回值:
        仅封装 Home 业务参数的 Service 实例。
    异常说明:
        本 fixture 不主动抛出异常。
    """
    return HomeService(gateway_client)


@pytest.fixture
def identity_service(gateway_client: GatewayClient) -> IdentityService:
    """构造只委托统一 Gateway 客户端的 Identity Service。

    参数说明:
        gateway_client: function-scope Gateway 客户端。
    返回值:
        :class:`IdentityService` 实例。
    异常说明:
        本 fixture 不主动抛出异常。
    """
    return IdentityService(gateway_client)


@pytest.fixture
def subscription_service(gateway_client: GatewayClient) -> SubscriptionService:
    """构造正常订阅流程使用的 Subscription Service。

    参数说明:
        gateway_client: function-scope Gateway 客户端。
    返回值:
        :class:`SubscriptionService` 实例。
    异常说明:
        本 fixture 不主动抛出异常。
    """
    return SubscriptionService(gateway_client)


@pytest.fixture
def billing_service(gateway_client: GatewayClient) -> BillingService:
    """构造独立底层订单 Billing Service，不与订阅 fixture 混用。

    参数说明:
        gateway_client: function-scope Gateway 客户端。
    返回值:
        :class:`BillingService` 实例。
    异常说明:
        本 fixture 不主动抛出异常。
    """
    return BillingService(gateway_client)


@pytest.fixture
def entitlement_adapter() -> EntitlementFixtureAdapter:
    """提供默认禁用且零网络的权益夹具适配器。

    返回值:
        :class:`DisabledEntitlementFixtureAdapter`；离线测试需要状态控制时必须在
        用例中显式构造 ``MockEntitlementFixtureAdapter``，不能隐式切换实现。
    异常说明:
        实际调用发放或撤销时抛 ``EntitlementFixtureUnavailable``。
    """
    return DisabledEntitlementFixtureAdapter()


@pytest.fixture
def live_entitlement_adapter() -> EntitlementFixtureAdapter:
    """为未来真实权益夹具保留入口，当前因协议和凭据未确认而明确跳过。

    返回值:
        当前永不返回；待后端确认真实协议且安全配置凭据后再接入具体实现。
    异常说明:
        无论危险开关状态均调用 ``pytest.skip``，防止根据猜测执行真实写入。
    """
    pytest.skip("真实权益夹具协议/凭据未配置")


@pytest.fixture
def anonymous_session(
    request: pytest.FixtureRequest,
    pytestconfig: pytest.Config,
    settings: Settings,
    identity_service: IdentityService,
) -> SessionContext:
    """仅在显式 live_safe 模式创建一次函数级匿名会话。

    功能说明:
        未提供 ``--run-live-safe`` 时在任何网络调用前主动跳过；显式启用后调用
        CreateAnonymousSession，执行统一双层成功断言并构造内存会话上下文。
    参数说明:
        request: 用于确认消费测试带 ``live_safe`` marker；pytestconfig: 用于读取
        安全开关；settings: 提供当前 ``device_id``；identity_service: 统一身份 Service。
    返回值:
        与当前设备绑定、仅供当前 live_safe 用例使用的 :class:`SessionContext`。
    异常说明:
        非 live_safe 测试误用时抛出 ``UsageError``，未授权时触发 Pytest skip；
        环境不可达、协议或业务失败时异常原样失败。
    """
    if request.node.get_closest_marker("live_safe") is None:
        raise pytest.UsageError("anonymous_session 仅供 live_safe 测试使用")
    if not pytestconfig.getoption("--run-live-safe"):
        pytest.skip("匿名会话 fixture 需显式传入 --run-live-safe")
    data = assert_business_success(
        identity_service.create_anonymous_session(
            consent_policy_version="2026-06-01",
            client_request_id=f"autotest-anonymous-{uuid4().hex}",
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
    return SessionContext.from_anonymous_session(
        device_id=settings.device_id,
        data=data,
    )
