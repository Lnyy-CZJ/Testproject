"""上传文档和 Review JSON 的安全校验。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import BinaryIO

from services.common.errors import INVALID_INPUT, REVIEW_FILE_INVALID, ServiceError


FUNCTIONAL_EXTENSIONS = frozenset({".md", ".txt"})
MIME_BY_EXTENSION = {
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".json": {"application/json", "text/json", "text/plain", "application/octet-stream"},
}


def _safe_extension(filename: str, allowed: frozenset[str]) -> str:
    """只接受纯文件名和允许的最终扩展名。"""

    if not filename or "\x00" in filename or Path(filename).name != filename or any(part in filename for part in ("/", "\\", "..")):
        raise ServiceError(422, INVALID_INPUT, "上传文件名不合法")
    extension = Path(filename).suffix.lower()
    if extension not in allowed:
        raise ServiceError(422, "UNSUPPORTED_DOCUMENT", "当前文件类型不受支持")
    return extension


def read_validated_text(
    stream: BinaryIO,
    *,
    filename: str,
    mimetype: str,
    allowed_extensions: frozenset[str],
    max_bytes: int = 5 * 1024 * 1024,
    max_characters: int = 500_000,
) -> tuple[bytes, str, str]:
    """读取并校验文本上传。

    返回值:
        原始字节、UTF-8 文本、规范化扩展名。
    异常说明:
        空文件、超限、非 UTF-8、MIME 或 JSON/YAML 语法不匹配时抛出 ServiceError。
    """

    extension = _safe_extension(filename, allowed_extensions)
    normalized_mime = (mimetype or "application/octet-stream").split(";", 1)[0].strip().lower()
    if normalized_mime not in MIME_BY_EXTENSION[extension]:
        raise ServiceError(422, INVALID_INPUT, "文件 MIME 类型与扩展名不匹配")
    data = stream.read(max_bytes + 1)
    if not data:
        raise ServiceError(422, INVALID_INPUT, "上传文件不能为空")
    if len(data) > max_bytes:
        raise ServiceError(413, INVALID_INPUT, "上传文件超过大小上限")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ServiceError(422, INVALID_INPUT, "文件必须使用 UTF-8 编码") from None
    if len(text) > max_characters:
        raise ServiceError(413, INVALID_INPUT, "文档字符数超过上限")
    if extension == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            raise ServiceError(422, INVALID_INPUT, "JSON 文档语法不正确") from None
    return data, text, extension


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """把已校验字节原子写入任务目录。"""

    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # 某些文件系统不支持目录 fsync；文件本身仍已原子发布。
            pass
    finally:
        temporary.unlink(missing_ok=True)


def validate_review_json(text: str, *, max_points: int = 5_000) -> list[dict]:
    """校验功能测试点 Review 文件并返回规范化列表。"""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise ServiceError(422, REVIEW_FILE_INVALID, "Review JSON 语法不正确") from None
    if isinstance(payload, dict):
        payload = payload.get("test_point") or payload.get("test_points") or payload.get("point")
    if not isinstance(payload, list) or not payload:
        raise ServiceError(422, REVIEW_FILE_INVALID, "Review JSON 必须包含非空测试点列表")
    if len(payload) > max_points:
        raise ServiceError(422, REVIEW_FILE_INVALID, "Review 测试点数量超过上限")
    required = {"test_point"}
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict) or not required.intersection(item):
            raise ServiceError(422, REVIEW_FILE_INVALID, f"第 {index} 个测试点缺少 test_point 字段")
    return payload


def sha256_bytes(data: bytes) -> str:
    """返回上传内容的 SHA-256。"""

    return hashlib.sha256(data).hexdigest()
