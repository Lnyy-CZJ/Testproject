"""由 YAML 数据驱动的 Gateway 单接口真实测试。"""

from __future__ import annotations

from copy import deepcopy
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# 直接执行本文件时，Python 默认只把 test_cases 放入模块搜索路径；
# 这里补入项目根目录，使 api 和 utils 与 pytest 启动时保持相同的导入行为。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from api.gateway_api import GatewayApi
from utils.custom.case_loader import CaseConfigError, load_single_cases
from utils.custom.project_registry import ProjectRegistry
from utils.custom.runtime_overrides import (
    RuntimeOverrideError,
    load_execution_asset_from_environment,
)
from utils.third_party.allure_reporter import set_single_case_metadata, step

# 指定需要调试的完整 Case ID；正式默认值为空元组，收集全部独立单接口用例。
# 临时调试示例：("GetMe::get_me_success",)。
RUN_CASE_IDS: tuple[str, ...] = ()


def _getoption(config: pytest.Config | None, name: str, default: Any = None) -> Any:
    """兼容单元测试直接调用；正式收集始终从 pytest Config 读取参数。"""
    if config is None:
        return default
    return config.getoption(name)


def _load_case_params(config: pytest.Config | None = None) -> list[Any]:
    """加载已选单接口 case，并转换为 pytest 参数。

    功能说明:
        使用 CaseLoader 展开 V1.3 多 case 集合，并把当前 case 的 tags 转换为
        pytest marks。``RUN_CASE_IDS`` 为空时收集全部独立 case。

    返回值:
        pytest.param 列表；每项携带完整 ``ApiId::case_id`` 和当前 case 标签。

    异常说明:
        ApiConfigError: API 定义不合法时由 ApiLoader 抛出。
        CaseConfigError: case 集合不合法或指定 ID 不存在时由 CaseLoader 抛出。
    """
    project_id = str(_getoption(config, "--project", "truthy"))
    try:
        execution_asset = load_execution_asset_from_environment(
            runtime_root=PROJECT_ROOT / "runtime",
            project_id=project_id,
            task_id=str(_getoption(config, "--task-id", "") or ""),
            environ=os.environ,
        )
    except RuntimeOverrideError as exc:
        # 一旦 TaskManager 指定了执行文件，任何身份、路径或摘要问题都必须
        # 终止收集，不能悄悄回退此刻磁盘上的 YAML。
        raise CaseConfigError(f"执行资产不可用: {exc.message}") from exc
    if execution_asset is not None:
        asset_type = execution_asset.get("asset_type")
        selected_case = _getoption(config, "--case")
        selected_api = _getoption(config, "--api")
        if asset_type == "case":
            single_cases = [
                deepcopy(
                    execution_asset["resolved_execution_asset"]["single_case"]
                )
            ]
        elif asset_type == "batch":
            batch = execution_asset["resolved_execution_asset"]
            if batch.get("batch_type") != "cases":
                raise CaseConfigError("执行资产批次类型与单接口入口不匹配")
            if selected_case or selected_api:
                raise CaseConfigError("Case 批次不能同时使用 --case 或 --api")
            # items 在 TaskManager 固化时已经按 Catalog 稳定顺序排列；这里
            # 只能顺序读取不可变清单，禁止重新扫描或排序当前 YAML。
            single_cases = [
                deepcopy(item["resolved_execution_asset"]["single_case"])
                for item in batch["items"]
            ]
        else:
            raise CaseConfigError("执行资产类型与单接口入口不匹配")
        if selected_case and single_cases[0].get("id") != str(selected_case):
            raise CaseConfigError("执行资产与 --case 选择不一致")
        if selected_api and single_cases[0].get("api_id") != str(selected_api):
            raise CaseConfigError("执行资产与 --api 选择不一致")
        return [
            _as_pytest_param(single_case, project_id=project_id)
            for single_case in single_cases
        ]

    direct_project_root = PROJECT_ROOT if (PROJECT_ROOT / "data").is_dir() else None
    project_root = (
        direct_project_root
        or ProjectRegistry(PROJECT_ROOT / "projects").get(project_id).root
    )
    selected_case = _getoption(config, "--case")
    selected_ids = (str(selected_case),) if selected_case else RUN_CASE_IDS
    selected_api = _getoption(config, "--api")
    loaded_cases = load_single_cases(
        project_root,
        selected_case_ids=selected_ids,
    )
    if selected_api:
        loaded_cases = [
            single_case
            for single_case in loaded_cases
            if single_case["api_id"] == selected_api
        ]
        if not loaded_cases:
            raise CaseConfigError(
                f"项目 {project_id} 中 API 不存在或没有 Case: {selected_api}"
            )

    return [
        _as_pytest_param(
            single_case,
            project_id=None if direct_project_root is not None else project_id,
        )
        for single_case in loaded_cases
    ]


def _as_pytest_param(
    single_case: dict[str, Any],
    *,
    project_id: str | None,
) -> Any:
    """以统一 ID 和 YAML tags 包装单接口参数。

    YAML 与执行快照共用本函数，避免两条收集路径在 marker 或报告 ID 上
    产生差异。
    """

    return pytest.param(
        single_case,
        id=(
            single_case["id"]
            if project_id is None
            else f"{project_id}::{single_case['id']}"
        ),
        marks=[getattr(pytest.mark, tag) for tag in single_case["tags"]],
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """在 pytest 参数解析后，按当前项目和 API/Case 选择动态收集。"""
    if "single_case" not in metafunc.fixturenames:
        return
    metafunc.parametrize("single_case", _load_case_params(metafunc.config))


def test_single_gateway_api(
    single_case: dict[str, Any],
    gateway_api: GatewayApi,
    runtime_report_metadata: dict[str, str],
) -> None:
    """执行一条已组装的 V1.3 单接口 case，并完成分层断言。"""
    # fixture 的返回值无需在测试体消费；声明依赖即可保证 JUnit/Allure 在
    # 业务调用前固化本次 Scope/Release 身份。
    del runtime_report_metadata
    set_single_case_metadata(single_case)
    with step(f"执行接口：{single_case['api_id']}"):
        gateway_api.execute(single_case["execution_case"])


def main(argv: Sequence[str] | None = None) -> int:
    """直接运行当前单接口测试文件，并实时显示请求与响应日志。

    参数说明:
        argv: 传给 pytest 的参数；为空时读取当前命令行参数。

    返回值:
        pytest 的退出码，0 表示所有已执行用例通过。

    异常说明:
        pytest 负责处理无效参数、配置错误和测试执行异常。
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
