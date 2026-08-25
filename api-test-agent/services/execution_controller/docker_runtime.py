"""S2 单 Run Docker 运行时；仅 Controller 进程可导入本模块。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path

import docker
from docker.errors import APIError, ImageNotFound, NotFound
from requests.exceptions import ReadTimeout

from services.execution_controller.contracts import CreateRunRequest, RuntimeResult


def plan_reference_matches(payload: object, request: CreateRunRequest) -> bool:
    """确认挂载输入中的计划引用与 Controller 窄请求完全一致。

    输入文件 SHA 只能证明文件未在传输中变化；本校验进一步防止调用方把一个
    计划的审计 ID/SHA 与另一份计划正文组合后交给 Executor。
    """

    if not isinstance(payload, dict):
        return False
    plan = payload.get("plan") or payload.get("execution_plan")
    return bool(
        isinstance(plan, dict)
        and str(plan.get("plan_id", "")) == request.plan_id
        and str(plan.get("sha256", "")) == request.plan_sha256
    )


class DockerRuntimeAdapter:
    """以固定镜像 ID 创建一个短生命周期、受限且无 Docker Socket 的 Executor。"""

    def __init__(
        self, *, runs_root: Path, image_reference: str, executor_network: str,
        proxy_url: str, resource_policy_id: str, egress_policy_id: str,
    ) -> None:
        """初始化运行时并解析不可变镜像 ID；镜像不存在时启动失败关闭。"""

        self.runs_root = runs_root.resolve()
        self.client = docker.from_env()
        try:
            image = self.client.images.get(image_reference)
        except ImageNotFound as exc:
            raise RuntimeError("固定 Executor 镜像不存在") from exc
        # 镜像引用可以是部署侧 tag，但 Docker 解析后的运行标识必须是不可变 sha256。
        # 该门禁防止 Controller 将可漂移 tag 作为真正的 Executor 镜像执行。
        raw_image_id = str(image.id)
        digest = raw_image_id.removeprefix("sha256:")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise RuntimeError("EXECUTOR_IMAGE_DIGEST_INVALID")
        self.image_id = f"sha256:{digest.lower()}"
        self.image_digest = self.image_id
        self.image_gate = "EXECUTOR_IMAGE_DIGEST_VERIFIED"
        self.executor_network = executor_network
        self.proxy_url = proxy_url
        self.resource_policy_id = resource_policy_id
        self.egress_policy_id = egress_policy_id

    def _resolve(self, logical_id: str, expected_name: str) -> Path:
        """将已校验逻辑 ID 解析到任务目录，并执行二次目录包含校验。"""

        task_id, run_id, name = logical_id.split("/")
        if name != expected_name or not task_id.startswith("task_") or not run_id.startswith("run_"):
            raise ValueError("逻辑 ID 与目标文件不匹配")
        path = (self.runs_root / task_id / "runs" / run_id / name).resolve()
        if self.runs_root not in path.parents:
            raise ValueError("逻辑 ID 越界")
        return path

    def create(self, request: CreateRunRequest) -> RuntimeResult:
        """校验输入 SHA 后同步运行容器，并将容器退出状态映射为稳定结果。"""

        if request.resource_policy_id != self.resource_policy_id or request.egress_policy_id != self.egress_policy_id:
            return RuntimeResult(status="failed", error_code="EXECUTION_POLICY_DENIED")
        container = None
        original_mode: int | None = None
        try:
            input_path = self._resolve(request.input_id, "input.json")
            output_path = self._resolve(request.output_id, "executor-output.json")
            raw = input_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != request.input_sha256:
                return RuntimeResult(status="failed", error_code="EXECUTION_INPUT_SHA_MISMATCH")
            payload = json.loads(raw)
            if not plan_reference_matches(payload, request):
                return RuntimeResult(status="failed", error_code="EXECUTION_PLAN_SHA_MISMATCH")
            output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Executor 仅绑定当前输入文件；临时开放只读位，Run 结束后立即恢复原权限。
            original_mode = input_path.stat().st_mode & 0o777
            input_path.chmod(0o444)
            container = self.client.containers.run(
                self.image_id,
                detach=True,
                name=f"api-executor-{request.run_id}",
                network=self.executor_network,
                user="10003:10003",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit="256m",
                nano_cpus=500_000_000,
                pids_limit=64,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=32m", "/run/output": "rw,noexec,nosuid,size=32m"},
                volumes={str(input_path): {"bind": "/run/input/input.json", "mode": "ro"}},
                environment={"HTTP_PROXY": self.proxy_url, "NO_PROXY": ""},
                # 仅记录计划引用和镜像门禁，不解释 DAG、用例、请求正文或 Credential。
                labels={
                    "api-test-agent.run-id": request.run_id,
                    "api-test-agent.managed": "true",
                    "api-test-agent.executor-image-digest": self.image_digest,
                    "api-test-agent.image-gate": self.image_gate,
                    **({"api-test-agent.plan-id": request.plan_id, "api-test-agent.plan-sha256": request.plan_sha256} if request.plan_id else {}),
                },
            )
            wait_result = container.wait(timeout=request.timeout_seconds)
            status_code = int(wait_result.get("StatusCode", 1))
            output = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            if output:
                if len(output.encode("utf-8")) > 16 * 1024 * 1024:
                    return RuntimeResult(status="failed", error_code="EXECUTOR_RESULT_TOO_LARGE")
                payload = json.loads(output)
                temporary = output_path.with_name(f".{output_path.name}.{secrets.token_hex(4)}.tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                temporary.chmod(0o600)
                os.replace(temporary, output_path)
            if status_code == 0 and output_path.is_file():
                return RuntimeResult(status="succeeded", result_id=request.output_id)
            return RuntimeResult(status="failed", error_code="EXECUTOR_FAILED")
        except ReadTimeout:
            return RuntimeResult(status="timed_out", error_code="EXECUTION_TIMEOUT")
        except (OSError, ValueError, json.JSONDecodeError):
            return RuntimeResult(status="failed", error_code="EXECUTION_INPUT_INVALID")
        except APIError:
            return RuntimeResult(status="failed", error_code="RUNTIME_UNAVAILABLE")
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except APIError:
                    pass
            if original_mode is not None:
                try:
                    input_path.chmod(original_mode)
                except OSError:
                    pass

    def cancel(self, run_id: str) -> RuntimeResult:
        """按固定容器名取消 Run；不存在时返回稳定错误。"""

        try:
            container = self.client.containers.get(f"api-executor-{run_id}")
            container.kill()
            container.remove(force=True)
            return RuntimeResult(status="cancelled")
        except NotFound:
            return RuntimeResult(status="failed", error_code="RUN_NOT_FOUND")
        except APIError:
            return RuntimeResult(status="failed", error_code="RUNTIME_UNAVAILABLE")

    def reconcile(self, active_run_ids: set[str]) -> list[str]:
        """回收带平台标签但不在活动清单中的孤儿 Executor。"""

        reclaimed: list[str] = []
        for container in self.client.containers.list(all=True, filters={"label": "api-test-agent.managed=true"}):
            run_id = container.labels.get("api-test-agent.run-id", "")
            if run_id and run_id not in active_run_ids:
                container.remove(force=True)
                reclaimed.append(run_id)
        return sorted(reclaimed)
