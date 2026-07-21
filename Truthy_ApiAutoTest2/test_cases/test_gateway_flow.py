"""通用 Flow/Scenario YAML 参数化测试入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api.gateway_api import GatewayApi
from utils.custom.flow_loader import load_flow_cases
from utils.custom.flow_runner import FlowEnvironmentError, FlowRunner
from utils.custom.runtime_context import RuntimeContext

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    flow_cases = load_flow_cases(PROJECT_ROOT, selected_flow=selected_flow)
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

    def gateway_factory(runtime_context: RuntimeContext) -> GatewayApi:
        """为当前 Flow 创建绑定独立上下文的 GatewayApi。"""
        return GatewayApi(
            gateway_api.settings,
            gateway_api.endpoint,
            http_client=gateway_api.http_client,
            runtime_context=runtime_context,
            session_cases=gateway_api.session_cases,
            now_ms=gateway_api.now_ms,
        )

    try:
        FlowRunner(PROJECT_ROOT, gateway_factory=gateway_factory).run(flow_case)
    except FlowEnvironmentError as exc:
        # 真实媒体文件属于本地运行条件，缺失时保持原有跳过策略。
        pytest.skip(f"真实 Flow 未执行: {exc}")
