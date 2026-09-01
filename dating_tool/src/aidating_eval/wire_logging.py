"""面向本地联调的原始 HTTP Wire Log。

这个模块与 ``artifacts`` 的安全摘要用途不同：Wire Log 的目标是复现一次真实网络交换，
因此按用户的明确要求保留请求头、凭据、正文、签名 URL、模型结果与二进制内容，不执行
任何脱敏或字段裁剪。日志只能用于个人本地排障，禁止提交、分享或作为测试报告上传。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import Enum
import base64
import json
import os
from pathlib import Path
import stat
import threading
from typing import Any
from uuid import uuid4


def _json_default(value: object) -> object:
    """为少量非 JSON 原生类型提供无损或可诊断的序列化表示。"""

    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return repr(value)


class RawWireLogger:
    """把一次 CLI 网络链路追加为线程安全的 JSON Lines 文件。

    ``write`` 在单个进程内由锁保护，保证 Eval 并发 Worker 不会把两条 JSON 记录交叉写坏。
    每次写入重新以 append 模式打开文件，避免长期持有句柄影响 SIGINT/SIGTERM 后查看日志。
    """

    def __init__(
        self,
        path: Path,
        *,
        now_fn: Callable[[], datetime] | None = None,
        expected_identity: tuple[int, int, int] | None = None,
        failure_type: str | None = None,
    ) -> None:
        self.path = path
        self._now_fn = now_fn or (lambda: datetime.now().astimezone())
        self._lock = threading.Lock()
        self._sequence = 0
        self._expected_identity = expected_identity
        self._failure_type = failure_type

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        now_fn: Callable[[], datetime] | None = None,
        pid: int | None = None,
    ) -> "RawWireLogger":
        """按本地日期和微秒时间创建权限为 ``0600`` 的唯一日志文件。

        Args:
            root: 日志根目录，默认由 CLI 传入 ``logs``。
            now_fn: 测试用时钟；未提供时使用带本地时区的当前时间。
            pid: 测试可固定的进程号；未提供时读取当前 PID。

        Returns:
            已经创建好目标文件的 logger。

        Raises:
            OSError: 目录或日志文件无法创建，或极小概率下文件名发生碰撞。
        """

        clock = now_fn or (lambda: datetime.now().astimezone())
        now = clock()
        if now.tzinfo is None:
            # 朴素时间只允许测试注入；按运行机器本地时区解释，保证目录仍符合用户视角。
            now = now.astimezone()
        root = Path(root)
        daily_dir = root / now.strftime("%Y-%m-%d")
        process_id = os.getpid() if pid is None else pid
        filename = f"{now:%Y%m%d_%H%M%S_%f}_test_{process_id}.log"
        path = daily_dir / filename
        descriptor: int | None = None
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(root, 0o700)
            daily_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(daily_dir, 0o700)
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.fchmod(descriptor, 0o600)
            info = os.fstat(descriptor)
            expected_identity = (info.st_dev, info.st_ino, info.st_uid)
        except Exception as exc:
            # 日志目录不可用不能阻断 doctor/run/cleanup 的真实业务与清理流程。
            return cls(
                path,
                now_fn=clock,
                failure_type=type(exc).__name__,
            )
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return cls(
            path,
            now_fn=clock,
            expected_identity=expected_identity,
        )

    @staticmethod
    def new_exchange_id() -> str:
        """生成请求与响应/异常之间的关联标识，支持并发链路重建。"""

        return uuid4().hex

    def write(self, event: str, **fields: Any) -> None:
        """原样追加事件；写入失败后永久降级，但不干扰远端 Task 清理。

        文件仅在 ``create`` 中使用 ``O_EXCL`` 创建。这里故意不使用普通 ``open('a')``：若
        文件被外部删除，append 会按进程 umask 静默重建，可能把完整凭据写进 ``0644``
        文件。任何序列化或 I/O 错误都会记录为内存状态，后续写入直接跳过。
        """

        with self._lock:
            if self._failure_type is not None:
                return
            self._sequence += 1
            try:
                timestamp = self._now_fn()
                if timestamp.tzinfo is None:
                    timestamp = timestamp.astimezone()
                record = {
                    "sequence": self._sequence,
                    "timestamp": timestamp.isoformat(timespec="microseconds"),
                    "process_id": os.getpid(),
                    "thread_name": threading.current_thread().name,
                    "event": event,
                    **fields,
                }
                line = json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=_json_default,
                )
                flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.path, flags)
                try:
                    info = os.fstat(descriptor)
                    identity = (info.st_dev, info.st_ino, info.st_uid)
                    mode = stat.S_IMODE(info.st_mode)
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or mode != 0o600
                        or identity != self._expected_identity
                    ):
                        raise PermissionError("WIRE_LOG_FILE_CHANGED")
                    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                        descriptor = -1
                        stream.write(line)
                        stream.write("\n")
                finally:
                    if descriptor >= 0:
                        os.close(descriptor)
            except Exception as exc:  # 日志不得覆盖已经发生的网络业务结果。
                self._failure_type = type(exc).__name__

    @property
    def failure_type(self) -> str | None:
        """返回首个日志降级错误类型；不包含可能带敏感路径的异常正文。"""

        with self._lock:
            return self._failure_type
