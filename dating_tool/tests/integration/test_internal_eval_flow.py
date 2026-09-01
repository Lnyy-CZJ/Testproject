import unittest

from tests.helpers import build_internal_batch_fixture


class InternalEvalIntegrationTests(unittest.TestCase):
    def test_mixed_reply_and_analysis_finish_in_order_and_delete(self):
        batch, cases, context_factory, gateway = build_internal_batch_fixture()
        outcomes = batch.run(cases, context_factory)
        self.assertEqual(
            [case.case_id for case in cases],
            [outcome.case_id for outcome in outcomes],
        )
        self.assertTrue(all(outcome.status == "completed" for outcome in outcomes))
        self.assertTrue(
            all(outcome.cleanup and outcome.cleanup.success for outcome in outcomes)
        )
        methods = [call.method_name for call in gateway.calls]
        self.assertIn("DeleteReplyEvaluationTaskData", methods)
        self.assertIn("DeleteAnalysisEvaluationTaskData", methods)


if __name__ == "__main__":
    unittest.main()
