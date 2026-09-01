"""已脱敏截图的只读格式和动态配置校验。"""

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from aidating_eval.errors import CaseValidationError


FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass(frozen=True)
class InspectedMedia:
    """一次读取后冻结的图片字节和已检测元数据。"""

    content: bytes = field(repr=False)
    content_type: str
    size_bytes: int
    width: int
    height: int


def inspect_media(source: Path) -> InspectedMedia:
    """读取一次源文件并用 Pillow 解码；不写回、不重编码。"""

    path = Path(source)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise CaseValidationError("媒体文件无法读取") from exc
    if not content:
        raise CaseValidationError("媒体文件不能为空")
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            detected_format = image.format
            if detected_format not in FORMAT_TO_MIME:
                raise CaseValidationError("图片格式不受支持")
            if image.getexif():
                raise CaseValidationError("图片包含 EXIF，请重新提供已脱敏 Fixture")
            content_type = FORMAT_TO_MIME[detected_format]
            width, height = image.size
    except CaseValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CaseValidationError("无法识别或解码图片") from exc

    expected = EXTENSION_TO_MIME.get(path.suffix.lower())
    if expected is None or expected != content_type:
        raise CaseValidationError("图片扩展名与实际格式不一致")
    if width <= 0 or height <= 0:
        raise CaseValidationError("图片尺寸无效")
    return InspectedMedia(content, content_type, len(content), width, height)


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CaseValidationError(f"Media 配置 {field_name} 必须为正整数")
    return value


def validate_against_media_config(
    media: InspectedMedia,
    config: Mapping[str, Any],
) -> None:
    """按实时服务配置检查单张图片 MIME 和包含上限。"""

    allowed = config.get("allowed_content_types")
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) for item in allowed
    ):
        raise CaseValidationError("Media 配置 allowed_content_types 无效")
    if media.content_type not in allowed:
        raise CaseValidationError("图片 MIME 不在服务端允许列表")
    maximum = _positive_int(config.get("max_size_bytes"), "max_size_bytes")
    if media.size_bytes > maximum:
        raise CaseValidationError("图片大小超过服务端上限")
