"""生成可追溯且不重复的自动化测试数据。"""

import re
from uuid import uuid4


def _safe_part(value: str) -> str:
    """将标识片段限制为字母、数字、点、下划线和短横线。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "unknown"


def _suffix() -> str:
    """返回短随机后缀，降低并行构造数据时的冲突概率。"""
    return uuid4().hex[:16]


def build_client_request_id(build_no: str, case_id: str) -> str:
    """构造一次业务调用使用的幂等请求 ID。

    功能说明:
        生成可追溯且适合在同一次网络重试中复用的幂等 ID。
    参数说明:
        build_no: CI 构建号或本地运行标识。
        case_id: 测试用例编号。
    返回值:
        带来源前缀及随机后缀的请求 ID；调用方应在网络重试中复用该值。
    异常说明:
        本函数不主动抛出异常。
    """
    return f"autotest-{_safe_part(build_no)}-{_safe_part(case_id)}-{_suffix()}"


def build_device_id(build_no: str) -> str:
    """构造本次测试运行使用的设备 ID。

    功能说明:
        生成带自动化前缀的唯一设备 ID。
    参数说明:
        build_no: CI 构建号或本地运行标识。
    返回值:
        带 ``autotest-device`` 前缀的唯一设备 ID。
    异常说明:
        本函数不主动抛出异常。
    """
    return f"autotest-device-{_safe_part(build_no)}-{_suffix()}"


def build_unique_name(build_no: str, case_id: str) -> str:
    """构造便于服务端筛选和人工追溯的测试名称。

    功能说明:
        生成便于服务端筛选和人工追溯的唯一测试名称。
    参数说明:
        build_no: CI 构建号或本地运行标识。
        case_id: 测试用例编号。
    返回值:
        带 ``autotest`` 前缀的唯一名称。
    异常说明:
        本函数不主动抛出异常。
    """
    return f"autotest-{_safe_part(build_no)}-{_safe_part(case_id)}-{_suffix()}"
