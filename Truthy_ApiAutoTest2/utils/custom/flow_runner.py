"""标准 Flow 步骤执行器。"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from utils.custom.api_loader import build_execution_case
from utils.custom.assertions import assert_data_equals, assert_gateway_response
from utils.custom.logger import get_logger
from utils.custom.runtime_context import RuntimeContext, RuntimeContextError
from utils.third_party.allure_reporter import attach_json, step as report_step

LOGGER = get_logger(__name__)
_ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)}$")


class FlowExecutionError(RuntimeError):
    """表示 Flow 步骤、轮询或上传在运行期间失败。"""


class FlowEnvironmentError(FlowExecutionError):
    """表示 Scenario 引用的环境变量或媒体文件不可用。"""


class FlowRunner:
    """按 Flow YAML 顺序执行调用、等待、轮询和 COS 上传。"""

    def __init__(
        self,
        project_root: Path,
        gateway_factory: Callable[[RuntimeContext], Any],
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """保存执行依赖，不在初始化阶段创建运行时上下文。

        参数说明:
            project_root: 项目根目录；保留该参数以维持现有构造接口，V1.3
                普通 API 步骤不再通过该路径读取 case YAML。
            gateway_factory: 根据本次 Flow 上下文创建 GatewayApi 的工厂。
            sleep: 等待函数，允许单元测试注入替身。
            monotonic: 单调时钟，允许测试轮询超时而不真实等待。
            environ: 环境变量映射；为空时使用当前进程环境。
        """
        self.project_root = project_root
        self.gateway_factory = gateway_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.environ = environ if environ is not None else os.environ

    def run(self, flow_case: dict[str, Any]) -> RuntimeContext:
        """执行一条 Flow/Scenario 配对并返回独立运行时上下文。

        参数说明:
            flow_case: FlowLoader 返回的流程用例对象。

        返回值:
            当前 Flow 独立的 RuntimeContext，供测试或后续诊断读取。

        异常说明:
            FlowExecutionError: 步骤动作不支持、轮询超时或上传失败时抛出。
            RuntimeContextError: 请求变量或提取路径无效时抛出。
        """
        flow = flow_case.get("flow") or {}
        scenario = flow_case.get("scenario") or {}
        api_definitions = flow_case.get("api_definitions") or {}
        initial = self._resolve_environment(scenario.get("variables") or {})
        context = RuntimeContext(initial)
        self._prepare_media_metadata(context)
        gateway = self.gateway_factory(context)
        steps = flow.get("steps") or []

        for position, step in enumerate(steps, start=1):
            step_id = str(step.get("id") or f"step_{position}")
            step_title = self._build_step_title(
                step,
                step_id,
                position,
                len(steps),
            )
            LOGGER.info(
                "开始 Flow 步骤: flow=%s scenario=%s step=%s (%s/%s)",
                flow_case.get("name") or flow_case.get("id"),
                scenario.get("name") or flow_case.get("id"),
                step_id,
                position,
                len(steps),
            )
            with report_step(step_title):
                if "wait" in step:
                    self.sleep(float(step["wait"]["seconds"]))
                elif "action" in step:
                    self._execute_action(str(step["action"]), gateway, context)
                elif "api" in step:
                    step_data = (scenario.get("step_data") or {}).get(step_id) or {}
                    self._execute_api(
                        step,
                        step_data,
                        api_definitions,
                        gateway,
                        context,
                    )
                else:
                    raise FlowExecutionError(f"步骤 {step_id} 没有可执行动作")
            LOGGER.info("完成 Flow 步骤: step=%s", step_id)
        return context

    @staticmethod
    def _build_step_title(
        step: dict[str, Any],
        step_id: str,
        position: int,
        total: int,
    ) -> str:
        """构造 Flow 顶层步骤的稳定报告标题。

        参数说明:
            step: 当前 Flow 步骤。
            step_id: 当前步骤 ID。
            position: 当前步骤从 1 开始的位置。
            total: Flow 顶层步骤总数。

        返回值:
            包含位置、步骤 ID 和动作信息的中文标题。

        异常说明:
            无。未知步骤返回缺少动作的诊断标题，随后由执行逻辑抛出原异常。
        """
        prefix = f"{position}/{total} {step_id}："
        if "api" in step:
            return f"{prefix}{step['api']}"
        if "wait" in step:
            return f"{prefix}等待 {step['wait']['seconds']}s"
        if "action" in step:
            return f"{prefix}{step['action']}"
        return f"{prefix}未知动作"

    def _execute_api(
        self,
        step: dict[str, Any],
        step_data: dict[str, Any],
        api_definitions: dict[str, dict[str, Any]],
        gateway: Any,
        context: RuntimeContext,
    ) -> None:
        """使用 API 路由和 Scenario 完整数据执行普通调用或轮询。

        参数说明:
            step: 当前 Flow API 步骤。
            step_data: Scenario 中与 step ID 对应的完整 params 和 assert。
            api_definitions: FlowLoader 注入的当前流程 API 定义子集。
            gateway: 当前 Flow 独立上下文绑定的 GatewayApi。
            context: 当前 Flow 的 RuntimeContext。

        返回值:
            无。断言和提取成功后更新 context。

        异常说明:
            FlowExecutionError: API 定义或 Scenario 步骤数据缺失时抛出。
            RuntimeContextError: 参数、断言变量或提取路径无法解析时抛出。
            AssertionError: Gateway 响应或 data_equals 不符合预期时抛出。
        """
        step_id = str(step.get("id") or "unknown")
        api_id = str(step.get("api") or "")
        api_definition = api_definitions.get(api_id)
        if not isinstance(api_definition, dict):
            raise FlowExecutionError(
                f"步骤 {step_id} 缺少已加载的 API 定义: {api_id or 'unknown'}"
            )
        if not isinstance(step_data, dict):
            raise FlowExecutionError(f"步骤 {step_id} 的 Scenario 数据必须是对象")
        if "params" not in step_data or "assert" not in step_data:
            raise FlowExecutionError(
                f"步骤 {step_id} 的 Scenario 必须提供完整 params 和 assert"
            )

        # V1.3 直接使用 Scenario 的完整数据，不读取或合并单接口 case。
        # 参数占位符由 GatewayApi.build_payload 统一解析，因为该层会先生成每次
        # 请求独有的 client_request_id；FlowRunner 只提前解析响应断言。
        params = deepcopy(step_data["params"])
        assertions = context.resolve(step_data["assert"])
        case = build_execution_case(
            api_definition,
            params,
            assertions,
        )

        if step.get("until"):
            data = self._poll(step, case, gateway, context)
        else:
            response = gateway.invoke(case)
            data = assert_gateway_response(response, case["assert"])
        self._finalize_api(step, case, data, context)

    def _poll(
        self,
        step: dict[str, Any],
        case: dict[str, Any],
        gateway: Any,
        context: RuntimeContext,
    ) -> dict[str, Any]:
        """重复调用当前 case，直到受控路径值等于期望值或超时。"""
        until = step["until"]
        path = str(until["path"])
        expected = context.resolve(until["equals"])
        interval = float(until["interval_seconds"])
        deadline = self.monotonic() + float(until["timeout_seconds"])
        attempts = 0
        last_value: Any = None

        while True:
            attempts += 1
            with report_step(f"第 {attempts} 次轮询"):
                response = gateway.invoke(case)
                data = assert_gateway_response(response, case["assert"])
                last_value = RuntimeContext.read_path(data, path)
                matched = last_value == expected
                attach_json(
                    "轮询结果",
                    {
                        "path": path,
                        "actual": last_value,
                        "expected": expected,
                        "matched": matched,
                    },
                )
            if matched:
                return data
            now = self.monotonic()
            if now >= deadline:
                step_id = step.get("id") or "unknown"
                raise FlowExecutionError(
                    f"轮询步骤 {step_id} 超时: 最后实际值 {last_value!r}，调用次数 {attempts}"
                )
            self.sleep(min(interval, deadline - now))

    @staticmethod
    def _finalize_api(
        step: dict[str, Any],
        case: dict[str, Any],
        data: dict[str, Any],
        context: RuntimeContext,
    ) -> None:
        """执行已解析的场景值断言和 Flow step 响应提取。"""
        expected_values = (case.get("assert") or {}).get("data_equals") or {}
        assert_data_equals(data, expected_values)
        extract_rules = step.get("extract") or {}
        if extract_rules:
            context.extract(data, extract_rules)

    def _execute_action(
        self,
        action: str,
        gateway: Any,
        context: RuntimeContext,
    ) -> None:
        """执行已注册的特殊动作；V1.2 仅保留已有媒体 PUT。"""
        if action != "prepared_media_upload":
            raise FlowExecutionError(f"不支持的 Flow action: {action}")
        media_path = Path(str(context.get("media_file") or "")).expanduser()
        if not media_path.is_file():
            raise FlowEnvironmentError(f"媒体文件不存在: {media_path}")
        content = media_path.read_bytes()
        upload_url = context.get("upload_url")
        upload_headers = context.get("upload_headers")
        if not isinstance(upload_url, str) or not upload_url:
            raise RuntimeContextError("运行时变量 upload_url 未定义或格式错误")
        if not isinstance(upload_headers, dict):
            raise RuntimeContextError("运行时变量 upload_headers 未定义或格式错误")
        declared_length = upload_headers.get("Content-Length")
        if declared_length is not None and int(declared_length) != len(content):
            raise FlowExecutionError("上传请求头 Content-Length 与媒体文件大小不一致")
        response = gateway.http_client.put_bytes(
            url=upload_url,
            headers=upload_headers,
            content=content,
            timeout=float(gateway.settings.get("timeout", 15)),
        )
        if not 200 <= response.status_code < 300:
            raise FlowExecutionError(f"媒体 PUT 上传失败: HTTP {response.status_code}")

    def _prepare_media_metadata(self, context: RuntimeContext) -> None:
        """在 PrepareMediaUpload 前写入本地媒体文件实际字节数。"""
        media_file = context.get("media_file")
        if not media_file:
            return
        media_path = Path(str(media_file)).expanduser()
        if not media_path.is_file():
            raise FlowEnvironmentError(f"媒体文件不存在: {media_path}")
        context.set("media_size_bytes", media_path.stat().st_size)

    def _resolve_environment(self, value: Any) -> Any:
        """递归解析 Scenario 中完整的 ``${ENV_NAME}`` 环境变量。"""
        if isinstance(value, dict):
            return {key: self._resolve_environment(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_environment(item) for item in value]
        if not isinstance(value, str):
            return deepcopy(value)
        match = _ENV_PATTERN.match(value)
        if not match:
            return value
        variable_name = match.group(1)
        if variable_name not in self.environ:
            raise FlowEnvironmentError(f"缺少 Flow 环境变量: {variable_name}")
        return self.environ[variable_name]
