"""内部结构化 Reply / Analysis Evaluation Adapter。

该模块只接受已经通过本地 Case 校验的 ``dating.transcript.v1``，不会上传截图或执行 OCR。
所有服务名和方法名都由任务类型固定映射，数据集无法覆盖 model、Prompt、app_id、user_id
或任意 RPC 方法，从边界上保证评测工具只使用后端开放的测试权限。
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from aidating_eval.domain import (
    CaseDefinition,
    CleanupResult,
    DoctorCheck,
    DoctorStatus,
    EvaluationAnalysisCase,
    EvaluationReplyCase,
    NegativeVariant,
    PollPolicy,
    PreparedCase,
    RunContext,
    RunMode,
    TaskKind,
    TaskSnapshot,
    TaskStatus,
)
from aidating_eval.errors import (
    BusinessError,
    ContractError,
    DatingEvalError,
    TransportError,
)
from aidating_eval.scheduling import EvaluationRequestGate


class EvaluationGateway(Protocol):
    """EvaluationGatewayClient 与测试 Fake 共同满足的最小端口。"""

    def call(
        self,
        method_name: str,
        params: Mapping[str, Any],
        *,
        client_request_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EvaluationMethods:
    create: str
    get_task: str
    get_result: str
    delete: str
    task_type: str
    schema_version: str
    create_reason: str


EVALUATION_METHODS = {
    TaskKind.REPLY: EvaluationMethods(
        create="CreateReplyEvaluationTask",
        get_task="GetReplyEvaluationTask",
        get_result="GetReplyEvaluationResult",
        delete="DeleteReplyEvaluationTaskData",
        task_type="reply_generation",
        schema_version="dating.reply_generation.v1",
        create_reason="automated Reply evaluation",
    ),
    TaskKind.ANALYSIS: EvaluationMethods(
        create="CreateAnalysisEvaluationTask",
        get_task="GetAnalysisEvaluationTask",
        get_result="GetAnalysisEvaluationResult",
        delete="DeleteAnalysisEvaluationTaskData",
        task_type="relationship_analysis",
        schema_version="dating.relationship_analysis.v1",
        create_reason="automated Analysis evaluation",
    ),
}


KNOWN_BUSINESS_CODES = frozenset(
    {
        "UNAUTHENTICATED",
        "PERMISSION_DENIED",
        "FEATURE_NOT_READY",
        "INPUT_INVALID",
        "IDEMPOTENCY_CONFLICT",
        "EVALUATION_LIMIT_EXCEEDED",
        "TASK_NOT_READY",
        "NOT_FOUND",
        "NO_VALID_CONVERSATION",
        "INSUFFICIENT_MESSAGES",
        "MODEL_OUTPUT_INVALID",
        "INTERNAL",
    }
)

DIAGNOSTIC_FIELDS = frozenset(
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
)


class InternalEvaluationAdapter:
    """执行结构化 Evaluation Task 的完整生命周期。"""

    poll_policy = PollPolicy(240, 3, 3)

    def __init__(
        self,
        *,
        gateway: EvaluationGateway,
        request_gate: EvaluationRequestGate,
    ) -> None:
        self.gateway = gateway
        self.request_gate = request_gate

    @classmethod
    def for_test(
        cls, *, gateway: EvaluationGateway
    ) -> "InternalEvaluationAdapter":
        """构造无真实 sleep 的协议测试实例。"""

        return cls(gateway=gateway, request_gate=EvaluationRequestGate.disabled())

    @staticmethod
    def _methods(context: RunContext) -> EvaluationMethods:
        if context.mode is not RunMode.EVAL:
            raise ContractError("INTERNAL_ADAPTER_REQUIRES_EVAL_MODE")
        try:
            return EVALUATION_METHODS[context.task_kind]
        except KeyError as exc:
            raise ContractError("INTERNAL_TASK_KIND_UNSUPPORTED") from exc

    @staticmethod
    def _assert_case_matches_context(
        case: CaseDefinition, context: RunContext
    ) -> None:
        if not isinstance(case, (EvaluationReplyCase, EvaluationAnalysisCase)):
            raise ContractError("INTERNAL_CASE_TYPE_INVALID")
        if case.task_kind is not context.task_kind:
            raise ContractError("CASE_CONTEXT_TASK_KIND_MISMATCH")

    def prepare_run(self, context: RunContext) -> None:
        """内部模式没有用户 Session；这里只验证模式，不产生外部副作用。"""

        self._methods(context)

    def prepare_case(
        self, case: CaseDefinition, context: RunContext
    ) -> PreparedCase:
        self._assert_case_matches_context(case, context)
        messages = [
            {
                "message_id": message.message_id,
                "message_type": "text",
                # Loader 已完成 self→user；这里再做一次封装层归一化，保护手工构造
                # Case 或未来其他调用方不会把 self 泄漏到后端协议。
                "speaker": "user" if message.speaker == "self" else message.speaker,
                "text": message.text,
            }
            for message in case.messages
        ]
        return PreparedCase(
            {"messages": messages},
            {
                "message_count": len(messages),
                "text_bytes": case.text_bytes,
                "negative_variant": case.negative_variant,
            },
        )

    def _call(
        self,
        method_name: str,
        params: Mapping[str, Any],
        *,
        client_request_id: str | None = None,
        reason: str | None = None,
        is_create: bool = False,
        retry_transport_once: bool = False,
        validate_business_code: bool = True,
    ) -> dict[str, Any]:
        """执行一个受共享节奏控制的 Admin Gateway 请求。

        限流与网络结果未知都最多各重试一次。Create 始终复用相同幂等键，其他方法
        始终复用同一 Task ID；Gateway Client 本身不做静默重试。
        """

        limit_retried = False
        transport_retried = False
        while True:
            self.request_gate.before_request(is_create=is_create)
            try:
                return self.gateway.call(
                    method_name,
                    params,
                    client_request_id=client_request_id,
                    reason=reason,
                )
            except BusinessError as exc:
                if validate_business_code and exc.code not in KNOWN_BUSINESS_CODES:
                    converted = ContractError("UNKNOWN_BUSINESS_ERROR_CODE")
                    converted.add_cleanup_task_ids(
                        *getattr(exc, "task_ids_to_cleanup", ())
                    )
                    raise converted from exc
                if exc.code == "EVALUATION_LIMIT_EXCEEDED":
                    self.request_gate.cooldown.defer(exc.retry_after_seconds)
                    if not limit_retried:
                        limit_retried = True
                        continue
                raise
            except TransportError:
                if retry_transport_once and not transport_retried:
                    transport_retried = True
                    continue
                raise

    @staticmethod
    def _base_params(
        case: CaseDefinition,
        prepared: PreparedCase,
        context: RunContext,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "case_id": case.case_id,
            "run_id": context.run_id,
            "client_request_id": context.attempt_id,
            "locale": case.locale,
            "transcript": {
                "schema_version": "dating.transcript.v1",
                "messages": deepcopy(prepared.payload["messages"]),
            },
        }
        if isinstance(case, EvaluationReplyCase):
            params["dating_goal"] = case.dating_goal
            params["your_voice"] = case.your_voice
            if case.requested_intent is not None:
                params["requested_intent"] = case.requested_intent
            if case.background is not None:
                params["background"] = case.background
        return params

    @staticmethod
    def _apply_negative_variant(
        params: dict[str, Any], variant: NegativeVariant | None
    ) -> None:
        """只在最终 Wire Payload 上应用封闭枚举变体，永不接受任意路径覆盖。"""

        if variant is None or variant in {
            NegativeVariant.IDEMPOTENCY_SAME,
            NegativeVariant.IDEMPOTENCY_CONFLICT,
        }:
            return
        messages = params["transcript"]["messages"]
        if variant is NegativeVariant.MESSAGE_COUNT_BELOW_MIN:
            params["transcript"]["messages"] = messages[:3]
        elif variant is NegativeVariant.INSUFFICIENT_PARTY_MESSAGES:
            for index, message in enumerate(messages):
                message["speaker"] = "user" if index == 0 else "other"
        elif variant is NegativeVariant.DUPLICATE_MESSAGE_ID:
            messages[1]["message_id"] = messages[0]["message_id"]
        elif variant is NegativeVariant.UNSUPPORTED_FIELD:
            params["unsupported_evaluation_field"] = True
        else:  # 枚举扩展若未同步实现，应在发送请求前显式失败。
            raise ContractError("NEGATIVE_VARIANT_NOT_IMPLEMENTED")

    def create_task(
        self,
        case: CaseDefinition,
        prepared: PreparedCase,
        context: RunContext,
    ) -> TaskSnapshot:
        self._assert_case_matches_context(case, context)
        methods = self._methods(context)
        params = self._base_params(case, prepared, context)
        self._apply_negative_variant(params, case.negative_variant)

        first = self._create_once(methods, params, context)
        if case.negative_variant is NegativeVariant.IDEMPOTENCY_SAME:
            try:
                second = self._create_once(methods, deepcopy(params), context)
            except DatingEvalError as exc:
                exc.prepend_cleanup_task_ids(first.task_id)
                raise
            if second.task_id != first.task_id:
                raise BusinessError(
                    "IDEMPOTENCY_SAME_TASK_MISMATCH",
                    task_ids_to_cleanup=(first.task_id, second.task_id),
                )
            return first

        if case.negative_variant is NegativeVariant.IDEMPOTENCY_CONFLICT:
            conflicting = deepcopy(params)
            conflicting["transcript"]["messages"][0]["text"] += " [conflict]"
            try:
                second = self._create_once(methods, conflicting, context)
            except DatingEvalError as exc:
                exc.prepend_cleanup_task_ids(first.task_id)
                raise
            raise BusinessError(
                "IDEMPOTENCY_CONFLICT_NOT_OBSERVED",
                task_ids_to_cleanup=(first.task_id, second.task_id),
            )
        return first

    def _create_once(
        self,
        methods: EvaluationMethods,
        params: Mapping[str, Any],
        context: RunContext,
    ) -> TaskSnapshot:
        data = self._call(
            methods.create,
            params,
            client_request_id=context.attempt_id,
            reason=methods.create_reason,
            is_create=True,
            retry_transport_once=True,
        )
        observed_task_id = data.get("task_id")
        try:
            snapshot = self._task_snapshot(data, methods)
        except ContractError as exc:
            if isinstance(observed_task_id, str) and observed_task_id:
                exc.add_cleanup_task_ids(observed_task_id)
            raise
        if snapshot.status is not TaskStatus.QUEUED:
            raise ContractError(
                "EVALUATION_CREATE_STATUS_NOT_QUEUED"
            ).add_cleanup_task_ids(snapshot.task_id)
        return snapshot

    @staticmethod
    def _task_snapshot(
        data: Mapping[str, Any], methods: EvaluationMethods
    ) -> TaskSnapshot:
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ContractError("EVALUATION_TASK_ID_INVALID")
        if data.get("task_type") != methods.task_type:
            raise ContractError("EVALUATION_TASK_TYPE_MISMATCH")
        try:
            status = TaskStatus(data.get("status"))
        except (TypeError, ValueError) as exc:
            raise ContractError("EVALUATION_TASK_STATUS_UNKNOWN") from exc
        phase = data.get("phase", "")
        if not isinstance(phase, str):
            raise ContractError("EVALUATION_TASK_PHASE_INVALID")
        retryable = data.get("retryable", False)
        if not isinstance(retryable, bool):
            raise ContractError("EVALUATION_TASK_RETRYABLE_INVALID")
        error_code = data.get("error_code") or None
        if error_code is not None and not isinstance(error_code, str):
            raise ContractError("EVALUATION_TASK_ERROR_CODE_INVALID")
        return TaskSnapshot(
            task_id,
            methods.task_type,
            status,
            phase,
            retryable,
            error_code,
            dict(data),
        )

    def get_task(self, task_id: str, context: RunContext) -> TaskSnapshot:
        methods = self._methods(context)
        data = self._call(methods.get_task, {"task_id": task_id})
        return self._task_snapshot(data, methods)

    def get_result(
        self,
        task_id: str,
        case: CaseDefinition,
        context: RunContext,
    ) -> Mapping[str, Any]:
        self._assert_case_matches_context(case, context)
        methods = self._methods(context)
        data = self._call(methods.get_result, {"task_id": task_id})
        if case.expect.result_schema != methods.schema_version:
            raise ContractError("CASE_RESULT_SCHEMA_MISMATCH")

        # 后端部署说明把 ``responses[0].data`` 定义为成功 Schema 本体；部分正式 Result
        # 实现还会像 Public API 一样增加 task 元数据和 ``result`` 外层。内部 Adapter 兼容
        # 这两种已文档化形态，但不会把 Public 的方法名或其他字段假设带进来。
        nested = data.get("result")
        if nested is None:
            result = data
            normalized_data: dict[str, Any] = {
                "schema_version": methods.schema_version,
                "result": dict(data),
            }
        elif isinstance(nested, dict):
            task_type = data.get("task_type")
            if task_type is not None and task_type != methods.task_type:
                raise ContractError("EVALUATION_RESULT_TASK_TYPE_MISMATCH")
            result = nested
            normalized_data = dict(data)
        else:
            raise ContractError("EVALUATION_RESULT_BODY_INVALID")
        if data.get("schema_version") != methods.schema_version:
            raise ContractError("EVALUATION_RESULT_SCHEMA_MISMATCH")
        if result.get("schema_version", methods.schema_version) != methods.schema_version:
            raise ContractError("EVALUATION_INNER_RESULT_SCHEMA_MISMATCH")
        if context.task_kind is TaskKind.REPLY:
            self._validate_reply_result(result, case)
        else:
            self._validate_analysis_result(result, case)
        # 始终归一化为带 ``result`` 的外层，使 Artifact Redactor 能整体移除生成正文，
        # 同时保留 schema_version 供 Runner 做确定性判断。
        return normalized_data

    @staticmethod
    def _warning_codes(result: Mapping[str, Any]) -> set[str]:
        warnings = result.get("warnings", [])
        if not isinstance(warnings, list):
            raise ContractError("WARNINGS_INVALID")
        codes: set[str] = set()
        for warning in warnings:
            if isinstance(warning, str) and warning:
                codes.add(warning)
            elif isinstance(warning, dict):
                code = warning.get("code") or warning.get("warning_code")
                if not isinstance(code, str) or not code:
                    raise ContractError("WARNING_CODE_INVALID")
                codes.add(code)
            else:
                raise ContractError("WARNING_ENTRY_INVALID")
        return codes

    @staticmethod
    def _validate_candidate(candidate: object) -> None:
        if not isinstance(candidate, dict):
            raise ContractError("REPLY_CANDIDATE_INVALID")
        if not isinstance(candidate.get("reply_id"), str) or not isinstance(
            candidate.get("text"), str
        ):
            raise ContractError("REPLY_CANDIDATE_FIELDS_INVALID")

    def _validate_reply_result(
        self, result: Mapping[str, Any], case: CaseDefinition
    ) -> None:
        if not isinstance(result.get("whats_happening"), dict):
            raise ContractError("REPLY_WHATS_HAPPENING_INVALID")
        roles = result.get("roles")
        if not isinstance(roles, list) or not 1 <= len(roles) <= 2:
            raise ContractError("REPLY_ROLE_COUNT_INVALID")
        ranks: list[int] = []
        best_count = 0
        for role in roles:
            if not isinstance(role, dict):
                raise ContractError("REPLY_ROLE_INVALID")
            rank = role.get("rank")
            if not isinstance(rank, int) or isinstance(rank, bool):
                raise ContractError("REPLY_ROLE_RANK_INVALID")
            ranks.append(rank)
            best_count += role.get("is_best_fit") is True
            self._validate_candidate(role.get("top_pick"))
            alternatives = role.get("alternatives")
            if not isinstance(alternatives, list) or len(alternatives) != 3:
                raise ContractError("REPLY_ALTERNATIVE_COUNT_INVALID")
            for candidate in alternatives:
                self._validate_candidate(candidate)
        if ranks != list(range(1, len(roles) + 1)) or len(set(ranks)) != len(ranks):
            raise ContractError("REPLY_ROLE_RANK_INVALID")
        if best_count != 1:
            raise ContractError("REPLY_BEST_FIT_COUNT_INVALID")
        warning_codes = self._warning_codes(result)
        if not set(case.expect.warning_codes).issubset(warning_codes):
            raise ContractError("EXPECTED_WARNING_MISSING")

    def _validate_analysis_result(
        self, result: Mapping[str, Any], case: CaseDefinition
    ) -> None:
        if not isinstance(case, EvaluationAnalysisCase):
            raise ContractError("ANALYSIS_CASE_TYPE_INVALID")
        for field in ("overview", "chat_signals", "key_events"):
            if not isinstance(result.get(field), dict):
                raise ContractError(f"ANALYSIS_{field.upper()}_INVALID")
        warning_codes = self._warning_codes(result)
        if not set(case.expect.warning_codes).issubset(warning_codes):
            raise ContractError("EXPECTED_WARNING_MISSING")

        if len(case.messages) > 300:
            scope = result.get("analysis_scope")
            if not isinstance(scope, dict) or (
                scope.get("truncated_to_recent_300") is not True
                or scope.get("analyzed_message_count") != 300
            ):
                raise ContractError("ANALYSIS_TRUNCATION_SCOPE_INVALID")
            if "TRUNCATED_TO_RECENT_300" not in warning_codes:
                raise ContractError("ANALYSIS_TRUNCATION_WARNING_MISSING")
            allowed_ids = {message.message_id for message in case.messages[-300:]}
            evidence_ids = self._collect_evidence_message_ids(result)
            if not evidence_ids.issubset(allowed_ids):
                raise ContractError("ANALYSIS_EVIDENCE_OUT_OF_SCOPE")

    @classmethod
    def _collect_evidence_message_ids(cls, value: object) -> set[str]:
        """递归收集所有 evidence_message_ids，并拒绝模糊或非字符串形态。"""

        found: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence_message_ids":
                    if not isinstance(child, list) or not all(
                        isinstance(item, str) and item for item in child
                    ):
                        raise ContractError("ANALYSIS_EVIDENCE_IDS_INVALID")
                    found.update(child)
                else:
                    found.update(cls._collect_evidence_message_ids(child))
        elif isinstance(value, list):
            for child in value:
                found.update(cls._collect_evidence_message_ids(child))
        return found

    def get_diagnostics(
        self,
        task_id: str,
        case: CaseDefinition,
        context: RunContext,
    ) -> Mapping[str, Any]:
        self._assert_case_matches_context(case, context)
        data = self._call("GetEvaluationDiagnostics", {"task_id": task_id})
        filtered = {key: data[key] for key in DIAGNOSTIC_FIELDS if key in data}
        if filtered.get("case_id") != case.case_id:
            raise ContractError("DIAGNOSTIC_CASE_ID_MISMATCH")
        if filtered.get("run_id") != context.run_id:
            raise ContractError("DIAGNOSTIC_RUN_ID_MISMATCH")
        for field in (
            "model_alias",
            "prompt_version",
            "policy_version",
            "result_schema_version",
        ):
            value = filtered.get(field)
            if value is not None and not isinstance(value, str):
                raise ContractError("DIAGNOSTIC_FIELD_INVALID")
        schema_version = filtered.get("result_schema_version")
        if schema_version is not None and schema_version != case.expect.result_schema:
            raise ContractError("DIAGNOSTIC_RESULT_SCHEMA_MISMATCH")
        for field in ("retry_count", "input_tokens", "output_tokens"):
            value = filtered.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ContractError("DIAGNOSTIC_FIELD_INVALID")
        latency = filtered.get("model_latency_ms")
        if latency is not None and (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or latency < 0
        ):
            raise ContractError("DIAGNOSTIC_FIELD_INVALID")
        policy_codes = filtered.get("policy_codes", [])
        if not isinstance(policy_codes, list) or not all(
            isinstance(code, str) and code for code in policy_codes
        ):
            raise ContractError("DIAGNOSTIC_POLICY_CODES_INVALID")
        if not set(case.expect.policy_codes).issubset(set(policy_codes)):
            raise ContractError("EXPECTED_POLICY_CODE_MISSING")
        validation_codes = filtered.get("validation_codes")
        if validation_codes is not None and (
            not isinstance(validation_codes, list)
            or not all(isinstance(code, str) and code for code in validation_codes)
        ):
            raise ContractError("DIAGNOSTIC_VALIDATION_CODES_INVALID")
        return filtered

    def delete_task(self, task_id: str, context: RunContext) -> CleanupResult:
        methods = self._methods(context)
        try:
            data = self._call(
                methods.delete,
                {"task_id": task_id},
                reason="evaluation case completed",
                retry_transport_once=True,
            )
        except BusinessError as exc:
            if exc.code == "NOT_FOUND":
                return CleanupResult(True, "already_absent", {"task_id": task_id})
            raise
        return CleanupResult(True, "deleted", dict(data))

    def verify_deleted(self, task_id: str, context: RunContext) -> None:
        """供删除契约测试显式验证 Task、Result、Diagnostics 均已不可访问。"""

        methods = self._methods(context)
        for method in (methods.get_task, methods.get_result, "GetEvaluationDiagnostics"):
            try:
                self._call(method, {"task_id": task_id})
            except BusinessError as exc:
                if exc.code == "NOT_FOUND":
                    continue
                raise
            raise ContractError("EVALUATION_DELETE_ACCESS_STILL_AVAILABLE")

    def doctor(self) -> list[DoctorCheck]:
        """只读探测 Reply/Analysis 查询权限；绝不通过 Create 验证权限。"""

        checks: list[DoctorCheck] = []
        probes = (
            ("eval_reply_access", TaskKind.REPLY, "dating_task_doctor_reply_000000000000"),
            ("eval_analysis_access", TaskKind.ANALYSIS, "dating_task_doctor_analysis_0000000000"),
        )
        for name, kind, task_id in probes:
            method = EVALUATION_METHODS[kind].get_task
            try:
                self._call(
                    method,
                    {"task_id": task_id},
                    validate_business_code=False,
                )
            except BusinessError as exc:
                if exc.code == "NOT_FOUND":
                    checks.append(DoctorCheck(name, DoctorStatus.PASS, "NOT_FOUND"))
                else:
                    checks.append(DoctorCheck(name, DoctorStatus.FAIL, exc.code))
            except (ContractError, TransportError) as exc:
                checks.append(
                    DoctorCheck(name, DoctorStatus.FAIL, str(exc) or type(exc).__name__)
                )
            else:
                checks.append(
                    DoctorCheck(name, DoctorStatus.FAIL, "PROBE_TASK_UNEXPECTEDLY_EXISTS")
                )
        return checks
