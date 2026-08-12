"""测试开发平台运行态冒烟测试。

功能说明:
    验证平台首页、四个工具页面、健康检查以及关键 POST 请求均可通过
    统一入口访问。测试只读取页面并发送最小输入，不保存测试日志。

配置说明:
    PLATFORM_BASE_URL 可覆盖默认的 http://127.0.0.1:8080。
"""

import json
import os
import unittest
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener


BASE_URL = os.environ.get("PLATFORM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
COOKIE_JAR = CookieJar()
OPENER = build_opener(HTTPCookieProcessor(COOKIE_JAR))


def request(path, data=None, content_type=None):
    """向平台发送请求并返回状态码、响应头和解码后的正文。"""
    headers = {"Accept": "*/*"}
    if content_type:
        headers["Content-Type"] = content_type
    if data is not None:
        csrf = next((cookie.value for cookie in COOKIE_JAR if cookie.name == "tp_csrf"), None)
        if csrf:
            headers["X-CSRF-Token"] = csrf
    request_object = Request(f"{BASE_URL}{path}", data=data, headers=headers)
    with OPENER.open(request_object, timeout=15) as response:
        return response.status, response.headers, response.read().decode("utf-8")


class NoRedirect(HTTPRedirectHandler):
    """保留原始 302，验证匿名工具入口确实由网关关闭。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def anonymous_status(path):
    """使用无 Cookie、无重定向客户端读取原始状态码。"""

    try:
        build_opener(NoRedirect()).open(f"{BASE_URL}{path}", timeout=15)
    except HTTPError as error:
        return error.code, error.headers
    raise AssertionError("匿名请求意外成功")


class PlatformSmokeTest(unittest.TestCase):
    """从用户统一入口验证平台和四个独立工具的核心连通性。"""

    @classmethod
    def setUpClass(cls):
        """使用本地临时管理员完成统一登录，密码不会写入测试输出。"""

        password = os.environ.get("PLATFORM_SMOKE_PASSWORD")
        if not password:
            password = Path(".runtime-secrets/initial-admin-password").read_text(encoding="utf-8").strip()
        payload = json.dumps({
            "username": os.environ.get("PLATFORM_SMOKE_USERNAME", "admin"),
            "password": password,
        }).encode("utf-8")
        status, _, _ = request("/api/v1/auth/login", payload, "application/json")
        if status != 200:
            raise AssertionError("平台冒烟账号登录失败")

    def test_anonymous_tool_and_catalog_access_fail_closed(self):
        """匿名页面跳登录，匿名目录 API 返回 401。"""

        page_status, page_headers = anonymous_status("/truthy-search/")
        api_status, _ = anonymous_status("/api/v1/tools")
        self.assertEqual(page_status, 302)
        self.assertTrue(page_headers["Location"].startswith("/login"))
        self.assertEqual(api_status, 401)

    def test_platform_home_and_dynamic_tool_catalog_are_available(self):
        status, _, body = request("/")
        api_status, _, api_body = request("/api/v1/tools")

        self.assertEqual(status, 200)
        self.assertIn("测试开发平台", body)
        self.assertIn('id="root"', body)
        self.assertEqual(api_status, 200)
        tool_ids = [item["id"] for item in json.loads(api_body)["items"]]
        self.assertEqual(
            tool_ids,
            ["trackevents", "log-filter", "truthy-search", "api-autotest"],
        )

    def test_platform_health_endpoints_are_available(self):
        live_status, _, live_body = request("/api/v1/health/live")
        ready_status, _, ready_body = request("/api/v1/health/ready")

        self.assertEqual(live_status, 200)
        self.assertEqual(json.loads(live_body)["status"], "ok")
        self.assertEqual(ready_status, 200)
        self.assertEqual(json.loads(ready_body)["status"], "ready")

    def test_trackevents_page_health_and_analysis_are_available(self):
        page_status, _, page = request("/trackevents/")
        health_status, _, health_body = request("/trackevents/health")
        payload = json.dumps({"log_text": "", "expected_counts": {}}).encode("utf-8")
        analyze_status, _, _ = request(
            "/trackevents/api/analyze",
            data=payload,
            content_type="application/json",
        )

        self.assertEqual(page_status, 200)
        self.assertIn("埋点测试工具", page)
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "ok")
        self.assertEqual(analyze_status, 200)

    def test_log_filter_page_health_sample_and_form_are_available(self):
        page_status, _, page = request("/log-filter/")
        health_status, _, health_body = request("/log-filter/health")
        sample_status, _, sample = request("/log-filter/sample")
        form_body = urlencode({"log_text": "", "method": "__ALL__"}).encode("utf-8")
        post_status, _, _ = request(
            "/log-filter/",
            data=form_body,
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(page_status, 200)
        self.assertIn("Log 过滤工具", page)
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "ok")
        self.assertEqual(sample_status, 200)
        self.assertTrue(sample)
        self.assertEqual(post_status, 200)

    def test_truthy_search_page_and_health_are_available(self):
        """只读验证检索评测页面、平台返回入口和 SQLite 健康状态。"""

        page_status, _, page = request("/truthy-search/")
        health_status, _, health_body = request("/truthy-search/health")

        self.assertEqual(page_status, 200)
        self.assertIn("Truthy Search", page)
        self.assertIn('data-app-base-path="/truthy-search"', page)
        self.assertIn("返回平台首页", page)
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "ok")

    def test_api_autotest_page_health_catalog_and_tasks_are_available(self):
        """只读验证接口自动化页面、健康状态、执行目录和任务列表。"""

        page_status, _, page = request("/api-autotest/")
        health_status, _, health_body = request("/api-autotest/health")
        catalog_status, _, catalog_body = request("/api-autotest/api/catalog")
        tasks_status, _, tasks_body = request("/api-autotest/api/tasks")

        self.assertEqual(page_status, 200)
        self.assertIn("接口自动化", page)
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "ok")
        self.assertEqual(catalog_status, 200)
        catalog = json.loads(catalog_body)
        self.assertIn("apis", catalog)
        self.assertIn("cases", catalog)
        self.assertIn("flows", catalog)
        self.assertEqual(tasks_status, 200)
        self.assertIn("items", json.loads(tasks_body))


if __name__ == "__main__":
    unittest.main()
