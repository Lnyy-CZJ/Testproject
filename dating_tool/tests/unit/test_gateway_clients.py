import unittest

from aidating_eval.errors import BusinessError, ContractError
from aidating_eval.evaluation_gateway import EvaluationGatewayClient
from aidating_eval.public_gateway import PublicGatewayClient
from tests.helpers import FakeTransport


class GatewayClientTests(unittest.TestCase):
    """验证两种 Gateway 信封、鉴权位置和稳定错误分支。"""

    def test_public_access_token_is_in_comm_not_authorization_header(self):
        transport = FakeTransport(
            [{"code": 0, "responses": [{"id": "r1", "success": True, "code": 0, "data": {}}]}]
        )
        client = PublicGatewayClient.example_for_test(transport)
        client.call("tool.identity.IdentityService", "GetMe", {}, "r1", "token")
        call = transport.calls[0]
        self.assertEqual("token", call.json_body["comm"]["auth_token"])
        self.assertNotIn("Authorization", call.headers)
        self.assertEqual("sequential", call.json_body["execution"]["mode"])

    def test_public_rejects_reserved_identity_fields_in_params(self):
        client = PublicGatewayClient.example_for_test(FakeTransport())
        for field in ("app_id", "user_id"):
            with self.subTest(field=field), self.assertRaises(ContractError):
                client.call("service", "method", {field: "forbidden"}, "r1", None)

    def test_internal_key_is_bearer_header_and_service_is_fixed(self):
        transport = FakeTransport(
            [{"responses": [{"success": True, "data": {"ok": True}}]}]
        )
        client = EvaluationGatewayClient(
            transport=transport,
            url="http://allowed.test/admin/invoke",
            api_key="secret",
        )
        result = client.call("GetAnalysisEvaluationTask", {"task_id": "task-1"})
        call = transport.calls[0]
        self.assertEqual({"ok": True}, result)
        self.assertEqual("Bearer secret", call.headers["Authorization"])
        self.assertEqual(
            "tool.dating.internal.DatingEvaluationService",
            call.json_body["service_name"],
        )

    def test_internal_optional_top_level_fields_are_only_added_when_supplied(self):
        transport = FakeTransport(
            [{"responses": [{"success": True, "data": {}}]}]
        )
        client = EvaluationGatewayClient(transport, "http://allowed", "key")
        client.call(
            "CreateReplyEvaluationTask",
            {"case_id": "case"},
            client_request_id="request-1",
            reason="automated Reply evaluation",
        )
        payload = transport.calls[0].json_body
        self.assertEqual("request-1", payload["client_request_id"])
        self.assertEqual("automated Reply evaluation", payload["reason"])

    def test_business_error_uses_code_not_free_text(self):
        transport = FakeTransport(
            [
                {
                    "code": 0,
                    "responses": [
                        {
                            "id": "r1",
                            "success": False,
                            "code": 306409,
                            "http_status": 409,
                            "message": "arbitrary private text",
                            "business_error_code": "TASK_NOT_READY",
                            "data": {
                                "error_code": "TASK_NOT_READY",
                                "retryable": True,
                                "retry_after_seconds": 3,
                            },
                        }
                    ],
                }
            ]
        )
        client = PublicGatewayClient.example_for_test(transport)
        with self.assertRaises(BusinessError) as raised:
            client.call(
                "tool.dating.DatingAssistantService",
                "GetAnalysisResult",
                {},
                "r1",
                "token",
            )
        self.assertEqual("TASK_NOT_READY", raised.exception.code)
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(3, raised.exception.retry_after_seconds)
        self.assertNotIn("arbitrary private text", str(raised.exception))

    def test_malformed_response_count_and_id_are_contract_errors(self):
        responses = [
            {"code": 0, "responses": []},
            {
                "code": 0,
                "responses": [
                    {"id": "wrong", "success": True, "code": 0, "data": {}}
                ],
            },
        ]
        for response in responses:
            client = PublicGatewayClient.example_for_test(FakeTransport([response]))
            with self.subTest(response=response), self.assertRaises(ContractError):
                client.call("service", "method", {}, "r1", None)


if __name__ == "__main__":
    unittest.main()
