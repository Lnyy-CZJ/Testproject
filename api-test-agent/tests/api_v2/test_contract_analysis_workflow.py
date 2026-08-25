"""阶段一 ContractAnalysisWorkflow 的端到端纯函数契约测试。

这些测试刻意只注入文档和模型候选，不创建 TaskStore、不访问网络，也不依赖
Runner。它们锁定 V2.4 最重要的边界：确定性事实不可被模型覆盖，且请求体、
鉴权结论和 Evidence 缺失时必须在保存前被门禁阻断。
"""

from __future__ import annotations

from agents.api_test.workflows.contract_analysis_workflow import ContractAnalysisWorkflow
from services.api_agent.models import ApiContract, WorkflowRuntimeContext


def _runtime() -> WorkflowRuntimeContext:
    """构造无外部副作用的工作流运行时，并保留节点事件供生产路径复用。"""

    return WorkflowRuntimeContext(
        task_id="task_contract_workflow",
        attempt_id="attempt_contract_workflow",
        workflow_id="contract-analysis",
        workflow_version="v2.4",
        input_versions={"documents": 1},
        event_sink=lambda _event: None,
        model_invoker=None,
    )


def _login_candidate(*, include_body: bool = True) -> dict:
    """返回与登录 Markdown 对应的旧 AI 结构化候选。"""

    candidate = {
        "name": "用户登录",
        "method": "POST",
        "path": "/auth/login",
        "parameters": {
            "header": [
                {"name": "Authorization", "required": True, "description": "Bearer token"},
                {"name": "X-CSRF-Token", "required": True, "description": "CSRF token"},
            ],
            "cookie": [
                {"name": "SESSION", "required": True, "description": "登录会话"},
            ],
        },
        "responses": {"http_code": "200", "description": "登录成功"},
    }
    if include_body:
        candidate["requestBody"] = {
            "content_type": "application/json",
            "body": [
                {"name": "username", "required": True, "type": {"type": "string"}},
                {"name": "password", "required": True, "type": {"type": "string"}},
            ],
        }
    return candidate


LOGIN_DOCUMENT = """# 用户登录

POST /auth/login

Authorization（必填）: Bearer ${token}
Cookie（必填）: SESSION=${session}
X-CSRF-Token（必填）: ${csrf_token}

请求体 application/json：username（必填）、password（必填）。
成功时返回 200。
"""


def _blocker_codes(result) -> set[str]:
    """从工作流候选的质量报告提取稳定 blocker code。"""

    return {
        issue.code
        for contract in (ApiContract.model_validate(item) for item in result.items)
        for issue in contract.quality_report.blockers
    }


def test_workflow_preserves_login_body_auth_and_csrf_from_grounded_legacy_candidate():
    """遗漏 Adapter 的 body/auth 映射时，此测试应失败。"""

    workflow = ContractAnalysisWorkflow(legacy_parser=lambda _text: _login_candidate())

    result = workflow.run(
        document_text=LOGIN_DOCUMENT,
        filename="login.md",
        runtime=_runtime(),
    )

    assert result.status == "ready"
    assert len(result.items) == 1
    contract = ApiContract.model_validate(result.items[0])
    assert contract.method == "POST"
    assert contract.path == "/auth/login"
    assert contract.request_body is not None
    assert set(contract.request_body.content["schema"]["properties"]) == {"username", "password"}
    assert contract.auth_conclusion == "required"
    assert {requirement.field_name for requirement in contract.auth_requirements} >= {
        "Authorization", "X-CSRF-Token", "SESSION",
    }
    assert not _blocker_codes(result)


def test_workflow_maps_explicit_openapi_empty_security_to_no_authentication():
    """把显式 security: [] 错误降级为 unresolved 会破坏该测试。"""

    document = """openapi: 3.0.3
info: {title: Health, version: '1'}
paths:
  /health:
    get:
      security: []
      responses:
        '200': {description: ok}
"""
    workflow = ContractAnalysisWorkflow()

    result = workflow.run(document_text=document, filename="openapi.yaml", runtime=_runtime())

    assert result.status == "ready"
    contract = ApiContract.model_validate(result.items[0])
    assert contract.method == "GET"
    assert contract.path == "/health"
    assert contract.auth_conclusion == "none"
    assert not _blocker_codes(result)


def test_workflow_blocks_login_document_when_body_signal_has_no_structured_body():
    """删除请求体完整性门禁时，此测试应失败。"""

    workflow = ContractAnalysisWorkflow(
        legacy_parser=lambda _text: _login_candidate(include_body=False)
    )

    result = workflow.run(document_text=LOGIN_DOCUMENT, filename="login.md", runtime=_runtime())

    assert "CONTRACT_REQUEST_BODY_MISSING" in _blocker_codes(result)


def test_workflow_blocks_auth_signals_without_an_authentication_conclusion():
    """删除 auth signal 到 unresolved 的判断时，此测试应失败。"""

    candidate = _login_candidate()
    candidate["parameters"] = {}
    workflow = ContractAnalysisWorkflow(legacy_parser=lambda _text: candidate)

    result = workflow.run(document_text=LOGIN_DOCUMENT, filename="login.md", runtime=_runtime())

    assert "CONTRACT_AUTH_CONCLUSION_MISSING" in _blocker_codes(result)


def test_workflow_keeps_openapi_method_and_path_when_model_candidate_conflicts():
    """让 LLM 覆盖 OpenAPI 的 method/path 时，此测试应失败。"""

    document = """openapi: 3.0.3
info: {title: Sessions, version: '1'}
paths:
  /sessions:
    post:
      responses:
        '201': {description: created}
"""
    workflow = ContractAnalysisWorkflow(
        legacy_parser=lambda _text: {
            "method": "GET",
            "path": "/model-overrode-a-fact",
            "responses": {"http_code": "200"},
        }
    )

    result = workflow.run(document_text=document, filename="openapi.yaml", runtime=_runtime())

    contract = ApiContract.model_validate(result.items[0])
    assert contract.method == "POST"
    assert contract.path == "/sessions"


def test_workflow_preserves_parameter_roles_and_nested_request_body_schema():
    """旧解析器的参数角色和嵌套请求体必须进入 V2.4 契约，供后续控制变量法使用。"""

    candidate = _login_candidate()
    candidate["parameters"]["query"] = [{
        "name": "remember_me", "required": False, "description": "可选，默认 false",
        "type": {"type": "boolean"}, "param_role": "optional",
        "default_value": False, "allow_omit": True, "baseline_value": True,
    }]
    candidate["requestBody"]["body"].append({
        "name": "profile", "required": False, "description": "可选用户资料",
        "type": {"type": "object"}, "param_role": "optional", "allow_omit": True,
        "nested_fields": [{
            "name": "device_id", "required": True, "description": "设备 ID",
            "type": {"type": "string"}, "param_role": "required",
        }],
    })
    result = ContractAnalysisWorkflow(legacy_parser=lambda _text: candidate).run(
        document_text=LOGIN_DOCUMENT + "\nremember_me 可选，默认 false。profile.device_id 为设备 ID。",
        filename="login.md", runtime=_runtime(),
    )

    contract = ApiContract.model_validate(result.items[0])
    remember = next(item for item in contract.parameters if item.name == "remember_me")
    assert remember.param_role == "optional"
    assert remember.default_value is False and remember.allow_omit is True
    profile = contract.request_body.content["schema"]["properties"]["profile"]
    assert profile["type"] == "object"
    assert profile["properties"]["device_id"]["type"] == "string"


def test_workflow_does_not_mark_hallucinated_fields_as_explicit_evidence():
    """模型伪造的 Header、必填性和状态码必须成为 blocker，而不是伪造文档依据。"""

    candidate = _login_candidate()
    candidate["parameters"]["header"].append({
        "name": "X-Admin-Secret", "required": True, "description": "管理员密钥",
    })
    candidate["responses"] = {"http_code": "299", "description": "模型臆造"}
    result = ContractAnalysisWorkflow(legacy_parser=lambda _text: candidate).run(
        document_text=LOGIN_DOCUMENT, filename="login.md", runtime=_runtime(),
    )
    contract = ApiContract.model_validate(result.items[0])
    fake_evidence = [
        item for item in contract.field_evidence
        if item.value in {"X-Admin-Secret", "299"}
    ]
    assert fake_evidence and all(item.evidence_type == "inferred" for item in fake_evidence)
    assert "UNGROUNDED_FIELD" in _blocker_codes(result)


def test_workflow_aggregates_all_explicit_endpoints_when_legacy_parser_returns_only_one() -> None:
    """旧单接口 Parser 不能让多接口 Markdown 静默只保留第一条。"""

    document = """# 平台接口

## 1. 通用约定
除 health/live 和 auth/login 外，公共接口要求有效统一会话 tp_session；写请求发送 X-CSRF-Token。

## 2. 登录
```http
GET /api/v1/health/live

POST /api/v1/auth/login
{"username":"admin","password":"..."}

GET /api/v1/auth/me
```
"""
    only_health = {
        "method": "GET", "path": "/api/v1/health/live", "summary": "健康",
        "parameters": {}, "responses": {"http_code": "200", "description": "ok"},
    }
    result = ContractAnalysisWorkflow(legacy_parser=lambda _text: only_health).run(
        document_text=document, filename="platform.md", runtime=_runtime(),
    )
    contracts = {
        (item.method, item.path): item
        for item in (ApiContract.model_validate(raw) for raw in result.items)
    }
    assert set(contracts) == {
        ("GET", "/api/v1/health/live"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/me"),
    }
    login = contracts[("POST", "/api/v1/auth/login")]
    assert login.auth_conclusion == "none"
    assert login.request_body is not None
    assert set(login.request_body.content["schema"]["properties"]) == {"username", "password"}
    current_user = contracts[("GET", "/api/v1/auth/me")]
    assert current_user.auth_conclusion == "required"
    assert {item.field_name for item in current_user.auth_requirements} == {"tp_session"}
