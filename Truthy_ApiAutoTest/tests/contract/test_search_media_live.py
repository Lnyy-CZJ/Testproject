"""阶段3显式授权后才可运行的搜索与媒体真实合同。"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from framework.assertions.gateway_assert import assert_business_success, assert_gateway_received
from framework.client.cos_client import CosClient
from framework.waiters.task_waiter import TaskWaiter
from services.media_service import MediaService
from services.search_service import SearchService
from services.subscription_service import SubscriptionService


_MAX_LOCAL_MEDIA_BYTES = 10 * 1024 * 1024


def _read_test_media(media_path: Path) -> bytes:
    """从稳定文件句柄读取不超过 10MB 的调用方授权媒体。

    参数说明:
        media_path: 已由真实合同确认存在的测试媒体路径。
    返回值:
        同一文件句柄在 ``fstat`` 后读取的二进制内容。
    异常说明:
        文件大于 10MB 或读取期间增长超过上限时明确 skip；打开、stat 和读取异常
        保持测试失败，不用空内容掩盖环境问题。
    """
    with media_path.open("rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        if file_size > _MAX_LOCAL_MEDIA_BYTES:
            pytest.skip("TEST_MEDIA_PATH 超过本地读取上限 10MB")
        content = stream.read(_MAX_LOCAL_MEDIA_BYTES + 1)
    if len(content) > _MAX_LOCAL_MEDIA_BYTES:
        pytest.skip("TEST_MEDIA_PATH 读取期间增长并超过 10MB")
    return content


@pytest.mark.contract
@pytest.mark.media
def test_live_media_reader_reads_small_file_from_stable_handle(tmp_path) -> None:
    media_path = tmp_path / "authorized.bin"
    media_path.write_bytes(b"authorized-test-bytes")

    assert _read_test_media(media_path) == b"authorized-test-bytes"


@pytest.mark.contract
@pytest.mark.media
def test_live_media_reader_skips_file_larger_than_ten_megabytes(tmp_path) -> None:
    media_path = tmp_path / "too-large.bin"
    with media_path.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)

    with pytest.raises(pytest.skip.Exception, match="10MB"):
        _read_test_media(media_path)


@pytest.mark.contract
@pytest.mark.live_safe
@pytest.mark.search
@pytest.mark.async_task
@pytest.mark.requires_entitlement
def test_live_safe_public_demo_search(settings, gateway_client) -> None:
    """仅用公开历史人物演示线索创建可追溯任务；缺账号或权益时明确跳过。"""
    if not settings.auth_token:
        pytest.skip("真实搜索合同缺少 TRUTHY_AUTH_TOKEN")
    entitlement_response = SubscriptionService(gateway_client).get_entitlement(
        access_token=settings.auth_token, product_code="people_insight"
    )
    assert_gateway_received(entitlement_response)
    entitlement_item = entitlement_response.responses[0]
    if not entitlement_item.success or entitlement_item.code != 0:
        pytest.skip(
            "真实搜索账号无有效身份/权益: "
            f"{entitlement_item.business_error_code or entitlement_item.code}"
        )
    entitlement = entitlement_item.data
    if not isinstance(entitlement, dict):
        pytest.skip("真实搜索账号权益响应缺少有效 data")
    if not entitlement["can_start_search"] or entitlement["decision"] != "ALLOW":
        pytest.skip("真实搜索账号缺少有效搜索权益")

    service = SearchService(gateway_client)
    client_request_id = f"autotest-live-safe-ada-{uuid4().hex[:12]}"
    created = assert_business_success(
        service.create_intent_task(
            access_token=settings.auth_token,
            client_request_id=client_request_id,
            match_strategy="UNION",
            clues=[
                {
                    "type": "FULL_NAME",
                    "full_name_query": {"full_name": "Ada Lovelace"},
                }
            ],
        ),
        required_data_fields={"task_id", "status"},
    )
    terminal = TaskWaiter(service).wait(
        access_token=settings.auth_token, task_id=created["task_id"]
    )

    assert terminal.status in {"SUCCEEDED", "NO_RESULT", "FAILED"}


@pytest.mark.contract
@pytest.mark.live_safe
@pytest.mark.live_write
@pytest.mark.destructive
@pytest.mark.media
def test_live_media_upload_requires_explicit_path_and_dangerous_authorization(
    settings, gateway_client
) -> None:
    """上传调用方提供的授权图片；不生成图片且缺路径或 token 时明确跳过。"""
    media_path_value = os.environ.get("TEST_MEDIA_PATH")
    if not media_path_value:
        pytest.skip("真实媒体合同未提供 TEST_MEDIA_PATH")
    if not settings.auth_token:
        pytest.skip("真实媒体合同缺少 TRUTHY_AUTH_TOKEN")
    media_path = Path(media_path_value)
    if not media_path.is_file():
        pytest.skip(f"TEST_MEDIA_PATH 不是可读取文件: {media_path}")
    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    content_type = content_types.get(media_path.suffix.lower())
    if content_type is None:
        pytest.skip("TEST_MEDIA_PATH 扩展名不是 jpg/jpeg/png/webp")

    content = _read_test_media(media_path)
    with CosClient(
        connect_timeout=settings.connect_timeout,
        read_timeout=settings.read_timeout,
    ) as cos_client:
        result = MediaService(
            gateway_client,
            cos_client=cos_client,
        ).upload_media(
            access_token=settings.auth_token,
            client_request_id=f"autotest-live-media-{uuid4().hex[:12]}",
            content_type=content_type,
            content=content,
        )

    uploaded = assert_business_success(result)
    assert uploaded["status"] == "uploaded"
    assert uploaded["media_asset_id"]
