"""仅本次运行参数覆盖领域模型测试。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from utils.custom.case_loader import load_single_cases
from utils.custom.flow_loader import FlowConfigError, load_flow_cases
from utils.custom.runtime_overrides import (
    RuntimeOverrideError,
    apply_runtime_overrides,
    build_case_asset_snapshot,
    build_flow_asset_snapshot,
    canonical_sha256,
    load_execution_asset_file,
    public_asset_contract,
    validate_case_runtime_inputs,
    validate_flow_runtime_inputs,
)


def _api_definitions() -> dict[str, dict]:
    """返回构建不可变资产快照所需的最小 API 注册表。"""
    return {
        "Demo": {
            "id": "Demo",
            "name": "Demo API",
            "credential_profile": "anonymous_session",
            "request": {
                "service_name": "example.DemoService",
                "method_name": "Demo",
            },
        }
    }


def _case_snapshot(input_type: str = "string", default_value=None) -> dict:
    """构造仅含一个公开字段的单接口基础快照。"""
    defaults = {
        "string": "base",
        "integer": 1,
        "number": 1.5,
        "boolean": True,
        "enum": "en-US",
    }
    value = defaults[input_type] if default_value is None else default_value
    declaration = {
        "label": "可编辑值",
        "description": "仅影响本次执行",
        "type": input_type,
        "required": True,
        "target": {"scope": "case_request", "path": "$.editable"},
    }
    if input_type == "enum":
        declaration["options"] = ["en-US", "zh-CN"]
    case = {
        "request": {"params": {"editable": value}},
        "runtime_inputs": {"editable": declaration},
    }
    normalized = validate_case_runtime_inputs(case, scope="Case Demo::success")
    single_case = {
        "id": "Demo::success",
        "api_id": "Demo",
        "case_id": "success",
        "name": "Demo success",
        "tags": ["unit"],
        "runtime_inputs": normalized,
        "execution_case": {
            "name": "Demo success",
            "request": {
                "service_name": "example.DemoService",
                "method_name": "Demo",
                "params": {"editable": value},
            },
            "assert": {"http_status": 200},
            "extract": {},
        },
    }
    return build_case_asset_snapshot("dating", single_case, _api_definitions())


def _flow_snapshot() -> dict:
    """构造一个开放 locale 的 Flow 基础快照。"""
    flow = {
        "name": "Demo flow",
        "inputs": {
            "media_files": {
                "type": "files",
                "required": True,
                "min_items": 1,
                "max_items": 9,
                "allowed_content_types": ["image/png"],
                "max_size_bytes": 7_000_000,
                "label": "聊天截图",
                "description": "按顺序选择图片",
            }
        },
        "steps": [{"id": "create_demo", "api": "Demo"}],
    }
    scenario = {
        "name": "Demo scenario",
        "variables": {},
        "runtime_inputs": {
            "client_locale": {
                "label": "结果语言",
                "type": "enum",
                "options": ["en-US", "zh-CN"],
                "required": True,
                "target": {
                    "scope": "flow_step_request",
                    "step_id": "create_demo",
                    "path": "$.locale",
                },
            }
        },
        "step_data": {
            "create_demo": {
                "params": {"locale": "en-US"},
                "assert": {"http_status": 200},
            }
        },
    }
    normalized = validate_flow_runtime_inputs(
        flow,
        scenario,
        scope="Flow demo",
    )
    flow_case = {
        "id": "demo_flow",
        "name": "Demo flow",
        "tags": ["unit"],
        "flow": flow,
        "scenario": scenario,
        "runtime_inputs": normalized,
        "api_definitions": _api_definitions(),
    }
    return build_flow_asset_snapshot("dating", flow_case, _api_definitions())


def test_canonical_sha256_is_stable_for_mapping_order() -> None:
    """对象键顺序不应改变资产版本。"""
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256(
        {"a": 1, "b": 2}
    )


def test_case_runtime_input_rejects_dynamic_target() -> None:
    """模板变量属于运行时动态值，不能再由浏览器覆盖。"""
    case = {
        "request": {"params": {"client_request_id": "{{client_request_id}}"}},
        "runtime_inputs": {
            "request_id": {
                "label": "请求 ID",
                "type": "string",
                "required": True,
                "target": {
                    "scope": "case_request",
                    "path": "$.client_request_id",
                },
            }
        },
    }
    with pytest.raises(RuntimeOverrideError) as error:
        validate_case_runtime_inputs(case, scope="Case demo")
    assert error.value.error_code == "RUNTIME_OVERRIDE_TARGET_INVALID"


def test_case_runtime_inputs_auto_discover_static_scalar_request_params() -> None:
    """未写声明的 Case 也应自动开放安全静态叶子，并按默认值推断控件类型。

    该测试防止实现退回“必须先在 YAML 枚举字段和值”的旧行为；动态模板、
    敏感字段、数组和无类型的 null 仍不能因此暴露给浏览器。
    """

    case = {
        "request": {
            "params": {
                "free_text": "default",
                "attempts": 2,
                "ratio": 0.5,
                "enabled": True,
                "nested": {"locale": "en-US"},
                "client_request_id": "{{client_request_id}}",
                "access_token": "must-not-leak",
                "items": ["one"],
                "unset": None,
            }
        }
    }

    normalized = validate_case_runtime_inputs(case, scope="Case demo")

    assert list(normalized) == [
        "free_text",
        "attempts",
        "ratio",
        "enabled",
        "nested__locale",
    ]
    assert {
        key: definition["type"] for key, definition in normalized.items()
    } == {
        "free_text": "string",
        "attempts": "integer",
        "ratio": "number",
        "enabled": "boolean",
        "nested__locale": "string",
    }
    assert normalized["free_text"]["options"] == []
    assert normalized["free_text"]["required"] is False
    assert normalized["nested__locale"]["target"] == {
        "scope": "case_request",
        "path": ["nested", "locale"],
    }


def test_case_explicit_runtime_input_customizes_one_auto_discovered_target() -> None:
    """显式声明可保留标签/枚举约束，但同一路径不能再生成第二个自动字段。"""

    case = {
        "request": {
            "params": {
                "locale": "en-US",
                "free_text": "default",
            }
        },
        "runtime_inputs": {
            "client_locale": {
                "label": "客户端语言",
                "type": "enum",
                "options": ["en-US", "zh-CN"],
                "required": True,
                "target": {
                    "scope": "case_request",
                    "path": "$.locale",
                },
            }
        },
    }

    normalized = validate_case_runtime_inputs(case, scope="Case demo")

    assert list(normalized) == ["client_locale", "free_text"]
    assert normalized["client_locale"]["type"] == "enum"
    assert normalized["free_text"]["type"] == "string"


def test_auto_discovered_case_string_accepts_arbitrary_runtime_value() -> None:
    """自动发现的字符串必须接受用户输入，而不是依赖预设 options。"""

    case = {
        "request": {"params": {"query": "yaml-default"}},
    }
    normalized = validate_case_runtime_inputs(case, scope="Case Demo::success")
    single_case = {
        "id": "Demo::success",
        "api_id": "Demo",
        "case_id": "success",
        "name": "Demo success",
        "tags": ["unit"],
        "runtime_inputs": normalized,
        "execution_case": {
            "name": "Demo success",
            "request": {
                "service_name": "example.DemoService",
                "method_name": "Demo",
                "params": {"query": "yaml-default"},
            },
            "assert": {"http_status": 200},
            "extract": {},
        },
    }
    snapshot = build_case_asset_snapshot(
        "dating",
        single_case,
        _api_definitions(),
    )

    resolved = apply_runtime_overrides(
        snapshot,
        {"query": "any value entered by the tester"},
        expected_revision=snapshot["asset_revision"],
        require_revision=True,
    )

    params = resolved["resolved_execution_asset"]["single_case"][
        "execution_case"
    ]["request"]["params"]
    assert params["query"] == "any value entered by the tester"


def test_flow_runtime_inputs_auto_discover_static_params_and_skip_dependencies() -> None:
    """Flow 应按 API 步骤自动开放静态标量，同时跳过前序输出和敏感目标。

    该测试防止 Flow 继续依赖手写白名单，也防止自动发现误把 ``task_id``、
    ``asset_ids`` 或模板变量暴露给浏览器。
    """

    flow = {
        "steps": [
            {"id": "prepare_upload", "api": "PrepareMediaUpload"},
            {"id": "create_analysis", "api": "CreateAnalysisTask"},
            {"id": "poll_analysis", "api": "GetAnalysisTask"},
        ]
    }
    scenario = {
        "step_data": {
            "prepare_upload": {
                "params": {
                    "content_type": "image/png",
                    "size_bytes": "{{media_file.size_bytes}}",
                }
            },
            "create_analysis": {
                "params": {
                    "client_request_id": "{{client_request_id}}",
                    "asset_ids": "{{asset_ids}}",
                    "access_token": "must-not-leak",
                    "locale": "en-US",
                    "preferences": {"tone": "warm", "enabled": True},
                }
            },
            "poll_analysis": {"params": {"task_id": "{{task_id}}"}},
        }
    }

    normalized = validate_flow_runtime_inputs(flow, scenario, scope="Flow demo")

    assert list(normalized) == [
        "prepare_upload__content_type",
        "create_analysis__locale",
        "create_analysis__preferences__tone",
        "create_analysis__preferences__enabled",
    ]
    assert normalized["prepare_upload__content_type"]["target"] == {
        "scope": "flow_step_request",
        "step_id": "prepare_upload",
        "path": ["content_type"],
    }
    assert normalized["create_analysis__preferences__tone"]["group"] == {
        "step_id": "create_analysis",
        "step_name": "CreateAnalysisTask",
    }
    assert normalized["create_analysis__preferences__enabled"]["type"] == "boolean"
    assert {
        tuple(definition["target"]["path"])
        for definition in normalized.values()
    }.isdisjoint(
        {
            ("size_bytes",),
            ("client_request_id",),
            ("asset_ids",),
            ("access_token",),
            ("task_id",),
        }
    )


def test_flow_explicit_runtime_input_customizes_auto_target_without_duplicate() -> None:
    """显式 Flow 声明只增强目标元数据，其他安全静态字段仍应自动出现。"""

    flow = {"steps": [{"id": "create_analysis", "api": "CreateAnalysisTask"}]}
    scenario = {
        "runtime_inputs": {
            "analysis_locale": {
                "label": "分析语言",
                "type": "enum",
                "options": ["en-US", "zh-CN"],
                "required": True,
                "target": {
                    "scope": "flow_step_request",
                    "step_id": "create_analysis",
                    "path": "$.locale",
                },
            }
        },
        "step_data": {
            "create_analysis": {
                "params": {"locale": "en-US", "tone": "concise"}
            }
        },
    }

    normalized = validate_flow_runtime_inputs(flow, scenario, scope="Flow demo")

    assert list(normalized) == ["analysis_locale", "create_analysis__tone"]
    assert normalized["analysis_locale"]["type"] == "enum"
    assert normalized["create_analysis__tone"]["type"] == "string"


def test_auto_discovered_flow_string_applies_only_to_selected_task_snapshot() -> None:
    """自动发现的 Flow 字符串应接受自由输入并写入不可变执行快照。"""

    flow = {"steps": [{"id": "create_demo", "api": "Demo"}]}
    scenario = {
        "step_data": {
            "create_demo": {
                "params": {"locale": "en-US", "tone": "yaml-default"},
                "assert": {"http_status": 200},
            }
        }
    }
    normalized = validate_flow_runtime_inputs(flow, scenario, scope="Flow demo")
    flow_case = {
        "id": "demo_flow",
        "name": "Demo flow",
        "tags": ["unit"],
        "flow": flow,
        "scenario": scenario,
        "runtime_inputs": normalized,
        "api_definitions": _api_definitions(),
    }
    snapshot = build_flow_asset_snapshot("dating", flow_case, _api_definitions())

    resolved = apply_runtime_overrides(
        snapshot,
        {"create_demo__tone": "any value entered by the tester"},
        expected_revision=snapshot["asset_revision"],
        require_revision=True,
    )

    params = resolved["resolved_execution_asset"]["flow_case"]["scenario"][
        "step_data"
    ]["create_demo"]["params"]
    assert params == {
        "locale": "en-US",
        "tone": "any value entered by the tester",
    }
    assert scenario["step_data"]["create_demo"]["params"]["tone"] == "yaml-default"


@pytest.mark.parametrize(
    "path",
    [
        "$.token",
        "$.accessToken",
        "$.auth_token",
        "$.client_secret",
        "$.credential_id",
        "$.credentialProfile",
        "$.profile_name",
        "$.gateway_url",
        "$.gatewayBaseUrl",
        "$.gateway_path",
        "$.request_headers",
        "$.request_header",
        "$.environment_name",
        "$.scope_id",
        "$.runtimeScopeId",
        "$.release_version",
        "$.releaseId",
        "$.request_timeout",
        "$.timeoutSeconds",
        "$.targetEnv",
        "$.task_id",
        "$.asset_ids",
        "$.poll_interval_seconds",
        "$.pollIntervalSeconds",
        "$.input_file",
    ],
)
def test_case_runtime_input_rejects_sensitive_or_dynamic_semantics(path: str) -> None:
    """平台配置、身份、素材和流程控制字段不得暴露为业务覆盖值。"""
    leaf = path.removeprefix("$.")
    case = {
        "request": {"params": {leaf: "base"}},
        "runtime_inputs": {
            "editable": {
                "label": "禁止字段",
                "type": "string",
                "required": True,
                "target": {"scope": "case_request", "path": path},
            }
        },
    }
    with pytest.raises(RuntimeOverrideError) as error:
        validate_case_runtime_inputs(case, scope="Case demo")
    assert error.value.error_code == "RUNTIME_OVERRIDE_TARGET_INVALID"


@pytest.mark.parametrize(
    ("input_type", "value"),
    [
        ("integer", True),
        ("number", float("nan")),
        ("number", float("inf")),
        ("boolean", "true"),
        ("string", 7),
        ("enum", "fr-FR"),
    ],
)
def test_runtime_override_rejects_invalid_values(input_type: str, value) -> None:
    """服务端不得对浏览器提交值做隐式类型转换。"""
    snapshot = _case_snapshot(input_type=input_type)
    with pytest.raises(RuntimeOverrideError) as error:
        apply_runtime_overrides(
            snapshot,
            {"editable": value},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    expected = (
        "RUNTIME_OVERRIDE_CONSTRAINT_FAILED"
        if input_type == "enum"
        else "RUNTIME_OVERRIDE_TYPE_INVALID"
    )
    assert error.value.error_code == expected


def test_required_string_runtime_input_rejects_empty_value() -> None:
    """required 字符串不能用空串绕过；P0 不支持空值删除。"""
    snapshot = _case_snapshot(input_type="string")
    with pytest.raises(RuntimeOverrideError) as error:
        apply_runtime_overrides(
            snapshot,
            {"editable": ""},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert error.value.error_code == "RUNTIME_OVERRIDE_CONSTRAINT_FAILED"
    assert error.value.field_errors == [
        {"key": "editable", "message": "此字段不能为空"}
    ]


@pytest.mark.parametrize("snapshot_factory", [_case_snapshot, _flow_snapshot])
def test_runtime_override_rejects_dynamic_template_injection(snapshot_factory) -> None:
    """普通字符串/枚举覆盖不得引用运行时 Token、Secret 或任务变量。"""
    snapshot = snapshot_factory()
    key = "editable" if snapshot["asset_type"] == "case" else "client_locale"
    with pytest.raises(RuntimeOverrideError) as error:
        apply_runtime_overrides(
            snapshot,
            {key: "{{access_token}}"},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert error.value.error_code == "RUNTIME_OVERRIDE_CONSTRAINT_FAILED"
    assert error.value.field_errors == [
        {"key": key, "message": "动态模板不能作为本次运行参数"}
    ]


def test_runtime_input_declaration_rejects_dynamic_enum_option() -> None:
    """enum 选项也属于浏览器可提交值，声明阶段必须拒绝动态模板。"""
    case = {
        "request": {"params": {"locale": "en-US"}},
        "runtime_inputs": {
            "locale": {
                "label": "语言",
                "type": "enum",
                "options": ["en-US", "{{access_token}}"],
                "required": True,
                "target": {"scope": "case_request", "path": "$.locale"},
            }
        },
    }
    with pytest.raises(RuntimeOverrideError) as error:
        validate_case_runtime_inputs(case, scope="Case demo")
    assert error.value.error_code == "RUNTIME_OVERRIDE_TARGET_INVALID"


def test_number_runtime_override_rejects_integer_outside_js_safe_range() -> None:
    """超大整数应受控拒绝，不能 500 或在浏览器中被静默舍入。"""
    snapshot = _case_snapshot(input_type="number")
    huge_integer = 10**309
    with pytest.raises(RuntimeOverrideError) as error:
        apply_runtime_overrides(
            snapshot,
            {"editable": huge_integer},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert error.value.error_code == "RUNTIME_OVERRIDE_CONSTRAINT_FAILED"


@pytest.mark.parametrize("input_type", ["integer", "number"])
def test_numeric_runtime_override_uses_javascript_safe_boundary(input_type: str) -> None:
    """Web JSON 契约的整数精度固定为 Number.MAX_SAFE_INTEGER。"""
    snapshot = _case_snapshot(input_type=input_type)
    maximum = 9_007_199_254_740_991
    resolved = apply_runtime_overrides(
        snapshot,
        {"editable": maximum},
        expected_revision=snapshot["asset_revision"],
        require_revision=True,
    )
    assert resolved["applied_overrides"][0]["resolved_value"] == maximum

    with pytest.raises(RuntimeOverrideError) as error:
        apply_runtime_overrides(
            snapshot,
            {"editable": maximum + 1},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert error.value.error_code == "RUNTIME_OVERRIDE_CONSTRAINT_FAILED"


@pytest.mark.parametrize(
    ("input_type", "value"),
    [
        ("string", "changed"),
        ("integer", 2),
        ("number", 2.5),
        ("boolean", False),
        ("enum", "zh-CN"),
    ],
)
def test_runtime_override_supports_all_p0_types(input_type: str, value) -> None:
    """五种 P0 类型都应在深拷贝资产上精确写入。"""
    snapshot = _case_snapshot(input_type=input_type)
    original = deepcopy(snapshot)
    resolved = apply_runtime_overrides(
        snapshot,
        {"editable": value},
        expected_revision=snapshot["asset_revision"],
        require_revision=True,
    )
    params = resolved["resolved_execution_asset"]["single_case"][
        "execution_case"
    ]["request"]["params"]
    assert params["editable"] == value
    assert resolved["applied_overrides"][0]["resolved_value"] == value
    assert snapshot == original


def test_flow_override_targets_only_declared_step() -> None:
    """Flow 覆盖只修改服务端声明的步骤与字段。"""
    snapshot = _flow_snapshot()
    resolved = apply_runtime_overrides(
        snapshot,
        {"client_locale": "zh-CN"},
        expected_revision=snapshot["asset_revision"],
        require_revision=True,
    )
    params = resolved["resolved_execution_asset"]["flow_case"]["scenario"][
        "step_data"
    ]["create_demo"]["params"]
    assert params["locale"] == "zh-CN"


def test_case_and_flow_snapshots_include_automatic_session_dependencies() -> None:
    """不可变快照必须携带临期刷新和过期重建会话所需的 API 路由。"""
    definitions = {
        **_api_definitions(),
        "CreateAnonymousSession": {
            "id": "CreateAnonymousSession",
            "request": {
                "service_name": "example.IdentityService",
                "method_name": "CreateAnonymousSession",
            },
        },
        "RefreshSession": {
            "id": "RefreshSession",
            "request": {
                "service_name": "example.IdentityService",
                "method_name": "RefreshSession",
            },
        },
        "Unrelated": {
            "id": "Unrelated",
            "request": {
                "service_name": "example.OtherService",
                "method_name": "Unrelated",
            },
        },
    }

    case_snapshot = build_case_asset_snapshot(
        "dating",
        _case_snapshot()["resolved_execution_asset"]["single_case"],
        definitions,
    )
    flow_case = _flow_snapshot()["resolved_execution_asset"]["flow_case"]
    # FlowLoader 原本只在 flow_case 内保存显式业务步骤，完整项目注册表由调用方
    # 传入；快照生成器应自行计算所需闭包，而不是把无关 API 一并固化。
    flow_case["api_definitions"] = {"Demo": definitions["Demo"]}
    flow_snapshot = build_flow_asset_snapshot("dating", flow_case, definitions)

    expected = {"Demo", "CreateAnonymousSession", "RefreshSession"}
    assert set(
        case_snapshot["resolved_execution_asset"]["api_definitions"]
    ) == expected
    assert set(
        flow_snapshot["resolved_execution_asset"]["api_definitions"]
    ) == expected
    assert set(
        flow_snapshot["resolved_execution_asset"]["flow_case"][
            "api_definitions"
        ]
    ) == expected


def test_flow_runtime_input_rejects_unknown_step() -> None:
    """浏览器不能通过伪造步骤 ID 指向未声明对象。"""
    flow = {"steps": [{"id": "create_demo", "api": "Demo"}]}
    scenario = {
        "runtime_inputs": {
            "client_locale": {
                "label": "结果语言",
                "type": "enum",
                "options": ["en-US", "zh-CN"],
                "required": True,
                "target": {
                    "scope": "flow_step_request",
                    "step_id": "missing",
                    "path": "$.locale",
                },
            }
        },
        "step_data": {
            "create_demo": {
                "params": {"locale": "en-US"},
                "assert": {},
            }
        },
    }
    with pytest.raises(RuntimeOverrideError) as error:
        validate_flow_runtime_inputs(flow, scenario, scope="Flow demo")
    assert error.value.error_code == "RUNTIME_OVERRIDE_TARGET_INVALID"


def test_runtime_override_requires_current_asset_revision() -> None:
    """非空覆盖必须与用户预览时看到的资产版本一致。"""
    snapshot = _case_snapshot()
    with pytest.raises(RuntimeOverrideError) as error:
        apply_runtime_overrides(
            snapshot,
            {"editable": "changed"},
            expected_revision=f"sha256:{'0' * 64}",
            require_revision=True,
        )
    assert error.value.status_code == 409
    assert error.value.error_code == "RUNTIME_OVERRIDE_SCHEMA_CHANGED"


def test_runtime_override_rejects_unknown_key_and_limits() -> None:
    """逻辑键、字段数量、字符串和规范化负载均由领域层限制。"""
    snapshot = _case_snapshot()
    with pytest.raises(RuntimeOverrideError) as unknown:
        apply_runtime_overrides(
            snapshot,
            {"missing": "value"},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert unknown.value.error_code == "RUNTIME_OVERRIDE_UNKNOWN_KEY"

    with pytest.raises(RuntimeOverrideError) as long_string:
        apply_runtime_overrides(
            snapshot,
            {"editable": "x" * 4097},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert long_string.value.error_code == "RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE"

    with pytest.raises(RuntimeOverrideError) as too_many:
        apply_runtime_overrides(
            snapshot,
            {f"field_{index}": index for index in range(33)},
            expected_revision=snapshot["asset_revision"],
            require_revision=True,
        )
    assert too_many.value.error_code == "RUNTIME_OVERRIDE_PAYLOAD_TOO_LARGE"


def test_public_contract_does_not_expose_targets_or_execution_asset() -> None:
    """Catalog/API 公开投影不得泄露内部路径或完整执行资产。"""
    public = public_asset_contract(_flow_snapshot())
    assert "runtime_input_definitions" not in public
    assert "resolved_execution_asset" not in public
    assert "target" not in public["runtime_inputs"][0]
    assert public["runtime_input_count"] == 1
    assert public["inputs"] == {
        "media_files": {
            "type": "files",
            "required": True,
            "min_items": 1,
            "max_items": 9,
            "allowed_content_types": ["image/png"],
            "max_size_bytes": 7_000_000,
            "label": "聊天截图",
            "description": "按顺序选择图片",
        }
    }


def test_load_execution_asset_validates_identity_path_and_digest(tmp_path: Path) -> None:
    """pytest 只接受当前任务固定路径下且摘要完整的 0600 文件。"""
    task_id = "20260829-120000-abcd"
    runtime_root = tmp_path / "runtime"
    path = runtime_root / "dating" / task_id / "execution-asset.json"
    path.parent.mkdir(parents=True)
    resolved_asset = _flow_snapshot()["resolved_execution_asset"]
    document = {
        "schema_version": 1,
        "task_id": task_id,
        "project_id": "dating",
        "asset_type": "flow",
        "asset_id": "demo_flow",
        "asset_revision": f"sha256:{'1' * 64}",
        "resolved_asset_revision": canonical_sha256(resolved_asset),
        "resolved_execution_asset": resolved_asset,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)
    assert load_execution_asset_file(
        path,
        runtime_root=runtime_root,
        project_id="dating",
        task_id=task_id,
    )["asset_id"] == "demo_flow"

    tampered = deepcopy(document)
    tampered["resolved_execution_asset"]["flow_case"]["name"] = "tampered"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(RuntimeOverrideError, match="完整性"):
        load_execution_asset_file(
            path,
            runtime_root=runtime_root,
            project_id="dating",
            task_id=task_id,
        )


def test_load_execution_asset_accepts_case_batch_with_individual_digests(
    tmp_path: Path,
) -> None:
    """批次文件必须逐项通过身份和摘要校验后才能交给 pytest。"""

    task_id = "20260829-120002-abcd"
    runtime_root = tmp_path / "runtime"
    path = runtime_root / "dating" / task_id / "execution-asset.json"
    path.parent.mkdir(parents=True)

    first = _case_snapshot()
    second = deepcopy(first)
    second["asset_id"] = "Other::secondary"
    second["resolved_execution_asset"]["single_case"]["id"] = (
        "Other::secondary"
    )
    second["resolved_execution_asset"]["single_case"]["api_id"] = "Other"
    second["resolved_execution_asset"]["single_case"]["case_id"] = "secondary"
    other_definition = deepcopy(_api_definitions()["Demo"])
    other_definition["id"] = "Other"
    other_definition["name"] = "Other API"
    second["resolved_execution_asset"]["api_definitions"] = {
        "Other": other_definition
    }
    second["resolved_asset_revision"] = canonical_sha256(
        second["resolved_execution_asset"]
    )
    items = [
        {
            "asset_type": item["asset_type"],
            "asset_id": item["asset_id"],
            "asset_revision": item["asset_revision"],
            "resolved_asset_revision": item["resolved_asset_revision"],
            "resolved_execution_asset": item["resolved_execution_asset"],
        }
        for item in (first, second)
    ]
    shared_definitions = deepcopy(
        first["resolved_execution_asset"]["api_definitions"]
    )
    shared_definitions.update(
        deepcopy(second["resolved_execution_asset"]["api_definitions"])
    )
    resolved = {
        "batch_type": "cases",
        "items": items,
        "api_definitions": shared_definitions,
    }
    document = {
        "schema_version": 1,
        "task_id": task_id,
        "project_id": "dating",
        "asset_type": "batch",
        "asset_id": "cases:2",
        "asset_revision": f"sha256:{'2' * 64}",
        "resolved_asset_revision": canonical_sha256(resolved),
        "resolved_execution_asset": resolved,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)

    loaded = load_execution_asset_file(
        path,
        runtime_root=runtime_root,
        project_id="dating",
        task_id=task_id,
    )

    assert [
        item["asset_id"]
        for item in loaded["resolved_execution_asset"]["items"]
    ] == ["Demo::success", "Other::secondary"]

    missing_shared_definition = deepcopy(document)
    del missing_shared_definition["resolved_execution_asset"]["api_definitions"][
        "Other"
    ]
    missing_shared_definition["resolved_asset_revision"] = canonical_sha256(
        missing_shared_definition["resolved_execution_asset"]
    )
    path.write_text(json.dumps(missing_shared_definition), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(RuntimeOverrideError, match="顶层 API 定义"):
        load_execution_asset_file(
            path,
            runtime_root=runtime_root,
            project_id="dating",
            task_id=task_id,
        )

    # 即便攻击者同步重算顶层摘要，单个条目的旧摘要仍必须阻止执行。
    tampered = deepcopy(document)
    tampered_item = tampered["resolved_execution_asset"]["items"][1]
    tampered_item["resolved_execution_asset"]["single_case"]["name"] = (
        "tampered"
    )
    tampered["resolved_asset_revision"] = canonical_sha256(
        tampered["resolved_execution_asset"]
    )
    path.write_text(json.dumps(tampered), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(RuntimeOverrideError, match="第 2 项.*完整性"):
        load_execution_asset_file(
            path,
            runtime_root=runtime_root,
            project_id="dating",
            task_id=task_id,
        )

    cross_project = deepcopy(document)
    cross_project["resolved_execution_asset"]["items"][0]["project_id"] = (
        "truthy"
    )
    cross_project["resolved_asset_revision"] = canonical_sha256(
        cross_project["resolved_execution_asset"]
    )
    path.write_text(json.dumps(cross_project), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(RuntimeOverrideError, match="项目身份"):
        load_execution_asset_file(
            path,
            runtime_root=runtime_root,
            project_id="dating",
            task_id=task_id,
        )


def test_load_execution_asset_rejects_symlinked_parent_escape(tmp_path: Path) -> None:
    """任务目录即使经父级符号链接指向外部，也必须 fail-closed。"""
    task_id = "20260829-120001-abcd"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (runtime_root / "dating").symlink_to(outside, target_is_directory=True)
    path = outside / task_id / "execution-asset.json"
    path.parent.mkdir()
    resolved_asset = _flow_snapshot()["resolved_execution_asset"]
    document = {
        "schema_version": 1,
        "task_id": task_id,
        "project_id": "dating",
        "asset_type": "flow",
        "asset_id": "demo_flow",
        "asset_revision": f"sha256:{'1' * 64}",
        "resolved_asset_revision": canonical_sha256(resolved_asset),
        "resolved_execution_asset": resolved_asset,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(RuntimeOverrideError, match="符号链接|不属于"):
        load_execution_asset_file(
            runtime_root / "dating" / task_id / "execution-asset.json",
            runtime_root=runtime_root,
            project_id="dating",
            task_id=task_id,
        )


def test_case_loader_returns_normalized_runtime_inputs(multi_project_root: Path) -> None:
    """CaseLoader 应把 YAML 声明转换为带基础值的内部定义。"""
    project = multi_project_root / "projects" / "dating"
    selected = load_single_cases(project, ("GetMe::get_me_success",))[0]
    field = selected["runtime_inputs"]["client_locale"]
    assert field["default_value"] == "en-US"
    assert field["target"]["path"] == ["locale"]


def test_flow_loader_returns_normalized_runtime_inputs(multi_project_root: Path) -> None:
    """FlowLoader 应从同名 Scenario 读取运行时字段。"""
    project = multi_project_root / "projects" / "dating"
    selected = load_flow_cases(project, "dating_demo_flow")[0]
    field = selected["runtime_inputs"]["client_locale"]
    assert field["default_value"] == "en-US"
    assert field["target"]["step_id"] == "get_me"


def test_flow_loader_rejects_runtime_input_targeting_unknown_step(
    multi_project_root: Path,
) -> None:
    """静态项目校验必须拒绝指向不存在步骤的声明。"""
    project = multi_project_root / "projects" / "dating"
    scenario = project / "data" / "scenarios" / "dating_demo_flow.yaml"
    scenario.write_text(
        scenario.read_text(encoding="utf-8").replace(
            "step_id: get_me",
            "step_id: missing",
        ),
        encoding="utf-8",
    )
    with pytest.raises(FlowConfigError, match="missing"):
        load_flow_cases(project, "dating_demo_flow")
