"""Kick chat polling client — reads public livestream chat."""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

KICK_API = "https://kick.com/api/v2/channels"


class KickClient:
    """Poll Kick livestream chat messages from public API + chat endpoint."""

    def __init__(self, channel: str, on_message: Any) -> None:
        self.channel = channel.lstrip("#")
        self.on_message = on_message
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._chatroom_id: int | None = None
        self._last_message_ids: set[str] = set()
        self._message_id_order: deque[str] = deque(maxlen=500)

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        backoff = 2.0
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "chat-aggregator-tui/0.1"}) as http:
            while not self._stop.is_set():
                try:
                    await self._resolve_chatroom(http)
                    if self._chatroom_id:
                        await self._poll_messages(http)
                    backoff = 2.0
                except Exception as exc:
                    logger.debug("Kick client error: %s", exc)
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                        return
                    except asyncio.TimeoutError:
                        backoff = min(backoff * 2, 30.0)

    async def _resolve_chatroom(self, http: httpx.AsyncClient) -> None:
        if self._chatroom_id is not None:
            return
        r = await http.get(f"{KICK_API}/{self.channel}")
        r.raise_for_status()
        data = r.json()
        self._chatroom_id = data.get("chatroom", {}).get("id")
        if not self._chatroom_id:
            raise RuntimeError("Kick channel has no chatroom")

    async def _poll_messages(self, http: httpx.AsyncClient) -> None:
        url = f"https://kick.com/api/v2/channels/{self.channel}/messages"
        r = await http.get(url)
        r.raise_for_status()
        data = r.json()
        messages = data.get("data", []) if isinstance(data, dict) else data
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            raw_id = msg.get("id")
            if raw_id is None:
                continue
            msg_id = str(raw_id)
            if msg_id in self._last_message_ids:
                continue
            if len(self._message_id_order) == self._message_id_order.maxlen:
                self._last_message_ids.discard(self._message_id_order[0])
            self._message_id_order.append(msg_id)
            self._last_message_ids.add(msg_id)
            await self.on_message({
                "username": msg.get("sender", {}).get("username", "—"),
                "text": msg.get("content", ""),
                "platform": "kick",
                "timestamp": msg.get("created_at") or msg.get("createdAt"),
                "id": msg_id,
            })
        # short poll interval for chat feel
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
