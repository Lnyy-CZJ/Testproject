"""Web 上传 Draft 的私有暂存。

Draft 只承担“浏览器输入 -> 可供既有 Case Loader 读取的本地文件”这一职责。它不执行
任何后端请求，也不把浏览器提交的字段原样当作 Gateway 参数；E2E 表单会重新组装成冻结
的 ``aidating.e2e.case.v1``，Eval 则只接受 UTF-8 JSONL 文件，最终仍由 application 的
统一 Loader 做第二次完整校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import re
import shutil
from threading import Lock
from time import time
from typing import Any, Iterable, Mapping
from uuid import uuid4


_DRAFT_ID_RE = re.compile(r"^draft-[A-Za-z0-9-]{8,80}$")
_FILE_NAME_RE = re.compile(r"^[^/\\\x00-\x1f]{1,120}$")
_MEDIA_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@dataclass(frozen=True)
class DraftRecord:
    """一次待认领 Web 输入的安全索引。"""

    draft_id: str
    mode: str
    task_kind: str
    root: Path
    dataset_path: Path
    fixture_root: Path | None
    case_id: str | None
    eval_concurrency: int | None
    source_name: str
    media_paths: tuple[Path, ...] = ()
    created_at: str = ""

    def to_request_kwargs(self) -> dict[str, Any]:
        """转换为 ``RunRequest`` 可用的非敏感字段。"""

        return {
            "mode": self.mode,
            "dataset_path": self.dataset_path,
            "fixture_root": self.fixture_root,
            "case_id": self.case_id,
            "eval_concurrency": self.eval_concurrency,
            "source_name": self.source_name,
        }


class WebInputStore:
    """管理 Draft 的创建、单次认领、清理和安全读取。"""

    def __init__(self, root: Path, *, draft_ttl_seconds: int = 3600) -> None:
        if draft_ttl_seconds < 60:
            raise ValueError("draft_ttl_seconds 必须至少为 60 秒")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.draft_ttl_seconds = draft_ttl_seconds
        self._lock = Lock()

    def create_e2e_draft(
        self,
        *,
        task_kind: str,
        locale: str,
        media: Iterable[tuple[str, bytes]],
        case_options: Mapping[str, Any] | None = None,
    ) -> DraftRecord:
        """把 E2E 表单和按顺序上传的图片写为单 Case Fixture。"""

        if task_kind not in {"reply", "analysis"}:
            raise ValueError("task_kind 必须为 reply 或 analysis")
        if not isinstance(locale, str) or not locale or len(locale) > 64:
            raise ValueError("locale 必须是 1～64 个字符")
        options = dict(case_options or {})
        allowed = (
            {"dating_goal", "your_voice", "requested_intent", "background"}
            if task_kind == "reply"
            else {"other_person_name", "background"}
        )
        unknown = set(options) - allowed
        if unknown:
            raise ValueError(f"E2E 表单字段不受支持: {','.join(sorted(unknown))}")

        media_items = list(media)
        if not media_items:
            raise ValueError("E2E 至少需要一张图片")
        draft_id = self._new_id()
        root = self.root / draft_id
        fixture_root = root / "fixture"
        media_root = fixture_root / "media"
        try:
            self._prepare_directory(root)
            self._prepare_directory(fixture_root)
            self._prepare_directory(media_root)
            media_entries: list[dict[str, str]] = []
            media_paths: list[Path] = []
            for index, (filename, content) in enumerate(media_items, 1):
                safe_name = self._safe_media_name(filename)
                if not isinstance(content, bytes) or not content:
                    raise ValueError("上传图片不能为空")
                stored = media_root / f"{index:04d}-{safe_name}"
                self._atomic_write_bytes(stored, content)
                media_paths.append(stored)
                media_entries.append({"path": f"media/{stored.name}"})
            case = self._build_e2e_case(
                task_kind=task_kind,
                locale=locale,
                media_entries=media_entries,
                options=options,
            )
            dataset_path = root / "dataset.json"
            self._atomic_write_json(dataset_path, case)
            return self._write_record(
                draft_id=draft_id,
                mode="e2e",
                task_kind=task_kind,
                root=root,
                dataset_path=dataset_path,
                fixture_root=fixture_root,
                case_id=str(case["case_id"]),
                eval_concurrency=None,
                source_name="web-e2e",
                media_paths=tuple(media_paths),
            )
        except Exception:
            self._remove_draft_path(root)
            raise

    def create_eval_draft(
        self,
        content: bytes,
        *,
        filename: str = "dataset.jsonl",
        case_id: str | None = None,
        eval_concurrency: int | None = None,
    ) -> DraftRecord:
        """保存用户上传的 Eval JSONL；不改写正文，确保 Case 行号可排查。"""

        if not isinstance(content, bytes) or not content:
            raise ValueError("Eval JSONL 不能为空")
        if not self._safe_file_name(filename) or Path(filename).suffix.lower() != ".jsonl":
            raise ValueError("Eval dataset 必须是安全的 .jsonl 文件名")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Eval JSONL 必须使用 UTF-8") from exc
        if case_id is not None and not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", case_id):
            raise ValueError("case_id 不是安全标识")
        if eval_concurrency is not None and not 1 <= eval_concurrency <= 5:
            raise ValueError("eval_concurrency 必须在 1 到 5 之间")
        draft_id = self._new_id()
        root = self.root / draft_id
        try:
            self._prepare_directory(root)
            dataset_path = root / "dataset.jsonl"
            self._atomic_write_bytes(dataset_path, content)
            return self._write_record(
                draft_id=draft_id,
                mode="eval",
                task_kind="mixed",
                root=root,
                dataset_path=dataset_path,
                fixture_root=None,
                case_id=case_id,
                eval_concurrency=eval_concurrency,
                source_name=filename,
            )
        except Exception:
            self._remove_draft_path(root)
            raise

    def get(self, draft_id: str) -> DraftRecord:
        """读取 Draft 索引并验证所有路径仍位于 Draft 根目录。"""

        root = self._safe_path(draft_id)
        record_path = root / "draft.json"
        try:
            raw = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Draft 不存在或已损坏") from exc
        if not isinstance(raw, dict) or raw.get("draft_id") != draft_id:
            raise ValueError("Draft 索引无效")
        dataset_path = self._inside(root, Path(str(raw.get("dataset_name", ""))))
        fixture_name = raw.get("fixture_name")
        fixture_root = self._inside(root, Path(str(fixture_name))) if fixture_name else None
        media_names = raw.get("media_names", [])
        if not isinstance(media_names, list):
            raise ValueError("Draft media 索引无效")
        media_paths = tuple(self._inside(root, Path(str(name))) for name in media_names)
        if not dataset_path.is_file() or any(not path.is_file() for path in media_paths):
            raise ValueError("Draft 文件不完整")
        return DraftRecord(
            draft_id=draft_id,
            mode=str(raw.get("mode")),
            task_kind=str(raw.get("task_kind")),
            root=root,
            dataset_path=dataset_path,
            fixture_root=fixture_root,
            case_id=raw.get("case_id") if isinstance(raw.get("case_id"), str) else None,
            eval_concurrency=(
                int(raw["eval_concurrency"])
                if raw.get("eval_concurrency") is not None
                else None
            ),
            source_name=str(raw.get("source_name", "web")),
            media_paths=media_paths,
            created_at=str(raw.get("created_at", "")),
        )

    def claim(self, draft_id: str) -> DraftRecord:
        """以 O_EXCL 标记一次认领，防止双击或两个浏览器重复执行。"""

        with self._lock:
            record = self.get(draft_id)
            marker = record.root / ".claimed"
            try:
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError as exc:
                raise ValueError("Draft 已被认领") from exc
            return record

    def delete(self, draft_id: str) -> None:
        """删除指定 Draft；不存在视为幂等成功，符号链接绝不跟随。"""

        with self._lock:
            if not _DRAFT_ID_RE.fullmatch(draft_id):
                raise ValueError("draft_id 不是安全标识")
            path = self.root / draft_id
            if not path.exists() and not path.is_symlink():
                return
            if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("Draft 路径无效")
            shutil.rmtree(path)

    def purge_stale(self, *, now: float | None = None) -> int:
        """清理超过 TTL 的 Draft，返回清理数量。"""

        cutoff = (time() if now is None else now) - self.draft_ttl_seconds
        removed = 0
        for entry in tuple(self.root.iterdir()) if self.root.is_dir() else ():
            if entry.is_symlink() or not entry.is_dir() or not _DRAFT_ID_RE.fullmatch(entry.name):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    self.delete(entry.name)
                    removed += 1
            except (OSError, ValueError):
                continue
        return removed

    def _write_record(self, **kwargs: Any) -> DraftRecord:
        record = DraftRecord(
            created_at=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )
        relative_dataset = record.dataset_path.relative_to(record.root).as_posix()
        relative_fixture = (
            record.fixture_root.relative_to(record.root).as_posix()
            if record.fixture_root is not None
            else None
        )
        payload = {
            "draft_id": record.draft_id,
            "mode": record.mode,
            "task_kind": record.task_kind,
            "dataset_name": relative_dataset,
            "fixture_name": relative_fixture,
            "media_names": [path.relative_to(record.root).as_posix() for path in record.media_paths],
            "case_id": record.case_id,
            "eval_concurrency": record.eval_concurrency,
            "source_name": record.source_name,
            "created_at": record.created_at,
        }
        self._atomic_write_json(record.root / "draft.json", payload)
        return record

    @staticmethod
    def _build_e2e_case(
        *,
        task_kind: str,
        locale: str,
        media_entries: list[dict[str, str]],
        options: Mapping[str, Any],
    ) -> dict[str, Any]:
        case: dict[str, Any] = {
            "schema_version": "aidating.e2e.case.v1",
            "case_id": f"web-e2e-{uuid4().hex[:10]}",
            "task_kind": task_kind,
            "locale": locale,
            "media": media_entries,
        }
        if task_kind == "reply":
            case["preferences"] = {
                "dating_goal": options.get("dating_goal", "serious_relationship"),
                "your_voice": options.get("your_voice", "warm_direct"),
            }
            case["reply"] = {
                key: options[key]
                for key in ("requested_intent", "background")
                if key in options and options[key] is not None
            }
        else:
            case["analysis"] = {
                key: options[key]
                for key in ("other_person_name", "background")
                if key in options and options[key] is not None
            }
        return case

    @staticmethod
    def _new_id() -> str:
        return f"draft-{uuid4().hex}"

    @staticmethod
    def _prepare_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

    @staticmethod
    def _atomic_write_bytes(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)

    @classmethod
    def _atomic_write_json(cls, path: Path, value: Mapping[str, Any]) -> None:
        cls._atomic_write_bytes(
            path,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )

    @staticmethod
    def _safe_file_name(value: str) -> bool:
        return (
            isinstance(value, str)
            and value not in {".", ".."}
            and bool(_FILE_NAME_RE.fullmatch(value))
        )

    @classmethod
    def _safe_media_name(cls, value: str) -> str:
        if not cls._safe_file_name(value) or Path(value).suffix.lower() not in _MEDIA_SUFFIXES:
            raise ValueError("图片文件名或扩展名不受支持")
        return value

    def _safe_path(self, draft_id: str) -> Path:
        if not _DRAFT_ID_RE.fullmatch(draft_id):
            raise ValueError("draft_id 不是安全标识")
        path = self.root / draft_id
        if path.is_symlink():
            raise ValueError("Draft 目录不允许是符号链接")
        try:
            resolved = path.resolve(strict=True)
            root = self.root.resolve()
        except OSError as exc:
            raise ValueError("Draft 不存在") from exc
        if not resolved.is_relative_to(root) or not resolved.is_dir():
            raise ValueError("Draft 路径无效")
        return resolved

    @staticmethod
    def _inside(root: Path, relative: Path) -> Path:
        if relative.is_absolute() or len(relative.parts) == 0 or ".." in relative.parts:
            raise ValueError("Draft 相对路径无效")
        candidate = root / relative
        if candidate.is_symlink():
            raise ValueError("Draft 文件不允许是符号链接")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root.resolve()):
            raise ValueError("Draft 路径越界")
        return resolved

    def _remove_draft_path(self, path: Path) -> None:
        if path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(self.root.resolve()):
            shutil.rmtree(path)
