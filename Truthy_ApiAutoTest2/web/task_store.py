"""任务记录的文件级存储。

功能说明:
    任务记录保存为 ``tasks/<task_id>.json``；子进程标准输出保存为
    ``tasks/<task_id>/console.log``。写入使用同目录临时文件 +
    flush/fsync + ``os.replace`` 原子替换，保证并发轮询读取时不会看到
    半份 JSON。任务 ID 采用 ``YYYYMMDD-HHMMSS-<4位十六进制>``，
    天然按时间排序。
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shutil
import stat
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterable

# 任务 ID 格式：日期-时间-4 位十六进制随机后缀。
TASK_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")

# Web 首期只允许 1～9 张常见聊天截图。这里是服务端保护上限；执行 Flow
# 仍会使用 GetMediaUploadConfig 的实时响应做第二次业务约束校验。
MAX_TASK_INPUT_FILES = 9
# Dating 新版协议明确为十进制 7,000,000 字节，而不是 7 MiB
# （7 * 1024 * 1024）。这是 Web 接收层的保护上限；Flow 执行时仍会
# 使用 GetMediaUploadConfig 的实时值做第二次业务校验。
MAX_TASK_INPUT_BYTES = 7_000_000
_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class TaskInputError(ValueError):
    """表示任务输入文件数量、类型、大小或完整性不合法。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class _StoredInputSource:
    """重试复制时复用上传写入管线的内部文件对象。"""

    filename: str
    content_type: str
    stream: BinaryIO


def new_task_id(now: datetime | None = None) -> str:
    """生成一个新的任务 ID。

    参数说明:
        now: 可选当前时间；未提供时使用系统时间，测试可注入固定时间。

    返回值:
        形如 ``20260807-163012-a1b2`` 的任务 ID。
    """
    moment = now or datetime.now()
    return f"{moment.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def is_valid_task_id(task_id: str) -> bool:
    """判断任务 ID 是否符合格式，防止路径穿越。"""
    return bool(TASK_ID_PATTERN.match(task_id or ""))


class TaskStore:
    """负责任务 JSON 的原子读写、列表、保留策略与关联产物清理。

    参数说明:
        tasks_dir: 任务记录目录 ``tasks/``。
        reports_dir: 报告目录 ``reports/``，删除任务时同步清理任务 JUnit。
    """

    def __init__(self, tasks_dir: Path, reports_dir: Path) -> None:
        self._tasks_dir = Path(tasks_dir)
        self._reports_dir = Path(reports_dir)
        self._runtime_dir = self._tasks_dir.parent / "runtime"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tasks_dir(self) -> Path:
        """任务记录目录。"""
        return self._tasks_dir

    def record_path(self, task_id: str) -> Path:
        """返回任务 JSON 路径；ID 非法时抛出 ValueError。"""
        if not is_valid_task_id(task_id):
            raise ValueError(f"非法任务 ID: {task_id!r}")
        return self._tasks_dir / f"{task_id}.json"

    def console_dir(self, task_id: str, project_id: str | None = None) -> Path:
        """返回 console 目录；V2 使用 ``runtime/<project>/<task>`` 隔离。"""
        if not is_valid_task_id(task_id):
            raise ValueError(f"非法任务 ID: {task_id!r}")
        if project_id is not None:
            if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", project_id):
                raise ValueError(f"非法项目 ID: {project_id!r}")
            return self._runtime_dir / project_id / task_id
        return self._tasks_dir / task_id

    def console_log_path(
        self,
        task_id: str,
        project_id: str | None = None,
    ) -> Path:
        """返回任务 console.log 路径。"""
        return self.console_dir(task_id, project_id) / "console.log"

    def execution_asset_path(self, task_id: str, project_id: str) -> Path:
        """返回当前任务固定的私有执行资产路径。

        文件名不接受调用方输入，并复用 ``console_dir`` 对任务和项目 ID 的
        校验，避免浏览器或内部调用构造任意落盘位置。
        """

        return self.console_dir(task_id, project_id) / "execution-asset.json"

    def save_execution_asset(
        self,
        task_id: str,
        project_id: str,
        document: dict[str, Any],
    ) -> Path:
        """以 0600 原子写入 pytest 使用的不可变执行资产。

        Task JSON 保留完整历史快照；本文件只在子进程存活期间存在，因此与
        同目录的 console.log、图片输入具有不同清理时机。
        """

        path = self.execution_asset_path(task_id, project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_manifest(path, document)
        return path

    def cleanup_execution_asset(self, task_id: str, project_id: str) -> None:
        """只删除执行 JSON，不递归删除 console、图片或任务目录。"""

        self.execution_asset_path(task_id, project_id).unlink(missing_ok=True)

    def input_dir(self, task_id: str, project_id: str) -> Path:
        """返回 V2 任务私有输入目录，复用项目/任务路径安全校验。"""

        return self.console_dir(task_id, project_id) / "inputs"

    @staticmethod
    def _normalized_original_name(filename: Any) -> str:
        """仅保留展示用文件名，剥离 POSIX/Windows 路径片段。"""

        normalized = str(filename or "").replace("\\", "/")
        name = normalized.rsplit("/", 1)[-1].strip()
        if not name or name in {".", ".."}:
            raise TaskInputError("TASK_INPUT_TYPE_INVALID", "图片文件名不能为空")
        return name

    @staticmethod
    def _detected_image_type(prefix: bytes) -> str | None:
        """根据稳定文件头识别 JPEG/PNG/WebP，不信任扩展名或请求 Header。"""

        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if len(prefix) >= 12 and prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
            return "image/webp"
        return None

    @staticmethod
    def _upload_stream(upload: Any) -> BinaryIO:
        """取得 Flask FileStorage 或兼容上传对象的二进制流。"""

        stream = getattr(upload, "stream", upload)
        if not callable(getattr(stream, "read", None)):
            raise TaskInputError("TASK_INPUT_TYPE_INVALID", "图片上传对象无效")
        try:
            stream.seek(0)
        except (AttributeError, OSError):
            # 网络流不一定可 seek；新上传通常从当前位置 0 开始，继续流式读取。
            pass
        return stream

    def _write_manifest(
        self,
        manifest_path: Path,
        document: dict[str, Any],
    ) -> None:
        """以 0600 + 原子替换写入任务输入清单。"""

        temporary = manifest_path.with_name(".manifest.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(document, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, manifest_path)
            manifest_path.chmod(0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def save_inputs(
        self,
        task_id: str,
        project_id: str,
        uploads: Iterable[Any],
    ) -> tuple[list[dict[str, Any]], str]:
        """校验并持久化一次任务的图片输入。

        参数说明:
            task_id/project_id: 已通过任务与项目格式校验的目标边界。
            uploads: Flask ``FileStorage`` 或提供 filename/content_type/read 的
                兼容对象，顺序即后续 Analysis 的图片顺序。

        返回值:
            ``(附件元数据列表, manifest 项目相对路径)``。

        异常说明:
            TaskInputError: 数量、真实文件类型、声明 MIME、大小或流无效。
            OSError: 文件系统错误原样透传；本方法会先清理半成品输入目录。
        """

        items = list(uploads)
        if not 1 <= len(items) <= MAX_TASK_INPUT_FILES:
            raise TaskInputError(
                "TASK_INPUT_COUNT_INVALID",
                f"图片数量必须为 1～{MAX_TASK_INPUT_FILES} 张",
            )

        input_directory = self.input_dir(task_id, project_id)
        if input_directory.exists():
            raise TaskInputError("TASK_INPUTS_MISSING", "任务输入目录已存在")
        input_directory.mkdir(parents=True, mode=0o700)
        input_directory.chmod(0o700)
        metadata: list[dict[str, Any]] = []
        try:
            for order, upload in enumerate(items, start=1):
                original_name = self._normalized_original_name(
                    getattr(upload, "filename", None)
                )
                declared_type = str(
                    getattr(upload, "content_type", "") or ""
                ).split(";", 1)[0].strip().lower()
                if declared_type not in _IMAGE_EXTENSIONS:
                    raise TaskInputError(
                        "TASK_INPUT_TYPE_INVALID",
                        f"图片 {original_name} 的类型不支持: {declared_type or 'unknown'}",
                    )

                stream = self._upload_stream(upload)
                temporary = input_directory / f".{order:03d}.uploading"
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                digest = hashlib.sha256()
                size_bytes = 0
                prefix = b""
                try:
                    with os.fdopen(descriptor, "wb") as file:
                        while True:
                            chunk = stream.read(64 * 1024)
                            if not chunk:
                                break
                            if not isinstance(chunk, bytes):
                                raise TaskInputError(
                                    "TASK_INPUT_TYPE_INVALID",
                                    f"图片 {original_name} 不是二进制文件",
                                )
                            if len(prefix) < 16:
                                prefix += chunk[: 16 - len(prefix)]
                            size_bytes += len(chunk)
                            if size_bytes > MAX_TASK_INPUT_BYTES:
                                raise TaskInputError(
                                    "TASK_INPUT_TOO_LARGE",
                                    f"图片 {original_name} 超过 7,000,000 字节",
                                )
                            digest.update(chunk)
                            file.write(chunk)
                        file.flush()
                        os.fsync(file.fileno())

                    detected_type = self._detected_image_type(prefix)
                    if detected_type is None or detected_type != declared_type:
                        raise TaskInputError(
                            "TASK_INPUT_TYPE_INVALID",
                            f"图片 {original_name} 的文件内容与声明类型不一致",
                        )
                    sha256 = digest.hexdigest()
                    safe_name = (
                        f"{order:03d}-{sha256[:12]}{_IMAGE_EXTENSIONS[detected_type]}"
                    )
                    final_path = input_directory / safe_name
                    os.replace(temporary, final_path)
                    final_path.chmod(0o600)
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise

                task_relative_path = final_path.relative_to(
                    self._runtime_dir.parent
                ).as_posix()
                metadata.append(
                    {
                        "order": order,
                        "original_name": original_name,
                        "safe_name": safe_name,
                        "content_type": detected_type,
                        "size_bytes": size_bytes,
                        "sha256": sha256,
                        # manifest 内只需相对 inputs/ 的受控文件名；任务 JSON
                        # 同时保留项目根相对路径，便于详情与重试定位且不泄露绝对路径。
                        "relative_path": safe_name,
                        "task_relative_path": task_relative_path,
                    }
                )

            manifest_path = input_directory / "manifest.json"
            self._write_manifest(
                manifest_path,
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "task_id": task_id,
                    "media_files": metadata,
                },
            )
            return metadata, manifest_path.relative_to(
                self._runtime_dir.parent
            ).as_posix()
        except Exception:
            self.cleanup_inputs(task_id, project_id)
            raise

    def cleanup_inputs(self, task_id: str, project_id: str) -> None:
        """仅清理当前任务 inputs；父任务目录为空时再安全移除。"""

        input_directory = self.input_dir(task_id, project_id)
        if input_directory.is_dir():
            shutil.rmtree(input_directory, ignore_errors=True)
        task_directory = self.console_dir(task_id, project_id)
        try:
            task_directory.rmdir()
        except (FileNotFoundError, OSError):
            # console/snapshot 已存在时必须保留父目录，只移除本次半成品输入。
            pass

    def clone_inputs(
        self,
        source_record: dict[str, Any],
        target_task_id: str,
        target_project_id: str,
    ) -> tuple[list[dict[str, Any]], str] | None:
        """校验源任务附件完整性并复制到新任务私有目录。

        返回 ``None`` 表示源任务没有附件。任何缺失、越界、大小或摘要不匹配
        都统一抛 ``TASK_INPUTS_MISSING``，避免重试静默使用错误图片。
        """

        attachments = source_record.get("attachments")
        if not attachments:
            return None
        if not isinstance(attachments, list):
            raise TaskInputError("TASK_INPUTS_MISSING", "原任务输入清单无效")
        source_project = source_record.get("project")
        source_project_id = (
            str(source_project.get("project_id") or "")
            if isinstance(source_project, dict)
            else ""
        )
        source_task_id = str(source_record.get("id") or "")
        source_directory = self.input_dir(source_task_id, source_project_id)
        if source_directory.is_symlink():
            raise TaskInputError("TASK_INPUTS_MISSING", "原任务输入目录不能是符号链接")
        source_boundary = source_directory.resolve()

        with ExitStack() as stack:
            uploads: list[_StoredInputSource] = []
            for item in attachments:
                if not isinstance(item, dict):
                    raise TaskInputError("TASK_INPUTS_MISSING", "原任务输入元数据无效")
                relative = str(item.get("task_relative_path") or "")
                candidate = self._runtime_dir.parent / relative
                # ``resolve`` 会抹掉最终路径的 symlink 身份，因此必须先在原始
                # 路径上拒绝。即使链接目标仍位于当前 inputs 内，也不能把任务
                # 执行输入从不可变普通文件悄悄换成可重定向的链接。
                if candidate.is_symlink():
                    raise TaskInputError(
                        "TASK_INPUTS_MISSING", "原任务图片不能是符号链接"
                    )
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(source_boundary)
                except (FileNotFoundError, OSError, ValueError) as exc:
                    raise TaskInputError(
                        "TASK_INPUTS_MISSING", "原任务图片缺失或路径无效"
                    ) from exc
                if not resolved.is_file():
                    raise TaskInputError("TASK_INPUTS_MISSING", "原任务图片不是普通文件")
                try:
                    descriptor = os.open(
                        resolved,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    )
                    stream = stack.enter_context(os.fdopen(descriptor, "rb"))
                    file_stat = os.fstat(stream.fileno())
                    if not stat.S_ISREG(file_stat.st_mode):
                        raise TaskInputError(
                            "TASK_INPUTS_MISSING", "原任务图片不是普通文件"
                        )
                    size_bytes = file_stat.st_size
                except OSError as exc:
                    raise TaskInputError("TASK_INPUTS_MISSING", "无法读取原任务图片") from exc
                # 先比较大小再流式计算摘要，篡改为超大文件时不会一次性读入内存。
                if size_bytes != item.get("size_bytes"):
                    raise TaskInputError("TASK_INPUTS_MISSING", "原任务图片完整性校验失败")
                digest = hashlib.sha256()
                while True:
                    chunk = stream.read(64 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                if digest.hexdigest() != item.get("sha256"):
                    raise TaskInputError("TASK_INPUTS_MISSING", "原任务图片完整性校验失败")
                stream.seek(0)
                uploads.append(
                    _StoredInputSource(
                        filename=str(item.get("original_name") or resolved.name),
                        content_type=str(item.get("content_type") or ""),
                        stream=stream,
                    )
                )
            return self.save_inputs(target_task_id, target_project_id, uploads)

    def save(self, record: dict[str, Any]) -> None:
        """原子写入一条任务记录。

        功能说明:
            先写同目录临时文件，flush/fsync 后用 ``os.replace`` 替换正式
            文件，确保任何时刻读取方看到的都是完整 JSON。

        参数说明:
            record: 任务记录字典，必须包含合法 ``id``。

        异常说明:
            ValueError: 记录缺少合法 ID 时抛出。
            OSError: 磁盘写入失败时由底层文件操作透传。
        """
        task_id = record.get("id", "")
        final_path = self.record_path(task_id)
        tmp_path = final_path.with_name(f".{task_id}.tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, final_path)

    def load(self, task_id: str) -> dict[str, Any] | None:
        """读取一条任务记录；不存在时返回 None。"""
        path = self.record_path(task_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        """返回全部任务记录，按 ID 倒序（最新在前）。

        功能说明:
            ID 前缀为时间戳，字典序倒排即时间倒序。损坏或临时文件跳过。
        """
        records: list[dict[str, Any]] = []
        for path in self._tasks_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                # 并发清理或异常残留不应阻断列表接口，跳过即可。
                continue
        records.sort(key=lambda item: item.get("id", ""), reverse=True)
        return records

    def delete(self, task_id: str) -> bool:
        """删除任务记录及其 console、JUnit 与任务专属报告目录。

        返回值:
            记录存在并完成删除返回 True；记录不存在返回 False。
        """
        path = self.record_path(task_id)
        record = self.load(task_id)
        if record is None and not path.exists():
            return False

        project = record.get("project") if isinstance(record, dict) else None
        project_id = project.get("project_id") if isinstance(project, dict) else None
        junit_file = record.get("junit_file") if isinstance(record, dict) else None
        # V2 使用记录内相对路径定位；历史记录继续识别旧文件名。
        junit_path = (
            self._reports_dir.parent / str(junit_file)
            if junit_file
            else self._reports_dir / f"junit-task-{task_id}.xml"
        )
        if junit_path.is_file():
            junit_path.unlink()
        # 报告以根任务 ID 作为物理隔离边界；任务因保留策略或人工操作被
        # 删除后，同步移除不可再授权访问的报告，避免产生永久孤儿产物。
        task_report_directory = self._reports_dir / "task-reports"
        if project_id:
            task_report_directory = task_report_directory / str(project_id)
        task_report_directory = task_report_directory / task_id
        if task_report_directory.is_dir():
            shutil.rmtree(task_report_directory, ignore_errors=True)
        console_directory = self.console_dir(task_id, str(project_id) if project_id else None)
        if console_directory.is_dir():
            shutil.rmtree(console_directory, ignore_errors=True)
        if path.is_file():
            path.unlink()
        return True

    def enforce_retention(self, retain: int) -> list[str]:
        """按保留条数清理最旧的任务记录。

        参数说明:
            retain: 保留条数上限，必须为正整数。

        返回值:
            被删除的任务 ID 列表（最新在前顺序中超出部分）。
        """
        if retain < 1:
            raise ValueError(f"保留条数必须为正整数，实际值: {retain}")
        # pending/running 是调度状态而不是历史记录；无论其创建时间多早都
        # 不能被 Retention 删除，否则队列会静默丢任务。保留上限只作用于
        # 已经不可再迁移的终态记录。
        records = [
            record
            for record in self.list()
            if record.get("status") in {"succeeded", "failed", "cancelled"}
        ]
        removed: list[str] = []
        for record in records[retain:]:
            task_id = record.get("id", "")
            if is_valid_task_id(task_id) and self.delete(task_id):
                removed.append(task_id)
        return removed
