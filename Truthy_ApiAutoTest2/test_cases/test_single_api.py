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
from utils.custom.case_loader import load_single_cases
from utils.third_party.allure_reporter import set_single_case_metadata, step

# 指定需要调试的完整 Case ID；正式默认值为空元组，收集全部独立单接口用例。
# 临时调试示例：("GetMe::get_me_success",)。
RUN_CASE_IDS: tuple[str, ...] = ()


def _load_case_params() -> list[Any]:
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
    params: list[Any] = []
    for single_case in load_single_cases(
        PROJECT_ROOT,
        selected_case_ids=RUN_CASE_IDS,
    ):
        marks = [
            getattr(pytest.mark, tag)
            for tag in single_case["tags"]
        ]
        params.append(
            pytest.param(
                single_case,
                id=single_case["id"],
                marks=marks,
            )
        )
    return params


@pytest.mark.parametrize("single_case", _load_case_params())
def test_single_gateway_api(
    single_case: dict[str, Any],
    gateway_api: GatewayApi,
) -> None:
    """执行一条已组装的 V1.3 单接口 case，并完成分层断言。"""
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
