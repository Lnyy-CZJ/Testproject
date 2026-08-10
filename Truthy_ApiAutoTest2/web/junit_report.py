"""JUnit XML 结果解析。

功能说明:
    解析任务级 JUnit 文件（``reports/junit-task-<id>.xml``），产出统计
    摘要与失败用例清单。取消或强制终止可能不会触发 pytest session
    finish，因此文件不存在属于合法边界，由调用方以
    ``result_available=false`` 表达，不抛异常。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from web.redaction import FAILED_MESSAGE_LIMIT, redact_text


def _case_message(element: ET.Element) -> str:
    """提取 failure/error 元素的摘要消息并脱敏截断。

    参数说明:
        element: testcase 下的 failure 或 error 元素。

    返回值:
        优先取 message 属性，其次取元素文本；统一脱敏并截断到
        ``FAILED_MESSAGE_LIMIT`` 字符。
    """
    message = element.get("message") or (element.text or "")
    return redact_text(message.strip(), max_length=FAILED_MESSAGE_LIMIT)


def parse_junit_file(
    path: Path,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """解析一个 JUnit XML 文件。

    功能说明:
        以 testcase 为单位统计 total/passed/failed/errors/skipped，
        并收集 failed 与 error 用例的名称和脱敏后的失败摘要。
        pytest 的 JUnit 可能嵌套 testsuite，故直接遍历全部 testcase。

    参数说明:
        path: JUnit XML 文件路径。
        project_root: 项目根目录，用于脱敏容器内绝对路径。

    返回值:
        ``{"summary": {...}, "failed_cases": [...]}``；文件不存在或
        不是合法 XML 时返回 None（视为结果不可用）。
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None

    total = failed = errors = skipped = 0
    failed_cases: list[dict[str, str]] = []
    for case in root.iter("testcase"):
        total += 1
        failure = case.find("failure")
        error = case.find("error")
        if failure is not None:
            failed += 1
            failed_cases.append(
                {"name": case.get("name", ""), "message": _case_message(failure)}
            )
        elif error is not None:
            errors += 1
            failed_cases.append(
                {"name": case.get("name", ""), "message": _case_message(error)}
            )
        elif case.find("skipped") is not None:
            skipped += 1

    passed = max(total - failed - errors - skipped, 0)
    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
        },
        "failed_cases": failed_cases,
    }
