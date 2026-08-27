"""统一 CLI 的项目、环境和资产选择行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtest import _create_parser, build_pytest_args


def test_new_cli_arguments_are_forwarded_to_pytest() -> None:
    """项目、目标环境、配置源及 API/Case/Flow 筛选必须进入 pytest。"""
    args = build_pytest_args(
        project="dating",
        target_env="test",
        config_source="local",
        api="GetMe",
        case="GetMe::success",
    )

    assert args[:4] == [
        "test_cases/test_single_api.py",
        "--project=dating",
        "--target-env=test",
        "--config-source=local",
    ]
    assert "--api=GetMe" in args
    assert "--case=GetMe::success" in args


def test_api_case_and_flow_selection_is_mutually_exclusive() -> None:
    """单接口选择和 Flow 选择混用会产生歧义，解析阶段必须拒绝。"""
    parser = _create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--api", "GetMe", "--flow", "anonymous_session_refresh"])


def test_legacy_env_maps_to_truthy_test_with_deprecation_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """旧 --env test 只兼容 Truthy/test，并输出一次明确弃用提示。"""
    args = build_pytest_args(env="test")

    assert "--project=truthy" in args
    assert "--target-env=test" in args
    assert "已弃用" in capsys.readouterr().err


def test_task_artifacts_are_project_and_task_isolated() -> None:
    """平台任务默认 JUnit/Allure 路径必须同时包含项目与全局任务 ID。"""
    args = build_pytest_args(
        project="dating",
        target_env="test",
        config_source="platform",
        task_id="task-42",
        runtime_scope_id="scope-dating-test",
    )

    assert "--task-id=task-42" in args
    assert "--runtime-scope-id=scope-dating-test" in args
    assert "--junitxml=reports/junit/dating/task-42.xml" in args
    assert (
        "--alluredir=reports/task-reports/dating/task-42/allure-results" in args
    )


def test_platform_pytest_logging_is_scoped_by_project_environment_and_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 pytest 入口的文件日志必须落在任务专属目录，不能靠 PID 猜测关联。"""

    from test_cases import conftest as project_conftest

    captured: dict[str, object] = {}

    def fake_configure_logging(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(project_conftest, "configure_logging", fake_configure_logging)

    class Config:
        @staticmethod
        def getoption(name: str):
            return {
                "--project": "dating",
                "--target-env": "test",
                "--env": None,
                "--task-id": "20260827-120000-a1b2",
            }[name]

        @staticmethod
        def addinivalue_line(_name: str, _value: str) -> None:
            return None

    project_conftest.pytest_configure(Config())  # type: ignore[arg-type]

    assert captured["log_directory"] == (
        Path(project_conftest.PROJECT_ROOT)
        / "logs/dating/test/20260827-120000-a1b2"
    )
