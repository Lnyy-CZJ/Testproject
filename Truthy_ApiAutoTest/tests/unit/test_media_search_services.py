"""MediaService 与 SearchService 文档请求形状测试。"""

from collections.abc import Iterable
from typing import Any

import pytest

from framework.models.envelope import GatewayResponse
from services.media_service import MediaService
from services.search_service import SearchService


def _response(data: Any) -> GatewayResponse:
    """构造单业务响应。"""
    response = GatewayResponse.model_validate(
        {
            "code": 0,
            "message": "OK",
            "request_id": "request-offline",
            "trace_id": "trace-offline",
            "responses": [
                {
                    "id": "req_0",
                    "code": 0,
                    "success": True,
                    "business_error_code": "",
                    "data": data,
                }
            ],
        }
    )
    response.http_status = 200
    return response


class _Gateway:
    """记录 Service 委托参数的离线 Gateway。"""

    def __init__(self, responses: Iterable[GatewayResponse] = ()) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def invoke(
        self, service_name: str, method_name: str, params: dict[str, Any], **kwargs: Any
    ) -> GatewayResponse:
        self.calls.append(
            {
                "service_name": service_name,
                "method_name": method_name,
                "params": params,
                **kwargs,
            }
        )
        return next(self.responses, _response({}))


class _Cos:
    """记录媒体二进制上传。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put(self, url: str, *, upload_headers: dict[str, str], content: bytes) -> None:
        self.calls.append(
            {"url": url, "upload_headers": upload_headers, "content": content}
        )


def _valid_config() -> dict[str, Any]:
    """返回严格合法的媒体配置数据。"""
    return {"allowed_content_types": ["image/jpeg"], "max_size_bytes": 100}


def _valid_prepare() -> dict[str, Any]:
    """返回与单字节 JPEG 请求一致的 Prepare 数据。"""
    return {
        "media_asset_id": "media-1",
        "status": "pending",
        "content_type": "image/jpeg",
        "size_bytes": 1,
        "upload_url": "https://cos.example.test/file",
        "upload_method": "PUT",
        "upload_headers": {"Content-Type": "image/jpeg"},
        "max_size_bytes": 100,
    }


def _valid_complete() -> dict[str, Any]:
    """返回与 Prepare 一致的 Complete 数据。"""
    return {
        "media_asset_id": "media-1",
        "status": "uploaded",
        "content_type": "image/jpeg",
        "size_bytes": 1,
    }


def test_media_methods_use_exact_documented_request_shapes() -> None:
    gateway = _Gateway()
    service = MediaService(gateway)

    service.get_media_upload_config(access_token="access")
    service.prepare_media_upload(
        access_token="access",
        client_request_id="stable-media-id",
        content_type="image/jpeg",
        size_bytes=17,
    )
    service.complete_media_upload(access_token="access", media_asset_id="media-1")

    assert [(c["service_name"], c["method_name"], c["params"]) for c in gateway.calls] == [
        ("tool.people_insight.MediaService", "GetMediaUploadConfig", {}),
        (
            "tool.people_insight.MediaService",
            "PrepareMediaUpload",
            {
                "client_request_id": "stable-media-id",
                "content_type": "image/jpeg",
                "size_bytes": 17,
            },
        ),
        (
            "tool.people_insight.MediaService",
            "CompleteMediaUpload",
            {"media_asset_id": "media-1"},
        ),
    ]
    assert gateway.calls[1]["client_request_id"] == "stable-media-id"
    assert all(call["auth_token"] == "access" for call in gateway.calls)


def test_upload_media_runs_config_prepare_put_complete_and_validates_result() -> None:
    content = b"jpeg-content"
    gateway = _Gateway(
        [
            _response(
                {"allowed_content_types": ["image/jpeg"], "max_size_bytes": 100}
            ),
            _response(
                {
                    "media_asset_id": "media-1",
                    "status": "pending",
                    "content_type": "image/jpeg",
                    "size_bytes": len(content),
                    "upload_url": "https://cos.example.test/file?signature=secret",
                    "upload_method": "PUT",
                    "upload_headers": {"Content-Type": "image/jpeg"},
                    "max_size_bytes": 100,
                }
            ),
            _response(
                {
                    "media_asset_id": "media-1",
                    "status": "uploaded",
                    "content_type": "image/jpeg",
                    "size_bytes": len(content),
                }
            ),
        ]
    )
    cos = _Cos()

    result = MediaService(gateway, cos_client=cos).upload_media(
        access_token="access",
        client_request_id="stable-media-id",
        content_type="image/jpeg",
        content=content,
    )

    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
        "CompleteMediaUpload",
    ]
    assert cos.calls == [
        {
            "url": "https://cos.example.test/file?signature=secret",
            "upload_headers": {"Content-Type": "image/jpeg"},
            "content": content,
        }
    ]
    assert result.responses[0].data["media_asset_id"] == "media-1"


@pytest.mark.parametrize(
    "config,prepare,complete,error",
    [
        (
            {"allowed_content_types": ["image/png"], "max_size_bytes": 100},
            {},
            {},
            "content_type",
        ),
        (
            {"allowed_content_types": ["image/jpeg"], "max_size_bytes": 0},
            {},
            {},
            "size",
        ),
        (
            {"allowed_content_types": ["image/jpeg"], "max_size_bytes": 100},
            {
                "media_asset_id": "media-1",
                "status": "wrong",
                "content_type": "image/jpeg",
                "size_bytes": 1,
                "upload_url": "https://cos.example.test/file",
                "upload_method": "PUT",
                "upload_headers": {},
                "max_size_bytes": 100,
            },
            {},
            "status",
        ),
        (
            {"allowed_content_types": ["image/jpeg"], "max_size_bytes": 100},
            {
                "media_asset_id": "media-1",
                "status": "pending",
                "content_type": "image/jpeg",
                "size_bytes": 1,
                "upload_url": "https://cos.example.test/file",
                "upload_method": "PUT",
                "upload_headers": {},
                "max_size_bytes": 100,
            },
            {
                "media_asset_id": "different",
                "status": "uploaded",
                "content_type": "image/jpeg",
                "size_bytes": 1,
            },
            "media_asset_id",
        ),
    ],
)
def test_upload_media_rejects_invalid_config_or_server_echo(
    config: dict[str, Any],
    prepare: dict[str, Any],
    complete: dict[str, Any],
    error: str,
) -> None:
    gateway = _Gateway([_response(config), _response(prepare), _response(complete)])

    with pytest.raises(ValueError, match=error):
        MediaService(gateway, cos_client=_Cos()).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("allowed_content_types", "image/jpeg"),
        ("allowed_content_types", [1]),
        ("max_size_bytes", True),
        ("max_size_bytes", 0),
        ("max_size_bytes", 1.5),
        ("max_size_bytes", "100"),
    ],
)
def test_upload_media_rejects_invalid_config_types_before_prepare(
    field: str, value: Any
) -> None:
    config = _valid_config()
    config[field] = value
    gateway = _Gateway([_response(config)])
    cos = _Cos()

    with pytest.raises(ValueError, match=field):
        MediaService(gateway, cos_client=cos).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )

    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig"
    ]
    assert cos.calls == []


@pytest.mark.parametrize("invalid_data", [None, [], "object", True])
def test_upload_media_rejects_non_object_config_data(invalid_data: Any) -> None:
    with pytest.raises(ValueError, match="Config data"):
        MediaService(_Gateway([_response(invalid_data)]), cos_client=_Cos()).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("media_asset_id", ""),
        ("media_asset_id", 1),
        ("status", ""),
        ("status", 1),
        ("status", "uploaded"),
        ("content_type", ""),
        ("content_type", 1),
        ("content_type", "image/png"),
        ("size_bytes", True),
        ("size_bytes", 0),
        ("size_bytes", 1.0),
        ("size_bytes", 2),
        ("upload_url", ""),
        ("upload_url", 1),
        ("upload_method", ""),
        ("upload_method", 1),
        ("upload_method", "POST"),
        ("upload_headers", []),
        ("upload_headers", {1: "value"}),
        ("upload_headers", {"header": 1}),
        ("max_size_bytes", True),
        ("max_size_bytes", 0),
        ("max_size_bytes", 1.0),
    ],
)
def test_prepare_invalid_field_never_reaches_cos_or_complete(
    field: str, value: Any
) -> None:
    prepare = _valid_prepare()
    prepare[field] = value
    gateway = _Gateway([_response(_valid_config()), _response(prepare)])
    cos = _Cos()

    with pytest.raises(ValueError, match=field):
        MediaService(gateway, cos_client=cos).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )

    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
    ]
    assert cos.calls == []


@pytest.mark.parametrize("invalid_data", [None, [], "object", True])
def test_prepare_non_object_data_never_reaches_cos(invalid_data: Any) -> None:
    gateway = _Gateway([_response(_valid_config()), _response(invalid_data)])
    cos = _Cos()

    with pytest.raises(ValueError, match="Prepare data"):
        MediaService(gateway, cos_client=cos).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )

    assert cos.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("media_asset_id", ""),
        ("media_asset_id", 1),
        ("media_asset_id", "different"),
        ("status", ""),
        ("status", 1),
        ("status", "pending"),
        ("content_type", ""),
        ("content_type", 1),
        ("content_type", "image/png"),
        ("size_bytes", True),
        ("size_bytes", 0),
        ("size_bytes", 1.0),
        ("size_bytes", 2),
    ],
)
def test_complete_data_is_strictly_typed_and_matches_prepare(
    field: str, value: Any
) -> None:
    complete = _valid_complete()
    complete[field] = value
    gateway = _Gateway(
        [
            _response(_valid_config()),
            _response(_valid_prepare()),
            _response(complete),
        ]
    )

    with pytest.raises(ValueError, match=field):
        MediaService(gateway, cos_client=_Cos()).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )


@pytest.mark.parametrize("invalid_data", [None, [], "object", True])
def test_complete_rejects_non_object_data(invalid_data: Any) -> None:
    gateway = _Gateway(
        [
            _response(_valid_config()),
            _response(_valid_prepare()),
            _response(invalid_data),
        ]
    )

    with pytest.raises(ValueError, match="Complete data"):
        MediaService(gateway, cos_client=_Cos()).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )


def test_cos_failure_never_calls_complete() -> None:
    class _FailingCos(_Cos):
        """模拟上传失败且不泄露内容。"""

        def put(
            self, url: str, *, upload_headers: dict[str, str], content: bytes
        ) -> None:
            raise RuntimeError("offline COS failure")

    gateway = _Gateway([_response(_valid_config()), _response(_valid_prepare())])

    with pytest.raises(RuntimeError, match="COS failure"):
        MediaService(gateway, cos_client=_FailingCos()).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"x",
        )

    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig",
        "PrepareMediaUpload",
    ]


def test_empty_media_content_is_rejected_before_prepare() -> None:
    gateway = _Gateway([_response(_valid_config())])

    with pytest.raises(ValueError, match="size_bytes"):
        MediaService(gateway, cos_client=_Cos()).upload_media(
            access_token="access",
            client_request_id="stable",
            content_type="image/jpeg",
            content=b"",
        )

    assert [call["method_name"] for call in gateway.calls] == [
        "GetMediaUploadConfig"
    ]


def test_search_methods_preserve_clues_and_exact_documented_params() -> None:
    gateway = _Gateway()
    service = SearchService(gateway)
    clues = [
        {"type": "FULL_NAME", "full_name_query": {"full_name": "Ada Lovelace"}},
        {"type": "PHOTO", "photo_query": {"media_asset_id": "media-1"}},
    ]
    details = [{"type": "PROFESSION", "value": "Mathematician"}]

    service.create_intent_task(
        access_token="access",
        client_request_id="stable-task-id",
        match_strategy="UNION",
        clues=clues,
        additional_details=details,
    )
    service.create_intent(
        access_token="access",
        client_request_id="stable-intent-id",
        match_strategy="UNION",
        clues=clues,
    )
    service.start_task(access_token="access", task_id="task-1")
    service.get_task(access_token="access", task_id="task-1")
    service.list_task_candidates(
        access_token="access", task_id="task-1", page_size=10, page_token="next"
    )
    service.get_task_candidate_detail(
        access_token="access", task_id="task-1", candidate_id="candidate-1"
    )
    service.list_search_history(
        access_token="access",
        page_size=20,
        page_token="history-next",
        status_filter=["SUCCEEDED"],
    )

    assert gateway.calls[0]["params"] == {
        "client_request_id": "stable-task-id",
        "match_strategy": "UNION",
        "clues": clues,
        "additional_details": details,
    }
    assert gateway.calls[0]["client_request_id"] == "stable-task-id"
    assert gateway.calls[1]["params"] == {
        "client_request_id": "stable-intent-id",
        "match_strategy": "UNION",
        "clues": clues,
    }
    assert gateway.calls[1]["client_request_id"] == "stable-intent-id"
    assert [(c["method_name"], c["params"]) for c in gateway.calls[2:]] == [
        ("StartTask", {"task_id": "task-1"}),
        ("GetTask", {"task_id": "task-1"}),
        (
            "ListTaskCandidates",
            {"task_id": "task-1", "page": {"page_size": 10, "page_token": "next"}},
        ),
        (
            "GetTaskCandidateDetail",
            {"task_id": "task-1", "candidate_id": "candidate-1"},
        ),
        (
            "ListSearchHistory",
            {
                "page": {"page_size": 20, "page_token": "history-next"},
                "status_filter": ["SUCCEEDED"],
            },
        ),
    ]
    assert clues[1]["photo_query"] == {"media_asset_id": "media-1"}


def test_get_task_forwards_optional_read_timeout() -> None:
    """任务等待器传入剩余预算时，SearchService 必须继续传到 GatewayClient。"""
    gateway = _Gateway()

    SearchService(gateway).get_task(
        access_token="access",
        task_id="task-1",
        read_timeout=4.5,
    )

    assert gateway.calls == [
        {
            "service_name": "tool.people_insight.SearchService",
            "method_name": "GetTask",
            "params": {"task_id": "task-1"},
            "auth_token": "access",
            "read_timeout": 4.5,
        }
    ]


@pytest.mark.parametrize(
    "clues,match_strategy",
    [
        ([], "UNION"),
        ([{"type": "FULL_NAME"}, {"type": "FULL_NAME"}], "UNION"),
        ([{"type": "LOCATION"}, {"type": "LOCATION"}], "UNION"),
        ([{"type": "FULL_NAME"}], "INTERSECTION"),
    ],
)
def test_search_service_does_not_block_negative_api_inputs(
    clues: list[dict[str, Any]], match_strategy: str
) -> None:
    gateway = _Gateway()

    SearchService(gateway).create_intent_task(
        access_token="access",
        client_request_id="negative-stable-id",
        match_strategy=match_strategy,
        clues=clues,
    )

    assert gateway.calls[0]["params"]["clues"] is clues
    assert gateway.calls[0]["params"]["match_strategy"] == match_strategy
