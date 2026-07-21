"""只发布脱敏构建摘要的飞书机器人通知器。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from types import TracebackType
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ElementTree

import requests

from framework.security.redactor import Redactor


DEFAULT_MAX_PAYLOAD_BYTES = 20 * 1024
DEFAULT_MAX_JUNIT_BYTES = 5 * 1024 * 1024
_SUMMARY_SCALAR_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:/\[\]-]{1,200}$")
_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(auth[_-]?token|refresh[_-]?token|authorization|password|secret|webhook|token)"
    r"\s*[:=]\s*[^\s,;&]+"
)


class NotificationError(RuntimeError):
    """飞书通知安全异常。

    功能说明:
        表示通知配置、传输或飞书业务失败，不包含远端诊断内容。
    参数说明:
        继承 ``RuntimeError`` 的安全错误消息参数。
    返回值:
        无；该类型仅用于异常传播。
    异常说明:
        本类型自身不额外抛出异常。
    """


class SummaryParseError(ValueError):
    """JUnit 摘要解析异常。

    功能说明:
        表示 JUnit 文件缺失、过大、不安全或结构错误。
    参数说明:
        继承 ``ValueError`` 的安全错误消息参数。
    返回值:
        无；该类型仅用于异常传播。
    异常说明:
        本类型自身不额外抛出异常。
    """


@dataclass(frozen=True, slots=True)
class BuildSummary:
    """飞书可用的严格构建摘要，刻意不提供原始请求或响应字段。

    功能说明:
        保存允许发送到飞书的严格构建摘要，不提供原始请求或响应字段。
    参数说明:
        build_number: CI 构建号；environment: 目标环境；suite: 测试集名称；
        total/passed/failed/skipped: JUnit 聚合计数；p0_failed_cases: P0 失败用例名；
        trace_ids: 用于服务端排查的 trace ID；allure_report_url: 可选 Allure 报告地址。
    返回值:
        实例作为通知器的冻结输入摘要。
    异常说明:
        字段类型错误、空关键字段、负数计数或计数不一致时抛出 ``ValueError``。
    """

    build_number: str
    environment: str
    suite: str
    total: int
    passed: int
    failed: int
    skipped: int
    p0_failed_cases: tuple[str, ...] = ()
    trace_ids: tuple[str, ...] = ()
    allure_report_url: str | None = None

    def __post_init__(self) -> None:
        """严格验证摘要，避免宽松类型转换掩盖 CI 数据错误。"""
        for field_name in ("build_number", "environment", "suite"):
            value = getattr(self, field_name)
            if type(value) is not str or not _SUMMARY_SCALAR_PATTERN.fullmatch(value):
                raise ValueError(
                    f"{field_name} 必须是 1～64 位字母、数字、点、下划线或连字符"
                )
        for field_name in ("total", "passed", "failed", "skipped"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} 必须是非负整数")
        if self.total != self.passed + self.failed + self.skipped:
            raise ValueError("总数必须等于通过、失败与跳过数之和")
        for field_name in ("p0_failed_cases", "trace_ids"):
            values = getattr(self, field_name)
            if type(values) is not tuple or any(
                type(item) is not str or not item.strip() for item in values
            ):
                raise ValueError(f"{field_name} 必须是非空字符串元组")
        if self.allure_report_url is not None and type(self.allure_report_url) is not str:
            raise ValueError("allure_report_url 必须是字符串或 None")


@dataclass(frozen=True, slots=True)
class NotificationResult:
    """通知发布结果。

    功能说明:
        表示 disabled、dry-run 或 published 状态；仅 dry-run 携带脱敏 payload。
    参数说明:
        status: 发布状态；payload: 可选脱敏消息载荷。
    返回值:
        实例作为 ``FeishuNotifier.publish`` 的冻结结果。
    异常说明:
        数据类构造不主动校验，类型约束供静态检查和调用方遵守。
    """

    status: Literal["disabled", "dry_run", "published"]
    payload: Mapping[str, Any] | None = None


class FeishuNotifier:
    """以禁重定向、分离超时和安全异常发布飞书构建摘要。

    功能说明:
        以禁重定向、分离超时和安全异常发布脱敏飞书构建摘要。
    参数说明:
        webhook_url: 飞书 webhook；空值表示禁用。dry_run: 仅生成脱敏 payload。
        session: 可注入 HTTP 会话用于离线测试。connect_timeout/read_timeout: 秒级超时。
        max_payload_bytes: UTF-8 JSON payload 的最大字节数。
    返回值:
        :meth:`publish` 返回 ``NotificationResult``，禁用和 dry-run 均零网络。
    异常说明:
        非 HTTPS、payload 过大、网络异常、非 2xx 或飞书业务码非 0 时抛出
        ``NotificationError``；异常文本不包含 webhook、URL、响应体或底层异常。
    """

    def __init__(
        self,
        *,
        webhook_url: str | None,
        dry_run: bool = False,
        session: requests.Session | Any | None = None,
        redactor: Redactor | None = None,
        connect_timeout: float = 3.0,
        read_timeout: float = 5.0,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        self._webhook_url = webhook_url.strip() if webhook_url else None
        self._dry_run = dry_run
        self._owns_session = session is None
        self._session = requests.Session() if session is None else session
        self._closed = False
        self._redactor = redactor or Redactor.from_config()
        self._timeout = (connect_timeout, read_timeout)
        self._max_payload_bytes = max_payload_bytes

    def __enter__(self) -> "FeishuNotifier":
        """进入上下文并返回当前通知器，由退出阶段负责关闭自建 Session。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出上下文；不吞掉业务异常，仅幂等关闭通知器自建的 Session。"""
        self.close()

    def close(self) -> None:
        """幂等关闭内部创建的 HTTP Session，注入的外部 Session 始终由调用方管理。

        功能说明:
            幂等关闭通知器自建的 HTTP Session。
        参数说明:
            无。
        返回值:
            无；首次关闭自建 Session 后，后续调用直接安全返回。
        异常说明:
            底层自建 Session 的 ``close`` 异常原样抛出，但不会在重试关闭时再次调用。
        """
        if self._closed or not self._owns_session:
            return
        self._closed = True
        close = getattr(self._session, "close", None)
        if callable(close):
            close()

    def publish(self, summary: BuildSummary) -> NotificationResult:
        """发布构建摘要，同时保证禁用与 dry-run 路径不会访问网络。

        功能说明:
            根据禁用、dry-run 或启用模式处理并发布脱敏摘要。
        参数说明:
            summary: 仅含允许发送字段的冻结 ``BuildSummary``。
        返回值:
            禁用、dry-run 或成功发布状态；仅 dry-run 返回脱敏 payload。
        异常说明:
            配置、大小、HTTP 或业务失败统一抛出不含秘密的 ``NotificationError``。
        """
        if not self._webhook_url:
            return NotificationResult(status="disabled")
        self._validate_webhook()
        payload = self._build_payload(summary)
        if self._dry_run:
            return NotificationResult(status="dry_run", payload=payload)
        try:
            response = self._session.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                allow_redirects=False,
                timeout=self._timeout,
            )
        except requests.RequestException:
            raise NotificationError("飞书通知网络请求失败") from None
        except Exception:
            raise NotificationError("飞书通知传输失败") from None
        if not 200 <= response.status_code < 300:
            raise NotificationError("飞书通知 HTTP 状态异常")
        try:
            body = response.json()
        except Exception:
            raise NotificationError("飞书通知响应格式异常") from None
        if not isinstance(body, dict) or body.get("code") != 0:
            raise NotificationError("飞书通知业务状态异常")
        return NotificationResult(status="published")

    def _validate_webhook(self) -> None:
        """仅接受具有主机名的 HTTPS webhook，错误信息不回显原值。"""
        try:
            parsed = urlsplit(self._webhook_url or "")
        except ValueError:
            raise NotificationError("飞书 webhook 必须是有效 HTTPS 地址") from None
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise NotificationError("飞书 webhook 必须是有效 HTTPS 地址")

    def _build_payload(self, summary: BuildSummary) -> dict[str, Any]:
        """先脱敏摘要再构造飞书文本消息，并按 UTF-8 JSON 大小拒绝超限数据。"""
        safe_summary = self._redactor.redact(asdict(summary))
        safe_cases = self._filter_identifiers(
            safe_summary["p0_failed_cases"], _CASE_ID_PATTERN
        )
        safe_trace_ids = self._filter_identifiers(
            safe_summary["trace_ids"], _TRACE_ID_PATTERN
        )
        safe_report_url = self._canonicalize_report_url(
            safe_summary["allure_report_url"]
        )
        lines = [
            "Truthy API 自动化测试结果",
            f"构建号: {safe_summary['build_number']}",
            f"环境: {safe_summary['environment']}",
            f"测试集: {safe_summary['suite']}",
            (
                "总计/通过/失败/跳过: "
                f"{safe_summary['total']}/{safe_summary['passed']}/"
                f"{safe_summary['failed']}/{safe_summary['skipped']}"
            ),
            "P0 失败: " + (", ".join(safe_cases) or "无"),
            "Trace IDs: " + (", ".join(safe_trace_ids) or "无"),
        ]
        if safe_report_url:
            lines.append(f"Allure: {safe_report_url}")
        safe_text = _SECRET_ASSIGNMENT_PATTERN.sub(
            lambda match: f"{match.group(1)}=***REDACTED***", "\n".join(lines)
        )
        payload = {"msg_type": "text", "content": {"text": safe_text}}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > self._max_payload_bytes:
            raise NotificationError("飞书通知 payload 大小超过安全上限")
        return payload

    @staticmethod
    def _filter_identifiers(
        values: tuple[str, ...] | list[str], pattern: re.Pattern[str]
    ) -> tuple[str, ...]:
        """按字段专用字符白名单和长度限制丢弃非法标识，并保持首次出现顺序。"""
        accepted: list[str] = []
        for value in values:
            if (
                pattern.fullmatch(value)
                and not _SECRET_ASSIGNMENT_PATTERN.search(value)
                and value not in accepted
            ):
                accepted.append(value)
        return tuple(accepted)

    @staticmethod
    def _canonicalize_report_url(value: str | None) -> str | None:
        """仅保留 HTTP(S) 报告 URL 的主机、端口和路径，删除用户信息、查询与片段。"""
        if not value or len(value) > 2048:
            return None
        try:
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                return None
            hostname = parsed.hostname
            if ":" in hostname:
                hostname = f"[{hostname}]"
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            return None
        return urlunsplit((parsed.scheme.lower(), f"{hostname}{port}", parsed.path, "", ""))


def parse_junit_summary(
    path: str | Path,
    *,
    build_number: str,
    environment: str,
    suite: str,
    allure_report_url: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_JUNIT_BYTES,
) -> BuildSummary:
    """从有限大小且无 DTD/实体声明的 JUnit XML 构造安全摘要。

    功能说明:
        安全读取 JUnit XML，重新聚合计数并抽取 P0 case 与 trace ID。
    参数说明:
        path: JUnit XML 路径；build_number/environment/suite: 构建元数据；
        allure_report_url: 可选报告地址；max_file_bytes: 最大允许文件大小。
    返回值:
        从 testcase 节点重新计算计数的冻结 ``BuildSummary``。
    异常说明:
        文件缺失、读取失败、文件过大、含 DTD/ENTITY、XML 畸形或无 testcase 时，
        抛出不包含 XML 内容的 ``SummaryParseError``。
    """
    report_path = Path(path)
    try:
        size = report_path.stat().st_size
        if size > max_file_bytes:
            raise SummaryParseError("JUnit XML 超过安全大小上限")
        raw = report_path.read_bytes()
    except SummaryParseError:
        raise
    except OSError:
        raise SummaryParseError("JUnit XML 不存在或不可读取") from None
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise SummaryParseError("JUnit XML 包含不允许的外部实体声明")
    try:
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, ValueError):
        raise SummaryParseError("JUnit XML 格式错误") from None
    cases = root.findall(".//testcase")
    if root.tag == "testcase":
        cases = [root]
    if not cases:
        raise SummaryParseError("JUnit XML 未包含测试用例")
    failed = 0
    skipped = 0
    p0_failures: list[str] = []
    trace_ids: list[str] = []
    for case in cases:
        is_failed = case.find("failure") is not None or case.find("error") is not None
        is_skipped = case.find("skipped") is not None
        failed += int(is_failed)
        skipped += int(is_skipped)
        properties = {
            item.get("name", "").lower(): item.get("value", "")
            for item in case.findall("./properties/property")
        }
        trace_id = properties.get("trace_id") or properties.get("trace-id")
        if trace_id and trace_id not in trace_ids:
            trace_ids.append(trace_id)
        marker_text = " ".join(
            value for name, value in properties.items() if name in {"markers", "marker", "tags"}
        ).lower()
        if is_failed and "p0" in marker_text.split():
            class_name = case.get("classname", "").strip()
            case_name = case.get("name", "unknown").strip()
            p0_failures.append(f"{class_name}::{case_name}" if class_name else case_name)
    total = len(cases)
    passed = total - failed - skipped
    if passed < 0:
        raise SummaryParseError("JUnit XML 用例状态不一致")
    return BuildSummary(
        build_number=build_number,
        environment=environment,
        suite=suite,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        p0_failed_cases=tuple(p0_failures),
        trace_ids=tuple(trace_ids),
        allure_report_url=allure_report_url,
    )
