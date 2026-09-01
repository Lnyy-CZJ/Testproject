"""测试专用 Fake；不包含任何 staging 地址或真实凭据。"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from threading import Lock
from typing import Any

from PIL import Image

from aidating_eval.domain import (
    CleanupResult,
    EvaluationAnalysisCase,
    PollPolicy,
    PreparedCase,
    RunContext,
    RunMode,
    TaskKind,
    TaskSnapshot,
    TranscriptMessage,
)


@dataclass(frozen=True)
class RecordedHttpCall:
    method: str
    url: str
    headers: dict[str, str]
    json_body: dict[str, Any] | None = None
    content: bytes | None = None


class FakeTransport:
    """记录调用并按顺序返回完整协议 Fixture。"""

    def __init__(self, responses: list[object] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[RecordedHttpCall] = []

    def _next(self) -> Any:
        if not self.responses:
            raise AssertionError("FakeTransport 没有剩余响应")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_status(self, url: str) -> int:
        self.calls.append(RecordedHttpCall("GET", url, {}))
        return self._next()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.calls.append(
            RecordedHttpCall(method, url, dict(headers), json_body=json_body)
        )
        return self._next()

    def put_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
    ) -> int:
        self.calls.append(
            RecordedHttpCall("PUT", url, dict(headers), content=content)
        )
        return self._next()


@dataclass(frozen=True)
class RecordedGatewayCall:
    service_name: str
    method_name: str
    params: dict[str, Any]
    request_id: str
    access_token: str | None


class FakePublicGateway:
    """按预期方法顺序返回已经解开响应信封的数据。"""

    def __init__(self, script: list[tuple[str, object]]) -> None:
        self.script = list(script)
        self.calls: list[RecordedGatewayCall] = []

    def call(
        self,
        service_name: str,
        method_name: str,
        params: Mapping[str, Any],
        request_id: str,
        access_token: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            RecordedGatewayCall(
                service_name,
                method_name,
                dict(params),
                request_id,
                access_token,
            )
        )
        if not self.script:
            raise AssertionError(f"未配置 {method_name} 的 Fake 响应")
        expected_method, response = self.script.pop(0)
        if method_name != expected_method:
            raise AssertionError(
                f"方法顺序错误：期望 {expected_method}，实际 {method_name}"
            )
        if isinstance(response, BaseException):
            raise response
        if not isinstance(response, dict):
            raise AssertionError("Fake Gateway 响应必须为对象")
        return dict(response)


@dataclass(frozen=True)
class RecordedEvaluationCall:
    """内部 Evaluation Fake 记录的单次 RPC 元数据。"""

    method_name: str
    params: dict[str, Any]
    client_request_id: str | None
    reason: str | None


class FakeEvaluationGateway:
    """按方法顺序返回已解开 ``responses[0].data`` 的内部 Gateway Fake。"""

    def __init__(self, script: list[tuple[str, object]]) -> None:
        self.script = list(script)
        self.calls: list[RecordedEvaluationCall] = []

    def call(
        self,
        method_name: str,
        params: Mapping[str, Any],
        *,
        client_request_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            RecordedEvaluationCall(
                method_name,
                dict(params),
                client_request_id,
                reason,
            )
        )
        if not self.script:
            raise AssertionError(f"未配置 {method_name} 的 Evaluation Fake 响应")
        expected_method, response = self.script.pop(0)
        if method_name != expected_method:
            raise AssertionError(
                f"方法顺序错误：期望 {expected_method}，实际 {method_name}"
            )
        if isinstance(response, BaseException):
            raise response
        if not isinstance(response, dict):
            raise AssertionError("Evaluation Fake 响应必须为对象")
        return dict(response)


class FakeClock:
    """无需真实等待即可验证限流算法的单调时钟。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        value = max(0.0, float(seconds))
        self.sleeps.append(value)
        self.now += value


FIXTURE_ROOT = Path(__file__).parent / "fixtures"


def fixture_response(name: str, *, group: str) -> dict[str, Any]:
    """读取测试包装 Fixture，并只返回真实 Wire Response 部分。"""

    wrapper = json.loads(
        (FIXTURE_ROOT / group / name).read_text(encoding="utf-8")
    )
    if wrapper.get("source") not in {"documented", "staging_observed"}:
        raise AssertionError("Fixture 缺少可信 source 标签")
    response = wrapper.get("response")
    if not isinstance(response, dict):
        raise AssertionError("Fixture response 必须为对象")
    return deepcopy(response)


def _public_fixture(name: str, request_id: str) -> dict[str, Any]:
    response = fixture_response(name, group="public")
    response["responses"][0]["id"] = request_id
    return response


def build_public_fixture_adapter(kind: str):
    """构造经过真实 Gateway Client 的完整公开 Fake Integration 场景。"""

    from aidating_eval.adapters.public_e2e import PublicE2EAdapter
    from aidating_eval.config import Settings
    from aidating_eval.domain import (
        E2EAnalysisCase,
        E2EReplyCase,
        ReplyPreferences,
        RunContext,
        RunMode,
        TaskKind,
    )
    from aidating_eval.public_gateway import PublicGatewayClient

    task_kind = TaskKind(kind)
    attempt = f"fixture-{kind}-attempt"
    temporary = tempfile.TemporaryDirectory()
    image_path = Path(temporary.name) / "synthetic.png"
    Image.new("RGB", (80, 120), "white").save(image_path)
    size = image_path.stat().st_size

    responses = [
        _public_fixture("identity-create-success.json", "identity-create"),
        _public_fixture("identity-get-me-success.json", "identity-me"),
    ]
    if task_kind is TaskKind.REPLY:
        responses.extend(
            [
                _public_fixture("preferences-get-incomplete.json", f"{attempt}-preferences-get"),
                _public_fixture("preferences-update-success.json", "preferences-update-1"),
                _public_fixture("preferences-get-complete.json", f"{attempt}-preferences-get"),
                _public_fixture("not-found.json", f"{attempt}-reply-probe-1"),
                _public_fixture("not-found.json", f"{attempt}-reply-probe-2"),
            ]
        )
    responses.append(_public_fixture("media-config-success.json", f"{attempt}-media-config"))
    prepared = _public_fixture("media-prepare-success.json", "media-prepare-1")
    prepared["responses"][0]["data"]["size_bytes"] = size
    responses.extend(
        [
            prepared,
            204,
            _public_fixture("media-complete-success.json", f"{attempt}-media-complete-1"),
        ]
    )
    if task_kind is TaskKind.ANALYSIS:
        responses.append(
            _public_fixture("quota-observed-success.json", f"{attempt}-analysis-quota")
        )
        names = (
            "analysis-create-success.json",
            "analysis-task-processing.json",
            "analysis-task-succeeded.json",
            "analysis-result-success.json",
        )
    else:
        names = (
            "reply-create-success.json",
            "reply-task-processing.json",
            "reply-task-succeeded.json",
            "reply-result-success.json",
        )
    responses.extend(
        [
            _public_fixture(names[0], f"{attempt}-create"),
            _public_fixture(names[1], f"{attempt}-task"),
            _public_fixture(names[2], f"{attempt}-task"),
            _public_fixture(names[3], f"{attempt}-result"),
            _public_fixture("analysis-delete-success.json", f"{attempt}-delete"),
            _public_fixture("not-found.json", f"{attempt}-delete-check-1"),
            _public_fixture("not-found.json", f"{attempt}-delete-check-2"),
        ]
    )
    transport = FakeTransport(responses)
    settings = Settings(
        mode="e2e",
        public_gateway_url="https://gateway.test/invoke",
        public_health_url="https://gateway.test/healthz",
        device_id="fixture-device",
        e2e_fixture_root=Path(temporary.name),
        artifacts_root=Path(temporary.name) / "artifacts",
    )
    gateway = PublicGatewayClient(
        transport,
        settings.public_gateway_url,
        device_id="fixture-device",
        platform="ios",
        app_version="1.0.0",
        locale="en-US",
        timezone="UTC+08:00",
        country="CN",
        app_package="com.example.fixture",
    )
    adapter = PublicE2EAdapter(
        gateway=gateway,
        transport=transport,
        settings=settings,
        sleep_fn=lambda _: None,
    )
    # TemporaryDirectory 必须存活到 CaseRunner 读取图片之后。
    adapter._fixture_temporary_directory = temporary
    context = RunContext(
        "fixture-run", attempt, RunMode.E2E, task_kind
    )
    if task_kind is TaskKind.REPLY:
        case = E2EReplyCase(
            "fixture-reply-case",
            "en-US",
            (image_path,),
            ReplyPreferences("serious_relationship", "warm_direct"),
            "flirt",
            "Synthetic fixture.",
        )
    else:
        case = E2EAnalysisCase(
            "fixture-analysis-case",
            "en-US",
            (image_path,),
            "Maya",
            "Synthetic fixture.",
        )
    return adapter, case, context


class RoutedEvaluationGateway:
    """为混合并发集成测试按 Task ID 路由响应，避免依赖线程调用顺序。"""

    def __init__(self) -> None:
        self.calls: list[RecordedEvaluationCall] = []
        self._polls: dict[str, int] = {}
        self._task_context: dict[str, tuple[str, str]] = {}
        self._lock = Lock()

    def call(
        self,
        method_name: str,
        params: Mapping[str, Any],
        *,
        client_request_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.calls.append(
                RecordedEvaluationCall(
                    method_name, dict(params), client_request_id, reason
                )
            )
            if method_name.startswith("CreateReply"):
                self._task_context["fixture-reply-task"] = (
                    str(params["case_id"]),
                    str(params["run_id"]),
                )
                return {"task_id": "fixture-reply-task", "task_type": "reply_generation", "status": "queued", "phase": "queued"}
            if method_name.startswith("CreateAnalysis"):
                self._task_context["fixture-analysis-task"] = (
                    str(params["case_id"]),
                    str(params["run_id"]),
                )
                return {"task_id": "fixture-analysis-task", "task_type": "relationship_analysis", "status": "queued", "phase": "queued"}
            if method_name in {"GetReplyEvaluationTask", "GetAnalysisEvaluationTask"}:
                task_id = str(params["task_id"])
                count = self._polls.get(task_id, 0)
                self._polls[task_id] = count + 1
                task_type = "reply_generation" if "reply" in task_id else "relationship_analysis"
                return {"task_id": task_id, "task_type": task_type, "status": "processing" if count == 0 else "succeeded", "phase": "working" if count == 0 else "done"}
            if method_name == "GetReplyEvaluationResult":
                return fixture_response("reply-evaluation-result-success.json", group="evaluation")["responses"][0]["data"]
            if method_name == "GetAnalysisEvaluationResult":
                return fixture_response("analysis-evaluation-result-success.json", group="evaluation")["responses"][0]["data"]
            if method_name == "GetEvaluationDiagnostics":
                diagnostics = fixture_response("evaluation-diagnostics-success.json", group="evaluation")["responses"][0]["data"]
                diagnostics["case_id"], diagnostics["run_id"] = self._task_context[
                    str(params["task_id"])
                ]
                diagnostics["result_schema_version"] = (
                    "dating.reply_generation.v1"
                    if "reply" in str(params["task_id"])
                    else "dating.relationship_analysis.v1"
                )
                return diagnostics
            if method_name in {"DeleteReplyEvaluationTaskData", "DeleteAnalysisEvaluationTaskData"}:
                return {"task_id": params["task_id"], "deleted": True}
            raise AssertionError(f"未处理的 Evaluation 方法: {method_name}")


def build_internal_batch_fixture():
    """构造一个 Reply + Analysis 混合并发 Batch。"""

    from aidating_eval.adapters.internal_evaluation import InternalEvaluationAdapter
    from aidating_eval.domain import (
        EvaluationReplyCase,
        RunContext,
        RunMode,
    )
    from aidating_eval.runner import CaseRunner, RunControl
    from aidating_eval.scheduling import (
        BatchRunner,
        CreatePacer,
        EvaluationRequestGate,
    )

    analysis = FakeAdapter.case()
    reply = EvaluationReplyCase(
        "fixture-reply-case",
        "en-US",
        analysis.messages,
        "serious_relationship",
        "warm_direct",
    )
    object.__setattr__(analysis, "case_id", "fixture-analysis-case")
    cases = [reply, analysis]
    gateway = RoutedEvaluationGateway()
    adapter = InternalEvaluationAdapter(
        gateway=gateway,
        request_gate=EvaluationRequestGate.disabled(),
    )
    artifacts = MemoryArtifactStore()
    control = RunControl()
    batch = BatchRunner(
        lambda _: CaseRunner(
            adapter, artifacts, sleep_fn=lambda _: None, run_control=control
        ),
        max_workers=2,
        create_pacer=CreatePacer.disabled(),
        run_control=control,
    )
    return (
        batch,
        cases,
        lambda case: RunContext.for_case(
            "fixture-batch-run", case.case_id, RunMode.EVAL, case.task_kind
        ),
        gateway,
    )


def run_public_reply_staging_readiness() -> str:
    """执行不上传媒体的真实 Public Reply readiness，并返回稳定状态码。"""

    from aidating_eval.cli import build_adapter
    from aidating_eval.config import Settings
    from aidating_eval.domain import (
        E2EReplyCase,
        ReplyPreferences,
        RunContext,
        RunMode,
        TaskKind,
    )
    from aidating_eval.errors import BusinessError

    settings = Settings.from_env("e2e")
    adapter = build_adapter(settings)
    case = E2EReplyCase(
        "public-reply-readiness",
        settings.locale,
        (),
        ReplyPreferences("serious_relationship", "warm_direct"),
        None,
        None,
    )
    context = RunContext.for_case(
        "public-reply-readiness-run",
        case.case_id,
        RunMode.E2E,
        TaskKind.REPLY,
    )
    adapter.prepare_run(context)
    try:
        adapter.check_reply_readiness(case, context)
    except BusinessError as exc:
        return exc.code
    return "READY"

class MemoryArtifactStore:
    """保留 Runner 可观察副作用的内存 Artifact Store。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, Mapping[str, Any]]] = []
        self.payloads: dict[tuple[str, str], Mapping[str, Any]] = {}

    def append_event(
        self, case_id: str, event: str, data: Mapping[str, Any] | None = None
    ) -> None:
        self.events.append((case_id, event, dict(data or {})))

    def write_case_payload(
        self, case_id: str, filename: str, payload: Mapping[str, Any]
    ) -> None:
        self.payloads[(case_id, filename)] = dict(payload)


class FakeAdapter:
    """Runner 测试使用的状态驱动 Adapter。"""

    poll_policy = PollPolicy(10, 0, 0)

    def __init__(
        self,
        *,
        tasks: list[TaskSnapshot],
        result: Mapping[str, Any] | BaseException,
        diagnostics: Mapping[str, Any] | None | BaseException = None,
        cleanup: CleanupResult | BaseException = CleanupResult(True, "deleted"),
        create_error: BaseException | None = None,
        on_create: Callable[[], None] | None = None,
    ) -> None:
        self.tasks = list(tasks)
        self.result = result
        self.diagnostics = diagnostics
        self.cleanup = cleanup
        self.create_error = create_error
        self.on_create = on_create
        self.deleted_task_ids: list[str] = []
        self.calls: list[str] = []
        self.context_attempts: list[str] = []

    @staticmethod
    def case() -> EvaluationAnalysisCase:
        messages = tuple(
            TranscriptMessage(
                f"m{i + 1}",
                "text",
                "other" if i % 2 == 0 else "user",
                f"message {i + 1}",
            )
            for i in range(4)
        )
        return EvaluationAnalysisCase("case-1", "en-US", messages)

    @staticmethod
    def context() -> RunContext:
        return RunContext.for_case(
            "run-1", "case-1", RunMode.EVAL, TaskKind.ANALYSIS
        )

    @classmethod
    def succeeded_but_result_fails(cls) -> "FakeAdapter":
        from aidating_eval.errors import ContractError

        return cls(
            tasks=[
                TaskSnapshot(
                    "task-1", "relationship_analysis", "succeeded", "done"
                )
            ],
            result=ContractError("RESULT_INVALID"),
            diagnostics={"model_alias": "safe"},
        )

    @classmethod
    def succeeded_but_delete_fails(cls) -> "FakeAdapter":
        from aidating_eval.errors import TransportError

        return cls(
            tasks=[
                TaskSnapshot(
                    "task-1", "relationship_analysis", "succeeded", "done"
                )
            ],
            result={"schema_version": "dating.relationship_analysis.v1"},
            cleanup=TransportError("HTTP_500"),
        )

    def doctor(self):
        return []

    def prepare_run(self, context: RunContext) -> None:
        self.calls.append("prepare_run")

    def prepare_case(self, case, context: RunContext) -> PreparedCase:
        self.calls.append("prepare_case")
        return PreparedCase({}, {"message_count": len(case.messages)})

    def create_task(self, case, prepared, context: RunContext) -> TaskSnapshot:
        self.calls.append("create_task")
        self.context_attempts.append(context.attempt_id)
        if self.create_error is not None:
            raise self.create_error
        if not self.tasks:
            raise AssertionError("FakeAdapter 没有 Create Task 响应")
        task = self.tasks.pop(0)
        if self.on_create:
            self.on_create()
        return task

    def get_task(self, task_id: str, context: RunContext) -> TaskSnapshot:
        self.calls.append("get_task")
        if not self.tasks:
            raise AssertionError("FakeAdapter 没有 Poll Task 响应")
        return self.tasks.pop(0)

    def get_result(self, task_id: str, case, context: RunContext):
        self.calls.append("get_result")
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def get_diagnostics(self, task_id: str, case, context: RunContext):
        self.calls.append("get_diagnostics")
        if isinstance(self.diagnostics, BaseException):
            raise self.diagnostics
        return self.diagnostics

    def delete_task(self, task_id: str, context: RunContext) -> CleanupResult:
        self.calls.append("delete_task")
        self.deleted_task_ids.append(task_id)
        if isinstance(self.cleanup, BaseException):
            raise self.cleanup
        return self.cleanup
