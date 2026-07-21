"""Flow 与同名 Scenario YAML 的加载和静态校验。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from utils.custom.config_loader import load_yaml


class FlowConfigError(ValueError):
    """表示 Flow/Scenario 配对或步骤配置不合法。"""


_PATH_PATTERN = re.compile(
    r"^\$\.[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[\d+]))*$"
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


def _validate_flow(
    flow_id: str,
    flow: dict[str, Any],
    scenario: dict[str, Any],
    cases_directory: Path,
) -> None:
    """校验一个 Flow 与 Scenario，确保错误发生在网络请求前。"""
    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        raise FlowConfigError(f"Flow {flow_id} 必须配置非空 steps")

    step_ids: set[str] = set()
    for position, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise FlowConfigError(f"Flow {flow_id} 第 {position} 个步骤必须是对象")
        step_id = str(step.get("id") or "")
        if not step_id:
            raise FlowConfigError(f"Flow {flow_id} 第 {position} 个步骤缺少 id")
        if step_id in step_ids:
            raise FlowConfigError(f"Flow {flow_id} 存在重复 step id: {step_id}")
        step_ids.add(step_id)

        actions = [key for key in ("call", "action", "wait") if key in step]
        if len(actions) != 1:
            raise FlowConfigError(f"步骤 {step_id} 必须且只能配置 call、action、wait 之一")
        if "call" in step:
            case_name = str(step["call"])
            case_path = cases_directory / case_name
            if not case_path.is_file():
                raise FlowConfigError(f"步骤 {step_id} 引用的 case 不存在: {case_name}")
            _validate_extract(load_yaml(case_path).get("extract"), f"case {case_name}.extract")
        if "action" in step and step["action"] != "prepared_media_upload":
            raise FlowConfigError(f"步骤 {step_id} 包含未知 action: {step['action']}")
        _validate_extract(step.get("extract"), f"步骤 {step_id}.extract")
        if "wait" in step:
            wait = step["wait"]
            if not isinstance(wait, dict) or "seconds" not in wait:
                raise FlowConfigError(f"步骤 {step_id} 的 wait 必须配置 seconds")
            _validate_number(wait["seconds"], f"步骤 {step_id}.wait.seconds", 0, 300)
        if "until" in step:
            until = step["until"]
            if "call" not in step or not isinstance(until, dict):
                raise FlowConfigError(f"步骤 {step_id} 的 until 只能用于 call")
            _validate_path(until.get("path"), f"步骤 {step_id}.until.path")
            if "equals" not in until:
                raise FlowConfigError(f"步骤 {step_id}.until 缺少 equals")
            interval = _validate_number(
                until.get("interval_seconds"),
                f"步骤 {step_id}.until.interval_seconds",
                0.000001,
            )
            timeout = _validate_number(
                until.get("timeout_seconds"),
                f"步骤 {step_id}.until.timeout_seconds",
                interval,
            )
            if timeout < interval:
                raise FlowConfigError(f"步骤 {step_id} 的轮询超时不得小于间隔")

    step_data = scenario.get("step_data") or {}
    if not isinstance(step_data, dict):
        raise FlowConfigError(f"Scenario {flow_id}.step_data 必须是对象")
    unknown_steps = set(step_data) - step_ids
    if unknown_steps:
        names = ", ".join(sorted(unknown_steps))
        raise FlowConfigError(f"Scenario {flow_id} 引用了不存在的 step id: {names}")
    for step_id, configured_data in step_data.items():
        if not isinstance(configured_data, dict):
            raise FlowConfigError(f"Scenario 步骤 {step_id} 数据必须是对象")
        assertions = configured_data.get("assert") or {}
        if not isinstance(assertions, dict):
            raise FlowConfigError(f"Scenario 步骤 {step_id}.assert 必须是对象")
        data_equals = assertions.get("data_equals") or {}
        if not isinstance(data_equals, dict):
            raise FlowConfigError(f"Scenario 步骤 {step_id}.data_equals 必须是对象")
        for path in data_equals:
            _validate_path(path, f"Scenario 步骤 {step_id}.data_equals", allow_short=True)


def load_flow_cases(
    project_root: Path,
    selected_flow: str | None = None,
) -> list[dict[str, Any]]:
    """加载并校验全部或指定 Flow/Scenario 配对。

    参数说明:
        project_root: 项目根目录。
        selected_flow: 可选 Flow 文件名，不含 ``.yaml``。

    返回值:
        每项包含 id、name、tags、flow 和 scenario 的流程用例列表。

    异常说明:
        FlowConfigError: 配对缺失、筛选名称不存在或配置不合法时抛出。
    """
    flows_directory = project_root / "data" / "flows"
    scenarios_directory = project_root / "data" / "scenarios"
    cases_directory = project_root / "data" / "cases"
    paths = sorted(flows_directory.glob("*.yaml"))
    available = [path.stem for path in paths]
    scenario_names = {
        path.stem for path in sorted(scenarios_directory.glob("*.yaml"))
    }
    orphan_scenarios = scenario_names - set(available)
    if orphan_scenarios:
        names = ", ".join(sorted(orphan_scenarios))
        raise FlowConfigError(f"Scenario 缺少同名 Flow: {names}")
    if selected_flow:
        normalized = Path(selected_flow).stem
        paths = [path for path in paths if path.stem == normalized]
        if not paths:
            names = ", ".join(available) or "无"
            raise FlowConfigError(f"Flow 不存在: {normalized}；可用 Flow: {names}")

    flow_cases: list[dict[str, Any]] = []
    for flow_path in paths:
        scenario_path = scenarios_directory / flow_path.name
        if not scenario_path.is_file():
            raise FlowConfigError(f"Flow {flow_path.stem} 缺少同名 Scenario 文件")
        flow = load_yaml(flow_path)
        scenario = load_yaml(scenario_path)
        _validate_flow(flow_path.stem, flow, scenario, cases_directory)
        tags = flow.get("tags") or []
        if not isinstance(tags, list):
            raise FlowConfigError(f"Flow {flow_path.stem}.tags 必须是数组")
        flow_cases.append(
            {
                "id": flow_path.stem,
                "name": str(flow.get("name") or flow_path.stem),
                "tags": [str(tag) for tag in tags],
                "flow": flow,
                "scenario": scenario,
            }
        )
    return flow_cases
