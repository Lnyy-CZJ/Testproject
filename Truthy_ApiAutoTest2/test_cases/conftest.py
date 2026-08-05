"""pytest 全局参数、配置 fixture 与 YAML 标签注册。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from api.gateway_api import GatewayApi
from utils.custom.api_loader import load_api_definitions
from utils.custom.case_loader import load_single_cases
from utils.custom.config_loader import ConfigError, load_settings, load_yaml
from utils.custom.logger import configure_logging
from utils.custom.runtime_context import RuntimeContext

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser: pytest.Parser) -> None:
    """注册框架环境参数。

    参数说明:
        parser: pytest 提供的命令行解析器。

    返回值:
        无。参数可通过 ``request.config.getoption`` 读取。
    """
    parser.addoption(
        "--env",
        action="store",
        default="test",
        help="选择 config/env 下的运行环境，默认 test",
    )
    parser.addoption(
        "--flow",
        action="store",
        default=None,
        help="按 data/flows 下的 YAML 文件名筛选流程",
    )


def pytest_configure(config: pytest.Config) -> None:
    """初始化日志并把 YAML tags 注册为 pytest marker。

    动态注册让新增普通用例时只需修改 YAML，不需要同步维护 pytest.ini。
    无法解析的 YAML 会在正式收集用例时给出明确错误，这里不吞掉该错误。
    """
    logging_config = load_yaml(PROJECT_ROOT / "config" / "settings.yaml").get(
        "logging"
    ) or {}
    log_directory = PROJECT_ROOT / str(logging_config.get("directory", "logs"))
    configure_logging(
        level=logging_config.get("level", "INFO"),
        log_directory=log_directory,
        env=str(config.getoption("--env")),
        console=bool(logging_config.get("console", True)),
        file=bool(logging_config.get("file", True)),
    )
    # CaseLoader 负责解析 V1.3 嵌套 cases；集合去重避免相同标签重复注册。
    case_tags = {
        tag
        for single_case in load_single_cases(PROJECT_ROOT)
        for tag in single_case["tags"]
    }
    for tag in sorted(case_tags):
        config.addinivalue_line("markers", f"{tag}: YAML 用例标签")
    for flow_path in sorted((PROJECT_ROOT / "data" / "flows").glob("*.yaml")):
        flow = load_yaml(flow_path)
        for tag in flow.get("tags") or []:
            config.addinivalue_line("markers", f"{tag}: Flow YAML 标签")


@pytest.fixture(scope="session")
def gateway_settings(request: pytest.FixtureRequest) -> dict[str, Any]:
    """加载本次测试会话的环境配置。

    缺少真实凭证时跳过真实接口用例，框架单元测试仍可正常执行。
    """
    env = request.config.getoption("--env")
    try:
        return load_settings(env, project_root=PROJECT_ROOT)
    except ConfigError as exc:
        pytest.skip(f"真实 Gateway 用例未执行: {exc}")


@pytest.fixture(scope="session")
def gateway_endpoint() -> dict[str, Any]:
    """返回 Gateway 固定 HTTP 接口配置。"""
    return load_yaml(PROJECT_ROOT / "data" / "api" / "gateway_invoke.yaml")


@pytest.fixture(scope="session")
def gateway_runtime(gateway_settings: dict[str, Any]) -> RuntimeContext:
    """创建本轮真实接口测试共享的内存运行时上下文。

    可选的启动 token 和 user_id 仅用于兼容本机调试；没有毫秒过期时间时，
    GatewayApi 会自动调用 CreateAnonymousSession 获取完整会话。同时提供当天的
    consent_policy_version，供匿名会话请求使用 YYYY-MM-DD 格式的最新日期。
    """
    initial = {
        **(gateway_settings.get("runtime_session") or {}),
        **(gateway_settings.get("runtime_variables") or {}),
    }
    initial["consent_policy_version"] = date.today().isoformat()
    return RuntimeContext(initial)


@pytest.fixture(scope="session")
def gateway_api(
    gateway_settings: dict[str, Any],
    gateway_endpoint: dict[str, Any],
    gateway_runtime: RuntimeContext,
) -> GatewayApi:
    """返回具备自动创建/刷新匿名会话能力的 Gateway 调用对象。

    自动会话只使用 API 定义中的路由；请求参数、断言和提取规则由
    ``GatewayApi`` 的内部会话协议统一管理，不依赖单接口 Cases。
    """
    return GatewayApi(
        gateway_settings,
        gateway_endpoint,
        runtime_context=gateway_runtime,
        api_definitions=load_api_definitions(PROJECT_ROOT),
        session_env_path=PROJECT_ROOT / ".env",
    )
