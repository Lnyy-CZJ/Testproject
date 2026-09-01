import os
import unittest

from aidating_eval.cli import main


RUN_REPLY = (
    os.getenv("AIDATING_RUN_STAGING_TESTS") == "1"
    and os.getenv("AIDATING_RUN_PUBLIC_REPLY_STAGING") == "1"
)


@unittest.skipUnless(
    RUN_REPLY,
    "Public Reply 需后端开放并显式开启独立 opt-in",
)
class PublicReplyStagingTests(unittest.TestCase):
    def test_one_local_sanitized_case_reaches_result_and_delete(self):
        code = main(
            [
                "run",
                "--mode",
                "e2e",
                "--dataset",
                "datasets/e2e-smoke/reply-single.json",
            ]
        )
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
