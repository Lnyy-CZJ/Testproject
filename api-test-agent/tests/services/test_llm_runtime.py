from pathlib import Path

from services.common.task_manager import TaskManager
from services.common.task_store import TaskStore


def test_runner_environment_prefers_llm_snapshot_and_omits_empty_options(tmp_path: Path) -> None:
    """API Agent 只向当前任务注入已发布快照中的有效参数。"""
    manager = TaskManager(
        store=TaskStore(tmp_path / "runtime"), runner_module="unused",
        config_loader=lambda: {}, result_collector=lambda *_: {},
        project_root=tmp_path, prompt_paths=[], app_revision="test", autostart=False,
    )
    environment = manager._runner_environment({
        "normal": {"LLM_MODEL": "legacy-model"},
        "secrets": {"LLM_API_KEY": "legacy-key"},
        "llm": {
            "model": "snapshot-model", "base_url": "https://provider.example/v1",
            "api_key": "snapshot-key", "temperature": None,
            "max_tokens": 4096, "timeout_seconds": 45,
        },
    }, "task_test")
    assert environment["LLM_MODEL"] == "snapshot-model"
    assert environment["DASHSCOPE_API_KEY"] == "snapshot-key"
    assert environment["LLM_MAX_TOKENS"] == "4096"
    assert environment["LLM_TIMEOUT_SECONDS"] == "45"
    assert "LLM_TEMPERATURE" not in environment
