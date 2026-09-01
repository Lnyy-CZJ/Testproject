"""标准 Flow 步骤执行器。"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from utils.custom.api_loader import build_execution_case
from utils.custom.assertions import (
    GatewayBusinessResponseError,
    assert_data_equals,
    assert_data_not_equals,
    assert_gateway_response,
)
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
        task_input_root: Path | None = None,
    ) -> None:
        """保存执行依赖，不在初始化阶段创建运行时上下文。

        参数说明:
            project_root: 项目根目录；保留该参数以维持现有构造接口，V1.3
                普通 API 步骤不再通过该路径读取 case YAML。
            gateway_factory: 根据本次 Flow 上下文创建 GatewayApi 的工厂。
            sleep: 等待函数，允许单元测试注入替身。
            monotonic: 单调时钟，允许测试轮询超时而不真实等待。
            environ: 环境变量映射；为空时使用当前进程环境。
            task_input_root: 当前任务 ``inputs/`` 目录；仅 ``input_file`` 动作
                可读取，未提供时任何任务文件读取都会 fail-closed。
        """
        self.project_root = project_root
        self.gateway_factory = gateway_factory
        self.sleep = sleep
        self.monotonic = monotonic
        self.environ = environ if environ is not None else os.environ
        self.runtime_variables = deepcopy(dict(runtime_variables or {}))
        self.task_input_root = (
            Path(task_input_root).resolve() if task_input_root is not None else None
        )

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
        # 最新客户端协议把幂等 ID 放在 Gateway comm，而非业务 params。平台可
        # 注入 task id；CLI 未提供时只在当前 Flow 内存中生成一次 UUID，供
        # Scenario 的步骤级 comm.client_request_id 显式复用。
        if not initial.get("flow_run_id"):
            initial["flow_run_id"] = f"flow_{uuid.uuid4().hex}"
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
            should_terminate = False
            try:
                with report_step(step_title):
                    should_terminate = self._execute_step(
                        step,
                        scenario,
                        api_definitions,
                        gateway,
                        context,
                    )
            except Exception as exc:
                # Gateway 分层断言、变量解析、网络异常与公共动作错误都可能发生
                # 在已创建远端私密数据之后。任何普通执行异常都先进入终止清理，
                # 再原样抛出首个错误；KeyboardInterrupt/SystemExit 不属于 Exception，
                # 仍交给进程级取消/终止机制处理。
                if pending_error is None:
                    pending_error = exc
                flow_terminated = True
                # 只有当前失败步骤之后实际存在 ``run_on_termination`` 步骤时，
                # 才能宣称“进入终止清理”。保留远端任务的交互 Flow 没有这类
                # 步骤，若继续使用旧文案会让用户误以为调用了 DeleteTaskData。
                remaining_cleanup_steps = [
                    str(candidate.get("id") or f"step_{candidate_position}")
                    for candidate_position, candidate in enumerate(
                        steps[position:],
                        start=position + 1,
                    )
                    if candidate.get("run_on_termination", False)
                ]
                if remaining_cleanup_steps:
                    LOGGER.error(
                        "Flow 步骤失败，进入终止清理: step=%s cleanup_steps=%s error=%s",
                        step_id,
                        ",".join(remaining_cleanup_steps),
                        exc,
                    )
                else:
                    LOGGER.error(
                        "Flow 步骤失败；当前 Flow 未配置可继续执行的终止清理步骤，"
                        "远端任务数据保持不变: step=%s error=%s",
                        step_id,
                        exc,
                    )
                continue
            LOGGER.info("完成 Flow 步骤: step=%s", step_id)
            if should_terminate:
                flow_terminated = True
                LOGGER.info(
                    "Flow 命中轮询终态: step=%s；仅继续执行标记 run_on_termination 的步骤",
                    step_id,
                )
        if pending_error is not None:
            raise pending_error
        return context

    def _execute_step(
        self,
        step: dict[str, Any],
        scenario: dict[str, Any],
        api_definitions: dict[str, dict[str, Any]],
        gateway: Any,
        context: RuntimeContext,
    ) -> bool:
        """执行一个已静态校验的步骤并返回是否命中流程终态。"""

        step_id = str(step.get("id") or "unknown")
        if "wait" in step:
            self.sleep(float(context.resolve(step["wait"]["seconds"])))
            return False
        if "action" in step:
            self._execute_action(step["action"], gateway, context)
            return False
        if "api" in step:
            step_data = (scenario.get("step_data") or {}).get(step_id) or {}
            return self._execute_api(
                step,
                step_data,
                api_definitions,
                gateway,
                context,
            )
        if "foreach" in step:
            return self._execute_foreach(
                step,
                scenario,
                api_definitions,
                gateway,
                context,
            )
        raise FlowExecutionError(f"步骤 {step_id} 没有可执行动作")

    def _execute_foreach(
        self,
        step: dict[str, Any],
        scenario: dict[str, Any],
        api_definitions: dict[str, dict[str, Any]],
        gateway: Any,
        context: RuntimeContext,
    ) -> bool:
        """按输入顺序执行一层 foreach，并在全部成功后原子写回 collect 列表。"""

        foreach = step.get("foreach")
        if not isinstance(foreach, dict):
            raise FlowExecutionError("foreach 配置无效")
        items = context.resolve(foreach.get("items"))
        if not isinstance(items, list) or not items:
            raise FlowExecutionError("foreach.items 必须解析为非空列表")
        item_name = str(foreach.get("item") or "")
        child_steps = foreach.get("steps") or []
        if not item_name or not isinstance(child_steps, list) or not child_steps:
            raise FlowExecutionError("foreach.item/steps 配置无效")
        if any(isinstance(child, dict) and "foreach" in child for child in child_steps):
            raise FlowExecutionError("不支持嵌套 foreach")

        collect = foreach.get("collect") or {}
        collected: dict[str, list[Any]] = {str(key): [] for key in collect}
        had_previous = context.contains(item_name)
        previous = deepcopy(context.get(item_name)) if had_previous else None
        try:
            for index, item in enumerate(items, start=1):
                context.set(item_name, item)
                iteration_terminated = False
                with report_step(f"第 {index}/{len(items)} 项"):
                    for position, child in enumerate(child_steps, start=1):
                        if not isinstance(child, dict):
                            raise FlowExecutionError("foreach 子步骤必须是对象")
                        child_id = str(child.get("id") or f"step_{position}")
                        if iteration_terminated and not child.get(
                            "run_on_termination", False
                        ):
                            LOGGER.info(
                                "foreach 迭代命中终态，跳过子步骤: iteration=%s step=%s",
                                index,
                                child_id,
                            )
                            continue
                        if self._should_skip_step(child, context):
                            LOGGER.info(
                                "foreach 条件跳过子步骤: iteration=%s step=%s",
                                index,
                                child_id,
                            )
                            continue
                        with report_step(
                            self._build_step_title(
                                child,
                                child_id,
                                position,
                                len(child_steps),
                            )
                        ):
                            child_terminated = self._execute_step(
                                child,
                                scenario,
                                api_definitions,
                                gateway,
                                context,
                            )
                        if child_terminated:
                            iteration_terminated = True
                if iteration_terminated:
                    return True
                for variable_name, expression in collect.items():
                    collected[str(variable_name)].append(context.resolve(expression))
            for variable_name, values in collected.items():
                context.set(variable_name, values)
            return False
        finally:
            if had_previous:
                context.set(item_name, previous)
            else:
                context.unset(item_name)

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
            action = step["action"]
            action_name = action.get("type") if isinstance(action, dict) else action
            return f"{prefix}{action_name}"
        if "foreach" in step:
            return f"{prefix}逐项执行"
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
            bool: 当前轮询步骤命中不可继续的 ``terminate_on`` 时返回 True，
            调用方应停止执行普通后续步骤；成功态或 ``continue_flow_on`` 声明
            的可诊断终态返回 False。

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
        # params 与步骤级 comm 的占位符都由 GatewayApi.build_payload 统一解析；
        # FlowRunner 只提前解析响应断言，避免两层使用不同的运行时变量快照。
        params = deepcopy(step_data["params"])
        assertions = context.resolve(step_data["assert"])
        case = build_execution_case(
            api_definition,
            params,
            assertions,
        )
        step_comm = step_data.get("comm")
        if step_comm is not None:
            # 保留占位符到 GatewayApi.build_payload 再解析，使真实执行与单元
            # 测试共用同一个 RuntimeContext，且内部 Evaluation 根级报文不受影响。
            case["comm"] = deepcopy(step_comm)

        if step.get("until"):
            data, should_terminate = self._poll(step, case, gateway, context)
        else:
            response = gateway.invoke(case)
            data = self._assert_flow_gateway_response(
                response,
                case,
                step_id=step_id,
                api_id=api_id,
            )
            should_terminate = False
        if should_terminate:
            until = step.get("until") or {}
            path = str(until["path"])
            actual = RuntimeContext.read_path(data, path)
            continue_flow_on = context.resolve(until.get("continue_flow_on") or [])
            if actual not in continue_flow_on:
                if bool(until.get("fail_on_termination")):
                    raise FlowExecutionError(
                        f"FLOW_TERMINATED: 步骤 {step_id} 进入失败终态 {actual!r}"
                    )
                # 终态响应已通过 Gateway 协议断言；跳过成功态数据断言和提取，
                # 防止 NO_RESULT 被按 SUCCEEDED 的场景断言误判为失败。
                return True

            # failed 对这类诊断 Flow 不是自动化执行失败：先保留状态提取，
            # 让 Result 的 skip_unless 生效，再继续查询 Debug 与 Cost。该规则
            # 必须由项目 Flow 显式声明，不影响 rejected 或其他既有终态。
            LOGGER.info(
                "轮询命中可继续诊断的业务终态: step=%s status=%r",
                step_id,
                actual,
            )
        self._finalize_api(step, case, data, context)
        # Flow 直接调用 invoke 并自行提取变量，不能依赖 GatewayApi.execute 的
        # 单接口持久化路径。仅在断言和提取全部成功后通知可选会话写回钩子，
        # 保证平台 Credential 不会停留在任务启动时的旧 token。
        persist_session = getattr(gateway, "persist_session_state_for_case", None)
        if callable(persist_session):
            persist_session(case)
        return False

    @staticmethod
    def _assert_flow_gateway_response(
        response: Any,
        case: dict[str, Any],
        *,
        step_id: str,
        api_id: str,
    ) -> dict[str, Any]:
        """断言 Flow 响应，并为未预期的业务失败补充步骤与 API 上下文。

        成功场景仍可只声明 HTTP 200 与顶层 ``message=ok``；若 Gateway 子响应
        明确返回 ``success=false``，这里会在读取动态字段前终止，并保留服务端
        ``business_error_code`` 与 ``message``，避免误报为 task_id 等路径缺失。
        """

        try:
            return assert_gateway_response(response, case["assert"])
        except GatewayBusinessResponseError as exc:
            raise FlowExecutionError(
                f"步骤 {step_id} ({api_id}) 执行业务失败: {exc}"
            ) from exc

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
        retry_business_codes = {
            str(value)
            for value in context.resolve(
                until.get("retry_on_business_error_codes") or []
            )
        }
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
                try:
                    data = self._assert_flow_gateway_response(
                        response,
                        case,
                        step_id=str(step.get("id") or "unknown"),
                        api_id=str(step.get("api") or "unknown"),
                    )
                except FlowExecutionError as exc:
                    cause = exc.__cause__
                    business_code = (
                        cause.business_error_code
                        if isinstance(cause, GatewayBusinessResponseError)
                        else None
                    )
                    if business_code not in retry_business_codes:
                        raise
                    # Debug/Cost 数据采用最终一致落库。只有 YAML 明确列出的稳定
                    # 业务码可以重试；认证、权限与未知错误仍立即失败。
                    data = None
                    last_value = f"business_error:{business_code}"
                    matched = False
                    terminated = False
                else:
                    last_value = RuntimeContext.read_path(data, path)
                    matched = last_value == expected
                    terminated = not matched and last_value in terminal_values
                poll_summary = {
                    "path": path,
                    "actual": last_value,
                    "expected": expected,
                    "matched": matched,
                }
                if data is None:
                    poll_summary["retry_business_error_code"] = business_code
                # 仅在 YAML 声明终态时附加该信息，保持旧轮询报告结构兼容。
                if terminal_values:
                    poll_summary["terminated"] = terminated
                attach_json(
                    "轮询结果",
                    poll_summary,
                )
            if matched:
                assert data is not None
                return data, False
            if terminated:
                assert data is not None
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
        forbidden_values = (case.get("assert") or {}).get("data_not_equals") or {}
        assert_data_not_equals(data, forbidden_values)
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
        """执行通用输入校验或签名二进制上传。"""
        if isinstance(action, dict) and action.get("type") == "validate_binary_inputs":
            self._validate_binary_inputs(action, context)
            return
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

        fixture_configured = action_config.get("fixture") not in (None, "")
        input_configured = action_config.get("input_file") not in (None, "")
        if fixture_configured == input_configured:
            raise FlowEnvironmentError(
                "signed_binary_upload fixture 与 input_file 必须二选一"
            )
        if input_configured:
            input_value = context.resolve(action_config.get("input_file"))
            if not isinstance(input_value, str) or not input_value:
                raise FlowEnvironmentError("signed_binary_upload input_file 未配置")
            media_path = self._resolve_task_input_path(input_value)
        else:
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
        LOGGER.info(
            "签名二进制上传开始: method=PUT url=%s bytes=%s",
            upload_url,
            len(content),
        )
        try:
            response = gateway.http_client.put_bytes(
                url=upload_url,
                headers=upload_headers,
                content=content,
                timeout=float(gateway.settings.get("timeout", 15)),
            )
        except Exception as exc:
            raise FlowExecutionError(
                "EXTERNAL_UPLOAD_FAILED: "
                f"NETWORK_ERROR url={upload_url} "
                f"exception={type(exc).__name__}: {exc}"
            ) from exc
        success_statuses = context.resolve(
            action_config.get("success_statuses", [200, 201, 202, 204])
        )
        if response.status_code not in success_statuses:
            raise FlowExecutionError(
                f"EXTERNAL_UPLOAD_FAILED: HTTP_{response.status_code} url={upload_url}"
            )
        LOGGER.info(
            "签名二进制上传完成: url=%s status=%s",
            upload_url,
            response.status_code,
        )
        output_variable = action_config.get("output")
        if isinstance(output_variable, str) and output_variable:
            context.set(output_variable, response.status_code)

    @staticmethod
    def _constraint_integer(value: Any, field: str) -> int:
        """把实时媒体配置规范为正整数，并输出稳定的约束失败错误。"""

        if isinstance(value, bool):
            raise FlowExecutionError(
                f"FLOW_INPUT_CONSTRAINT_FAILED: {field} 必须是正整数"
            )
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise FlowExecutionError(
                f"FLOW_INPUT_CONSTRAINT_FAILED: {field} 必须是正整数"
            ) from exc
        if normalized <= 0:
            raise FlowExecutionError(
                f"FLOW_INPUT_CONSTRAINT_FAILED: {field} 必须是正整数"
            )
        return normalized

    def _validate_binary_inputs(
        self,
        action: dict[str, Any],
        context: RuntimeContext,
    ) -> None:
        """使用接口实时返回的数量、类型和大小限制校验完整任务输入。"""

        files = context.resolve(action.get("files"))
        allowed_types = context.resolve(action.get("allowed_content_types"))
        min_items = self._constraint_integer(
            context.resolve(action.get("min_items")), "min_items"
        )
        max_items = self._constraint_integer(
            context.resolve(action.get("max_items")), "max_items"
        )
        max_size_bytes = self._constraint_integer(
            context.resolve(action.get("max_size_bytes")), "max_size_bytes"
        )
        if not isinstance(files, list) or not isinstance(allowed_types, list):
            raise FlowExecutionError(
                "FLOW_INPUT_CONSTRAINT_FAILED: files/allowed_content_types 类型无效"
            )
        normalized_types = {str(item) for item in allowed_types if str(item)}
        if not normalized_types or min_items > max_items or not min_items <= len(files) <= max_items:
            raise FlowExecutionError(
                "FLOW_INPUT_CONSTRAINT_FAILED: "
                f"图片数量 {len(files)} 不在 {min_items}～{max_items} 范围内"
            )
        for index, item in enumerate(files, start=1):
            if not isinstance(item, dict):
                raise FlowExecutionError(
                    f"FLOW_INPUT_CONSTRAINT_FAILED: 第 {index} 个图片元数据无效"
                )
            content_type = str(item.get("content_type") or "")
            size_bytes = item.get("size_bytes")
            if content_type not in normalized_types:
                raise FlowExecutionError(
                    "FLOW_INPUT_CONSTRAINT_FAILED: "
                    f"第 {index} 张图片类型 {content_type or 'unknown'} 不被允许"
                )
            if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
                raise FlowExecutionError(
                    f"FLOW_INPUT_CONSTRAINT_FAILED: 第 {index} 张图片大小无效"
                )
            if size_bytes <= 0 or size_bytes > max_size_bytes:
                raise FlowExecutionError(
                    "FLOW_INPUT_CONSTRAINT_FAILED: "
                    f"第 {index} 张图片大小 {size_bytes} 超过限制 {max_size_bytes}"
                )

    def _resolve_task_input_path(self, input_file: str) -> Path:
        """仅从当前任务 inputs 根读取普通文件，拒绝绝对路径、越界与符号链接。"""

        requested = Path(input_file)
        if requested.is_absolute() or self.task_input_root is None:
            raise FlowEnvironmentError(f"input_file 路径越界或任务输入未初始化: {input_file}")
        candidate = self.task_input_root / requested
        if candidate.is_symlink():
            raise FlowEnvironmentError(f"input_file 禁止使用符号链接: {input_file}")
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.task_input_root)
        except ValueError as exc:
            raise FlowEnvironmentError(f"input_file 路径越界: {input_file}") from exc
        if not resolved.is_file():
            raise FlowEnvironmentError(f"input_file 文件不存在: {input_file}")
        return resolved

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
