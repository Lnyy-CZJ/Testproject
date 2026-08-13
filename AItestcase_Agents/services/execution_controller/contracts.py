"""Controller 窄接口与未启用容器策略模型。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ControllerModel(BaseModel):
    """拒绝额外字段，禁止调用方注入命令、宿主路径或环境变量。"""

    model_config = ConfigDict(extra="forbid")


class CreateRunRequest(ControllerModel):
    """Controller 唯一接受的创建参数。"""

    run_id: str
    input_id: str
    output_id: str
    input_sha256: str
    resource_policy_id: str
    egress_policy_id: str
    timeout_seconds: int = Field(ge=1, le=3600)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        """Run ID 必须使用平台生成的固定前缀。"""

        if not value.startswith("run_"):
            raise ValueError("run_id 不合法")
        return value

    @field_validator("input_id", "output_id")
    @classmethod
    def validate_storage_id(cls, value: str) -> str:
        """只接受 ``task/run/file`` 形式的逻辑 ID，禁止调用方传入宿主路径。"""

        parts = value.split("/")
        if len(parts) != 3 or any(not part or part in {".", ".."} for part in parts):
            raise ValueError("存储逻辑 ID 不合法")
        if any("\\" in part for part in parts):
            raise ValueError("存储逻辑 ID 不合法")
        return value


class RuntimeResult(ControllerModel):
    """Fake Runtime 返回的标准结果。"""

    status: Literal["succeeded", "failed", "cancelled", "timed_out"]
    result_id: str = ""
    error_code: str = ""


class ContainerPolicy(ControllerModel):
    """S2 前仅固化、不启用的单 Run 容器策略。"""

    policy_id: str
    image_digest: str
    run_as_user: int = Field(gt=0)
    read_only_root: bool = True
    drop_all_capabilities: bool = True
    cpu_limit: float = Field(gt=0, le=4)
    memory_mb: int = Field(ge=64, le=4096)
    pid_limit: int = Field(ge=16, le=1024)
    disk_mb: int = Field(ge=16, le=4096)
    provisioning_timeout_seconds: int = Field(ge=1, le=300)
    execution_timeout_seconds: int = Field(ge=1, le=3600)
    reporting_timeout_seconds: int = Field(ge=1, le=300)

    @field_validator("image_digest")
    @classmethod
    def require_fixed_digest(cls, value: str) -> str:
        """只接受 sha256 固定镜像摘要，不接受 tag 或镜像名。"""

        digest = value.removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise ValueError("image_digest 必须是固定 sha256 摘要")
        return f"sha256:{digest.lower()}"


class InternalAuthClaims(ControllerModel):
    """S2 前固化的 Controller 内部身份声明，不包含或配置真实 Secret。"""

    service_id: Literal["api-test-agent-web"]
    audience: Literal["api-execution-controller"]
    expires_at: str


def validate_internal_claims(claims: InternalAuthClaims, *, now: datetime | None = None) -> bool:
    """校验已由上游认证层验证过的内部身份时效；签名实现留待 S2。"""

    try:
        expiry = datetime.fromisoformat(claims.expires_at)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        return False
    return expiry > (now or datetime.now(UTC))


class RuntimeAdapter(Protocol):
    """测试可注入的运行时协议；生产默认实现只拒绝。"""

    def create(self, request: CreateRunRequest) -> RuntimeResult: ...
    def cancel(self, run_id: str) -> RuntimeResult: ...
    def reconcile(self, active_run_ids: set[str]) -> list[str]: ...
