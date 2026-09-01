"""公开截图 E2E Adapter。

该 Adapter 是唯一了解 Public Gateway 方法名、身份、偏好、媒体和结果结构的模块。Runner
只看到统一 TaskFlowAdapter，不会把 Analysis 的类型专属方法错误复用于 Reply。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Protocol
from urllib.parse import urlsplit

from aidating_eval.config import PUBLIC_GATEWAY_URL, PUBLIC_HEALTH_URL, Settings
from aidating_eval.domain import (
    CaseDefinition,
    CleanupResult,
    DoctorCheck,
    DoctorStatus,
    E2EAnalysisCase,
    E2EReplyCase,
    PollPolicy,
    PreparedCase,
    ReplyPreferences,
    RunContext,
    RunMode,
    SessionTokens,
    TaskKind,
    TaskSnapshot,
    TaskStatus,
)
from aidating_eval.errors import (
    BusinessError,
    CaseValidationError,
    ConfigurationError,
    ContractError,
    TransportError,
)
from aidating_eval.media_validation import inspect_media, validate_against_media_config


IDENTITY_SERVICE = "tool.identity.IdentityService"
ASSISTANT_SERVICE = "tool.dating.DatingAssistantService"
MEDIA_SERVICE = "tool.dating.DatingMediaService"
SUBSCRIPTION_SERVICE = "tool.subscription.SubscriptionService"


class PublicGateway(Protocol):
    def call(
        self,
        service_name: str,
        method_name: str,
        params: Mapping[str, Any],
        request_id: str,
        access_token: str | None,
    ) -> dict[str, Any]: ...


class MediaTransport(Protocol):
    def get_status(self, url: str) -> int: ...

    def put_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
    ) -> int: ...


class _UnavailableMediaTransport:
    """测试未提供媒体传输器时的安全占位实现。

    这个占位对象只允许测试身份、偏好和 readiness 等不涉及 COS 的逻辑；一旦测试
    意外进入媒体网络调用便立即失败，避免生产包反向依赖 ``tests`` 目录。
    """

    def get_status(self, url: str) -> int:
        raise AssertionError("本测试未配置媒体传输器，禁止执行 COS 探测")

    def put_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str],
        content: bytes,
    ) -> int:
        raise AssertionError("本测试未配置媒体传输器，禁止执行 COS 上传")


@dataclass(frozen=True)
class PublicTaskMethods:
    create: str
    get_task: str
    get_result: str
    task_type: str
    schema_version: str


PUBLIC_METHODS = {
    TaskKind.REPLY: PublicTaskMethods(
        create="CreateReplyTask",
        get_task="GetTask",
        get_result="GetTaskResult",
        task_type="reply_generation",
        schema_version="dating.reply_generation.v1",
    ),
    TaskKind.ANALYSIS: PublicTaskMethods(
        create="CreateAnalysisTask",
        get_task="GetAnalysisTask",
        get_result="GetAnalysisResult",
        task_type="relationship_analysis",
        schema_version="dating.relationship_analysis.v1",
    ),
}


class PublicE2EAdapter:
    """串行执行 Identity、Preferences、Media 与公开 AI Task。"""

    poll_policy = PollPolicy(90, 1, 2, 10)

    def __init__(
        self,
        *,
        gateway: PublicGateway,
        transport: MediaTransport,
        settings: Settings,
        sleep_fn=sleep,
        monotonic_fn=monotonic,
    ) -> None:
        self.gateway = gateway
        self.transport = transport
        self.settings = settings
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.session_tokens: SessionTokens | None = None
        self._automatic_refresh_used = False
        self._media_config: dict[str, Any] | None = None
        self._media_config_expires_at = 0.0

    @classmethod
    def for_test(
        cls,
        *,
        gateway: PublicGateway,
        transport: MediaTransport | None = None,
        authenticated: bool = False,
    ) -> "PublicE2EAdapter":
        """构造不访问网络的测试实例；真实代码不使用该快捷入口。"""

        if transport is None:
            transport = _UnavailableMediaTransport()
        settings = Settings(
            mode="e2e",
            public_gateway_url=PUBLIC_GATEWAY_URL,
            public_health_url=PUBLIC_HEALTH_URL,
            device_id="test-device",
            # 测试快捷入口可能使用系统临时目录；真实 CLI 永远使用 Settings 中的精确
            # Fixture Root，并在 upload_media 再做一次路径边界检查。
            e2e_fixture_root=Path("/"),
            artifacts_root=Path.cwd() / "artifacts",
        )
        adapter = cls(
            gateway=gateway,
            transport=transport,
            settings=settings,
            sleep_fn=lambda _: None,
        )
        if authenticated:
            adapter.session_tokens = SessionTokens(
                "test-user", "test-access", 1, "test-refresh", 2
            )
        return adapter

    @staticmethod
    def test_context(task_kind: str = "analysis") -> RunContext:
        return RunContext.for_case(
            "run-test",
            "case-test",
            RunMode.E2E,
            TaskKind(task_kind),
        )

    def _tokens(self) -> SessionTokens:
        if self.session_tokens is None:
            raise ConfigurationError("PUBLIC_SESSION_NOT_PREPARED")
        return self.session_tokens

    def doctor(self) -> list[DoctorCheck]:
        """执行无远端写入的公开环境检查。"""

        checks: list[DoctorCheck] = []
        try:
            health = self.transport.get_status(self.settings.public_health_url)
            checks.append(
                DoctorCheck(
                    "public_health",
                    DoctorStatus.PASS if health == 200 else DoctorStatus.FAIL,
                    "HTTP_200" if health == 200 else f"HTTP_{health}",
                )
            )
        except TransportError as exc:
            checks.append(
                DoctorCheck("public_health", DoctorStatus.FAIL, type(exc).__name__)
            )
        fixture_ok = self.settings.e2e_fixture_root.is_dir()
        checks.append(
            DoctorCheck(
                "fixture_root",
                DoctorStatus.PASS if fixture_ok else DoctorStatus.FAIL,
                "READABLE" if fixture_ok else "MISSING",
            )
        )
        try:
            self.settings.artifacts_root.mkdir(parents=True, exist_ok=True)
            self.settings.artifacts_root.chmod(0o700)
            artifact_status = DoctorStatus.PASS
            artifact_message = "PRIVATE_WRITABLE"
        except OSError:
            artifact_status = DoctorStatus.FAIL
            artifact_message = "NOT_WRITABLE"
        checks.append(
            DoctorCheck("artifacts", artifact_status, artifact_message)
        )
        checks.append(
            DoctorCheck("cos_connectivity", DoctorStatus.DEFERRED, "MEDIA_SMOKE_REQUIRED")
        )
        return checks

    def prepare_run(self, context: RunContext) -> None:
        # Adapter 可被测试复用；每个 Run 只允许一次自动 Refresh，防止失效凭据形成循环。
        self._automatic_refresh_used = False
        self.create_session()
        self.get_me()

    def create_session(self) -> SessionTokens:
        data = self.gateway.call(
            IDENTITY_SERVICE,
            "CreateAnonymousSession",
            {"consent_policy_version": self.settings.consent_policy_version},
            "identity-create",
            None,
        )
        tokens = self._parse_tokens(data)
        self.session_tokens = tokens
        return tokens

    def refresh_session(self) -> SessionTokens:
        old = self._tokens()
        data = self.gateway.call(
            IDENTITY_SERVICE,
            "RefreshSession",
            {"refresh_token": old.refresh_token},
            "identity-refresh",
            None,
        )
        replacement = self._parse_tokens(data)
        # 只有完整响应通过校验后才整体替换旧 Token 对。
        self.session_tokens = replacement
        self.get_me()
        return replacement

    def get_me(self) -> dict[str, Any]:
        tokens = self._tokens()
        data = self._authenticated_call(
            IDENTITY_SERVICE,
            "GetMe",
            {},
            "identity-me",
        )
        if data.get("user_id") != tokens.user_id:
            raise ContractError("PUBLIC_SESSION_USER_MISMATCH")
        return data

    @staticmethod
    def _parse_tokens(data: Mapping[str, Any]) -> SessionTokens:
        fields = (
            "user_id",
            "access_token",
            "expires_time",
            "refresh_token",
            "refresh_expires_time",
        )
        if not all(field in data for field in fields):
            raise ContractError("PUBLIC_SESSION_FIELDS_MISSING")
        if not all(isinstance(data[field], str) and data[field] for field in ("user_id", "access_token", "refresh_token")):
            raise ContractError("PUBLIC_SESSION_TOKEN_INVALID")
        if not all(
            isinstance(data[field], int) and not isinstance(data[field], bool)
            for field in ("expires_time", "refresh_expires_time")
        ):
            raise ContractError("PUBLIC_SESSION_EXPIRY_INVALID")
        return SessionTokens(
            data["user_id"],
            data["access_token"],
            data["expires_time"],
            data["refresh_token"],
            data["refresh_expires_time"],
        )

    def ensure_preferences(
        self,
        desired: ReplyPreferences,
        context: RunContext,
    ) -> None:
        """使用 version 乐观更新，并在冲突时只重新尝试一次。"""

        current = self._get_preferences(context)
        if self._preferences_match(current, desired):
            return
        for attempt in range(2):
            version = current.get("version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 0:
                raise ContractError("PREFERENCES_VERSION_INVALID")
            params = {
                "client_request_id": f"{context.attempt_id}-preferences",
                "dating_goal": desired.dating_goal,
                "your_voice": desired.your_voice,
                "expected_version": version,
            }
            try:
                self._call_with_unknown_network_retry(
                    ASSISTANT_SERVICE,
                    "UpdateUserPreferences",
                    params,
                    f"preferences-update-{attempt + 1}",
                )
            except BusinessError as exc:
                if exc.code != "PREFERENCES_VERSION_CONFLICT" or attempt == 1:
                    raise
                current = self._get_preferences(context)
                continue
            current = self._get_preferences(context)
            if not self._preferences_match(current, desired):
                raise ContractError("PREFERENCES_NOT_CONFIRMED")
            return
        raise ContractError("PREFERENCES_NOT_CONFIRMED")

    def _get_preferences(self, context: RunContext) -> dict[str, Any]:
        return self._authenticated_call(
            ASSISTANT_SERVICE,
            "GetUserPreferences",
            {},
            f"{context.attempt_id}-preferences-get",
        )

    @staticmethod
    def _preferences_match(
        current: Mapping[str, Any], desired: ReplyPreferences
    ) -> bool:
        return (
            current.get("preferences_complete") is True
            and current.get("dating_goal") == desired.dating_goal
            and current.get("your_voice") == desired.your_voice
        )

    def _authenticated_call(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any],
        request_id: str,
        *,
        retry_transport_once: bool = False,
    ) -> dict[str, Any]:
        """调用需要 Access Token 的 Public RPC。

        收到一次 ``UNAUTHENTICATED`` 时原子刷新 Token、重新校验身份，并以完全相同的
        request ID 和参数重试原请求。整个 Run 最多自动刷新一次；网络结果未知的重试
        独立计数，也始终复用原 request ID。
        """

        transport_retried = False
        while True:
            try:
                return self.gateway.call(
                    service,
                    method,
                    params,
                    request_id,
                    self._tokens().access_token,
                )
            except BusinessError as exc:
                if exc.code != "UNAUTHENTICATED" or self._automatic_refresh_used:
                    raise
                self._automatic_refresh_used = True
                self.refresh_session()
            except TransportError:
                if not retry_transport_once or transport_retried:
                    raise
                transport_retried = True

    def _call_with_unknown_network_retry(
        self,
        service: str,
        method: str,
        params: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        return self._authenticated_call(
            service,
            method,
            params,
            request_id,
            retry_transport_once=True,
        )

    def _check_reply_readiness(self, context: RunContext) -> None:
        sentinel = "dating_task_public_reply_probe"
        methods = PUBLIC_METHODS[TaskKind.REPLY]
        for index, method in enumerate((methods.get_task, methods.get_result), 1):
            try:
                self._authenticated_call(
                    ASSISTANT_SERVICE,
                    method,
                    {"task_id": sentinel},
                    f"{context.attempt_id}-reply-probe-{index}",
                )
            except BusinessError as exc:
                if exc.code == "NOT_FOUND":
                    continue
                raise
            raise ContractError("PUBLIC_REPLY_PROBE_UNEXPECTED_SUCCESS")

    def check_reply_readiness(
        self,
        case: E2EReplyCase,
        context: RunContext,
    ) -> None:
        """只检查 Reply Preferences 与 Task/Result 方法，不接触媒体或创建 Task。

        该入口专用于 staging 尚未开放完整 Public Reply 时的分层验收。调用方必须先执行
        ``prepare_run`` 建立内存 Session；即便后端已开放所有探测方法，本方法也会在
        readiness 完成后立即返回，不会因为“已就绪”而继续上传截图。
        """

        if context.mode is not RunMode.E2E or context.task_kind is not TaskKind.REPLY:
            raise ContractError("PUBLIC_REPLY_READINESS_CONTEXT_INVALID")
        if case.task_kind is not TaskKind.REPLY:
            raise ContractError("PUBLIC_REPLY_READINESS_CASE_INVALID")
        self.ensure_preferences(case.preferences, context)
        self._check_reply_readiness(context)

    def prepare_case(
        self,
        case: CaseDefinition,
        context: RunContext,
    ) -> PreparedCase:
        if context.task_kind != case.task_kind:
            raise ContractError("RUN_CONTEXT_TASK_KIND_MISMATCH")
        if isinstance(case, E2EReplyCase):
            self.ensure_preferences(case.preferences, context)
            self._check_reply_readiness(context)
            asset_ids = self.upload_media(case, context)
            return PreparedCase(
                {"asset_ids": asset_ids},
                {"asset_ids": list(asset_ids), "asset_count": len(asset_ids)},
            )
        if isinstance(case, E2EAnalysisCase):
            asset_ids = self.upload_media(case, context)
            quota = self._get_quota(context)
            return PreparedCase(
                {"asset_ids": asset_ids, "quota": quota},
                {
                    "asset_ids": list(asset_ids),
                    "asset_count": len(asset_ids),
                    "quota_checked": True,
                },
            )
        raise ContractError("PUBLIC_ADAPTER_REQUIRES_E2E_CASE")

    def _media_configuration(self, context: RunContext) -> dict[str, Any]:
        now = self.monotonic_fn()
        if self._media_config is not None and now < self._media_config_expires_at:
            return self._media_config
        config = self._authenticated_call(
            MEDIA_SERVICE,
            "GetMediaUploadConfig",
            {},
            f"{context.attempt_id}-media-config",
        )
        allowed = config.get("allowed_content_types")
        if not isinstance(allowed, list) or not allowed:
            raise ContractError("MEDIA_CONFIG_TYPES_INVALID")
        for field in ("min_asset_count", "max_asset_count", "max_size_bytes"):
            value = config.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ContractError(f"MEDIA_CONFIG_{field.upper()}_INVALID")
        ttl = config.get("config_cache_ttl_seconds", 0)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl < 0:
            raise ContractError("MEDIA_CONFIG_TTL_INVALID")
        self._media_config = dict(config)
        self._media_config_expires_at = now + float(ttl)
        return self._media_config

    def upload_media(
        self,
        case: E2EReplyCase | E2EAnalysisCase,
        context: RunContext,
    ) -> tuple[str, ...]:
        """按 Case 顺序逐张 Prepare、PUT、Complete，并返回未排序 asset IDs。"""

        fixture_root = self.settings.e2e_fixture_root.resolve()
        for path in case.media_paths:
            if not path.resolve().is_relative_to(fixture_root):
                raise CaseValidationError("媒体路径不得越出 Fixture Root")
        config = self._media_configuration(context)
        minimum = int(config["min_asset_count"])
        maximum = int(config["max_asset_count"])
        if not minimum <= len(case.media_paths) <= maximum:
            raise CaseValidationError("媒体数量不符合实时配置")

        asset_ids: list[str] = []
        for index, path in enumerate(case.media_paths, 1):
            media = inspect_media(path)
            validate_against_media_config(media, config)
            media_request_id = f"{context.attempt_id}-media-{index}"
            prepared = self._prepare_media(media, media_request_id, index)
            try:
                self.transport.put_bytes(
                    prepared["upload_url"],
                    headers=prepared["required_headers"],
                    content=media.content,
                )
            except TransportError as exc:
                if str(exc) not in {"HTTP_401", "HTTP_403", "HTTP_410"}:
                    raise
                prepared = self._prepare_media(media, media_request_id, index)
                self.transport.put_bytes(
                    prepared["upload_url"],
                    headers=prepared["required_headers"],
                    content=media.content,
                )
            self._complete_media(prepared["asset_id"], config, context, index)
            if prepared["asset_id"] in asset_ids:
                raise ContractError("DUPLICATE_ASSET_ID")
            asset_ids.append(prepared["asset_id"])
            # 下一轮开始前不再保留本张图片引用；原始 Fixture 始终未被修改。
            del media
        return tuple(asset_ids)

    def _prepare_media(
        self,
        media,
        client_request_id: str,
        index: int,
    ) -> dict[str, Any]:
        data = self._authenticated_call(
            MEDIA_SERVICE,
            "PrepareMediaUpload",
            {
                "client_request_id": client_request_id,
                "content_type": media.content_type,
                "size_bytes": media.size_bytes,
            },
            f"media-prepare-{index}",
        )
        asset_id = data.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            raise ContractError("MEDIA_ASSET_ID_INVALID")
        if data.get("content_type") != media.content_type or data.get("size_bytes") != media.size_bytes:
            raise ContractError("MEDIA_PREPARE_ECHO_MISMATCH")
        if data.get("upload_method") != "PUT":
            raise ContractError("MEDIA_UPLOAD_METHOD_NOT_PUT")
        maximum = data.get("max_size_bytes")
        if isinstance(maximum, bool) or not isinstance(maximum, int) or media.size_bytes > maximum:
            raise ContractError("MEDIA_PREPARE_SIZE_INVALID")
        upload_url = data.get("upload_url")
        if not isinstance(upload_url, str):
            raise ContractError("MEDIA_UPLOAD_URL_INVALID")
        parsed = urlsplit(upload_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ContractError("MEDIA_UPLOAD_URL_INVALID")
        if not parsed.query:
            raise ContractError("MEDIA_UPLOAD_URL_NOT_PRESIGNED")
        headers = data.get("required_headers")
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise ContractError("MEDIA_REQUIRED_HEADERS_INVALID")
        return {"asset_id": asset_id, "upload_url": upload_url, "required_headers": dict(headers)}

    def _complete_media(
        self,
        asset_id: str,
        config: Mapping[str, Any],
        context: RunContext,
        index: int,
    ) -> None:
        retry = config.get("complete_retry", {})
        if not isinstance(retry, dict):
            raise ContractError("MEDIA_COMPLETE_RETRY_INVALID")
        max_attempts = retry.get("max_attempts", 1)
        initial_ms = retry.get("initial_delay_ms", 0)
        max_ms = retry.get("max_delay_ms", initial_ms)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (max_attempts, initial_ms, max_ms)) or max_attempts < 1:
            raise ContractError("MEDIA_COMPLETE_RETRY_INVALID")
        for attempt in range(max_attempts):
            try:
                data = self._authenticated_call(
                    MEDIA_SERVICE,
                    "CompleteMediaUpload",
                    {"asset_id": asset_id},
                    f"{context.attempt_id}-media-complete-{index}",
                )
            except BusinessError as exc:
                if not exc.retryable or attempt + 1 >= max_attempts:
                    raise
                delay_ms = min(initial_ms * (2**attempt), max_ms)
                self.sleep_fn(delay_ms / 1000)
                continue
            if data.get("asset_id") != asset_id or data.get("status") != "uploaded":
                raise ContractError("MEDIA_COMPLETE_NOT_UPLOADED")
            return
        raise ContractError("MEDIA_COMPLETE_NOT_UPLOADED")

    def _get_quota(self, context: RunContext) -> dict[str, Any]:
        data = self._authenticated_call(
            SUBSCRIPTION_SERVICE,
            "GetQuotaStatus",
            {
                "product_code": "dating_assistant",
                "entitlement_code": "quota.dating.analysis.monthly",
            },
            f"{context.attempt_id}-analysis-quota",
        )
        remaining = data.get("remaining")
        if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
            if remaining <= 0 and data.get("unlimited") is not True:
                raise BusinessError("QUOTA_EXHAUSTED")
        return data

    def create_task(
        self,
        case: CaseDefinition,
        prepared: PreparedCase,
        context: RunContext,
    ) -> TaskSnapshot:
        methods = PUBLIC_METHODS[context.task_kind]
        asset_ids = prepared.payload.get("asset_ids")
        if not isinstance(asset_ids, tuple) or not asset_ids:
            raise ContractError("PREPARED_ASSET_IDS_INVALID")
        params: dict[str, Any] = {
            "client_request_id": context.attempt_id,
            "asset_ids": list(asset_ids),
            "locale": case.locale,
        }
        if isinstance(case, E2EReplyCase):
            if case.requested_intent is not None:
                params["requested_intent"] = case.requested_intent
            if case.background is not None:
                params["background"] = case.background
        elif isinstance(case, E2EAnalysisCase):
            if case.other_person_name is not None:
                params["other_person_name"] = case.other_person_name
            if case.background is not None:
                params["background"] = case.background
        else:
            raise ContractError("PUBLIC_ADAPTER_REQUIRES_E2E_CASE")
        data = self._call_with_unknown_network_retry(
            ASSISTANT_SERVICE,
            methods.create,
            params,
            f"{context.attempt_id}-create",
        )
        observed_task_id = data.get("task_id")
        try:
            snapshot = self._task_snapshot(data, methods)
        except ContractError as exc:
            if isinstance(observed_task_id, str) and observed_task_id:
                exc.add_cleanup_task_ids(observed_task_id)
            raise
        if snapshot.status is not TaskStatus.QUEUED:
            raise ContractError("PUBLIC_CREATE_STATUS_NOT_QUEUED").add_cleanup_task_ids(
                snapshot.task_id
            )
        return snapshot

    def get_task(self, task_id: str, context: RunContext) -> TaskSnapshot:
        methods = PUBLIC_METHODS[context.task_kind]
        data = self._authenticated_call(
            ASSISTANT_SERVICE,
            methods.get_task,
            {"task_id": task_id},
            f"{context.attempt_id}-task",
        )
        return self._task_snapshot(data, methods)

    @staticmethod
    def _task_snapshot(
        data: Mapping[str, Any], methods: PublicTaskMethods
    ) -> TaskSnapshot:
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ContractError("PUBLIC_TASK_ID_INVALID")
        if data.get("task_type") != methods.task_type:
            raise ContractError("PUBLIC_TASK_TYPE_MISMATCH")
        try:
            status = TaskStatus(data.get("status"))
        except (ValueError, TypeError) as exc:
            raise ContractError("PUBLIC_TASK_STATUS_UNKNOWN") from exc
        phase = data.get("phase", "")
        if not isinstance(phase, str):
            raise ContractError("PUBLIC_TASK_PHASE_INVALID")
        retryable = data.get("retryable", False)
        if not isinstance(retryable, bool):
            raise ContractError("PUBLIC_TASK_RETRYABLE_INVALID")
        error_code = data.get("error_code") or None
        if error_code is not None and not isinstance(error_code, str):
            raise ContractError("PUBLIC_TASK_ERROR_CODE_INVALID")
        return TaskSnapshot(
            task_id,
            methods.task_type,
            status,
            phase,
            retryable,
            error_code,
            dict(data),
        )

    def get_result(
        self,
        task_id: str,
        case: CaseDefinition,
        context: RunContext,
    ) -> Mapping[str, Any]:
        methods = PUBLIC_METHODS[context.task_kind]
        data = self._authenticated_call(
            ASSISTANT_SERVICE,
            methods.get_result,
            {"task_id": task_id},
            f"{context.attempt_id}-result",
        )
        if data.get("task_type") != methods.task_type:
            raise ContractError("PUBLIC_RESULT_TASK_TYPE_MISMATCH")
        if data.get("schema_version") != methods.schema_version:
            raise ContractError("PUBLIC_RESULT_SCHEMA_MISMATCH")
        if case.expect.result_schema != methods.schema_version:
            raise ContractError("CASE_RESULT_SCHEMA_MISMATCH")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ContractError("PUBLIC_RESULT_BODY_INVALID")
        if context.task_kind is TaskKind.REPLY:
            self._validate_reply_result(result, case)
        else:
            self._validate_analysis_result(result, case)
        return data

    @staticmethod
    def _warning_codes(result: Mapping[str, Any]) -> set[str]:
        warnings = result.get("warnings", [])
        if not isinstance(warnings, list):
            raise ContractError("WARNINGS_INVALID")
        codes: set[str] = set()
        for item in warnings:
            if isinstance(item, str):
                codes.add(item)
            elif isinstance(item, dict):
                code = item.get("code") or item.get("warning_code")
                if not isinstance(code, str):
                    raise ContractError("WARNING_CODE_INVALID")
                codes.add(code)
            else:
                raise ContractError("WARNING_ENTRY_INVALID")
        return codes

    def _validate_reply_result(
        self, result: Mapping[str, Any], case: CaseDefinition
    ) -> None:
        if not isinstance(result.get("whats_happening"), dict):
            raise ContractError("REPLY_WHATS_HAPPENING_INVALID")
        roles = result.get("roles")
        if not isinstance(roles, list) or not 1 <= len(roles) <= 2:
            raise ContractError("REPLY_ROLE_COUNT_INVALID")
        ranks: list[int] = []
        best = 0
        for role in roles:
            if not isinstance(role, dict):
                raise ContractError("REPLY_ROLE_INVALID")
            ranks.append(role.get("rank"))
            best += role.get("is_best_fit") is True
            self._validate_reply_candidate(role.get("top_pick"))
            alternatives = role.get("alternatives")
            if not isinstance(alternatives, list) or len(alternatives) != 3:
                raise ContractError("REPLY_ALTERNATIVE_COUNT_INVALID")
            for candidate in alternatives:
                self._validate_reply_candidate(candidate)
        if ranks != list(range(1, len(roles) + 1)) or len(set(ranks)) != len(ranks):
            raise ContractError("REPLY_ROLE_RANK_INVALID")
        if best != 1:
            raise ContractError("REPLY_BEST_FIT_COUNT_INVALID")
        codes = self._warning_codes(result)
        if not set(case.expect.warning_codes).issubset(codes):
            raise ContractError("EXPECTED_WARNING_MISSING")

    @staticmethod
    def _validate_reply_candidate(candidate: object) -> None:
        if not isinstance(candidate, dict):
            raise ContractError("REPLY_CANDIDATE_INVALID")
        if not isinstance(candidate.get("reply_id"), str) or not isinstance(
            candidate.get("text"), str
        ):
            raise ContractError("REPLY_CANDIDATE_FIELDS_INVALID")

    def _validate_analysis_result(
        self, result: Mapping[str, Any], case: CaseDefinition
    ) -> None:
        for field in ("overview", "chat_signals", "key_events"):
            if not isinstance(result.get(field), dict):
                raise ContractError(f"ANALYSIS_{field.upper()}_INVALID")
        overview = result["overview"]
        next_steps = overview.get("next_steps")
        if not isinstance(next_steps, list) or [
            item.get("type") if isinstance(item, dict) else None for item in next_steps
        ] != ["action", "communication", "observation"]:
            raise ContractError("ANALYSIS_NEXT_STEPS_INVALID")
        dashboard = overview.get("dashboard", {})
        if not isinstance(dashboard, dict):
            raise ContractError("ANALYSIS_DASHBOARD_INVALID")
        match_degree = dashboard.get("match_degree", {})
        if not isinstance(match_degree, dict):
            raise ContractError("ANALYSIS_MATCH_DEGREE_INVALID")
        if match_degree.get("status") == "unclear" and match_degree.get("score") is not None:
            raise ContractError("ANALYSIS_UNCLEAR_SCORE_MUST_BE_NULL")
        signals = result["chat_signals"]
        for field in ("positive", "watch", "risk"):
            items = signals.get(field)
            if not isinstance(items, list) or len(items) > 3:
                raise ContractError("ANALYSIS_SIGNAL_COUNT_INVALID")
        events = result["key_events"]
        total = 0
        for field in ("turning_points", "hidden_meanings", "did_well", "could_improve"):
            items = events.get(field)
            if not isinstance(items, list) or len(items) > 3:
                raise ContractError("ANALYSIS_EVENT_COUNT_INVALID")
            total += len(items)
        if total > 8:
            raise ContractError("ANALYSIS_EVENT_TOTAL_INVALID")
        codes = self._warning_codes(result)
        if not set(case.expect.warning_codes).issubset(codes):
            raise ContractError("EXPECTED_WARNING_MISSING")

    def get_diagnostics(
        self,
        task_id: str,
        case: CaseDefinition,
        context: RunContext,
    ) -> None:
        return None

    def delete_task(self, task_id: str, context: RunContext) -> CleanupResult:
        methods = PUBLIC_METHODS[context.task_kind]
        try:
            data = self._call_with_unknown_network_retry(
                ASSISTANT_SERVICE,
                "DeleteTaskData",
                {"task_id": task_id},
                f"{context.attempt_id}-delete",
            )
        except BusinessError as exc:
            if exc.code == "NOT_FOUND":
                return CleanupResult(True, "already_absent", {"task_id": task_id})
            raise
        if data.get("logical_deleted") is not True:
            raise ContractError("PUBLIC_DELETE_NOT_LOGICAL")
        for index, method in enumerate((methods.get_task, methods.get_result), 1):
            try:
                self._authenticated_call(
                    ASSISTANT_SERVICE,
                    method,
                    {"task_id": task_id},
                    f"{context.attempt_id}-delete-check-{index}",
                )
            except BusinessError as exc:
                if exc.code == "NOT_FOUND":
                    continue
                raise
            raise ContractError("PUBLIC_DELETE_ACCESS_STILL_AVAILABLE")
        return CleanupResult(True, "deleted", dict(data))
