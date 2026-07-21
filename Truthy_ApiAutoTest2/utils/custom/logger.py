"""项目日志初始化工具。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


def configure_logging(
    level: int | str = logging.INFO,
    log_directory: str | Path | None = None,
    env: str = "test",
    console: bool = True,
    file: bool = False,
) -> Path | None:
    """初始化终端与文件日志。

    参数说明:
        level: Python logging 日志级别或名称。
        log_directory: 日志目录；启用文件日志时必须提供。
        env: 当前运行环境，用于日志文件名。
        console: 是否输出到终端。
        file: 是否输出到日志文件。

    返回值:
        创建的日志文件路径；未启用文件日志时返回 None。

    异常说明:
        ValueError: 日志级别无效或启用文件日志但未提供目录时抛出。
    """
    if isinstance(level, str):
        resolved_level = getattr(logging, level.upper(), None)
        if not isinstance(resolved_level, int):
            raise ValueError(f"不支持的日志级别: {level}")
    else:
        resolved_level = level

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    # 只清理由本模块创建的 Handler，保留 pytest 的日志捕获 Handler。
    for handler in list(root_logger.handlers):
        if getattr(handler, "_truthy_managed", False):
            root_logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler._truthy_managed = True  # type: ignore[attr-defined]
        root_logger.addHandler(console_handler)

    log_path: Path | None = None
    if file:
        if log_directory is None:
            raise ValueError("启用文件日志时必须配置 log_directory")
        directory = Path(log_directory)
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_env = "".join(char for char in env if char.isalnum() or char in "-_")
        log_path = directory / f"{timestamp}_{safe_env}_{os.getpid()}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._truthy_managed = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)
    return log_path


def get_logger(name: str) -> logging.Logger:
    """按模块名称返回标准 Logger，不维护额外全局状态。"""
    return logging.getLogger(name)
