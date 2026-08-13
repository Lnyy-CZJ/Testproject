import copy
import json
import os
import sys
import time
import traceback
from typing import List

import pymysql

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from agents.common.utils.basecase import BaseTestCase
from agents.common.utils.database_client import DBClient
from agents.common.utils.test_result import TestResult

try:
    from agents.common.utils.data_aware_basecase import DataAwareBaseTestCase
    HAS_DATA_AWARE_EXECUTOR = True
except ImportError:
    HAS_DATA_AWARE_EXECUTOR = False


class TestExecutor:
    """Test case executor."""

    def __init__(self, test_env_global: dict, db_config: list):
        self.results: List[TestResult] = []
        self.summary = {
            "total": 0,
            "success": 0,
            "fail": 0,
            "error": 0,
            "skip": 0,
            "duration": 0,
        }
        self.test_env_global = copy.deepcopy(test_env_global) if test_env_global else {}
        self.db_config = db_config or []
        self.db = DBClient(self.db_config)

    def _get_mysql_writeback_config(self):
        for db_item in self.db_config:
            if db_item.get("type") == "mysql":
                return dict(db_item.get("config", {}))
        return None

    def _sync_case_result_to_db(self, case_id, result: TestResult):
        if not case_id:
            return

        db_params = self._get_mysql_writeback_config()
        if not db_params:
            result.add_warning_log("未找到 mysql 数据库配置，跳过 real_response 回写")
            return

        last_request = result.api_requests_info[-1] if result.api_requests_info else None
        real_response_dict = {
            "status_code": getattr(last_request, "status_code", None),
            "response_body": getattr(last_request, "response_body", None),
            "error_message": result.error_message,
        }
        real_response_json = json.dumps(real_response_dict, ensure_ascii=False, default=str)

        connection = None
        cursor = None
        try:
            db_params.setdefault("charset", "utf8mb4")
            connection = pymysql.connect(**db_params)
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE api_test_case SET real_response = %s, status = %s WHERE id = %s",
                (real_response_json, result.status, case_id),
            )
            connection.commit()
        except Exception as exc:
            result.add_error_log(f"回写 real_response 失败: {exc}")
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    @staticmethod
    def _serialize_api_request_info(result: TestResult):
        serialized_requests = []
        for api_request in result.api_requests_info:
            serialized_requests.append(
                {
                    "response_body": api_request.response_body,
                    "url": api_request.url,
                    "method": api_request.method,
                    "headers": api_request.headers,
                    "params": api_request.params,
                    "body": api_request.body,
                    "case_id": api_request.case_id,
                    "status_code": api_request.status_code,
                }
            )
        result.api_requests_info = serialized_requests

    def execute_test_case(self, case_data: dict) -> TestResult:
        """Execute a single test case."""
        case_name = case_data.get("name")
        case_id = case_data.get("id")
        result = TestResult(case_name, case_id)

        if case_data.get("skip"):
            result.status = "skip"
            result.add_info_log(f"【跳过用例】：{case_name}")
            self._sync_case_result_to_db(case_id, result)
            self._serialize_api_request_info(result)
            return result

        result.start_time = time.time()
        result.add_info_log(f"【开始执行用例】：{case_name}")
        try:
            # 提取_test_data字段（用于数据驱动）
            test_data = case_data.get("_test_data", {})

            # 根据是否有test_data选择执行器
            if HAS_DATA_AWARE_EXECUTOR and test_data:
                # 使用数据感知执行器
                case_run = DataAwareBaseTestCase(
                    case_data,
                    result,
                    self.test_env_global,
                    self.db,
                    test_data=test_data
                )
            else:
                # 使用原有执行器（向后兼容）
                case_run = BaseTestCase(case_data, result, self.test_env_global, self.db)

            case_run.run()
        except AssertionError as exc:
            result.status = "failed"
            result.error_message = str(exc)
            result.traceback = traceback.format_exc()
            result.add_error_log(f"用例 {case_name} 断言失败，错误信息：{exc}")
        except Exception as exc:
            result.status = "error"
            result.error_message = str(exc)
            result.traceback = traceback.format_exc()
            result.add_error_log(f"用例 {case_name} 执行异常，错误信息：{exc}")
        else:
            result.status = "success"
            result.add_info_log(f"【执行通过】：用例 {case_name}")
        finally:
            result.end_time = time.time()
            result.duration = result.end_time - result.start_time

        self._sync_case_result_to_db(case_id, result)
        self._serialize_api_request_info(result)
        return result

    def execute_test_suite(self, suite_data: dict):
        """Execute a test suite."""
        start_time = time.time()
        cases_list = suite_data.get("cases_list", [])
        self.summary["total"] = len(cases_list)

        for case_data in cases_list:
            result = self.execute_test_case(case_data)
            self.results.append(result)
            if result.status == "success":
                self.summary["success"] += 1
            elif result.status == "failed":
                self.summary["fail"] += 1
            elif result.status == "error":
                self.summary["error"] += 1
            elif result.status == "skip":
                self.summary["skip"] += 1

        self.summary["duration"] = time.time() - start_time
        return {"results": self.results, "summary": self.summary}

    def execute_workflow_cases(self, workflow_state: dict, suite_name: str = "API工作流生成用例"):
        """Execute generated workflow cases."""
        cases_list = workflow_state.get("api_case_list", []) if workflow_state else []
        runnable_cases = [case for case in cases_list if case]
        self.results = []
        self.summary = {
            "total": 0,
            "success": 0,
            "fail": 0,
            "error": 0,
            "skip": 0,
            "duration": 0,
        }
        return self.execute_test_suite({"suite_name": suite_name, "cases_list": runnable_cases})

    def execute_test_task(self, task_data: dict):
        """Execute a test task."""
        task_start_time = time.time()
        task_summary = {
            "total_suites": 0,
            "total_cases": 0,
            "success_cases": 0,
            "failed_cases": 0,
            "error_cases": 0,
            "skip_cases": 0,
            "duration": 0,
        }

        suite_results = []
        suites_list = task_data.get("suites_list", [])
        task_summary["total_suites"] = len(suites_list)

        for suite_data in suites_list:
            self.results = []
            self.summary = {
                "total": 0,
                "success": 0,
                "fail": 0,
                "error": 0,
                "skip": 0,
                "duration": 0,
            }
            suite_result = self.execute_test_suite(suite_data)
            suite_result["suite_id"] = suite_data.get("id")
            suite_result["suite_name"] = suite_data.get("suite_name")
            suite_results.append(suite_result)

            task_summary["total_cases"] += suite_result["summary"]["total"]
            task_summary["success_cases"] += suite_result["summary"]["success"]
            task_summary["failed_cases"] += suite_result["summary"]["fail"]
            task_summary["error_cases"] += suite_result["summary"]["error"]
            task_summary["skip_cases"] += suite_result["summary"]["skip"]

        task_summary["duration"] = time.time() - task_start_time
        return {
            "task_id": task_data.get("id"),
            "task_name": task_data.get("task_name"),
            "task_summary": task_summary,
            "suite_results": suite_results,
        }
