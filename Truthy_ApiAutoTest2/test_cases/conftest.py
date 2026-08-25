"""pytest 全局参数、配置 fixture 与 YAML 标签注册。"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests

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
    session_path: Path | None = PROJECT_ROOT / ".env"
    session_writer = None
    if os.getenv("API_AUTOTEST_SESSION_PROVIDER", "dotenv") == "platform":
        platform_api_url = os.getenv("PLATFORM_API_URL", "").rstrip("/")
        credential_id = os.getenv("PLATFORM_CREDENTIAL_ID", "")
        runtime_context_id = os.getenv("PLATFORM_RUNTIME_CONTEXT_ID", "")
        token_path = Path(os.getenv("PLATFORM_CLIENT_TOKEN_FILE", ""))
        if (
            not platform_api_url
            or not credential_id
            or not runtime_context_id
            or not token_path.is_file()
        ):
            raise RuntimeError("平台会话写回客户端未正确部署")
        token = token_path.read_text(encoding="utf-8").strip()
        version = [int(os.getenv("PLATFORM_CREDENTIAL_VERSION", "0"))]

        def write_platform_session(values: dict[str, Any]) -> None:
            """使用 CAS 将完整会话原子写回当前工具凭证。"""

            payload_values = {
                env_key: values[runtime_key]
                for runtime_key, env_key in {
                    "access_token": "AUTH_TOKEN", "refresh_token": "REFRESH_TOKEN",
                    "user_id": "USER_ID", "device_id": "DEVICE_ID",
                    "expires_time": "EXPIRES_TIME", "refresh_expires_time": "REFRESH_EXPIRES_TIME",
                }.items()
                if values.get(runtime_key) not in (None, "")
            }
            response = requests.put(
                f"{platform_api_url}/internal/tools/api-autotest/user-credentials/{credential_id}/session",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "runtime_context_id": runtime_context_id,
                    "expected_version": version[0],
                    "values": payload_values,
                },
                timeout=5,
            )
            response.raise_for_status()
            version[0] += 1

        session_path = None
        session_writer = write_platform_session

    return GatewayApi(
        gateway_settings,
        gateway_endpoint,
        runtime_context=gateway_runtime,
        api_definitions=load_api_definitions(PROJECT_ROOT),
        session_env_path=session_path,
        session_state_writer=session_writer,
    )
