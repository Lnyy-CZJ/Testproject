"""阶段3 Flask 页面、路由、导入与 Raw API 测试。"""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from analysis_service import AnalysisService
from analysis_store import AnalysisStore
from web_app import RunCoordinator, create_app


def jsonl_bytes(records: list[dict]) -> bytes:
    """把测试记录编码为上传所需的 UTF-8 JSONL。"""

    return "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    ).encode("utf-8")


class RecordingCoordinator:
    """只记录提交，不启动真实线程或 HTTP 请求。"""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.retried: list[tuple[str, str]] = []

    def submit(self, run_id: str) -> None:
        """记录页面提交的 Run ID。"""

        self.submitted.append(run_id)

    def submit_query_retry(self, run_id: str, query_id: str) -> None:
        """记录单条重跑提交，避免 Web 路由测试启动真实线程。"""

        self.retried.append((run_id, query_id))


class CoordinatorClient:
    """为后台协调器测试提供不访问网络的固定成功响应。"""

    def __init__(self) -> None:
        """准备 process_one 所需配置与接口阶段响应。"""

        self.config = SimpleNamespace(
            max_poll_count=2,
            poll_interval_seconds=0.001,
        )
        self.responses = [
            {
                "code": 0,
                "responses": [
                    {"success": True, "code": 0, "data": {"task_id": "task-bg"}}
                ],
            },
            {
                "code": 0,
                "responses": [
                    {
                        "success": True,
                        "code": 0,
                        "data": {"status": "NO_RESULT"},
                    }
                ],
            },
            {
                "code": 0,
                "responses": [
                    {"success": True, "code": 0, "data": {"items": []}}
                ],
            },
        ]

    def call(self, stage: str, params: dict) -> dict:
        """按 Create/Get/List 顺序返回响应。"""

        if not self.responses:
            raise AssertionError(f"未预期的接口调用: {stage} {params}")
        return self.responses.pop(0)


class WebAppTests(unittest.TestCase):
    """验证阶段3最小页面闭环、安全边界和服务器端分页。"""

    def setUp(self):
        """创建独立数据库、Flask 测试客户端和无网络协调器。"""

        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.db_path = self.data_dir / "searchtool.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SEARCH_DATA_DIR": str(self.data_dir),
                "SEARCH_DB_FILE": str(self.db_path),
                "SEARCH_REPORT_DIR": str(self.root / "reports"),
                "SEARCH_ENV_FILE": str(self.root / ".env"),
                "MAX_CONTENT_LENGTH": 1024 * 1024,
                "RECOVER_INTERRUPTED_RUNS": False,
                "SEARCH_REPORT_EXCEL_ENABLED": False,
            }
        )
        self.coordinator = RecordingCoordinator()
        self.app.extensions["run_coordinator"] = self.coordinator
        self.client = self.app.test_client()
        self.store: AnalysisStore = self.app.extensions["analysis_store"]
        self.service: AnalysisService = self.app.extensions["analysis_service"]
        self.store.create_evaluation("eval-web", "Web 阶段3", "测试说明")

    def tearDown(self):
        """关闭后台执行器并清理测试数据。"""

        default_coordinator = self.app.extensions.get("default_run_coordinator")
        if default_coordinator is not None:
            default_coordinator.shutdown(wait=False)
        self.temp_dir.cleanup()

    def test_stage1_datetime_filter_converts_utc_and_tolerates_history(self):
        """展示过滤器转换北京时间，同时兼容空值和非法历史值。"""

        formatter = self.app.jinja_env.filters["format_datetime"]

        self.assertEqual(
            "2026-07-24 14:08:31",
            formatter("2026-07-24T06:08:31.593258+00:00"),
        )
        self.assertEqual(
            "2026-07-24 14:08:31",
            formatter("2026-07-24T06:08:31Z"),
        )
        self.assertEqual("处理中", formatter(None, "处理中"))
        self.assertEqual("legacy-invalid", formatter("legacy-invalid"))

        fallback_app = create_app(
            {
                "TESTING": True,
                "SEARCH_DATA_DIR": str(self.root / "fallback-data"),
                "SEARCH_DB_FILE": str(self.root / "fallback.db"),
                "SEARCH_REPORT_DIR": str(self.root / "fallback-reports"),
                "SEARCH_ENV_FILE": str(self.root / ".env"),
                "SEARCH_DISPLAY_TIMEZONE": "Invalid/Timezone",
                "RECOVER_INTERRUPTED_RUNS": False,
            }
        )
        try:
            self.assertEqual(
                "Asia/Shanghai",
                fallback_app.config["SEARCH_DISPLAY_TIMEZONE"],
            )
            self.assertEqual(
                "2026-07-24 14:08:31",
                fallback_app.jinja_env.filters["format_datetime"](
                    "2026-07-24T06:08:31"
                ),
            )
        finally:
            fallback_app.extensions["default_run_coordinator"].shutdown(
                wait=False
            )

    def import_dataset(self, dataset_id: str = "dataset-web") -> None:
        """通过 Web 上传一个合法 FULL_NAME/FULL_NAME_SOCIAL 数据集。"""

        response = self.client.post(
            "/imports",
            data={
                "import_type": "dataset",
                "dataset_id": dataset_id,
                "name": "Web 数据集",
                "source_file": (
                    io.BytesIO(
                        jsonl_bytes(
                            [
                                {
                                    "input_id": "query-web",
                                    "person_id": "person-web",
                                    "query_stage": "FULL_NAME_SOCIAL",
                                    "clues": [
                                        {
                                            "type": "FULL_NAME",
                                            "value": "Example Person",
                                        },
                                        {
                                            "type": "SOCIAL_LINK",
                                            "value": "https://example.test/person",
                                        },
                                    ],
                                    "additional_details": [],
                                }
                            ]
                        )
                    ),
                    "tasks-web.jsonl",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(302, response.status_code)

    def seed_imported_result(self) -> tuple[str, str, str]:
        """导入一条历史结果，返回 Run、Candidate 与 Raw 标识。"""

        source = self.root / "history-results.jsonl"
        source.write_bytes(
            jsonl_bytes(
                [
                    {
                        "result_schema_version": "1.3",
                        "input_id": "query-history",
                        "person_id": "person-history",
                        "query_stage": "FULL_NAME",
                        "task_id": "task-history",
                        "query_status": "SUCCESS",
                        "result_status": "HAS_CANDIDATES",
                        "candidate_count_total": 1,
                        "candidate_count_listed": 1,
                        "detail_success_count": 1,
                        "detail_failure_count": 0,
                        "task_fields": {
                            "llm_cost": 1.0,
                            "third_party_cost": 2.0,
                            "total_cost": 3.0,
                            "pdl_called": False,
                            "search_duration_ms": 1500,
                        },
                        "raw": {
                            "create_intent_task": {
                                "sequence_no": 1,
                                "request_params": {"clues": []},
                                "response_body": {"future_field": "visible"},
                            },
                            "get_task_history": [],
                            "list_task_candidates": {
                                "sequence_no": 1,
                                "response_body": {"items": []},
                            },
                        },
                        "results": [
                            {
                                "candidate_rank": 1,
                                "candidate_id": "candidate-history",
                                "rank_score": 0.91,
                                "detail_status": "SUCCESS",
                                "detail_error": "",
                                "list_item_raw": {
                                    "candidate_id": "candidate-history"
                                },
                                "detail_data_raw": {
                                    "ui_sections": {
                                        "summary": {
                                            "status": "data",
                                            "data": {
                                                "display_name": "History Person"
                                            },
                                        },
                                        "profile": {
                                            "status": "data",
                                            "data": {"location": "Shanghai"},
                                        },
                                    },
                                    "unknown_new_field": "kept",
                                },
                                "ui_sections": {
                                    "summary": {
                                        "status": "data",
                                        "data": {
                                            "display_name": "History Person"
                                        },
                                    },
                                    "profile": {
                                        "status": "data",
                                        "data": {"location": "Shanghai"},
                                    },
                                },
                            }
                        ],
                    }
                ]
            )
        )
        result = self.service.import_results_jsonl(
            source,
            evaluation_id="eval-web",
            run_label="history",
            system_version="history-v1",
            evaluation_phase="PHASE_1_BASELINE",
            run_id="run-history",
        )
        candidate = self.store.fetch_one(
            "SELECT candidate_pk FROM candidates WHERE run_id = ?",
            (result.object_id,),
        )
        raw = self.store.fetch_one(
            "SELECT raw_id FROM raw_records WHERE run_id = ? ORDER BY collected_at",
            (result.object_id,),
        )
        return result.object_id, candidate["candidate_pk"], raw["raw_id"]

    def test_evaluation_dataset_run_creation_and_active_run_guard(self):
        """页面可创建 Evaluation/执行 Run，并拒绝第二个活动执行。"""

        home = self.client.get("/")
        created = self.client.post(
            "/evaluations/new",
            data={
                "evaluation_id": "eval-created",
                "name": "页面创建评测",
                "notes": "",
                "threshold_profile_id": "",
            },
        )
        self.import_dataset()
        detail = self.client.get("/evaluations/eval-web")
        run_response = self.client.post(
            "/evaluations/eval-web/runs",
            data={
                "dataset_id": "dataset-web",
                "run_label": "candidate",
                "system_version": "web-v1",
                "evaluation_phase": "PHASE_2_POST_OPTIMIZATION",
            },
        )
        run = self.store.fetch_one(
            """
            SELECT run_id, status, evaluation_phase
            FROM runs WHERE source_type = 'EXECUTION'
            """
        )
        duplicate = self.client.post(
            "/evaluations/eval-web/runs",
            data={
                "dataset_id": "dataset-web",
                "run_label": "candidate-2",
                "system_version": "web-v2",
                "evaluation_phase": "PHASE_3_TARGETED_ITERATION",
            },
        )

        self.assertEqual(200, home.status_code)
        self.assertIn("Web 阶段3", home.get_data(as_text=True))
        self.assertEqual(302, created.status_code)
        created_evaluation = self.store.fetch_one(
            """
            SELECT threshold_profile_id, thresholds_json
            FROM evaluations WHERE evaluation_id = 'eval-created'
            """
        )
        self.assertIsNone(created_evaluation["threshold_profile_id"])
        self.assertTrue(
            all(
                value is None
                for stage in json.loads(
                    created_evaluation["thresholds_json"]
                ).values()
                for value in stage.values()
            )
        )
        self.assertEqual(200, detail.status_code)
        self.assertIn("Web 数据集", detail.get_data(as_text=True))
        self.assertEqual(302, run_response.status_code)
        self.assertEqual("PENDING", run["status"])
        self.assertEqual(
            "PHASE_2_POST_OPTIMIZATION",
            run["evaluation_phase"],
        )
        self.assertEqual([run["run_id"]], self.coordinator.submitted)
        self.assertEqual(409, duplicate.status_code)
        self.assertIn("已有执行任务", duplicate.get_data(as_text=True))

    def test_failed_query_can_be_queued_for_retry_in_its_original_run(self):
        """详情页的单条重跑入口复用原 Run，不创建新的执行记录。"""

        self.import_dataset("dataset-query-retry")
        run_id = self.service.create_execution_run(
            evaluation_id="eval-web",
            dataset_id="dataset-query-retry",
            run_label="retry",
            system_version="web-v1",
            evaluation_phase="PHASE_1_BASELINE",
            run_id="run-query-retry",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE runs SET status = 'FAILED' WHERE run_id = ?", (run_id,)
            )
            connection.execute(
                """
                UPDATE run_queries SET status = 'FAILED',
                    result_status = 'EXECUTION_FAILED'
                WHERE run_id = ? AND query_id = 'query-web'
                """,
                (run_id,),
            )

        page = self.client.get(f"/runs/{run_id}/queries/query-web")
        response = self.client.post(f"/runs/{run_id}/queries/query-web/retry")

        self.assertEqual(200, page.status_code)
        self.assertIn("仅重跑此人", page.get_data(as_text=True))
        self.assertEqual(302, response.status_code)
        self.assertEqual([(run_id, "query-web")], self.coordinator.retried)
        self.assertEqual(
            1,
            self.store.fetch_one(
                "SELECT COUNT(*) AS count FROM runs WHERE run_id = ?", (run_id,)
            )["count"],
        )

    def test_stage1_run_person_links_web_workspace_and_save(self):
        """Run 页面可进入人物关联工作区并保存唯一建议。"""

        dataset_path = self.root / "person-links-tasks.jsonl"
        dataset_path.write_bytes(
            jsonl_bytes(
                [
                    {
                        "input_id": "query-person-link",
                        "query_stage": "FULL_NAME",
                        "clues": [
                            {
                                "type": "FULL_NAME",
                                "full_name_query": {
                                    "full_name": "Web Link Person"
                                },
                            }
                        ],
                        "additional_details": [],
                    }
                ]
            )
        )
        self.service.import_dataset_jsonl(
            dataset_path,
            name="人物关联数据集",
            dataset_id="dataset-web-person-links",
        )
        baseline_path = self.root / "person-links-baseline.jsonl"
        baseline_path.write_bytes(
            jsonl_bytes(
                [
                    {
                        "person_id": "person-web-link",
                        "display_name": "Web Link Person",
                        "fields": {
                            "summary_display_name": "Web Link Person"
                        },
                        "baseline_available_fields": [
                            "summary_display_name"
                        ],
                    }
                ]
            )
        )
        self.service.import_baseline_jsonl(
            baseline_path,
            name="人物关联基准",
            baseline_version="baseline-web-person-links",
        )
        run_id = self.service.create_execution_run(
            evaluation_id="eval-web",
            dataset_id="dataset-web-person-links",
            run_label="人物关联页面",
            system_version="phase1",
            evaluation_phase="PHASE_1_BASELINE",
            run_id="run-web-person-links",
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE runs SET status = 'COMPLETED' WHERE run_id = ?",
                (run_id,),
            )

        run_page = self.client.get(f"/runs/{run_id}")
        workspace = self.client.get(
            f"/runs/{run_id}/person-links",
            query_string={"baseline_version": "baseline-web-person-links"},
        )
        saved = self.client.post(
            f"/runs/{run_id}/person-links",
            data={
                "baseline_version": "baseline-web-person-links",
                "changes_json": json.dumps(
                    [
                        {
                            "query_id": "query-person-link",
                            "expected_person_id": None,
                            "person_id": "person-web-link",
                        }
                    ]
                ),
                "sync_dataset": "1",
                "note": "Web阶段1关联",
            },
        )
        stale_page = self.client.post(
            f"/runs/{run_id}/person-links",
            data={
                "baseline_version": "baseline-web-person-links",
                "changes_json": json.dumps(
                    [
                        {
                            "query_id": "query-person-link",
                            "expected_person_id": None,
                            "person_id": "",
                        }
                    ]
                ),
            },
        )
        query = self.store.fetch_one(
            """
            SELECT person_id, person_id_source FROM run_queries
            WHERE run_id = ? AND query_id = 'query-person-link'
            """,
            (run_id,),
        )

        self.assertEqual(200, run_page.status_code)
        self.assertIn("管理人物关联", run_page.get_data(as_text=True))
        self.assertEqual(200, workspace.status_code)
        workspace_html = workspace.get_data(as_text=True)
        self.assertIn("Query 人物关联", workspace_html)
        self.assertIn("Web Link Person", workspace_html)
        self.assertIn("唯一精确建议", workspace_html)
        self.assertEqual(302, saved.status_code)
        self.assertEqual("person-web-link", query["person_id"])
        self.assertEqual("MANUAL_RUN", query["person_id_source"])
        self.assertEqual(409, stale_page.status_code)
        self.assertIn("已被其他页面修改", stale_page.get_data(as_text=True))

    def test_stage5_evaluation_thresholds_web_update_and_validation(self):
        """旧参考线接口保持兼容，非法值不会覆盖已有快照。"""

        updated = self.client.post(
            "/evaluations/eval-web/thresholds",
            data={
                (
                    "threshold__FULL_NAME__"
                    "min_retrieval_success"
                ): "0.75",
                (
                    "threshold__FULL_NAME__"
                    "max_average_total_cost"
                ): "6.5",
                (
                    "threshold__FULL_NAME_SOCIAL__"
                    "min_matched_accuracy"
                ): "0.9",
            },
        )
        stored = json.loads(
            self.store.fetch_one(
                """
                SELECT thresholds_json FROM evaluations
                WHERE evaluation_id = 'eval-web'
                """
            )["thresholds_json"]
        )
        invalid = self.client.post(
            "/evaluations/eval-web/thresholds",
            data={
                (
                    "threshold__FULL_NAME__"
                    "min_retrieval_success"
                ): "1.5",
            },
        )
        after_invalid = json.loads(
            self.store.fetch_one(
                """
                SELECT thresholds_json FROM evaluations
                WHERE evaluation_id = 'eval-web'
                """
            )["thresholds_json"]
        )
        detail = self.client.get("/evaluations/eval-web")

        self.assertEqual(200, detail.status_code)
        self.assertIn("历史自定义参考线", detail.get_data(as_text=True))
        self.assertEqual(302, updated.status_code)
        self.assertEqual(0.75, stored["FULL_NAME"]["min_retrieval_success"])
        self.assertEqual(6.5, stored["FULL_NAME"]["max_average_total_cost"])
        self.assertEqual(
            0.9,
            stored["FULL_NAME_SOCIAL"]["min_matched_accuracy"],
        )
        self.assertEqual(400, invalid.status_code)
        self.assertIn("必须在0到1之间", invalid.get_data(as_text=True))
        self.assertEqual(stored, after_invalid)

    def test_stage3_threshold_profile_web_management_and_evaluation_selection(self):
        """Web 可创建、复制、归档方案，并在 Evaluation 中选择快照。"""

        created_v1 = self.client.post(
            "/threshold-profiles",
            data={
                "profile_id": "web-release-v1",
                "name": "Web 发布参考线",
                "description": "首版",
                "version": "1",
                "based_on_profile_id": "",
                "threshold__FULL_NAME__min_retrieval_success": "0.75",
                "threshold__FULL_NAME_SOCIAL__min_matched_accuracy": "0.9",
            },
        )
        copy_page = self.client.get(
            "/threshold-profiles/web-release-v1/copy"
        )
        created_v2 = self.client.post(
            "/threshold-profiles",
            data={
                "profile_id": "web-release-v2",
                "name": "Web 发布参考线",
                "description": "第二版",
                "version": "2",
                "based_on_profile_id": "web-release-v1",
                "threshold__FULL_NAME__min_retrieval_success": "0.85",
                "threshold__FULL_NAME_SOCIAL__min_matched_accuracy": "0.95",
            },
        )
        evaluation_created = self.client.post(
            "/evaluations/new",
            data={
                "evaluation_id": "eval-profile-web",
                "name": "方案评测",
                "notes": "",
                "threshold_profile_id": "web-release-v1",
            },
        )
        changed = self.client.post(
            "/evaluations/eval-profile-web/threshold-profile",
            data={"threshold_profile_id": "web-release-v2"},
        )
        detail = self.client.get("/evaluations/eval-profile-web")
        archived = self.client.post(
            "/threshold-profiles/web-release-v2/archive"
        )
        new_evaluation_page = self.client.get("/evaluations/new")
        archived_detail = self.client.get(
            "/threshold-profiles/web-release-v2"
        )
        evaluation = self.store.fetch_one(
            """
            SELECT threshold_profile_id, thresholds_json
            FROM evaluations WHERE evaluation_id = 'eval-profile-web'
            """
        )

        self.assertEqual(302, created_v1.status_code)
        self.assertEqual(200, copy_page.status_code)
        self.assertIn("web-release-v1", copy_page.get_data(as_text=True))
        self.assertEqual(302, created_v2.status_code)
        self.assertEqual(302, evaluation_created.status_code)
        self.assertEqual(302, changed.status_code)
        self.assertEqual("web-release-v2", evaluation["threshold_profile_id"])
        self.assertEqual(
            0.85,
            json.loads(evaluation["thresholds_json"])["FULL_NAME"][
                "min_retrieval_success"
            ],
        )
        detail_html = detail.get_data(as_text=True)
        self.assertIn("Web 发布参考线 v2", detail_html)
        self.assertIn("更换只影响以后生成的新报告", detail_html)
        self.assertEqual(302, archived.status_code)
        self.assertIn(
            "ARCHIVED",
            archived_detail.get_data(as_text=True),
        )
        new_html = new_evaluation_page.get_data(as_text=True)
        self.assertIn("web-release-v1", new_html)
        self.assertNotIn("web-release-v2", new_html)

    def test_history_import_pages_filter_pagination_raw_and_download(self):
        """历史结果可通过页面下钻，Raw 按需加载且下载受目录约束。"""

        run_id, candidate_pk, raw_id = self.seed_imported_result()

        run_page = self.client.get(
            f"/runs/{run_id}?q=query-history&status=SUCCESS&page=1"
        )
        query_page = self.client.get(
            f"/runs/{run_id}/queries/query-history?page=1"
        )
        candidate_page = self.client.get(f"/candidates/{candidate_pk}")
        raw_response = self.client.get(f"/api/raw/{raw_id}")
        status_response = self.client.get(f"/api/runs/{run_id}/status")
        download_response = self.client.get(f"/downloads/results/{run_id}")
        invalid_download = self.client.get(f"/downloads/../../{run_id}")
        phase_update = self.client.post(
            f"/runs/{run_id}/evaluation-phase",
            data={"evaluation_phase": "PHASE_3_TARGETED_ITERATION"},
        )

        self.assertEqual(200, run_page.status_code)
        self.assertIn("query-history", run_page.get_data(as_text=True))
        self.assertEqual(200, query_page.status_code)
        self.assertIn("candidate-history", query_page.get_data(as_text=True))
        self.assertIn("HAS_CANDIDATES", query_page.get_data(as_text=True))
        self.assertIn("third_party_cost", query_page.get_data(as_text=True))
        self.assertEqual(200, candidate_page.status_code)
        self.assertIn("History Person", candidate_page.get_data(as_text=True))
        self.assertEqual(200, raw_response.status_code)
        self.assertEqual("visible", raw_response.get_json()["payload"]["response_body"]["future_field"])
        self.assertNotIn("auth_token", raw_response.get_data(as_text=True))
        self.assertEqual("COMPLETED", status_response.get_json()["status"])
        self.assertEqual(302, phase_update.status_code)
        self.assertEqual(
            "PHASE_3_TARGETED_ITERATION",
            self.store.fetch_one(
                "SELECT evaluation_phase FROM runs WHERE run_id = ?",
                (run_id,),
            )["evaluation_phase"],
        )
        self.assertEqual(200, download_response.status_code)
        self.assertEqual(404, invalid_download.status_code)
        download_response.close()

    def test_run_query_list_uses_fifty_row_server_pagination(self):
        """101条 Query 只在首屏加载50条，并可访问第三页。"""

        source = self.root / "many-tasks.jsonl"
        source.write_bytes(
            jsonl_bytes(
                [
                    {
                        "input_id": f"query-{index:03d}",
                        "person_id": f"person-{index:03d}",
                        "query_stage": "FULL_NAME",
                        "clues": [{"type": "FULL_NAME", "value": f"Person {index}"}],
                    }
                    for index in range(1, 102)
                ]
            )
        )
        self.service.import_dataset_jsonl(
            source,
            name="101人分页数据集",
            dataset_id="dataset-pagination",
        )
        run_id = self.service.create_execution_run(
            evaluation_id="eval-web",
            dataset_id="dataset-pagination",
            run_label="pagination",
            system_version="web-v1",
            evaluation_phase="PHASE_1_BASELINE",
            run_id="run-pagination",
        )

        first_page = self.client.get(f"/runs/{run_id}?page=1")
        third_page = self.client.get(f"/runs/{run_id}?page=3")

        first_html = first_page.get_data(as_text=True)
        third_html = third_page.get_data(as_text=True)
        self.assertEqual(200, first_page.status_code)
        self.assertEqual(
            50,
            first_html.count(f"/runs/{run_id}/queries/"),
        )
        self.assertIn("query-001", first_html)
        self.assertNotIn("query-051", first_html)
        self.assertEqual(200, third_page.status_code)
        self.assertIn("query-101", third_html)

    def test_background_coordinator_completes_web_created_run(self):
        """页面创建的 Run 能由单线程协调器执行并进入终态。"""

        self.import_dataset("dataset-background")
        coordinator = RunCoordinator(
            self.service,
            self.root / ".env",
            client_factory=CoordinatorClient,
        )
        self.app.extensions["run_coordinator"] = coordinator
        response = self.client.post(
            "/evaluations/eval-web/runs",
            data={
                "dataset_id": "dataset-background",
                "run_label": "background",
                "system_version": "web-v1",
                "evaluation_phase": "PHASE_1_BASELINE",
            },
        )
        run = self.store.fetch_one(
            "SELECT run_id FROM runs WHERE run_label = 'background'"
        )

        deadline = time.monotonic() + 3
        status = ""
        while time.monotonic() < deadline:
            status = self.store.fetch_one(
                "SELECT status FROM runs WHERE run_id = ?",
                (run["run_id"],),
            )["status"]
            if status in {"COMPLETED", "PARTIAL_FAILED", "FAILED"}:
                break
            time.sleep(0.01)
        coordinator.shutdown(wait=True)

        self.assertEqual(302, response.status_code)
        self.assertEqual("COMPLETED", status)
        self.assertEqual(
            "NO_CANDIDATE",
            self.store.fetch_one(
                "SELECT status FROM run_queries WHERE run_id = ?",
                (run["run_id"],),
            )["status"],
        )

    def test_web_history_import_and_error_page_do_not_leak_secrets(self):
        """Web 可导入结果，非法上传只返回可读错误且不泄漏配置。"""

        uploaded = self.client.post(
            "/imports",
            data={
                "import_type": "results_jsonl",
                "evaluation_id": "eval-web",
                "run_label": "uploaded",
                "system_version": "history-v2",
                "evaluation_phase": "PHASE_3_TARGETED_ITERATION",
                "source_file": (
                    io.BytesIO(
                        jsonl_bytes(
                            [
                                {
                                    "input_id": "query-uploaded",
                                    "task_id": "task-uploaded",
                                    "results": [],
                                }
                            ]
                        )
                    ),
                    "uploaded-results.jsonl",
                ),
            },
            content_type="multipart/form-data",
        )
        invalid = self.client.post(
            "/imports",
            data={
                "import_type": "dataset",
                "dataset_id": "bad",
                "name": "坏上传",
                "source_file": (io.BytesIO(b"not-json"), "bad.txt"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(302, uploaded.status_code)
        uploaded_run = self.store.fetch_one(
            """
            SELECT run_id, evaluation_phase
            FROM runs WHERE run_label = 'uploaded'
            """
        )
        self.assertIsNotNone(uploaded_run)
        self.assertEqual(
            "PHASE_3_TARGETED_ITERATION",
            uploaded_run["evaluation_phase"],
        )
        self.assertEqual(400, invalid.status_code)
        page = invalid.get_data(as_text=True)
        self.assertIn("只支持", page)
        self.assertNotIn("AUTH_TOKEN", page)
        self.assertNotIn("Traceback", page)

    def test_field_schema_publish_process_and_candidate_processed_view(self):
        """Web 可发布新配置、重新处理，并在 Candidate 页面使用处理结果。"""

        schema_list = self.client.get("/field-schemas")
        definitions = [
            {
                "field_key": "summary_name",
                "display_name": "Summary Name",
                "module": "Summary",
                "source_stage": "GetTaskCandidateDetail",
                "source_path": "ui_sections.summary.data.display_name",
                "data_type": "string",
                "array_mode": "preserve",
                "empty_rule": "default",
                "normalizer": "trim_text",
                "scoring_role": ["display"],
                "compare_mode": "normalized_text",
                "enabled": True,
                "sort_order": 10,
            }
        ]
        published = self.client.post(
            "/field-schemas/new",
            data={
                "name": "Web 字段配置",
                "created_by": "tester",
                "definitions_json": json.dumps(definitions, ensure_ascii=False),
            },
        )
        active = self.store.fetch_one(
            "SELECT schema_version FROM field_schemas WHERE is_active = 1"
        )
        schema_api = self.client.get(
            f"/api/field-schemas/{active['schema_version']}"
        )
        run_id, candidate_pk, _ = self.seed_imported_result()
        processed = self.client.post(
            f"/runs/{run_id}/process",
            data={"schema_version": active["schema_version"]},
        )
        process = self.store.fetch_one(
            """
            SELECT process_id, status FROM process_runs
            WHERE run_id = ? ORDER BY created_at DESC LIMIT 1
            """,
            (run_id,),
        )
        process_page = self.client.get(f"/processes/{process['process_id']}")
        candidate_page = self.client.get(
            f"/candidates/{candidate_pk}?process_id={process['process_id']}"
        )
        second = self.client.post(
            f"/runs/{run_id}/process",
            data={"schema_version": active["schema_version"]},
        )

        self.assertEqual(200, schema_list.status_code)
        self.assertIn("默认字段配置", schema_list.get_data(as_text=True))
        self.assertIn("QUERY", schema_list.get_data(as_text=True))
        self.assertIn("CANDIDATE", schema_list.get_data(as_text=True))
        self.assertEqual(302, published.status_code)
        self.assertEqual("summary_name", schema_api.get_json()["definitions"][0]["field_key"])
        self.assertEqual(302, processed.status_code)
        self.assertEqual("COMPLETED", process["status"])
        self.assertEqual(200, process_page.status_code)
        self.assertIn("Query 字段空值", process_page.get_data(as_text=True))
        self.assertIn("Candidate 字段空值", process_page.get_data(as_text=True))
        self.assertIn("History Person", process_page.get_data(as_text=True))
        self.assertEqual(200, candidate_page.status_code)
        self.assertIn("Summary Name", candidate_page.get_data(as_text=True))
        self.assertIn("History Person", candidate_page.get_data(as_text=True))
        self.assertEqual(302, second.status_code)
        self.assertEqual(
            2,
            self.store.fetch_one(
                "SELECT COUNT(*) AS count FROM process_runs WHERE run_id = ?",
                (run_id,),
            )["count"],
        )

    def test_invalid_field_schema_is_rejected_without_overwriting_active(self):
        """非法路径配置返回可读错误，当前活跃版本保持不变。"""

        active_before = self.store.fetch_one(
            "SELECT schema_version FROM field_schemas WHERE is_active = 1"
        )["schema_version"]
        invalid = self.client.post(
            "/field-schemas/new",
            data={
                "name": "非法字段配置",
                "definitions_json": json.dumps(
                    [
                        {
                            "field_key": "bad",
                            "display_name": "Bad",
                            "module": "Summary",
                            "source_stage": "GetTaskCandidateDetail",
                            "source_path": "ui_sections.items[?].value",
                            "data_type": "string",
                            "array_mode": "preserve",
                            "empty_rule": "default",
                            "normalizer": "identity",
                            "scoring_role": ["display"],
                            "compare_mode": "exact",
                            "enabled": True,
                            "sort_order": 1,
                        }
                    ]
                ),
            },
        )

        self.assertEqual(400, invalid.status_code)
        self.assertIn("source_path", invalid.get_data(as_text=True))
        self.assertEqual(
            active_before,
            self.store.fetch_one(
                "SELECT schema_version FROM field_schemas WHERE is_active = 1"
            )["schema_version"],
        )

    def test_stage5_baseline_review_and_metrics_web_flow(self):
        """Web 可导入基准、关联处理、保存复核并展示正式指标。"""

        baseline_response = self.client.post(
            "/baselines",
            data={
                "baseline_version": "baseline-web-stage5",
                "name": "Web 阶段5基准",
                "source_file": (
                    io.BytesIO(
                        jsonl_bytes(
                            [
                                {
                                    "person_id": "person-history",
                                    "display_name": "History Person",
                                    "fields": {
                                        "summary_name": "History Person",
                                        "future_unknown": "kept",
                                    },
                                    "baseline_available_fields": [
                                        "summary_name",
                                        "future_unknown",
                                    ],
                                    "evidence": {},
                                }
                            ]
                        )
                    ),
                    "baseline-stage5.jsonl",
                ),
            },
            content_type="multipart/form-data",
        )
        definitions = [
            {
                "field_key": "summary_name",
                "display_name": "Summary Name",
                "module": "Summary",
                "source_stage": "GetTaskCandidateDetail",
                "source_path": "ui_sections.summary.data.display_name",
                "data_type": "string",
                "array_mode": "preserve",
                "empty_rule": "default",
                "normalizer": "trim_text",
                "scoring_role": ["completeness", "accuracy"],
                "compare_mode": "normalized_text",
                "enabled": True,
                "sort_order": 10,
            }
        ]
        schema_version = self.service.publish_field_schema(
            name="Web 阶段5字段",
            definitions=definitions,
            schema_version="field-schema-web-stage5",
        )
        run_id, candidate_pk, _ = self.seed_imported_result()
        processed_response = self.client.post(
            f"/runs/{run_id}/process",
            data={
                "schema_version": schema_version,
                "baseline_version": "baseline-web-stage5",
            },
        )
        process = self.store.fetch_one(
            """
            SELECT process_id FROM process_runs
            WHERE run_id = ? ORDER BY created_at DESC LIMIT 1
            """,
            (run_id,),
        )
        candidate_page = self.client.get(
            f"/candidates/{candidate_pk}?process_id={process['process_id']}"
        )
        context = self.service.get_review_context(
            process["process_id"],
            candidate_pk,
        )
        review_response = self.client.post(
            (
                f"/processes/{process['process_id']}/candidates/"
                f"{candidate_pk}/review"
            ),
            data={
                "judgement": "HIT",
                "reason": "MANUAL",
                "evidence": "人工确认人物一致",
                "reviewer": "web-tester",
                "review_note": "阶段5 Web 复核",
                "expected_reviewed_at": context["reviewed_at"],
                "field_scores_json": json.dumps(
                    context["field_scores"],
                    ensure_ascii=False,
                ),
            },
        )
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE reviews SET reviewed_at = ?
                WHERE process_id = ? AND candidate_pk = ?
                """,
                (
                    "2026-07-24T06:08:31.593258+00:00",
                    process["process_id"],
                    candidate_pk,
                ),
            )
        reviewed_candidate_page = self.client.get(
            f"/candidates/{candidate_pk}?process_id={process['process_id']}"
        )
        process_page = self.client.get(
            f"/processes/{process['process_id']}"
        )
        metrics_api = self.client.get(
            f"/api/processes/{process['process_id']}/metrics"
        )
        baseline_page = self.client.get("/baselines")
        available_update = self.client.post(
            (
                "/baselines/baseline-web-stage5/people/"
                "person-history/available-fields"
            ),
            data={"available_fields": ["summary_name"]},
        )
        available_row = self.store.fetch_one(
            """
            SELECT available_fields_json, available_fields_source
            FROM baseline_people
            WHERE baseline_version = ? AND person_id = ?
            """,
            ("baseline-web-stage5", "person-history"),
        )

        self.assertEqual(302, baseline_response.status_code)
        self.assertEqual(302, processed_response.status_code)
        self.assertEqual(200, candidate_page.status_code)
        self.assertIn("候选人复核", candidate_page.get_data(as_text=True))
        self.assertEqual(302, review_response.status_code)
        reviewed_html = reviewed_candidate_page.get_data(as_text=True)
        self.assertIn("2026-07-24 14:08:31", reviewed_html)
        self.assertIn(
            'name="expected_reviewed_at" '
            'value="2026-07-24T06:08:31.593258+00:00"',
            reviewed_html,
        )
        self.assertIn("目标人物命中率", process_page.get_data(as_text=True))
        self.assertIn("结果状态", process_page.get_data(as_text=True))
        self.assertIn("成本与耗时", process_page.get_data(as_text=True))
        self.assertIn("置信度分布", process_page.get_data(as_text=True))
        self.assertIn("REVIEWED", process_page.get_data(as_text=True))
        self.assertIn(
            "NO_NONMATCHED_CONFIRMED",
            process_page.get_data(as_text=True),
        )
        self.assertNotIn(
            "完整度字段未就绪 future_unknown",
            process_page.get_data(as_text=True),
        )
        self.assertEqual(1.0, metrics_api.get_json()["retrieval_success"]["value"])
        self.assertEqual(
            "metrics-v3",
            metrics_api.get_json()["metrics_rule_version"],
        )
        self.assertIn("Web 阶段5基准", baseline_page.get_data(as_text=True))
        self.assertIn("未知字段", baseline_page.get_data(as_text=True))
        baseline_html = baseline_page.get_data(as_text=True)
        self.assertIn('data-baseline-workbench', baseline_html)
        self.assertIn('data-baseline-field-search', baseline_html)
        self.assertIn('data-baseline-select-valued', baseline_html)
        self.assertIn('data-baseline-clear', baseline_html)
        self.assertIn('class="baseline-field-group"', baseline_html)
        self.assertIn("Summary", baseline_html)
        self.assertIn("未配置字段", baseline_html)
        self.assertEqual(302, available_update.status_code)
        self.assertEqual(["summary_name"], json.loads(available_row["available_fields_json"]))
        self.assertEqual("MANUAL", available_row["available_fields_source"])

    def test_stage2_report_center_home_filters_pagination_and_artifacts(self):
        """报告中心提供首页摘要、固定筛选、50条分页和真实产物链接。"""

        run_id, _, _ = self.seed_imported_result()
        schema = self.store.fetch_one(
            """
            SELECT schema_version FROM field_schemas
            WHERE is_active = 1 LIMIT 1
            """
        )
        process = self.service.process_run(
            run_id=run_id,
            schema_version=schema["schema_version"],
            process_id="process-report-center",
        )
        base_time = datetime(2026, 7, 1, tzinfo=timezone.utc)
        records = []
        for index in range(55):
            report_id = f"report-center-{index:02d}"
            status = (
                "READY"
                if index % 3 == 0
                else "STALE"
                if index % 3 == 1
                else "FAILED"
            )
            report_type = "COMPARE" if index % 2 == 0 else "SINGLE"
            relative_dir = Path("eval-web") / report_id
            records.append(
                (
                    report_id,
                    "eval-web",
                    process.process_id if report_type == "COMPARE" else None,
                    process.process_id,
                    report_type,
                    status,
                    "{}",
                    (relative_dir / f"{report_id}_report.html").as_posix(),
                    (relative_dir / f"{report_id}_report.xlsx").as_posix(),
                    (base_time + timedelta(minutes=index)).isoformat(),
                )
            )
        with self.store.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO reports(
                    report_id, evaluation_id, baseline_process_id,
                    candidate_process_id, report_type, status, metrics_json,
                    html_file, excel_file, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

        latest_report_dir = (
            self.root / "reports" / "eval-web" / "report-center-54"
        )
        latest_report_dir.mkdir(parents=True)
        (latest_report_dir / "report-center-54_report.html").write_text(
            "<!doctype html><title>report-center-54</title>",
            encoding="utf-8",
        )
        (latest_report_dir / "report-center-54_report.xlsx").write_bytes(
            b"test-xlsx"
        )

        home = self.client.get("/")
        first_page = self.client.get("/reports")
        second_page = self.client.get("/reports?page=2")
        ready_page = self.client.get("/reports?status=READY")
        type_page = self.client.get("/reports?report_type=COMPARE")
        evaluation_page = self.client.get(
            "/reports?evaluation_id=eval-web"
        )
        version_page = self.client.get(
            "/reports?system_version=history-v1"
        )
        empty_version_page = self.client.get(
            "/reports?system_version=missing-version"
        )

        home_html = home.get_data(as_text=True)
        first_html = first_page.get_data(as_text=True)
        second_html = second_page.get_data(as_text=True)
        self.assertEqual(200, home.status_code)
        self.assertIn("最近报告", home_html)
        self.assertIn("report-center-54", home_html)
        self.assertIn("report-center-45", home_html)
        self.assertNotIn("report-center-44", home_html)
        self.assertIn('href="/reports"', home_html)

        self.assertEqual(200, first_page.status_code)
        self.assertEqual(50, first_html.count('class="report-row"'))
        self.assertIn("report-center-54", first_html)
        self.assertNotIn("report-center-04", first_html)
        self.assertIn(
            "/downloads/report-html/report-center-54",
            first_html,
        )
        self.assertIn(
            "/downloads/report-excel/report-center-54",
            first_html,
        )
        self.assertNotIn(
            "/downloads/report-html/report-center-53",
            first_html,
        )
        self.assertNotIn(
            "/downloads/report-html/report-center-52",
            first_html,
        )

        self.assertEqual(200, second_page.status_code)
        self.assertEqual(5, second_html.count('class="report-row"'))
        self.assertIn("report-center-04", second_html)
        self.assertNotIn("report-center-54", second_html)

        ready_html = ready_page.get_data(as_text=True)
        self.assertIn("report-center-54", ready_html)
        self.assertNotIn("report-center-53", ready_html)
        self.assertNotIn("report-center-52", ready_html)
        self.assertIn("report-center-54", type_page.get_data(as_text=True))
        self.assertNotIn(
            "report-center-53",
            type_page.get_data(as_text=True),
        )
        self.assertIn(
            "report-center-54",
            evaluation_page.get_data(as_text=True),
        )
        self.assertIn(
            "report-center-54",
            version_page.get_data(as_text=True),
        )
        self.assertNotIn(
            "report-center-54",
            empty_version_page.get_data(as_text=True),
        )

    def test_stage6_report_web_static_html_download_and_drilldown(self):
        """报告快照可在 Web 查看、下钻并安全导出独立静态 HTML。"""

        baseline_path = self.root / "baseline-web-stage6.jsonl"
        baseline_path.write_bytes(
            jsonl_bytes(
                [
                    {
                        "person_id": "person-history",
                        "display_name": "Report Person",
                        "fields": {"summary_name": "History Person"},
                        "evidence": {},
                    }
                ]
            )
        )
        self.service.import_baseline_jsonl(
            baseline_path,
            name="Web 阶段6基准",
            baseline_version="baseline-web-stage6",
        )
        schema_version = self.service.publish_field_schema(
            name="Web 阶段6字段",
            definitions=[
                {
                    "field_key": "summary_name",
                    "display_name": "Summary Name",
                    "module": "Summary",
                    "source_stage": "GetTaskCandidateDetail",
                    "source_path": "ui_sections.summary.data.display_name",
                    "data_type": "string",
                    "array_mode": "preserve",
                    "empty_rule": "default",
                    "normalizer": "trim_text",
                    "scoring_role": ["completeness", "accuracy"],
                    "compare_mode": "normalized_text",
                    "enabled": True,
                    "sort_order": 10,
                }
            ],
            schema_version="field-schema-web-stage6",
        )
        run_id, candidate_pk, _ = self.seed_imported_result()
        with self.store.transaction() as connection:
            connection.execute(
                """
                UPDATE runs SET system_version = ?
                WHERE run_id = ?
                """,
                ("<script>alert('report')</script>", run_id),
            )
        process = self.service.process_run(
            run_id=run_id,
            schema_version=schema_version,
            baseline_version="baseline-web-stage6",
            process_id="process-web-stage6",
        )
        context = self.service.get_review_context(
            process.process_id,
            candidate_pk,
        )
        self.service.save_review(
            process_id=process.process_id,
            candidate_pk=candidate_pk,
            judgement="HIT",
            reason="MANUAL",
            evidence="Web 报告测试",
            reviewer="web-report-tester",
            review_note="已确认",
            field_scores=context["field_scores"],
            expected_reviewed_at=context["reviewed_at"],
        )

        created = self.client.post(
            "/reports",
            data={
                "candidate_process_id": process.process_id,
                "baseline_process_id": "",
                "data_marker": "MOCK",
            },
        )
        report = self.store.fetch_one(
            "SELECT * FROM reports ORDER BY created_at DESC LIMIT 1"
        )
        report_page = self.client.get(f"/reports/{report['report_id']}")
        html_download = self.client.get(
            f"/downloads/report-html/{report['report_id']}"
        )
        excel_download = self.client.get(
            f"/downloads/report-excel/{report['report_id']}"
        )
        static_html = html_download.get_data(as_text=True)
        legacy_model = json.loads(report["metrics_json"])
        for key in (
            "result_status_metrics",
            "quality_metrics",
            "cost_metrics",
            "pdl_metrics",
            "confidence_metrics",
            "grouped_metrics",
            "comparison",
            "threshold_assessment",
        ):
            legacy_model.pop(key, None)
        for key in (
            "report_model_version",
            "metrics_rule_version",
            "evaluation_phase",
            "baseline_evaluation_phase",
            "threshold_profile_id",
            "threshold_profile_name",
            "threshold_profile_version",
        ):
            legacy_model["metadata"].pop(key, None)
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO reports(
                    report_id, evaluation_id, baseline_process_id,
                    candidate_process_id, report_type, status,
                    metrics_json, html_file, excel_file, created_at
                ) VALUES (
                    'report-legacy-v1', 'eval-web', NULL, ?,
                    'SINGLE', 'READY', ?, 'legacy/report.html', NULL, ?
                )
                """,
                (
                    process.process_id,
                    json.dumps(legacy_model, ensure_ascii=False),
                    report["created_at"],
                ),
            )
        legacy_page = self.client.get("/reports/report-legacy-v1")

        self.assertEqual(302, created.status_code)
        model = json.loads(report["metrics_json"])
        self.assertEqual(
            "report-model-v3",
            model["metadata"]["report_model_version"],
        )
        self.assertEqual(
            "暂不能判断",
            model["threshold_assessment"]["recommendation"],
        )
        formatted_generated_at = self.app.jinja_env.filters[
            "format_datetime"
        ](model["metadata"]["generated_at"])
        self.assertEqual(200, report_page.status_code)
        page = report_page.get_data(as_text=True)
        self.assertIn('href="/reports"', page)
        self.assertIn('href="/evaluations/eval-web"', page)
        self.assertIn(formatted_generated_at, page)
        self.assertIn("执行摘要", page)
        self.assertIn("结果状态", page)
        self.assertIn("参考线与建议", page)
        self.assertIn("未选择参考线方案", page)
        self.assertIn("模块与字段", page)
        self.assertIn(f"/candidates/{candidate_pk}", page)
        self.assertNotIn("<script>alert('report')</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(200, html_download.status_code)
        self.assertTrue(static_html.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn(formatted_generated_at, static_html)
        self.assertNotIn(model["metadata"]["generated_at"], static_html)
        self.assertNotIn("cdn.", static_html.lower())
        self.assertNotIn("<script>alert('report')</script>", static_html)
        self.assertEqual(404, excel_download.status_code)
        self.assertEqual(200, legacy_page.status_code)
        legacy_html = legacy_page.get_data(as_text=True)
        self.assertIn(
            "report-model-v1",
            legacy_html,
        )
        self.assertIn("历史自定义参考线", legacy_html)
        self.assertNotIn(
            "/downloads/report-html/report-legacy-v1",
            legacy_html,
        )
        html_download.close()
        excel_download.close()

    def test_report_v5_web_uses_snapshot_explorer_and_keeps_optional_sections_hidden(self):
        """v5 Web 报告以快照驱动 Query 工作台，并不渲染空参考线章节。

        功能说明：使用已有历史结果完成 v3 字段处理与正式身份归类，验证
        新报告页面仅嵌入报告快照、提供前端分段加载所需容器，并保留候选人
        详情下钻入口。该测试不执行浏览器脚本，也不触发检索接口。

        返回值：无；所有断言通过代表页面结构和条件展示契约成立。
        异常说明：报告创建、快照版本或模板渲染异常时测试直接失败。
        """

        schema_version = self.service.ensure_default_field_schema_v3()
        baseline_path = self.root / "baseline-v5-web.jsonl"
        baseline_path.write_bytes(
            jsonl_bytes([
                {
                    "person_id": "person-history",
                    "display_name": "History Person",
                    "fields": {"summary_display_name": "History Person"},
                    "baseline_available_fields": ["summary_display_name"],
                }
            ])
        )
        self.service.import_baseline_jsonl(
            baseline_path,
            name="v5 Web 基准",
            baseline_version="baseline-v5-web",
        )
        run_id, candidate_pk, _ = self.seed_imported_result()
        process = self.service.process_run(
            run_id=run_id,
            schema_version=schema_version,
            baseline_version="baseline-v5-web",
            process_id="process-v5-web",
        )
        context = self.service.get_review_context(
            process.process_id,
            candidate_pk,
        )
        self.service.save_review(
            process_id=process.process_id,
            candidate_pk=candidate_pk,
            judgement="HIT",
            reason="MANUAL",
            evidence="v5 Web 页面夹具",
            reviewer="web-v5-tester",
            review_note="已确认",
            field_scores=context["field_scores"],
            expected_reviewed_at=context["reviewed_at"],
        )
        response = self.client.post(
            "/reports",
            data={
                "candidate_process_id": process.process_id,
                "baseline_process_id": "",
                "data_marker": "MOCK",
            },
        )
        report = self.store.fetch_one(
            "SELECT report_id, metrics_json FROM reports ORDER BY created_at DESC LIMIT 1"
        )
        page = self.client.get(f"/reports/{report['report_id']}")
        static_download = self.client.get(
            f"/downloads/report-html/{report['report_id']}"
        )
        model = json.loads(report["metrics_json"])
        html = page.get_data(as_text=True)
        static_html = static_download.get_data(as_text=True)

        self.assertEqual(302, response.status_code, response.get_data(as_text=True))
        self.assertEqual("report-model-v5", model["metadata"]["report_model_version"])
        self.assertEqual(200, page.status_code)
        self.assertIn("核心评测结果", html)
        self.assertIn("衡量系统能否在全部有效 Query 中找到目标人物", html)
        self.assertIn("本次数据处理范围", html)
        self.assertIn("五大资料模块返回概览", html)
        self.assertIn("模块有数据率", html)
        self.assertIn("字段完整度", html)
        self.assertIn("05 · Confidence distribution", html)
        self.assertIn("07 · Query explorer", html)
        self.assertIn("候选人置信度分布", html)
        self.assertRegex(html, r"\d+(?:\.\d+)?% · \d+ 人")
        self.assertIn("非命中候选人资料相似度", html)
        self.assertIn('data-report-metric-dialog', html)
        self.assertIn('data-metric-dialog-populations', html)
        self.assertIn('id="report-v5-metric-snapshot"', html)
        self.assertIn('"initial_query_count": 5', html)
        self.assertIn('"load_more_query_count": 10', html)
        self.assertIn("Query 与全部候选人", html)
        self.assertIn('data-report-explorer', html)
        self.assertIn('id="report-v5-snapshot"', html)
        self.assertIn(candidate_pk, html)
        self.assertNotIn("参考线判断", html)
        self.assertNotIn("风险与口径说明", html)
        self.assertEqual(200, static_download.status_code)
        self.assertIn("核心评测结果", static_html)
        self.assertIn("计算公式", static_html)
        self.assertIn("正式整体指标", static_html)
        self.assertIn("本次数据处理范围", static_html)
        self.assertIn("五大资料模块返回概览", static_html)
        self.assertIn("模块有数据率", static_html)
        self.assertIn("字段完整度", static_html)
        self.assertIn("05 · Confidence distribution", static_html)
        self.assertIn("07 · Query explorer", static_html)
        self.assertIn("候选人置信度分布", static_html)
        self.assertRegex(static_html, r"\d+(?:\.\d+)?% · \d+ 人")
        self.assertIn("非命中候选人资料相似度", static_html)
        self.assertIn("Query 与全部候选人", static_html)
        self.assertIn("candidate-history", static_html)
        self.assertIn("静态报告不嵌入 Raw 内容", static_html)
        self.assertNotIn("report-v5-snapshot", static_html)
        self.assertNotIn("unknown_new_field", static_html)
        static_download.close()

        # 对比报告复用同一 v5 静态分支；此处只替换快照中的对比上下文，
        # 不触发新的 Process、HTTP 请求或临时数据库查询。
        compare_model = json.loads(json.dumps(model))
        compare_model["metadata"]["report_type"] = "COMPARE"
        compare_model["optional_sections"]["show_comparison"] = True
        compare_model["comparison"] = {
            "same_condition": {
                "coverage": {"paired_count": 1},
                "category_counts": {
                    "持续命中": 1,
                    "新增命中": 0,
                    "退化未命中": 0,
                    "持续未命中": 0,
                },
            }
        }
        compare_html = self.app.jinja_env.get_template(
            "report_static.html"
        ).render(report=compare_model, static_export=True)
        self.assertIn("版本变化概览", compare_html)
        self.assertIn("持续命中", compare_html)


    def test_stage2_reprocess_and_query_classification_web_flow(self):
        """Run 可无成本重处理，并在 Query 工作台保存主命中。"""

        run_id, candidate_pk, _ = self.seed_imported_result()
        schema = self.store.fetch_one(
            "SELECT schema_version FROM field_schemas WHERE is_active = 1"
        )
        response = self.client.post(
            f"/runs/{run_id}/process",
            data={
                "schema_version": schema["schema_version"],
                "baseline_version": "",
                "processing_mode": "REPROCESS_EXISTING",
                "confirm_existing_data": "true",
            },
        )
        self.assertEqual(302, response.status_code)
        process = self.store.fetch_one(
            """
            SELECT * FROM process_runs WHERE run_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id,),
        )
        page = self.client.get(
            f"/processes/{process['process_id']}/queries/query-history/"
            "classification"
        )
        html = page.get_data(as_text=True)
        self.assertEqual(200, page.status_code)
        self.assertIn("候选人身份判定", html)
        self.assertIn("不会修改接口返回数据", html)
        saved = self.client.post(
            f"/processes/{process['process_id']}/queries/query-history/"
            "classification",
            data={
                "primary_hit_candidate_pk": candidate_pk,
                "confirm_no_hit": "",
                "reviewer": "web-stage2",
                "review_note": "确认主命中",
                f"judgement__{candidate_pk}": "HIT",
                f"reason__{candidate_pk}": "MANUAL",
                f"evidence__{candidate_pk}": "人工确认",
                f"expected_reviewed_at__{candidate_pk}": "",
            },
        )
        self.assertEqual(302, saved.status_code)
        review = self.store.fetch_one(
            """
            SELECT * FROM reviews
            WHERE process_id = ? AND candidate_pk = ?
            """,
            (process["process_id"], candidate_pk),
        )
        self.assertEqual("MANUAL", review["classification_source"])
        self.assertEqual(1, review["is_primary_hit"])

    def test_stage3_field_comparison_matrix_and_publish_copy(self):
        """字段配置页可打开矩阵，并通过矩阵复制发布不可变新版本。"""

        baseline_source = self.root / "stage3-web-baseline.jsonl"
        baseline_source.write_bytes(
            jsonl_bytes([{
                "person_id": "person-history",
                "display_name": "History Person",
                "fields": {
                    "summary_display_name": "History Person",
                    "baseline_only": "prepared",
                },
                "baseline_available_fields": [
                    "summary_display_name",
                    "baseline_only",
                ],
            }])
        )
        self.service.import_baseline_jsonl(
            baseline_source,
            name="Web阶段3基准",
            baseline_version="baseline-web-stage3",
        )
        schema = self.store.fetch_one(
            "SELECT * FROM field_schemas WHERE is_active = 1"
        )
        matrix_page = self.client.get(
            f"/field-schemas/{schema['schema_version']}/comparison-matrix"
            "?baseline_version=baseline-web-stage3"
        )
        html = matrix_page.get_data(as_text=True)
        self.assertEqual(200, matrix_page.status_code)
        self.assertIn("字段对比矩阵", html)
        self.assertIn("baseline_only", html)
        self.assertIn("BASELINE_ENABLED_NOT_EXTRACTED", html)

        definitions = json.loads(schema["definitions_json"])
        enabled_keys = [
            definition["field_key"] for definition in definitions
            if definition["enabled"]
        ]
        published = self.client.post(
            f"/field-schemas/{schema['schema_version']}/comparison-matrix",
            data={
                "baseline_version": "baseline-web-stage3",
                "name": "Web阶段3复制配置",
                "created_by": "web-stage3",
                "enabled_fields": enabled_keys,
                "completeness_fields": ["summary_display_name"],
                "accuracy_fields": ["summary_display_name"],
                "identity_fields": ["social_urls"],
                "compare_mode__summary_display_name": "normalized_text",
                "normalizer__summary_display_name": "trim_text",
            },
        )
        self.assertEqual(302, published.status_code)
        created = self.store.fetch_one(
            """
            SELECT * FROM field_schemas
            WHERE name = 'Web阶段3复制配置'
            """
        )
        self.assertIsNotNone(created)
        self.assertNotEqual(schema["schema_version"], created["schema_version"])

    def test_field_schema_v3_catalog_and_discovery_are_visible_without_writes(self):
        """字段目录按模块展示，未知 ui_sections 字段仅作为发布建议。"""

        run_id, _, _ = self.seed_imported_result()
        baseline_path = self.root / "field-v3-discovery-baseline.jsonl"
        baseline_path.write_bytes(
            jsonl_bytes([
                {
                    "person_id": "person-history",
                    "display_name": "History Person",
                    "fields": {"summary_display_name": "History Person"},
                    "baseline_available_fields": ["summary_display_name"],
                }
            ])
        )
        self.service.import_baseline_jsonl(
            baseline_path,
            name="字段目录发现基准",
            baseline_version="baseline-field-v3-discovery",
        )
        schema = self.store.fetch_one(
            "SELECT * FROM field_schemas WHERE is_active = 1"
        )
        processed = self.client.post(
            f"/runs/{run_id}/process",
            data={"schema_version": schema["schema_version"]},
        )
        process = self.store.fetch_one(
            """
            SELECT process_id FROM process_runs WHERE run_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id,),
        )
        page = self.client.get(
            f"/field-schemas/{schema['schema_version']}/comparison-matrix"
            f"?process_id={process['process_id']}"
            "&baseline_version=baseline-field-v3-discovery"
        )
        schema_page = self.client.get("/field-schemas")
        api = self.client.get(f"/api/field-schemas/{schema['schema_version']}")

        self.assertEqual(302, processed.status_code)
        self.assertEqual(200, page.status_code)
        self.assertIn("待配置字段", page.get_data(as_text=True))
        self.assertIn("Profile location", page.get_data(as_text=True))
        self.assertEqual(200, schema_page.status_code)
        self.assertIn("field-schema-default-v3", schema_page.get_data(as_text=True))
        definitions = api.get_json()["definitions"]
        self.assertTrue(
            any(
                item["field_key"] == "summary_web_links"
                and item["display_enabled"]
                for item in definitions
            )
        )

    def test_stage3_field_workbench_publishes_mapping_and_discovered_profile(self):
        """工作台可保存字段映射，并把勾选的 Profile 建议发布为新版本。"""

        run_id, _, _ = self.seed_imported_result()
        # 构造一个目录中尚未登记的 Profile 原子字段，用于验证“发现后勾选
        # 发布”的真实闭环；不修改默认字段目录或其他历史样例。
        with self.store.transaction() as conn:
            conn.execute(
                """
                UPDATE candidates
                SET ui_sections_json = ?
                WHERE run_id = ?
                """,
                (
                    json.dumps({
                        "summary": {
                            "status": "data",
                            "data": {"display_name": "History Person"},
                        },
                        "profile": {
                            "status": "data",
                            "data": {
                                "sections": [{
                                    "title": "Contact",
                                    "items": [{
                                        "label": "Office",
                                        "value": "Shanghai",
                                    }],
                                }],
                            },
                        },
                    }, ensure_ascii=False),
                    run_id,
                ),
            )
        baseline_path = self.root / "stage3-workbench-baseline.jsonl"
        baseline_path.write_bytes(
            jsonl_bytes([{
                "person_id": "person-history",
                "display_name": "History Person",
                "fields": {
                    "summary_display_name": "History Person",
                    "profile_contact_office": "Shanghai",
                },
                "baseline_available_fields": [
                    "summary_display_name", "profile_contact_office",
                ],
            }])
        )
        self.service.import_baseline_jsonl(
            baseline_path,
            name="工作台基准",
            baseline_version="baseline-stage3-workbench",
        )
        schema = self.store.fetch_one(
            "SELECT * FROM field_schemas WHERE is_active = 1"
        )
        self.client.post(
            f"/runs/{run_id}/process",
            data={"schema_version": schema["schema_version"]},
        )
        process = self.store.fetch_one(
            """
            SELECT process_id FROM process_runs WHERE run_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id,),
        )
        definitions = json.loads(schema["definitions_json"])
        discovery = self.service.discover_field_candidates(
            schema_version=schema["schema_version"],
            process_id=process["process_id"],
            baseline_version="baseline-stage3-workbench",
        )
        profile_contact_office = next(
            item for item in discovery["suggestions"]
            if item["field_key"] == "profile_contact_office"
        )
        data = {
            "baseline_version": "baseline-stage3-workbench",
            "name": "阶段3工作台配置",
            "created_by": "web-stage3",
            "visible_fields": [item["field_key"] for item in definitions],
            "enabled_fields": [
                item["field_key"] for item in definitions if item["enabled"]
            ],
            "display_fields": [
                item["field_key"]
                for item in definitions if item["display_enabled"]
            ],
            "baseline_compare_fields": [
                item["field_key"]
                for item in definitions
                if item["baseline_compare_enabled"]
            ] + ["summary_display_name"],
            "run_compare_fields": [
                item["field_key"]
                for item in definitions if item["run_compare_enabled"]
            ],
            "completeness_fields": [
                item["field_key"]
                for item in definitions if item["completeness_enabled"]
            ],
            "accuracy_fields": [
                item["field_key"]
                for item in definitions if item["accuracy_enabled"]
            ],
            "identity_fields": [
                item["field_key"]
                for item in definitions if item["identity_enabled"]
            ],
            "baseline_field_key__summary_display_name": "summary_display_name",
            "discovered_field_keys": [profile_contact_office["field_key"]],
            "discovered_definitions_json": json.dumps(
                discovery["suggestions"], ensure_ascii=False
            ),
        }
        published = self.client.post(
            f"/field-schemas/{schema['schema_version']}/comparison-matrix",
            data=data,
        )
        created = self.store.fetch_one(
            "SELECT definitions_json FROM field_schemas WHERE name = ?",
            ("阶段3工作台配置",),
        )
        created_definitions = json.loads(created["definitions_json"])
        by_key = {item["field_key"]: item for item in created_definitions}
        filtered = self.client.get("/field-schemas?module=Profile&q=office")

        self.assertEqual(302, published.status_code)
        self.assertTrue(by_key["summary_display_name"]["baseline_compare_enabled"])
        self.assertEqual(
            "summary_display_name",
            by_key["summary_display_name"]["baseline_field_key"],
        )
        self.assertEqual(
            "PROFILE_ITEM", by_key["profile_contact_office"]["source_type"]
        )
        self.assertEqual(
            "Office",
            by_key["profile_contact_office"]["source_options"]["label"],
        )
        self.assertEqual(200, filtered.status_code)
        self.assertIn("profile_contact_office", filtered.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
