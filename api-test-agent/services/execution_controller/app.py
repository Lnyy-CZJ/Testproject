"""独立 API 执行 Controller；该服务是唯一持有 Docker Socket 的组件。"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from flask import Flask, jsonify, request
from pydantic import ValidationError

from services.execution_controller.contracts import CreateRunRequest


def create_app(runtime=None) -> Flask:
    """创建窄 Controller API；内部 Token 每次从只读文件读取以支持轮换。"""

    app = Flask(__name__)
    token_file = Path(os.getenv("CONTROLLER_TOKEN_FILE", "/run/secrets/controller-token"))
    if runtime is None:
        # 延迟导入 Docker SDK，使契约测试和 Web 服务环境无需安装宿主运行时依赖。
        from services.execution_controller.docker_runtime import DockerRuntimeAdapter

        active_runtime = DockerRuntimeAdapter(
            runs_root=Path(os.environ["CONTROLLER_RUNS_ROOT"]),
            image_reference=os.environ["EXECUTOR_IMAGE"],
            executor_network=os.environ["EXECUTOR_NETWORK"],
            proxy_url=os.environ["EXECUTOR_PROXY_URL"],
            resource_policy_id=os.getenv("RESOURCE_POLICY_ID", "local-restricted-v1"),
            egress_policy_id=os.getenv("EGRESS_POLICY_ID", "local-platform-v1"),
        )
    else:
        active_runtime = runtime

    def authorized() -> bool:
        """恒定时间比较内部 Bearer Token；缺文件或空 Token 时失败关闭。"""

        try:
            expected = token_file.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return bool(expected and supplied and hmac.compare_digest(expected, supplied))

    @app.before_request
    def require_internal_auth():
        if request.path == "/health":
            return None
        if not authorized():
            return jsonify({"error": {"code": "CONTROLLER_UNAUTHORIZED", "message": "内部鉴权失败"}}), 401
        return None

    @app.get("/health")
    def health():
        return jsonify({
            "status": "ok", "service": "api-execution-controller",
            "image_id": getattr(active_runtime, "image_id", "fake"),
            "version": os.getenv("APP_VERSION", "unknown"),
            "revision": os.getenv("APP_REVISION", "unknown"),
            "dirty": os.getenv("APP_BUILD_DIRTY", "true").lower() == "true",
            "content_sha256": os.getenv("APP_CONTENT_SHA256", "unknown"),
            "runtime_environment": os.getenv("PLATFORM_RUNTIME_ENV", "unknown"),
        })

    @app.post("/internal/v1/runs")
    def create_run():
        try:
            payload = CreateRunRequest.model_validate(request.get_json(silent=True) or {})
        except ValidationError:
            return jsonify({"error": {"code": "CONTROLLER_REQUEST_INVALID", "message": "运行请求不合法"}}), 400
        result = active_runtime.create(payload)
        return jsonify(result.model_dump(mode="json")), 200 if result.status == "succeeded" else 409

    @app.post("/internal/v1/runs/<run_id>/cancel")
    def cancel_run(run_id: str):
        result = active_runtime.cancel(run_id)
        return jsonify(result.model_dump(mode="json")), 200 if result.status == "cancelled" else 404

    @app.post("/internal/v1/reconcile")
    def reconcile():
        body = request.get_json(silent=True) or {}
        active = {str(item) for item in body.get("active_run_ids", []) if str(item).startswith("run_")}
        return jsonify({"reclaimed_run_ids": active_runtime.reconcile(active)})

    return app
