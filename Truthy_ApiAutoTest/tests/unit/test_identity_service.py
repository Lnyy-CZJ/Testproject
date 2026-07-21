"""IdentityService 请求形状与会话鉴权单元测试。"""

from typing import Any

from services.identity_service import IdentityService


class _RecordingClient:
    """记录 invoke 调用并返回固定哨兵。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def invoke(self, *args: Any, **kwargs: Any) -> object:
        self.calls.append((args, kwargs))
        return object()


def test_create_anonymous_session_is_explicitly_anonymous() -> None:
    client = _RecordingClient()
    service = IdentityService(client)

    response = service.create_anonymous_session(
        consent_policy_version="2026-06-01",
        client_request_id="crid-anonymous-stable",
    )

    assert response is not None
    assert client.calls == [
        (
            (
                "tool.identity.IdentityService",
                "CreateAnonymousSession",
                {"consent_policy_version": "2026-06-01"},
            ),
            {
                "auth_token": None,
                "client_request_id": "crid-anonymous-stable",
            },
        )
    ]


def test_refresh_session_is_explicitly_anonymous() -> None:
    client = _RecordingClient()
    service = IdentityService(client)

    service.refresh_session(refresh_token="refresh-next")

    assert client.calls == [
        (
            (
                "tool.identity.IdentityService",
                "RefreshSession",
                {"refresh_token": "refresh-next"},
            ),
            {"auth_token": None},
        )
    ]


def test_get_me_passes_latest_access_token() -> None:
    client = _RecordingClient()
    service = IdentityService(client)

    service.get_me(access_token="access-latest")

    assert client.calls == [
        (
            ("tool.identity.IdentityService", "GetMe", {}),
            {"auth_token": "access-latest"},
        )
    ]
