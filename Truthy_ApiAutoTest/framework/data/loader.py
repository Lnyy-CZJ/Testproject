"""YAML/JSON 测试数据加载与自动失效缓存。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class _CaseData(BaseModel):
    """测试数据文件中单条用例的最小结构。"""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    markers: list[str]
    steps: list[Any]
    expected: dict[str, Any]


_CACHE: dict[Path, tuple[tuple[int, int], list[dict[str, Any]]]] = {}


def clear_case_data_cache() -> None:
    """清空进程内测试数据缓存。

    功能说明:
        清除当前进程的 YAML/JSON 用例数据缓存。
    参数说明:
        无。
    返回值:
        无，主要用于测试隔离或显式释放缓存。
    异常说明:
        本函数不主动抛出异常。
    """
    _CACHE.clear()


def load_case_data(path: str | Path) -> list[dict[str, Any]]:
    """加载并校验 YAML 或 JSON 测试数据。

    功能说明:
        以绝对路径、纳秒修改时间和文件大小为缓存签名；文件变化后自动重新读取。
    参数说明:
        path: ``.yaml/.yml/.json`` 用例文件路径，根结构可为列表或含 ``cases`` 的对象。
    返回值:
        经过结构校验的字典列表；每次返回深拷贝，防止调用方污染缓存。
    异常说明:
        文件类型不支持、根结构错误或必需字段缺失时抛出 ``ValueError``；读取失败原样抛出。
    """
    resolved = Path(path).resolve()
    stat = resolved.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(resolved)
    if cached is not None and cached[0] == signature:
        return copy.deepcopy(cached[1])

    suffix = resolved.suffix.lower()
    raw_text = resolved.read_text(encoding="utf-8")
    if suffix == ".json":
        raw = json.loads(raw_text)
    elif suffix in {".yaml", ".yml"}:
        raw = yaml.safe_load(raw_text)
    else:
        raise ValueError(f"不支持的测试数据格式: {suffix}")

    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list):
        raise ValueError(f"测试数据根结构必须是列表或包含 cases 列表: {resolved}")
    try:
        validated = [_CaseData.model_validate(case).model_dump() for case in cases]
    except (ValidationError, TypeError) as exc:
        raise ValueError(f"测试数据结构无效: {resolved}: {exc}") from exc

    _CACHE[resolved] = (signature, validated)
    return copy.deepcopy(validated)
