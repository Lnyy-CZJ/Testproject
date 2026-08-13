"""功能测试智能体 Flask 应用入口。"""

from __future__ import annotations

from pathlib import Path

from services.common.config import ServiceSettings, load_service_settings
from services.common.platform_client import PlatformClient
from services.common.task_manager import TaskManager
from services.common.task_store import TaskStore
from services.common.web import create_agent_app
from services.functional_agent.adapter import collect_result


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_app(
    *,
    settings: ServiceSettings | None = None,
    platform_client: PlatformClient | None = None,
    safe_config_loader=None,
    manager_factory=None,
):
    """创建功能智能体应用；注入点仅用于隔离自动化测试。"""

    active_settings = settings or load_service_settings(
        "functional-test-agent", "functional", "/functional-test-agent", 5004,
    )

    def default_manager(store: TaskStore, config_loader):
        return TaskManager(
            store=store,
            runner_module="services.functional_agent.runner",
            config_loader=config_loader,
            result_collector=lambda task_id, task_dir, result: collect_result(store, task_id, task_dir, result),
            project_root=PROJECT_ROOT,
            prompt_paths=["agents/functional_test/prompts", "prompts"],
            app_revision=active_settings.app_revision,
        )

    return create_agent_app(
        settings=active_settings,
        manager_factory=manager_factory or default_manager,
        operations={"decompose_requirement", "generate_test_points", "generate_test_cases", "full_pipeline"},
        title="功能测试智能体",
        description="从需求拆解到测试点 Review，再生成可下载的功能测试用例。",
        platform_client=platform_client,
        safe_config_loader=safe_config_loader,
    )


if __name__ == "__main__":
    settings = load_service_settings("functional-test-agent", "functional", "/functional-test-agent", 5004)
    app = create_app(settings=settings)
    app.run(host=settings.host, port=settings.port, threaded=True)
