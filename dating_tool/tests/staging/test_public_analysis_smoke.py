import os
import unittest

from aidating_eval.cli import main


RUN_STAGING = os.getenv("AIDATING_RUN_STAGING_TESTS") == "1"


@unittest.skipUnless(RUN_STAGING, "需要显式开启 staging 测试")
class PublicAnalysisStagingTests(unittest.TestCase):
    def test_one_synthetic_case_reaches_result_and_delete(self):
        code = main(
            [
                "run",
                "--mode",
                "e2e",
                "--dataset",
                "datasets/e2e-smoke/analysis-single.json",
            ]
        )
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
