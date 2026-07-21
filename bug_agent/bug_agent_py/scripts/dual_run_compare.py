"""
Go/Python 双跑响应比较工具

功能说明:
    用于灰度上线前比较 Go 版和 Python 版关键接口响应结构是否兼容。
    默认忽略时间戳、traceId 等易变字段，避免误报。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VOLATILE_KEYS = {
    "createdAt",
    "updatedAt",
    "firstSeenAt",
    "lastSeenAt",
    "created_at",
    "updated_at",
    "traceId",
    "requestId",
}


@dataclass(frozen=True)
class CompareResult:
    """
    双跑比较结果。

    参数说明:
        compatible: 是否兼容。
        differences: 差异路径列表。
    """

    compatible: bool
    differences: list[str] = field(default_factory=list)


def normalize_response(value: Any, ignored_keys: set[str] | None = None) -> Any:
    """
    归一化响应，移除易变字段。

    参数说明:
        value: 任意 JSON 可序列化对象。
        ignored_keys: 需要忽略的字段名集合。

    返回值:
        Any: 去除易变字段后的结构。
    """
    ignored = ignored_keys or VOLATILE_KEYS
    if isinstance(value, dict):
        return {
            key: normalize_response(item, ignored)
            for key, item in sorted(value.items())
            if key not in ignored
        }
    if isinstance(value, list):
        return [normalize_response(item, ignored) for item in value]
    return value


def compare_response_pair(go_response: Any, python_response: Any) -> CompareResult:
    """
    比较一组 Go/Python JSON 响应。

    返回值:
        CompareResult: 兼容状态和差异路径。
    """
    go_normalized = normalize_response(go_response)
    py_normalized = normalize_response(python_response)
    differences: list[str] = []
    _collect_differences(go_normalized, py_normalized, "", differences)
    return CompareResult(compatible=not differences, differences=differences)


def _collect_differences(left: Any, right: Any, path: str, differences: list[str]) -> None:
    """递归收集结构差异"""
    current_path = path or "$"
    if type(left) is not type(right):
        differences.append(f"{current_path}: type {type(left).__name__} != {type(right).__name__}")
        return

    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(left_keys - right_keys):
            differences.append(f"{_join_path(path, key)}: missing in python")
        for key in sorted(right_keys - left_keys):
            differences.append(f"{_join_path(path, key)}: extra in python")
        for key in sorted(left_keys & right_keys):
            _collect_differences(left[key], right[key], _join_path(path, key), differences)
        return

    if isinstance(left, list):
        if len(left) != len(right):
            differences.append(f"{current_path}: length {len(left)} != {len(right)}")
            return
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            _collect_differences(left_item, right_item, f"{current_path}[{index}]", differences)
        return

    if left != right:
        differences.append(f"{current_path}: {left!r} != {right!r}")


def _join_path(prefix: str, key: str) -> str:
    """拼接差异路径"""
    if not prefix:
        return key
    return f"{prefix}.{key}"


def _load_json(path: Path) -> Any:
    """读取 JSON 文件"""
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    """
    命令行入口。

    用法:
        python3 scripts/dual_run_compare.py --go go.json --python py.json
    """
    parser = argparse.ArgumentParser(description="Compare Go/Python API JSON responses")
    parser.add_argument("--go", required=True, type=Path, help="Go response JSON file")
    parser.add_argument("--python", required=True, type=Path, help="Python response JSON file")
    args = parser.parse_args()

    result = compare_response_pair(_load_json(args.go), _load_json(args.python))
    print(json.dumps({"compatible": result.compatible, "differences": result.differences}, ensure_ascii=False))
    return 0 if result.compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
