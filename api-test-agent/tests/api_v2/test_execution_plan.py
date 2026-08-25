"""阶段四纯 ExecutionPlan 编译器的行为测试。

这些测试只使用字典输入，刻意不依赖尚在演进的 Pydantic V3 模型；这样编译器
可以保持纯函数，并在控制平面完成模型适配前先固定 DAG 与门禁语义。
"""

from __future__ import annotations

from services.api_agent.execution_plan import compile_execution_plan, validate_execution_plan_hashes


TARGETS = {
    "target_test": {
        "environment": "test",
        "allow_write_methods": True,
    },
}


def _case(case_id: str, **overrides: object) -> dict[str, object]:
    """构造一条已经确认且可执行的最小执行定义。"""

    payload: dict[str, object] = {
        "executable_case_id": case_id,
        "validation_status": "ready",
        "enabled": True,
        "review_status": "confirmed",
        "request": {"method": "GET", "path": f"/{case_id}"},
        "precondition_case_ids": [],
        "variable_producers": [],
        "variable_consumers": [],
        "session_produces": [],
        "session_consumes": [],
        "retry_policy": {"max_retries": 0},
        "failure_policy": "block_dependents",
        "risk_level": "low",
    }
    payload.update(overrides)
    return payload


def _compile(cases: list[dict[str, object]], **overrides: object):
    """调用真实编译器，并为每个测试提供一致的受控策略输入。"""

    options: dict[str, object] = {
        "task_id": "task_20260821_0123456789abcdef0123",
        "source_executable_version": 7,
        "source_executable_sha256": "a" * 64,
        "target_id": "target_test",
        "environment": "test",
        "registered_targets": TARGETS,
        "resource_policy_id": "resource-v1",
        "egress_policy_id": "egress-v1",
        "policy_version": "policy-sha-v1",
        "manual_edges": [],
    }
    options.update(overrides)
    return compile_execution_plan(cases, **options)


def test_compiler_uses_stable_kahn_order_and_sha_when_input_order_changes():
    """防止调用方数组顺序改变导致同一计划产生不同确认摘要。"""

    producer = _case(
        "login",
        variable_producers=[{"name": "token", "extractor_type": "json_pointer", "source_path": "/token"}],
    )
    consumer = _case(
        "profile",
        variable_consumers=[{"name": "token", "destination": "header", "field_path": "Authorization", "required": True}],
    )
    independent = _case("health")

    first = _compile([consumer, independent, producer])
    second = _compile([independent, producer, consumer])

    assert first.blockers == ()
    assert second.blockers == ()
    assert first.plan is not None
    assert second.plan is not None
    assert first.plan["topological_order"] == ["health", "login", "profile"]
    assert first.plan["topological_order"] == second.plan["topological_order"]
    assert first.plan["sha256"] == second.plan["sha256"]


def test_compiler_records_explicit_variable_session_csrf_and_manual_edge_sources():
    """防止边只有顺序而没有可审计来源，导致计划预览无法解释依赖。"""

    login = _case(
        "login",
        variable_producers=[{"name": "access_token", "extractor_type": "json_pointer", "source_path": "/token"}],
        session_produces=["cookie:session", "csrf:csrf_token"],
    )
    protected = _case(
        "protected",
        precondition_case_ids=["login"],
        variable_consumers=[{"name": "access_token", "destination": "header", "field_path": "Authorization", "required": True}],
        session_consumes=["cookie:session", "csrf:csrf_token"],
    )
    logout = _case("logout")

    result = _compile([logout, protected, login], manual_edges=[{"from_node": "protected", "to_node": "logout", "reason": "清理会话"}])

    assert result.blockers == ()
    assert result.plan is not None
    edges = {(edge["from_node"], edge["to_node"], edge["source_type"], edge["source_ref"]) for edge in result.plan["edges"]}
    assert ("login", "protected", "explicit_precondition", "login") in edges
    assert ("login", "protected", "variable", "access_token") in edges
    assert ("login", "protected", "cookie_session", "cookie:session") in edges
    assert ("login", "protected", "csrf", "csrf:csrf_token") in edges
    assert ("protected", "logout", "manual_order", "清理会话") in edges


def test_compiler_blocks_dependency_cycle():
    """防止环被错误地交给串行执行器，造成永远无法开始的 Run。"""

    result = _compile([
        _case("a", precondition_case_ids=["b"]),
        _case("b", precondition_case_ids=["a"]),
    ])

    assert result.plan is None
    assert [blocker.code for blocker in result.blockers] == ["EXECUTION_DEPENDENCY_CYCLE"]


def test_compiler_blocks_missing_required_variable_source():
    """防止 required 模板变量在运行时被静默替换为空字符串。"""

    result = _compile([
        _case("profile", variable_consumers=[{"name": "token", "destination": "header", "field_path": "Authorization", "required": True}]),
    ])

    assert result.plan is None
    assert [blocker.code for blocker in result.blockers] == ["VARIABLE_SOURCE_MISSING"]


def test_compiler_blocks_conflicting_variable_producers():
    """防止两个前置节点覆盖同名变量，使运行结果取决于偶然顺序。"""

    result = _compile([
        _case("login_a", variable_producers=[{"name": "token", "extractor_type": "json_pointer", "source_path": "/token"}]),
        _case("login_b", variable_producers=[{"name": "token", "extractor_type": "json_pointer", "source_path": "/token"}]),
        _case("profile", variable_consumers=[{"name": "token", "destination": "header", "field_path": "Authorization", "required": True}]),
    ])

    assert result.plan is None
    assert [blocker.code for blocker in result.blockers] == ["VARIABLE_NAME_CONFLICT"]


def test_compiler_blocks_stale_and_excludes_disabled_cases_from_plan():
    """历史定义继续阻断；明确禁用项保留展示但不应拖垮其他合格执行计划。"""

    result = _compile([
        _case("stale", lifecycle_status="stale"),
        _case("disabled", validation_status="disabled", enabled=False),
    ])

    assert result.plan is None
    assert [blocker.code for blocker in result.blockers] == ["EXECUTION_PLAN_INVALID"]

    ready = _compile([
        _case("health"),
        _case("disabled", validation_status="disabled", review_status="disabled", enabled=False),
    ])
    assert ready.ready is True
    assert [node["executable_case_id"] for node in ready.plan["nodes"]] == ["health"]


def test_compiler_blocks_unregistered_target():
    """防止用例或浏览器借由计划编译绕过登记目标边界。"""

    result = _compile([_case("health")], target_id="target_unknown")

    assert result.plan is None
    assert [blocker.code for blocker in result.blockers] == ["EXECUTION_PLAN_INVALID"]


def test_compiler_blocks_write_retry_without_confirmed_idempotency():
    """防止 POST 等写请求在瞬态网络失败后被隐式重复提交。"""

    result = _compile([
        _case(
            "create_order",
            request={"method": "POST", "path": "/orders"},
            retry_policy={"max_retries": 1},
        ),
    ])

    assert result.plan is None
    assert [blocker.code for blocker in result.blockers] == ["WRITE_RETRY_NOT_ALLOWED"]


def test_compiler_blocks_write_when_target_does_not_allow_writes():
    """目标未显式授权写操作时，计划编译即阻断 POST/PUT/PATCH/DELETE。"""

    result = _compile(
        [_case("create", request={"method": "POST", "path": "/items"})],
        registered_targets={"target_test": {"environment": "test", "allow_write_methods": False}},
    )
    assert result.plan is None
    assert "EXECUTION_TARGET_WRITE_DENIED" in {item.code for item in result.blockers}


def test_compiler_blocks_plaintext_credentials_and_unknown_assertions():
    """明文凭证与 Executor 不支持的断言都不得进入不可变计划。"""

    result = _compile([_case(
        "unsafe",
        request={
            "method": "POST", "path": "/login",
            "headers": {"Authorization": "Bearer real-secret"},
            "body": {"password": "plain-password"},
        },
        assertions=[{"operator": "schema", "expected": {"type": "object"}}],
    )])
    codes = {item.code for item in result.blockers}
    assert "PLAINTEXT_CREDENTIAL_FORBIDDEN" in codes
    assert "ASSERTION_OPERATOR_UNSUPPORTED" in codes


def test_compiler_requires_confirmed_nonempty_idempotency_header_for_write_retry():
    """仅声明幂等性不够，已确认幂等 Header 必须真实存在于请求。"""

    policy = {
        "max_attempts": 2, "idempotent": True, "confirmed": True,
        "idempotency_key_header": "Idempotency-Key",
    }
    blocked = _compile([_case(
        "write", request={"method": "POST", "path": "/items"}, retry_policy=policy,
    )])
    assert "WRITE_RETRY_NOT_ALLOWED" in {item.code for item in blocked.blockers}
    ready = _compile([_case(
        "write", request={
            "method": "POST", "path": "/items", "headers": {"Idempotency-Key": "{{request_key}}"},
        }, retry_policy=policy,
    )])
    assert ready.plan is not None


def test_confirmation_sha_changes_when_policy_snapshot_changes():
    """防止目标或安全策略变更后沿用旧的最终确认。"""

    first = _compile([_case("health")], policy_version="policy-sha-v1")
    second = _compile([_case("health")], policy_version="policy-sha-v2")

    assert first.plan is not None
    assert second.plan is not None
    assert first.plan["confirmation_sha256"] != second.plan["confirmation_sha256"]


def test_compiled_node_preserves_extraction_and_model_retry_policy() -> None:
    """执行计划必须把 Workflow 变量提取和 V3 重试策略原样交给受限 Executor。"""

    result = _compile([_case(
        "login",
        variable_producers=[{
            "name": "access_token", "extractor_type": "json_pointer",
            "source_path": "/data/token", "required": True, "sensitive": True,
        }],
        retry_policy={"max_attempts": 2, "idempotent": True, "confirmed": True},
    )])

    assert result.plan is not None
    node = result.plan["nodes"][0]
    assert node["producers"][0]["source_path"] == "/data/token"
    assert node["retry_policy"]["max_attempts"] == 2


def test_compiled_plan_records_write_nodes_and_detects_content_tampering() -> None:
    """运行前写权限复核需要确定性标记，计划正文变化必须使两个 SHA 校验失败。"""

    result = _compile([_case("create", request={"method": "POST", "path": "/items"})])
    assert result.plan is not None
    assert result.plan["nodes"][0]["write_operation"] is True
    assert validate_execution_plan_hashes(result.plan) is True

    tampered = {**result.plan, "nodes": [{**result.plan["nodes"][0], "request": {"method": "DELETE", "path": "/items/1"}}]}
    assert validate_execution_plan_hashes(tampered) is False
