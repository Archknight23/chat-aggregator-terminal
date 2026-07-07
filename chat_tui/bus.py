"""Async message bus — decouples platform clients from the UI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


MSG_CHAT = "chat"
MSG_ALERT = "alert"
MSG_VIEWER_COUNT = "viewer_count"
MSG_STATUS = "status"
MSG_SEND_STATUS = "send_status"


@dataclass
class BusMessage:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class MessageBus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[BusMessage] = asyncio.Queue()

    async def put(self, kind: str, payload: dict[str, Any]) -> None:
        await self._queue.put(BusMessage(kind, payload))

    async def get(self) -> BusMessage:
        return await self._queue.get()

    def put_nowait(self, kind: str, payload: dict[str, Any]) -> None:
        self._queue.put_nowait(BusMessage(kind, payload))