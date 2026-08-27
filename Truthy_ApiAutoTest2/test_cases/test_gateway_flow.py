"""通用 Flow/Scenario YAML 参数化测试入口。"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# 直接执行本文件时，Python 默认只把 test_cases 放入模块搜索路径；
# 这里补入项目根目录，使 api 和 utils 的导入行为与 pytest 保持一致。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from api.gateway_api import GatewayApi
from utils.custom.flow_loader import FlowConfigError, load_flow_cases
from utils.custom.flow_runner import FlowEnvironmentError, FlowRunner
from utils.custom.project_registry import ProjectRegistry
from utils.custom.runtime_context import RuntimeContext
from utils.third_party.allure_reporter import set_flow_metadata

# 本地调试 Flow 的完整文件名 stem；空元组表示收集全部 Flow。
# 临时调试示例：("AnonymousSessionMediaSearch",)。
# 提交入库时必须保持空元组，否则 CI/平台不带 --flow 的入口只会执行此处列出的 Flow。
RUN_FLOW_IDS: tuple[str, ...] = ()
# 仅复制会话生命周期需要的框架变量；Flow 业务变量始终保持独立。
_FRAMEWORK_SESSION_KEYS = (
    "access_token",
    "expires_time",
    "refresh_token",
    "refresh_expires_time",
    "user_id",
    "consent_policy_version",
    # Admin 审计接口从 .env 读取的凭证也需要复制到每条独立 Flow 上下文。
    "admin_session_token",
    "admin_operator_id",
    "admin_operator_name",
)
_ADMIN_FLOW_API_IDS = {"GetSearchTaskDebug", "GetProviderCostSummary"}
_ADMIN_RUNTIME_VARIABLES = {
    "admin_session_token": "ADMIN_SESSION_TOKEN",
    "admin_operator_id": "ADMIN_OPERATOR_ID",
    "admin_operator_name": "ADMIN_OPERATOR_NAME",
}


def _handle_flow_environment_error(
    config_source: str,
    error: FlowEnvironmentError,
) -> None:
    """按配置源处理项目运行资产缺失。

    本地开发可能尚未准备真实媒体 fixture，保持可识别的 skip；平台模式运行
    的项目包已经是发布资产，缺失文件或越界引用必须 fail-closed，使 CLI、
    Jenkins 与 Web 三条入口得到一致的非零结论。
    """

    if config_source == "platform":
        pytest.fail(f"平台项目运行资产不可用: {error}", pytrace=False)
    pytest.skip(f"真实 Flow 未执行: {error}")


def _load_selected_flow_cases(
    selected_flow: str | None,
    project_id: str = "truthy",
) -> list[dict[str, Any]]:
    """加载命令行或本地调试配置选中的 Flow。

    功能说明:
        命令行 ``--flow`` 优先于 ``RUN_FLOW_IDS``，方便临时命令覆盖文件内的
        本地调试常量；未设置任何筛选时返回全部合法 Flow。

    参数说明:
        selected_flow: pytest ``--flow`` 的单个 Flow 文件名 stem，可为空。

    返回值:
        已通过 FlowLoader 校验的流程用例列表，保持 YAML 文件排序。

    异常说明:
        FlowConfigError: 命令行或 ``RUN_FLOW_IDS`` 指向不存在的 Flow 时抛出。
    """
    project_root = (
        PROJECT_ROOT
        if (PROJECT_ROOT / "data").is_dir()
        else ProjectRegistry(PROJECT_ROOT / "projects").get(project_id).root
    )
    if selected_flow:
        return load_flow_cases(project_root, selected_flow=selected_flow)

    flow_cases = load_flow_cases(project_root)
    if not RUN_FLOW_IDS:
        return flow_cases

    available_ids = [flow_case["id"] for flow_case in flow_cases]
    missing_ids = sorted(set(RUN_FLOW_IDS) - set(available_ids))
    if missing_ids:
        missing_text = ", ".join(missing_ids)
        available_text = ", ".join(available_ids) or "无"
        raise FlowConfigError(
            f"RUN_FLOW_IDS 包含不存在的 Flow: {missing_text}；"
            f"可用 Flow: {available_text}"
        )
    requested_ids = set(RUN_FLOW_IDS)
    return [
        flow_case
        for flow_case in flow_cases
        if flow_case["id"] in requested_ids
    ]


def _copy_framework_session_context(
    flow_context: RuntimeContext,
    framework_context: RuntimeContext | None,
) -> None:
    """将会话生命周期字段深拷贝到独立 Flow 上下文。

    参数说明:
        flow_context: 当前 Flow 新建的业务上下文，仅会写入缺失的会话字段。
        framework_context: pytest session 级 Gateway 上下文，保存 token 和 consent
            日期等框架状态；为空时不做任何处理。

    返回值:
        无。Flow 的业务变量和父上下文中的非会话字段不会被复制。

    异常说明:
        无。RuntimeContext 自身在写入时完成深拷贝。
    """
    if not framework_context:
        return
    framework_values = framework_context.as_dict()
    for key in _FRAMEWORK_SESSION_KEYS:
        if flow_context.get(key) is None and key in framework_values:
            flow_context.set(key, framework_values[key])


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """按 Flow/Scenario 配对动态生成 pytest 用例。

    参数说明:
        metafunc: pytest 收集阶段提供的参数化对象。

    返回值:
        无；仅当测试函数声明 flow_case 参数时执行参数化。

    异常说明:
        FlowConfigError: Flow 配置不合法时由加载器抛出并中止对应收集。
    """
    if "flow_case" not in metafunc.fixturenames:
        return
    selected_flow = metafunc.config.getoption("--flow")
    project_id = str(metafunc.config.getoption("--project"))
    flow_cases = _load_selected_flow_cases(selected_flow, project_id)
    params = [
        pytest.param(
            flow_case,
            id=f"{project_id}::{flow_case['id']}",
            marks=[getattr(pytest.mark, tag) for tag in flow_case["tags"]],
        )
        for flow_case in flow_cases
    ]
    metafunc.parametrize("flow_case", params)


def test_gateway_flow(
    flow_case: dict[str, Any],
    gateway_api: GatewayApi,
    project_package: Any,
    runtime_report_metadata: dict[str, str],
    request: pytest.FixtureRequest,
) -> None:
    """使用通用 FlowRunner 执行一条独立 Flow/Scenario 用例。"""
    # fixture 的返回值无需在测试体消费；声明依赖即可保证报告身份先落盘。
    del runtime_report_metadata
    set_flow_metadata(flow_case)
    flow_api_ids = {
        str(step.get("api") or "")
        for step in (flow_case.get("flow") or {}).get("steps") or []
    }
    if flow_api_ids & _ADMIN_FLOW_API_IDS:
        runtime_values = gateway_api.runtime_context.as_dict() if gateway_api.runtime_context else {}
        missing_env_keys = [
            env_key
            for runtime_key, env_key in _ADMIN_RUNTIME_VARIABLES.items()
            if not runtime_values.get(runtime_key)
        ]
        if missing_env_keys:
            pytest.skip(
                "真实 Flow 未执行: .env 缺少 Admin 凭证 "
                + ", ".join(missing_env_keys)
            )

    def gateway_factory(runtime_context: RuntimeContext) -> GatewayApi:
        """为当前 Flow 创建绑定独立业务和会话上下文的 GatewayApi。"""
        _copy_framework_session_context(
            runtime_context,
            gateway_api.runtime_context,
        )
        return GatewayApi(
            gateway_api.settings,
            gateway_api.endpoint,
            http_client=gateway_api.http_client,
            runtime_context=runtime_context,
            api_definitions=gateway_api.api_definitions,
            now_ms=gateway_api.now_ms,
            session_env_path=gateway_api.session_env_path,
            # 平台 writer 内部持有共享 CAS 版本；所有 Flow 子 Gateway 必须复用
            # 同一闭包，确保连续创建/刷新按版本顺序写回当前 Scope Credential。
            session_state_writer=gateway_api.session_state_writer,
        )

    try:
        flow_runtime_variables = {
            **(gateway_api.settings.get("runtime_variables") or {}),
        }
        analysis_config = (
            (gateway_api.settings.get("flow") or {}).get("analysis") or {}
        )
        for source_key, variable_name in (
            ("poll_interval_seconds", "analysis_poll_interval_seconds"),
            ("timeout_seconds", "analysis_timeout_seconds"),
        ):
            if source_key in analysis_config:
                flow_runtime_variables[variable_name] = analysis_config[source_key]
        FlowRunner(
            project_package.root,
            gateway_factory=gateway_factory,
            runtime_variables=flow_runtime_variables,
        ).run(flow_case)
    except FlowEnvironmentError as exc:
        _handle_flow_environment_error(
            str(request.config.getoption("--config-source")),
            exc,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """直接运行当前 Flow 测试文件，并实时显示请求与响应日志。

    参数说明:
        argv: 传给 pytest 的参数；为空时读取当前命令行参数。可传入
            ``--flow FlowId`` 覆盖 ``RUN_FLOW_IDS``。

    返回值:
        pytest 的退出码，0 表示所有已执行 Flow 通过。

    异常说明:
        pytest 负责处理无效参数、配置错误和 Flow 执行异常。
    """
    pytest_args = [
        str(Path(__file__).resolve()),
        "-s",
        "--log-cli-level=INFO",
        *(argv if argv is not None else sys.argv[1:]),
    ]
    return int(pytest.main(pytest_args))


if __name__ == "__main__":
    raise SystemExit(main())
