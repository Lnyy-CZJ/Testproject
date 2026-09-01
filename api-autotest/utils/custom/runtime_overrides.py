"""“仅本次运行参数修改”的共享领域模型。

本模块位于 YAML Loader、Web API、任务管理器和 pytest 执行入口之间，负责
把项目资产中的静态业务参数转换成同一份受控契约。单接口 Case 默认自动
发现安全的静态请求叶子，显式声明只用于补充标签或约束；Flow 继续采用显式
最小白名单。浏览器只能提交逻辑字段和值；目标路径、基础值和最终执行资产
始终由服务端解析和固化。

模块只依赖 Python 标准库，避免领域校验反向依赖 Flask、平台配置或任务存储。
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


RUNTIME_INPUT_TYPES = frozenset(
    {"string", "integer", "number", "boolean", "enum", "json"}
)
RUNTIME_OVERRIDE_MAX_FIELDS = 32
RUNTIME_OVERRIDE_MAX_BYTES = 256 * 1024
RUNTIME_OVERRIDE_MAX_STRING_LENGTH = 4096
# 浏览器使用 IEEE-754 Number 传输 JSON 数值。超出该整数边界会在表单或
# JSON.parse 阶段静默舍入，因此服务端必须采用同一边界，不能只在前端拦截。
RUNTIME_OVERRIDE_MAX_SAFE_NUMBER = 9_007_199_254_740_991
RUNTIME_INPUT_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
RUNTIME_INPUT_PATH_PATTERN = re.compile(
    r"^\$\.[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
DYNAMIC_TEMPLATE_PATTERN = re.compile(r"{{[^{}]+}}")
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_BATCH_EXECUTION_MAX_ITEMS = 200
_AUTOMATIC_SESSION_API_IDS = ("CreateAnonymousSession", "RefreshSession")
_PUBLIC_FILE_INPUT_FIELDS = {
    "type",
    "required",
    "min_items",
    "max_items",
    "allowed_content_types",
    "max_size_bytes",
    "label",
    "description",
}

_COMMON_DECLARATION_FIELDS = {
    "label",
    "description",
    "type",
    "required",
    "options",
    "min_length",
    "max_length",
    "pattern",
    "minimum",
    "maximum",
    "target",
}
_STRING_CONSTRAINTS = {"min_length", "max_length", "pattern"}
_NUMBER_CONSTRAINTS = {"minimum", "maximum"}

# 这些语义属于平台配置、身份凭证、流程控制或运行时动态数据。即便路径确实
# 存在，也不能通过 Case/Scenario 的声明把它们开放给浏览器。
_FORBIDDEN_IDENTIFIERS = {
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "credential",
    "credential_profile",
    "profile",
    "gateway",
    "gateway_url",
    "base_url",
    "header",
    "headers",
    "comm",
    "environment",
    "env",
    "scope",
    "runtime_scope",
    "release",
    "target_env",
    "timeout",
    "timeout_seconds",
    "poll",
    "polling",
    "poll_interval",
    "poll_interval_seconds",
    "interval_seconds",
    "task_id",
    "asset_id",
    "asset_ids",
    "client_request_id",
    "request_id",
    "signed_url",
    "upload_url",
    "input_file",
    "file_path",
    "filepath",
    "relative_path",
    "device_id",
}
_FORBIDDEN_IDENTIFIER_PARTS = {
    "token",
    "secret",
    "credential",
    "profile",
    "gateway",
    "header",
    "headers",
    "environment",
    "env",
    "scope",
    "release",
    "timeout",
    "poll",
    "polling",
}


class RuntimeOverrideError(ValueError):
    """运行时声明、覆盖值、资产版本或执行快照不合法。

    属性说明:
        status_code: Web Task API 应返回的 HTTP 状态码。
        error_code: 稳定业务错误码，供前端按场景展示。
        message: 面向测试人员的错误说明。
        field_errors: 可选字段级错误；每项包含逻辑键和错误消息。
    """

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        *,
        field_errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.field_errors = list(field_errors or [])


def canonical_sha256(document: Any) -> str:
    """返回带 ``sha256:`` 前缀的稳定规范化 JSON 摘要。

    映射键顺序和 YAML 文件 mtime 不参与摘要；NaN、Infinity 或不能序列化的
    对象会被拒绝，避免不同 JSON 实现产生不一致版本。
    """

    try:
        payload = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_TYPE_INVALID",
            "运行参数包含无法规范化的值",
        ) from exc
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _target_error(scope: str, message: str) -> RuntimeOverrideError:
    """构造统一的项目静态声明错误。"""

    return RuntimeOverrideError(
        400,
        "RUNTIME_OVERRIDE_TARGET_INVALID",
        f"{scope}: {message}",
    )


def _parse_target_path(value: Any, *, scope: str) -> list[str]:
    """把受限对象路径转换为固定 token，不执行任意 JSONPath。"""

    if not isinstance(value, str) or not RUNTIME_INPUT_PATH_PATTERN.fullmatch(value):
        raise _target_error(scope, "target.path 必须是仅包含对象字段的 $.field 路径")
    return value[2:].split(".")


def _lookup_path(root: Any, path: list[str], *, scope: str) -> Any:
    """读取已声明对象路径，任何缺失或非对象中间节点都直接失败。"""

    current = root
    for token in path:
        if not isinstance(current, dict) or token not in current:
            raise _target_error(scope, f"目标路径不存在: $.{'.'.join(path)}")
        current = current[token]
    return current


def _assign_path(root: Any, path: list[str], value: Any, *, scope: str) -> None:
    """只给已存在的静态叶子赋值，禁止借覆盖值新增字段。"""

    current = root
    for token in path[:-1]:
        if not isinstance(current, dict) or token not in current:
            raise _target_error(scope, f"目标路径不存在: $.{'.'.join(path)}")
        current = current[token]
    leaf = path[-1]
    if not isinstance(current, dict) or leaf not in current:
        raise _target_error(scope, f"目标路径不存在: $.{'.'.join(path)}")
    current[leaf] = deepcopy(value)


def _contains_forbidden_semantics(key: str, path: list[str]) -> bool:
    """识别平台配置或运行时动态字段语义。

    这里不笼统禁止普通 ``url`` 文本；只有签名/上传 URL 等明确传输语义才
    拒绝，从而避免误伤真实业务字符串。
    """

    candidates = [key, *path]
    normalized = [_normalize_identifier(item) for item in candidates]
    for item in normalized:
        if item in _FORBIDDEN_IDENTIFIERS:
            return True
        # 组合名同样受限，例如 auth_token、client_secret、scope_id、
        # release_version。只做完整下划线分词，避免误伤 tokenizer 等普通词。
        if set(item.split("_")) & _FORBIDDEN_IDENTIFIER_PARTS:
            return True
        if any(
            marker in item
            for marker in (
                "access_token",
                "refresh_token",
                "client_request_id",
                "credential_profile",
                "poll_interval",
                "timeout_seconds",
                "signed_url",
                "upload_url",
                "file_path",
            )
        ):
            return True
        if item.endswith("_task_id") or item.endswith("_asset_id"):
            return True
        if item.endswith("_asset_ids") or item.endswith("_headers"):
            return True
    return False


def _normalize_identifier(value: str) -> str:
    """把 snake/kebab/camel/Pascal 标识符统一成小写下划线形式。

    运行参数声明来自 YAML，字段命名风格不能被当成安全边界。例如
    ``accessToken`` 与 ``access_token`` 语义相同，必须命中同一套保留字段规则。
    """

    with_word_boundaries = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    with_all_boundaries = re.sub(
        r"([a-z0-9])([A-Z])",
        r"\1_\2",
        with_word_boundaries,
    )
    return re.sub(r"[^a-z0-9]+", "_", with_all_boundaries.lower()).strip("_")


def _validate_number(value: Any, *, integer: bool) -> bool:
    """区分 bool 与真正数值，并拒绝非有限浮点数。"""

    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        # Python/JSON 整数没有 Infinity/NaN；直接交给 math.isfinite 会先转为
        # float，并让合法的任意精度大整数触发 OverflowError。
        return True
    if integer:
        return False
    return isinstance(value, float) and math.isfinite(value)


def _validate_runtime_value(
    definition: dict[str, Any],
    value: Any,
    *,
    key: str,
) -> None:
    """按规范化字段定义验证一个覆盖值，不进行隐式类型转换。"""

    input_type = definition["type"]
    type_valid = {
        "string": isinstance(value, str),
        "integer": _validate_number(value, integer=True),
        "number": _validate_number(value, integer=False),
        "boolean": isinstance(value, bool),
        "enum": isinstance(value, str),
        "json": isinstance(value, dict),
    }[input_type]
    if not type_valid:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_TYPE_INVALID",
            f"字段 {key} 的值类型必须为 {input_type}",
            field_errors=[{"key": key, "message": f"值类型必须为 {input_type}"}],
        )

    if (
        input_type in {"integer", "number"}
        and abs(value) > RUNTIME_OVERRIDE_MAX_SAFE_NUMBER
    ):
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
            f"字段 {key} 超出浏览器可无损传输的数值范围",
            field_errors=[
                {
                    "key": key,
                    "message": (
                        "数值必须在 "
                        f"±{RUNTIME_OVERRIDE_MAX_SAFE_NUMBER} 范围内"
                    ),
                }
            ],
        )

    def contains_dynamic_template(item: Any) -> bool:
        """递归检查 JSON 值，阻止交互输入间接读取 RuntimeContext Secret。"""

        if isinstance(item, str):
            return DYNAMIC_TEMPLATE_PATTERN.search(item) is not None
        if isinstance(item, dict):
            return any(contains_dynamic_template(child) for child in item.values())
        if isinstance(item, list):
            return any(contains_dynamic_template(child) for child in item)
        return False

    if contains_dynamic_template(value):
        # RuntimeContext 会在真正发请求前解析 {{...}}。若这里允许模板，普通
        # 业务字段即可间接引用 Token/Secret，并把值送入 Gateway 与完整日志。
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
            f"字段 {key} 不能使用动态模板",
            field_errors=[
                {"key": key, "message": "动态模板不能作为本次运行参数"}
            ],
        )

    if definition.get("required") is True and isinstance(value, str) and not value:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
            f"字段 {key} 不能为空",
            field_errors=[{"key": key, "message": "此字段不能为空"}],
        )

    if isinstance(value, str) and len(value) > RUNTIME_OVERRIDE_MAX_STRING_LENGTH:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE",
            f"字段 {key} 超过 {RUNTIME_OVERRIDE_MAX_STRING_LENGTH} 字符",
            field_errors=[{"key": key, "message": "字符串长度超出限制"}],
        )

    if input_type == "enum" and value not in definition.get("options", []):
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
            f"字段 {key} 必须选择声明的枚举值",
            field_errors=[{"key": key, "message": "值不在允许选项中"}],
        )

    constraints = definition.get("constraints") or {}
    if isinstance(value, str):
        minimum = constraints.get("min_length")
        maximum = constraints.get("max_length")
        pattern = constraints.get("pattern")
        if minimum is not None and len(value) < minimum:
            raise RuntimeOverrideError(
                400,
                "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
                f"字段 {key} 长度不得小于 {minimum}",
                field_errors=[{"key": key, "message": f"最少 {minimum} 个字符"}],
            )
        if maximum is not None and len(value) > maximum:
            raise RuntimeOverrideError(
                400,
                "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
                f"字段 {key} 长度不得超过 {maximum}",
                field_errors=[{"key": key, "message": f"最多 {maximum} 个字符"}],
            )
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise RuntimeOverrideError(
                400,
                "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
                f"字段 {key} 不符合格式要求",
                field_errors=[{"key": key, "message": "值不符合格式要求"}],
            )

    if input_type in {"integer", "number"}:
        minimum = constraints.get("minimum")
        maximum = constraints.get("maximum")
        if minimum is not None and value < minimum:
            raise RuntimeOverrideError(
                400,
                "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
                f"字段 {key} 不得小于 {minimum}",
                field_errors=[{"key": key, "message": f"最小值为 {minimum}"}],
            )
        if maximum is not None and value > maximum:
            raise RuntimeOverrideError(
                400,
                "RUNTIME_OVERRIDE_CONSTRAINT_FAILED",
                f"字段 {key} 不得大于 {maximum}",
                field_errors=[{"key": key, "message": f"最大值为 {maximum}"}],
            )


def _normalize_common_definition(
    key: str,
    declaration: Any,
    *,
    default_value: Any,
    target: dict[str, Any],
    scope: str,
    group: dict[str, str] | None = None,
) -> dict[str, Any]:
    """校验声明白名单、类型约束和基础值，返回统一内部定义。"""

    field_scope = f"{scope}.runtime_inputs.{key}"
    if not RUNTIME_INPUT_KEY_PATTERN.fullmatch(key):
        raise _target_error(field_scope, "逻辑键格式不合法")
    if not isinstance(declaration, dict):
        raise _target_error(field_scope, "字段定义必须是对象")
    unexpected = sorted(set(declaration) - _COMMON_DECLARATION_FIELDS)
    if unexpected:
        raise _target_error(field_scope, f"包含不支持字段: {', '.join(unexpected)}")

    label = declaration.get("label")
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 80:
        raise _target_error(field_scope, "label 必须是 1～80 字符的字符串")
    description = declaration.get("description", "")
    if not isinstance(description, str) or len(description) > 240:
        raise _target_error(field_scope, "description 必须是不超过 240 字符的字符串")
    input_type = declaration.get("type")
    if input_type not in RUNTIME_INPUT_TYPES:
        raise _target_error(
            field_scope,
            "type 必须是 string/integer/number/boolean/enum/json",
        )
    if not isinstance(declaration.get("required"), bool):
        raise _target_error(field_scope, "required 必须显式声明为布尔值")

    options: list[str] = []
    if input_type == "enum":
        raw_options = declaration.get("options")
        if (
            not isinstance(raw_options, list)
            or not 1 <= len(raw_options) <= 100
            or any(not isinstance(item, str) or not item for item in raw_options)
            or len(set(raw_options)) != len(raw_options)
        ):
            raise _target_error(field_scope, "enum.options 必须是 1～100 个不重复非空字符串")
        if any(DYNAMIC_TEMPLATE_PATTERN.search(item) for item in raw_options):
            raise _target_error(field_scope, "enum.options 不能包含动态模板")
        options = list(raw_options)
    elif "options" in declaration:
        raise _target_error(field_scope, "只有 enum 类型允许 options")

    constraints: dict[str, Any] = {}
    string_constraints = set(declaration) & _STRING_CONSTRAINTS
    number_constraints = set(declaration) & _NUMBER_CONSTRAINTS
    if string_constraints and input_type != "string":
        raise _target_error(field_scope, "字符串约束只能用于 string 类型")
    if number_constraints and input_type not in {"integer", "number"}:
        raise _target_error(field_scope, "数值约束只能用于 integer/number 类型")

    if "min_length" in declaration:
        value = declaration["min_length"]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4096:
            raise _target_error(field_scope, "min_length 必须是 0～4096 的整数")
        constraints["min_length"] = value
    if "max_length" in declaration:
        value = declaration["max_length"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4096:
            raise _target_error(field_scope, "max_length 必须是 1～4096 的整数")
        if value < constraints.get("min_length", 0):
            raise _target_error(field_scope, "max_length 不得小于 min_length")
        constraints["max_length"] = value
    if "pattern" in declaration:
        pattern = declaration["pattern"]
        if not isinstance(pattern, str) or len(pattern) > 256:
            raise _target_error(field_scope, "pattern 必须是不超过 256 字符的正则")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise _target_error(field_scope, "pattern 不是有效正则") from exc
        constraints["pattern"] = pattern
    for name in ("minimum", "maximum"):
        if name not in declaration:
            continue
        value = declaration[name]
        if not _validate_number(value, integer=False):
            raise _target_error(field_scope, f"{name} 必须是有限数值")
        if abs(value) > RUNTIME_OVERRIDE_MAX_SAFE_NUMBER:
            raise _target_error(
                field_scope,
                f"{name} 超出浏览器可无损传输的数值范围",
            )
        constraints[name] = value
    if (
        "minimum" in constraints
        and "maximum" in constraints
        and constraints["maximum"] < constraints["minimum"]
    ):
        raise _target_error(field_scope, "maximum 不得小于 minimum")

    normalized = {
        "key": key,
        "label": label.strip(),
        "description": description,
        "type": input_type,
        "required": declaration["required"],
        "options": options,
        "constraints": constraints,
        "target": deepcopy(target),
        "default_value": deepcopy(default_value),
    }
    if group is not None:
        normalized["group"] = deepcopy(group)

    try:
        _validate_runtime_value(normalized, default_value, key=key)
    except RuntimeOverrideError as exc:
        raise _target_error(field_scope, f"基础值与声明不兼容: {exc.message}") from exc
    return normalized


def _validate_declaration_collection(value: Any, *, scope: str) -> dict[str, Any]:
    """校验 runtime_inputs 根对象和字段数量。"""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _target_error(scope, "runtime_inputs 必须是对象")
    if len(value) > RUNTIME_OVERRIDE_MAX_FIELDS:
        raise _target_error(scope, f"runtime_inputs 最多声明 {RUNTIME_OVERRIDE_MAX_FIELDS} 项")
    return value


def _automatic_runtime_input_type(value: Any) -> str | None:
    """根据 YAML 默认值推断运行参数表单类型，不对值做隐式转换。

    ``bool`` 在 Python 中属于 ``int`` 的子类，因此必须最先判断。null、数组、
    非有限或超出浏览器安全范围的数值没有可靠的 P0 编辑器，返回 ``None``
    表示保留 YAML 默认值但不向浏览器开放。
    """

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return (
            "integer"
            if abs(value) <= RUNTIME_OVERRIDE_MAX_SAFE_NUMBER
            else None
        )
    if isinstance(value, float):
        return (
            "number"
            if math.isfinite(value)
            and abs(value) <= RUNTIME_OVERRIDE_MAX_SAFE_NUMBER
            else None
        )
    if isinstance(value, str):
        if (
            len(value) > RUNTIME_OVERRIDE_MAX_STRING_LENGTH
            or DYNAMIC_TEMPLATE_PATTERN.search(value)
        ):
            return None
        return "string"
    return None


def _iter_automatic_runtime_leaves(
    value: Any,
    *,
    path: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], Any, str]]:
    """按 YAML 顺序递归返回可安全编辑的静态请求参数叶子。

    对象本身不作为一个 JSON 大文本开放，而是继续展开其中符合目标路径语法的
    字段；数组、null、模板值及无法无损传给浏览器的类型直接跳过。这样既提供
    常用请求参数入口，也不会把完整请求对象变成绕过字段级校验的后门。
    """

    if isinstance(value, dict):
        leaves: list[tuple[tuple[str, ...], Any, str]] = []
        for raw_key, child in value.items():
            if (
                not isinstance(raw_key, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw_key) is None
            ):
                continue
            leaves.extend(
                _iter_automatic_runtime_leaves(
                    child,
                    path=(*path, raw_key),
                )
            )
        return leaves

    input_type = _automatic_runtime_input_type(value)
    if input_type is None or not path:
        return []
    return [(path, value, input_type)]


def _automatic_runtime_input_key(
    identity: tuple[str, ...],
    *,
    used_keys: set[str],
) -> str:
    """为自动字段生成稳定逻辑键，并处理路径命名碰撞。"""

    candidate = "__".join(identity)
    if (
        RUNTIME_INPUT_KEY_PATTERN.fullmatch(candidate)
        and candidate not in used_keys
    ):
        return candidate
    digest = hashlib.sha256(
        ("$." + ".".join(identity)).encode("utf-8")
    ).hexdigest()[:16]
    fallback = f"request_param_{digest}"
    suffix = 2
    while fallback in used_keys:
        fallback = f"request_param_{digest}_{suffix}"
        suffix += 1
    return fallback


def _automatic_runtime_declaration(
    path: tuple[str, ...],
    *,
    input_type: str,
    description_prefix: str = "请求参数",
) -> dict[str, Any]:
    """生成浏览器自由输入所需的最小字段元数据。

    自动字段不声明 options，也不猜测业务必填性；用户可以输入任意同类型值，
    服务端仍统一执行模板、长度、数值范围和敏感目标校验。
    """

    path_text = ".".join(path)
    label = path_text if len(path_text) <= 80 else f"{path_text[:77]}..."
    description = (
        f"{description_prefix} $.{path_text}，仅影响当前任务，可输入任意同类型值。"
    )
    return {
        "label": label,
        "description": description[:240],
        "type": input_type,
        "required": False,
    }


def validate_case_runtime_inputs(
    case: dict[str, Any],
    *,
    scope: str,
) -> dict[str, dict[str, Any]]:
    """返回 Case 可修改请求参数的规范化内部定义。

    ``request.params`` 中安全的静态基础类型叶子默认自动开放，用户无需为了
    提供输入框而重复编写 YAML 声明。已有 ``runtime_inputs`` 仍可给特定路径
    设置自定义标签、枚举或约束，并优先于同一路径的自动定义。显式声明若指向
    动态或敏感目标会使项目校验失败；自动发现遇到这些字段则安全跳过。
    """

    declarations = _validate_declaration_collection(
        case.get("runtime_inputs"),
        scope=scope,
    )
    request = case.get("request")
    params = request.get("params") if isinstance(request, dict) else None
    if not isinstance(params, dict):
        raise _target_error(scope, "Case request.params 必须是对象")

    result: dict[str, dict[str, Any]] = {}
    used_targets: set[tuple[str, ...]] = set()
    for key, declaration in declarations.items():
        field_scope = f"{scope}.runtime_inputs.{key}"
        if not isinstance(declaration, dict):
            raise _target_error(field_scope, "字段定义必须是对象")
        target = declaration.get("target")
        if not isinstance(target, dict) or set(target) != {"scope", "path"}:
            raise _target_error(field_scope, "Case target 只能包含 scope 和 path")
        if target.get("scope") != "case_request":
            raise _target_error(field_scope, "Case target.scope 必须为 case_request")
        path = _parse_target_path(target.get("path"), scope=field_scope)
        if _contains_forbidden_semantics(str(key), path):
            raise _target_error(field_scope, "目标属于配置、凭证或运行时动态字段")
        path_identity = tuple(path)
        if path_identity in used_targets:
            raise _target_error(field_scope, "多个逻辑字段不能指向同一目标")
        used_targets.add(path_identity)
        default_value = _lookup_path(params, path, scope=field_scope)
        if isinstance(default_value, (dict, list)):
            if declaration.get("type") != "json" or not isinstance(default_value, dict):
                raise _target_error(
                    field_scope,
                    "对象目标必须声明为 json，数组不能作为运行参数根节点",
                )
        if isinstance(default_value, str) and DYNAMIC_TEMPLATE_PATTERN.search(default_value):
            raise _target_error(field_scope, "动态模板值不能开放运行时覆盖")
        result[str(key)] = _normalize_common_definition(
            str(key),
            declaration,
            default_value=default_value,
            target={"scope": "case_request", "path": path},
            scope=scope,
        )

    # 自动发现只补充尚未由显式声明占用的安全路径。字段总数继续受既有 32 项
    # 上限约束；到达上限后停止补充，避免旧 Case 因参数较多而突然校验失败。
    used_keys = set(result)
    for path, default_value, input_type in _iter_automatic_runtime_leaves(params):
        if len(result) >= RUNTIME_OVERRIDE_MAX_FIELDS:
            break
        if any(path[: len(target)] == target for target in used_targets):
            continue
        key = _automatic_runtime_input_key(path, used_keys=used_keys)
        if _contains_forbidden_semantics(key, list(path)):
            continue
        definition = _normalize_common_definition(
            key,
            _automatic_runtime_declaration(path, input_type=input_type),
            default_value=default_value,
            target={"scope": "case_request", "path": list(path)},
            scope=scope,
        )
        result[key] = definition
        used_keys.add(key)
        used_targets.add(path)
    return result


def _flatten_api_steps(steps: Any) -> dict[str, dict[str, Any]]:
    """递归收集 Flow 中的 API 步骤，支持 foreach 内嵌步骤。"""

    result: dict[str, dict[str, Any]] = {}
    if not isinstance(steps, list):
        return result
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = step.get("id")
        if isinstance(step_id, str) and isinstance(step.get("api"), str):
            result[step_id] = step
        foreach = step.get("foreach")
        if isinstance(foreach, dict):
            result.update(_flatten_api_steps(foreach.get("steps")))
    return result


def validate_flow_runtime_inputs(
    flow: dict[str, Any],
    scenario: dict[str, Any],
    *,
    scope: str,
) -> dict[str, dict[str, Any]]:
    """返回 Flow 各 API 步骤可修改请求参数的规范化内部定义。

    每个 API 步骤 ``step_data.<step>.params`` 中安全的静态标量叶子默认自动
    开放；模板变量、素材/任务标识、凭证及平台配置字段会跳过。Scenario 顶层
    ``runtime_inputs`` 继续作为可选元数据与约束，并优先于同一目标的自动字段。
    Flow 的文件输入和拓扑不属于普通运行参数，仍由原有独立契约处理。
    """

    declarations = _validate_declaration_collection(
        scenario.get("runtime_inputs"),
        scope=scope,
    )
    api_steps = _flatten_api_steps(flow.get("steps"))
    step_data = scenario.get("step_data")
    if not isinstance(step_data, dict):
        raise _target_error(scope, "Scenario step_data 必须是对象")

    result: dict[str, dict[str, Any]] = {}
    used_targets: set[tuple[str, ...]] = set()
    for key, declaration in declarations.items():
        field_scope = f"{scope}.runtime_inputs.{key}"
        if not isinstance(declaration, dict):
            raise _target_error(field_scope, "字段定义必须是对象")
        target = declaration.get("target")
        if not isinstance(target, dict) or set(target) != {"scope", "step_id", "path"}:
            raise _target_error(
                field_scope,
                "Flow target 只能包含 scope、step_id 和 path",
            )
        if target.get("scope") != "flow_step_request":
            raise _target_error(
                field_scope,
                "Flow target.scope 必须为 flow_step_request",
            )
        step_id = target.get("step_id")
        if not isinstance(step_id, str) or step_id not in api_steps:
            raise _target_error(field_scope, f"目标 API 步骤不存在: {step_id}")
        configured_step = step_data.get(step_id)
        params = configured_step.get("params") if isinstance(configured_step, dict) else None
        if not isinstance(params, dict):
            raise _target_error(field_scope, f"Scenario 步骤 {step_id}.params 不存在")
        path = _parse_target_path(target.get("path"), scope=field_scope)
        if _contains_forbidden_semantics(str(key), path):
            raise _target_error(field_scope, "目标属于配置、凭证或运行时动态字段")
        path_identity = (step_id, *path)
        if path_identity in used_targets:
            raise _target_error(field_scope, "多个逻辑字段不能指向同一目标")
        used_targets.add(path_identity)
        default_value = _lookup_path(params, path, scope=field_scope)
        if isinstance(default_value, (dict, list)):
            if declaration.get("type") != "json" or not isinstance(default_value, dict):
                raise _target_error(
                    field_scope,
                    "对象目标必须声明为 json，数组不能作为运行参数根节点",
                )
        if isinstance(default_value, str) and DYNAMIC_TEMPLATE_PATTERN.search(default_value):
            raise _target_error(field_scope, "动态模板值不能开放运行时覆盖")
        step = api_steps[step_id]
        result[str(key)] = _normalize_common_definition(
            str(key),
            declaration,
            default_value=default_value,
            target={
                "scope": "flow_step_request",
                "step_id": step_id,
                "path": path,
            },
            scope=scope,
            group={
                "step_id": step_id,
                "step_name": str(step.get("api") or step_id),
            },
        )

    # 显式字段先进入结果，既保留产品化标签/枚举，也用于阻止同一目标重复生成
    # 自动字段。随后严格按 Flow API 步骤和 Scenario YAML 的顺序发现静态值，
    # 确保 Catalog、asset_revision 与浏览器表单在不同运行中保持稳定。
    used_keys = set(result)
    for step_id, step in api_steps.items():
        if len(result) >= RUNTIME_OVERRIDE_MAX_FIELDS:
            break
        configured_step = step_data.get(step_id)
        params = configured_step.get("params") if isinstance(configured_step, dict) else None
        if not isinstance(params, dict):
            continue
        for path, default_value, input_type in _iter_automatic_runtime_leaves(params):
            if len(result) >= RUNTIME_OVERRIDE_MAX_FIELDS:
                break
            path_identity = (step_id, *path)
            if any(
                path_identity[: len(target)] == target
                for target in used_targets
            ):
                continue
            # 自动逻辑键包含步骤 ID 只是为避免跨步骤重名；安全判断只针对真实
            # 请求路径，避免步骤名中的 poll/task 等业务词误伤普通静态参数。
            if _contains_forbidden_semantics("__".join(path), list(path)):
                continue
            key = _automatic_runtime_input_key(
                path_identity,
                used_keys=used_keys,
            )
            step_name = str(step.get("api") or step_id)
            definition = _normalize_common_definition(
                key,
                _automatic_runtime_declaration(
                    path,
                    input_type=input_type,
                    description_prefix=f"步骤 {step_id} 的请求参数",
                ),
                default_value=default_value,
                target={
                    "scope": "flow_step_request",
                    "step_id": step_id,
                    "path": list(path),
                },
                scope=scope,
                group={
                    "step_id": step_id,
                    "step_name": step_name,
                },
            )
            result[key] = definition
            used_keys.add(key)
            used_targets.add(path_identity)
    return result


def _public_runtime_input(definition: dict[str, Any]) -> dict[str, Any]:
    """删除内部目标，返回可安全发送到浏览器的字段描述。"""

    return {
        key: deepcopy(value)
        for key, value in definition.items()
        if key != "target"
    }


def _build_snapshot(
    *,
    project_id: str,
    asset_type: str,
    asset_id: str,
    runtime_input_definitions: dict[str, dict[str, Any]],
    resolved_execution_asset: dict[str, Any],
) -> dict[str, Any]:
    """构建 Case/Flow 共用的基础快照和版本摘要。"""

    definitions = deepcopy(runtime_input_definitions)
    execution_asset = deepcopy(resolved_execution_asset)
    revision_document = {
        "schema_version": 1,
        "project_id": project_id,
        "asset_type": asset_type,
        "asset_id": asset_id,
        "runtime_input_definitions": definitions,
        "resolved_execution_asset": execution_asset,
    }
    return {
        "schema_version": 1,
        "project_id": project_id,
        "asset_type": asset_type,
        "asset_id": asset_id,
        "asset_revision": canonical_sha256(revision_document),
        "runtime_input_schema_revision": canonical_sha256(definitions),
        "runtime_input_definitions": definitions,
        "runtime_inputs": [
            _public_runtime_input(definition)
            for definition in definitions.values()
        ],
        "applied_overrides": [],
        "resolved_asset_revision": canonical_sha256(execution_asset),
        "resolved_execution_asset": execution_asset,
    }


def _select_execution_api_definitions(
    api_definitions: dict[str, dict[str, Any]],
    referenced_api_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """固化业务 API 与自动会话 API 的最小依赖闭包。

    GatewayApi 会在普通请求前根据会话剩余时间自动调用刷新或重建接口。
    执行阶段禁止回退当前 YAML，因此这两个存在于项目注册表中的依赖也必须
    和业务资产一起进入不可变快照；无关 API 不纳入，避免无关修改改变版本。
    """

    selected_ids = set(referenced_api_ids)
    selected_ids.update(
        api_id
        for api_id in _AUTOMATIC_SESSION_API_IDS
        if api_id in api_definitions
    )
    return {
        api_id: deepcopy(api_definitions[api_id])
        for api_id in sorted(selected_ids)
        if api_id in api_definitions
    }


def build_case_asset_snapshot(
    project_id: str,
    single_case: dict[str, Any],
    api_definitions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """生成未覆盖的单接口基础资产快照。

    固化当前 Case API 与自动会话依赖，避免执行期回退 YAML；无关 API 的修改
    不应改变当前资产版本。
    """

    api_id = single_case.get("api_id")
    asset_id = single_case.get("id")
    if not isinstance(api_id, str) or api_id not in api_definitions:
        raise _target_error("Case 快照", "所选 API 定义不存在")
    if not isinstance(asset_id, str) or not asset_id:
        raise _target_error("Case 快照", "Case ID 不合法")
    definitions = single_case.get("runtime_inputs") or {}
    if not isinstance(definitions, dict):
        raise _target_error("Case 快照", "runtime_inputs 必须是规范化对象")
    execution_definitions = _select_execution_api_definitions(
        api_definitions,
        {api_id},
    )
    return _build_snapshot(
        project_id=project_id,
        asset_type="case",
        asset_id=asset_id,
        runtime_input_definitions=definitions,
        resolved_execution_asset={
            "single_case": deepcopy(single_case),
            "api_definitions": execution_definitions,
        },
    )


def build_flow_asset_snapshot(
    project_id: str,
    flow_case: dict[str, Any],
    api_definitions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """生成未覆盖的 Flow 基础资产快照。"""

    asset_id = flow_case.get("id")
    if not isinstance(asset_id, str) or not asset_id:
        raise _target_error("Flow 快照", "Flow ID 不合法")
    definitions = flow_case.get("runtime_inputs") or {}
    if not isinstance(definitions, dict):
        raise _target_error("Flow 快照", "runtime_inputs 必须是规范化对象")
    referenced_definitions = flow_case.get("api_definitions") or {}
    if not isinstance(referenced_definitions, dict):
        raise _target_error("Flow 快照", "api_definitions 必须是对象")
    referenced_ids = {str(api_id) for api_id in referenced_definitions}
    missing_ids = sorted(referenced_ids - set(api_definitions))
    if missing_ids:
        raise _target_error(
            "Flow 快照",
            f"引用的 API 定义不存在: {', '.join(missing_ids)}",
        )
    execution_definitions = _select_execution_api_definitions(
        api_definitions,
        referenced_ids,
    )
    resolved_flow_case = deepcopy(flow_case)
    # FlowRunner 和 GatewayApi 分别从 flow_case 与快照顶层读取 API 注册表，
    # 两处必须指向同一个依赖闭包，避免会话状态不同导致执行行为漂移。
    resolved_flow_case["api_definitions"] = deepcopy(execution_definitions)
    return _build_snapshot(
        project_id=project_id,
        asset_type="flow",
        asset_id=asset_id,
        runtime_input_definitions=definitions,
        resolved_execution_asset={
            "flow_case": resolved_flow_case,
            "api_definitions": execution_definitions,
        },
    )


def public_asset_contract(snapshot: dict[str, Any]) -> dict[str, Any]:
    """返回不含目标路径和完整执行资产的浏览器安全视图。"""

    runtime_inputs = [
        {
            key: deepcopy(value)
            for key, value in field.items()
            if key != "target"
        }
        for field in snapshot.get("runtime_inputs", [])
        if isinstance(field, dict)
    ]
    applied = deepcopy(snapshot.get("applied_overrides") or [])
    public_inputs: dict[str, Any] = {}
    if snapshot.get("asset_type") == "flow":
        execution_asset = snapshot.get("resolved_execution_asset")
        flow_case = (
            execution_asset.get("flow_case")
            if isinstance(execution_asset, dict)
            else None
        )
        flow = flow_case.get("flow") if isinstance(flow_case, dict) else None
        inputs = flow.get("inputs") if isinstance(flow, dict) else None
        media_files = inputs.get("media_files") if isinstance(inputs, dict) else None
        if isinstance(media_files, dict):
            # FlowLoader 已校验输入契约；公开层仍显式白名单，避免未来内部字段
            # 扩展时被完整执行资产顺带暴露给浏览器。
            public_inputs["media_files"] = {
                key: deepcopy(value)
                for key, value in media_files.items()
                if key in _PUBLIC_FILE_INPUT_FIELDS
            }
    return {
        "asset_type": snapshot.get("asset_type"),
        "asset_id": snapshot.get("asset_id"),
        "asset_revision": snapshot.get("asset_revision"),
        "runtime_input_schema_revision": snapshot.get(
            "runtime_input_schema_revision"
        ),
        "runtime_inputs": runtime_inputs,
        "runtime_input_count": len(runtime_inputs),
        "inputs": public_inputs,
        "applied_overrides": applied,
        "override_count": len(applied),
    }


def _schema_changed(message: str) -> RuntimeOverrideError:
    """构造 Preflight 与提交之间资产发生变化的 409。"""

    return RuntimeOverrideError(
        409,
        "RUNTIME_OVERRIDE_SCHEMA_CHANGED",
        message,
    )


def validate_retry_runtime_input_schema(
    previous_definitions: Any,
    current_definitions: Any,
    runtime_overrides: Any,
) -> None:
    """确认直接 Retry 的逻辑字段仍指向同一类业务目标。

    Retry 可以使用当前 YAML 的默认值和约束，但不能把旧逻辑键静默重定向到
    新步骤或新字段。类型/目标变化要求用户进入“修改参数后重试”重新确认；
    当前约束是否仍接受旧值，则继续由 ``apply_runtime_overrides`` 判定。
    """

    if runtime_overrides in (None, {}):
        return
    if not isinstance(runtime_overrides, Mapping):
        raise _schema_changed("原任务运行参数与当前 YAML 声明不兼容")
    if not isinstance(previous_definitions, Mapping) or not isinstance(
        current_definitions,
        Mapping,
    ):
        raise _schema_changed("原任务缺少可验证的运行参数声明，请修改参数后重试")

    for raw_key in runtime_overrides:
        key = str(raw_key)
        previous = previous_definitions.get(key)
        current = current_definitions.get(key)
        if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
            raise _schema_changed("原任务运行参数与当前 YAML 声明不兼容")
        if previous.get("type") != current.get("type"):
            raise _schema_changed("运行参数类型已变化，请修改参数后重试")
        if previous.get("target") != current.get("target"):
            raise _schema_changed("运行参数目标已变化，请修改参数后重试")


def apply_runtime_overrides(
    snapshot: dict[str, Any],
    runtime_overrides: Any,
    *,
    expected_revision: str | None,
    require_revision: bool,
    schema_change_error: bool = False,
) -> dict[str, Any]:
    """校验并在深拷贝上应用覆盖，返回新的不可变资产快照。

    ``schema_change_error`` 用于 Retry：旧逻辑键若与当前 YAML 不兼容，统一
    映射为 409，而普通首次提交仍保留具体 400 错误便于用户修正。
    """

    overrides = {} if runtime_overrides is None else runtime_overrides
    if not isinstance(overrides, dict):
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_TYPE_INVALID",
            "runtime_overrides 必须是对象",
        )
    if len(overrides) > RUNTIME_OVERRIDE_MAX_FIELDS:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE",
            f"本次最多修改 {RUNTIME_OVERRIDE_MAX_FIELDS} 个字段",
        )
    try:
        payload = json.dumps(
            overrides,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_TYPE_INVALID",
            "runtime_overrides 包含无法序列化或非有限数值",
        ) from exc
    if len(payload) > RUNTIME_OVERRIDE_MAX_BYTES:
        raise RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE",
            f"runtime_overrides 规范化后不得超过 {RUNTIME_OVERRIDE_MAX_BYTES} 字节",
        )
    for key, value in overrides.items():
        if isinstance(value, str) and len(value) > RUNTIME_OVERRIDE_MAX_STRING_LENGTH:
            raise RuntimeOverrideError(
                400,
                "RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE",
                f"字段 {key} 超过 {RUNTIME_OVERRIDE_MAX_STRING_LENGTH} 字符",
                field_errors=[{"key": str(key), "message": "字符串长度超出限制"}],
            )

    actual_revision = snapshot.get("asset_revision")
    if overrides and require_revision and not expected_revision:
        raise _schema_changed("提交运行参数前必须携带当前 asset_revision")
    if expected_revision is not None and expected_revision != actual_revision:
        raise _schema_changed("资产已更新，请重新预检并确认本次运行参数")

    definitions = snapshot.get("runtime_input_definitions")
    if not isinstance(definitions, dict):
        raise _target_error("资产快照", "runtime_input_definitions 不合法")
    unknown = [str(key) for key in overrides if key not in definitions]
    if unknown:
        error = RuntimeOverrideError(
            400,
            "RUNTIME_OVERRIDE_UNKNOWN_KEY",
            f"存在未声明的运行参数: {', '.join(sorted(unknown))}",
            field_errors=[
                {"key": key, "message": "字段未在当前 YAML 中开放"}
                for key in sorted(unknown)
            ],
        )
        if schema_change_error:
            raise _schema_changed("原任务运行参数与当前 YAML 声明不兼容") from error
        raise error

    result = deepcopy(snapshot)
    execution_asset = result.get("resolved_execution_asset")
    if not isinstance(execution_asset, dict):
        raise _target_error("资产快照", "resolved_execution_asset 不合法")
    applied: list[dict[str, Any]] = []
    try:
        for key, value in overrides.items():
            definition = definitions[key]
            _validate_runtime_value(definition, value, key=str(key))
            target = definition.get("target") or {}
            path = target.get("path")
            if not isinstance(path, list) or not path:
                raise _target_error(str(key), "内部目标路径不合法")
            if target.get("scope") == "case_request":
                params = execution_asset["single_case"]["execution_case"][
                    "request"
                ]["params"]
                step_id = None
            elif target.get("scope") == "flow_step_request":
                step_id = target.get("step_id")
                params = execution_asset["flow_case"]["scenario"]["step_data"][
                    step_id
                ]["params"]
            else:
                raise _target_error(str(key), "内部目标 scope 不合法")
            _assign_path(params, path, value, scope=str(key))
            base_value = deepcopy(definition.get("default_value"))
            if value != base_value:
                difference = {
                    "key": str(key),
                    "label": str(definition.get("label") or key),
                    "base_value": base_value,
                    "override_value": deepcopy(value),
                    "resolved_value": deepcopy(value),
                }
                if step_id is not None:
                    difference["step_id"] = str(step_id)
                applied.append(difference)
    except (KeyError, TypeError) as exc:
        error = _target_error("资产快照", "覆盖目标与当前执行资产不一致")
        if schema_change_error:
            raise _schema_changed("原任务运行参数与当前 YAML 声明不兼容") from exc
        raise error from exc
    except RuntimeOverrideError as exc:
        if schema_change_error and exc.error_code != "RUNTIME_OVERRIDE_SCHEMA_CHANGED":
            raise _schema_changed("原任务运行参数与当前 YAML 声明不兼容") from exc
        raise

    result["applied_overrides"] = applied
    result["resolved_asset_revision"] = canonical_sha256(execution_asset)
    return result


def load_execution_asset_file(
    path: Path,
    *,
    runtime_root: Path,
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """校验任务执行文件身份、路径、schema 和内容摘要。

    该入口用于 pytest 的 fail-closed 执行。只要内部环境变量已经设置，文件
    缺失、越界、符号链接、权限错误或内容被篡改都必须终止，绝不回退 YAML。
    """

    supplied = Path(path)
    expected = Path(runtime_root) / project_id / task_id / "execution-asset.json"
    if supplied.name != "execution-asset.json":
        raise _target_error("执行资产", "文件名必须为 execution-asset.json")
    # 文件自身和 runtime 根目录以下任一父级都不能是符号链接。仅比较最终
    # resolve 结果不足以发现 ``runtime/<project>`` 指向根目录外部的情况。
    controlled_parts = (expected.parent.parent, expected.parent, expected)
    if any(candidate.is_symlink() for candidate in controlled_parts):
        raise _target_error("执行资产", "禁止使用符号链接")
    try:
        runtime_root_resolved = Path(runtime_root).resolve(strict=True)
        supplied_resolved = supplied.resolve(strict=True)
        expected_resolved = expected.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise _target_error("执行资产", "文件不存在或无法访问") from exc
    if supplied_resolved != expected_resolved:
        raise _target_error("执行资产", "文件路径不属于当前项目和任务")
    try:
        supplied_resolved.relative_to(runtime_root_resolved)
    except ValueError as exc:
        raise _target_error("执行资产", "文件路径不属于 runtime 根目录") from exc
    if not supplied_resolved.is_file():
        raise _target_error("执行资产", "路径不是普通文件")
    if stat.S_IMODE(supplied_resolved.stat().st_mode) != 0o600:
        raise _target_error("执行资产", "文件权限必须为 0600")
    try:
        document = json.loads(supplied_resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _target_error("执行资产", "文件不是有效 UTF-8 JSON") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise _target_error("执行资产", "schema_version 必须为 1")
    if document.get("project_id") != project_id or document.get("task_id") != task_id:
        raise _target_error("执行资产", "项目或任务身份不一致")
    asset_type = document.get("asset_type")
    asset_id = document.get("asset_id")
    if (
        asset_type not in {"case", "flow", "batch"}
        or not isinstance(asset_id, str)
        or not asset_id
    ):
        raise _target_error("执行资产", "资产类型或 ID 不合法")
    for digest_field in ("asset_revision", "resolved_asset_revision"):
        if not _SHA256_PATTERN.fullmatch(str(document.get(digest_field) or "")):
            raise _target_error("执行资产", f"{digest_field} 不合法")
    resolved = document.get("resolved_execution_asset")
    if not isinstance(resolved, dict) or not isinstance(
        resolved.get("api_definitions"), dict
    ):
        raise _target_error("执行资产", "执行对象结构不合法")
    if asset_type == "batch":
        _validate_batch_execution_asset(
            resolved,
            asset_id=asset_id,
            project_id=project_id,
        )
    else:
        _validate_execution_asset_item(
            {
                "asset_type": asset_type,
                "asset_id": asset_id,
                "asset_revision": document.get("asset_revision"),
                "resolved_asset_revision": document.get(
                    "resolved_asset_revision"
                ),
                "resolved_execution_asset": resolved,
            },
            expected_type=asset_type,
            project_id=project_id,
            scope="执行资产",
        )
    if canonical_sha256(resolved) != document.get("resolved_asset_revision"):
        raise _target_error("执行资产", "执行资产完整性校验失败")
    return document


def _validate_execution_asset_item(
    item: Any,
    *,
    expected_type: str,
    project_id: str,
    scope: str,
) -> None:
    """校验单个 Case/Flow 执行对象的身份和不可变摘要。

    批次条目没有独立文件路径，但其安全边界与顶层执行文件相同：类型、ID、
    摘要和内层对象必须互相吻合。若未来写入可选 ``project_id``，也只能等于
    当前顶层项目，避免跨项目对象被拼入合法批次。
    """

    if not isinstance(item, dict):
        raise _target_error(scope, "条目必须是对象")
    item_project_id = item.get("project_id")
    if item_project_id is not None and item_project_id != project_id:
        raise _target_error(scope, "条目项目身份不一致")
    asset_type = item.get("asset_type")
    asset_id = item.get("asset_id")
    if asset_type != expected_type or not isinstance(asset_id, str) or not asset_id:
        raise _target_error(scope, "资产类型或 ID 不合法")
    for digest_field in ("asset_revision", "resolved_asset_revision"):
        if not _SHA256_PATTERN.fullmatch(str(item.get(digest_field) or "")):
            raise _target_error(scope, f"{digest_field} 不合法")
    resolved = item.get("resolved_execution_asset")
    if not isinstance(resolved, dict) or not isinstance(
        resolved.get("api_definitions"), dict
    ):
        raise _target_error(scope, "执行对象结构不合法")
    identity_key = "single_case" if asset_type == "case" else "flow_case"
    selected = resolved.get(identity_key)
    if not isinstance(selected, dict) or selected.get("id") != asset_id:
        raise _target_error(scope, "执行对象与资产身份不一致")
    if canonical_sha256(resolved) != item.get("resolved_asset_revision"):
        raise _target_error(scope, "执行资产完整性校验失败")


def _validate_batch_execution_asset(
    resolved: dict[str, Any],
    *,
    asset_id: str,
    project_id: str,
) -> None:
    """逐项校验批次执行清单，并确保顶层 API 注册表覆盖每个条目。

    pytest 的 Gateway fixture 只读取批次顶层 ``api_definitions``，因此除逐项
    摘要外，还必须验证每个条目固化的 API 定义在顶层存在且内容相同；否则
    一个摘要合法但注册表不一致的批次会执行错误接口定义。
    """

    batch_type = resolved.get("batch_type")
    expected_item_type = {"cases": "case", "flows": "flow"}.get(batch_type)
    items = resolved.get("items")
    if expected_item_type is None or not isinstance(items, list) or not items:
        raise _target_error("批次执行资产", "batch_type 或 items 不合法")
    if len(items) > _BATCH_EXECUTION_MAX_ITEMS:
        raise _target_error(
            "批次执行资产",
            f"条目数量不得超过 {_BATCH_EXECUTION_MAX_ITEMS}",
        )
    if asset_id != f"{batch_type}:{len(items)}":
        raise _target_error("批次执行资产", "批次 ID 与类型或条目数量不一致")

    shared_definitions = resolved.get("api_definitions")
    if not isinstance(shared_definitions, dict):
        raise _target_error("批次执行资产", "api_definitions 不合法")
    for index, item in enumerate(items):
        item_scope = f"批次执行资产第 {index + 1} 项"
        _validate_execution_asset_item(
            item,
            expected_type=expected_item_type,
            project_id=project_id,
            scope=item_scope,
        )
        item_definitions = item["resolved_execution_asset"]["api_definitions"]
        mismatched_api_ids = [
            str(api_id)
            for api_id, definition in item_definitions.items()
            if shared_definitions.get(api_id) != definition
        ]
        if mismatched_api_ids:
            raise _target_error(
                item_scope,
                "顶层 API 定义缺失或与条目不一致: "
                + ", ".join(sorted(mismatched_api_ids)),
            )


def load_execution_asset_from_environment(
    *,
    runtime_root: Path,
    project_id: str,
    task_id: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """从内部环境变量读取执行文件；未配置时保持普通 CLI/YAML 行为。"""

    source = os.environ if environ is None else environ
    configured_path = source.get("API_AUTOTEST_EXECUTION_ASSET_FILE")
    if configured_path is None:
        return None
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise _target_error("执行资产", "内部文件路径不能为空")
    if not task_id:
        raise _target_error("执行资产", "设置执行资产文件时必须提供 task_id")
    return load_execution_asset_file(
        Path(configured_path),
        runtime_root=runtime_root,
        project_id=project_id,
        task_id=task_id,
    )
