import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidating_eval.config import Settings
from aidating_eval.errors import ConfigurationError


EVAL_URL = (
    "http://lb-rg3phjei-vzmdn2i7ey8rq40l.clb.usw-tencentclb.com/admin/invoke"
)
PUBLIC_URL = "https://gateway.spark-jam.top/dating/gateway/invoke"
HEALTH_URL = "https://gateway.spark-jam.top/healthz"


class SettingsTests(unittest.TestCase):
    """验证两种模式只接受已冻结、不会泄密的配置。"""

    def test_eval_http_requires_explicit_switch(self):
        env = {
            "AIDATING_EVAL_BASE_URL": EVAL_URL,
            "AIDATING_EVAL_API_KEY": "test-secret",
            "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "false",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env("eval")

    def test_unknown_http_host_is_always_rejected(self):
        env = {
            "AIDATING_EVAL_BASE_URL": "http://evil.example/admin/invoke",
            "AIDATING_EVAL_API_KEY": "test-secret",
            "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env("eval")

    def test_secret_and_device_id_are_redacted(self):
        env = {
            "AIDATING_EVAL_BASE_URL": EVAL_URL,
            "AIDATING_EVAL_API_KEY": "test-secret",
            "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "true",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = Settings.from_env("eval")
        self.assertNotIn("test-secret", repr(settings))
        self.assertEqual("***", settings.redacted()["eval_api_key"])

    def test_eval_concurrency_must_be_integer_between_one_and_five(self):
        for invalid in ("0", "6", "many"):
            with self.subTest(invalid=invalid), patch.dict(
                "os.environ",
                {
                    "AIDATING_EVAL_BASE_URL": EVAL_URL,
                    "AIDATING_EVAL_API_KEY": "test-secret",
                    "AIDATING_EVAL_ALLOW_INSECURE_HTTP": "true",
                    "AIDATING_EVAL_CONCURRENCY": invalid,
                },
                clear=True,
            ):
                with self.assertRaises(ConfigurationError):
                    Settings.from_env("eval")

    def test_e2e_requires_exact_urls_device_and_existing_fixture_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            valid = {
                "AIDATING_PUBLIC_GATEWAY_URL": PUBLIC_URL,
                "AIDATING_PUBLIC_HEALTH_URL": HEALTH_URL,
                "AIDATING_E2E_DEVICE_ID": "device-001",
                "AIDATING_E2E_FIXTURE_ROOT": temp_dir,
            }
            with patch.dict("os.environ", valid, clear=True):
                settings = Settings.from_env("e2e")
            self.assertEqual("***", settings.redacted()["device_id"])

            invalid_variants = [
                {**valid, "AIDATING_PUBLIC_GATEWAY_URL": "https://example.com"},
                {**valid, "AIDATING_PUBLIC_HEALTH_URL": "https://example.com"},
                {**valid, "AIDATING_E2E_DEVICE_ID": ""},
                {**valid, "AIDATING_E2E_FIXTURE_ROOT": str(Path(temp_dir) / "missing")},
            ]
            for env in invalid_variants:
                with self.subTest(env=env), patch.dict("os.environ", env, clear=True):
                    with self.assertRaises(ConfigurationError):
                        Settings.from_env("e2e")

    def test_unknown_mode_is_rejected(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ConfigurationError):
                Settings.from_env("unknown")


if __name__ == "__main__":
    unittest.main()
