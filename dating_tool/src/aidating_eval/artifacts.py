"""以私密权限写入最小、脱敏的本地排障产物。"""

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4
import json
import os
import re

from aidating_eval.redaction import redact_mapping


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

# Artifact 不信任后端未来新增字段。每类文件只允许落盘完成协议排障所需的稳定元数据；
# 对话、Prompt、模型正文和未知字段全部丢弃，而不是依赖一份永远追不上协议演进的黑名单。
CASE_ARTIFACT_FIELDS = {
    "metadata": frozenset(
        {"case_id", "mode", "task_kind", "locale", "attempt_id"}
    ),
    "task": frozenset(
        {
            "task_id",
            "task_type",
            "status",
            "phase",
            "retryable",
            "error_code",
            "create_time",
            "expire_time",
            "schema_version",
        }
    ),
    "result": frozenset(
        {"task_id", "task_type", "schema_version", "result"}
    ),
    "diagnostics": frozenset(
        {
            "case_id",
            "run_id",
            "model_alias",
            "prompt_version",
            "policy_version",
            "result_schema_version",
            "policy_codes",
            "validation_codes",
            "retry_count",
            "input_tokens",
            "output_tokens",
            "model_latency_ms",
        }
    ),
    "cleanup": frozenset(
        {
            "success",
            "status",
            "task_id",
            "task_ids",
            "deleted",
            "logical_deleted",
            "object_deletion_status",
            "error_type",
            "business_error_code",
        }
    ),
    "error": frozenset({"error_type", "business_error_code"}),
}

EVENT_DATA_FIELDS = frozenset(
    {
        "attempt_id",
        "mode",
        "task_kind",
        "task_id",
        "task_type",
        "phase",
        "status",
        "business_error_code",
        "error_type",
        "asset_ids",
        "asset_count",
        "message_count",
        "text_bytes",
        "negative_variant",
        "quota_checked",
    }
)


def _artifact_kind(filename: str) -> str | None:
    match = re.fullmatch(
        r"(metadata|task|result|diagnostics|cleanup|error)(?:-[1-9][0-9]*)?\.json",
        filename,
    )
    return match.group(1) if match else None


def _safe_case_payload(filename: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """按 Artifact 类型建立允许字段视图，正文容器只保留脱敏占位。"""

    kind = _artifact_kind(filename)
    if kind is None:
        raise ValueError("filename 不是允许的 Case Artifact")
    allowed = CASE_ARTIFACT_FIELDS[kind]
    safe: dict[str, Any] = {}
    for key in allowed:
        if key not in payload:
            continue
        safe[key] = "***" if key == "result" else payload[key]
    return safe


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


class ArtifactStore:
    """一个 Run 的安全 Artifact 写入器。

    ``run-state.jsonl`` 是追加式恢复证据，因此每次追加都会 flush + fsync；普通 JSON 使用
    同目录临时文件原子替换，避免进程中断留下半个 JSON。
    """

    def __init__(self, root: Path, run_id: str) -> None:
        if not SAFE_NAME_RE.fullmatch(run_id):
            raise ValueError("run_id 不是安全文件名")
        self.root = Path(root)
        self.run_id = run_id
        self.run_path = self.root / run_id
        self._event_lock = Lock()
        self._manifest_lock = Lock()
        self._prepare_directory(self.root)
        self._prepare_directory(self.run_path)
        self._prepare_directory(self.run_path / "cases")

    @staticmethod
    def _prepare_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

    def start_run(self, redacted_config: Mapping[str, Any] | None = None) -> Path:
        """创建或刷新 manifest，并返回本次 Run 的精确目录。"""

        created_at = datetime.now(timezone.utc).isoformat()
        self._atomic_write_json(
            self.run_path / "manifest.json",
            {
                "schema_version": "aidating.run.manifest.v1",
                "run_id": self.run_id,
                "created_at": created_at,
                "updated_at": created_at,
                "status": "waiting",
                "config": dict(redacted_config or {}),
            },
        )
        return self.run_path

    def update_manifest(self, changes: Mapping[str, Any]) -> dict[str, Any]:
        """原子合并 Run Manifest，供后台状态和 Web 查询共享。

        ``run_id`` 是目录与远端追踪的身份锚点，不能被调用方覆盖；其它字段采用浅层
        合并，嵌套的 ``summary`` 等对象由调用方一次性提供完整值。每次更新自动刷新
        ``updated_at``，并沿用 ``_atomic_write_json`` 的私有权限和 fsync 语义。
        """

        manifest_path = self.run_path / "manifest.json"
        with self._manifest_lock:
            try:
                current = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("manifest.json 不存在或损坏") from exc
            if not isinstance(current, dict):
                raise ValueError("manifest.json 必须是 JSON 对象")
            requested_run_id = changes.get("run_id")
            if requested_run_id is not None and requested_run_id != self.run_id:
                raise ValueError("manifest run_id 不可修改")
            merged = dict(current)
            merged.update(dict(changes))
            merged["run_id"] = self.run_id
            merged["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._atomic_write_json(manifest_path, merged)
            return merged

    def append_event(
        self,
        case_id: str,
        event: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        """线程安全地追加一条不含正文或 Secret 的运行状态。"""

        self._validate_name(case_id, "case_id")
        self._validate_name(event, "event")
        safe_data = {
            key: value
            for key, value in dict(data or {}).items()
            if key in EVENT_DATA_FIELDS
        }
        payload = redact_mapping(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "case_id": case_id,
                "event": event,
                "data": safe_data,
            }
        )
        line = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )
        path = self.run_path / "run-state.jsonl"
        with self._event_lock:
            descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                path.chmod(0o600)
            except Exception:
                # fdopen 接管 descriptor；只有在打开文件前失败才需要显式关闭。
                raise

    def write_case_payload(
        self,
        case_id: str,
        filename: str,
        payload: Mapping[str, Any],
    ) -> Path:
        """原子写入单案例 JSON，并在写入前执行统一脱敏。"""

        self._validate_name(case_id, "case_id")
        if not SAFE_NAME_RE.fullmatch(filename) or not filename.endswith(".json"):
            raise ValueError("filename 必须是安全 JSON 文件名")
        case_path = self.run_path / "cases" / case_id
        self._prepare_directory(case_path)
        destination = case_path / filename
        self._atomic_write_json(
            destination,
            redact_mapping(_safe_case_payload(filename, payload)),
        )
        return destination

    @staticmethod
    def _validate_name(value: str, field: str) -> None:
        if not SAFE_NAME_RE.fullmatch(value):
            raise ValueError(f"{field} 不是安全文件名")

    @staticmethod
    def _atomic_write_json(path: Path, payload: object) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        encoded = json.dumps(
            redact_mapping(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        ).encode("utf-8")
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
            path.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
