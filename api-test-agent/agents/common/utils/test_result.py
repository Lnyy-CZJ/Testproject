
import logging
from typing import List

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建一个日志输出渠道，输出到控制台
console_handler = logging.StreamHandler()
# 设置日志输出渠道的等级为INFO
console_handler.setLevel(logging.INFO)
# 设置日志输出格式
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
# 将日志输出渠道添加到日志对象中
logger.addHandler(console_handler)


class APIRequestInfo:
    """记录每个接口的请求信息"""

    def __init__(self, interface_id):
        self.case_id = interface_id
        # 完整请求地址
        self.url = ""
        # 请求方法
        self.method = ""
        # 请求头
        self.headers = {}
        # 请求参数
        self.params = {}
        # 请求体
        self.body = {}
        # 响应结果
        self.response_body = {}
        # 响应状态码
        self.status_code = 0


class TestResult:
    """用例执行结果记录(每条用例执行的结果)"""

    def __init__(self, case_name, case_id):
        self.case_id = case_id  # 用例id
        self.case_name = case_name  # 用例名称
        self.status = "unknown"  # passed / failed / error / skipped
        self.error_message = ""  # 错误信息
        self.traceback = ""  # 异常堆栈信息
        self.start_time = None  # 用例执行开始时间
        self.end_time = None  # 用例执行结束时间
        self.duration = None  # 用例执行时长
        self.logs = []  # 用例执行的详细日志
        self.api_requests_info: List[APIRequestInfo] = []  # 记录用例所有接口的请求和响应信息

    def add_error_log(self, log):
        """"""
        self.logs.append({"level": "error", "message": log})
        # 同步输出到控制台/文件
        logger.error(log)

    def add_info_log(self, log):
        """"""
        self.logs.append({"level": "info", "message": log})
        # 同步输出到控制台/文件
        logger.info(log)

    def add_debug_log(self, log):
        """"""
        self.logs.append({"level": "debug", "message": log})
        # 同步输出到控制台/文件
        logger.debug(log)

    def add_warning_log(self, log):
        """"""
        self.logs.append({"level": "warning", "message": log})
        # 同步输出到控制台/文件
        logger.warning(log)

    def add_critical_log(self, log):
        """"""
        self.logs.append({"level": "critical", "message": log})
        # 同步输出到控制台/文件
        logger.critical(log)
