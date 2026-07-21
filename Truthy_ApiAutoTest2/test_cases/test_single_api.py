"""由 YAML 数据驱动的 Gateway 单接口真实测试。"""

from __future__ import annotations

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
from utils.custom.config_loader import load_yaml

# 指定需要执行的 YAML 用例名称；空元组表示执行 data/cases 下的全部单接口用例。
# 名称必须与 YAML 文件中的 name 字段完全一致，例如：("获取当前用户",)。
RUN_CASE_NAMES: tuple[str, ...] = ("获取当前用户",)


def _load_case_params() -> list[Any]:
    """读取已选单接口 YAML，并把 tags 转换为 pytest marks。

    RUN_CASE_NAMES 为空时加载全部用例；不为空时只加载名称在该配置中的用例。

    返回值:
        pytest.param 列表，每项携带用例名称和 YAML 标签。

    异常说明:
        ConfigError: 用例 YAML 缺失或格式不合法时由 load_yaml 抛出。
    """
    params: list[Any] = []
    for case_path in sorted((PROJECT_ROOT / "data" / "cases").glob("*.yaml")):
        case = load_yaml(case_path)
        case_name = str(case.get("name") or case_path.stem)
        if case.get("flow_only"):
            continue
        if RUN_CASE_NAMES and case_name not in RUN_CASE_NAMES:
            continue
        marks = [getattr(pytest.mark, str(tag)) for tag in case.get("tags") or []]
        params.append(
            pytest.param(
                case,
                id=case_name,
                marks=marks,
            )
        )
    return params


@pytest.mark.parametrize("case", _load_case_params())
def test_single_gateway_api(
    case: dict[str, Any],
    gateway_api: GatewayApi,
) -> None:
    """执行一个 YAML 单接口用例并完成分层断言。"""
    gateway_api.execute(case)


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
