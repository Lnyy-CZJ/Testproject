"""API 测试智能体 Flask 应用入口。"""

from __future__ import annotations

from pathlib import Path
import os

from services.api_agent.adapter import collect_result
from services.api_agent.blueprint import create_api_v2_blueprint
from services.common.config import ServiceSettings, load_service_settings
from services.common.platform_client import PlatformClient
from services.api_agent.task_manager import ApiTaskManager
from services.api_agent.controller_client import ControllerClient
from services.api_agent.execution_config import execution_enabled, load_execution_targets
from services.api_agent.execution_service import RealExecutionService
from services.common.task_store import TaskStore
from services.common.web import create_agent_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(
    *,
    settings: ServiceSettings | None = None,
    platform_client: PlatformClient | None = None,
    safe_config_loader=None,
    manager_factory=None,
):
    """创建 API 智能体应用；真实运行时仅在非生产显式开关下注册。"""

    active_settings = settings or load_service_settings(
        "api-test-agent", "api", "/api-test-agent", 5005,
    )

    def default_manager(store: TaskStore, config_loader):
        return ApiTaskManager(
            store=store,
            runner_module="services.api_agent.runner",
            config_loader=config_loader,
            result_collector=lambda task_id, task_dir, result: collect_result(store, task_id, task_dir, result),
            project_root=PROJECT_ROOT,
            prompt_paths=["agents/api_test/prompts"],
            app_revision=active_settings.app_revision,
            # OpenAPI/Swagger 确定性解析不依赖模型；非结构化解析在 Runner 内映射模型错误。
            require_llm_config=False,
        )

    app = create_agent_app(
        settings=active_settings,
        manager_factory=manager_factory or default_manager,
        operations={"parse_api_document", "generate_api_cases"},
        title="API 测试智能体",
        description="解析 API 文档并生成文件化测试用例；真实请求执行在 MVP 中保持关闭。",
        platform_client=platform_client,
        safe_config_loader=safe_config_loader,
    )
    app.register_blueprint(create_api_v2_blueprint(active_settings.base_path))
    app.extensions["api_execution_targets"] = load_execution_targets()
    app.extensions["api_execution_enabled"] = execution_enabled()
    if app.extensions["api_execution_enabled"]:
        controller = ControllerClient(
            os.getenv("API_EXECUTION_CONTROLLER_URL", "http://api-execution-controller:5010"),
            Path(os.getenv("API_EXECUTION_CONTROLLER_TOKEN_FILE", "/run/secrets/controller-token")),
        )
        app.extensions["api_real_execution_service"] = RealExecutionService(app.extensions["task_store"], controller)
    return app


if __name__ == "__main__":
    settings = load_service_settings("api-test-agent", "api", "/api-test-agent", 5005)
    app = create_app(settings=settings)
    app.run(host=settings.host, port=settings.port, threaded=True)
