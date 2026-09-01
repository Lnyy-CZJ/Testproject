import unittest

from aidating_eval.runner import CaseRunner
from tests.helpers import (
    MemoryArtifactStore,
    build_public_fixture_adapter,
)


class PublicE2EIntegrationTests(unittest.TestCase):
    def test_identity_preferences_media_reply_result_delete(self):
        adapter, case, context = build_public_fixture_adapter("reply")
        self.addCleanup(adapter._fixture_temporary_directory.cleanup)
        adapter.prepare_run(context)
        outcome = CaseRunner(
            adapter, MemoryArtifactStore(), sleep_fn=lambda _: None
        ).execute(case, context)
        self.assertEqual("completed", outcome.status)
        self.assertEqual("dating.reply_generation.v1", outcome.schema_version)
        self.assertTrue(outcome.cleanup and outcome.cleanup.success)

    def test_identity_media_quota_analysis_result_delete(self):
        adapter, case, context = build_public_fixture_adapter("analysis")
        self.addCleanup(adapter._fixture_temporary_directory.cleanup)
        adapter.prepare_run(context)
        outcome = CaseRunner(
            adapter, MemoryArtifactStore(), sleep_fn=lambda _: None
        ).execute(case, context)
        self.assertEqual("completed", outcome.status)
        self.assertEqual("dating.relationship_analysis.v1", outcome.schema_version)
        self.assertTrue(outcome.cleanup and outcome.cleanup.success)


if __name__ == "__main__":
    unittest.main()
