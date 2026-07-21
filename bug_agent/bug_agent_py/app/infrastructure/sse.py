"""
SSE 事件格式化基础设施

功能说明:
    第零阶段先冻结 Go 版兼容的 SSE 文本格式，后续 Redis Pub/Sub
    Broker 和 FastAPI 端点可以复用这里的格式化函数。

设计约束:
    - event 名保持 Go 版约定，例如 defect:status_changed
    - data 必须是 JSON 对象并使用 camelCase 字段
    - 输出必须符合 text/event-stream 协议的空行结尾要求
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def format_sse_event(event: str, data: Mapping[str, Any]) -> str:
    """
    格式化单条 SSE 事件。

    功能说明:
        将事件名和 JSON 数据转换为前端 EventSource/fetch 流可消费的
        `event: ...` + `data: ...` 文本格式。

    参数说明:
        event (str): SSE 事件名，必须是非空字符串。
        data (Mapping[str, Any]): 事件数据，必须可被 JSON 序列化。

    返回值:
        str: 符合 SSE 协议的事件文本，末尾包含两个换行符。

    异常说明:
        ValueError: event 为空时抛出，避免产生无法路由的事件。
        TypeError: data 中存在不可 JSON 序列化对象时由 json.dumps 抛出。
    """
    if not event.strip():
        raise ValueError("SSE 事件名不能为空")

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def status_changed_event(
    defect_id: int,
    from_status: str,
    to_status: str,
    operator_id: int | None = None,
) -> str:
    """
    构造缺陷状态变更事件。

    功能说明:
        固化 `defect:status_changed` 的 data 字段，作为第零阶段
        golden event 测试样例，后续 WorkflowService 触发 SSE 时复用。

    参数说明:
        defect_id (int): 缺陷 ID。
        from_status (str): 流转前状态。
        to_status (str): 流转后状态。
        operator_id (int | None): 操作人 ID，系统自动流转时可为空。

    返回值:
        str: 格式化后的 SSE 事件文本。
    """
    return format_sse_event(
        "defect:status_changed",
        {
            "defectId": defect_id,
            "fromStatus": from_status,
            "toStatus": to_status,
            "operatorId": operator_id,
        },
    )


@dataclass(frozen=True)
class SSEEvent:
    """
    SSE 事件对象。

    参数说明:
        event: 事件名，例如 analysis:progress。
        data: camelCase 事件载荷。
        room: 事件所属房间，例如 defect:1。
    """

    event: str
    data: Mapping[str, Any]
    room: str


class InMemorySSEBroker:
    """
    进程内 SSE Broker。

    设计说明:
        第三阶段先提供单进程可用的发布/订阅能力。生产多实例部署时可将本类
        替换为 Redis Pub/Sub 实现，API 和服务调用点保持不变。
    """

    def __init__(self, history_limit: int = 100):
        self._subscribers: dict[str, set[asyncio.Queue[SSEEvent]]] = defaultdict(set)
        self._history: deque[SSEEvent] = deque(maxlen=history_limit)
        self._lock = asyncio.Lock()

    async def publish(self, room: str, event: str, data: Mapping[str, Any]) -> None:
        """
        发布事件到房间。

        参数说明:
            room: 订阅房间名。
            event: SSE 事件名。
            data: 事件数据。
        """
        item = SSEEvent(event=event, data=data, room=room)
        async with self._lock:
            self._history.append(item)
            subscribers = list(self._subscribers.get(room, set()))
            subscribers.extend(self._subscribers.get("*", set()))
        for queue in subscribers:
            queue.put_nowait(item)

    async def subscribe(self, rooms: list[str]) -> asyncio.Queue[SSEEvent]:
        """
        订阅一个或多个房间。

        返回值:
            asyncio.Queue[SSEEvent]: 当前连接专属事件队列。
        """
        queue: asyncio.Queue[SSEEvent] = asyncio.Queue()
        target_rooms = rooms or ["*"]
        async with self._lock:
            for room in target_rooms:
                self._subscribers[room].add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[SSEEvent]) -> None:
        """
        取消订阅。

        参数说明:
            queue: subscribe 返回的队列。
        """
        async with self._lock:
            for subscribers in self._subscribers.values():
                subscribers.discard(queue)

    def recent_events(self, room: str | None = None) -> list[SSEEvent]:
        """
        查询近期事件，作为 SSE 断线重连前的轻量补偿。

        返回值:
            list[SSEEvent]: 按发布时间排序的近期事件。
        """
        if room is None:
            return list(self._history)
        return [event for event in self._history if event.room == room]


sse_broker = InMemorySSEBroker()
