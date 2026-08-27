"""标准 Flow 步骤执行器。"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
        runtime_variables: Mapping[str, Any] | None = None,
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
        self.runtime_variables = deepcopy(dict(runtime_variables or {}))

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
        initial = {
            **self.runtime_variables,
            **self._resolve_environment(scenario.get("variables") or {}),
        }
        context = RuntimeContext(initial)
        self._prepare_media_metadata(context)
        gateway = self.gateway_factory(context)
        steps = flow.get("steps") or []

        flow_terminated = False
        pending_error: Exception | None = None
        for position, step in enumerate(steps, start=1):
            step_id = str(step.get("id") or f"step_{position}")
            if flow_terminated and not step.get("run_on_termination", False):
                LOGGER.info("因流程终态跳过 Flow 步骤: step=%s", step_id)
                continue
            if self._should_skip_step(step, context):
                LOGGER.info("因条件跳过 Flow 步骤: step=%s", step_id)
                continue
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
            try:
                with report_step(step_title):
                    if "wait" in step:
                        self.sleep(float(context.resolve(step["wait"]["seconds"])))
                    elif "action" in step:
                        self._execute_action(step["action"], gateway, context)
                    elif "api" in step:
                        step_data = (scenario.get("step_data") or {}).get(step_id) or {}
                        should_terminate = self._execute_api(
                            step,
                            step_data,
                            api_definitions,
                            gateway,
                            context,
                        )
                    else:
                        raise FlowExecutionError(f"步骤 {step_id} 没有可执行动作")
            except Exception as exc:
                # Gateway 分层断言、变量解析、网络异常与公共动作错误都可能发生
                # 在已创建远端私密数据之后。任何普通执行异常都先进入终止清理，
                # 再原样抛出首个错误；KeyboardInterrupt/SystemExit 不属于 Exception，
                # 仍交给进程级取消/终止机制处理。
                if pending_error is None:
                    pending_error = exc
                flow_terminated = True
                LOGGER.error("Flow 步骤失败，进入终止清理: step=%s error=%s", step_id, exc)
                continue
            LOGGER.info("完成 Flow 步骤: step=%s", step_id)
            if "api" in step and should_terminate:
                flow_terminated = True
                LOGGER.info(
                    "Flow 命中轮询终态: step=%s；仅继续执行标记 run_on_termination 的步骤",
                    step_id,
                )
        if pending_error is not None:
            raise pending_error
        return context

    @staticmethod
    def _should_skip_step(step: dict[str, Any], context: RuntimeContext) -> bool:
        """根据步骤 ``skip_if`` 条件判断是否跳过当前步骤。

        参数说明:
            step: 当前 Flow 步骤；可选 ``skip_if`` 使用 ``variable`` 读取运行时
                变量，并在其值等于 ``equals`` 时跳过当前步骤。
            context: 当前 Flow 的运行时上下文。

        返回值:
            bool: 条件命中时返回 True；未配置条件、变量不存在或不匹配时返回 False。

        异常说明:
            RuntimeContextError: ``equals`` 使用了未定义的占位符时抛出。
        """
        skip_if = step.get("skip_if")
        if isinstance(skip_if, dict):
            variable = str(skip_if.get("variable") or "")
            if variable and context.get(variable) == context.resolve(skip_if.get("equals")):
                return True
        skip_unless = step.get("skip_unless")
        if isinstance(skip_unless, dict):
            variable = str(skip_unless.get("variable") or "")
            if variable:
                return context.get(variable) != context.resolve(skip_unless.get("equals"))
        return False

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
    ) -> bool:
        """使用 API 路由和 Scenario 完整数据执行普通调用或轮询。

        参数说明:
            step: 当前 Flow API 步骤。
            step_data: Scenario 中与 step ID 对应的完整 params 和 assert。
            api_definitions: FlowLoader 注入的当前流程 API 定义子集。
            gateway: 当前 Flow 独立上下文绑定的 GatewayApi。
            context: 当前 Flow 的 RuntimeContext。

        返回值:
            bool: 当前轮询步骤命中 ``terminate_on`` 时返回 True，调用方应停止
            执行该 Flow 的后续步骤；其他情况返回 False。

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
            data, should_terminate = self._poll(step, case, gateway, context)
        else:
            response = gateway.invoke(case)
            data = assert_gateway_response(response, case["assert"])
            should_terminate = False
        if should_terminate:
            # 终态响应已通过 Gateway 协议断言；跳过成功态数据断言和提取，
            # 防止 NO_RESULT 被按 SUCCEEDED 的场景断言误判为失败。
            return True
        self._finalize_api(step, case, data, context)
        # Flow 直接调用 invoke 并自行提取变量，不能依赖 GatewayApi.execute 的
        # 单接口持久化路径。仅在断言和提取全部成功后通知可选会话写回钩子，
        # 保证平台 Credential 不会停留在任务启动时的旧 token。
        persist_session = getattr(gateway, "persist_session_state_for_case", None)
        if callable(persist_session):
            persist_session(case)
        return False

    def _poll(
        self,
        step: dict[str, Any],
        case: dict[str, Any],
        gateway: Any,
        context: RuntimeContext,
    ) -> tuple[dict[str, Any], bool]:
        """轮询至成功或声明的终态；终态时通知调用方结束整个 Flow。"""
        until = step["until"]
        path = str(until["path"])
        expected = context.resolve(until["equals"])
        terminal_values = context.resolve(until.get("terminate_on") or [])
        interval = float(context.resolve(until["interval_seconds"]))
        timeout = float(context.resolve(until["timeout_seconds"]))
        if interval <= 0 or timeout < interval:
            raise FlowExecutionError("轮询间隔必须大于 0，且超时不得小于间隔")
        deadline = self.monotonic() + timeout
        attempts = 0
        last_value: Any = None

        while True:
            attempts += 1
            with report_step(f"第 {attempts} 次轮询"):
                response = gateway.invoke(case)
                data = assert_gateway_response(response, case["assert"])
                last_value = RuntimeContext.read_path(data, path)
                matched = last_value == expected
                terminated = not matched and last_value in terminal_values
                poll_summary = {
                    "path": path,
                    "actual": last_value,
                    "expected": expected,
                    "matched": matched,
                }
                # 仅在 YAML 声明终态时附加该信息，保持旧轮询报告结构兼容。
                if terminal_values:
                    poll_summary["terminated"] = terminated
                attach_json(
                    "轮询结果",
                    poll_summary,
                )
            if matched:
                return data, False
            if terminated:
                return data, True
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
        optional_extract_rules = step.get("optional_extract") or {}
        if optional_extract_rules:
            context.extract_optional(data, optional_extract_rules)

    def _execute_action(
        self,
        action: str | dict[str, Any],
        gateway: Any,
        context: RuntimeContext,
    ) -> None:
        """执行通用签名二进制上传；旧动作名仅映射参数，不保留业务实现。"""
        if action == "prepared_media_upload":
            media_value = context.get("media_file")
            if isinstance(media_value, str) and media_value.startswith("fixtures/"):
                media_value = media_value.removeprefix("fixtures/")
            action_config: dict[str, Any] = {
                "type": "signed_binary_upload",
                "url": "{{upload_url}}",
                "headers": "{{upload_headers}}",
                "fixture": media_value,
                "method": "PUT",
                "success_statuses": list(range(200, 300)),
            }
            LOGGER.warning("Flow action prepared_media_upload 已弃用，请改用 signed_binary_upload")
        elif isinstance(action, dict) and action.get("type") == "signed_binary_upload":
            action_config = action
        else:
            raise FlowExecutionError(f"不支持的 Flow action: {action}")

        fixture_value = context.resolve(action_config.get("fixture"))
        if not isinstance(fixture_value, str) or not fixture_value:
            raise FlowEnvironmentError("signed_binary_upload fixture 未配置")
        media_path = self._resolve_fixture_path(fixture_value)
        content = media_path.read_bytes()
        upload_url = context.resolve(action_config.get("url"))
        upload_headers = context.resolve(action_config.get("headers"))
        if not isinstance(upload_url, str) or not upload_url:
            raise RuntimeContextError("signed_binary_upload url 未定义或格式错误")
        if not isinstance(upload_headers, dict):
            raise RuntimeContextError("signed_binary_upload headers 未定义或格式错误")
        method = context.resolve(action_config.get("method", "PUT"))
        if method != "PUT":
            raise FlowExecutionError("signed_binary_upload 首期仅支持 PUT")
        declared_length = upload_headers.get("Content-Length")
        if declared_length is not None and int(declared_length) != len(content):
            raise FlowExecutionError("上传请求头 Content-Length 与媒体文件大小不一致")
        safe_url = self._redact_signed_url(upload_url)
        LOGGER.info("签名二进制上传开始: method=PUT url=%s bytes=%s", safe_url, len(content))
        try:
            response = gateway.http_client.put_bytes(
                url=upload_url,
                headers=upload_headers,
                content=content,
                timeout=float(gateway.settings.get("timeout", 15)),
            )
        except Exception as exc:
            raise FlowExecutionError(
                f"EXTERNAL_UPLOAD_FAILED: NETWORK_ERROR url={safe_url}"
            ) from exc
        success_statuses = context.resolve(
            action_config.get("success_statuses", [200, 201, 202, 204])
        )
        if response.status_code not in success_statuses:
            raise FlowExecutionError(
                f"EXTERNAL_UPLOAD_FAILED: HTTP_{response.status_code} url={safe_url}"
            )
        LOGGER.info("签名二进制上传完成: url=%s status=%s", safe_url, response.status_code)
        output_variable = action_config.get("output")
        if isinstance(output_variable, str) and output_variable:
            context.set(output_variable, response.status_code)

    @staticmethod
    def _redact_signed_url(url: str) -> str:
        """保留域名与对象路径，统一移除全部查询签名。"""
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "<redacted>" if parts.query else "", ""))

    def _resolve_fixture_path(self, fixture: str) -> Path:
        """仅从当前项目 fixtures 读取普通文件，并拒绝符号链接越界。"""
        requested = Path(fixture)
        if requested.is_absolute():
            raise FlowEnvironmentError(f"fixture 路径越界: {fixture}")
        fixture_root = (self.project_root / "fixtures").resolve()
        resolved = (fixture_root / requested).resolve(strict=False)
        try:
            resolved.relative_to(fixture_root)
        except ValueError as exc:
            raise FlowEnvironmentError(f"fixture 路径越界: {fixture}") from exc
        if not resolved.is_file():
            raise FlowEnvironmentError(f"fixture 文件不存在: {fixture}")
        return resolved

    def _prepare_media_metadata(self, context: RuntimeContext) -> None:
        """在 PrepareMediaUpload 前写入本地媒体文件实际字节数。"""
        media_path = self._resolve_media_path(context)
        if media_path is None:
            return
        if not media_path.is_file():
            raise FlowEnvironmentError(f"媒体文件不存在: {media_path}")
        context.set("media_size_bytes", media_path.stat().st_size)

    def _resolve_media_path(
        self,
        context: RuntimeContext,
        required: bool = False,
    ) -> Path | None:
        """解析 Scenario 中声明的媒体文件路径。

        功能说明:
            允许 YAML 直接写入相对项目根目录的路径，例如
            ``data/photo/face.jpeg``；绝对路径和 ``~`` 路径保持原有兼容。

        参数说明:
            context: 当前 Flow 的运行时上下文，读取其中的 ``media_file``。
            required: 为 True 时缺少 ``media_file`` 立即抛出环境配置异常。

        返回值:
            Path: 已展开并规范为项目绝对位置的媒体路径。
            None: 未声明媒体文件且 ``required`` 为 False 时返回。

        异常说明:
            FlowEnvironmentError: 媒体动作必须执行但未配置 ``media_file`` 时抛出。
        """
        media_file = context.get("media_file")
        if not media_file:
            if required:
                raise FlowEnvironmentError("媒体上传步骤缺少 Scenario variables.media_file")
            return None
        fixture_value = str(media_file)
        if fixture_value.startswith("fixtures/"):
            fixture_value = fixture_value.removeprefix("fixtures/")
        return self._resolve_fixture_path(fixture_value)

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
