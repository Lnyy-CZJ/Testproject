import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProjectContractTests(unittest.TestCase):
    """约束工程的安全默认值和可安装版本契约。"""

    def test_artifacts_env_and_private_media_are_git_ignored(self):
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("artifacts/*", rules)
        self.assertIn(".env", rules)
        self.assertIn("datasets/media/*", rules)
        self.assertIn("logs/", rules)

    def test_example_env_never_contains_real_key(self):
        content = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertNotIn("adm_key_", content)
        self.assertIn("AIDATING_EVAL_API_KEY=", content)

    def test_package_version_is_importable(self):
        from aidating_eval import __version__

        self.assertRegex(__version__, r"^0\.3\.\d+$")


if __name__ == "__main__":
    unittest.main()
