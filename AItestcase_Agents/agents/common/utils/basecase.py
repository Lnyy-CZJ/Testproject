import re
import traceback
from urllib.parse import urlsplit

import jmespath
from func_timeout import FunctionTimedOut, func_timeout
from requests.sessions import Session
from requests_toolbelt import MultipartEncoder

from agents.common.tools import global_tools as global_function
from agents.common.utils.database_client import DBClient
from agents.common.utils.test_result import APIRequestInfo, TestResult

"""
定义单条接口测试用例执行的核心逻辑
    1、检查是否有前置依赖接口
        - 有的话就先请求前置依赖的接口，提取依赖字段进行保存
         遍历出来每一个接口
            - 前置脚本执行
            - 替换用例参数中的变量引用
            - 发送请求（request）
            - 后置脚本执行
            - 后面接口依赖字段，数据的提取
    2、执行用例前置脚本
    3、替换用例参数中的变量引用(依赖字段，测试环境中的数据，base_url)
    4、发送请求（request）
    5、后置脚本执行
    6、记录实际响应结果（已移除断言）


问题点： 在执行后置脚本的时候，如何获取前置脚本中提取的变量(前后置脚本中的数据互通)
"""


class ScriptExecutionTimeoutError(RuntimeError):
    """Raised when generated setup/teardown script runs too long."""


class _EmptyResponse:
    """URL 为空时的默认响应对象，模拟 requests.Response 的最小接口"""

    status_code = None
    text = ""
    headers = {}

    def json(self):
        return None


class BaseTestCase:
    """核心执行器 for a single API test case."""

    def __init__(self, case_data: dict, result: TestResult, test_env_global: dict, db: DBClient):
        self.case_data = case_data or {}
        self.result = result
        self.test_env_global = test_env_global or {}
        self.http = Session()
        self.db = db
        # 调试日志：检查 test_env_global 是否包含 base_url
        if 'base_url' not in self.test_env_global:
            self.result.add_warning_log(f"警告：test_env_global 中未找到 base_url，当前包含的键: {list(self.test_env_global.keys())}")
        else:
            self.result.add_info_log(f"test_env_global 包含 base_url: {self.test_env_global.get('base_url')}")

    def execute_preconditions(self):
        """Execute prerequisite API calls."""
        self.result.add_info_log("开始执行用例前置依赖接口")
        for api in self.case_data.get("preconditions") or []:
            api_info = api.get("request", {})
            self.execute_setup_script(api_info)
            api_info = self.replace_variables(api_info)
            response = self.request_api(api_info)
            self.execute_teardown_script(response)
            self.extract_data(api, response)
        self.result.add_info_log("前置依赖接口执行完成")

    def _safe_exec(self, script: str, script_globals: dict):
        """Execute dynamic script with a hard timeout."""
        if not script:
            return
        try:
            func_timeout(5, exec, args=(script, script_globals))
        except FunctionTimedOut as exc:
            raise ScriptExecutionTimeoutError(
                "脚本执行超时，已阻断本次执行。请检查是否存在死循环或长时间阻塞逻辑。"
            ) from exc

    def _build_script_globals(self):
        env = self.test_env_global

        def _env_get(key, default=""):
            return env.get(key, default)

        return {
            "test": self,
            "db": self.db,
            "global_function": global_function,
            "test_context": self,
            "test_env_variables": self.test_env_global,
            "get": _env_get,
        }

    def _run_script(self, api_info):
        """Run setup script first and teardown script after response is sent in."""
        api_info = api_info or {}
        script_globals = self._build_script_globals()

        setup_script = api_info.get("setup_script", "")
        if setup_script:
            self.result.add_info_log(f"开始执行前置脚本:\n{setup_script}")
            try:
                self._safe_exec(setup_script, script_globals)
            except Exception as exc:
                self.result.add_error_log(f"前置脚本执行异常: {exc}")
                raise

        response = yield

        teardown_script = api_info.get("teardown_script", "")
        if teardown_script:
            self.result.add_info_log(f"开始执行后置脚本:\n{teardown_script}")
            try:
                script_globals["response"] = response
                self._safe_exec(teardown_script, script_globals)
            except Exception as exc:
                self.result.add_error_log(f"后置脚本执行异常: {exc}")
                raise

    def execute_setup_script(self, api_info):
        """Run case setup script."""
        self.script_executor = self._run_script(api_info)
        next(self.script_executor)

    def execute_teardown_script(self, response):
        """Run case teardown script."""
        try:
            self.script_executor.send(response)
        except StopIteration:
            pass
        finally:
            if hasattr(self, "script_executor"):
                del self.script_executor

    def _deep_replace(self, data, pattern):
        """Safely replace `${{var}}` placeholders while preserving native types."""
        if isinstance(data, dict):
            return {key: self._deep_replace(value, pattern) for key, value in data.items()}
        if isinstance(data, list):
            return [self._deep_replace(item, pattern) for item in data]
        if not isinstance(data, str):
            return data

        replaced = data
        for match in re.finditer(pattern, data):
            placeholder = match.group(0)
            variable_name = match.group(1)
            value = self.test_env_global.get(variable_name, "")
            self.result.add_info_log(
                f"变量替换: {placeholder} -> {variable_name}，值为: {value}"
            )
            if replaced == placeholder:
                return value
            replaced = replaced.replace(placeholder, str(value))
        return replaced

    def replace_variables(self, api_info: dict) -> dict:
        """Replace variable placeholders in request payload."""
        self.result.add_info_log(f"【变量替换前】test_env_global 内容: {self.test_env_global}")
        self.result.add_info_log(f"【变量替换前】api_info 请求信息: {api_info}")
        self.result.add_info_log("开始替换请求参数中的变量引用")
        if not api_info:
            return {}

        # 支持四种格式的变量占位符: 
        # 1. ${{var}} - 双花括号带美元符号
        # 2. {{var}} - 双花括号不带美元符号
        # 3. ${var} - 单花括号带美元符号
        # 4. {var} - 单花括号不带美元符号
        # 使用 [^}]+ 而不是 .+? 来避免匹配 } 字符
        # 注意：必须按复杂程度从高到低排列，避免部分匹配
        patterns = [r"\${{([^}]+)}}", r"{{([^}]+)}}", r"\${([^}]+)}", r"{([^}]+)}"]
        for field in ("url", "base_url", "headers", "params", "body", "files"):
            original_value = api_info.get(field)
            value = original_value
            for pattern in patterns:
                value = self._deep_replace(value, pattern)
            api_info[field] = value
            if original_value != value:
                self.result.add_info_log(f"【变量替换成功】{field}: {original_value} -> {value}")
            else:
                self.result.add_info_log(f"【变量替换无变化】{field}: {original_value}")
        self.result.add_info_log(f"【变量替换后】api_info: {api_info}")
        return api_info

    def _join_request_url(self, base_url, request_url):
        """
        Build the final request URL with duplicate-base protection.

        Args:
            base_url: Resolved environment base URL.
            request_url: Resolved URL/path from the executable case.

        Returns:
            str: Final URL sent to requests.

        Exception handling:
            The method never raises for malformed input; it returns the safest
            string form so the caller can log or skip empty URLs consistently.
        """
        base_url = "" if base_url is None else str(base_url).strip()
        request_url = "" if request_url is None else str(request_url).strip()
        if not request_url:
            return base_url

        request_parts = urlsplit(request_url)
        if request_parts.scheme in {"http", "https"}:
            return request_url

        for prefix in (base_url, "${{base_url}}", "{{base_url}}", "${base_url}", "{base_url}"):
            if prefix and request_url.startswith(prefix):
                request_url = request_url[len(prefix):].strip()

        for marker in ("/index.php?s=", "index.php?s="):
            if request_url.startswith(marker) and base_url.endswith("index.php?s="):
                request_url = request_url[len(marker):]

        if request_url.startswith("?s=") and base_url.endswith("index.php?s="):
            request_url = request_url[3:]

        if base_url and request_url and not request_url.startswith("/"):
            request_url = f"/{request_url}"
        return f"{base_url}{request_url}"

    def request_api(self, api_info):
        """Send HTTP request for the current test step."""
        api_request_info = APIRequestInfo(interface_id=api_info.get("interface_id"))
        method = api_info.get("method", "GET").upper()
        api_request_info.method = method

        url = self._join_request_url(
            api_info.get("base_url", self.test_env_global.get("base_url", "")),
            api_info.get("url", ""),
        )
        api_request_info.url = url

        # 防御性校验：URL 为空时跳过请求，返回默认空响应
        if not url or not url.strip():
            self.result.add_warning_log("URL 为空，跳过 HTTP 请求（仅执行脚本）")
            api_request_info.status_code = None
            api_request_info.response_body = None
            self.result.api_requests_info.append(api_request_info)
            return _EmptyResponse()

        raw_headers = api_info.get("headers", {}) or {}
        # 确保所有 header 值为字符串，避免 requests 库因非字符串类型抛出 InvalidHeader
        headers = {k: str(v) if not isinstance(v, str) else v for k, v in raw_headers.items()}
        api_request_info.headers = headers
        params = api_info.get("params", {}) or {}
        api_request_info.params = params
        body = api_info.get("body", {}) or {}
        files = api_info.get("files", {}) or {}
        content_type = headers.get("Content-Type", "").lower()

        self.result.add_info_log(
            f"开始发送请求: url={url}, method={method}, headers={headers}, params={params}, body={body}"
        )

        api_request_info.body = body
        try:
            if content_type.startswith("application/json"):
                response = self.http.request(method=method, url=url, headers=headers, params=params, json=body)
            elif content_type.startswith("application/xml"):
                response = self.http.request(method=method, url=url, headers=headers, params=params, data=body)
            elif content_type.startswith("application/x-www-form-urlencoded"):
                response = self.http.request(method=method, url=url, headers=headers, params=params, data=body)
            elif content_type.startswith("multipart/form-data"):
                new_files = {}
                opened_files = []
                try:
                    for key, value in files.items():
                        if isinstance(value, list) and len(value) == 3:
                            file_name, file_path, file_type = value
                            file_content = open(file_path, "rb")
                            opened_files.append(file_content)
                            new_files[key] = (file_name, file_content, file_type)
                        else:
                            new_files[key] = value
                    encoder = MultipartEncoder(fields=new_files)
                    headers["Content-Type"] = encoder.content_type
                    response = self.http.request(method=method, url=url, headers=headers, params=params, data=encoder)
                    api_request_info.body = str(encoder)
                finally:
                    for opened_file in opened_files:
                        opened_file.close()
            else:
                response = self.http.request(method=method, url=url, headers=headers, params=params, data=body)
        except Exception as exc:
            api_request_info.status_code = None
            api_request_info.response_body = None
            self.result.api_requests_info.append(api_request_info)
            self.result.add_error_log(f"请求接口异常: {exc}")
            self.result.traceback = traceback.format_exc()
            raise

        api_request_info.status_code = response.status_code
        if response.headers.get("Content-Type", "").lower().startswith("application/json"):
            try:
                api_request_info.response_body = response.json()
            except ValueError:
                api_request_info.response_body = response.text
            body_str = str(api_request_info.response_body)[:500] + "..." if len(str(api_request_info.response_body)) > 500 else str(api_request_info.response_body)
            self.result.add_info_log(
                f"请求响应: status_code={response.status_code}, body={body_str}, headers={dict(response.headers)}"
            )
        else:
            api_request_info.response_body = response.text
            body_str = response.text[:500] + "..." if len(response.text) > 500 else response.text
            self.result.add_info_log(
                f"请求响应: status_code={response.status_code}, body={body_str}, headers={dict(response.headers)}"
            )
        self.result.api_requests_info.append(api_request_info)
        return response

    def extract_data(self, api_info, response):
        """从响应中提取数据到环境变量，兼容 response 为 dict 或 Response 对象"""
        self.result.add_info_log("开始提取响应数据")
        try:
            body = response.json() if callable(getattr(response, "json", None)) else response
        except (ValueError, TypeError):
            body = response if isinstance(response, dict) else {}
        for var_name, jmes_path in api_info.get("extract", []) or []:
            var_value = jmespath.search(jmes_path, body)
            self.test_env_global[var_name] = var_value
            self.result.add_info_log(f"提取成功: {var_name}={var_value}")

    def save_test_env_variables(self, name, value):
        """Persist environment variable for following steps."""
        self.result.add_info_log(f"保存环境变量: {name}={value}")
        self.test_env_global[name] = value

    def get_test_env_variables(self, name):
        """Read environment variable."""
        self.result.add_info_log(f"获取环境变量: {name}")
        return self.test_env_global.get(name)

    def json_extract(self, expr, response):
        """Extract data with jmespath，兼容 response 为 dict 或 Response 对象的场景"""
        try:
            body = response.json() if hasattr(response, "json") and callable(response.json) else response
        except (ValueError, TypeError):
            body = response if isinstance(response, dict) else {}
        value = jmespath.search(expr, body)
        self.result.add_info_log(f"JSON 提取: expr={expr}, result={value}")
        return value

    def re_extract(self, string, pattern):
        """Extract data with regex."""
        match = re.search(pattern, string)
        value = match.group(1) if match else None
        self.result.add_info_log(f"正则提取: pattern={pattern}, result={value}")
        return value

    def run(self):
        """
        执行完整的用例流程（已移除断言）

        流程：
        1. 执行前置依赖接口
        2. 执行前置脚本
        3. 替换变量引用
        4. 发送请求
        5. 执行后置脚本
        6. 提取响应数据
        7. 记录实际响应（不再进行断言验证）
        """
        self.execute_preconditions()
        case_api_info = self.case_data.get("request", {})

        self.execute_setup_script(case_api_info)
        case_api_info = self.replace_variables(case_api_info)
        response = self.request_api(case_api_info)
        self.execute_teardown_script(response)

        self.result.add_info_log("【探索模式】用例执行完成，已记录实际响应，不再进行断言验证")
        self.result.add_info_log(f"实际响应状态码: {response.status_code}")
