"""Gateway 接口自动化框架统一执行入口。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import pytest


def build_pytest_args(
    env: str,
    module: str | None = None,
    tag: str | None = None,
    extra_args: Sequence[str] | None = None,
    flow: str | None = None,
) -> list[str]:
    """把入口参数转换为 pytest 参数。

    参数说明:
        env: 运行环境名称。
        module: pytest ``-k`` 使用的模块或关键字。
        tag: pytest ``-m`` 使用的标签表达式。
        extra_args: 需要透传给 pytest 的其他参数。
        flow: 需要执行的 Flow 文件名，不含 ``.yaml``。

    返回值:
        可直接传给 ``pytest.main`` 的参数列表。
    """
    args = ["test_cases", f"--env={env}"]
    if module:
        args.extend(["-k", module])
    if tag:
        args.extend(["-m", tag])
    if flow:
        args.append(f"--flow={flow}")
    args.extend(extra_args or [])
    return args


def _create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器，集中维护统一入口参数。"""
    parser = argparse.ArgumentParser(description="运行 Gateway 接口自动化测试")
    parser.add_argument("--env", default="test", help="运行环境，默认 test")
    parser.add_argument("--module", help="按 pytest -k 关键字筛选模块或用例")
    parser.add_argument("--tag", help="按 pytest -m 表达式筛选标签")
    parser.add_argument("--flow", help="按 Flow YAML 文件名筛选流程")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析命令行并启动 pytest。

    参数说明:
        argv: 可选命令行参数，主要用于自动化测试；为空时读取系统参数。

    返回值:
        pytest 退出码，调用方可直接用于进程退出状态。
    """
    parser = _create_parser()
    known, extra = parser.parse_known_args(argv)
    if extra and extra[0] == "--":
        extra = extra[1:]
    return int(
        pytest.main(
            build_pytest_args(
                known.env,
                known.module,
                known.tag,
                extra_args=extra,
                flow=known.flow,
            )
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
