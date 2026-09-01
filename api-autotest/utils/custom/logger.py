"""项目日志初始化工具。"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path


LOG_RETENTION_DAYS = 7


def _clean_expired_log_directories(
    log_root: Path,
    current_date: date,
) -> None:
    """删除超过保留期的日期日志目录。

    参数说明:
        log_root: 日志根目录，仅扫描其下一层子目录。
        current_date: 当前日志日期，用于计算保留边界。

    返回值:
        无。仅删除名称为 ``YYYY-MM-DD`` 且早于保留边界的目录。

    异常说明:
        OSError: 过期目录无法删除时由 ``shutil.rmtree`` 透传，避免静默保留
            可能持续增长的旧日志。
    """
    retention_boundary = current_date - timedelta(days=LOG_RETENTION_DAYS)
    for child in log_root.iterdir():
        if not child.is_dir():
            continue
        try:
            directory_date = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            # 非框架生成的目录不属于日志保留策略，保持原样。
            continue
        if directory_date < retention_boundary:
            shutil.rmtree(child)


def _prepare_daily_log_directory(
    log_root: Path,
    current_time: datetime,
) -> Path:
    """创建当天日志目录，并在首次创建时清理过期日志目录。

    参数说明:
        log_root: 配置的日志根目录，例如项目根目录下的 ``logs``。
        current_time: 本次初始化使用的当前时间，测试可注入固定时间。

    返回值:
        当前日期对应的日志目录，格式为 ``logs/YYYY-MM-DD``。

    异常说明:
        OSError: 目录创建、扫描或过期目录删除失败时抛出。
    """
    log_root.mkdir(parents=True, exist_ok=True)
    daily_directory = log_root / current_time.strftime("%Y-%m-%d")
    is_first_creation = not daily_directory.exists()
    daily_directory.mkdir(parents=True, exist_ok=True)
    if is_first_creation:
        _clean_expired_log_directories(log_root, current_time.date())
    return daily_directory


def configure_logging(
    level: int | str = logging.INFO,
    log_directory: str | Path | None = None,
    env: str = "test",
    console: bool = True,
    file: bool = False,
    now: datetime | None = None,
) -> Path | None:
    """初始化终端与文件日志。

    参数说明:
        level: Python logging 日志级别或名称。
        log_directory: 日志目录；启用文件日志时必须提供。
        env: 当前运行环境，用于日志文件名；当运行环境同时提供
            ``API_AUTOTEST_TASK_ID`` 时，文件名会追加平台任务 ID，便于任务记录
            精确定位本次业务日志。
        console: 是否输出到终端。
        file: 是否输出到日志文件。
        now: 可选当前时间；未提供时使用系统时间，主要用于稳定测试日期目录和
            日志保留行为。

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
        current_time = now or datetime.now()
        directory = _prepare_daily_log_directory(
            Path(log_directory),
            current_time,
        )
        timestamp = current_time.strftime("%Y%m%d_%H%M%S_%f")
        safe_env = "".join(char for char in env if char.isalnum() or char in "-_")
        task_id = os.getenv("API_AUTOTEST_TASK_ID")
        if task_id:
            # 平台任务 ID 由任务运行器生成并已遵循固定安全格式；此处保留原值，
            # 仅把它加入文件名，不增加任务目录，也不改变业务日志内容。
            filename = f"{timestamp}_{safe_env}_{task_id}_{os.getpid()}.log"
        else:
            # CLI 等非平台入口继续使用历史命名，避免影响既有日志消费方。
            filename = f"{timestamp}_{safe_env}_{os.getpid()}.log"
        log_path = directory / filename
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._truthy_managed = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)
    return log_path


def get_logger(name: str) -> logging.Logger:
    """按模块名称返回标准 Logger，不维护额外全局状态。"""
    return logging.getLogger(name)
