"""上传、Review 和产物路径安全测试。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from services.common.artifacts import preview_artifact, publish_artifact, resolve_artifact, save_registry
from services.common.errors import ServiceError
from services.common.task_store import TaskStore, new_task_id
from services.common.uploads import FUNCTIONAL_EXTENSIONS, read_validated_text, validate_review_json


def test_upload_limits_utf8_and_filename_safety() -> None:
    data, text, extension = read_validated_text(
        io.BytesIO(b"# requirement\n"), filename="requirement.md", mimetype="text/markdown",
        allowed_extensions=FUNCTIONAL_EXTENSIONS,
    )
    assert data and text and extension == ".md"
    for payload, filename in [(b"\xff", "requirement.md")]:
        with pytest.raises(ServiceError):
            read_validated_text(io.BytesIO(payload), filename=filename, mimetype="text/plain", allowed_extensions=FUNCTIONAL_EXTENSIONS)
    with pytest.raises(ServiceError):
        read_validated_text(io.BytesIO(b"x"), filename="../requirement.md", mimetype="text/plain", allowed_extensions=FUNCTIONAL_EXTENSIONS)


def test_review_schema_and_artifact_containment(tmp_path: Path) -> None:
    points = validate_review_json('[{"test_point":"登录成功"}]')
    assert points[0]["test_point"] == "登录成功"
    with pytest.raises(ServiceError):
        validate_review_json('[{"name":"missing"}]')

    store = TaskStore(tmp_path / "runtime")
    task_id = new_task_id()
    task_dir = store.task_dir(task_id, create=True)
    source = task_dir / "work" / "result.json"
    source.write_text("[]", encoding="utf-8")
    item = publish_artifact(store, task_id, source, artifact_type="result_json", stage="completed", destination_group="results")
    save_registry(store, task_id, [item])
    path, loaded = resolve_artifact(store, task_id, item["id"])
    assert path.read_text(encoding="utf-8") == "[]"
    assert loaded["sha256"] == item["sha256"]
    with pytest.raises(FileNotFoundError):
        resolve_artifact(store, task_id, "artifact_forged")


def test_artifact_preview_redacts_internal_paths(tmp_path: Path) -> None:
    """在线预览不得把容器或宿主机绝对路径暴露给普通用户。"""

    artifact = tmp_path / "requirements.json"
    artifact.write_text('{"source_path":"/app/runtime/dev/functional/tasks/task_123/input/source.md"}', encoding="utf-8")

    content = preview_artifact(artifact)["content"]

    assert "/app/runtime" not in content
    assert "[INTERNAL_PATH]" in content
