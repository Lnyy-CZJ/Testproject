import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aidating_eval.cli import main


RUN_STAGING = os.getenv("AIDATING_RUN_STAGING_TESTS") == "1"


@unittest.skipUnless(RUN_STAGING, "需要显式开启 staging 测试")
class InternalAnalysisStagingTests(unittest.TestCase):
    def test_one_structured_analysis_case_reaches_result_diagnostics_and_delete(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"AIDATING_ARTIFACTS_ROOT": directory}, clear=False
        ):
            code = main(
                [
                    "run",
                    "--mode",
                    "eval",
                    "--dataset",
                    "datasets/eval-smoke.jsonl",
                    "--case",
                    "eval-analysis-happy-001",
                ]
            )
            run_path = next(Path(directory).iterdir())
            events = [
                json.loads(line)["event"]
                for line in (run_path / "run-state.jsonl").read_text().splitlines()
            ]
        self.assertEqual(0, code)
        self.assertIn("diagnostics_fetched", events)
        self.assertTrue(
            {"delete_succeeded", "delete_already_absent"}.intersection(events)
        )


if __name__ == "__main__":
    unittest.main()
