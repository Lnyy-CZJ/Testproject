"""本地与 CI 共用的 Pytest 参数入口。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import importlib.util

import pytest


_SUITE_PATHS = {
    "all": "tests",
    "unit": "tests/unit",
    "contract": "tests/contract",
    "smoke": "tests",
    "regression": "tests",
}
_SUITE_MARKERS = {"smoke": "smoke"}


def has_xdist() -> bool:
    """判断当前环境是否安装 pytest-xdist。

    功能说明:
        探测可选并发插件，不因插件缺失阻断串行测试。
    参数说明:
        无。
    返回值:
        已安装返回 ``True``，否则返回 ``False``。
    异常说明:
        本函数不主动抛出异常。
    """
    return importlib.util.find_spec("xdist") is not None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析统一测试入口参数。

    功能说明:
        解析环境、suite、marker、并发和报告等统一入口参数。
    参数说明:
        argv: 不含程序名的参数序列；``None`` 时读取当前进程命令行。
    返回值:
        argparse 解析结果。
    异常说明:
        参数缺失或值不合法时由 argparse 输出帮助并抛出 ``SystemExit``。
    """
    parser = argparse.ArgumentParser(description="Truthy 接口自动化测试统一入口")
    parser.add_argument("--env", default="test", help="环境配置名")
    parser.add_argument("--suite", choices=sorted(_SUITE_PATHS), default="all")
    parser.add_argument("--markers", help="Pytest marker 表达式")
    parser.add_argument("--exclude-marker", help="需要排除的 marker 表达式")
    parser.add_argument("--workers", type=int, default=1, help="pytest-xdist worker 数")
    parser.add_argument("--junitxml", help="JUnit XML 输出路径")
    parser.add_argument("--alluredir", help="Allure 结果输出目录")
    parser.add_argument("--run-live-safe", action="store_true", help="显式运行安全只读联调")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="提高输出详细度")
    args = parser.parse_args(argv)
    if args.workers is not None and args.workers < 1:
        parser.error("--workers 必须大于 0")
    return args


def build_pytest_args(args: argparse.Namespace) -> list[str]:
    """将统一入口参数转换为 Pytest 参数列表。

    功能说明:
        把统一入口参数转换为带安全 marker 保护的 Pytest 参数。
    参数说明:
        args: :func:`parse_args` 的返回值。
    返回值:
        可直接传给 ``pytest.main`` 的参数列表。
    异常说明:
        suite 不在受支持集合时抛出 ``KeyError``，正常 CLI 解析会提前阻止该情况。
    """
    pytest_args = [_SUITE_PATHS[args.suite], "--env", args.env]
    marker_parts = []
    if args.suite in _SUITE_MARKERS:
        marker_parts.append(f"({_SUITE_MARKERS[args.suite]})")
    if args.markers:
        marker_parts.append(f"({args.markers})")
    if args.exclude_marker:
        marker_parts.append(f"not ({args.exclude_marker})")
    marker_parts.append("not (payment_real or destructive)")
    marker_expression = " and ".join(marker_parts)
    if marker_expression:
        pytest_args.extend(["-m", marker_expression])
    if args.workers is not None and has_xdist():
        pytest_args.extend(["-n", str(args.workers)])
    if args.junitxml:
        pytest_args.extend(["--junitxml", args.junitxml])
    if args.alluredir:
        pytest_args.extend(["--alluredir", args.alluredir])
    if args.run_live_safe:
        pytest_args.append("--run-live-safe")
    if args.verbose:
        pytest_args.append("-" + "v" * args.verbose)
    return pytest_args


def main(argv: Sequence[str] | None = None) -> int:
    """解析参数并调用 Pytest。

    功能说明:
        解析统一入口参数并执行 Pytest。
    参数说明:
        argv: 不含程序名的参数序列，默认读取当前进程命令行。
    返回值:
        Pytest 整数退出码。
    异常说明:
        参数无效时由 argparse 抛出 ``SystemExit``；Pytest 内部异常遵循其标准行为。
    """
    return int(pytest.main(build_pytest_args(parse_args(argv))))


if __name__ == "__main__":
    raise SystemExit(main())
