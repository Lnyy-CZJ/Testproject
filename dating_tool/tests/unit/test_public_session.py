import unittest

from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.domain import TaskStatus
from aidating_eval.errors import BusinessError
from tests.helpers import FakePublicGateway


def _session(access="access-1", refresh="refresh-1"):
    return {
        "user_id": "user-1",
        "access_token": access,
        "expires_time": 1787558400000,
        "refresh_token": refresh,
        "refresh_expires_time": 1790064000000,
        "is_new_user": True,
    }


class PublicSessionTests(unittest.TestCase):
    """公开 Session 必须在内存中原子保存并经 GetMe 校验。"""

    def test_create_session_then_get_me(self):
        gateway = FakePublicGateway(
            [("CreateAnonymousSession", _session()), ("GetMe", {"user_id": "user-1"})]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        adapter.prepare_run(adapter.test_context())
        self.assertEqual(
            ["CreateAnonymousSession", "GetMe"],
            [call.method_name for call in gateway.calls],
        )
        self.assertNotIn("access-1", repr(adapter.session_tokens))
        self.assertIsNone(gateway.calls[0].access_token)
        self.assertEqual("access-1", gateway.calls[1].access_token)

    def test_refresh_replaces_both_tokens_and_revalidates_identity(self):
        gateway = FakePublicGateway(
            [
                ("CreateAnonymousSession", _session()),
                ("GetMe", {"user_id": "user-1"}),
                ("RefreshSession", _session("access-2", "refresh-2")),
                ("GetMe", {"user_id": "user-1"}),
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway)
        adapter.prepare_run(adapter.test_context())
        adapter.refresh_session()
        self.assertEqual("access-2", adapter.session_tokens.access_token)
        self.assertEqual("refresh-2", adapter.session_tokens.refresh_token)
        refresh_call = gateway.calls[2]
        self.assertIsNone(refresh_call.access_token)
        self.assertEqual("refresh-1", refresh_call.params["refresh_token"])

    def test_authenticated_call_refreshes_once_and_retries_same_request(self):
        replacement = _session("access-2", "refresh-2")
        replacement["user_id"] = "test-user"
        gateway = FakePublicGateway(
            [
                ("GetAnalysisTask", BusinessError("UNAUTHENTICATED")),
                ("RefreshSession", replacement),
                ("GetMe", {"user_id": "test-user"}),
                (
                    "GetAnalysisTask",
                    {
                        "task_id": "task-analysis",
                        "task_type": "relationship_analysis",
                        "status": "succeeded",
                        "phase": "done",
                    },
                ),
                ("GetAnalysisTask", BusinessError("UNAUTHENTICATED")),
            ]
        )
        adapter = PublicE2EAdapter.for_test(gateway=gateway, authenticated=True)
        context = adapter.test_context("analysis")

        snapshot = adapter.get_task("task-analysis", context)
        self.assertEqual(TaskStatus.SUCCEEDED, snapshot.status)
        with self.assertRaisesRegex(BusinessError, "UNAUTHENTICATED"):
            adapter.get_task("task-analysis", context)

        methods = [call.method_name for call in gateway.calls]
        self.assertEqual(1, methods.count("RefreshSession"))
        first, retried = gateway.calls[0], gateway.calls[3]
        self.assertEqual(first.request_id, retried.request_id)
        self.assertEqual(first.params, retried.params)
        self.assertEqual("access-2", retried.access_token)

    def test_get_me_user_mismatch_is_contract_error(self):
        from aidating_eval.errors import ContractError

        gateway = FakePublicGateway(
            [("CreateAnonymousSession", _session()), ("GetMe", {"user_id": "different"})]
        )
        with self.assertRaises(ContractError):
            PublicE2EAdapter.for_test(gateway=gateway).prepare_run(
                PublicE2EAdapter.test_context()
            )

    def test_boolean_session_expiry_is_not_accepted_as_integer_timestamp(self):
        from aidating_eval.errors import ContractError

        invalid = _session()
        invalid["expires_time"] = True
        gateway = FakePublicGateway([("CreateAnonymousSession", invalid)])
        with self.assertRaisesRegex(ContractError, "PUBLIC_SESSION_EXPIRY_INVALID"):
            PublicE2EAdapter.for_test(gateway=gateway).create_session()


if __name__ == "__main__":
    unittest.main()
