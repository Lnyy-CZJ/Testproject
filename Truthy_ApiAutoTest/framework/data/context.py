"""单个测试用例的动态数据上下文。"""

from dataclasses import dataclass, field
from typing import Any, ClassVar


_TOKEN_FIELDS = (
    "access_token",
    "expires_time",
    "refresh_token",
    "refresh_expires_time",
)


def _validate_non_empty_string(name: str, value: Any) -> str:
    """校验会话标识或 token 是非空字符串。

    参数说明:
        name: 用于异常定位的字段名；value: 待校验值。
    返回值:
        类型和值均有效的原字符串。
    异常说明:
        非字符串抛出 ``TypeError``，空字符串抛出 ``ValueError``。
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} 必须是字符串")
    if not value:
        raise ValueError(f"{name} 不能为空")
    return value


def _validate_strict_timestamp(name: str, value: Any) -> int:
    """校验会话过期时间是排除布尔值的严格整数。

    参数说明:
        name: 用于异常定位的字段名；value: 待校验时间戳。
    返回值:
        严格整数时间戳。
    异常说明:
        布尔值、字符串或其他非整数类型抛出 ``TypeError``。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 必须是整数时间戳")
    return value


def _validated_token_values(data: dict[str, Any]) -> tuple[str, int, str, int]:
    """完整校验 token 数据并返回可一次性赋值的不可变元组。

    参数说明:
        data: RefreshSession 或匿名会话业务 ``data`` 对象。
    返回值:
        access token、其过期时间、refresh token、其过期时间。
    异常说明:
        字段缺失抛出 ``KeyError``；token 空值或过期时间类型错误抛出
        ``ValueError``/``TypeError``。校验期间不修改任何上下文。
    """
    values = tuple(data[field] for field in _TOKEN_FIELDS)
    access_token, expires_time, refresh_token, refresh_expires_time = values
    return (
        _validate_non_empty_string("access_token", access_token),
        _validate_strict_timestamp("expires_time", expires_time),
        _validate_non_empty_string("refresh_token", refresh_token),
        _validate_strict_timestamp("refresh_expires_time", refresh_expires_time),
    )


@dataclass(slots=True)
class SessionContext:
    """保存同一设备和用户的最新内存会话。

    功能说明:
        维护 ``device_id + user_id + 最新 access_token`` 归属关系和刷新数据；
        ``user_id`` 仅用于本地断言，Service 不会把它写入 Gateway ``comm``。
    参数说明:
        device_id/user_id: 同一匿名会话的设备与用户标识；token 和过期时间均
        来自同一次成功响应；is_new_user: 创建匿名会话时的服务端标志。
    返回值:
        通过属性提供当前会话，``replace_tokens`` 原子更新 token 数据。
    异常说明:
        构建辅助方法或刷新收到不完整、空值、错误类型时抛出校验异常。
    """

    device_id: str = field(repr=False)
    user_id: str = field(repr=False)
    access_token: str = field(repr=False)
    expires_time: int
    refresh_token: str = field(repr=False)
    refresh_expires_time: int
    is_new_user: bool | None = None

    def __post_init__(self) -> None:
        """统一校验所有直接或工厂构造的会话核心字段。

        参数说明:
            使用当前实例的设备、用户、token 与过期时间字段，无额外参数。
        返回值:
            无；所有字段有效时完成构造。
        异常说明:
            标识/token 非空字符串约束或严格整数时间戳约束不满足时，抛出
            ``TypeError``/``ValueError``，实例不会交付给调用方。
        """
        _validate_non_empty_string("device_id", self.device_id)
        _validate_non_empty_string("user_id", self.user_id)
        _validated_token_values(
            {
                "access_token": self.access_token,
                "expires_time": self.expires_time,
                "refresh_token": self.refresh_token,
                "refresh_expires_time": self.refresh_expires_time,
            }
        )

    @classmethod
    def from_anonymous_session(
        cls, *, device_id: str, data: dict[str, Any]
    ) -> "SessionContext":
        """从已断言成功的 CreateAnonymousSession 数据构造上下文。

        功能说明:
            从已断言成功的匿名会话响应构造严格上下文。
        参数说明:
            device_id: 当前 Gateway 配置使用的设备 ID；data: 匿名会话业务数据。
        返回值:
            字段完整且归属固定的 :class:`SessionContext`。
        异常说明:
            标识、token、时间或 ``is_new_user`` 缺失/无效时抛出校验异常。
        """
        user_id = data["user_id"]
        is_new_user = data["is_new_user"]
        if not isinstance(is_new_user, bool):
            raise TypeError("is_new_user 必须是布尔值")
        return cls(
            device_id=device_id,
            user_id=user_id,
            access_token=data["access_token"],
            expires_time=data["expires_time"],
            refresh_token=data["refresh_token"],
            refresh_expires_time=data["refresh_expires_time"],
            is_new_user=is_new_user,
        )

    def replace_tokens(self, data: dict[str, Any]) -> None:
        """完整校验后一次性替换四个刷新字段。

        功能说明:
            完整校验刷新响应后一次性替换四个 token 字段。
        参数说明:
            data: RefreshSession 成功子响应的 ``data`` 对象。
        返回值:
            无；成功后当前上下文立即使用全部新 token 数据。
        异常说明:
            任一字段缺失或无效时抛出校验异常，原四个字段保持不变。
        """
        values = _validated_token_values(data)
        (
            self.access_token,
            self.expires_time,
            self.refresh_token,
            self.refresh_expires_time,
        ) = values


@dataclass(slots=True)
class CaseContext:
    """保存单个用例执行期间产生的动态值。

    功能说明:
        在同一用例的多个步骤间传递 token、用户及业务实体 ID，不进行跨用例缓存。
    参数说明:
        case_id: 可追溯的用例编号。
        values: 初始动态值，默认空字典。
    返回值:
        上下文本身不产生返回值，通过 ``set/get/require`` 访问数据。
    异常说明:
        ``require`` 请求不存在的键时抛出 ``KeyError``。
    """

    case_id: str
    auth_token: str | None = None
    refresh_token: str | None = None
    user_id: str | None = None
    media_asset_id: str | None = None
    task_id: str | None = None
    candidate_id: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    _DIRECT_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "auth_token",
            "refresh_token",
            "user_id",
            "media_asset_id",
            "task_id",
            "candidate_id",
        }
    )

    def set(self, name: str, value: Any) -> None:
        """保存动态值。

        功能说明:
            在当前用例上下文保存核心字段或扩展动态值。
        参数说明:
            name: 值的业务名称。
            value: 任意仅在当前用例中使用的值。
        返回值:
            无。
        异常说明:
            名称与方法或核心字段冲突时抛出 ``ValueError``。
        """
        if name in self._DIRECT_FIELDS:
            setattr(self, name, value)
            return
        if name in {"case_id", "values"} or hasattr(type(self), name):
            raise ValueError(f"动态值名称与保留名称冲突: {name}")
        self.values[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """读取动态值。

        功能说明:
            从当前用例上下文读取核心字段或扩展动态值。
        参数说明:
            name: 待读取的动态值名称。
            default: 名称不存在时返回的默认值。
        返回值:
            已保存的值或 ``default``。
        异常说明:
            本方法不主动抛出异常。
        """
        if name in self._DIRECT_FIELDS:
            return getattr(self, name)
        return self.values.get(name, default)

    def require(self, name: str) -> Any:
        """读取必需动态值。

        功能说明:
            读取必须存在且不为 ``None`` 的动态值。
        参数说明:
            name: 必须存在且不为 ``None`` 的键。
        返回值:
            已保存的动态值。
        异常说明:
            键不存在或值为 ``None`` 时抛出 ``KeyError``。
        """
        value = self.get(name)
        if value is None:
            raise KeyError(f"用例 {self.case_id} 缺少动态值: {name}")
        return value
