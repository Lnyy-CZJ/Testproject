"""Dating AI Assistant 双流程轻量 MVP 命令行入口。

CLI 只负责装配、输入选择、退出码和最小元数据输出。两套后端协议仍分别由 Public 与
Internal Adapter 持有；命令行不会打印聊天、模型结果、Token、API Key、图片路径或签名
URL。真实网络交换按用户显式选择写入本地原始 Wire Log，与安全摘要 Artifact 相互独立。
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Sequence
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import sys
from typing import Any

from dotenv import load_dotenv

from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
from aidating_eval.adapters.public_e2e import PublicE2EAdapter
from aidating_eval.application import (
    RunApplicationService,
    RunRequest,
    build_adapter as _application_build_adapter,
    load_and_validate as _application_load_and_validate,
    outcome_exit_code as _application_outcome_exit_code,
    select_case as _application_select_case,
)
from aidating_eval.artifacts import ArtifactStore, SAFE_NAME_RE
from aidating_eval.cases import load_cases
from aidating_eval.config import Settings
from aidating_eval.domain import (
    CaseDefinition,
    CaseOutcome,
    CaseOutcomeStatus,
    RunContext,
    RunMode,
    TaskKind,
    new_run_id,
)
from aidating_eval.errors import (
    BusinessError,
    CaseValidationError,
    ConfigurationError,
    ContractError,
    DatingEvalError,
    TransportError,
)
from aidating_eval.evaluation_gateway import EvaluationGatewayClient
from aidating_eval.http import RequestsTransport
from aidating_eval.media_validation import inspect_media
from aidating_eval.public_gateway import PublicGatewayClient
from aidating_eval.runner import CaseRunner, RunControl
from aidating_eval.scheduling import (
    BatchRunner,
    CreatePacer,
    EvaluationRequestGate,
    calculate_eval_budget,
)
from aidating_eval.wire_logging import RawWireLogger


EXIT_OK = 0
EXIT_CASE_FAILURE = 1
EXIT_CONFIG_OR_INPUT = 2
EXIT_AUTH_OR_ENV = 3
EXIT_INCOMPLETE_OR_CLEANUP = 4

AUTH_OR_ENV_CODES = frozenset(
    {"UNAUTHENTICATED", "PERMISSION_DENIED", "FEATURE_NOT_READY"}
)


class _ArgumentParser(argparse.ArgumentParser):
    """把 argparse 的进程退出转换成 ``main`` 可测试的稳定退出码。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self._print_message(f"{self.prog}: 参数错误\n", sys.stderr)
        raise SystemExit(EXIT_CONFIG_OR_INPUT)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="dating-eval")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "validate", "run"):
        command = subcommands.add_parser(name)
        command.add_argument("--mode", choices=("e2e", "eval"), required=True)
        if name in {"validate", "run"}:
            command.add_argument("--dataset", type=Path, required=True)
            command.add_argument("--case", dest="case_id")
    cleanup = subcommands.add_parser("cleanup")
    cleanup.add_argument("--run", dest="run_id", required=True)
    return parser


def build_adapter(
    settings: Settings,
    *,
    create_pacer: CreatePacer | None = None,
    wire_logger: RawWireLogger | None = None,
) -> PublicE2EAdapter | InternalEvaluationAdapter:
    """兼容旧 CLI 调用方的 Adapter 工厂；实际装配集中在 application 模块。"""

    return _application_build_adapter(
        settings,
        create_pacer=create_pacer,
        wire_logger=wire_logger,
    )


def _start_wire_log(
    command: str,
    *,
    mode: str | None = None,
    run_id: str | None = None,
) -> RawWireLogger:
    """为一次有网络行为的 CLI 调用创建原始日志。

    日志根目录可通过 ``AIDATING_LOG_ROOT`` 改到其他个人本地位置，默认严格使用用户约定
    的 ``logs``。日志事件保留所有凭据和正文，因此这里只输出文件路径，不回显任何内容。
    """

    root = Path(os.getenv("AIDATING_LOG_ROOT", "logs"))
    logger = RawWireLogger.create(root)
    logger.write(
        "log_started",
        command=command,
        mode=mode,
        run_id=run_id,
        warning="RAW_PRIVATE_DATA_NO_REDACTION",
    )
    return logger


class _WireLogContext:
    """让 cleanup 延迟创建日志，同时把 logger 暴露给 main 的统一异常处理。"""

    def __init__(self) -> None:
        self.logger: RawWireLogger | None = None

    def start(
        self,
        command: str,
        *,
        mode: str | None = None,
        run_id: str | None = None,
    ) -> RawWireLogger:
        """至多创建一次日志，并立即输出本次链路的定位路径。"""

        if self.logger is None:
            self.logger = _start_wire_log(command, mode=mode, run_id=run_id)
            print(f"LOG path={self.logger.path}")
        return self.logger


def _load_and_validate(
    mode: str, dataset: Path
) -> tuple[list[CaseDefinition], dict[str, Any]]:
    """兼容旧 CLI 的本地校验入口；实现集中在 application 模块。"""

    return _application_load_and_validate(mode, dataset)


def _select_case(
    cases: Sequence[CaseDefinition], case_id: str | None
) -> list[CaseDefinition]:
    return _application_select_case(cases, case_id)


def _doctor(mode: str, wire_logger: RawWireLogger) -> int:
    service = RunApplicationService(adapter_factory=build_adapter)
    checks = service.doctor(mode, wire_logger=wire_logger)
    for check in checks:
        print(f"{check.status} {check.name} {check.safe_message}")
    return (
        EXIT_AUTH_OR_ENV
        if any(check.status == "FAIL" for check in checks)
        else EXIT_OK
    )


def _validate(mode: str, dataset: Path, case_id: str | None) -> int:
    cases, totals = _load_and_validate(mode, dataset)
    selected = _select_case(cases, case_id)
    if mode == "eval":
        try:
            concurrency = int(os.getenv("AIDATING_EVAL_CONCURRENCY", "3"))
        except ValueError as exc:
            raise ConfigurationError(
                "AIDATING_EVAL_CONCURRENCY 必须为整数"
            ) from exc
        budget = calculate_eval_budget(selected, max_workers=concurrency)
        print(
            "VALID "
            f"mode=eval cases={len(selected)} messages={sum(len(c.messages) for c in selected)} "
            f"input_bytes={sum(c.text_bytes for c in selected)} "
            f"normal_create={budget.normal_create_requests} "
            f"worst_create={budget.worst_create_requests} concurrency={concurrency}"
        )
    else:
        selected_ids = {case.case_id for case in selected}
        for item in totals["media_items"]:
            if item["case_id"] in selected_ids:
                print(
                    f"MEDIA case={item['case_id']} index={item['index']} "
                    f"type={item['content_type']} bytes={item['size_bytes']}"
                )
        selected_media = sum(len(case.media_paths) for case in selected)
        print(
            f"VALID mode=e2e cases={len(selected)} media={selected_media} "
            f"validated_dataset_cases={totals['case_count']}"
        )
    return EXIT_OK


@contextmanager
def _signal_stop(control: RunControl):
    """把 SIGINT/SIGTERM 转成协作停止，让已知 Task 仍能进入 finally 删除。"""

    previous: dict[int, Any] = {}

    def request_stop(signum, frame) -> None:  # noqa: ARG001 - signal handler signature
        control.request_stop("SIGNAL_STOP_REQUESTED")

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _outcome_exit_code(outcomes: Sequence[CaseOutcome]) -> int:
    return _application_outcome_exit_code(outcomes)


def _print_outcomes(run_id: str, outcomes: Sequence[CaseOutcome]) -> None:
    """只输出允许的运行元数据，绝不展开 Result 或 Diagnostics。"""

    for outcome in outcomes:
        cleanup = outcome.cleanup.status if outcome.cleanup else "not_applicable"
        print(
            f"CASE run={run_id} case={outcome.case_id} "
            f"task={outcome.task_id or '-'} status={outcome.status} "
            f"error={outcome.business_error_code or '-'} cleanup={cleanup}"
        )
    counts = Counter(outcome.status for outcome in outcomes)
    print(
        f"RUN run={run_id} total={len(outcomes)} "
        f"completed={counts[CaseOutcomeStatus.COMPLETED]} "
        f"failed={counts[CaseOutcomeStatus.FAILED]} "
        f"incomplete={counts[CaseOutcomeStatus.INCOMPLETE]} "
        f"cleanup_pending={counts[CaseOutcomeStatus.CLEANUP_PENDING]}"
    )


def _run(
    mode: str,
    dataset: Path,
    case_id: str | None,
    wire_logger: RawWireLogger,
) -> int:
    request = RunRequest(
        mode=RunMode(mode),
        dataset_path=dataset,
        case_id=case_id,
    )
    service = RunApplicationService(adapter_factory=build_adapter)
    prepared = service.prepare(request, wire_logger=wire_logger)
    control = RunControl()
    with _signal_stop(control):
        result = service.execute(prepared, control=control)

    _print_outcomes(result.run_id, result.outcomes)
    return result.exit_code


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("运行产物不存在或损坏") from exc
    if not isinstance(value, dict):
        raise ConfigurationError("运行产物必须为 JSON 对象")
    return value


def _pending_internal_tasks(run_path: Path) -> list[dict[str, str]]:
    """从追加式事件中恢复尚无成功删除证据的内部 Task。"""

    state_path = run_path / "run-state.jsonl"
    try:
        lines = state_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError("run-state.jsonl 不存在或不可读") from exc
    tasks: dict[tuple[str, str], dict[str, str]] = {}
    cleaned: set[tuple[str, str]] = set()
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("run-state.jsonl 包含损坏记录") from exc
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            raise ConfigurationError("run-state.jsonl 记录结构无效")
        data = event["data"]
        attempt_id = data.get("attempt_id")
        task_id = data.get("task_id")
        if not isinstance(attempt_id, str) or not isinstance(task_id, str):
            continue
        key = (attempt_id, task_id)
        if event.get("event") in {"task_created", "task_observed"}:
            if data.get("mode") != "eval":
                raise ConfigurationError(
                    "run-state Task 模式与 Internal cleanup 不匹配"
                )
            kind = data.get("task_kind")
            case_id = event.get("case_id")
            if isinstance(kind, str) and isinstance(case_id, str):
                tasks[key] = {
                    "attempt_id": attempt_id,
                    "task_id": task_id,
                    "task_kind": kind,
                    "case_id": case_id,
                }
        elif event.get("event") in {
            "delete_succeeded",
            "delete_already_absent",
        }:
            cleaned.add(key)
    return [value for key, value in tasks.items() if key not in cleaned]


def _cleanup(run_id: str, wire_context: _WireLogContext) -> int:
    if not SAFE_NAME_RE.fullmatch(run_id):
        raise ConfigurationError("run_id 不是安全标识")
    artifacts_root = Path(os.getenv("AIDATING_ARTIFACTS_ROOT", "artifacts"))
    run_path = (artifacts_root / run_id).resolve()
    if not run_path.is_relative_to(artifacts_root.resolve()):
        raise ConfigurationError("run_id 越出 Artifact Root")
    manifest = _read_json_object(run_path / "manifest.json")
    if manifest.get("run_id") != run_id:
        raise ConfigurationError("manifest run_id 与目标目录不匹配")
    config = manifest.get("config")
    if not isinstance(config, dict) or config.get("mode") not in {"e2e", "eval"}:
        raise ConfigurationError("manifest 缺少可信 mode")
    if config["mode"] == "e2e":
        print("INCOMPLETE mode=e2e cleanup=requires_in_memory_public_token_or_ttl")
        return EXIT_INCOMPLETE_OR_CLEANUP

    pending = _pending_internal_tasks(run_path)
    if not pending:
        print(f"CLEANUP run={run_id} pending=0")
        return EXIT_OK
    wire_logger = wire_context.start(
        "cleanup",
        mode="eval",
        run_id=run_id,
    )
    settings = Settings.from_env("eval")
    adapter = build_adapter(settings, wire_logger=wire_logger)
    artifacts = ArtifactStore(artifacts_root, run_id)
    failures = 0
    for item in pending:
        try:
            kind = TaskKind(item["task_kind"])
        except ValueError as exc:
            raise ConfigurationError("run-state 包含未知 task_kind") from exc
        context = RunContext(
            run_id,
            item["attempt_id"],
            RunMode.EVAL,
            kind,
        )
        try:
            cleanup = adapter.delete_task(item["task_id"], context)
        except BusinessError as exc:
            if exc.code in AUTH_OR_ENV_CODES:
                return EXIT_AUTH_OR_ENV
            failures += 1
            continue
        except DatingEvalError:
            failures += 1
            continue
        event = (
            "delete_already_absent"
            if cleanup.status == "already_absent"
            else "delete_succeeded"
        )
        artifacts.append_event(
            item["case_id"],
            event,
            {
                "attempt_id": item["attempt_id"],
                "mode": RunMode.EVAL,
                "task_kind": kind,
                "task_id": item["task_id"],
            },
        )
    print(f"CLEANUP run={run_id} attempted={len(pending)} failed={failures}")
    return EXIT_INCOMPLETE_OR_CLEANUP if failures else EXIT_OK


def _safe_error_code(exc: BaseException) -> str:
    if isinstance(exc, BusinessError):
        return exc.code
    if isinstance(exc, (ContractError, TransportError)):
        return str(exc) or type(exc).__name__
    return type(exc).__name__


def _write_cli_event(
    wire_logger: RawWireLogger | None,
    event: str,
    **fields: Any,
) -> None:
    """记录 CLI 边界事件；自定义 logger 失败也不能改变既有退出码。"""

    if wire_logger is None:
        return
    try:
        wire_logger.write(event, **fields)
    except Exception:
        return


def _report_wire_log_status(wire_logger: RawWireLogger | None) -> None:
    """在日志降级时给出不含路径正文或凭据的控制台提示。"""

    if wire_logger is None:
        return
    try:
        failure_type = wire_logger.failure_type
    except Exception:
        return
    if failure_type:
        print(f"LOG status=degraded error={failure_type}")


def main(argv: Sequence[str] | None = None) -> int:
    """执行 CLI 并返回冻结退出码；Console Script 会把返回值交给 ``sys.exit``。"""

    load_dotenv(override=False)
    wire_context = _WireLogContext()
    try:
        args = build_parser().parse_args(list(argv) if argv is not None else None)
        if args.command in {"doctor", "run"}:
            wire_context.start(
                args.command,
                mode=args.mode,
            )
        if args.command == "doctor":
            wire_logger = wire_context.logger
            assert wire_logger is not None
            exit_code = _doctor(args.mode, wire_logger)
        elif args.command == "validate":
            exit_code = _validate(args.mode, args.dataset, args.case_id)
        elif args.command == "run":
            wire_logger = wire_context.logger
            assert wire_logger is not None
            exit_code = _run(
                args.mode,
                args.dataset,
                args.case_id,
                wire_logger,
            )
        elif args.command == "cleanup":
            exit_code = _cleanup(args.run_id, wire_context)
        else:
            raise ConfigurationError("未知命令")
        _write_cli_event(
            wire_context.logger,
            "cli_completed",
            exit_code=exit_code,
        )
        _report_wire_log_status(wire_context.logger)
        return exit_code
    except SystemExit as exc:
        return int(exc.code or 0)
    except (ConfigurationError, CaseValidationError) as exc:
        _write_cli_event(
            wire_context.logger,
            "cli_error",
            category="input",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        _report_wire_log_status(wire_context.logger)
        print(f"ERROR category=input code={type(exc).__name__}")
        return EXIT_CONFIG_OR_INPUT
    except BusinessError as exc:
        _write_cli_event(
            wire_context.logger,
            "cli_error",
            category="business",
            error_type=type(exc).__name__,
            business_error_code=exc.code,
            message=str(exc),
        )
        _report_wire_log_status(wire_context.logger)
        print(f"ERROR category=business code={exc.code}")
        return (
            EXIT_AUTH_OR_ENV if exc.code in AUTH_OR_ENV_CODES else EXIT_CASE_FAILURE
        )
    except (ContractError, TransportError) as exc:
        _write_cli_event(
            wire_context.logger,
            "cli_error",
            category="environment",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        _report_wire_log_status(wire_context.logger)
        print(f"ERROR category=environment code={_safe_error_code(exc)}")
        return EXIT_AUTH_OR_ENV
    except KeyboardInterrupt:
        _write_cli_event(
            wire_context.logger,
            "cli_error",
            category="interrupted",
            error_type="KeyboardInterrupt",
            message="KEYBOARD_INTERRUPT",
        )
        _report_wire_log_status(wire_context.logger)
        print("ERROR category=interrupted code=KEYBOARD_INTERRUPT")
        return EXIT_INCOMPLETE_OR_CLEANUP
    except Exception as exc:  # 最外层安全兜底，禁止 traceback 携带敏感上下文。
        _write_cli_event(
            wire_context.logger,
            "cli_error",
            category="internal",
            error_type=type(exc).__name__,
            message=str(exc),
        )
        _report_wire_log_status(wire_context.logger)
        print(f"ERROR category=internal code={type(exc).__name__}")
        return EXIT_CASE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
