"""Flow 与同名 Scenario YAML 的加载和静态校验。"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from utils.custom.api_loader import load_api_definitions
from utils.custom.config_loader import load_yaml
from utils.custom.runtime_overrides import (
    RuntimeOverrideError,
    validate_flow_runtime_inputs,
)


class FlowConfigError(ValueError):
    """表示 Flow/Scenario 配对或步骤配置不合法。"""


def _safe_yaml_paths(directory: Path, project_root: Path, kind: str) -> list[Path]:
    """枚举项目内 Flow/Scenario 普通文件，拒绝跨项目符号链接。"""
    boundary = project_root.resolve()
    paths = sorted(directory.glob("*.yaml"))
    for path in paths:
        if path.is_symlink():
            raise FlowConfigError(f"{kind} 文件禁止使用符号链接: {path.name}")
        try:
            path.resolve().relative_to(boundary)
        except ValueError as exc:
            raise FlowConfigError(f"{kind} 文件路径越界: {path.name}") from exc
    return paths


_PATH_PATTERN = re.compile(
    r"^\$\.[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[\d+]))*$"
)
_VARIABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FLOW_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
_SIGNED_UPLOAD_FIELDS = {
    "type",
    "url",
    "headers",
    "fixture",
    "input_file",
    "method",
    "success_statuses",
    "output",
}
_VALIDATE_BINARY_INPUT_FIELDS = {
    "type",
    "files",
    "allowed_content_types",
    "min_items",
    "max_items",
    "max_size_bytes",
}
_FOREACH_FIELDS = {"items", "item", "collect", "steps"}
_FILE_INPUT_FIELDS = {
    "type",
    "required",
    "min_items",
    "max_items",
    "allowed_content_types",
    "max_size_bytes",
    "label",
    "description",
}
_SUPPORTED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_STEP_COMM_FIELDS = {"client_request_id"}
_VARIABLE_EXPRESSION_PATTERN = re.compile(
    r"^{{\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\s*}}$"
)


def _validate_path(path: Any, field: str, allow_short: bool = False) -> None:
    """校验受控对象/数组路径，不执行任意表达式。"""
    text = str(path or "")
    normalized = f"$.{text}" if allow_short and not text.startswith("$.") else text
    if not _PATH_PATTERN.fullmatch(normalized):
        raise FlowConfigError(f"{field} 路径格式错误: {text!r}")


def _validate_extract(rules: Any, field: str) -> None:
    """校验变量提取映射及其中每条路径。"""
    if rules is None:
        return
    if not isinstance(rules, dict):
        raise FlowConfigError(f"{field} 必须是对象")
    for variable_name, path in rules.items():
        if not str(variable_name):
            raise FlowConfigError(f"{field} 包含空变量名")
        _validate_path(path, field)


def _validate_number(value: Any, field: str, minimum: float, maximum: float | None = None) -> float:
    """校验等待相关数值并返回浮点数。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FlowConfigError(f"{field} 必须是数字")
    number = float(value)
    if number < minimum or (maximum is not None and number > maximum):
        limit = f"{minimum}～{maximum}" if maximum is not None else f">= {minimum}"
        raise FlowConfigError(f"{field} 必须在 {limit} 范围内")
    return number


def _validate_flow_inputs(flow_id: str, inputs: Any) -> None:
    """校验 Web 可交互文件输入契约；未声明 inputs 的旧 Flow 保持不变。"""

    if inputs is None:
        return
    if not isinstance(inputs, dict):
        raise FlowConfigError(f"Flow {flow_id}.inputs 必须是对象")
    for input_name, definition in inputs.items():
        if not _VARIABLE_NAME_PATTERN.fullmatch(str(input_name)):
            raise FlowConfigError(f"Flow {flow_id}.inputs 包含非法输入名: {input_name}")
        if not isinstance(definition, dict):
            raise FlowConfigError(f"Flow {flow_id}.inputs.{input_name} 必须是对象")
        unexpected = sorted(set(definition) - _FILE_INPUT_FIELDS)
        if unexpected:
            raise FlowConfigError(
                f"Flow {flow_id}.inputs.{input_name} 包含未知字段: {', '.join(unexpected)}"
            )
        if definition.get("type") != "files":
            raise FlowConfigError(
                f"Flow {flow_id}.inputs.{input_name}.type 仅支持 files"
            )
        if definition.get("required") is not True:
            raise FlowConfigError(
                f"Flow {flow_id}.inputs.{input_name}.required 首期必须为 true"
            )
        min_items = definition.get("min_items")
        max_items = definition.get("max_items")
        if (
            isinstance(min_items, bool)
            or not isinstance(min_items, int)
            or isinstance(max_items, bool)
            or not isinstance(max_items, int)
            or not 1 <= min_items <= max_items <= 9
        ):
            raise FlowConfigError(
                f"Flow {flow_id}.inputs.{input_name} 数量必须满足 1 <= min_items <= max_items <= 9"
            )
        content_types = definition.get("allowed_content_types")
        if (
            not isinstance(content_types, list)
            or not content_types
            or any(item not in _SUPPORTED_IMAGE_CONTENT_TYPES for item in content_types)
        ):
            raise FlowConfigError(
                f"Flow {flow_id}.inputs.{input_name}.allowed_content_types 无效"
            )
        max_size_bytes = definition.get("max_size_bytes")
        if (
            isinstance(max_size_bytes, bool)
            or not isinstance(max_size_bytes, int)
            or not 1 <= max_size_bytes <= 7 * 1024 * 1024
        ):
            raise FlowConfigError(
                f"Flow {flow_id}.inputs.{input_name}.max_size_bytes 必须在 1～7340032"
            )


def _flatten_steps_for_validation(
    flow_id: str,
    steps: list[Any],
    *,
    foreach_depth: int = 0,
) -> list[Any]:
    """展开一层 foreach 以复用既有步骤/Scenario 校验，禁止继续嵌套。"""

    flattened: list[Any] = []
    for position, step in enumerate(steps, start=1):
        flattened.append(step)
        if not isinstance(step, dict) or "foreach" not in step:
            continue
        step_id = str(step.get("id") or f"第 {position} 个步骤")
        if foreach_depth >= 1:
            raise FlowConfigError(f"步骤 {step_id} 不支持嵌套 foreach")
        foreach = step.get("foreach")
        if not isinstance(foreach, dict):
            raise FlowConfigError(f"步骤 {step_id}.foreach 必须是对象")
        unexpected = sorted(set(foreach) - _FOREACH_FIELDS)
        if unexpected:
            raise FlowConfigError(
                f"步骤 {step_id}.foreach 包含未知字段: {', '.join(unexpected)}"
            )
        items = foreach.get("items")
        if not isinstance(items, str) or not _VARIABLE_EXPRESSION_PATTERN.fullmatch(items):
            raise FlowConfigError(
                f"步骤 {step_id}.foreach.items 必须是完整运行时变量占位符"
            )
        item_name = foreach.get("item")
        if not isinstance(item_name, str) or not _VARIABLE_NAME_PATTERN.fullmatch(item_name):
            raise FlowConfigError(f"步骤 {step_id}.foreach.item 必须是有效变量名")
        collect = foreach.get("collect") or {}
        if not isinstance(collect, dict):
            raise FlowConfigError(f"步骤 {step_id}.foreach.collect 必须是对象")
        for variable_name, expression in collect.items():
            if not _VARIABLE_NAME_PATTERN.fullmatch(str(variable_name)):
                raise FlowConfigError(
                    f"步骤 {step_id}.foreach.collect 包含非法变量名: {variable_name}"
                )
            if not isinstance(expression, str) or not _VARIABLE_EXPRESSION_PATTERN.fullmatch(
                expression
            ):
                raise FlowConfigError(
                    f"步骤 {step_id}.foreach.collect.{variable_name} 必须是完整变量占位符"
                )
        child_steps = foreach.get("steps")
        if not isinstance(child_steps, list) or not child_steps:
            raise FlowConfigError(f"步骤 {step_id}.foreach.steps 必须是非空数组")
        flattened.extend(
            _flatten_steps_for_validation(
                flow_id,
                child_steps,
                foreach_depth=foreach_depth + 1,
            )
        )
    return flattened


def _validate_flow(
    flow_id: str,
    flow: dict[str, Any],
    scenario: dict[str, Any],
    api_definitions: dict[str, dict[str, Any]],
) -> list[str]:
    """校验一个 Flow 与 Scenario，并返回按步骤顺序引用的 API ID。

    参数说明:
        flow_id: Flow 文件名 stem，用于错误定位。
        flow: Flow YAML 根对象。
        scenario: 同名 Scenario YAML 根对象。
        api_definitions: ApiLoader 返回的完整 API 注册表。

    返回值:
        当前 Flow 按首次出现顺序引用的去重 API ID 列表。

    异常说明:
        FlowConfigError: 步骤动作、API 引用、Scenario 数据、路径或等待参数
        不符合 V1.3 设计时抛出，确保错误发生在网络请求前。
    """
    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise FlowConfigError(f"Flow {flow_id} 必须配置非空 steps")
    _validate_flow_inputs(flow_id, flow.get("inputs"))
    steps = _flatten_steps_for_validation(flow_id, steps)

    step_ids: set[str] = set()
    api_step_ids: list[str] = []
    api_step_id_set: set[str] = set()
    referenced_api_ids: list[str] = []
    for position, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise FlowConfigError(f"Flow {flow_id} 第 {position} 个步骤必须是对象")
        step_id = str(step.get("id") or "")
        if not step_id:
            raise FlowConfigError(f"Flow {flow_id} 第 {position} 个步骤缺少 id")
        if step_id in step_ids:
            raise FlowConfigError(f"Flow {flow_id} 存在重复 step id: {step_id}")
        step_ids.add(step_id)

        if "call" in step:
            raise FlowConfigError(
                f"步骤 {step_id} 不再支持 call，请改用 api 引用接口定义"
            )
        actions = [key for key in ("api", "action", "wait", "foreach") if key in step]
        if len(actions) != 1:
            raise FlowConfigError(
                f"步骤 {step_id} 必须且只能配置 api、action、wait、foreach 之一"
            )

        if "api" in step:
            api_id = step["api"]
            if not isinstance(api_id, str) or not api_id.strip():
                raise FlowConfigError(f"步骤 {step_id}.api 必须是非空字符串")
            api_id = api_id.strip()
            step["api"] = api_id
            if api_id not in api_definitions:
                raise FlowConfigError(
                    f"步骤 {step_id} 引用的 API 不存在: {api_id}"
                )
            api_step_ids.append(step_id)
            api_step_id_set.add(step_id)
            if api_id not in referenced_api_ids:
                referenced_api_ids.append(api_id)
            _validate_extract(step.get("extract"), f"步骤 {step_id}.extract")
            _validate_extract(
                step.get("optional_extract"),
                f"步骤 {step_id}.optional_extract",
            )
        elif "extract" in step or "optional_extract" in step:
            raise FlowConfigError(
                f"步骤 {step_id} 的 extract、optional_extract 只能用于 api 步骤"
            )

        for condition_name in ("skip_if", "skip_unless"):
            if condition_name not in step:
                continue
            condition = step[condition_name]
            if not isinstance(condition, dict):
                raise FlowConfigError(f"步骤 {step_id}.{condition_name} 必须是对象")
            variable = condition.get("variable")
            if not isinstance(variable, str) or not _VARIABLE_NAME_PATTERN.fullmatch(variable):
                raise FlowConfigError(
                    f"步骤 {step_id}.{condition_name}.variable 必须是有效变量名"
                )
            if "equals" not in condition:
                raise FlowConfigError(f"步骤 {step_id}.{condition_name} 缺少 equals")

        if "until" in step and "api" not in step:
            raise FlowConfigError(
                f"步骤 {step_id} 的 until 只能用于 api 步骤"
            )
        if "run_on_termination" in step:
            if "api" not in step or not isinstance(step["run_on_termination"], bool):
                raise FlowConfigError(
                    f"步骤 {step_id}.run_on_termination 只能为 API 步骤的布尔值"
                )
        if "action" in step:
            action = step["action"]
            if action == "prepared_media_upload":
                pass
            elif not isinstance(action, dict):
                raise FlowConfigError(
                    f"步骤 {step_id} 包含未知 action: {action}"
                )
            elif action.get("type") == "signed_binary_upload":
                unexpected = sorted(set(action) - _SIGNED_UPLOAD_FIELDS)
                if unexpected:
                    raise FlowConfigError(
                        f"步骤 {step_id}.action 包含未知字段: {', '.join(unexpected)}"
                    )
                for field in ("url", "headers"):
                    if not isinstance(action.get(field), str) or not action[field].strip():
                        raise FlowConfigError(
                            f"步骤 {step_id}.action.{field} 必须为非空字符串"
                        )
                sources = [
                    field
                    for field in ("fixture", "input_file")
                    if isinstance(action.get(field), str) and action[field].strip()
                ]
                if len(sources) != 1:
                    raise FlowConfigError(
                        f"步骤 {step_id}.action.fixture 与 input_file 必须二选一"
                    )
                method = action.get("method", "PUT")
                if method != "PUT":
                    raise FlowConfigError(
                        f"步骤 {step_id}.action.method 首期仅支持 PUT"
                    )
                statuses = action.get("success_statuses", [200, 201, 202, 204])
                if not isinstance(statuses, list) or not statuses or any(
                    isinstance(status, bool)
                    or not isinstance(status, int)
                    or not 100 <= status <= 599
                    for status in statuses
                ):
                    raise FlowConfigError(
                        f"步骤 {step_id}.action.success_statuses 必须是 HTTP 状态码数组"
                    )
            elif action.get("type") == "validate_binary_inputs":
                unexpected = sorted(set(action) - _VALIDATE_BINARY_INPUT_FIELDS)
                if unexpected:
                    raise FlowConfigError(
                        f"步骤 {step_id}.action 包含未知字段: {', '.join(unexpected)}"
                    )
                for field in (
                    "files",
                    "allowed_content_types",
                    "min_items",
                    "max_items",
                    "max_size_bytes",
                ):
                    if field not in action:
                        raise FlowConfigError(
                            f"步骤 {step_id}.action.validate_binary_inputs 缺少 {field}"
                        )
            else:
                raise FlowConfigError(
                    f"步骤 {step_id}.action.type 不支持: {action.get('type')}"
                )
        elif "wait" in step:
            wait = step["wait"]
            if not isinstance(wait, dict) or "seconds" not in wait:
                raise FlowConfigError(f"步骤 {step_id} 的 wait 必须配置 seconds")
            _validate_number(wait["seconds"], f"步骤 {step_id}.wait.seconds", 0, 300)
        if "until" in step:
            until = step["until"]
            if not isinstance(until, dict):
                raise FlowConfigError(f"步骤 {step_id}.until 必须是对象")
            _validate_path(until.get("path"), f"步骤 {step_id}.until.path")
            if "equals" not in until:
                raise FlowConfigError(f"步骤 {step_id}.until 缺少 equals")
            if "terminate_on" in until:
                terminate_on = until["terminate_on"]
                if (
                    not isinstance(terminate_on, list)
                    or not terminate_on
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in terminate_on
                    )
                    or len(set(terminate_on)) != len(terminate_on)
                ):
                    raise FlowConfigError(
                        f"步骤 {step_id}.until.terminate_on "
                        "必须是不重复的非空字符串数组"
                    )
            if "continue_flow_on" in until:
                continue_flow_on = until["continue_flow_on"]
                if (
                    not isinstance(continue_flow_on, list)
                    or not continue_flow_on
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in continue_flow_on
                    )
                    or len(set(continue_flow_on)) != len(continue_flow_on)
                ):
                    raise FlowConfigError(
                        f"步骤 {step_id}.until.continue_flow_on "
                        "必须是不重复的非空字符串数组"
                    )
                terminate_on = until.get("terminate_on")
                if not terminate_on or any(
                    value not in terminate_on for value in continue_flow_on
                ):
                    # continue_flow_on 只负责细分 terminate_on 中的业务终态。
                    # 强制子集关系可在项目加载时发现拼写错误，避免运行时静默
                    # 把本应失败的状态继续执行。
                    raise FlowConfigError(
                        f"步骤 {step_id}.until.continue_flow_on "
                        "必须是 terminate_on 的子集"
                    )
            if "fail_on_termination" in until:
                if not isinstance(until["fail_on_termination"], bool):
                    raise FlowConfigError(
                        f"步骤 {step_id}.until.fail_on_termination 必须是布尔值"
                    )
                if until["fail_on_termination"] and not until.get("terminate_on"):
                    raise FlowConfigError(
                        f"步骤 {step_id}.until.fail_on_termination 需要 terminate_on"
                    )
            if "retry_on_business_error_codes" in until:
                retry_codes = until["retry_on_business_error_codes"]
                if (
                    not isinstance(retry_codes, list)
                    or not retry_codes
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in retry_codes
                    )
                    or len(set(retry_codes)) != len(retry_codes)
                ):
                    raise FlowConfigError(
                        f"步骤 {step_id}.until.retry_on_business_error_codes "
                        "必须是不重复的非空字符串数组"
                    )
            interval_value = until.get("interval_seconds")
            timeout_value = until.get("timeout_seconds")
            # 平台 Release 的轮询值在运行时注入，因此完整占位符在静态阶段只校验
            # 变量语法；字面量仍沿用原有边界校验。
            if isinstance(interval_value, str) and _VARIABLE_EXPRESSION_PATTERN.fullmatch(
                interval_value
            ):
                interval = None
            else:
                interval = _validate_number(
                    interval_value,
                    f"步骤 {step_id}.until.interval_seconds",
                    0.000001,
                )
            if isinstance(timeout_value, str) and _VARIABLE_EXPRESSION_PATTERN.fullmatch(
                timeout_value
            ):
                timeout = None
            else:
                timeout = _validate_number(
                    timeout_value,
                    f"步骤 {step_id}.until.timeout_seconds",
                    interval or 0.000001,
                )
            if interval is not None and timeout is not None and timeout < interval:
                raise FlowConfigError(f"步骤 {step_id} 的轮询超时不得小于间隔")

    step_data = scenario.get("step_data")
    if step_data is None:
        step_data = {}
    if not isinstance(step_data, dict):
        raise FlowConfigError(f"Scenario {flow_id}.step_data 必须是对象")
    unknown_steps = set(step_data) - step_ids
    if unknown_steps:
        names = ", ".join(sorted(unknown_steps))
        raise FlowConfigError(f"Scenario {flow_id} 引用了不存在的 step id: {names}")

    non_api_steps = set(step_data) - api_step_id_set
    if non_api_steps:
        names = ", ".join(sorted(non_api_steps))
        raise FlowConfigError(
            f"Scenario 步骤 {names} 配置了 step_data，"
            "仅 API 步骤允许配置接口数据"
        )

    for step_id in api_step_ids:
        if step_id not in step_data:
            raise FlowConfigError(
                f"API 步骤 {step_id} 缺少 Scenario step_data"
            )
        configured_data = step_data[step_id]
        if not isinstance(configured_data, dict):
            raise FlowConfigError(f"Scenario 步骤 {step_id} 数据必须是对象")
        if "params" not in configured_data:
            raise FlowConfigError(f"Scenario 步骤 {step_id} 缺少 params")
        if not isinstance(configured_data["params"], dict):
            raise FlowConfigError(
                f"Scenario 步骤 {step_id}.params 必须是对象"
            )
        comm = configured_data.get("comm")
        if comm is not None:
            if not isinstance(comm, dict):
                raise FlowConfigError(f"Scenario 步骤 {step_id}.comm 必须是对象")
            unexpected_comm_fields = sorted(set(comm) - _STEP_COMM_FIELDS)
            if unexpected_comm_fields:
                raise FlowConfigError(
                    f"Scenario 步骤 {step_id}.comm 包含禁止字段: "
                    + ", ".join(unexpected_comm_fields)
                )
            client_request_id = comm.get("client_request_id")
            if (
                not isinstance(client_request_id, str)
                or not client_request_id.strip()
            ):
                raise FlowConfigError(
                    f"Scenario 步骤 {step_id}.comm.client_request_id 必须是非空字符串"
                )
        if "assert" not in configured_data:
            raise FlowConfigError(f"Scenario 步骤 {step_id} 缺少 assert")
        assertions = configured_data["assert"]
        if not isinstance(assertions, dict):
            raise FlowConfigError(f"Scenario 步骤 {step_id}.assert 必须是对象")
        for assertion_name in ("data_equals", "data_not_equals"):
            expected_values = assertions.get(assertion_name)
            if expected_values is None:
                expected_values = {}
            if not isinstance(expected_values, dict):
                raise FlowConfigError(
                    f"Scenario 步骤 {step_id}.{assertion_name} 必须是对象"
                )
            for path in expected_values:
                _validate_path(
                    path,
                    f"Scenario 步骤 {step_id}.{assertion_name}",
                    allow_short=True,
                )
    return referenced_api_ids


def load_flow_cases(
    project_root: Path,
    selected_flow: str | None = None,
) -> list[dict[str, Any]]:
    """加载并校验全部或指定 Flow/Scenario 配对。

    参数说明:
        project_root: 项目根目录。
        selected_flow: 可选 Flow 文件名，不含 ``.yaml``。

    返回值:
        每项包含 id、name、tags、flow、scenario 和当前引用 API 子集的流程
        用例列表。

    异常说明:
        ApiConfigError: API 定义目录或具体定义不合法时由 ApiLoader 抛出。
        FlowConfigError: 配对缺失、筛选名称不存在或配置不合法时抛出。
    """
    flows_directory = project_root / "data" / "flows"
    scenarios_directory = project_root / "data" / "scenarios"
    paths = _safe_yaml_paths(flows_directory, project_root, "Flow")
    available = [path.stem for path in paths]
    scenario_names = {
        path.stem
        for path in _safe_yaml_paths(scenarios_directory, project_root, "Scenario")
    }
    orphan_scenarios = scenario_names - set(available)
    if orphan_scenarios:
        names = ", ".join(sorted(orphan_scenarios))
        raise FlowConfigError(f"Scenario 缺少同名 Flow: {names}")
    if selected_flow:
        # Flow 是项目内逻辑 ID，不是文件路径。禁止 ``Path.stem`` 静默把
        # ``../flow``、绝对路径或 ``flow.yaml`` 归一成可执行资产，确保 CLI
        # 与 Web 的路径穿越边界一致。
        if not _FLOW_ID_PATTERN.fullmatch(selected_flow):
            raise FlowConfigError(f"Flow ID 不合法: {selected_flow!r}")
        normalized = selected_flow
        paths = [path for path in paths if path.stem == normalized]
        if not paths:
            names = ", ".join(available) or "无"
            raise FlowConfigError(f"Flow 不存在: {normalized}；可用 Flow: {names}")

    api_definitions = load_api_definitions(project_root)
    flow_cases: list[dict[str, Any]] = []
    for flow_path in paths:
        scenario_path = scenarios_directory / flow_path.name
        if not scenario_path.is_file():
            raise FlowConfigError(f"Flow {flow_path.stem} 缺少同名 Scenario 文件")
        flow = load_yaml(flow_path)
        scenario = load_yaml(scenario_path)
        referenced_api_ids = _validate_flow(
            flow_path.stem,
            flow,
            scenario,
            api_definitions,
        )
        try:
            # Scenario 拥有 step_data，因此运行时字段也必须从同名 Scenario
            # 解析；Flow 的文件输入与拓扑继续由原校验逻辑负责。
            runtime_inputs = validate_flow_runtime_inputs(
                flow,
                scenario,
                scope=f"Flow {flow_path.stem}",
            )
        except RuntimeOverrideError as exc:
            raise FlowConfigError(exc.message) from exc
        tags = flow.get("tags") or []
        if not isinstance(tags, list):
            raise FlowConfigError(f"Flow {flow_path.stem}.tags 必须是数组")
        flow_cases.append(
            {
                "id": flow_path.stem,
                "name": str(flow.get("name") or flow_path.stem),
                "tags": [str(tag) for tag in tags],
                "runtime_inputs": runtime_inputs,
                "flow": flow,
                "scenario": scenario,
                "api_definitions": {
                    api_id: deepcopy(api_definitions[api_id])
                    for api_id in referenced_api_ids
                },
            }
        )
    return flow_cases
