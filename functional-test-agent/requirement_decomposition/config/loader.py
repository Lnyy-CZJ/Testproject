"""配置文件加载器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from requirement_decomposition.models.schema import DecompositionConfig, SourceConfig


def load_config(config_path: str, source_path: str | None = None) -> DecompositionConfig:
    """加载 YAML 配置，并在调用方传入 source_path 时覆盖第一个来源。

    这样可以保留配置文件中的项目和输出设置，同时允许命令式入口直接指定
    当前要拆解的 PRD 文件。
    """

    config_file = Path(config_path).expanduser().resolve()
    raw_config = _read_yaml(config_file)

    raw_config["sources"] = _normalize_sources(raw_config.get("sources", []))

    if source_path:
        raw_config["sources"] = _merge_source_path(raw_config["sources"], source_path)

    config = DecompositionConfig.model_validate(raw_config)
    if not config.sources:
        raise ValueError("配置中至少需要一个 sources，或调用时传入 source_path")
    return config


def _read_yaml(config_file: Path) -> dict[str, Any]:
    """读取 YAML 文件，空文件按空配置处理。"""

    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_file}")

    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("配置文件顶层必须是对象")
    return data


def _normalize_sources(sources: object) -> list[dict[str, Any]]:
    """兼容 sources 写成单个对象或对象数组两种 YAML 形态。"""

    if isinstance(sources, dict):
        return [sources]
    if isinstance(sources, list):
        return sources
    if sources in (None, ""):
        return []
    raise ValueError("配置字段 sources 必须是对象数组，或单个 source 对象")


def _merge_source_path(sources: list[dict[str, Any]], source_path: str) -> list[dict[str, Any]]:
    """将显式 source_path 合并到 sources 中。"""

    if sources:
        merged = dict(sources[0])
        merged["path"] = source_path
        return [merged, *sources[1:]]

    return [SourceConfig(path=source_path).model_dump()]
