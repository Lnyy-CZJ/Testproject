import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.domain import ReplyPreferences
from aidating_eval.errors import BusinessError
from tests.helpers import FakePublicGateway


class PublicPreferencesTests(unittest.TestCase):
    """Reply 偏好使用乐观版本，并且不影响 Analysis。"""

    def test_reads_updates_and_confirms_preferences(self):
        gateway = FakePublicGateway(
            [
                (
                    "GetUserPreferences",
                    {
                        "preferences_complete": False,
                        "dating_goal": "",
                        "your_voice": "",
                        "version": 0,
                    },
                ),
                (
                    "UpdateUserPreferences",
                    {
                        "preferences_complete": True,
                        "dating_goal": "serious_relationship",
                        "your_voice": "warm_direct",
                        "version": 1,
                    },
                ),
                (
                    "GetUserPreferences",
                    {
                        "preferences_complete": True,
                        "dating_goal": "serious_relationship",
                        "your_voice": "warm_direct",
                        "version": 1,
                    },
                ),
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        adapter.ensure_preferences(
            ReplyPreferences("serious_relationship", "warm_direct"),
            adapter.test_context(task_kind="reply"),
        )
        self.assertEqual(
            ["GetUserPreferences", "UpdateUserPreferences", "GetUserPreferences"],
            [call.method_name for call in gateway.calls],
        )
        self.assertEqual(0, gateway.calls[1].params["expected_version"])

    def test_matching_complete_preferences_skip_update(self):
        gateway = FakePublicGateway(
            [
                (
                    "GetUserPreferences",
                    {
                        "preferences_complete": True,
                        "dating_goal": "serious_relationship",
                        "your_voice": "warm_direct",
                        "version": 3,
                    },
                )
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        adapter.ensure_preferences(
            ReplyPreferences("serious_relationship", "warm_direct"),
            adapter.test_context(task_kind="reply"),
        )
        self.assertEqual(["GetUserPreferences"], [call.method_name for call in gateway.calls])

    def test_version_conflict_reloads_and_retries_only_once(self):
        conflict = BusinessError("PREFERENCES_VERSION_CONFLICT")
        gateway = FakePublicGateway(
            [
                ("GetUserPreferences", {"preferences_complete": False, "dating_goal": "", "your_voice": "", "version": 1}),
                ("UpdateUserPreferences", conflict),
                ("GetUserPreferences", {"preferences_complete": False, "dating_goal": "", "your_voice": "", "version": 2}),
                ("UpdateUserPreferences", {"preferences_complete": True, "dating_goal": "serious_relationship", "your_voice": "warm_direct", "version": 3}),
                ("GetUserPreferences", {"preferences_complete": True, "dating_goal": "serious_relationship", "your_voice": "warm_direct", "version": 3}),
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        adapter.ensure_preferences(
            ReplyPreferences("serious_relationship", "warm_direct"),
            adapter.test_context(task_kind="reply"),
        )
        updates = [call for call in gateway.calls if call.method_name == "UpdateUserPreferences"]
        self.assertEqual([1, 2], [call.params["expected_version"] for call in updates])


if __name__ == "__main__":
    unittest.main()
