"""
SSE 实时事件 API

功能说明:
    提供 Go 版兼容的 `/api/v1/sse?token=...&rooms=...` 连接入口。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import security
from app.infrastructure.database import async_session_factory
from app.infrastructure.sse import format_sse_event, sse_broker
from app.models.user import User

router = APIRouter(tags=["sse"])


async def _get_user_from_query_token(db: AsyncSession, token: str) -> User:
    """
    通过 query token 解析 SSE 用户。

    异常说明:
        HTTPException(401): token 缺失、失效或用户不存在。
    """
    payload = security.decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    user = await db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期")
    return user


@router.get("/sse", response_class=StreamingResponse)
async def connect_sse(
    token: str = Query(...),
    rooms: str = Query(default=""),
) -> StreamingResponse:
    """
    建立 SSE 连接。

    参数说明:
        token: JWT token，EventSource 无法稳定设置 Authorization 时使用 query。
        rooms: 逗号分隔房间列表，例如 defect:1,project:5。
    """
    async with async_session_factory() as db:
        await _get_user_from_query_token(db, token)

    room_list = [room.strip() for room in rooms.split(",") if room.strip()]
    queue = await sse_broker.subscribe(room_list)

    async def event_stream():
        """持续输出 SSE 事件，并定期发送心跳"""
        try:
            yield format_sse_event("connected", {"rooms": room_list})
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                    yield format_sse_event(item.event, item.data)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            await sse_broker.unsubscribe(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
