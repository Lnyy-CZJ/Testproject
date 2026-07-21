"""
第零阶段契约冻结测试

验证范围:
    - SSE golden event 文本格式
    - schema diff 工具的表字段差异判断
    - OpenAPI 基础端点存在
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.api.v1.router import api_router
from app.infrastructure.sse import format_sse_event, status_changed_event
from app.schemas.common import PaginatedResponse
from scripts.schema_diff import ColumnSpec, collect_metadata_schema, diff_schema_maps


def test_sse_status_changed_golden_event():
    """验证缺陷状态变更 SSE 事件与 Go 版前端消费格式兼容"""
    event = status_changed_event(
        defect_id=1,
        from_status="pending_analysis",
        to_status="analyzing",
        operator_id=99,
    )

    assert event == (
        'event: defect:status_changed\n'
        'data: {"defectId":1,"fromStatus":"pending_analysis",'
        '"toStatus":"analyzing","operatorId":99}\n\n'
    )


def test_sse_rejects_empty_event_name():
    """验证空事件名会被拒绝，避免生成前端无法路由的 SSE 消息"""
    try:
        format_sse_event("", {"defectId": 1})
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:
        raise AssertionError("空 SSE 事件名应抛出 ValueError")


def test_schema_diff_detects_missing_column():
    """验证 schema diff 能发现 Go/Python 兼容性中的缺失字段"""
    expected = {"users": {"id": ColumnSpec("bigint", False), "email": ColumnSpec("string", False)}}
    actual = {"users": {"id": ColumnSpec("bigint", False)}}

    assert diff_schema_maps(expected, actual) == ["缺失字段: users.email"]


def test_schema_diff_detects_type_and_nullable_mismatch():
    """验证 schema diff 能发现字段类型和 nullable 语义不一致"""
    expected = {"defects": {"status": ColumnSpec("string", False)}}
    actual = {"defects": {"status": ColumnSpec("text", True)}}

    assert diff_schema_maps(expected, actual) == [
        "字段类型不一致: defects.status expected=string actual=text",
        "字段 nullable 不一致: defects.status expected=False actual=True",
    ]


def test_metadata_schema_contains_phase_zero_core_tables():
    """验证 ORM baseline 已注册第零阶段需要冻结的核心表"""
    schema = collect_metadata_schema()

    for table_name in [
        "users",
        "projects",
        "iterations",
        "project_repos",
        "defects",
        "analysis_reports",
        "fix_tasks",
        "issue_clusters",
        "notifications",
    ]:
        assert table_name in schema


def test_api_routes_serialize_response_using_camel_case_field_names():
    """
    验证 API 路由不按 ORM snake_case alias 输出响应。

    返回值:
        None: 所有业务路由统一关闭 response_model_by_alias。
    """
    business_routes = [route for route in api_router.routes if isinstance(route, APIRoute)]

    assert business_routes
    assert all(route.response_model_by_alias is False for route in business_routes)


def test_paginated_response_keeps_legacy_list_field_with_camel_case_serialization():
    """
    验证关闭 alias 响应序列化后分页兼容字段仍命名为 list。

    返回值:
        None: items 与 list 同时可供前端读取。
    """
    payload = PaginatedResponse.from_items(items=[{"id": 1}], total=1, page=1, size=20)
    serialized = payload.model_dump(by_alias=False)

    assert serialized["items"] == [{"id": 1}]
    assert serialized["list"] == [{"id": 1}]
    assert "list_" not in serialized
