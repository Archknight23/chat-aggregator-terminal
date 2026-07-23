"""Read-only client for the NexusChaos channel-chats public feed.

Consumes:
  GET {base}/api/chat/recent
  GET {base}/api/chat/stream  (SSE)
  GET {base}/api/chat/status  (optional connector map)

Maps the VPS message shape {id, platform, author, text, ts, badges}
onto the TUI chat shape {id, platform, username, text, timestamp}.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

OnMessage = Callable[[dict[str, Any]], None]
OnStatus = Callable[[str, str], None]  # platform, state


def _to_tui_message(row: dict[str, Any]) -> dict[str, Any] | None:
    text = str(row.get("text") or "").strip()
    if not text:
        return None
    author = str(row.get("author") or row.get("username") or "—")
    platform = str(row.get("platform") or "system").lower()
    ts = row.get("ts") if row.get("ts") is not None else row.get("timestamp")
    try:
        ts_ms = int(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts_ms = None
    return {
        "id": str(row["id"]) if row.get("id") is not None else None,
        "username": author,
        "text": text,
        "platform": platform,
        "timestamp": ts_ms,
        "badges": row.get("badges") or [],
        "source": "remote",
    }


class RemoteChatFeed:
    """Long-lived SSE consumer with recent backfill."""

    def __init__(
        self,
        base_url: str,
        on_message: OnMessage,
        on_status: OnStatus | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.on_message = on_message
        self.on_status = on_status or (lambda _p, _s: None)
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

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

    async def fetch_status(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as http:
                r = await http.get(f"{self.base_url}/api/chat/status")
                if r.status_code == 200:
                    return r.json()
                # Fallback for older deploys that only expose /health internally
                r2 = await http.get(f"{self.base_url}/api/chat/recent", params={"limit": 1})
                if r2.status_code == 200:
                    return {"status": "ok", "connectors": {}, "reachable": True}
        except Exception as exc:
            logger.debug("remote status failed: %s", exc)
        return None

    async def _run(self) -> None:
        backoff = 1.0
        self.on_status("remote", "connecting")
        while not self._stop.is_set():
            try:
                async with httpx.AsyncClient(timeout=None) as http:
                    await self._backfill(http)
                    self.on_status("remote", "live")
                    backoff = 1.0
                    async with http.stream("GET", f"{self.base_url}/api/chat/stream") as r:
                        r.raise_for_status()
                        buf = ""
                        async for chunk in r.aiter_text():
                            if self._stop.is_set():
                                return
                            buf += chunk
                            while "\n\n" in buf:
                                block, buf = buf.split("\n\n", 1)
                                for line in block.split("\n"):
                                    if line.startswith("data: "):
                                        try:
                                            payload = json.loads(line[6:])
                                        except json.JSONDecodeError:
                                            break
                                        msg = _to_tui_message(payload)
                                        if msg:
                                            self.on_message(msg)
                                        break
                self.on_status("remote", "reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("remote feed disconnected: %s", exc)
                self.on_status("remote", "reconnecting")
            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _backfill(self, http: httpx.AsyncClient) -> None:
        try:
            r = await http.get(f"{self.base_url}/api/chat/recent", params={"limit": 100}, timeout=10.0)
            if r.status_code != 200:
                return
            rows = r.json()
            if not isinstance(rows, list):
                return
            for row in rows:
                if isinstance(row, dict):
                    msg = _to_tui_message(row)
                    if msg:
                        self.on_message(msg)
        except Exception as exc:
            logger.debug("remote backfill failed: %s", exc)
