import tempfile
import unittest
from pathlib import Path

from PIL import Image

from aidating_eval.errors import CaseValidationError
from aidating_eval.media_validation import inspect_media, validate_against_media_config


class MediaValidationTests(unittest.TestCase):
    """媒体校验只读取源文件，真实格式、扩展名和元数据必须一致。"""

    def test_rejects_exif_without_modifying_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            image = Image.new("RGB", (1200, 800), "white")
            exif = Image.Exif()
            exif[0x010E] = "private metadata"
            image.save(source, exif=exif)
            original = source.read_bytes()
            with self.assertRaises(CaseValidationError):
                inspect_media(source)
            self.assertEqual(original, source.read_bytes())

    def test_accepts_clean_image_and_preserves_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clean.jpg"
            Image.new("RGB", (1200, 800), "white").save(source, format="JPEG")
            original = source.read_bytes()
            media = inspect_media(source)
            self.assertEqual("image/jpeg", media.content_type)
            self.assertEqual(len(original), media.size_bytes)
            self.assertEqual(original, media.content)
            self.assertNotIn(str(source), repr(media))

    def test_rejects_extension_that_disagrees_with_detected_format(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "wrong.png"
            Image.new("RGB", (100, 100), "white").save(source, format="JPEG")
            with self.assertRaises(CaseValidationError):
                inspect_media(source)

    def test_dynamic_config_enforces_mime_and_inclusive_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clean.png"
            Image.new("RGB", (10, 10), "white").save(source, format="PNG")
            media = inspect_media(source)
            config = {
                "allowed_content_types": ["image/png"],
                "max_size_bytes": media.size_bytes,
            }
            validate_against_media_config(media, config)
            with self.assertRaises(CaseValidationError):
                validate_against_media_config(
                    media,
                    {**config, "max_size_bytes": media.size_bytes - 1},
                )


if __name__ == "__main__":
    unittest.main()
