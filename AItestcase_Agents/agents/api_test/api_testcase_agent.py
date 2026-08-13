"""
API接口自动化测试完整执行入口
流程：上传文档 → AI解析 → 生成用例 → 执行测试 → 生成报告
"""
import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from agents.api_test.parsers.ai_parser_api_document import AIAPIDocumentParser
from agents.api_test.workflows.api_case_generator_main_workflow import ApiCaseGeneratoMainWorkFlow


class APITestCaseExecutor:
    """API测试用例执行完整流程"""

    def __init__(
        self,
        api_doc_path: str,
        test_env: dict,
        db_config: list,
        additional_info: dict = None,
        interface_id: int = None,
        persist_to_database: bool | None = None,
    ):
        """
        初始化API测试执行器
        Args:
            api_doc_path: API文档路径
            test_env: 测试环境配置（如 base_url）
            db_config: 数据库配置
            additional_info: 额外配置信息
            interface_id: 接口ID（用于数据库关联）。
            persist_to_database: 是否写入数据库；None 保持旧命令行入口的写入行为，平台必须显式传值。
        """
        self.api_doc_path = api_doc_path
        self.test_env = test_env
        self.db_config = db_config
        self.additional_info = additional_info or {}
        self.interface_id = interface_id
        self.persist_to_database = True if persist_to_database is None else persist_to_database
        self.api_info = None
        self.workflow_result = None
        self.execution_result = None

    def read_api_document(self) -> str:
        """读取API文档内容"""
        print("=" * 60)
        print("【步骤1】读取API文档")
        print("=" * 60)

        if not os.path.exists(self.api_doc_path):
            raise FileNotFoundError(f"API文档不存在: {self.api_doc_path}")

        with open(self.api_doc_path, 'r', encoding='utf-8') as f:
            content = f.read()

        print(f"文档路径: {self.api_doc_path}")
        print(f"文档长度: {len(content)} 字符")
        print(f"文档内容预览:\n{content[:500]}...")
        print()
        return content

    def parse_api_document(self, document_content: str) -> dict:
        """使用AI解析API文档"""
        print("=" * 60)
        print("【步骤2】AI解析API文档")
        print("=" * 60)

        parser = AIAPIDocumentParser()
        self.api_info = parser.parser(document_content)

        print(f"解析完成，接口数量: {len(self.api_info) if isinstance(self.api_info, list) else 1}")
        if isinstance(self.api_info, dict):
            print(f"接口路径: {self.api_info.get('path')}")
            print(f"请求方法: {self.api_info.get('method')}")
            print(f"接口描述: {self.api_info.get('summary')}")
        print()
        return self.api_info

    def generate_test_cases(self, api_info: dict, preconditions: list = None) -> dict:
        """生成基础用例和可执行用例"""
        print("=" * 60)
        print("【步骤3】生成测试用例")
        print("=" * 60)

        workflow = ApiCaseGeneratoMainWorkFlow().create_workflow()

        api_infos = api_info if isinstance(api_info, list) else [api_info]
        base_interface_id = self.interface_id
        if self.persist_to_database and base_interface_id is None:
            base_interface_id = int(datetime.now().timestamp() * 1000)
        all_api_cases = []
        all_base_cases = []
        persistence_statuses = []

        for index, single_api_info in enumerate(api_infos):
            interface_id = base_interface_id + index if base_interface_id is not None else None
            workflow_result = workflow.invoke({
                "api_info": json.dumps(single_api_info, ensure_ascii=False),
                "preconditions": preconditions or [],
                "db_config": self.db_config,
                "additional_info": self.additional_info,
                "test_data": self.test_env,
                "interface_id": interface_id,
                "persist_to_database": self.persist_to_database,
            })

            api_case_list = workflow_result.get("api_case_list", [])
            if isinstance(api_case_list, list):
                all_api_cases.extend(case for case in api_case_list if case)
            all_base_cases.extend(workflow_result.get("base_cases", []) or [])
            persistence_statuses.extend(workflow_result.get("database_persist_statuses", []) or [])

        self.workflow_result = {
            "api_case_list": all_api_cases,
            "base_cases": all_base_cases,
            "database_persist_statuses": persistence_statuses,
        }
        api_case_list = all_api_cases
        print(f"用例生成完成，共生成 {len(api_case_list)} 条可执行用例")
        print()
        return self.workflow_result

    def execute_test_cases(self) -> dict:
        """执行生成的测试用例"""
        # MVP 解析/生成路径不得加载真实执行依赖；仅旧命令行显式执行时延迟导入。
        from agents.common.utils.api_testcase_execute import TestExecutor

        print("=" * 60)
        print("【步骤4】执行测试用例")
        print("=" * 60)

        executor = TestExecutor(
            test_env_global=self.test_env,
            db_config=self.db_config
        )

        self.execution_result = executor.execute_workflow_cases(
            workflow_state=self.workflow_result,
            suite_name="API工作流生成用例"
        )

        self.print_execution_summary()
        print()
        return self.execution_result

    def print_execution_summary(self):
        """打印执行摘要"""
        if not self.execution_result:
            return

        summary = self.execution_result.get("summary", {})
        results = self.execution_result.get("results", [])

        print("-" * 40)
        print("【执行结果摘要】")
        print("-" * 40)
        print(f"总用例数: {summary.get('total', 0)}")
        print(f"成功: {summary.get('success', 0)}")
        print(f"失败: {summary.get('fail', 0)}")
        print(f"错误: {summary.get('error', 0)}")
        print(f"跳过: {summary.get('skip', 0)}")
        print(f"总耗时: {summary.get('duration', 0):.2f}秒")
        print("-" * 40)

        for i, result in enumerate(results, 1):
            status_icon = "OK" if result.status == "success" else "FAIL" if result.status == "failed" else "WARN"
            print(f"[{status_icon}] {i}. {result.case_name} - {result.status}")
            if result.error_message:
                print(f"   错误: {result.error_message[:100]}...")

    def generate_report(self) -> dict:
        """生成测试报告"""
        print("=" * 60)
        print("【步骤5】生成测试报告")
        print("=" * 60)

        if not self.execution_result:
            print("没有执行结果可生成报告")
            return {}

        summary = self.execution_result.get("summary", {})
        results = self.execution_result.get("results", [])

        report = {
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "api_doc_path": self.api_doc_path,
            "summary": {
                "total": summary.get("total", 0),
                "success": summary.get("success", 0),
                "fail": summary.get("fail", 0),
                "error": summary.get("error", 0),
                "skip": summary.get("skip", 0),
                "duration": summary.get("duration", 0),
                "pass_rate": f"{(summary.get('success', 0) / max(summary.get('total', 1), 1) * 100):.2f}%"
            },
            "test_results": []
        }

        for result in results:
            test_result = {
                "case_name": result.case_name,
                "case_id": result.case_id,
                "status": result.status,
                "duration": result.duration,
                "start_time": datetime.fromtimestamp(result.start_time).strftime("%Y-%m-%d %H:%M:%S") if result.start_time else None,
                "end_time": datetime.fromtimestamp(result.end_time).strftime("%Y-%m-%d %H:%M:%S") if result.end_time else None,
                "error_message": result.error_message,
                "api_requests": []
            }

            for req in result.api_requests_info:
                test_result["api_requests"].append({
                    "url": req.get("url"),
                    "method": req.get("method"),
                    "status_code": req.get("status_code")
                })

            report["test_results"].append(test_result)

        self.save_report(report)
        self.print_report(report)
        print()
        return report

    def save_report(self, report: dict):
        """保存报告到文件"""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "output", "test_reports")
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = os.path.join(output_dir, f"test_report_{timestamp}.json")

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"报告已保存: {report_file}")

    def print_report(self, report: dict):
        """打印报告"""
        print("-" * 60)
        print("【测试报告】")
        print("-" * 60)
        print(f"报告时间: {report.get('report_time')}")
        print(f"API文档: {report.get('api_doc_path')}")
        print("-" * 60)
        print("【汇总统计】")
        summary = report.get("summary", {})
        print(f"  总用例数: {summary.get('total')}")
        print(f"  通过: {summary.get('success')} ({summary.get('pass_rate')})")
        print(f"  失败: {summary.get('fail')}")
        print(f"  错误: {summary.get('error')}")
        print(f"  跳过: {summary.get('skip')}")
        print(f"  总耗时: {summary.get('duration', 0):.2f}秒")
        print("-" * 60)
        print("【用例详情】")
        for i, result in enumerate(report.get("test_results", []), 1):
            status_icon = "OK" if result["status"] == "success" else "FAIL" if result["status"] == "failed" else "WARN"
            print(f"  {i}. [{status_icon}] {result['case_name']}")
            print(f"     状态: {result['status']} | 耗时: {result['duration']:.2f}s")
            if result.get('error_message'):
                print(f"     错误: {result['error_message'][:80]}...")
        print("-" * 60)

    def run(self) -> dict:
        """运行完整流程"""
        print()
        print("#" * 60)
        print("#" + " " * 15 + "API接口自动化测试系统" + " " * 15 + "#")
        print("#" * 60)
        print()

        try:
            document_content = self.read_api_document()
            api_info = self.parse_api_document(document_content)
            self.generate_test_cases(api_info)
            self.execute_test_cases()
            report = self.generate_report()

            print()
            print("#" * 60)
            print("#" + " " * 18 + "测试流程完成" + " " * 20 + "#")
            print("#" * 60)
            print()

            return report

        except Exception as e:
            print()
            print("=" * 60)
            print(f"【错误】执行过程中出现异常: {e}")
            print("=" * 60)
            import traceback
            traceback.print_exc()
            raise


if __name__ == '__main__':
    API_DOC_PATH = r"PRD\ApiDocument\LoginApi_Doc.md"

    TEST_ENV = {
        "base_url": "http://shop-xo.hctestedu.com/index.php?s=",
        "application": "web",
        "application_client_type": "PC"
    }

    DB_CONFIG = [
        {
            "type": "mysql",
            "name": "localhost",
            "config": {
                "host": "localhost",
                "port": 3306,
                "user": "root",
                "password": "123456",
                "database": "test",
            }
        }
    ]

    ADDITIONAL_INFO = {
        "项目名称": "登录系统测试",
        "模块名称": "用户登录",
        "备注": "测试登录接口功能"
    }

    INTERFACE_ID = 999995

    executor = APITestCaseExecutor(
        api_doc_path=API_DOC_PATH,
        test_env=TEST_ENV,
        db_config=DB_CONFIG,
        additional_info=ADDITIONAL_INFO,
        interface_id=INTERFACE_ID,
    )

    report = executor.run()
