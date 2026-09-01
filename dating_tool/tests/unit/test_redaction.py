import unittest

from aidating_eval.redaction import redact_mapping


class RedactionTests(unittest.TestCase):
    """任何嵌套层级都不能把凭据或带签名 URL 带入产物。"""

    def test_redacts_nested_tokens_headers_and_signed_urls(self):
        source = {
            "comm": {"auth_token": "access-secret"},
            "refresh_token": "refresh-secret",
            "headers": {"Authorization": "Bearer eval-secret"},
            "callback": "https://cos.example/object?signature=query-secret&x=1",
            "upload_url": "https://cos.example/object?credential=secret",
            "task_id": "dating_task_safe",
        }
        redacted = redact_mapping(source)
        serialized = repr(redacted)
        for secret in (
            "access-secret",
            "refresh-secret",
            "eval-secret",
            "query-secret",
            "credential=secret",
        ):
            self.assertNotIn(secret, serialized)
        self.assertEqual("dating_task_safe", redacted["task_id"])

    def test_redacts_tuple_content_without_mutating_source(self):
        source = ({"api_key": "secret"}, "safe")
        redacted = redact_mapping(source)
        self.assertEqual([{"api_key": "***"}, "safe"], redacted)
        self.assertEqual("secret", source[0]["api_key"])

    def test_redacts_entire_generated_result_body_but_keeps_schema_metadata(self):
        source = {
            "task_id": "dating_task_safe",
            "schema_version": "dating.relationship_analysis.v1",
            "result": {
                "overview": {"insight_title": "private generated conclusion"},
                "roles": [{"role_name": "private generated role"}],
            },
        }
        redacted = redact_mapping(source)
        self.assertEqual("***", redacted["result"])
        self.assertEqual(
            "dating.relationship_analysis.v1", redacted["schema_version"]
        )

    def test_redacts_free_text_error_messages_from_task_payloads(self):
        redacted = redact_mapping(
            {
                "status": "failed",
                "error_code": "MODEL_OUTPUT_INVALID",
                "message": "raw server explanation",
                "error_message": "raw model validation detail",
            }
        )
        self.assertEqual("MODEL_OUTPUT_INVALID", redacted["error_code"])
        self.assertEqual("***", redacted["message"])
        self.assertEqual("***", redacted["error_message"])


if __name__ == "__main__":
    unittest.main()
