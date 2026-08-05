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
from utils.custom.runtime_context import RuntimeContext
from utils.third_party.allure_reporter import set_flow_metadata

# 本地调试 Flow 的完整文件名 stem；空元组表示收集全部 Flow。
# 临时调试示例：("AnonymousSessionMediaSearch",)。
RUN_FLOW_IDS: tuple[str, ...] = ("NameWithConditionsSearch",)
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


def _load_selected_flow_cases(selected_flow: str | None) -> list[dict[str, Any]]:
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
    if selected_flow:
        return load_flow_cases(PROJECT_ROOT, selected_flow=selected_flow)

    flow_cases = load_flow_cases(PROJECT_ROOT)
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
    flow_cases = _load_selected_flow_cases(selected_flow)
    params = [
        pytest.param(
            flow_case,
            id=flow_case["id"],
            marks=[getattr(pytest.mark, tag) for tag in flow_case["tags"]],
        )
        for flow_case in flow_cases
    ]
    metafunc.parametrize("flow_case", params)


def test_gateway_flow(flow_case: dict[str, Any], gateway_api: GatewayApi) -> None:
    """使用通用 FlowRunner 执行一条独立 Flow/Scenario 用例。"""
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
        )

    try:
        FlowRunner(PROJECT_ROOT, gateway_factory=gateway_factory).run(flow_case)
    except FlowEnvironmentError as exc:
        # 真实媒体文件属于本地运行条件，缺失时保持原有跳过策略。
        pytest.skip(f"真实 Flow 未执行: {exc}")


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
