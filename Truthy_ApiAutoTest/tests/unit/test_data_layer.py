"""测试数据加载、上下文与动态 ID 工厂测试。"""

from pathlib import Path

import pytest

from framework.data.context import CaseContext, SessionContext
from framework.data.factories import build_client_request_id, build_device_id, build_unique_name
from framework.data.loader import clear_case_data_cache, load_case_data


def test_case_data_cache_invalidates_after_file_change(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: C1\n  title: first\n  markers: [contract]\n  steps: []\n  expected: {}\n",
        encoding="utf-8",
    )
    clear_case_data_cache()
    first = load_case_data(path)

    path.write_text(
        "- id: C1\n  title: changed-title\n  markers: [contract]\n  steps: []\n  expected: {}\n",
        encoding="utf-8",
    )
    second = load_case_data(path)

    assert first[0]["title"] == "first"
    assert second[0]["title"] == "changed-title"


def test_case_data_rejects_incomplete_structure(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('[{"id": "C1"}]', encoding="utf-8")

    with pytest.raises(ValueError, match="测试数据结构无效"):
        load_case_data(path)


def test_case_context_stores_and_requires_dynamic_values() -> None:
    context = CaseContext(case_id="TC-001")
    context.set("task_id", "task-1")

    assert context.get("task_id") == "task-1"
    assert context.require("task_id") == "task-1"
    with pytest.raises(KeyError, match="missing"):
        context.require("missing")


def test_case_context_rejects_method_and_core_field_name_conflicts() -> None:
    context = CaseContext(case_id="TC-001")

    with pytest.raises(ValueError, match="保留名称"):
        context.set("get", "shadowed")
    with pytest.raises(ValueError, match="保留名称"):
        context.set("case_id", "changed")

    assert context.case_id == "TC-001"


def test_id_factories_are_traceable_and_unique() -> None:
    first = build_client_request_id("build-7", "TC-001")
    second = build_client_request_id("build-7", "TC-001")

    assert first.startswith("autotest-build-7-TC-001-")
    assert len(first.rsplit("-", 1)[-1]) >= 16
    assert first != second
    assert build_device_id("build-7").startswith("autotest-device-build-7-")
    assert build_unique_name("build-7", "TC-001").startswith("autotest-build-7-TC-001-")


def test_session_context_builds_from_complete_anonymous_session() -> None:
    context = SessionContext.from_anonymous_session(
        device_id="device-1",
        data={
            "user_id": "user-1",
            "access_token": "access-old",
            "expires_time": 1000,
            "refresh_token": "refresh-old",
            "refresh_expires_time": 2000,
            "is_new_user": True,
        },
    )

    assert context.device_id == "device-1"
    assert context.user_id == "user-1"
    assert context.access_token == "access-old"
    assert context.is_new_user is True


def test_session_context_refresh_replaces_all_token_fields_atomically() -> None:
    context = SessionContext(
        device_id="device-1",
        user_id="user-1",
        access_token="access-old",
        expires_time=1000,
        refresh_token="refresh-old",
        refresh_expires_time=2000,
    )

    context.replace_tokens(
        {
            "access_token": "access-new",
            "expires_time": 3000,
            "refresh_token": "refresh-new",
            "refresh_expires_time": 4000,
        }
    )

    assert (
        context.access_token,
        context.expires_time,
        context.refresh_token,
        context.refresh_expires_time,
        context.user_id,
    ) == ("access-new", 3000, "refresh-new", 4000, "user-1")


@pytest.mark.parametrize(
    "invalid_data",
    [
        {
            "access_token": "access-new",
            "expires_time": 3000,
            "refresh_token": "refresh-new",
        },
        {
            "access_token": "",
            "expires_time": 3000,
            "refresh_token": "refresh-new",
            "refresh_expires_time": 4000,
        },
        {
            "access_token": "access-new",
            "expires_time": "3000",
            "refresh_token": "refresh-new",
            "refresh_expires_time": 4000,
        },
    ],
)
def test_session_context_failed_refresh_does_not_partially_overwrite(
    invalid_data: dict[str, object],
) -> None:
    context = SessionContext(
        device_id="device-1",
        user_id="user-1",
        access_token="access-old",
        expires_time=1000,
        refresh_token="refresh-old",
        refresh_expires_time=2000,
    )

    with pytest.raises((KeyError, TypeError, ValueError)):
        context.replace_tokens(invalid_data)

    assert (
        context.access_token,
        context.expires_time,
        context.refresh_token,
        context.refresh_expires_time,
    ) == ("access-old", 1000, "refresh-old", 2000)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("device_id", ""),
        ("device_id", None),
        ("user_id", ""),
        ("user_id", 123),
        ("access_token", ""),
        ("access_token", object()),
        ("refresh_token", ""),
        ("refresh_token", []),
        ("expires_time", True),
        ("expires_time", "1000"),
        ("refresh_expires_time", False),
        ("refresh_expires_time", "2000"),
    ],
)
def test_session_context_direct_constructor_rejects_invalid_fields(
    field_name: str, invalid_value: object
) -> None:
    """直接构造必须与工厂和刷新路径执行相同的严格校验。"""
    values: dict[str, object] = {
        "device_id": "device-sensitive",
        "user_id": "user-sensitive",
        "access_token": "access-sensitive",
        "expires_time": 1000,
        "refresh_token": "refresh-sensitive",
        "refresh_expires_time": 2000,
    }
    values[field_name] = invalid_value

    with pytest.raises((TypeError, ValueError)):
        SessionContext(**values)


def test_session_context_repr_does_not_expose_identifiers_or_tokens() -> None:
    """调试 repr 不得泄露设备、用户或会话凭据原值。"""
    secrets = {
        "device_id": "device-sensitive",
        "user_id": "user-sensitive",
        "access_token": "access-sensitive",
        "refresh_token": "refresh-sensitive",
    }
    context = SessionContext(
        **secrets,
        expires_time=1000,
        refresh_expires_time=2000,
    )

    rendered = repr(context)

    assert all(value not in rendered for value in secrets.values())
