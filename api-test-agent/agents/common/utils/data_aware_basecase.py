"""
数据感知型测试用例执行器

功能：
    - 继承BaseTestCase的所有功能
    - 支持从用例中提取_test_data字段
    - 自动将测试数据注入执行上下文
    - 在变量替换阶段合并数据

不包含：
    - 任何断言执行逻辑
    - 断言验证逻辑
    - 响应结果比对

使用示例：
    from agents.common.utils.data_aware_basecase import DataAwareBaseTestCase
    from agents.common.utils.test_result import TestResult

    # 用例数据（包含_test_data字段）
    case_data = {
        "name": "用户名长度边界测试",
        "request": {
            "method": "POST",
            "url": "/api/user/login",
            "body": {
                "username": "${{username}}",
                "password": "${{password}}"
            }
        },
        "_test_data": {
            "username": "abcdefghijklmnopqrs"  # 19位
        }
    }

    result = TestResult("测试用例", None)
    executor = DataAwareBaseTestCase(
        case_data,
        result,
        {"base_url": "http://test.com"},
        None,
        test_data=case_data.get("_test_data")
    )
    executor.run()
"""

from agents.common.utils.basecase import BaseTestCase
from agents.common.utils.test_result import TestResult
from agents.common.utils.database_client import DBClient


class DataAwareBaseTestCase(BaseTestCase):
    """
    数据感知型用例执行器

    继承自BaseTestCase，增强点：
    1. 构造函数支持可选的test_data参数
    2. replace_variables方法增强，自动将_test_data注入执行上下文
    3. 不修改父类的任何原有逻辑

    不包含断言执行逻辑
    """

    def __init__(
        self,
        case_data: dict,
        result: TestResult,
        test_env_global: dict,
        db: DBClient,
        test_data: dict = None
    ):
        """
        初始化数据感知执行器

        Args:
            case_data: 用例数据字典
            result: 测试结果对象
            test_env_global: 全局测试环境变量字典
            db: 数据库客户端实例
            test_data: 测试数据字典（可选），不传则从case_data中提取或为空
        """
        # 调用父类构造函数（原有逻辑完全不变）
        super().__init__(case_data, result, test_env_global, db)

        # 新增：测试数据
        # 优先使用传入的test_data，其次尝试从case_data中提取
        if test_data is None:
            test_data = case_data.get("_test_data", {})
        self.test_data = test_data or {}

    def replace_variables(self, api_info: dict) -> dict:
        """
        增强版变量替换

        增强点：
        1. 先将_test_data中的数据注入到test_env_global
        2. 然后执行父类的变量替换逻辑

        不修改父类的任何替换逻辑

        Args:
            api_info: API请求信息字典

        Returns:
            替换后的API请求信息
        """
        # 增强点：将测试数据注册到执行上下文
        if self.test_data:
            self.result.add_info_log(
                f"【数据注入】加载测试数据: {list(self.test_data.keys())}"
            )
            for key, value in self.test_data.items():
                self.test_env_global[key] = value
                self.result.add_info_log(f"  - {key} = {value}")

        # 调用父类的变量替换（原有逻辑完全不变）
        return super().replace_variables(api_info)

    def run(self):
        """
        执行用例

        继承自BaseTestCase.run()，不新增任何断言逻辑

        执行流程：
        1. 执行前置依赖接口
        2. 执行前置脚本（setup_script）
        3. 替换变量引用（会先注入_test_data）
        4. 发送HTTP请求
        5. 执行后置脚本（teardown_script）
        6. 记录执行完成

        不包含任何断言验证逻辑
        """
        # 执行前置依赖接口
        self.execute_preconditions()

        # 获取主请求信息
        case_api_info = self.case_data.get("request", {})

        # 执行前置脚本
        self.execute_setup_script(case_api_info)

        # 替换变量（会先注入_test_data）
        case_api_info = self.replace_variables(case_api_info)

        # 发送请求
        response = self.request_api(case_api_info)

        # 执行后置脚本
        self.execute_teardown_script(response)

        # 记录执行完成（探索模式）
        self.result.add_info_log(f"用例执行完成，响应状态码: {response.status_code}")
