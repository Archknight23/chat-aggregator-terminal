"""Server client — SSE streaming + HTTP API for the Node backend.

The server stays unchanged. We talk to:
  - /api/twitch/sse       — Twitch EventSub events (raids, rewards, status)
  - /api/youtube/sse      — YouTube live chat proxy
  - /api/viewers/*        — viewer count polling
  - /api/send/{platform}  — outbound chat messages
  - /api/twitch/raid       — initiate raid
  - /api/twitch/pkce/exchange — OAuth token exchange
  - /api/youtube/live-video-id — resolve channel to video ID
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class ServerClient:
    def __init__(self, base_url: str = "http://localhost:4174") -> None:
        self.base_url = base_url.rstrip("/")
        self._http: httpx.AsyncClient | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def stop(self) -> None:
        self._stop.set()
        if self._http:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if not self._http:
            raise RuntimeError("ServerClient not started")
        return self._http

    async def health(self) -> bool:
        try:
            r = await self.http.get("/api/health")
            return r.status_code == 200
        except Exception:
            return False

    async def resolve_youtube_id(self, target: str) -> str | None:
        try:
            r = await self.http.get("/api/youtube/live-video-id", params={"target": target})
            if r.status_code == 200:
                return r.json().get("videoId")
        except Exception as exc:
            logger.debug("youtube resolve failed: %s", exc)
        return None

    async def fetch_viewers(self, platform: str, channel: str) -> int | None:
        try:
            if platform not in {"twitch", "youtube", "kick"}:
                raise ValueError(f"Unsupported platform: {platform}")
            r = await self.http.get(f"/api/viewers/{platform}/{quote(channel, safe='')}")
            if r.status_code == 200:
                return r.json().get("viewers")
        except Exception:
            pass
        return None

    async def send_message(self, platform: str, text: str, channel: str = "") -> dict[str, Any]:
        try:
            r = await self.http.post(f"/api/send/{platform}", json={"text": text, "channel": channel})
            return r.json()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def initiate_raid(self, target_channel: str) -> dict[str, Any]:
        try:
            r = await self.http.post("/api/twitch/raid", json={"targetChannel": target_channel})
            return r.json()
        except Exception as exc:
            return {"error": str(exc)}

    async def twitch_status(self) -> dict[str, Any] | None:
        try:
            r = await self.http.get("/api/twitch/status")
            if r.status_code == 200:
                return r.json()
        except Exception as exc:
            logger.debug("twitch status failed: %s", exc)
        return None

    async def twitch_logout(self) -> dict[str, Any]:
        try:
            r = await self.http.post("/api/twitch/logout")
            return {"ok": r.status_code == 200}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def sse_stream(self, path: str) -> Any:
        """Async generator yielding SSE data payloads from the server."""
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with self.http.stream("GET", path) as r:
                    r.raise_for_status()
                    backoff = 1.0
                    buf = ""
                    async for chunk in r.aiter_text():
                        if self._stop.is_set():
                            break
                        buf += chunk
                        while "\n\n" in buf:
                            block, buf = buf.split("\n\n", 1)
                            for line in block.split("\n"):
                                if line.startswith("data: "):
                                    data_str = line[6:]
                                    try:
                                        yield json.loads(data_str)
                                    except json.JSONDecodeError:
                                        pass
                                    break
            except Exception as exc:
                logger.debug("SSE %s disconnected: %s", path, exc)
                yield {"_disconnected": True}
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
