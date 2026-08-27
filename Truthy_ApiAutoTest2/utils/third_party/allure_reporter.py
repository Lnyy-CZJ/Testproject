"""Allure 报告观察层，集中隔离报告失败与业务测试执行。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import allure

from utils.custom.logger import get_logger

LOGGER = get_logger(__name__)

# 运行报告只允许携带这些不可变追溯字段。Gateway、Secret、Profile 内容和
# runtime_variables 不在白名单内，避免 JUnit/Allure 变成第二份配置副本。
_RUNTIME_METADATA_KEYS = (
    "task_id",
    "platform_environment",
    "runtime_scope_id",
    "config_release_id",
    "config_release_version",
)


def _log_reporter_failure(operation: str, exc: Exception) -> None:
    """仅记录报告异常类型，避免原始业务数据通过异常消息泄露。"""
    LOGGER.warning("Allure %s失败: %s", operation, type(exc).__name__)


def build_runtime_report_metadata(
    *,
    project_id: str,
    target_env: str,
    config_source: str,
    settings: dict[str, Any],
) -> dict[str, str]:
    """构造 JUnit/Allure 共用的非敏感运行身份元数据。

    参数说明:
        project_id: 当前项目包 ID。
        target_env: 当前被测环境，由平台实例固定映射。
        config_source: ``platform`` 或兼容期 ``local``。
        settings: 已加载的运行配置；仅读取其中 ``runtime_metadata`` 白名单。

    返回值:
        可直接写入报告属性的字符串字典。空字段会被省略，本函数绝不复制
        Gateway 地址、Secret、Credential 或任意业务配置值。
    """
    metadata: dict[str, str] = {
        "project_id": str(project_id),
        "target_env": str(target_env),
        "config_source": str(config_source),
    }
    runtime_metadata = settings.get("runtime_metadata")
    if not isinstance(runtime_metadata, dict):
        return metadata
    for key in _RUNTIME_METADATA_KEYS:
        value = runtime_metadata.get(key)
        # 白名单字段均应为标量；拒绝容器可防止未来字段形态变化时意外把
        # Credential/Profile 详情序列化进报告。
        if value in (None, "") or isinstance(value, (dict, list, tuple, set)):
            continue
        metadata[key] = str(value)
    return metadata


def set_runtime_report_metadata(metadata: dict[str, str]) -> None:
    """把非敏感 Scope/Release 身份写入当前 Allure 用例参数区。

    Allure 属于观察层；报告插件不可用时只记录异常类型，不得改变真实接口
    测试结果。调用方同时使用 pytest ``record_property`` 写入 JUnit。
    """
    try:
        for name, value in metadata.items():
            allure.dynamic.parameter(name, value)
    except Exception as exc:
        _log_reporter_failure("设置运行上下文元数据", exc)


def set_single_case_metadata(single_case: dict[str, Any]) -> None:
    """设置单接口用例的 Allure 元数据。

    参数说明:
        single_case: CaseLoader 返回的单接口用例，包含名称、API、case 和标签。

    返回值:
        无。元数据只影响报告展示。

    异常说明:
        Allure 写入异常会被记录并降级，不改变业务测试结果。
    """
    try:
        allure.dynamic.title(str(single_case["name"]))
        allure.dynamic.parent_suite("Gateway API 自动化")
        allure.dynamic.suite("单接口测试")
        allure.dynamic.feature(str(single_case["api_id"]))
        allure.dynamic.story(str(single_case["case_id"]))
        for tag in single_case.get("tags") or []:
            allure.dynamic.tag(str(tag))
    except Exception as exc:
        _log_reporter_failure("设置单接口元数据", exc)


def set_flow_metadata(flow_case: dict[str, Any]) -> None:
    """设置 Flow/Scenario 用例的 Allure 元数据。

    参数说明:
        flow_case: FlowLoader 返回的流程用例。

    返回值:
        无。标题优先使用 Scenario 名称，其次为 Flow 名称和 Flow ID。

    异常说明:
        Allure 写入异常会被记录并降级，不改变流程执行结果。
    """
    try:
        scenario = flow_case.get("scenario") or {}
        title = (
            scenario.get("name")
            or flow_case.get("name")
            or flow_case.get("id")
        )
        allure.dynamic.title(str(title))
        allure.dynamic.suite("多接口流程")
        allure.dynamic.feature(str(flow_case["id"]))
        for tag in flow_case.get("tags") or []:
            allure.dynamic.tag(str(tag))
    except Exception as exc:
        _log_reporter_failure("设置 Flow 元数据", exc)


@contextmanager
def step(title: str) -> Iterator[None]:
    """创建 Allure 步骤，并在报告不可用时退化为空上下文。

    参数说明:
        title: 报告中显示的步骤标题。

    返回值:
        可用于 ``with`` 的上下文管理器。

    异常说明:
        Allure 创建或关闭步骤失败时仅记录异常类型；测试体自身异常始终原样传播。
    """
    try:
        manager = allure.step(title)
        manager.__enter__()
    except Exception as exc:
        _log_reporter_failure("创建步骤", exc)
        yield
        return

    try:
        yield
    except BaseException as body_exc:
        # Reporter 关闭失败时仍优先保留原始业务异常及其 traceback。
        try:
            manager.__exit__(
                type(body_exc),
                body_exc,
                body_exc.__traceback__,
            )
        except Exception as exc:
            _log_reporter_failure("关闭失败步骤", exc)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            _log_reporter_failure("关闭步骤", exc)


def attach_json(name: str, data: Any) -> None:
    """附加中文友好的 JSON 数据。

    参数说明:
        name: 附件名称。
        data: 已由调用方完成脱敏的 JSON 兼容对象。

    返回值:
        无。

    异常说明:
        序列化或 Allure 写入失败时仅记录异常类型，不回退保存原始数据。
    """
    try:
        content = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        allure.attach(
            content,
            name=name,
            attachment_type=allure.attachment_type.JSON,
        )
    except Exception as exc:
        _log_reporter_failure("写入 JSON 附件", exc)


def attach_text(name: str, content: Any) -> None:
    """附加普通文本内容。

    参数说明:
        name: 附件名称。
        content: 调用方确认可安全写入报告的文本内容。

    返回值:
        无。

    异常说明:
        Allure 写入失败时仅记录异常类型，不回退保存原始数据。
    """
    try:
        allure.attach(
            str(content),
            name=name,
            attachment_type=allure.attachment_type.TEXT,
        )
    except Exception as exc:
        _log_reporter_failure("写入文本附件", exc)
