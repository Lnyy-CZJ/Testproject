"""从本地 Artifact 和 Wire Log 读取 Web 所需的历史运行数据。

Repository 是只读边界：浏览器只能通过可信的 ``run_id``、``case_id`` 和 Manifest 绑定的
日志相对路径读取内容，不能把任意服务端路径传给 Flask。Artifact 中的业务正文沿用既有
落盘策略，完整请求/响应正文只存在用户明确要求的本地 Wire Log。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aidating_eval.artifacts import SAFE_NAME_RE


ALLOWED_CASE_FILES = (
    "metadata.json",
    "task.json",
    "result.json",
    "diagnostics.json",
    "cleanup.json",
    "error.json",
)
ALLOWED_LOG_TAILS = frozenset({100, 200, 500})


@dataclass(frozen=True)
class RunQuery:
    """Run 列表的安全筛选参数。"""

    mode: str | None = None
    task_kind: str | None = None
    status: str | None = None
    page: int = 1
    page_size: int = 50

    def __post_init__(self) -> None:
        if self.page < 1 or self.page_size < 1 or self.page_size > 100:
            raise ValueError("page/page_size 超出允许范围")


@dataclass(frozen=True)
class RunPage:
    items: tuple[dict[str, Any], ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True)
class LogTail:
    lines: tuple[str, ...]
    truncated: bool
    tail: int


class RunRepository:
    """安全读取本地 Run、Case Artifact 和 Wire Log。"""

    def __init__(
        self,
        *,
        artifacts_root: Path,
        logs_root: Path,
        active_provider: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.logs_root = Path(logs_root)
        self.active_provider = active_provider

    def list_runs(self, query: RunQuery | None = None) -> RunPage:
        """按时间倒序返回可解析的 Run 摘要；单条损坏 Artifact 不拖垮列表。"""

        query = query or RunQuery()
        summaries: list[dict[str, Any]] = []
        if not self.artifacts_root.is_dir():
            return RunPage((), query.page, query.page_size, 0)
        for entry in self.artifacts_root.iterdir():
            if not entry.is_dir() or entry.is_symlink() or not SAFE_NAME_RE.fullmatch(entry.name):
                continue
            try:
                manifest = self._read_manifest(entry.name)
            except ValueError:
                continue
            self._fill_legacy_summary(manifest, entry)
            item = self._summary(manifest)
            active = self.active_provider(entry.name) if self.active_provider else None
            if active:
                item.update(dict(active))
            if query.mode and item.get("mode") != query.mode:
                continue
            if query.task_kind and item.get("task_kind") != query.task_kind:
                continue
            if query.status and item.get("status") != query.status:
                continue
            summaries.append(item)
        summaries.sort(
            key=lambda item: (str(item.get("updated_at", "")), str(item.get("run_id", ""))),
            reverse=True,
        )
        offset = (query.page - 1) * query.page_size
        return RunPage(
            tuple(summaries[offset : offset + query.page_size]),
            query.page,
            query.page_size,
            len(summaries),
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        """读取 Run Manifest、状态事件和 Case 摘要。"""

        run_path = self._safe_run_path(run_id)
        manifest = self._read_manifest(run_id)
        events = self._read_events(run_path / "run-state.jsonl")
        self._fill_legacy_summary(manifest, run_path, events=events)
        case_ids = manifest.get("case_ids")
        if not isinstance(case_ids, list):
            cases_root = run_path / "cases"
            case_ids = [
                entry.name
                for entry in cases_root.iterdir()
                if entry.is_dir() and not entry.is_symlink() and SAFE_NAME_RE.fullmatch(entry.name)
            ] if cases_root.is_dir() else []
        cases = []
        for case_id in case_ids:
            if not isinstance(case_id, str) or not SAFE_NAME_RE.fullmatch(case_id):
                continue
            cases.append(self._case_summary(run_path, case_id))
        result: dict[str, Any] = {
            "manifest": manifest,
            "cases": cases,
            "events": events,
            "log_available": self._log_path(manifest, require_exists=False) is not None,
        }
        active = self.active_provider(run_id) if self.active_provider else None
        if active:
            result["active"] = dict(active)
        return result

    def get_case(self, run_id: str, case_id: str) -> dict[str, Any]:
        """读取固定白名单中的 Case Artifact，不接受任意文件名。"""

        run_path = self._safe_run_path(run_id)
        manifest = self._read_manifest(run_id)
        case_ids = manifest.get("case_ids")
        if isinstance(case_ids, list) and case_id not in case_ids:
            raise ValueError("case_id 不属于目标 Run")
        if not SAFE_NAME_RE.fullmatch(case_id):
            raise ValueError("case_id 不是安全标识")
        case_path = run_path / "cases" / case_id
        if not case_path.is_dir() or case_path.is_symlink():
            raise ValueError("Case Artifact 不存在")
        payload: dict[str, Any] = {}
        for filename in ALLOWED_CASE_FILES:
            candidate = case_path / filename
            if not candidate.exists() or candidate.is_symlink():
                continue
            if not candidate.is_file() or not candidate.resolve().is_relative_to(case_path.resolve()):
                raise ValueError("Case Artifact 路径无效")
            payload[filename.removesuffix(".json")] = self._read_json(candidate)
        if not payload:
            raise ValueError("Case Artifact 不存在")
        return payload

    def tail_log(self, run_id: str, line_count: int = 200) -> LogTail:
        """按 Manifest 绑定的相对路径读取日志尾部。"""

        if line_count not in ALLOWED_LOG_TAILS:
            raise ValueError("日志 tail 只能是 100、200 或 500")
        manifest = self._read_manifest(run_id)
        log_path = self._log_path(manifest, require_exists=True)
        if log_path is None:
            raise ValueError("日志不存在")
        try:
            content = log_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("日志不可读") from exc
        all_lines = content.splitlines()
        truncated = len(all_lines) > line_count
        return LogTail(tuple(all_lines[-line_count:]), truncated, line_count)

    def _summary(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        keys = (
            "run_id",
            "created_at",
            "updated_at",
            "mode",
            "task_kind",
            "status",
            "case_count",
            "cleanup_status",
            "cancel_requested",
            "summary",
        )
        return {key: manifest[key] for key in keys if key in manifest}

    def _case_summary(self, run_path: Path, case_id: str) -> dict[str, Any]:
        case_path = run_path / "cases" / case_id
        result: dict[str, Any] = {"case_id": case_id}
        metadata_path = case_path / "metadata.json"
        task_path = case_path / "task.json"
        cleanup_path = case_path / "cleanup.json"
        for label, candidate in (
            ("metadata", metadata_path),
            ("task", task_path),
            ("cleanup", cleanup_path),
        ):
            if candidate.is_file() and not candidate.is_symlink():
                try:
                    result[label] = self._read_json(candidate)
                except ValueError:
                    result[label] = {"error_code": "LOCAL_ARTIFACT_INVALID"}
        return result

    def _read_manifest(self, run_id: str) -> dict[str, Any]:
        run_path = self._safe_run_path(run_id)
        manifest = self._read_json(run_path / "manifest.json")
        if manifest.get("run_id") != run_id:
            raise ValueError("manifest run_id 与目录不匹配")
        return manifest

    def _fill_legacy_summary(
        self,
        manifest: dict[str, Any],
        run_path: Path,
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        """为旧 CLI 产物补齐列表/详情所需的非敏感摘要，不改写磁盘。"""

        config = manifest.get("config")
        if isinstance(config, Mapping):
            manifest.setdefault("mode", config.get("mode"))
        cases_root = run_path / "cases"
        case_dirs = (
            [item for item in cases_root.iterdir() if item.is_dir() and not item.is_symlink()]
            if cases_root.is_dir()
            else []
        )
        if "case_count" not in manifest:
            manifest["case_count"] = len(case_dirs)
        if "case_ids" not in manifest:
            manifest["case_ids"] = [item.name for item in case_dirs if SAFE_NAME_RE.fullmatch(item.name)]
        if events is None:
            try:
                events = self._read_events(run_path / "run-state.jsonl")
            except ValueError:
                events = []
        if "task_kind" not in manifest:
            kinds = {
                str(event.get("data", {}).get("task_kind"))
                for event in events
                if isinstance(event.get("data"), Mapping) and event.get("data", {}).get("task_kind")
            }
            if len(kinds) == 1:
                manifest["task_kind"] = next(iter(kinds))
            elif len(kinds) > 1:
                manifest["task_kind"] = "mixed"
        if "status" not in manifest:
            finished = [
                event.get("data", {}).get("status")
                for event in events
                if event.get("event") == "case_finished" and isinstance(event.get("data"), Mapping)
            ]
            if finished and all(value == "completed" for value in finished):
                manifest["status"] = "completed"
            elif finished:
                manifest["status"] = "failed"
            else:
                manifest["status"] = "unknown"
        if "cleanup_status" not in manifest:
            cleanup_events = {
                event.get("event")
                for event in events
                if event.get("event") in {"delete_succeeded", "delete_already_absent", "delete_failed"}
            }
            manifest["cleanup_status"] = (
                "deleted"
                if cleanup_events and "delete_failed" not in cleanup_events
                else "pending"
                if "delete_failed" in cleanup_events
                else "unknown"
            )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("本地 JSON Artifact 损坏") from exc
        if not isinstance(value, dict):
            raise ValueError("本地 JSON Artifact 必须是对象")
        return value

    @staticmethod
    def _read_events(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        if path.is_symlink():
            raise ValueError("run-state.jsonl 不允许是符号链接")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError("run-state.jsonl 不可读") from exc
        events: list[dict[str, Any]] = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("run-state.jsonl 包含损坏记录") from exc
            if isinstance(value, dict):
                events.append(value)
        return events

    def _safe_run_path(self, run_id: str) -> Path:
        if not SAFE_NAME_RE.fullmatch(run_id):
            raise ValueError("run_id 不是安全标识")
        path = self.artifacts_root / run_id
        if path.is_symlink():
            raise ValueError("Run 目录不允许是符号链接")
        try:
            resolved_root = self.artifacts_root.resolve()
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("Run 不存在") from exc
        if not resolved.is_relative_to(resolved_root) or not resolved.is_dir():
            raise ValueError("Run 路径无效")
        return resolved

    def _log_path(
        self,
        manifest: Mapping[str, Any],
        *,
        require_exists: bool,
    ) -> Path | None:
        relative = manifest.get("wire_log_path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            return None
        candidate = self.logs_root / relative
        # 先检查逻辑路径本身，再 resolve；否则 resolve 后的目标已经不再是 symlink，
        # 一个指向 logs 根目录外的链接可能绕过后续的文件类型判断。
        if candidate.is_symlink():
            return None
        try:
            resolved = candidate.resolve(strict=require_exists)
        except OSError:
            return None
        if not resolved.is_relative_to(self.logs_root.resolve()):
            return None
        if require_exists and not resolved.is_file():
            return None
        return resolved
