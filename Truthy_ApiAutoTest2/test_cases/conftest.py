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
from utils.custom.config_loader import (
    ConfigError,
    load_settings,
    load_yaml,
    validate_settings_contract,
)
from utils.custom.logger import configure_logging
from utils.custom.project_registry import ProjectPackage, ProjectRegistry
from utils.custom.runtime_context import RuntimeContext
from utils.third_party.allure_reporter import (
    build_runtime_report_metadata,
    set_runtime_report_metadata,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser: pytest.Parser) -> None:
    """注册框架环境参数。

    参数说明:
        parser: pytest 提供的命令行解析器。

    返回值:
        无。参数可通过 ``request.config.getoption`` 读取。
    """
    parser.addoption(
        "--project",
        action="store",
        default="truthy",
        help="选择 projects 下的标准项目包，默认 truthy",
    )
    parser.addoption(
        "--target-env",
        action="store",
        default=None,
        help="选择被测系统环境，默认 test",
    )
    parser.addoption(
        "--config-source",
        action="store",
        choices=("platform", "local"),
        default="local",
        help="选择互斥配置来源",
    )
    parser.addoption(
        "--env",
        action="store",
        default=None,
        help="已弃用：truthy 的 target-env 兼容别名",
    )
    parser.addoption(
        "--api",
        action="store",
        default=None,
        help="按当前项目 API ID 筛选单接口用例",
    )
    parser.addoption(
        "--case",
        action="store",
        default=None,
        help="按当前项目完整 ApiId::case_id 筛选单接口用例",
    )
    parser.addoption(
        "--flow",
        action="store",
        default=None,
        help="按 data/flows 下的 YAML 文件名筛选流程",
    )
    parser.addoption(
        "--task-id",
        action="store",
        default=None,
        help="平台内部任务身份，仅用于快照一致性校验",
    )
    parser.addoption(
        "--runtime-scope-id",
        action="store",
        default=None,
        help="平台内部 Runtime Scope 身份，仅用于快照一致性校验",
    )


def pytest_configure(config: pytest.Config) -> None:
    """初始化日志并把 YAML tags 注册为 pytest marker。

    动态注册让新增普通用例时只需修改 YAML，不需要同步维护 pytest.ini。
    无法解析的 YAML 会在正式收集用例时给出明确错误，这里不吞掉该错误。
    """
    direct_project_root = PROJECT_ROOT if (PROJECT_ROOT / "data").is_dir() else None
    if direct_project_root is not None:
        project_id = "truthy"
        project_root = direct_project_root
        target_env = str(config.getoption("--env"))
        task_id = None
        flows_dir = project_root / "data" / "flows"
    else:
        project_id = str(config.getoption("--project"))
        package = ProjectRegistry(PROJECT_ROOT / "projects").get(project_id)
        project_root = package.root
        target_env = _target_env(config)
        task_id = config.getoption("--task-id")
        flows_dir = package.flows_dir
    logging_config = load_yaml(PROJECT_ROOT / "config" / "settings.yaml").get(
        "logging"
    ) or {}
    log_directory = (
        PROJECT_ROOT
        / str(logging_config.get("directory", "logs"))
        / project_id
        / target_env
    )
    if task_id:
        # 平台任务使用全局任务 ID 作为日志物理边界；configure_logging 仍可在
        # 该目录内按日期分层，TaskManager 通过 rglob 只关联当前任务产物。
        log_directory /= str(task_id)
    configure_logging(
        level=logging_config.get("level", "INFO"),
        log_directory=log_directory,
        env=target_env,
        console=bool(logging_config.get("console", True)),
        file=bool(logging_config.get("file", True)),
    )
    # CaseLoader 负责解析 V1.3 嵌套 cases；集合去重避免相同标签重复注册。
    case_tags = {
        tag
        for single_case in load_single_cases(project_root)
        for tag in single_case["tags"]
    }
    for tag in sorted(case_tags):
        config.addinivalue_line("markers", f"{tag}: YAML 用例标签")
    for flow_path in sorted(flows_dir.glob("*.yaml")):
        flow = load_yaml(flow_path)
        for tag in flow.get("tags") or []:
            config.addinivalue_line("markers", f"{tag}: Flow YAML 标签")


def _target_env(config: pytest.Config) -> str:
    """解析新旧环境参数，并拒绝旧参数跨项目或覆盖新参数。"""
    target_env = config.getoption("--target-env")
    legacy_env = config.getoption("--env")
    project_id = config.getoption("--project")
    if legacy_env:
        if project_id != "truthy":
            raise pytest.UsageError("--env 仅兼容 truthy 项目")
        if target_env and target_env != legacy_env:
            raise pytest.UsageError("--env 与 --target-env 不一致")
        return str(legacy_env)
    return str(target_env or "test")


@pytest.fixture(scope="session")
def project_package(request: pytest.FixtureRequest) -> ProjectPackage:
    """返回本次 pytest 会话唯一的标准项目包。"""
    project_id = str(request.config.getoption("--project"))
    return ProjectRegistry(PROJECT_ROOT / "projects").get(project_id)


@pytest.fixture(scope="session")
def gateway_settings(
    request: pytest.FixtureRequest,
    project_package: ProjectPackage,
) -> dict[str, Any]:
    """加载本次测试会话的环境配置。

    缺少真实凭证时跳过真实接口用例，框架单元测试仍可正常执行。
    """
    env = _target_env(request.config)
    config_source = str(request.config.getoption("--config-source"))
    try:
        settings = load_settings(
            env,
            project_root=PROJECT_ROOT,
            config_source=config_source,
            project_id=project_package.project_id,
            task_id=request.config.getoption("--task-id")
            or os.getenv("API_AUTOTEST_TASK_ID")
            or None,
            runtime_scope_id=request.config.getoption("--runtime-scope-id")
            or os.getenv("API_AUTOTEST_RUNTIME_SCOPE_ID")
            or None,
        )
        if config_source == "platform":
            validate_settings_contract(
                settings,
                project_package.manifest.config_contract.required_keys,
            )
        return settings
    except ConfigError as exc:
        pytest.skip(f"真实 Gateway 用例未执行: {exc}")


@pytest.fixture
def runtime_report_metadata(
    request: pytest.FixtureRequest,
    project_package: ProjectPackage,
    gateway_settings: dict[str, Any],
    record_property: Any,
) -> dict[str, str]:
    """将同一组非敏感运行身份写入 JUnit 与 Allure。

    该 fixture 只注入两个真实 Gateway 测试入口，不影响框架单元测试收集。
    平台快照中的配置和凭证内容均不进入报告；报告仅保留项目、环境、Scope、
    Release 与任务身份，便于从历史报告回溯到平台唯一真源。
    """
    metadata = build_runtime_report_metadata(
        project_id=project_package.project_id,
        target_env=_target_env(request.config),
        config_source=str(request.config.getoption("--config-source")),
        settings=gateway_settings,
    )
    for name, value in metadata.items():
        record_property(name, value)
    set_runtime_report_metadata(metadata)
    return metadata


@pytest.fixture(scope="session")
def gateway_endpoint(
    project_package: ProjectPackage,
    gateway_settings: dict[str, Any],
) -> dict[str, Any]:
    """返回当前快照固化的 Gateway 入口，项目 YAML 只提供 local 默认结构。"""
    endpoint = load_yaml(project_package.api_dir / "gateway_invoke.yaml")
    for settings_key, endpoint_key in (
        ("gateway_path", "path"),
        ("gateway_method", "method"),
        ("gateway_headers", "headers"),
    ):
        if settings_key in gateway_settings:
            endpoint[endpoint_key] = gateway_settings[settings_key]
    return endpoint


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
    request: pytest.FixtureRequest,
    gateway_settings: dict[str, Any],
    gateway_endpoint: dict[str, Any],
    gateway_runtime: RuntimeContext,
    project_package: ProjectPackage,
) -> GatewayApi:
    """返回具备自动创建/刷新匿名会话能力的 Gateway 调用对象。

    自动会话只使用 API 定义中的路由；请求参数、断言和提取规则由
    ``GatewayApi`` 的内部会话协议统一管理，不依赖单接口 Cases。
    """
    config_source = str(request.config.getoption("--config-source"))
    # 仅 Truthy local 兼容入口可读写旧根 .env；Dating 与后续项目从不继承它。
    session_path: Path | None = (
        PROJECT_ROOT / ".env"
        if project_package.project_id == "truthy" and config_source == "local"
        else None
    )
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
        api_definitions=load_api_definitions(project_package.root),
        session_env_path=session_path,
        session_state_writer=session_writer,
    )
