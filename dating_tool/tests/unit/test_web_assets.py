from pathlib import Path
import unittest


class WebAssetsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parents[2] / "src" / "aidating_eval" / "web"

    def test_pages_do_not_embed_backend_wire_calls_or_old_project_concepts(self):
        templates = "\n".join(path.read_text(encoding="utf-8") for path in (self.root / "templates").glob("*.html"))
        script = (self.root / "static" / "app.js").read_text(encoding="utf-8")
        source = templates + script
        for forbidden in ("api-autotest", "Project Registry", "Allure", "Gateway URL", "api_key"):
            self.assertNotIn(forbidden, source)
        self.assertIn("/api/runs/validate", source)
        self.assertIn("/api/runs", source)


if __name__ == "__main__":
    unittest.main()
