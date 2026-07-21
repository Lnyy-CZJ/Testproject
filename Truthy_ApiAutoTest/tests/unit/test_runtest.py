"""统一运行入口参数组装测试。"""

from typing import Any

import pytest

import runtest


def test_build_pytest_args_combines_suite_markers_and_reports(monkeypatch: Any) -> None:
    monkeypatch.setattr(runtest, "has_xdist", lambda: True)
    args = runtest.parse_args(
        [
            "--env",
            "staging",
            "--suite",
            "contract",
            "--markers",
            "p0 and smoke",
            "--exclude-marker",
            "payment_real",
            "--workers",
            "3",
            "--junitxml",
            "artifacts/junit.xml",
            "--alluredir",
            "allure-results",
            "--run-live-safe",
            "-v",
        ]
    )

    pytest_args = runtest.build_pytest_args(args)

    assert pytest_args[0] == "tests/contract"
    assert pytest_args[pytest_args.index("--env") + 1] == "staging"
    marker_expression = pytest_args[pytest_args.index("-m") + 1]
    assert marker_expression == "(p0 and smoke) and not (payment_real) and not (payment_real or destructive)"
    assert pytest_args[pytest_args.index("-n") + 1] == "3"
    assert "--run-live-safe" in pytest_args
    assert "-v" in pytest_args


def test_main_calls_pytest_main_with_built_arguments(monkeypatch: Any) -> None:
    captured: list[list[str]] = []
    monkeypatch.setattr(runtest.pytest, "main", lambda args: captured.append(args) or 7)
    monkeypatch.setattr(runtest, "has_xdist", lambda: False)

    exit_code = runtest.main(["--suite", "unit", "--env", "test"])

    assert exit_code == 7
    assert captured == [[
        "tests/unit", "--env", "test", "-m", "not (payment_real or destructive)"
    ]]


def test_default_and_live_safe_runs_keep_dangerous_markers_excluded() -> None:
    default_args = runtest.build_pytest_args(runtest.parse_args([]))
    live_args = runtest.build_pytest_args(runtest.parse_args(["--run-live-safe"]))

    assert default_args[default_args.index("-m") + 1] == "not (payment_real or destructive)"
    assert live_args[live_args.index("-m") + 1] == "not (payment_real or destructive)"


def test_smoke_and_regression_suites_combine_builtin_and_custom_markers() -> None:
    smoke = runtest.build_pytest_args(
        runtest.parse_args(["--suite", "smoke", "--markers", "p0"])
    )
    regression = runtest.build_pytest_args(
        runtest.parse_args(["--suite", "regression", "--markers", "contract"])
    )

    assert smoke[0] == "tests"
    assert smoke[smoke.index("-m") + 1] == "(smoke) and (p0) and not (payment_real or destructive)"
    assert regression[0] == "tests"
    assert regression[regression.index("-m") + 1] == "(contract) and not (payment_real or destructive)"


def test_dangerous_markers_cannot_be_enabled_or_bypass_exclusion() -> None:
    pytest_args = runtest.build_pytest_args(
        runtest.parse_args(["--markers", "payment_real or smoke"])
    )

    assert pytest_args[pytest_args.index("-m") + 1].endswith(
        "and not (payment_real or destructive)"
    )
    with pytest.raises(SystemExit):
        runtest.parse_args(["--run-dangerous"])


def test_workers_default_to_one_and_only_use_xdist_when_available(monkeypatch: Any) -> None:
    args = runtest.parse_args([])
    assert args.workers == 1

    monkeypatch.setattr(runtest, "has_xdist", lambda: False)
    assert "-n" not in runtest.build_pytest_args(args)

    monkeypatch.setattr(runtest, "has_xdist", lambda: True)
    pytest_args = runtest.build_pytest_args(args)
    assert pytest_args[pytest_args.index("-n") + 1] == "1"
