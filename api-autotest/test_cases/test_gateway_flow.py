"""通用 Flow/Scenario YAML 参数化测试入口。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
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
from utils.custom.runtime_overrides import (
    RuntimeOverrideError,
    load_execution_asset_from_environment,
)
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
_ADMIN_RUNTIME_VARIABLES = {
    "admin_session_token": "ADMIN_SESSION_TOKEN",
    "admin_operator_id": "ADMIN_OPERATOR_ID",
    "admin_operator_name": "ADMIN_OPERATOR_NAME",
}
_ISOLATED_SESSION_KEYS = (
    "access_token",
    "expires_time",
    "refresh_token",
    "refresh_expires_time",
    "user_id",
)


def _flow_requires_admin_credentials(flow_case: dict[str, Any]) -> bool:
    """按当前项目快照中的逻辑 Profile 判断 Flow 是否需要 Truthy Admin。

    API ID 只保证在单个项目包内唯一。Truthy Admin 与 Dating Evaluation 都有
    ``GetProviderCostSummary``，因此不能再用全局 ID 集合推断凭证。FlowLoader
    已把当前 Flow 实际引用的 API Definition 子集固化到 ``api_definitions``，
    读取其 ``credential_profile`` 才能保持项目隔离。

    参数说明:
        flow_case: FlowLoader 或任务执行快照生成的完整 Flow 用例。

    返回值:
        只要任一实际引用接口声明 ``admin_session`` 就返回 ``True``；缺失或
        非法定义按不需要 Admin 处理，后续项目资产校验会负责报告结构错误。
    """

    definitions = flow_case.get("api_definitions") or {}
    if not isinstance(definitions, dict):
        return False
    return any(
        isinstance(definition, dict)
        and definition.get("credential_profile") == "admin_session"
        for definition in definitions.values()
    )


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
    config: pytest.Config | None = None,
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
    try:
        execution_asset = load_execution_asset_from_environment(
            runtime_root=PROJECT_ROOT / "runtime",
            project_id=project_id,
            task_id=str(config.getoption("--task-id") or "") if config else "",
            environ=os.environ,
        )
    except RuntimeOverrideError as exc:
        raise FlowConfigError(f"执行资产不可用: {exc.message}") from exc
    if execution_asset is not None:
        asset_type = execution_asset.get("asset_type")
        if asset_type == "flow":
            flow_cases = [
                deepcopy(
                    execution_asset["resolved_execution_asset"]["flow_case"]
                )
            ]
        elif asset_type == "batch":
            batch = execution_asset["resolved_execution_asset"]
            if batch.get("batch_type") != "flows":
                raise FlowConfigError("执行资产批次类型与 Flow 入口不匹配")
            if selected_flow:
                raise FlowConfigError("Flow 批次不能同时使用 --flow")
            # 全部 Flow 读取同一任务级图片 manifest。批次条目只保存业务资产，
            # 不复制图片路径，从而保持上传顺序和输入隔离由既有 fixture 负责。
            flow_cases = [
                deepcopy(item["resolved_execution_asset"]["flow_case"])
                for item in batch["items"]
            ]
        else:
            raise FlowConfigError("执行资产类型与 Flow 入口不匹配")
        if selected_flow and flow_cases[0].get("id") != selected_flow:
            raise FlowConfigError("执行资产与 --flow 选择不一致")
        if (
            any(_flow_requires_task_inputs(flow_case) for flow_case in flow_cases)
            and not os.getenv("API_AUTOTEST_TASK_INPUT_MANIFEST_FILE")
        ):
            raise FlowEnvironmentError(
                "TASK_INPUTS_REQUIRED: 当前 Flow 执行资产需要任务图片输入"
            )
        return flow_cases

    project_root = (
        PROJECT_ROOT
        if (PROJECT_ROOT / "data").is_dir()
        else ProjectRegistry(PROJECT_ROOT / "projects").get(project_id).root
    )
    if selected_flow:
        selected_cases = load_flow_cases(project_root, selected_flow=selected_flow)
        if (
            any(_flow_requires_task_inputs(item) for item in selected_cases)
            and not os.getenv("API_AUTOTEST_TASK_INPUT_MANIFEST_FILE")
        ):
            raise FlowEnvironmentError(
                f"TASK_INPUTS_REQUIRED: Flow {selected_flow} 需要任务图片输入"
            )
        return selected_cases

    flow_cases = [
        flow_case
        for flow_case in load_flow_cases(project_root)
        if not _flow_is_explicit_only(flow_case)
    ]
    if not os.getenv("API_AUTOTEST_TASK_INPUT_MANIFEST_FILE"):
        # 默认 all/smoke 收集不能误跑需要人工选择图片的交互 Flow；只有显式
        # 任务 manifest 存在时，才把这类 Flow 纳入当前 pytest 进程。
        flow_cases = [
            flow_case
            for flow_case in flow_cases
            if not _flow_requires_task_inputs(flow_case)
        ]
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


def _flow_requires_task_inputs(flow_case: dict[str, Any]) -> bool:
    """判断 Flow 是否声明至少一个 required 文件输入。"""

    inputs = (flow_case.get("flow") or {}).get("inputs") or {}
    return any(
        isinstance(definition, dict)
        and definition.get("type") == "files"
        and definition.get("required") is True
        for definition in inputs.values()
    ) if isinstance(inputs, dict) else False


def _flow_is_explicit_only(flow_case: dict[str, Any]) -> bool:
    """返回 Flow 是否只能通过 ``--flow`` 精确选择执行。

    cleanup、账号删除等资产即使不需要上传文件，也不能被默认 all/smoke
    收集。项目以统一 ``explicit`` 标签声明该约束，避免把业务名称硬编码进
    公共执行器。
    """

    tags = flow_case.get("tags") or []
    return isinstance(tags, list) and "explicit" in tags


def _sha256_file(path: Path) -> str:
    """流式计算任务图片摘要，避免执行入口一次把多张图片读入内存。"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_task_input_manifest(
    manifest_path: Path,
    *,
    project_id: str,
    task_id: str,
) -> tuple[dict[str, Any], Path]:
    """读取任务输入清单并 fail-closed 校验身份、路径、大小与摘要。

    返回值:
        ``({"media_files": [...]}, inputs_root)``，可直接注入 FlowRunner。

    异常说明:
        FlowEnvironmentError: 清单不存在、身份不符、文件越界/缺失或被篡改。
    """

    path = Path(manifest_path)

    def invalid(message: str) -> FlowEnvironmentError:
        return FlowEnvironmentError(f"TASK_INPUTS_MISSING: {message}")

    if path.is_symlink() or not path.is_file():
        raise invalid("任务输入清单不存在或为符号链接")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise invalid("任务输入清单无法读取") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise invalid("任务输入清单版本无效")
    if document.get("project_id") != project_id or document.get("task_id") != task_id:
        raise invalid("任务输入清单与当前项目/任务身份不匹配")

    input_root = path.parent.resolve()
    if (
        input_root.name != "inputs"
        or input_root.parent.name != task_id
        or input_root.parent.parent.name != project_id
    ):
        raise invalid("任务输入清单不在当前项目任务目录")
    media_files = document.get("media_files")
    if not isinstance(media_files, list) or not 1 <= len(media_files) <= 9:
        raise invalid("任务图片数量无效")

    verified: list[dict[str, Any]] = []
    for expected_order, item in enumerate(media_files, start=1):
        if not isinstance(item, dict) or item.get("order") != expected_order:
            raise invalid("任务图片顺序元数据无效")
        relative_text = str(item.get("relative_path") or "")
        relative_path = Path(relative_text)
        if relative_path.is_absolute() or not relative_text:
            raise invalid("任务图片路径无效")
        candidate = input_root / relative_path
        if candidate.is_symlink():
            raise invalid("任务图片禁止使用符号链接")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(input_root)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise invalid("任务图片缺失或路径越界") from exc
        if not resolved.is_file():
            raise invalid("任务图片不是普通文件")
        try:
            actual_size = resolved.stat().st_size
            actual_sha256 = _sha256_file(resolved)
        except OSError as exc:
            raise invalid("任务图片无法读取") from exc
        if actual_size != item.get("size_bytes") or actual_sha256 != item.get("sha256"):
            raise invalid("任务图片完整性校验失败")
        if item.get("content_type") not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise invalid("任务图片 MIME 无效")
        verified.append(dict(item))
    return {"media_files": verified}, input_root


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


def _configure_flow_session(
    flow_case: dict[str, Any],
    flow_context: RuntimeContext,
    framework_context: RuntimeContext | None,
) -> bool:
    """准备普通或隔离 Flow 的会话，并返回是否启用隔离。

    ``isolated`` Flow 可能注销账号或清除用户数据，不得复制平台共享 Token。
    consent 版本没有身份含义，可从框架上下文复制以创建任务级匿名账号。
    """

    tags = flow_case.get("tags") or []
    isolated = isinstance(tags, list) and "isolated" in tags
    if not isolated:
        _copy_framework_session_context(flow_context, framework_context)
        return False

    for key in _ISOLATED_SESSION_KEYS:
        flow_context.unset(key)
    if framework_context and flow_context.get("consent_policy_version") is None:
        consent = framework_context.get("consent_policy_version")
        if consent not in (None, ""):
            flow_context.set("consent_policy_version", consent)
    return True


def _isolated_gateway_settings(
    settings: dict[str, Any],
    flow_context: RuntimeContext,
) -> dict[str, Any]:
    """从平台 Comm 派生任务级 device id，且不修改共享 settings。

    动态后缀仅存在当前 Flow 内存，平台 Release 仍是静态 Comm 的唯一真源；
    这样同一任务的 Create/Delete 使用同一设备，不同任务也不会共享账号。
    """

    isolated_settings = deepcopy(settings)
    comm = isolated_settings.setdefault("comm", {})
    if not isinstance(comm, dict):
        raise FlowEnvironmentError("isolated Flow 的平台 comm 配置无效")
    flow_run_id = str(flow_context.get("flow_run_id") or "")
    if not flow_run_id:
        raise FlowEnvironmentError("isolated Flow 缺少 flow_run_id")
    base_device_id = str(comm.get("device_id") or "dating-test")
    comm["device_id"] = f"{base_device_id}-isolated-{flow_run_id}"
    return isolated_settings


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
    flow_cases = _load_selected_flow_cases(
        selected_flow,
        project_id,
        metafunc.config,
    )
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
    if _flow_requires_admin_credentials(flow_case):
        runtime_values = gateway_api.runtime_context.as_dict() if gateway_api.runtime_context else {}
        missing_env_keys = [
            env_key
            for runtime_key, env_key in _ADMIN_RUNTIME_VARIABLES.items()
            if not runtime_values.get(runtime_key)
        ]
        if missing_env_keys:
            # 平台模式的 Secret 已被物化到任务运行时快照；这里检查的是快照值，
            # 不是项目目录下的 .env。文案必须准确指向平台 Scope/Release，避免
            # 使用者误以为还需要在工具目录重复维护 Truthy Admin 配置。
            pytest.skip(
                "真实 Flow 未执行: 当前运行时快照缺少 Admin 凭证 "
                + ", ".join(missing_env_keys)
            )

    def gateway_factory(runtime_context: RuntimeContext) -> GatewayApi:
        """为当前 Flow 创建绑定独立业务和会话上下文的 GatewayApi。"""
        isolated = _configure_flow_session(
            flow_case,
            runtime_context,
            gateway_api.runtime_context,
        )
        gateway_settings = (
            _isolated_gateway_settings(gateway_api.settings, runtime_context)
            if isolated
            else gateway_api.settings
        )
        return GatewayApi(
            gateway_settings,
            gateway_api.endpoint,
            http_client=gateway_api.http_client,
            runtime_context=runtime_context,
            api_definitions=gateway_api.api_definitions,
            now_ms=gateway_api.now_ms,
            session_env_path=None if isolated else gateway_api.session_env_path,
            # 平台 writer 内部持有共享 CAS 版本；所有 Flow 子 Gateway 必须复用
            # 同一闭包，确保连续创建/刷新按版本顺序写回当前 Scope Credential。
            session_state_writer=(
                None if isolated else gateway_api.session_state_writer
            ),
        )

    try:
        flow_runtime_variables = {
            **(gateway_api.settings.get("runtime_variables") or {}),
        }
        task_id = str(request.config.getoption("--task-id") or "")
        if task_id:
            flow_runtime_variables["flow_run_id"] = task_id
        analysis_config = (
            (gateway_api.settings.get("flow") or {}).get("analysis") or {}
        )
        for source_key, variable_name in (
            ("poll_interval_seconds", "analysis_poll_interval_seconds"),
            ("timeout_seconds", "analysis_timeout_seconds"),
        ):
            if source_key in analysis_config:
                flow_runtime_variables[variable_name] = analysis_config[source_key]
        input_root: Path | None = None
        manifest_file = os.getenv("API_AUTOTEST_TASK_INPUT_MANIFEST_FILE")
        if manifest_file:
            input_variables, input_root = _load_task_input_manifest(
                Path(manifest_file),
                project_id=str(request.config.getoption("--project")),
                task_id=str(request.config.getoption("--task-id") or ""),
            )
            flow_runtime_variables.update(input_variables)
        FlowRunner(
            project_package.root,
            gateway_factory=gateway_factory,
            runtime_variables=flow_runtime_variables,
            task_input_root=input_root,
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
