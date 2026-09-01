"""Dating AI Assistant 本地 Web 工作台。

Flask 只提供页面、Draft 输入和本地 Run 查询 API。任何真实的 Identity、Media、Task、
Result、Diagnostics、限流、轮询和 Delete 都必须经过 ``RunApplicationService``，因此 Web
层不会复制公开协议或内部 Evaluation 的请求拼装逻辑。
"""

from __future__ import annotations

import argparse
import atexit
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, url_for
from dotenv import load_dotenv

from aidating_eval.application import RunApplicationService, RunRequest
from aidating_eval.web.input_store import WebInputStore
from aidating_eval.web.run_manager import RunManager
from aidating_eval.web.run_repository import RunQuery, RunRepository
from aidating_eval.web.view_models import jsonable


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5005


def create_app(
    *,
    service: Any | None = None,
    manager: RunManager | Any | None = None,
    repository: Any | None = None,
    input_store: WebInputStore | Any | None = None,
    testing: bool = False,
) -> Flask:
    """创建可注入依赖的 Flask App，供本机运行和 Fake Integration 共用。"""

    package_root = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(package_root / "templates"),
        static_folder=str(package_root / "static"),
        static_url_path="/static",
    )
    app.config.update(
        TESTING=testing,
        MAX_CONTENT_LENGTH=int(os.getenv("AIDATING_WEB_MAX_CONTENT_BYTES", str(50 * 1024 * 1024))),
        WEB_HOST=DEFAULT_HOST,
        WEB_PORT=int(os.getenv("AIDATING_WEB_PORT", str(DEFAULT_PORT))),
    )

    artifacts_root = Path(os.getenv("AIDATING_ARTIFACTS_ROOT", "artifacts"))
    logs_root = Path(os.getenv("AIDATING_LOG_ROOT", "logs"))
    owned_manager = manager is None
    if input_store is None:
        draft_root = os.getenv(
            "AIDATING_WEB_DRAFT_ROOT",
            os.getenv("AIDATING_WEB_INPUT_ROOT", str(artifacts_root / ".drafts")),
        )
        input_store = WebInputStore(
            Path(draft_root)
        )
    if service is None:
        service = RunApplicationService()
    if manager is None:
        manager = RunManager(service=service, input_store=input_store)
    if repository is None:
        repository = RunRepository(
            artifacts_root=artifacts_root,
            logs_root=logs_root,
            active_provider=manager.snapshot,
        )
    app.extensions["aidating_service"] = service
    app.extensions["aidating_manager"] = manager
    app.extensions["aidating_repository"] = repository
    app.extensions["aidating_input_store"] = input_store
    if owned_manager:
        atexit.register(manager.shutdown, wait=False)

    @app.get("/")
    def index():
        return redirect(url_for("new_run"))

    @app.get("/runs/new")
    def new_run():
        return render_template("task_form.html", page_title="创建评测 Run")

    @app.get("/runs")
    def runs_page():
        return render_template("tasks.html", page_title="Run 记录")

    @app.get("/runs/<run_id>")
    def run_detail_page(run_id: str):
        return render_template("task_detail.html", run_id=run_id, page_title="Run 详情")

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "aidating-eval-web", "port": app.config["WEB_PORT"]})

    @app.get("/api/doctor")
    def doctor_api():
        mode = request.args.get("mode", "")
        if mode not in {"e2e", "eval"}:
            return _error("mode 必须为 e2e 或 eval", "INPUT_INVALID", 400)
        try:
            checks = service.doctor(mode)
        except Exception as exc:
            return _error(type(exc).__name__, type(exc).__name__, 500)
        return jsonify({"mode": mode, "checks": [jsonable(item) for item in checks]})

    @app.post("/api/runs/validate")
    def validate_run_api():
        try:
            draft = _get_or_create_draft(input_store)
            summary = service.validate(RunRequest(**draft.to_request_kwargs()))
        except Exception as exc:
            draft_id = locals().get("draft").draft_id if "draft" in locals() else None
            return _error(
                type(exc).__name__,
                "INPUT_INVALID",
                422,
                draft_id=draft_id,
            )
        return jsonify(
            {
                "draft_id": draft.draft_id,
                "mode": draft.mode,
                "task_kind": draft.task_kind,
                "summary": jsonable(summary),
            }
        )

    @app.post("/api/runs")
    def create_run_api():
        body = request.get_json(silent=True) or {}
        draft_id = body.get("draft_id")
        if not isinstance(draft_id, str) or not draft_id:
            return _error("draft_id 必填", "INPUT_INVALID", 400)
        try:
            handle = manager.submit(draft_id)
        except ValueError as exc:
            return _error(str(exc), "RUN_NOT_ACCEPTED", 409)
        except Exception as exc:
            return _error(type(exc).__name__, type(exc).__name__, 500)
        return jsonify({"run_id": handle.run_id, "draft_id": handle.draft_id, "status": "waiting"}), 202

    @app.get("/api/runs")
    def list_runs_api():
        try:
            query = RunQuery(
                mode=_optional_query("mode"),
                task_kind=_optional_query("task_kind"),
                status=_optional_query("status"),
                page=_positive_query_int("page", 1),
                page_size=min(100, _positive_query_int("page_size", 50)),
            )
            page = repository.list_runs(query)
        except ValueError as exc:
            return _error(str(exc), "INPUT_INVALID", 400)
        return jsonify(
            {
                "items": jsonable(page.items),
                "page": page.page,
                "page_size": page.page_size,
                "total": page.total,
            }
        )

    @app.get("/api/runs/<run_id>")
    def get_run_api(run_id: str):
        try:
            value = repository.get_run(run_id)
        except ValueError as exc:
            return _error(str(exc), "NOT_FOUND", 404)
        return jsonify(jsonable(value))

    @app.get("/api/runs/<run_id>/cases/<case_id>")
    def get_case_api(run_id: str, case_id: str):
        try:
            value = repository.get_case(run_id, case_id)
        except ValueError as exc:
            return _error(str(exc), "NOT_FOUND", 404)
        return jsonify(jsonable(value))

    @app.get("/api/runs/<run_id>/logs")
    def get_logs_api(run_id: str):
        try:
            tail = _positive_query_int("tail", 200)
            value = repository.tail_log(run_id, tail)
        except ValueError as exc:
            return _error(str(exc), "NOT_FOUND", 404)
        return jsonify(
            {
                "lines": list(getattr(value, "lines", ())),
                "truncated": bool(getattr(value, "truncated", False)),
                "tail": int(getattr(value, "tail", tail)),
            }
        )

    @app.post("/api/runs/<run_id>/cancel")
    def cancel_run_api(run_id: str):
        if not manager.cancel(run_id):
            return _error("Run 不存在", "NOT_FOUND", 404)
        return jsonify({"run_id": run_id, "cancel_requested": True})

    @app.errorhandler(413)
    def request_too_large(_error):
        return _error_response("上传内容超过本地限制", "INPUT_TOO_LARGE", 413)

    return app


def _get_or_create_draft(store: Any):
    body = request.get_json(silent=True) if request.is_json else None
    if isinstance(body, dict) and isinstance(body.get("draft_id"), str):
        return store.get(body["draft_id"])
    mode = request.form.get("mode") or (body or {}).get("mode")
    if mode == "e2e":
        task_kind = request.form.get("task_kind", "analysis")
        locale = request.form.get("locale", "en-US")
        files = request.files.getlist("media")
        media = []
        for item in files:
            if item.filename:
                media.append((item.filename, item.read()))
        options: dict[str, Any] = {}
        allowed = (
            ("dating_goal", "your_voice", "requested_intent", "background")
            if task_kind == "reply"
            else ("other_person_name", "background")
        )
        for key in allowed:
            value = request.form.get(key)
            if value not in (None, ""):
                options[key] = value
        return store.create_e2e_draft(
            task_kind=task_kind,
            locale=locale,
            media=media,
            case_options=options,
        )
    if mode == "eval":
        uploaded = request.files.get("dataset")
        if uploaded is None:
            raise ValueError("Eval 必须上传 dataset.jsonl")
        raw_concurrency = request.form.get("eval_concurrency")
        concurrency = int(raw_concurrency) if raw_concurrency else None
        case_id = request.form.get("case_id") or None
        return store.create_eval_draft(
            uploaded.read(),
            filename=uploaded.filename or "dataset.jsonl",
            case_id=case_id,
            eval_concurrency=concurrency,
        )
    raise ValueError("mode 必须为 e2e 或 eval")


def _optional_query(name: str) -> str | None:
    value = request.args.get(name)
    return value or None


def _positive_query_int(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} 必须为正整数")
    return value


def _error(message: str, code: str, status: int, **extra: Any):
    return _error_response(message, code, status, **extra)


def _error_response(message: str, code: str, status: int, **extra: Any):
    payload = {"success": False, "error_code": code, **extra}
    if message:
        payload["message"] = message
    return jsonify(payload), status


def main(argv: list[str] | None = None) -> int:
    """启动本机回环 Web 服务；生产部署不属于 MVP 范围。"""

    load_dotenv(override=False)
    parser = argparse.ArgumentParser(
        prog="dating-eval-web",
        description="Dating AI 本地 Web 评测工作台",
    )
    parser.parse_args(argv)
    app = create_app()
    app.run(
        host=app.config["WEB_HOST"],
        port=app.config["WEB_PORT"],
        debug=False,
        threaded=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
