import base64
import json
import tempfile
import unittest
from pathlib import Path

import requests

from aidating_eval.errors import TransportError
from aidating_eval.http import RequestsTransport
from aidating_eval.wire_logging import RawWireLogger


class _Response:
    def __init__(
        self,
        status_code=200,
        body=None,
        json_error=None,
        *,
        headers=None,
        text=None,
        content=None,
    ):
        self.status_code = status_code
        self._body = {} if body is None else body
        self._json_error = json_error
        self.headers = {} if headers is None else headers
        self.text = (
            json.dumps(self._body, ensure_ascii=False) if text is None else text
        )
        self.content = self.text.encode("utf-8") if content is None else content

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._body


class _Session:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)


class _FailingWireLogger:
    """模拟磁盘在请求发出后写满，验证日志不能破坏 Task 生命周期。"""

    def __init__(self):
        self.calls = 0

    @staticmethod
    def new_exchange_id():
        return "exchange-1"

    def write(self, event, **fields):
        self.calls += 1
        if self.calls >= 2:
            raise OSError("disk full")


class RequestsTransportTests(unittest.TestCase):
    """Transport 的错误只能暴露类型或状态码，不能携带 URL/正文。"""

    def test_request_json_rejects_redirect_and_does_not_follow_it(self):
        session = _Session(_Response(302, {"secret": "body"}))
        transport = RequestsTransport(session_factory=lambda: session)
        with self.assertRaisesRegex(TransportError, "HTTP_302"):
            transport.request_json("POST", "https://safe.test/invoke", headers={}, json_body={})
        self.assertFalse(session.calls[0][2]["allow_redirects"])

    def test_request_json_rejects_non_object_and_invalid_json(self):
        for response in (
            _Response(200, []),
            _Response(200, json_error=ValueError("raw response secret")),
        ):
            with self.subTest(response=response):
                transport = RequestsTransport(session_factory=lambda r=response: _Session(r))
                with self.assertRaises(TransportError) as raised:
                    transport.request_json(
                        "POST", "https://safe.test/invoke?signature=secret", headers={}, json_body={}
                    )
                self.assertNotIn("signature=secret", str(raised.exception))
                self.assertNotIn("raw response secret", str(raised.exception))

    def test_connection_error_does_not_include_url(self):
        session = _Session(error=requests.ConnectionError("https://host/path?secret=1"))
        transport = RequestsTransport(session_factory=lambda: session)
        with self.assertRaises(TransportError) as raised:
            transport.get_status("https://host/path?secret=1")
        self.assertNotIn("secret=1", str(raised.exception))

    def test_put_bytes_uses_put_without_redirect_and_ignores_body(self):
        session = _Session(_Response(204, {"private": "body"}))
        transport = RequestsTransport(session_factory=lambda: session)
        status = transport.put_bytes(
            "https://cos.test/object?signature=secret",
            headers={"Content-Type": "image/png"},
            content=b"png",
        )
        self.assertEqual(204, status)
        method, _, kwargs = session.calls[0]
        self.assertEqual("PUT", method)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(b"png", kwargs["data"])

    def test_json_exchange_logs_full_raw_request_and_response(self):
        response = _Response(
            200,
            {
                "responses": [
                    {
                        "success": True,
                        "data": {
                            "auth_token": "returned-token",
                            "reply_text": "Exact generated reply",
                        },
                    }
                ]
            },
            headers={"X-Request-Id": "backend-request-1"},
        )
        session = _Session(response)
        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")
            transport = RequestsTransport(
                session_factory=lambda: session,
                wire_logger=logger,
            )
            transport.request_json(
                "POST",
                "https://gateway.test/invoke?signature=full-signature",
                headers={"Authorization": "Bearer full-api-key"},
                json_body={
                    "comm": {"device_id": "device-1"},
                    "text": "Exact request text",
                },
            )
            events = [
                json.loads(line)
                for line in logger.path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(["http_request", "http_response"], [e["event"] for e in events])
        request, logged_response = events
        self.assertEqual(
            "https://gateway.test/invoke?signature=full-signature",
            request["url"],
        )
        self.assertEqual("Bearer full-api-key", request["headers"]["Authorization"])
        self.assertEqual("Exact request text", request["json_body"]["text"])
        self.assertEqual(request["exchange_id"], logged_response["exchange_id"])
        self.assertEqual(200, logged_response["status_code"])
        self.assertEqual(
            "backend-request-1", logged_response["headers"]["X-Request-Id"]
        )
        self.assertEqual(
            "Exact generated reply",
            logged_response["json_body"]["responses"][0]["data"]["reply_text"],
        )
        self.assertIn("elapsed_ms", logged_response)

    def test_logs_the_actual_prepared_request_with_runtime_headers_and_url(self):
        session_for_prepare = requests.Session()
        prepared = session_for_prepare.prepare_request(
            requests.Request(
                "POST",
                "https://gateway.test/path with space",
                headers={
                    "Authorization": "Bearer prepared-token",
                    "Cookie": "session=prepared-cookie",
                },
                json={"text": "prepared body"},
            )
        )
        response = _Response(200, {"ok": True})
        response.request = prepared
        session = _Session(response)

        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")
            transport = RequestsTransport(
                session_factory=lambda: session,
                wire_logger=logger,
            )
            transport.request_json(
                "POST",
                "https://gateway.test/path with space",
                headers={"Authorization": "Bearer prepared-token"},
                json_body={"text": "prepared body"},
            )
            events = [
                json.loads(line)
                for line in logger.path.read_text(encoding="utf-8").splitlines()
            ]

        prepared_event = next(
            event for event in events if event["event"] == "http_prepared_request"
        )
        self.assertEqual(
            "https://gateway.test/path%20with%20space", prepared_event["url"]
        )
        self.assertEqual(
            "Bearer prepared-token", prepared_event["headers"]["Authorization"]
        )
        self.assertEqual(
            "session=prepared-cookie", prepared_event["headers"]["Cookie"]
        )
        self.assertIn("User-Agent", prepared_event["headers"])
        self.assertIn("Content-Length", prepared_event["headers"])
        self.assertEqual("prepared body", prepared_event["json_body"]["text"])

    def test_cos_exchange_logs_signed_url_headers_binary_and_response(self):
        response = _Response(
            204,
            headers={"ETag": "private-etag"},
            text="uploaded",
            content=b"uploaded",
        )
        session = _Session(response)
        payload = b"\x89PNG\r\nprivate-image-bytes"
        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")
            transport = RequestsTransport(
                session_factory=lambda: session,
                wire_logger=logger,
            )
            transport.put_bytes(
                "https://cos.test/object?signature=private-signature",
                headers={"X-Cos-Security-Token": "private-token"},
                content=payload,
            )
            events = [
                json.loads(line)
                for line in logger.path.read_text(encoding="utf-8").splitlines()
            ]

        request, logged_response = events
        self.assertEqual(base64.b64encode(payload).decode("ascii"), request["body_base64"])
        self.assertEqual("private-token", request["headers"]["X-Cos-Security-Token"])
        self.assertIn("private-signature", request["url"])
        self.assertEqual("private-etag", logged_response["headers"]["ETag"])
        self.assertEqual(
            base64.b64encode(b"uploaded").decode("ascii"),
            logged_response["body_base64"],
        )

    def test_transport_exception_is_logged_with_original_message(self):
        session = _Session(
            error=requests.ConnectionError(
                "https://host/path?secret=raw network detail"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            logger = RawWireLogger.create(Path(directory) / "logs")
            transport = RequestsTransport(
                session_factory=lambda: session,
                wire_logger=logger,
            )
            with self.assertRaises(TransportError):
                transport.get_status("https://host/path?secret=raw-url")
            events = [
                json.loads(line)
                for line in logger.path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(["http_request", "http_error"], [e["event"] for e in events])
        self.assertEqual(
            "https://host/path?secret=raw-url", events[0]["url"]
        )
        self.assertIn("raw network detail", events[1]["message"])

    def test_log_write_failure_does_not_replace_successful_network_result(self):
        session = _Session(_Response(200, {"task_id": "task-created"}))
        transport = RequestsTransport(
            session_factory=lambda: session,
            wire_logger=_FailingWireLogger(),
        )

        body = transport.request_json(
            "POST",
            "https://gateway.test/invoke",
            headers={},
            json_body={"method_name": "CreateTask"},
        )

        self.assertEqual({"task_id": "task-created"}, body)

    def test_log_write_failure_does_not_replace_transport_error(self):
        class AlwaysFailLogger(_FailingWireLogger):
            def write(self, event, **fields):
                raise OSError("disk full")

        session = _Session(error=requests.ConnectionError("network down"))
        transport = RequestsTransport(
            session_factory=lambda: session,
            wire_logger=AlwaysFailLogger(),
        )

        with self.assertRaisesRegex(TransportError, "ConnectionError"):
            transport.get_status("https://gateway.test/healthz")


if __name__ == "__main__":
    unittest.main()
