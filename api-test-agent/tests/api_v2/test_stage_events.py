"""阶段事件、Prompt 来源和模型用量存储测试。"""

from __future__ import annotations

import io
import logging

from services.api_agent.models import ModelUsageRecord, StageEvent
from services.api_agent.stage_events import StageEventStore
from services.common.errors import structured_log
from services.common.task_store import TaskStore, new_task_id


def test_stage_events_are_redacted_and_cursor_paginated(tmp_path) -> None:
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "status": "running"})
    events = StageEventStore(store)
    events.append(StageEvent(
        event_id="event_1", task_id=task_id, attempt_id="attempt_1",
        stage="base_case_generation", node="fused_kernel", event_type="started",
        status="running", message="Authorization: Bearer secret-value",
    ))
    events.append(StageEvent(
        event_id="event_2", task_id=task_id, attempt_id="attempt_1",
        stage="base_case_generation", node="grounding", event_type="completed",
        status="succeeded", message="完成",
    ))

    page = events.list_events(
        task_id, attempt_id="attempt_1", level="info", cursor=0, limit=1,
    )
    assert page["next_cursor"] == 1
    assert "secret-value" not in page["items"][0]["message"]
    assert page["items"][0]["level"] == "info"


def test_unreported_model_usage_is_not_estimated(tmp_path) -> None:
    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({"id": task_id, "status": "running"})
    events = StageEventStore(store)
    events.save_usage(task_id, ModelUsageRecord(
        call_id="call_1", attempt_id="attempt_1", stage="base_case_generation",
        node="llm_business_cases", prompt_id="base_case_v2", prompt_sha256="a" * 64,
        model_name="fake", reported=False,
    ))
    result = events.list_usage(task_id, attempt_id="attempt_1")
    assert result["summary"]["reported_calls"] == 0
    assert result["summary"]["total_tokens"] == 0
    assert result["items"][0]["reported"] is False


def test_file_usage_summary_groups_reported_tokens_and_retries(tmp_path) -> None:
    """文件化统计必须与原始用量一致，且不估算成本。"""

    store = TaskStore(tmp_path)
    task_id = new_task_id()
    store.task_dir(task_id, create=True)
    store.save({
        "id": task_id, "schema_version": 2, "status": "waiting_case_review",
        "project_id": "project-a", "project_name": "项目 A",
        "module_id": "login", "module_name": "登录",
    })
    events = StageEventStore(store)
    for call_id, retry in (("call_1", 0), ("call_2", 1)):
        events.save_usage(task_id, ModelUsageRecord(
            call_id=call_id, attempt_id="attempt_1", stage="base_case_generation",
            node="llm_business_cases", prompt_id="base_case_v2", prompt_sha256="a" * 64,
            model_name="fake", input_tokens=100, output_tokens=50, total_tokens=150,
            reported=True, retry_number=retry, duration_ms=100 + retry,
        ))

    result = events.summarize_usage([store.load(task_id)], group_by="stage")

    assert result["summary"]["call_count"] == 2
    assert result["summary"]["input_tokens"] == 200
    assert result["summary"]["output_tokens"] == 100
    assert result["summary"]["total_tokens"] == 300
    assert result["summary"]["retry_rate"] == 0.5
    assert result["groups"][0]["key"] == "base_case_generation"
    assert result["estimated_cost"] is None
    assert result["cost_status"] == "not_configured"


def test_structured_application_log_redacts_secret_and_keeps_request_id() -> None:
    """技术日志可用 request_id 关联，但不能写入凭证。"""

    output = io.StringIO()
    logger = logging.getLogger("test.v23.structured")
    logger.handlers = [logging.StreamHandler(output)]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    structured_log(
        logger, request_id="req_test", event="service_error", status=500,
        authorization="Bearer secret-value",
    )

    rendered = output.getvalue()
    assert "req_test" in rendered
    assert "secret-value" not in rendered
