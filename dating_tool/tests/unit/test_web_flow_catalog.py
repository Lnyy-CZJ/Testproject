import unittest

from aidating_eval.web.flow_catalog import flow_catalog


class FlowCatalogTests(unittest.TestCase):
    def test_has_two_modes_and_four_protocol_flows(self):
        flows = flow_catalog()
        self.assertEqual(4, len(flows))
        self.assertEqual({"e2e", "eval"}, {flow.mode for flow in flows})
        self.assertEqual({"reply", "analysis"}, {flow.task_kind for flow in flows})
        self.assertIn("Media Upload", flows[0].steps)
        self.assertIn("Diagnostics", flows[-1].steps)
        for flow in flows:
            self.assertNotIn("Gateway", " ".join(flow.steps))


if __name__ == "__main__":
    unittest.main()
