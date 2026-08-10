"""junit_report 单元测试：统计、失败清单、缺失与损坏边界。"""

from __future__ import annotations

from pathlib import Path

from conftest import junit_xml

from web.junit_report import parse_junit_file


def _write(tmp_path: Path, content: str) -> Path:
    """把 XML 文本写入临时 JUnit 文件。"""
    path = tmp_path / "junit.xml"
    path.write_text(content, encoding="utf-8")
    return path


def test_mixed_summary(tmp_path: Path) -> None:
    """正常/失败/错误/跳过混合统计正确。"""
    path = _write(
        tmp_path,
        junit_xml(
            [
                ("case_pass_1", "passed"),
                ("case_pass_2", "passed"),
                ("case_fail", "failure"),
                ("case_error", "error"),
                ("case_skip", "skipped"),
            ]
        ),
    )
    parsed = parse_junit_file(path)
    assert parsed is not None
    assert parsed["summary"] == {
        "total": 5,
        "passed": 2,
        "failed": 1,
        "errors": 1,
        "skipped": 1,
    }
    names = [case["name"] for case in parsed["failed_cases"]]
    assert names == ["case_fail", "case_error"]


def test_failure_message_truncated(tmp_path: Path) -> None:
    """失败摘要截断到 500 字符以内。"""
    long_message = "x" * 800
    xml = junit_xml([("case_fail", "failure")], message=long_message)
    parsed = parse_junit_file(_write(tmp_path, xml))
    assert parsed is not None
    assert len(parsed["failed_cases"][0]["message"]) <= 500


def test_failure_message_redacted(tmp_path: Path) -> None:
    """失败摘要中的凭证必须被掩盖。"""
    xml = junit_xml(
        [("case_fail", "failure")],
        message="Authorization: Bearer secret-token-value",
    )
    parsed = parse_junit_file(_write(tmp_path, xml))
    assert parsed is not None
    assert "secret-token-value" not in parsed["failed_cases"][0]["message"]


def test_missing_file_returns_none(tmp_path: Path) -> None:
    """文件不存在是合法边界：返回 None 而非抛异常。"""
    assert parse_junit_file(tmp_path / "not-exists.xml") is None


def test_corrupted_xml_returns_none(tmp_path: Path) -> None:
    """损坏 XML 视为结果不可用。"""
    assert parse_junit_file(_write(tmp_path, "<testsuites><broken")) is None


def test_empty_testsuite(tmp_path: Path) -> None:
    """无用例时统计全零。"""
    parsed = parse_junit_file(
        _write(tmp_path, '<?xml version="1.0"?><testsuites></testsuites>')
    )
    assert parsed is not None
    assert parsed["summary"]["total"] == 0
    assert parsed["failed_cases"] == []
