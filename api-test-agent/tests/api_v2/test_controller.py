"""Controller 窄接口、Fake 生命周期和 Egress 负向策略测试。"""

import pytest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from pydantic import ValidationError

from services.execution_controller.contracts import ContainerPolicy, CreateRunRequest, InternalAuthClaims, validate_internal_claims
from services.execution_controller.fake_runtime import FakeRuntimeAdapter
from services.execution_controller.policies import RegisteredTarget, validate_destination, validate_redirect


def request_payload():
    return {
        "run_id": "run_123", "input_id": "task_20260813_0123456789abcdef0123/run_123/input.json",
        "output_id": "task_20260813_0123456789abcdef0123/run_123/executor-output.json",
        "input_sha256": "a" * 64, "resource_policy_id": "resource_1",
        "egress_policy_id": "egress_1", "timeout_seconds": 30,
        "plan_id": "plan_001", "plan_sha256": "b" * 64,
    }


def test_controller_rejects_runtime_escape_fields_and_reclaims_orphan():
    with pytest.raises(ValidationError):
        CreateRunRequest(**request_payload(), command=["curl"], environment={"TOKEN": "secret"})
    runtime = FakeRuntimeAdapter()
    result = runtime.create(CreateRunRequest(**request_payload()))
    assert result.status == "succeeded"
    assert runtime.reconcile(set()) == ["run_123"]
    assert runtime.states["run_123"].status == "cancelled"


def test_controller_accepts_only_plan_audit_reference_not_business_cases():
    """Controller 只接收计划 ID/SHA，不能接收用例、Host 或动态命令。"""

    request = CreateRunRequest(**request_payload())
    assert request.plan_id == "plan_001"
    with pytest.raises(ValidationError):
        CreateRunRequest(**request_payload(), cases=[{"request": {"path": "/health"}}])
    with pytest.raises(ValidationError):
        CreateRunRequest(**{key: value for key, value in request_payload().items() if key != "plan_sha256"})
    with pytest.raises(ValidationError):
        CreateRunRequest(**{key: value for key, value in request_payload().items() if key != "plan_id"})


def test_docker_runtime_requires_resolved_sha256_image_id(monkeypatch, tmp_path: Path):
    """固定镜像引用必须在 Controller 启动时解析为不可变 sha256 ID 并记录门禁。"""

    from services.execution_controller import docker_runtime

    invalid_client = SimpleNamespace(images=SimpleNamespace(get=lambda _reference: SimpleNamespace(id="executor:latest")))
    monkeypatch.setattr(docker_runtime.docker, "from_env", lambda: invalid_client)
    with pytest.raises(RuntimeError, match="EXECUTOR_IMAGE_DIGEST_INVALID"):
        docker_runtime.DockerRuntimeAdapter(
            runs_root=tmp_path, image_reference="executor:latest", executor_network="executor",
            proxy_url="http://proxy:5011", resource_policy_id="resource", egress_policy_id="egress",
        )

    valid_client = SimpleNamespace(images=SimpleNamespace(get=lambda _reference: SimpleNamespace(id="sha256:" + "a" * 64)))
    monkeypatch.setattr(docker_runtime.docker, "from_env", lambda: valid_client)
    runtime = docker_runtime.DockerRuntimeAdapter(
        runs_root=tmp_path, image_reference="executor:latest", executor_network="executor",
        proxy_url="http://proxy:5011", resource_policy_id="resource", egress_policy_id="egress",
    )
    assert runtime.image_id == "sha256:" + "a" * 64
    assert runtime.image_gate == "EXECUTOR_IMAGE_DIGEST_VERIFIED"


def test_controller_requires_input_plan_reference_to_match_narrow_request() -> None:
    """即使输入文件 SHA 正确，计划 ID/SHA 与窄请求不一致也必须失败关闭。"""

    from services.execution_controller.docker_runtime import plan_reference_matches

    request = CreateRunRequest(**request_payload())
    assert plan_reference_matches({"plan": {"plan_id": "plan_001", "sha256": "b" * 64}}, request)
    assert not plan_reference_matches({"plan": {"plan_id": "plan_other", "sha256": "b" * 64}}, request)
    assert not plan_reference_matches({"plan": {"plan_id": "plan_001", "sha256": "c" * 64}}, request)


def test_egress_blocks_ssrf_host_header_redirect_and_unregistered_paths():
    target = RegisteredTarget(
        target_id="target_1", schemes=frozenset({"https"}), hosts=frozenset({"api.example.test"}),
        ports=frozenset({443}), path_prefixes=("/v1/",),
    )
    assert validate_destination("https://api.example.test/v1/users", target, ["127.0.0.1"])[1] == "SSRF_ADDRESS_DENIED"
    assert validate_destination("https://api.example.test/v1/users", target, ["203.0.113.10"], host_header="evil.test")[1] == "HOST_HEADER_MISMATCH"
    assert validate_destination("https://api.example.test/admin", target, ["203.0.113.10"])[1] == "EGRESS_PATH_DENIED"
    assert validate_redirect("http://169.254.169.254/latest", target, ["169.254.169.254"])[0] is False


def test_fixed_digest_policy_and_internal_claim_expiry():
    with pytest.raises(ValidationError):
        ContainerPolicy(
            policy_id="p1", image_digest="runner:latest", run_as_user=10001,
            cpu_limit=1, memory_mb=256, pid_limit=64, disk_mb=128,
            provisioning_timeout_seconds=30, execution_timeout_seconds=60, reporting_timeout_seconds=30,
        )
    now = datetime.now(UTC)
    valid = InternalAuthClaims(
        service_id="api-test-agent-web", audience="api-execution-controller",
        expires_at=(now + timedelta(minutes=1)).isoformat(),
    )
    assert validate_internal_claims(valid, now=now)
    assert not validate_internal_claims(valid.model_copy(update={"expires_at": (now - timedelta(seconds=1)).isoformat()}), now=now)
