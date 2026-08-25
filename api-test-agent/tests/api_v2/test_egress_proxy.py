"""出口代理登记目标、DNS 重绑定、Cookie 转发和 HTTPS 负向测试。"""

from __future__ import annotations

from email.message import Message
from io import BytesIO
import importlib

def test_proxy_only_finds_registered_host(monkeypatch):
    """完整 URL 中的未登记 Host 不得进入 DNS 或转发阶段。"""

    monkeypatch.setenv(
        "REGISTERED_TARGETS",
        '[{"target_id":"local","schemes":["http"],"hosts":["platform-gateway"],"ports":[80],"path_prefixes":["/api/v1/"],"allowed_cidrs":["172.16.0.0/12"]}]',
    )
    proxy_app = importlib.import_module("services.egress_proxy.app")
    assert proxy_app.find_target("http://platform-gateway/api/v1/health/live") is not None
    assert proxy_app.find_target("http://127.0.0.1/api/v1/health/live") is None
    assert proxy_app.find_target("http://169.254.169.254/latest/meta-data") is None
    assert proxy_app.find_target("http://platform-gateway.evil.test/api/v1/health/live") is None


def test_proxy_forwards_set_cookie_without_logging_and_rejects_https_when_http_only(monkeypatch):
    """响应 Cookie 必须回到同一 Executor 连接；当前 HTTP 代理不得伪装支持 HTTPS。"""

    monkeypatch.setenv(
        "REGISTERED_TARGETS",
        '[{"target_id":"local","schemes":["http","https"],"hosts":["platform-gateway"],"ports":[80,443],"path_prefixes":["/api/v1/"],"allowed_cidrs":["172.16.0.0/12"]}]',
    )
    proxy_app = importlib.reload(importlib.import_module("services.egress_proxy.app"))
    target = proxy_app.TARGETS["local"]

    class UpstreamResponse:
        status = 200

        def getheaders(self):
            return [("Set-Cookie", "session=secret-value; Path=/"), ("X-Upstream", "ok")]

        def getheader(self, name):
            return "" if name.lower() == "location" else None

        def read(self, _limit):
            return b'{"ok":true}'

    class UpstreamConnection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            return None

        def getresponse(self):
            return UpstreamResponse()

    monkeypatch.setattr(proxy_app.socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("172.16.1.2", 0))])
    monkeypatch.setattr(proxy_app.http.client, "HTTPConnection", UpstreamConnection)
    handler = object.__new__(proxy_app.ProxyHandler)
    headers = Message()
    headers["Host"] = "platform-gateway"
    handler.headers = headers
    handler.path = "http://platform-gateway/api/v1/session"
    handler.command = "GET"
    handler.rfile = BytesIO()
    handler.wfile = BytesIO()
    forwarded_headers = []
    handler.send_response = lambda _status: None
    handler.send_header = lambda key, value: forwarded_headers.append((key, value))
    handler.end_headers = lambda: None
    handler._forward()
    assert ("Set-Cookie", "session=secret-value; Path=/") in forwarded_headers
    assert proxy_app.ProxyHandler.log_message(handler, "%s", "session=secret-value") is None

    denied = []
    handler = object.__new__(proxy_app.ProxyHandler)
    handler.path = "https://platform-gateway/api/v1/session"
    handler._deny = lambda code, status=403: denied.append((code, status))
    monkeypatch.setattr(proxy_app, "find_target", lambda _url: target)
    handler._forward()
    assert denied == [("EGRESS_HTTPS_NOT_READY", 501)]
