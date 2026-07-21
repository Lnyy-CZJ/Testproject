"""阶段 5 CI 模板和安全脚本的静态测试。"""

import re
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TC018_NODE = "test_search_contract.py::test_tc018_compatibility_create_start_and_duplicate_start"


def _collect_search_contract(marker_expression: str) -> subprocess.CompletedProcess[str]:
    """按 CI 使用的 marker 表达式收集搜索合同，返回节点输出而不依赖固定数量。"""
    return subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/contract/test_search_contract.py",
            "-m",
            marker_expression,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_jenkinsfile_has_required_safety_gates_and_publishers() -> None:
    text = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")

    assert "agent any" in text
    assert "cron(" in text and "1-5" in text
    assert "timeout(time: 35, unit: 'MINUTES')" in text
    assert "disableConcurrentBuilds()" in text
    assert "daysToKeepStr: '30'" in text
    for parameter in (
        "EXECUTION_MODE",
        "TARGET_ENV",
        "TEST_SUITE",
        "PYTEST_MARKERS",
        "WORKERS",
    ):
        assert parameter in text
    assert "env.CHANGE_ID" in text
    assert "TimerTrigger$TimerTriggerCause" in text
    assert "UserIdCause" in text
    assert re.search(
        r"if \(env\.CHANGE_ID.*?EFFECTIVE_MODE = 'merge_request'.*?"
        r"EFFECTIVE_SUITE = 'contract'.*?EFFECTIVE_MARKERS = 'p0 and not \(live_write",
        text,
        re.S,
    )
    assert re.search(
        r"timerBuild.*?EFFECTIVE_MODE = 'weekday_smoke'.*?"
        r"EFFECTIVE_SUITE = 'smoke'.*?EFFECTIVE_MARKERS = 'p0 and not \(live_write",
        text,
        re.S,
    )
    assert re.search(
        r"\['release', 'payment_sandbox', 'compatibility'\].*?"
        r"if \(!manualBuild\).*?error\(",
        text,
        re.S,
    )
    assert re.search(
        r"stage\('Release P0'\).*?--markers \"p0 and not \(live_write",
        text,
        re.S,
    )
    assert re.search(
        r"stage\('Release P1'\).*?returnStatus: true.*?--markers \"p1 and not "
        r"\(live_write.*?input message:",
        text,
        re.S,
    )
    assert "pip install --require-hashes -r requirements.lock" in text
    assert "python3 runtest.py" in text
    assert "artifacts/junit.xml" in text and "allure-results" in text
    assert "--run-dangerous" not in text
    assert "EFFECTIVE_LIVE_ARGS = '--run-live-safe'" in text
    assert re.search(
        r"EFFECTIVE_MODE = 'merge_request'.*?EFFECTIVE_LIVE_ARGS = ''",
        text,
        re.S,
    )
    assert "junit " in text and "allure " in text and "archiveArtifacts" in text
    assert "scripts/notify_feishu.py" in text
    assert not re.search(r"https://[^'\" ]*(?:hook|token)", text, re.I)


def test_weekday_home_probe_is_live_safe_smoke_p0() -> None:
    """工作日集合必须包含明确授权、无凭据时可跳过的 Home 只读探针。"""
    source = (ROOT / "tests/contract/test_home_contract.py").read_text(encoding="utf-8")
    live_test = source[source.index("def test_get_home_content_live_safe") - 180 :]

    assert "@pytest.mark.live_safe" in live_test
    assert "@pytest.mark.smoke" in live_test
    assert "@pytest.mark.p0" in live_test


def test_payment_sandbox_manual_expression_selects_offline_contracts() -> None:
    """手工支付沙箱表达式至少选中一个离线 mock，且执行不需要网络。"""
    collected = subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/contract/test_identity_subscription_contract.py",
            "tests/unit/test_billing_service.py",
            "-m",
            "payment_sandbox and not live_write",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert collected.returncode == 0
    assert "test_tc010_duplicate_create" in collected.stdout
    assert "test_create_order_matches_document" in collected.stdout
def test_notify_script_is_disabled_before_reading_junit_when_webhook_missing() -> None:
    environment = os.environ.copy()
    environment.pop("FEISHU_WEBHOOK", None)

    result = subprocess.run(
        [
            "python3",
            "scripts/notify_feishu.py",
            "--junitxml",
            "artifacts/definitely-missing.xml",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "disabled" in result.stdout.lower()
    assert result.stderr == ""


def test_manual_compatibility_mode_selects_and_passes_tc018() -> None:
    collected = _collect_search_contract("compatibility and not live_write")
    assert collected.returncode == 0
    assert TC018_NODE in collected.stdout

    executed = subprocess.run(
        [
            "python3",
            "runtest.py",
            "--suite",
            "all",
            "--markers",
            "compatibility and not live_write",
            "-v",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert executed.returncode == 0
    assert TC018_NODE in executed.stdout
    assert "PASSED" in executed.stdout


def test_automatic_and_release_gates_do_not_collect_tc018() -> None:
    gate_expressions = {
        "merge_request": "p0 and not (live_write or payment_sandbox or compatibility)",
        "weekday": "smoke and p0 and not (live_write or payment_sandbox or compatibility)",
        "release_p0": "p0 and not (live_write or payment_sandbox or compatibility)",
        "release_p1": "p1 and not (live_write or payment_sandbox or compatibility)",
    }

    for expression in gate_expressions.values():
        collected = _collect_search_contract(expression)
        assert TC018_NODE not in collected.stdout
