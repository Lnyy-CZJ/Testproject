"""飞书通知器的离线安全测试。"""

from pathlib import Path
import subprocess
import tempfile
from typing import Any

import pytest
import requests

import framework.integrations.feishu_notifier as feishu_module
from framework.integrations.feishu_notifier import (
    BuildSummary,
    FeishuNotifier,
    NotificationError,
    SummaryParseError,
    parse_junit_summary,
)


def _summary(**overrides: Any) -> BuildSummary:
    values = {
        "build_number": "42",
        "environment": "test",
        "suite": "smoke",
        "total": 3,
        "passed": 1,
        "failed": 1,
        "skipped": 1,
        "p0_failed_cases": ("case_p0",),
        "trace_ids": ("trace-1",),
        "allure_report_url": "https://reports.example/allure?signature=secret",
    }
    values.update(overrides)
    return BuildSummary(**values)


class _Response:
    def __init__(self, status_code: int = 200, body: Any = None) -> None:
        self.status_code = status_code
        self._body = {"code": 0} if body is None else body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Session:
    def __init__(self, response: _Response | Exception = _Response()) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.close_calls = 0

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def close(self) -> None:
        self.close_calls += 1


def test_disabled_and_dry_run_never_touch_network() -> None:
    session = _Session()
    disabled = FeishuNotifier(webhook_url=None, session=session)
    dry_run = FeishuNotifier(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/secret-token",
        dry_run=True,
        session=session,
    )

    assert disabled.publish(_summary()).status == "disabled"
    result = dry_run.publish(_summary())

    assert result.status == "dry_run"
    assert session.calls == []
    rendered = str(result.payload)
    assert "secret-token" not in rendered
    assert "signature=secret" not in rendered


def test_enabled_requires_https_before_network() -> None:
    session = _Session()
    notifier = FeishuNotifier(webhook_url="http://example.test/hook/token", session=session)

    with pytest.raises(NotificationError, match="HTTPS") as error:
        notifier.publish(_summary())

    assert session.calls == []
    assert "token" not in str(error.value)


def test_post_disables_redirect_and_sets_split_timeout() -> None:
    session = _Session()
    notifier = FeishuNotifier(
        webhook_url="https://example.test/hook/token",
        session=session,
        connect_timeout=1.5,
        read_timeout=4.0,
    )

    assert notifier.publish(_summary()).status == "published"

    assert session.calls[0]["allow_redirects"] is False
    assert session.calls[0]["timeout"] == (1.5, 4.0)
    assert session.calls[0]["headers"] == {"Content-Type": "application/json"}


@pytest.mark.parametrize(
    "response",
    [
        _Response(302, {"code": 0}),
        _Response(500, {"code": 0}),
        _Response(200, {"code": 19001}),
        _Response(200, ValueError("response included secret")),
        requests.ReadTimeout("https://example.test/hook/secret-token"),
    ],
)
def test_remote_failures_raise_safe_error(response: _Response | Exception) -> None:
    notifier = FeishuNotifier(
        webhook_url="https://example.test/hook/secret-token",
        session=_Session(response),
    )

    with pytest.raises(NotificationError) as error:
        notifier.publish(_summary())

    message = str(error.value)
    assert "secret-token" not in message
    assert "https://" not in message
    assert "response included secret" not in message


def test_payload_is_redacted_and_size_limited() -> None:
    notifier = FeishuNotifier(webhook_url="https://example.test/hook/token", dry_run=True)

    payload = notifier.publish(_summary()).payload
    assert "secret" not in str(payload)

    many_valid_cases = tuple(
        f"tests.contract.test_payload::test_case_{index:04d}[{'x' * 120}]"
        for index in range(300)
    )
    with pytest.raises(NotificationError, match="大小"):
        notifier.publish(_summary(p0_failed_cases=many_valid_cases))


def test_payload_applies_field_whitelists_and_canonicalizes_allure_url() -> None:
    notifier = FeishuNotifier(webhook_url="https://example.test/hook/token", dry_run=True)

    result = notifier.publish(
        _summary(
            p0_failed_cases=(
                "tests.contract.test_home::test_safe[id-1]",
                "token=CASE_SECRET",
                "bad case with spaces",
                "x" * 300,
            ),
            trace_ids=("trace-safe_123", "token=TRACE_SECRET", "bad trace!"),
            allure_report_url=(
                "https://user:password@reports.example:8443/allure/42"
                "?token=URL_SECRET&signature=abc#private"
            ),
        )
    )

    rendered = str(result.payload)
    assert "tests.contract.test_home::test_safe[id-1]" in rendered
    assert "trace-safe_123" in rendered
    assert "https://reports.example:8443/allure/42" in rendered
    for secret in ("CASE_SECRET", "TRACE_SECRET", "URL_SECRET", "password", "private"):
        assert secret not in rendered


def test_payload_drops_identifiers_with_sensitive_colon_or_equals_assignments() -> None:
    notifier = FeishuNotifier(webhook_url="https://example.test/hook/token", dry_run=True)

    result = notifier.publish(
        _summary(
            p0_failed_cases=(
                "tests.x::test_safe[id-1]",
                "tests.x::test_token[param-1]",
                "tests.x::token:CASE_SECRET",
                "tests.x::auth_token:AUTH_UNDERSCORE_SECRET",
                "tests.x::test_auth_token:PREFIX_AUTH_SECRET",
                "tests.x::case-refresh_token:PREFIX_REFRESH_SECRET",
                "tests.x::TEST_AUTH-TOKEN:UPPER_AUTH_SECRET",
                "tests.x::Auth-Token=AUTH_SECRET",
                "tests.x::webhook:HOOK_SECRET",
            ),
            trace_ids=(
                "trace-safe-1",
                "trace-auth_token:TRACE_PREFIX_SECRET",
                "authorization:TRACE_SECRET",
                "REFRESH_TOKEN=REFRESH_SECRET",
                "password:PASS_SECRET",
                "secret:PLAIN_SECRET",
            ),
            allure_report_url=(
                "https://reports.example/password=URL_PASS_SECRET/"
                "secret:URL_SECRET/report"
            ),
        )
    )

    rendered = str(result.payload)
    assert "tests.x::test_safe[id-1]" in rendered
    assert "tests.x::test_token[param-1]" in rendered
    assert "trace-safe-1" in rendered
    assert "tests.x::token" not in rendered
    assert "authorization:" not in rendered.lower()
    for secret in (
        "CASE_SECRET",
        "AUTH_SECRET",
        "AUTH_UNDERSCORE_SECRET",
        "PREFIX_AUTH_SECRET",
        "PREFIX_REFRESH_SECRET",
        "UPPER_AUTH_SECRET",
        "HOOK_SECRET",
        "TRACE_SECRET",
        "TRACE_PREFIX_SECRET",
        "REFRESH_SECRET",
        "PASS_SECRET",
        "PLAIN_SECRET",
        "URL_PASS_SECRET",
        "URL_SECRET",
    ):
        assert secret not in rendered


def test_notifier_closes_only_owned_session_once_and_supports_context_manager(
    monkeypatch: Any,
) -> None:
    first_owned = _Session()
    second_owned = _Session()
    owned_sessions = iter((first_owned, second_owned))
    monkeypatch.setattr(feishu_module.requests, "Session", lambda: next(owned_sessions))

    notifier = FeishuNotifier(webhook_url=None)
    notifier.close()
    notifier.close()
    assert first_owned.close_calls == 1

    with FeishuNotifier(webhook_url=None) as managed:
        assert isinstance(managed, FeishuNotifier)
    assert second_owned.close_calls == 1

    external = _Session()
    with FeishuNotifier(webhook_url=None, session=external):
        pass
    assert external.close_calls == 0


def test_summary_scalar_fields_enforce_whitelist_and_length() -> None:
    with pytest.raises(ValueError):
        _summary(build_number="token=BUILD_SECRET")
    with pytest.raises(ValueError):
        _summary(environment="x" * 65)


def test_build_summary_is_frozen_and_rejects_inconsistent_counts() -> None:
    summary = _summary()
    with pytest.raises((AttributeError, TypeError)):
        summary.total = 8  # type: ignore[misc]
    with pytest.raises(ValueError, match="总数"):
        _summary(total=9)


def test_parse_junit_summary_extracts_failures_p0_and_trace_ids(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        """<?xml version="1.0"?>
        <testsuites tests="3" failures="1" errors="0" skipped="1">
          <testsuite name="suite">
            <testcase classname="tests.test_demo" name="test_ok">
              <properties><property name="trace_id" value="trace-ok"/></properties>
            </testcase>
            <testcase classname="tests.test_demo" name="test_bad">
              <properties><property name="markers" value="contract p0 smoke"/>
              <property name="trace_id" value="trace-bad"/></properties>
              <failure message="nope"/>
            </testcase>
            <testcase classname="tests.test_demo" name="test_skip"><skipped/></testcase>
          </testsuite>
        </testsuites>""",
        encoding="utf-8",
    )

    summary = parse_junit_summary(
        report,
        build_number="42",
        environment="test",
        suite="smoke",
        allure_report_url="https://reports.example/42",
    )

    assert (summary.total, summary.passed, summary.failed, summary.skipped) == (3, 1, 1, 1)
    assert summary.p0_failed_cases == ("tests.test_demo::test_bad",)
    assert summary.trace_ids == ("trace-ok", "trace-bad")


def test_real_pytest_junit_preserves_p0_failure_for_summary(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    # 放在项目 tests 下才能复现真实 conftest 自动发现；上下文结束后目录立即清理。
    with tempfile.TemporaryDirectory(prefix="phase5-junit-", dir=root / "tests") as directory:
        test_file = Path(directory) / "test_marker_failure.py"
        report = tmp_path / "junit.xml"
        test_file.write_text(
            "import pytest\n"
            "@pytest.mark.p0\n"
            "@pytest.mark.smoke\n"
            "def test_p0_failure():\n"
            "    assert False\n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                "python3",
                "-m",
                "pytest",
                "-q",
                str(test_file),
                "--junitxml",
                str(report),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 1

        summary = parse_junit_summary(
            report,
            build_number="integration",
            environment="test",
            suite="smoke",
        )
        assert len(summary.p0_failed_cases) == 1
        assert summary.p0_failed_cases[0].endswith(
            "test_marker_failure::test_p0_failure"
        )


@pytest.mark.parametrize("content", ["<broken", "<!DOCTYPE x [<!ENTITY a 'x'>]><testsuites/>"])
def test_parse_junit_summary_rejects_unsafe_or_malformed_xml(
    tmp_path: Path, content: str
) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(content, encoding="utf-8")

    with pytest.raises(SummaryParseError):
        parse_junit_summary(report, build_number="1", environment="test", suite="unit")
