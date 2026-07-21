"""短期测试权益夹具协议、禁用实现与离线内存实现。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from threading import RLock
import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from framework.data.context import SessionContext


class EntitlementFixtureUnavailable(RuntimeError):
    """权益夹具未配置时的安全异常。

    功能说明:
        表示真实权益协议或凭据不可用，消息不得包含会话或凭据。
    参数说明:
        继承 ``RuntimeError`` 的安全错误消息参数。
    返回值:
        无；该类型仅用于异常传播。
    异常说明:
        本类型自身不额外抛出异常。
    """


class EntitlementFixtureState(str, Enum):
    """离线权益夹具允许的三种状态。

    功能说明:
        统一表示 active、expired 与 inactive 状态。
    参数说明:
        无；枚举成员固定定义。
    返回值:
        枚举成员可作为字符串状态使用。
    异常说明:
        非法枚举值构造时由 ``Enum`` 抛出 ``ValueError``。
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class EntitlementFixtureResult:
    """不含 session、token、用户标识或真实夹具响应的操作结果。

    功能说明:
        保存不含 session、token、用户标识或真实夹具响应的操作结果。
    参数说明:
        product_code: 调用方提供的商品编码；state: 操作后的状态；ttl_seconds:
        发放时的短期有效秒数，撤销或显式过期时为 ``None``。
    返回值:
        实例作为发放、撤销或过期操作的安全结果。
    异常说明:
        数据类构造不主动校验，输入约束由适配器方法负责。
    """

    product_code: str
    state: EntitlementFixtureState
    ttl_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class _EntitlementRecord:
    """锁保护的内部状态与有限单调截止时间。"""

    state: EntitlementFixtureState
    deadline: float | None


@runtime_checkable
class EntitlementFixtureAdapter(Protocol):
    """阶段4依赖的最小权益夹具接口。

    功能说明:
        以当前内存会话和商品编码发放或撤销短期测试权益；接口不规定任何真实
        HTTP URL、鉴权头或请求字段，未来实现通过工厂显式注入。
    参数说明:
        无构造参数要求；实现类需提供 ``grant`` 与 ``revoke``。
    返回值:
        仅返回不含凭据的 :class:`EntitlementFixtureResult`。
    异常说明:
        未配置实现抛 :class:`EntitlementFixtureUnavailable`；具体实现的输入或
        外部调用异常遵循其自身契约，但不得泄露 session/token。
    """

    def grant(
        self, session: SessionContext, product_code: str, ttl_seconds: int
    ) -> EntitlementFixtureResult:
        """发放短期测试权益。

        功能说明:
            为指定会话和商品发放有限时长的测试权益。
        参数说明:
            session: 当前内存会话；product_code: 商品编码；ttl_seconds: 有效秒数。
        返回值:
            不含凭据的权益操作结果。
        异常说明:
            禁用实现抛 ``EntitlementFixtureUnavailable``；其他实现按自身契约校验。
        """
        ...

    def revoke(
        self, session: SessionContext, product_code: str
    ) -> EntitlementFixtureResult:
        """撤销测试权益。

        功能说明:
            将指定会话和商品的测试权益置为不可用。
        参数说明:
            session: 当前内存会话；product_code: 商品编码。
        返回值:
            不含凭据的权益操作结果。
        异常说明:
            禁用实现抛 ``EntitlementFixtureUnavailable``；其他实现按自身契约校验。
        """
        ...


class DisabledEntitlementFixtureAdapter:
    """默认禁用实现。

    功能说明:
        所有操作始终在本地安全失败，绝不执行网络调用。
    参数说明:
        无。
    返回值:
        无操作可成功返回。
    异常说明:
        ``grant`` 与 ``revoke`` 始终抛 ``EntitlementFixtureUnavailable``。
    """

    _MESSAGE = "真实权益夹具未配置协议或凭据"

    def grant(
        self, session: SessionContext, product_code: str, ttl_seconds: int
    ) -> EntitlementFixtureResult:
        """拒绝发放权益。

        功能说明:
            不读取参数并立即本地失败，避免意外连接或秘密回显。
        参数说明:
            session/product_code/ttl_seconds: 为兼容协议保留，均不会被读取。
        返回值:
            不返回结果。
        异常说明:
            始终抛 ``EntitlementFixtureUnavailable``。
        """
        raise EntitlementFixtureUnavailable(self._MESSAGE)

    def revoke(
        self, session: SessionContext, product_code: str
    ) -> EntitlementFixtureResult:
        """拒绝撤销权益。

        功能说明:
            不读取参数并立即本地失败，避免意外连接或秘密回显。
        参数说明:
            session/product_code: 为兼容协议保留，均不会被读取。
        返回值:
            不返回结果。
        异常说明:
            始终抛 ``EntitlementFixtureUnavailable``。
        """
        raise EntitlementFixtureUnavailable(self._MESSAGE)


class MockEntitlementFixtureAdapter:
    """线程安全的用户/商品隔离内存权益状态机。

    功能说明:
        仅以 ``session.user_id + product_code`` 作为内存联合键，支持发放、撤销、
        显式过期和读取状态；active 记录有限单调截止时间，到期读取时原子转为
        expired。不读取 token、不联网，也不模拟真实 HTTP 协议。
    参数说明:
        clock: 可选单调时钟，默认使用 ``time.monotonic``。
    返回值:
        修改方法返回不含联合键中用户部分的安全结果；未设置状态读取为 inactive。
    异常说明:
        session/user/product/ttl 类型或边界无效时抛 ``TypeError``/``ValueError``，
        异常只包含字段约束，不回显传入值。
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        """构造内存适配器并注入可测试的单调时钟。

        参数说明:
            clock: 返回有限非 bool 数值的单调时钟；默认使用 ``time.monotonic``。
        异常说明:
            时钟只在 grant 或读取 active 状态时调用，无效值或回退安全失败。
        """
        self._states: dict[tuple[str, str], _EntitlementRecord] = {}
        self._lock = RLock()
        self._clock = clock
        self._last_clock: float | None = None

    def grant(
        self, session: SessionContext, product_code: str, ttl_seconds: int
    ) -> EntitlementFixtureResult:
        """原子发放内存权益。

        功能说明:
            将指定用户商品置为 active，并记录安全 TTL 截止时间。
        参数说明:
            session: 含用户 ID 的会话；product_code: 商品编码；ttl_seconds: 正整数秒数。
        返回值:
            状态为 active 且含 TTL 的安全结果。
        异常说明:
            联合键、TTL 或单调时钟无效时抛 ``TypeError``/``ValueError``。
        """
        key = self._validated_key(session, product_code)
        ttl = self._validate_ttl(ttl_seconds)
        with self._lock:
            now = self._read_clock_locked()
            try:
                deadline = now + float(ttl)
            except (OverflowError, ValueError):
                raise ValueError("ttl_seconds 无法形成有限 deadline") from None
            if not math.isfinite(deadline):
                raise ValueError("ttl_seconds 无法形成有限 deadline")
            self._states[key] = _EntitlementRecord(
                EntitlementFixtureState.ACTIVE, deadline
            )
        return EntitlementFixtureResult(product_code, EntitlementFixtureState.ACTIVE, ttl)

    def revoke(
        self, session: SessionContext, product_code: str
    ) -> EntitlementFixtureResult:
        """原子撤销内存权益。

        功能说明:
            将指定用户商品置为 inactive。
        参数说明:
            session: 含用户 ID 的会话；product_code: 商品编码。
        返回值:
            状态为 inactive 的安全结果。
        异常说明:
            联合键无效时抛 ``TypeError``/``ValueError``。
        """
        return self._set_state(session, product_code, EntitlementFixtureState.INACTIVE)

    def expire(
        self, session: SessionContext, product_code: str
    ) -> EntitlementFixtureResult:
        """显式过期内存权益。

        功能说明:
            测试专用地将指定用户商品置为 expired，不模拟真实后台协议。
        参数说明:
            session: 含用户 ID 的会话；product_code: 商品编码。
        返回值:
            状态为 expired 的安全结果。
        异常说明:
            联合键无效时抛 ``TypeError``/``ValueError``。
        """
        return self._set_state(session, product_code, EntitlementFixtureState.EXPIRED)

    def get_state(
        self, session: SessionContext, product_code: str
    ) -> EntitlementFixtureState:
        """原子读取内存权益状态。

        功能说明:
            读取指定联合键，到期 active 会原子转为 expired；未发放时返回 inactive。
        参数说明:
            session: 含用户 ID 的会话；product_code: 商品编码。
        返回值:
            当前 ``EntitlementFixtureState``。
        异常说明:
            联合键、时钟或内部 active 记录无效时抛出对应安全异常。
        """
        key = self._validated_key(session, product_code)
        with self._lock:
            record = self._states.get(key)
            if record is None:
                return EntitlementFixtureState.INACTIVE
            if record.state is EntitlementFixtureState.ACTIVE:
                now = self._read_clock_locked()
                if record.deadline is None:
                    raise RuntimeError("active 权益缺少内部 deadline")
                if now >= record.deadline:
                    record = _EntitlementRecord(
                        EntitlementFixtureState.EXPIRED, None
                    )
                    self._states[key] = record
            return record.state

    def _set_state(
        self,
        session: SessionContext,
        product_code: str,
        state: EntitlementFixtureState,
    ) -> EntitlementFixtureResult:
        """校验联合键后在同一个锁范围内完成状态更新。"""
        key = self._validated_key(session, product_code)
        with self._lock:
            self._states[key] = _EntitlementRecord(state, None)
        return EntitlementFixtureResult(product_code, state)

    def _read_clock_locked(self) -> float:
        """在锁内读取并验证有限、非回退的单调时钟值。"""
        try:
            raw = self._clock()
        except Exception as exc:  # noqa: BLE001 - 注入时钟异常消息可能含秘密
            raise ValueError(f"clock 读取失败: {type(exc).__name__}") from None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise TypeError("clock 必须返回有限非 bool 数值")
        try:
            value = float(raw)
        except (OverflowError, ValueError):
            raise ValueError("clock 必须返回有限数值") from None
        if not math.isfinite(value):
            raise ValueError("clock 必须返回有限数值")
        if self._last_clock is not None and value < self._last_clock:
            raise ValueError("clock 单调值发生回退")
        self._last_clock = value
        return value

    @staticmethod
    def _validated_key(
        session: SessionContext, product_code: str
    ) -> tuple[str, str]:
        """生成严格的内存联合键，任何失败均不回显输入对象。"""
        try:
            user_id = session.user_id
        except Exception:  # noqa: BLE001 - 自定义 session 属性异常也必须脱敏
            raise TypeError("session 必须提供非空字符串 user_id") from None
        if type(user_id) is not str:
            raise TypeError("session 必须提供非空字符串 user_id")
        if not user_id or user_id != user_id.strip():
            raise ValueError("session.user_id 必须是无首尾空白的非空字符串")
        if type(product_code) is not str:
            raise TypeError("product_code 必须是字符串")
        if not product_code or product_code != product_code.strip():
            raise ValueError("product_code 必须是无首尾空白的非空字符串")
        return user_id, product_code

    @staticmethod
    def _validate_ttl(ttl_seconds: int) -> int:
        """要求 TTL 为排除 bool 的正整数。"""
        if type(ttl_seconds) is not int:
            raise TypeError("ttl_seconds 必须是非 bool 整数")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        return ttl_seconds


def build_entitlement_fixture_adapter(
    configured_adapter: EntitlementFixtureAdapter | None = None,
) -> EntitlementFixtureAdapter:
    """返回显式注入的实现，否则返回安全禁用实现。

    功能说明:
        选择显式适配器，否则创建安全禁用实现。
    参数说明:
        configured_adapter: 配置层未来构造的真实实现或测试显式提供的 mock；本
        工厂不解析 URL、凭据，也不猜测真实 HTTP 请求协议。
    返回值:
        注入实现本身，或 :class:`DisabledEntitlementFixtureAdapter`。
    异常说明:
        本工厂不主动调用适配器；实现不符合协议时在实际消费点自然失败。
    """
    if configured_adapter is not None:
        return configured_adapter
    return DisabledEntitlementFixtureAdapter()
