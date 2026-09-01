import json
import unittest
from pathlib import Path


class ContractFixtureTests(unittest.TestCase):
    def test_all_gateway_fixtures_use_explicit_source_wrapper(self):
        root = Path("tests/fixtures")
        paths = list((root / "public").glob("*.json")) + list(
            (root / "evaluation").glob("*.json")
        )
        self.assertGreater(len(paths), 20)
        for path in paths:
            with self.subTest(path=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn(value.get("source"), {"documented", "staging_observed"})
                self.assertIsInstance(value.get("response"), dict)


if __name__ == "__main__":
    unittest.main()
