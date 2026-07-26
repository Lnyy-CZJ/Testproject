#!/usr/bin/env python3
"""searchTool v1.3 阶段6本地 Web、报告与导出入口。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from dotenv import dotenv_values
from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from analysis_service import (
    ActiveRunError,
    AnalysisService,
    DuplicateImportError,
    EVALUATION_PHASES,
    EVALUATION_THRESHOLD_FIELDS,
    FieldSchemaValidationError,
    ImportValidationError,
    RESULT_STATUSES,
    ReviewValidationError,
    SUPPORTED_QUERY_STAGES,
    normalize_evaluation_thresholds,
    validate_field_definitions,
    validate_storage_id,
)
from analysis_store import AnalysisStore
from search_tool import Config, SearchClient


PROJECT_ROOT = Path(__file__).resolve().parent
TERMINAL_RUN_STATUSES = {
    "COMPLETED",
    "PARTIAL_FAILED",
    "FAILED",
    "INTERRUPTED",
}
QUERY_STATUSES = {
    "PENDING",
    "RUNNING",
    "SUCCESS",
    "NO_CANDIDATE",
    "PARTIAL_DETAIL_FAILED",
    "FAILED",
}
QUERY_STAGES = {"FULL_NAME", "FULL_NAME_SOCIAL"}
ALLOWED_UPLOAD_SUFFIXES = {".jsonl", ".json", ".xlsx"}


def _project_path(value: str | Path) -> Path:
    """把相对配置路径稳定解析到项目目录。"""

    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _positive_int(value: Any, default: int) -> int:
    """把配置值转换为正整数，无效值回退到安全默认值。"""

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _threshold_form_payload(form: Any) -> dict[str, dict[str, Any]]:
    """把结构化 Evaluation 表单转换为服务层参考线对象。"""

    return {
        query_stage: {
            field_key: form.get(
                f"threshold__{query_stage}__{field_key}",
                "",
            )
            for field_key in EVALUATION_THRESHOLD_FIELDS
        }
        for query_stage in sorted(SUPPORTED_QUERY_STAGES)
    }


def _boolean_value(value: Any, default: bool = False) -> bool:
    """解析 .env/测试覆盖中的布尔开关。"""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class RunCoordinator:
    """使用单线程后台执行器串行运行 searchTool。

    功能说明:
        Web 请求只提交 Run ID，真实接口流程在线程池中执行。每个任务由
        AnalysisService 独立打开 SQLite 连接，不跨线程复用连接对象。
    """

    def __init__(
        self,
        service: AnalysisService,
        env_file: Path,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        """绑定执行服务、环境文件和可测试的 HTTP 客户端工厂。"""

        self.service = service
        self.env_file = env_file
        self.client_factory = client_factory or self._default_client
        self.executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="searchtool-run",
        )
        self._lock = threading.Lock()
        self._futures: dict[str, Future[None]] = {}

    def _default_client(self) -> SearchClient:
        """仅在后台真正开始执行时读取接口鉴权配置。"""

        return SearchClient(Config.from_env(self.env_file))

    def _execute(self, run_id: str) -> None:
        """执行一个 Run，意外错误转换为可见终态且不暴露堆栈。"""

        try:
            self.service.execute_run(
                run_id,
                self.client_factory(),
                sleep_fn=time.sleep,
            )
        except Exception as exc:
            self.service.mark_run_failed(
                run_id,
                f"后台执行失败（{type(exc).__name__}）: {exc}",
            )
        finally:
            with self._lock:
                self._futures.pop(run_id, None)

    def submit(self, run_id: str) -> None:
        """提交一个已创建的 PENDING Run，重复提交同一 ID 时拒绝。"""

        with self._lock:
            if run_id in self._futures:
                raise ActiveRunError(f"Run {run_id} 已提交")
            self._futures[run_id] = self.executor.submit(self._execute, run_id)

    def shutdown(self, *, wait: bool = True) -> None:
        """关闭后台执行器；命令行退出和测试清理时调用。"""

        self.executor.shutdown(wait=wait, cancel_futures=False)


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    """创建阶段3 Flask 应用并初始化 Store、Service 与后台执行器。

    参数说明:
        config_overrides: 测试或嵌入平台提供的 Flask/路径覆盖配置。

    返回值:
        已注册页面、状态 API、历史导入和受控下载路由的 Flask 应用。

    异常说明:
        数据库无法初始化或路径不可写时直接抛出，避免启动半可用服务。
        接口 Token 等配置延迟到真正执行 Run 时校验，不阻塞历史数据浏览。
    """

    overrides = dict(config_overrides or {})
    env_file = _project_path(
        overrides.get(
            "SEARCH_ENV_FILE",
            os.getenv("SEARCH_ENV_FILE", ".env"),
        )
    )
    file_values = dotenv_values(env_file) if env_file.is_file() else {}

    def setting(name: str, default: Any) -> Any:
        """按显式覆盖、进程环境、env 文件、默认值顺序读取配置。"""

        if name in overrides:
            return overrides[name]
        if name in os.environ:
            return os.environ[name]
        return file_values.get(name, default)

    data_dir = _project_path(setting("SEARCH_DATA_DIR", "data"))
    db_path = _project_path(
        setting("SEARCH_DB_FILE", data_dir / "searchtool_v1_3.db")
    )
    import_dir = _project_path(
        setting("SEARCH_IMPORT_DIR", data_dir / "imports")
    )
    raw_dir = _project_path(setting("SEARCH_RAW_DIR", data_dir / "raw"))
    report_dir = _project_path(
        setting("SEARCH_REPORT_DIR", "output/reports")
    )
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=str(setting("SEARCH_WEB_SECRET_KEY", "local-searchtool-v1.3")),
        SEARCH_DATA_DIR=str(data_dir),
        SEARCH_DB_FILE=str(db_path),
        SEARCH_IMPORT_DIR=str(import_dir),
        SEARCH_RAW_DIR=str(raw_dir),
        SEARCH_REPORT_DIR=str(report_dir),
        SEARCH_REPORT_EXCEL_ENABLED=_boolean_value(
            setting("SEARCH_REPORT_EXCEL_ENABLED", True),
            True,
        ),
        SEARCH_ENV_FILE=str(env_file),
        SEARCH_WEB_HOST=str(setting("SEARCH_WEB_HOST", "127.0.0.1")),
        SEARCH_WEB_PORT=_positive_int(setting("SEARCH_WEB_PORT", 5002), 5002),
        MAX_CONTENT_LENGTH=_positive_int(
            setting("SEARCH_WEB_MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
            50 * 1024 * 1024,
        ),
        RECOVER_INTERRUPTED_RUNS=True,
    )
    app.config.update(overrides)

    store = AnalysisStore(app.config["SEARCH_DB_FILE"])
    store.initialize()
    service = AnalysisService(
        store,
        app.config["SEARCH_DATA_DIR"],
        import_dir=app.config["SEARCH_IMPORT_DIR"],
        raw_dir=app.config["SEARCH_RAW_DIR"],
        report_dir=app.config["SEARCH_REPORT_DIR"],
    )
    service.ensure_default_field_schema()
    if app.config.get("RECOVER_INTERRUPTED_RUNS", True):
        service.recover_interrupted_runs()
    coordinator = RunCoordinator(service, Path(app.config["SEARCH_ENV_FILE"]))
    app.extensions["analysis_store"] = store
    app.extensions["analysis_service"] = service
    app.extensions["run_coordinator"] = coordinator
    app.extensions["default_run_coordinator"] = coordinator

    def page_number(name: str = "page") -> int:
        """读取最小为1的分页页码。"""

        return max(_positive_int(request.args.get(name, 1), 1), 1)

    def parse_json(value: Any, default: Any) -> Any:
        """解析数据库 JSON TEXT；异常历史值回退而不破坏详情页。"""

        if value in (None, ""):
            return default
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    def render_imports(
        *,
        status: int = 200,
        errors: list[str] | None = None,
    ) -> tuple[str, int]:
        """渲染导入页所需的 Evaluation 和 Dataset 选项。"""

        evaluations = store.fetch_all(
            "SELECT * FROM evaluations ORDER BY created_at DESC"
        )
        datasets = store.fetch_all(
            "SELECT * FROM datasets ORDER BY created_at DESC"
        )
        return (
            render_template(
                "imports.html",
                evaluations=evaluations,
                datasets=datasets,
                evaluation_phases=sorted(EVALUATION_PHASES),
                errors=errors or [],
            ),
            status,
        )

    def save_upload(upload: Any, directory: Path, role: str) -> Path | None:
        """把上传保存到受控临时目录并校验扩展名。

        返回值:
            未选择文件时返回 ``None``；其他情况返回临时文件绝对路径。

        异常说明:
            ImportValidationError: 文件后缀不受支持或安全文件名为空。
        """

        if upload is None or not upload.filename:
            return None
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise ImportValidationError(
                ["上传只支持 .jsonl、.json 或 .xlsx 文件"]
            )
        filename = secure_filename(upload.filename)
        if not filename:
            filename = f"{role}{suffix}"
        target = directory / f"{role}__{filename}"
        upload.save(target)
        return target

    @app.template_filter("status_class")
    def status_class(value: Any) -> str:
        """将状态映射为少量稳定的视觉等级。"""

        text = str(value or "").upper()
        if text in {
            "SUCCESS",
            "COMPLETED",
            "SUCCEEDED",
            "NO_CANDIDATE",
            "HIT",
            "REVIEWED",
            "READY",
            "HAS_CANDIDATES",
            "VALID",
        }:
            return "success"
        if text in {
            "FAILED",
            "PARTIAL_FAILED",
            "PARTIAL_DETAIL_FAILED",
            "INTERRUPTED",
            "NOT_HIT",
            "STALE",
            "EXECUTION_FAILED",
            "ERROR",
        }:
            return "danger"
        if text in {
            "RUNNING",
            "SEARCHING",
            "QUEUED",
            "PENDING",
            "PENDING_REVIEW",
            "SUSPECTED",
        }:
            return "active"
        return "neutral"

    @app.template_filter("is_http_url")
    def is_http_url(value: Any) -> bool:
        """仅允许 http/https 字符串显示为可点击 URL。"""

        if not isinstance(value, str):
            return False
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @app.template_filter("is_image_url")
    def is_image_url(value: Any) -> bool:
        """按常见扩展名判断是否展示受控缩略图。"""

        if not is_http_url(value):
            return False
        return Path(urlparse(value).path).suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
        }

    @app.get("/")
    def index() -> str:
        """展示 Evaluation 列表和 Run 汇总。"""

        evaluations = store.fetch_all(
            """
            SELECT e.*,
                   COUNT(r.run_id) AS run_count,
                   SUM(CASE WHEN r.status = 'RUNNING' THEN 1 ELSE 0 END)
                       AS running_count,
                   MAX(r.created_at) AS latest_run_at
            FROM evaluations AS e
            LEFT JOIN runs AS r ON r.evaluation_id = e.evaluation_id
            GROUP BY e.evaluation_id
            ORDER BY e.updated_at DESC
            """
        )
        return render_template("index.html", evaluations=evaluations)

    @app.route("/evaluations/new", methods=["GET", "POST"])
    def evaluation_new() -> Response | str | tuple[str, int]:
        """创建评测；重复或非法标识返回可行动错误。"""

        empty_thresholds = normalize_evaluation_thresholds({})
        if request.method == "GET":
            return render_template(
                "evaluation_new.html",
                thresholds=empty_thresholds,
                threshold_fields=EVALUATION_THRESHOLD_FIELDS,
            )
        try:
            evaluation_id = request.form.get("evaluation_id", "").strip()
            validate_storage_id(evaluation_id, "evaluation_id")
            thresholds = normalize_evaluation_thresholds(
                _threshold_form_payload(request.form)
            )
            store.create_evaluation(
                evaluation_id,
                request.form.get("name", "").strip(),
                request.form.get("notes", "").strip(),
                thresholds,
            )
        except Exception as exc:
            return (
                render_template(
                    "evaluation_new.html",
                    errors=[f"创建评测失败: {exc}"],
                    form=request.form,
                    thresholds=_threshold_form_payload(request.form),
                    threshold_fields=EVALUATION_THRESHOLD_FIELDS,
                ),
                400,
            )
        flash("评测创建成功", "success")
        return redirect(
            url_for(
                "evaluation_detail",
                evaluation_id=evaluation_id,
            )
        )

    @app.get("/evaluations/<evaluation_id>")
    def evaluation_detail(evaluation_id: str) -> str:
        """展示一个 Evaluation 下的 Run 和可执行 Dataset。"""

        evaluation = store.fetch_one(
            "SELECT * FROM evaluations WHERE evaluation_id = ?",
            (evaluation_id,),
        )
        if evaluation is None:
            abort(404)
        try:
            thresholds = normalize_evaluation_thresholds(
                parse_json(evaluation["thresholds_json"], {})
            )
        except ReviewValidationError:
            thresholds = normalize_evaluation_thresholds({})
        runs = store.fetch_all(
            """
            SELECT * FROM runs
            WHERE evaluation_id = ?
            ORDER BY created_at DESC
            """,
            (evaluation_id,),
        )
        datasets = store.fetch_all(
            "SELECT * FROM datasets ORDER BY created_at DESC"
        )
        reports = store.fetch_all(
            """
            SELECT rp.*, pr.run_id, r.run_label, r.system_version
            FROM reports AS rp
            JOIN process_runs AS pr
              ON pr.process_id = rp.candidate_process_id
            JOIN runs AS r ON r.run_id = pr.run_id
            WHERE rp.evaluation_id = ?
            ORDER BY rp.created_at DESC
            """,
            (evaluation_id,),
        )
        return render_template(
            "evaluation_detail.html",
            evaluation=evaluation,
            runs=runs,
            datasets=datasets,
            reports=reports,
            thresholds=thresholds,
            threshold_fields=EVALUATION_THRESHOLD_FIELDS,
            evaluation_phases=sorted(
                phase
                for phase in EVALUATION_PHASES
                if phase != "UNSPECIFIED"
            ),
        )

    @app.post("/evaluations/<evaluation_id>/thresholds")
    def evaluation_thresholds_update(
        evaluation_id: str,
    ) -> Response | tuple[str, int]:
        """校验并保存 Evaluation 参考线，非法提交不覆盖旧值。"""

        try:
            service.update_evaluation_thresholds(
                evaluation_id,
                _threshold_form_payload(request.form),
            )
        except ReviewValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法保存参考线",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("参考线已保存；既有报告仍保留生成时快照", "success")
        return redirect(
            url_for(
                "evaluation_detail",
                evaluation_id=evaluation_id,
            )
        )

    @app.post("/evaluations/<evaluation_id>/runs")
    def run_create(evaluation_id: str) -> Response | tuple[str, int]:
        """创建执行 Run 并立即提交给单线程后台协调器。"""

        try:
            run_id = service.create_execution_run(
                evaluation_id=evaluation_id,
                dataset_id=request.form.get("dataset_id", "").strip(),
                run_label=request.form.get("run_label", "").strip(),
                system_version=request.form.get("system_version", "").strip(),
                evaluation_phase=request.form.get(
                    "evaluation_phase",
                    "",
                ).strip(),
            )
            app.extensions["run_coordinator"].submit(run_id)
        except ActiveRunError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法启动新的执行",
                    message=str(exc),
                    status_code=409,
                ),
                409,
            )
        except (ImportValidationError, ValueError) as exc:
            return (
                render_template(
                    "error.html",
                    title="执行参数错误",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("Run 已进入后台执行队列", "success")
        return redirect(url_for("run_detail", run_id=run_id))

    @app.get("/runs/<run_id>")
    def run_detail(run_id: str) -> str:
        """服务端分页展示 Run 的 Query、失败和最新进度。"""

        run = store.fetch_one(
            """
            SELECT r.*, e.name AS evaluation_name
            FROM runs AS r
            JOIN evaluations AS e ON e.evaluation_id = r.evaluation_id
            WHERE r.run_id = ?
            """,
            (run_id,),
        )
        if run is None:
            abort(404)
        page = page_number()
        per_page = 50
        keyword = request.args.get("q", "").strip()
        status = request.args.get("status", "").strip()
        result_status = request.args.get("result_status", "").strip()
        query_stage = request.args.get("query_stage", "").strip()
        sort = request.args.get("sort", "query_id")
        direction = request.args.get("direction", "asc").lower()
        sort_columns = {
            "query_id": "query_id",
            "person_id": "person_id",
            "query_stage": "query_stage",
            "status": "status",
            "result_status": "result_status",
            "candidate_count_listed": "candidate_count_listed",
            "detail_failure_count": "detail_failure_count",
        }
        sort_column = sort_columns.get(sort, "query_id")
        sort_direction = "DESC" if direction == "desc" else "ASC"
        where = ["run_id = ?"]
        parameters: list[Any] = [run_id]
        if keyword:
            where.append(
                "(query_id LIKE ? OR COALESCE(person_id, '') LIKE ? "
                "OR COALESCE(task_id, '') LIKE ?)"
            )
            wildcard = f"%{keyword}%"
            parameters.extend([wildcard, wildcard, wildcard])
        if status in QUERY_STATUSES:
            where.append("status = ?")
            parameters.append(status)
        if result_status in RESULT_STATUSES:
            where.append("result_status = ?")
            parameters.append(result_status)
        if query_stage in QUERY_STAGES:
            where.append("query_stage = ?")
            parameters.append(query_stage)
        where_sql = " AND ".join(where)
        total = store.fetch_one(
            f"SELECT COUNT(*) AS count FROM run_queries WHERE {where_sql}",
            parameters,
        )["count"]
        queries = store.fetch_all(
            f"""
            SELECT * FROM run_queries
            WHERE {where_sql}
            ORDER BY {sort_column} {sort_direction}, query_id ASC
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        )
        failures = store.fetch_all(
            """
            SELECT * FROM failures
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (run_id,),
        )
        field_schemas = store.fetch_all(
            """
            SELECT schema_version, name, is_active
            FROM field_schemas
            ORDER BY is_active DESC, created_at DESC
            """
        )
        process_runs = store.fetch_all(
            """
            SELECT pr.*, fs.name AS schema_name
            FROM process_runs AS pr
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.run_id = ?
            ORDER BY pr.created_at DESC
            """,
            (run_id,),
        )
        baseline_sets = store.fetch_all(
            """
            SELECT bs.baseline_version, bs.name, COUNT(bp.person_id) AS person_count
            FROM baseline_sets AS bs
            LEFT JOIN baseline_people AS bp
              ON bp.baseline_version = bs.baseline_version
            GROUP BY bs.baseline_version
            ORDER BY bs.created_at DESC
            """
        )
        result_status_counts = {
            row["result_status"]: row["count"]
            for row in store.fetch_all(
                """
                SELECT COALESCE(result_status, 'UNSPECIFIED') AS result_status,
                       COUNT(*) AS count
                FROM run_queries WHERE run_id = ?
                GROUP BY COALESCE(result_status, 'UNSPECIFIED')
                """,
                (run_id,),
            )
        }
        return render_template(
            "run_detail.html",
            run=run,
            queries=queries,
            failures=failures,
            field_schemas=field_schemas,
            baseline_sets=baseline_sets,
            process_runs=process_runs,
            page=page,
            per_page=per_page,
            total=total,
            filters={
                "q": keyword,
                "status": status,
                "result_status": result_status,
                "query_stage": query_stage,
                "sort": sort,
                "direction": direction,
            },
            terminal_statuses=TERMINAL_RUN_STATUSES,
            result_status_counts=result_status_counts,
            evaluation_phases=sorted(EVALUATION_PHASES),
        )

    @app.post("/runs/<run_id>/evaluation-phase")
    def run_evaluation_phase_update(run_id: str) -> Response | tuple[str, int]:
        """人工补录或修正 Run 评估阶段，不根据名称自动猜测。"""

        try:
            service.update_run_evaluation_phase(
                run_id,
                request.form.get("evaluation_phase", "").strip(),
            )
        except ImportValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="评估阶段更新失败",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("Evaluation Phase 已更新", "success")
        return redirect(url_for("run_detail", run_id=run_id))

    @app.get("/runs/<run_id>/queries/<query_id>")
    def query_detail(run_id: str, query_id: str) -> str:
        """展示 Query 输入、Task、候选人、失败和 Raw 索引。"""

        query = store.fetch_one(
            """
            SELECT rq.*, r.evaluation_id, r.dataset_id, r.run_label,
                   r.system_version, r.evaluation_phase, dq.clues_json,
                   dq.additional_details_json, dq.metadata_json,
                   dq.match_strategy
            FROM run_queries AS rq
            JOIN runs AS r ON r.run_id = rq.run_id
            LEFT JOIN dataset_queries AS dq
              ON dq.dataset_id = r.dataset_id AND dq.query_id = rq.query_id
            WHERE rq.run_id = ? AND rq.query_id = ?
            """,
            (run_id, query_id),
        )
        if query is None:
            abort(404)
        page = page_number()
        per_page = 50
        candidate_total = store.fetch_one(
            """
            SELECT COUNT(*) AS count FROM candidates
            WHERE run_id = ? AND query_id = ?
            """,
            (run_id, query_id),
        )["count"]
        candidates = store.fetch_all(
            """
            SELECT * FROM candidates
            WHERE run_id = ? AND query_id = ?
            ORDER BY candidate_rank
            LIMIT ? OFFSET ?
            """,
            (run_id, query_id, per_page, (page - 1) * per_page),
        )
        raw_records = store.fetch_all(
            """
            SELECT raw_id, stage, sequence_no, candidate_pk, collected_at
            FROM raw_records
            WHERE run_id = ? AND query_id = ?
            ORDER BY collected_at, sequence_no
            """,
            (run_id, query_id),
        )
        failures = store.fetch_all(
            """
            SELECT * FROM failures
            WHERE run_id = ? AND query_id = ?
            ORDER BY created_at
            """,
            (run_id, query_id),
        )
        input_payload = {
            "match_strategy": query["match_strategy"],
            "clues": parse_json(query["clues_json"], []),
            "additional_details": parse_json(
                query["additional_details_json"],
                [],
            ),
            "metadata": parse_json(query["metadata_json"], {}),
        }
        task_field_states = []
        for field_key, expected_type in [
            ("llm_cost", "number"),
            ("third_party_cost", "number"),
            ("total_cost", "number"),
            ("pdl_called", "boolean"),
            ("search_duration_ms", "integer"),
        ]:
            value = query[field_key]
            if value is None:
                data_status = "MISSING"
            elif expected_type == "number" and (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
            ):
                data_status = "ERROR"
            elif expected_type == "boolean" and value not in {0, 1, False, True}:
                data_status = "ERROR"
            elif expected_type == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                data_status = "ERROR"
            else:
                data_status = "VALID"
            task_field_states.append(
                {
                    "field_key": field_key,
                    "value": value,
                    "data_status": data_status,
                }
            )
        return render_template(
            "query_detail.html",
            query=query,
            candidates=candidates,
            candidate_total=candidate_total,
            raw_records=raw_records,
            failures=failures,
            input_payload=input_payload,
            task_field_states=task_field_states,
            public_fields=parse_json(query["public_fields_json"], {}),
            page=page,
            per_page=per_page,
        )

    @app.get("/candidates/<candidate_pk>")
    def candidate_detail(candidate_pk: str) -> str:
        """展示 Candidate 五个业务模块和按需加载的 Detail Raw。"""

        candidate = store.fetch_one(
            """
            SELECT c.*, r.evaluation_id, r.run_label, r.system_version
            FROM candidates AS c
            JOIN runs AS r ON r.run_id = c.run_id
            WHERE c.candidate_pk = ?
            """,
            (candidate_pk,),
        )
        if candidate is None:
            abort(404)
        raw_records = store.fetch_all(
            """
            SELECT raw_id, stage, sequence_no, collected_at
            FROM raw_records
            WHERE candidate_pk = ?
            ORDER BY collected_at, sequence_no
            """,
            (candidate_pk,),
        )
        ui_sections = parse_json(candidate["ui_sections_json"], {})
        requested_process_id = request.args.get("process_id", "").strip()
        if requested_process_id:
            processed = store.fetch_one(
                """
                SELECT pc.*, pr.schema_version, pr.status AS process_status,
                       fs.name AS schema_name, fs.definitions_json
                FROM processed_candidates AS pc
                JOIN process_runs AS pr ON pr.process_id = pc.process_id
                JOIN field_schemas AS fs
                  ON fs.schema_version = pr.schema_version
                WHERE pc.candidate_pk = ? AND pc.process_id = ?
                """,
                (candidate_pk, requested_process_id),
            )
        else:
            processed = store.fetch_one(
                """
                SELECT pc.*, pr.schema_version, pr.status AS process_status,
                       fs.name AS schema_name, fs.definitions_json
                FROM processed_candidates AS pc
                JOIN process_runs AS pr ON pr.process_id = pc.process_id
                JOIN field_schemas AS fs
                  ON fs.schema_version = pr.schema_version
                WHERE pc.candidate_pk = ? AND pr.status = 'COMPLETED'
                ORDER BY pr.created_at DESC LIMIT 1
                """,
                (candidate_pk,),
            )
        processed_view = None
        review_context = None
        if processed is not None:
            definitions = parse_json(processed["definitions_json"], [])
            processed_view = {
                "process_id": processed["process_id"],
                "schema_version": processed["schema_version"],
                "schema_name": processed["schema_name"],
                "fields": parse_json(processed["fields_json"], {}),
                "empty_fields": parse_json(
                    processed["empty_fields_json"],
                    {},
                ),
                "errors": parse_json(
                    processed["processing_errors_json"],
                    [],
                ),
                "definitions": {
                    item.get("field_key"): item
                    for item in definitions
                    if isinstance(item, dict) and item.get("field_key")
                },
            }
            try:
                review_context = service.get_review_context(
                    processed["process_id"],
                    candidate_pk,
                )
            except ReviewValidationError:
                # 历史损坏数据仍允许查看 Raw，复核区显示为不可用。
                review_context = None
        return render_template(
            "candidate_detail.html",
            candidate=candidate,
            ui_sections=ui_sections,
            detail_data=parse_json(candidate["detail_data_json"], {}),
            list_item=parse_json(candidate["list_item_json"], {}),
            raw_records=raw_records,
            processed=processed_view,
            review=review_context,
        )

    @app.route("/imports", methods=["GET", "POST"])
    def imports() -> Response | tuple[str, int]:
        """通过受控上传导入 Dataset 或历史 JSONL/Excel 结果。"""

        if request.method == "GET":
            return render_imports()
        upload_root = data_dir / ".uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(
                prefix="web-import-",
                dir=upload_root,
            ) as temp_dir:
                temp_path = Path(temp_dir)
                source = save_upload(
                    request.files.get("source_file"),
                    temp_path,
                    "source",
                )
                if source is None:
                    raise ImportValidationError(["请选择需要导入的文件"])
                import_type = request.form.get("import_type", "")
                if import_type == "dataset":
                    name = request.form.get("name", "").strip()
                    if not name:
                        raise ImportValidationError(["数据集名称不能为空"])
                    dataset_id = request.form.get("dataset_id", "").strip() or None
                    if source.suffix.lower() == ".xlsx":
                        result = service.import_dataset_excel(
                            source,
                            name=name,
                            dataset_id=dataset_id,
                        )
                    elif source.suffix.lower() == ".jsonl":
                        result = service.import_dataset_jsonl(
                            source,
                            name=name,
                            dataset_id=dataset_id,
                        )
                    else:
                        raise ImportValidationError(
                            ["Dataset 只支持 .jsonl 或 .xlsx"]
                        )
                    flash(
                        f"Dataset 导入成功，共 {result.imported_count} 条 Query",
                        "success",
                    )
                    return redirect(url_for("imports"))
                if import_type == "results_jsonl":
                    evaluation_id = request.form.get(
                        "evaluation_id",
                        "",
                    ).strip()
                    run_label = request.form.get("run_label", "").strip()
                    system_version = request.form.get(
                        "system_version",
                        "",
                    ).strip()
                    evaluation_phase = request.form.get(
                        "evaluation_phase",
                        "UNSPECIFIED",
                    ).strip()
                    if not evaluation_id or not run_label or not system_version:
                        raise ImportValidationError(
                            ["Evaluation、run_label 和 system_version 不能为空"]
                        )
                    if source.suffix.lower() != ".jsonl":
                        raise ImportValidationError(
                            ["历史 JSONL 结果必须使用 .jsonl 文件"]
                        )
                    failures = save_upload(
                        request.files.get("failures_file"),
                        temp_path,
                        "failures",
                    )
                    metadata = save_upload(
                        request.files.get("metadata_file"),
                        temp_path,
                        "metadata",
                    )
                    result = service.import_results_jsonl(
                        source,
                        evaluation_id=evaluation_id,
                        run_label=run_label,
                        system_version=system_version,
                        evaluation_phase=evaluation_phase,
                        failures_path=failures,
                        metadata_path=metadata,
                    )
                elif import_type == "results_excel":
                    evaluation_id = request.form.get(
                        "evaluation_id",
                        "",
                    ).strip()
                    run_label = request.form.get("run_label", "").strip()
                    system_version = request.form.get(
                        "system_version",
                        "",
                    ).strip()
                    evaluation_phase = request.form.get(
                        "evaluation_phase",
                        "UNSPECIFIED",
                    ).strip()
                    if not evaluation_id or not run_label or not system_version:
                        raise ImportValidationError(
                            ["Evaluation、run_label 和 system_version 不能为空"]
                        )
                    if source.suffix.lower() != ".xlsx":
                        raise ImportValidationError(
                            ["历史 Excel 结果必须使用 .xlsx 文件"]
                        )
                    result = service.import_results_excel(
                        source,
                        evaluation_id=evaluation_id,
                        run_label=run_label,
                        system_version=system_version,
                        evaluation_phase=evaluation_phase,
                    )
                else:
                    raise ImportValidationError(["请选择有效的导入类型"])
            flash(
                f"历史结果导入成功，共 {result.imported_count} 条 Query",
                "success",
            )
            return redirect(url_for("run_detail", run_id=result.object_id))
        except (
            ImportValidationError,
            DuplicateImportError,
            ValueError,
        ) as exc:
            errors = getattr(exc, "errors", None) or [str(exc)]
            return render_imports(status=400, errors=errors)

    @app.route("/baselines", methods=["GET", "POST"])
    def baselines() -> Response | str | tuple[str, int]:
        """导入版本化 Person 基准并分页查看人物记录。"""

        errors: list[str] = []
        if request.method == "POST":
            upload_root = data_dir / ".uploads"
            upload_root.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(
                    prefix="web-baseline-",
                    dir=upload_root,
                ) as temp_dir:
                    source = save_upload(
                        request.files.get("source_file"),
                        Path(temp_dir),
                        "baseline",
                    )
                    if source is None:
                        raise ImportValidationError(["请选择基准数据文件"])
                    name = request.form.get("name", "").strip()
                    baseline_version = request.form.get(
                        "baseline_version",
                        "",
                    ).strip()
                    if not name or not baseline_version:
                        raise ImportValidationError(
                            ["基准名称和 baseline_version 不能为空"]
                        )
                    if source.suffix.lower() == ".jsonl":
                        result = service.import_baseline_jsonl(
                            source,
                            name=name,
                            baseline_version=baseline_version,
                        )
                    elif source.suffix.lower() == ".xlsx":
                        result = service.import_baseline_excel(
                            source,
                            name=name,
                            baseline_version=baseline_version,
                        )
                    else:
                        raise ImportValidationError(
                            ["基准数据只支持 .jsonl 或 .xlsx"]
                        )
                flash(
                    f"基准导入成功，共 {result.imported_count} 人",
                    "success",
                )
                return redirect(
                    url_for(
                        "baselines",
                        baseline_version=result.object_id,
                    )
                )
            except (
                ImportValidationError,
                DuplicateImportError,
                ValueError,
            ) as exc:
                errors = getattr(exc, "errors", None) or [str(exc)]

        baseline_sets = store.fetch_all(
            """
            SELECT bs.*, COUNT(bp.person_id) AS person_count
            FROM baseline_sets AS bs
            LEFT JOIN baseline_people AS bp
              ON bp.baseline_version = bs.baseline_version
            GROUP BY bs.baseline_version
            ORDER BY bs.created_at DESC
            """
        )
        selected_version = request.args.get(
            "baseline_version",
            "",
        ).strip()
        if not selected_version and baseline_sets:
            selected_version = baseline_sets[0]["baseline_version"]
        page = page_number()
        per_page = 50
        people = []
        total = 0
        active_schema = store.fetch_one(
            """
            SELECT schema_version, definitions_json FROM field_schemas
            WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1
            """
        )
        active_definitions = []
        if active_schema is not None:
            try:
                active_definitions = validate_field_definitions(
                    parse_json(active_schema["definitions_json"], [])
                )
            except FieldSchemaValidationError:
                active_definitions = []
        candidate_definitions = {
            definition["field_key"]: definition
            for definition in active_definitions
            if definition["value_scope"] == "CANDIDATE"
            and definition["enabled"]
        }
        if selected_version:
            total_row = store.fetch_one(
                """
                SELECT COUNT(*) AS count FROM baseline_people
                WHERE baseline_version = ?
                """,
                (selected_version,),
            )
            total = total_row["count"] if total_row else 0
            rows = store.fetch_all(
                """
                SELECT * FROM baseline_people
                WHERE baseline_version = ?
                ORDER BY person_id LIMIT ? OFFSET ?
                """,
                (
                    selected_version,
                    per_page,
                    (page - 1) * per_page,
                ),
            )
            for row in rows:
                item = dict(row)
                item["fields"] = parse_json(row["fields_json"], {})
                item["evidence"] = parse_json(row["evidence_json"], {})
                item["available_fields"] = parse_json(
                    row["available_fields_json"],
                    [],
                )
                item["unknown_available_fields"] = [
                    field_key
                    for field_key in item["available_fields"]
                    if field_key not in candidate_definitions
                ]
                field_keys = list(candidate_definitions)
                for field_key in [
                    *item["fields"],
                    *item["available_fields"],
                ]:
                    if field_key not in field_keys:
                        field_keys.append(field_key)
                item["field_options"] = [
                    {
                        "field_key": field_key,
                        "display_name": candidate_definitions.get(
                            field_key,
                            {},
                        ).get("display_name", field_key),
                        "value": item["fields"].get(field_key),
                        "unknown": field_key not in candidate_definitions,
                    }
                    for field_key in field_keys
                ]
                people.append(item)
        status = 400 if errors else 200
        return (
            render_template(
                "baselines.html",
                baseline_sets=baseline_sets,
                selected_version=selected_version,
                people=people,
                page=page,
                per_page=per_page,
                total=total,
                active_schema=active_schema,
                errors=errors,
            ),
            status,
        )

    @app.post(
        "/baselines/<baseline_version>/people/<person_id>/available-fields"
    )
    def baseline_available_fields_update(
        baseline_version: str,
        person_id: str,
    ) -> Response | tuple[str, int]:
        """保存人物级可评估字段，来源标记为人工维护。"""

        try:
            service.update_baseline_available_fields(
                baseline_version,
                person_id,
                request.form.getlist("available_fields"),
            )
        except ImportValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="Baseline 可用字段更新失败",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash("Baseline 可用字段已更新", "success")
        return redirect(
            url_for(
                "baselines",
                baseline_version=baseline_version,
            )
        )

    @app.get("/field-schemas")
    def field_schemas() -> str:
        """展示不可变字段配置版本、活跃状态和处理引用次数。"""

        rows = store.fetch_all(
            """
            SELECT fs.*, COUNT(pr.process_id) AS process_count
            FROM field_schemas AS fs
            LEFT JOIN process_runs AS pr
              ON pr.schema_version = fs.schema_version
            GROUP BY fs.schema_version
            ORDER BY fs.is_active DESC, fs.created_at DESC
            """
        )
        schemas = []
        for row in rows:
            item = dict(row)
            definitions = parse_json(row["definitions_json"], [])
            display_definitions = []
            for definition in definitions:
                if not isinstance(definition, dict):
                    continue
                field = dict(definition)
                field.setdefault(
                    "value_scope",
                    "QUERY"
                    if field.get("module") == "Task"
                    else "CANDIDATE",
                )
                field.setdefault(
                    "missing_policy",
                    "ERROR"
                    if field.get("field_key") in {"task_id", "candidate_id"}
                    else "EMPTY",
                )
                display_definitions.append(field)
            item["definitions"] = display_definitions
            item["query_field_count"] = sum(
                field["value_scope"] == "QUERY"
                for field in display_definitions
            )
            item["candidate_field_count"] = sum(
                field["value_scope"] == "CANDIDATE"
                for field in display_definitions
            )
            schemas.append(item)
        return render_template("field_schemas.html", schemas=schemas)

    @app.route("/field-schemas/new", methods=["GET", "POST"])
    def field_schema_new() -> Response | str | tuple[str, int]:
        """复制已有版本或提交完整 JSON，发布一个新的字段配置版本。"""

        base_version = (
            request.args.get("base", "").strip()
            if request.method == "GET"
            else request.form.get("base_version", "").strip()
        )
        base = None
        if base_version:
            base = store.fetch_one(
                "SELECT * FROM field_schemas WHERE schema_version = ?",
                (base_version,),
            )
            if base is None:
                abort(404)
        if request.method == "GET":
            if base is None:
                base = store.fetch_one(
                    """
                    SELECT * FROM field_schemas
                    WHERE is_active = 1
                    ORDER BY created_at DESC LIMIT 1
                    """
                )
            definitions = parse_json(
                base["definitions_json"] if base is not None else "[]",
                [],
            )
            return render_template(
                "field_schema_new.html",
                base=base,
                form={},
                definitions_json=json.dumps(
                    definitions,
                    ensure_ascii=False,
                    indent=2,
                ),
                errors=[],
            )
        raw_definitions = request.form.get("definitions_json", "")
        try:
            definitions = json.loads(raw_definitions)
            schema_version = service.publish_field_schema(
                name=request.form.get("name", "").strip(),
                definitions=definitions,
                created_by=request.form.get("created_by", "").strip(),
            )
        except (json.JSONDecodeError, FieldSchemaValidationError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                errors = [f"字段配置 JSON 格式错误: {exc.msg}"]
            else:
                errors = exc.errors
            return (
                render_template(
                    "field_schema_new.html",
                    base=base,
                    form=request.form,
                    definitions_json=raw_definitions,
                    errors=errors,
                ),
                400,
            )
        flash(f"字段配置已发布为新版本 {schema_version}", "success")
        return redirect(url_for("field_schemas"))

    @app.post("/runs/<run_id>/process")
    def process_run(run_id: str) -> Response | tuple[str, int]:
        """同步启动字段处理，每次提交都生成新的 ProcessResult。"""

        try:
            result = service.process_run(
                run_id=run_id,
                schema_version=request.form.get(
                    "schema_version",
                    "",
                ).strip(),
                baseline_version=request.form.get(
                    "baseline_version",
                    "",
                ).strip() or None,
            )
        except FieldSchemaValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法启动字段处理",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        flash(
            f"字段处理完成：候选人 {result.candidate_count}，"
            f"字段错误 {result.error_count}",
            "success",
        )
        return redirect(
            url_for("process_detail", process_id=result.process_id)
        )

    @app.get("/processes/<process_id>")
    def process_detail(process_id: str) -> str:
        """分页展示一次不可变处理结果及字段级错误。"""

        process = store.fetch_one(
            """
            SELECT pr.*, r.run_label, r.system_version, r.evaluation_id,
                   fs.name AS schema_name, fs.definitions_json
            FROM process_runs AS pr
            JOIN runs AS r ON r.run_id = pr.run_id
            JOIN field_schemas AS fs
              ON fs.schema_version = pr.schema_version
            WHERE pr.process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            abort(404)
        definitions = parse_json(process["definitions_json"], [])
        definitions_by_key = {
            item.get("field_key"): item
            for item in definitions
            if isinstance(item, dict) and item.get("field_key")
        }
        try:
            metrics = service.calculate_process_metrics(process_id)
        except ReviewValidationError:
            metrics = None
        comparison = None
        comparison_error = ""
        compare_process_id = request.args.get(
            "compare_process_id",
            "",
        ).strip()
        if compare_process_id:
            try:
                comparison = service.compare_processes(
                    compare_process_id,
                    process_id,
                )
            except ReviewValidationError as exc:
                comparison_error = str(exc)
        compatible_processes = store.fetch_all(
            """
            SELECT other.process_id, other.run_id, other.schema_version,
                   other.baseline_version, r.run_label, r.system_version
            FROM process_runs AS other
            JOIN runs AS r ON r.run_id = other.run_id
            WHERE r.evaluation_id = ?
              AND other.process_id <> ?
              AND other.status = 'COMPLETED'
            ORDER BY other.created_at DESC
            """,
            (process["evaluation_id"], process_id),
        )
        reports = store.fetch_all(
            """
            SELECT * FROM reports
            WHERE candidate_process_id = ? OR baseline_process_id = ?
            ORDER BY created_at DESC
            """,
            (process_id, process_id),
        )
        page = page_number()
        per_page = 50
        keyword = request.args.get("q", "").strip()
        where = ["pc.process_id = ?"]
        parameters: list[Any] = [process_id]
        if keyword:
            where.append(
                "(c.candidate_id LIKE ? OR c.query_id LIKE ?)"
            )
            wildcard = f"%{keyword}%"
            parameters.extend([wildcard, wildcard])
        where_sql = " AND ".join(where)
        total = store.fetch_one(
            f"""
            SELECT COUNT(*) AS count
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            WHERE {where_sql}
            """,
            parameters,
        )["count"]
        rows = store.fetch_all(
            f"""
            SELECT pc.*, c.run_id, c.query_id, c.candidate_id,
                   c.candidate_rank, c.detail_status,
                   rv.judgement, rv.reviewed_at
            FROM processed_candidates AS pc
            JOIN candidates AS c ON c.candidate_pk = pc.candidate_pk
            LEFT JOIN reviews AS rv
              ON rv.process_id = pc.process_id
             AND rv.candidate_pk = pc.candidate_pk
            WHERE {where_sql}
            ORDER BY c.query_id, c.candidate_rank
            LIMIT ? OFFSET ?
            """,
            [*parameters, per_page, (page - 1) * per_page],
        )
        candidates = []
        for row in rows:
            item = dict(row)
            item["fields"] = parse_json(row["fields_json"], {})
            item["empty_fields"] = parse_json(
                row["empty_fields_json"],
                {},
            )
            item["errors"] = parse_json(
                row["processing_errors_json"],
                [],
            )
            candidates.append(item)
        query_rows = store.fetch_all(
            """
            SELECT * FROM processed_queries
            WHERE process_id = ?
            ORDER BY query_id
            """,
            (process_id,),
        )
        processed_queries = []
        query_empty_count = 0
        query_error_count = 0
        for row in query_rows:
            item = dict(row)
            item["fields"] = parse_json(row["fields_json"], {})
            item["empty_fields"] = parse_json(
                row["empty_fields_json"],
                {},
            )
            item["errors"] = parse_json(
                row["processing_errors_json"],
                [],
            )
            query_empty_count += sum(
                bool(value) for value in item["empty_fields"].values()
            )
            query_error_count += len(item["errors"])
            processed_queries.append(item)
        candidate_empty_count = 0
        candidate_error_count = 0
        detail_failure_count = 0
        for row in store.fetch_all(
            """
            SELECT empty_fields_json, processing_errors_json
            FROM processed_candidates
            WHERE process_id = ?
            """,
            (process_id,),
        ):
            empty_fields = parse_json(row["empty_fields_json"], {})
            errors = parse_json(row["processing_errors_json"], [])
            candidate_empty_count += sum(
                bool(value) for value in empty_fields.values()
            )
            detail_failures = sum(
                error.get("code") == "DETAIL_FAILED"
                for error in errors
                if isinstance(error, dict)
            )
            detail_failure_count += detail_failures
            candidate_error_count += len(errors) - detail_failures
        return render_template(
            "process_detail.html",
            process=process,
            candidates=candidates,
            definitions=definitions_by_key,
            page=page,
            per_page=per_page,
            total=total,
            keyword=keyword,
            metrics=metrics,
            comparison=comparison,
            comparison_error=comparison_error,
            compare_process_id=compare_process_id,
            compatible_processes=compatible_processes,
            reports=reports,
            processed_queries=processed_queries,
            query_empty_count=query_empty_count,
            candidate_empty_count=candidate_empty_count,
            query_error_count=query_error_count,
            candidate_error_count=candidate_error_count,
            detail_failure_count=detail_failure_count,
        )

    @app.post(
        "/processes/<process_id>/candidates/<candidate_pk>/review"
    )
    def candidate_review(
        process_id: str,
        candidate_pk: str,
    ) -> Response | tuple[str, int]:
        """保存候选人最终判定及字段得分，拒绝旧页面覆盖新记录。"""

        try:
            raw_scores = request.form.get("field_scores_json", "").strip()
            if raw_scores:
                field_scores = json.loads(raw_scores)
            else:
                context = service.get_review_context(
                    process_id,
                    candidate_pk,
                )
                field_scores = context["field_scores"]
                for field_key, score in field_scores.items():
                    score["completeness_score"] = request.form.get(
                        f"completeness__{field_key}",
                        "",
                    )
                    score["accuracy_score"] = request.form.get(
                        f"accuracy__{field_key}",
                        "",
                    )
                    score["review_note"] = request.form.get(
                        f"field_note__{field_key}",
                        "",
                    )
            service.save_review(
                process_id=process_id,
                candidate_pk=candidate_pk,
                judgement=request.form.get("judgement", "").strip(),
                reason=request.form.get("reason", "").strip(),
                evidence=request.form.get("evidence", ""),
                reviewer=request.form.get("reviewer", ""),
                review_note=request.form.get("review_note", ""),
                field_scores=field_scores,
                expected_reviewed_at=request.form.get(
                    "expected_reviewed_at",
                    "",
                ),
            )
        except json.JSONDecodeError as exc:
            error = ReviewValidationError(
                f"字段得分 JSON 格式错误: {exc.msg}"
            )
            return (
                render_template(
                    "error.html",
                    title="无法保存复核",
                    message=str(error),
                    status_code=400,
                ),
                400,
            )
        except ReviewValidationError as exc:
            return (
                render_template(
                    "error.html",
                    title="无法保存复核",
                    message=str(exc),
                    status_code=409 if "其他页面" in str(exc) else 400,
                ),
                409 if "其他页面" in str(exc) else 400,
            )
        flash("候选人复核已保存，关联 READY 报告已标记过期", "success")
        return redirect(
            url_for(
                "candidate_detail",
                candidate_pk=candidate_pk,
                process_id=process_id,
            )
        )

    @app.post("/reports")
    def report_create() -> Response | tuple[str, int]:
        """创建报告模型快照、静态 HTML，并尽力生成 processed Excel。"""

        report = None
        try:
            report = service.create_report(
                candidate_process_id=request.form.get(
                    "candidate_process_id",
                    "",
                ).strip(),
                baseline_process_id=request.form.get(
                    "baseline_process_id",
                    "",
                ).strip()
                or None,
                data_marker=request.form.get(
                    "data_marker",
                    "REAL_TEST_DATA",
                ).strip(),
            )
            static_html = render_template(
                "report_static.html",
                report=report.model,
                static_export=True,
            )
            service.save_report_html(report.report_id, static_html)
        except (ReviewValidationError, ValueError) as exc:
            if report is not None:
                service.mark_report_failed(report.report_id)
            return (
                render_template(
                    "error.html",
                    title="无法生成报告",
                    message=str(exc),
                    status_code=400,
                ),
                400,
            )
        except Exception as exc:
            if report is not None:
                service.mark_report_failed(report.report_id)
            return (
                render_template(
                    "error.html",
                    title="报告文件生成失败",
                    message=f"{type(exc).__name__}: {str(exc)[:500]}",
                    status_code=500,
                ),
                500,
            )
        excel_message = ""
        if app.config.get("SEARCH_REPORT_EXCEL_ENABLED", True):
            try:
                service.export_report_excel(report.report_id)
            except (RuntimeError, subprocess.SubprocessError) as exc:
                excel_message = f"；Excel 暂不可用：{str(exc)[:300]}"
        flash(
            f"报告 {report.report_id} 已生成{excel_message}",
            "success" if not excel_message else "warning",
        )
        return redirect(
            url_for("report_detail", report_id=report.report_id)
        )

    @app.get("/reports/<report_id>")
    def report_detail(report_id: str) -> str:
        """只读取 metrics_json 快照展示报告，不重新计算历史数字。"""

        row = store.fetch_one(
            """
            SELECT rp.*, candidate.run_id AS candidate_run_id,
                   baseline.run_id AS baseline_run_id
            FROM reports AS rp
            JOIN process_runs AS candidate
              ON candidate.process_id = rp.candidate_process_id
            LEFT JOIN process_runs AS baseline
              ON baseline.process_id = rp.baseline_process_id
            WHERE rp.report_id = ?
            """,
            (report_id,),
        )
        if row is None:
            abort(404)
        model = parse_json(row["metrics_json"], {})
        return render_template(
            "report_detail.html",
            report=model,
            report_row=row,
            static_export=False,
        )

    @app.get("/api/runs/<run_id>/status")
    def run_status(run_id: str) -> Response:
        """返回页面定时刷新需要的 Run 和当前 Query 进度。"""

        run = store.fetch_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if run is None:
            abort(404)
        current = store.fetch_one(
            """
            SELECT query_id, current_stage
            FROM run_queries
            WHERE run_id = ? AND status = 'RUNNING'
            ORDER BY started_at DESC LIMIT 1
            """,
            (run_id,),
        )
        return jsonify(
            {
                "run_id": run_id,
                "status": run["status"],
                "total_queries": run["total_queries"],
                "completed_queries": (
                    run["success_queries"] + run["failed_queries"]
                ),
                "success_queries": run["success_queries"],
                "failed_queries": run["failed_queries"],
                "current_query_id": current["query_id"] if current else "",
                "current_stage": current["current_stage"] if current else "",
                "message": run["message"],
            }
        )

    @app.get("/api/field-schemas/<schema_version>")
    def field_schema_api(schema_version: str) -> Response:
        """返回字段配置快照，供页面预览和平台后续集成。"""

        schema = store.fetch_one(
            "SELECT * FROM field_schemas WHERE schema_version = ?",
            (schema_version,),
        )
        if schema is None:
            abort(404)
        definitions = validate_field_definitions(
            parse_json(schema["definitions_json"], [])
        )
        return jsonify(
            {
                "schema_version": schema["schema_version"],
                "name": schema["name"],
                "created_by": schema["created_by"],
                "created_at": schema["created_at"],
                "is_active": bool(schema["is_active"]),
                "definitions": definitions,
            }
        )

    @app.get("/api/processes/<process_id>/status")
    def process_status(process_id: str) -> Response:
        """返回同步处理的终态摘要，保留未来后台化兼容入口。"""

        process = store.fetch_one(
            """
            SELECT process_id, run_id, schema_version, status,
                   error_count, created_at, finished_at
            FROM process_runs WHERE process_id = ?
            """,
            (process_id,),
        )
        if process is None:
            abort(404)
        return jsonify(dict(process))

    @app.get("/api/processes/<process_id>/metrics")
    def process_metrics(process_id: str) -> Response:
        """返回与 Process 页面相同的可追溯指标模型。"""

        try:
            return jsonify(service.calculate_process_metrics(process_id))
        except ReviewValidationError:
            abort(404)

    @app.get("/api/raw/<raw_id>")
    def raw_record(raw_id: str) -> Response:
        """按 Raw ID 返回一条脱敏业务 JSON，不在列表页嵌入大对象。"""

        raw = store.fetch_one(
            """
            SELECT raw_id, run_id, query_id, candidate_pk, stage,
                   sequence_no, payload_json, collected_at
            FROM raw_records WHERE raw_id = ?
            """,
            (raw_id,),
        )
        if raw is None:
            abort(404)
        return jsonify(
            {
                "raw_id": raw["raw_id"],
                "run_id": raw["run_id"],
                "query_id": raw["query_id"],
                "candidate_pk": raw["candidate_pk"],
                "stage": raw["stage"],
                "sequence_no": raw["sequence_no"],
                "collected_at": raw["collected_at"],
                "payload": parse_json(raw["payload_json"], {}),
            }
        )

    @app.get("/downloads/<file_type>/<run_id>")
    def download_run_file(file_type: str, run_id: str) -> Response:
        """通过数据库 ID 下载 Run JSONL 或报告 HTML/Excel。"""

        if file_type in {"report-html", "report-excel"}:
            try:
                target = service.resolve_report_artifact(
                    run_id,
                    "html" if file_type == "report-html" else "excel",
                )
            except ReviewValidationError:
                abort(404)
            return send_file(
                target,
                as_attachment=True,
                download_name=target.name,
            )

        columns = {"results": "results_file", "failures": "failures_file"}
        column = columns.get(file_type)
        if column is None:
            abort(404)
        row = store.fetch_one(
            f"SELECT {column} AS relative_path FROM runs WHERE run_id = ?",
            (run_id,),
        )
        if row is None or not row["relative_path"]:
            abort(404)
        target = (data_dir / row["relative_path"]).resolve()
        try:
            target.relative_to(data_dir.resolve())
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)
        return send_file(target, as_attachment=True, download_name=target.name)

    @app.errorhandler(413)
    def upload_too_large(_: HTTPException) -> tuple[str, int]:
        """上传超过限制时返回可读页面，不暴露 Flask 堆栈。"""

        return (
            render_template(
                "error.html",
                title="上传文件过大",
                message="请拆分文件，或调整 SEARCH_WEB_MAX_UPLOAD_BYTES。",
                status_code=413,
            ),
            413,
        )

    @app.errorhandler(404)
    def not_found(_: HTTPException) -> tuple[str, int]:
        """统一返回不包含内部路径的404页面。"""

        return (
            render_template(
                "error.html",
                title="没有找到该记录",
                message="请返回列表确认对象是否存在。",
                status_code=404,
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(_: HTTPException) -> tuple[str, int]:
        """隐藏内部堆栈和配置，只提供下一步建议。"""

        return (
            render_template(
                "error.html",
                title="页面处理失败",
                message="请查看终端日志并刷新页面；已落库数据不会被覆盖。",
                status_code=500,
            ),
            500,
        )

    return app


def build_parser() -> argparse.ArgumentParser:
    """构造本地 Web 启动参数。"""

    parser = argparse.ArgumentParser(description="启动 searchTool v1.3 本地 Web")
    parser.add_argument("--env-file", default=".env", help="环境变量文件")
    parser.add_argument("--host", default=None, help="监听地址，默认读取 .env")
    parser.add_argument("--port", type=int, default=None, help="监听端口")
    return parser


def main(argv: list[str] | None = None) -> int:
    """启动无自动重载的本地服务，退出时等待当前 Query 安全收尾。"""

    args = build_parser().parse_args(argv)
    overrides: dict[str, Any] = {"SEARCH_ENV_FILE": args.env_file}
    if args.host:
        overrides["SEARCH_WEB_HOST"] = args.host
    if args.port:
        overrides["SEARCH_WEB_PORT"] = args.port
    app = create_app(overrides)
    coordinator: RunCoordinator = app.extensions["default_run_coordinator"]
    try:
        app.run(
            host=app.config["SEARCH_WEB_HOST"],
            port=app.config["SEARCH_WEB_PORT"],
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    finally:
        coordinator.shutdown(wait=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
