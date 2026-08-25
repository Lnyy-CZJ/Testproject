"""本机 S2 试点的登记目标 HTTP 出口代理。"""

from __future__ import annotations

import http.client
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from services.execution_controller.policies import RegisteredTarget, validate_destination


def load_targets() -> dict[str, RegisteredTarget]:
    """从只读部署配置加载登记目标；配置异常时进程启动失败关闭。"""

    raw = json.loads(os.getenv("REGISTERED_TARGETS", "[]"))
    targets = {}
    for item in raw:
        target = RegisteredTarget(
            target_id=str(item["target_id"]), schemes=frozenset(item["schemes"]),
            hosts=frozenset(item["hosts"]), ports=frozenset(int(port) for port in item["ports"]),
            path_prefixes=tuple(item.get("path_prefixes", ["/"])),
            allowed_cidrs=tuple(item.get("allowed_cidrs", [])),
        )
        targets[target.target_id] = target
    if not targets:
        raise RuntimeError("未登记任何执行目标")
    return targets


TARGETS = load_targets()


def find_target(url: str) -> RegisteredTarget | None:
    """按登记 Host 查找目标，绝不依据调用方传入的 target_id 放宽策略。"""

    host = (urlsplit(url).hostname or "").lower()
    return next((item for item in TARGETS.values() if host in {value.lower() for value in item.hosts}), None)


class ProxyHandler(BaseHTTPRequestHandler):
    """只转发完整 HTTP URL；拒绝 CONNECT、用户信息和未登记目的地。"""

    protocol_version = "HTTP/1.1"

    def _deny(self, code: str, status: int = 403) -> None:
        body = json.dumps({"error": {"code": code}}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _forward(self) -> None:
        parsed = urlsplit(self.path)
        target = find_target(self.path)
        if target is None:
            self._deny("EGRESS_TARGET_NOT_REGISTERED")
            return
        # 当前代理只实现受控 HTTP 转发；不能以明文 HTTPConnection 冒充 HTTPS 成功。
        if parsed.scheme == "https":
            self._deny("EGRESS_HTTPS_NOT_READY", 501)
            return
        try:
            before = sorted({item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80, type=socket.SOCK_STREAM)})
            after = sorted({item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80, type=socket.SOCK_STREAM)})
        except socket.gaierror:
            self._deny("DNS_RESOLUTION_FAILED", 502)
            return
        if before != after:
            self._deny("DNS_REBINDING_DENIED")
            return
        allowed, reason = validate_destination(self.path, target, before, host_header=self.headers.get("Host", ""))
        if not allowed:
            self._deny(reason)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 2 * 1024 * 1024:
            self._deny("REQUEST_BODY_TOO_LARGE", 413)
            return
        body = self.rfile.read(length) if length else None
        headers = {
            key: value for key, value in self.headers.items()
            if key.lower() not in {"proxy-authorization", "proxy-connection", "connection", "host"}
        }
        headers["Host"] = parsed.netloc
        try:
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=15)
            path = parsed.path or "/"
            if parsed.query:
                path += f"?{parsed.query}"
            connection.request(self.command, path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read(2 * 1024 * 1024)
        except (OSError, http.client.HTTPException):
            self._deny("EGRESS_UPSTREAM_FAILED", 502)
            return
        self.send_response(response.status)
        for key, value in response.getheaders():
            # Set-Cookie 只沿当前 Executor 请求链转发，Proxy 不记录它到日志或持久化输出。
            if key.lower() not in {"connection", "transfer-encoding", "location", "content-length"}:
                self.send_header(key, value)
        location = response.getheader("Location")
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(response_body)

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_PATCH = _forward
    do_DELETE = _forward
    do_HEAD = _forward
    do_OPTIONS = _forward

    def do_CONNECT(self) -> None:
        self._deny("EGRESS_CONNECT_NOT_SUPPORTED")

    def log_message(self, _format: str, *_args) -> None:
        """禁止默认日志记录完整 URL 和 Query，避免 Secret 泄露。"""

        return


def main() -> None:
    """启动仅在 Executor 内部网络可访问的代理。"""

    ThreadingHTTPServer(("0.0.0.0", 5011), ProxyHandler).serve_forever()


if __name__ == "__main__":
    main()
