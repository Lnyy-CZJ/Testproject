"""壳服务日志文本兼容与显示长度控制。

产品当前要求接口自动化工具的所有日志、报告附件和失败摘要保留原文。本模块
继续保留历史 ``redact_text`` 入口，避免调用方与插件接口断裂，但只负责限制
超长响应，不再替换 Header、Token、Cookie、签名 URL 或本机路径。
"""

from __future__ import annotations

from pathlib import Path

# Web 日志与错误展示的默认长度，避免一次响应加载无限量历史输出。
DEFAULT_MAX_LENGTH = 2000

# 任务列表和 JUnit 失败摘要的单条显示上限。
FAILED_MESSAGE_LIMIT = 500

# 截断标注后缀；计入总长度，保证输出不超过 max_length。
_TRUNCATION_SUFFIX = "...(truncated)"


def redact_text(
    text: str,
    project_root: Path | None = None,
    max_length: int | None = DEFAULT_MAX_LENGTH,
) -> str:
    """返回原始文本，并按需要截断过长内容。

    参数说明:
        text: 待展示的日志、异常或报告文本。
        project_root: 历史兼容参数；不再用于替换绝对路径。
        max_length: 截断上限；``None`` 表示完整返回。

    返回值:
        未脱敏的原始文本；超过上限时保留前缀并追加截断标记。

    设计说明:
        函数名因既有调用契约继续保留。显式忽略 ``project_root``，确保主目录和
        容器路径均可用于直接定位失败位置。
    """
    del project_root
    if not text:
        return ""
    if max_length is None or len(text) <= max_length:
        return text
    keep = max(max_length - len(_TRUNCATION_SUFFIX), 0)
    return text[:keep] + _TRUNCATION_SUFFIX


def truncate_tail(text: str, max_length: int | None) -> str:
    """保留原始文本的最新尾部，并在超限时标记前段已省略。

    参数说明:
        text: 已按行数选出的日志或异常原文。
        max_length: 最大字符数；``None`` 表示完整返回。

    返回值:
        未超限时逐字返回；超限时返回截断标记和最后 ``max_length`` 范围内的
        原文。该方向用于日志尾部和失败摘要，确保最终异常不会因限长丢失。
    """
    if not text:
        return ""
    if max_length is None or len(text) <= max_length:
        return text
    keep = max(max_length - len(_TRUNCATION_SUFFIX), 0)
    return _TRUNCATION_SUFFIX[:max_length] + (text[-keep:] if keep else "")
