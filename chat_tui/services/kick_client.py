"""Kick chat polling client — reads public livestream chat.

Kick's unofficial `/api/v2/channels/{slug}/messages` endpoint currently
returns HTTP 500 for many channels. We still try the public path, surface
degraded/error state honestly, and prefer the VPS webhook feed when present.
"""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

KICK_API = "https://kick.com/api/v2/channels"
OnMessage = Callable[[dict[str, Any]], Any]
OnStatus = Callable[..., None]


class KickClient:
    """Poll Kick livestream chat messages from public API + chat endpoint."""

    def __init__(
        self,
        channel: str,
        on_message: OnMessage,
        on_status: OnStatus | None = None,
    ) -> None:
        self.channel = channel.lstrip("#")
        self.on_message = on_message
        self.on_status = on_status or (lambda *_a, **_k: None)
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._chatroom_id: int | None = None
        self._last_message_ids: set[str] = set()
        self._message_id_order: deque[str] = deque(maxlen=500)
        self._consecutive_failures = 0

    async def start(self) -> None:
        self._stop.clear()
        self.on_status("connecting")
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
        headers = {
            "User-Agent": "chat-aggregator-tui/0.1",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as http:
            while not self._stop.is_set():
                try:
                    await self._resolve_chatroom(http)
                    if self._chatroom_id:
                        ok = await self._poll_messages(http)
                        if ok:
                            self._consecutive_failures = 0
                            self.on_status("live")
                            backoff = 2.0
                        else:
                            self._consecutive_failures += 1
                            if self._consecutive_failures >= 3:
                                self.on_status(
                                    "degraded",
                                    "Kick messages API returning errors — use VPS feed or official webhooks",
                                )
                            await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                            backoff = min(backoff * 2, 30.0)
                            continue
                except Exception as exc:
                    logger.debug("Kick client error: %s", exc)
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 3:
                        self.on_status("degraded", str(exc)[:120])
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

    async def _poll_messages(self, http: httpx.AsyncClient) -> bool:
        # Primary (legacy public) endpoint — currently hard-500s for many channels.
        url = f"https://kick.com/api/v2/channels/{self.channel}/messages"
        r = await http.get(url)
        if r.status_code >= 500:
            logger.debug("Kick messages HTTP %s for %s", r.status_code, self.channel)
            return False
        if r.status_code == 404:
            # Alternate path used by some Kick frontends
            alt = f"https://kick.com/api/v2/channels/{self._chatroom_id}/messages"
            r = await http.get(alt)
            if r.status_code >= 400:
                return False
        r.raise_for_status()
        data = r.json()
        messages = data.get("data", []) if isinstance(data, dict) else data
        if not isinstance(messages, list):
            return False
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
            sender = msg.get("sender") or {}
            result = self.on_message({
                "username": sender.get("username", "—"),
                "text": msg.get("content", ""),
                "platform": "kick",
                "timestamp": msg.get("created_at") or msg.get("createdAt"),
                "id": msg_id,
            })
            if asyncio.iscoroutine(result):
                await result
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=2.0)
            return True
        except asyncio.TimeoutError:
            return True
