"""测试会话运行时变量、占位符替换与响应字段提取工具。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


class RuntimeContextError(ValueError):
    """表示运行时变量缺失、提取路径无效或目标响应字段为空。"""


_VARIABLE_EXPRESSION = (
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
)
_FULL_VARIABLE_PATTERN = re.compile(rf"^\{{\{{\s*({_VARIABLE_EXPRESSION})\s*}}}}$")
_VARIABLE_PATTERN = re.compile(rf"\{{\{{\s*({_VARIABLE_EXPRESSION})\s*}}}}")
_PATH_TOKEN_PATTERN = re.compile(r"([^.\[\]]+)|\[(\d+)]")


class RuntimeContext:
    """保存一次 pytest 会话内产生的动态变量。

    功能说明:
        提供变量读写、嵌套请求参数替换、简单 JSON 路径提取及 token
        毫秒过期时间判断。所有值仅保存在内存中。

    参数说明:
        initial: 可选初始变量；内容会被深拷贝，避免调用方后续修改污染上下文。
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._values: dict[str, Any] = deepcopy(initial or {})

    def get(self, key: str, default: Any = None) -> Any:
        """返回变量值；变量不存在时返回调用方指定的默认值。"""
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """深拷贝并保存一个运行时变量，防止可变响应对象被外部修改。"""
        self._values[key] = deepcopy(value)

    def contains(self, key: str) -> bool:
        """判断顶层变量是否存在，供 foreach 在结束时恢复调用方上下文。"""

        return key in self._values

    def unset(self, key: str) -> None:
        """移除一个顶层变量；变量不存在时保持幂等。"""

        self._values.pop(key, None)

    def update(self, values: dict[str, Any]) -> None:
        """批量深拷贝运行时变量，后写入值覆盖同名旧值。"""
        for key, value in values.items():
            self.set(key, value)

    def as_dict(self) -> dict[str, Any]:
        """返回全部变量的深拷贝，供单次请求创建临时解析上下文。"""
        return deepcopy(self._values)

    def resolve(self, value: Any) -> Any:
        """递归解析字典、列表和字符串中的 ``{{变量名}}``。

        完整字符串占位符直接返回变量原始类型；混合文本中的变量转换为字符串。
        未定义变量会抛出 RuntimeContextError，阻止无效占位符发送到服务端。
        """
        if isinstance(value, dict):
            return {key: self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if not isinstance(value, str):
            return deepcopy(value)

        full_match = _FULL_VARIABLE_PATTERN.match(value)
        if full_match:
            return deepcopy(self._require_expression(full_match.group(1)))

        def replace(match: re.Match[str]) -> str:
            return str(self._require_expression(match.group(1)))

        resolved = _VARIABLE_PATTERN.sub(replace, value)
        if "{{" in resolved or "}}" in resolved:
            raise RuntimeContextError(f"运行时变量表达式格式错误: {value!r}")
        return resolved

    def extract(self, data: dict[str, Any], rules: dict[str, str]) -> None:
        """根据以业务 ``data`` 为根的路径提取字段并写入上下文。

        参数说明:
            data: Gateway 目标子响应的 data 对象。
            rules: ``变量名 -> $.field[0].child`` 格式的提取规则。

        异常说明:
            RuntimeContextError: 路径格式错误、字段不存在、数组越界或值为空。
        """
        for variable_name, path in rules.items():
            extracted = self.read_path(data, path)
            if extracted is None or extracted == "":
                raise RuntimeContextError(
                    f"运行时变量提取结果为空: {variable_name} <- {path}"
                )
            self.set(variable_name, extracted)

    def extract_optional(self, data: dict[str, Any], rules: dict[str, str]) -> None:
        """按可选规则提取响应字段，目标路径不存在或为空时不写入变量。

        功能说明:
            用于列表可能为空的正常业务分支。与 ``extract`` 不同，当前响应中
            缺少某个可选字段不会中断 Flow；后续步骤可通过 ``skip_if`` 根据
            已成功提取的分支标识决定是否执行。

        参数说明:
            data: Gateway 目标子响应的 data 对象。
            rules: ``变量名 -> $.field[0].child`` 格式的可选提取规则。

        返回值:
            无。仅将存在且非空的提取值写入当前运行时上下文。

        异常说明:
            无。路径不存在、数组越界或提取值为空均视为该可选字段未提供。
        """
        for variable_name, path in rules.items():
            try:
                extracted = self.read_path(data, path)
            except RuntimeContextError:
                continue
            if extracted is None or extracted == "":
                continue
            self.set(variable_name, extracted)

    def access_token_status(
        self,
        now_ms: int,
        refresh_before_ms: int,
    ) -> str:
        """返回 access token 的三态会话决策。

        参数说明:
            now_ms: 当前 UTC 毫秒时间戳。
            refresh_before_ms: 临期刷新窗口；剩余时间等于该值时也刷新。

        返回值:
            ``valid`` 表示可直接复用，``refresh`` 表示尚未过期但已进入刷新
            窗口，``expired`` 表示 token 缺失、过期时间无效或已经到期。

        设计说明:
            显式区分临期与过期，避免 refresh token 仍有效时把已过期的 access
            token 误送入 RefreshSession 分支。
        """
        access_token = self.get("access_token")
        expires_time = self._timestamp("expires_time")
        if not access_token or expires_time is None or expires_time <= now_ms:
            return "expired"
        if expires_time - now_ms <= refresh_before_ms:
            return "refresh"
        return "valid"

    def refresh_token_is_valid(self, now_ms: int) -> bool:
        """仅当 refresh token 存在且其毫秒过期时间晚于当前时间时返回 True。"""
        refresh_token = self.get("refresh_token")
        expires_time = self._timestamp("refresh_expires_time")
        return bool(refresh_token and expires_time is not None and expires_time > now_ms)

    def _require(self, key: str) -> Any:
        """读取必需变量，并将缺失错误转换为用户可定位的配置错误。"""
        if key not in self._values:
            raise RuntimeContextError(f"运行时变量未定义: {key}")
        return self._values[key]

    def _require_expression(self, expression: str) -> Any:
        """读取 ``root.child`` 受控变量路径，不执行属性访问或任意表达式。

        根变量沿用既有命名规则；后续段只能读取 Mapping 中不以下划线开头的
        公开键。这样既能支持 foreach 元数据，又不会暴露 ``__class__`` 等
        Python 对象反射入口。
        """

        segments = expression.split(".")
        current = self._require(segments[0])
        for segment in segments[1:]:
            if segment.startswith("_"):
                raise RuntimeContextError(f"运行时变量路径不允许访问私有字段: {expression}")
            if not isinstance(current, Mapping) or segment not in current:
                raise RuntimeContextError(f"运行时变量路径不存在: {expression}")
            current = current[segment]
        return current

    def _timestamp(self, key: str) -> int | None:
        """将毫秒时间戳转换为整数；缺失或格式无效时返回 None。"""
        value = self.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def read_path(data: Any, path: str) -> Any:
        """读取受控的 ``$.field[index]`` 路径，不执行任意表达式。

        参数说明:
            data: 路径读取的根对象。
            path: 以 ``$.`` 开头的对象和数组路径。

        返回值:
            路径指向的原始值。

        异常说明:
            RuntimeContextError: 路径格式错误、字段不存在或数组越界时抛出。
        """
        if not isinstance(path, str) or not path.startswith("$."):
            raise RuntimeContextError(f"提取路径必须以 $. 开头: {path!r}")

        expression = path[2:]
        tokens = list(_PATH_TOKEN_PATTERN.finditer(expression))
        if not tokens or "".join(match.group(0) for match in tokens) != expression.replace(".", ""):
            raise RuntimeContextError(f"提取路径格式错误: {path}")

        current = data
        for match in tokens:
            field, index = match.groups()
            if field is not None:
                if not isinstance(current, dict) or field not in current:
                    raise RuntimeContextError(f"提取路径不存在: {path}")
                current = current[field]
            else:
                position = int(index)
                if not isinstance(current, list) or position >= len(current):
                    raise RuntimeContextError(f"提取数组索引不存在: {path}")
                current = current[position]
        return current
