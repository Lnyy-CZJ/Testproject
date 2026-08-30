"""Gateway 接口自动化框架统一执行入口。"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest


def build_pytest_args(
    env: str | None = None,
    module: str | None = None,
    tag: str | None = None,
    extra_args: Sequence[str] | None = None,
    flow: str | None = None,
    *,
    project: str | None = None,
    target_env: str | None = None,
    config_source: str = "local",
    api: str | None = None,
    case: str | None = None,
    task_id: str | None = None,
    runtime_scope_id: str | None = None,
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
    if env is not None:
        if target_env is not None and target_env != env:
            raise ValueError("--env 与 --target-env 不一致")
        if project not in (None, "truthy"):
            raise ValueError("兼容参数 --env 仅允许映射到 truthy 项目")
        project = "truthy"
        target_env = env
        print(
            "弃用提示：--env 已弃用，已兼容映射为 --project truthy "
            f"--target-env {env}",
            file=sys.stderr,
        )
    if project is None:
        project = "truthy"
        print(
            "弃用提示：未传 --project，兼容期默认使用 truthy；请显式传入项目。",
            file=sys.stderr,
        )
    if target_env is None:
        target_env = "test"
    if config_source not in {"local", "platform"}:
        raise ValueError("config_source 必须为 platform 或 local")
    if flow and (api or case):
        raise ValueError("--flow 不能与 --api/--case 同时使用")

    # 指定资产时只收集对应通用入口，避免无关项目资产被 pytest 同时收集。
    if flow:
        target = "test_cases/test_gateway_flow.py"
    elif api or case:
        target = "test_cases/test_single_api.py"
    else:
        target = "test_cases"
    args = [
        target,
        f"--project={project}",
        f"--target-env={target_env}",
        f"--config-source={config_source}",
    ]
    if module:
        args.extend(["-k", module])
    if tag:
        args.extend(["-m", tag])
    if flow:
        args.append(f"--flow={flow}")
    if api:
        args.append(f"--api={api}")
    if case:
        args.append(f"--case={case}")
    task_id = task_id or os.getenv("API_AUTOTEST_TASK_ID")
    runtime_scope_id = runtime_scope_id or os.getenv("API_AUTOTEST_RUNTIME_SCOPE_ID")
    if task_id:
        args.append(f"--task-id={task_id}")
    if runtime_scope_id:
        args.append(f"--runtime-scope-id={runtime_scope_id}")
    forwarded = list(extra_args or [])
    if task_id:
        if not any(
            argument.startswith(("--junitxml", "--junit-xml"))
            for argument in forwarded
        ):
            args.append(f"--junitxml=reports/junit/{project}/{task_id}.xml")
        if not any(argument.startswith("--alluredir") for argument in forwarded):
            args.append(
                f"--alluredir=reports/task-reports/{project}/{task_id}/allure-results"
            )
    args.extend(forwarded)
    return args


def _create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器，集中维护统一入口参数。"""
    parser = argparse.ArgumentParser(description="运行 Gateway 接口自动化测试")
    parser.add_argument("--project", help="标准项目包 ID；兼容期缺省 truthy")
    parser.add_argument("--target-env", help="被测系统环境，例如 test 或 prod")
    parser.add_argument("--env", help="已弃用：仅兼容 truthy 的 target-env 别名")
    parser.add_argument(
        "--config-source",
        choices=("platform", "local"),
        default="local",
        help="互斥配置来源；平台任务必须使用 platform",
    )
    parser.add_argument("--module", help="按 pytest -k 关键字筛选模块或用例")
    parser.add_argument("--tag", help="按 pytest -m 表达式筛选标签")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--api", help="按当前项目 API ID 筛选单接口用例")
    selection.add_argument("--flow", help="按当前项目 Flow 文件名筛选流程")
    parser.add_argument("--case", help="按完整 ApiId::case_id 筛选单接口用例")
    parser.add_argument(
        "--validate-projects",
        action="store_true",
        help="仅静态校验全部标准项目包，不发起网络请求",
    )
    parser.add_argument("--task-id", help="平台内部任务身份，用于快照一致性校验")
    parser.add_argument(
        "--runtime-scope-id",
        help="平台内部 Runtime Scope 身份，用于快照一致性校验",
    )
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
    if known.flow and known.case:
        parser.error("--flow 不能与 --case 同时使用")
    from utils.custom.project_registry import ProjectRegistry, ProjectRegistryError

    registry = ProjectRegistry(Path(__file__).resolve().parent / "projects")
    if known.validate_projects:
        try:
            results = registry.validate_all()
        except ProjectRegistryError as exc:
            print(f"项目包校验失败: {exc}", file=sys.stderr)
            return 2
        for project_id in sorted(results):
            print(f"[OK] {project_id}")
        return 0
    project_id = known.project or "truthy"
    try:
        registry.get(project_id)
    except ProjectRegistryError as exc:
        parser.error(str(exc))
    return int(
        pytest.main(
            build_pytest_args(
                known.env,
                known.module,
                known.tag,
                extra_args=extra,
                flow=known.flow,
                project=known.project,
                target_env=known.target_env,
                config_source=known.config_source,
                api=known.api,
                case=known.case,
                task_id=known.task_id,
                runtime_scope_id=known.runtime_scope_id,
            )
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
