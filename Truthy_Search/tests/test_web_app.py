"""阶段3 Flask 页面、路由、导入与 Raw API 测试。"""

from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
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

    def submit(self, run_id: str) -> None:
        """记录页面提交的 Run ID。"""

        self.submitted.append(run_id)


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
                        "data": {"status": "SUCCEEDED", "candidate_count": 0},
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
                (
                    "threshold__FULL_NAME__"
                    "min_retrieval_success"
                ): "0.7",
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
        self.assertEqual(
            0.7,
            json.loads(
                self.store.fetch_one(
                    """
                    SELECT thresholds_json FROM evaluations
                    WHERE evaluation_id = 'eval-created'
                    """
                )["thresholds_json"]
            )["FULL_NAME"]["min_retrieval_success"],
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

    def test_stage5_evaluation_thresholds_web_update_and_validation(self):
        """Evaluation 页面可维护结构化参考线，非法值不会覆盖旧配置。"""

        detail = self.client.get("/evaluations/eval-web")
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

        self.assertEqual(200, detail.status_code)
        self.assertIn("参考线与建议", detail.get_data(as_text=True))
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
                "expected_reviewed_at": "",
                "field_scores_json": json.dumps(
                    context["field_scores"],
                    ensure_ascii=False,
                ),
            },
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
        self.assertIn("检索成功率", process_page.get_data(as_text=True))
        self.assertIn("结果状态", process_page.get_data(as_text=True))
        self.assertIn("成本与耗时", process_page.get_data(as_text=True))
        self.assertIn("置信度分布", process_page.get_data(as_text=True))
        self.assertIn("PENDING_REVIEW", process_page.get_data(as_text=True))
        self.assertIn(
            "完整度字段未就绪 future_unknown",
            process_page.get_data(as_text=True),
        )
        self.assertEqual(1.0, metrics_api.get_json()["retrieval_success"]["value"])
        self.assertEqual(
            "metrics-v2",
            metrics_api.get_json()["metrics_rule_version"],
        )
        self.assertIn("Web 阶段5基准", baseline_page.get_data(as_text=True))
        self.assertIn("未知字段", baseline_page.get_data(as_text=True))
        self.assertEqual(302, available_update.status_code)
        self.assertEqual(["summary_name"], json.loads(available_row["available_fields_json"]))
        self.assertEqual("MANUAL", available_row["available_fields_source"])

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
            expected_reviewed_at="",
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
            "report-model-v2",
            model["metadata"]["report_model_version"],
        )
        self.assertEqual(
            "暂不能判断",
            model["threshold_assessment"]["recommendation"],
        )
        self.assertEqual(200, report_page.status_code)
        page = report_page.get_data(as_text=True)
        self.assertIn("执行摘要", page)
        self.assertIn("结果状态", page)
        self.assertIn("参考线与建议", page)
        self.assertIn("模块与字段", page)
        self.assertIn(f"/candidates/{candidate_pk}", page)
        self.assertNotIn("<script>alert('report')</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(200, html_download.status_code)
        self.assertTrue(static_html.lstrip().lower().startswith("<!doctype html>"))
        self.assertNotIn("cdn.", static_html.lower())
        self.assertNotIn("<script>alert('report')</script>", static_html)
        self.assertEqual(404, excel_download.status_code)
        self.assertEqual(200, legacy_page.status_code)
        self.assertIn(
            "report-model-v1",
            legacy_page.get_data(as_text=True),
        )
        html_download.close()
        excel_download.close()


if __name__ == "__main__":
    unittest.main()
