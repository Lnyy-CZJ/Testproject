import tempfile
import unittest
from pathlib import Path

from PIL import Image

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.config import PUBLIC_GATEWAY_URL, PUBLIC_HEALTH_URL, Settings
from aidating_eval.domain import E2EAnalysisCase
from aidating_eval.errors import CaseValidationError, ContractError
from tests.helpers import FakePublicGateway, FakeTransport


def _png(path: Path, color: str) -> None:
    Image.new("RGB", (100, 100), color).save(path, format="PNG")


class PublicMediaTests(unittest.TestCase):
    """Prepare/PUT/Complete 必须保持 Case 中的媒体顺序。"""

    def test_prepare_put_complete_preserves_asset_order(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "1.png", Path(directory) / "2.png"
            _png(first, "white")
            _png(second, "black")
            sizes = [first.stat().st_size, second.stat().st_size]
            original_contents = [first.read_bytes(), second.read_bytes()]
            config = {
                "allowed_content_types": ["image/png"],
                "min_asset_count": 1,
                "max_asset_count": 9,
                "max_size_bytes": 7_000_000,
                "config_cache_ttl_seconds": 300,
                "complete_retry": {"max_attempts": 1, "initial_delay_ms": 0, "max_delay_ms": 0},
            }
            script = [("GetMediaUploadConfig", config)]
            for asset_id, size in zip(("asset-2", "asset-1"), sizes, strict=True):
                script.extend(
                    [
                        ("PrepareMediaUpload", {
                            "asset_id": asset_id,
                            "content_type": "image/png",
                            "size_bytes": size,
                            "upload_url": f"https://cos.test/{asset_id}?signature=safe",
                            "upload_method": "PUT",
                            "required_headers": {"Content-Type": "image/png"},
                            "max_size_bytes": 7_000_000,
                        }),
                        ("CompleteMediaUpload", {"asset_id": asset_id, "status": "uploaded"}),
                    ]
                )
            gateway = FakePublicGateway(script)
            transport = FakeTransport([204, 204])
            adapter = PublicE2EAdapter.for_test(
                gateway=gateway, transport=transport, authenticated=True
            )
            case = E2EAnalysisCase(
                "two-images", "en-US", (first, second), None, None
            )
            asset_ids = adapter.upload_media(case, adapter.test_context())
        self.assertEqual(("asset-2", "asset-1"), asset_ids)
        put_calls = [call for call in transport.calls if call.method == "PUT"]
        self.assertEqual(2, len(put_calls))
        self.assertEqual(original_contents, [call.content for call in put_calls])
        self.assertEqual(
            ["PrepareMediaUpload", "CompleteMediaUpload", "PrepareMediaUpload", "CompleteMediaUpload"],
            [call.method_name for call in gateway.calls if call.method_name != "GetMediaUploadConfig"],
        )

    def test_group_count_uses_dynamic_config(self):
        gateway = FakePublicGateway(
            [("GetMediaUploadConfig", {
                "allowed_content_types": ["image/png"],
                "min_asset_count": 1,
                "max_asset_count": 1,
                "max_size_bytes": 1000,
                "config_cache_ttl_seconds": 300,
            })]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "1.png", Path(directory) / "2.png"
            _png(first, "white")
            _png(second, "black")
            case = E2EAnalysisCase("too-many", "en-US", (first, second), None, None)
            with self.assertRaises(Exception):
                adapter.upload_media(case, adapter.test_context())

    def test_upload_url_must_be_presigned_https(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "chat.png"
            _png(image, "white")
            size = image.stat().st_size
            gateway = FakePublicGateway(
                [
                    ("GetMediaUploadConfig", {
                        "allowed_content_types": ["image/png"],
                        "min_asset_count": 1,
                        "max_asset_count": 1,
                        "max_size_bytes": 7000000,
                        "config_cache_ttl_seconds": 300,
                    }),
                    ("PrepareMediaUpload", {
                        "asset_id": "asset-1",
                        "content_type": "image/png",
                        "size_bytes": size,
                        "upload_url": "https://cos.test/upload",
                        "upload_method": "PUT",
                        "required_headers": {"Content-Type": "image/png"},
                        "max_size_bytes": 7000000,
                    }),
                ]
            )
            adapter = PublicE2EAdapter.for_test(
                gateway=gateway, transport=FakeTransport(), authenticated=True
            )
            case = E2EAnalysisCase("unsigned", "en-US", (image,), None, None)
            with self.assertRaisesRegex(
                ContractError, "MEDIA_UPLOAD_URL_NOT_PRESIGNED"
            ):
                adapter.upload_media(case, adapter.test_context())

    def test_adapter_rejects_media_outside_fixture_root_before_gateway(self):
        with tempfile.TemporaryDirectory() as fixture, tempfile.TemporaryDirectory() as outside:
            image = Path(outside) / "chat.png"
            _png(image, "white")
            gateway = FakePublicGateway([])
            settings = Settings(
                mode="e2e",
                public_gateway_url=PUBLIC_GATEWAY_URL,
                public_health_url=PUBLIC_HEALTH_URL,
                device_id="fixture-device",
                e2e_fixture_root=Path(fixture),
                artifacts_root=Path(fixture) / "artifacts",
            )
            adapter = PublicE2EAdapter(
                gateway=gateway,
                transport=FakeTransport(),
                settings=settings,
            )
            adapter.session_tokens = PublicE2EAdapter.for_test(
                gateway=FakePublicGateway([]), authenticated=True
            ).session_tokens
            case = E2EAnalysisCase("escape", "en-US", (image,), None, None)
            with self.assertRaisesRegex(CaseValidationError, "Fixture Root"):
                adapter.upload_media(case, adapter.test_context())
            self.assertEqual([], gateway.calls)


if __name__ == "__main__":
    unittest.main()
